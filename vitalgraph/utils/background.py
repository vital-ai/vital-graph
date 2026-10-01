"""Fire-and-forget tasks that survive long enough to finish.

`issues/253`. Deferrable work must not be awaited by a request — five production
writes were lost because one `await` on an ANALYZE held a write transaction open
past `idle_in_transaction_session_timeout`. Scheduling it instead needs three
things done right, and each of them has already been got wrong somewhere:

1. **A STRONG REFERENCE.** `asyncio` keeps only a weak reference to a running
   task, so a task nobody holds can be garbage-collected mid-flight — silently,
   with the work half done. Callers of fire-and-forget helpers discard the return
   value by definition, so the helper has to hold it.
2. **EXCEPTIONS SWALLOWED DELIBERATELY.** Nothing awaits these, so an exception
   surfaces as asyncio's "Task exception was never retrieved" with no context
   attached, usually long after the fact. Logged here with the label and key, and
   not re-raised, because there is no caller to re-raise to.
3. **NO EVENT LOOP IS NOT AN ERROR.** These paths are reached from scripts and
   tests that call the write methods synchronously. Skip quietly.

`vectorization.auto_sync` got all three right first and keeps its own registry
because it also cancels in-flight work when a space is dropped; that extra
requirement is why it is not folded in here.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, Optional, Set

logger = logging.getLogger(__name__)

__all__ = ["BackgroundTasks"]


class BackgroundTasks:
    """A registry of scheduled, unawaited tasks, grouped by key.

    One instance per kind of work, so the label in the log says what failed and
    the key says which space it was for.
    """

    def __init__(self, label: str):
        self._label = label
        self._in_flight: Dict[str, Set[asyncio.Task]] = {}

    def schedule(self, coro, *, key: str) -> Optional[asyncio.Task]:
        """Run *coro* in the background. Returns the task, or None if not started.

        The coroutine is CLOSED when there is no loop to run it on, so a skipped
        schedule does not leave an un-awaited coroutine behind for the GC to
        complain about.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            coro.close()
            logger.debug("%s(%s): no running event loop, skipping",
                         self._label, key)
            return None

        task = loop.create_task(coro, name=f"{self._label}:{key}")
        self._in_flight.setdefault(key, set()).add(task)
        task.add_done_callback(lambda t: self._finished(key, t))
        return task

    def in_flight(self, key: str) -> int:
        """How many tasks are still running for *key*."""
        return len(self._in_flight.get(key, ()))

    def _finished(self, key: str, task: asyncio.Task) -> None:
        pending = self._in_flight.get(key)
        if pending is not None:
            pending.discard(task)
            if not pending:
                self._in_flight.pop(key, None)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("%s(%s) task failed: %s", self._label, key, exc)
