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
import os
import time
import logging
import weakref
from enum import Enum
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

# Log any acquire that WAITS this long but still succeeds.
#
# Timing out was already logged; waiting 40 seconds and then succeeding was
# not, and that is the case that actually reached production. A single
# `GET kgentities` was measured at 39.972s while the calls either side of it,
# same endpoint and same client process, took 0.020-0.092s. Nothing in any log
# attributed it, because the only pool diagnostic fired on TimeoutError.
#
# A slow success and a timeout are the same starvation; only one of them was
# visible.
#
# OVERRIDABLE because 1.0s is an alerting threshold, not a measuring
# instrument. A local bulkhead run at a 5-connection pool produced p99 read
# latency of 1152ms with ZERO `pool_wait` records: the queueing was real and
# every individual acquire came in under a second, so the counter said "no
# contention" about a run that was visibly contended. Set
# VG_SLOW_ACQUIRE_SECONDS low (e.g. 0.05) to see the distribution rather than
# the tail.
SLOW_ACQUIRE_SECONDS = float(os.environ.get("VG_SLOW_ACQUIRE_SECONDS", "1.0"))


# ---------------------------------------------------------------------------
# Workload classes (`issues/231`)
# ---------------------------------------------------------------------------
#
# Three kinds of work reach PostgreSQL and they want different guarantees:
#
#   QUERY     read-only, request-driven, latency-sensitive. Must never starve.
#   MUTATION  request-driven writes. Bursty, holds locks.
#   INTERNAL  background: ANALYZE, VACUUM, backfill, segmentation, auto-sync.
#             Always deferrable; nothing waits on it interactively.
#
# SEPARATE POOLS, NOT A SHARED LIMITER (decided 2026-09-24). A pool per class is
# legible: its size is a number in config, its exhaustion is attributable to one
# class, and it cannot lend a reader's connection to a bulk writer by accident.
# The accepted cost is a static partition — QUERY can wait while INTERNAL sits
# idle — and `_WaitRecord` below exists to measure exactly that cost, so the
# decision can be revisited on evidence rather than taste.


class PoolClass(str, Enum):
    QUERY = "query"
    MUTATION = "mutation"
    INTERNAL = "internal"

    # The shared request pool, BEFORE query and mutation are split apart
    # (`issues/231` step 3, not yet done). It is its own class rather than
    # being labelled QUERY because labelling it QUERY would file every
    # mutation's wait as a query wait — and the whole reason this record
    # exists is to decide, from the data, whether readers are being starved.
    # Mislabelling the mixed pool would answer that question wrongly and
    # invisibly. When the split lands, this disappears.
    REQUEST = "request"


# Every live classed pool, so a waiter can ask what the OTHER classes were
# doing at the instant it began waiting. Weak refs: a closed pool must not be
# kept alive by this, and a stale entry would corrupt the one number this whole
# mechanism exists to produce.
_REGISTRY: "weakref.WeakValueDictionary[str, TimeoutPool]" = weakref.WeakValueDictionary()


def register_pool(pool: "TimeoutPool", pool_class: PoolClass) -> None:
    pool.pool_class = pool_class
    _REGISTRY[pool_class.value] = pool


def other_classes_idle(exclude: Optional[PoolClass]) -> int:
    """Free connections across every class EXCEPT `exclude`, right now.

    THE POINT OF THE WHOLE RECORD. This is the capacity a shared limiter could
    have lent to a waiter, and it is only meaningful read at the instant of the
    wait. Per-pool metrics gathered independently cannot answer the question —
    "QUERY waited 12s" and "INTERNAL averaged 30% utilisation" say nothing
    about whether the two overlapped.
    """
    total = 0
    for name, pool in list(_REGISTRY.items()):
        if exclude is not None and name == exclude.value:
            continue
        try:
            total += max(0, pool.get_max_size() - (pool.get_size() - pool.get_idle_size()))
        except Exception:
            continue    # diagnostics must never mask the real path
    return total


# Whether the INTERNAL/REQUEST conflation has already been reported. One line per
# process, not per acquire: this is a misconfiguration, and repeating it on every
# background job would bury the rest of the log.
_internal_fallback_reported = False


def internal_pool_for(db_impl):
    """The pool DEFERRABLE background work must use, and nothing else.

    WHY THIS IS A FUNCTION AND NOT `getattr(db_impl, 'internal_pool', None) or
    pool`. That expression conflates two situations that need opposite
    treatment, and the conflation is silent:

      * **Deliberately disabled** (`internal_pool_size=0`). Running background
        work on the request pool is exactly what the operator asked for. The
        choice is already logged at WARNING when the pool is not created.
      * **Missing when it should exist.** A programming error — and papering over
        it puts ANALYZE, VACUUM and auto-sync back on the connections readers
        need, which is the 2026-09-24 outage configuration. Reached silently,
        nothing distinguishes it from a working bulkhead.

    So the deliberate case returns the request pool quietly, and the accidental
    case says so at ERROR. It still RETURNS the request pool rather than raising:
    background work that cannot run is a stale-statistics problem, but a
    `connect()` path that raises here would take down the write path to protect
    the read path, which is the wrong trade at startup.
    """
    global _internal_fallback_reported
    internal = getattr(db_impl, 'internal_pool', None)
    if internal is not None:
        return internal

    request = getattr(db_impl, 'connection_pool', None)
    if getattr(db_impl, 'internal_pool_disabled', False):
        return request        # the operator's choice, already warned about

    if not _internal_fallback_reported:
        _internal_fallback_reported = True
        logger.error(
            "INTERNAL pool is absent but was NOT disabled — background work is "
            "falling back to the REQUEST pool. That is the configuration that "
            "exhausted the pool on 2026-09-24 (`issues/231`); ANALYZE, VACUUM, "
            "auto-sync and the scheduled jobs are now competing with request "
            "serving. Check that connect() created the internal pool."
        )
    return request


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

    def _report_slow(self, waited: float, other_idle: Optional[int] = None) -> None:
        """A slow-but-successful acquire is starvation that nothing else logs.

        ON WAITS ONLY. The fast path must not pay for this: an acquire that
        does not queue writes nothing, computes nothing, and touches no sibling
        pool.
        """
        if waited < SLOW_ACQUIRE_SECONDS:
            return
        cls = getattr(self._pool, "pool_class", None)
        try:
            in_use = self._pool.get_size() - self._pool.get_idle_size()
            # `pool_wait` is the structured record `issues/231` specifies. One
            # line per WAIT, carrying what the other classes had free at the
            # moment this wait began — the number that decides whether the
            # static partition is costing anything.
            logger.warning(
                "pool_wait %s",
                {
                    "class": cls.value if cls else "unclassed",
                    "waited_ms": round(waited * 1000),
                    "in_use": in_use,
                    "size": self._pool.get_max_size(),
                    "other_classes_idle": other_idle,
                },
            )
        except Exception:   # diagnostics must never mask the real path
            logger.warning("pool acquire WAITED %.2fs (state unavailable)", waited)

    async def __aenter__(self):
        t0 = time.monotonic()
        # Read the siblings BEFORE waiting. Read afterwards it describes the
        # world at the moment the wait ENDED — by which time the capacity that
        # would have answered the question has usually been handed over.
        other_idle = self._sibling_idle()
        try:
            conn = await self._ctx.__aenter__()
        except asyncio.TimeoutError:
            log_pool_state(self._pool, "acquire timed out")
            raise
        self._report_slow(time.monotonic() - t0, other_idle)
        return conn

    def _sibling_idle(self):
        cls = getattr(self._pool, "pool_class", None)
        if cls is None:
            return None
        try:
            return other_classes_idle(cls)
        except Exception:
            return None

    async def __aexit__(self, *exc_info):
        return await self._ctx.__aexit__(*exc_info)

    def __await__(self):
        t0 = time.monotonic()
        other_idle = self._sibling_idle()
        try:
            conn = yield from self._ctx.__await__()
        except asyncio.TimeoutError:
            log_pool_state(self._pool, "acquire timed out")
            raise
        self._report_slow(time.monotonic() - t0, other_idle)
        return conn


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
