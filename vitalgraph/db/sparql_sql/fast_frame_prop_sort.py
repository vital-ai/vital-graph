"""Serve a sorted, filtered page of TOP-LEVEL (Assertion) frames.

The frame twin of `fast_prop_sort`, reading `{space}_frame_prop_sort`.

SERVES EVERY TAB. `frame_prop_sort` holds every frame, with the resolved form
type in a column, so Assertion / Aspect / All differ by one predicate.

It did not always. An earlier revision scoped the TABLE to Assertions, which
made form type a property of the population rather than a filter. Traversal is
general -- the parent -> child hop over the edge table is the same hop whatever
a frame's form type is -- so a table that admits only one form type can only
answer half the traversals put to it. Measured on `lead_nurture_grouped`, every
one of its 900,000 child frames resolves to Aspect, so no parent-scoped listing
there could be served at all.

A tab is a FILTER, not a population. Assertion means a frame not enclosed by an
entity; Aspect means one that is. Neither has any bearing on which frames a
traversal reaches.

`value_num` is live here where it is dead for entities: `hasFrameSequence` is
an integer, so a frame list ordered by authored sequence is an ordered index
scan on the numeric lane.

PARENT-SCOPED LISTINGS ARE SERVED, not declined. "The children of this frame" is
a single typed hop, and `{space}_edge` is the table built for it --
`idx_{space}_edge_type_src` is `(edge_type_uuid, source_node_uuid)`, so it is a
seek. It joins the property criteria as one more INTERSECT conjunct, so
parent + filter + sort is one plan rather than a fallback.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from .sync_frame_prop_sort import _u, ASSERTION_URI, ASPECT_URI  # noqa: E402

CHILD_FRAME_EDGE_URI = "http://vital.ai/ontology/haley-ai-kg#Edge_hasKGFrame"

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
CORE = "http://vital.ai/ontology/vital-core#"
VITAL = "http://vital.ai/ontology/vital#"
AIMP = "http://vital.ai/ontology/vital-aimp#"

# Mirrors `_FILTERABLE_FRAME_PROPERTIES` + the sequence property.
_DATATYPES = {
    f"{CORE}hasName": "string",
    f"{VITAL}hasObjectModificationDateTime": "dateTime",
    f"{AIMP}hasObjectCreationTime": "dateTime",
    f"{HALEY}hasKGFormType": "uri",
    f"{AIMP}hasObjectStatusType": "uri",
    f"{HALEY}hasKGFrameType": "uri",
    f"{HALEY}hasKGFrameTypeDescription": "string",
    f"{HALEY}hasFrameSequence": "integer",
}

_SORT_LANE = {"string": "value_text", "uri": "value_text",
              "dateTime": "value_dt", "integer": "value_num"}


async def frame_prop_sort_blocked(conn, space_id: str,
                                  frame_type_uri: Optional[str] = None) -> bool:
    """Whether `{space}_frame_prop_sort` is known to be at risk.

    Reads the WHOLE-SPACE block in `slot_sort_block` as well as its own per-type
    table, so restore and resync — which take a space-wide block — cover this
    table too without any new site having to remember it.

    Defaults to blocked on any uncertainty: not knowing is not the same as
    knowing it is fine, and being wrong here yields a confident subset.
    """
    ty = _u(frame_type_uri) if frame_type_uri else None
    try:
        if await conn.fetchrow(
                "SELECT 1 FROM slot_sort_block "
                " WHERE space_id = $1 AND entity_type_uuid IS NULL LIMIT 1", space_id):
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
        logger.info("frame_prop_sort DECLINE(%s): block table unreadable, "
                    "failing closed: %s", space_id, exc)
        return True
    return row is not None


def _filter_terms(filters: Optional[Dict[str, Any]]) -> Optional[List[tuple]]:
    """Structured filter values -> `(property_uri, op, value)`.

    Returns None for anything unrecognised so the caller declines the listing
    rather than serving a subset of the filters.
    """
    if not filters:
        return []
    known = {
        "status": (f"{AIMP}hasObjectStatusType", "eq"),
        "exclude_status": (f"{AIMP}hasObjectStatusType", "ne"),
        "created_after": (f"{AIMP}hasObjectCreationTime", "gte"),
        "created_before": (f"{AIMP}hasObjectCreationTime", "lte"),
        "modified_after": (f"{VITAL}hasObjectModificationDateTime", "gte"),
        "modified_before": (f"{VITAL}hasObjectModificationDateTime", "lte"),
        "frame_type_uri": (f"{HALEY}hasKGFrameType", "eq"),
    }
    out: List[tuple] = []
    for key, value in (filters or {}).items():
        if value in (None, "", []):
            continue
        if key not in known:
            return None
        prop, op = known[key]
        out.append((prop, op, value))
    return out


def build_frame_page_sql(space_id: str, terms: List[tuple], sort_by: Optional[str],
                         descending: bool, typed: bool = True,
                         parent_uri: Optional[str] = None,
                         form_uuid=None) -> Optional[tuple]:
    """`(sql, params)` or None if the shape is not expressible.

    `parent_uri` restricts to a parent's CHILD frames, and it is served from
    `{space}_edge` rather than declined. That table exists for exactly this hop:
    `idx_{space}_edge_type_src` is `(edge_type_uuid, source_node_uuid)`, so
    "destinations of Edge_hasKGFrame from this parent" is a seek, not a scan --
    the same index the traversal planner uses. It INTERSECTs with the property
    criteria like any other conjunct.
    """
    t = f"{space_id}_frame_prop_sort"
    params: List[Any] = []
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
        if op == "eq":
            parts.append(f"SELECT frame_uuid FROM {t} WHERE context_uuid = $1 "
                         f"AND property_uuid = {pu} AND value_all @> ARRAY[{p(str(value))}]::text[]")
        elif op == "ne":
            parts.append(f"SELECT frame_uuid FROM {t} WHERE context_uuid = $1 "
                         f"AND property_uuid = {pu} AND NOT (value_all @> ARRAY[{p(str(value))}]::text[])")
        elif op in ("gte", "lte"):
            if dt != "dateTime":
                return None
            cmp = ">=" if op == "gte" else "<="
            parts.append(f"SELECT frame_uuid FROM {t} WHERE context_uuid = $1 "
                         f"AND property_uuid = {pu} AND value_dt IS NOT NULL "
                         f"AND value_dt {cmp} {p(str(value))}::timestamp")
        else:
            return None

    if form_uuid is not None:
        # A TAB IS A FILTER. Applied to the resolved column, so it composes
        # with the traversal hop and the property criteria rather than
        # deciding what the table contains.
        fu = p(form_uuid)
        parts.append(f"SELECT frame_uuid FROM {t} WHERE context_uuid = $1 "
                     f"AND form_type_uuid = {fu}")

    if parent_uri:
        # The child-frame hop, from the edge table. Same INTERSECT shape as a
        # property criterion, so it composes with filters and the sort without
        # any special case downstream.
        pe = p(_u(CHILD_FRAME_EDGE_URI))
        ps = p(_u(parent_uri))
        parts.append(f"SELECT dest_node_uuid AS frame_uuid FROM {space_id}_edge "
                     f"WHERE edge_type_uuid = {pe} AND source_node_uuid = {ps} "
                     f"AND context_uuid = $1")

    if sort_by:
        dt = _DATATYPES.get(sort_by)
        lane = _SORT_LANE.get(dt or "")
        if lane is None:
            return None
        su = p(_u(sort_by))
        direction = "DESC" if descending else "ASC"
        collate = ' COLLATE "C"' if lane == "value_text" else ""
        # EMIT THE PARTIAL INDEX'S OWN PREDICATE, or the index cannot be used.
        # `_..._num` and `_..._dt` are partial (`WHERE value_x IS NOT NULL`) and
        # PostgreSQL will only choose a partial index when the query IMPLIES its
        # predicate. Without this the sort fell back to a parallel Sort in BOTH
        # directions -- measured 43 ms and 13,991 buffers where the ordered scan
        # is sub-millisecond. The schema comment beside those indexes records
        # exactly this rule; the query simply did not honour it.
        #
        # Not needed for `value_text`, whose index is not partial.
        #
        # It also narrows nothing the caller would miss: the SPARQL this
        # replaces binds the sort triple as REQUIRED, so a subject without the
        # property is absent there too.
        lane_not_null = f" AND s.{lane} IS NOT NULL" if lane != "value_text" else ""
        # Tie-break on the URI, matching the SPARQL `ORDER BY ?frame`, and it is
        # the last index column so the correct order is the index order.
        order = f"s.{lane}{collate} {direction} NULLS LAST, s.frame_uri"
        if typed:
            base = (f"SELECT s.frame_uri FROM {t} s "
                    f"WHERE s.context_uuid = $1 AND s.property_uuid = {su} "
                    f"AND s.frame_type_uuid = $2{lane_not_null}")
        else:
            base = (f"SELECT s.frame_uri FROM {t} s "
                    f"WHERE s.context_uuid = $1 AND s.property_uuid = {su}"
                    f"{lane_not_null}")
        if parts:
            base += " AND s.frame_uuid IN (" + " INTERSECT ".join(parts) + ")"
        return (f"{base} ORDER BY {order} "
                f"LIMIT ${len(params) + fixed + 1} OFFSET ${len(params) + fixed + 2}"), params

    if not parts:
        return None
    inner = " INTERSECT ".join(parts)
    sql = (f"SELECT (SELECT u.frame_uri FROM {t} u"
           f"          WHERE u.frame_uuid = f.frame_uuid AND u.context_uuid = $1"
           f"          LIMIT 1) AS frame_uri FROM ({inner}) f "
           f" WHERE {'$2::uuid IS NULL OR ' if typed else ''}"
           f"   {'EXISTS (SELECT 1 FROM ' + t + ' ty WHERE ty.frame_uuid = f.frame_uuid AND ty.context_uuid = $1 AND ty.frame_type_uuid = $2)' if typed else 'TRUE'}"
           f" ORDER BY 1 LIMIT ${len(params) + fixed + 1} OFFSET ${len(params) + fixed + 2}")
    return sql, params


async def fast_frame_prop_page(
    impl, space_id: str, graph_id: str, page_size: int, offset: int,
    form_type: Optional[str] = None,
    frame_type_uri: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    sort_by: Optional[str] = None,
    sort_order: str = "asc",
    parent_uri: Optional[str] = None,
) -> Optional[List[str]]:
    """An ordered page of frame URIs, or None to decline.

    EVERY TAB IS SERVED. The table holds every frame with the resolved form
    type in a column, so Assertion, Aspect and All are one filter apart. An
    earlier revision indexed Assertions only and had to decline the rest —
    which also made a parent-scoped listing unservable, since a child of an
    Assertion is an Aspect.
    """
    from .sparql_sql_space_impl import _generate_term_uuid

    # Declines log at INFO, for the reason `fast_prop_sort` records: a silent
    # decline is undiagnosable in a deployment running at INFO, and the symptom
    # (a correct, populated, unblocked table that is simply never used) points
    # at everything except the gate.
    terms = _filter_terms(filters)
    if terms is None:
        logger.info("frame_prop_sort DECLINE(%s): unexpressible filter key in %s",
                    space_id, sorted(filters or {}))
        return None
    if not terms and not sort_by and not parent_uri and form_type is None:
        logger.info("frame_prop_sort DECLINE(%s): nothing to serve — no sort, "
                    "filter, parent or form type", space_id)
        return None

    # Only Assertion and Aspect are resolvable to a stored value; the All tab
    # passes None and is simply unfiltered.
    form_uuid = None
    if form_type in (ASSERTION_URI, ASPECT_URI):
        form_uuid = _u(form_type)
    elif form_type is not None:
        logger.info("frame_prop_sort DECLINE(%s): unrecognised form_type %s",
                    space_id, form_type)
        return None            # decline rather than ignore it

    built = build_frame_page_sql(space_id, terms, sort_by,
                                descending=(sort_order or "asc").lower() == "desc",
                                typed=frame_type_uri is not None,
                                parent_uri=parent_uri, form_uuid=form_uuid)
    if built is None:
        logger.info("frame_prop_sort DECLINE(%s): unexpressible shape sort_by=%s",
                    space_id, sort_by)
        return None
    sql, params = built

    g_uuid = _generate_term_uuid(graph_id, 'U')
    ty = _u(frame_type_uri) if frame_type_uri else None
    try:
        async with impl.db_impl.connection_pool.acquire() as conn:
            if await frame_prop_sort_blocked(conn, space_id, frame_type_uri):
                logger.info("frame_prop_sort DECLINE(%s): blocked (space or "
                            "type %s)", space_id, frame_type_uri)
                return None
            head = (g_uuid, ty) if frame_type_uri else (g_uuid,)
            rows = await conn.fetch(sql, *head, *params, page_size, offset)
            return [r["frame_uri"] for r in rows if r["frame_uri"] is not None]
    except Exception:
        logger.warning("frame prop_sort page failed, caller will fall back",
                       exc_info=True)
        return None
