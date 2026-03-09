"""Per-space row-change counter and automatic ANALYZE trigger.

Tracks how many quad rows have been inserted or deleted since the last
ANALYZE.  When the threshold is reached, runs ANALYZE on the main
rdf_quad table and resets the counter.

This keeps PostgreSQL planner statistics fresh without requiring manual
intervention or periodic cron jobs.
"""

from __future__ import annotations

import logging
from typing import Dict

logger = logging.getLogger(__name__)

# Per-space counters: space_id → number of rows changed since last ANALYZE
_change_counts: Dict[str, int] = {}

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
    """Run ANALYZE on rdf_quad if the change count exceeds the threshold.

    Returns True if ANALYZE was run, False otherwise.
    Must be called with a connection NOT inside a transaction (ANALYZE
    cannot run inside a transaction in some configurations).
    """
    count = _change_counts.get(space_id, 0)
    if count < threshold:
        return False

    t_quad = f"{space_id}_rdf_quad"
    try:
        await conn.execute(f"ANALYZE {t_quad}")
        _change_counts[space_id] = 0
        logger.debug("auto_analyze(%s): ANALYZE after %d row changes", space_id, count)
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
