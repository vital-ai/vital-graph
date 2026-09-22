"""
Server-side retry decorator for transient asyncpg / PostgreSQL errors.

Wraps async functions that use ``pool.acquire()`` so that transient
connection failures (reset, timeout, interface error) are retried with
exponential back-off instead of immediately surfacing as 500s.

Usage::

    from vitalgraph.utils.db_retry import with_db_retry

    @with_db_retry()
    async def get_widget(self, widget_id: str):
        async with self.pool.acquire() as conn:
            ...

Or applied at call-site::

    result = await with_db_retry(max_retries=2)(self.get_widget)(widget_id)
"""

import asyncio
import functools
import logging
import random
from typing import Callable, Tuple, Type

import asyncpg

logger = logging.getLogger(__name__)

# asyncpg exception types that indicate a transient connection issue
# (as opposed to a query/logic error that would fail again on retry).
TRANSIENT_PG_EXCEPTIONS: Tuple[Type[BaseException], ...] = (
    asyncpg.InterfaceError,                # connection already closed / broken pipe
    asyncpg.ConnectionDoesNotExistError,   # stale connection reuse
    asyncpg.TooManyConnectionsError,       # pool / server exhaustion
    asyncpg.CannotConnectNowError,         # server starting up
    ConnectionResetError,
    ConnectionRefusedError,
    OSError,                               # catch-all for low-level socket errors
)

# Errors that look transient based on message content even if the
# exception type is generic (e.g. asyncpg.PostgresError).
_TRANSIENT_MSG_FRAGMENTS = (
    "connection reset",
    "connection refused",
    "server closed the connection",
    "terminating connection",
    "could not connect",
    "timeout",
    "too many clients",
)


class SparqlQueryFailed(Exception):
    """A SPARQL read did not complete. NOT "it matched nothing".

    `execute_sparql_query` reports failure correctly, returning
    `{'results': {'bindings': []}, 'success': False, 'error': ...}`. Every
    `_extract_bindings` helper then read `results.bindings` and never looked at
    `success`, so a killed query and an empty space produced the same value —
    an empty list — and the distinction was gone before any caller could act
    on it.

    Observed on the dev instance: the same listing returned 0 entities after a
    56 s statement timeout and 25 entities warm a minute later, both HTTP 200
    (`issues/215`).

    Raised rather than returned so it cannot be flattened again by accident.
    Callers that want the 200-with-error contract catch it and set
    `OperationStatus.QUERY_FAILED`; callers that do not catch it get a loud
    failure, which is still strictly better than a confident empty answer.
    """

    def __init__(self, error: str = "", space_id: str = ""):
        self.error = error
        self.space_id = space_id
        super().__init__(
            f"SPARQL query failed{f' on {space_id}' if space_id else ''}: "
            f"{error or 'no error text reported'}")


def is_query_timeout(exc: BaseException) -> bool:
    """Did this read run out of TIME, as opposed to being unable to run at all?

    The split that decides a KGQuery's HTTP status. A query that ran and
    exceeded its budget is a domain outcome — the request was answerable in
    principle, it was too expensive — so it is reported as HTTP 200 with
    `status=query_failed`, as the entity and type endpoints already do. An
    unreachable sidecar or a lost connection is a server-level fault and stays
    an HTTP 500 (`issues/082`).

    Two sources count as a timeout:

    * PostgreSQL's `statement_timeout` — SQLSTATE 57014 with the server's own
      message "canceling statement due to statement timeout". 57014 is also an
      administrator's cancel ("due to user request"), which is NOT a timeout,
      so the message is what separates them; it is emitted by PostgreSQL
      itself, not composed here.
    * the driver's `command_timeout`, surfaced as `asyncio.TimeoutError`.
    """
    import asyncio
    try:
        import asyncpg
    except ImportError:  # pragma: no cover - client-only installs
        asyncpg = None
    if isinstance(exc, asyncio.TimeoutError):
        return True
    if asyncpg is not None and isinstance(exc, asyncpg.QueryCanceledError):
        return "statement timeout" in str(exc)
    return False


class DatabaseUnavailableError(Exception):
    """Raised when the database is unreachable after all retry attempts.

    HTTP layers should catch this and return 503 Service Unavailable
    so that clients know to retry.
    """

    def __init__(self, cause: BaseException, attempts: int):
        self.cause = cause
        self.attempts = attempts
        super().__init__(
            f"Database unavailable after {attempts} attempt(s): {cause}"
        )


def _is_transient(exc: BaseException) -> bool:
    """Return True if *exc* looks like a transient DB failure."""
    if isinstance(exc, TRANSIENT_PG_EXCEPTIONS):
        return True
    msg = str(exc).lower()
    return any(frag in msg for frag in _TRANSIENT_MSG_FRAGMENTS)


def with_db_retry(
    max_retries: int = 3,
    base_delay: float = 0.25,
    max_delay: float = 4.0,
    jitter: float = 0.25,
):
    """
    Decorator factory for retrying async functions on transient DB errors.

    Args:
        max_retries:  Number of retry attempts after the initial call.
        base_delay:   Initial back-off delay in seconds.
        max_delay:    Cap for exponential back-off.
        jitter:       Random jitter added to each delay (seconds).
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return await fn(*args, **kwargs)
                except Exception as exc:
                    if not _is_transient(exc):
                        raise
                    if attempt >= max_retries:
                        raise DatabaseUnavailableError(exc, max_retries + 1) from exc
                    last_exc = exc
                    delay = min(base_delay * (2 ** attempt), max_delay) + random.uniform(0, jitter)
                    logger.warning(
                        "Transient DB error in %s (attempt %d/%d): %s — retrying in %.2fs",
                        fn.__qualname__, attempt + 1, max_retries + 1,
                        exc, delay,
                    )
                    await asyncio.sleep(delay)
            # Should not reach here, but safety net
            raise last_exc  # type: ignore[misc]

        return wrapper
    return decorator
