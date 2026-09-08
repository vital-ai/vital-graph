"""Serve a sorted, filtered page of KG entities from `{space}_entity_prop_sort`.

The read half of `sync_entity_prop_sort`. Where that module maintains the table,
this one decides whether it may be used and builds the page when it may.

WHAT IT REPLACES. `fast_entity_page` declines the moment a listing names a type,
a filter or a sort -- so every sorted or filtered page falls to a SPARQL
properties query. Measured on a 74.5M-quad space, a sorted page is 128.8 ms from
the quads against 2.5 ms here, and the quad figure is a FLOOR: it is one join,
where the real listing measured ~17 s.

The property that actually matters is not the ratio, it is that this stays FLAT
as the page deepens (2.1 ms at offset 10,000) where an OFFSET over a sort of the
whole population does not. The complaint was a deep page, not the first one.

RETURNS None TO DECLINE, exactly like `fast_typed_subject_page`, and the caller
falls back. Declining is always safe; serving when the table is short is not,
which is why the gate defaults to blocked on any uncertainty.

SEARCH IS NOT SERVED HERE YET, deliberately. Text lives in
`{space}_fts_{index}`, and composing the two is a join whose driving side
depends on how selective the search is -- the measurement recorded in
`planning_ui/kg_search_filter_sort_fts_plan.md`. `issues/172` is what guessing
that costs: two fast paths each declining the other's input, and the combination
falling to a plan that did not finish in 120 s. So a search declines, for now,
visibly.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from .sync_entity_prop_sort import (  # noqa: E402
    SORTABLE_PROPERTY_URIS, _u,
)

# Mirrors `_FILTERABLE_ENTITY_PROPERTIES`; asserted equal by
# `test_entity_prop_sort_constants`. Datatype decides which lane a comparison
# reads, so it cannot be inferred from the value.
_DATATYPES = {
    "http://vital.ai/ontology/vital-core#hasName": "string",
    "http://vital.ai/ontology/vital#hasObjectModificationDateTime": "dateTime",
    "http://vital.ai/ontology/vital-aimp#hasObjectCreationTime": "dateTime",
    "http://vital.ai/ontology/haley-ai-kg#hasKGEntityType": "uri",
    "http://vital.ai/ontology/vital-aimp#hasObjectStatusType": "uri",
    "http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList": "uri_list",
    "http://vital.ai/ontology/haley-ai-kg#hasKGProvenanceType": "uri",
}

# Which column an ORDER BY reads. `uri` and `uri_list` sort as text because a
# uri IS text here -- `value_all` holds them as TEXT[] for the same reason.
_SORT_LANE = {"string": "value_text", "uri": "value_text",
              "uri_list": "value_text", "dateTime": "value_dt"}


async def prop_sort_blocked(conn, space_id: str,
                            entity_type_uri: Optional[str] = None) -> bool:
    """Whether `{space}_entity_prop_sort` is KNOWN TO BE AT RISK right now.

    A block-list, not an allow-list, for the reason `issues/167` records on the
    sibling: read as an allow-list, ABSENCE meant DECLINE, and absence is the
    common case -- nine spaces with complete, correct tables were served by the
    slow path purely because no row existed.

    READS BOTH TABLES. A whole-space block lives in `slot_sort_block`, because
    restore and resync take one there and those events invalidate every derived
    table in the space, this one included. Sharing it means a future restore path
    cannot block one derived table and forget the other; there is no second site
    to remember. Per-type blocks are separate, in `prop_sort_block`, because a
    shortfall in the slot table says nothing about this one.

    DEFAULTS TO BLOCKED ON ANY UNCERTAINTY -- an unreadable table, a missing one,
    an error. Not knowing is not the same as knowing it is fine, and the cost of
    being wrong is a confident SUBSET rather than a slow answer.
    """
    ty = _u(entity_type_uri) if entity_type_uri else None
    try:
        row = await conn.fetchrow(
            "SELECT 1 FROM slot_sort_block "
            " WHERE space_id = $1 AND entity_type_uuid IS NULL LIMIT 1", space_id)
        if row is not None:
            return True
        row = await conn.fetchrow(
            # A NULL `entity_type_uuid` is a WHOLE-SPACE block and must match
            # whatever type is asked for -- that is how a rebuild blocks its
            # own table. The previous predicate only matched a whole-space row
            # when the caller happened to pass no type, so a typed listing
            # would have been served straight out of a half-built table.
            "SELECT 1 FROM prop_sort_block WHERE space_id = $1"
            "   AND (entity_type_uuid IS NULL"
            "        OR $2::uuid IS NULL OR entity_type_uuid = $2) LIMIT 1",
            space_id, ty)
    except Exception as exc:
        # AT INFO, because this is how the gate fails CLOSED. An unreadable
        # block table — a missing GRANT, most likely, which is exactly what took
        # the slot-sort fast path down once already — turns every listing slow
        # with no other symptom.
        logger.info("prop_sort DECLINE(%s): block table unreadable, failing "
                    "closed: %s", space_id, exc)
        return True
    return row is not None


def _filter_terms(filters: Optional[Dict[str, Any]]) -> Optional[List[tuple]]:
    """Structured filter values -> `(property_uri, op, value)`.

    Takes the STRUCTURED values the listing already has, never the SPARQL
    fragment `_build_property_filter_clauses` produces. Re-parsing generated
    SPARQL to recover what it meant is how a fast path comes to disagree with the
    slow one it is supposed to match.

    Returns None if anything is present that this cannot express, so the caller
    declines the whole listing rather than serving a SUBSET of the filters --
    which would be a confident wrong answer, not a slow one.
    """
    if not filters:
        return []
    STATUS = "http://vital.ai/ontology/vital-aimp#hasObjectStatusType"
    CREATED = "http://vital.ai/ontology/vital-aimp#hasObjectCreationTime"
    MODIFIED = "http://vital.ai/ontology/vital#hasObjectModificationDateTime"
    ACTION = "http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList"
    PROV = "http://vital.ai/ontology/haley-ai-kg#hasKGProvenanceType"

    known = {"status": (STATUS, "eq"), "exclude_status": (STATUS, "ne"),
             "created_after": (CREATED, "gte"), "created_before": (CREATED, "lte"),
             "modified_after": (MODIFIED, "gte"), "modified_before": (MODIFIED, "lte"),
             "action_type": (ACTION, "has"), "provenance_type": (PROV, "eq")}

    out: List[tuple] = []
    for key, value in (filters or {}).items():
        if value in (None, "", []):
            continue
        if key not in known:
            return None          # something new; decline rather than ignore it
        prop, op = known[key]
        out.append((prop, op, value))
    return out


def build_page_sql(space_id: str, terms: List[tuple], sort_by: Optional[str],
                   descending: bool, typed: bool = True) -> Optional[tuple]:
    """`(sql, params_after_context_and_type)` or None if not expressible.

    ONE equality probe per criterion, INTERSECTed on `entity_uuid`, then the sort
    applied to the survivors -- the shape `fast_slot_filter` already uses for a
    conjunction, which is proven here and does not need reinventing.

    A filter and a sort may name DIFFERENT properties; that is two rows of the
    same table for one entity, which is why the intersect is on `entity_uuid`
    rather than everything being read from a single row.
    """
    t = f"{space_id}_entity_prop_sort"
    params: List[Any] = []
    # $1 is the context. $2 is the entity type ONLY when typed -- in the untyped
    # form the column is not referenced at all, and a parameter that appears
    # nowhere has no inferable type ("could not determine data type of $2").
    fixed = 2 if typed else 1
    def p(v):
        params.append(v)
        return f"${len(params) + fixed}"

    parts: List[str] = []
    for prop, op, value in terms:
        dt = _DATATYPES.get(prop)
        if dt is None:
            return None
        pu = p(_u(prop))
        if op in ("eq", "has"):
            # MEMBERSHIP, from `value_all`, never from the MIN lane. An entity
            # may carry several values and the MIN is only the smallest; served
            # from it, `eq` would match one value in three and return a subset
            # that still looks like a complete answer.
            parts.append(f"SELECT entity_uuid FROM {t} WHERE context_uuid = $1 "
                         f"AND property_uuid = {pu} AND value_all @> ARRAY[{p(str(value))}]::text[]")
        elif op == "ne":
            parts.append(f"SELECT entity_uuid FROM {t} WHERE context_uuid = $1 "
                         f"AND property_uuid = {pu} AND NOT (value_all @> ARRAY[{p(str(value))}]::text[])")
        elif op in ("gte", "lte"):
            if dt != "dateTime":
                return None
            # RANGE reads the typed lane, which holds the MIN. On a multi-valued
            # property that compares against the smallest value -- documented in
            # the plan as the one place the two gates differ. Both dateTime
            # properties are single-valued in practice.
            cmp = ">=" if op == "gte" else "<="
            parts.append(f"SELECT entity_uuid FROM {t} WHERE context_uuid = $1 "
                         f"AND property_uuid = {pu} AND value_dt IS NOT NULL "
                         f"AND value_dt {cmp} {p(str(value))}::timestamp")
        else:
            return None

    if sort_by:
        dt = _DATATYPES.get(sort_by)
        lane = _SORT_LANE.get(dt or "")
        if lane is None:
            return None
        su = p(_u(sort_by))
        direction = "DESC" if descending else "ASC"
        # NULLS LAST in both directions: an entity missing the sort property
        # belongs at the end of the list, not at the top of a descending one.
        collate = ' COLLATE "C"' if lane == "value_text" else ""
        # TIE-BREAK ON THE ENTITY URI, not on `entity_uuid`, because the SPARQL
        # query this replaces breaks ties with `?s`. `entity_uuid` is a hash of
        # the URI, so its order is unrelated -- five entities sharing a name came
        # back b,e,a,c,d here against a,b,c,d,e there.
        #
        # NOT AN EDGE CASE, which is why it is worth the join. Two of the seven
        # sortable properties are `uri` typed with a handful of distinct values
        # (`hasObjectStatusType`, `hasKGEntityType`), so sorting by one of those
        # ties almost every row and the TIE-BREAK IS THE PAGE ORDER.
        #
        # Costs less than it looks: the index still supplies `{lane}` order, so
        # PostgreSQL adds an Incremental Sort within each tie group rather than
        # sorting the population.
        order = f"s.{lane}{collate} {direction} NULLS LAST, s.entity_uri"
        # TWO FORMS, not one with `$2 IS NULL OR ...`. That OR is unsatisfiable
        # as an index predicate: the planner cannot know $2 is non-null, so it
        # will not use `entity_type_uuid` as an equality prefix, and the ordered
        # scan degrades to a sort of the population. The untyped form drops the
        # column entirely and is served by the `_any_` indexes instead.
        if typed:
            base = (f"SELECT s.entity_uri FROM {t} s "
                    f"WHERE s.context_uuid = $1 AND s.property_uuid = {su} "
                    f"AND s.entity_type_uuid = $2")
        else:
            base = (f"SELECT s.entity_uri FROM {t} s "
                    f"WHERE s.context_uuid = $1 AND s.property_uuid = {su}")
        if parts:
            base += " AND s.entity_uuid IN (" + " INTERSECT ".join(parts) + ")"
        sql = f"{base} ORDER BY {order} LIMIT ${len(params) + fixed + 1} OFFSET ${len(params) + fixed + 2}"
        return sql, params

    if not parts and not sort_by:
        # A TYPED LISTING WITH NO SORT AND NO FILTERS. Served, not declined:
        # "all entities of this type, default order" is the most common browse,
        # and declining sent it to the SPARQL walk (3.7 s warm, 30 s when the
        # transaction timeout killed it).
        #
        # ORDERED BY entity_uri, which is what the SPARQL query it replaces
        # does (`ORDER BY ?s`). NOT by `entity_uuid`, which is a hash: the
        # sibling `fast_typed_subject_page` orders by `subject_uuid` and so
        # already disagrees with SPARQL, and reproducing that here would change
        # the observed order of every typed browse.
        #
        # DISTINCT because the table holds one row per indexed property; with
        # `idx_{space}_eps_type_uri` those duplicates are adjacent, so this is a
        # unique index-only scan rather than a hash aggregate.
        if not typed:
            return None                 # untyped default; `fast_typed_subject_page` owns it
        return (f"SELECT DISTINCT s.entity_uri FROM {t} s "
                f"WHERE s.context_uuid = $1 AND s.entity_type_uuid = $2 "
                f"ORDER BY s.entity_uri "
                f"LIMIT ${len(params) + fixed + 1} OFFSET ${len(params) + fixed + 2}"), params

    if not parts:
        return None                     # nothing to serve; caller's default path
    inner = " INTERSECT ".join(parts)
    # The type restriction applies here too. Left off, a typed listing with only
    # filters would page entities of EVERY type -- extra rows rather than
    # missing ones, which is the failure that looks like working software.
    #
    # ORDERED BY THE ENTITY URI, not by `entity_uuid`, because that is what the
    # SPARQL query this replaces does (`ORDER BY ?s`) and a filtered page must
    # not shuffle merely because it got faster. `entity_uuid` is a hash, so its
    # order is arbitrary with respect to the URI -- caught by
    # `test_fast_path_and_sparql_return_the_same_page`, which compared the two
    # paths and found the same rows in a different order.
    #
    # This costs a sort, where the sorted branch above gets its order from the
    # index. Acceptable here precisely because a filter narrows first: the sort
    # is over the survivors, not the population.
    sql = (f"SELECT (SELECT u.entity_uri FROM {t} u"
           f"          WHERE u.entity_uuid = f.entity_uuid AND u.context_uuid = $1"
           f"          LIMIT 1) AS entity_uri FROM ({inner}) f "
           f" WHERE $2::uuid IS NULL OR EXISTS ("
           f"     SELECT 1 FROM {t} ty WHERE ty.entity_uuid = f.entity_uuid"
           f"       AND ty.context_uuid = $1 AND ty.entity_type_uuid = $2)"
           f" ORDER BY 1 LIMIT ${len(params) + fixed + 1} OFFSET ${len(params) + fixed + 2}")
    return sql, params


async def fast_entity_prop_page(
    impl, space_id: str, graph_id: str, page_size: int, offset: int,
    entity_type_uri: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    sort_by: Optional[str] = None,
    sort_order: str = "asc",
) -> Optional[List[str]]:
    """An ordered page of entity URIs, or None to decline.

    Declining is always safe -- the caller falls back to the SPARQL properties
    query, which is slow and correct. Serving when the table is short is not,
    which is why every uncertainty here returns None rather than guessing.
    """
    from .sparql_sql_space_impl import _generate_term_uuid

    # DECLINES ARE LOGGED AT INFO, not DEBUG.
    #
    # A fast path that silently declines is undiagnosable in production, which
    # runs at INFO: the table was correct, populated, unblocked and readable,
    # the wiring was deployed, and the listing still fell to the SPARQL walk
    # with nothing anywhere saying why. Working that out took static analysis
    # and a hand-off. One line at INFO answers it in seconds.
    #
    # Cheap by construction: at most one line per declined request, and the
    # served path logs nothing extra.
    terms = _filter_terms(filters)
    if terms is None:
        logger.info("prop_sort DECLINE(%s): unexpressible filter key in %s",
                    space_id, sorted(filters or {}))
        return None
    if not terms and not sort_by and entity_type_uri is None:
        # An UNTYPED listing with no sort and no filters is the plain default,
        # which `fast_typed_subject_page` serves from the quads. A TYPED one is
        # served here.
        logger.info("prop_sort DECLINE(%s): untyped listing with no sort or "
                    "filter; the plain default path owns it", space_id)
        return None

    built = build_page_sql(space_id, terms, sort_by,
                           descending=(sort_order or "asc").lower() == "desc",
                           typed=entity_type_uri is not None)
    if built is None:
        logger.info("prop_sort DECLINE(%s): unexpressible shape sort_by=%s "
                    "filters=%s", space_id, sort_by,
                    sorted(k for k, v in (filters or {}).items() if v))
        return None
    sql, params = built

    g_uuid = _generate_term_uuid(graph_id, 'U')
    ty = _u(entity_type_uri) if entity_type_uri else None
    try:
        async with impl.db_impl.connection_pool.acquire() as conn:
            if await prop_sort_blocked(conn, space_id, entity_type_uri):
                logger.info("prop_sort DECLINE(%s): blocked (space or type %s)",
                            space_id, entity_type_uri)
                return None
            head = (g_uuid, ty) if entity_type_uri else (g_uuid,)
            rows = await conn.fetch(sql, *head, *params, page_size, offset)
            # The URI comes straight out of the ordered scan. It used to be a
            # second lookup keyed by `entity_uuid`, which had to be re-ordered
            # afterwards -- an unordered `ANY()` whose result, used directly,
            # would silently discard the sort this path exists to produce.
            return [r["entity_uri"] for r in rows if r["entity_uri"] is not None]
    except Exception:
        logger.warning("prop_sort page failed, caller will fall back", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# The coverage marker, and the block that must stay in step with it
# ---------------------------------------------------------------------------

async def take_prop_sort_block(conn, space_id: str, entity_type_uuid,
                               reason: str) -> None:
    """Declare a space, or one type in it, AT RISK. NULL type = whole space."""
    try:
        await conn.execute(
            "INSERT INTO prop_sort_block (space_id, entity_type_uuid, reason)"
            " VALUES ($1, $2, $3)"
            " ON CONFLICT (space_id, entity_type_uuid) DO UPDATE SET"
            "   reason = EXCLUDED.reason",
            space_id, entity_type_uuid, reason)
    except Exception as exc:
        logger.debug("could not take prop_sort_block for %s: %s", space_id, exc)


async def release_prop_sort_block(conn, space_id: str, entity_type_uuid) -> None:
    """Only ever call this having just MEASURED coverage."""
    try:
        if entity_type_uuid is None:
            await conn.execute(
                "DELETE FROM prop_sort_block WHERE space_id = $1"
                "  AND entity_type_uuid IS NULL", space_id)
        else:
            await conn.execute(
                "DELETE FROM prop_sort_block WHERE space_id = $1"
                "  AND entity_type_uuid = $2", space_id, entity_type_uuid)
    except Exception as exc:
        logger.debug("could not release prop_sort_block for %s: %s", space_id, exc)


async def record_prop_sort_coverage(conn, space_id: str, entity_type_uuid,
                                    in_table: int, of_type: int) -> None:
    """Record what the probe measured, AND keep the block in step with it.

    `prop_sort_coverage` was created with the table and then never written by
    anything, which is worse than not having it: an operator diagnosing a slow
    listing found it empty and reasonably read that as "coverage was never
    established", when in fact nothing had ever recorded a number. An empty
    table that looks like a signal is a trap.

    `complete` is `in_table >= of_type`, not `==`, for the reason
    `record_slot_sort_coverage` gives: the table can legitimately hold rows for
    entities the type count no longer sees, and that direction costs no matches.
    Short is the only dangerous direction.

    MEASURING AND GATING STAY TOGETHER. This is the only place that measures, so
    it is the only place entitled to decide whether a type is at risk. Splitting
    them is what produced every marker-lifecycle bug in `issues/161`: something
    cleared one and did not restore the other.
    """
    try:
        await conn.execute(
            "INSERT INTO prop_sort_coverage (space_id, entity_type_uuid,"
            "  entities_in_table, entities_of_type, complete, verified_at)"
            " VALUES ($1, $2, $3, $4, $5, NOW())"
            " ON CONFLICT (space_id, entity_type_uuid) DO UPDATE SET"
            "  entities_in_table = EXCLUDED.entities_in_table,"
            "  entities_of_type  = EXCLUDED.entities_of_type,"
            "  complete          = EXCLUDED.complete,"
            "  verified_at       = EXCLUDED.verified_at",
            space_id, entity_type_uuid, int(in_table), int(of_type),
            bool(in_table >= of_type and of_type > 0))
        if in_table >= of_type and of_type > 0:
            await release_prop_sort_block(conn, space_id, entity_type_uuid)
        else:
            await take_prop_sort_block(
                conn, space_id, entity_type_uuid,
                reason=f"coverage {in_table}/{of_type}")
    except Exception as exc:
        logger.debug("could not record prop_sort_coverage for %s: %s",
                     space_id, exc)


async def clear_prop_sort_coverage(conn, space_id: str) -> None:
    """Drop every marker for a space; a bulk load invalidates them.

    An import repopulates the quads long before a resync rebuilds the derived
    tables (`issues/159`), so a marker written beforehand describes a table that
    no longer covers the data.
    """
    try:
        await conn.execute(
            "DELETE FROM prop_sort_coverage WHERE space_id = $1", space_id)
    except Exception as exc:
        logger.debug("could not clear prop_sort_coverage for %s: %s", space_id, exc)
