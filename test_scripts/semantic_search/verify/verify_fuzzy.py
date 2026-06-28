"""Fuzzy matching search verification via SPARQL."""

from test_scripts.semantic_search.verify import SearchVerifier


async def test_fuzzy_search(v: SearchVerifier):
    """Execute fuzzy matching search via SPARQL."""
    print("\n  --- Fuzzy Search (SPARQL) ---")

    # Fuzzy match — misspelled "Joes Piza" should match "Joe's Pizza"
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
    try:
        resp = await v.sparql(query)
        bindings = resp.results.get("bindings", []) if resp.results else []
        v.check("Fuzzy search 'Joes Piza' returns results",
                len(bindings) > 0, f"count={len(bindings)}")
        if bindings:
            top_name = bindings[0].get("name", {}).get("value", "?")
            v.check("Fuzzy top result contains 'Pizza'",
                    "pizza" in top_name.lower() or "joe" in top_name.lower(),
                    f"name={top_name}")
    except Exception as e:
        v.check("Fuzzy search 'Joes Piza'", False, str(e))

    # Fuzzy match — "Effel Towe" should match "Eiffel Tower"
    query2 = """PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX core: <http://vital.ai/ontology/vital-core#>
SELECT ?entity ?name ?score
WHERE {
  OPTIONAL { ?entity core:hasName ?name }
  BIND(vg:fuzzyMatch(?entity, "Effel Towe", 30) AS ?score)
  FILTER(BOUND(?score))
}
ORDER BY DESC(?score)
LIMIT 10"""
    try:
        resp = await v.sparql(query2)
        bindings = resp.results.get("bindings", []) if resp.results else []
        v.check("Fuzzy search 'Effel Towe' returns results",
                len(bindings) > 0, f"count={len(bindings)}")
    except Exception as e:
        v.check("Fuzzy search 'Effel Towe'", False, str(e))
