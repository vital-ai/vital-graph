"""Say what an exception actually was, including the one it replaced.

`issues/253`. Five production writes were lost on 2026-09-30 and the log line for
each said only:

    update_subjects_graph failed: cannot call Transaction.__aexit__():
    the underlying connection is closed

which is the symptom. The cause — the thing that killed the connection in the
first place — was DISCARDED, and finding it took a trawl through the database's
own logs to rule out a server-side termination.

TWO MECHANISMS CONSPIRE, and neither is obvious at the call site.

1. **An exception raised while LEAVING a context manager replaces the one raised
   inside it.** `async with conn.transaction():` is exactly this shape: the body
   fails, the rollback then fails because the connection is already gone, and the
   `except Exception as e` above sees only the rollback's error. The original is
   not lost — Python keeps it in `e.__context__` — it is simply never read.

2. **`str()` of some exceptions is EMPTY.** `asyncio.TimeoutError`, which is what
   asyncpg's `command_timeout` raises, is the one that matters here: `"%s" % e`
   renders nothing at all. This file's sibling defect is recorded in
   `sparql_sql_db_impl.py` — a resync that died at 60 s "surfaced as
   `Resync failed: ` with no reason". So unmasking is not enough on its own; the
   TYPE has to be printed too.

`__cause__` and `__context__` are distinguished in the output because they mean
different things: `__cause__` is a deliberate `raise ... from`, `__context__` is
an accident of nesting, and reading the second as the first would misattribute
the blame. `raise ... from None` sets `__suppress_context__`, which is an author
saying the chain is noise — that is honoured rather than overridden.
"""
from __future__ import annotations

__all__ = ["describe_exception"]

# How many exception FRAMES to print, the raised one included. Deep enough for
# the real chains (rollback -> timeout, or one layer of wrapping), short enough
# that a pathological chain cannot fill a log line.
_MAX_FRAMES = 4


def _one(exc: BaseException) -> str:
    text = str(exc)
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _behind(exc: BaseException):
    """The next frame back and what it is, or None.

    `__cause__` first: a deliberate `raise ... from` outranks the accident of
    nesting. `raise ... from None` sets `__suppress_context__`, which is an
    author saying the chain is noise, and that is honoured.
    """
    if exc.__cause__ is not None:
        return exc.__cause__, "caused by"
    if exc.__context__ is not None and not exc.__suppress_context__:
        return exc.__context__, "masked"
    return None


def describe_exception(exc: BaseException, max_frames: int = _MAX_FRAMES) -> str:
    """*exc* and the chain behind it, as one line.

    >>> try:
    ...     try:
    ...         raise TimeoutError()
    ...     except TimeoutError:
    ...         raise RuntimeError("connection is closed")
    ... except RuntimeError as e:
    ...     describe_exception(e)
    'RuntimeError: connection is closed <- masked TimeoutError'
    """
    parts = [_one(exc)]
    seen = {id(exc)}
    current = exc
    while len(parts) < max_frames:
        behind = _behind(current)
        # A chain can be cyclic once someone re-raises an exception they were
        # holding; without this the loop would be bounded only by max_frames and
        # would print the same frame repeatedly.
        if behind is None or id(behind[0]) in seen:
            return " ".join(parts)
        nxt, how = behind
        seen.add(id(nxt))
        parts.append(f"<- {how} {_one(nxt)}")
        current = nxt
    # Only claim truncation when something was actually left out — an "..." on a
    # chain that happens to be exactly `max_frames` long would send the next
    # reader looking for a frame that does not exist.
    behind = _behind(current)
    if behind is not None and id(behind[0]) not in seen:
        parts.append("<- ...")
    return " ".join(parts)
