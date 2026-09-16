"""Read slot VALUES out of `{space}_entity_slot_sort` (issues/208).

THE THIRD THING THE TABLE CAN DO. `fast_slot_sort` orders a population by a
slot value and `fast_slot_filter` selects one; both project the entity URI and
neither returns the value. `slot_sort_range` and `component_intersect` read it
too, and both use the value as a search key. Four readers, and until this one
nothing handed a value back.

WHY IT IS WORTH A MODULE. Measured on `lead_nurture_grouped` (74.5M quads,
4.06M slot-sort rows), one 25-entity page and eight columns spanning seven frame
paths:

    the same 8 values from the QUADS         57.65 ms    62,953 buffers
    page + projection from this table         0.76 ms     1,163 buffers

identical values, checked pair by pair against the quad walk. The
`include_entity_graph` fan-out that a list view uses today to get the same eight
columns costs 3.5-5.1 s and returns ~18,000 quads per 25-entity page.

IT IS ENTITY-LED, AND THAT IS THE WHOLE TRICK. The three lane indexes are
`(context, entity_type, frame_type_path, slot_type, value, entity_uuid)` — built
for the FILTER's direction, seek a value and read out entities. A projection
already has the entities and wants the values, which is the other way round, so
it probes `idx_*_ess_entity` instead and accepts a heap fetch: 276 buffers for
25 entities, of which 222 are heap. Not index-only and it does not matter at
page scale.

Two consequences of being entity-led, both measured:

  * Cost tracks SLOTS PER ENTITY, not columns asked for — the probe reads every
    slot row of each entity (1,025 rows to return 200) and filters. One column
    costs what eight cost.
  * Columns under DIFFERENT frame paths share one probe, because the path is
    returned rather than matched in SQL. The prefix-led alternative needs one
    arm per path and measured 5x slower.

THE PATH IS STILL MATCHED, just in Python rather than in the index: a row counts
for a column only when its `frame_type_path` equals that column's path exactly.
`component_intersect.py:39` records why a loose match is a wrong answer — it
admits entities reached by a different path.

VALUES COME BACK AS A LIST. An entity may legitimately carry several slots of
one type: 1,200 such (entity, slot_type) pairs on `kg_load_test` at up to 3, and
`sparql_sql_schema.py:1191` records 9,354 at up to 6 on `prod_kg`. A sort
collapses them with MIN; a projection that did the same would silently show one
of them.

COVERAGE GATES THIS, and the asymmetry is the reason. A short table makes a sort
MIS-ORDER a page and a filter return a SUBSET; it makes a projection render a
BLANK COLUMN, which reads as "no value set" — plausible, no error, no way to
tell. So this is served only when `slot_sort_is_blocked` says no, exactly like
the filter, and the CALLER applies that gate.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .fast_slot_sort import _LANE, _term_uuid

logger = logging.getLogger(__name__)

# The column each lane reads. `value_all` has no equivalent here: this table
# stores one value per SLOT and multiplicity comes from several slot ROWS, not
# from an array, which is why the caller gets a list assembled per entity.
_LANE_COLUMN = {"text": "value_text", "num": "value_num", "dt": "value_dt"}


class ProjectionColumn:
    """One resolved column: the uuids to probe with and the lane to read."""

    __slots__ = ("alias", "path", "slot_type", "lane")

    def __init__(self, alias: str, path: Tuple, slot_type, lane: str):
        self.alias = alias
        self.path = path
        self.slot_type = slot_type
        self.lane = lane


def resolve_columns(projection) -> Optional[List[ProjectionColumn]]:
    """Resolve wire columns to uuids, or None if ANY of them is unanswerable.

    None means DECLINE THE WHOLE PROJECTION rather than serve the columns that
    happen to resolve. A partially applied projection is a blank column, which
    is the one failure this module exists to avoid -- the same rule
    `fast_slot_filter._eq_criteria` follows for a conjunction.

    The wire model already refuses an empty `frame_path` and an unknown
    `slot_class_uri`, so reaching those checks here means a caller built the
    objects directly. They are repeated rather than assumed.
    """
    if not projection:
        return None
    out = []
    for p in projection:
        slot_type = getattr(p, "slot_type", None)
        path = list(getattr(p, "frame_path", None) or [])
        lane = _LANE.get(getattr(p, "slot_class_uri", None) or "")
        alias = getattr(p, "alias", None)
        if not (alias and slot_type and path) or lane is None:
            logger.info(
                "slot projection declined: column %r is missing an alias, a "
                "slot_type, a frame_path, or names an unmapped slot class",
                alias)
            return None
        out.append(ProjectionColumn(
            alias=alias,
            path=tuple(_term_uuid(f) for f in path),
            slot_type=_term_uuid(slot_type),
            lane=lane))
    return out


async def project_slot_values(
    conn, space_id: str, graph_uri: str, entity_uris: Sequence[str],
    columns: List[ProjectionColumn],
) -> Dict[str, Dict[str, List[Any]]]:
    """`{entity_uri: {alias: [values]}}` for the page, from the sort table.

    Every requested alias is present for every requested entity, with an empty
    list where the table holds no such slot. An absent KEY would be ambiguous
    between "no value" and "not asked for"; an empty list is not.

    No term join: an entity's uuid is `uuid5` over its URI (`_term_uuid`), so
    the page's URIs give both the probe keys and the map back, which is what the
    write path does too. That is ~800 buffers cheaper than joining `term` to
    recover URIs the caller already has.
    """
    out: Dict[str, Dict[str, List[Any]]] = {
        uri: {c.alias: [] for c in columns} for uri in entity_uris}
    if not entity_uris or not columns:
        return out

    uuid_of = {_term_uuid(u): u for u in entity_uris}
    # A column is identified by (path, slot_type); two columns may share a slot
    # type under different paths, and the path is what tells them apart.
    by_key: Dict[Tuple, List[ProjectionColumn]] = {}
    for c in columns:
        by_key.setdefault((c.path, c.slot_type), []).append(c)

    t = f"{space_id}_entity_slot_sort"
    rows = await conn.fetch(
        f"""
        SELECT entity_uuid, frame_type_path, slot_type_uuid,
               value_text, value_num, value_dt
        FROM {t}
        WHERE context_uuid = $1
          AND entity_uuid = ANY($2::uuid[])
          AND slot_type_uuid = ANY($3::uuid[])
        """,
        _term_uuid(graph_uri), list(uuid_of), [c.slot_type for c in columns])

    for r in rows:
        uri = uuid_of.get(r["entity_uuid"])
        if uri is None:
            continue
        # The path must match WHOLE. A row under a different path describes a
        # different column, and counting it here is the wrong-rows failure
        # `component_intersect` names.
        key = (tuple(r["frame_type_path"] or ()), r["slot_type_uuid"])
        for c in by_key.get(key, ()):
            v = r[_LANE_COLUMN[c.lane]]
            if v is not None:
                out[uri][c.alias].append(v)

    # Deterministic order within a column. The rows arrive in whatever order the
    # probe produced, so an entity with three values would otherwise render them
    # differently between two identical requests.
    for per_entity in out.values():
        for alias, vals in per_entity.items():
            if len(vals) > 1:
                vals.sort(key=lambda x: (x is None, str(x)))
    return out
