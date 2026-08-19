"""
Process Scheduler — periodic asyncio job runner with distributed locking.

Manages one or more registered jobs. Each job runs on a fixed interval.
Before executing, the scheduler acquires an advisory lock via
ProcessLockManager so that only one instance (across N ECS tasks) runs
a given job at a time.

Lifecycle:
    scheduler = ProcessScheduler(pool, postgresql_config)
    scheduler.register_job("db_maintenance", 300, maintenance_job.run)
    await scheduler.start()
    ...
    await scheduler.stop()
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional, Union

from .process_lock_manager import ProcessLockManager

logger = logging.getLogger(__name__)


@dataclass
class _RegisteredJob:
    """Internal descriptor for a registered periodic job."""
    name: str
    interval_seconds: float
    handler: Any  # Callable or object with async .run() method
    process_type: str = "maintenance"
    # Whether the handler exposes `trigger_<process_type>(space_id)`. Decided at
    # registration so a scoped request gets an answer rather than a full sweep.
    supports_scope: bool = False
    task: Optional[asyncio.Task] = field(default=None, repr=False)
    run_count: int = 0
    last_run: Optional[float] = None
    last_error: Optional[str] = None


class ProcessScheduler:
    """Periodic asyncio job runner with distributed advisory-lock gating.

    Usage::

        scheduler = ProcessScheduler(pool, postgresql_config)
        scheduler.register_job(
            name="db_maintenance",
            interval_seconds=300,
            handler=maintenance_job.run,
            process_type="maintenance",
        )
        await scheduler.start()
        # ... app runs ...
        await scheduler.stop()
    """

    def __init__(self, pool, postgresql_config: dict, enabled: bool = True):
        """
        Args:
            pool: asyncpg connection pool (for lock manager).
            postgresql_config: Dict with host/port/database/username/password
                               (passed to ProcessLockManager).
            enabled: Master switch. If False, start() is a no-op.
        """
        self._pool = pool
        self._lock_manager = ProcessLockManager(postgresql_config)
        self._enabled = enabled
        self._running = False
        self._jobs: Dict[str, _RegisteredJob] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_job(
        self,
        name: str,
        interval_seconds: float,
        handler: Any,
        process_type: str = "maintenance",
    ) -> None:
        """Register a periodic job.

        Args:
            name: Unique job name (also used as advisory lock sub-key).
            interval_seconds: How often to run (e.g. 300 = every 5 min).
            handler: Async callable to invoke each cycle.
            process_type: Process type string for advisory lock namespace.
        """
        if name in self._jobs:
            raise ValueError(f"Job '{name}' already registered")

        # SCOPING IS DECLARED AT REGISTRATION, not discovered per request.
        #
        # `trigger_now` honours `space_id` by looking for `trigger_<process_type>`
        # on the handler and FELL THROUGH to the full sweep when it was absent —
        # silently, with `triggered: true` either way. Two jobs shipped that way
        # and the cost was found only when a test timed out: `maintenance` ran
        # 109 s for a request scoped to one space, `analytics` 227 s. See
        # issues/109.
        #
        # A missing method is not an error — a job may legitimately have nothing
        # per-space to do. What is not acceptable is DISCOVERING that per request
        # and answering as though the request had been honoured. Recording it
        # here lets `trigger_now` say so.
        supports_scope = callable(getattr(handler, f"trigger_{process_type}", None))
        if not supports_scope:
            logger.info(
                "ProcessScheduler: job '%s' (process_type=%s) has no "
                "trigger_%s(space_id) — requests naming a space will be "
                "REFUSED rather than silently run against every space",
                name, process_type, process_type)

        self._jobs[name] = _RegisteredJob(
            name=name,
            interval_seconds=interval_seconds,
            handler=handler,
            process_type=process_type,
            supports_scope=supports_scope,
        )
        logger.info("ProcessScheduler: registered job '%s' (every %ds)", name, interval_seconds)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start all registered jobs as background asyncio tasks."""
        if not self._enabled:
            logger.info("ProcessScheduler: disabled, not starting")
            return
        if self._running:
            return

        await self._lock_manager.connect()
        self._running = True

        for job in self._jobs.values():
            job.task = asyncio.create_task(self._job_loop(job))

        logger.info(
            "ProcessScheduler: started %d job(s): %s",
            len(self._jobs),
            ", ".join(self._jobs.keys()),
        )

    async def stop(self) -> None:
        """Cancel all job tasks and disconnect the lock manager."""
        self._running = False

        for job in self._jobs.values():
            if job.task and not job.task.done():
                job.task.cancel()
                try:
                    await job.task
                except asyncio.CancelledError:
                    pass
                job.task = None

        await self._lock_manager.disconnect()
        logger.info("ProcessScheduler: stopped")

    # ------------------------------------------------------------------
    # On-demand trigger
    # ------------------------------------------------------------------

    class ScopingUnsupported(ValueError):
        """`space_id` was given for a process type that cannot honour it.

        Distinct from both other refusals: the type EXISTS and the lock is free,
        but scoping is not available. Silently running the whole sweep instead
        was the defect in issues/109 — 109 s and 227 s for requests naming one
        space, answered `triggered: true`.
        """


    class UnknownProcessType(ValueError):
        """No handler is registered for this process type.

        Distinct from a busy lock, and the distinction is the point: a busy lock
        means TRY AGAIN SHORTLY, an unknown type means THIS WILL NEVER WORK.
        Both returned None, so the endpoint answered "Lock busy or no handler
        registered for this process type" — one message for a transient
        condition and a permanent one, leaving the caller no way to choose
        between retrying and fixing the request.
        """

    async def trigger_now(
        self,
        process_type: str,
        space_id: Optional[str] = None,
    ) -> Optional[Any]:
        """Trigger a maintenance operation immediately (bypasses scheduler interval).

        This acquires the advisory lock and runs the matching job handler
        directly. If no matching job is found, logs a warning.

        Args:
            process_type: E.g. 'analyze', 'vacuum', 'stats_rebuild'.
            space_id: Target space (passed to handler if supported).

        Returns:
            Handler result, or None if lock was busy / no handler found.
        """
        # Find a registered job whose process_type matches
        job = next(
            (j for j in self._jobs.values() if j.process_type == process_type),
            None,
        )
        handler = None
        if job:
            handler = job.handler
        # Fallback: find any handler that has a trigger_{process_type} method
        if handler is None:
            for j in self._jobs.values():
                if hasattr(j.handler, f"trigger_{process_type}"):
                    handler = j.handler
                    break
        if handler is None:
            known = sorted({j.process_type for j in self._jobs.values()})
            logger.warning("ProcessScheduler: no handler for process_type='%s' "
                           "(registered: %s)", process_type, ", ".join(known))
            raise ProcessScheduler.UnknownProcessType(
                f"no handler registered for process_type={process_type!r}; "
                f"registered types are: {', '.join(known) or '(none)'}")

        lock_subtype = f"{process_type}:{space_id}" if space_id else process_type
        acquired = await self._lock_manager.try_acquire(process_type, lock_subtype)
        if not acquired:
            logger.info("ProcessScheduler: trigger_now lock busy for %s", lock_subtype)
            return None

        try:
            # If the handler supports trigger_* methods, call those directly
            if space_id:
                trigger_method = getattr(handler, f"trigger_{process_type}", None)
                if callable(trigger_method):
                    return await trigger_method(space_id)  # type: ignore[misc]
                # REFUSE rather than fall through. Running the full sweep for a
                # request that named ONE space is not a degraded version of what
                # was asked for — it is different work, of a different order,
                # reported as success. issues/109.
                raise ProcessScheduler.ScopingUnsupported(
                    f"process_type={process_type!r} cannot be scoped to a space: "
                    f"its handler has no trigger_{process_type}(space_id). "
                    f"Omit space_id to run it for every space.")

            # Fallback: call the handler's run()
            if hasattr(handler, "run") and callable(handler.run):
                return await handler.run()  # type: ignore[misc]
            return await handler()  # type: ignore[misc]
        finally:
            await self._lock_manager.release(process_type, lock_subtype)

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    async def _job_loop(self, job: _RegisteredJob) -> None:
        """Background loop for a single registered job."""
        # Initial jitter: wait a bit before first run to avoid thundering herd
        await asyncio.sleep(min(job.interval_seconds, 10.0))

        while self._running:
            try:
                await self._run_once(job)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("ProcessScheduler: unexpected error in '%s': %s", job.name, e, exc_info=True)

            # Sleep until next interval
            try:
                await asyncio.sleep(job.interval_seconds)
            except asyncio.CancelledError:
                break

    async def _run_once(self, job: _RegisteredJob) -> None:
        """Attempt to acquire lock and run a single job cycle."""
        acquired = await self._lock_manager.try_acquire(job.process_type, job.name)
        if not acquired:
            logger.debug(
                "ProcessScheduler: skipping '%s' — another instance holds the lock",
                job.name,
            )
            return

        start = time.monotonic()
        try:
            logger.debug("ProcessScheduler: running '%s'", job.name)
            if hasattr(job.handler, "run") and callable(job.handler.run):
                await job.handler.run()  # type: ignore[misc]
            else:
                await job.handler()  # type: ignore[misc]
            job.run_count += 1
            job.last_run = time.monotonic()
            job.last_error = None

            elapsed = (time.monotonic() - start) * 1000
            logger.debug("ProcessScheduler: '%s' completed in %.0fms", job.name, elapsed)

        except Exception as e:
            job.last_error = str(e)
            logger.error("ProcessScheduler: '%s' failed: %s", job.name, e, exc_info=True)

        finally:
            await self._lock_manager.release(job.process_type, job.name)

    # ------------------------------------------------------------------
    # Info
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Return scheduler and job status for monitoring."""
        return {
            "enabled": self._enabled,
            "running": self._running,
            "jobs": {
                name: {
                    "interval_seconds": j.interval_seconds,
                    "run_count": j.run_count,
                    "last_run": j.last_run,
                    "last_error": j.last_error,
                    "running": j.task is not None and not j.task.done() if j.task else False,
                }
                for name, j in self._jobs.items()
            },
            "active_locks": self._lock_manager.active_lock_count,
        }
