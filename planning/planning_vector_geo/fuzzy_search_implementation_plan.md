# Fuzzy Search — Implementation Plan

## 1. Overview

**Status: ✅ IMPLEMENTED (June 2026)**

The SPARQL `vg:fuzzyMatch` function is fully integrated with the MinHash LSH
fuzzy search system via a placeholder + resolve pattern (like vector search).
When a fuzzy mapping exists for the space, it resolves via MinHash LSH band
lookup + RapidFuzz scoring; otherwise it falls back to pg_trgm `similarity()`.

The fuzzy search system uses:
- **MinHash LSH** for fast candidate retrieval (stored in PostgreSQL band tables)
- **RapidFuzz** for precise scoring (token_sort_ratio, partial_ratio, etc.)
- **Phonetic matching** (Jellyfish metaphone/soundex) for pronunciation-based bonus
- **Typo-variant generation** for resilient candidate discovery

| Component | Implementation |
|-----------|---------------|
| **Algorithm** | MinHash LSH + RapidFuzz + Phonetic (with pg_trgm fallback) |
| **Index** | LSH band hashes in `{space}_fuzzy_band` tables |
| **Properties** | Configurable via `fuzzy_mapping` + `fuzzy_mapping_property` tables |
| **Scoring** | Composite: token_sort + partial + phonetic bonus |
| **Candidate filtering** | Progressive band queries with early stopping |
| **SPARQL** | `vg:fuzzyMatch` via placeholder + resolve pattern in `vg_resolve.py` |
| **REST** | `GET /api/entity-registry/search/similar` + `/api/fuzzy-mappings` CRUD |
| **Admin UI** | `frontend/src/pages/FuzzyMappings.tsx` + `FuzzyMappingDetail.tsx` |

---

## 2. Two-Track Architecture

Fuzzy search has two independent use cases with different requirements:

### Track A: SPARQL / RDF Quads (general purpose)

For arbitrary SPARQL queries over any graph data. Properties to match are
determined by `fuzzy_mapping` configuration. Keeps the implementation simple.

**Flow:**
1. `fuzzy_populator.py` reads RDF quads for mapped properties → computes
   MinHash bands → stores in `{space}_fuzzy_band`
2. At SPARQL query time, `vg:fuzzyMatch` resolves like vector search:
   placeholder in SQL → resolve step runs MinHash lookup + RapidFuzz scoring
   → injects candidate UUIDs + scores
3. No in-memory cache needed — candidate names fetched from `{space}_term`
   table on demand (small candidate sets, ~20-50 entities)

### Track B: Entity Registry (optimized)

For the entity registry's fuzzy search use case. Can retain additional optimizations
(in-memory scoring cache, phonetic LSH, typo-variant generation) since the
entity registry already maintains its own lifecycle for entities.

**Flow (existing, unchanged):**
1. `entity_fuzzy_pg.py` — entities indexed via `add_entity()`
2. `find_similar()` — band lookup → in-memory cache scoring → results
3. REST endpoint exposes this directly

The entity registry track is **already implemented**. This plan focuses on
**Track A** — wiring the real fuzzy search algorithm into the SPARQL/RDF path.

---

## 3. Design Decisions (Resolved)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Mapping tables | **New** `fuzzy_mapping` + `fuzzy_mapping_property` | Cleaner separation; fuzzy needs different config fields (shingle_k, threshold, phonetic_bonus) |
| SPARQL integration | **Placeholder + resolve** (like vector search) | Single SQL query; resolve step runs MinHash + scoring before execution |
| Index scope | **Space-scoped** (`{space}_fuzzy_band`) | Aligns with vector/geo pattern; multi-tenant safe |
| Scoring cache | **None** — both tracks fetch on demand from existing tables | Candidate sets are small (~20-50); Track A uses term table, Track B uses entity registry tables |
| Population source | **RDF quads** for Track A; entity registry for Track B | Each track indexes from its own data source independently |

### Additional Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Score injection in SQL | **CASE expression** | No join overhead; candidate sets ~20-50; trivial for PG executor |
| No fuzzy mapping fallback | **pg_trgm via existing GIN index** | `idx_{space}_term_trgm` already exists for REGEX/CONTAINS; works with zero config |
| Shared algorithm code | **`fuzzy_core.py`** shared module | Both tracks import shingle computation, MinHash build, band hashing, RapidFuzz scoring |
| Track A ↔ Track B | **Entirely independent** | Different data sources, different scopes, no interaction |

---

## 4. Track A: SPARQL Fuzzy Search Design

### 4.1 Schema

#### `{space}_fuzzy_mapping`

```sql
CREATE TABLE {space}_fuzzy_mapping (
    mapping_id      SERIAL PRIMARY KEY,
    mapping_type    VARCHAR(50) NOT NULL,      -- 'kgentity' | 'kgdocument' | etc.
    type_uri        VARCHAR(500),              -- specific KG type (NULL = class-level)
    index_name      VARCHAR(255) NOT NULL,     -- logical fuzzy index name
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    shingle_k       INTEGER NOT NULL DEFAULT 3,
    num_perm        INTEGER NOT NULL DEFAULT 64,
    lsh_threshold   FLOAT NOT NULL DEFAULT 0.3,
    phonetic_bonus  FLOAT NOT NULL DEFAULT 10.0,
    created_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### `{space}_fuzzy_mapping_property`

```sql
CREATE TABLE {space}_fuzzy_mapping_property (
    property_id     SERIAL PRIMARY KEY,
    mapping_id      INTEGER NOT NULL REFERENCES {space}_fuzzy_mapping(mapping_id) ON DELETE CASCADE,
    property_uri    VARCHAR(500) NOT NULL,
    property_role   VARCHAR(20) NOT NULL DEFAULT 'include',  -- 'include' | 'primary' | 'alias'
    ordinal         INTEGER DEFAULT 0,
    UNIQUE (mapping_id, property_uri)
);
```

Property roles:
- `primary` — the main name field (used for scoring weight)
- `alias` — alternative names (also searched/scored)
- `include` — generic include (treated as alias)

#### `{space}_fuzzy_band`

```sql
CREATE TABLE {space}_fuzzy_band (
    band_id     INTEGER NOT NULL,
    band_hash   BYTEA NOT NULL,
    entity_key  VARCHAR(500) NOT NULL   -- '{subject_uuid}:{variant_idx}'
);
CREATE INDEX idx_{space}_fuzzy_band_lookup ON {space}_fuzzy_band (band_id, band_hash);
```

#### `{space}_fuzzy_phonetic_band`

Same schema as `fuzzy_band`, for phonetic MinHash signatures.

### 4.2 Fuzzy Populator (`fuzzy_populator.py`)

Analogous to `vector_populator.py`:

1. Resolve fuzzy mapping for entity type → get mapped property URIs
2. Fetch literal property values from RDF quads for all subjects
3. For each subject: extract name variants from mapped properties
4. Compute MinHash signatures (character k-shingles)
5. Compute phonetic MinHash signatures
6. Store band hashes in `{space}_fuzzy_band` / `{space}_fuzzy_phonetic_band`
7. Wire into `auto_sync.py` for CRUD-triggered re-indexing

### 4.3 SPARQL Integration (Resolve Pattern)

Follows the same pattern as `vg:vectorSimilarity`:

1. **Compile**: `vg:fuzzyMatch(?entity, "Acme Corp", 50)` → generates SQL with
   placeholder `__VG_FUZZY_{id}__` and a `FuzzyRequest` object
2. **Resolve** (`vg_resolve.py`): Before SQL execution:
   - Check if fuzzy mapping exists for the space
   - **If mapping exists**: Build MinHash → query `{space}_fuzzy_band` → fetch
     candidate names from term table → RapidFuzz score → filter by min_score
   - **If no mapping (fallback)**: Use pg_trgm `similarity()` via existing GIN
     trigram index (zero-config, lower quality)
   - Replace placeholder with resolved SQL:
     ```sql
     -- UUID filter
     subject_uuid IN ('uuid1', 'uuid2', ...)
     -- Score as CASE expression
     CASE subject_uuid
       WHEN 'uuid1' THEN 85.2
       WHEN 'uuid2' THEN 72.1
       ...
       ELSE 0
     END
     ```
3. **Execute**: Single SQL query with the resolved UUID filter + CASE scores

#### SPARQL Function Signature (unchanged)

```sparql
BIND(vg:fuzzyMatch(?entity, "Acme Corp", 50) AS ?score)
FILTER(?score > 0)
```

### 4.4 Auto-Sync Hook

In `auto_sync.py`, alongside vector and geo sync:

```python
# After vector sync
if fuzzy_enabled:
    await fuzzy_populator.update_subject_fuzzy(conn, space_id, subject_uuid, context_uuid)
```

---

## 5. Track B: Entity Registry (Minor Refactor + REST)

The entity registry fuzzy search (`entity_fuzzy_pg.py`) already works but needs
a small refactor to survive restarts without a full rebuild:

### 5.1 Current Problem

The in-memory `_entity_cache` stores scoring metadata (primary_name, aliases,
type_key, etc.) for every indexed entity. At 1M+ entities this takes significant
time to rebuild on restart. The band hashes already survive restart (they're in
PostgreSQL), but scoring fails without the cache.

### 5.2 Solution: Lazy-Load from Entity Tables

Remove the in-memory scoring cache. Instead, when `find_similar()` returns
candidate IDs from band lookup, fetch their metadata from the existing entity
registry tables on demand:

```python
# After band lookup returns candidate_ids (~20-50 entities)
candidate_data = await self._fetch_candidate_metadata(candidate_ids)
# Score using RapidFuzz against fetched data
results = self.score_candidates(entity, candidate_data, ...)
```

This means:
- **Band hashes**: already persisted in PostgreSQL (survives restart) ✅
- **Scoring metadata**: fetched on demand from entity registry tables ✅
- **No startup rebuild**: band lookup works immediately after restart ✅
- **Per-query cost**: one DB fetch for ~20-50 candidate rows (negligible) ✅
- **No new tables**: reuses existing entity registry data ✅

### 5.3 Remaining Work

| Task | Priority | Status |
|------|----------|--------|
| Refactor `find_similar()` to fetch scoring data from entity tables | High | ✅ Done |
| Convert `_entity_cache` to lazy-load cache (fetch on miss from DB) | Medium | ✅ Done |
| Refactor `entity_fuzzy_pg.py` to delegate to `fuzzy_core.py` | High | ✅ Done |
| `GET /api/entity-registry/search/similar` REST endpoint | High | ✅ Done (pre-existing) |
| Python client `find_similar()` method | Medium | ✅ Done (pre-existing) |
| TypeScript client mirror | Low | ✅ Done (pre-existing) |

---

## 6. Implementation Phases

### Phase 1: Schema & Populator (Track A)

| Task | Priority | Status |
|------|----------|--------|
| Create `{space}_fuzzy_mapping` + `{space}_fuzzy_mapping_property` DDL | High | ✅ Done |
| Create `{space}_fuzzy_band` + `{space}_fuzzy_phonetic_band` DDL | High | ✅ Done |
| Add DDL to `sparql_sql_schema.py` | High | ✅ Done |
| Migration script for fuzzy tables | Medium | ✅ Done |
| Create `fuzzy_core.py` (shared: shingles, MinHash, band hash, RapidFuzz scoring) | High | ✅ Done |
| Create `fuzzy_mapping_manager.py` (CRUD for fuzzy mappings) | Medium | ✅ Done |
| Create `fuzzy_populator.py` (read quads → compute MinHash → store bands) | High | ✅ Done |
| Wire into `auto_sync.py` | Medium | ✅ Done |

### Phase 2: SPARQL Integration (Track A)

| Task | Priority | Status |
|------|----------|--------|
| Define `FuzzyRequest` dataclass (like `VectorRequest`) | High | ✅ Done |
| Refactor `vg:fuzzyMatch` to emit placeholder + `FuzzyRequest` | High | ✅ Done |
| Add `resolve_fuzzy_requests()` to `vg_resolve.py` | High | ✅ Done |
| Implement MinHash band lookup in resolve step | High | ✅ Done |
| Implement RapidFuzz scoring with term table fetch | High | ✅ Done |
| Update `emit_expressions.py` dispatch | Medium | ✅ Done |
| Handle empty/uninitialized fuzzy index gracefully | Medium | ✅ Done |
| Update unit tests (`fuzzy_core.py` — 42 passing) | Medium | ✅ Done |
| Update e2e SPARQL tests | Medium | ✅ Done |

### Phase 3: REST & Client (Track B)

| Task | Priority | Status |
|------|----------|--------|
| `GET /api/entity-registry/search/similar` REST endpoint | High | ✅ Done (pre-existing) |
| Fuzzy mapping CRUD endpoint (`/api/fuzzy-mappings`) | Medium | ✅ Done |
| Fuzzy mapping populate endpoint (`/api/fuzzy-mappings/populate`) | Medium | ✅ Done |
| Python client: `client.fuzzy_mappings.*` | Medium | ✅ Done |
| TypeScript client: `client.fuzzyMappings.*` | Low | ✅ Done |
| App registration in `vitalgraphapp_impl.py` | Medium | ✅ Done |
| Integration tests via client | Medium | ✅ Done (`test_fuzzy_mapping_endpoints.py` — 27/27 pass) |
| Index stats endpoint (`/api/fuzzy-mappings/stats`) | Medium | ✅ Done |

### Phase 4: Rename `dedup` → `fuzzy` (Track B) ✅ COMPLETE (June 2026)

Comprehensive codebase-wide rename completed. All entity fuzzy search files,
classes, variables, env vars, DB columns, CLI commands, REST params, wire
protocol channel name, test files, scripts, and planning docs updated.
SQL deduplication references in `vitalgraph/db/sparql_sql/` intentionally
kept unchanged (different domain).

See `geo_fuzzy_search_testing_plan.md` Phase 6 for full details.

### Phase 5: Admin UI — Fuzzy Mapping Configuration ✅ COMPLETE (June 2026)

> UI details consolidated in `planning_vector_geo/search_ui_plan.md` §9.

---

## 7. Testing Plan

### 7.1 Unit Tests (`test_scripts/test_fuzzy_core_unit.py`)

Test the shared `fuzzy_core.py` module in isolation (no DB):

| Test | What it verifies |
|------|-----------------|
| Shingle computation | `"hello" → {"hel", "ell", "llo"}` for k=3 |
| MinHash determinism | Same input → same signature |
| MinHash similarity | Similar strings → high Jaccard estimate |
| Band hash computation | Correct SHA1 of band slice |
| RapidFuzz scoring | Composite score matches expected for known pairs |
| Phonetic codes | Metaphone/soundex for known words |
| Phonetic bonus | Applied correctly when codes match |

### 7.2 Populator Tests (`test_scripts/test_fuzzy_populator.py`)

Test that fuzzy_populator correctly reads quads and stores bands:

| Test | What it verifies |
|------|-----------------|
| Populate from quads | Entities with mapped properties get band rows |
| Mapping resolution | Correct properties selected per entity type |
| Incremental update | Single subject re-indexed without full rebuild |
| Delete handling | Bands removed when entity deleted |
| No mapping → no bands | Unmapped entity types are skipped |

### 7.3 SPARQL Integration Tests (`test_scripts/test_fuzzy_sparql_e2e.py`)

End-to-end tests with real DB:

| Test | What it verifies |
|------|-----------------|
| Basic fuzzy match | `vg:fuzzyMatch(?e, "Apple Inc", 50)` returns similar entities |
| Score ordering | Higher similarity → higher score |
| Threshold filtering | Entities below min_score excluded |
| No mapping fallback | pg_trgm used when no fuzzy mapping configured |
| Empty index | Returns 0 results gracefully (no crash) |
| Multiple properties | Matches against aliases, not just primary name |
| Spelling variants | "Microsft" matches "Microsoft" |
| Phonetic match | "Googel" matches "Google" |

### 7.4 Track B Tests (`test_scripts/test_fuzzy_entity_registry.py`)

Test the refactored entity registry fuzzy search:

| Test | What it verifies |
|------|-----------------|
| Lazy-load scoring | `find_similar()` works without in-memory cache |
| Restart resilience | Band lookup works after simulated restart (no `initialize()`) |
| REST endpoint | `GET /api/entity-registry/similar` returns scored results |
| Large candidate set | Performance acceptable with 1000+ indexed entities |

### 7.5 Test Data

Reuse and extend `test_scripts/data/generate_fuzzy_test_data.py`:
- Entities with known spelling variants (Acme Corp, Acme Corporation, Acme Inc)
- Phonetic matches (Smith vs Smyth, Google vs Googel)
- Non-matches (completely different names) for false-positive validation
- Multiple entity types to test mapping isolation

---

## 8. Files Referenced

| File | Purpose |
|------|---------|
| `vitalgraph/vectorization/fuzzy_core.py` | Shared: shingles, MinHash, band hash, RapidFuzz scoring |
| `vitalgraph/vectorization/fuzzy_populator.py` | Track A: RDF quad → MinHash band population |
| `vitalgraph/vectorization/fuzzy_mapping_manager.py` | Track A: fuzzy mapping CRUD |
| `vitalgraph/vectorization/auto_sync.py` | Fuzzy sync hook (alongside vector + geo) |
| `vitalgraph/entity_registry/entity_fuzzy_pg.py` | Track B: MinHash LSH + RapidFuzz (imports fuzzy_core) |
| `vitalgraph/entity_registry/entity_fuzzy_storage.py` | Track B: band hash storage |
| `vitalgraph/db/sparql_sql/vg_functions.py` | `fuzzy_match_sql()` — emits placeholder + FuzzyRequest |
| `vitalgraph/db/sparql_sql/vg_resolve.py` | Fuzzy + vector placeholder resolve |
| `vitalgraph/db/sparql_sql/emit_expressions.py` | SPARQL expression dispatch |
| `vitalgraph/endpoint/entity_registry_endpoint.py` | REST: `GET /search/similar` |
| `vitalgraph/endpoint/fuzzy_mapping_endpoint.py` | REST: fuzzy mapping CRUD + populate |
| `frontend/src/pages/FuzzyMappings.tsx` | Admin UI: list/create/delete mappings |
| `frontend/src/pages/FuzzyMappingDetail.tsx` | Admin UI: detail/edit/populate + properties |
| `frontend/src/services/FuzzyMappingService.ts` | Frontend service layer |
| `frontend/src/types/fuzzyMappings.ts` | Frontend TypeScript types |
| `test_scripts/test_fuzzy_match_unit.py` | Unit tests (fuzzy_core) |
| `test_scripts/test_fuzzy_sparql_e2e.py` | SPARQL integration tests |
| `vitalgraph_client_test/test_fuzzy_mapping_endpoints.py` | Client integration tests (27/27 pass) |
| `vitalgraph/client/endpoint/fuzzy_mappings_endpoint.py` | Python client endpoint (CRUD + stats + populate) |
| `vitalgraph-client-ts/src/endpoint/FuzzyMappingsEndpoint.ts` | TypeScript client endpoint |
