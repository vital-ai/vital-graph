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

    # 4. Geo table — extract lat/lon from existing quads
    geo_points = 0
    try:
        from ...vectorization.geo_populator import populate_geo
        # List all graphs in the space
        graph_rows = await conn.fetch(
            "SELECT graph_uri FROM graph WHERE space_id = $1", space_id,
        )
        term_table = t.get('term', f"{space_id}_term")
        for gr in graph_rows:
            graph_uri = gr["graph_uri"]
            # Resolve graph URI to context_uuid
            ctx_row = await conn.fetchrow(
                f"SELECT term_uuid FROM {term_table} "
                f"WHERE term_text = $1 AND term_type = 'U' LIMIT 1",
                graph_uri,
            )
            if ctx_row:
                geo_stats = await populate_geo(conn, space_id, ctx_row["term_uuid"])
                geo_points += geo_stats.points_upserted
        logger.info("resync geo(%s): %d points upserted across %d graphs",
                     space_id, geo_points, len(graph_rows))
    except Exception as e:
        logger.warning("Geo resync failed (non-critical): %s", e)

    # 5. ANALYZE all space tables
    for table_name in t.values():
        await conn.execute(f"ANALYZE {table_name}")

    # 6. Invalidate in-memory stats cache + reset change counter
    invalidate_stats_cache(space_id)
    from .auto_analyze import reset_counter
    reset_counter(space_id)

    # 7. Notify other instances to invalidate their stats cache
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
        'geo_points': geo_points,
    }
    logger.info("resync_all_auxiliary_tables(%s): %s", space_id, result)
    return result
