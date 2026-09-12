"""Incremental and full sync for the {space}_frame_prop_sort table.

`entity_prop_sort` for TOP-LEVEL (Assertion) FRAMES. Same shape, same
reasoning, one population difference that is the whole point of the module.

SCOPED TO ASSERTIONS, AND THE DEFINITION IS COPIED, NOT APPROXIMATED. The
frames listing sorts within a form-type tab, and this serves the Assertion tab.
`kgframes_endpoint` defines an Assertion as:

    hasKGFormType = KGFormType_Assertion
    OR (no hasKGFormType AND no hasFrameGraphURI)      <- the unset default

The obvious approximation -- "a frame with no parent frame edge" -- is WRONG,
and measurably so. On the test stack:

    space                 frames    Assertions   no-parent-edge
    wordnet_frames       285,348      285,348          285,348   agree
    sp_lead_dup            5,500        5,500            1,000   DISAGREE
    lead_nurture_grouped 1,200,000            0          300,000   DISAGREE

A population that differs from what the tab lists is the plausible-subset
failure this table exists to avoid, so the rule is reproduced exactly and
`test_frame_prop_sort_population_matches_the_endpoint` pins it.

(`lead_nurture_grouped` has zero Assertions because every frame there carries
`hasFrameGraphURI`. That is a property of that fixture, not of this table:
the Assertion TAB is equally empty on it. `wordnet_frames` is the space to
validate against.)

WHY `value_num` MATTERS HERE and did not for entities: `hasFrameSequence` is an
integer, so frames genuinely use all three lanes. Sorting a frame list by
sequence is the "slots and frames in their authored order" case.

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
KGFRAME_URI = f"{HALEY}KGFrame"
FRAME_TYPE_URI = f"{HALEY}hasKGFrameType"
FORM_TYPE_URI = f"{HALEY}hasKGFormType"
FRAME_GRAPH_URI = f"{HALEY}hasFrameGraphURI"
ASSERTION_URI = f"{HALEY}KGFormType_Assertion"
ASPECT_URI = f"{HALEY}KGFormType_Aspect"

# Mirrors `_FRAME_SORT_PROPERTIES`. Asserted equal by
# `test_frame_prop_sort_properties_match_the_model`, because a property the
# listing offers but this does not index is served from a table with no rows
# for it -- an empty answer that looks like a real one.
SORTABLE_PROPERTY_URIS = (
    f"{CORE}hasName",
    f"{VITAL}hasObjectModificationDateTime",
    f"{AIMP}hasObjectCreationTime",
    f"{HALEY}hasKGFormType",
    f"{AIMP}hasObjectStatusType",
    f"{HALEY}hasFrameSequence",
    # The two that carry the data: `hasKGFrameType` (a `KGFrameType`) is what
    # the endpoint's frame_type_uri filter emits and what all 285,348 wordnet
    # frames carry, alongside its description. For a top-level frame list these
    # two ARE the sort -- those frames have a type, a type description, and none
    # of the other properties at all.
    f"{HALEY}hasKGFrameType",
    f"{HALEY}hasKGFrameTypeDescription",
)

_VITALGRAPH_NS = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')


def _u(uri: str) -> uuid.UUID:
    return uuid.uuid5(_VITALGRAPH_NS, f"{uri}\x00U")


_VITALTYPE = _u(VITALTYPE_URI)
_KGFRAME = _u(KGFRAME_URI)
_FRAME_TYPE = _u(FRAME_TYPE_URI)
_FORM_TYPE = _u(FORM_TYPE_URI)
_FRAME_GRAPH = _u(FRAME_GRAPH_URI)
_ASSERTION = _u(ASSERTION_URI)
_ASPECT = _u(ASPECT_URI)
_SORT_PROPS = [_u(x) for x in SORTABLE_PROPERTY_URIS]


def _select_rows(space_id: str, where: str, seed_param: str = None) -> str:
    """The derivation, as one SELECT. Used verbatim by resync, backfill and the
    incremental re-derive, so the three cannot disagree about what the table
    means.

    `$1` vitaltype, `$2` KGFrame, `$3` frame-type predicate, `$4` the sortable
    property predicates, `$5` form-type predicate, `$6` the Assertion value,
    `$7` frame-graph predicate. `where` supplies any restriction from `$8`.
    """
    t_quad = f"{space_id}_rdf_quad"
    t_term = f"{space_id}_term"
    # SEEDS THE POPULATION CTE, and without it cost tracks the SPACE rather than
    # the CHANGE. `MATERIALIZED` is what makes the Assertion test run once per
    # frame instead of once per property row -- but it also forces both CTEs to
    # be computed IN FULL before the outer `where` can filter them, so an
    # incremental write materialised every frame in the space and discarded
    # nearly all of it. Measured on a 1.2M-frame space: 5 touched subjects did
    # not finish in 25 s, against 23 ms for the entity equivalent.
    #
    # This is the defect `sync_entity_slot_sort._select_rows` records verbatim
    # ("the touched-set filter sat in the outer SELECT where PostgreSQL cannot
    # push it into a recursive CTE ... cost tracked the SPACE, not the change"),
    # reintroduced here while fixing a different one.
    #
    # `seed_param` stays None for the full resync and the backfill, which must
    # walk everything.
    _seed = f" AND subject_uuid = ANY({seed_param})" if seed_param else ""
    # THE ASSERTION TEST RUNS ONCE PER FRAME, in a MATERIALIZED CTE, not once
    # per property quad in the WHERE. Written the obvious way -- correlated
    # EXISTS/NOT EXISTS inside the main WHERE -- it is evaluated for every
    # property row of every frame and did not finish in 120 s on
    # `wordnet_frames`. Reducing the frame set first and joining to it is the
    # same answer `sync_entity_slot_sort` reaches by seeding its walk.
    #
    # THE ANTI-JOINS PROBE THE INDEX; they do not build a set. An intermediate
    # revision put `hasKGFormType` and `hasFrameGraphURI` into MATERIALIZED
    # DISTINCT CTEs and joined against those. On `lead_nurture_grouped` that
    # meant a DISTINCT over 10,354,000 rows to answer a question about 1,200,000
    # frames, and it had not finished after 343 s. As `NOT EXISTS` against the
    # base table each frame is two probes of `idx_{space}_quad_ps`
    # (predicate_uuid, subject_uuid), which is what that index is for.
    return f"""
        WITH frames AS MATERIALIZED (
            SELECT DISTINCT subject_uuid, context_uuid
              FROM {t_quad}
             WHERE predicate_uuid = $1 AND object_uuid = $2{_seed}
        ),
        -- EVERY FRAME IS INDEXED. Form type is RESOLVED to a column, not used
        -- to decide membership.
        --
        -- An earlier revision indexed Assertions only, because the listing's
        -- Assertion tab was the target. That made form type a property of the
        -- POPULATION, and the cost showed up the moment a parent-scoped
        -- listing needed it: the parent -> child hop is general traversal over
        -- the EDGE table, which knows nothing about form type, so a table
        -- admitting one form type can only answer the traversals whose results
        -- happen to share it. Measured on `lead_nurture_grouped`, every one of
        -- its 900,000 child frames resolves to Aspect, so no parent-scoped
        -- listing there could be served at all.
        --
        -- Membership is "it is a frame". Assertion means a frame NOT enclosed
        -- by an entity and Aspect means one that is; neither says anything
        -- about which frames a traversal reaches. So form type is a FILTER on
        -- one column, which is what a tab is.
        form AS MATERIALIZED (
            SELECT f.subject_uuid, f.context_uuid,
                   CASE
                     WHEN ex.object_uuid IS NOT NULL THEN ex.object_uuid
                     -- The unset default, MIRRORING `kgframes_endpoint`
                     -- exactly rather than improving on it: no form type and
                     -- no frame graph uri means Assertion; no form type WITH
                     -- one means Aspect.
                     --
                     -- Mirrored deliberately, because this table's job is to
                     -- agree with what the tab lists. The DEFINITION is about
                     -- entity enclosure -- an Aspect is a frame enclosed by an
                     -- entity, an Assertion is one that is not -- and
                     -- `hasFrameGraphURI` is a proxy for that, not the thing
                     -- itself. Measured on `lead_nurture_grouped`, all
                     -- 1,200,000 frames carry both `hasFrameGraphURI` and
                     -- `hasKGGraphURI` and all are genuinely entity-enclosed,
                     -- so the proxy agrees there; on `wordnet_frames` neither
                     -- predicate appears and nothing is entity-enclosed, so it
                     -- agrees there too.
                     --
                     -- If that proxy is ever corrected, correct it in the
                     -- endpoint and this follows. Diverging here would make the
                     -- table disagree with the tab, which is worse than
                     -- inheriting an imperfect rule.
                     WHEN NOT EXISTS (SELECT 1 FROM {t_quad} g
                                       WHERE g.predicate_uuid = $7
                                         AND g.subject_uuid = f.subject_uuid
                                         AND g.context_uuid = f.context_uuid)
                       THEN $6::uuid
                     ELSE $8::uuid
                   END AS form_type_uuid
              FROM frames f
              LEFT JOIN {t_quad} ex
                ON ex.subject_uuid = f.subject_uuid
               AND ex.context_uuid = f.context_uuid
               AND ex.predicate_uuid = $5
        )
        SELECT
            q.subject_uuid    AS frame_uuid,
            q.context_uuid    AS context_uuid,
            (array_agg(ft.object_uuid ORDER BY ft.object_uuid))[1]
                              AS frame_type_uuid,
            q.predicate_uuid  AS property_uuid,
            min(t.term_text COLLATE "C") AS value_text,
            min(t.num_val)               AS value_num,
            min(t.dt_val)                AS value_dt,
            array_agg(DISTINCT t.term_text) AS value_all,
            min(et.term_text)            AS frame_uri,
            -- Not `min(uuid)`: that aggregate only exists from PostgreSQL 14,
            -- and this must build on whatever the RDS instance runs. Same
            -- reason `frame_type_uuid` above uses the array form.
            (array_agg(a.form_type_uuid))[1] AS form_type_uuid
        FROM form a
        JOIN {t_quad} q
          ON q.subject_uuid = a.subject_uuid
         AND q.context_uuid = a.context_uuid
         AND q.predicate_uuid = ANY($4)
        JOIN {t_term} t  ON t.term_uuid = q.object_uuid
        JOIN {t_term} et ON et.term_uuid = q.subject_uuid
        LEFT JOIN {t_quad} ft
          ON ft.subject_uuid = q.subject_uuid
         AND ft.context_uuid = q.context_uuid
         AND ft.predicate_uuid = $3
        WHERE {where}
        GROUP BY q.subject_uuid, q.context_uuid, q.predicate_uuid
    """


_INSERT_COLS = ("frame_uuid, context_uuid, frame_type_uuid, property_uuid, "
                "value_text, value_num, value_dt, value_all, frame_uri, "
                "form_type_uuid")

_ON_CONFLICT = """
    ON CONFLICT (frame_uuid, context_uuid, property_uuid) DO UPDATE SET
        frame_type_uuid = EXCLUDED.frame_type_uuid,
        value_text = EXCLUDED.value_text,
        value_num  = EXCLUDED.value_num,
        value_dt   = EXCLUDED.value_dt,
        value_all  = EXCLUDED.value_all,
        frame_uri  = EXCLUDED.frame_uri,
        form_type_uuid = EXCLUDED.form_type_uuid
"""


def _args():
    return [_VITALTYPE, _KGFRAME, _FRAME_TYPE, _SORT_PROPS,
            _FORM_TYPE, _ASSERTION, _FRAME_GRAPH, _ASPECT]


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


async def sync_frame_prop_sort_after_change(
    conn, space_id: str, subject_uuids: List[uuid.UUID],
    context_uuid: Optional[uuid.UUID] = None,
) -> int:
    """Drop and re-derive for touched frames. Runs AFTER the quads move.

    One entry point for insert and delete alike, for the reason the entity
    version records: a delete here is a RECOMPUTE, not a row drop, and a
    `before_delete` cannot see the survivors.

    It matters MORE here. A frame's Assertion membership is itself derived from
    quads on the frame -- setting `hasFrameGraphURI` turns an Assertion into an
    Aspect, and the row must then DISAPPEAR even though the property quads it
    was built from never changed. Re-deriving from the surviving quads handles
    that; anything keyed on "which property changed" would not.
    """
    if not subject_uuids:
        return 0
    t = f"{space_id}_frame_prop_sort"
    if not await _table_present(conn, space_id, t):
        return 0
    if context_uuid:
        await conn.execute(
            f"DELETE FROM {t} WHERE frame_uuid = ANY($1) AND context_uuid = $2",
            subject_uuids, context_uuid)
    else:
        await conn.execute(
            f"DELETE FROM {t} WHERE frame_uuid = ANY($1)", subject_uuids)
    sel = _select_rows(space_id, "q.subject_uuid = ANY($9)", seed_param="$9")
    result = await conn.execute(
        f"INSERT INTO {t} ({_INSERT_COLS}) {sel} {_ON_CONFLICT}",
        *_args(), subject_uuids)
    rows = int(result.split()[-1]) if result else 0
    logger.debug("frame_prop_sort after_change(%s): %d subjects -> %d rows",
                 space_id, len(subject_uuids), rows)
    return rows


async def delete_frame_prop_sort_for_context(conn, space_id: str,
                                             context_uuid: uuid.UUID) -> int:
    """Drop every row for one graph. Pairs with clear/drop graph."""
    result = await conn.execute(
        f"DELETE FROM {space_id}_frame_prop_sort WHERE context_uuid = $1",
        context_uuid)
    return int(result.split()[-1]) if result else 0


async def resync_frame_prop_sort(conn, space_id: str) -> int:
    """TRUNCATE and rebuild. For bulk loads and recovery."""
    t = f"{space_id}_frame_prop_sort"
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
    logger.info("resync_frame_prop_sort(%s): %d rows", space_id, rows)
    return rows


async def backfill_frame_prop_sort(conn, space_id: str) -> int:
    """Insert missing rows WITHOUT truncating; takes only ROW EXCLUSIVE."""
    t = f"{space_id}_frame_prop_sort"
    result = await conn.execute(
        f"INSERT INTO {t} ({_INSERT_COLS}) "
        f"{_select_rows(space_id, 'TRUE')} {_ON_CONFLICT}", *_args())
    rows = int(result.split()[-1]) if result else 0
    logger.info("backfill_frame_prop_sort(%s): %d rows", space_id, rows)
    return rows


FPS_BACKFILL_BATCH = 500


async def backfill_frame_prop_sort_batch(
        conn, space_id: str, batch_size: int = None,
        timeout: float | None = None) -> tuple[int, int]:
    """Repair ONE BOUNDED BATCH of frames missing at least one pair.

    `issues/194`, the frame twin of `backfill_entity_prop_sort_batch`, and
    everything that one says about being BOUNDED and PAIR-SEEDED applies
    verbatim: `backfill_frame_prop_sort` is a single unbounded
    `INSERT ... SELECT` that an RDS `statement_timeout` kills and rolls back, and
    a seed keyed on frames with NO rows selects nothing on a table whose frames
    are each missing only SOME of their properties.

    Membership is "it is a frame", matching the derivation — see the `form` CTE
    in `_select_rows`. Form type is resolved to a COLUMN here, not used to decide
    membership, so there is no Assertion restriction to mirror. (The docstring of
    `scripts/migrate_frame_prop_sort.py` still says Assertion-scoped; it predates
    that change.)

    Returns `(frames_selected, rows_written)`, with the same contract as the
    entity twin: `selected > 0 and written == 0` means these frames derive
    nothing and the caller must stop rather than reselect them forever.
    """
    n = int(batch_size or FPS_BACKFILL_BATCH)
    t = f"{space_id}_frame_prop_sort"
    rows = await conn.fetch(
        f"SELECT DISTINCT q.subject_uuid FROM {space_id}_rdf_quad q "
        f" WHERE q.predicate_uuid = ANY($1) "
        # Population membership, the same test the derivation applies.
        f"   AND EXISTS (SELECT 1 FROM {space_id}_rdf_quad v "
        f"                WHERE v.subject_uuid = q.subject_uuid "
        f"                  AND v.context_uuid = q.context_uuid "
        f"                  AND v.predicate_uuid = $2 "
        f"                  AND v.object_uuid = $3) "
        # PAIR-KEYED, matching the table's unique index.
        f"   AND NOT EXISTS (SELECT 1 FROM {t} f "
        f"                    WHERE f.frame_uuid = q.subject_uuid "
        f"                      AND f.context_uuid = q.context_uuid "
        f"                      AND f.property_uuid = q.predicate_uuid) "
        f" LIMIT {n}",
        _SORT_PROPS, _VITALTYPE, _KGFRAME, timeout=timeout)
    seeds = [r["subject_uuid"] for r in rows]
    if not seeds:
        return 0, 0
    sel = _select_rows(space_id, "q.subject_uuid = ANY($9)", seed_param="$9")
    result = await conn.execute(
        f"INSERT INTO {t} ({_INSERT_COLS}) {sel} {_ON_CONFLICT}",
        *_args(), seeds, timeout=timeout)
    written = int(result.split()[-1]) if result else 0
    logger.info("backfill_frame_prop_sort_batch(%s): %d frames -> %d rows",
                space_id, len(seeds), written)
    return len(seeds), written


async def frame_prop_sort_drift(conn, space_id: str,
                                timeout: float | None = None) -> tuple[int, int]:
    """`(expected, actual)` row counts, the order `_run_*_integrity` reads."""
    expected = await conn.fetchval(
        f"SELECT count(*) FROM ({_select_rows(space_id, 'TRUE')}) d",
        *_args(), timeout=timeout)
    actual = await conn.fetchval(
        f"SELECT count(*) FROM {space_id}_frame_prop_sort", timeout=timeout)
    return int(expected or 0), int(actual or 0)


async def frame_prop_sort_coverage(conn, space_id: str, limit: int = 5,
                                  only_gaps: bool = True,
                                   timeout: float | None = None) -> list[dict]:
    """Frames IN the table against frames in the QUADS.

    Independent of the derivation, which is what the drift probe above is not:
    that compares the table against the same SELECT that filled it, so when the
    derivation is at fault the two agree perfectly and it reports converged.
    `issues/149` measured exactly that on `entity_slot_sort`: 1.05% coverage
    while drift was satisfied.

    NOT EXACT THE WAY THE ENTITY PROBE IS. There, `hasKGEntityType` was both the
    grouping key and an indexed property, so every counted entity had to have a
    row. A frame's type comes from `hasKGFrameType`, which this table does NOT
    index -- so an Assertion carrying a frame type and none of the seven
    sortable properties legitimately has no rows. On `wordnet_frames` that is
    nobody (all 285,348 carry `hasKGFrameType`... which is not indexed), so the
    denominator is deliberately restricted to frames that HAVE at least one
    indexed property. Anything short of that is a real gap.
    """
    # `only_gaps=False` returns EVERY type, complete ones included.
    # The gap form answers "where is the worst shortfall" and is empty
    # exactly when all is well, which makes it useless for the opposite
    # question the coverage MARKER needs: a positive statement of
    # completeness, not the absence of a complaint (`issues/161`).
    # COUNTED IN (frame, context, property) PAIRS SINCE `issues/194`, not in
    # frames. Presence was `EXISTS (... WHERE f.frame_uuid = y.frame_uuid)`, so
    # ANY single row made a frame covered — the same blindness measured on the
    # entity twin, where it reported 0 gaps and every type COMPLETE on a table
    # missing 329,235 rows. The table is keyed (frame, context, property); a
    # probe that counts subjects cannot validate it.
    #
    # All four prod tables were verified pair-complete before this changed
    # (cardiff_kg 1,214,433, lead_data 659,772, wordnet_frames 570,696,
    # lead_prod 566,283), so re-keying blocks nothing that was being served.
    _present = (f"EXISTS (SELECT 1 FROM {space_id}_frame_prop_sort f"
                f"  WHERE f.frame_uuid = y.frame_uuid"
                f"    AND f.context_uuid = y.context_uuid"
                f"    AND f.property_uuid = y.property_uuid)")
    _having = (f"HAVING count(*) FILTER (WHERE {_present}) < count(*)"
               if only_gaps else "")
    rows = await conn.fetch(f"""
        WITH population AS (
            -- One row per (frame, context, PROPERTY IT ACTUALLY CARRIES). The
            -- inner join to the property quad replaces the previous EXISTS and
            -- keeps the guarantee that came with it: a frame carrying none of
            -- the sortable properties contributes nothing, so it cannot read as
            -- a shortfall no backfill can close.
            SELECT DISTINCT q.subject_uuid AS frame_uuid, q.context_uuid,
                   pq.predicate_uuid AS property_uuid
              FROM {space_id}_rdf_quad q
              JOIN {space_id}_rdf_quad pq
                ON pq.subject_uuid = q.subject_uuid
               AND pq.context_uuid = q.context_uuid
               AND pq.predicate_uuid = ANY($4)
             WHERE q.predicate_uuid = $1 AND q.object_uuid = $2
        ),
        typed AS (
            SELECT a.frame_uuid, a.context_uuid, a.property_uuid,
                   (SELECT ft.object_uuid FROM {space_id}_rdf_quad ft
                     WHERE ft.subject_uuid = a.frame_uuid
                       AND ft.context_uuid = a.context_uuid
                       AND ft.predicate_uuid = $3 LIMIT 1) AS ty
              FROM population a
        )
        SELECT coalesce(t.term_text, '(untyped)') AS frame_type,
               y.ty AS frame_type_uuid,
               count(*) FILTER (WHERE {_present}) AS in_table,
               count(*) AS of_type
          FROM typed y
          LEFT JOIN {space_id}_term t ON t.term_uuid = y.ty
         GROUP BY 1, 2
        {_having}
         ORDER BY (count(*) - count(*) FILTER (WHERE {_present})) DESC
         LIMIT {int(limit)}
    """, *_args()[:4], timeout=timeout)   # this query uses $1..$4 only
    return [
        {"frame_type": r["frame_type"],
         "frame_type_uuid": r["frame_type_uuid"],
         "in_table": int(r["in_table"]),
         "of_type": int(r["of_type"]),
         "ratio": (int(r["in_table"]) / int(r["of_type"])) if r["of_type"] else 1.0}
        for r in rows
    ]
