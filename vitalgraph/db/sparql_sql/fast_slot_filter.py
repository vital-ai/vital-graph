"""Direct-SQL entity FILTER served from `{space}_entity_slot_sort`.

The sibling of `fast_slot_sort`, for the other half of what the table can
answer. `fast_slot_sort` orders a population; this SELECTS one.

WHY THIS EXISTS. The production slot-value entity query compiles to a flat BGP
of ~18 triple patterns — entity -> frame -> slot -> value, once per frame
criterion — joined over the quad table. Measured on `lead_nurture_100k`
(53.4M quads), against answers verified from the quads:

    query                current (BGP)     here          result
    campaign head        13.9 s            46.9 ms       78,871
    campaign + ABSENT    TIMEOUT (>55s)    271 ms        0
    campaign + PRESENT   17.2 s            98.8 ms       1

The join was re-deriving what the table already stores. The table carries
`(context_uuid, entity_type_uuid, frame_type_path, slot_type_uuid, value_text,
entity_uuid)` with a btree index on exactly that tuple, which is an equality
probe for this shape.

THE INDEX PREFIX IS NOT OPTIONAL. Probing `slot_type_uuid` + `value_text` alone
measured 5.36 s; the same query supplying `context_uuid`, `entity_type_uuid` and
`frame_type_path` measured 271 ms. Every probe here emits the full leading
prefix, which is why `entity_type` and a frame path are hard requirements rather
than niceties.

WHY A SEPARATE `can_serve_filter` RATHER THAN LOOSENING `can_serve`. The sort
path declines `frame_criteria` deliberately — "the table sorts a population; it
does not select one" — and several of its other conditions exist to prevent a
WRONG PAGE. Relaxing that predicate in place would quietly widen the sort path
too. These are two different questions about the same table and they get two
predicates.

COMPLETENESS IS THE CALLER'S JOB, and the asymmetry is the reason. A stale table
makes a sort MIS-ORDER a page; it makes a filter return a SUBSET that looks like
a complete answer, with a plausible count and no error. So this module refuses
to guess: it answers the shape, and the caller must establish that the table is
complete for the entity type before believing it. See
`slot_sort_coverage_is_complete`.

A per-query coverage count is NOT the way to do that: measured on the same
space, the quad side is 31 ms but `count(DISTINCT entity_uuid)` over the table
is 5,677 ms. The gate has to be a maintained marker, not an inline count.
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from .fast_slot_sort import _LANE, _LANE_SQL, _term_uuid

logger = logging.getLogger(__name__)


def _eq_criteria(frame_criteria):
    """Flatten frame criteria into `(frame_path, slot_type, lane, value)` tuples.

    Returns None if ANY criterion is outside what the index answers, because a
    partial application would be a wrong answer rather than a slow one. A
    conjunction is only served when EVERY conjunct is served.

    Nested `frame_criteria` are walked so a nested frame contributes its own
    path, matching how the table stores the whole ordered type path.
    """
    out = []

    def walk(fc, prefix):
        ft = getattr(fc, "frame_type", None)
        if not ft:
            return False
        path = prefix + [ft]
        for sc in (getattr(fc, "slot_criteria", None) or []):
            if (getattr(sc, "comparator", "eq") or "eq").lower() != "eq":
                return False
            slot_type = getattr(sc, "slot_type", None)
            lane = _LANE.get(getattr(sc, "slot_class_uri", None) or "")
            if not slot_type or lane is None:
                return False
            val = getattr(sc, "value", None)
            if val is None:
                return False
            out.append((path, slot_type, lane, val))
        for nested in (getattr(fc, "frame_criteria", None) or []):
            if not walk(nested, path):
                return False
        return True

    for fc in frame_criteria:
        if not walk(fc, []):
            return None
    return out or None


def can_serve_filter(criteria) -> bool:
    """Whether this criteria object is a FILTER the table answers exactly.

    Deliberately narrow. Anything outside falls back to the general pipeline,
    which is slow but correct.
    """
    fcs = getattr(criteria, "frame_criteria", None)
    if not fcs:
        return False
    # Without an entity type the index cannot be probed on its leading columns,
    # so every probe degrades to a scan of the whole table — the 5.36s shape.
    if not getattr(criteria, "entity_type", None):
        return False
    # A sort is the OTHER path's job. Serving both here would mean ordering by a
    # column this query never selected.
    if getattr(criteria, "sort_criteria", None):
        return False
    for attr in ("vector_criteria", "multi_vector_criteria", "geo_criteria",
                 "entity_property_filters", "entity_uris", "search_string"):
        if getattr(criteria, attr, None):
            return False
    return _eq_criteria(fcs) is not None


def _probe(t: str, idx: int, lane: str):
    """One INTERSECT arm: an equality probe on the index's full leading prefix."""
    col, _mn, _mx = _LANE_SQL[lane]
    b = idx * 3
    return f"""
        SELECT entity_uuid FROM {t}
         WHERE context_uuid = $1 AND entity_type_uuid = $2
           AND frame_type_path = ${b + 3}
           AND slot_type_uuid  = ${b + 4}
           AND {col} = ${b + 5}
    """


def _build(space_id: str, graph_uri: str, criteria):
    """(sql_body, args) for the INTERSECT of every criterion, or None."""
    parsed = _eq_criteria(criteria.frame_criteria)
    if parsed is None:
        return None
    args = [_term_uuid(graph_uri), _term_uuid(criteria.entity_type)]
    t = f"{space_id}_entity_slot_sort"
    arms = []
    for i, (path, slot_type, lane, val) in enumerate(parsed):
        col, _mn, _mx = _LANE_SQL[lane]
        # `value_num`/`value_dt` are typed columns; asyncpg needs the Python type
        # to match, and a caller may hand us a string for either. Only `text` is
        # safe to stringify, which is also the only lane a URI or text slot uses.
        v = val if lane != "text" else str(val)
        args += [[_term_uuid(u) for u in path], _term_uuid(slot_type), v]
        arms.append(_probe(t, i, lane))
    # INTERSECT, not a join: several criteria mean the entity satisfies ALL of
    # them, which is what the generated SPARQL conjunction means. It also lets
    # each arm be an independent index probe, so an arm matching NOTHING costs
    # one lookup instead of driving a join.
    return "\n INTERSECT \n".join(arms), args


async def fast_slot_filter_count(
    conn, space_id: str, graph_uri: str, criteria,
) -> Optional[int]:
    """How many distinct entities satisfy every criterion, or None if unserved."""
    if not can_serve_filter(criteria):
        return None
    built = _build(space_id, graph_uri, criteria)
    if built is None:
        return None
    body, args = built
    try:
        return await conn.fetchval(
            f"SELECT count(*) FROM ({body}) x", *args)
    except Exception as exc:
        # A space predating the table, or one where it was never populated.
        logger.debug("fast_slot_filter_count(%s) declined: %s", space_id, exc)
        return None


async def fast_slot_filter_page(
    conn, space_id: str, graph_uri: str, criteria,
    page_size: int, offset: int,
) -> Optional[List[str]]:
    """One page of matching entity URIs, or None if unserved.

    Ordered by `entity_uuid` so paging is STABLE. The caller asked for no sort —
    `can_serve_filter` refuses when it did — but a page without a total order is
    a page that can repeat or skip rows across offsets.
    """
    if not can_serve_filter(criteria):
        return None
    built = _build(space_id, graph_uri, criteria)
    if built is None:
        return None
    body, args = built
    n = len(args)
    t_term = f"{space_id}_term"
    try:
        rows = await conn.fetch(f"""
            SELECT tm.term_text
            FROM (
                SELECT entity_uuid FROM ({body}) x
                ORDER BY entity_uuid
                LIMIT ${n + 1} OFFSET ${n + 2}
            ) p
            JOIN {t_term} tm ON tm.term_uuid = p.entity_uuid
            ORDER BY p.entity_uuid
        """, *args, page_size, offset)
    except Exception as exc:
        logger.debug("fast_slot_filter_page(%s) declined: %s", space_id, exc)
        return None
    return [r[0] for r in rows]


async def slot_sort_coverage_is_complete(conn, space_id: str,
                                         entity_type_uri: str) -> bool:
    """Is `{space}_entity_slot_sort` known COMPLETE for this entity type?

    Reads the marker the maintenance coverage probe maintains. Defaults to
    FALSE for every uncertainty — no row, an unreadable table, a stale space —
    because the cost of being wrong is asymmetric: a false NO is a slow correct
    answer down the general path, and a false YES is a silently short one.

    Deliberately NOT time-bounded. A `verified_at` freshness window would make
    the fast path switch itself off on a quiet space where nothing changed and
    the marker is still perfectly true, and would still not catch a write that
    landed one second after a check. Writes maintain the table incrementally
    (`sparql_sql_space_impl` syncs on every quad insert, delete and context
    drop) and a bulk import CLEARS the marker, so the marker is invalidated by
    the events that can invalidate it rather than by the clock.
    """
    try:
        row = await conn.fetchrow(
            "SELECT complete FROM slot_sort_coverage "
            " WHERE space_id = $1 AND entity_type_uuid = $2",
            space_id, _term_uuid(entity_type_uri))
    except Exception as exc:
        logger.debug("slot_sort_coverage unreadable for %s: %s", space_id, exc)
        return False
    return bool(row and row["complete"])


async def record_slot_sort_coverage(conn, space_id: str, entity_type_uuid,
                                    in_table: int, of_type: int) -> None:
    """Record what the coverage probe measured, for the read path to consult.

    `complete` is `in_table >= of_type`, not `==`: the table can legitimately
    hold rows for entities the type count no longer sees (a type quad deleted
    while slot rows await their sync), and that direction does not cost the
    filter any matches. Short is the only dangerous direction.
    """
    try:
        await conn.execute(
            "INSERT INTO slot_sort_coverage (space_id, entity_type_uuid,"
            "  entities_in_table, entities_of_type, complete, verified_at)"
            " VALUES ($1, $2, $3, $4, $5, NOW())"
            " ON CONFLICT (space_id, entity_type_uuid) DO UPDATE SET"
            "  entities_in_table = EXCLUDED.entities_in_table,"
            "  entities_of_type  = EXCLUDED.entities_of_type,"
            "  complete          = EXCLUDED.complete,"
            "  verified_at       = EXCLUDED.verified_at",
            space_id, entity_type_uuid, int(in_table), int(of_type),
            bool(in_table >= of_type and of_type > 0))
    except Exception as exc:
        logger.debug("could not record slot_sort_coverage for %s: %s",
                     space_id, exc)


async def clear_slot_sort_coverage(conn, space_id: str) -> None:
    """Drop every marker for a space. Called when a bulk load invalidates them.

    An import repopulates the quads long before its resync rebuilds the derived
    tables (`issues/159`), so a marker written before the import describes a
    table that no longer covers the data. Clearing is safe in the only direction
    that matters: the filter path falls back until the probe re-verifies.
    """
    try:
        await conn.execute(
            "DELETE FROM slot_sort_coverage WHERE space_id = $1", space_id)
    except Exception as exc:
        logger.debug("could not clear slot_sort_coverage for %s: %s",
                     space_id, exc)
