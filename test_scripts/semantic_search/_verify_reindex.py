#!/usr/bin/env python3
"""Quick script to verify reindex worked after vitaltype fix."""
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.sparql_model import SPARQLQueryRequest


async def main():
    print("Waiting 10s for background reindex to complete...")
    await asyncio.sleep(10)

    client = VitalGraphClient()
    await client.open()

    # Test 1: Basic vector search
    query = """PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX core: <http://vital.ai/ontology/vital-core#>
SELECT ?entity ?name ?score
WHERE {
  OPTIONAL { ?entity core:hasName ?name }
  BIND(vg:vectorSimilarity(?entity, "authentic Italian pizza New York", "entity_vector") AS ?score)
  FILTER(BOUND(?score))
  FILTER(?score > 0.1)
}
ORDER BY DESC(?score)
LIMIT 5"""

    req = SPARQLQueryRequest(query=query, default_graph_uri=["urn:semantic_search_test"])
    resp = await client.execute_sparql_query("sp_semantic_search_test", req)
    bindings = resp.results.get("bindings", []) if resp.results else []
    print(f"\n[Test 1] Vector search 'Italian pizza': {len(bindings)} results")
    for b in bindings:
        name = b.get("name", {}).get("value", "?")
        score = b.get("score", {}).get("value", "?")
        print(f"  {name}: {score}")

    # Test 2: Entity type filter
    query2 = """PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX core: <http://vital.ai/ontology/vital-core#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
SELECT ?entity ?name ?score
WHERE {
  ?entity a haley:KGEntity .
  ?entity haley:hasKGEntityType <http://vital.ai/test/semantic/ArticleEntity> .
  OPTIONAL { ?entity core:hasName ?name }
  BIND(vg:vectorSimilarity(?entity, "food culture culinary travel", "entity_vector") AS ?score)
  FILTER(BOUND(?score))
  FILTER(?score > 0.1)
}"""

    req2 = SPARQLQueryRequest(query=query2, default_graph_uri=["urn:semantic_search_test"])
    resp2 = await client.execute_sparql_query("sp_semantic_search_test", req2)
    bindings2 = resp2.results.get("bindings", []) if resp2.results else []
    print(f"\n[Test 2] ArticleEntity vector search: {len(bindings2)} results")
    for b in bindings2:
        name = b.get("name", {}).get("value", "?")
        score = b.get("score", {}).get("value", "?")
        print(f"  {name}: {score}")

    # Test 3: Frame type query
    query3 = """PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
SELECT ?frame ?slot_value
WHERE {
  ?frame a haley:KGFrame .
  ?frame haley:hasKGFrameType <http://vital.ai/test/semantic/LocationFrame> .
  OPTIONAL { ?frame haley:hasTextSlotValue ?slot_value }
}
LIMIT 20"""

    req3 = SPARQLQueryRequest(query=query3, default_graph_uri=["urn:semantic_search_test"])
    resp3 = await client.execute_sparql_query("sp_semantic_search_test", req3)
    bindings3 = resp3.results.get("bindings", []) if resp3.results else []
    print(f"\n[Test 3] LocationFrame query: {len(bindings3)} results")
    for b in bindings3[:5]:
        frame = b.get("frame", {}).get("value", "?")
        print(f"  {frame}")

    await client.close()
    
    # Summary
    print("\n--- Summary ---")
    print(f"  Vector search: {'PASS' if len(bindings) > 0 else 'FAIL'} ({len(bindings)} results)")
    print(f"  ArticleEntity: {'PASS' if len(bindings2) > 0 else 'FAIL'} ({len(bindings2)} results)")
    print(f"  LocationFrame: {'PASS' if len(bindings3) > 0 else 'FAIL'} ({len(bindings3)} results)")


if __name__ == "__main__":
    asyncio.run(main())
