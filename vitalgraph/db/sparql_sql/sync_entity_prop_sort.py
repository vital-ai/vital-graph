"""Incremental and full sync for the {space}_entity_prop_sort table.

WHAT IT IS. One row per (entity, context, DIRECT property) for the properties
the entity listing can sort or filter on — `_FILTERABLE_ENTITY_PROPERTIES` in
`kgentities_model.py`. It is the sibling of `entity_slot_sort` with the frame
walk removed, and it exists for the same reason: a sort or filter on one of
these properties is O(total) against the quad table and O(page) against an
ordered index here.

WHY IT IS SIMPLER THAN ITS SIBLING, which is the whole point. `entity_slot_sort`
walks `entity -> frame ( -> frame )* -> slot -> value` and paid for it twice —
once in a recursive CTE that had to be seeded, once in a `frame_type_path` that
had to replace a single frame type after nested-frame slots were found missing.
These properties hang STRAIGHT OFF the entity. There is no walk, so there is no
seeding problem, no depth bound, and no path column. A write touches the entity
subject directly, so the invalidation filter is `entity_uuid = ANY($1)` rather
than the six-disjunct touched-set filter that module needs.

THE ROW CARRIES TWO THINGS, because the two gates want different data:

  * `value_text / value_num / value_dt` hold the MIN. Sorting needs exactly one
    key per entity or an entity with three values is emitted three times.
  * `value_all` holds EVERY value. Every operator the `uri_list` datatype allows
    -- has / has_any / has_all / not_has / not_has_any / exists / not_exists --
    is a membership test, and not one is an ordering comparison, so the MIN
    cannot answer any of them.

`value_all` is populated for every property, not only the `uri_list` one. This is
a general quad store and any predicate may become multi-valued at any time; were
`eq` served from the MIN it would match only the smallest value and return a
subset that still looks like a complete answer.

CATEGORY: STRUCTURAL MIRROR (`planning_sql/derived_table_maintenance.md`).
Absence is a WRONG ANSWER, not a slow one -- a short table makes a sort mis-order
a page and makes a FILTER return a plausible subset -- so there is no acceptable
staleness window, and the drift probe, the coverage probe and the resync exist
here from the start rather than after the first incident. Two earlier derived
tables shipped stale in production before their probes existed (`issues/041`, and
an edge table once ~25% incomplete).

DEPENDS ON NOTHING BUT THE QUADS. Unlike `entity_slot_sort` and `frame_entity`
it does not read `edge`, so an incomplete edge table cannot make it incomplete.

All functions take an asyncpg connection already inside a transaction.
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

logger = logging.getLogger(__name__)

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
CORE = "http://vital.ai/ontology/vital-core#"
VITAL = "http://vital.ai/ontology/vital#"
AIMP = "http://vital.ai/ontology/vital-aimp#"

VITALTYPE_URI = f"{CORE}vitaltype"
ENTITY_TYPE_URI = f"{HALEY}hasKGEntityType"

# The population, and it must match what the read side calls an entity:
# `fast_entity_page` pages `vitaltype IN _KGENTITY_TYPE_URIS`. Duplicated rather
# than imported because that constant lives in `kg_impl`, and the db layer does
# not depend upwards -- `test_entity_prop_sort_population_matches_read_side`
# asserts the two lists agree so the duplication cannot drift silently.
KGENTITY_TYPE_URIS = (
    f"{HALEY}KGEntity",
    f"{HALEY}KGNewsEntity",
    f"{HALEY}KGProductEntity",
    f"{HALEY}KGWebEntity",
)

# The sortable/filterable direct properties, mirroring
# `_FILTERABLE_ENTITY_PROPERTIES`. Same duplication, same reason, and
# `test_entity_prop_sort_properties_match_the_model` asserts they agree: a
# property added to the model but not here would be served by a table that has
# no rows for it, which is the silent-subset failure this table must not have.
SORTABLE_PROPERTY_URIS = (
    f"{CORE}hasName",
    f"{VITAL}hasObjectModificationDateTime",
    f"{AIMP}hasObjectCreationTime",
    f"{HALEY}hasKGEntityType",
    f"{AIMP}hasObjectStatusType",
    f"{HALEY}hasKGActionTypeList",
    f"{HALEY}hasKGProvenanceType",
)

# Deterministic UUID namespace (same as sparql_sql_space_impl).
_VITALGRAPH_NS = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')


def _u(uri: str) -> uuid.UUID:
    """Term uuid for a URI, by the same rule the write path uses."""
    return uuid.uuid5(_VITALGRAPH_NS, f"{uri}\x00U")


_VITALTYPE = _u(VITALTYPE_URI)
_ENTITY_TYPE = _u(ENTITY_TYPE_URI)
_KGENTITY_TYPES = [_u(x) for x in KGENTITY_TYPE_URIS]
_SORT_PROPS = [_u(x) for x in SORTABLE_PROPERTY_URIS]


def _select_rows(space_id: str, where: str) -> str:
    """The derivation itself, as one SELECT.

    Used verbatim by the full resync, the backfill and the incremental
    re-derive, so those three cannot disagree about what the table means. That
    they CAN disagree is how `edge` ended up with an `ensure` path and a `resync`
    path that were both defective in different ways.

    `$1` vitaltype predicate, `$2` the KGEntity class term uuids, `$3` the
    entity-type predicate, `$4` the sortable property predicates. `where`
    supplies any incremental restriction and its own parameters from `$5`.
    """
    t_quad = f"{space_id}_rdf_quad"
    t_term = f"{space_id}_term"
    return f"""
        SELECT
            q.subject_uuid    AS entity_uuid,
            q.context_uuid    AS context_uuid,
            -- Deterministic pick when an entity carries more than one
            -- `hasKGEntityType`. This column is only the index discriminator;
            -- type FILTERING reads the `hasKGEntityType` row's `value_all`,
            -- which holds them all, so a second type is not lost -- it just
            -- does not get its own copy of the index prefix.
            --
            -- `array_agg(... ORDER BY ...)[1]` rather than `min()` because
            -- `min(uuid)` only exists from PostgreSQL 14 and this must build on
            -- whatever the RDS instance is running.
            (array_agg(ent_t.object_uuid ORDER BY ent_t.object_uuid))[1]
                              AS entity_type_uuid,
            q.predicate_uuid  AS property_uuid,
            -- The MIN, in the same three lanes the term table splits on, so
            -- ordering is correct per type rather than lexical for all.
            -- COLLATE "C" because that is what the text index is built under;
            -- picking the MIN under a different collation could store a value
            -- the index would not order first.
            min(t.term_text COLLATE "C") AS value_text,
            min(t.num_val)               AS value_num,
            min(t.dt_val)                AS value_dt,
            -- DISTINCT so the membership array is not multiplied by the
            -- entity-type join above, and so it is deterministic (an aggregate
            -- with DISTINCT sorts).
            array_agg(DISTINCT t.term_text) AS value_all,
            -- The entity's own URI, denormalised to be the sort TIE-BREAK
            -- without a join. See the column comment in the schema: joining for
            -- it cost a deep page 2.1ms -> 123ms.
            min(et.term_text) AS entity_uri
        FROM {t_quad} q
        JOIN {t_term} t ON t.term_uuid = q.object_uuid
        JOIN {t_term} et ON et.term_uuid = q.subject_uuid
        -- The population. INNER: this table describes ENTITIES, and a subject
        -- that is not one must not appear, or the count the coverage probe
        -- compares against would never agree.
        JOIN {t_quad} vt
          ON vt.subject_uuid = q.subject_uuid
         AND vt.context_uuid = q.context_uuid
         AND vt.predicate_uuid = $1
         AND vt.object_uuid = ANY($2)
        -- LEFT for the reason `entity_slot_sort` records: an untyped entity is
        -- still part of the population, and an inner join would DROP it from the
        -- table -- changing which rows it describes, not just how fast it
        -- answers.
        LEFT JOIN {t_quad} ent_t
          ON ent_t.subject_uuid = q.subject_uuid
         AND ent_t.context_uuid = q.context_uuid
         AND ent_t.predicate_uuid = $3
        WHERE q.predicate_uuid = ANY($4)
          AND {where}
        GROUP BY q.subject_uuid, q.context_uuid, q.predicate_uuid
    """


_INSERT_COLS = ("entity_uuid, context_uuid, entity_type_uuid, property_uuid, "
                "value_text, value_num, value_dt, value_all, entity_uri")

# DO UPDATE, not DO NOTHING, and that is load-bearing. The incremental path
# deletes before it re-derives, so a conflict should be impossible -- but if a
# delete ever misses a row, DO NOTHING leaves the OLD value in place forever and
# the row COUNT never changes, so no drift check can see it. That is precisely
# the defect `sync_frame_entity_before_delete` documents having shipped. DO
# UPDATE makes the re-derive authoritative regardless.
#
# The target is named rather than left bare: a targetless DO NOTHING applies to
# EVERY unique index on the table, which silently widens as indexes are added.
_ON_CONFLICT = """
    ON CONFLICT (entity_uuid, context_uuid, property_uuid) DO UPDATE SET
        entity_type_uuid = EXCLUDED.entity_type_uuid,
        value_text = EXCLUDED.value_text,
        value_num  = EXCLUDED.value_num,
        value_dt   = EXCLUDED.value_dt,
        value_all  = EXCLUDED.value_all,
        entity_uri = EXCLUDED.entity_uri
"""


def _args():
    return [_VITALTYPE, _KGENTITY_TYPES, _ENTITY_TYPE, _SORT_PROPS]


# ---------------------------------------------------------------------------
# Incremental — drop and re-derive
# ---------------------------------------------------------------------------

# Spaces whose table is known to exist. Only the POSITIVE answer is cached: a
# space that lacks the table today may be migrated at any moment, and a cached
# "absent" would keep it excluded for the life of the process. Present is the
# steady state, so the catalog lookup is paid only by unmigrated spaces --
# which are exactly the ones already running degraded.
_TABLE_PRESENT: set = set()
_WARNED: set = set()


async def _table_present(conn, space_id: str, table: str) -> bool:
    """Whether `table` exists, so a write to an UNMIGRATED space can proceed.

    THIS TABLE IS AN OPTIMISATION AND A WRITE MUST NOT DEPEND ON IT. Without
    this guard, every write to a space that predates the table failed outright:
    `add_rdf_quads_batch_bulk` raised `relation "{space}_entity_prop_sort" does
    not exist`, `update_quads` returned False and the endpoint answered 500. The
    table is created by an explicit migration, never as a side effect
    (deliberately), so "the space has not been migrated yet" is a NORMAL state
    -- and it is the state every space is in immediately after this code ships
    and before the migration runs.

    Checked rather than caught, because a failed statement aborts the enclosing
    transaction: by the time the error surfaced, the write could no longer be
    completed even by ignoring it.

    Reads already degrade this way -- `fast_entity_prop_page` falls back to
    SPARQL when the table cannot be read. Only writes failed closed.
    """
    if space_id in _TABLE_PRESENT:
        return True
    exists = await conn.fetchval("SELECT to_regclass($1)", table) is not None
    if exists:
        _TABLE_PRESENT.add(space_id)
        return True
    if space_id not in _WARNED:
        _WARNED.add(space_id)
        logger.warning(
            "%s does not exist, so this write maintains no property-sort rows "
            "for %s. The space has not been migrated; listings fall back to "
            "SPARQL and stay CORRECT, only slower. Run the migration to fix.",
            table, space_id)
    return False


async def sync_entity_prop_sort_after_change(
    conn, space_id: str, subject_uuids: List[uuid.UUID],
    context_uuid: Optional[uuid.UUID] = None,
) -> int:
    """Drop and re-derive the rows for touched entities. Runs AFTER the quads
    have been written or deleted, on every write path.

    ONE function for insert and delete alike, where `entity_slot_sort` needs a
    `before_delete` and an `after_edge_insert`. That is not tidiness -- it is the
    only shape that is correct here.

    A delete on this table is a RECOMPUTE, not a row drop. Removing one of three
    values of a multi-valued property must move the stored MIN to the next
    surviving value and shorten `value_all`, while the ROW ITSELF SURVIVES.
    A `before_delete` alone cannot do that: it runs while the doomed quad is
    still present, so anything it re-derives includes the value being removed.
    The re-derive has to happen after the DELETE lands, against the survivors.

    That is also why this must not be modelled as "delete the rows, let the next
    insert rebuild them". If the last write to an entity is a DELETE, there is no
    next insert, and the entity disappears from every sort and filter -- with a
    row count that has moved in the direction the drift probe expects, so nothing
    reports it.

    Keyed on `entity_uuid` alone, which is complete here in a way the sibling's
    six-disjunct touched filter is not: every quad this table derives from has
    the entity as its SUBJECT -- the property quads, the `vitaltype` membership
    quad and the `hasKGEntityType` discriminator alike. There is no edge or
    intermediate node whose change could invalidate a row without touching it.
    """
    if not subject_uuids:
        return 0
    t = f"{space_id}_entity_prop_sort"
    if not await _table_present(conn, space_id, t):
        return 0
    if context_uuid:
        await conn.execute(
            f"DELETE FROM {t} WHERE entity_uuid = ANY($1) AND context_uuid = $2",
            subject_uuids, context_uuid)
    else:
        await conn.execute(
            f"DELETE FROM {t} WHERE entity_uuid = ANY($1)", subject_uuids)
    sel = _select_rows(space_id, "q.subject_uuid = ANY($5)")
    result = await conn.execute(
        f"INSERT INTO {t} ({_INSERT_COLS}) {sel} {_ON_CONFLICT}",
        *_args(), subject_uuids)
    rows = int(result.split()[-1]) if result else 0
    logger.debug("entity_prop_sort after_change(%s): %d subjects -> %d rows",
                 space_id, len(subject_uuids), rows)
    return rows


async def delete_entity_prop_sort_for_context(conn, space_id: str,
                                              context_uuid: uuid.UUID) -> int:
    """Drop every row for one graph. Pairs with clear/drop graph."""
    t = f"{space_id}_entity_prop_sort"
    result = await conn.execute(
        f"DELETE FROM {t} WHERE context_uuid = $1", context_uuid)
    return int(result.split()[-1]) if result else 0


# ---------------------------------------------------------------------------
# Full rebuild and repair
# ---------------------------------------------------------------------------

async def resync_entity_prop_sort(conn, space_id: str) -> int:
    """TRUNCATE and rebuild from the graph. For bulk loads and recovery."""
    t = f"{space_id}_entity_prop_sort"
    await conn.execute(f"TRUNCATE {t}")
    result = await conn.execute(
        f"INSERT INTO {t} ({_INSERT_COLS}) "
        f"{_select_rows(space_id, 'TRUE')} {_ON_CONFLICT}", *_args())
    rows = int(result.split()[-1]) if result else 0
    # A TRUNCATE discards the statistics with the rows. Without this the planner
    # estimates a handful of rows and picks a Sort over the ordered index:
    # measured 490 ms / 23,767 buffers for a first page, against 0.3 ms / 5
    # buffers once analysed.
    await conn.execute(f"ANALYZE {t}")
    logger.info("resync_entity_prop_sort(%s): %d rows", space_id, rows)
    return rows


async def backfill_entity_prop_sort(conn, space_id: str) -> int:
    """Insert missing rows WITHOUT truncating.

    Takes only ROW EXCLUSIVE, so a maintenance job can repair drift while queries
    keep reading -- the same reason `backfill_edge_table` exists rather than
    everything going through the resync.
    """
    t = f"{space_id}_entity_prop_sort"
    result = await conn.execute(
        f"INSERT INTO {t} ({_INSERT_COLS}) "
        f"{_select_rows(space_id, 'TRUE')} {_ON_CONFLICT}", *_args())
    rows = int(result.split()[-1]) if result else 0
    logger.info("backfill_entity_prop_sort(%s): %d rows", space_id, rows)
    return rows


EPS_BACKFILL_BATCH = 500


async def backfill_entity_prop_sort_batch(
        conn, space_id: str, batch_size: int = None,
        timeout: float | None = None) -> tuple[int, int]:
    """Repair ONE BOUNDED BATCH of entities that are missing at least one pair.

    `issues/194`. Two things wrong with putting `backfill_entity_prop_sort` on a
    maintenance loop, and the second is the one that matters:

    1. It is UNBOUNDED -- one `INSERT ... SELECT` over the whole space. Under an
       RDS `statement_timeout` that is killed and rolls back, so it makes ZERO
       progress every cycle, forever. That is `issues/151` for the slot table and
       `issues/136` for VACUUM: an unbounded statement on a loop does not
       converge, it just fails on a schedule.

    2. SEEDING PER ENTITY WOULD NOT FIX THE GAP THIS ISSUE IS ABOUT.
       `backfill_entity_slot_sort_batch` seeds on entities with NO rows at all
       (`NOT EXISTS ... WHERE e.entity_uuid = q.subject_uuid`). Every entity in
       the space that raised `194` already had 2 of its 5 property rows, so that
       seed selects NOTHING and the table never heals. The missing thing is a
       (entity, property) PAIR, so the seed has to be keyed on pairs.

    Returns `(entities_selected, rows_written)`, and the caller needs both for
    the same reason the slot-sort batch does:

      selected == 0   nothing is missing a pair. Done.
      selected  > 0
        written  > 0  progress.
        written == 0  these entities derive nothing -- the derivation joins the
                      value and its term as INNER, so a property quad whose
                      object has no term row yields no output. They stay absent
                      and would be selected again forever, so the caller must
                      treat this as "stop", not "retry".

    `written` counts rows INSERTED OR UPDATED, because `_ON_CONFLICT` is DO
    UPDATE; it is progress made, not strictly new pairs.
    """
    n = int(batch_size or EPS_BACKFILL_BATCH)
    t = f"{space_id}_entity_prop_sort"
    # PAIR-KEYED, and `context_uuid` is part of the key because the table's
    # unique index is (entity, context, property) -- the same property in a
    # second graph is a different row.
    rows = await conn.fetch(
        f"SELECT DISTINCT q.subject_uuid FROM {space_id}_rdf_quad q "
        f" WHERE q.predicate_uuid = ANY($1) "
        # POPULATION MEMBERSHIP, the same test the derivation and the probe
        # apply. Seeding on `hasKGEntityType` alone would be BROADER than the
        # derivation, so a subject carrying that predicate without being a
        # KGEntity would be selected every cycle, derive nothing, and make the
        # caller report "cannot converge" forever.
        f"   AND EXISTS (SELECT 1 FROM {space_id}_rdf_quad v "
        f"                WHERE v.subject_uuid = q.subject_uuid "
        f"                  AND v.context_uuid = q.context_uuid "
        f"                  AND v.predicate_uuid = $2 "
        f"                  AND v.object_uuid = ANY($3)) "
        f"   AND NOT EXISTS (SELECT 1 FROM {t} f "
        f"                    WHERE f.entity_uuid = q.subject_uuid "
        f"                      AND f.context_uuid = q.context_uuid "
        f"                      AND f.property_uuid = q.predicate_uuid) "
        f" LIMIT {n}",
        _SORT_PROPS, _VITALTYPE, _KGENTITY_TYPES, timeout=timeout)
    seeds = [r["subject_uuid"] for r in rows]
    if not seeds:
        return 0, 0
    args = _args()
    result = await conn.execute(
        f"INSERT INTO {t} ({_INSERT_COLS}) "
        f"{_select_rows(space_id, f'q.subject_uuid = ANY(${len(args) + 1})')} "
        f"{_ON_CONFLICT}", *args, seeds, timeout=timeout)
    written = int(result.split()[-1]) if result else 0
    logger.info("backfill_entity_prop_sort_batch(%s): %d entities -> %d rows",
                space_id, len(seeds), written)
    return len(seeds), written


# ---------------------------------------------------------------------------
# Probes — two of them, because they fail in different directions
# ---------------------------------------------------------------------------

async def entity_prop_sort_drift(conn, space_id: str,
                                 timeout: float | None = None
                                 ) -> tuple[int, int]:
    """`(expected, actual)` row counts — the order `frame_entity_drift` uses, so
    `_run_*_integrity` reads `drift = expected - actual` for both.

    Counts the derivation rather than sampling it. A cheaper probe would have to
    assume which direction drift takes, and both have been seen: `issues/041`
    left tables EMPTY, while a delete path that does not clean up leaves them
    TOO FULL.

    WHAT THIS CANNOT SEE, and it matters more here than for the sibling: a row
    whose key is intact but whose VALUE is stale. The count is identical, so no
    count-based probe can detect it. This table is unusually exposed to that,
    because a multi-valued property's MIN changes when a value is DELETED while
    the row itself must survive -- so a delete path that drops rows instead of
    recomputing them produces exactly the invisible failure. That is what
    `sync_entity_prop_sort_after_insert` running on delete paths is for, and
    what the coverage probe below cannot check either.
    """
    expected = await conn.fetchval(
        f"SELECT count(*) FROM ({_select_rows(space_id, 'TRUE')}) d",
        *_args(), timeout=timeout)
    actual = await conn.fetchval(
        f"SELECT count(*) FROM {space_id}_entity_prop_sort", timeout=timeout)
    return int(expected or 0), int(actual or 0)


async def entity_prop_sort_coverage(conn, space_id: str, limit: int = 5,
                                  only_gaps: bool = True,
                                    timeout: float | None = None) -> list[dict]:
    """Entities IN the table against entities OF THAT TYPE in the quads.

    `entity_prop_sort_drift` cannot see a shortfall of this kind, and the reason
    is structural: it compares the table against `_select_rows`, which is the
    same derivation that POPULATED the table. When the derivation is the thing at
    fault the two agree perfectly and it reports converged -- a probe that can
    only confirm its own input. `issues/149` measured that on the sibling: 1.05%
    coverage while the drift probe was satisfied.

    This counts from the QUADS, which no derived table can influence.

    COUNTED IN PAIRS, NOT ENTITIES, SINCE `issues/194`. Presence used to be
    `EXISTS (... WHERE f.entity_uuid = o.entity_uuid)`, so ANY single row made an
    entity covered. Run against prod `wordnet_frames`, which was missing three of
    five properties for every one of its 109,745 entities -- 329,235 absent rows
    -- that form reported **0 gaps and all four types COMPLETE**. Worse than
    useless: `record_prop_sort_coverage` takes or releases the block from the
    number it is handed, so that reading would have RELEASED the block and
    written a positive completeness marker over a 60%-empty table.

    The table is keyed (entity, context, property). A probe that counts subjects
    cannot validate it; the unit has to be the key.

    THE DENOMINATOR IS STILL EXACT, not a heuristic, for the reason it always
    was: it counts (entity, property) pairs PRESENT IN THE QUADS for entities in
    the population, and `hasKGEntityType` is itself one of the indexed
    properties, so every entity in it has at least one pair due. There is no
    "pair that legitimately has no row" to explain away, which for
    `entity_slot_sort` (an entity may simply own no frames) there is. Anything
    short of 100% is a real gap.

    Presence is tested by `entity_uuid`, NOT by the table's own type column --
    the sibling's first version grouped by the derived table's `entity_type_uuid`
    and reported a false 1.54% shortfall when all 77,468 entities were present,
    because that check trusts the derived table's account of itself.
    """
    # `only_gaps=False` returns EVERY type, complete ones included.
    # The gap form answers "where is the worst shortfall" and is empty
    # exactly when all is well, which makes it useless for the opposite
    # question the coverage MARKER needs: a positive statement of
    # completeness, not the absence of a complaint (`issues/161`).
    #
    # COUNTED IN (entity, context, property) PAIRS SINCE `issues/194`, not in
    # entities: the per-entity form reported 0 gaps and every type COMPLETE on a
    # table missing 329,235 rows.
    _present = (f"EXISTS (SELECT 1 FROM {space_id}_entity_prop_sort f"
                f"  WHERE f.entity_uuid = p.entity_uuid"
                f"    AND f.context_uuid = p.context_uuid"
                f"    AND f.property_uuid = p.property_uuid)")
    _having = (f"HAVING count(*) FILTER (WHERE {_present}) < count(*)"
               if only_gaps else "")
    rows = await conn.fetch(f"""
        WITH pairs AS (
            SELECT DISTINCT et.object_uuid AS ty,
                   q.subject_uuid   AS entity_uuid,
                   q.context_uuid   AS context_uuid,
                   q.predicate_uuid AS property_uuid
              FROM {space_id}_rdf_quad q
              -- The type comes from the entity's own `hasKGEntityType`, which is
              -- itself one of the indexed properties, so every entity in the
              -- denominator has at least one pair due.
              JOIN {space_id}_rdf_quad et
                ON et.subject_uuid = q.subject_uuid
               AND et.predicate_uuid = $1
             WHERE q.predicate_uuid = ANY($4)
               -- Population membership, unchanged: subjects that merely carry a
               -- sortable predicate would inflate the denominator and report a
               -- permanent shortfall the backfill can never close.
               AND EXISTS (
                   SELECT 1 FROM {space_id}_rdf_quad v
                    WHERE v.subject_uuid = q.subject_uuid
                      AND v.context_uuid = q.context_uuid
                      AND v.predicate_uuid = $2
                      AND v.object_uuid = ANY($3)))
        SELECT t.term_text AS entity_type,
               p.ty        AS entity_type_uuid,
               count(*) FILTER (WHERE {_present}) AS in_table,
               count(*) AS of_type
          FROM pairs p
          JOIN {space_id}_term t ON t.term_uuid = p.ty
         GROUP BY 1, 2
        {_having}
         ORDER BY (count(*) - count(*) FILTER (WHERE {_present})) DESC
         LIMIT {int(limit)}
    """, _ENTITY_TYPE, _VITALTYPE, _KGENTITY_TYPES, _SORT_PROPS, timeout=timeout)
    return [
        {"entity_type": r["entity_type"],
         "entity_type_uuid": r["entity_type_uuid"],
         "in_table": int(r["in_table"]),
         "of_type": int(r["of_type"]),
         "ratio": (int(r["in_table"]) / int(r["of_type"])) if r["of_type"] else 1.0}
        for r in rows
    ]
