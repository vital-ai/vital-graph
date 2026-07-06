# drop_space leaves residual FTS/search_mapping tables

## Status: FIXED

## Summary

`SparqlSQLSchema.drop_space()` does not fully clean up all tables created by
the space bootstrap process. After a drop, tables like
`{space_id}_fts_document_segments` and `{space_id}_search_mapping_index`
remain in the database.

## Root Cause

In `vitalgraph/db/sparql_sql/sparql_sql_schema.py`:

1. **`_fts_document_segments`** — Line 802 explicitly skips this table in the
   dynamic `_fts_*` cleanup loop:
   ```python
   if tbl in (f"{space_id}_fts_index", f"{space_id}_fts_document_segments"):
       continue
   ```
   The intent is to let `drop_space_tables_sql()` handle it, but
   `_fts_document_segments` is NOT in the well-known tables list at line 684-702.

2. **`_search_mapping_index`** — Created by the document_segments vector
   bootstrap (`setup_document_segments_vectorization`) but not included in
   `drop_space_tables_sql()`.

## Reproduction

```python
await SparqlSQLSchema.create_space(conn, space_id)
await SparqlSQLSchema.drop_space(conn, space_id)
# Query: SELECT table_name FROM information_schema.tables WHERE table_name LIKE '{space_id}%'
# Result: ['{space_id}_fts_document_segments', '{space_id}_search_mapping_index']
```

## Proposed Fix

Add the missing tables to `drop_space_tables_sql()`:
```python
f"DROP TABLE IF EXISTS {t.get('fts_document_segments', f'{space_id}_fts_document_segments')} CASCADE",
f"DROP TABLE IF EXISTS {space_id}_search_mapping_index CASCADE",
```

Or remove the skip condition on line 802 and let the dynamic `_fts_*` loop
handle `_fts_document_segments`.

## Note on global/system spaces

Some spaces (e.g. `sp_kg_types`) are used globally for KG type definitions.
These should never be dropped in test fixtures. Integration tests must use
ephemeral space IDs (e.g. `inttest_<random>`) and never touch system spaces.

## Severity

**Low** — cosmetic issue (orphan empty tables), but causes test assertion
failures if checking for complete cleanup.

## Files

- `vitalgraph/db/sparql_sql/sparql_sql_schema.py` (lines 681-702, 799-804)
