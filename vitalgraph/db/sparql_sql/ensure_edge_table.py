"""DDL helpers — ensure the edge table exists for query rewrites.

The edge table is a regular table maintained by app-level sync
(replacing the old edge_mv materialized view).
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Predicate URIs used in edge table population
EDGE_SOURCE_URI = "http://vital.ai/ontology/vital-core#hasEdgeSource"
EDGE_DEST_URI = "http://vital.ai/ontology/vital-core#hasEdgeDestination"


# Module-level cache: space_id → bool
_edge_table_ready: dict = {}    # True once table verified populated this process


async def ensure_edge_table(space_id: str, conn=None, conn_params=None) -> bool:
    """Ensure the edge table exists and is populated.  Returns True if usable.

    On first access per process:
    - Creates the table if it doesn't exist
    - Populates the table from rdf_quad if empty
    """
    if _edge_table_ready.get(space_id):
        return True

    from . import db_provider as db

    table_name = f"{space_id}_edge"
    quad_table = f"{space_id}_rdf_quad"
    term_table = f"{space_id}_term"

    try:
        # Check if edge table exists
        table_rows = await db.execute_query(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = %s",
            params=(table_name,), conn=conn, conn_params=conn_params,
        )

        if not table_rows:
            # Create the edge table + indexes
            logger.info("ensure_edge_table(%s): creating edge table", space_id)
            async with db.get_connection(params=conn_params) as c:
                await c.execute(f"""
                    CREATE TABLE IF NOT EXISTS {table_name} (
                        edge_uuid        UUID NOT NULL,
                        source_node_uuid UUID NOT NULL,
                        dest_node_uuid   UUID NOT NULL,
                        context_uuid     UUID NOT NULL,
                        PRIMARY KEY (edge_uuid, context_uuid)
                    )
                """)
                idx = f"idx_{space_id}_edge"
                await c.execute(f"CREATE INDEX IF NOT EXISTS {idx}_src_dst ON {table_name} (source_node_uuid, dest_node_uuid)")
                await c.execute(f"CREATE INDEX IF NOT EXISTS {idx}_dst_src ON {table_name} (dest_node_uuid, source_node_uuid)")
                await c.execute(f"CREATE INDEX IF NOT EXISTS {idx}_edge ON {table_name} (edge_uuid)")
                await c.execute(f"CREATE INDEX IF NOT EXISTS {idx}_ctx ON {table_name} (context_uuid)")
            logger.info("ensure_edge_table(%s): edge table created", space_id)

        # Check if table is empty and needs population
        count_rows = await db.execute_query(
            f"SELECT COUNT(*) AS cnt FROM {table_name}",
            conn=conn, conn_params=conn_params,
        )
        row_count = count_rows[0]["cnt"] if count_rows else 0

        if row_count == 0:
            # Populate from rdf_quad
            logger.info("ensure_edge_table(%s): populating edge table from rdf_quad", space_id)
            populate_sql = f"""
                INSERT INTO {table_name} (edge_uuid, source_node_uuid, dest_node_uuid, context_uuid)
                SELECT
                    src.subject_uuid,
                    src.object_uuid,
                    dst.object_uuid,
                    src.context_uuid
                FROM {quad_table} src
                JOIN {quad_table} dst
                    ON dst.subject_uuid = src.subject_uuid
                    AND dst.context_uuid = src.context_uuid
                WHERE src.predicate_uuid = (
                    SELECT term_uuid FROM {term_table}
                    WHERE term_text = '{EDGE_SOURCE_URI}' AND term_type = 'U' LIMIT 1
                )
                AND dst.predicate_uuid = (
                    SELECT term_uuid FROM {term_table}
                    WHERE term_text = '{EDGE_DEST_URI}' AND term_type = 'U' LIMIT 1
                )
                ON CONFLICT DO NOTHING
            """
            async with db.get_connection(params=conn_params) as c:
                await c.execute(populate_sql)
                await c.execute(f"ANALYZE {table_name}")

            # Re-check count
            count_rows = await db.execute_query(
                f"SELECT COUNT(*) AS cnt FROM {table_name}",
                conn=conn, conn_params=conn_params,
            )
            row_count = count_rows[0]["cnt"] if count_rows else 0
            logger.info("ensure_edge_table(%s): populated %d edge rows", space_id, row_count)

        _edge_table_ready[space_id] = True
        return True

    except Exception as e:
        logger.warning("ensure_edge_table(%s): failed: %s", space_id, e)
        _edge_table_ready[space_id] = False
        return False
