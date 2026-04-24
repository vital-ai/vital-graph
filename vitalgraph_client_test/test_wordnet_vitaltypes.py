#!/usr/bin/env python3
"""Check all vitaltype values in WordNet frames dataset."""
import asyncio, sys
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
load_dotenv(project_root / '.env')

import logging
logging.basicConfig(level=logging.WARNING)

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.sparql_model import SPARQLQueryRequest

SPACE = "wordnet_frames"
GRAPH = "urn:wordnet_frames"


async def sparql(client, query):
    resp = await client.sparql.execute_sparql_query(SPACE, SPARQLQueryRequest(query=query))
    return resp.results.get('bindings', []) if resp.results else []


async def main():
    c = VitalGraphClient()
    await c.open()

    print("--- All vitaltype values ---")
    rows = await sparql(c, f"""
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        SELECT ?vtype (COUNT(*) AS ?cnt) WHERE {{
          GRAPH <{GRAPH}> {{
            ?s vital:vitaltype ?vtype .
          }}
        }} GROUP BY ?vtype ORDER BY DESC(?cnt)
    """)
    for r in rows:
        print(f"  {r['vtype']['value'].split('#')[-1]}  = {r['cnt']['value']}")

    print("\n--- All rdf:type values ---")
    rows = await sparql(c, f"""
        SELECT ?rtype (COUNT(*) AS ?cnt) WHERE {{
          GRAPH <{GRAPH}> {{
            ?s <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> ?rtype .
          }}
        }} GROUP BY ?rtype ORDER BY DESC(?cnt)
    """)
    for r in rows:
        print(f"  {r['rtype']['value'].split('#')[-1]}  = {r['cnt']['value']}")

    print("\n--- Edge_hasKGSlot via rdf:type (frame->slot edges) ---")
    rows = await sparql(c, f"""
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT ?frame ?slot ?slot_type ?entity WHERE {{
          GRAPH <{GRAPH}> {{
            ?edge <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> haley:Edge_hasKGSlot .
            ?edge vital:hasEdgeSource ?frame .
            ?edge vital:hasEdgeDestination ?slot .
            ?slot haley:hasKGSlotType ?slot_type .
            ?slot haley:hasEntitySlotValue ?entity .
          }}
        }} LIMIT 3
    """)
    print(f"  Found {len(rows)} results")
    for r in rows:
        print(f"  frame: {r['frame']['value'][:60]}")
        print(f"  slot_type: {r['slot_type']['value']}")
        print(f"  entity: {r['entity']['value'][:60]}")
        print()

    await c.close()


if __name__ == "__main__":
    asyncio.run(main())
