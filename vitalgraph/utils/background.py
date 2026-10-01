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

A FOURTH thing, learned by running the tests rather than by reasoning: a
scheduled task OUTLIVES the space it was scheduled for. The API suite deletes its
ephemeral space while an ANALYZE is still in flight, and the task then logs a wall
of `relation "…" does not exist`. `cancel_all` closes that, and
`space_manager.delete_space_with_tables` calls it before dropping anything — the
same thing it already does for `vectorization.auto_sync`, which hit this first and
whose registry stays separate because it carries extra per-space semantics.
"""
from __future__ import annotations

import asyncio
import logging
import weakref
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

__all__ = ["BackgroundTasks", "cancel_all"]

# Every live registry, so one call can sweep them all when a space is dropped.
# WEAK references: a registry created in a test must not be kept alive by this,
# and a dead one must not be swept.
#
# A registry-of-registries rather than a list of cancel calls at the drop site,
# because the failure this prevents is someone adding a FOURTH scheduler and
# forgetting to wire its teardown in — `vectorization.auto_sync` learned that
# lesson by filling the PostgreSQL log with "relation does not exist" when its
# tasks woke against a half-dropped schema.
_REGISTRIES: "weakref.WeakSet[BackgroundTasks]" = weakref.WeakSet()


async def cancel_all(key: str, *, timeout: float = 5.0) -> int:
    """Cancel in-flight tasks for *key* across every registry. Returns the count.

    Call this BEFORE dropping a space's tables. A scheduled task that wakes up
    against a half-dropped schema logs a wall of "relation does not exist", and
    PostgreSQL records every failed statement server-side even though the client
    swallows it.
    """
    cancelled = 0
    for registry in list(_REGISTRIES):
        cancelled += await registry.cancel(key, timeout=timeout)
    return cancelled


class BackgroundTasks:
    """A registry of scheduled, unawaited tasks, grouped by key.

    One instance per kind of work, so the label in the log says what failed and
    the key says which space it was for.
    """

    def __init__(self, label: str):
        self._label = label
        self._in_flight: Dict[str, Set[asyncio.Task]] = {}
        _REGISTRIES.add(self)

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

    async def cancel(self, key: str, *, timeout: float = 5.0) -> int:
        """Cancel the tasks for *key* and WAIT for them. Returns how many.

        Waiting matters: the caller is about to drop the tables these tasks are
        reading, and returning before they have actually stopped would leave the
        race this exists to close.
        """
        pending = list(self._in_flight.get(key, ()))
        if not pending:
            return 0
        for task in pending:
            task.cancel()
        # `return_exceptions`: a task that was mid-statement surfaces the
        # cancellation as an exception, and one of those must not stop the rest
        # from being awaited.
        try:
            await asyncio.wait_for(
                asyncio.gather(*pending, return_exceptions=True), timeout)
        except (asyncio.TimeoutError, TimeoutError):
            logger.warning("%s(%s): %d task(s) did not stop within %.1fs",
                           self._label, key, len(pending), timeout)
        return len(pending)
