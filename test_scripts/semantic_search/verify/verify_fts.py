"""Full-text search (FTS) verification via SPARQL."""

from test_scripts.semantic_search.config import (
    TEST_SPACE_ID, FTS_INDEX_NAME,
)
from test_scripts.semantic_search.verify import SearchVerifier


async def test_fts_search(v: SearchVerifier):
    """Execute full-text search via SPARQL."""
    print("\n  --- FTS Search (SPARQL) ---")

    # Verify index exists and has rows
    try:
        indexes = await v.client.fts_indexes.list_indexes(space_id=TEST_SPACE_ID)
        idx_names = [idx.index_name for idx in indexes.indexes]
        v.check(f"FTS index '{FTS_INDEX_NAME}' exists",
                FTS_INDEX_NAME in idx_names, f"indexes={idx_names}")
        if FTS_INDEX_NAME in idx_names:
            stats = await v.client.fts_indexes.get_stats(
                space_id=TEST_SPACE_ID, index_name=FTS_INDEX_NAME)
            v.check("FTS index has rows", stats.row_count > 0,
                    f"rows={stats.row_count}")
    except Exception as e:
        v.check("FTS index check", False, str(e))

    # FTS search for "pizza"
    query = f"""PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX core: <http://vital.ai/ontology/vital-core#>
SELECT ?entity ?name ?score
WHERE {{
  OPTIONAL {{ ?entity core:hasName ?name }}
  BIND(vg:textSearch(?entity, "pizza", "{FTS_INDEX_NAME}") AS ?score)
  FILTER(BOUND(?score))
}}
ORDER BY DESC(?score)
LIMIT 10"""
    try:
        resp = await v.sparql(query)
        bindings = resp.results.get("bindings", []) if resp.results else []
        v.check("FTS search 'pizza' returns results",
                len(bindings) > 0, f"count={len(bindings)}")
    except Exception as e:
        v.check("FTS search 'pizza'", False, str(e))

    # FTS search for "tower"
    query2 = f"""PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX core: <http://vital.ai/ontology/vital-core#>
SELECT ?entity ?name ?score
WHERE {{
  OPTIONAL {{ ?entity core:hasName ?name }}
  BIND(vg:textSearch(?entity, "tower", "{FTS_INDEX_NAME}") AS ?score)
  FILTER(BOUND(?score))
}}
ORDER BY DESC(?score)
LIMIT 10"""
    try:
        resp = await v.sparql(query2)
        bindings = resp.results.get("bindings", []) if resp.results else []
        v.check("FTS search 'tower' returns results",
                len(bindings) > 0, f"count={len(bindings)}")
    except Exception as e:
        v.check("FTS search 'tower'", False, str(e))
