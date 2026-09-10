"""Build `{space}_frame_slot` — the frame collapse without hardcoded roles.

`frame_entity` names two `hasKGSlotType` VALUES in its columns
(`source_entity_uuid`, `dest_entity_uuid`) and its builder filters to them.
Those values are data, not schema: another frame schema uses different ones, or
more than two slots per frame, and gets no collapse and no warning
(`issues/183`).

This table keeps the role as data — one row per (frame, slot):

    frame_uuid  slot_uuid  role_uuid  entity_uuid  context_uuid  frame_type_uuid

so a query arm collapses to one join carrying `role_uuid = <that arm's
constant>`, whatever the constant happens to be.

WHAT IT DOES NOT DO. It does not decide which slots are "interesting". Every
slot reachable from a frame through `Edge_hasKGSlot` and carrying a
`hasKGSlotType` gets a row, including one with no `hasEntitySlotValue` — that
slot is still a slot of that frame, and filtering it out here would change which
frames the table describes rather than only how fast it answers.
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

logger = logging.getLogger(__name__)

SLOT_TYPE_URI = "http://vital.ai/ontology/haley-ai-kg#hasKGSlotType"
SLOT_VALUE_URI = "http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue"
VITALTYPE_URI = "http://vital.ai/ontology/vital-core#vitaltype"

_VITALGRAPH_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def _term_uuid(text: str) -> uuid.UUID:
    return uuid.uuid5(_VITALGRAPH_NS, f"{text}\x00U")


_SLOT_TYPE_UUID = _term_uuid(SLOT_TYPE_URI)
_SLOT_VALUE_UUID = _term_uuid(SLOT_VALUE_URI)
_VITALTYPE_UUID = _term_uuid(VITALTYPE_URI)


async def resync_frame_slot_table(conn, space_id: str) -> int:
    """Rebuild the whole table. Returns rows inserted."""
    t_fs = f"{space_id}_frame_slot"
    t_edge = f"{space_id}_edge"
    t_quad = f"{space_id}_rdf_quad"

    await conn.execute(f"TRUNCATE {t_fs}")
    result = await conn.execute(f"""
        INSERT INTO {t_fs} (frame_uuid, slot_uuid, role_uuid, entity_uuid,
                            context_uuid, frame_type_uuid)
        SELECT DISTINCT ON (emv.source_node_uuid, emv.dest_node_uuid, emv.context_uuid)
            emv.source_node_uuid,
            emv.dest_node_uuid,
            st.object_uuid,          -- the ROLE, as data. No filter.
            sv.object_uuid,
            emv.context_uuid,
            vt.object_uuid
        FROM {t_edge} emv
        JOIN {t_quad} st
          ON st.subject_uuid = emv.dest_node_uuid
         AND st.predicate_uuid = $1
        -- LEFT, deliberately: a slot with a role but no value is still a slot
        -- of this frame (see the module docstring).
        LEFT JOIN {t_quad} sv
          ON sv.subject_uuid = emv.dest_node_uuid
         AND sv.predicate_uuid = $2
        LEFT JOIN {t_quad} vt
          ON vt.subject_uuid = emv.source_node_uuid
         AND vt.context_uuid = emv.context_uuid
         AND vt.predicate_uuid = $3
    """, _SLOT_TYPE_UUID, _SLOT_VALUE_UUID, _VITALTYPE_UUID)

    n = int(result.split()[-1]) if result else 0
    logger.info("resync_frame_slot_table(%s): %d rows inserted", space_id, n)
    return n


async def backfill_frame_slot_table(
        conn, space_id: str, timeout: float | None = None) -> int:
    """Add only the MISSING frame_slot rows — no TRUNCATE, no rebuild.

    The non-blocking counterpart of `resync_frame_slot_table`, which TRUNCATEs
    and holds ACCESS EXCLUSIVE: a plain `INSERT ... ON CONFLICT DO NOTHING`
    taking only ROW EXCLUSIVE, so concurrent frame-slot queries keep running.

    Omitted when `frame_entity` was retired (`issues/183`), along with
    `cleanup_stale_frame_slot`, which left the maintenance self-heal path with
    only the blocking rebuild. Row validity is defined exactly as the resync
    defines it, and the role is carried as DATA — `st.object_uuid` is selected,
    never compared against a URI this module names.
    """
    t_fs = f"{space_id}_frame_slot"
    t_edge = f"{space_id}_edge"
    t_quad = f"{space_id}_rdf_quad"

    result = await conn.execute(f"""
        INSERT INTO {t_fs} (frame_uuid, slot_uuid, role_uuid, entity_uuid,
                            context_uuid, frame_type_uuid)
        SELECT DISTINCT ON (emv.source_node_uuid, emv.dest_node_uuid, emv.context_uuid)
            emv.source_node_uuid,
            emv.dest_node_uuid,
            st.object_uuid,
            sv.object_uuid,
            emv.context_uuid,
            vt.object_uuid
        FROM {t_edge} emv
        JOIN {t_quad} st
          ON st.subject_uuid = emv.dest_node_uuid
         AND st.predicate_uuid = $1
        LEFT JOIN {t_quad} sv
          ON sv.subject_uuid = emv.dest_node_uuid
         AND sv.predicate_uuid = $2
        LEFT JOIN {t_quad} vt
          ON vt.subject_uuid = emv.source_node_uuid
         AND vt.context_uuid = emv.context_uuid
         AND vt.predicate_uuid = $3
        ON CONFLICT DO NOTHING
    """, _SLOT_TYPE_UUID, _SLOT_VALUE_UUID, _VITALTYPE_UUID, timeout=timeout)

    inserted = int(result.split()[-1]) if result else 0
    if inserted:
        await conn.execute(f"ANALYZE {t_fs}", timeout=timeout)
    logger.info("backfill_frame_slot_table(%s): %d rows inserted",
                space_id, inserted)
    return inserted


async def frame_slot_row_count(conn, space_id: str) -> int:
    return await conn.fetchval(f"SELECT count(*) FROM {space_id}_frame_slot")


async def _forced(conn, sql, *args):
    """Run with a CUSTOM plan.

    `sync_frame_entity_table` measured the reason: PostgreSQL switches a
    prepared statement to a GENERIC plan after five executions, and for this
    shape — an array of touched uuids, where the right plan depends entirely on
    how many there are — it is catastrophically wrong. Measured there: ~1 ms for
    runs 1-5, then EIGHT SECONDS from run six onward, permanently, because a
    prepared statement lives as long as the pooled connection.
    """
    if conn.is_in_transaction():
        await conn.execute("SET LOCAL plan_cache_mode = force_custom_plan")
        return await conn.execute(sql, *args)
    async with conn.transaction():
        await conn.execute("SET LOCAL plan_cache_mode = force_custom_plan")
        return await conn.execute(sql, *args)


async def sync_frame_slot_after_edge_insert(conn, space_id: str,
                                            touched_uuids: List[uuid.UUID]) -> int:
    """Re-derive `frame_slot` rows for every frame a write touched.

    A frame is affected if the write touched the frame, one of its slots, or the
    edge joining them — all three positions are matched. `sync_frame_entity_table`
    records what matching only the frame cost: repointing a slot's
    `hasEntitySlotValue` touches the SLOT, nothing matched, and the derived table
    kept naming the old entity — silently, with the row count unchanged, so no
    drift check could see it.

    `DO UPDATE`, not `DO NOTHING`. The frame-entity path pairs DO NOTHING with a
    delete-first call; if that delete is ever missed the stale row survives. An
    upsert cannot go stale that way and costs nothing when the row is unchanged.
    """
    if not touched_uuids:
        return 0
    t_fs = f"{space_id}_frame_slot"
    t_edge = f"{space_id}_edge"
    t_quad = f"{space_id}_rdf_quad"

    from .sync_edge_table import chunk_uuids

    n = 0
    for chunk in chunk_uuids(touched_uuids):
        result = await _forced(conn, f"""
            INSERT INTO {t_fs} (frame_uuid, slot_uuid, role_uuid, entity_uuid,
                                context_uuid, frame_type_uuid)
            SELECT DISTINCT ON (emv.source_node_uuid, emv.dest_node_uuid, emv.context_uuid)
                emv.source_node_uuid, emv.dest_node_uuid, st.object_uuid,
                sv.object_uuid, emv.context_uuid, vt.object_uuid
            FROM {t_edge} emv
            JOIN {t_quad} st
              ON st.subject_uuid = emv.dest_node_uuid AND st.predicate_uuid = $1
            LEFT JOIN {t_quad} sv
              ON sv.subject_uuid = emv.dest_node_uuid AND sv.predicate_uuid = $2
            LEFT JOIN {t_quad} vt
              ON vt.subject_uuid = emv.source_node_uuid
             AND vt.context_uuid = emv.context_uuid
             AND vt.predicate_uuid = $3
            WHERE emv.source_node_uuid IN (
                    SELECT e2.source_node_uuid FROM {t_edge} e2
                    WHERE e2.source_node_uuid = ANY($4)
                       OR e2.dest_node_uuid = ANY($4)
                       OR e2.edge_uuid = ANY($4))
            ON CONFLICT (frame_uuid, slot_uuid, context_uuid) DO UPDATE
               SET role_uuid       = EXCLUDED.role_uuid,
                   entity_uuid     = EXCLUDED.entity_uuid,
                   frame_type_uuid = EXCLUDED.frame_type_uuid
        """, _SLOT_TYPE_UUID, _SLOT_VALUE_UUID, _VITALTYPE_UUID, chunk)
        n += int(result.split()[-1]) if result else 0
    if n:
        logger.debug("sync_frame_slot_after_edge_insert(%s): %d row(s)", space_id, n)
    return n


async def sync_frame_slot_before_delete(conn, space_id: str,
                                        subject_uuids: List[uuid.UUID],
                                        context_uuid: Optional[uuid.UUID] = None) -> int:
    """Drop `frame_slot` rows a pending delete invalidates.

    Resolves slots and edges back to their frame, for the reason the
    frame-entity twin records: deleting only `frame_uuid = ANY(subjects)` misses
    an UPDATE that repoints a slot, because that write touches the slot, not the
    frame.
    """
    if not subject_uuids:
        return 0
    t_fs = f"{space_id}_frame_slot"
    t_edge = f"{space_id}_edge"
    where = f"""(frame_uuid = ANY($1)
                 OR frame_uuid IN (SELECT source_node_uuid FROM {t_edge}
                                   WHERE dest_node_uuid = ANY($1)
                                      OR edge_uuid = ANY($1)))"""
    if context_uuid is not None:
        result = await _forced(conn,
            f"DELETE FROM {t_fs} WHERE {where} AND context_uuid = $2",
            subject_uuids, context_uuid)
    else:
        result = await _forced(conn, f"DELETE FROM {t_fs} WHERE {where}",
                               subject_uuids)
    n = int(result.split()[-1]) if result else 0
    if n:
        logger.debug("sync_frame_slot_before_delete(%s): %d row(s)", space_id, n)
    return n


_FS_SWEEP_SCAN_ROWS = 50_000
_fs_sweep_cursor: dict = {}


async def cleanup_stale_frame_slot(conn, space_id: str,
                                   limit: int = 50_000,
                                   scan_rows: int = _FS_SWEEP_SCAN_ROWS) -> int:
    """Remove frame_slot rows whose defining chain is gone. Bounded.

    The delete-side counterpart. `sync_frame_slot_before_delete` needs a frame
    uuid list, which a SPARQL UPDATE cannot produce for WHERE-bound subjects, so
    without this those deletions leave rows asserting a slot that no longer
    exists (`issues/064` for the table this replaces). Omitting it when
    `frame_entity` was retired for `frame_slot` reintroduced exactly that
    defect: 14 rows survived a DROP GRAPH, and 14 more kept naming the old
    entity after a slot was repointed — invisible to any drift check, because a
    stale row is an EXTRA row and the counts still matched.

    Validity is defined exactly as `resync_frame_slot_table` defines it, and
    ROLE-AGNOSTICALLY: the frame must still reach THIS slot, and the slot must
    still carry the recorded role and the recorded entity. The role is read from
    the row, never named here — it is a data value, not schema (`issues/183`).

    Bounded and a plain DELETE, so it takes ROW EXCLUSIVE and does not block
    readers the way the resync's TRUNCATE does.
    """
    t_fs = f"{space_id}_frame_slot"
    t_edge = f"{space_id}_edge"
    t_quad = f"{space_id}_rdf_quad"

    cursor = _fs_sweep_cursor.get(space_id) or "(0,0)"
    rows = await conn.fetch(f"""
        SELECT fs.ctid::text AS ctid,
               (NOT EXISTS (
                    SELECT 1
                    FROM {t_edge} emv
                    JOIN {t_quad} st ON st.subject_uuid = emv.dest_node_uuid
                        AND st.predicate_uuid = $1
                        AND st.object_uuid = fs.role_uuid
                    JOIN {t_quad} sv ON sv.subject_uuid = emv.dest_node_uuid
                        AND sv.predicate_uuid = $2
                        AND sv.object_uuid = fs.entity_uuid
                    WHERE emv.source_node_uuid = fs.frame_uuid
                      AND emv.dest_node_uuid = fs.slot_uuid
                      AND emv.context_uuid = fs.context_uuid)) AS stale
        FROM (
            SELECT ctid, frame_uuid, slot_uuid, role_uuid, entity_uuid,
                   context_uuid
            FROM {t_fs}
            WHERE ctid > $3::text::tid
            ORDER BY ctid
            LIMIT {int(scan_rows)}
        ) fs
    """, _SLOT_TYPE_UUID, _SLOT_VALUE_UUID, cursor)

    if not rows:
        _fs_sweep_cursor[space_id] = None       # end of table: wrap next pass
        return 0
    _fs_sweep_cursor[space_id] = rows[-1]["ctid"]

    stale_ctids = [r["ctid"] for r in rows if r["stale"]][:int(limit)]
    if not stale_ctids:
        return 0

    result = await conn.execute(
        f"DELETE FROM {t_fs} WHERE ctid = ANY($1::text[]::tid[])", stale_ctids)
    deleted = int(result.split()[-1]) if result else 0
    if deleted:
        logger.info("cleanup_stale_frame_slot(%s): removed %d stale row(s) "
                    "from a %d-row window", space_id, deleted, len(rows))
    return deleted


async def delete_frame_slot_for_context(conn, space_id: str,
                                        context_uuid: uuid.UUID) -> int:
    """Drop every row for one graph — the counterpart of a graph-level delete."""
    result = await conn.execute(
        f"DELETE FROM {space_id}_frame_slot WHERE context_uuid = $1", context_uuid)
    return int(result.split()[-1]) if result else 0


async def frame_slot_drift(conn, space_id: str, timeout: float = None) -> tuple:
    """(expected, actual) row counts for `{space}_frame_slot`.

    Expected is one row per (frame, slot, context) reachable through
    `Edge_hasKGSlot` where the slot carries a `hasKGSlotType` — the same
    condition the builder uses, with no role filter, because there is no
    privileged role (`issues/183`).
    """
    t_fs = f"{space_id}_frame_slot"
    t_edge = f"{space_id}_edge"
    t_quad = f"{space_id}_rdf_quad"
    expected = await conn.fetchval(f"""
        SELECT count(*) FROM (
          SELECT DISTINCT emv.source_node_uuid, emv.dest_node_uuid, emv.context_uuid
          FROM {t_edge} emv
          JOIN {t_quad} st ON st.subject_uuid = emv.dest_node_uuid
           AND st.predicate_uuid = $1) x""", _SLOT_TYPE_UUID)
    actual = await conn.fetchval(f"SELECT count(*) FROM {t_fs}")
    return int(expected or 0), int(actual or 0)


async def frame_slot_orphan_rate(conn, space_id: str) -> float:
    """Fraction of rows whose frame no longer has the edge that produced them.

    Counts agreeing does NOT mean the rows are right. A space reloaded in place,
    or under a new graph URI, leaves this table a faithful materialisation of
    the PREVIOUS contents: same size, disjoint set, drift zero, every traversal
    empty. `issues/041` is that failure, and only a referential probe sees it.
    """
    t_fs = f"{space_id}_frame_slot"
    t_edge = f"{space_id}_edge"
    total = await conn.fetchval(f"SELECT count(*) FROM {t_fs}")
    if not total:
        return 0.0
    orphans = await conn.fetchval(f"""
        SELECT count(*) FROM {t_fs} fs
        WHERE NOT EXISTS (
          SELECT 1 FROM {t_edge} e
          WHERE e.source_node_uuid = fs.frame_uuid
            AND e.dest_node_uuid  = fs.slot_uuid
            AND e.context_uuid    = fs.context_uuid)""")
    return float(orphans or 0) / float(total)
