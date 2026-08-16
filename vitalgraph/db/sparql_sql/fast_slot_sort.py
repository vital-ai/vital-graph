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
`cardiff_kg`, 360 ms and 423,742 buffers for a 25-row page. Against the table
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


def can_serve(criteria) -> bool:
    """Whether this builder criteria object is a shape the table answers.

    Kept separate from the query so the endpoint can decide without a database
    round trip, and so the conditions are testable on their own.
    """
    sc = getattr(criteria, "sort_criteria", None)
    if not sc or len(sc) != 1:
        return False
    s = sc[0]
    if s.sort_type not in ("entity_frame_slot", "frame_slot"):
        return False
    if not s.slot_type:
        return False
    if _LANE.get(s.slot_class_uri or "") is None:
        return False
    # At least one frame hop. Depth beyond that is fine — the type path is
    # stored and matched whole — but a slot hanging directly off the entity is
    # not in the table at all, and answering it from frame-borne rows would be
    # a wrong page rather than a slow one.
    if not (s.frame_path or []):
        return False
    # The table sorts a population; it does not select one.
    if getattr(criteria, "frame_criteria", None):
        return False
    if getattr(criteria, "entity_property_filters", None):
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


async def fast_slot_sort_page(
    conn, space_id: str, graph_uri: str, criteria,
    page_size: int, offset: int,
) -> Optional[List[str]]:
    """One ordered page of entity URIs, or None if unserved.

    None means "not my shape" AND "the table is not there / not populated" —
    both must fall back, and the caller cannot tell them apart, which is
    deliberate: a half-populated table answering a page would be a wrong answer.
    """
    if not can_serve(criteria):
        return None
    s = criteria.sort_criteria[0]
    lane = _LANE[s.slot_class_uri]
    col, agg_min, agg_max = _LANE_SQL[lane]
    descending = (s.sort_order or "asc").lower() == "desc"
    agg = agg_max if descending else agg_min
    direction = "DESC" if descending else "ASC"

    t = f"{space_id}_entity_slot_sort"
    t_term = f"{space_id}_term"

    ctx = _term_uuid(graph_uri)
    ent_t = _term_uuid(criteria.entity_type)
    slot_t = _term_uuid(s.slot_type)
    # The WHOLE path, in order — this is what makes a nested frame criterion
    # reachable. Matching only `frame_path[0]` would return rows for any slot of
    # that type anywhere under that root frame, which is a different question.
    frame_path = [_term_uuid(u) for u in s.frame_path]

    # frame_type_path is part of the index's leading columns, so it is matched
    # rather than left unconstrained.
    args = [ctx, ent_t, slot_t, frame_path]
    n = len(args)

    sql = f"""
        SELECT tm.term_text
        FROM (
            SELECT entity_uuid, {agg} AS sv
            FROM {t}
            WHERE context_uuid = $1
              AND entity_type_uuid = $2
              AND slot_type_uuid = $3
              AND frame_type_path = $4
              AND {col} IS NOT NULL
            GROUP BY entity_uuid
            ORDER BY sv {direction}, entity_uuid
            LIMIT ${n + 1} OFFSET ${n + 2}
        ) p
        JOIN {t_term} tm ON tm.term_uuid = p.entity_uuid
        ORDER BY p.sv {direction}, p.entity_uuid
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
    if not can_serve(criteria):
        return None
    s = criteria.sort_criteria[0]
    lane = _LANE[s.slot_class_uri]
    col, _mn, _mx = _LANE_SQL[lane]

    t = f"{space_id}_entity_slot_sort"
    ctx = _term_uuid(graph_uri)
    ent_t = _term_uuid(criteria.entity_type)
    slot_t = _term_uuid(s.slot_type)
    frame_path = [_term_uuid(u) for u in s.frame_path]
    args = [ctx, ent_t, slot_t, frame_path]

    try:
        return await conn.fetchval(f"""
            SELECT count(DISTINCT entity_uuid) FROM {t}
            WHERE context_uuid = $1 AND entity_type_uuid = $2
              AND slot_type_uuid = $3 AND frame_type_path = $4
              AND {col} IS NOT NULL
        """, *args)
    except Exception as exc:
        logger.debug("fast_slot_sort_count(%s) declined: %s", space_id, exc)
        return None
