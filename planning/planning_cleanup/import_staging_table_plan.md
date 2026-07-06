# Import Engine — Staged Bulk Import via UNLOGGED Tables

## 1. Summary

The current `ImportEngine` (`vitalgraph/endpoint/impl/data_import_impl.py`)
has two import paths that both write directly into live term/quad tables:

- **Bulk** — drops indexes, COPY into live tables, recreate indexes.
  Fast but blocks all reads and writes for the entire duration.
- **Incremental** — batched `INSERT ON CONFLICT` (5k rows).  No index
  drops, safe for concurrent access, but slow for large datasets.

A full UNLOGGED staging table implementation exists in the archive but
was never integrated.  This plan covers reviewing, modernizing, and
integrating it as a third import mode for scalability.

| Item | Detail |
|------|--------|
| **Archived implementation** | `archive/archive_vitalgraph_old/db_postgresql/space/postgresql_space_db_import.py` |
| **Current import engine** | `vitalgraph/endpoint/impl/data_import_impl.py` |
| **Test script reference** | `test_scripts/import/test_copy_import_process.py` |
| **Priority** | High |

---

## 2. Archived Implementation Overview

The archived `PostgreSQLSpaceDBImport` class implements a 5-phase
staging pipeline:

1. **`setup_partition_import_session()`** — Creates UNLOGGED temp tables
   (`temp_term_import_*`, `temp_quad_import_*`) with the same schema as
   main tables plus extra raw-text columns.  Adds `CHECK (dataset = ...)`
   constraints with `NOT VALID` for fast partition attachment.

2. **`load_ntriples_into_partition_session()`** — Parses N-Triples via
   pyoxigraph → writes CSV with deterministic UUIDs → `COPY` into the
   UNLOGGED staging quad table using 64KB chunked streaming.

3. **`_extract_and_deduplicate_terms_for_partition()`** — Single
   `INSERT ... SELECT DISTINCT ... FROM (UNION ALL of s/p/o/g) ON CONFLICT DO NOTHING`
   to populate the staging term table from the staging quad table.

4. **`attach_partitions_zero_copy()`** — *(did not work in practice)*
   Attempted to drop extra columns, `SET LOGGED`, and `ATTACH PARTITION`
   to main tables.  This path had issues and was never production-ready.

5. **`_vacuum_analyze_partitions()`** — VACUUM ANALYZE on new partitions.

---

## 3. What to Keep vs Discard

The partition-attach path (phase 4) did not work reliably and should
be replaced with a straightforward `INSERT INTO main SELECT FROM staging`
transfer.  The valuable parts are phases 1–3: UNLOGGED staging tables
with COPY-based loading and SQL-side term deduplication.

---

## 4. Why UNLOGGED Staging Tables Matter

- Current bulk path writes directly to live tables with indexes dropped —
  blocks both reads and writes during import
- Current incremental path uses `INSERT ON CONFLICT` row-by-row in
  5k batches — slow for large datasets
- UNLOGGED staging tables: no WAL overhead during load, no index
  contention on live tables, single bulk `INSERT INTO ... SELECT`
  transfer at the end

---

## 5. Concurrency Model

- **Staged bulk**: Reads continue during the load phase (staging tables
  are separate).  Writes to the space are blocked only during the
  brief transfer window (drop indexes → INSERT → recreate indexes).
  This is a significant improvement over the current bulk path which
  blocks everything for the entire duration.
- **Incremental**: Reads and writes continue in parallel throughout.
  No blocking at any point — batched `INSERT ON CONFLICT` is safe
  for concurrent access.

### 5.1 Write Blocking During Transfer

Use PostgreSQL table-level locks for correctness:
```sql
BEGIN;
LOCK TABLE {term_tbl} IN EXCLUSIVE MODE;
LOCK TABLE {quad_tbl} IN EXCLUSIVE MODE;
-- drop indexes, INSERT INTO ... SELECT, recreate indexes
COMMIT;  -- locks release automatically
```
`EXCLUSIVE MODE` allows concurrent `SELECT` (reads continue) but
blocks `INSERT`/`UPDATE`/`DELETE`.  Queued writes proceed automatically
once the transaction commits.  This works whether the bulk import is
initiated from the CLI or the REST API.

### 5.2 Client Notifications

Clients also need to know the space is in bulk-import mode so they can
handle blocked writes gracefully (e.g. show a status message rather
than timing out with an error).  Use `NOTIFY`/`LISTEN` to broadcast
space state transitions:
```
NOTIFY vitalgraph_space_events, '{"space":"my_space","event":"bulk_import_start"}'
-- ... transfer completes ...
NOTIFY vitalgraph_space_events, '{"space":"my_space","event":"bulk_import_end"}'
```
API clients subscribed via `LISTEN vitalgraph_space_events` can then
return an appropriate response (e.g. HTTP 503 with `Retry-After`)
instead of hanging on a lock or throwing unexpected errors.

---

## 6. Integration Tasks

1. Review the archived staging table creation and COPY phases against
   current schema (the archive uses psycopg2-style sync cursors;
   current codebase uses asyncpg)
2. Port to asyncpg using `conn.copy_records_to_table()` or
   `conn.copy_to_table()` for the COPY phase
3. Simplify staging table schema — drop extra columns (`is_literal`,
   `object_datatype`, `processing_status`, `import_batch_id`) that
   were only needed for the partition-attach path
4. Replace the partition-attach step with index-free bulk transfer:
   ```
   a. Save and drop non-PK indexes on live term + quad tables
   b. INSERT INTO {term_tbl} SELECT ... FROM {staging_term_tbl}
   c. INSERT INTO {quad_tbl} SELECT ... FROM {staging_quad_tbl}
   d. Recreate saved indexes
   e. DROP staging tables
   ```
   Dropping indexes before the transfer avoids per-row index probes
   and ON CONFLICT overhead.  Since the staging term table is already
   deduplicated (phase 3) and the staging quad table contains only
   new data, conflicts should not arise in the normal case.  For
   append-to-existing-data scenarios, add `ON CONFLICT DO NOTHING`
   on the term insert only (terms may pre-exist; quads should not
   duplicate if graph was cleared or is new).
5. Add staging path as a third import mode in `ImportEngine`
   (e.g. `import_ntriples_staged`)
6. Wire into the REST import endpoint as an option
   (`ImportMode.STAGED`)
7. Add integration test: import 7M WordNet triples via staged path →
   verify data → compare timing vs bulk and incremental paths
8. Ensure auxiliary table resync (edge, frame_entity, stats) runs
   after staging import completes

---

## 7. Performance Baselines (Informational)

| Path | Mechanism | Expected time (7M triples) | Concurrent reads | Concurrent writes |
|------|-----------|---------------------------|------------------|-------------------|
| **Bulk** (current) | Drop indexes → COPY → recreate | ~60s | Blocked | Blocked |
| **Incremental** (current) | INSERT ON CONFLICT 5k batches | ~2–5 min | Yes | Yes |
| **Staged** (planned) | UNLOGGED COPY → transfer with locks | ~60–90s | Yes (blocked briefly during transfer) | Blocked during transfer only |
