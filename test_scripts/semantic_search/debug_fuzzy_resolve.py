"""Debug: inspect fuzzy resolution via SPARQL using VitalGraph client."""
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from test_scripts.semantic_search.config import TEST_SPACE_ID
from test_scripts.semantic_search.verify import SearchVerifier


async def main():
    client = VitalGraphClient()
    await client.open()
    v = SearchVerifier(client)

    query = """PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX core: <http://vital.ai/ontology/vital-core#>
SELECT ?entity ?name ?score
WHERE {
  OPTIONAL { ?entity core:hasName ?name }
  BIND(vg:fuzzyMatch(?entity, "Joes Piza", 30) AS ?score)
  FILTER(BOUND(?score))
}
ORDER BY DESC(?score)
LIMIT 10"""

    resp = await v.sparql(query)
    bindings = resp.results.get("bindings", []) if resp.results else []
    print(f"Results: {len(bindings)}")
    for i, b in enumerate(bindings[:10]):
        name = b.get("name", {}).get("value", "?")
        score = b.get("score", {}).get("value", "?")
        entity = b.get("entity", {}).get("value", "?")
        print(f"  {i+1}. score={score}  name={name}  entity={entity}")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
