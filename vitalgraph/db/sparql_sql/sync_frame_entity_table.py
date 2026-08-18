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
# The frame's type, denormalised onto the row (issues/060 did the same for
# `edge`). VITALTYPE rather than rdf:type, for three reasons that agree: it is
# single-valued by design so the column is well-defined, `edge_type_uuid` uses
# it, and it is what the product actually queries with —
# `kgframes_endpoint` emits `<frame> vital-core:vitaltype <KGFrame>`.
VITALTYPE_URI = "http://vital.ai/ontology/vital-core#vitaltype"

# Deterministic UUID namespace (same as sparql_sql_space_impl)
_VITALGRAPH_NS = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')

# Pre-computed predicate/type UUIDs
_ST_UUID = uuid.uuid5(_VITALGRAPH_NS, f"{SLOT_TYPE_URI}\x00U")
_SV_UUID = uuid.uuid5(_VITALGRAPH_NS, f"{SLOT_VALUE_URI}\x00U")
_SRC_UUID = uuid.uuid5(_VITALGRAPH_NS, f"{SOURCE_ENTITY_URI}\x00U")
_DST_UUID = uuid.uuid5(_VITALGRAPH_NS, f"{DEST_ENTITY_URI}\x00U")
_VT_UUID = uuid.uuid5(_VITALGRAPH_NS, f"{VITALTYPE_URI}\x00U")
# `hasEdgeSource` is what MAKES a frame_entity row: the frame is the object
# of that quad. Used by the orphan probe, which must not assume a predicate
# the data is not obliged to carry.
EDGE_SOURCE_URI = "http://vital.ai/ontology/vital-core#hasEdgeSource"
_ES_UUID = uuid.uuid5(_VITALGRAPH_NS, f"{EDGE_SOURCE_URI}\x00U")


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

    This used to match only `emv.source_node_uuid` — the frame. That is enough
    when the frame is itself a subject of the same write, which it is whenever
    the frame is created (it carries its own type triple), so the common case
    worked.

    It is NOT enough for incremental CRUD on an existing frame. Changing a
    slot's `hasEntitySlotValue`, or adding a slot to a frame that already
    exists, touches only the slot (and maybe the edge) — the frame is not a
    subject of that write, nothing matched, and frame_entity kept the old
    entity. Silently: the table still has a row, it just describes a
    relationship that has changed.
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

    # Force a CUSTOM plan for the statement below.
    #
    # PostgreSQL plans a prepared statement per-parameter for its first five
    # executions, then decides whether a GENERIC plan is competitive. For this
    # query it decides wrongly, and by an enormous margin — measured on
    # wordnet_frames, syncing five touched frames:
    #
    #     plan_cache_mode=auto           [4, 1, 2, 1, 1, 10186, 8094, 8885, 8581] ms
    #     plan_cache_mode=force_custom   [1, 1, 1, 1, 1,     1,    1,    1,    1] ms
    #
    # Runs one to five are a millisecond; run six onwards is EIGHT SECONDS, and
    # it stays there — a prepared statement lives as long as the connection, so
    # a pooled connection degrades permanently after its fifth write.
    #
    # The parameter is an array of touched uuids, and the right plan depends
    # entirely on how many there are, which is exactly the case a generic plan
    # cannot serve. Rewriting the OR-subquery as a UNION was tried and only
    # moved 5.5 s to 4.0 s: the generic plan is bad for the whole shape, not
    # just that clause.
    #
    # SET LOCAL reverts at the end of the caller's transaction. Outside one it
    # would warn and do nothing, so the statement is wrapped when needed.
    async def _forced(sql, *args):
        if conn.is_in_transaction():
            await conn.execute("SET LOCAL plan_cache_mode = force_custom_plan")
            return await conn.execute(sql, *args)
        async with conn.transaction():
            await conn.execute("SET LOCAL plan_cache_mode = force_custom_plan")
            return await conn.execute(sql, *args)

    inserted = 0
    for chunk in chunk_uuids(touched_uuids):
        result = await _forced(f"""
            INSERT INTO {t_fe} (frame_uuid, source_entity_uuid, dest_entity_uuid,
                                context_uuid, frame_type_uuid)
            SELECT
                emv.source_node_uuid AS frame_uuid,
                (array_agg(sv.object_uuid) FILTER (
                    WHERE st.object_uuid = $3
                ))[1] AS source_entity_uuid,
                (array_agg(sv.object_uuid) FILTER (
                    WHERE st.object_uuid = $4
                ))[1] AS dest_entity_uuid,
                emv.context_uuid,
                -- One vitaltype per frame by design, so this picks the single
                -- value rather than choosing between several. Aggregated
                -- because the GROUP BY is per frame while the join fans out
                -- over that frame's slots, and FILTERed because the LEFT JOIN
                -- contributes NULLs that would otherwise win position [1].
                (array_agg(vt.object_uuid)
                 FILTER (WHERE vt.object_uuid IS NOT NULL))[1] AS frame_type_uuid
            FROM {t_edge} emv
            JOIN {t_quad} st
                ON st.subject_uuid = emv.dest_node_uuid
                AND st.predicate_uuid = $1
            JOIN {t_quad} sv
                ON sv.subject_uuid = emv.dest_node_uuid
                AND sv.predicate_uuid = $2
            LEFT JOIN {t_quad} vt
                ON vt.subject_uuid = emv.source_node_uuid
                AND vt.context_uuid = emv.context_uuid
                AND vt.predicate_uuid = $6
            WHERE st.object_uuid IN ($3, $4)
              -- Select the FRAMES the write touched, then aggregate over ALL
              -- of each frame's slots. Filtering the join rows themselves by
              -- the touched uuid instead restricts the aggregate to the one
              -- slot that changed, so the HAVING below — which requires both a
              -- source and a destination role — drops the frame entirely and
              -- the row is deleted and never rebuilt.
              AND emv.source_node_uuid IN (
                    SELECT e2.source_node_uuid FROM {t_edge} e2
                    WHERE e2.source_node_uuid = ANY($5)
                       OR e2.dest_node_uuid = ANY($5)
                       OR e2.edge_uuid = ANY($5))
            GROUP BY emv.source_node_uuid, emv.context_uuid
            HAVING (array_agg(sv.object_uuid) FILTER (WHERE st.object_uuid = $3))[1] IS NOT NULL
               AND (array_agg(sv.object_uuid) FILTER (WHERE st.object_uuid = $4))[1] IS NOT NULL
            ON CONFLICT DO NOTHING
        """, st_uuid, sv_uuid, src_uuid, dst_uuid, chunk, _VT_UUID)
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
    """Before quads are deleted, remove the frame_entity rows they invalidate.

    Removes rows for any frame the write touched — directly, or through one of
    its slots or the edge joining them. Callers pair this with
    `sync_frame_entity_after_edge_insert` to drop and re-derive.

    Resolving slots and edges back to their frame is what makes an UPDATE work.
    This used to delete only `frame_uuid = ANY(subjects)`, and repointing a
    slot's `hasEntitySlotValue` touches the SLOT, not the frame: nothing was
    dropped, the re-derive hit ON CONFLICT DO NOTHING, and the row kept naming
    the OLD entity indefinitely. The row count never changes, so no drift check
    can see it — the table simply asserts a relationship that has moved.

    (The previous docstring also claimed it removed rows by source_entity_uuid
    and dest_entity_uuid, for entities being deleted. It never did. That case is
    now covered by `cleanup_stale_frame_entity`, which is referential rather
    than subject-driven.)
    """
    if not subject_uuids:
        return 0

    t_fe = f"{space_id}_frame_entity"
    t_edge = f"{space_id}_edge"
    deleted = 0

    frame_filter = f"""
        (frame_uuid = ANY($1)
         OR frame_uuid IN (
            SELECT source_node_uuid FROM {t_edge}
            WHERE dest_node_uuid = ANY($1) OR edge_uuid = ANY($1)))
    """

    if context_uuid:
        result = await conn.execute(
            f"DELETE FROM {t_fe} WHERE {frame_filter} AND context_uuid = $2",
            subject_uuids, context_uuid,
        )
    else:
        result = await conn.execute(
            f"DELETE FROM {t_fe} WHERE {frame_filter}",
            subject_uuids,
        )
    deleted += int(result.split()[-1]) if result else 0

    if deleted:
        logger.debug("sync_frame_entity_before_delete(%s): %d rows", space_id, deleted)
    return deleted


# Rows this sweep may EXAMINE per pass, and where the next pass starts. Same
# reasoning as the edge sweep in sync_edge_table (issues/079): a LIMIT on rows
# DELETED bounds nothing in the healthy case, because proving there is nothing
# to delete still walks the whole table — and the check here is strictly more
# expensive than the edge one, two correlated NOT EXISTS each joining the edge
# table to two quads. In-process cursor: losing it on restart costs one repeated
# window, and the sweep is convergent, so it does not need to be durable.
_FE_SWEEP_SCAN_ROWS = 50_000
_fe_sweep_cursor: dict = {}


async def cleanup_stale_frame_entity(conn, space_id: str,
                                     limit: int = 50_000,
                                     scan_rows: int = _FE_SWEEP_SCAN_ROWS) -> int:
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

    cursor = _fe_sweep_cursor.get(space_id) or "(0,0)"
    rows = await conn.fetch(f"""
        SELECT fe.ctid::text AS ctid,
               (NOT EXISTS (
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
                  AND emv.context_uuid = fe.context_uuid)) AS stale
        FROM (
            SELECT ctid, frame_uuid, context_uuid,
                   source_entity_uuid, dest_entity_uuid
            FROM {t_fe}
            WHERE ctid > $5::text::tid
            ORDER BY ctid
            LIMIT {int(scan_rows)}
        ) fe
    """, st_uuid, sv_uuid, src_uuid, dst_uuid, cursor)

    if not rows:
        _fe_sweep_cursor[space_id] = None       # end of table: wrap next pass
        return 0
    _fe_sweep_cursor[space_id] = rows[-1]["ctid"]

    stale_ctids = [r["ctid"] for r in rows if r["stale"]][:int(limit)]
    if not stale_ctids:
        return 0

    result = await conn.execute(
        f"DELETE FROM {t_fe} WHERE ctid = ANY($1::text[]::tid[])", stale_ctids)
    deleted = int(result.split()[-1]) if result else 0
    if deleted:
        logger.info("cleanup_stale_frame_entity(%s): removed %d stale row(s) "
                    "from a %d-row window", space_id, deleted, len(rows))
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
        INSERT INTO {t_fe} (frame_uuid, source_entity_uuid, dest_entity_uuid,
                            context_uuid, frame_type_uuid)
        SELECT
            emv.source_node_uuid AS frame_uuid,
            (array_agg(sv.object_uuid) FILTER (
                WHERE st.object_uuid = $3
            ))[1] AS source_entity_uuid,
            (array_agg(sv.object_uuid) FILTER (
                WHERE st.object_uuid = $4
            ))[1] AS dest_entity_uuid,
            emv.context_uuid,
            (array_agg(vt.object_uuid)
             FILTER (WHERE vt.object_uuid IS NOT NULL))[1] AS frame_type_uuid
        FROM {t_edge} emv
        JOIN {t_quad} st
            ON st.subject_uuid = emv.dest_node_uuid
            AND st.predicate_uuid = $1
        JOIN {t_quad} sv
            ON sv.subject_uuid = emv.dest_node_uuid
            AND sv.predicate_uuid = $2
        LEFT JOIN {t_quad} vt
            ON vt.subject_uuid = emv.source_node_uuid
            AND vt.context_uuid = emv.context_uuid
            AND vt.predicate_uuid = $5
        WHERE st.object_uuid IN ($3, $4)
        GROUP BY emv.source_node_uuid, emv.context_uuid
        HAVING (array_agg(sv.object_uuid) FILTER (WHERE st.object_uuid = $3))[1] IS NOT NULL
           AND (array_agg(sv.object_uuid) FILTER (WHERE st.object_uuid = $4))[1] IS NOT NULL
    """, st_uuid, sv_uuid, src_uuid, dst_uuid, _VT_UUID)

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
        INSERT INTO {t_fe} (frame_uuid, source_entity_uuid, dest_entity_uuid,
                            context_uuid, frame_type_uuid)
        SELECT
            emv.source_node_uuid AS frame_uuid,
            (array_agg(sv.object_uuid) FILTER (WHERE st.object_uuid = $3))[1] AS source_entity_uuid,
            (array_agg(sv.object_uuid) FILTER (WHERE st.object_uuid = $4))[1] AS dest_entity_uuid,
            emv.context_uuid,
            (array_agg(vt.object_uuid)
             FILTER (WHERE vt.object_uuid IS NOT NULL))[1] AS frame_type_uuid
        FROM {t_edge} emv
        JOIN {t_quad} st ON st.subject_uuid = emv.dest_node_uuid AND st.predicate_uuid = $1
        JOIN {t_quad} sv ON sv.subject_uuid = emv.dest_node_uuid AND sv.predicate_uuid = $2
        LEFT JOIN {t_quad} vt ON vt.subject_uuid = emv.source_node_uuid
            AND vt.context_uuid = emv.context_uuid AND vt.predicate_uuid = $5
        WHERE st.object_uuid IN ($3, $4)
        GROUP BY emv.source_node_uuid, emv.context_uuid
        HAVING (array_agg(sv.object_uuid) FILTER (WHERE st.object_uuid = $3))[1] IS NOT NULL
           AND (array_agg(sv.object_uuid) FILTER (WHERE st.object_uuid = $4))[1] IS NOT NULL
        ON CONFLICT DO NOTHING
    """, st_uuid, sv_uuid, src_uuid, dst_uuid, _VT_UUID)

    inserted = int(result.split()[-1]) if result else 0
    if inserted:
        await conn.execute(f"ANALYZE {t_fe}")
    logger.info("backfill_frame_entity_table(%s): %d rows inserted", space_id, inserted)
    return inserted


async def frame_entity_orphan_rate(conn, space_id: str, sample: int = 200) -> float:
    """Fraction of sampled `frame_entity` rows that no longer refer to anything.

    `frame_entity_drift` compares COUNTS, and the failure this exists for has
    identical counts. `issues/041`: a space reloaded in place leaves a derived
    table that is a faithful materialisation of the PREVIOUS contents — same
    size, disjoint set, every count check green, and every traversal returning
    nothing. Only a referential probe sees it.

    That issue closed the gap for `{space}_edge` and recorded that the same
    argument applies here, with no equivalent probe. This is that probe.

    THE CONTEXT IS PART OF THE CHECK, and it is the half that matters most.
    Reloading a space under a different graph URI leaves every row pointing at
    the old context: the frame uuids still resolve, so an identity-only probe
    reports a healthy 0% while every query filters on the new context and
    matches none of them. That is exactly how the edge probe was wrong when
    first written — `sp_lead_synth_100k`, reloaded from `urn:lead_synth_100k` to
    `urn:sp_lead_synth_100k`, read 0% while a criterion with 9,220 expected
    matches returned 0 rows in 154 seconds.

    Note the asymmetry with the edge table, because it explains why this probe
    was not obviously needed: on the wordnet reload, `frame_entity` was
    UNAFFECTED — it references only frames and entities, whose URIs were
    identical across both exports, while the edge table referenced the edge
    nodes, which were regenerated. A rename of the GRAPH hits both.

    ANCHORED ON `hasEdgeSource`, NOT ON THE TYPE QUAD. The first version asked
    whether the frame still carried a `vitaltype` quad and read 100% on
    `prolog_spike_frames`. Two things were wrong with that, and the first is the
    less interesting one:

      * That space types its objects with `rdf:type`, not `vitaltype` — 1,200
        quads of it. The two are alternative spellings the generator already
        treats as equivalent (`generator.py`, `slot_type_tautology`), so a probe
        that checks only one of them is asking a narrower question than it
        looks. A frame IS defined by its type; the probe was wrong about where
        the type is written, not about whether frames have one.

      * More fundamentally, the type is the wrong anchor at any spelling. The
        builder LEFT JOINs it — `frame_type_uuid` is nullable and a row is
        created without it — so a row can be perfectly current with no type quad
        at all. A staleness probe must ask about what the builder REQUIRES,
        which is the inner join: the frame is the object of a `hasEdgeSource`
        quad. If that is gone, the row derives from something that no longer
        exists.

    Proven rather than argued: resyncing `prolog_spike_frames` rebuilds all 200
    rows byte-identical, so the table the type-anchored probe called 100% stale
    was not stale at all — it would have sent an operator to a repair that
    changes nothing.

    Bounded by `sample`: one index probe each, so cost is independent of table
    size. Returns 0.0 for an empty table — nothing sampled is not evidence of
    staleness, and `frame_entity_drift` is what reports an unpopulated one.
    """
    t_fe = f"{space_id}_frame_entity"
    t_quad = f"{space_id}_rdf_quad"
    orphans = await conn.fetchval(
        f"""
        SELECT count(*) FROM (
            SELECT frame_uuid, context_uuid FROM {t_fe} LIMIT {int(sample)}
        ) s
        WHERE NOT EXISTS (
            SELECT 1 FROM {t_quad} q
            WHERE q.object_uuid = s.frame_uuid AND q.predicate_uuid = $1
              AND q.context_uuid = s.context_uuid
        )
        """, _ES_UUID)
    checked = await conn.fetchval(
        f"SELECT count(*) FROM (SELECT 1 FROM {t_fe} LIMIT {int(sample)}) s")
    if not checked:
        return 0.0
    return float(orphans or 0) / float(checked)


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
