"""Incremental sync for the {space}_edge table.

Called after quad inserts and before/after quad deletes to keep the edge
table in sync with rdf_quad.  All functions accept an asyncpg connection
that is already inside a transaction.
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

logger = logging.getLogger(__name__)

EDGE_SOURCE_URI = "http://vital.ai/ontology/vital-core#hasEdgeSource"
EDGE_DEST_URI = "http://vital.ai/ontology/vital-core#hasEdgeDestination"

# Deterministic UUID namespace (same as sparql_sql_space_impl)
_VITALGRAPH_NS = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')

# Pre-computed predicate UUIDs (deterministic, never change)
_EDGE_SRC_UUID = uuid.uuid5(_VITALGRAPH_NS, f"{EDGE_SOURCE_URI}\x00U")
_EDGE_DST_UUID = uuid.uuid5(_VITALGRAPH_NS, f"{EDGE_DEST_URI}\x00U")


async def sync_edge_table_after_insert(
    conn,
    space_id: str,
    subject_uuids: List[uuid.UUID],
) -> int:
    """After quads are inserted, find new edge pairs and insert into edge table.

    Scans only the given subject_uuids for hasEdgeSource + hasEdgeDestination
    pairs.  Returns the number of edge rows inserted.
    """
    if not subject_uuids:
        return 0

    t_edge = f"{space_id}_edge"
    t_quad = f"{space_id}_rdf_quad"

    result = await conn.execute(f"""
        INSERT INTO {t_edge} (edge_uuid, source_node_uuid, dest_node_uuid, context_uuid)
        SELECT
            src.subject_uuid,
            src.object_uuid,
            dst.object_uuid,
            src.context_uuid
        FROM {t_quad} src
        JOIN {t_quad} dst
            ON dst.subject_uuid = src.subject_uuid
            AND dst.context_uuid = src.context_uuid
        WHERE src.predicate_uuid = $1
          AND dst.predicate_uuid = $2
          AND src.subject_uuid = ANY($3)
        ON CONFLICT DO NOTHING
    """, _EDGE_SRC_UUID, _EDGE_DST_UUID, subject_uuids)

    inserted = int(result.split()[-1]) if result else 0
    if inserted:
        logger.debug("sync_edge_table_after_insert(%s): %d edge rows", space_id, inserted)
    return inserted


async def sync_edge_table_before_delete(
    conn,
    space_id: str,
    subject_uuids: List[uuid.UUID],
    context_uuid: Optional[uuid.UUID] = None,
) -> int:
    """Before quads are deleted, remove corresponding edge table rows.

    Deletes edge rows where edge_uuid is in subject_uuids.
    If context_uuid is provided, scopes the delete to that graph.
    Returns the number of edge rows deleted.
    """
    if not subject_uuids:
        return 0

    t_edge = f"{space_id}_edge"

    if context_uuid:
        result = await conn.execute(
            f"DELETE FROM {t_edge} WHERE edge_uuid = ANY($1) AND context_uuid = $2",
            subject_uuids, context_uuid,
        )
    else:
        result = await conn.execute(
            f"DELETE FROM {t_edge} WHERE edge_uuid = ANY($1)",
            subject_uuids,
        )

    deleted = int(result.split()[-1]) if result else 0
    if deleted:
        logger.debug("sync_edge_table_before_delete(%s): %d edge rows", space_id, deleted)
    return deleted


async def resync_edge_table(conn, space_id: str) -> int:
    """Rebuild {space}_edge from scratch by scanning rdf_quad.

    Truncates the edge table and repopulates it from hasEdgeSource +
    hasEdgeDestination quad pairs.  Runs ANALYZE afterwards.
    Returns the number of rows inserted.
    """
    t_edge = f"{space_id}_edge"
    t_quad = f"{space_id}_rdf_quad"

    await conn.execute(f"TRUNCATE {t_edge}")

    result = await conn.execute(f"""
        INSERT INTO {t_edge} (edge_uuid, source_node_uuid, dest_node_uuid, context_uuid)
        SELECT
            src.subject_uuid,
            src.object_uuid,
            dst.object_uuid,
            src.context_uuid
        FROM {t_quad} src
        JOIN {t_quad} dst
            ON dst.subject_uuid = src.subject_uuid
            AND dst.context_uuid = src.context_uuid
        WHERE src.predicate_uuid = $1
          AND dst.predicate_uuid = $2
    """, _EDGE_SRC_UUID, _EDGE_DST_UUID)

    inserted = int(result.split()[-1]) if result else 0
    await conn.execute(f"ANALYZE {t_edge}")
    logger.info("resync_edge_table(%s): %d rows inserted", space_id, inserted)
    return inserted
