#!/usr/bin/env python3
"""
Discover WordNet dataset structure — both wordnet_exp and wordnet_frames.
"""
import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
load_dotenv(project_root / '.env')

import logging
logging.basicConfig(level=logging.WARNING)

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.sparql_model import SPARQLQueryRequest


async def sparql(client, space_id, query):
    resp = await client.sparql.execute_sparql_query(space_id, SPARQLQueryRequest(query=query))
    return resp.results.get('bindings', []) if resp.results else []


async def explore_space(client, space_id, graph_id):
    print(f"\n{'='*60}")
    print(f"  {space_id} / {graph_id}")
    print(f"{'='*60}")

    # Edge types
    print("\n--- Edge types (vitaltype containing Slot/Frame/Entity) ---")
    rows = await sparql(client, space_id, f"""
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        SELECT ?etype (COUNT(*) AS ?cnt) WHERE {{
          GRAPH <{graph_id}> {{
            ?e vital:vitaltype ?etype .
            FILTER(CONTAINS(STR(?etype), "Slot") || CONTAINS(STR(?etype), "Frame") || CONTAINS(STR(?etype), "Entity"))
          }}
        }} GROUP BY ?etype ORDER BY DESC(?cnt)
    """)
    for r in rows:
        print(f"  {r['etype']['value'].split('#')[-1]}  = {r['cnt']['value']}")

    # Object properties connecting frames to slots
    print("\n--- Object properties from KGFrame subjects ---")
    rows = await sparql(client, space_id, f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT ?p (COUNT(*) AS ?cnt) WHERE {{
          GRAPH <{graph_id}> {{
            ?frame a haley:KGFrame .
            ?frame ?p ?o .
          }}
        }} GROUP BY ?p ORDER BY DESC(?cnt) LIMIT 15
    """)
    for r in rows:
        print(f"  {r['p']['value'].split('#')[-1]}  = {r['cnt']['value']}")

    # Direct frame→slot property check
    print("\n--- Frame→Slot direct property links ---")
    rows = await sparql(client, space_id, f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT ?p (COUNT(*) AS ?cnt) WHERE {{
          GRAPH <{graph_id}> {{
            ?frame a haley:KGFrame .
            ?frame ?p ?slot .
            ?slot a haley:KGEntitySlot .
          }}
        }} GROUP BY ?p ORDER BY DESC(?cnt) LIMIT 10
    """)
    if rows:
        for r in rows:
            print(f"  {r['p']['value'].split('#')[-1]}  = {r['cnt']['value']}")
    else:
        print("  (none)")

    # Sample frame→slot→entity chain
    print("\n--- Sample frame→slot→entity (direct props, limit 3) ---")
    rows = await sparql(client, space_id, f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT ?frame ?p ?slot ?slot_type ?entity WHERE {{
          GRAPH <{graph_id}> {{
            ?frame a haley:KGFrame .
            ?frame ?p ?slot .
            ?slot a haley:KGEntitySlot .
            ?slot haley:hasKGSlotType ?slot_type .
            ?slot haley:hasEntitySlotValue ?entity .
          }}
        }} LIMIT 3
    """)
    if rows:
        for r in rows:
            print(f"  frame: {r['frame']['value'][:60]}")
            print(f"  via prop: {r['p']['value'].split('#')[-1]}")
            print(f"  slot_type: {r['slot_type']['value']}")
            print(f"  entity: {r['entity']['value'][:60]}")
            print()
    else:
        print("  (none)")

    # Sample frame→slot→entity via edges
    print("--- Sample frame→slot→entity (via Edge_hasKGFrameSlot, limit 3) ---")
    rows = await sparql(client, space_id, f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        SELECT ?frame ?slot ?slot_type ?entity WHERE {{
          GRAPH <{graph_id}> {{
            ?edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGFrameSlot> .
            ?edge vital:hasEdgeSource ?frame .
            ?edge vital:hasEdgeDestination ?slot .
            ?slot haley:hasKGSlotType ?slot_type .
            ?slot haley:hasEntitySlotValue ?entity .
          }}
        }} LIMIT 3
    """)
    if rows:
        for r in rows:
            print(f"  frame: {r['frame']['value'][:60]}")
            print(f"  slot_type: {r['slot_type']['value']}")
            print(f"  entity: {r['entity']['value'][:60]}")
            print()
    else:
        print("  (none)")


async def main():
    client = VitalGraphClient()
    await client.open()

    # List graphs for both spaces
    for space_id in ['wordnet_exp', 'wordnet_frames']:
        try:
            resp = await client.graphs.list_graphs(space_id=space_id)
            if resp.is_success and resp.graphs:
                for g in resp.graphs:
                    graph_id = getattr(g, 'graph_id', None) or getattr(g, 'graph_uri', None)
                    if graph_id:
                        await explore_space(client, space_id, graph_id)
            else:
                print(f"\n{space_id}: no graphs found")
        except Exception as e:
            print(f"\n{space_id}: error listing graphs: {e}")

    await client.close()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
