# Issue 008: Vector upsert drops subject_uri on retrieval

## Summary

When vectors are inserted via `POST /api/vector-indexes/vectors` (the direct
upsert API), the `subject_uri` and `graph_uri` provided by the client are
hashed to UUID v5 and stored in the vector data table — but the original URI
text is **not** written to the space's `_term` table.

When `GET /api/vector-indexes/vectors` retrieves these vectors, it joins against
the term table to resolve human-readable URIs. Because no term row exists, the
join returns `NULL` and the endpoint falls back to `str(subject_uuid)`, returning
bare UUIDs instead of the original URIs.

## Reproduction

```python
# Upsert with subject_uri = "urn:test:entity_1"
await client.vector_indexes.upsert_vectors(
    space_id=space, index_name=idx,
    vectors=[{"subject_uri": "urn:test:entity_1", "graph_uri": graph,
              "embedding": [0.1, 0.2, 0.3, 0.4]}],
)
# Retrieve
resp = await client.vector_indexes.get_vectors(space_id=space, index_name=idx,
                                                graph_uri=graph)
print(resp.vectors[0].subject_uri)
# → "17884b94-e1eb-5233-81c4-3ade21c4a513"  (expected: "urn:test:entity_1")
```

## Root Cause

`vitalgraph/endpoint/vector_indexes_endpoint.py` `upsert_vectors()` (line ~306)
computes `subject_uuid = uuid.uuid5(ns, f"{entry.subject_uri}\x00U")` and
inserts into the vector data table, but does **not** also insert the term:

```sql
INSERT INTO {term_table} (term_uuid, term_text, term_type)
VALUES ($1, $2, 'U') ON CONFLICT DO NOTHING
```

The UUID generation is compatible with `_generate_term_uuid(uri, 'U')` from
`sparql_sql_space_impl.py`, so adding the term row is safe and consistent.

## Fix

In `upsert_vectors`, after computing `subject_uuid` and `context_uuid`, also
insert both URIs into the term table with `ON CONFLICT DO NOTHING`:

```python
await conn.execute(
    f"INSERT INTO {term_table} (term_uuid, term_text, term_type) "
    f"VALUES ($1, $2, 'U') ON CONFLICT DO NOTHING",
    subject_uuid, entry.subject_uri,
)
```

Applied in `vitalgraph/endpoint/vector_indexes_endpoint.py` lines ~318-330.
**Resolved.**

Regression test: `test_vector_search_api.py::TestVectorSearch::test_get_vectors`
asserts `TEST_URI in [v.subject_uri for v in resp.vectors]`.

## Severity

Medium — affects all vectors inserted via the direct upsert API. Vectors
populated through the reindex pipeline (which goes via the normal RDF ingest
path) are unaffected because they already have term rows.

## Discovered

During API endpoint test coverage expansion (test_vector_search_api.py).
