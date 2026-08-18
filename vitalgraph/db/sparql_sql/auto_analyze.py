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

    conn = psycopg.connect(
        host=require(pg_config, 'host'),
        port=require(pg_config, 'port'),
        dbname=require(pg_config, 'database'),
        user=require(pg_config, 'username'),
        password=require(pg_config, 'password'),
        autocommit=True,
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
        f"{space_id}_frame_entity",
        f"{space_id}_rdf_pred_stats",
        f"{space_id}_rdf_stats",
        f"{space_id}_datatype",
    ]
    try:
        if pg_config:
            await asyncio.to_thread(_sync_analyze, tables, pg_config)
        else:
            for tbl in tables:
                await conn.execute(f"ANALYZE {tbl}")
        _change_counts[space_id] = 0
        _last_analyze_time[space_id] = time.monotonic()
        logger.debug("auto_analyze(%s): ANALYZE %d tables after %d row changes", space_id, len(tables), count)
        return True
    except Exception as e:
        logger.warning("auto_analyze(%s): ANALYZE failed: %s", space_id, e)
        return False


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
