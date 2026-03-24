"""Per-space row-change counter and automatic ANALYZE trigger.

Tracks how many quad rows have been inserted or deleted since the last
ANALYZE.  When the threshold is reached, runs ANALYZE on all per-space
tables and resets the counter.

This keeps PostgreSQL planner statistics fresh without requiring manual
intervention or periodic cron jobs.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Per-space counters: space_id → number of rows changed since last ANALYZE
_change_counts: Dict[str, int] = {}

# Per-space timestamp of the last ANALYZE run (monotonic seconds)
_last_analyze_time: Dict[str, float] = {}

# Default threshold: ANALYZE after this many row changes
DEFAULT_ANALYZE_THRESHOLD = 1000


def record_changes(space_id: str, row_count: int) -> None:
    """Record that row_count rows were inserted or deleted."""
    _change_counts[space_id] = _change_counts.get(space_id, 0) + row_count


async def maybe_analyze(
    conn,
    space_id: str,
    threshold: int = DEFAULT_ANALYZE_THRESHOLD,
) -> bool:
    """Run ANALYZE on all per-space tables if the change count exceeds the threshold.

    Returns True if ANALYZE was run, False otherwise.
    Must be called with a connection NOT inside a transaction (ANALYZE
    cannot run inside a transaction in some configurations).
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
