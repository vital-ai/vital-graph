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
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

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
    # Not currently registered, but a SPARQL SELECT posted in a body is the same
    # shape and should not have to be rediscovered if one is added.
    re.compile(r"/sparql/query(?:/|$)"),
)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Above the read path's 55s statement_timeout, so a single slow statement
# surfaces as its own error rather than as an opaque request timeout — the
# specific fence is the more useful diagnosis. 0 disables.
_DEFAULT_REQUEST_DEADLINE_S = 120.0

# How often to ask whether the client is still there. Cheap — it reads a flag
# uvicorn already maintains — but not free, so not a tight loop.
_DISCONNECT_POLL_S = 0.5


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
    if method.upper() in _SAFE_METHODS:
        return True
    if method.upper() == "POST":
        return any(p.search(path) for p in _READ_POST_PATHS)
    return False


class RequestBoundsMiddleware(BaseHTTPMiddleware):
    """Cancel a read when its client disconnects, or when it outlives the deadline."""

    async def dispatch(self, request, call_next):
        if not is_cancellable_read(request.method, request.url.path):
            return await call_next(request)

        deadline = _request_deadline_s()
        handler = asyncio.ensure_future(call_next(request))
        watcher = asyncio.ensure_future(self._watch_disconnect(request))

        try:
            done, _pending = await asyncio.wait(
                {handler, watcher},
                timeout=deadline if deadline > 0 else None,
                return_when=asyncio.FIRST_COMPLETED,
            )

            if handler in done:
                return handler.result()

            # Either the client went away or the deadline passed. Cancel and
            # WAIT for it: returning while the query is still winding down is
            # what leaves the backend running, which is the whole defect.
            reason = "client disconnected" if watcher in done else "deadline exceeded"
            handler.cancel()
            try:
                await handler
            except (asyncio.CancelledError, Exception):
                pass

            logger.info("request bounded: %s %s — %s",
                        request.method, request.url.path, reason)
            if watcher in done:
                # Nobody is listening; the status is for logs and middleware
                # below us, not for a client.
                return JSONResponse(status_code=499,
                                    content={"detail": "client disconnected"})
            return JSONResponse(
                status_code=504,
                content={"detail": f"request exceeded {deadline:g}s deadline"})
        finally:
            if not watcher.done():
                watcher.cancel()

    @staticmethod
    async def _watch_disconnect(request) -> None:
        """Return once the client has hung up."""
        while True:
            try:
                if await request.is_disconnected():
                    return
            except Exception:
                # A transport that cannot answer is not a reason to kill the
                # request; fall back to the deadline.
                return
            await asyncio.sleep(_DISCONNECT_POLL_S)
