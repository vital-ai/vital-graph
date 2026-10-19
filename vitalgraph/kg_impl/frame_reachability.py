"""A frame write must not leave what it wrote unreachable — issues/279.

The frame routes wrote whatever they were sent. A request whose
`Edge_hasKGFrame` / `Edge_hasKGSlot` named a frame that was neither in the
request nor in the store was accepted, and its slots hung off a node that never
existed: unreachable from the entity, invisible to every entity-led read, found
days later by the maintenance job's dangling-endpoint probe. Production
accumulated 4,704 such subtrees in five days from one client's builder, which
sent a child frame's slots and edges but not the child frame (`issues/212` saw
the same shape before).

Two rules, on the write's OUTCOME:

1. Every endpoint of a structural edge the write stores (`Edge_hasKGFrame`,
   `Edge_hasKGSlot`, `Edge_hasEntityKGFrame` — the links reads walk) that the
   write does not itself store still exists afterwards.
2. Every slot the write stores is the destination of some `Edge_hasKGSlot`
   afterwards.

WHY AFTER THE WRITE, NOT BEFORE IT. A frame upsert replaces each named frame's
whole graph and a replace deletes whole subtrees, so a stored object an edge
names can be deleted by the same write. Checked first, it is present and the
write passes; committed, it dangles. So the check is a `postcheck`: it runs in
the write's transaction, under its lock, after the delete and the insert and
before the commit, and a refusal rolls all of it back.

FREE WHEN THE REQUEST IS SELF-CONTAINED. Both rules are decided against the
request first; only what the request cannot answer is looked up, and a request
that names nothing outside itself gets no postcheck at all.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Set

from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.KGSlot import KGSlot

from .refusals import RequestRefused

EDGE_HAS_KG_SLOT = 'http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot'
_STRUCTURAL = (Edge_hasKGFrame, Edge_hasKGSlot, Edge_hasEntityKGFrame)
_SHOWN = 10


class UnreachableObjects(RequestRefused):
    """The write would leave edges or slots pointing at nothing; nothing was written."""

    def __init__(self, missing: List[str], unattached: List[str]):
        self.missing = missing
        self.unattached = unattached
        parts = []
        if missing:
            parts.append(
                f"{len(missing)} object(s) named by this write's edges are neither in "
                f"the request nor in the graph: " + ", ".join(missing[:_SHOWN])
                + (" ..." if len(missing) > _SHOWN else ""))
        if unattached:
            parts.append(
                f"{len(unattached)} slot(s) would have no Edge_hasKGSlot: "
                + ", ".join(unattached[:_SHOWN])
                + (" ..." if len(unattached) > _SHOWN else ""))
        super().__init__(
            "; ".join(parts) + ". Nothing was written: send every frame the "
            "request's edges name, and each slot's Edge_hasKGSlot (issues/279)")


def _uri(v) -> Optional[str]:
    return str(v) if v else None


def outside_references(objects: Iterable):
    """(names, loose_slots) for the objects a write will store.

    `names`: endpoints of its structural edges that are not among its objects.
    `loose_slots`: its slots that none of its `Edge_hasKGSlot` reaches.
    Both empty means the request is self-contained.
    """
    objects = list(objects)
    written: Set[str] = {str(o.URI) for o in objects if getattr(o, "URI", None)}
    names: Set[str] = set()
    edged: Set[str] = set()
    for o in objects:
        if isinstance(o, _STRUCTURAL):
            src, dst = _uri(o.edgeSource), _uri(o.edgeDestination)
            for end in (src, dst):
                if end and end not in written:
                    names.add(end)
            if isinstance(o, Edge_hasKGSlot) and dst:
                edged.add(dst)
    loose = {str(o.URI) for o in objects
             if isinstance(o, KGSlot) and getattr(o, "URI", None)} - edged
    return names, loose


async def _slots_with_edge(conn, space_id: str, graph_id: str, slot_uris: List[str]) -> Set[str]:
    """Which of `slot_uris` an `Edge_hasKGSlot` in the graph points at."""
    if not slot_uris:
        return set()
    from ..db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
    from ..db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
    from .kg_backend_utils import HAS_EDGE_DESTINATION, VITALTYPE_URI
    U = lambda u: _generate_term_uuid(u, 'U')  # noqa: E731
    q = SparqlSQLSchema.get_table_names(space_id)['rdf_quad']
    by_uuid = {U(u): u for u in slot_uris}
    rows = await conn.fetch(
        f"SELECT DISTINCT d.object_uuid FROM {q} d "
        f"WHERE d.predicate_uuid = $2 AND d.object_uuid = ANY($1::uuid[]) "
        f"  AND d.context_uuid = $3 "
        f"  AND EXISTS (SELECT 1 FROM {q} vt WHERE vt.subject_uuid = d.subject_uuid "
        f"                AND vt.context_uuid = $3 AND vt.predicate_uuid = $4 "
        f"                AND vt.object_uuid = $5)",
        list(by_uuid), U(HAS_EDGE_DESTINATION), U(graph_id), U(VITALTYPE_URI),
        U(EDGE_HAS_KG_SLOT))
    return {by_uuid[r['object_uuid']] for r in rows}


def reachability_postcheck(space_id: str, graph_id: str, objects: Iterable):
    """The `postcheck` for a frame write storing `objects`, or None when the
    request answers both rules itself."""
    names, loose = outside_references(objects)
    if not names and not loose:
        return None
    names_l, loose_l = sorted(names), sorted(loose)

    async def _check(conn):
        from .kg_backend_utils import _present
        missing = sorted(set(names_l) - await _present(conn, space_id, graph_id, names_l))
        unattached = sorted(set(loose_l) - await _slots_with_edge(
            conn, space_id, graph_id, loose_l))
        if missing or unattached:
            raise UnreachableObjects(missing, unattached)
    return _check
