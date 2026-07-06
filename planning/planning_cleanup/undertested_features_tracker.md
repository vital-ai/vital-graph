# Under-Tested Features Tracker

**Created:** 2026-07-04  
**Purpose:** Track features that are not tested, under-tested, or only discussed in planning
but not covered by backend API tests (`tests/api/`) or frontend E2E tests (`e2e/tests/`).

This document will be incrementally updated as planning docs are reviewed.

---

## Legend

| Status | Meaning |
|--------|---------|
| :red_circle: NOT TESTED | Feature is implemented but has no automated test coverage |
| :orange_circle: UNDER-TESTED | Feature has partial coverage — key paths are missing |
| :yellow_circle: PLANNED ONLY | Feature is discussed in planning docs — unclear if fully built |
| :white_circle: SMOKE ONLY | E2E test only verifies page loads, not functional behavior |

---

## 1. Backend API — Missing Integration Tests

### 1.1 Document Segmentation → Vector Search Pipeline
- **Status:** :orange_circle: UNDER-TESTED (E2E passing; API integration tests unconfirmed in CI)
- **Source:** `planning/planning_cleanup/document_segmentation_e2e_test_plan.md`, `planning/planning_kgdocument/kgdocument_plan.md`
- **Implementation:** `vitalgraph/document/` (segmenter, processor, worker, config manager, auto-hook)
- **What exists:**
  - `tests/api/test_kgdocuments_api.py` — 15 tests: CRUD (7) + segmentation config CRUD (5) + trigger/status (3)
  - `tests/api/test_document_segmentation_search_integration.py` — 9 tests: full pipeline (config → create doc → segment → vectorize → semantic search)
  - `tests/api/test_wikipedia_document_e2e.py` — multi-doc pipeline with real Wikipedia content + FTS
  - `e2e/tests/kgdocuments-crud.spec.ts` — E2E: upload → trigger segmentation → verify segments appear in list → semantic search → delete cleanup (**all passing as of 2026-07-05**)
- **What's broken/missing:**
  - Wikipedia test blocked by B-tree 8KB index limit on large `term_text` values (documents never stored)
  - API segmentation integration tests not confirmed passing in CI (requires live server + segmentation worker)
  - No unit test of `SegmentationWorker` job claim/processing logic in isolation
  - No test of `AutoSegmentationHook` firing automatically on document create (tests trigger manually)
- **Bugs fixed (2026-07-05):**
  - Race condition: parallel E2E `describe` blocks caused premature document deletion → wrapped in serial parent block
  - Segment list not rendering: SPARQL query used wrong edge pattern (direct predicate instead of `hasEdgeSource`/`hasEdgeDestination` 2-hop traversal) → fixed in `KGDocumentDetail.tsx`
  - Seed idempotency: `_seed_kgdocument` created duplicates on re-run → added existence check
  - WebSocket infinite loop: generic `Exception` handler in message loop didn't break on closed connection → added `break`

### 1.2 Large Batch Import → SPARQL Query (WordNet)
- **Status:** :red_circle: NOT TESTED
- **Source:** `planning/planning_cleanup/integration_workflow_tests_plan.md` §3.3
- **What's missing:** No test for bulk N-Triples import (7M triples) → SPARQL query → verify aux tables synced → export round-trip
- **Planned test:** `tests/api/test_wordnet_import_integration.py`

### 1.3 Background Jobs & Process Scheduler
- **Status:** :red_circle: NOT TESTED (functional behavior)
- **Source:** `planning/planning_cleanup/background_task_catalog.md`
- **Implementation:** `vitalgraph/process/` (maintenance_job, analytics_job, metrics_rollup_job, import_export_cleanup_job)
- **What exists:** `test_process_endpoint_api.py` tests the REST status endpoint (7 tests) but does NOT test actual job execution, completion, or side effects
- **Missing coverage:**
  - MaintenanceJob actually running ANALYZE/VACUUM
  - AnalyticsJob computing and storing space analytics
  - MetricsRollupJob aggregating minute→hourly data
  - ImportExportCleanupJob purging old jobs/files
  - ProcessScheduler distributed locking behavior
  - SegmentationWorker job claim and processing

### 1.4 BackfillServerPropertiesTask
- **Status:** :red_circle: NOT TESTED
- **Source:** `planning/planning_cleanup/background_task_catalog.md` §2.1
- **Implementation:** `vitalgraph/tasks/backfill_server_properties_task.py`, `vitalgraph/kg_impl/kg_server_properties.py`
- **What's missing:** No test verifies that entities created via raw import (bypassing endpoint) get their server-managed properties backfilled

### 1.5 Cross-Space KGType Re-Vectorization
- **Status:** :orange_circle: UNDER-TESTED
- **Source:** `planning/planning_cleanup/testing_plan_tier4.md` §KGTypes architecture
- **What exists:** `test_kgtypes_entity_integration.py` (5 tests) covers type_description→entity vector→search
- **What's missing:** No test for the cross-space re-sync trigger — updating a KGType in `sp_kg_types` should trigger re-vectorization in all referencing spaces

### 1.6 Auto-Sync (Index Auto-Population on Data Changes)
- **Status:** :orange_circle: UNDER-TESTED
- **Source:** `planning/planning_features/vitalgraph_components_and_features.md` §5
- **What exists:** Geo auto-sync tested in `test_geo_search_integration.py`
- **What's missing:** No test for vector auto-sync or FTS auto-sync on entity create/update (as opposed to explicit reindex/populate calls)

### 1.7 Entity Registry — Dedup Detection & Clustering
- **Status:** :orange_circle: UNDER-TESTED
- **Source:** `planning/planning_features/entity_registry.md`, `planning/planning_vector_geo/fuzzy_redis_to_postgresql_plan.md`
- **What exists:** `test_entity_registry_crud_api.py` (26 tests) covers entity/identifier/alias/category/location CRUD
- **What's missing:**
  - Near-duplicate detection (MinHash LSH + RapidFuzz matching)
  - Entity clustering
  - Weaviate integration sync
  - Dedup PostgreSQL backend (band/hash tables)

### 1.8 Concurrent Write + Search Consistency
- **Status:** :red_circle: NOT TESTED
- **Source:** `planning/planning_cleanup/integration_workflow_tests_plan.md` §4
- **What's missing:** No test exercises search consistency during concurrent entity writes

### 1.9 CLI Tools Functional Testing
- **Status:** :red_circle: NOT TESTED
- **Source:** `planning/planning_vital_cli/cli_implementation_plan.md`
- **Implementation:** `vitalgraph/cmd/`, `vitalgraph/admin_cmd/`, `bin/`
- **What's missing:** No automated tests for CLI commands (`vitalgraphadmin init/purge/delete`, `vitalgraphimport`, `vitalgraphexport`, `vitalgraphsearch`)

### 1.10 Token Revocation & Refresh
- **Status:** :orange_circle: UNDER-TESTED
- **Source:** `planning/planning_auth/authentication_modernization_plan.md`
- **What exists:** `test_api_keys_api.py` (5 tests) covers API key lifecycle
- **What's missing:**
  - JWT refresh token flow (token expires → refresh → new token)
  - Token revocation (revoke token → subsequent requests fail)
  - Token version cache invalidation
  - Role-based access enforcement (editor can't do admin ops, viewer is read-only)

### 1.11 Audit Logging
- **Status:** :orange_circle: UNDER-TESTED
- **Source:** `planning/planning_auth/auth_audit_logging_plan.md`
- **What exists:** `test_admin_api.py` (3 tests) includes basic audit log query + actor filter
- **What's missing:**
  - Audit log entries created for all mutation operations
  - Audit log time range filtering
  - Audit log event type filtering
  - Audit log completeness (all endpoint mutations generate entries)

### 1.12 Multi-Vector Search with Different Providers
- **Status:** :orange_circle: UNDER-TESTED
- **Source:** `planning/planning_multi_vector/multi_vector_query_plan.md`
- **What exists:** `test_multi_vector_search_api.py` (9 tests), `test_multi_vector_semantic_api.py` (4 tests)
- **What's missing:** No test combines vectors from different providers (e.g., OpenAI + VitalSigns local) in a single multi-vector fusion query

### 1.13 SPARQL Federation Across Spaces
- **Status:** :red_circle: NOT TESTED
- **Source:** `planning/planning_cleanup/integration_workflow_tests_plan.md` §4
- **What's missing:** No test for cross-space SERVICE clause (SPARQL federation)

### 1.14 Staged Bulk Import (UNLOGGED Tables)
- **Status:** :yellow_circle: PLANNED ONLY
- **Source:** `planning/planning_cleanup/import_staging_table_plan.md`
- **What's missing:** Unclear if `ImportMode.STAGED` path is fully implemented; no test exists

### 1.15 ~~KGTypes `GET /kgtypes/description` Route~~ — RESOLVED
- **Status:** ✅ TESTED (removed from gap list)
- **Source:** `planning/planning_cleanup/testing_plan_tier4.md` line 268
- **What exists:** Client method `kgtypes.get_type_description()`, 2 API tests in `test_kgtypes_api.py::TestKGTypeDescription`, plus 5 integration tests in `test_kgtypes_entity_integration.py` covering the full type_description→vector→search pipeline
- **Note:** Tier 4 plan doc was stale — route, client, and tests all implemented. Bug #013 (wrong column names) already fixed.

### 1.16 KGFrames Filter/Sort — API-Level Tests in `tests/api/`
- **Status:** :orange_circle: UNDER-TESTED
- **Source:** `planning/planning_kg_model/kgframes_filter_sort_parity_plan.md`
- **What exists:** `vitalgraph_client_test/test_kgframes_filter_sort.py` (10 tests) — manual script, NOT in `tests/api/`
- **What exists in CI path:** `tests/api/test_kgframes_api.py` (17 tests) covers basic CRUD but NOT the new filter/sort parameters (form_type, frame_type_uri, date ranges, property URI sort)
- **What's missing:** The new filter/sort capabilities need to be tested in the formal `tests/api/` suite (CI-runnable)

### 1.17 KGFormType Backfill Script
- **Status:** :yellow_circle: PLANNED ONLY
- **Source:** `planning/planning_kg_model/kg_model_plan.md` task 3.5
- **What's missing:** No backfill script exists to classify existing frames based on `kGGraphURI` presence; existing frames lack `hasKGFormType`

### 1.18 Entity `hasKGFormType` Auto-Set
- **Status:** :yellow_circle: PLANNED ONLY
- **Source:** `planning/planning_kg_model/kg_model_plan.md` task 3.2 (entity sub-item unchecked)
- **What's missing:** Entity create does NOT set `KGFormType_Entity` on the entity itself — all other paths (frames/aspects) are done

### 1.19 Graph Visualization — Backend Expand/Neighbors API
- **Status:** :orange_circle: UNDER-TESTED
- **Source:** `planning/planning_visualization/graph_visualization_plan.md`
- **What exists:** `test_kgqueries_api.py` (9 tests) covers relation/entity/frame queries
- **What's missing:** The visualization expand/collapse pattern (fetch N-hop neighbors by entity URI) is not directly tested as an API workflow

### 1.20 Space Analytics — Functional Verification
- **Status:** :orange_circle: UNDER-TESTED
- **Source:** `planning/planning_space_analytics/space_analytics_plan.md`
- **What exists:** `test_spaces.py` (13 tests) includes analytics get + refresh
- **What's missing:** No test verifies analytics computation actually produces correct KG-level stats (entity type counts, relation counts, temporal distributions)

### 1.21 Query Metrics Rollup Pipeline
- **Status:** :red_circle: NOT TESTED
- **Source:** `planning/planning_space_analytics/query_tracking_plan.md`
- **Implementation:** `vitalgraph/process/metrics_rollup_job.py`, `vitalgraph/metrics/`
- **What exists:** `test_metrics_api.py` (2 tests) — only verifies REST endpoint returns data
- **What's missing:** No test for minute→hourly aggregation logic, purge behavior, or slow query log rotation

---

## 2. Frontend E2E — Missing Functional Tests

The existing E2E tests (`e2e/tests/`) cover 25 spec files with 191 test cases (all passing as of 2026-07-05).
Many are shallow (verify page loads, not functional operations), but KG Documents, Indexes, and Mappings
now have full CRUD + functional coverage.

### 2.1 Semantic Search — Functional Execution
- **Status:** :white_circle: SMOKE ONLY
- **Source:** `e2e/tests/search-query.spec.ts`
- **What exists:** Page loads, can type in input (2 tests)
- **What's missing:** Actually executing a search and verifying results render

### 2.2 Data Import/Export — Full Workflow
- **Status:** :white_circle: SMOKE ONLY
- **Source:** `e2e/tests/data-import-export.spec.ts`
- **What exists:** Pages load (4 tests)
- **What's missing:** Create an import job, upload file, monitor progress, verify imported data appears

### 2.3 Graph Visualization — Functional Interaction
- **Status:** :white_circle: SMOKE ONLY
- **Source:** `e2e/tests/visualization-layout.spec.ts`
- **What exists:** Page loads (1 test)
- **What's missing:** Load data, verify nodes/edges render, test zoom/pan, node click → detail

### 2.4 ~~KG Documents Page — Segmentation Controls~~ — RESOLVED
- **Status:** ✅ TESTED
- **Source:** `planning/planning_ui/ui_testing_plan.md` Tier 3 item 15-16
- **What exists (as of 2026-07-05):**
  - `e2e/tests/kgdocuments-crud.spec.ts` — 10 tests covering: seeded doc visible, CRUD (create/edit/delete), upload markdown, trigger segmentation, verify segment list renders (Markdown Section badges), semantic search, delete cleanup
  - Serial execution wrapper prevents race conditions between CRUD and Segmentation describe blocks
  - Segment list SPARQL query fixed to use correct edge traversal pattern (UNION of 1-hop and 2-hop)

### 2.5 KG Relations Page — Full CRUD
- **Status:** :orange_circle: UNDER-TESTED
- **Source:** `planning/planning_ui/ui_testing_plan.md` Tier 3 item 14
- **What exists:** `kg-objects.spec.ts` may touch relations tab
- **What's missing:** Create relation, verify source/destination display, delete relation

### 2.6 Indexes & Mappings — Configuration Workflows
- **Status:** :orange_circle: UNDER-TESTED
- **Source:** `e2e/tests/indexes-mappings.spec.ts`, `planning/planning_ui/ui_testing_plan.md` Tier 6
- **What exists:** Basic index/mapping page loads and some CRUD
  - `e2e/tests/indexes-crud.spec.ts` — FTS and Vector index create/list/delete (all passing as of 2026-07-05)
  - `e2e/tests/search-mappings-crud.spec.ts` — Mapping create/toggle/delete (all passing as of 2026-07-05)
- **Bugs fixed (2026-07-05):**
  - Index cleanup used path params (`/api/fts-indexes/{name}`) instead of query params (`?index_name=`) → stale indexes caused "already exists" errors
  - Mapping delete assertion used non-exact `getByText('kgdocument')` which also matched `kgdocument_segment` → added `{ exact: true }`
- **What's missing:**
  - Create FTS index → configure languages
  - Create fuzzy mapping → configure thresholds
  - Geo config enable/disable workflow
  - Properties drag-and-drop on search mapping detail

### 2.7 Entity Registry UI — Functional Workflows
- **Status:** :orange_circle: UNDER-TESTED
- **Source:** `e2e/tests/entity-registry-crud.spec.ts`
- **What's missing:**
  - Identifier lookup (search by identifier value)
  - Alias management workflow
  - Category assignment
  - Location CRUD with map

### 2.8 SPARQL Editor — Query Execution & Results
- **Status:** :orange_circle: UNDER-TESTED
- **Source:** `e2e/tests/files-triples-sparql.spec.ts`
- **What's missing:** Enter SPARQL query → execute → verify results table renders with correct data

### 2.9 Audit Log UI
- **Status:** :red_circle: NOT TESTED
- **Source:** `planning/planning_ui/ui_testing_plan.md` Tier 9 item 45
- **What's missing:** No E2E test for audit log table, actor filter, time range, event type filter

### 2.10 Metrics Dashboard
- **Status:** :red_circle: NOT TESTED
- **Source:** `planning/planning_ui/ui_testing_plan.md` Tier 9
- **What's missing:** No E2E test for metrics dashboard page functionality

### 2.11 Agent Registry UI
- **Status:** :red_circle: NOT TESTED
- **Source:** `planning/planning_ui/ui_testing_plan.md` Tier 9 items 48-49
- **What exists:** `test_agent_registry_api.py` covers the API
- **What's missing:** No frontend E2E test for agent registry pages

### 2.12 Geo Shapes / Map Visualization
- **Status:** :red_circle: NOT TESTED
- **Source:** `planning/planning_ui/ui_testing_plan.md` Tier 6 item 31
- **What's missing:** No E2E test for geo shapes page or Leaflet map rendering

---

## 3. Performance Testing

### 3.1 Performance Regression Suite
- **Status:** :red_circle: NOT IMPLEMENTED
- **Source:** `planning/planning_cleanup/testing_plan_tier5.md`
- **What's missing:** Entire Tier 5 is "Not started" — no pytest-benchmark integration, no baseline, no regression alerting

---

## 4. TypeScript Client Library

### 4.1 TypeScript Client Integration Tests
- **Status:** :yellow_circle: PLANNED ONLY
- **Source:** `planning/planning_client/typescript_client_plan.md`
- **Implementation:** `vitalgraph-client-ts/tests/`
- **What exists:** Unit test stubs in `tests/unit/`
- **What's missing:** No integration tests running against a live server

---

## 5. CI/CD Gaps

### 5.1 Functional Tests in CI
- **Status:** :orange_circle: UNDER-TESTED
- **Source:** `planning/planning_cleanup/testing_plan.md` §Current State
- **What exists:** `.github/workflows/unit-tests.yml` (Tier 1 only), packaging smoke tests
- **What's missing:**
  - DAWG conformance tests not in CI
  - Integration tests (Tier 3) not in CI
  - API tests (Tier 4) not in CI
  - E2E tests (Playwright) not in CI
  - All require running PostgreSQL + server — needs Docker compose CI setup

---

## Review Progress

| Planning Directory | Reviewed | Date |
|-------------------|----------|------|
| `planning/planning_cleanup/` | ✅ | 2026-07-04 |
| `planning/planning_features/` | ✅ | 2026-07-04 |
| `planning/planning_auth/` | ✅ | 2026-07-04 |
| `planning/planning_kgdocument/` | ✅ | 2026-07-04 |
| `planning/planning_ui/` | ✅ | 2026-07-04 |
| `planning/planning_vector_geo/` | ✅ | 2026-07-04 |
| `planning/planning_multi_vector/` | ✅ | 2026-07-04 |
| `planning/planning_client/` | ✅ | 2026-07-04 |
| `planning/planning_sql/` | ✅ | 2026-07-04 |
| `planning/planning_import_export/` | ✅ | 2026-07-04 |
| `planning/planning_space_analytics/` | ✅ | 2026-07-04 |
| `planning/planning_vital_cli/` | ✅ | 2026-07-04 |
| `planning/planning_kg_model/` | ✅ | 2026-07-04 |
| `planning/planning_visualization/` | ✅ | 2026-07-04 |
| `planning/planning_fuseki/` | Skipped (out of scope) | — |

---

## Summary Statistics

| Category | Not Tested | Under-Tested | Smoke Only | Planned Only |
|----------|-----------|-------------|-----------|-------------|
| Backend API | 10 | 10 | — | 4 |
| Frontend E2E | 4 | 4 | 3 | — |
| Performance | 1 | — | — | — |
| Client Libraries | — | — | — | 1 |
| CI/CD | — | 1 | — | — |
| **Total** | **15** | **15** | **3** | **5** |

*Last updated: 2026-07-05 — 191/191 E2E tests passing, KG Documents + Indexes + Mappings fully covered.*
