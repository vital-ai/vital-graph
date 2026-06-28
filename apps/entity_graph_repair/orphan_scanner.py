"""Scan and inspect orphaned KG entity graphs.

An entity graph is orphaned when its top-level KGEntity node has been
deleted but child objects (frames, slots, edges, documents) remain with
``hasKGGraphURI`` still pointing to the missing entity URI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.sparql_model import SPARQLQueryRequest

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class OrphanSummary:
    """Summary of a single orphaned entity graph."""
    entity_uri: str
    object_count: int = 0
    type_counts: dict = field(default_factory=dict)

    def __str__(self) -> str:
        parts = [f"{v} {k}" for k, v in sorted(self.type_counts.items())]
        detail = f" ({', '.join(parts)})" if parts else ""
        return f"{self.entity_uri} — ORPHAN — {self.object_count} objects{detail}"


@dataclass
class InspectResult:
    """Detailed inspection of an entity graph."""
    entity_uri: str
    entity_triples: List[dict] = field(default_factory=list)
    graph_members: List[dict] = field(default_factory=list)
    edges: List[dict] = field(default_factory=list)
    frame_edges: List[dict] = field(default_factory=list)
    frame_children: dict = field(default_factory=dict)  # frame_uri -> [objects]
    is_orphan: bool = False


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

_SCAN_ORPHAN_GRAPHS = """\
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT ?graphURI (COUNT(DISTINCT ?s) AS ?objectCount)
WHERE {
  ?s haley:hasKGGraphURI ?graphURI .
  FILTER NOT EXISTS {
    ?graphURI rdf:type ?entityType .
  }
}
GROUP BY ?graphURI
ORDER BY DESC(?objectCount)
"""

_GRAPH_MEMBERS_BY_TYPE = """\
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT ?subject ?type
WHERE {{
  ?subject haley:hasKGGraphURI <{entity_uri}> .
  OPTIONAL {{ ?subject rdf:type ?type . }}
}}
ORDER BY ?type ?subject
"""

_ENTITY_TRIPLES = """\
SELECT ?predicate ?object
WHERE {{
  <{entity_uri}> ?predicate ?object .
}}
ORDER BY ?predicate
"""

_ENTITY_EDGES = """\
PREFIX vital: <http://vital.ai/ontology/vital-core#>
PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT DISTINCT ?edge ?type ?source ?dest
WHERE {{
  {{
    ?edge vital:hasEdgeSource <{entity_uri}> .
    ?edge vital:hasEdgeDestination ?dest .
    OPTIONAL {{ ?edge rdf:type ?type . }}
    BIND(<{entity_uri}> AS ?source)
  }} UNION {{
    ?edge vital:hasEdgeDestination <{entity_uri}> .
    ?edge vital:hasEdgeSource ?source .
    OPTIONAL {{ ?edge rdf:type ?type . }}
    BIND(<{entity_uri}> AS ?dest)
  }}
}}
ORDER BY ?type ?edge
"""

_FRAME_EDGES = """\
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX vital: <http://vital.ai/ontology/vital-core#>
PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT DISTINCT ?edge ?frame
WHERE {{
  ?edge rdf:type haley:Edge_hasEntityKGFrame .
  ?edge vital:hasEdgeSource <{entity_uri}> .
  ?edge vital:hasEdgeDestination ?frame .
}}
"""

_FRAME_GRAPH_CHILDREN = """\
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT DISTINCT ?subject ?type
WHERE {{
  ?subject haley:hasFrameGraphURI <{frame_uri}> .
  OPTIONAL {{ ?subject rdf:type ?type . }}
}}
ORDER BY ?type ?subject
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_bindings(response) -> List[dict]:
    if response.results and isinstance(response.results, dict):
        return response.results.get("bindings", [])
    elif hasattr(response, "bindings"):
        return response.bindings or []
    return []


def _val(binding: dict, key: str) -> str:
    return binding.get(key, {}).get("value", "")


_PREFIX_MAP = {
    "http://vital.ai/ontology/haley-ai-kg#": "haley:",
    "http://vital.ai/ontology/vital-core#": "vital:",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#": "rdf:",
    "http://www.w3.org/2001/XMLSchema#": "xsd:",
}


def shorten(uri: str) -> str:
    """Shorten well-known URI prefixes for display."""
    if not uri:
        return ""
    for full, short in _PREFIX_MAP.items():
        if uri.startswith(full):
            return short + uri[len(full):]
    return uri


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def scan_orphan_graphs(
    client: VitalGraphClient,
    space_id: str,
) -> List[OrphanSummary]:
    """Return a list of orphaned entity graphs in the given space."""
    resp = await client.sparql.execute_sparql_query(
        space_id, SPARQLQueryRequest(query=_SCAN_ORPHAN_GRAPHS)
    )
    bindings = _extract_bindings(resp)

    orphans: List[OrphanSummary] = []
    for b in bindings:
        uri = _val(b, "graphURI")
        count = int(_val(b, "objectCount") or "0")
        if uri:
            orphans.append(OrphanSummary(entity_uri=uri, object_count=count))

    # Enrich with type breakdown for each orphan
    for orphan in orphans:
        query = _GRAPH_MEMBERS_BY_TYPE.format(entity_uri=orphan.entity_uri)
        resp = await client.sparql.execute_sparql_query(
            space_id, SPARQLQueryRequest(query=query)
        )
        type_counts: dict = {}
        for b in _extract_bindings(resp):
            rdf_type = shorten(_val(b, "type")) or "(untyped)"
            type_counts[rdf_type] = type_counts.get(rdf_type, 0) + 1
        orphan.type_counts = type_counts

    return orphans


async def inspect_entity_graph(
    client: VitalGraphClient,
    space_id: str,
    entity_uri: str,
) -> InspectResult:
    """Return detailed inspection of an entity graph."""
    result = InspectResult(entity_uri=entity_uri)

    # 1. Check if entity node itself exists
    q1 = _ENTITY_TRIPLES.format(entity_uri=entity_uri)
    resp1 = await client.sparql.execute_sparql_query(
        space_id, SPARQLQueryRequest(query=q1)
    )
    result.entity_triples = _extract_bindings(resp1)
    result.is_orphan = len(result.entity_triples) == 0

    # 2. Graph members (objects with hasKGGraphURI = entity_uri)
    q2 = _GRAPH_MEMBERS_BY_TYPE.format(entity_uri=entity_uri)
    resp2 = await client.sparql.execute_sparql_query(
        space_id, SPARQLQueryRequest(query=q2)
    )
    result.graph_members = _extract_bindings(resp2)

    # 3. Edges referencing entity as source or destination
    q3 = _ENTITY_EDGES.format(entity_uri=entity_uri)
    resp3 = await client.sparql.execute_sparql_query(
        space_id, SPARQLQueryRequest(query=q3)
    )
    result.edges = _extract_bindings(resp3)

    # 4. Frame edges
    q4 = _FRAME_EDGES.format(entity_uri=entity_uri)
    resp4 = await client.sparql.execute_sparql_query(
        space_id, SPARQLQueryRequest(query=q4)
    )
    result.frame_edges = _extract_bindings(resp4)

    # 5. Children of each frame
    for b in result.frame_edges:
        frame_uri = _val(b, "frame")
        if frame_uri:
            q5 = _FRAME_GRAPH_CHILDREN.format(frame_uri=frame_uri)
            resp5 = await client.sparql.execute_sparql_query(
                space_id, SPARQLQueryRequest(query=q5)
            )
            result.frame_children[frame_uri] = _extract_bindings(resp5)

    return result


def print_inspect_result(result: InspectResult) -> None:
    """Pretty-print an InspectResult to stdout."""
    print(f"Entity URI: {result.entity_uri}")
    print(f"Status: {'ORPHAN (entity node missing)' if result.is_orphan else 'PRESENT'}")
    print("=" * 80)

    # Entity triples
    print(f"\n[1] Entity node triples: {len(result.entity_triples)}")
    print("-" * 60)
    for b in result.entity_triples:
        print(f"  {shorten(_val(b, 'predicate'))}  =  {shorten(_val(b, 'object'))}")

    # Graph members
    print(f"\n[2] Objects with hasKGGraphURI = entity: {len(result.graph_members)}")
    print("-" * 60)
    for b in result.graph_members:
        print(f"  {_val(b, 'subject')}  [{shorten(_val(b, 'type'))}]")

    # Edges
    print(f"\n[3] Edges referencing entity: {len(result.edges)}")
    print("-" * 60)
    for b in result.edges:
        print(
            f"  {shorten(_val(b, 'edge'))}  type={shorten(_val(b, 'type'))}"
            f"  src={shorten(_val(b, 'source'))}  dst={shorten(_val(b, 'dest'))}"
        )

    # Frame edges + children
    print(f"\n[4] Frame edges: {len(result.frame_edges)}")
    print("-" * 60)
    for b in result.frame_edges:
        frame_uri = _val(b, "frame")
        children = result.frame_children.get(frame_uri, [])
        print(f"  Edge: {shorten(_val(b, 'edge'))}")
        print(f"  Frame: {frame_uri}  ({len(children)} children)")
        for c in children:
            print(f"    {shorten(_val(c, 'subject'))}  [{shorten(_val(c, 'type'))}]")

    # Summary
    total = len(result.graph_members) + len(result.edges)
    child_count = sum(len(v) for v in result.frame_children.values())
    print(f"\n{'=' * 80}")
    print(f"TOTAL: {len(result.graph_members)} graph members, "
          f"{len(result.edges)} edges, {child_count} frame children")
