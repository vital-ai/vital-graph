# Plan: Review and Reorganize `scripts/` Directory

**Date:** 2026-06-28
**Status:** ✅ Complete

---

## Goal

Review each file in `scripts/` to determine whether it:
1. Is an active operational script still used in production/development
2. Is a one-off migration script that has already been run (archive candidate)
3. Is a debug/investigation script (archive or delete candidate)
4. Should be moved to a more appropriate location (e.g., `bin/`, `vitalgraph/`, `test_scripts/`)

---

## Python Scripts to Review (10 files)

| # | File | Size | Initial Category (to confirm) |
|---|------|------|-------------------------------|
| 1 | `backfill_entity_server_properties.py` | 9K | One-off migration — likely already run |
| 2 | `check_residual_triples.py` | 2K | Debug/investigation — check if still needed |
| 3 | `delete_kggraph_uri_subjects.py` | 4K | Data repair — likely one-off |
| 4 | `generate_jwt_secret.py` | 3K | Utility — may belong in `bin/` or CLI |
| 5 | `init_vitalgraph_fuseki_admin.py` | 13K | Fuseki setup — check if fuseki backend still active |
| 6 | `migrate_entity_registry_vectors.py` | 1K | Migration — likely already run |
| 7 | `migrate_fuzzy_redis_to_pg.py` | 14K | Migration — Redis→PG fuzzy index, likely already run |
| 8 | `query_entity_graph_leftovers.py` | 7K | Debug/investigation — orphan detection |
| 9 | `query_kggraph_uri_subjects.py` | 2K | Debug/investigation — diagnostic query |
| 10 | `sync_fuzzy_index.py` | 17K | Operational — fuzzy index sync, may be active |

---

## SQL Scripts to Review (`scripts/sql_scripts/`, 34 files)

### Likely Active / Reference

| # | File | Size | Notes |
|---|------|------|-------|
| 1 | `init-sparql-sql.sql` | 3K | Core DB init — likely embedded in code already |
| 2 | `create_vitalgraph_term_uuid_function.sql` | 1K | UUID function — check if embedded in DDL |
| 3 | `create_process_table.sql` | 1K | Admin table — check if embedded |
| 4 | `migrate_graph_unique_constraint.sql` | 0.3K | Migration — likely already applied |

### Edge Materialized View iterations (likely archive)

| # | File | Size | Notes |
|---|------|------|-------|
| 5 | `create_edge_materialized_view.sql` | 3K | MV creation |
| 6 | `create_optimized_edge_materialized_view.sql` | 4K | Optimized version |
| 7 | `create_incremental_edge_mv.sql` | 3K | Incremental refresh |
| 8 | `create_edge_indexes.sql` | 2K | Edge indexes |
| 9 | `create_simple_edge_indexes.sql` | 2K | Simplified indexes |
| 10 | `create_covering_index.sql` | 1K | Covering index |
| 11 | `step1_create_edge_mv.sql` | 2K | Step-by-step MV setup |
| 12 | `step2_create_edge_indexes.sql` | 1K | Step-by-step indexes |

### Happy frame query iterations (17 versions — likely archive)

| # | File | Size | Notes |
|---|------|------|-------|
| 13 | `happy_frame_query.sparql` | — | Original SPARQL query |
| 14–30 | `happy_frame_query_1.sql` through `_17_verbose.sql` | 3–9K each | 17 SQL iterations of the same query optimization |

### Debug/diagnostic SQL

| # | File | Size | Notes |
|---|------|------|-------|
| 31 | `debug_frame_query_steps.sql` | 4K | Debug query |
| 32 | `find_unused_terms.sql` | 8K | Maintenance query |
| 33 | `get_constants.sql` | 3K | Reference query |

---

## Review Process (per file)

1. Read the file header/docstring
2. Check if the functionality is embedded in the main codebase (duplicated)
3. Check if it references current or obsolete infrastructure
4. Categorize:
   - **Move to `apps/`** — Ongoing maintenance/operational tool, should be a standalone app (or incorporate into CLI entry points in `bin/`)
   - **Move to `apps/fuseki/`** — Fuseki-related scripts (experimental backend, kept separate)
   - **Move to `test_scripts/`** — Diagnostic/test utility
   - **Move to `vitalgraph_sparql_sql_dev/`** — SPARQL-to-SQL dev/test scripts (this directory holds dev and testing code for the SPARQL-to-SQL implementation, separate from the main codebase)
   - **Archive** — One-off migration or historical iteration, move to `archive/scripts/`
   - **Delete** — Empty, trivial, or fully superseded

---

## Expected Outcomes

### Likely archive (completed migrations / iterations)
- `backfill_entity_server_properties.py` — one-off backfill
- `migrate_entity_registry_vectors.py` — one-off migration
- `migrate_fuzzy_redis_to_pg.py` — Redis→PG migration (has a planning doc)
- `happy_frame_query_*.sql` (17 iterations) — historical optimization work
- Edge MV SQL files (8 files) — historical iterations

### Likely move to `apps/` or incorporate into CLI
- `generate_jwt_secret.py` — operational utility, incorporate into CLI or `apps/`
- `sync_fuzzy_index.py` — ongoing maintenance tool, move to `apps/`

### Likely move to `apps/fuseki/`
- `init_vitalgraph_fuseki_admin.py` — Fuseki setup/admin (experimental backend)

### Likely move to `test_scripts/`
- `check_residual_triples.py` — diagnostic query
- `query_entity_graph_leftovers.py` — orphan detection diagnostic
- `query_kggraph_uri_subjects.py` — diagnostic query
- `delete_kggraph_uri_subjects.py` — data repair (review if still needed)

### Likely move to `vitalgraph_sparql_sql_dev/`
- `happy_frame_query_*.sql` (17 iterations) — SPARQL-to-SQL optimization work
- `debug_frame_query_steps.sql` — SPARQL-to-SQL debugging
- `happy_frame_query.sparql` — source SPARQL for the SQL iterations

### Likely keep as reference SQL
- `init-sparql-sql.sql` — check if embedded in code, keep if not
- `find_unused_terms.sql` — maintenance utility
- `create_vitalgraph_term_uuid_function.sql` — check if embedded in DDL

---

## Results

All 44 files processed. `scripts/` now contains only 6 reference SQL files in `sql_scripts/`.

### Archived → `archive/scripts/` (13 files)
One-off migrations and historical iterations:
- `backfill_entity_server_properties.py` — incorporated into `vitalgraph/tasks/backfill_server_properties_task.py`
- `migrate_entity_registry_vectors.py` — one-off DDL migration
- `check_residual_triples.py` — hardcoded to specific campaign URIs, one-off investigation
- `query_kggraph_uri_subjects.py` — hardcoded campaign URIs, one-off
- `delete_kggraph_uri_subjects.py` — hardcoded campaign URIs, one-off data repair
- 8 edge materialized view SQL iterations (`create_edge_*.sql`, `create_covering_index.sql`, `step1_*.sql`, `step2_*.sql`)

### Moved → `apps/fuzzy_index/` (2 files)
Ongoing operational tools:
- `sync_fuzzy_index.py` — bulk sync of entity fuzzy index
- `migrate_fuzzy_redis_to_pg.py` — PG fuzzy index rebuild/verify/compare

### Moved → `apps/` (1 file)
- `generate_jwt_secret.py` — JWT secret key utility

### Moved → `apps/fuseki/` (1 file)
- `init_vitalgraph_fuseki_admin.py` — Fuseki admin setup (experimental backend)

### Moved → `test_scripts/` (1 file)
- `query_entity_graph_leftovers.py` — orphan graph object diagnostic

### Moved → `vitalgraph_sparql_sql_dev/sql_reference/` (19 files)
SPARQL-to-SQL dev/optimization work:
- `happy_frame_query.sparql` — source SPARQL query
- `happy_frame_query_1.sql` through `happy_frame_query_17_verbose.sql` — 17 SQL optimization iterations
- `debug_frame_query_steps.sql` — frame query debugging

### Kept in `scripts/sql_scripts/` (6 files)
Reference SQL:
- `init-sparql-sql.sql` — core DB init (also embedded in code)
- `create_vitalgraph_term_uuid_function.sql` — UUID function (also embedded in DDL)
- `create_process_table.sql` — admin table DDL
- `find_unused_terms.sql` — maintenance utility
- `get_constants.sql` — reference query
- `migrate_graph_unique_constraint.sql` — migration DDL

---

## Dependencies

- Check `bin/` for any scripts that already wrap these
- Check if migration scripts have corresponding planning docs marked complete
- Verify fuseki backend status before archiving fuseki-related scripts
