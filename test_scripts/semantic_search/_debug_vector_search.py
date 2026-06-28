#!/usr/bin/env python3
"""Quick debug: run a vector search SPARQL and print results."""
import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
load_dotenv(project_root / ".env")

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.sparql_model import SPARQLQueryRequest

SPARQL = """
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>

SELECT ?entity ?name ?score
WHERE {
  OPTIONAL { ?entity <http://vital.ai/ontology/vital-core#hasName> ?name }
  BIND(vg:vectorSimilarity(?entity, "pizza", "entity_vector") AS ?score)
  FILTER(BOUND(?score))
  FILTER(?score > 0.2)
}
ORDER BY DESC(?score)
LIMIT 20
"""

async def main():
    client = VitalGraphClient()
    await client.open()
    try:
        req = SPARQLQueryRequest(query=SPARQL)
        resp = await client.sparql.execute_sparql_query(
            space_id="sp_semantic_search_test", request=req)
        data = resp.model_dump() if hasattr(resp, "model_dump") else resp
        bindings = data.get("results", {}).get("bindings", [])
        print(f"Results: {len(bindings)}")
        for b in bindings:
            entity = b.get("entity", {}).get("value", "?")
            name = b.get("name", {}).get("value", "(no name)")
            score = b.get("score", {}).get("value", "?")
            print(f"  {score}  {name}  [{entity}]")

        # Check Joe's Pizza specifically with no threshold
        sparql2 = """
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
SELECT ?score WHERE {
  BIND(vg:vectorSimilarity(<http://vital.ai/test/semantic/entity/joes_pizza>, "italian", "entity_vector") AS ?score)
}
"""
        req2 = SPARQLQueryRequest(query=sparql2)
        resp2 = await client.sparql.execute_sparql_query(
            space_id="sp_semantic_search_test", request=req2)
        data2 = resp2.model_dump() if hasattr(resp2, "model_dump") else resp2
        bindings2 = data2.get("results", {}).get("bindings", [])
        if bindings2:
            print(f"\nJoe's Pizza score for 'italian': {bindings2[0].get('score', {}).get('value', 'N/A')}")
        else:
            print("\nJoe's Pizza: no score returned")
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(main())
