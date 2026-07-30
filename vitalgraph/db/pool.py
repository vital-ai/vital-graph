"""asyncpg connection pool with a default acquire timeout.

asyncpg's ``Pool.acquire()`` waits **indefinitely** when the pool is exhausted.
In production that turned connection starvation into silent multi-minute stalls:
``batch_exists_check`` — a 30 ms primary-key lookup — was observed queueing for a
median of 178s and a maximum of 1,779s, because every caller simply waited its
turn behind an under-sized pool with no upper bound on the wait.

A default acquire timeout converts that failure mode from "hang until the client
gives up and retries, adding more load" into a prompt, visible
``asyncio.TimeoutError``.

``TimeoutPool`` sets the default; individual call sites can still pass an
explicit ``timeout=`` to override it (including ``timeout=None`` for the rare
operation that genuinely should wait, e.g. long-running maintenance).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import asyncpg
from asyncpg import protocol
from asyncpg.connection import Connection

logger = logging.getLogger(__name__)

# Default seconds to wait for a free connection before raising asyncio.TimeoutError.
# Keep this comfortably below the API client's own timeout so the server surfaces
# the failure first, rather than the client timing out and retrying blind.
DEFAULT_ACQUIRE_TIMEOUT = 15.0

# Sentinel distinguishing "caller said nothing" from an explicit timeout=None,
# which is a legitimate request to wait indefinitely.
_UNSET: object = object()


class _LoggingAcquireContext:
    """Wraps asyncpg's PoolAcquireContext to log pool state on timeout.

    Supports both usages asyncpg allows::

        async with pool.acquire() as conn: ...
        conn = await pool.acquire()
    """

    __slots__ = ('_pool', '_ctx')

    def __init__(self, pool: 'TimeoutPool', ctx):
        self._pool = pool
        self._ctx = ctx

    async def __aenter__(self):
        try:
            return await self._ctx.__aenter__()
        except asyncio.TimeoutError:
            log_pool_state(self._pool, "acquire timed out")
            raise

    async def __aexit__(self, *exc_info):
        return await self._ctx.__aexit__(*exc_info)

    def __await__(self):
        try:
            return (yield from self._ctx.__await__())
        except asyncio.TimeoutError:
            log_pool_state(self._pool, "acquire timed out")
            raise


class TimeoutPool(asyncpg.pool.Pool):
    """An ``asyncpg.Pool`` that applies a default timeout to ``acquire()``."""

    def __init__(self, *connect_args, acquire_timeout: Optional[float] = None, **kwargs):
        super().__init__(*connect_args, **kwargs)
        self._acquire_timeout = acquire_timeout

    def acquire(self, *, timeout=_UNSET):
        """Acquire a connection, applying the pool's default timeout.

        Pass an explicit ``timeout`` (including ``None``) to override.
        """
        if timeout is _UNSET:
            timeout = self._acquire_timeout
        return _LoggingAcquireContext(self, super().acquire(timeout=timeout))

    @property
    def acquire_timeout(self) -> Optional[float]:
        return self._acquire_timeout


async def create_pool(
    dsn=None,
    *,
    min_size=10,
    max_size=10,
    max_queries=50000,
    max_inactive_connection_lifetime=300.0,
    connect=None,
    setup=None,
    init=None,
    reset=None,
    loop=None,
    connection_class=Connection,
    record_class=protocol.Record,
    acquire_timeout: Optional[float] = DEFAULT_ACQUIRE_TIMEOUT,
    **connect_kwargs,
) -> TimeoutPool:
    """Drop-in replacement for ``asyncpg.create_pool`` returning a ``TimeoutPool``.

    Mirrors asyncpg's own defaults; adds *acquire_timeout*.
    """
    pool = TimeoutPool(
        dsn,
        connection_class=connection_class,
        record_class=record_class,
        min_size=min_size,
        max_size=max_size,
        max_queries=max_queries,
        loop=loop,
        connect=connect,
        setup=setup,
        init=init,
        reset=reset,
        max_inactive_connection_lifetime=max_inactive_connection_lifetime,
        acquire_timeout=acquire_timeout,
        **connect_kwargs,
    )
    return await pool


# Fraction of max_size in use above which periodic monitoring escalates to WARNING.
POOL_PRESSURE_THRESHOLD = 0.8
# How often the monitor samples. Long enough to be cheap, short enough to catch a
# burst that would otherwise only show up as a downstream timeout.
POOL_MONITOR_INTERVAL = 60.0


async def _monitor_pool(pool: asyncpg.Pool, interval: float, threshold: float) -> None:
    """Periodically sample pool occupancy; escalate to WARNING under pressure.

    Deliberately quiet at steady state (DEBUG) so this can run always-on. It exists
    because pool exhaustion previously had no direct signal at all — it surfaced only
    as unexplained multi-minute latency in unrelated call paths.

    Tracks a high-water mark so a brief burst between samples is still reported
    rather than being averaged away.
    """
    high_water = 0
    try:
        while True:
            await asyncio.sleep(interval)
            try:
                size, idle = pool.get_size(), pool.get_idle_size()
                max_size = pool.get_max_size()
                in_use = size - idle
                high_water = max(high_water, in_use)
                saturated = max_size > 0 and (in_use / max_size) >= threshold
                logger.log(
                    logging.WARNING if saturated else logging.DEBUG,
                    "pool: in_use=%s/%s idle=%s size=%s high_water=%s%s",
                    in_use, max_size, idle, size, high_water,
                    " — near capacity, acquires may start timing out" if saturated else "",
                )
            except Exception as e:  # never let monitoring kill the pool
                logger.debug("pool monitor sample failed: %s", e)
    except asyncio.CancelledError:
        logger.debug("pool monitor stopped (high_water=%s)", high_water)
        raise


def start_pool_monitor(
    pool: asyncpg.Pool,
    interval: float = POOL_MONITOR_INTERVAL,
    threshold: float = POOL_PRESSURE_THRESHOLD,
) -> "asyncio.Task":
    """Start periodic pool-state logging. Cancel the returned task to stop.

    Per-process by design: every task has its own pool with its own occupancy, so
    this must NOT be routed through ProcessScheduler, which advisory-locks a job to
    a single instance.
    """
    return asyncio.create_task(_monitor_pool(pool, interval, threshold))


def log_pool_state(pool: asyncpg.Pool, context: str = "") -> None:
    """Log pool occupancy — call this when an acquire times out.

    Pool starvation was originally only diagnosable by noticing a 6,000x gap
    between an application timer and the SQL it wrapped; this makes it explicit.
    """
    try:
        logger.warning(
            "pool state%s: size=%s idle=%s min=%s max=%s",
            f" ({context})" if context else "",
            pool.get_size(), pool.get_idle_size(),
            pool.get_min_size(), pool.get_max_size(),
        )
    except Exception:  # pragma: no cover - diagnostics must never mask the real error
        logger.warning("pool state unavailable%s", f" ({context})" if context else "")
