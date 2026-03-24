"""Bulk resync of all auxiliary tables for a space.

Call after bulk loads, disaster recovery, or manual DB edits.
Rebuilds edge, frame_entity, and stats tables from scratch,
runs ANALYZE on all space tables, and invalidates the stats cache.
"""

from __future__ import annotations

import logging
from typing import Dict

logger = logging.getLogger(__name__)


async def resync_all_auxiliary_tables(conn, space_id: str) -> Dict[str, int]:
    """Full resync of all auxiliary tables + ANALYZE.  Call after bulk loads.

    Must be called with a connection (not inside a transaction, since
    TRUNCATE + bulk INSERT benefits from autocommit or a wrapping txn
    managed by the caller).

    Returns dict with row counts for each table.
    """
    from .sync_edge_table import resync_edge_table
    from .sync_frame_entity_table import resync_frame_entity_table
    from .sync_stats_tables import resync_stats_tables
    from .generator import invalidate_stats_cache
    from .sparql_sql_schema import SparqlSQLSchema

    t = SparqlSQLSchema.get_table_names(space_id)

    # 1. Edge table (frame_entity depends on this)
    edge_count = await resync_edge_table(conn, space_id)

    # 2. Frame-entity table
    fe_count = await resync_frame_entity_table(conn, space_id)

    # 3. Stats tables
    stats = await resync_stats_tables(conn, space_id)

    # 4. ANALYZE all space tables
    for table_name in t.values():
        await conn.execute(f"ANALYZE {table_name}")

    # 5. Invalidate in-memory stats cache + reset change counter
    invalidate_stats_cache(space_id)
    from .auto_analyze import reset_counter
    reset_counter(space_id)

    # 6. Notify other instances to invalidate their stats cache
    try:
        from . import db_provider as _db
        impl = _db._impl
        sm = impl.get_signal_manager() if impl and hasattr(impl, 'get_signal_manager') else None
        if sm:
            await sm.notify_cache_invalidate("stats", space_id)
    except Exception as e:
        logger.debug("Stats cache invalidation notify failed (non-critical): %s", e)

    result = {
        'edge_rows': edge_count,
        'frame_entity_rows': fe_count,
        'pred_stats_rows': stats['pred_stats'],
        'quad_stats_rows': stats['quad_stats'],
    }
    logger.info("resync_all_auxiliary_tables(%s): %s", space_id, result)
    return result
