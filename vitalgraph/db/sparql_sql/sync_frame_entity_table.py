"""Incremental and full sync for the {space}_frame_entity table.

The frame_entity table depends on the edge table, so edge sync must
run first.  All functions accept an asyncpg connection already inside
a transaction.
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

logger = logging.getLogger(__name__)

SLOT_TYPE_URI = "http://vital.ai/ontology/haley-ai-kg#hasKGSlotType"
SLOT_VALUE_URI = "http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue"
SOURCE_ENTITY_URI = "urn:hasSourceEntity"
DEST_ENTITY_URI = "urn:hasDestinationEntity"

# Deterministic UUID namespace (same as sparql_sql_space_impl)
_VITALGRAPH_NS = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')

# Pre-computed predicate/type UUIDs
_ST_UUID = uuid.uuid5(_VITALGRAPH_NS, f"{SLOT_TYPE_URI}\x00U")
_SV_UUID = uuid.uuid5(_VITALGRAPH_NS, f"{SLOT_VALUE_URI}\x00U")
_SRC_UUID = uuid.uuid5(_VITALGRAPH_NS, f"{SOURCE_ENTITY_URI}\x00U")
_DST_UUID = uuid.uuid5(_VITALGRAPH_NS, f"{DEST_ENTITY_URI}\x00U")


async def _resolve_uuids(conn, space_id: str):
    """Resolve the 4 frame-entity URIs to UUIDs from the term table.

    Returns (st_uuid, sv_uuid, src_uuid, dst_uuid) or None if any URI
    is missing from the term table.
    """
    t_term = f"{space_id}_term"
    for uri, expected in [
        (SLOT_TYPE_URI, _ST_UUID),
        (SLOT_VALUE_URI, _SV_UUID),
        (SOURCE_ENTITY_URI, _SRC_UUID),
        (DEST_ENTITY_URI, _DST_UUID),
    ]:
        row = await conn.fetchrow(
            f"SELECT term_uuid FROM {t_term} WHERE term_uuid = $1",
            expected,
        )
        if not row:
            return None
    return _ST_UUID, _SV_UUID, _SRC_UUID, _DST_UUID


async def sync_frame_entity_after_edge_insert(
    conn,
    space_id: str,
    edge_source_uuids: List[uuid.UUID],
) -> int:
    """After edge rows are inserted, find new frame_entity rows.

    edge_source_uuids: the source_node_uuid values from newly inserted
    edge rows (these are the frame UUIDs in the frame→slot pattern).
    Returns the number of frame_entity rows inserted.
    """
    if not edge_source_uuids:
        return 0

    uuids = await _resolve_uuids(conn, space_id)
    if not uuids:
        return 0
    st_uuid, sv_uuid, src_uuid, dst_uuid = uuids

    t_fe = f"{space_id}_frame_entity"
    t_edge = f"{space_id}_edge"
    t_quad = f"{space_id}_rdf_quad"

    result = await conn.execute(f"""
        INSERT INTO {t_fe} (frame_uuid, source_entity_uuid, dest_entity_uuid, context_uuid)
        SELECT
            emv.source_node_uuid AS frame_uuid,
            (array_agg(sv.object_uuid) FILTER (
                WHERE st.object_uuid = $3
            ))[1] AS source_entity_uuid,
            (array_agg(sv.object_uuid) FILTER (
                WHERE st.object_uuid = $4
            ))[1] AS dest_entity_uuid,
            emv.context_uuid
        FROM {t_edge} emv
        JOIN {t_quad} st
            ON st.subject_uuid = emv.dest_node_uuid
            AND st.predicate_uuid = $1
        JOIN {t_quad} sv
            ON sv.subject_uuid = emv.dest_node_uuid
            AND sv.predicate_uuid = $2
        WHERE st.object_uuid IN ($3, $4)
          AND emv.source_node_uuid = ANY($5)
        GROUP BY emv.source_node_uuid, emv.context_uuid
        HAVING (array_agg(sv.object_uuid) FILTER (WHERE st.object_uuid = $3))[1] IS NOT NULL
           AND (array_agg(sv.object_uuid) FILTER (WHERE st.object_uuid = $4))[1] IS NOT NULL
        ON CONFLICT DO NOTHING
    """, st_uuid, sv_uuid, src_uuid, dst_uuid, edge_source_uuids)

    inserted = int(result.split()[-1]) if result else 0
    if inserted:
        logger.debug("sync_frame_entity_after_edge_insert(%s): %d rows", space_id, inserted)
    return inserted


async def sync_frame_entity_before_delete(
    conn,
    space_id: str,
    subject_uuids: List[uuid.UUID],
    context_uuid: Optional[uuid.UUID] = None,
) -> int:
    """Before entity quads are deleted, remove corresponding frame_entity rows.

    Removes rows where frame_uuid is in subject_uuids (frames being deleted).
    Also removes rows where source_entity_uuid or dest_entity_uuid is in
    subject_uuids (entities being deleted).
    Returns total rows deleted.
    """
    if not subject_uuids:
        return 0

    t_fe = f"{space_id}_frame_entity"
    deleted = 0

    if context_uuid:
        result = await conn.execute(
            f"DELETE FROM {t_fe} WHERE frame_uuid = ANY($1) AND context_uuid = $2",
            subject_uuids, context_uuid,
        )
    else:
        result = await conn.execute(
            f"DELETE FROM {t_fe} WHERE frame_uuid = ANY($1)",
            subject_uuids,
        )
    deleted += int(result.split()[-1]) if result else 0

    if deleted:
        logger.debug("sync_frame_entity_before_delete(%s): %d rows", space_id, deleted)
    return deleted


async def resync_frame_entity_table(conn, space_id: str) -> int:
    """Rebuild {space}_frame_entity from scratch using edge + rdf_quad.

    Truncates the frame_entity table and repopulates it.
    Runs ANALYZE afterwards.  Returns rows inserted.
    """
    uuids = await _resolve_uuids(conn, space_id)
    if not uuids:
        logger.info("resync_frame_entity_table(%s): URIs not in term table, skipping", space_id)
        return 0
    st_uuid, sv_uuid, src_uuid, dst_uuid = uuids

    t_fe = f"{space_id}_frame_entity"
    t_edge = f"{space_id}_edge"
    t_quad = f"{space_id}_rdf_quad"

    await conn.execute(f"TRUNCATE {t_fe}")

    result = await conn.execute(f"""
        INSERT INTO {t_fe} (frame_uuid, source_entity_uuid, dest_entity_uuid, context_uuid)
        SELECT
            emv.source_node_uuid AS frame_uuid,
            (array_agg(sv.object_uuid) FILTER (
                WHERE st.object_uuid = $3
            ))[1] AS source_entity_uuid,
            (array_agg(sv.object_uuid) FILTER (
                WHERE st.object_uuid = $4
            ))[1] AS dest_entity_uuid,
            emv.context_uuid
        FROM {t_edge} emv
        JOIN {t_quad} st
            ON st.subject_uuid = emv.dest_node_uuid
            AND st.predicate_uuid = $1
        JOIN {t_quad} sv
            ON sv.subject_uuid = emv.dest_node_uuid
            AND sv.predicate_uuid = $2
        WHERE st.object_uuid IN ($3, $4)
        GROUP BY emv.source_node_uuid, emv.context_uuid
        HAVING (array_agg(sv.object_uuid) FILTER (WHERE st.object_uuid = $3))[1] IS NOT NULL
           AND (array_agg(sv.object_uuid) FILTER (WHERE st.object_uuid = $4))[1] IS NOT NULL
    """, st_uuid, sv_uuid, src_uuid, dst_uuid)

    inserted = int(result.split()[-1]) if result else 0
    await conn.execute(f"ANALYZE {t_fe}")
    logger.info("resync_frame_entity_table(%s): %d rows inserted", space_id, inserted)
    return inserted
