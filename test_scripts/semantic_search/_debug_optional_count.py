#!/usr/bin/env python3
"""Compare results with 1 OPTIONAL vs 3 OPTIONALs."""
import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
load_dotenv(project_root / ".env")

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.sparql_model import SPARQLQueryRequest

SPARQL_1OPT = """
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
SELECT ?entity ?name ?score
WHERE {
  OPTIONAL { ?entity <http://vital.ai/ontology/vital-core#hasName> ?name }
  BIND(vg:vectorSimilarity(?entity, "italian", "entity_vector") AS ?score)
  FILTER(BOUND(?score))
  FILTER(?score > 0.01)
}
ORDER BY DESC(?score)
LIMIT 10
"""

SPARQL_3OPT = """
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
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

    for label, sparql in [("1 OPTIONAL", SPARQL_1OPT), ("3 OPTIONALs", SPARQL_3OPT)]:
        req = SPARQLQueryRequest(query=sparql)
        resp = await client.sparql.execute_sparql_query(
            space_id="sp_semantic_search_test", request=req
        )
        data = resp.model_dump() if hasattr(resp, "model_dump") else resp
        bindings = data.get("results", {}).get("bindings", [])
        print(f"\n{label}: {len(bindings)} results")
        for b in bindings[:5]:
            score = b.get("score", {}).get("value", "?")
            name = b.get("name", b.get("prop0", {})).get("value", "(none)")
            entity = b.get("entity", {}).get("value", "?")
            print(f"  {score}  {name}  [{entity}]")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
