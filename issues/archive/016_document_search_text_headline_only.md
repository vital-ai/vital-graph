# Document search_text filter only searches headline, misses content

## Status: ✅ FIXED (2026-07-04)

## Summary

The `search_text` filter in `KGQueryBuilder._build_document_where_clause()` only
searched `hasKGDocumentHeadline`, ignoring `hasKGDocumentContent`. This meant text
searches on segments (which often have a heading but store the searchable text in
content) returned zero results for terms that appear only in the content body.

## Symptoms

1. `query_documents(search_text="neural network", search_scope="segments")` returns
   0 results even though multiple AI-article segments contain "neural network" in
   their content.
2. Only segments whose `hasKGDocumentHeadline` contains the exact search term match.

## Root cause

In `vitalgraph/sparql/kg_query_builder.py`, the document search clause was:

```sparql
?entity haley:hasKGDocumentHeadline ?_hl .
FILTER(CONTAINS(LCASE(STR(?_hl)), LCASE("search term")))
```

This is a required triple pattern, so entities without a headline are also excluded.
Content (`hasKGDocumentContent`) was never checked.

## Fix applied — Two modes

The `search_text` filter now supports two modes controlled by the new
`fts_index_name` field on `DocumentSearchCriteria`:

### Mode 1: FTS (when `fts_index_name` is set)

Uses the existing GIN-indexed FTS infrastructure (`vg:textSearch`):

```sparql
BIND(vg:textSearch(?entity, "search term", "document_segments") AS ?_fts_score)
FILTER(?_fts_score > 0)
```

Benefits:
- GIN tsvector index — O(log n) lookup instead of full scan
- BM25 relevance ranking (results sorted by `?_fts_score DESC`)
- Language-aware stemming ("networks" matches "network")
- Populated automatically via `auto_sync` (same path as vectors)

### Mode 2: CONTAINS fallback (when `fts_index_name` is not set)

Brute-force scan on headline + content for backward compatibility:

```sparql
OPTIONAL { ?entity haley:hasKGDocumentHeadline ?_hl . }
OPTIONAL { ?entity haley:hasKGDocumentContent ?_ct . }
FILTER(CONTAINS(LCASE(STR(COALESCE(?_hl, ""))), LCASE("search term"))
    || CONTAINS(LCASE(STR(COALESCE(?_ct, ""))), LCASE("search term")))
```

## Files changed

| File | Change |
|------|--------|
| `vitalgraph/sparql/kg_query_builder.py` | `_build_document_where_clause()` — dual-mode search_text (lines ~1787-1807); `build_document_query_sparql()` — project `?_fts_score` + ORDER BY DESC |
| `vitalgraph/sparql/kg_query_builder.py` | `DocumentQueryCriteria` — added `fts_index_name: Optional[str]` field |
| `vitalgraph/model/kgentities_model.py` | `DocumentSearchCriteria` — added `fts_index_name` field with description |
| `vitalgraph/endpoint/kgquery_endpoint.py` | Pass `fts_index_name` through to builder |
| `vitalgraph/client/endpoint/kgqueries_endpoint.py` | Added `fts_index_name` param to `query_documents()` |
| `tests/api/test_wikipedia_document_e2e.py` | Creates FTS index + attaches to mapping; passes `fts_index_name=INDEX_NAME` |

## Usage

```python
# FTS mode (recommended — requires FTS index to exist)
resp = await vg_client.kgqueries.query_documents(
    space_id="my_space",
    graph_id="my_graph",
    search_text="neural network",
    fts_index_name="document_segments",  # ← enables GIN BM25 search
    search_scope="segments",
)

# Fallback mode (no FTS index needed, but slower)
resp = await vg_client.kgqueries.query_documents(
    space_id="my_space",
    graph_id="my_graph",
    search_text="neural network",
    # fts_index_name not set → CONTAINS scan
    search_scope="segments",
)
```

## Prerequisites for FTS mode

1. Create FTS index: `vg_client.fts_indexes.create_index(space_id, index_name, languages=["english"])`
2. Attach to search mapping: `vg_client.search_mappings.add_index(space_id, mapping_id, index_type="fts", index_name=...)`
3. Data is populated automatically by `auto_sync` on document/segment CRUD

## Test coverage

- `tests/api/test_wikipedia_document_e2e.py::TestKGQueryDocuments::test_query_with_text_search`
  — searches for "neural network" in segments using FTS mode; passes (31/31 tests green)

## Related

- `vitalgraph/vectorization/fts_populator.py` — FTS population pipeline
- `vitalgraph/vectorization/auto_sync.py` — `_sync_fts_for_subjects()` keeps FTS data current
- `vitalgraph/db/sparql_sql/vg_functions.py` — `text_search_sql()` generates BM25 SQL
- `vitalgraph/endpoint/fts_indexes_endpoint.py` — FTS index REST API
- The `get_vectors` endpoint pagination bug (fixed same session) — see
  `vitalgraph/endpoint/vector_indexes_endpoint.py`
