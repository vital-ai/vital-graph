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
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from .fast_slot_sort import _LANE, _LANE_SQL, _term_uuid
# The ISO and timezone tests the GENERAL PIPELINE uses for the same comparison,
# imported rather than restated. A second copy of either is a second definition
# of which values this store considers dates, and the two paths must agree about
# that or the fast one is not answering the same question.
from .filter_pushdown import _ISO_RE, _TZ_RE, _TZ_SQL_RE

logger = logging.getLogger(__name__)


def _lane_arg(lane: str, val):
    """The driver argument for `val` in `lane`, or None if it is not in that lane.

    THE VALUE ARRIVES AS JSON. `SlotCriteria.value` is `Optional[Any]`, so a
    KGQuery criterion carries whatever the client sent -- a str for a date, an
    int or float for a number -- while `value_num` is NUMERIC and `value_dt` is
    TIMESTAMP. asyncpg types each parameter from the column it is compared
    against and refuses anything else:

        asyncpg.exceptions.DataError: invalid input for query argument $5:
            '2026-06-23T14:00:00.000Z' (expected a datetime.date or
            datetime.datetime instance, got 'str')

    Caught at DEBUG by both callers, so every dated slot equality -- and every
    float-valued numeric one -- has silently fallen to the ~300x slower BGP join
    for as long as this path has existed. The answers were right; the fast path
    was simply never reached from the API that feeds it.

    A value that does not belong to its lane returns None, which declines the
    WHOLE query in `_eq_criteria` rather than dropping that conjunct.

    DATES STAY STRINGS. They are normalised in SQL by `vitalgraph_iso_to_utc`,
    the function `value_dt` itself was derived with, so the comparison cannot
    drift from the column. Parsing here would put that UTC decision in a second
    place; `_ISO_RE` only decides whether the value IS a date, which is what the
    general pipeline uses it for too.
    """
    if lane == "text":
        return str(val)
    if lane == "num":
        try:
            d = Decimal(str(val))
        except (InvalidOperation, ValueError):
            return None
        # NaN and the infinities are valid Decimals and match nothing; a
        # criterion that cannot match is better declined than served as empty.
        return d if d.is_finite() else None
    s = str(val).strip()
    return s if _ISO_RE.match(s) else None


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
        # A NEGATED CRITERION IS THE COMPLEMENT OF WHAT THIS PROBES, and nothing
        # here read the flag. `FrameCriteria.negate` means "match entities that
        # do NOT have this frame pattern" -- the builder emits
        # `FILTER NOT EXISTS { ... }` for it (`kg_query_builder.py:803`) -- so
        # served as an equality probe it returned precisely the entities the
        # caller asked to EXCLUDE. Not a subset, the complement, with a
        # plausible count and no error.
        #
        # Declined outright rather than emitted as an EXCEPT: `frame_type_path`
        # is an ordered path and the absence of a row means "no such slot in the
        # table", which a stale or incomplete table produces as readily as the
        # data does. Negation over a table whose completeness is the caller's
        # job is exactly the direction that turns staleness into extra rows.
        if getattr(fc, "negate", False):
            return False
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
            arg = _lane_arg(lane, val)
            if arg is None:
                return False
            out.append((path, slot_type, lane, arg))
        for nested in (getattr(fc, "frame_criteria", None) or []):
            if not walk(nested, path):
                return False
        return True

    for fc in frame_criteria:
        if not walk(fc, []):
            return None
    return out or None


def filter_decline_reason(criteria) -> Optional[str]:
    """WHY `can_serve_filter` would decline, or None if it would serve.

    `can_serve_filter` returns a bare bool over NINE independent disqualifiers,
    so a query that falls through to the general pipeline gives an operator no
    way to tell which one applied. That matters because the two paths differ by
    orders of magnitude — measured 21 ms against a 60 s timeout on the same
    shape — and "it declined" is not an actionable fact.

    Kept separate from `can_serve_filter` rather than folded into it: the gate is
    on the request path and must stay a cheap bool, and a diagnostic that changes
    the decision is a diagnostic that can change behaviour.
    """
    if not getattr(criteria, "frame_criteria", None):
        return "no frame_criteria — nothing for the index to match"
    if not getattr(criteria, "entity_type", None):
        return ("no entity_type — the index cannot be probed on its leading "
                "columns, so every probe degrades to a full scan")
    if getattr(criteria, "sort_criteria", None):
        return ("sort_criteria present — the SORT path serves those; if it "
                "declines too, the query falls to the general pipeline "
                "(issues/172)")
    for attr in ("vector_criteria", "multi_vector_criteria", "geo_criteria",
                 "entity_property_filters", "entity_uris", "slot_criteria",
                 "search_string"):
        if getattr(criteria, attr, None):
            return (f"{attr} present — this table answers frame/slot equality "
                    f"only, and a partially applied query is a wrong answer")
    parsed = _eq_criteria(getattr(criteria, "frame_criteria", None))
    if parsed is None:
        return ("a criterion is outside what the index answers — a NEGATED "
                "frame criterion, a comparator that is not `eq`, an unmapped "
                "slot_class_uri, a missing slot_type, a null value, or a value "
                "outside its lane (a non-numeric value on a numeric slot, a "
                "non-ISO value on a dateTime slot). A conjunction is served "
                "only when EVERY conjunct is")
    return None


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
    # `slot_criteria` IS THE TOP-LEVEL ONE, not a frame's. `EntityQueryCriteria`
    # carries entity -> frame -> slot criteria with no frame type named, which
    # the builder emits as its own pattern (`kg_query_builder.py:809`) and this
    # probe cannot express: `frame_type_path` is the index prefix and there is
    # no path to supply. Read nowhere, they would simply not be applied, and an
    # unapplied conjunct is a SUPERSET.
    #
    # Not reachable today — neither site that builds the criteria object this
    # gate sees populates the field — so this is insurance, taken because the
    # SORT path has checked it all along (`fast_slot_sort.can_serve`) and an
    # asymmetry between two gates over one table is how the last four defects
    # here happened.
    for attr in ("vector_criteria", "multi_vector_criteria", "geo_criteria",
                 "entity_property_filters", "entity_uris", "slot_criteria",
                 "search_string"):
        if getattr(criteria, attr, None):
            return False
    return _eq_criteria(fcs) is not None


def _value_sql(lane: str, n: int) -> str:
    """The right-hand side of a comparison against this lane's column.

    A date is normalised IN SQL rather than bound as a timestamp -- see `_probe`
    for both reasons. Shared with `fast_slot_sort._filter_exists`, which applies
    the same criteria to the same table for a sorted page: it binds through
    `_eq_criteria` too, so a normalisation living only here would leave that path
    declining every dated filter, which is exactly what it did.
    """
    return f"vitalgraph_iso_to_utc(${n})" if lane == "dt" else f"${n}"


def _tz_guard(lane: str, val, alias: str = "") -> str:
    """The timezone-agreement predicate for a date, or "" for other lanes."""
    if lane != "dt":
        return ""
    col = f"{alias}.value_text" if alias else "value_text"
    return (f" AND ({col} ~ '{_TZ_SQL_RE}') IS "
            f"{'true' if _TZ_RE.search(str(val)) else 'false'}")


def _probe(t: str, idx: int, lane: str, val=None):
    """One INTERSECT arm: an equality probe on the index's full leading prefix.

    THE DATE ARM IS NOT A PLAIN `= $n`, for two reasons.

    It is normalised: `value_dt` is `term.dt_val`, i.e.
    `vitalgraph_iso_to_utc(term_text)`, so the bound is read by the same
    function and one instant matches however it was written -- `...Z`,
    `...+00:00` and `2019-12-31T23:00:00-01:00` are one moment. A cast would
    instead type the parameter and make asyncpg reject the string the criterion
    holds.

    And it carries the TIMEZONE-AGREEMENT GUARD, copied from the general
    pipeline's `_eq_cond` because both must answer the same question.
    `vitalgraph_iso_to_utc` reads an untimezoned value AS IF UTC; XSD says a
    timezoned and an untimezoned dateTime are INCOMPARABLE, since the answer
    depends on an offset nobody supplied. Without the guard, normalising would
    declare them equal -- a wrong match rather than a missing one. The lexical
    form is right here in `value_text`, which holds `term_text` for every row
    whatever its lane, so the guard costs no join.
    """
    col, _mn, _mx = _LANE_SQL[lane]
    b = idx * 3
    return f"""
        SELECT entity_uuid FROM {t}
         WHERE context_uuid = $1 AND entity_type_uuid = $2
           AND frame_type_path = ${b + 3}
           AND slot_type_uuid  = ${b + 4}
           AND {col} = {_value_sql(lane, b + 5)}{_tz_guard(lane, val)}
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
        # `val` is already the driver argument: `_eq_criteria` puts every value
        # through `_lane_arg`, which is where a value outside its lane declines
        # the query. Doing it there and not here keeps `can_serve_filter`,
        # `filter_decline_reason` and this builder answering the same question —
        # a gate that says yes to a shape the builder then cannot bind is how a
        # fast path comes to raise instead of declining.
        args += [[_term_uuid(u) for u in path], _term_uuid(slot_type), val]
        arms.append(_probe(t, i, lane, val))
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
        # DISTINCT, because the table holds a row per SLOT and the question is
        # how many ENTITIES match. One entity with two frames of the same type,
        # both carrying the value -- two Campaign frames on a lead, both ACTIVE
        # -- produces two rows, and `count(*)` counted it twice. A single
        # criterion is a single arm, so there was no INTERSECT to deduplicate
        # it; the bug appears exactly when the filter is simplest.
        #
        # `count(*)` over a DISTINCT subquery rather than `count(DISTINCT ...)`:
        # the same answer from a HashAggregate instead of a sort per group.
        return await conn.fetchval(
            f"SELECT count(*) FROM (SELECT DISTINCT entity_uuid "
            f"                        FROM ({body}) x) y", *args)
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

    DISTINCT for the reason the count carries: a row per slot means an entity
    matching twice was RETURNED twice, taking two of the page's fifty slots and
    shifting every later offset. Ordering made it look deliberate — the repeats
    sit adjacent, so it reads as data rather than as a duplicate.
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
                SELECT DISTINCT entity_uuid FROM ({body}) x
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


async def take_slot_sort_block(conn, space_id: str, entity_type_uuid=None,
                               reason: str = "") -> None:
    """Declare this space (or one type in it) AT RISK until released.

    `issues/167`. Taken by the operation that creates the risk, in the same
    transaction that begins it — never by a caller remembering to afterwards. If
    taking the block and starting the work can come apart, they will: `resync_all`
    clearing a marker and leaving it cleared, and `bulk_export.import_space`
    registering no graphs, are both that failure already.

    `entity_type_uuid=None` blocks the WHOLE SPACE, which is what a restore or a
    full resync needs: it invalidates every type at once and does not know their
    uuids when it starts.

    A block is a ROW, so it survives a crash. That fails in the correct
    direction — a stuck block is slow and right, and is visible.
    """
    await conn.execute(
        "INSERT INTO slot_sort_block (space_id, entity_type_uuid, reason)"
        " VALUES ($1, $2, $3)"
        " ON CONFLICT (space_id, entity_type_uuid) DO UPDATE"
        "   SET reason = EXCLUDED.reason, created_at = NOW()",
        space_id, entity_type_uuid, reason or "unspecified")


async def release_slot_sort_block(conn, space_id: str,
                                  entity_type_uuid=None) -> None:
    """Release a block. ONLY call this having just MEASURED coverage.

    Releasing because a job finished running is not the same as releasing
    because the table is now complete, and the difference is a wrong answer.
    """
    if entity_type_uuid is None:
        await conn.execute(
            "DELETE FROM slot_sort_block"
            " WHERE space_id = $1 AND entity_type_uuid IS NULL", space_id)
    else:
        await conn.execute(
            "DELETE FROM slot_sort_block"
            " WHERE space_id = $1 AND entity_type_uuid = $2",
            space_id, entity_type_uuid)


async def _space_has_no_slots(conn, space_id: str) -> bool:
    """True when the space contains no slot-typed subject at all.

    The difference between "nothing to measure" and "could not measure". An
    EXISTS against the predicate index short-circuits on the first row, so this
    is cheap even on a large space — and it is only reached when a coverage
    sweep came back empty, which on a space with data means something is wrong
    and the block should stay.
    """
    # IMPORTED, not re-derived. A local uuid5 would be a second definition of
    # the same constant, and if the namespace or the URI ever moved this probe
    # would quietly match nothing — which reads as "no slots", which releases a
    # block it should have held. Imported inside the function because
    # `sync_entity_slot_sort` is the heavier module and nothing else here needs
    # it at import time.
    from .sync_entity_slot_sort import _SLOT_TYPE as slot_type
    try:
        found = await conn.fetchval(
            f"SELECT EXISTS (SELECT 1 FROM {space_id}_rdf_quad "
            f" WHERE predicate_uuid = $1)", slot_type)
        return not found
    except Exception as exc:
        # Could not answer -> do NOT release. Absence of evidence is the one
        # thing this function must never read as evidence of absence.
        logger.debug("slot presence probe failed for %s: %s", space_id, exc)
        return False


async def _slot_rows_account_for_every_slot(conn, space_id: str) -> bool:
    """True when the table holds a row for every slot the quads declare.

    The ONE case where an upper bound is conclusive. `row_shortfall` counts
    `quad_slots - table_rows` and is documented as an upper bound on the gap,
    because a legitimately-absent slot (valueless, unreachable, lane not split
    on) inflates it. At ZERO there is nothing for those causes to explain:
    nothing is missing.

    It proves nothing is MISSING, not that nothing is EXTRA. Stale surplus rows
    are drift and `entity_slot_sort_drift` is what sees those.
    """
    from .sync_entity_slot_sort import entity_slot_sort_row_shortfall
    try:
        sf = await entity_slot_sort_row_shortfall(conn, space_id)
        return sf["shortfall"] == 0
    except Exception as exc:
        logger.debug("shortfall probe failed for %s: %s", space_id, exc)
        return False


async def release_whole_space_block_if_complete(conn, space_id: str,
                                               coverage_rows,
                                               slot_shortfall: int = 0) -> bool:
    """Clear a WHOLE-SPACE block once every type has measured complete.

    THE WHOLE-SPACE BLOCK HAD NO RELEASER. `record_slot_sort_coverage` releases
    per type, and the read gate matches `entity_type_uuid IS NULL OR = $2` — so
    one whole-space row switches the fast path off for EVERY type in the space
    and nothing ever took it back. A space seeded with one at upgrade
    ("coverage never measured") therefore stayed off permanently, with correct
    answers and no error, until an operator ran the DELETE by hand. Found on a
    deploy rehearsal against a clean instance, where two spaces sat blocked
    while their tables were complete the whole time.

    Per-type release cannot fix this: the type that would clear the block does
    not know it is the last one. Only a caller that has just measured EVERY
    type in the space may release it, which is why `coverage_rows` is passed in
    rather than re-read — it is the evidence, and requiring it as an argument
    keeps the contract on `release_slot_sort_block` ("only having just MEASURED
    coverage") true by construction.

    Releases only when the sweep saw at least one type AND every one of them is
    complete.

    AN EMPTY SWEEP IS TWO DIFFERENT SITUATIONS and this used to treat them as
    one. "Types could not be measured" must hold the block. "There are no types
    to measure" must not — a space with no slot data has nothing to cover, so
    the table is complete by vacuity and holding the block switches off a fast
    path that could never have served anything anyway.

    Conflating them held eleven dev spaces blocked from the moment an upgrade
    seeded them (2026-09-06) with no way out, all of them slot-free test
    spaces. The cost was not the disabled fast path — there was nothing for it
    to serve — it was the alarm: every cycle, for every one of them,
    "the repair is not converging, or nothing is working on it", which is how a
    warning that matters gets tuned out.

    One indexed EXISTS separates them, and it is asked ONLY on the empty-sweep
    path, so the normal case pays nothing.
    """
    rows = list(coverage_rows or [])
    if not rows:
        # Two ways an empty sweep still means COMPLETE, and one that does not.
        #
        #   no slots at all          -> nothing to cover, complete by vacuity
        #   slots, and none missing  -> the sweep is TYPE-driven and this space
        #                               has no typed entities, so it can see
        #                               nothing; the row count can
        #   slots, and some missing  -> hold, this is the real failure
        #
        # The middle case is `kg_crud_stress_test`: 160 slots, 160 rows, and
        # ZERO entities carrying `hasKGEntityType`. `entity_slot_sort_all_types`
        # groups by entity type, so it returns nothing and the block was held
        # forever over a table that was complete the whole time. The fast path
        # can serve those rows — `fast_slot_filter`'s gate matches
        # `entity_type_uuid IS NULL OR = $2` — so the block cost a real path.
        if (await _space_has_no_slots(conn, space_id)
                or await _slot_rows_account_for_every_slot(conn, space_id)):
            try:
                await release_slot_sort_block(conn, space_id, None)
            except Exception as exc:
                logger.debug("could not release whole-space block for %s: %s",
                             space_id, exc)
                return False
            return True
        return False
    if not all(r["in_table"] >= r["of_type"] and r["of_type"] > 0 for r in rows):
        return False
    # A GENUINELY ABSENT SLOT ROW HOLDS THE BLOCK (`issues/194`), even when every
    # per-entity number is complete — those count entities, and an entity
    # missing one slot type still counts as covered. Releasing on them alone
    # would hand the fast path a table known to be short.
    if slot_shortfall:
        return False
    try:
        await release_slot_sort_block(conn, space_id, None)
    except Exception as exc:
        logger.debug("could not release whole-space block for %s: %s",
                     space_id, exc)
        return False
    return True


async def slot_sort_is_blocked(conn, space_id: str,
                               entity_type_uri: str) -> bool:
    """Is the slot-sort table KNOWN to be at risk for this space/type?

    The read-path gate, and the inverse of what `slot_sort_coverage_is_complete`
    asked. Absence of a block means SERVE: normal writes derive the table inline
    in the caller's transaction, so it is correct unless something is actively
    making it otherwise.

    DEFAULTS TO BLOCKED ON ANY UNCERTAINTY — an unreadable table, a missing one,
    an error. That keeps the asymmetry the allow-list had, in the one place it
    still applies: not knowing is not the same as knowing it is fine, and the
    cost of being wrong here is a confident subset rather than a slow answer.
    A deployment whose schema predates this table therefore declines everything
    until it is created, which is slow and correct.
    """
    try:
        row = await conn.fetchrow(
            "SELECT 1 FROM slot_sort_block WHERE space_id = $1"
            "   AND (entity_type_uuid IS NULL OR entity_type_uuid = $2) LIMIT 1",
            space_id, _term_uuid(entity_type_uri))
    except Exception as exc:
        logger.debug("slot_sort_block unreadable for %s: %s", space_id, exc)
        return True
    return row is not None


async def slot_sort_alarms(conn, space_id: str, coverage_rows,
                           stale_after_hours: int = 24) -> list:
    """The two bugs a block-list can have. `issues/167`.

    MUST BE CALLED BEFORE `record_slot_sort_coverage`, which takes a block for
    any short type — running it afterwards erases the evidence for the first
    alarm, which is the whole point of having it.

    UNDECLARED SHORTFALL. A type measured short with NO block already held means
    something made the table incomplete WITHOUT DECLARING IT. Under an
    allow-list that was merely slow; under a block-list it means queries were
    being served from a short table until this probe happened to run. It is the
    detector for the design's one real hole — a write path that does not take a
    block — and it names a hole in the code, not a problem with the data.

    STALE BLOCK. A block older than `stale_after_hours` means the job that
    should clear it is not converging, or nothing is working on it at all. That
    is slow-and-correct rather than wrong, but it is indefinite: the fast path
    stays off until someone acts, and nothing else would say so.

    Returns findings rather than logging, so the caller decides severity and
    this stays testable without a log capture.
    """
    findings: list = []
    try:
        held = {r["entity_type_uuid"]: r for r in await conn.fetch(
            "SELECT entity_type_uuid, reason, created_at,"
            "       (NOW() - created_at) > ($2 || ' hours')::interval AS stale"
            "  FROM slot_sort_block WHERE space_id = $1",
            space_id, str(int(stale_after_hours)))}
    except Exception as exc:
        logger.debug("slot_sort_block unreadable for %s: %s", space_id, exc)
        return findings

    # A whole-space block covers every type, so a shortfall under one is
    # declared, not undeclared.
    space_blocked = None in held

    for cov in coverage_rows or []:
        short = not (cov["in_table"] >= cov["of_type"] and cov["of_type"] > 0)
        if short and not space_blocked and cov["entity_type_uuid"] not in held:
            findings.append({
                "kind": "undeclared_shortfall",
                "space_id": space_id,
                "entity_type_uuid": cov["entity_type_uuid"],
                "in_table": cov["in_table"], "of_type": cov["of_type"],
            })

    for type_uuid, row in held.items():
        if row["stale"]:
            findings.append({
                "kind": "stale_block",
                "space_id": space_id,
                "entity_type_uuid": type_uuid,
                "reason": row["reason"], "since": row["created_at"],
            })
    return findings


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
                                    in_table: int, of_type: int,
                                    slot_shortfall: int = 0) -> None:
    """Record what the coverage probe measured, for the read path to consult.

    `complete` is `in_table >= of_type`, not `==`: the table can legitimately
    hold rows for entities the type count no longer sees (a type quad deleted
    while slot rows await their sync), and that direction does not cost the
    filter any matches. Short is the only dangerous direction.

    `slot_shortfall` IS THE SPACE-LEVEL COUNT OF GENUINELY ABSENT SLOT ROWS
    (`issues/194`), and a nonzero one means NOT COMPLETE however good the
    per-entity numbers look.

    It has to enter the decision HERE rather than block separately alongside it.
    The two measurements see different things — `in_table`/`of_type` count
    ENTITIES, so an entity holding rows for slot type A while missing type B is
    counted as covered — and this function is the only place entitled to move the
    gate, for the reason below. A second blocker on the side would take a block
    that this function then released, every cycle: the marker-lifecycle failure
    `issues/161` is a catalogue of.

    It is deliberately SPACE-level and not per-type. Attributing an absent slot
    to an entity type needs the entity->frame->slot walk `issues/151` removed
    from the maintenance loop, and a bounded sample could only ever attribute
    SOME types — fine for taking a block, unsound for releasing one, because a
    type the sample missed would read as clean. So any real shortfall in the
    space holds every type in it. That is the conservative direction, and the
    repair (`backfill_entity_slot_sort_missing_slots`) drives it to zero.
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
            bool(in_table >= of_type and of_type > 0 and not slot_shortfall))
        # AND KEEP THE BLOCK IN STEP WITH IT (`issues/167`).
        #
        # This function is the only place that MEASURES coverage, so it is the
        # only place entitled to decide whether the type is at risk. Splitting
        # the measurement from the gate is what produced every marker-lifecycle
        # bug in `issues/161`: something cleared one and did not restore it, or
        # recorded one and never took the other.
        #
        # A type that is short takes a block; a type that is complete releases
        # one. Releasing here is safe by construction because coverage was just
        # measured, which is the condition `release_slot_sort_block` requires.
        if in_table >= of_type and of_type > 0 and not slot_shortfall:
            await release_slot_sort_block(conn, space_id, entity_type_uuid)
        else:
            reason = f"coverage {in_table}/{of_type}"
            if slot_shortfall:
                # Named so an operator reading the row knows which measurement
                # holds the block, and that it is not the entity counts.
                reason += f"; {slot_shortfall} slot row(s) absent space-wide"
            await take_slot_sort_block(
                conn, space_id, entity_type_uuid, reason=reason)
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
