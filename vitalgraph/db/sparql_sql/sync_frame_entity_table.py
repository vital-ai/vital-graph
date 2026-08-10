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
    touched_uuids: List[uuid.UUID],
) -> int:
    """After edge rows are inserted, find new frame_entity rows.

    `touched_uuids` are the subject uuids a write touched. A frame is affected
    if the write touched the frame itself, one of its slots, or the edge joining
    them — so all three positions are matched, not just one.

    This used to take "the source_node_uuid values from newly inserted edge rows
    (these are the frame UUIDs)". Both callers pass QUAD SUBJECTS instead, which
    are edge and slot uuids and never the frame, so `source_node_uuid = ANY(...)`
    matched nothing and the incremental sync populated **nothing, on any write
    path, ever**. The symptom was easy to misread: `resync_all_auxiliary_tables`
    reports `frame_entity_rows=0` for every space, which looks like "no space has
    relation frames" rather than "the incremental path is dead" — and the full
    resync has no such filter, so a rebuild masked it by working correctly.

    Found by a fixture-guard test asserting that the seed shape actually
    produces rows before testing deletion against it.
    """
    if not touched_uuids:
        return 0

    uuids = await _resolve_uuids(conn, space_id)
    if not uuids:
        return 0
    st_uuid, sv_uuid, src_uuid, dst_uuid = uuids

    t_fe = f"{space_id}_frame_entity"
    t_edge = f"{space_id}_edge"
    t_quad = f"{space_id}_rdf_quad"

    from .sync_edge_table import chunk_uuids

    inserted = 0
    for chunk in chunk_uuids(touched_uuids):
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
              -- The frame, its slot, or the edge between them: a write to any
              -- of the three can create or invalidate a frame_entity row.
              AND (emv.source_node_uuid = ANY($5)
                   OR emv.dest_node_uuid = ANY($5)
                   OR emv.edge_uuid = ANY($5))
            GROUP BY emv.source_node_uuid, emv.context_uuid
            HAVING (array_agg(sv.object_uuid) FILTER (WHERE st.object_uuid = $3))[1] IS NOT NULL
               AND (array_agg(sv.object_uuid) FILTER (WHERE st.object_uuid = $4))[1] IS NOT NULL
            ON CONFLICT DO NOTHING
        """, st_uuid, sv_uuid, src_uuid, dst_uuid, chunk)
        inserted += int(result.split()[-1]) if result else 0

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


async def cleanup_stale_frame_entity(conn, space_id: str,
                                     limit: int = 50_000) -> int:
    """Remove frame_entity rows whose defining slot chain is gone. Bounded.

    The delete-side counterpart, and the piece frame_entity never had.
    `sync_frame_entity_before_delete` needs a frame uuid list, which a SPARQL
    UPDATE cannot produce for WHERE-bound subjects, so those deletions left rows
    asserting a relationship between entities that no longer exists
    (`issues/064`).

    Validity is defined exactly as `resync_frame_entity_table` defines it: the
    frame must still reach a slot typed `urn:hasSourceEntity` carrying the
    recorded source entity, and likewise for the destination. Anything else is
    a row the rebuild would not produce.

    Bounded and a plain DELETE, so it takes ROW EXCLUSIVE and does not block
    readers the way the resync's TRUNCATE does.
    """
    uuids = await _resolve_uuids(conn, space_id)
    if not uuids:
        return 0
    st_uuid, sv_uuid, src_uuid, dst_uuid = uuids

    t_fe = f"{space_id}_frame_entity"
    t_edge = f"{space_id}_edge"
    t_quad = f"{space_id}_rdf_quad"

    result = await conn.execute(f"""
        DELETE FROM {t_fe} WHERE ctid IN (
            SELECT fe.ctid FROM {t_fe} fe
            WHERE NOT EXISTS (
                SELECT 1
                FROM {t_edge} emv
                JOIN {t_quad} st ON st.subject_uuid = emv.dest_node_uuid
                    AND st.predicate_uuid = $1 AND st.object_uuid = $3
                JOIN {t_quad} sv ON sv.subject_uuid = emv.dest_node_uuid
                    AND sv.predicate_uuid = $2
                    AND sv.object_uuid = fe.source_entity_uuid
                WHERE emv.source_node_uuid = fe.frame_uuid
                  AND emv.context_uuid = fe.context_uuid)
            OR NOT EXISTS (
                SELECT 1
                FROM {t_edge} emv
                JOIN {t_quad} st ON st.subject_uuid = emv.dest_node_uuid
                    AND st.predicate_uuid = $1 AND st.object_uuid = $4
                JOIN {t_quad} sv ON sv.subject_uuid = emv.dest_node_uuid
                    AND sv.predicate_uuid = $2
                    AND sv.object_uuid = fe.dest_entity_uuid
                WHERE emv.source_node_uuid = fe.frame_uuid
                  AND emv.context_uuid = fe.context_uuid)
            LIMIT {int(limit)})
    """, st_uuid, sv_uuid, src_uuid, dst_uuid)
    deleted = int(result.split()[-1]) if result else 0
    if deleted:
        logger.info("cleanup_stale_frame_entity(%s): removed %d stale row(s)",
                    space_id, deleted)
    return deleted


async def delete_frame_entity_for_context(conn, space_id: str,
                                          context_uuid) -> int:
    """Remove every frame_entity row for a graph. For DROP GRAPH / CLEAR GRAPH.

    Those forms name no subjects, so the per-frame hook never fires and the
    whole graph's rows survive it (`issues/064`).
    """
    t_fe = f"{space_id}_frame_entity"
    result = await conn.execute(
        f"DELETE FROM {t_fe} WHERE context_uuid = $1", context_uuid)
    deleted = int(result.split()[-1]) if result else 0
    if deleted:
        logger.info("delete_frame_entity_for_context(%s): removed %d row(s)",
                    space_id, deleted)
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


async def backfill_frame_entity_table(conn, space_id: str) -> int:
    """Add only the MISSING frame_entity rows — no TRUNCATE, no rebuild.

    The non-blocking counterpart of resync_frame_entity_table (which TRUNCATEs
    and holds ACCESS EXCLUSIVE): a plain INSERT ... ON CONFLICT DO NOTHING taking
    only ROW EXCLUSIVE, so concurrent frame-entity-rewrite queries keep running.
    Deletes stay in sync via sync_frame_entity_before_delete, so drift is always
    *missing* rows, which this adds.  No-op (returns 0) when the connector-frame
    URIs are absent from the space.  Returns rows inserted.
    """
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
            (array_agg(sv.object_uuid) FILTER (WHERE st.object_uuid = $3))[1] AS source_entity_uuid,
            (array_agg(sv.object_uuid) FILTER (WHERE st.object_uuid = $4))[1] AS dest_entity_uuid,
            emv.context_uuid
        FROM {t_edge} emv
        JOIN {t_quad} st ON st.subject_uuid = emv.dest_node_uuid AND st.predicate_uuid = $1
        JOIN {t_quad} sv ON sv.subject_uuid = emv.dest_node_uuid AND sv.predicate_uuid = $2
        WHERE st.object_uuid IN ($3, $4)
        GROUP BY emv.source_node_uuid, emv.context_uuid
        HAVING (array_agg(sv.object_uuid) FILTER (WHERE st.object_uuid = $3))[1] IS NOT NULL
           AND (array_agg(sv.object_uuid) FILTER (WHERE st.object_uuid = $4))[1] IS NOT NULL
        ON CONFLICT DO NOTHING
    """, st_uuid, sv_uuid, src_uuid, dst_uuid)

    inserted = int(result.split()[-1]) if result else 0
    if inserted:
        await conn.execute(f"ANALYZE {t_fe}")
    logger.info("backfill_frame_entity_table(%s): %d rows inserted", space_id, inserted)
    return inserted


async def frame_entity_drift(conn, space_id: str) -> tuple[int, int]:
    """Return (expected_rows, actual_rows) — a cheap drift signal for frame_entity.

    expected_rows = min(#source-entity slots, #dest-entity slots): an upper bound
    on frames that have BOTH endpoints (so a frame with a source but no dest does
    not register as drift).  actual_rows = current frame_entity rows.  All three
    are single index/heap counts, and 0 for spaces without connector frames.
    """
    t_fe = f"{space_id}_frame_entity"
    t_quad = f"{space_id}_rdf_quad"
    src_slots = await conn.fetchval(
        f"SELECT count(*) FROM {t_quad} WHERE predicate_uuid = $1 AND object_uuid = $2",
        _ST_UUID, _SRC_UUID)
    dst_slots = await conn.fetchval(
        f"SELECT count(*) FROM {t_quad} WHERE predicate_uuid = $1 AND object_uuid = $2",
        _ST_UUID, _DST_UUID)
    fe_rows = await conn.fetchval(f"SELECT count(*) FROM {t_fe}")
    expected = min(int(src_slots or 0), int(dst_slots or 0))
    return expected, int(fe_rows or 0)
