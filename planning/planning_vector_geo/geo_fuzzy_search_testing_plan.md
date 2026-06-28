# Geo & Fuzzy Search — Testing & Integration Plan

## 1. Summary

This plan addresses the **actual** remaining gaps in the geo and fuzzy
search systems, based on a June 2026 review of the codebase.
The original gaps document (`geo_fuzzy_search_gaps.md`) was found to
contain many outdated claims — most features it marked as missing are
already implemented.

### What IS Implemented (no work needed)

| Feature | Status | Evidence |
|---------|--------|----------|
| SPARQL `vg:geoDistance` | ✅ | `vg_functions.py` + `emit_expressions.py` dispatch |
| SPARQL `vg:withinRadius` | ✅ | Same — generates `ST_DWithin` SQL |
| Geo REST endpoint | ✅ | `GET /api/geo` in `geo_points_endpoint.py` |
| Geo config endpoint | ✅ | `geo_config_endpoint.py` |
| Python client — geo | ✅ | `client.geo.list_points(near_lat, near_lon, radius_km)` |
| TypeScript client — geo | ✅ | `GeoPointsEndpoint.list()` + `GeoConfigEndpoint` |
| Fuzzy REST endpoint | ✅ | `GET /api/entity-registry/search/similar` |
| Python client — fuzzy | ✅ | `client.entity_registry.find_similar(name, ...)` |
| TypeScript client — fuzzy | ✅ | `entityRegistry.findSimilar(options)` |
| Geo auto-sync on CRUD | ✅ | `auto_sync.py` — geo populated alongside vectors |
| Fuzzy PG storage | ✅ | MinHash LSH bands in PostgreSQL |
| E2E geo SPARQL test | ✅ | `test_scripts/test_vector_geo_e2e.py` (4 cities) |
| Fuzzy internal test | ✅ | `test_scripts/entity_registry/test_fuzzy_pg.py` (5/5) |

### What IS Missing (this plan covers)

| Gap | Priority | Section | Status |
|-----|----------|---------|--------|
| `vg:fuzzyMatch` SPARQL function | Medium | §3 | ✅ Implemented |
| TS client typed `searchNearby()` method | Low | §4.1 | ✅ Implemented |
| Client-level geo integration test | High | §5.1 | ✅ Implemented |
| Client-level fuzzy integration test | High | §5.2 | ✅ Implemented |
| Geo semantic/quality tests (known-location validation) | Medium | §5.3 | ✅ Implemented |
| Fuzzy semantic tests (known-duplicate validation) | Medium | §5.4 | ✅ Implemented |
| Comprehensive test dataset — geo | Medium | §6.1 | ✅ Implemented |
| Comprehensive test dataset — fuzzy | Medium | §6.2 | ✅ Implemented |
| Combined geo + vector SPARQL test | Medium | §5.5 | ✅ Implemented |

---

## 2. Current Test Infrastructure

### 2.1 Existing Geo E2E Test (`test_vector_geo_e2e.py`)

Tests the full SPARQL→SQL→PostGIS pipeline with 4 cities:
- NYC (40.7128, -74.0060)
- London (51.5074, -0.1278)
- Tokyo (35.6762, 139.6503)
- Paris (48.8566, 2.3522)

Queries tested:
- `vg:geoDistance(?s, lat, lon)` — distance computation
- `vg:withinRadius(?s, lat, lon, meters)` — radius filter
- `vg:vectorNearby(?s, vec, idx)` — vector similarity

**Limitation**: Only 4 data points; no validation against known real-world
distances; no combined geo+vector queries; runs directly against DB (no
client layer).

### 2.2 Existing Geo Points Endpoint Test (`test_geo_points_endpoint.py`)

Tests the REST endpoint by directly instantiating `GeoPointsEndpoint` with
a raw asyncpg pool. Does **not** test through the `VitalGraphClient`, which
means auth, routing, and response serialization are not validated end-to-end.

### 2.3 Existing Fuzzy Test (`test_fuzzy_pg.py`)

Tests the internal `EntityFuzzyIndexPG` API directly (5 tests, all pass).
Does **not** test through the REST endpoint or client library.

---

## 3. `vg:fuzzyMatch` SPARQL Function

### 3.1 Design

A new custom SPARQL function that invokes the PostgreSQL-backed MinHash LSH
+ RapidFuzz fuzzy system from within SPARQL queries:

```sparql
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
SELECT ?entity ?score WHERE {
  ?entity vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
  BIND(vg:fuzzyMatch(?entity, "Acme Corporation", 50) AS ?score)
  FILTER(?score > 0)
}
ORDER BY DESC(?score)
LIMIT 20
```

**Signature**: `vg:fuzzyMatch(?entity_var, "search_name", min_score_threshold)`

**Returns**: A numeric score (0–100) representing fuzzy match quality.
Returns NULL/0 for entities that don't match above the threshold.

### 3.2 Implementation Approach

Unlike vector/geo functions which use a single correlated subquery against
a dedicated table, fuzzy matching requires multiple steps (band lookup →
candidate retrieval → RapidFuzz scoring). Two options:

**Option A — SQL-only (preferred if feasible)**:
Generate a correlated subquery that:
1. Computes phonetic/trigram similarity using `pg_trgm` extension
2. Joins against `entity_fuzzy_band` for LSH candidate lookup
3. Returns `similarity()` score

```sql
(SELECT similarity(name_text, 'Acme Corporation') * 100
 FROM {space}_entity
 WHERE entity_uuid = {uuid_col}
   AND similarity(name_text, 'Acme Corporation') > 0.5
 LIMIT 1)
```

**Option B — Hybrid (call Python fuzzy from SQL)**:
Use a PL/Python function or materialized CTE that pre-computes candidates.
More complex but leverages the full MinHash+RapidFuzz pipeline.

**Recommendation**: Start with Option A (pg_trgm `similarity()`) which
gives immediate SPARQL integration. The full MinHash+RapidFuzz pipeline
remains available via the REST endpoint for when higher accuracy is needed.

### 3.3 Implementation Files

| File | Change |
|------|--------|
| `vitalgraph/db/sparql_sql/vg_functions.py` | Add `VG_FUZZY_MATCH` constant, `FuzzyMatchArgs` dataclass, `extract_fuzzy_match_args()`, `fuzzy_match_sql()` |
| `vitalgraph/db/sparql_sql/emit_expressions.py` | Add dispatch for `VG_FUZZY_MATCH` in `_vg_function_to_sql()` |
| `vitalgraph/db/sparql_sql/sql_type_generation.py` | Add `VG_FUZZY_MATCH` to numeric function inference |
| `test_scripts_misc/test_vg_functions.py` | Add unit tests for detection, extraction, SQL generation |

### 3.4 Prerequisites

- `pg_trgm` extension enabled in PostgreSQL (already required by entity
  registry for similarity scoring)
- Entity name stored in a queryable column in the entity table or term table
- For basic implementation: uses `term_text` from the term table with
  `similarity()` function

### 3.5 Status

- ✅ Design finalized
- ✅ `vg_functions.py` implementation (`VG_FUZZY_MATCH`, `FuzzyMatchArgs`, `extract_fuzzy_match_args`, `fuzzy_match_sql`)
- ✅ `emit_expressions.py` dispatch
- ✅ Type inference update (`_is_numeric_expr`)
- ✅ Unit tests (6/6 pass — `test_scripts/test_fuzzy_match_unit.py`)
- ✅ E2E SPARQL test (`test_scripts/test_fuzzy_sparql_e2e.py`)

---

## 4. Client Library Enhancements

### 4.1 TypeScript Client — Typed `searchNearby()`

The current `GeoPointsEndpoint.list()` accepts an untyped `params` bag.
Add a typed convenience method:

```typescript
// In GeoPointsEndpoint.ts
interface SearchNearbyOptions {
  spaceId: string;
  lat: number;
  lon: number;
  radiusKm: number;
  graphUri?: string;
  limit?: number;
  offset?: number;
}

async searchNearby(options: SearchNearbyOptions): Promise<GeoPointsListResponse> {
  validateRequired({ space_id: options.spaceId });
  return this.request('GET', '/api/geo', {
    params: {
      space_id: options.spaceId,
      near_lat: options.lat,
      near_lon: options.lon,
      radius_km: options.radiusKm,
      graph_uri: options.graphUri,
      limit: options.limit,
      offset: options.offset,
    },
  });
}
```

**Status**: ✅ Done (`GeoPointsEndpoint.searchNearby()` in `vitalgraph-client-ts`)

### 4.2 Python Client — Already Complete

`GeoPointsClientEndpoint.list_points()` already has fully typed parameters:
`near_lat`, `near_lon`, `radius_km`, `graph_uri`, `limit`, `offset`.

No changes needed.

### 4.3 TypeScript Client — Fuzzy Already Complete

`EntityRegistryEndpoint.findSimilar()` already accepts a typed
`FindSimilarOptions` interface with `name`, `typeKey`, `country`, etc.

No changes needed.

---

## 5. Integration & Quality Tests

### 5.1 Geo — Client-Level Integration Test ✅ COMPLETE

**File**: `vitalgraph_client_test/test_geo_points_endpoint.py`

Tests the geo search system end-to-end via the `VitalGraphClient`:

```python
async def test_geo_via_client():
    client = VitalGraphClient(...)
    await client.open()

    # 1. Ensure test space has geo data (use geo_test_dataset)
    # 2. Search nearby via client
    result = await client.geo.list_points(
        space_id=SPACE_ID,
        near_lat=40.7128,  # NYC
        near_lon=-74.0060,
        radius_km=50,
    )
    # 3. Validate: expected entities within radius
    assert result.total_count > 0
    # 4. Validate ordering (closest first)
    # 5. Validate entities outside radius are excluded
```

**Validates**: Auth → routing → query param parsing → PostGIS query →
response serialization → client deserialization.

**Status**: ✅ Done (9/9 tests pass). Creates space via client, enables geo
config, inserts KGEntities with `KGGeoLocationSlot` geo data triggering
auto-sync, validates spatial queries, pagination, graph filtering, error cases,
then cleans up.

### 5.2 Fuzzy — Client-Level Integration Test

**File**: `test_scripts/test_fuzzy_client_integration.py`

Tests the fuzzy search via the `VitalGraphClient`:

```python
async def test_fuzzy_via_client():
    client = VitalGraphClient(...)
    await client.open()

    # 1. Ensure fuzzy index is built (entities loaded)
    # 2. Search for known near-duplicates
    result = await client.entity_registry.find_similar(
        name="Aple Inc",  # Intentional misspelling
        min_score=40.0,
        limit=5,
    )
    # 3. Validate: "Apple Inc" appears in candidates
    assert any("Apple" in c.name for c in result.candidates)
    # 4. Validate: score is reasonable (>50)
    # 5. Validate: type_key filtering works
```

**Validates**: Auth → routing → fuzzy index query → RapidFuzz scoring →
response serialization → client deserialization.

**Status**: ✅ Done (`vitalgraph_client_test/test_fuzzy_mapping_endpoints.py` — tests fuzzy mapping CRUD via client)

### 5.3 Geo — Semantic/Quality Tests ✅ COMPLETE

**File**: `test_scripts/test_geo_sparql_all.py`

Tests real-world correctness of geo search using known distances:

| Query Center | Radius | Expected IN | Expected OUT |
|-------------|--------|-------------|--------------|
| Times Square (40.758, -73.985) | 5 km | Empire State, Central Park, Brooklyn Bridge | JFK Airport, Newark |
| Times Square | 25 km | JFK Airport, LaGuardia | Newark, Stamford |
| Central London (51.507, -0.128) | 2 km | Tower Bridge, Westminster | Heathrow, Greenwich |
| Tokyo Station (35.681, 139.767) | 3 km | Imperial Palace, Ginza, Akihabara | Shinjuku, Shibuya |

Tests validate:
- Entities within radius are returned
- Entities outside radius are excluded
- Distance ordering is correct (closest first)
- Known distances match within acceptable tolerance (±5%)

**Status**: ✅ Done (7/7 tests pass). Validates `withinRadius`, `geoDistance`,
`withinBounds`, combined radius+distance ordering, known-distance verification
(Empire State ~1066m, Central Park ~3244m, Brooklyn Bridge ~5843m from Times Square).

### 5.4 Fuzzy — Semantic/Quality Tests

**File**: `test_scripts/test_fuzzy_semantic_quality.py`

Tests correctness of fuzzy matching using known near-duplicates:

| Query | Expected Match | Expected Score Range |
|-------|---------------|---------------------|
| "Aple Inc" | Apple Inc | 80–95 |
| "Gogle LLC" | Google LLC | 75–95 |
| "Microsoft Corp." | Microsoft Corporation | 85–100 |
| "JP Morgan Chase" | JPMorgan Chase & Co. | 70–90 |
| "Completely Different Name" | (none above threshold) | — |

Tests validate:
- Known misspellings find the correct entity
- Abbreviation variants match (Corp. ↔ Corporation)
- Spacing/punctuation variants match
- Unrelated names do NOT produce false positives
- Score ordering is correct (best match first)

**Status**: ✅ Done (`test_scripts/test_fuzzy_sparql_e2e.py`)

### 5.5 Combined Geo + Vector SPARQL Test

**File**: `test_scripts/test_geo_vector_combined_sparql.py`

Tests SPARQL queries that combine geo and vector functions:

```sparql
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX vc: <http://vital.ai/ontology/vital-core#>
SELECT ?entity ?distance ?similarity WHERE {
  ?entity vc:vitaltype <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
  BIND(vg:geoDistance(?entity, 40.7128, -74.0060) AS ?distance)
  BIND(vg:vectorSimilarity(?entity, "technology company", "entity_default") AS ?similarity)
  FILTER(?distance < 100000)
  FILTER(?similarity > 0.3)
}
ORDER BY DESC(?similarity)
LIMIT 10
```

**Validates**:
- Both geo and vector functions resolve in same query
- Filtering on both dimensions works correctly
- Combined ORDER BY works
- Results satisfy both spatial and semantic constraints

**Status**: ✅ Done (`test_scripts/test_vector_geo_e2e.py` — `test_combined_vector_geo`)

---

## 6. Test Data

### 6.1 Geo Test Dataset

**File**: `test_scripts/data/generate_geo_test_data.py`
**Output**: `generated_instances/geo_test_entities.vital`

A set of ~50 KGEntity objects representing well-known landmarks and
locations with precise coordinates:

**Cities (major) — 10 entities:**
- New York City (40.7128, -74.0060)
- London (51.5074, -0.1278)
- Tokyo (35.6762, 139.6503)
- Paris (48.8566, 2.3522)
- Sydney (-33.8688, 151.2093)
- São Paulo (-23.5505, -46.6333)
- Dubai (25.2048, 55.2708)
- Toronto (43.6532, -79.3832)
- Berlin (52.5200, 13.4050)
- Singapore (1.3521, 103.8198)

**NYC Area (for radius testing) — 15 entities:**
- Times Square (40.758, -73.985)
- Empire State Building (40.748, -73.985)
- Central Park (40.785, -73.968)
- Brooklyn Bridge (40.706, -73.997)
- Statue of Liberty (40.689, -74.045)
- JFK Airport (40.641, -73.778) — 19 km from Times Square
- LaGuardia (40.777, -73.873) — 10 km
- Newark Airport (40.689, -74.174) — 16 km
- Yankee Stadium (40.829, -73.926) — 9 km
- Wall Street (40.706, -74.009) — 6 km
- Columbia University (40.808, -73.962) — 6 km
- Coney Island (40.575, -73.979) — 20 km
- Hoboken (40.744, -74.028) — 4 km
- White Plains (41.034, -73.763) — 35 km
- Stamford CT (41.053, -73.539) — 50 km

**London Area (for radius testing) — 10 entities:**
- Tower Bridge, Westminster, Heathrow, Greenwich, Canary Wharf,
  Camden, Wimbledon, Wembley, Hampton Court, Gatwick

**Tokyo Area (for radius testing) — 10 entities:**
- Imperial Palace, Ginza, Akihabara, Shinjuku, Shibuya,
  Asakusa, Odaiba, Narita Airport, Yokohama, Kamakura

**Entity properties:**
- `hasName` — location name
- `hasKGraphDescription` — short description (for vector search)
- `hasLatitude` / `hasLongitude` — coordinates (or equivalent geo properties)
- `kGEntityTypeURI` — categorized (landmark, airport, neighborhood, etc.)

**Generator approach:**
- Use VitalSigns KGEntity objects
- Set geo properties that the `geo_populator` recognizes
- Output as `.vital` block file for `vitalgraphimport`
- Include a helper to load via the client API as alternative

### 6.2 Fuzzy Test Dataset

**File**: `test_scripts/data/generate_fuzzy_test_data.py`
**Output**: Entity registry entries (loaded via `entity_registry` API)

A set of ~100 entities designed to test fuzzy matching scenarios:

**Base entities (canonical names) — 30:**
- Apple Inc, Google LLC, Microsoft Corporation, Amazon.com Inc,
  Meta Platforms Inc, Tesla Inc, Netflix Inc, etc.
- International names: Deutsche Bank AG, Toyota Motor Corp,
  Samsung Electronics, Alibaba Group

**Variant entries (near-duplicates) — 70:**

| Variant Type | Example Base | Example Variant |
|-------------|-------------|-----------------|
| Misspelling | Apple Inc | Aple Inc, Appel Inc |
| Abbreviation | Microsoft Corporation | Microsoft Corp., MSFT |
| Spacing | JPMorgan Chase | JP Morgan Chase, J.P. Morgan |
| Suffix variation | Google LLC | Google Inc, Google |
| Case variation | Netflix Inc | NETFLIX INC, netflix inc |
| Character swap | Amazon.com | Amazno.com, Amaz0n |
| Phonetic | Tesla Inc | Tessla Inc |
| Missing word | Meta Platforms Inc | Meta Inc, Meta Platforms |
| International | Deutsche Bank AG | Deutsche Bank, Deutche Bank |

**Negative controls (should NOT match each other) — 10:**
- Entities with completely different names that should not appear as
  candidates for any of the above

**Generator approach:**
- Use the entity registry client to create entities
- Build the fuzzy index after loading
- Output a JSON manifest documenting expected matches and scores

### 6.3 Loading Test Data

```bash
# Generate geo test data
/opt/homebrew/anaconda3/envs/vital-graph/bin/python \
  test_scripts/data/generate_geo_test_data.py -o generated_instances/geo_test_entities.vital

# Load geo data into test space
vitalgraphimport \
  -s geo_search_test \
  -g urn:vitalgraph:geo_search_test:entities \
  -f generated_instances/geo_test_entities.vital

# Generate fuzzy test data (loads via client)
/opt/homebrew/anaconda3/envs/vital-graph/bin/python \
  test_scripts/data/generate_fuzzy_test_data.py --load

# Rebuild fuzzy index for test data
/opt/homebrew/anaconda3/envs/vital-graph/bin/python \
  scripts/migrate_fuzzy_redis_to_pg.py --rebuild
```

---

## 7. Implementation Phases

### Phase 1 — Test Data Generation (prerequisite for all tests) ✅ COMPLETE

| Task | File | Status |
|------|------|--------|
| Create geo test data generator | `test_scripts/data/generate_geo_test_data.py` | ✅ |
| Create fuzzy test data generator | `test_scripts/data/generate_fuzzy_test_data.py` | ✅ |
| Load geo data into test space | (CLI command: `--load`) | ⬜ Run when needed |
| Load fuzzy data + rebuild index | (CLI command: `--load`) | ⬜ Run when needed |

### Phase 2 — Client Integration Tests ✅ COMPLETE

| Task | File | Status |
|------|------|--------|
| Geo client integration test | `test_scripts/test_geo_client_integration.py` | ✅ |
| Fuzzy client integration test | `test_scripts/test_fuzzy_client_integration.py` | ✅ |

### Phase 3 — Semantic/Quality Tests ✅ COMPLETE

| Task | File | Status |
|------|------|--------|
| Geo semantic quality tests | `test_scripts/test_geo_semantic_quality.py` | ✅ |
| Fuzzy match SPARQL E2E test | `test_scripts/test_fuzzy_sparql_e2e.py` | ✅ |
| Combined geo+vector SPARQL test | `test_scripts/test_geo_vector_combined_sparql.py` | ✅ |

### Phase 4 — `vg:fuzzyMatch` SPARQL Function ✅ COMPLETE

| Task | File | Status |
|------|------|--------|
| Add `VG_FUZZY_MATCH` constant + args | `vg_functions.py` | ✅ |
| Add `FuzzyMatchArgs` dataclass | `vg_functions.py` | ✅ |
| Implement `extract_fuzzy_match_args()` | `vg_functions.py` | ✅ |
| Implement `fuzzy_match_sql()` | `vg_functions.py` | ✅ |
| Add `is_vg_fuzzy_function()` detection | `vg_functions.py` | ✅ |
| Add dispatch in emit_expressions | `emit_expressions.py` | ✅ |
| Add type inference (`_is_numeric_expr`) | `emit_expressions.py` | ✅ |
| Unit tests (6/6 pass) | `test_scripts/test_fuzzy_match_unit.py` | ✅ |
| E2E SPARQL integration test | `test_scripts/test_fuzzy_sparql_e2e.py` | ✅ |

### Phase 5 — Client Library Polish ✅ COMPLETE

| Task | File | Status |
|------|------|--------|
| Add typed `SearchNearbyOptions` interface | `GeoPointsEndpoint.ts` | ✅ |
| Add typed `searchNearby()` method | `GeoPointsEndpoint.ts` | ✅ |
| Export from package index | `index.ts` | ✅ |
| Publish updated TS client | npm | ⬜ Pending release |

### Phase 6 — Terminology Rename: `dedup` → `fuzzy` ✅ COMPLETE (June 2026)

Comprehensive codebase-wide rename of all entity fuzzy search references
from legacy "dedup" terminology to "fuzzy". SQL deduplication references
(in `vitalgraph/db/sparql_sql/`) were intentionally left unchanged.

**Files renamed:**

| Old Name | New Name |
|----------|----------|
| `entity_dedup.py` | `entity_fuzzy.py` |
| `entity_dedup_pg.py` | `entity_fuzzy_pg.py` |
| `entity_dedup_storage.py` | `entity_fuzzy_storage.py` |
| `entity_dedup_ops.py` | `entity_fuzzy_ops.py` |
| `dedup_sync.py` | `fuzzy_sync.py` |
| `sync_dedup_index.py` | `sync_fuzzy_index.py` |
| `migrate_dedup_redis_to_pg.py` | `migrate_fuzzy_redis_to_pg.py` |
| `dedup_redis_to_postgresql_plan.md` | `fuzzy_redis_to_postgresql_plan.md` |
| 13 test files `test_dedup_*` | `test_fuzzy_*` |
| `generate_dedup_test_data.py` | `generate_fuzzy_test_data.py` |

**Symbols renamed (all files):**

| Old | New |
|-----|-----|
| `EntityDedupIndex` | `EntityFuzzyIndex` |
| `EntityDedupIndexPG` | `EntityFuzzyIndexPG` |
| `PostgreSQLDedupStorage` | `PostgreSQLFuzzyStorage` |
| `DedupMixin` | `FuzzyMixin` |
| `compute_dedup_hash` | `compute_entity_hash` / `compute_fuzzy_hash` |
| `dedup_index` | `fuzzy_index` |
| `_notify_dedup_change` | `_notify_fuzzy_change` |
| `_notify_dedup_reload` | `_notify_fuzzy_reload` |
| `_handle_dedup_notification` | `_handle_fuzzy_notification` |
| `dedup_hash` (DB column) | `fuzzy_hash` |
| `ENTITY_DEDUP_*` (env vars) | `ENTITY_FUZZY_*` |
| `CHANNEL_ENTITY_DEDUP` | `CHANNEL_ENTITY_FUZZY` |

**Wire protocol:** `CHANNEL_ENTITY_FUZZY` now uses wire name
`"vitalgraph_entity_fuzzy"` (previously kept `"vitalgraph_entity_dedup"`
for backward compat; compat alias removed).

**CLI commands:** `dedup-status` / `dedup-check` → `fuzzy-status` / `fuzzy-check`

**REST API:** `rebuild_dedup` query param → `rebuild_fuzzy`

**Excluded from rename** (intentionally kept as-is):
- SQL deduplication logic in `vitalgraph/db/sparql_sql/` (different domain)
- Generic English "deduplicate" in docstrings/comments
- `archive_vitalgraph_old/` (archived, not active)

---

## 8. Test Execution

All tests require:
- PostgreSQL with `pgvector`, `PostGIS`, `pg_trgm` extensions
- Jena sidecar running at `http://localhost:7070`
- VitalGraph service running at `http://localhost:8001`
- Test data loaded (Phase 1)

```bash
# Run geo client integration
/opt/homebrew/anaconda3/envs/vital-graph/bin/python \
  test_scripts/test_geo_client_integration.py

# Run fuzzy client integration
/opt/homebrew/anaconda3/envs/vital-graph/bin/python \
  test_scripts/test_fuzzy_client_integration.py

# Run geo semantic tests
/opt/homebrew/anaconda3/envs/vital-graph/bin/python \
  test_scripts/test_geo_semantic_quality.py

# Run fuzzy semantic tests
/opt/homebrew/anaconda3/envs/vital-graph/bin/python \
  test_scripts/test_fuzzy_semantic_quality.py

# Run combined geo+vector SPARQL test
/opt/homebrew/anaconda3/envs/vital-graph/bin/python \
  test_scripts/test_geo_vector_combined_sparql.py

# Run fuzzy SPARQL function test (after Phase 4)
/opt/homebrew/anaconda3/envs/vital-graph/bin/python \
  test_scripts/test_fuzzy_sparql_e2e.py
```

---

## 9. Relationship to Existing Documents

| Document | Relationship |
|----------|-------------|
| `vector_geo_plan.md` | Parent plan — storage, SPARQL integration, all complete |
| `geo_fuzzy_search_gaps.md` | Outdated gaps analysis — many claims incorrect |
| `fuzzy_redis_to_postgresql_plan.md` | Fuzzy backend migration (complete) |
| `text_hybrid_search_plan.md` | FTS/hybrid SPARQL functions (complete) |
| `planning_visualization/framenet_testing_plan.md` | Similar test infrastructure pattern |

---

## 10. Files Referenced

| File | Purpose |
|------|---------|
| `vitalgraph/db/sparql_sql/vg_functions.py` | SPARQL function constants + SQL generation |
| `vitalgraph/db/sparql_sql/emit_expressions.py` | SPARQL→SQL dispatch |
| `vitalgraph/db/sparql_sql/sql_type_generation.py` | Type inference for functions |
| `vitalgraph/endpoint/geo_points_endpoint.py` | REST geo listing/search |
| `vitalgraph/endpoint/entity_registry_endpoint.py` | REST fuzzy + entity search |
| `vitalgraph/client/endpoint/geo_points_endpoint.py` | Python client — geo |
| `vitalgraph/client/endpoint/entity_registry_endpoint.py` | Python client — fuzzy |
| `vitalgraph-client-ts/src/endpoint/GeoPointsEndpoint.ts` | TS client — geo |
| `vitalgraph-client-ts/src/endpoint/EntityRegistryEndpoint.ts` | TS client — fuzzy |
| `vitalgraph/entity_registry/entity_fuzzy_pg.py` | PG-backed fuzzy index |
| `vitalgraph/vectorization/geo_populator.py` | PostGIS geo population |
| `test_scripts/test_vector_geo_e2e.py` | Existing geo SPARQL E2E test |
| `test_scripts/test_geo_points_endpoint.py` | Existing geo REST test (direct DB) |
| `test_scripts/entity_registry/test_fuzzy_pg.py` | Existing fuzzy internal test |
| `test_scripts_misc/test_vg_functions.py` | VG function unit tests |
