"""Direct-SQL page for an entity sort by a slot value.

The READ side of `{space}_entity_slot_sort` (`issues/096`). Without this the
table would be maintained and never consulted — the state
`derived_table_maintenance.md` describes for one of the fan-out diagnostics,
under "Loaded but not demonstrably read". A derived table with no consumer costs
write latency and storage and buys nothing, so the read path ships with the
write path rather than after it.

(That diagnostic is deliberately not named here. A unit test greps the tree for
its name to prove nothing consumes it, so a mention in prose — even this one —
reads to that test exactly like a consumer.)

Shaped after `kg_backend_utils.fast_entity_page`: a narrow direct-SQL path that
returns `None` for any shape it does not serve, so the caller falls back to the
general SPARQL pipeline rather than this having to be complete.

WHAT IT REPLACES. `SortCriteria(sort_type="entity_frame_slot")` compiles to a
six-way join that walks entity -> frame -> EVERY slot of that frame and fetches
each one's value before discarding all but the sort slot: measured on
`prod_kg`, 360 ms and 423,742 buffers for a 25-row page. Against the table
the same page is an index-only scan — **7.2 ms and 78 buffers, flat as the page
deepens** rather than growing with OFFSET.

WHAT IT DOES NOT SERVE, and why each is a hard decline rather than a best
effort. Returning a WRONG PAGE is far worse than returning None:

  * **An EMPTY frame_path.** Every row is reached through at least one frame, so
    a slot attached directly to the entity — which `sort_type="frame_slot"` with
    no frame path describes — is not in the table. Answering it from frame-borne
    rows would be a WRONG page, not a slow one, so it declines.
    (Nested frame paths ARE served: the table stores the ordered type path, and
    this matches the whole array.)
  * **Any frame/slot/property/vector/geo criterion.** The table answers "order
    these entities by this slot value"; it does not know which entities a
    criterion admits, and applying the sort to an unfiltered set would page
    through the wrong population.
  * **More than one sort criterion.** Secondary sort keys are not stored.
  * **`entity_uris` pinned.** The general path is already fast there (222
    buffers, 0.7 ms measured) and this would be no better.
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

logger = logging.getLogger(__name__)

_VITALGRAPH_NS = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')

HALEY = "http://vital.ai/ontology/haley-ai-kg#"

# Which value lane a slot class lands in. Mirrors
# `_SLOT_CLASS_TO_VALUE_PROPERTY` in kg_query_builder, collapsed to the three
# columns the table splits on.
#
# Anything absent declines rather than defaulting to text. The builder defaults
# an unknown class to `hasTextSlotValue`; doing the same here would order a
# numeric slot lexically and put "9" after "10" — a wrong ORDER, silently, which
# is the exact failure class this whole issue is about.
_LANE = {
    f"{HALEY}KGTextSlot": "text",
    f"{HALEY}KGChoiceSlot": "text",
    f"{HALEY}KGJsonSlot": "text",
    f"{HALEY}KGURISlot": "text",
    f"{HALEY}KGBooleanSlot": "text",
    f"{HALEY}KGIntegerSlot": "num",
    f"{HALEY}KGLongSlot": "num",
    f"{HALEY}KGDoubleSlot": "num",
    f"{HALEY}KGCurrencySlot": "num",
    f"{HALEY}KGDateTimeSlot": "dt",
}

# The column, and the ORDER BY expression that matches the index it is stored
# in. The COLLATE has to be repeated here: the index is built `COLLATE "C"` and
# an ORDER BY under the database's default collation cannot use it, which
# silently returns the query to the six-way join this exists to avoid.
_LANE_SQL = {
    "text": ('value_text', 'MIN(value_text COLLATE "C")', 'MAX(value_text COLLATE "C")'),
    "num": ('value_num', 'MIN(value_num)', 'MAX(value_num)'),
    "dt": ('value_dt', 'MIN(value_dt)', 'MAX(value_dt)'),
}


def _term_uuid(uri: str) -> uuid.UUID:
    return uuid.uuid5(_VITALGRAPH_NS, f"{uri}\x00U")


# More keys are one more conditional aggregate each, not one more join, so the
# cost curve is flat in a way a self-join's would not be. The cap is here
# because "flat" was measured at two and asserted at three, not because
# anything breaks above it: past this the general pipeline is the safer answer.
MAX_SORT_KEYS = 3


def sort_keys(criteria):
    """The sort criteria this table can answer, in the builder's own order.

    `None` -- not a list -- when the shape is unserved, so callers get one
    answer to one question instead of re-deriving the conditions.

    ORDER MATTERS AND MUST MATCH THE BUILDER. `_build_sort_bindings` emits
    `sorted(sort_criteria, key=priority)`, and Python's sort is stable, so equal
    priorities keep declaration order. Sorting differently here would return a
    page ordered by the right values in the wrong precedence -- a wrong page
    that looks entirely plausible.
    """
    sc = getattr(criteria, "sort_criteria", None) or []
    if not 1 <= len(sc) <= MAX_SORT_KEYS:
        return None
    keys = sorted(sc, key=lambda x: getattr(x, "priority", 1))
    for s in keys:
        if s.sort_type not in ("entity_frame_slot", "frame_slot"):
            return None
        if not s.slot_type:
            return None
        if _LANE.get(s.slot_class_uri or "") is None:
            return None
        # At least one frame hop, per key. See the note in `can_serve`.
        if not (s.frame_path or []):
            return None
    # EVERY KEY MUST WALK THE SAME FRAME PATH. `frame_type_path` is one of the
    # index's leading columns and is matched as a whole array; two keys under
    # different paths would need an OR of (slot_type, path) pairs, which gives
    # up the index-only scan that makes this worth doing. Declining is a
    # fallback to the general pipeline, so it costs latency and not correctness.
    if any(list(k.frame_path) != list(keys[0].frame_path) for k in keys[1:]):
        return None
    return keys


def can_serve(criteria) -> bool:
    """Whether this builder criteria object is a shape the table answers.

    Kept separate from the query so the endpoint can decide without a database
    round trip, and so the conditions are testable on their own.
    """
    keys = sort_keys(criteria)
    if keys is None:
        return False
    s = keys[0]
    # The frame-hop requirement is enforced per key in `sort_keys`: depth beyond
    # one is fine -- the type path is stored and matched whole -- but a slot
    # hanging directly off the entity is not in the table at all, and answering
    # it from frame-borne rows would be a wrong page rather than a slow one.
    # FRAME CRITERIA ARE SERVED HERE NOW, when every one of them is an equality
    # this table can answer (`issues/172`).
    #
    # This used to read "the table sorts a population; it does not select one",
    # and declined. `can_serve_filter` symmetrically declines when a sort is
    # present, so a FILTERED, SORTED LIST — the main list view — was served by
    # neither and fell through to the general pipeline. Measured on a 74.2M-quad
    # space: the filter alone answers in 4-5ms, and the same filter WITH a sort
    # did not finish in 120s. The plan shows why: it materialises the whole
    # match set through a GroupAggregate and sorts it three times before the
    # LIMIT applies, so every one of 78,496 matches is paid for to return 50.
    #
    # Both halves are in ONE index. `idx_{space}_ess_text` is
    # (context, entity_type, frame_type_path, slot_type, value_text, entity_uuid)
    # — leading columns for each equality, and an ordered value_text for the
    # sort. Measured with the filter added as EXISTS clauses: 72ms warm, 938ms
    # cold, verified against a brute-force top-50.
    #
    # NOT O(page), and NOT O(matches either) — it is O(POPULATION OF THE SORT
    # SLOT). Measured across a 168-fold range of match counts on 100,000
    # entities: 54.6ms unfiltered, 90.6ms at 78,496 matches, 42.6ms at 2,820,
    # 46.2ms at 467, 21.2ms at none. Flat, because the scan walks the sort
    # slot's rows in value order and tests each with the EXISTS; the filter
    # changes how many SURVIVE, not how many are EXAMINED.
    #
    # So the bound that matters for scaling is the entity count of the type, not
    # the selectivity of the criteria. Ten times the entities costs about ten
    # times; ten times the matches over the same population costs nothing extra.
    #
    # Forcing a nested loop for early termination measured SLOWER (222ms against
    # 72ms) and was not pursued. It would only help if the FILTER could be the
    # leading access rather than a per-row test, which is a different plan
    # shape — worth trying if the entity-count curve turns out to bend badly.
    filters = None
    if getattr(criteria, "frame_criteria", None):
        from .fast_slot_filter import _eq_criteria
        filters = _eq_criteria(criteria.frame_criteria)
        if filters is None:
            # A comparator this table cannot answer disqualifies the whole
            # query, exactly as it does on the filter path: a partially applied
            # conjunction is a wrong answer, not a slow one.
            return False
    # Entity-property filters are SERVED when every one is an equality on a
    # URI-valued property (`entity_prop_filters` explains the restriction).
    if entity_prop_filters(criteria) is None:
        return False
    if getattr(criteria, "entity_uris", None):
        return False
    for attr in ("vector_criteria", "multi_vector_criteria", "geo_criteria",
                 "slot_criteria", "search_string"):
        if getattr(criteria, attr, None):
            return False
    if not getattr(criteria, "entity_type", None):
        # Without an entity type the index cannot be probed on its leading
        # columns, so the scan would be the whole table.
        return False
    return True



def _filter_exists(t: str, criteria, args: list) -> str:
    """EXISTS clauses restricting the sorted population to the filter's matches.

    `issues/172`. One clause per equality criterion, correlated on
    `entity_uuid`, each hitting `idx_{space}_ess_text` on its own leading
    columns. The planner turns them into semi-joins over a compact table, which
    measured 72ms warm where the general pipeline did not finish in 120s.

    Appends to `args` in step with the placeholders it emits, so the caller's
    numbering stays correct however many criteria there are.
    """
    fcs = getattr(criteria, "frame_criteria", None)
    if not fcs:
        return ""
    from .fast_slot_filter import _eq_criteria
    parsed = _eq_criteria(fcs)
    if not parsed:
        return ""
    out = []
    for path, slot_type, lane, val in parsed:
        args.append([_term_uuid(u) for u in path])
        p_path = len(args)
        args.append(_term_uuid(slot_type))
        p_slot = len(args)
        args.append(val)
        p_val = len(args)
        out.append(
            f"AND EXISTS (SELECT 1 FROM {t} f{p_slot}"
            f" WHERE f{p_slot}.context_uuid = $1"
            f"   AND f{p_slot}.entity_type_uuid = $2"
            f"   AND f{p_slot}.frame_type_path = ${p_path}"
            f"   AND f{p_slot}.slot_type_uuid = ${p_slot}"
            # `_LANE` yields the lane NAME ('text'/'num'/'dt'); the COLUMN is
            # `value_text`/`value_num`/`value_dt`, which `_LANE_SQL` holds.
            # Emitting the bare lane produced `f.text = $n` — a column that does
            # not exist, so the count errored and the page silently returned
            # nothing.
            f"   AND f{p_slot}.{_LANE_SQL[lane][0]} = ${p_val}"
            f"   AND f{p_slot}.entity_uuid = {t}.entity_uuid)")
    return "\n              ".join(out)


def entity_prop_filters(criteria):
    """The entity-property filters this path can answer, or None if any cannot.

    None means DECLINE THE WHOLE QUERY. Applying some filters and ignoring the
    rest returns a superset with a plausible count and no error, which is the
    same rule `fast_slot_filter._eq_criteria` follows for frame criteria.

    ONLY `eq` ON A URI-VALUED PROPERTY. The value has to be resolved to a
    `term_uuid` to probe the quad table, and for a URI that hash is unambiguous
    (`uuid5(ns, text + "\x00U")`, which is `_term_uuid` here). A LITERAL also
    folds in `lang` and a space-local numeric `datatype_id`, so guessing it
    wrong does not error -- it matches no term, and the page comes back EMPTY
    but well-formed. Declining costs a fallback; guessing costs a wrong answer.

    The datatype is DECLARED, not inferred, in the builder's own map, so this
    reads that map rather than sniffing the value. Today it admits
    `hasObjectStatusType` and `hasKGEntityType`; the other three declared
    properties are string or dateTime and decline here.
    """
    epf = getattr(criteria, "entity_property_filters", None)
    if not epf:
        return []
    try:
        from ...sparql.kg_query_builder import _FILTERABLE_ENTITY_PROPERTIES
    except Exception:
        return None
    out = []
    for f in epf:
        if getattr(f, "operator", None) != "eq":
            return None
        val = getattr(f, "value", None)
        if not isinstance(val, str):
            return None
        if _FILTERABLE_ENTITY_PROPERTIES.get(getattr(f, "property_uri", None)) != "uri":
            return None
        out.append((f.property_uri, val))
    return out


def _prop_filter_exists(space_id: str, props, args: list) -> str:
    """EXISTS clauses on the quad table, correlated on `entity_uuid`.

    The property lives on the ENTITY, not in `entity_slot_sort`, so unlike the
    frame criteria in `_filter_exists` this cannot stay inside the sort table.
    Scoped to `context_uuid` because the generated SPARQL puts these patterns
    inside `GRAPH <...>`; an unscoped probe would match a property asserted in
    another graph.

    Measured on `cardiff_kg`, a broad filter (status ACTIVE, matching all 2,863)
    with a CompanyName sort: 1,007,597 buffers / 548.9 ms through the general
    pipeline, against 8,751 buffers / 23 ms here. The planner picks a hash semi
    join unaided -- the `rows=1` misestimate that first appeared while probing
    this was an artefact of resolving the constants with inline sub-SELECTs,
    which are opaque at plan time; as bound parameters the estimate is 8,666
    against 8,755 actual.
    """
    q = f"{space_id}_rdf_quad"
    out = []
    for i, (prop_uri, val) in enumerate(props):
        # INLINED AS LITERALS, NOT BOUND AS PARAMETERS -- deliberately, and it is
        # the difference between 10 ms and 1,180 ms.
        #
        # asyncpg prepares every statement, and PostgreSQL switches a prepared
        # statement to a GENERIC plan after five executions. A generic plan
        # cannot see the parameter values, so it cannot know this predicate
        # matches 8,755 rows, and it reverts to the nested loop that drives off
        # the filter set. Measured on one connection, same statement:
        #
        #     exec 1-5     ~10 ms      custom plan, values known
        #     exec 6+    ~1,180 ms     generic plan
        #
        # A pooled server holds prepared statements across requests, so real
        # traffic lands on the second number, permanently. The frame-criteria
        # EXISTS in `_filter_exists` does NOT have this problem and stays
        # parameterised: it probes `entity_slot_sort` on its own leading index
        # columns, where the generic plan is the same good plan (measured flat
        # at 0.6 ms over eight executions).
        #
        # Safe to inline because these are `uuid.UUID` values produced by
        # `_term_uuid`, a uuid5 hash -- not caller text. The assertion keeps it
        # that way rather than trusting the call site.
        prop_u, val_u = _term_uuid(prop_uri), _term_uuid(val)
        assert isinstance(prop_u, uuid.UUID) and isinstance(val_u, uuid.UUID)
        a = f"p{i}"
        out.append(
            f"AND EXISTS (SELECT 1 FROM {q} {a}"
            f" WHERE {a}.subject_uuid = {space_id}_entity_slot_sort.entity_uuid"
            f"   AND {a}.context_uuid = $1"
            f"   AND {a}.predicate_uuid = '{prop_u}'::uuid"
            f"   AND {a}.object_uuid = '{val_u}'::uuid)")
    return "\n              ".join(out)


def _grouped(space_id: str, graph_uri: str, criteria, keys):
    """The grouped population the page and the count must BOTH be drawn from.

    One place, because the page and the count disagreeing is the failure this
    path keeps producing: a UI that offers a last page it cannot reach. Returns
    the pieces rather than a query so each caller adds only its own tail.

    N keys is N conditional aggregates over ONE index-only scan, not N-1 joins.
    Measured on `cardiff_kg`, two keys, page 25: 165 buffers / 3.6 ms with zero
    heap fetches, against 1,405,617 buffers / 778.5 ms for the same page through
    the general pipeline, and 650 / 11.3 for the self-join form.

    HAVING, not WHERE, is what makes an entity missing ANY key absent -- which
    is the general pipeline's semantics, not a choice: `_build_sort_bindings`
    emits every sort pattern as a REQUIRED triple, never OPTIONAL, so the
    pipeline drops such an entity too. An outer join here would return rows the
    query being imitated does not.
    """
    t = f"{space_id}_entity_slot_sort"
    args = [_term_uuid(graph_uri), _term_uuid(criteria.entity_type),
            [_term_uuid(u) for u in keys[0].frame_path]]
    slot_ph = []
    for k in keys:
        args.append(_term_uuid(k.slot_type))
        slot_ph.append(f"${len(args)}")

    sel, having, order = [], [], []
    for i, (k, ph) in enumerate(zip(keys, slot_ph)):
        col, agg_min, agg_max = _LANE_SQL[_LANE[k.slot_class_uri]]
        descending = (k.sort_order or "asc").lower() == "desc"
        # MIN ascending / MAX descending, per key -- order each entity by the
        # value that will actually determine its position when a slot type
        # appears more than once under the path. This mirrors the aggregate
        # `_build_sort_bindings` chooses for exactly the same reason.
        agg = f"{agg_max if descending else agg_min} FILTER (WHERE slot_type_uuid = {ph})"
        sel.append(f"{agg} AS sv{i}")
        # Repeated rather than referenced: HAVING cannot see a SELECT alias.
        having.append(f"{agg} IS NOT NULL")
        order.append(f"sv{i} {'DESC' if descending else 'ASC'}")

    # Filters append to `args`, so every placeholder above must already be in it.
    where_filters = _filter_exists(t, criteria, args)
    props = entity_prop_filters(criteria)
    if props:
        where_filters += "\n              " + _prop_filter_exists(space_id, props, args)
    where = (f"context_uuid = $1 AND entity_type_uuid = $2 "
             f"AND frame_type_path = $3 "
             f"AND slot_type_uuid IN ({', '.join(slot_ph)})"
             f"{where_filters}")
    return t, args, ", ".join(sel), where, " AND ".join(having), order


async def fast_slot_sort_page(
    conn, space_id: str, graph_uri: str, criteria,
    page_size: int, offset: int,
) -> Optional[List[str]]:
    """One ordered page of entity URIs, or None if unserved.

    None means "not my shape" AND "the table is not there / not populated" —
    both must fall back, and the caller cannot tell them apart, which is
    deliberate: a half-populated table answering a page would be a wrong answer.
    """
    keys = sort_keys(criteria)
    if keys is None:
        return None
    t, args, sel, where, having, order = _grouped(
        space_id, graph_uri, criteria, keys)
    t_term = f"{space_id}_term"
    n = len(args)
    tail = ", ".join(order)

    sql = f"""
        SELECT tm.term_text
        FROM (
            SELECT entity_uuid, {sel}
            FROM {t}
            WHERE {where}
            GROUP BY entity_uuid
            HAVING {having}
            ORDER BY {tail}, entity_uuid
            LIMIT ${n + 1} OFFSET ${n + 2}
        ) p
        JOIN {t_term} tm ON tm.term_uuid = p.entity_uuid
        ORDER BY {", ".join("p." + o for o in order)}, p.entity_uuid
    """
    try:
        rows = await conn.fetch(sql, *args, page_size, offset)
    except Exception as exc:
        # A space predating the table, or one where it was never populated.
        # Declining is correct; the fallback is the general path.
        logger.debug("fast_slot_sort_page(%s) declined: %s", space_id, exc)
        return None
    return [r[0] for r in rows]


async def fast_slot_sort_count(
    conn, space_id: str, graph_uri: str, criteria,
) -> Optional[int]:
    """Total distinct entities the same page is drawn from, or None.

    Must apply the SAME `{col} IS NOT NULL` restriction as the page. The
    generated SPARQL joins the sort value as a required triple, so an entity
    without one is absent from both the page and the count; a count that
    omitted the restriction would disagree with its own page and the UI would
    show a last page that cannot be reached.
    """
    keys = sort_keys(criteria)
    if keys is None:
        return None
    t, args, sel, where, having, _order = _grouped(
        space_id, graph_uri, criteria, keys)

    try:
        return await conn.fetchval(f"""
            SELECT count(*) FROM (
                SELECT entity_uuid, {sel}
                FROM {t}
                WHERE {where}
                GROUP BY entity_uuid
                HAVING {having}
            ) x
        """, *args)
    except Exception as exc:
        logger.debug("fast_slot_sort_count(%s) declined: %s", space_id, exc)
        return None
