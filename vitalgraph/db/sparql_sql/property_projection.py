"""Read DIRECT entity property values for a page, from the quads (issues/208).

The sibling of `slot_projection`, for the other half of what a list view
renders: properties hanging straight off the entity — `hasName`, a status, a
modification time — rather than values reached through a frame.

WHY THE QUADS AND NOT `entity_prop_sort`, WHICH IS THE OBVIOUS ANSWER. The
issue named that table as the next increment. Measured, on
`lead_nurture_grouped`, five properties across a 25-entity page:

    entity_prop_sort   0.07 ms     62 buffers     PK seek, entity leads
    the quads          0.31 ms    696 buffers     PK seek, subject leads

identical values, 125 pairs checked. Both are noise next to the 0.76 ms the
slot half already costs, and at that price the quads win on everything else:

  * They are AUTHORITATIVE. `entity_prop_sort` is a derived table behind a
    block-list, and a short one renders a BLANK COLUMN that reads as "no value
    set" — `issues/194` found it unmaintained by seven write paths, with
    `wordnet_frames` missing 329,235 rows. A projection off the quads cannot be
    stale, so it needs no gate and can never go quietly blank.
  * They hold EVERY property. `entity_prop_sort` stores the SEVEN in
    `SORTABLE_PROPERTY_URIS`, so projecting anything else from it would return
    an empty column for a property the entity plainly has.

This is not an argument against that table. It exists because a SORT or FILTER
over a whole population is O(total) on the quads and O(page) on an ordered
index. A projection is neither: the page is already chosen, so the probe is
bounded by it, and the collapse the table offers has nothing to collapse.

The probe is subject-led — `(subject_uuid, predicate_uuid, object_uuid,
context_uuid)` is the quad table's primary key — and bounded twice over, by the
page and by the properties asked for.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from .fast_slot_sort import _term_uuid

logger = logging.getLogger(__name__)


class PropertyColumn:
    """One resolved column: the alias and the predicate uuid to probe with."""

    __slots__ = ("alias", "predicate")

    def __init__(self, alias: str, predicate):
        self.alias = alias
        self.predicate = predicate


def resolve_property_columns(projection) -> Optional[List[PropertyColumn]]:
    """Resolve wire columns to uuids, or None if ANY is unusable.

    None declines the WHOLE projection rather than the offending column, for the
    reason `slot_projection.resolve_columns` gives: a partially applied
    projection is a blank column, and a blank column reads as a missing value.
    """
    if not projection:
        return None
    out = []
    for p in projection:
        alias = getattr(p, "alias", None)
        prop = getattr(p, "property_uri", None)
        if not alias or not prop:
            logger.info(
                "property projection declined: a column is missing its alias "
                "or property_uri")
            return None
        out.append(PropertyColumn(alias=alias, predicate=_term_uuid(prop)))
    return out


async def project_property_values(
    conn, space_id: str, graph_uri: str, entity_uris: Sequence[str],
    columns: List[PropertyColumn],
) -> Dict[str, Dict[str, List[Any]]]:
    """`{entity_uri: {alias: [values]}}` for the page, from the quad table.

    Every requested alias is present for every requested entity, empty where the
    entity carries no such property — an absent key cannot be told from a column
    nobody asked for.

    Values are the LEXICAL form, which is what a URI and a literal share and
    what every other value on this API crosses the wire as. A list for the same
    reason the slot half returns one: a property may carry several values, and
    picking one would be a choice the caller never made.
    """
    out: Dict[str, Dict[str, List[Any]]] = {
        uri: {c.alias: [] for c in columns} for uri in entity_uris}
    if not entity_uris or not columns:
        return out

    uuid_of = {_term_uuid(u): u for u in entity_uris}
    alias_of: Dict[Any, List[str]] = {}
    for c in columns:
        alias_of.setdefault(c.predicate, []).append(c.alias)

    rows = await conn.fetch(
        f"""
        SELECT q.subject_uuid, q.predicate_uuid, t.term_text
        FROM {space_id}_rdf_quad q
        JOIN {space_id}_term t ON t.term_uuid = q.object_uuid
        WHERE q.context_uuid = $1
          AND q.subject_uuid = ANY($2::uuid[])
          AND q.predicate_uuid = ANY($3::uuid[])
        """,
        _term_uuid(graph_uri), list(uuid_of), list(alias_of))

    for r in rows:
        uri = uuid_of.get(r["subject_uuid"])
        if uri is None:
            continue
        for alias in alias_of.get(r["predicate_uuid"], ()):
            out[uri][alias].append(r["term_text"])

    # Deterministic order, so two identical requests render identically. The
    # quad probe returns multiple values in index order, which is by object
    # uuid -- a hash, and therefore arbitrary to a reader.
    for per_entity in out.values():
        for vals in per_entity.values():
            if len(vals) > 1:
                vals.sort()
    return out
