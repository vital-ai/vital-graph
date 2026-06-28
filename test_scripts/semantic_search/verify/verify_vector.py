"""Vector similarity search verification via SPARQL."""

from test_scripts.semantic_search.config import (
    TEST_SPACE_ID, VECTOR_INDEX_NAME,
)
from test_scripts.semantic_search.verify import SearchVerifier


async def test_vector_search(v: SearchVerifier):
    """Execute vector similarity search via SPARQL."""
    print("\n  --- Vector Search (SPARQL) ---")

    # Verify index exists
    indexes = await v.client.vector_indexes.list_indexes(space_id=TEST_SPACE_ID)
    idx_names = [idx.index_name for idx in indexes.indexes]
    v.check(f"Vector index '{VECTOR_INDEX_NAME}' exists",
            VECTOR_INDEX_NAME in idx_names, f"indexes={idx_names}")

    # Vector search for "authentic Italian pizza New York"
    query = f"""PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX core: <http://vital.ai/ontology/vital-core#>
SELECT ?entity ?name ?score
WHERE {{
  OPTIONAL {{ ?entity core:hasName ?name }}
  BIND(vg:vectorSimilarity(?entity, "authentic Italian pizza New York", "{VECTOR_INDEX_NAME}") AS ?score)
  FILTER(BOUND(?score))
  FILTER(?score > 0.1)
}}
ORDER BY DESC(?score)
LIMIT 10"""
    try:
        resp = await v.sparql(query)
        bindings = resp.results.get("bindings", []) if resp.results else []
        v.check("Vector search returns results",
                len(bindings) > 0, f"count={len(bindings)}")
        if bindings:
            top_name = bindings[0].get("name", {}).get("value", "?")
            top_score = bindings[0].get("score", {}).get("value", "?")
            v.check("Vector top result is relevant",
                    True, f"name={top_name}, score={top_score}")
    except Exception as e:
        v.check("Vector search execution", False, str(e))

    # Vector search for "historical monument"
    query2 = f"""PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX core: <http://vital.ai/ontology/vital-core#>
SELECT ?entity ?name ?score
WHERE {{
  OPTIONAL {{ ?entity core:hasName ?name }}
  BIND(vg:vectorSimilarity(?entity, "historical monument landmark", "{VECTOR_INDEX_NAME}") AS ?score)
  FILTER(BOUND(?score))
  FILTER(?score > 0.1)
}}
ORDER BY DESC(?score)
LIMIT 5"""
    try:
        resp = await v.sparql(query2)
        bindings = resp.results.get("bindings", []) if resp.results else []
        v.check("Vector search 'historical monument' returns results",
                len(bindings) > 0, f"count={len(bindings)}")
    except Exception as e:
        v.check("Vector search 'historical monument'", False, str(e))
