"""Incremental and full sync for the {space}_entity_slot_sort table.

WHAT IT IS. One row per SLOT reachable by the two-hop membership walk
`entity -Edge_hasEntityKGFrame-> frame -Edge_hasKGSlot-> slot`, carrying that
slot's value and the three types the walk was discriminated by. It exists so a
sort on a slot value — `SortCriteria(sort_type="entity_frame_slot")`, the
"sort leads by Company" shape — becomes an ordered index scan instead of a
six-way join.

WHY, with the number. `issues/096`. Sorting 2,863 KGLeads by a CompanyName slot
walked entity -> frame -> EVERY slot (~24 per frame), fetched the text value for
all 68,683, and only then asked which were CompanyName: 360 ms and 423,742
buffers for 25 rows. Against this table the same page is **4.2 ms and 58
buffers**, and — because the index is ordered by value — it stays flat as the
page deepens (9.5 ms at offset 500, 6.1 ms at offset 2000) rather than growing
with OFFSET. Prototyped on `prod_kg` before being built: 126,452 rows, 38 MB,
1.6% of that space's quad table, covering all 99 of its slot types.

WHY NOT THE OTHER OPTIONS, since a derived table is the expensive answer:

  * Extended statistics on `(predicate_uuid, object_uuid)` are already in place
    and already working — the SCAN estimates are good. The misplan is JOIN
    selectivity collapsing to `rows=1` across six joins, which per-table
    statistics do not describe.
  * The semi-join rewrite, which is what rescued the analogous high-cardinality
    FILTER queries, is structurally unavailable to a SORT. `semijoin.py:736`:
    "a semi-join collapses the right side to its join key, so a projected value
    could not be produced from it" — and a sort must project the value it sorts
    by. `:753` refuses to cross a GROUP BY at all.
  * `frame_entity` indexes CONNECTOR frames (a frame joining two entities), not
    entity->frame membership. Different relation; it cannot serve this walk.

CATEGORY: STRUCTURAL MIRROR (`planning_sql/derived_table_maintenance.md`).
Absence is a WRONG ORDER, not a slow one, so there is no acceptable staleness
window and this is maintained incrementally on every write path. It is the third
such table, and the two that came before it have both shipped stale in
production — `issues/041` (empty on every space) and an edge table once ~25%
incomplete — which is why the drift probe and the resync exist here from the
start rather than being added after the first incident.

COVERAGE: NESTED FRAMES, to `MAX_FRAME_DEPTH`. The walk is
`entity -Edge_hasEntityKGFrame-> frame ( -Edge_hasKGFrame-> frame )*
-Edge_hasKGSlot-> slot`, and `frame_type_path` holds the ordered frame types
from the entity down to the slot's parent.

The first version stopped at ONE hop and stored a single `frame_type_uuid`. That
silently excluded every slot under a child frame — on `prod_kg`,
`GuarantorEmail` and `GuarantorPhone`, 2,863 each, reachable only through
`PersonalGuarantorContactFrame`, which is reached by `Edge_hasKGFrame` 2,863
times and by `Edge_hasEntityKGFrame` zero times. Two of the eight columns the
portal's lead list renders were simply absent, and nothing about the table said
so. Storing the PATH rather than one level is what fixed it.

STILL NOT A GENERAL SLOT PROJECTION, for a different reason now. Every row is
reached through at least one frame, so a slot attached DIRECTLY to an entity
(`entity -Edge_hasKGSlot-> slot`, which `sort_type="frame_slot"` with an empty
`frame_path` describes) is not here. `fast_slot_sort` declines that shape rather
than answering it from frame-borne rows, which would be a wrong answer rather
than a slow one.

DEPENDS ON `edge`, so edge sync runs first, exactly as `frame_entity` does. An
incomplete edge table yields an incomplete table here; that is inherited, not
introduced.

All functions take an asyncpg connection already inside a transaction.
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

logger = logging.getLogger(__name__)

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
CORE = "http://vital.ai/ontology/vital-core#"

ENTITY_FRAME_EDGE_URI = f"{HALEY}Edge_hasEntityKGFrame"
SLOT_EDGE_URI = f"{HALEY}Edge_hasKGSlot"
CHILD_FRAME_EDGE_URI = f"{HALEY}Edge_hasKGFrame"
SLOT_TYPE_URI = f"{HALEY}hasKGSlotType"
FRAME_TYPE_URI = f"{HALEY}hasKGFrameType"
ENTITY_TYPE_URI = f"{HALEY}hasKGEntityType"

# Every predicate a KGSlot can carry its value under. Enumerated rather than
# matched by name: a `LIKE '%SlotValue'` would also pick up a future predicate
# nobody has considered, and this table's rows would silently change meaning.
# Kept in sync with `KGQueryCriteriaBuilder._get_slot_value_property`.
SLOT_VALUE_URIS = (
    f"{HALEY}hasTextSlotValue",
    f"{HALEY}hasBooleanSlotValue",
    f"{HALEY}hasDateTimeSlotValue",
    f"{HALEY}hasIntegerSlotValue",
    f"{HALEY}hasDoubleSlotValue",
    f"{HALEY}hasCurrencySlotValue",
    f"{HALEY}hasUriSlotValue",
    f"{HALEY}hasChoiceSlotValue",
    f"{HALEY}hasJsonSlotValue",
    f"{HALEY}hasLongSlotValue",
)

# Deterministic UUID namespace (same as sparql_sql_space_impl).
_VITALGRAPH_NS = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')


def _u(uri: str) -> uuid.UUID:
    """Term uuid for a URI, by the same rule the write path uses."""
    return uuid.uuid5(_VITALGRAPH_NS, f"{uri}\x00U")


_ENTITY_FRAME_EDGE = _u(ENTITY_FRAME_EDGE_URI)
_SLOT_EDGE = _u(SLOT_EDGE_URI)
_CHILD_FRAME_EDGE = _u(CHILD_FRAME_EDGE_URI)
_SLOT_TYPE = _u(SLOT_TYPE_URI)
_FRAME_TYPE = _u(FRAME_TYPE_URI)
_ENTITY_TYPE = _u(ENTITY_TYPE_URI)
_SLOT_VALUE_PREDS = [_u(x) for x in SLOT_VALUE_URIS]


# How many frame hops the walk will follow below the entity. Measured on
# `prod_kg`: real nesting reaches depth 3 (41,730 frames at 1, 18,551 at 2,
# 6 at 3) and terminates, so 6 is slack rather than a limit anyone is near.
#
# It exists because nothing in the model forbids a frame cycle, and a recursive
# CTE that meets one does not return. A bounded walk that misses a hypothetical
# depth-7 frame degrades to "the sort falls back to SPARQL for it"; an unbounded
# one that meets a cycle takes the connection down.
MAX_FRAME_DEPTH = 6


def _select_rows(space_id: str, where: str, *, seed_param: str = None) -> str:
    """The derivation itself: the walk, as one SELECT.

    Used verbatim by the full resync, the backfill and the incremental
    re-derive, so those three cannot disagree about what the table means. That
    they CAN disagree is how `edge` ended up with an `ensure` path and a
    `resync` path that were both defective in different ways
    (`edge_table_integrity_bug.md`).

    The walk is `entity -Edge_hasEntityKGFrame-> frame ( -Edge_hasKGFrame->
    frame )* -Edge_hasKGSlot-> slot`, and `frame_type_path` records the ordered
    frame types from the entity down to the slot's parent — which is exactly
    what a `SortCriteria.frame_path` names, so the read side matches the whole
    array rather than one level.

    Storing a PATH rather than the immediate frame type is what makes nested
    frames representable at all. The first version stored a single
    `frame_type_uuid`, which silently excluded every slot under a child frame:
    on `prod_kg` that was `GuarantorEmail` and `GuarantorPhone`, 2,863 each,
    reachable only through `PersonalGuarantorContactFrame` — a child frame.

    `$1..$5` are the discriminating type uuids, `$6` the value predicates.
    `where` supplies the incremental restriction and its own parameters.
    """
    t_edge = f"{space_id}_edge"
    t_quad = f"{space_id}_rdf_quad"
    t_term = f"{space_id}_term"
    # SEEDS the recursion; it used not to, and that was the whole cost.
    #
    # The base case selected EVERY entity->frame edge in the space, and the
    # touched-set filter sat in the outer SELECT where PostgreSQL cannot push
    # it into a recursive CTE. So an incremental write materialised the entire
    # frame graph and discarded nearly all of it. Measured on production:
    # 9,147 ms to produce 15 rows for 16 subjects, and the statement had burned
    # 3.7 hours of database time within hours of the deploy (mean 9,575 ms,
    # max 58,173 ms). Cost tracked the SPACE, not the change — lead_prod, a
    # quarter the size, cost a quarter as much.
    #
    # Seeded from the affected roots: 107 ms for the same 15 rows, and 1,011 ms
    # against 20,844 ms for 323 rows at 64 subjects. Row-identical to the
    # unseeded form in both, verified on production data.
    #
    # `seed_param` stays None for the full resync and the backfill, which must
    # walk everything. `_frame_roots` explains why a SUPERSET of roots is what
    # makes the seeded form provably equivalent.
    _seed = f" AND fe.source_node_uuid = ANY({seed_param})" if seed_param else ""
    return f"""
        WITH RECURSIVE frame_walk AS (
            -- Level 1: frames hanging directly off an entity.
            SELECT
                fe.source_node_uuid AS entity_uuid,
                fe.dest_node_uuid   AS frame_uuid,
                fe.context_uuid     AS context_uuid,
                ARRAY[ft.object_uuid] AS frame_type_path,
                -- The frame UUIDs walked, not stored — the incremental
                -- re-derive needs to match a touched INTERMEDIATE frame, and
                -- only the slot's immediate parent survives into the row.
                ARRAY[fe.dest_node_uuid] AS frame_uuid_path,
                1 AS depth
            FROM {t_edge} fe
            LEFT JOIN {t_quad} ft
              ON ft.subject_uuid = fe.dest_node_uuid
             AND ft.predicate_uuid = $4
             AND ft.context_uuid = fe.context_uuid
            WHERE fe.edge_type_uuid = $1{_seed}

            UNION ALL

            -- Child frames, appending their type to the path.
            SELECT
                w.entity_uuid,
                ce.dest_node_uuid,
                ce.context_uuid,
                w.frame_type_path || ft2.object_uuid,
                w.frame_uuid_path || ce.dest_node_uuid,
                w.depth + 1
            FROM frame_walk w
            JOIN {t_edge} ce
              ON ce.source_node_uuid = w.frame_uuid
             AND ce.context_uuid = w.context_uuid
             AND ce.edge_type_uuid = $7
            LEFT JOIN {t_quad} ft2
              ON ft2.subject_uuid = ce.dest_node_uuid
             AND ft2.predicate_uuid = $4
             AND ft2.context_uuid = ce.context_uuid
            WHERE w.depth < {MAX_FRAME_DEPTH}
        )
        SELECT
            slot_e.dest_node_uuid          AS slot_uuid,
            slot_e.context_uuid            AS context_uuid,
            frame_w.entity_uuid            AS entity_uuid,
            slot_e.source_node_uuid        AS frame_uuid,
            ent_t.object_uuid              AS entity_type_uuid,
            frame_w.frame_type_path        AS frame_type_path,
            slt_t.object_uuid              AS slot_type_uuid,
            val_t.term_text                AS value_text,
            val_t.num_val                  AS value_num,
            val_t.dt_val                   AS value_dt
        FROM frame_walk frame_w
        JOIN {t_edge} slot_e
          ON slot_e.source_node_uuid = frame_w.frame_uuid
         AND slot_e.context_uuid = frame_w.context_uuid
         AND slot_e.edge_type_uuid = $2
        -- The slot's type. INNER: a slot with no type cannot be selected by a
        -- sort criterion, so a row for it would never be read.
        JOIN {t_quad} slt_t
          ON slt_t.subject_uuid = slot_e.dest_node_uuid
         AND slt_t.predicate_uuid = $3
         AND slt_t.context_uuid = slot_e.context_uuid
        -- The value. INNER for the same reason: the sort orders BY this, and
        -- the generated SPARQL joins it as a required triple, so a valueless
        -- slot is absent from the answer either way.
        JOIN {t_quad} val_q
          ON val_q.subject_uuid = slot_e.dest_node_uuid
         AND val_q.predicate_uuid = ANY($6)
         AND val_q.context_uuid = slot_e.context_uuid
        JOIN {t_term} val_t ON val_t.term_uuid = val_q.object_uuid
        -- Entity type is LEFT for the same reason the frame types are, and the
        -- frame types are LEFT inside the walk above: an untyped entity or
        -- frame is still part of the graph, and an inner join would DROP it
        -- from the table — changing which rows it describes rather than only
        -- how fast it answers. An untyped level leaves a NULL in the path,
        -- which no typed criterion can match, which is the same answer SPARQL
        -- gives since it joins `hasKGFrameType` as a required triple.
        LEFT JOIN {t_quad} ent_t
          ON ent_t.subject_uuid = frame_w.entity_uuid
         AND ent_t.predicate_uuid = $5
         AND ent_t.context_uuid = frame_w.context_uuid
        WHERE {where}
    """


_INSERT_COLS = ("slot_uuid, context_uuid, entity_uuid, frame_uuid, "
                "entity_type_uuid, frame_type_path, slot_type_uuid, "
                "value_text, value_num, value_dt")

# One row per (slot, context). A slot carrying two different value predicates
# would otherwise produce two rows and double-count in a MIN/MAX; keeping the
# first is deterministic and matches what the SPARQL form returns, which also
# takes one value per slot.
_ON_CONFLICT = "ON CONFLICT (slot_uuid, context_uuid) DO NOTHING"


async def _type_args(space_id: str):
    return [_ENTITY_FRAME_EDGE, _SLOT_EDGE, _SLOT_TYPE, _FRAME_TYPE,
            _ENTITY_TYPE, _SLOT_VALUE_PREDS, _CHILD_FRAME_EDGE]


# ---------------------------------------------------------------------------
# Incremental — drop and re-derive, the same shape frame_entity uses
# ---------------------------------------------------------------------------

# A write can touch any node on the walk. Resolving a touched SLOT or EDGE back
# to the rows it invalidates is what makes an UPDATE work: repointing a slot's
# value touches only the slot, so a delete keyed on the entity would match
# nothing, the re-derive would hit ON CONFLICT DO NOTHING, and the row would
# keep the OLD value forever. The row COUNT never changes in that failure, so no
# drift check can see it — exactly the defect `sync_frame_entity_before_delete`
# documents having shipped.
_TOUCHED_FILTER = """
    (slot_uuid = ANY($1)
     OR entity_uuid = ANY($1)
     OR frame_uuid = ANY($1)
     OR slot_uuid IN (SELECT dest_node_uuid FROM {t_edge}
                      WHERE edge_uuid = ANY($1))
     OR frame_uuid IN (SELECT dest_node_uuid FROM {t_edge}
                       WHERE edge_uuid = ANY($1)))
"""


async def sync_entity_slot_sort_before_delete(
    conn, space_id: str, subject_uuids: List[uuid.UUID],
    context_uuid: Optional[uuid.UUID] = None,
) -> int:
    """Before quads are deleted, drop the rows they invalidate."""
    if not subject_uuids:
        return 0
    t = f"{space_id}_entity_slot_sort"
    where = _TOUCHED_FILTER.format(t_edge=f"{space_id}_edge")
    if context_uuid:
        result = await conn.execute(
            f"DELETE FROM {t} WHERE {where} AND context_uuid = $2",
            subject_uuids, context_uuid)
    else:
        result = await conn.execute(
            f"DELETE FROM {t} WHERE {where}", subject_uuids)
    deleted = int(result.split()[-1]) if result else 0
    if deleted:
        logger.debug("entity_slot_sort before_delete(%s): %d rows",
                     space_id, deleted)
    return deleted



async def _frame_roots(conn, space_id: str, touched_uuids: List[uuid.UUID]):
    """Entity roots whose frame walk could reach anything in *touched_uuids*.

    Climbs UP the edge table — dest_node_uuid -> source_node_uuid — from every
    touched node, and from the destination of every touched EDGE uuid, to
    `MAX_FRAME_DEPTH`. Uses `idx_{space}_edge_dst_src`; measured 58-164 ms on a
    3.2M-row edge table.

    DELIBERATELY A SUPERSET. The climb returns intermediate frames as well as
    true entity roots, and it does not try to mirror the six disjuncts of the
    caller's WHERE (touched slot, touched entity, touched frame in the path,
    touched slot edge, and two edge_uuid -> dest_node_uuid indirections).
    Matching those one for one is where this would go wrong: a disjunct missed
    is a row not derived, and `issues/096` records that a wrong
    entity_slot_sort produces wrong SORT RESULTS, not merely a slow query.

    Over-approximating is safe by construction. Extra seeds only add candidate
    walks, and the outer WHERE that selects rows is unchanged, so a superset
    cannot lose a row — it can only do slightly more work. That property is
    what makes the seeded walk provably equivalent rather than equivalent-by-
    inspection, and it is what the equivalence test pins.
    """
    if not touched_uuids:
        return []
    t_edge = f"{space_id}_edge"
    rows = await conn.fetch(f"""
        WITH RECURSIVE seed AS (
            SELECT unnest($1::uuid[]) AS n
            UNION
            SELECT dest_node_uuid FROM {t_edge} WHERE edge_uuid = ANY($1)
        ), climb AS (
            SELECT n, 0 AS d FROM seed
            UNION ALL
            SELECT e.source_node_uuid, c.d + 1
              FROM climb c
              JOIN {t_edge} e ON e.dest_node_uuid = c.n
             WHERE c.d < {MAX_FRAME_DEPTH}
        )
        SELECT DISTINCT n FROM climb
    """, touched_uuids)
    return [r["n"] for r in rows]


async def sync_entity_slot_sort_after_edge_insert(
    conn, space_id: str, touched_uuids: List[uuid.UUID],
) -> int:
    """After edge rows are inserted, derive the rows the write created.

    Deletes first, so a CHANGED value replaces its row rather than losing to
    ON CONFLICT DO NOTHING. Insert-only would make an update a silent no-op.
    """
    if not touched_uuids:
        return 0
    t = f"{space_id}_entity_slot_sort"
    t_edge = f"{space_id}_edge"

    await sync_entity_slot_sort_before_delete(conn, space_id, touched_uuids)

    # Re-derive over exactly the reach the delete used. The two are written to
    # mirror each other on purpose: a re-derive narrower than its delete drops
    # rows silently, and one wider than its delete is merely wasted work. The
    # `edge_uuid` sub-selects are the same resolution `_TOUCHED_FILTER` does.
    #
    # `frame_uuid_path && ...` is array OVERLAP, which is what catches a touched
    # INTERMEDIATE frame: only the slot's immediate parent reaches the row, so
    # matching on `frame_uuid` alone would miss a change two levels up and leave
    # every descendant slot describing the old graph.
    where = f"""
        (slot_e.dest_node_uuid = ANY($8)
         OR frame_w.entity_uuid = ANY($8)
         OR frame_w.frame_uuid_path && $8
         OR slot_e.edge_uuid = ANY($8)
         OR slot_e.dest_node_uuid IN (
              SELECT dest_node_uuid FROM {t_edge} WHERE edge_uuid = ANY($8))
         OR frame_w.frame_uuid_path && ARRAY(
              SELECT dest_node_uuid FROM {t_edge} WHERE edge_uuid = ANY($8)))
    """
    args = await _type_args(space_id)
    roots = await _frame_roots(conn, space_id, touched_uuids)
    if not roots:
        # Nothing in the graph reaches the touched set, so the walk would
        # derive nothing. The delete above still stands, which is correct:
        # rows that referenced these subjects are gone.
        return 0
    result = await conn.execute(
        f"INSERT INTO {t} ({_INSERT_COLS}) "
        f"{_select_rows(space_id, where, seed_param='$9')} {_ON_CONFLICT}",
        *args, touched_uuids, roots)
    inserted = int(result.split()[-1]) if result else 0
    if inserted:
        logger.debug("entity_slot_sort after_insert(%s): %d rows",
                     space_id, inserted)
    return inserted


async def delete_entity_slot_sort_for_context(conn, space_id: str,
                                              context_uuid: uuid.UUID) -> int:
    """Drop every row for one graph. Pairs with clear/drop graph."""
    t = f"{space_id}_entity_slot_sort"
    result = await conn.execute(
        f"DELETE FROM {t} WHERE context_uuid = $1", context_uuid)
    return int(result.split()[-1]) if result else 0


# ---------------------------------------------------------------------------
# Full rebuild and repair
# ---------------------------------------------------------------------------

async def resync_entity_slot_sort(conn, space_id: str) -> int:
    """TRUNCATE and rebuild from the graph. For bulk loads and recovery."""
    t = f"{space_id}_entity_slot_sort"
    await conn.execute(f"TRUNCATE {t}")
    args = await _type_args(space_id)
    result = await conn.execute(
        f"INSERT INTO {t} ({_INSERT_COLS}) "
        f"{_select_rows(space_id, 'TRUE')} {_ON_CONFLICT}", *args)
    rows = int(result.split()[-1]) if result else 0
    logger.info("resync_entity_slot_sort(%s): %d rows", space_id, rows)
    return rows


async def backfill_entity_slot_sort(conn, space_id: str) -> int:
    """Insert missing rows WITHOUT truncating.

    Takes only ROW EXCLUSIVE, so the maintenance job can repair drift while
    queries keep reading — the same reason `backfill_edge_table` exists rather
    than the drift detector calling the resync.
    """
    t = f"{space_id}_entity_slot_sort"
    args = await _type_args(space_id)
    result = await conn.execute(
        f"INSERT INTO {t} ({_INSERT_COLS}) "
        f"{_select_rows(space_id, 'TRUE')} {_ON_CONFLICT}", *args)
    rows = int(result.split()[-1]) if result else 0
    if rows:
        logger.info("backfill_entity_slot_sort(%s): %d rows added", space_id, rows)
    return rows


async def entity_slot_sort_drift(conn, space_id: str) -> tuple[int, int]:
    """`(expected, actual)` row counts — the order `frame_entity_drift` uses,
    so `_run_*_integrity` reads `drift = expected - actual` for both.

    Counts the derivation rather than sampling it. A cheaper probe would have to
    assume which direction drift takes, and both have been seen: `041` left
    tables EMPTY, while a delete path that does not clean up leaves them TOO
    FULL.

    WHAT THIS CANNOT SEE: a row whose key is intact but whose VALUE is stale —
    the count is identical, so no count-based probe can detect it. That is the
    failure mode `sync_frame_entity_before_delete` documents having shipped, and
    it is prevented at the write path by deleting before re-deriving rather than
    detected here. The backfill cannot repair it either: `backfill` only ADDS.
    A space suspected of it needs `resync_entity_slot_sort`.
    """
    t = f"{space_id}_entity_slot_sort"
    actual = await conn.fetchval(f"SELECT count(*) FROM {t}")
    args = await _type_args(space_id)
    expected = await conn.fetchval(
        f"SELECT count(*) FROM (SELECT DISTINCT slot_uuid, context_uuid FROM ("
        f"{_select_rows(space_id, 'TRUE')}) s) d", *args)
    return int(expected or 0), int(actual or 0)
