#!/usr/bin/env python3
"""Check if WordNet frames and slots share kGGraphURI grouping."""
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

    # 1. Do frames have kGGraphURI?
    print("--- Frames with kGGraphURI ---")
    rows = await sparql(c, f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT (COUNT(*) AS ?cnt) WHERE {{
          GRAPH <{GRAPH}> {{
            ?f a haley:KGFrame .
            ?f haley:kGGraphURI ?g .
          }}
        }}
    """)
    print(f"  frames with kGGraphURI: {rows[0]['cnt']['value'] if rows else '?'}")

    # 2. Do entity slots have kGGraphURI?
    print("\n--- Entity slots with kGGraphURI ---")
    rows = await sparql(c, f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT (COUNT(*) AS ?cnt) WHERE {{
          GRAPH <{GRAPH}> {{
            ?s a haley:KGEntitySlot .
            ?s haley:kGGraphURI ?g .
          }}
        }}
    """)
    print(f"  entity slots with kGGraphURI: {rows[0]['cnt']['value'] if rows else '?'}")

    # 3. Sample: find a frame and slot that share the same kGGraphURI
    print("\n--- Frame+Slot sharing kGGraphURI (limit 3) ---")
    rows = await sparql(c, f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT ?frame ?slot ?slot_type ?entity ?graph_uri WHERE {{
          GRAPH <{GRAPH}> {{
            ?frame a haley:KGFrame .
            ?frame haley:kGGraphURI ?graph_uri .
            ?slot a haley:KGEntitySlot .
            ?slot haley:kGGraphURI ?graph_uri .
            ?slot haley:hasKGSlotType ?slot_type .
            ?slot haley:hasEntitySlotValue ?entity .
          }}
        }} LIMIT 3
    """)
    if rows:
        for r in rows:
            print(f"  graph_uri: {r['graph_uri']['value'][:60]}")
            print(f"  frame: {r['frame']['value'][:60]}")
            print(f"  slot_type: {r['slot_type']['value']}")
            print(f"  entity: {r['entity']['value'][:60]}")
            print()
    else:
        print("  (none — frames and slots don't share kGGraphURI)")

    # 4. Alternative: check if kGFrameSlotFrame property exists on slots
    print("--- kGFrameSlotFrame on entity slots ---")
    rows = await sparql(c, f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT ?slot ?frame WHERE {{
          GRAPH <{GRAPH}> {{
            ?slot a haley:KGEntitySlot .
            ?slot haley:kGFrameSlotFrame ?frame .
          }}
        }} LIMIT 3
    """)
    if rows:
        for r in rows:
            print(f"  slot: {r['slot']['value'][:60]} → frame: {r['frame']['value'][:60]}")
    else:
        print("  (none)")

    # 5. All predicates used by entity slots
    print("\n--- All predicates on KGEntitySlot ---")
    rows = await sparql(c, f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT ?p (COUNT(*) AS ?cnt) WHERE {{
          GRAPH <{GRAPH}> {{
            ?s a haley:KGEntitySlot .
            ?s ?p ?o .
          }}
        }} GROUP BY ?p ORDER BY DESC(?cnt)
    """)
    for r in rows:
        print(f"  {r['p']['value'].split('#')[-1]}  = {r['cnt']['value']}")

    await c.close()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
