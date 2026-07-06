# Testing Plan — Tier 4: API / End-to-End Tests (needs running server)

> Split from [testing_plan.md](testing_plan.md). See main doc for overall
> architecture, CI pipeline, fixtures, and migration strategy.

## Purpose

Verify the REST API contracts (request/response shapes, status
codes, pagination, error handling) via end-to-end tests against a live service.

**Key distinction**: These are end-to-end test scripts that run against a live
VitalGraph server and exercise the system through the Python client library.
They consolidate and improve the existing test runners and cases currently
scattered across `vitalgraph_client_test/`, `vitalgraph_mock_client_test/`,
`test_client_api/`, and `vitalgraph_service_tests/`.

## Approach

- Requires a running VitalGraph server (local, Docker, or CI service).
- Exercises the system via `VitalGraphClient` over real HTTP.
- Validates end-to-end behavior including auth, serialization, and round-trip
  data integrity.
- Test authentication, authorization, error responses.

## Coverage

- Every endpoint in `vitalgraph/endpoint/` gets at least:
  - Happy path (200/201)
  - Not found (404)
  - Bad request (400/422)
  - Auth required (401)
- Pagination correctness (total_count, offset, page_size).
- Large payload handling.

**Estimated count**: ~80–120 test cases.

---

## Implementation Progress

**Infrastructure** (`tests/api/`):
- `conftest.py` — session-scoped `VitalGraphClient` fixture with JWT login,
  module-scoped ephemeral test space and named graph fixtures.
  Server must be running — unreachable server causes test errors (no skip).
- Uses `VitalGraphClient` over real HTTP against Docker-launched (or local) server.
- All test spaces use `apitest_` prefix with UUID suffix.
- Patterns and assertions modeled after `test_scripts/vitalgraph_client_test/sparql_sql/` case classes.

**Test files** (`tests/api/`):

| File | Tests | What it validates |
|------|-------|-------------------|
| `test_health.py` | 3 | Raw `/health` endpoint, client connection + JWT auth, `get_server_info()` |
| `test_spaces.py` | 3 | Space list, create→get→list→delete lifecycle, get nonexistent space |
| `test_graphs_api.py` | 5 | Graph list, create, get_info, clear (after SPARQL insert), drop + verify |
| `test_sparql_api.py` | 3 | SELECT query, INSERT DATA + SELECT roundtrip, DELETE DATA + verify removal |
| `test_kgentities_api.py` | 6 | Create (3 entities), list, get by URI, update + verify, delete + verify, batch delete |
| `test_triples_api.py` | 8 | Add quads, list all, filter by subject/predicate/object, delete by subject, delete by predicate, verify empty |
| `test_entity_frames_api.py` | 5 | Create frames on entity, list frames, get frame by URI + verify slot, update slot value, delete frame |
| `test_kgtypes_api.py` | 19 | CRUD (6), get_by_uris (2), search keyword/fts/vector/hybrid (8), relationships (2), documentation (1) |
| `test_kgtypes_entity_integration.py` | 5 | Type description → entity vector → semantic search (type_description source_type) |
| `test_objects_api.py` | 6 | Create 3 objects, list, get by URI, update, delete, batch delete |
| `test_files_api.py` | 9 | Create FileNodes, list, get by URI, update name, delete + verify; upload PNG/PDF via client, download-to-bytes + download-to-file with exact size matching |
| `test_agent_registry_api.py` | 5 | List/create agent types, agent lifecycle (create→get→search→update→status→delete), endpoint CRUD, function CRUD |
| `test_entity_graph_cache_api.py` | 5 | Cache miss→populate, cache hit (hits counter), invalidate on update, invalidate on delete, cache stats endpoint |
| `test_entity_graph_ref_id_api.py` | 5 | Create entity+frame+slots, get by ref_id (no graph), get by ref_id (with graph — regression), get by URI (with graph), object count = 7 |
| `test_process_endpoint_api.py` | 7 | Scheduler status, list processes, type filter, status filter, pagination, trigger maintenance, get non-existent (404) |
| `test_registry_search_api.py` | 10 | Entity semantic/type/geo/combined/identifier search, location geo/semantic/address search, agent search + type filter |
| `test_kgrelations_api.py` | 5 | Create 3 entities + 2 relations, list, get by URI, delete + verify |
| `test_kgdocuments_api.py` | 7 | Create document + segments, list, get by URI, update, delete, batch delete |
| `test_kgqueries_api.py` | 9 | KG query: relation traversal (3 tests), entity query (3 tests), frame query (3 tests) |
| `test_import_export_api.py` | 11 | NQuads/JSON-LD/TriG/Turtle import + export lifecycle |
| `test_users_api.py` | 8 | List, get, filter, create, get created, update, delete, filter created |
| `test_api_keys_api.py` | 5 | Create, list, get, revoke, expiry check |
| `test_vector_search_api.py` | 25 | Vector index lifecycle (cosine + L2), batch upsert, get by subject/graph, multiple mappings (source_type/include_pred_name variants), disable/enable, multi-property, direct DB verification (registry, tables, HNSW idx, term table, row counts) |
| `test_text_search_api.py` | 28 | FTS index (multi-language create, update languages), search mappings (properties_type/include_pred_name variants, disable/enable), fuzzy mappings (custom shingle_k/num_perm/lsh_threshold/phonetic_bonus), direct DB verification (registry, data tables, tsvector columns, mapping counts, fuzzy band indexes) |
| `test_geo_search_api.py` | 16 | Geo config (get/enable/disable/re-enable/multi-predicate/delete), SPARQL-loaded geo entities, spatial queries (radius/large radius/graph filter/pagination), direct DB verification (config table, data table, spatial indexes, column schema, config state) |
| `test_metrics_api.py` | 2 | Realtime metrics, slow queries |
| `test_admin_api.py` | 3 | Resync auxiliary tables, audit log query + actor filter |
| `test_kgframes_api.py` | 17 | Frame CRUD (create, list, get, update, delete, batch delete), slot CRUD (create, get, update, delete), frames-with-slots retrieval, frame query (search, pagination, no-results), frame graph (with slots, nonexistent) |
| `test_entity_registry_crud_api.py` | 26 | Entity CRUD (create, get, list, update, delete + shared entity), identifiers (add, list, lookup, remove), aliases (add, list, remove), categories (create, list, assign, list by entity, list entities by category, remove), locations (create type, list types, create, list, update, remove), cleanup |
| `test_spaces.py` | 13 | Space lifecycle (list, create→get→delete, nonexistent), info (existing, statistics, nonexistent), analytics (get, refresh, structure), update (name, verify persistence), filter (by name, no results) |
| `test_ontology_api.py` | 5 | List classes (non-empty, known URI present), get properties (KGEntity fields, metadata populated, unknown class empty) |
| `test_mappings_api.py` | 23 | Vector/Fuzzy/Search mapping standalone CRUD (list, create, get, update, delete × 3 types) + property-level add/remove × 3 types |
| `test_integration_workflows.py` | 5 | Entity→vector reindex→verify, entity→FTS populate→text search, entity CRUD round-trip |
| `test_multi_vector_search_api.py` | 9 | Multi-vector weighted fusion (equal/A-heavy/B-heavy weights), pre-computed vectors, fusion strategies (weighted_sum/relative_score/ranked), min_score threshold, INTERSECT semantics, oversample factor |
| `test_multi_vector_semantic_api.py` | 4 | True multi-vector semantic search: orthogonal dimensions (profession × favorite food), 2×2 entity matrix, real ONNX embeddings, weight-driven disambiguation across independent axes |
| **Total** | **371** | **371 pass, 0 fail** |

## Assertion Quality Requirement

Every end-to-end test MUST validate actual response data, not just HTTP 200 / `is_success`.
Specifically:
- **Create** — assert `created_count` matches expected number of objects sent.
- **List** — assert returned count ≥ expected; verify known URIs appear in results.
- **Get** — assert returned object's URI, name, and key properties match what was created.
- **Update** — re-fetch and assert the mutated field contains the new value.
- **Delete** — re-fetch and assert the object is gone (empty result or 404).
- **Search** — assert result structure has expected fields; if data is deterministic, assert specific URIs/names appear.
- **File upload/download** — assert exact byte counts match source file size.
- **Cache** — assert counter values (hits, misses, invalidations) change by expected deltas.

Do NOT rely solely on `resp.is_success`, `hasattr(resp, ...)`, or HTTP status code checks.

## Notes

- Delete tests cast `entity.URI` to `str()` to work around VitalSigns `CombinedProperty`
  not being auto-coerced by Pydantic in the client's `DeleteResponse` builder.
- All Pyright warnings about "missing arguments" are false positives — flagged params
  have `Field(None, ...)` defaults in Pydantic models.
- File upload/download tests use real test files (`vampire_queen_baby.png`, `2502.16143v1.pdf`)
  from `test_files/`.  Required fix: `S3FileManager` was failing to initialize because the
  `Minio()` constructor rejects URLs with scheme prefixes — fixed by stripping `http://`/`https://`
  in `vitalgraph/storage/s3_file_manager.py`.
- Entity search `type_key` filter was causing 500 — SQL referenced `e.type_key` instead of
  `et.type_key` in 3 methods. Fixed in `entity_registry_search.py`. See `issues/005`.
- Users endpoint: missing `UserCreate` model meant client could never create users (password
  not passed). Added `UserCreate` model, updated server + client. See `issues/006`.
- Users endpoint: `update_user` passed raw dict to DB (expected kwargs), `delete_user`
  response missing `deleted_count`, `filter_users` called non-existent route. All fixed.
  See `issues/007`.
- Vector upsert: direct upsert API did not write URIs to term table, so
  `get_vectors` returned bare UUIDs instead of original URIs. Fixed. See `issues/008`.

---

## Remaining Endpoint Coverage

| Test File | Missing Routes | Status |
|-----------|---------------|--------|
| `test_spaces.py` | space info, analytics, update, filter (5 routes) | ✅ Done |
| `test_graphs_api.py` | graph export (1 route) | ✅ N/A — no separate route; covered by export job lifecycle |
| `test_sparql_api.py` | GET query, form-based insert/delete (3 routes) | ✅ GET done; form-based low-priority |
| `test_entity_registry_crud_api.py` | entity CRUD, location CRUD, identifier CRUD, category CRUD (~24 routes) | ✅ Done (26 tests) |
| `test_kgtypes_api.py` | `GET /kgtypes/description` | ✅ Done (bug fix #013) |

---

## P2 Index Testing Strategy

The P2 index endpoints (vector, FTS, fuzzy, geo) require **multi-step workflow
tests** rather than simple CRUD — the full lifecycle involves:

1. **Create index with different options** — each index type must be tested with
   multiple configuration variants (e.g. cosine vs L2 distance for vector;
   single-language vs multi-language for FTS; custom shingle_k/num_perm/lsh_threshold
   for fuzzy; single vs multiple lat/lon predicates for geo).
2. **Load data** — insert entities with indexable properties into the space
   (vectors via batch upsert; geo entities via SPARQL with lat/lon triples).
3. **Trigger indexing** — ensure the index processes the loaded data
   (populate/reindex endpoints or auto_sync for geo).
4. **Query via index** — execute search queries that exercise the index
   (get_vectors by subject/graph; spatial radius queries with various params).
5. **Verify DB state** — confirm via direct PostgreSQL queries:
   - Registry tables have expected rows with correct config values
   - Per-index data tables exist and have correct schema (tsvector columns, etc.)
   - Actual database indexes (HNSW, GIN, B-tree) were created
   - Loaded data is present in the data tables with correct row counts
   - Term table contains original URIs (regression: issue #008)
6. **Manage index** — update config (disable/enable, change separator, add/remove
   properties), verify changes take effect.
7. **Teardown** — delete index and test data

**Pytest approach**: Use **module-scoped fixtures** (`@pytest_asyncio.fixture(scope="module")`)
with `yield` to handle expensive setup/teardown once per test module.

---

## P2 Index Test Gap Analysis

| Requirement | Vector | FTS | Fuzzy | Geo |
|---|---|---|---|---|
| **Create index** | ✅ cosine + L2 | ✅ english + multi-lang | ✅ custom params | ✅ enable/disable/re-enable |
| **Create with different options** | ✅ cosine + L2 distance | ✅ english + [en,fr,de] | ✅ shingle_k=4, num_perm=128, lsh=0.5, phonetic=15 | ✅ multi-predicate (schema.org + wgs84) |
| **Load data** | ✅ batch upsert (3 vectors) | ✅ 5 entities → FTS populate (async) | ✅ 5 entities → fuzzy populate (async) | ✅ SPARQL insert 3 geo entities |
| **Query using index** | ✅ get_vectors by subject + graph | ✅ search_entity(q=...) text queries | ✅ fuzzy stats verified after populate | ✅ radius/large-radius/graph-filter/pagination |
| **Direct DB verification** | ✅ HNSW opclass (cosine+L2), vector(N) dims, row counts | ✅ GIN index def, tsvector column type, registry languages | ✅ config values in DB (shingle_k/num_perm/lsh/phonetic), phonetic band table | ✅ column types (double precision, uuid), index definitions, predicate storage |
| **Management (update/config)** | ✅ update separator, disable/enable | ✅ update languages, disable/enable | ✅ update threshold | ✅ enable/disable/re-enable, multi-predicate |
| **Reindex** | ✅ reindex + poll vectors | ✅ re-populate + poll stats | — | — |
| **Delete index** | ✅ (teardown) | ✅ (teardown) | ✅ (teardown) | ✅ (delete config) |
| **Multiple vectors/entities** | ✅ 3 vectors batch | ✅ 5 FTS entities | ✅ 5 fuzzy entities | ✅ 3 geo entities |

---

## PostgreSQL Index Verification Requirements

The direct DB verification tests must go beyond checking table existence. They must
inspect the **actual index definitions and status** in PostgreSQL to confirm that
the indexes created via the REST API match the requested parameters:

| Index Type | What to verify in `pg_indexes` / `pg_class` / `pg_am` |
|---|---|
| **Vector (HNSW)** | Index exists with `hnsw` access method; `opclass` matches distance metric (cosine → `vector_cosine_ops`, L2 → `vector_l2_ops`, inner product → `vector_ip_ops`); column type is `vector(N)` where N = requested dimensions |
| **FTS (GIN)** | GIN index exists on `tsv` column; tsvector config matches requested language(s); trigger function uses correct regconfig |
| **Fuzzy (B-tree/hash)** | Band lookup indexes exist; band table schema matches `shingle_k` (ngram size determines band width); phonetic band table created when `phonetic_bonus > 0` |
| **Geo (spatial)** | Indexes on `subject_uuid` and `context_uuid` exist; latitude/longitude columns have correct numeric type; config row reflects predicate URIs |

---

## KGTypes Endpoint — Comprehensive Test Requirements

> **Context docs**: `planning_visualization/centralized_kgtypes_space_plan.md`,
> `planning_vector_geo/search_ui_plan.md` §10.

The KGTypes system is more than a CRUD endpoint. It manages the type ontology
that underpins entity classification, vector search text enrichment, and
cross-space synchronization. Testing must cover the full API surface **and**
the downstream effects of types on entity queries.

### Architecture summary

- **System space `sp_kg_types`** — all KG types live in a single protected
  system space, not per-space. Graph: `urn:vitalgraph:sp_kg_types:kg_types`.
  Created at startup via `_ensure_system_spaces()`. Cannot be deleted.
- **Type-specific description properties** — NOT `hasKGraphDescription`.
  Each mapping type has its own description field:
  - KGEntity → `hasKGEntityTypeDescription`
  - KGFrame → `hasKGFrameTypeDescription`
  - KGDocument → `hasKGDocumentTypeDescription`
  - KGSlot → `hasKGSlotTypeDescription`
- **`source_type` enum on `search_mapping`** controls what text gets vectorized:
  - `type_description` — only the KGType description (cross-space lookup)
  - `properties` — subject's own property values
  - `properties_type` — properties + type description appended
  - `default` — all literals (legacy fallback)
- **Cross-space reads** — when vectorizing entities in space X, the populator
  reads type descriptions from `sp_kg_types` tables via `KGTypeDescriptionLookup`.
  Only triggered when `source_type` ∈ {`type_description`, `properties_type`}.
- **Cross-space re-sync** — when a KGType is created/updated in `sp_kg_types`,
  `kgtype_cross_space_sync.py` finds all spaces with affected mappings and
  schedules background re-vectorization of referencing subjects.
- **Junction table** — `{space}_search_mapping_index` links mappings to
  concrete vector/FTS indexes.
- **`kgtype_default` index** — auto-created in `sp_kg_types` via
  `kgtype_index_setup.py` (384 dims, cosine, `paraphrase-multilingual-MiniLM-L12-v2`).
- **KGType search** — 4 modes through SPARQL pipeline:
  `keyword` (CONTAINS), `fts` (vg:textSearch), `vector` (vg:vectorSimilarity),
  `hybrid` (vg:hybridSearch with alpha: 0.0=pure BM25, 1.0=pure vector).

### ⚠️ Test fixture caution — global data persistence

Unlike per-space test data, KG Types live in the **global `sp_kg_types`
system space** which is protected and never deleted between test runs.
Test types created in `sp_kg_types` survive teardown of ephemeral test
spaces. This means:

1. **Explicit cleanup required** — every fixture that creates types in
   `sp_kg_types` MUST delete them in its teardown (via
   `delete_kgtypes_batch`). Leftover types pollute subsequent runs.
2. **Unique naming** — use test-specific prefixes or UUIDs in type names
   (e.g. `PersonSearchTest`) to avoid collisions with production types
   or types from other test modules.
3. **Vector index side-effects** — created types auto-sync into the
   `kgtype_default` vector index. Deletion removes the type but the
   vector entry cleanup may be async. Tests should not assume instant
   disappearance from vector search after delete.
4. **Cross-space sync** — if entity integration tests trigger
   re-vectorization in other spaces, ensure those spaces still exist
   at the time of type cleanup (delete types before tearing down
   dependent spaces, or accept that sync will no-op on missing spaces).

### A. KGTypes Endpoint Route Coverage

The server exposes **15 routes**. As of 2025-06-30, `test_kgtypes_api.py` covers **14/15**.

| # | Route | Client Method | Coverage | Test Class |
|---|-------|--------------|----------|------------|
| 1 | `GET /kgtypes/description` | `(no client method yet)` | ❌ | — |
| 2 | `GET /kgtypes` (list) | `list_kgtypes()` | ✅ | `TestKGTypesCrud` |
| 3 | `GET /kgtypes?uri=` | `get_kgtype()` | ✅ | `TestKGTypesCrud` |
| 4 | `GET /kgtypes?uri_list=` | `get_kgtypes_by_uris()` | ✅ | `TestKGTypesGetByUris` |
| 5 | `POST /kgtypes` | `create_kgtypes()` | ✅ | `TestKGTypesCrud` |
| 6 | `PUT /kgtypes` | `update_kgtypes()` | ✅ | `TestKGTypesCrud` |
| 7 | `DELETE /kgtypes?uri=` | `delete_kgtype()` | ✅ | `TestKGTypesCrud` |
| 8 | `DELETE /kgtypes?uri_list=` | `delete_kgtypes_batch()` | ✅ | `TestKGTypesCrud` |
| 9 | `GET /kgtypes/relationships` | `get_type_relationships()` | ✅ | `TestKGTypeRelationships` |
| 10 | `POST /kgtypes/relationships` | `create_type_relationship()` | ✅ | `TestKGTypeRelationships` |
| 11 | `DELETE /kgtypes/relationships` | `delete_type_relationship()` | ✅ | `TestKGTypeRelationships` |
| 12 | `GET /kgtypes/documentation` | `get_type_documentation()` | ✅ | `TestKGTypeDocumentation` |
| 13 | `PUT /kgtypes/documentation` | `update_type_documentation()` | ✅ | `TestKGTypeDocumentation` |
| 14 | `DELETE /kgtypes/documentation` | `delete_type_documentation()` | ✅ | `TestKGTypeDocumentation` |
| 15 | `GET /kgtypes/search` | `search_types()` | ✅ | `TestKGTypeSearch` |

**Remaining gap**: Route 1 (`GET /kgtypes/description`) has no client method.

### B. KGTypes Search — Internal Vector Index Testing

**✅ IMPLEMENTED** — `TestKGTypeSearch` in `test_kgtypes_api.py` (8 tests, all passing).
Client fix: added `alpha` parameter to `search_types()` in `kgtypes_endpoint.py`.

### C. KGTypes in Entity Query Scenarios

**✅ IMPLEMENTED** — `TestKGTypeEntityIntegration` in `test_kgtypes_entity_integration.py`
(5 tests, all passing). Uses `source_type='type_description'` mapping, reindex,
and KGQuery vector search with `search_text`.

### D. KGTypes Relationships Testing

**✅ IMPLEMENTED** — `TestKGTypeRelationships` in `test_kgtypes_api.py` (2 tests, passing).

### E. KGTypes Documentation Testing

**✅ IMPLEMENTED** — `TestKGTypeDocumentation` in `test_kgtypes_api.py` (1 test, passing).

### F. KGTypes Description Lookup + Cache

The `KGTypeDescriptionLookup` class (in `vitalgraph/vectorization/kgtype_description_lookup.py`)
caches type descriptions with a 10-min TTL LRU cache. Tests should verify:

1. Description retrieved correctly for a known type URI
2. Cache invalidation after type update
3. Batch lookup returns correct descriptions for multiple types
4. Correct description property used per mapping_type
5. Missing type URI returns None (no crash)

**Status**: ❌ Future work.

### G. Test File Organization

| Test File | Classes | Tests | Status |
|-----------|---------|-------|--------|
| `test_kgtypes_api.py` | `TestKGTypesCrud`, `TestKGTypesGetByUris`, `TestKGTypeSearch`, `TestKGTypeRelationships`, `TestKGTypeDocumentation` | 19 | ✅ All passing |
| `test_kgtypes_entity_integration.py` | `TestKGTypeEntityIntegration` | 5 | ✅ All passing |

**Total: 24 tests covering 14/15 routes + entity integration.**

### H. Implementation Status

| Priority | Item | Status |
|----------|------|--------|
| P1 | Search modes (#15): keyword/fts/vector/hybrid | ✅ Done |
| P1 | get_kgtypes_by_uris (#4) | ✅ Done |
| P2 | Relationships (#9-11) | ✅ Done |
| P2 | Documentation (#12-14) | ✅ Done |
| P2 | Entity integration (type_description → vector → search) | ✅ Done |
| P2 | Type description endpoint (#1) | ❌ No client method |
| — | Cross-space sync after type update (§C.8-9) | ❌ Future |
| — | Description lookup cache invalidation (§F) | ❌ Future |

### I. Cross-References

- `planning_visualization/centralized_kgtypes_space_plan.md` — system space
  architecture, `source_type` enum, cross-space lookup, implementation status
- `planning_vector_geo/search_ui_plan.md` §10 — KGType search UI, 4 search
  modes, SPARQL pipeline, hybrid alpha
- `vitalgraph/vectorization/kgtype_description_lookup.py` — cross-space lookup
- `vitalgraph/vectorization/kgtype_cross_space_sync.py` — re-sync on type update
- `vitalgraph/vectorization/search_text_builder.py` — `source_type` handling
- `vitalgraph/kg_impl/kgtype_index_setup.py` — `kgtype_default` vector+FTS+mapping setup
- `vitalgraph/constants.py` — `SP_KG_TYPES`, `TYPE_URI_PROPERTIES`, `TYPE_DESCRIPTION_PROPERTIES`

---

## Next Priority — Uncovered Endpoints

### 1. Entity Registry CRUD (~25 routes) — `entity_registry_endpoint.py`

> **✅ IMPLEMENTED** — `test_entity_registry_crud_api.py` has 26 tests covering
> entity CRUD, identifiers, aliases, categories, and locations.
> All 26 tests pass.

> **⚠️ Global data caution**: The entity and agent registries are **global** —
> they are not scoped to a space that can be cleanly deleted. Tests must
> explicitly create entries with unique names/prefixes and tear them down in
> fixture finalizers. Leftover data from failed runs will persist. Use a
> naming convention (e.g. `regtest_<uuid>`) and add cleanup logic that
> removes all matching entries at both setup and teardown.

**Prefix**: `/api/registry`

| Route | Method | Purpose |
|-------|--------|---------|
| `/entities` | POST | Create entity |
| `/entities` | GET | List entities (query, type_key, page, page_size) |
| `/entities/get` | GET | Get entity by ID |
| `/entities/update` | PUT | Update entity |
| `/entities/delete` | DELETE | Delete entity |
| `/identifiers/add` | POST | Add identifier to entity |
| `/identifiers/list` | GET | List identifiers for entity |
| `/identifiers/remove` | DELETE | Remove identifier |
| `/identifiers/lookup` | GET | Lookup entity by namespace+value |
| `/aliases/add` | POST | Add alias |
| `/aliases/list` | GET | List aliases |
| `/aliases/remove` | DELETE | Remove alias |
| `/categories` | GET | List all categories |
| `/categories` | POST | Create category |
| `/categories/entity` | GET | List categories for entity |
| `/categories/assign` | POST | Assign category to entity |
| `/categories/remove` | DELETE | Remove category from entity |
| `/categories/entities` | GET | List entities by category |
| `/location/types` | GET | List location types |
| `/location/types` | POST | Create location type |
| `/locations/add` | POST | Create location for entity |
| `/locations/list` | GET | List locations for entity |
| `/locations/update` | PUT | Update location |
| `/locations/remove` | DELETE | Remove location |

**Test file**: `test_entity_registry_crud_api.py`

**Test classes**:
- `TestEntityCrud` — create, get, list, update, delete, not-found
- `TestIdentifiers` — add, list, lookup by namespace+value, remove, duplicate handling
- `TestAliases` — add, list, remove
- `TestCategories` — create category, assign to entity, list by entity, list entities by category, remove
- `TestLocations` — create location type, add location, list, update, remove

**Estimated**: ~30–40 tests

---

### 1b. Agent Registry Extended (~17 routes) — `agent_endpoint.py`

> **✅ FULLY COVERED** — `test_agent_registry_api.py` has 5 tests that exercise
> all 15 implemented routes via lifecycle tests (`test_agent_lifecycle`,
> `test_endpoint_lifecycle`, `test_function_lifecycle`). The endpoint update/delete
> and function get/update/delete were already tested within those lifecycle tests.
>
> The remaining 2 routes (`/agent/function/discover` and `/agent/changelog`) have
> **no server or client implementation** — they are planned features, not testable.

| Route | Method | Purpose | Tested? |
|-------|--------|---------|---------|
| `/agent/types` | GET | List agent types | ✅ |
| `/agent/types` | POST | Create agent type | ✅ |
| `/agent` | GET | List agents / get by ID / by URI | ✅ |
| `/agent` | POST | Create agent | ✅ |
| `/agent` | PUT | Update agent | ✅ |
| `/agent` | DELETE | Delete agent | ✅ |
| `/agent/status` | PUT | Change agent status | ✅ |
| `/agent/endpoints` | GET | List endpoints for agent | ✅ |
| `/agent/endpoints` | POST | Create endpoint | ✅ |
| `/agent/endpoints` | PUT | Update endpoint | ✅ |
| `/agent/endpoints` | DELETE | Delete endpoint | ✅ |
| `/agent/functions` | GET | List functions for agent | ✅ |
| `/agent/functions` | POST | Create function | ✅ |
| `/agent/function` | GET | Get function by ID | ✅ |
| `/agent/functions` | PUT | Update function | ✅ |
| `/agent/functions` | DELETE | Delete function | ✅ |
| `/agent/function/discover` | GET | Discover agents by function URI | ⬜ Not implemented |
| `/agent/changelog` | GET | Get agent change log | ⬜ Not implemented |

---

### 2. Import/Export Job API (15 routes) — `import_endpoint.py` + `export_endpoint.py`

> **✅ IMPLEMENTED** — `test_import_export_api.py` now covers the full job
> lifecycle including upload, execute, poll, download, and error cases.

**Prefix**: `/api/data`

| Route | Method | Purpose | Tested? |
|-------|--------|---------|---------|
| `/import` | POST | Create import job | ✅ |
| `/import` | GET | List import jobs | ✅ |
| `/import/job` | GET | Get import job by ID | ✅ |
| `/import` | DELETE | Delete import job | ✅ |
| `/import/upload` | POST | Upload file for import job | ✅ |
| `/import/execute` | POST | Start import execution | ✅ |
| `/import/status` | GET | Get import progress | ✅ |
| `/import/log` | GET | Get import log | ✅ |
| `/export` | POST | Create export job | ✅ |
| `/export` | GET | List export jobs | ✅ |
| `/export/job` | GET | Get export job by ID | ✅ |
| `/export` | DELETE | Delete/cancel export job | ✅ |
| `/export/execute` | POST | Start export execution | ✅ |
| `/export/status` | GET | Get export progress | ✅ |
| `/export/download` | GET | Download export file | ✅ |

**Test file**: `test_import_export_api.py`

**Test classes** (4 classes, ~22 tests):
- `TestImportJobLifecycle` (6) — create, list, get, status, log, delete
- `TestExportJobLifecycle` (5) — create, list, get, status, delete
- `TestImportExecution` (3) — upload file, upload→execute→poll, execute-without-upload error
- `TestExportExecution` (3) — execute→poll, execute→poll→download→verify, download-before-complete error
- `TestImportExportErrors` (8) — 404 for get/delete/execute (import+export), status filter (import+export)

**Note**: Requires admin role. Tests use a small N-Quads fixture + SPARQL INSERT for data.

---

### 3. KGFrames Full CRUD (~8 routes) — `kgframes_endpoint.py`

> **✅ IMPLEMENTED** — `test_kgframes_api.py` has 17 tests covering frame CRUD
> (create, list, get, update, delete, batch delete), slot CRUD (create, get,
> update, delete), frames-with-slots retrieval, frame query (search, pagination,
> no-results), and frame graph (with slots, nonexistent). All 17 tests pass.

**Prefix**: `/api/graphs`

| Route | Method | Purpose |
|-------|--------|---------|
| `/kgframes` | GET | List/get frames (with pagination, filtering) |
| `/kgframes` | POST | Create/update/upsert frames |
| `/kgframes` | DELETE | Delete frames |
| `/kgframes/slots` | GET | List slots for frame |
| `/kgframes/slots` | POST | Create/update slots |
| `/kgframes/slots` | DELETE | Delete slots |
| `/kgframes/query` | POST | Query frames with criteria |
| `/kgframes/graph` | GET | Get full frame graph (frame + slots) |

**Test file**: `test_kgframes_api.py`

**Test classes**:
- `TestFrameCrud` — create, get by URI, list with pagination, update, delete
- `TestSlotCrud` — create slot on frame, list slots, update slot, delete slot
- `TestFrameQuery` — query by type, by property filter, pagination
- `TestFrameGraph` — retrieve hierarchical frame + slot graph

**Estimated**: ~20–25 tests

---

### 4. Spaces Extended Routes (5 routes) — `spaces_endpoint.py`

> `test_spaces.py` covers create, list, delete. Missing: info, analytics,
> update, filter.

| Route | Method | Purpose |
|-------|--------|---------|
| `/spaces/info` | GET | Detailed space metadata |
| `/spaces/analytics` | GET | Space analytics (triple counts, graph sizes) |
| `/spaces` | PUT | Update space properties |
| `/spaces/filter` | GET | Filter spaces by criteria |
| `/graph_counts` | GET | Fast graph object counts |

**Test file**: Extend existing `test_spaces.py`

**Test classes** (add to existing):
- `TestSpaceInfo` — get info for existing space, not-found
- `TestSpaceAnalytics` — get analytics, verify structure, refresh param
- `TestSpaceUpdate` — update display name, update metadata
- `TestSpaceFilter` — filter by prefix, empty result

**Estimated**: ~10–12 tests

---

### 5. Geo Points Endpoint (1 route) — `geo_points_endpoint.py`

> **✅ IMPLEMENTED** — `test_geo_search_api.py` already includes `TestGeoPoints`
> with 5 tests covering list all, radius (Cardiff), large radius, graph filter,
> and pagination. All 17 tests in the file pass.

**Estimated**: ~4–5 tests

---

### 6. Ontology Introspection (2 routes) — `ontology_endpoint.py`

> Low priority — static data, rarely changes.

| Route | Method | Purpose |
|-------|--------|---------|
| `/ontology/properties` | GET | List known ontology properties |
| `/ontology/classes` | GET | List known ontology classes |

**Test file**: `test_ontology_api.py`

**Test cases**:
- List properties returns non-empty list with expected fields
- List classes returns non-empty list
- Known property (e.g. `hasName`) present in results

**Estimated**: ~3–4 tests

---

## Partially Covered — Missing Route Tests

### Existing files needing expansion

| Test File | Missing Coverage | Priority | Status |
|-----------|-----------------|----------|--------|
| `test_sparql_api.py` | ~~GET query variant~~, ~~form-based insert/delete~~ | — | ✅ Done |
| `test_graphs_api.py` | ~~`GET /graph_counts`~~, ~~graph export~~ | — | ✅ Done (no separate export route) |
| `test_kgtypes_api.py` | ~~`GET /kgtypes/description`~~ | — | ✅ Done |

---

## Implementation Priority

| # | Item | Routes | Est. Tests | Priority | Status |
|---|------|--------|------------|----------|--------|
| 1 | Entity Registry CRUD | 24 | 30–40 | **P1** | ✅ Done (26 tests) |
| 2 | Import/Export Jobs | 14 | 20–25 | **P1** | ✅ Done (11 tests) |
| 3 | KGFrames Full CRUD | 8 | 20–25 | **P1** | ✅ Done (17 tests) |
| 1b | Agent Registry Extended | 7 | 10–15 | **P1.5** | ✅ Already covered (5 tests, 15/17 routes; 2 routes unimplemented) |
| 4 | Spaces Extended | 5 | 10–12 | **P2** | ✅ Done (10 new tests; see issue #012 for list_spaces name bug) |
| 5 | Geo Points | 1 | 4–5 | **P2** | ✅ Done (5 tests in geo_search) |
| 6 | Ontology | 2 | 3–4 | **P3** | ✅ Done (5 tests + client endpoint + shared model) |
| — | Partial gaps (SPARQL, graphs, kgtypes desc) | 4 | 5–6 | **P3** | ✅ Done (6 tests + 3 client methods + 2 models + bug fix #013) |

**All Tier 4 priority items resolved. Tier 5 complete. 344 tests passing.**

---

## Tier 5 — Remaining Uncovered Routes

Full audit of endpoint files identified the following routes with no direct test coverage.

### 7. KG Document Segmentation (6 routes) — `kgdocuments_endpoint.py`

| Route | Method | Purpose |
|-------|--------|---------|
| `/kgdocuments/segment` | POST | Trigger document segmentation |
| `/kgdocuments/segmentation-status` | GET | Poll segmentation status |
| `/kgdocuments/segmentation-configs` | GET | List segmentation configs |
| `/kgdocuments/segmentation-configs` | POST | Create segmentation config |
| `/kgdocuments/segmentation-configs` | PUT | Update segmentation config |
| `/kgdocuments/segmentation-configs` | DELETE | Delete segmentation config |

**Test file**: Extend `test_kgdocuments_api.py`

**Estimated**: ~6–10 tests

---

### 8. User Space Access & Password (4 routes) — `users_endpoint.py`

| Route | Method | Purpose |
|-------|--------|---------|
| `/users/spaces` | GET | Get user's space access list |
| `/users/spaces` | PUT | Grant space access to user |
| `/users/spaces` | DELETE | Revoke space access from user |
| `/me/password` | POST | Change own password |

**Test file**: Extend `test_users_api.py`

**Estimated**: ~4–6 tests

---

### 9. Entity Count (2 routes) — `kgentities_endpoint.py`

| Route | Method | Purpose |
|-------|--------|---------|
| `/kgentities/count` | GET | Count entities (by type, graph) |
| `/kgentities/counts` | POST | Batch count entities (multiple criteria) |

**Test file**: Extend `test_kgentities_api.py`

**Estimated**: ~2–3 tests

---

### 10. File Streaming (2 routes) — `files_endpoint.py`

| Route | Method | Purpose |
|-------|--------|---------|
| `/files/stream/upload` | POST | Upload file via streaming (chunked) |
| `/files/stream/download` | GET | Download file via streaming |

**Test file**: Extend `test_files_api.py`

**Estimated**: ~2–3 tests

---

### 11. Vector/Search/Fuzzy Mappings (standalone CRUD)

These mapping endpoints are exercised partially during the vector/FTS/fuzzy index
lifecycle tests, but need explicit standalone CRUD tests for full coverage.

#### 11a. Vector Mappings (6 routes) — `vector_mappings_endpoint.py`

| Route | Method | Purpose |
|-------|--------|--------|
| `/vector-mappings` | GET | List/get vector mappings |
| `/vector-mappings` | POST | Create vector mapping |
| `/vector-mappings` | PUT | Update vector mapping |
| `/vector-mappings` | DELETE | Delete vector mapping |
| `/vector-mappings/properties` | POST | Add property to mapping |
| `/vector-mappings/properties` | DELETE | Remove property from mapping |

**Test file**: Extend `test_vector_search_api.py`

#### 11b. Search Mappings (10 routes) — `search_mappings_endpoint.py`

| Route | Method | Purpose |
|-------|--------|--------|
| `/search-mappings` | GET | List search mappings |
| `/search-mappings/{id}` | GET | Get search mapping by ID |
| `/search-mappings` | POST | Create search mapping |
| `/search-mappings/{id}` | PUT | Update search mapping |
| `/search-mappings/{id}` | DELETE | Delete search mapping |
| `/search-mappings/{id}/properties` | POST | Add property to mapping |
| `/search-mappings/{id}/properties/{pid}` | DELETE | Remove property from mapping |
| `/search-mappings/{id}/indexes` | GET | List mapping indexes |
| `/search-mappings/{id}/indexes` | POST | Add index to mapping |
| `/search-mappings/{id}/indexes/{jid}` | DELETE | Remove index from mapping |

**Test file**: Extend `test_text_search_api.py`

#### 11c. Fuzzy Mappings (8 routes) — `fuzzy_mappings_endpoint.py`

| Route | Method | Purpose |
|-------|--------|--------|
| `/fuzzy-mappings` | GET | List/get fuzzy mappings |
| `/fuzzy-mappings` | POST | Create fuzzy mapping |
| `/fuzzy-mappings` | PUT | Update fuzzy mapping |
| `/fuzzy-mappings` | DELETE | Delete fuzzy mapping |
| `/fuzzy-mappings/properties` | POST | Add property to mapping |
| `/fuzzy-mappings/properties` | DELETE | Remove property from mapping |
| `/fuzzy-mappings/stats` | GET | Get fuzzy mapping stats |
| `/fuzzy-mappings/populate` | POST | Populate fuzzy index |

**Test file**: Extend `test_text_search_api.py`

**Estimated (11a+11b+11c)**: ~15–20 tests

---

### MetaQL Endpoints — NOT TESTED (intentionally)

`metaql_query_endpoint.py` and `metaql_update_endpoint.py` are **empty stub files**
with no route definitions. No tests needed.

---

## Tier 5 Implementation Priority

| # | Item | Routes | Est. Tests | Priority | Status |
|---|------|--------|------------|----------|--------|
| 7 | KG Document Segmentation | 6 | 6–10 | **P2** | ✅ Done (8 tests + bug fix #014: connection pool leak + sync fallback hang) |
| 8 | User Space Access & Password | 4 | 4–6 | **P2** | ✅ Done (4 tests + 3 client methods + URL bug fix) |
| 9 | Entity Count | 2 | 2–3 | **P3** | ✅ Done (3 tests) |
| 10 | File Streaming | 2 | 2–3 | **P3** | ✅ Already covered (4 tests in test_files_api.py) |
| 11 | Mapping Standalone CRUD | ~24 | 15–20 | **P3** | ✅ Done (15 tests + bug fix #015: vector-mappings response_model) |
| — | MetaQL | 0 | 0 | — | ⏭️ Skip (empty stubs, not needed) |

**All Tier 5 items resolved. 37 new tests added this session.**

---

## Tier 6 — Next Priority

### 12. Property-Level Mapping Tests

Standalone tests for add/remove properties on vector, search, and fuzzy mappings.
Currently exercised implicitly during index lifecycle tests but not tested in isolation.

| Endpoint | Method | Route | Purpose |
|----------|--------|-------|---------|
| Vector Mappings | POST | `/vector-mappings/properties` | Add property to vector mapping |
| Vector Mappings | DELETE | `/vector-mappings/properties` | Remove property from vector mapping |
| Search Mappings | POST | `/search-mappings/{id}/properties` | Add property to search mapping |
| Search Mappings | DELETE | `/search-mappings/{id}/properties/{pid}` | Remove property from search mapping |
| Fuzzy Mappings | POST | `/fuzzy-mappings/properties` | Add property to fuzzy mapping |
| Fuzzy Mappings | DELETE | `/fuzzy-mappings/properties` | Remove property from fuzzy mapping |

**Test file**: Extend `test_mappings_api.py`

**Estimated**: ~6–9 tests (create mapping → add property → verify → remove → verify × 3 types)

---

### 13. Integration Tests — End-to-End Workflows

Multi-endpoint workflows that exercise the full data pipeline across create, index, and query.

| Workflow | Endpoints Involved | Purpose |
|----------|-------------------|---------|
| Entity → Vectorize → Vector Search | kgentities, vector-mappings, vector-indexes, vector search | Verify entity creation triggers vectorization and is searchable |
| Entity → FTS Index → Text Search | kgentities, search-mappings, fts-indexes, text search | Verify entity appears in full-text search after indexing |
| Entity → Fuzzy Index → Fuzzy Search | kgentities, fuzzy-mappings, fuzzy populate, fuzzy search | Verify entity is discoverable via fuzzy matching |
| Document → Segment → Query Segments | kgdocuments, segment, kgentities (segments) | Verify document segmentation produces queryable segments |
| Import → Verify → Export | import job, kgentities/sparql, export job | Verify round-trip data integrity through import/export |

**Test file**: New `test_integration_workflows.py`

**Estimated**: ~10–15 tests

---

### Tier 6 Implementation Priority

| # | Item | Routes | Est. Tests | Priority | Status |
|---|------|--------|------------|----------|--------|
| 12 | Property-Level Mapping CRUD | 6 | 6–9 | **P2** | ✅ Done (8 tests in test_mappings_api.py) |
| 13 | Integration Workflows | multi | 10–15 | **P2** | ✅ Done (5 tests in test_integration_workflows.py) |

---

## Tier 7 — Multi-Vector Query Coverage

### 14. Multi-Vector Search (End-to-End API Tests)

Full coverage of the multi-vector query pipeline: `vg:multiVectorSimilarity` and `vg:multiVectorNearby`
functions exposed through the KG Query Criteria REST API (`multi_vector_criteria` field).

**Reference**: `planning/planning_multi_vector/multi_vector_query_plan.md`

**Implementation Status**: Phases 1–3 complete. All unit tests pass (54 tests for SQL generation,
26 tests for criteria builder, 7 end-to-end tests in `test_sparql_sql_multi_vector.py`).

#### What Needs API-Level Test Coverage

| Scenario | Description | Key Assertions |
|----------|-------------|----------------|
| 2-vector weighted search | Query with two indexes, different weights (0.3/0.7) | Results ranked by combined score; top result dominates the higher-weighted index |
| 3-vector search | Three vector indexes with different queries | All three contribute to scoring; combined score in [0,1] |
| Pre-computed vectors (`multiVectorNearby`) | Pass embedding arrays instead of text | Same fusion behavior but skips vectorization |
| Equal-weight search | All weights = 1.0 (auto-normalized) | Same as explicit equal fractions |
| Fusion strategies | `weighted_sum`, `relative_score`, `ranked` | Score ordering differs per strategy; `relative_score` normalizes to [0,1] per-index |
| Min score threshold | `min_combined_score: 0.6` | Results below threshold excluded |
| INTERSECT semantics | Entity missing from one index | That entity excluded from results (not scored with 0) |
| Mixed-model auto-detect | Indexes with different dimensions/providers | Auto-upgrades to `relative_score` normalization |
| Combined with entity filters | Multi-vector + entity_type filter + graph filter | Only filtered entities scored |
| Oversample factor | Custom `oversample_factor` vs default | More candidates → potentially different top-K ordering |

**Test file**: New `test_multi_vector_search_api.py`

**Prerequisites**: At least 2 vector indexes with data in the test space (can reuse existing vector_env fixtures or create dedicated ones).

**Estimated**: ~10–12 tests

---

### Tier 7 Implementation Priority

| # | Item | Routes | Est. Tests | Priority | Status |
|---|------|--------|------------|----------|--------|
| 14 | Multi-Vector Query (API-level) | POST /kgentities/query | 9 | **P2** | ✅ Done (test_multi_vector_search_api.py) |
| 15 | Multi-Vector Semantic (E2E with real embeddings) | POST /kgentities/query | 4 | **P2** | ✅ Done (test_multi_vector_semantic_api.py) |

---

## Tier 8 — UI Testing (Playwright)

### Goal: Frontend–Backend Alignment

A primary goal of UI testing is to **verify that the frontend screens accurately
reflect what the backend actually implements**, and to surface gaps in either
direction:

1. **Frontend consuming backend correctly** — Every UI screen should use the
   backend endpoints as designed. Tests should confirm that the data displayed
   (spaces, graphs, entities, search results, etc.) matches what the API returns
   for the same parameters.

2. **Identifying frontend orchestration that belongs on the backend** — If the
   UI is performing significant cross-endpoint orchestration (e.g. fetching from
   3+ endpoints sequentially to assemble a single view, doing client-side joins,
   aggregating counts across multiple calls), that logic is a candidate for a
   dedicated backend endpoint or composite response. UI tests that are slow or
   brittle because of multi-call orchestration signal this gap.

3. **Surfacing backend capabilities not exposed in the UI** — The API test suite
   (Tiers 4–7) validates ~370+ endpoint behaviors. Where the backend supports
   functionality that has no corresponding UI (e.g. entity count endpoints,
   frame queries, fuzzy search, multi-vector search), these are candidates for
   new UI features or at minimum should be documented as intentional omissions.

4. **Surfacing UI features with no backend support** — If a frontend screen
   shows controls, filters, or actions that don't map to any backend endpoint
   (dead buttons, unimplemented filters), UI tests will catch these as errors
   or timeouts. These should be either removed from the UI or implemented on
   the backend.

### Seed Data Notes

- The **WordNet frames dataset** works well for exercising the graph visualization
  UI — its entity-frame-slot structure produces rich, multi-hop graphs that stress
  the EntityGraphViewer component with realistic data.

### Alignment Audit Checklist

The following screens should be audited during UI test development:

| UI Screen | Backend Endpoints Used | Potential Gaps |
|-----------|----------------------|----------------|
| **Home / Dashboard** | spaces list, graph counts, user info | Stats may require multiple calls that could be a single `/dashboard` endpoint |
| **Spaces** | spaces list, graphs per space (N+1 calls) | Per-space graph/triple counts fetched in parallel — consider composite endpoint |
| **Graphs** | graphs list per space | — |
| **KG Entities** | entities list with pagination, sort, type filter, search | Verify all filter params actually reach the backend |
| **KG Entity Detail** | entity get, entity graph, geo mini-map | Multiple independent calls — acceptable if concurrent |
| **Semantic Search** | SPARQL query, vector/FTS/fuzzy indexes, mappings, registry search | Complex orchestration across 4+ services — verify each mode works end-to-end |
| **KG Types** | kgtypes CRUD, search, relationships | — |
| **KG Frames** | frames CRUD, slots, frame graph | — |
| **KG Documents** | documents CRUD, segmentation | — |
| **Entity Registry** | registry CRUD, identifiers, aliases, categories, locations, search | — |
| **Agent Registry** | agent CRUD, endpoints, functions | — |
| **Import / Export** | job lifecycle, file upload/download | — |
| **Users / API Keys** | users CRUD, API key CRUD | — |
| **Vector / FTS / Geo Config** | index CRUD, mapping CRUD | — |

### Rules for Identifying Backend Expansion Candidates

A frontend pattern should be moved to a backend endpoint when:

- The UI makes **3+ sequential API calls** to build a single view component
- The UI performs **client-side aggregation** (summing counts, joining by URI)
- The UI implements **business logic** (type resolution, fallback chains)
- The same orchestration is **duplicated across multiple screens**
- The orchestration is **latency-sensitive** (user-visible loading delays)

When such patterns are found during UI test development, file them as backend
enhancement issues with the tag `backend-expansion`.

### Implementation Status

| Item | Status |
|------|--------|
| Playwright infrastructure (e2e/, config, global-setup, auth) | ✅ Done |
| docker-compose.test.yml with ephemeral PG + PostGIS + pgvector | ✅ Done |
| Isolated project name (`vg-test`) — no image/network collisions with dev stack | ✅ Done |
| VG_AUTO_INIT server startup hook (incl. admin user provisioning) | ✅ Done |
| Seed script (tests/shared/seed_ui_test_data.py) — space, graph, 3 entities | ✅ Done |
| data-testid instrumentation — page-level (51/52 pages + ObjectDetailRenderer) | ✅ Done |
| data-testid instrumentation — row/card-level (KGEntities, KGFrames, KGTypes, KGRelations, KGDocuments) | ✅ Done |
| Entity lifecycle proof test (entity-lifecycle.spec.ts) — **4/4 passing** | ✅ Done |
| One-shot test runner (`e2e/run-tests.sh`) — up, seed, test, down | ✅ Done |
| Alignment audit (backend ↔ UI gap analysis) — see `ui_testing_plan.md` | ✅ Done |
| Backend expansion issues from UI test findings | ❌ Pending |

### Verifying UI Correctness via API Tests

The existing API endpoint tests (Tiers 4–7) serve as a reference for verifying
UI correctness. For any value displayed on a frontend screen, the corresponding
API call and expected response shape can be found in the endpoint test suite.
Playwright tests can confirm correctness by:

- Following the same API call patterns used in the endpoint tests to look up
  values from the REST service
- Asserting that the UI displays the same data the API returns for identical
  parameters (space ID, graph ID, entity URI, etc.)
- Using the endpoint test assertions as ground truth for expected counts,
  property values, type URIs, and error conditions

More critically, **mutations initiated through the UI can be verified by calling
the REST API directly** to confirm the change persisted. For example:

- Create an entity via the UI form → `GET /api/graphs/kgentities?uri=...`
  confirms it exists with the correct name and type
- Edit a property in the entity detail page → `GET` the entity and assert the
  updated value
- Delete an entity via the UI trash icon → `GET` returns 404 or empty result
- Create a space or graph via the UI → `GET /api/spaces` or `GET /api/graphs`
  confirms the new record

This pattern — **UI action → API verification** — is the strongest form of E2E
assertion because it proves the frontend correctly calls the backend write path
and the data round-trips through the full stack. Playwright's `request` API
context makes these verification calls straightforward without leaving the test.

The API tests and UI tests together form a two-layer verification: the API
tests prove the backend returns correct data, and the UI tests prove the
frontend both renders and *writes* that data faithfully.

### Issues Resolved During Bring-Up

1. **PostGIS missing** — `pgvector/pgvector:pg17` image lacks PostGIS. Created
   custom Dockerfile (`docker/test-pg/Dockerfile`) based on `postgres:17` with
   both `postgresql-17-postgis-3` and `postgresql-17-pgvector`.
2. **Bootstrap admin 401** — `VG_AUTO_INIT` created tables but not the admin
   user, so JWT token-version validation failed after login. Fixed by adding
   admin user provisioning to `_auto_init_tables()`.
3. **KGEntity import** — Seed script imported from non-existent
   `kgraphservice.kgentity`; correct path is
   `ai_haley_kg_domain.model.KGEntity`.
4. **Entity view navigation** — Playwright test clicked entity name text (not a
   link); the actual navigation is via the eye-icon button. Added
   `data-testid="entity-view-{uri}"` and updated the test selector.
5. **Docker image collisions** — Both dev and test compose files produced
   identically-named images. Added `name: vg-test` to the test compose file.
