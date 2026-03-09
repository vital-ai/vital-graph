"""DDL helper — ensure the frame_entity table exists for query rewrites.

The frame-entity table maps frames to their source/destination entities.
It depends on the edge table as a prerequisite.
Replaces the old frame_entity_mv materialized view.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

SLOT_TYPE_URI = "http://vital.ai/ontology/haley-ai-kg#hasKGSlotType"
SLOT_VALUE_URI = "http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue"
SOURCE_ENTITY_URI = "urn:hasSourceEntity"
DEST_ENTITY_URI = "urn:hasDestinationEntity"

# Module-level cache: space_id → bool
_frame_entity_table_ready: dict = {}


async def ensure_frame_entity_table(space_id: str, conn=None, conn_params=None) -> bool:
    """Ensure the frame_entity table exists and is populated.  Returns True if usable.

    On first access per process:
    - Drops any legacy frame_entity_mv materialized view
    - Creates the table if it doesn't exist
    - Populates the table from edge + rdf_quad if empty
    """
    if _frame_entity_table_ready.get(space_id):
        return True

    from . import db_provider as db

    table_name = f"{space_id}_frame_entity"
    edge_table_name = f"{space_id}_edge"
    quad_table = f"{space_id}_rdf_quad"
    term_table = f"{space_id}_term"

    try:
        # Check if edge table exists (prerequisite)
        edge_rows = await db.execute_query(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = %s",
            params=(edge_table_name,), conn=conn, conn_params=conn_params,
        )
        if not edge_rows:
            logger.info("ensure_frame_entity_table(%s): edge table missing, skipping", space_id)
            return False

        # Check if frame_entity table exists
        table_rows = await db.execute_query(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = %s",
            params=(table_name,), conn=conn, conn_params=conn_params,
        )

        if not table_rows:
            logger.info("ensure_frame_entity_table(%s): creating table", space_id)
            async with db.get_connection(params=conn_params) as c:
                await c.execute(f"""
                    CREATE TABLE IF NOT EXISTS {table_name} (
                        frame_uuid           UUID NOT NULL,
                        source_entity_uuid   UUID,
                        dest_entity_uuid     UUID,
                        context_uuid         UUID NOT NULL,
                        PRIMARY KEY (frame_uuid, context_uuid)
                    )
                """)
                idx = f"idx_{space_id}_fe"
                await c.execute(f"CREATE INDEX IF NOT EXISTS {idx}_src_frame ON {table_name} (source_entity_uuid, frame_uuid)")
                await c.execute(f"CREATE INDEX IF NOT EXISTS {idx}_dst_frame ON {table_name} (dest_entity_uuid, frame_uuid)")
                await c.execute(f"CREATE INDEX IF NOT EXISTS {idx}_frame ON {table_name} (frame_uuid)")
                await c.execute(f"CREATE INDEX IF NOT EXISTS {idx}_ctx ON {table_name} (context_uuid)")
            logger.info("ensure_frame_entity_table(%s): table created", space_id)

        # Check if table is empty and needs population
        count_rows = await db.execute_query(
            f"SELECT COUNT(*) AS cnt FROM {table_name}",
            conn=conn, conn_params=conn_params,
        )
        row_count = count_rows[0]["cnt"] if count_rows else 0

        if row_count == 0:
            # Resolve predicate/type UUIDs
            uuid_map = {}
            for uri in [SLOT_TYPE_URI, SLOT_VALUE_URI, SOURCE_ENTITY_URI, DEST_ENTITY_URI]:
                rows = await db.execute_query(
                    f"SELECT term_uuid FROM {term_table} WHERE term_text = %s LIMIT 1",
                    params=(uri,), conn=conn, conn_params=conn_params,
                )
                if not rows:
                    logger.info("ensure_frame_entity_table(%s): URI %s not found, skipping populate", space_id, uri)
                    _frame_entity_table_ready[space_id] = True
                    return True  # table exists but data doesn't use frames
                uuid_map[uri] = str(rows[0]["term_uuid"])

            st_uuid = uuid_map[SLOT_TYPE_URI]
            sv_uuid = uuid_map[SLOT_VALUE_URI]
            src_uuid = uuid_map[SOURCE_ENTITY_URI]
            dst_uuid = uuid_map[DEST_ENTITY_URI]

            logger.info("ensure_frame_entity_table(%s): populating from edge + rdf_quad", space_id)
            populate_sql = f"""
                INSERT INTO {table_name} (frame_uuid, source_entity_uuid, dest_entity_uuid, context_uuid)
                SELECT
                    emv.source_node_uuid  AS frame_uuid,
                    (array_agg(sv.object_uuid) FILTER (
                        WHERE st.object_uuid = '{src_uuid}'::uuid
                    ))[1] AS source_entity_uuid,
                    (array_agg(sv.object_uuid) FILTER (
                        WHERE st.object_uuid = '{dst_uuid}'::uuid
                    ))[1] AS dest_entity_uuid,
                    emv.context_uuid      AS context_uuid
                FROM {edge_table_name} emv
                JOIN {quad_table} st
                    ON st.subject_uuid = emv.dest_node_uuid
                    AND st.predicate_uuid = '{st_uuid}'::uuid
                JOIN {quad_table} sv
                    ON sv.subject_uuid = emv.dest_node_uuid
                    AND sv.predicate_uuid = '{sv_uuid}'::uuid
                WHERE st.object_uuid IN ('{src_uuid}'::uuid, '{dst_uuid}'::uuid)
                GROUP BY emv.source_node_uuid, emv.context_uuid
                HAVING (array_agg(sv.object_uuid) FILTER (
                    WHERE st.object_uuid = '{src_uuid}'::uuid
                ))[1] IS NOT NULL
                AND (array_agg(sv.object_uuid) FILTER (
                    WHERE st.object_uuid = '{dst_uuid}'::uuid
                ))[1] IS NOT NULL
                ON CONFLICT DO NOTHING
            """
            async with db.get_connection(params=conn_params) as c:
                await c.execute(populate_sql)
                await c.execute(f"ANALYZE {table_name}")

            count_rows = await db.execute_query(
                f"SELECT COUNT(*) AS cnt FROM {table_name}",
                conn=conn, conn_params=conn_params,
            )
            row_count = count_rows[0]["cnt"] if count_rows else 0
            logger.info("ensure_frame_entity_table(%s): populated %d rows", space_id, row_count)

        _frame_entity_table_ready[space_id] = True
        return True

    except Exception as e:
        logger.warning("ensure_frame_entity_table(%s): failed: %s", space_id, e)
        _frame_entity_table_ready[space_id] = False
        return False
