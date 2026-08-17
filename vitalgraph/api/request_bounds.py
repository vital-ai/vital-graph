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

SLOW IS FINE, STUCK IS NOT. Exempting transfers from the deadline left them with
no fence at all, so a connection that stopped moving bytes could hold a worker
and an S3 stream indefinitely. Duration cannot distinguish the two — a large file
over a thin link looks like a hang — but PROGRESS can, and both directions move
in chunks. `_progress_bounded` cancels a transfer that has gone quiet for
`VITALGRAPH_TRANSFER_STALL_S` (60s, 0 disables) while never capping a
slow-but-progressing one.

It watches only the phases where bytes SHOULD be moving: for a write, from the
first chunk until the body is complete, after which the handler is committing
and silence is expected; for a read, from the first response byte onward, since
an export generates its file before sending anything. Cancelling either of those
quiet-but-busy phases would be the silent rollback this module exists to avoid.

A write blocked in `receive` counts as watched even before any chunk arrives:
wanting client bytes that never come is a silent client, and a busy handler
cannot look like that because it never reaches the await.

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
#   GET /files/stream/download  StreamingResponse   (files_endpoint.py)
#
# The deadline is time-to-first-byte (see `__call__`), so a long transfer is
# already safe and this list is DEFENCE IN DEPTH, not the thing holding them up.
# It still earns its place: these paths can be slow BEFORE the first byte too —
# an export generates a file, and an S3 fetch pays its latency up front — and a
# 504 there would be just as wrong. Pinned by a test: a 0.9 s stream delivers
# all six chunks under a 0.4 s deadline.
_LONG_TRANSFER_PATHS = (
    re.compile(r"/export/download(?:/|$)"),
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


# A transfer is allowed to be SLOW but not STUCK. Total duration says nothing —
# a large file over a thin link is indistinguishable from a hang by that measure
# — but both directions move in chunks (8192 bytes by default, see
# files_endpoint), so "no bytes at all for this long" separates the two cleanly.
#
# 60s is deliberately generous: it is not a performance fence, it is the point
# past which a connection is not coming back.
_DEFAULT_TRANSFER_STALL_S = 60.0


def _transfer_stall_s() -> float:
    raw = os.environ.get("VITALGRAPH_TRANSFER_STALL_S")
    if raw is None:
        return _DEFAULT_TRANSFER_STALL_S
    try:
        return max(0.0, float(raw))          # 0 disables
    except ValueError:
        logger.warning("VITALGRAPH_TRANSFER_STALL_S=%r is not a number; using %s",
                       raw, _DEFAULT_TRANSFER_STALL_S)
        return _DEFAULT_TRANSFER_STALL_S


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
    JSON. `/files/stream/upload` is excluded and tested for; buffering a file here
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
            # Uploads, downloads and writes. No deadline and no buffering, but
            # not unwatched either — a connection that stops MOVING BYTES is
            # stuck, and that is visible without capping how long a legitimate
            # transfer may run. See `_progress_bounded`.
            await self._progress_bounded(scope, receive, send)
            return

        deadline = _request_deadline_s()
        loop = asyncio.get_event_loop()

        # THE DRAIN IS INSIDE THE DEADLINE. It has to be: a client can send
        # headers and then nothing, and this loop would otherwise wait on a body
        # that never arrives, holding the connection with no fence running —
        # the timer below has not started yet. The old BaseHTTPMiddleware had no
        # such hole, because the handler's own body read happened INSIDE its
        # `asyncio.wait`; moving the read out here is what opened it.
        expires = loop.time() + deadline if deadline > 0 else None

        chunks: list = []
        while True:
            try:
                if expires is None:
                    message = await receive()
                else:
                    message = await asyncio.wait_for(
                        receive(), timeout=max(0.0, expires - loop.time()))
            except (asyncio.TimeoutError, TimeoutError):
                logger.info("request bounded: %s %s — deadline exceeded "
                            "awaiting request body",
                            scope.get("method"), scope.get("path"))
                await _send_json(
                    send, 504,
                    {"detail": f"request exceeded {deadline:g}s deadline"})
                return
            if message["type"] == "http.disconnect":
                return              # gone before we began; nothing to answer
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)

        # Whatever the drain used is gone from the budget; the rest bounds
        # time-to-first-byte, so a slow body plus a slow query cannot together
        # exceed the deadline they are each supposed to be inside.
        remaining = max(0.0, expires - loop.time()) if expires is not None else 0.0

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
                timeout=remaining if expires is not None else None,
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

    async def _progress_bounded(self, scope, receive, send) -> None:
        """Cancel a connection that has stopped moving bytes. No deadline.

        This is what covers uploads and downloads, which the deadline path
        deliberately will not touch: their duration is set by file size and by
        object storage, so any total-time bound is either too short for a big
        file or too long to be worth having.

        WHICH PHASES ARE WATCHED IS THE WHOLE DESIGN. The watchdog runs only
        while bytes SHOULD be moving:

          upload / write   from the first chunk until the request body is
                           complete, then it detaches. After that the handler
                           is committing to S3 and the database, which looks
                           exactly like a stall from out here — and cancelling
                           a commit is the silent rollback that the reads-only
                           policy exists to prevent (see the module docstring).

          download / read  from the first byte of the response onward. NOT
                           before: an export generates its file first, and an
                           S3 fetch pays its latency up front, with no bytes
                           moving through either — which is precisely why these
                           paths are exempt from the deadline to begin with.

        So a stalled transfer is reclaimed, while slow-but-progressing transfers
        and busy-but-silent handlers are both left alone.
        """
        stall = _transfer_stall_s()
        if stall <= 0:
            await self.app(scope, receive, send)
            return

        loop = asyncio.get_event_loop()
        is_read = scope.get("method", "").upper() in _SAFE_METHODS
        last = loop.time()
        awaiting_bytes = False          # blocked in `receive` on a write
        watching = asyncio.Event()      # bytes should be moving right now
        detached = asyncio.Event()      # stop watching for good

        # NOT armed yet, in either direction. Arming happens when bytes actually
        # start moving — at the first response byte for a read, and at the first
        # multi-chunk body message for a write. Arming a write up front would
        # cancel any slow handler that never reads a body (or reads it in one
        # message), since nothing would ever refresh the timestamp — a write
        # cancelled by silence, which is the exact failure this must not cause.

        async def wrapped_receive():
            nonlocal last, awaiting_bytes
            # Being BLOCKED HERE on a write is itself the signal: the handler
            # wants client bytes and none are coming. That is a silent client,
            # and it is distinguishable from a busy handler — which never
            # reaches this await at all. Reads are excluded because a
            # StreamingResponse parks in `receive` purely to listen for
            # disconnects, so a download would look permanently blocked.
            awaiting_bytes = not is_read
            try:
                message = await receive()
            finally:
                awaiting_bytes = False
            last = loop.time()
            if message["type"] == "http.disconnect":
                detached.set()          # nothing left to measure
            elif not is_read and message["type"] == "http.request":
                # Writes ONLY — a StreamingResponse also reads `receive` to
                # listen for disconnects, so on a GET the end-of-body message
                # arrives immediately and would detach the watchdog before the
                # download had sent a single byte.
                if message.get("more_body", False):
                    watching.set()      # a real upload is in flight
                else:
                    detached.set()      # body is in; the handler owns it now
            return message

        async def wrapped_send(message):
            nonlocal last
            # Timestamp AFTER the await, not before: when a client stops reading,
            # TCP backpressure blocks here, and that is the stall we want to see.
            await send(message)
            last = loop.time()
            if is_read and message["type"] == "http.response.start":
                watching.set()

        handler = asyncio.ensure_future(
            self.app(scope, wrapped_receive, wrapped_send))

        async def watchdog():
            tick = min(stall / 4.0, 5.0)
            while not handler.done() and not detached.is_set():
                await asyncio.sleep(tick)
                if detached.is_set():
                    continue
                if not (watching.is_set() or awaiting_bytes):
                    continue
                if loop.time() - last > stall:
                    logger.warning(
                        "transfer bounded: %s %s — %s for %gs",
                        scope.get("method"), scope.get("path"),
                        "no request body" if awaiting_bytes else "no progress",
                        stall)
                    handler.cancel()
                    return

        guard = asyncio.ensure_future(watchdog())
        try:
            await handler
        except asyncio.CancelledError:
            if not guard.done():        # our own cancellation, not the caller's
                raise
        finally:
            if not guard.done():
                guard.cancel()
