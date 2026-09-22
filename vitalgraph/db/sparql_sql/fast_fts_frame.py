"""Serve an FTS frame page from `entity_slot_sort`, not from raw quads.

The general pipeline answers an FTS frame query by joining quads: owner entity →
every slot → slot type → the FTS match set. On a 49.7M-quad space that is fine
while the match set is small enough to inline (`_measure_fts_leaves`), and
ruinous when it is not. From production, 24h:

    app          119,254 matches   page/sort 7.4-25.5 s
    application  123,318 matches   count     10.8-21.1 s
    business      22,597 matches   count/page 9.3-21.9 s

`entity_slot_sort` already holds what those joins reconstruct — one row per slot
with its owning entity, its frame, its type and the entity's type — and
`entity_prop_sort` holds the entity properties a date filter or sort needs, in
typed, indexed lanes. Measured on the same shapes, 118,935 matches:

    + 30-day filter, page      14,695 ms -> 3.0 ms
    + filter + sort, page      17,212 ms -> 318 ms
    + sort only, page          32,697 ms -> 1,035 ms
    + filter, capped count     16,341 ms -> 302 ms

WHAT THIS PATH IS NOT ALLOWED TO DO. It must answer EXACTLY what the pipeline
answers or decline. The gate is therefore narrow and every unhandled shape
declines rather than approximating:

  * the table is a MIRROR, and a short mirror returns a confident subset. The
    read gate is the shared `slot_sort_block` list, same as `fast_slot_filter`,
    and not knowing counts as blocked (`issues/149`: a production type at 1.05%
    coverage whose own drift probe reported converged);
  * one entity can reach a frame through several slots, so the page is DISTINCT
    on the frame (`issues/223` counted such an entity twice);
  * ordering matches the pipeline exactly — the synthesized frame-uuid order
    when no sort is asked for, and `<sort lane> <dir>, frame URI COLLATE "C"`
    when one is, because the pipeline ties on the frame's URI TEXT;
  * date bounds go through `vitalgraph_iso_to_utc`, never `::timestamp`, which
    is how `value_dt` itself was derived (`ed165956`).
"""
from __future__ import annotations

import logging
import uuid as _uuid
from typing import Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

_VITALGRAPH_NS = _uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

#: Entity properties this path can filter or sort on, and the lane each uses.
#: Mirrors `_SORT_LANE` in `fast_prop_sort`; anything else declines.
_LANE = {"string": "value_text", "uri": "value_text", "dateTime": "value_dt"}

_RANGE_OPS = {"gte": ">=", "gt": ">", "lte": "<=", "lt": "<", "eq": "="}


def _term_uuid(text: str) -> _uuid.UUID:
    return _uuid.uuid5(_VITALGRAPH_NS, f"{text}\x00U")


def _prop_datatype(property_uri: str) -> Optional[str]:
    from ...sparql.kg_query_builder import _FILTERABLE_ENTITY_PROPERTIES
    return _FILTERABLE_ENTITY_PROPERTIES.get(property_uri)


def fts_frame_decline_reason(criteria) -> Optional[str]:
    """Why this path cannot serve `criteria`, or None if it can.

    Named rather than a bare False: the two paths differ by orders of magnitude,
    so "it declined" is not actionable while "slot_criteria present" is.
    """
    fts = getattr(criteria, "fts_criteria", None)
    if not fts:
        return "no fts_criteria"
    if not getattr(fts, "targets", None):
        return "fts_criteria carries no targets"
    if any(not getattr(t, "slot_type", None) for t in fts.targets):
        return "a target has no slot_type"
    # Without the entity type there is no coverage statement to check, and the
    # index on entity_slot_sort is keyed on it.
    if not getattr(criteria, "entity_type", None):
        return "no entity_type"
    for attr in ("search_string", "slot_criteria", "frame_criteria",
                 "vector_criteria", "multi_vector_criteria", "geo_criteria",
                 "entity_uris", "frame_type"):
        if getattr(criteria, attr, None):
            return f"{attr} present"
    for f in (getattr(criteria, "entity_property_filters", None) or []):
        dt = _prop_datatype(getattr(f, "property_uri", "") or "")
        if dt not in _LANE:
            return f"filter on unregistered or list property {f.property_uri}"
        if getattr(f, "operator", None) not in _RANGE_OPS:
            return f"filter operator {f.operator} not served here"
    sorts = list(getattr(criteria, "sort_criteria", None) or [])
    if len(sorts) > 1:
        return "more than one sort"
    for sc in sorts:
        if getattr(sc, "sort_type", None) != "entity_property":
            return f"sort_type {sc.sort_type} not served here"
        if _prop_datatype(getattr(sc, "property_uri", "") or "") not in _LANE:
            return "sort on unregistered or list property"
    return None


def can_serve_fts_frame(criteria) -> bool:
    return fts_frame_decline_reason(criteria) is None


async def _resolve_index(conn, space_id: str, index_name: str
                         ) -> Optional[Tuple[str, str]]:
    """(fts table, text-search config) for the requested index, or None.

    Resolves an alias exactly as the push-down does — a name in
    `search_mapping` resolves through `search_mapping_index` to the real index —
    so this path never answers a query the pipeline would answer differently.
    """
    real = index_name
    try:
        alias = await conn.fetchval(
            f"SELECT smi.index_name FROM {space_id}_search_mapping sm "
            f"JOIN {space_id}_search_mapping_index smi ON smi.mapping_id = sm.mapping_id "
            f"WHERE sm.index_name = $1 AND smi.index_type = 'fts' LIMIT 1", index_name)
        real = alias or index_name
    except Exception:
        pass
    try:
        langs = await conn.fetchval(
            f"SELECT languages FROM {space_id}_fts_index WHERE index_name = $1", real)
    except Exception:
        return None
    if langs is None:
        return None
    cfg = (list(langs) or ["english"])[0]
    table = f"{space_id}_fts_{real}"
    if not await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", table):
        return None
    return table, cfg


def _build(space_id: str, criteria, fts_table: str, cfg: str, *, for_count: bool,
           cap: Optional[int], page_size: int, offset: int) -> Tuple[str, list]:
    """The page or count SQL, and its parameters."""
    ess = f"{space_id}_entity_slot_sort"
    eps = f"{space_id}_entity_prop_sort"
    term = f"{space_id}_term"
    fts = criteria.fts_criteria
    args: List[Any] = []

    def p(v) -> str:
        args.append(v)
        return f"${len(args)}"

    ctx = p(_term_uuid(criteria.graph_uri))
    text = p(fts.text)
    slot_types = p([_term_uuid(t.slot_type) for t in fts.targets])
    entity_type = p(_term_uuid(criteria.entity_type))

    where = [
        f"m.tsv @@ websearch_to_tsquery('{cfg}'::regconfig, {text})",
        f"m.context_uuid = {ctx}",
        f"s.context_uuid = {ctx}",
        f"s.slot_type_uuid = ANY({slot_types}::uuid[])",
        f"s.entity_type_uuid = {entity_type}",
    ]
    for f in (getattr(criteria, "entity_property_filters", None) or []):
        lane = _LANE[_prop_datatype(f.property_uri)]
        op = _RANGE_OPS[f.operator]
        pu = p(_term_uuid(f.property_uri))
        if lane == "value_dt":
            # The same function `value_dt` was derived with, so a bound with an
            # offset compares in UTC rather than being read as wall time.
            cmp_sql = f"e.value_dt {op} vitalgraph_iso_to_utc({p(str(f.value))})"
            lane_sql = "e.value_dt IS NOT NULL AND " + cmp_sql
        else:
            lane_sql = f'e.value_text COLLATE "C" {op} {p(str(f.value))}'
        where.append(
            f"EXISTS (SELECT 1 FROM {eps} e WHERE e.entity_uuid = s.entity_uuid "
            f"AND e.context_uuid = {ctx} AND e.property_uuid = {pu} AND {lane_sql})")

    sorts = list(getattr(criteria, "sort_criteria", None) or [])
    join_sort, order = "", "s.frame_uuid"
    select_extra = ""
    if sorts:
        sc = sorts[0]
        lane = _LANE[_prop_datatype(sc.property_uri)]
        spu = p(_term_uuid(sc.property_uri))
        direction = "DESC" if (sc.sort_order or "asc").lower() == "desc" else "ASC"
        collate = ' COLLATE "C"' if lane == "value_text" else ""
        join_sort = (f"JOIN {eps} sv ON sv.entity_uuid = s.entity_uuid "
                     f"AND sv.context_uuid = {ctx} AND sv.property_uuid = {spu}")
        # Tie on the frame's URI TEXT, which is what the pipeline orders by.
        # ORDER BY the SELECT ALIASES: under SELECT DISTINCT an ordering
        # expression must appear in the select list, and `sv.value_dt` or a
        # collated `ft.term_text` does not match the projected column.
        # The collation goes on the SELECT alias, not the ORDER BY: an output
        # name is only usable bare there, so `frame_uri COLLATE "C"` is read as
        # an expression over INPUT columns and fails to resolve.
        order = "sort_val {d}, frame_uri ASC".format(d=direction)
        select_extra = f", sv.{lane}{collate} AS sort_val"

    inner = (
        f'SELECT DISTINCT s.frame_uuid, ft.term_text COLLATE "C" AS frame_uri'
        f"{select_extra} "
        f"FROM {fts_table} m "
        f"JOIN {ess} s ON s.slot_uuid = m.subject_uuid "
        f"{join_sort} "
        f"JOIN {term} ft ON ft.term_uuid = s.frame_uuid "
        f"WHERE {' AND '.join(where)}")

    if for_count:
        limit = f" LIMIT {int(cap) + 1}" if cap else ""
        return (f"SELECT count(*) AS n FROM ({inner}{limit}) x", args)
    return (f"{inner} ORDER BY {order} LIMIT {int(page_size)} OFFSET {int(offset)}",
            args)


async def _gate(conn, space_id: str, criteria) -> Optional[str]:
    """Anything that makes serving from the mirror unsafe, or None."""
    from .fast_slot_filter import slot_sort_is_blocked
    if await slot_sort_is_blocked(conn, space_id, criteria.entity_type):
        return "slot_sort is blocked for this type"
    return None


async def _match_set_is_small(conn, fts_table: str, cfg: str, criteria) -> bool:
    """Would the general pipeline INLINE this match set?

    The two paths are complements, and the boundary is exactly the inline cap.
    Below it the pipeline emits the match set as a literal array, PostgreSQL
    estimates it correctly, and the quad joins are index probes over a handful
    of rows — measured on the test stack, a 14-row phrase sorted by date:
    115 ms through the pipeline against 4,858 ms through this path, because a
    mirror scan cannot beat 14 index probes. Above the cap the pipeline stops
    inlining and walks the owner side instead: 18-133 s, where this path is
    195-474 ms.

    So a small match set DECLINES here and is served by the pipeline. The count
    is bounded, so it costs the same few milliseconds whatever the term matches.

    SIZE IS NOT THE ONLY AXIS. What makes the pipeline collapse is walking the
    OWNER side, which a date filter or an entity-property sort forces. Measured
    on `saved application`, 4,327 matches:

        plain                pipeline    958 ms   |  this path  4,390 ms
        + filter + sort      pipeline  TIMED OUT  |  this path  6,687 ms
                                  (180 s)

    so a mid-sized PLAIN query stays with the pipeline while the same term with
    a filter or sort comes here. `_MIN_PLAIN` is the size above which a plain
    query is still worth taking (118,935 matches: 17.8 s against 991 ms). It is
    PROVISIONAL — two measured points either side, not a curve — and tunable
    with VG_FTS_FASTPATH_MIN_PLAIN.
    """
    import os
    from .generator import FTS_INLINE_MAX
    if FTS_INLINE_MAX <= 0:
        return False
    has_owner_work = bool(getattr(criteria, "entity_property_filters", None)
                          or getattr(criteria, "sort_criteria", None))
    floor = FTS_INLINE_MAX if has_owner_work else max(
        FTS_INLINE_MAX, int(os.getenv("VG_FTS_FASTPATH_MIN_PLAIN", "20000")))
    n = await conn.fetchval(
        f"SELECT count(*) FROM (SELECT 1 FROM {fts_table} "
        f"WHERE tsv @@ websearch_to_tsquery('{cfg}'::regconfig, $1) "
        f"AND context_uuid = $2 LIMIT {floor + 1}) x",
        criteria.fts_criteria.text, _term_uuid(criteria.graph_uri))
    return (n or 0) <= floor


async def fast_fts_frame_page(conn, space_id: str, graph_uri: str, criteria,
                              page_size: int, offset: int
                              ) -> Optional[List[str]]:
    """Frame URIs for one page, or None when this path declines.

    None means "ask the general pipeline", never "no results" — a decline and an
    empty page must not look alike to the caller.
    """
    reason = fts_frame_decline_reason(criteria)
    if reason:
        logger.debug("fts frame fast path declined: %s", reason)
        return None
    criteria.graph_uri = graph_uri
    if await _gate(conn, space_id, criteria):
        return None
    resolved = await _resolve_index(conn, space_id, criteria.fts_criteria.index_name)
    if resolved is None:
        return None
    if await _match_set_is_small(conn, *resolved, criteria):
        return None          # the pipeline inlines it and is faster there
    sql, args = _build(space_id, criteria, *resolved, for_count=False, cap=None,
                       page_size=page_size, offset=offset)
    rows = await conn.fetch(sql, *args)
    return [r["frame_uri"] for r in rows]


async def fast_fts_frame_count(conn, space_id: str, graph_uri: str, criteria,
                               cap: Optional[int]) -> Optional[int]:
    """Distinct matching frames, capped, or None when this path declines."""
    if fts_frame_decline_reason(criteria):
        return None
    criteria.graph_uri = graph_uri
    if await _gate(conn, space_id, criteria):
        return None
    resolved = await _resolve_index(conn, space_id, criteria.fts_criteria.index_name)
    if resolved is None:
        return None
    if await _match_set_is_small(conn, *resolved, criteria):
        return None          # the pipeline inlines it and is faster there
    sql, args = _build(space_id, criteria, *resolved, for_count=True, cap=cap,
                       page_size=0, offset=0)
    return await conn.fetchval(sql, *args)
