"""RequestBoundsMiddleware — issues/044 gaps 1 and 4.

Nothing bounded a REQUEST. The fences that exist are per-STATEMENT (asyncpg's
command_timeout, the read path's statement_timeout), and one KGQuery request
runs several, so a request could take an arbitrary multiple of any single fence.
And uvicorn never cancels the ASGI task when a client hangs up, so a handler
whose client left ran to completion holding a pool slot and a database backend.

The policy under test is deliberately narrow: cancel READS only. A write may
have been intended by a client that then hit a network hiccup, and PostgreSQL
would roll it back on cancel — silent data loss the client cannot detect,
because it is by definition no longer listening.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from starlette.testclient import TestClient

from vitalgraph.api.request_bounds import (
    RequestBoundsMiddleware, is_cancellable_read,
)


class TestPolicy:
    """Which requests may be abandoned. One readable predicate, so test it."""

    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "get"])
    def test_safe_methods_are_cancellable(self, method):
        assert is_cancellable_read(method, "/anything") is True

    @pytest.mark.parametrize("path", [
        "/api/kgqueries",
        "/api/kgentities/query",
        "/api/kgrelations/query",
        "/api/kgframes/query",
        "/api/sparql/query",
    ])
    def test_read_shaped_posts_are_cancellable(self, path):
        assert is_cancellable_read("POST", path) is True

    @pytest.mark.parametrize("path", [
        "/api/graphs/kgqueries",
        "/api/graphs/kgentities/query",
        "/api/graphs/kgrelations/query",
        "/api/graphs/kgframes/query",
        "/api/graphs/sparql/query",
    ])
    def test_real_registered_paths_are_matched(self, path):
        """The paths ABOVE are shorthand; these are what the server registers.

        Read off the running server's openapi.json, because the prefix is
        `/api/graphs/` and not the `/api/` these tests had assumed — a
        difference the shorthand cases cannot catch, since `.search()` matches
        either way. An earlier version of this allowlist already shipped one
        wrong pattern (`kgqueries?` matching "kgquerie" + optional "s"), so the
        patterns get checked against reality, not against their own shorthand.
        """
        assert is_cancellable_read("POST", path) is True

    @pytest.mark.parametrize("path", [
        "/api/graphs/sparql/update",
        "/api/graphs/sparql/insert",
        "/api/graphs/sparql/insert-data",
        "/api/graphs/sparql/delete",
    ])
    def test_sparql_write_siblings_are_not_swept_in(self, path):
        """`/sparql/query` sits beside four writes under the same prefix.

        Anchoring on "sparql" instead of "query" would cancel updates — the one
        thing the reads-only policy exists to prevent.
        """
        assert is_cancellable_read("POST", path) is False

    @pytest.mark.parametrize("method,path", [
        ("POST", "/api/spaces"),
        ("POST", "/api/kgentities"),          # create, not query
        ("POST", "/api/kgframes"),            # create, not query
        ("POST", "/api/sparql/update"),
        ("POST", "/api/files/upload"),          # buffering a file would OOM
        ("POST", "/api/files/stream/upload"),
        ("PUT", "/api/entities/e1"),
        ("PATCH", "/api/entities/e1"),
        ("DELETE", "/api/spaces/s1"),
    ])
    def test_writes_are_never_cancelled(self, method, path):
        """The policy decision. Widening this needs an answer for half-commits."""
        assert is_cancellable_read(method, path) is False


class TestPostBodySurvives:
    """A cancellable POST must still receive its body.

    `Request.is_disconnected()` READS FROM THE ASGI RECEIVE CHANNEL. A poll loop
    running beside the handler consumes the `http.request` message carrying the
    body, and the handler's `await request.json()` then raises ClientDisconnect.

    This shipped. It broke every query POST in the E2E suite — SPARQL execution,
    keyword and semantic search, graph-visualization search — while every
    GET-based page test passed, which is exactly the signature.

    The original tests covered a GET and a POST with NO body, so the one thing
    the allowlisted endpoints all have — a body — was the one thing untested.
    """

    def test_allowlisted_post_receives_its_body(self, monkeypatch):
        monkeypatch.setenv("VITALGRAPH_REQUEST_DEADLINE_S", "20")
        app = FastAPI()
        app.add_middleware(RequestBoundsMiddleware)

        @app.post("/api/kgentities/query")
        async def q(request: Request):
            return {"got": await request.json()}

        with TestClient(app) as c:
            r = c.post("/api/kgentities/query", json={"q": "SELECT *"})
        assert r.status_code == 200
        assert r.json() == {"got": {"q": "SELECT *"}}

    def test_kgqueries_post_receives_its_body(self, monkeypatch):
        monkeypatch.setenv("VITALGRAPH_REQUEST_DEADLINE_S", "20")
        app = FastAPI()
        app.add_middleware(RequestBoundsMiddleware)

        @app.post("/api/kgqueries")
        async def q(request: Request):
            body = await request.json()
            return {"n": len(body.get("criteria", []))}

        with TestClient(app) as c:
            r = c.post("/api/kgqueries", json={"criteria": [1, 2, 3]})
        assert r.status_code == 200 and r.json() == {"n": 3}

    def test_body_carrying_post_is_watched_and_cancelled_on_disconnect(self):
        """The two halves of gap 4 have to hold AT ONCE, so assert both here.

        The first attempt polled `is_disconnected()`, which reads the receive
        channel and so ate the body — watching worked, queries didn't. The fix
        drains the body up front and replays it, which only counts if the
        handler still sees it. A passing disconnect assertion beside a body
        assertion is what says we didn't just trade one failure for the other.
        """
        seen_body = {}
        cancelled = asyncio.Event()

        async def app(scope, receive, send):
            message = await receive()
            seen_body["body"] = message.get("body", b"")
            try:
                await asyncio.sleep(10)          # a slow query
            except asyncio.CancelledError:
                cancelled.set()
                raise

        payload = b'{"criteria": [1, 2, 3]}'
        scope = {"type": "http", "method": "POST", "path": "/api/kgqueries",
                 "headers": []}
        inbound = asyncio.Queue()
        inbound.put_nowait({"type": "http.request", "body": payload,
                            "more_body": False})
        inbound.put_nowait({"type": "http.disconnect"})

        async def run():
            await RequestBoundsMiddleware(app)(
                scope, inbound.get, lambda m: asyncio.sleep(0))

        started = time.monotonic()
        asyncio.run(asyncio.wait_for(run(), timeout=5))
        elapsed = time.monotonic() - started

        assert seen_body["body"] == payload, "drain-and-replay lost the body"
        assert cancelled.is_set(), "disconnect did not cancel the handler"
        assert elapsed < 1, f"returned in {elapsed:.1f}s — waited on the sleep"


class TestDeadlineBoundsFirstByteNotTransfer:
    """A download must not be capped by the request deadline.

    File bytes come from object storage — `/files/stream/download` streams from
    S3 via `stream_download_from_s3` — so the transfer takes as long as the file
    and the network take. That is not a server-side pathology, and cancelling it
    is worse than useless: the 200 already went out, so the client receives a
    TRUNCATED FILE rather than an error it could retry.

    `_LONG_TRANSFER_PATHS` covers the three known download routes, but an
    exclusion list is the wrong thing to rely on — a new S3-backed route would
    inherit the cap silently. So the deadline bounds time-to-FIRST-BYTE, and
    these tests use paths that are NOT excluded, which is exactly what the list
    would otherwise be hiding.
    """

    def test_slow_stream_on_a_non_excluded_path_is_delivered_whole(self, monkeypatch):
        monkeypatch.setenv("VITALGRAPH_REQUEST_DEADLINE_S", "0.4")
        app = FastAPI()
        app.add_middleware(RequestBoundsMiddleware)

        @app.get("/api/graphs/kgdocuments/content")   # deliberately NOT excluded
        async def content():
            async def gen():
                for i in range(6):
                    await asyncio.sleep(0.15)          # 0.9 s — well past 0.4 s
                    yield f"chunk{i}\n".encode()
            return StreamingResponse(gen(), media_type="text/plain")

        with TestClient(app) as c:
            r = c.get("/api/graphs/kgdocuments/content")
        assert r.status_code == 200
        assert r.text == "".join(f"chunk{i}\n" for i in range(6)), \
            "transfer was cut short by the deadline"

    def test_slow_handler_before_first_byte_is_still_bounded(self, monkeypatch):
        """The other half: TTFB semantics must not defeat the deadline itself."""
        monkeypatch.setenv("VITALGRAPH_REQUEST_DEADLINE_S", "0.3")
        app = FastAPI()
        app.add_middleware(RequestBoundsMiddleware)

        @app.get("/api/spaces")
        async def slow():
            await asyncio.sleep(30)                    # a hung query
            return {"never": True}

        with TestClient(app) as c:
            r = c.get("/api/spaces")
        assert r.status_code == 504


class TestLongTransfersAreNeverBounded:
    """Downloads and streams are GETs, and a deadline is wrong for them.

    The safe-method rule would otherwise sweep them in:

        GET /export/download        FileResponse
        GET /files/download         StreamingResponse
        GET /files/stream/download  StreamingResponse

    They used to survive by accident: BaseHTTPMiddleware's call_next returned
    when the response STARTED, so the deadline bounded time-to-first-byte and
    the body streamed on outside it. The pure-ASGI rewrite inherits no such
    luck — it would bound the whole transfer — so the exclusion is explicit
    and these tests pin it.
    """

    @pytest.mark.parametrize("path", [
        "/api/export/download",
        "/api/files/download",
        "/api/files/stream/download",
        "/api/files/stream/abc123",
    ])
    def test_transfer_paths_are_excluded(self, path):
        assert is_cancellable_read("GET", path) is False

    def test_ordinary_get_is_still_bounded(self):
        assert is_cancellable_read("GET", "/api/spaces") is True

    def test_a_slow_stream_is_delivered_whole(self, monkeypatch):
        """A stream longer than the deadline must not be truncated."""
        monkeypatch.setenv("VITALGRAPH_REQUEST_DEADLINE_S", "0.4")
        app = FastAPI()
        app.add_middleware(RequestBoundsMiddleware)

        @app.get("/api/export/download")
        async def dl():
            async def gen():
                for i in range(6):
                    await asyncio.sleep(0.15)      # 0.9 s total
                    yield f"chunk{i}\n".encode()
            return StreamingResponse(gen(), media_type="text/plain")

        with TestClient(app) as c:
            r = c.get("/api/export/download")
        assert r.status_code == 200
        assert r.text.count("chunk") == 6

    def test_upload_is_not_allowlisted(self):
        """The unfinished half of gap 4 would buffer whole bodies (issues/044).

        Doing that to an upload would hold the file in memory, so uploads must
        stay outside the allowlist — a constraint on that design, not an
        accident of this one.
        """
        assert is_cancellable_read("POST", "/api/files/upload") is False
        assert is_cancellable_read("POST", "/api/files/stream/upload") is False


class TestDisconnectDuringBodyRequest:
    """A POST that carries a body must BOTH keep its body and be cancellable.

    Written BEFORE the implementation, because the previous attempt at gap 4
    shipped a watcher that ate the body and no test noticed. These two
    assertions are in tension — the naive way to get one loses the other — so
    they belong in the same class.
    """

    def test_body_survives_and_handler_completes(self, monkeypatch):
        monkeypatch.setenv("VITALGRAPH_REQUEST_DEADLINE_S", "20")
        app = FastAPI()
        app.add_middleware(RequestBoundsMiddleware)

        @app.post("/api/kgqueries")
        async def q(request: Request):
            body = await request.json()
            return {"echo": body["q"]}

        with TestClient(app) as c:
            r = c.post("/api/kgqueries", json={"q": "SELECT * WHERE {?s ?p ?o}"})
        assert r.status_code == 200
        assert r.json() == {"echo": "SELECT * WHERE {?s ?p ?o}"}

    def test_body_request_is_still_deadline_bounded(self, monkeypatch):
        """Cancellation must still reach a body-carrying read."""
        monkeypatch.setenv("VITALGRAPH_REQUEST_DEADLINE_S", "0.2")
        app = FastAPI()
        app.add_middleware(RequestBoundsMiddleware)

        @app.post("/api/kgqueries")
        async def slow(request: Request):
            await request.json()
            await asyncio.sleep(5)
            return {"ok": True}

        with TestClient(app) as c:
            r = c.post("/api/kgqueries", json={"q": "x"})
        assert r.status_code == 504


def _app(handler_seconds: float):
    app = FastAPI()
    app.add_middleware(RequestBoundsMiddleware)

    @app.get("/slow")
    async def slow():
        await asyncio.sleep(handler_seconds)
        return {"ok": True}

    @app.post("/api/spaces")
    async def write():
        await asyncio.sleep(handler_seconds)
        return {"ok": True}

    return app


class TestDeadline:

    def test_read_under_the_deadline_succeeds(self, monkeypatch):
        monkeypatch.setenv("VITALGRAPH_REQUEST_DEADLINE_S", "5")
        with TestClient(_app(0.01)) as c:
            r = c.get("/slow")
        assert r.status_code == 200 and r.json() == {"ok": True}

    def test_read_over_the_deadline_is_bounded(self, monkeypatch):
        monkeypatch.setenv("VITALGRAPH_REQUEST_DEADLINE_S", "0.2")
        with TestClient(_app(5)) as c:
            r = c.get("/slow")
        assert r.status_code == 504
        assert "deadline" in r.json()["detail"]

    def test_write_is_not_bounded_by_the_deadline(self, monkeypatch):
        """A slow write must NOT be cut off — same reason it is not cancelled."""
        monkeypatch.setenv("VITALGRAPH_REQUEST_DEADLINE_S", "0.2")
        with TestClient(_app(0.6)) as c:
            r = c.post("/api/spaces")
        assert r.status_code == 200

    def test_zero_disables_the_deadline(self, monkeypatch):
        monkeypatch.setenv("VITALGRAPH_REQUEST_DEADLINE_S", "0")
        with TestClient(_app(0.3)) as c:
            r = c.get("/slow")
        assert r.status_code == 200

    def test_garbage_deadline_falls_back(self, monkeypatch):
        from vitalgraph.api.request_bounds import (
            _request_deadline_s, _DEFAULT_REQUEST_DEADLINE_S)
        monkeypatch.setenv("VITALGRAPH_REQUEST_DEADLINE_S", "two minutes")
        assert _request_deadline_s() == _DEFAULT_REQUEST_DEADLINE_S
