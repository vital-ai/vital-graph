#!/usr/bin/env python3
"""Search for leftover graph objects from a deleted KG entity.

Checks for:
1. Objects with hasKGGraphURI pointing to the entity URI (entity graph members)
2. Direct triples with the entity URI as subject (the entity itself)
3. Objects with hasFrameGraphURI pointing to any frame that belonged to this entity
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.sparql_model import SPARQLQueryRequest


SPACE_ID = os.getenv("SPACE_ID", "cardiff_kg")
ENTITY_URI = os.getenv("ENTITY_URI", "urn:cardiff:nurture:TEST_DISPATCH_001:winback_sms")


async def main():
    client = VitalGraphClient()
    try:
        await client.open()
        print(f"Connected to VitalGraph")
        print(f"Space: {SPACE_ID}")
        print(f"Entity URI: {ENTITY_URI}\n")
        print("=" * 80)

        # Query 1: Find all objects with hasKGGraphURI = entity URI
        print("\n[1] Objects with hasKGGraphURI = entity URI:")
        print("-" * 60)
        q1 = f"""\
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT DISTINCT ?subject ?type WHERE {{
  ?subject haley:hasKGGraphURI <{ENTITY_URI}> .
  OPTIONAL {{ ?subject rdf:type ?type . }}
}}
ORDER BY ?type ?subject
"""
        resp1 = await client.sparql.execute_sparql_query(SPACE_ID, SPARQLQueryRequest(query=q1))
        bindings1 = _extract_bindings(resp1)
        print(f"  Found {len(bindings1)} objects")
        for b in bindings1:
            subj = b.get("subject", {}).get("value", "")
            rdf_type = b.get("type", {}).get("value", "")
            print(f"    {subj}  [{rdf_type}]")

        # Query 2: Check if the entity itself still has triples
        print(f"\n[2] Direct triples with entity as subject:")
        print("-" * 60)
        q2 = f"""\
SELECT ?predicate ?object WHERE {{
  <{ENTITY_URI}> ?predicate ?object .
}}
ORDER BY ?predicate
"""
        resp2 = await client.sparql.execute_sparql_query(SPACE_ID, SPARQLQueryRequest(query=q2))
        bindings2 = _extract_bindings(resp2)
        print(f"  Found {len(bindings2)} triples")
        for b in bindings2:
            pred = b.get("predicate", {}).get("value", "")
            obj = b.get("object", {}).get("value", "")
            print(f"    {_short(pred)}  =  {_short(obj)}")

        # Query 3: Find frame URIs associated with this entity (via edges or kGGraphURI)
        print(f"\n[3] Frames that belonged to this entity (via Edge_hasEntityKGFrame):")
        print("-" * 60)
        q3 = f"""\
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX vital: <http://vital.ai/ontology/vital-core#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT DISTINCT ?edge ?frame WHERE {{
  ?edge rdf:type haley:Edge_hasEntityKGFrame .
  ?edge vital:hasEdgeSource <{ENTITY_URI}> .
  ?edge vital:hasEdgeDestination ?frame .
}}
"""
        resp3 = await client.sparql.execute_sparql_query(SPACE_ID, SPARQLQueryRequest(query=q3))
        bindings3 = _extract_bindings(resp3)
        print(f"  Found {len(bindings3)} frame edges")
        frame_uris = []
        for b in bindings3:
            edge = b.get("edge", {}).get("value", "")
            frame = b.get("frame", {}).get("value", "")
            frame_uris.append(frame)
            print(f"    Edge: {_short(edge)}")
            print(f"    Frame: {frame}")

        # Query 4: For each frame found, check for frameGraphURI objects
        if frame_uris:
            print(f"\n[4] Objects with hasFrameGraphURI pointing to discovered frames:")
            print("-" * 60)
            for frame_uri in frame_uris:
                q4 = f"""\
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT DISTINCT ?subject ?type WHERE {{
  ?subject haley:hasFrameGraphURI <{frame_uri}> .
  OPTIONAL {{ ?subject rdf:type ?type . }}
}}
ORDER BY ?type ?subject
"""
                resp4 = await client.sparql.execute_sparql_query(SPACE_ID, SPARQLQueryRequest(query=q4))
                bindings4 = _extract_bindings(resp4)
                if bindings4:
                    print(f"\n  Frame: {frame_uri}")
                    print(f"  Objects in frame graph: {len(bindings4)}")
                    for b in bindings4:
                        subj = b.get("subject", {}).get("value", "")
                        rdf_type = b.get("type", {}).get("value", "")
                        print(f"      {_short(subj)}  [{_short(rdf_type)}]")

        # Query 5: Check for any edges referencing this entity as source or destination
        print(f"\n[5] Edges referencing entity as source or destination:")
        print("-" * 60)
        q5 = f"""\
PREFIX vital: <http://vital.ai/ontology/vital-core#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT DISTINCT ?edge ?type ?source ?dest WHERE {{
  {{
    ?edge vital:hasEdgeSource <{ENTITY_URI}> .
    ?edge vital:hasEdgeDestination ?dest .
    OPTIONAL {{ ?edge rdf:type ?type . }}
    BIND(<{ENTITY_URI}> AS ?source)
  }} UNION {{
    ?edge vital:hasEdgeDestination <{ENTITY_URI}> .
    ?edge vital:hasEdgeSource ?source .
    OPTIONAL {{ ?edge rdf:type ?type . }}
    BIND(<{ENTITY_URI}> AS ?dest)
  }}
}}
ORDER BY ?type ?edge
"""
        resp5 = await client.sparql.execute_sparql_query(SPACE_ID, SPARQLQueryRequest(query=q5))
        bindings5 = _extract_bindings(resp5)
        print(f"  Found {len(bindings5)} edges")
        for b in bindings5:
            edge = b.get("edge", {}).get("value", "")
            etype = b.get("type", {}).get("value", "")
            source = b.get("source", {}).get("value", "")
            dest = b.get("dest", {}).get("value", "")
            print(f"    {_short(edge)}  type={_short(etype)}  src={_short(source)}  dst={_short(dest)}")

        # Summary
        print("\n" + "=" * 80)
        total = len(bindings1) + len(bindings2) + len(bindings3) + len(bindings5)
        print(f"SUMMARY: {total} total leftover items found")
        if total > 0:
            print("  These objects were likely left over from a delete of the KG entity")
            print("  without properly deleting the entity graph.")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await client.close()


def _extract_bindings(response):
    """Extract bindings from SPARQL response."""
    if response.results and isinstance(response.results, dict):
        return response.results.get("bindings", [])
    elif hasattr(response, 'bindings'):
        return response.bindings or []
    return []


def _short(uri: str) -> str:
    """Shorten URI for display."""
    if not uri:
        return ""
    prefixes = {
        "http://vital.ai/ontology/haley-ai-kg#": "haley:",
        "http://vital.ai/ontology/vital-core#": "vital:",
        "http://www.w3.org/1999/02/22-rdf-syntax-ns#": "rdf:",
        "http://www.w3.org/2001/XMLSchema#": "xsd:",
    }
    for full, short in prefixes.items():
        if uri.startswith(full):
            return short + uri[len(full):]
    return uri


if __name__ == "__main__":
    asyncio.run(main())
