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

# Mirrors `_FRAME_SORT_PROPERTIES`. Asserted equal by
# `test_frame_prop_sort_properties_match_the_model`, because a property the
# listing offers but this does not index is served from a table with no rows
# for it -- an empty answer that looks like a real one.
SORTABLE_PROPERTY_URIS = (
    f"{CORE}hasName",
    f"{VITAL}hasObjectModificationDateTime",
    f"{AIMP}hasObjectCreationTime",
    f"{HALEY}hasKGFormType",
    f"{HALEY}hasKGFrameTypeURI",
    f"{AIMP}hasObjectStatusType",
    f"{HALEY}hasFrameSequence",
    # The two that carry the data. `hasKGFrameTypeURI` above is a name nothing
    # in the corpus uses; `hasKGFrameType` is what the endpoint's own
    # frame_type_uri filter emits and what all 285,348 wordnet frames carry. For
    # a top-level frame list these two ARE the sort -- those frames have a type,
    # a type description, and none of the other seven properties at all.
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
_SORT_PROPS = [_u(x) for x in SORTABLE_PROPERTY_URIS]


def _select_rows(space_id: str, where: str) -> str:
    """The derivation, as one SELECT. Used verbatim by resync, backfill and the
    incremental re-derive, so the three cannot disagree about what the table
    means.

    `$1` vitaltype, `$2` KGFrame, `$3` frame-type predicate, `$4` the sortable
    property predicates, `$5` form-type predicate, `$6` the Assertion value,
    `$7` frame-graph predicate. `where` supplies any restriction from `$8`.
    """
    t_quad = f"{space_id}_rdf_quad"
    t_term = f"{space_id}_term"
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
             WHERE predicate_uuid = $1 AND object_uuid = $2
        ),
        assertion AS MATERIALIZED (
            SELECT f.subject_uuid, f.context_uuid
              FROM frames f
             WHERE EXISTS (SELECT 1 FROM {t_quad} x
                            WHERE x.predicate_uuid = $5
                              AND x.subject_uuid = f.subject_uuid
                              AND x.context_uuid = f.context_uuid
                              AND x.object_uuid = $6)
                OR (NOT EXISTS (SELECT 1 FROM {t_quad} x2
                                 WHERE x2.predicate_uuid = $5
                                   AND x2.subject_uuid = f.subject_uuid
                                   AND x2.context_uuid = f.context_uuid)
                    AND NOT EXISTS (SELECT 1 FROM {t_quad} g
                                     WHERE g.predicate_uuid = $7
                                       AND g.subject_uuid = f.subject_uuid
                                       AND g.context_uuid = f.context_uuid))
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
            min(et.term_text)            AS frame_uri
        FROM assertion a
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
                "value_text, value_num, value_dt, value_all, frame_uri")

_ON_CONFLICT = """
    ON CONFLICT (frame_uuid, context_uuid, property_uuid) DO UPDATE SET
        frame_type_uuid = EXCLUDED.frame_type_uuid,
        value_text = EXCLUDED.value_text,
        value_num  = EXCLUDED.value_num,
        value_dt   = EXCLUDED.value_dt,
        value_all  = EXCLUDED.value_all,
        frame_uri  = EXCLUDED.frame_uri
"""


def _args():
    return [_VITALTYPE, _KGFRAME, _FRAME_TYPE, _SORT_PROPS,
            _FORM_TYPE, _ASSERTION, _FRAME_GRAPH]


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
    if context_uuid:
        await conn.execute(
            f"DELETE FROM {t} WHERE frame_uuid = ANY($1) AND context_uuid = $2",
            subject_uuids, context_uuid)
    else:
        await conn.execute(
            f"DELETE FROM {t} WHERE frame_uuid = ANY($1)", subject_uuids)
    sel = _select_rows(space_id, "q.subject_uuid = ANY($8)")
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
                                   timeout: float | None = None) -> list[dict]:
    """Assertion frames IN the table against Assertion frames in the QUADS.

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
    rows = await conn.fetch(f"""
        WITH assertion AS (
            SELECT DISTINCT q.subject_uuid AS frame_uuid, q.context_uuid
              FROM {space_id}_rdf_quad q
             WHERE q.predicate_uuid = $1 AND q.object_uuid = $2
               AND (
                     EXISTS (SELECT 1 FROM {space_id}_rdf_quad fo
                              WHERE fo.subject_uuid = q.subject_uuid
                                AND fo.context_uuid = q.context_uuid
                                AND fo.predicate_uuid = $5
                                AND fo.object_uuid = $6)
                  OR (NOT EXISTS (SELECT 1 FROM {space_id}_rdf_quad fo2
                                   WHERE fo2.subject_uuid = q.subject_uuid
                                     AND fo2.context_uuid = q.context_uuid
                                     AND fo2.predicate_uuid = $5)
                      AND NOT EXISTS (SELECT 1 FROM {space_id}_rdf_quad fg
                                       WHERE fg.subject_uuid = q.subject_uuid
                                         AND fg.context_uuid = q.context_uuid
                                         AND fg.predicate_uuid = $7)))
               -- Only frames that HAVE something this table indexes; the rest
               -- correctly have no rows and must not read as a shortfall.
               AND EXISTS (SELECT 1 FROM {space_id}_rdf_quad pq
                            WHERE pq.subject_uuid = q.subject_uuid
                              AND pq.context_uuid = q.context_uuid
                              AND pq.predicate_uuid = ANY($4))
        ),
        typed AS (
            SELECT a.frame_uuid, a.context_uuid,
                   (SELECT ft.object_uuid FROM {space_id}_rdf_quad ft
                     WHERE ft.subject_uuid = a.frame_uuid
                       AND ft.context_uuid = a.context_uuid
                       AND ft.predicate_uuid = $3 LIMIT 1) AS ty
              FROM assertion a
        )
        SELECT coalesce(t.term_text, '(untyped)') AS frame_type,
               y.ty AS frame_type_uuid,
               count(*) FILTER (WHERE EXISTS (
                   SELECT 1 FROM {space_id}_frame_prop_sort f
                    WHERE f.frame_uuid = y.frame_uuid)) AS in_table,
               count(*) AS of_type
          FROM typed y
          LEFT JOIN {space_id}_term t ON t.term_uuid = y.ty
         GROUP BY 1, 2
        HAVING count(*) FILTER (WHERE EXISTS (
                   SELECT 1 FROM {space_id}_frame_prop_sort f
                    WHERE f.frame_uuid = y.frame_uuid)) < count(*)
         ORDER BY (count(*) - count(*) FILTER (WHERE EXISTS (
                   SELECT 1 FROM {space_id}_frame_prop_sort f
                    WHERE f.frame_uuid = y.frame_uuid))) DESC
         LIMIT {int(limit)}
    """, *_args(), timeout=timeout)
    return [
        {"frame_type": r["frame_type"],
         "frame_type_uuid": r["frame_type_uuid"],
         "in_table": int(r["in_table"]),
         "of_type": int(r["of_type"]),
         "ratio": (int(r["in_table"]) / int(r["of_type"])) if r["of_type"] else 1.0}
        for r in rows
    ]
