#!/usr/bin/env python3
"""Minimal vector query to understand result limits."""
import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
load_dotenv(project_root / ".env")

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.sparql_model import SPARQLQueryRequest

QUERIES = {
    "italian_with_optional_limit10": """
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
SELECT ?entity ?name ?score WHERE {
  OPTIONAL { ?entity <http://vital.ai/ontology/vital-core#hasName> ?name }
  BIND(vg:vectorSimilarity(?entity, "italian", "entity_vector") AS ?score)
  FILTER(BOUND(?score))
  FILTER(?score > 0.01)
} ORDER BY DESC(?score) LIMIT 10
""",
    "italian_with_optional_limit20": """
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
SELECT ?entity ?name ?score WHERE {
  OPTIONAL { ?entity <http://vital.ai/ontology/vital-core#hasName> ?name }
  BIND(vg:vectorSimilarity(?entity, "italian", "entity_vector") AS ?score)
  FILTER(BOUND(?score))
  FILTER(?score > 0.2)
} ORDER BY DESC(?score) LIMIT 20
""",
    "pizza_with_optional_limit20": """
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
SELECT ?entity ?name ?score WHERE {
  OPTIONAL { ?entity <http://vital.ai/ontology/vital-core#hasName> ?name }
  BIND(vg:vectorSimilarity(?entity, "pizza", "entity_vector") AS ?score)
  FILTER(BOUND(?score))
  FILTER(?score > 0.2)
} ORDER BY DESC(?score) LIMIT 20
""",
}


async def main():
    client = VitalGraphClient()
    await client.open()

    for label, sparql in QUERIES.items():
        req = SPARQLQueryRequest(query=sparql)
        resp = await client.sparql.execute_sparql_query(
            space_id="sp_semantic_search_test", request=req
        )
        data = resp.model_dump() if hasattr(resp, "model_dump") else resp
        bindings = data.get("results", {}).get("bindings", [])
        print(f"\n{label}: {len(bindings)} results")
        for b in bindings[:3]:
            score = b.get("score", {}).get("value", "?")
            entity = b.get("entity", {}).get("value", "?")
            print(f"  {score}  {entity}")
        if len(bindings) > 3:
            print(f"  ... ({len(bindings)} total)")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
