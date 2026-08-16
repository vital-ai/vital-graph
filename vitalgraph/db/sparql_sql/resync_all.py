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
    from .sync_value_stats import resync_value_stats
    from .generator import invalidate_stats_cache
    from .sparql_sql_schema import SparqlSQLSchema

    t = SparqlSQLSchema.get_table_names(space_id)

    # 1. Edge table (frame_entity depends on this)
    edge_count = await resync_edge_table(conn, space_id)

    # 2. Frame-entity table
    fe_count = await resync_frame_entity_table(conn, space_id)

    # 2b. Entity/slot sort table (issues/096). Also derived from edge, so it
    # follows it for the same reason frame_entity does. Tolerated missing: a
    # space created before this table exists must still resync everything else,
    # and `repair_derived_tables.py` / `migrate_space_schema.py` are what add it.
    ess_count = 0
    try:
        from .sync_entity_slot_sort import resync_entity_slot_sort
        ess_count = await resync_entity_slot_sort(conn, space_id)
    except Exception as exc:
        logger.warning("resync_all(%s): entity_slot_sort skipped (%s)",
                       space_id, exc)

    # 3. Stats tables
    stats = await resync_stats_tables(conn, space_id)
    # Value histograms: rdf_stats answers equality on a small value set,
    # this answers ranges over a large one (issues/090).
    try:
        vstats = await resync_value_stats(conn, space_id)
    except Exception as exc:
        # A space whose tables predate this must still resync everything
        # else; a missing histogram degrades an estimate, it does not
        # break a query.
        logger.warning('value stats resync skipped for %s: %s', space_id, exc)
        vstats = {'rows': 0}

    # 3b. Edge fan-out. After the edge table, which it reads, and recomputed in
    # full because fan-out is a structural property that moves slowly — making
    # it incremental would mean maintaining a distribution under every write.
    fanout_rows = 0
    try:
        from .sync_edge_fanout import compute_edge_fanout
        fanout_rows = await compute_edge_fanout(conn, space_id)
    except Exception as exc:
        # A space predating the table should not fail a resync over a statistic
        # that only affects plan choice.
        logger.warning("resync_all(%s): edge fan-out skipped (%s)",
                       space_id, exc)

    # 3b. Entity fan-out — the hub list. Same rationale as edge fan-out: a
    # periodic full rebuild, never incremental. It is also FAIL-SAFE, so a
    # failure here costs an optimisation and never an answer.
    entity_hubs = {}
    try:
        from .sync_entity_fanout import resync_entity_fanout
        entity_hubs = await resync_entity_fanout(conn, space_id)
    except Exception as exc:
        logger.warning("resync_all(%s): entity fan-out skipped (%s)",
                       space_id, exc)

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

    # 5. ANALYZE all space tables the space actually has.
    #
    # get_table_names() describes the current schema, but a space created by an
    # older version does not necessarily have every table in it. Failing the
    # whole resync because one optional table is absent leaves the derived
    # tables half-rebuilt, which is worse than skipping the ANALYZE — and the
    # caller has usually just finished a bulk load at that point.
    present = {r["tablename"] for r in await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
        "AND tablename = ANY($1)", list(t.values()))}
    missing = sorted(set(t.values()) - present)
    if missing:
        logger.info("resync(%s): skipping ANALYZE of %d table(s) this space "
                    "does not have: %s", space_id, len(missing),
                    ", ".join(missing))
    for table_name in sorted(present):
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
        'entity_slot_sort_rows': ess_count,
        'value_stats_rows': vstats.get('rows', 0),
        'pred_stats_rows': stats['pred_stats'],
        'quad_stats_rows': stats['quad_stats'],
        'edge_fanout_rows': fanout_rows,
        'entity_fanout_rows': sum(entity_hubs.values()) if entity_hubs else 0,
        'geo_points': geo_points,
    }
    logger.info("resync_all_auxiliary_tables(%s): %s", space_id, result)
    return result
