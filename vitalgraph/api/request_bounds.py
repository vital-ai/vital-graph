"""Bound a request as a whole: cancel it when the client leaves, or on deadline.

`issues/044` gaps 1 and 4. Both are the same missing thing — nothing bounds a
REQUEST — so one middleware answers both.

Gap 4, client disconnect. uvicorn's `connection_lost` sets `cycle.disconnected`
and wakes the message event, but **never cancels the ASGI task**, and nothing
under `vitalgraph/` called `request.is_disconnected()` (zero hits). A handler
whose client hung up ran to completion, burning CPU, a pool slot and a database
backend for a response nobody would read.

Gap 1, per-request bound. The fences that exist are per-STATEMENT — asyncpg's
`command_timeout` and the read path's `statement_timeout`. One KGQuery request
runs several statements (index metadata prefetches, pair statistics, the page,
the count), each getting its own independent budget, so a request could take an
arbitrary multiple of any single fence. That is why the symptom read as "no
server-side timeout" even though fences existed.

WHY CANCELLATION IS ENOUGH TO STOP THE WORK: asyncpg turns task cancellation
into a PostgreSQL CancelRequest and the backend disappears from
`pg_stat_activity` immediately — verified in `issues/044` and relied on by
`kgquery_endpoint._gather_cancelling`.

READS ONLY, DELIBERATELY
------------------------
Cancelling a disconnected client's WRITE mid-transaction is not obviously right,
so this does not do it. A client that hangs up after issuing a write may well
have intended the write; PostgreSQL would roll it back on cancel, turning a
network hiccup into silent data loss that the client cannot detect, because it
is by definition no longer listening.

Reads have no such ambiguity: nobody is waiting for the answer, and abandoning
the work is exactly right.

So the policy is: cancel on disconnect for safe methods (GET/HEAD/OPTIONS), plus
an explicit allowlist of paths that are reads despite being POST — KGQuery and
SPARQL SELECT both post their query in a body. Everything else runs to
completion as it does today. Anyone widening this should be able to answer what
happens to a half-committed write first.

The deadline is separate and applies to reads only for the same reason.

WHAT THE DEADLINE BOUNDS: time to the FIRST BYTE, not the transfer. A slow QUERY
is what this is for; how long a download takes is set by file size and by object
storage, and `/files/stream/download` streams from S3 (`stream_download_from_s3`)
in chunks. Bounding that would cap legitimate transfers, and it would fail badly
— the 200 has already gone out, so cancelling mid-stream TRUNCATES THE FILE
instead of raising anything the client can see.

The old `BaseHTTPMiddleware` got this semantic by accident: `call_next` returned
as soon as the handler produced a response object, so the body streamed on
outside its `asyncio.wait`. Pure ASGI wraps `send` and would otherwise see the
transfer through to the last byte, so the two-phase wait in `__call__` makes the
same semantic explicit. Disconnect still cancels during the transfer, which is
purely good: it stops pulling bytes from S3 for a client that left.

UPLOADS are outside the allowlist and must stay there. Detecting a disconnect
for a body-carrying POST means draining and buffering that body first (see the
class docstring); doing that to an upload would hold the entire file in memory.
The allowlist is query endpoints only, and that is a constraint on the design,
not an accident of it.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Optional

import json

logger = logging.getLogger(__name__)

# Reads that arrive as POST because the query goes in the body. Matched against
# the path, so a new read endpoint has to be added here deliberately rather than
# inheriting cancellation by accident.
# Taken from the registered routes, not guessed. A first version guessed and got
# it wrong in a way the tests caught: `kgqueries?` means "kgquerie" + optional
# "s", which never matches "kgquery".
#
#   kgquery_endpoint.py:112      POST /kgqueries
#   kgentities_endpoint.py:423   POST /kgentities/query
#   kgrelations_endpoint.py:166  POST /kgrelations/query
#   kgframes_endpoint.py:684     POST /kgframes/query
_READ_POST_PATHS = (
    re.compile(r"/kgqueries(?:/|$)"),
    re.compile(r"/kg(?:entities|relations|frames|documents)/query(?:/|$)"),
    # Registered as POST /api/graphs/sparql/query. Note the sibling write routes
    # under the same prefix — /sparql/update, /sparql/insert, /sparql/delete —
    # which this must NOT match, hence anchoring on "query" and not "sparql".
    re.compile(r"/sparql/query(?:/|$)"),
)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Long-lived transfers, excluded outright. These are GETs, so the safe-method
# rule would otherwise sweep them in, and a request DEADLINE is the wrong idea
# for a transfer whose whole job is to take as long as the data needs:
#
#   GET /export/download        FileResponse        (export_endpoint.py:170)
#   GET /files/download         StreamingResponse   (files_endpoint.py:182)
#   GET /files/stream/download  StreamingResponse   (files_endpoint.py:212)
#
# The deadline is time-to-first-byte (see `__call__`), so a long transfer is
# already safe and this list is DEFENCE IN DEPTH, not the thing holding them up.
# It still earns its place: these paths can be slow BEFORE the first byte too —
# an export generates a file, and an S3 fetch pays its latency up front — and a
# 504 there would be just as wrong. Pinned by a test: a 0.9 s stream delivers
# all six chunks under a 0.4 s deadline.
_LONG_TRANSFER_PATHS = (
    re.compile(r"/export/download(?:/|$)"),
    re.compile(r"/files/(?:stream/)?download(?:/|$)"),
    re.compile(r"/files/stream(?:/|$)"),
)


_DEFAULT_REQUEST_DEADLINE_S = 120.0

def _request_deadline_s() -> float:
    raw = os.environ.get("VITALGRAPH_REQUEST_DEADLINE_S")
    if raw is None:
        return _DEFAULT_REQUEST_DEADLINE_S
    try:
        return max(0.0, float(raw))
    except ValueError:
        logger.warning("VITALGRAPH_REQUEST_DEADLINE_S=%r is not a number; "
                       "using %s", raw, _DEFAULT_REQUEST_DEADLINE_S)
        return _DEFAULT_REQUEST_DEADLINE_S


def is_cancellable_read(method: str, path: str) -> bool:
    """Whether abandoning this request is unambiguously safe.

    Split out so it is testable without an ASGI stack, and so the policy is one
    readable predicate rather than a condition buried in the middleware.
    """
    if any(p.search(path) for p in _LONG_TRANSFER_PATHS):
        return False          # long-lived transfer — never bound it
    if method.upper() in _SAFE_METHODS:
        return True
    if method.upper() == "POST":
        return any(p.search(path) for p in _READ_POST_PATHS)
    return False


async def _send_json(send, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class RequestBoundsMiddleware:
    """Pure ASGI, deliberately — `BaseHTTPMiddleware` owns the receive wrapper.

    The first version subclassed it and polled `Request.is_disconnected()`
    beside the handler. That reads the receive channel, so it CONSUMED THE
    REQUEST BODY and every query POST broke. The stopgap was to watch only
    bodyless requests, which left gap 4 half delivered: a client hanging up
    mid-query on `/kgqueries` went unnoticed until the deadline.

    This is the shape that works, and the ORDER is the whole idea:

      1. Drain the body HERE, before the handler starts. Afterwards the only
         message the client can still send is `http.disconnect`, so watching
         for one can no longer steal anything.
      2. Give the handler a `receive` that REPLAYS the buffered body once, then
         yields whatever the watcher forwards.
      3. The watcher is the SINGLE owner of the real `receive`. Two callers
         would race for the same message.

    Buffering is why the allowlist stays query endpoints only — small criteria
    JSON. `/files/upload` is excluded and tested for; buffering a file here
    would hold it in memory. Long transfers are excluded too
    (`_LONG_TRANSFER_PATHS`): the old base class returned at first byte so a
    stream outran the deadline by accident, and nothing here inherits that.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        if not is_cancellable_read(scope.get("method", ""), scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        deadline = _request_deadline_s()

        chunks: list = []
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return              # gone before we began; nothing to answer
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)

        forwarded: asyncio.Queue = asyncio.Queue()
        disconnected = asyncio.Event()
        responding = asyncio.Event()
        replayed = False

        async def wrapped_receive():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await forwarded.get()

        async def watch():
            while True:
                message = await receive()
                await forwarded.put(message)
                if message["type"] == "http.disconnect":
                    disconnected.set()
                    return

        async def wrapped_send(message):
            if message["type"] == "http.response.start":
                responding.set()
            await send(message)

        handler = asyncio.ensure_future(
            self.app(scope, wrapped_receive, wrapped_send))
        watcher = asyncio.ensure_future(watch())
        gone = asyncio.ensure_future(disconnected.wait())
        first_byte = asyncio.ensure_future(responding.wait())

        try:
            # PHASE 1 — bound TIME TO FIRST BYTE, not the transfer.
            #
            # The deadline exists to catch a slow QUERY. Applying it to the
            # response body would cap how long a DOWNLOAD may take, and file
            # bytes come from object storage (`stream_download_from_s3`), where
            # the duration is set by file size and S3 latency — neither of which
            # is a server-side pathology. Worse, the failure mode is a TRUNCATED
            # file rather than an error: we would have cancelled mid-stream
            # after a 200 already went out.
            done, _pending = await asyncio.wait(
                {handler, gone, first_byte},
                timeout=deadline if deadline > 0 else None,
                return_when=asyncio.FIRST_COMPLETED,
            )

            # PHASE 2 — bytes are flowing, so the deadline has done its job and
            # the transfer takes as long as it takes. Disconnect still cancels:
            # if the client hangs up mid-download, stop pulling from S3.
            if first_byte in done and handler not in done and gone not in done:
                done, _pending = await asyncio.wait(
                    {handler, gone}, return_when=asyncio.FIRST_COMPLETED)

            if handler in done:
                exc = handler.exception()
                if exc is not None:
                    raise exc
                return

            hung_up = gone in done
            reason = "client disconnected" if hung_up else "deadline exceeded"

            # Cancel AND AWAIT. Returning while the query is still winding down
            # is the defect this exists to fix; asyncpg turns the cancellation
            # into a PostgreSQL CancelRequest.
            handler.cancel()
            try:
                await handler
            except (asyncio.CancelledError, Exception):
                pass

            logger.info("request bounded: %s %s — %s",
                        scope.get("method"), scope.get("path"), reason)

            if not responding.is_set() and not hung_up:
                # Only worth answering when someone is still listening — and
                # only when nothing was sent, or we would be appending a 504 to
                # a response that already started with some other status.
                await _send_json(
                    send, 504,
                    {"detail": f"request exceeded {deadline:g}s deadline"})
        finally:
            for task in (watcher, gone, first_byte):
                if not task.done():
                    task.cancel()
