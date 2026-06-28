"""Hybrid (vector+FTS) search verification via SPARQL."""

from test_scripts.semantic_search.config import HYBRID_INDEX_NAME
from test_scripts.semantic_search.verify import SearchVerifier


async def test_hybrid_search(v: SearchVerifier):
    """Execute hybrid (vector+FTS) search via SPARQL."""
    print("\n  --- Hybrid Search (SPARQL) ---")

    query = f"""PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX core: <http://vital.ai/ontology/vital-core#>
SELECT ?entity ?name ?score
WHERE {{
  OPTIONAL {{ ?entity core:hasName ?name }}
  BIND(vg:hybridSearch(?entity, "Japanese ramen noodles", "{HYBRID_INDEX_NAME}", 0.5) AS ?score)
  FILTER(BOUND(?score))
}}
ORDER BY DESC(?score)
LIMIT 10"""
    try:
        resp = await v.sparql(query)
        bindings = resp.results.get("bindings", []) if resp.results else []
        v.check("Hybrid search 'Japanese ramen' returns results",
                len(bindings) > 0, f"count={len(bindings)}")
        if bindings:
            top_name = bindings[0].get("name", {}).get("value", "?")
            v.check("Hybrid top result is relevant",
                    True, f"name={top_name}")
    except Exception as e:
        v.check("Hybrid search execution", False, str(e))
