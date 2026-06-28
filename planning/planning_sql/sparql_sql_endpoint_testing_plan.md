# SPARQL-SQL Backend: Endpoint Testing Plan

## Overview

This plan tracks the testing of all VitalGraph REST API endpoints against the **sparql_sql** backend (pure PostgreSQL, no Fuseki). The goal is to validate every endpoint with real data, starting with triples and KG endpoints using lead entity data — the same dataset tested against the fuseki_postgresql backend in `vitalgraph_client_test/test_lead_entity_graph.py` and `test_lead_entity_graph_dataset.py`.

## Architecture Context

```
Client (VitalGraphClient)
  → REST API (FastAPI endpoints)
    → Endpoint Layer (kgentities_endpoint.py, etc.)
      → KG Backend Adapter (SparqlSQLBackendAdapter in kg_backend_utils.py)
        → SparqlSQLSpaceImpl (sparql_sql_space_impl.py)
          → PostgreSQL (asyncpg pool)
          → Jena Sidecar (SPARQL → SQL compilation)
```

Key files:
- **Backend**: `vitalgraph/db/sparql_sql/sparql_sql_space_impl.py` — SpaceBackendInterface impl
- **Adapter**: `vitalgraph/kg_impl/kg_backend_utils.py` — `SparqlSQLBackendAdapter`
- **Endpoints**: `vitalgraph/endpoint/` — FastAPI route handlers
- **Schema**: `vitalgraph/db/sparql_sql/sparql_sql_schema.py` — per-space DDL
- **Admin CLI**: `vitalgraph/admin_cmd/vitalgraphdb_admin_cmd.py` — DB init & bulk load

## Reference Test Scripts (fuseki_postgresql backend)

These existing scripts test the same operations against the fuseki_postgresql backend:
- `vitalgraph_client_test/test_lead_entity_graph.py` — CRUD test (load, verify, query, frame ops, delete)
- `vitalgraph_client_test/test_lead_entity_graph_dataset.py` — Bulk load + read-only queries
- `vitalgraph_client_test/entity_graph_lead/` — Individual CRUD test cases
- `vitalgraph_client_test/entity_graph_lead_dataset/` — Bulk load + query test cases

---

## Phase 0: Infrastructure Prerequisites

| # | Task | Status | Notes |
|---|------|--------|-------|
| 0.1 | sparql_sql Docker service running (PostgreSQL + app) | ✅ Done | Docker Compose with `sparql_sql_graph` DB |
| 0.2 | Jena sidecar running on port 7070 | ✅ Done | Required for SPARQL→SQL compilation |
| 0.3 | Admin tables initialized (install, space, graph, user) | ✅ Done | Via `sql_scripts/init-sparql-sql.sql` |
| 0.4 | `pg_trgm` extension installed | ✅ Done | In `init-sparql-sql.sql` line 5 |
| 0.5 | GIN trigram index in schema DDL | ✅ Done | Added to `sparql_sql_schema.py` |

---

## Phase 1: Foundation Endpoints (Already Verified)

| # | Endpoint | Method | Status | Test Script |
|---|----------|--------|--------|-------------|
| 1.1 | `/api/login` | POST | ✅ Done | `test_sparql_wordnet.py` |
| 1.2 | `/api/spaces` | GET | ✅ Done | `test_sparql_wordnet.py` |
| 1.3 | `/api/spaces` | POST (create) | ✅ Done | WordNet space exists |
| 1.4 | `/api/graphs/sparql/{space}/query` | POST | ✅ Done | 7/7 WordNet queries pass |
| 1.5 | `/api/graphs/sparql/{space}/graphs` | GET (list) | ✅ Done | `test_sparql_sql_crud.py` — Graphs CRUD 9/9 |
| 1.6 | `/api/graphs/sparql/{space}/graph` | POST (create) | ✅ Done | `test_sparql_sql_crud.py` — Graphs CRUD 9/9 |
| 1.7 | `/api/graphs/sparql/{space}/graph/{uri}` | DELETE (drop) | ✅ Done | `test_sparql_sql_crud.py` — Graphs CRUD 9/9 |
| 1.8 | `/api/graphs/sparql/{space}/graph` | POST (clear) | ✅ Done | `test_sparql_sql_crud.py` — Graphs CRUD 9/9 |
| 1.9 | `/api/spaces` | PUT (update) | ✅ Done | `test_sparql_sql_crud.py` — Spaces CRUD 7/7 |
| 1.10 | `/api/spaces/{id}` | GET (get) | ✅ Done | `test_sparql_sql_crud.py` — Spaces CRUD 7/7 |
| 1.11 | `/api/spaces/{id}/info` | GET (info) | ✅ Done | `test_sparql_sql_crud.py` — Spaces CRUD 7/7 |
| 1.12 | `/api/spaces/{id}` | DELETE | ✅ Done | `test_sparql_sql_crud.py` — Spaces CRUD 7/7 |

---

## Phase 2: Triples Endpoint

Test raw triple CRUD operations. These are the lowest-level data operations and validate the quad storage layer.

| # | Endpoint | Method | Route | Status | Notes |
|---|----------|--------|-------|--------|-------|
| 2.1 | List triples | GET | `/api/graphs/triples` | ✅ Done | Pagination, subject/predicate/object filters |
| 2.2 | Add triples | POST | `/api/graphs/triples` | ✅ Done | QuadRequest body (N-Quads) |
| 2.3 | Delete triples | DELETE | `/api/graphs/triples` | ✅ Done | QuadRequest body |

**All 11/11 triples tests pass** (`test_sparql_sql_crud.py`):
- Add 7 triples, list with pagination, filter by subject/predicate/object_filter
- Delete by subject, delete by predicate, delete remaining, verify 0 remaining

### Key Fixes Applied
- **`query_quads()`** added to `SparqlSQLSpaceImpl` — delegates to `execute_sparql_query()` and extracts SPARQL bindings
- **`.graphs` adapter** added — lightweight wrapper so endpoint code can call `db_space_impl.graphs.list_graphs()`
- **Graph URIs stored as `'U'`** — removed `force_type='G'` that caused UUID mismatches in the V2 pipeline
- **`remove_rdf_quads_batch`** — now extracts `lang` and resolves `datatype_id` from RDFLib Literals for correct UUID generation
- **Client `delete_triples`** — fixed to list matching triples first, then send as `QuadRequest` body

---

## Phase 3: KG Entities — Multi-Step Testing

This is the primary test phase. Three progressive steps, each with its own runner and test cases.

### Step 1: KGEntities CRUD (programmatic data)

Basic entity + entity frame CRUD using programmatically created objects — no lead data dependency.

| # | Endpoint | Method | Route | Status | Notes |
|---|----------|--------|-------|--------|-------|
| 3.1.1 | Create entities | POST | `/api/graphs/kgentities` | ✅ Done | KGEntity objects via VitalSigns |
| 3.1.2 | List entities | GET | `/api/graphs/kgentities` | ✅ Done | Pagination, count |
| 3.1.3 | Get entity by URI | GET | `/api/graphs/kgentities?uri=...` | ✅ Done | Single retrieval |
| 3.1.4 | Update entity | POST | `/api/graphs/kgentities?operation_mode=update` | ✅ Done | Update name, verify (required UNION+BIND fix) |
| 3.1.5 | Delete entity | DELETE | `/api/graphs/kgentities?uri=...` | ✅ Done | Single + verify |
| 3.1.6 | Batch delete entities | DELETE | `/api/graphs/kgentities?uri_list=...` | ✅ Done | |
| 3.1.7 | Create entity frames | POST | `/api/graphs/kgentities/kgframes` | ✅ Done | Add frames to entity |
| 3.1.8 | Get entity frames | GET | `/api/graphs/kgentities/kgframes` | ✅ Done | List, hierarchy |
| 3.1.9 | Update entity frames | PUT | `/api/graphs/kgentities/kgframes` | ✅ Done | Modify slot value |
| 3.1.10 | Delete entity frames | DELETE | `/api/graphs/kgentities/kgframes` | ✅ Done | Remove frame + verify |

**KGEntities + Frames CRUD: 18/18 tests pass** (`test_sparql_sql_kgentities.py`):
- KGEntities (10/10): Create 3 entities (individually), list, get by URI, update name + verify, delete single, verify deleted, list remaining, batch delete, final verify 0
- Entity Frames (8/8): Create frames with slots, list frames, get frame by URI, verify slot values, update slot + verify, delete frame + verify, verify remaining, cleanup

**Key fixes applied:**
- **UNION+BIND SQL type mismatch** — `produce_companions()` in `sql_type_generation.py` emitted `NULL` (text) for `__uuid` column. In a UNION ALL with a BGP branch having real `uuid` columns, PostgreSQL errored with "UNION types text and uuid cannot be matched". Fix: `NULL` → `NULL::uuid` (line 233).

**Known bug — batch `create_kgentities` kGGraphURI grouping:**
- When `create_kgentities` is called with multiple independent KGEntity objects in one batch, `set_dual_grouping_uris_with_frame_separation` stamps ALL objects with the first entity's URI as `kGGraphURI`. This is correct for entity graphs (entity + frames + slots) but wrong for independent entities. The update's DELETE phase then deletes ALL entities sharing that `kGGraphURI`, not just the target. **Workaround**: create independent entities with separate calls. **Fix needed**: the grouping logic should detect multiple independent entities in a batch and assign each its own `kGGraphURI`.

**Key fixes applied (Entity Frames):**
- **`categorize_frame_objects`** — switched from string-matching (`type(obj).__name__`) to `isinstance` checks for `KGFrame`, `KGSlot`, `VITAL_Edge`
- **`assign_grouping_uris`** — skip `frameGraphURI` assignment for `Edge_hasEntityKGFrame` (which doesn't have that property); assign for `KGFrame`, `KGSlot`, `Edge_hasKGSlot`, `Edge_hasKGFrame`
- **`_update_entity_frames` two-pass grouping** — server-side fix: first pass collects all `KGFrame` objects and initializes groups, second pass assigns slots and edges to the correct frame group regardless of input object order

**Runner**: `test_sparql_sql_kgentities.py`
**Cases**: `sparql_sql/case_kgentities_crud.py`, `sparql_sql/case_entity_frames_crud.py`
**Orchestrator**: Wire into `test_sparql_sql_crud.py` as Step 7

### Step 2: Lead Entity CRUD (real .nt data, 3 leads)

Load real lead entity graphs from N-Triples files (first 3 leads), run full CRUD lifecycle per lead.
Mirrors `test_lead_entity_graph.py` flow against sparql_sql backend.

| # | Operation | Status | Notes |
|---|-----------|--------|-------|
| 3.2.1 | Load lead .nt → VitalSigns → create_kgentities | ✅ Done | Parse N-Triples via RDFLib |
| 3.2.2 | Verify entity graph structure | ✅ Done | Triple count, object types |
| 3.2.3 | Query entity graph (SPARQL) | ✅ Done | Basic SPARQL on entity data |
| 3.2.4 | Frame operations: list all frames | ✅ Done | Top-level + child hierarchy |
| 3.2.5 | Frame operations: get specific frame | ✅ Done | With slots |
| 3.2.6 | Frame operations: update slot value | ✅ Done | Modify + verify round-trip |
| 3.2.7 | Frame operations: delete frame | ✅ Done | Remove + verify |
| 3.2.8 | Delete entity graph | ✅ Done | Full cleanup |

**Lead Entity CRUD: 60/60 tests pass** (`test_sparql_sql_lead_crud.py`):
- 3 leads × 20 tests each (load, verify×3, query, frame ops×11, delete×3)
- Reuses existing `entity_graph_lead/` test case modules against sparql_sql backend

**Runner**: `test_sparql_sql_lead_crud.py` (processes 3 leads sequentially)
**Cases**: Reuses `entity_graph_lead/case_load_lead_graph.py`, `case_verify_lead_graph.py`, `case_query_lead_graph.py`, `case_frame_operations.py`, `case_delete_lead_graph.py`
**Data**: `lead_test_data/lead_*.nt` (first 3 files)

### Step 3: Lead Dataset Queries (100 leads, complex queries)

Bulk load 100 lead entities, run complex KGQuery frame-based queries.
Mirrors `test_lead_entity_graph_dataset.py` flow against sparql_sql backend.

| # | Operation | Status | Notes |
|---|-----------|--------|-------|
| 3.3.1 | Bulk load 100 lead .nt files | ✅ Done | 192,810 triples, 115s (~0.75s/entity) after batch optimization |
| 3.3.2 | List & paginate entities | ✅ Done | Verify count=100, 5 pages of 20 |
| 3.3.3 | Retrieve entity graphs (sample 5) | ✅ Done | Verify frame structure, child frames |
| 3.3.4 | KGQuery: MQL leads | ✅ Done | Frame query: `MQL=true` (61ms) |
| 3.3.5 | KGQuery: State filter | ✅ Done | company state = "CA" (52ms) |
| 3.3.6 | KGQuery: Rating filter | ✅ Done | MQL rating >= 65 (44ms) |
| 3.3.7 | KGQuery: Multi-criteria | ✅ Done | Combined frame/slot filters (161ms) |
| 3.3.8 | KGQuery: Converted leads | ✅ Done | `isConverted=true` (41ms) |

**Lead Dataset: 21/21 tests pass** (`test_sparql_sql_lead_dataset.py`):
- Bulk load (2/2), List & Query (4/4), Retrieve (3/3), KGQuery (12/12)
- 12 KGQuery frame-based queries averaging **62ms** each
- Includes hierarchical parent→child frame queries, range filters, pagination, empty results
- `SKIP_LOAD=True` option re-runs queries only (9.7s vs 115s with load)

**Runner**: `test_sparql_sql_lead_dataset.py` (standalone, `SKIP_LOAD` option)
**Cases**: Reuses `entity_graph_lead_dataset/case_bulk_load_dataset.py`, `case_list_and_query_entities.py`, `case_retrieve_entity_graphs.py`, `case_kgquery_lead_queries.py`
**Data**: `lead_test_data/lead_*.nt` (100 files)

### Reference: Existing Test Cases (fuseki_postgresql backend)

These existing scripts test the same operations against fuseki_postgresql and serve as reference implementations:

| Directory | Cases | Description |
|-----------|-------|-------------|
| `entity_graph_lead/` | `case_load_lead_graph.py` | Load .nt → VitalSigns → create |
| | `case_verify_lead_graph.py` | Verify structure after load |
| | `case_query_lead_graph.py` | SPARQL queries on entity |
| | `case_frame_operations.py` | Frame hierarchy, list/get/update/delete (867 lines) |
| | `case_delete_lead_graph.py` | Delete entity + verify |
| `entity_graph_lead_dataset/` | `case_bulk_load_dataset.py` | Bulk load 100 .nt files |
| | `case_list_and_query_entities.py` | Paginated list + SPARQL queries |
| | `case_retrieve_entity_graphs.py` | Sample entity graph retrieval |
| | `case_kgquery_lead_queries.py` | 8 KGQuery scenarios (935 lines) |

### Phase 3 — Future Endpoints (after lead testing)

### 3F: KGRelations Endpoint

| # | Endpoint | Method | Route | Status | Notes |
|---|----------|--------|-------|--------|-------|
| 3F.1 | List relations | GET | `/api/graphs/kgrelations` | ❌ TODO | Filter by source/dest/type |
| 3F.2 | Create relations | POST | `/api/graphs/kgrelations` | ❌ TODO | |
| 3F.3 | Delete relations | DELETE | `/api/graphs/kgrelations` | ❌ TODO | |
| 3F.4 | Query relations | POST | `/api/graphs/kgrelations/query` | ❌ TODO | |

### 3G: KGQueries Endpoint

| # | Endpoint | Method | Route | Status | Notes |
|---|----------|--------|-------|--------|-------|
| 3G.1 | Relation query | POST | `/api/graphs/kgqueries` | ❌ TODO | query_type=relation |
| 3G.2 | Frame query | POST | `/api/graphs/kgqueries` | ✅ Done | query_type=frame — 12/12 KGQuery tests in lead dataset |

---

## Phase 4: Objects & Types Endpoints

| # | Endpoint | Method | Route | Status | Notes |
|---|----------|--------|-------|--------|-------|
| 4.1 | List objects | GET | `/api/graphs/objects` | ✅ Done | Pagination, vitaltype_filter |
| 4.2 | Get object by URI | GET | `/api/graphs/objects?uri=...` | ✅ Done | |
| 4.3 | Create objects | POST | `/api/graphs/objects` | ✅ Done | VitalSigns KGEntity objects |
| 4.4 | Update objects | PUT | `/api/graphs/objects` | ✅ Done | Update + verify round-trip |
| 4.5 | Delete objects | DELETE | `/api/graphs/objects` | ✅ Done | Single + batch delete |
| 4.6 | List KG types | GET | `/api/graphs/kgtypes` | ✅ Done | Pagination, vitaltype_filter |
| 4.7 | Get KG type by URI | GET | `/api/graphs/kgtypes?uri=...` | ✅ Done | |
| 4.8 | Create KG types | POST | `/api/graphs/kgtypes` | ✅ Done | KGEntityType, KGFrameType, etc. |
| 4.9 | Update KG types | PUT | `/api/graphs/kgtypes` | ✅ Done | Update + verify round-trip |
| 4.10 | Delete KG types | DELETE | `/api/graphs/kgtypes` | ✅ Done | Single + batch delete |

**All 10/10 objects tests pass** (`test_sparql_sql_objects.py`):
- Create 3 KGEntity objects, list, get by URI, update + verify, delete single, verify deleted, list remaining, batch delete, final verify 0

**All 10/10 KGTypes tests pass** (`test_sparql_sql_kgtypes.py`):
- Create 3 KGTypes (KGEntityType, KGFrameType, KGRelationType), list, get by URI, update + verify, delete single, verify deleted, list remaining, batch delete, final verify 0

**Key fix**: `kgtypes_endpoint.py` batch delete — split comma-separated URIs within list elements (FastAPI parses `?uri_list=a,b` as `['a,b']`)

### Key Additions
- **`db_ops` adapter** (`_SparqlSQLDbOpsAdapter`) — mirrors `FusekiPostgreSQLDbOps` API for `ObjectsImpl` write operations
- **`core` adapter** (`_SparqlSQLCoreAdapter`) — provides `create_transaction()` for `execute_with_transaction` in `impl_utils.py`
- **`_SparqlSQLTransaction`** — async context manager matching `FusekiPostgreSQLTransaction` interface

---

## Phase 5: Files Endpoint

| # | Endpoint | Method | Route | Status | Notes |
|---|----------|--------|-------|--------|-------|
| 5.1 | List files | GET | `/api/files` | ✅ Done | Pagination |
| 5.2 | Get file by URI | GET | `/api/files?uri=...` | ✅ Done | |
| 5.3 | Create files | POST | `/api/files` | ✅ Done | FileNode metadata |
| 5.4 | Update files | PUT | `/api/files` | ✅ Done | Update + verify |
| 5.5 | Delete files | DELETE | `/api/files` | ✅ Done | Single + batch |
| 5.6 | Streaming upload | POST | `/api/files/stream/upload` | ✅ Done | AsyncFilePathGenerator + aiohttp |
| 5.7 | Streaming download (bytes) | GET | `/api/files/download` | ✅ Done | To memory |
| 5.8 | Streaming download (file) | GET | `/api/files/download` | ✅ Done | To disk |

**All 13/13 files tests pass** (`test_sparql_sql_files.py`):
- Create 3 FileNodes, list, get, update + verify, streaming upload (real PNG via `AsyncFilePathGenerator`),
  streaming download to bytes, streaming download to file, delete single, verify deleted, list remaining,
  batch delete, final verify 0
- Uses real test files: `test_files/2502.16143v1.pdf`, `test_files/vampire_queen_baby.png`
- Downloads to `test_files_download/`

**Key fix**: `upload_file_stream` (httpx sync wrapper) broken — must use `upload_file_stream_async` with
`AsyncFilePathGenerator` (aiohttp path)

## Phase 5B: Data Import/Export (Future)

| # | Endpoint | Method | Route | Status | Notes |
|---|----------|--------|-------|--------|-------|
| 5B.1 | Import data | POST | `/api/data/import` | ❌ TODO | N-Triples/N-Quads upload |
| 5B.2 | Export data | GET | `/api/data/export` | ❌ TODO | |

---

## Phase 6: SPARQL Advanced Operations

| # | Endpoint | Method | Route | Status | Notes |
|---|----------|--------|-------|--------|-------|
| 6.1 | SPARQL INSERT | POST | `/api/graphs/sparql/{space}/insert` | ❌ TODO | |
| 6.2 | SPARQL DELETE | POST | `/api/graphs/sparql/{space}/delete` | ❌ TODO | |
| 6.3 | SPARQL UPDATE | POST | `/api/graphs/sparql/{space}/update` | ❌ TODO | |
| 6.4 | Graph CREATE | POST | `/api/graphs/sparql/{space}/graph` | ❌ TODO | |
| 6.5 | Graph DROP | DELETE | `/api/graphs/sparql/{space}/graph/{uri}` | ❌ TODO | |
| 6.6 | Graph CLEAR | POST | `/api/graphs/sparql/{space}/graph` | ❌ TODO | operation=CLEAR |

---

## kg_impl Compatibility Analysis (Completed)

### Architecture
Both adapters exist in `kg_backend_utils.py`:
- `FusekiPostgreSQLBackendAdapter` (line 89) — fuseki_postgresql backend
- `SparqlSQLBackendAdapter` (line 670) — sparql_sql backend
- `create_backend_adapter()` factory (line 903) — routes by backend type

### ✅ GRAPH Clause: Already Supported
`collect.py:277` handles `OpGraph` → `context_uuid = (subquery)`. All KG queries use `GRAPH <uri> { ... }`.

### ✅ Leaky Abstraction: Fixed
`SparqlSQLSpaceImpl` now has `db_objects` (`SparqlSQLDbObjects`), `db_ops` (`_SparqlSQLDbOpsAdapter`), and `core` (`_SparqlSQLCoreAdapter`), matching the fuseki_postgresql interface.

### ⚠️ Type Annotations (Cosmetic)
14 files import `FusekiPostgreSQLBackendAdapter` for type hints instead of `KGBackendInterface`.
Not breaking at runtime (duck typing), but should be cleaned up.

### ✅ Method Compatibility: Clean
All kg_impl method calls on the adapter exist on both adapters:
`execute_sparql_query`, `execute_sparql_update`, `update_quads`, `store_objects`,
`get_entity`, `get_entity_graph`, `object_exists`, `delete_object`.

### Conclusion: No Parallel Implementation Needed
Changes required:
1. Fix 1 line in `kgframe_graph_impl.py` (leaky abstraction)
2. Optional: clean up 14 type annotations
3. End-to-end test with GRAPH clause queries

---

## Remaining Implementation Gaps

1. **SPARQL UPDATE pipeline** — `execute_sparql_update()` is implemented but relies on the V2 generator handling UPDATE algebra. KG create/update/delete operations need INSERT DATA, DELETE WHERE, etc. to work.

2. ~~**VitalSigns round-trip**~~ — ✅ Verified. 60/60 lead CRUD tests + 21/21 dataset tests confirm store → retrieve → VitalSigns round-trip works correctly with real lead data.

3. **Materialized edge view** — `ensure_mv.py` handles `edge_mv` refresh. KG frame traversal queries may depend on this. Verify it's populated after data load.

4. ~~**Triples endpoint adapter wiring**~~ — ✅ Fixed. `SparqlSQLSpaceImpl` now has `query_quads()`, `.graphs`, `.db_ops`, `.core` adapters.

---

## Test Script Location

Test scripts for sparql_sql backend:
```
vitalgraph_client_test/
  test_sparql_sql_crud.py                   # Main orchestrator: Spaces/Graphs/Triples/Objects/KGTypes/Files (60/60 ✅)
  test_sparql_sql_objects.py                # Standalone: Objects CRUD (10/10 ✅)
  test_sparql_sql_kgtypes.py                # Standalone: KGTypes CRUD (10/10 ✅)
  test_sparql_sql_files.py                  # Standalone: Files CRUD + Streaming (13/13 ✅)
  sparql_sql/case_spaces_crud.py            # Modular: Spaces test case (7 tests)
  sparql_sql/case_graphs_crud.py            # Modular: Graphs test case (9 tests)
  sparql_sql/case_triples_crud.py           # Modular: Triples test case (11 tests)
  sparql_sql/case_objects_crud.py           # Modular: Objects test case (10 tests)
  sparql_sql/case_kgtypes_crud.py           # Modular: KGTypes test case (10 tests)
  sparql_sql/case_files_crud.py             # Modular: Files + Streaming test case (13 tests)
  --- Phase 3 (Complete) ---
  test_sparql_sql_kgentities.py             # Phase 3 Step 1: KGEntities + Frames CRUD (18/18 ✅)
  test_sparql_sql_lead_crud.py              # Phase 3 Step 2: Lead entity CRUD, 3 leads (60/60 ✅)
  test_sparql_sql_lead_dataset.py           # Phase 3 Step 3: 100-lead bulk load + KGQuery (21/21 ✅)
  sparql_sql/case_kgentities_crud.py        # Modular: KGEntity CRUD (10/10 ✅)
  sparql_sql/case_entity_frames_crud.py     # Modular: Entity frame operations (8/8 ✅)
  --- Phase 7 Profiling ---
  test_sparql_sql_single_lead.py            # Single lead insert via REST API (timing)
  ../vitalgraph_sparql_sql/scripts/profile_lead_insert.py  # Direct DB insert profiling (--raw / VitalSigns path)
```

## Execution Order

### ✅ Completed
1. **Phase 1** — Foundation endpoints (login, spaces, graphs) — 25/25 ✅
2. **Phase 2** — Triples CRUD — 11/11 ✅
3. **Phase 4** — Objects CRUD — 10/10 ✅
4. **Phase 4** — KGTypes CRUD — 10/10 ✅
5. **Phase 5** — Files CRUD + Streaming — 13/13 ✅
6. **Phase 3 Step 1** — KGEntities + Frames CRUD — 18/18 ✅
7. **Phase 3 Step 2** — Lead Entity CRUD (3 leads) — 60/60 ✅
8. **Phase 3 Step 3** — Lead Dataset (100 leads, 192K triples, KGQuery) — 21/21 ✅

**Total: 169/169 tests passing** (all re-verified after insert optimization)

### ✅ Phase 7 Insert Optimization (Completed)
9. **Phase 7.2** — Batched SQL inserts (`to_triples()` + `executemany`) — 6.8s → 0.42s per entity (16×) ✅
10. **Phase 7.2** — Batched existence checks (direct SQL) — 0.64s → 0.04s (15×) ✅
11. **Lead CRUD regression** — 60/60 passed, 18.5s total ✅
12. **Lead Dataset regression** — 21/21 passed, 100 leads in 115s ✅

### ✅ Phase 7 Delete/Update Optimization (Completed)
13. **Phase 7.2** — Bulk entity graph delete (`delete_entity_graph_bulk`) — 2.0s → 0.008s (200×) ✅
14. **Phase 7.2** — Batched quad removal (`remove_rdf_quads_batch_bulk` + `executemany`) ✅
15. **Phase 7.2** — `update_quads` uses bulk remove + bulk insert in single txn ✅
16. **Lead CRUD regression** — 60/60 passed, 11.8s total ✅
17. **Test fix** — Added 5 missing slot types + KGDateTimeSlot string handling ✅

### 🔜 Next: Phase 3F-3G (KGRelations + KGQueries)

#### Step 1: KGEntities CRUD (`test_sparql_sql_kgentities.py`)
Basic entity CRUD without lead data dependency. Uses programmatically created KGEntity + KGFrame objects.

| Test | Description |
|------|-------------|
| Create KGEntities | Create 3 entities via `client.kgentities.create_kgentities()` |
| List KGEntities | Paginated list, verify count |
| Get KGEntity by URI | Single entity retrieval |
| Update KGEntity | Update entity name, verify round-trip |
| Delete KGEntity | Single delete + verify |
| Batch Delete | Delete remaining entities |
| Create Entity Frames | Add frames to an entity via `client.kgentities.create_entity_frames()` |
| Get Entity Frames | List frames for entity, verify hierarchy |
| Update Entity Frames | Modify a slot value, verify round-trip |
| Delete Entity Frames | Delete a frame, verify removal |

Runner: `test_sparql_sql_kgentities.py` (standalone, dedicated space)
Cases: `sparql_sql/case_kgentities_crud.py`, `sparql_sql/case_entity_frames_crud.py`
Orchestrator: Wire into `test_sparql_sql_crud.py` as Step 7

#### Step 2: Lead Entity CRUD (`test_sparql_sql_lead_crud.py`)
Load real lead .nt files (3 leads), test full entity lifecycle. Mirrors `test_lead_entity_graph.py`.

| Test | Description |
|------|-------------|
| Load lead .nt file | Parse N-Triples → VitalSigns → `create_kgentities()` |
| Verify entity graph | Check triple count, entity URI, object types |
| Query entity graph | SPARQL queries on entity data |
| Frame operations | List/get/update/delete frames on loaded lead |
| Delete entity graph | Delete entity + verify cleanup |

Runner: `test_sparql_sql_lead_crud.py` (standalone, processes 3 lead files sequentially)
Cases: `sparql_sql/case_lead_load.py`, `sparql_sql/case_lead_verify.py`, `sparql_sql/case_lead_frame_ops.py`
Data: `lead_test_data/lead_*.nt` (first 3 files)

#### Step 3: Lead Dataset Queries (`test_sparql_sql_lead_dataset.py`)
Bulk load 100 leads, run complex frame-based queries. Mirrors `test_lead_entity_graph_dataset.py`.

| Test | Description |
|------|-------------|
| Bulk load 100 leads | Load all `lead_test_data/lead_*.nt` files |
| List & paginate entities | Verify count=100, pagination works |
| Retrieve entity graphs | Sample 5 entities, verify frame structure |
| KGQuery: MQL leads | Frame query: `MQL=true` |
| KGQuery: State filter | Frame query: company state = "CA" |
| KGQuery: Rating filter | Frame query: MQL rating >= 65 |
| KGQuery: Multi-criteria | Combined frame/slot filters |
| KGQuery: Converted leads | Frame query: `isConverted=true` |

Runner: `test_sparql_sql_lead_dataset.py` (standalone, dedicated space, skip_load option)
Cases: `sparql_sql/case_lead_dataset_load.py`, `sparql_sql/case_lead_dataset_queries.py`, `sparql_sql/case_lead_dataset_retrieve.py`
Data: `lead_test_data/lead_*.nt` (up to 100 files)

### Future
9. **Phase 3F** — KGRelations (CRUD + query) 🔜
10. **Phase 3G** — KGQueries: relation query (frame query already works via lead dataset tests)
11. **Phase 5B** — Data Import/Export
12. **Phase 6** — SPARQL Advanced Operations
13. **Phase 7** — Remaining Performance Optimizations (§7.4-7.6)

---

## Phase 7: Performance Optimization

### 7.1 Entity Graph Insert Performance

**Before optimization**: Each entity graph insert took **7–8 seconds** (100 leads × ~1,928 triples each = 192,810 total triples loaded in 729s). This was ~260 triples/second throughput.

**After optimization**: Each entity graph insert takes **0.4–0.7 seconds** (100 leads loaded in 115s). This is ~1,676 triples/second throughput — a **6.3× overall improvement**.

**Old insert path** (before optimization):
```
GraphObject.to_rdf() → Turtle text (per object)
  → RDFLib Graph.parse(format='turtle') → (s, p, o) triples
    → add_rdf_quads_batch():
        for each of ~2,700 quads:
          _ensure_term(s) → INSERT INTO terms ON CONFLICT DO NOTHING
          _ensure_term(p) → INSERT INTO terms ON CONFLICT DO NOTHING
          _ensure_term(o) → INSERT INTO terms ON CONFLICT DO NOTHING
          _ensure_term(g) → INSERT INTO terms ON CONFLICT DO NOTHING
          INSERT INTO rdf_quad ON CONFLICT DO NOTHING
```

**New insert path** (after optimization):
```
GraphObject.to_triples() → RDFLib (s, p, o) tuples directly (no serialization)
  → add_rdf_quads_batch_bulk():
      1. Resolve unique datatype URIs (few queries)
      2. Classify all terms in Python (CPU-only, no I/O)
      3. executemany() → bulk INSERT terms ON CONFLICT DO NOTHING
      4. executemany() → bulk INSERT quads ON CONFLICT DO NOTHING
      All in one transaction
```

**Bottleneck analysis**:

| Stage | Cost | Notes |
|-------|------|-------|
| `GraphObject.to_rdf()` | Low | Turtle serialization, ~1ms per object |
| `RDFLib.parse()` | Low | Parse Turtle back to triples, ~1ms per object |
| **Sequential SQL statements** | **Very High** | ~1,900 quads × 5 statements = **~9,500 SQL round-trips per entity graph** |
| `_ensure_term()` per term | High | 4 UPSERT calls per quad — each is a separate `conn.execute()` |
| `INSERT INTO rdf_quad` per quad | Medium | 1 INSERT per quad with ON CONFLICT DO NOTHING |
| Index maintenance | Medium | B-tree + GIN indexes updated per INSERT statement |

**Profiling results** (same lead file, same 2,727 quads):

*Before optimization (sequential `add_rdf_quads_batch`):*

| Where | Time | Per-stmt | Notes |
|-------|------|----------|-------|
| Direct script (host→localhost PG) | 1.66s | 0.120ms | True localhost loopback |
| Docker server (container→host PG) | 5.64s | 0.408ms | ~13,800 sequential SQL calls |

**Root cause**: ~13,800 sequential `conn.execute()` calls per entity graph (4 `_ensure_term` + 1 INSERT per quad, plus 200 `_resolve_datatype_id` for typed literals).

**Server-side timing breakdown — BEFORE (6.8s total endpoint):**

| Stage | Time | % |
|-------|------|---|
| `quad_list_to_graphobjects` | 0.030s | 0.4% |
| `entity_exists_check` (1 entity, SPARQL) | 0.409s | 6.0% |
| `sub_object_exists_check` (396 URIs, SPARQL) | 0.104s | 1.5% |
| `to_rdf+parse` (397 objects → 2,727 quads) | 0.103s | 1.5% |
| **`add_rdf_quads_batch`** (2,727 quads) | **5.635s** | **82.5%** |
| Other (FastAPI, response serialization) | ~0.5s | 8% |

**Server-side timing breakdown — AFTER (0.42s total endpoint):**

| Stage | Time | % | Speedup |
|-------|------|---|--------|
| `quad_list_to_graphobjects` | 0.030s | 7% | — |
| `batch_exists_check` (397 URIs, direct SQL) | **0.043s** | 10% | **15×** |
| `to_triples` (397 objects → 2,727 quads) | **0.012s** | 3% | **9×** |
| **`add_rdf_quads_batch_bulk`** (2,727 quads) | **0.141s** | 34% | **40×** |
| Other (FastAPI, response serialization) | ~0.19s | 46% | — |

Bulk insert internal breakdown: dt_resolve=0.005s, classify=0.025s, terms_insert=0.065s (716 unique), quads_insert=0.075s (2,727).

### 7.2 Batched SQL Insert Path — ✅ IMPLEMENTED

Three optimizations implemented, all in production:

**Optimization 1: `to_triples()` instead of `to_rdf()` + reparse** (9× speedup)
- `GraphObject.to_triples()` returns RDFLib `(URIRef, URIRef, URIRef|Literal)` tuples directly
- Eliminates Turtle serialization → string → `RDFLib.parse()` round-trip
- File: `kg_backend_utils.py` — `SparqlSQLBackendAdapter.store_objects()`

**Optimization 2: `add_rdf_quads_batch_bulk()` with `executemany`** (40× speedup)
- Collects all unique terms from all quads in Python (CPU-only)
- Resolves datatype URIs in batch (few queries for unique datatypes)
- `conn.executemany()` for terms INSERT (716 unique terms in one call)
- `conn.executemany()` for quads INSERT (2,727 quads in one call)
- All in a single transaction (one WAL flush instead of ~13,800)
- File: `sparql_sql_space_impl.py` — `SparqlSQLSpaceImpl.add_rdf_quads_batch_bulk()`

**Optimization 3: Direct SQL existence check** (15× speedup)
- `check_subjects_exist()` — single SQL query with `ANY($1)` on term UUIDs
- Replaces two SPARQL queries (entity exists + sub-object exists) that went through full SPARQL→SQL pipeline
- File: `sparql_sql_space_impl.py` — `SparqlSQLSpaceImpl.check_subjects_exist()`
- File: `kgentity_create_impl.py` — `_handle_create_mode()` batched check

**Actual results**: Entity insert 6.8s → 0.42s (**16× speedup**). 100-lead bulk load 729s → 115s (**6.3× speedup**).

**Phase B (skip RDFLib entirely)** remains a future option:
```
GraphObject → direct property iteration
  → Generate (term_text, term_type, lang, datatype_id) tuples directly
  → Generate (s_uuid, p_uuid, o_uuid, g_uuid) tuples directly
  → COPY into terms + quads
```
This would skip `to_triples()` overhead (currently 0.012s — negligible) but could help at very large scale.

### 7.3 Prepared Statements for Known Query Patterns

Frame queries (list frames, get frame by URI, get slots for frame) follow a fixed SPARQL pattern that always compiles to the same SQL shape. Currently each query goes through:
```
SPARQL text → Jena Sidecar → SQL AST → SQL text → PostgreSQL parse+plan+execute
```

**Optimization options**:
- **Server-side prepared statements** (`PREPARE`): Pre-compile the SQL for common frame query shapes. The SPARQL→SQL output is deterministic for a given query template — only the bind parameters change.
- **SQL template cache**: Cache the compiled SQL keyed by (SPARQL template hash). On cache hit, skip the Jena Sidecar entirely and just substitute parameters.
- **Direct SQL functions**: For the most common patterns (list entity frames, get frame graph, get slots by frame URI), write optimized SQL directly rather than going through SPARQL at all. These patterns are known at development time and don't need the flexibility of SPARQL compilation.

The 12 KGQuery tests already average **62ms** per query, which is good. But for high-throughput production use, caching or prepared statements could cut this further.

### 7.4 Index Management Strategy

**Current state**: B-tree and GIN indexes exist on the `quads` and `terms` tables. These are updated synchronously on every INSERT/UPDATE/DELETE.

**Problem**: During bulk loads (100+ entity graphs), index maintenance dominates INSERT time. Each of the ~1,900 triples per entity triggers index updates.

**Strategy options**:

| Approach | When to Use | Trade-offs |
|----------|------------|------------|
| **Always on** (current) | Small inserts, interactive use | Slow bulk loads, always-fresh indexes |
| **Deferred indexes** | Major bulk uploads | Drop indexes → bulk insert → recreate indexes. Much faster bulk load, but queries fail during load |
| **Partial rebuild** | After each entity graph insert | `REINDEX` only affected index partitions. Middle ground |
| **Async index refresh** | Background process | Insert without indexes, schedule async REINDEX. Queries may be stale briefly |

**Recommendation**: For normal interactive use (single entity creates/updates), keep indexes always on — the overhead per individual operation is acceptable. For major bulk uploads (100+ entities), offer a **bulk load mode** that:
1. Drops secondary indexes (keep primary key)
2. Bulk inserts all data (via direct SQL path, §7.2)
3. Recreates indexes
4. Runs `ANALYZE` to refresh statistics

This is the standard PostgreSQL bulk load pattern and would reduce the 729s bulk load to potentially under 60s.

### 7.5 Statistics Building & Rebuilding

**Current state**: PostgreSQL `ANALYZE` is not explicitly called after data loads. The query planner relies on auto-analyze, which may not trigger immediately after large inserts.

**Impact**: Stale statistics → suboptimal query plans → slow queries after data changes.

**Recommendations — dynamic stats maintenance**:

Statistics must be kept fresh **as data changes**, not only after bulk loads. The per-space tables (`{space_id}_rdf_quad`, `{space_id}_term`) and any maintained tables (edge table, frame-entity table) are all affected.

| Trigger | Action | Scope |
|---------|--------|-------|
| **After bulk load** | `ANALYZE {space}_rdf_quad, {space}_term, {space}_edge, {space}_frame_entity` | All space tables |
| **After entity graph create/update/delete** | `ANALYZE {space}_rdf_quad` (if Δrows > threshold) | Modified table(s) |
| **After maintained table sync** | `ANALYZE {space}_edge` / `ANALYZE {space}_frame_entity` | Edge/frame tables |
| **Periodic (production)** | Tune `autovacuum_analyze_threshold` + `autovacuum_analyze_scale_factor` per table | All space tables |
| **On demand** | Admin endpoint / CLI `ANALYZE` command | User-triggered |

**Implementation approach — incremental ANALYZE**:
- Track a per-space row-change counter (incremented by `add_rdf_quads_batch_bulk`, `remove_rdf_quads_batch_bulk`, `update_quads`).
- When the counter crosses a configurable threshold (e.g. 1000 rows changed), run `ANALYZE` on the affected tables and reset the counter.
- This avoids running `ANALYZE` on every single-entity operation (expensive) while ensuring stats never drift far from reality.
- The maintained edge/frame-entity tables should be included in the same `ANALYZE` call since they change in lockstep with the quad table.

**Why this matters**: Without fresh statistics, PostgreSQL falls back to default row estimates, picks wrong join orders, and chooses nested loops where hash joins would be 10–100× faster. This was directly observed in the Phase 8 slow relation queries (R4, R8).

#### Co-Occurrence Stats Tables (`rdf_stats`, `rdf_pred_stats`)

In addition to PostgreSQL's own planner statistics (`ANALYZE`), the V2 pipeline maintains its own co-occurrence stats in `{space}_rdf_stats` and `{space}_rdf_pred_stats`, used by `_reorder_joins()` for selectivity-guided join ordering. These tables are currently **never populated** during REST API operations.

**Previous approach (flawed)**: Ignore co-occurrences with count < 2 to keep the table small. But if you never count from 1, the count never reaches 2 — so no stats ever appear.

**Correct approach — always write, threshold on read**:

- **Write path**: On every entity graph create/update/delete, increment counts for every `(predicate_uuid, object_uuid)` pair and every `predicate_uuid` in the affected quads. Use `INSERT ... ON CONFLICT DO UPDATE SET row_count = row_count + delta`. Counts grow organically: 1 → 2 → N.
- **Read path** (`_load_quad_stats` in `generator.py`): Only load entries with `row_count >= 2` (minimum threshold) AND `row_count <= 200000` (existing upper cap). This keeps the in-memory cache small by excluding rare noise entries while still providing selectivity signal.
- **On DELETE**: Decrement counts (floor at 0). Periodic cleanup removes zero-count rows.
- **Cache invalidation**: Clear `_stats_cache[space_id]` when the row-change counter triggers (same threshold as ANALYZE) so the next query reloads fresh stats.

### 7.6 Materialized Views → Maintained Tables

**Current state**: `edge_mv` materialized view exists for edge traversal queries. Materialized views require explicit `REFRESH` and are stale between refreshes.

**Problem**: After entity graph inserts/updates/deletes, the materialized view is stale until refreshed. Frame hierarchy queries may return incorrect results if the MV is not refreshed.

**Proposed alternative**: Replace the materialized view with an **actual table** maintained by triggers or application-level logic:

| Approach | Pros | Cons |
|----------|------|------|
| **Materialized view + REFRESH** | Simple DDL, correct on refresh | Stale between refreshes, REFRESH locks table, must coordinate timing |
| **Regular table + triggers** | Always current, no manual refresh | Trigger overhead on every INSERT/UPDATE/DELETE, more complex DDL |
| **Regular table + app-level sync** | Always current, no trigger overhead | Application must remember to update, risk of inconsistency |
| **Regular table + bulk rebuild** | Correct after rebuild, no per-row overhead | Stale between rebuilds (same as MV but with explicit control) |

**Recommendation**: Switch to a **regular table with application-level sync**:
- On entity graph create/update/delete, the application code that performs the quad operations also inserts/updates/deletes the corresponding rows in the edge table.
- This keeps the edge data always consistent without trigger overhead.
- For bulk loads, defer edge table updates to the end (same as deferred indexes).
- The edge table schema matches the MV schema, so query code doesn't need to change — just the DDL (`CREATE TABLE` instead of `CREATE MATERIALIZED VIEW`).

### 7.7 Summary: Optimization Priorities

| Priority | Optimization | Expected Impact | Status |
|----------|-------------|----------------|--------|
| **P1** | ~~Batch SQL inserts (`executemany`) for terms + quads (§7.2)~~ | ~~10–20× insert speedup~~ → **40× actual** | ✅ Done |
| **P1** | ~~`to_triples()` instead of `to_rdf()` + reparse (§7.2)~~ | ~~Eliminate serialization~~ → **9× actual** | ✅ Done |
| **P1** | ~~Direct SQL existence checks (§7.2)~~ | ~~Skip SPARQL pipeline~~ → **15× actual** | ✅ Done |
| **P1** | ~~Bulk entity graph delete (`delete_entity_graph_bulk`)~~ | ~~Skip SPARQL pipeline~~ → **200× actual** | ✅ Done |
| **P1** | ~~Batched quad removal + update (`remove_rdf_quads_batch_bulk`)~~ | Bulk delete + insert in single txn | ✅ Done |
| **P1** | Bulk load mode: drop secondary indexes → batch insert → recreate (§7.4) | Additional 2–3× on top of batching | 🔜 TODO |
| **P1** | Dynamic `ANALYZE` on data changes (§7.5) | Always-fresh stats → correct query plans | TODO |
| **P2** | Materialized view → maintained table (§7.6) | Always-fresh edge data | TODO |
| **P3** | Skip RDFLib: direct GraphObject → SQL (§7.2 Phase B) | Minimal gain (to_triples is 0.012s) | Low priority |
| **P3** | SQL template cache / prepared statements for frame queries (§7.3) | 2× query speedup | TODO |
| **P3** | Direct SQL for known frame query patterns (§7.3) | Eliminate sidecar for common queries | TODO |

---

## Phase 8: KGQueries + KGRelations Multi-Entity Testing

### 8.1 Test Infrastructure

Created dedicated test runners for multi-entity KGQuery scenarios (relation queries + frame queries with 10 organizations, 10 business events, 16 relations):

| Runner | Tests | Status |
|--------|-------|--------|
| `test_sparql_sql_kgqueries.py` | 35/35 | ✅ Pass |
| `test_sparql_sql_kgrelations.py` | TBD | 🔜 Pending |

Test data: 10 organizations (Technology, Finance, Healthcare, etc.) with company info frames (industry, city, employee count), 10 business events with detail frames, 6 products, 16 relations (MakesProduct, CompetitorOf, PartnerWith, Supplies).

### 8.2 Key Fixes Applied

1. **`kgrelations_endpoint.py` adapter** — was hardcoded to `FusekiPostgreSQLBackendAdapter`; fixed to use `create_backend_adapter()`.
2. **`query_mode` parameterization** — Fuseki backend uses `"direct"` (vg-direct:hasEntityFrame quads), sparql_sql uses `"edge"` (Edge_hasEntityKGFrame). All test cases now accept `query_mode` as a parameter; runners pass the correct mode.
3. **URI collision bug** — `create_business_event` in `client_test_data.py` generated non-unique URIs for child objects (frames, slots, edges). Multiple events of the same `event_type` overwrote each other. Fix: append a unique `uid` suffix to all child object URIs.
4. **Enhanced logging** — `kgquery_endpoint.py` now logs generated SPARQL (multiline), pretty-printed SQL, and execution timing (ms) for both relation and frame queries.

### 8.3 Performance Investigation: Slow Relation Queries

Relation queries R4 ("MakesProduct from Technology cos") and R8 ("MakesProduct from large Tech cos") were significantly slower than simpler queries despite returning only 2 results each. Investigation identified two root causes:

#### Root Cause 1: Edge MV Rewrite Not Matching (var_slots co-reference issue)

The `rewrite_edge_mv` module (`vitalgraph/db/sparql_sql/rewrite_edge_mv.py`) is designed to replace pairs of `hasEdgeSource` + `hasEdgeDestination` quad lookups with a single `edge_mv` table scan. It detects these pairs by looking for explicit co-reference constraints in `plan.tagged_constraints` matching the regex:

```
(\w+)\.subject_uuid\s*=\s*(\w+)\.subject_uuid
```

**The problem**: The v2 IR pipeline does not store co-references as explicit constraint strings. Instead, it uses `plan.var_slots` — a variable that appears in multiple quad positions:

```python
# v2 pipeline represents ?relation_edge (shared subject) as:
var_slots["relation_edge"].positions = [
    ("q2", "subject_uuid"),   # hasEdgeSource quad
    ("q3", "subject_uuid"),   # hasEdgeDestination quad
]
```

The emit phase reads `var_slots` and generates the SQL JOIN condition `q2.subject_uuid = q3.subject_uuid` at SQL generation time. No explicit constraint string is ever stored in `tagged_constraints`.

**Diagnostic evidence** (from logs):
```
rewrite_edge_mv: found src/dst quads but no co-reference pairs. src={'q2': 'c_3'}, dst={'q3': 'c_4'}
rewrite_edge_mv: potential var_slots co-ref via ?relation_edge: q2(src) + q3(dst) — NOT YET REWRITING
```

The rewrite correctly identifies `hasEdgeSource` (q2) and `hasEdgeDestination` (q3) quads, but cannot find the co-reference between them because it only looks in `tagged_constraints`.

**Required fix — var_slots-aware co-reference detection and rewrite**:

1. **Detect pairs via var_slots** — for each variable in `plan.var_slots`, check if it has `subject_uuid` positions in both a `src_quad` and a `dst_quad`. ✅ Detection works (tested and confirmed).

2. **Remove the two quad tables** (`q2`, `q3`) from `plan.tables`.

3. **Add one `edge_mv` table** (`mv0`) to `plan.tables`.

4. **Remap var_slots correctly** — this is the critical step:
   - The shared subject variable (`?relation_edge`): change from `[(q2, subject_uuid), (q3, subject_uuid)]` → `[(mv0, edge_uuid)]`
   - The source object variable (`?source_entity`): change from `[(q2, object_uuid), ...]` → `[(mv0, source_node_uuid), ...]`
   - The dest object variable (`?destination_entity`): change from `[(q3, object_uuid), ...]` → `[(mv0, dest_node_uuid), ...]`
   - Context variables: deduplicate to `[(mv0, context_uuid)]`

5. **Remove predicate constraints** for the removed quads (these are in `tagged_constraints`).

6. **Do NOT remove co-reference constraints** — they don't exist as strings. The emit phase handles them via var_slots automatically.

**Why the naive fix broke queries**: An initial attempt activated the rewrite after detecting pairs via var_slots, but the downstream rewrite logic (steps 2–6) was designed for the explicit-constraint model. It incorrectly remapped var_slot positions, causing the emit phase to generate broken JOINs. Result: 0/8 relation queries returned results. The fix was reverted.

**Impact**: Without the MV rewrite, each edge traversal requires 2 quad table lookups (hasEdgeSource + hasEdgeDestination) joined on subject_uuid. For complex relation queries with 3–4 edge traversals (relation edge + source frame edge + source slot edge + dest frame edge + dest slot edge), this means 6–10 quad table JOINs instead of 3–5 MV lookups.

#### Root Cause 2: Missing PostgreSQL Statistics on Dynamic Tables

The sparql_sql backend creates per-space tables dynamically (`{space_id}_rdf_quad`, `{space_id}_term`). When entities are inserted via the REST API (one-by-one), PostgreSQL's autovacuum/autoanalyze may not run before queries execute. Without statistics:

- PostgreSQL uses default row estimates (often wildly inaccurate)
- Join order selection is suboptimal
- Nested loops chosen where hash joins would be faster
- The MV itself (if it existed from a previous run) may contain stale data

The bulk import path (`postgresql_space_db_import.py`) already runs `ANALYZE` + `VACUUM ANALYZE` after data loading (lines 635–755). The per-entity REST API insertion path does not.

**This also affects the MV directly**: The edge MV is created via `ensure_edge_mv()` which checks `pg_matviews` and creates the MV if missing. But:
- The MV may persist from a **previous test run** (space tables dropped and recreated, but MV not dropped due to CASCADE not being used)
- If the MV was created during an earlier data insertion phase (with partial data), it is **never refreshed** — `REFRESH MATERIALIZED VIEW` is never called
- Even if refreshed, `ANALYZE` is never run on the MV itself, so PostgreSQL has no stats for MV scans

**Resolution**: Because data is dynamic (entities created/updated/deleted at any time), materialized views are inherently problematic — they require explicit `REFRESH` and `ANALYZE` after every data change. As outlined in §7.6, the planned approach is to **replace materialized views with maintained tables** that are updated synchronously by application-level logic during entity graph create/update/delete operations. This eliminates staleness entirely and ensures stats are always current (or at minimum, `ANALYZE` can be run on the maintained table after bulk operations).

### 8.4 Files Modified

| File | Change |
|------|--------|
| `vitalgraph/endpoint/kgrelations_endpoint.py` | Fixed to use `create_backend_adapter()` |
| `vitalgraph/endpoint/kgquery_endpoint.py` | Enhanced logging: SPARQL, pretty-printed SQL, timing |
| `vitalgraph/db/sparql_sql/sparql_sql_space_impl.py` | Added SQL to query results, pipeline timing metrics |
| `vitalgraph/db/sparql_sql/ensure_mv.py` | Added diagnostic logging for MV creation/existence checks |
| `vitalgraph/db/sparql_sql/rewrite_edge_mv.py` | Added diagnostic logging for pair detection; var_slots detection (disabled, needs full rewrite) |
| `vitalgraph_client_test/client_test_data.py` | Fixed URI collision in `create_business_event` |
| `vitalgraph_client_test/test_sparql_sql_kgqueries.py` | New test runner for multi-entity KGQueries |
| `vitalgraph_client_test/kgqueries/case_relation_queries.py` | Parameterized `query_mode` |
| `vitalgraph_client_test/kgqueries/case_frame_queries.py` | Parameterized `query_mode` |
| `vitalgraph_client_test/multi_kgentity/case_kgquery_frame_queries.py` | Parameterized `query_mode` |
| `vitalgraph_client_test/entity_graph_lead_dataset/case_kgquery_lead_queries.py` | Parameterized `query_mode`, tightened assertions |

---

## Key Differences from fuseki_postgresql Tests

- **No Fuseki** — all SPARQL goes through Jena sidecar → V2 SQL pipeline → PostgreSQL
- **No dual-write** — single source of truth (PostgreSQL only)
- **SPARQL compilation required** — every SPARQL query hits the Jena sidecar first
- **SQL-level optimization** — GIN trigram indexes, BGP reordering, OFFSET 0 fences
- **Server URL**: `http://localhost:8001` (same service, different backend config)
