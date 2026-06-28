#!/usr/bin/env python3
"""Run the exact SPARQL that the UI generates."""
import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
load_dotenv(project_root / ".env")

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.sparql_model import SPARQLQueryRequest

# Exact SPARQL from UI
SPARQL = """
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?entity ?prop0 ?prop1 ?prop2 ?score
WHERE {
  OPTIONAL { ?entity <http://vital.ai/ontology/vital-core#hasName> ?prop0 }
  OPTIONAL { ?entity <http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription> ?prop1 }
  OPTIONAL { ?entity <http://vital.ai/ontology/haley-ai-kg#hasTextSlotValue> ?prop2 }
  BIND(vg:vectorSimilarity(?entity, "italian", "entity_vector") AS ?score)
  FILTER(BOUND(?score))
  FILTER(?score > 0.01)
}
ORDER BY DESC(?score)
LIMIT 10
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
            name = b.get("prop0", {}).get("value", "(no name)")
            score = b.get("score", {}).get("value", "?")
            print(f"  {score}  {name}  [{entity}]")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
