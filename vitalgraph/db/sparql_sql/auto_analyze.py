"""Per-space row-change counter and automatic ANALYZE trigger.

Tracks how many quad rows have been inserted or deleted since the last
ANALYZE.  When the threshold is reached, runs ANALYZE on all per-space
tables and resets the counter.

This keeps PostgreSQL planner statistics fresh without requiring manual
intervention or periodic cron jobs.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
from ..connection_config import require
from ...utils.background import BackgroundTasks

logger = logging.getLogger(__name__)

# Per-space counters: space_id → number of rows changed since last ANALYZE
_change_counts: Dict[str, int] = {}

# Per-space timestamp of the last ANALYZE run (monotonic seconds)
_last_analyze_time: Dict[str, float] = {}

# Default threshold: ANALYZE after this many row changes
DEFAULT_ANALYZE_THRESHOLD = 50000

# --- Per-write ANALYZE guard tiers -----------------------------------------
# Tier 0: in-process fast path. Cheap short-circuit that avoids a catalog
# roundtrip on the hot write path.
ANALYZE_LOCAL_GUARD_SECONDS = 60.0
# Tier 1: shared minimum interval, enforced via pg_stat_user_tables.last_analyze
# so the guard holds across workers and ECS tasks (the in-process dict does not:
# with N processes the old 10s guard permitted N ANALYZEs per 10s, and every task
# restart reset it).
ANALYZE_MIN_INTERVAL = 900.0


async def fetch_last_analyze_age(conn, table: str) -> Optional[float]:
    """Seconds since *table* was last ANALYZEd, or None if it never has been.

    Reads ``pg_stat_user_tables``, which PostgreSQL maintains globally — so this
    is shared across processes and survives restarts, unlike the in-process
    ``_last_analyze_time`` dict.

    Takes ``GREATEST(last_analyze, last_autoanalyze)`` so autovacuum's work
    counts; otherwise we re-analyze on top of it. Filters on ``relid`` rather
    than a ``relname LIKE`` pattern so this is a single-row lookup.
    """
    try:
        row = await conn.fetchrow(
            "SELECT extract(epoch FROM now() - GREATEST("
            "    COALESCE(last_analyze,     'epoch'::timestamptz),"
            "    COALESCE(last_autoanalyze, 'epoch'::timestamptz))) AS age "
            "FROM pg_stat_user_tables WHERE relid = $1::regclass",
            table,
        )
    except Exception as e:
        # Never let the guard's own failure block the write path.
        logger.debug("fetch_last_analyze_age(%s) failed: %s", table, e)
        return None
    if row is None or row['age'] is None:
        return None
    return float(row['age'])


def record_changes(space_id: str, row_count: int) -> None:
    """Record that row_count rows were inserted or deleted."""
    _change_counts[space_id] = _change_counts.get(space_id, 0) + row_count


def _sync_analyze(tables: List[str], pg_config: Dict[str, Any]) -> int:
    """Run ANALYZE on tables via a short-lived psycopg sync connection.

    Designed to be called via ``asyncio.to_thread()`` so the event loop
    is never blocked.
    """
    import psycopg
    from psycopg import sql as psql

    # Same reason as `maintenance_job.maintenance_conn_options` — a fresh
    # connection is not a fresh CONFIGURATION, and a deployment-level
    # `statement_timeout` is inherited here too. Imported rather than
    # duplicated so the two cannot drift.
    from ...process.maintenance_job import maintenance_conn_options
    conn = psycopg.connect(
        host=require(pg_config, 'host'),
        port=require(pg_config, 'port'),
        dbname=require(pg_config, 'database'),
        user=require(pg_config, 'username'),
        password=require(pg_config, 'password'),
        autocommit=True,
        options=maintenance_conn_options(),
    )
    completed = 0
    try:
        for table in tables:
            try:
                conn.execute(psql.SQL("ANALYZE {}").format(psql.Identifier(table)))
                completed += 1
            except Exception as e:
                logger.warning("ANALYZE %s failed: %s", table, e)
    finally:
        conn.close()
    return completed


async def maybe_analyze(
    conn,
    space_id: str,
    threshold: int = DEFAULT_ANALYZE_THRESHOLD,
    *,
    pg_config: Optional[Dict[str, Any]] = None,
) -> bool:
    """Run ANALYZE on all per-space tables if the change count exceeds the threshold.

    Returns True if ANALYZE was run, False otherwise.

    When *pg_config* is provided, ANALYZE runs in a background thread via
    a psycopg sync connection so the asyncio event loop is never blocked.
    Otherwise falls back to the provided asyncpg *conn*.
    """
    count = _change_counts.get(space_id, 0)
    if count < threshold:
        return False

    tables = [
        f"{space_id}_rdf_quad",
        f"{space_id}_term",
        f"{space_id}_edge",
        f"{space_id}_frame_slot",
        f"{space_id}_rdf_pred_stats",
        f"{space_id}_rdf_stats",
        f"{space_id}_datatype",
    ]
    # NON-BLOCKING EXCLUSION, AND SKIP RATHER THAN QUEUE (`issues/230`).
    #
    # ANALYZE takes a ShareUpdateExclusiveLock, which CONFLICTS WITH ITSELF, so
    # concurrent ANALYZE on one table is strictly serial. The threshold above
    # was the only guard this function had, and `_change_counts` was reset only
    # when the ANALYZE COMPLETED -- so every writer in a burst read the same
    # over-threshold count, every one started an ANALYZE, and they queued one at
    # a time while each held a pooled connection.
    #
    # Measured in production: six `ANALYZE "{space}_term"` stacked on each
    # other, the connection pool exhausted behind them, ordinary queries going
    # from 0.22s to over 50s. Sampling `pg_locks` through it showed 1,599
    # ungranted ShareUpdateExclusiveLock and nothing else.
    #
    # WAITING IS STRICTLY WORSE THAN NOT ANALYSING: the statistics a waiter
    # would produce are the ones the holder is already producing.
    #
    # Same key as `ProcessLockManager`'s ('analyze', space_id), deliberately, so
    # this and `_maybe_analyze_aux_tables` -- which already had this tier --
    # exclude EACH OTHER rather than each holding a private lock.
    from ...process.process_lock_manager import process_lock_key
    lock_key = process_lock_key("analyze", space_id)
    try:
        got = await conn.fetchval("SELECT pg_try_advisory_lock($1)", lock_key)
    except Exception as e:
        # The guard's own failure must not block the write path.
        logger.debug("auto_analyze(%s): lock probe failed: %s", space_id, e)
        got = True
    if not got:
        logger.debug("auto_analyze(%s): skipped, another ANALYZE holds the lock",
                     space_id)
        return False

    # RESET BEFORE, NOT AFTER. Leaving the counter over threshold for the whole
    # run is what let the next caller through to queue behind this one.
    _change_counts[space_id] = 0

    try:
        if pg_config:
            await asyncio.to_thread(_sync_analyze, tables, pg_config)
        else:
            for tbl in tables:
                await conn.execute(f"ANALYZE {tbl}")
        _last_analyze_time[space_id] = time.monotonic()
        logger.debug("auto_analyze(%s): ANALYZE %d tables after %d row changes", space_id, len(tables), count)
        return True
    except Exception as e:
        logger.warning("auto_analyze(%s): ANALYZE failed: %s", space_id, e)
        return False
    finally:
        # ALWAYS, and on this connection. A session-scoped advisory lock left
        # held on a pooled connection outlives the request and blocks every
        # later ANALYZE for that space until the connection is recycled.
        try:
            await conn.fetchval("SELECT pg_advisory_unlock($1)", lock_key)
        except Exception as e:
            logger.warning("auto_analyze(%s): advisory unlock failed: %s",
                           space_id, e)


def reset_counter(space_id: str) -> None:
    """Reset the change counter for a space (e.g. after resync_all)."""
    _change_counts.pop(space_id, None)


def get_counter(space_id: str) -> int:
    """Get the current change count for a space."""
    return _change_counts.get(space_id, 0)


def was_analyzed_recently(space_id: str, max_age_seconds: float = 10.0) -> bool:
    """Return True if ANALYZE was run for this space within the last *max_age_seconds*."""
    last = _last_analyze_time.get(space_id)
    if last is None:
        return False
    return (time.monotonic() - last) < max_age_seconds


def set_last_analyze_time(space_id: str) -> None:
    """Manually mark that ANALYZE was just run for this space."""
    _last_analyze_time[space_id] = time.monotonic()


def get_last_analyze_time(space_id: str) -> Optional[float]:
    """Return the monotonic timestamp of the last ANALYZE, or None."""
    return _last_analyze_time.get(space_id)


# ---------------------------------------------------------------------------
# Fire-and-forget scheduling (`issues/253`)
# ---------------------------------------------------------------------------
#
# WHY NO WRITE MAY AWAIT THIS. Three call sites used to do
#
#     async with self._db._internal_pool.acquire() as conn:
#         await maybe_analyze(conn, space_id, pg_config=...)
#
# under a comment saying "outside transaction" — which held only when the
# enclosing function opened its own transaction. Every caller that passes
# `connection=` (the frame-write path always does) still had its WRITE
# TRANSACTION OPEN around it, so the write's session sat IDLE IN TRANSACTION for
# the whole ANALYZE.
#
# Measured on production 2026-09-30: those ANALYZEs run **60-98 seconds each** on
# `rdf_quad` and `term`, back to back, while
# `idle_in_transaction_session_timeout` is 60 s. PostgreSQL terminated the
# write's connection, the ANALYZE finished, the write resumed one to two seconds
# later and died in its rollback. **Five confirmed lost writes in one day**, and
# the database log matches it 4 for 4 in the hour examined: every
# idle-in-transaction FATAL falls inside an ANALYZE window.
#
# So this is scheduled, never awaited. A request must not wait on deferrable
# maintenance even when it holds no transaction — one to three minutes added to a
# user's write is its own defect.
#
# THE THRESHOLD IS CHECKED BEFORE ANYTHING IS ACQUIRED. `maybe_analyze` tests it
# after being handed a connection, so the old shape paid an internal-pool
# acquisition on EVERY write to discover there was nothing to do. At a 50,000-row
# threshold that is almost every write.

# Scheduling lives in `utils.background`: a strong reference is required, because
# a task referenced by nothing can be garbage-collected mid-ANALYZE, and the
# exception has to be logged because nothing awaits it. Shared rather than
# re-implemented — `kg_backend_utils` schedules the aux-table ANALYZE the same
# way, and this bookkeeping is exactly where fire-and-forget goes wrong.
_TASKS = BackgroundTasks("auto_analyze")


def changes_pending(space_id: str,
                    threshold: int = DEFAULT_ANALYZE_THRESHOLD) -> bool:
    """Whether enough rows have changed to be worth an ANALYZE.

    In-process and free — no connection, no catalogue read. This is the guard
    that keeps the common write off the scheduling path entirely.
    """
    return _change_counts.get(space_id, 0) >= threshold


def schedule_maybe_analyze(db_impl, space_id: str, *,
                           pg_config: Optional[Dict[str, Any]] = None,
                           threshold: int = DEFAULT_ANALYZE_THRESHOLD):
    """Schedule `maybe_analyze` in the background. NEVER awaited by a write.

    Returns the task, or None when there is nothing to do, no event loop, or no
    pool to use. `maybe_analyze` re-checks the threshold and takes a
    non-blocking advisory lock of its own, so a duplicate schedule is harmless.
    """
    if not changes_pending(space_id, threshold):
        return None

    from ..pool import internal_pool_for
    # `internal_pool_for`, not `db_impl._internal_pool`: it distinguishes an
    # internal pool that is absent ON PURPOSE from one that is missing by
    # accident, and returns the request pool rather than raising. Reaching for
    # the attribute directly would turn a configuration choice into an
    # AttributeError on a background path nobody is watching.
    pool = internal_pool_for(db_impl)
    if pool is None:
        logger.debug("auto_analyze(%s): no pool available, skipping", space_id)
        return None

    async def _run() -> None:
        async with pool.acquire() as conn:
            await maybe_analyze(conn, space_id, threshold, pg_config=pg_config)

    return _TASKS.schedule(_run(), key=space_id)
