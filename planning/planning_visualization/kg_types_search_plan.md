# KG Types Full-Text & Vector Search Plan

## 1. Overview

Enable full-text search (PostgreSQL `tsvector`) and vector similarity search
(pgvector HNSW) over KG Type objects (`KGType`, `KGEntityType`, `KGFrameType`,
`KGRelationType`, `KGSlotType`, `KGSlotRoleType`).

The existing vectorization infrastructure (`search_text_builder.py`,
`vector_populator.py`, `search_mapping_manager.py`) already supports per-class
vector mapping rules and auto-generated `tsvector` columns on the
`{space}_vec_{index}` tables. This plan defines how to extend that to KG Types
specifically.

> **Migration complete (Jun 2025):** All mapping operations now use the shared
> `{space}_search_mapping` table. The legacy `{space}_vector_mapping` table has
> been removed from DDL creation and dropping. Reindex and FTS populate
> endpoints are now async (fire-and-forget with background workers).

### Goals

1. **Full-text search** — `ts_rank`-ranked retrieval of types by name, description, and
   subclass-specific text fields (e.g. slot type labels).
2. **Vector similarity search** — Semantic "find similar types" using embedded
   description text.
3. **Hybrid search** — Combine BM25 full-text rank with cosine similarity for
   re-ranking.
4. **REST + client integration** — Expose search through the existing
   `GET /api/graphs/kgtypes/search` endpoint (already stubbed with keyword CONTAINS mode).

---

## 2. KG Type Classes & Searchable Properties

| VitalType URI | Class | Key Text Properties |
|---------------|-------|---------------------|
| `haley-ai-kg#KGType` | `KGType` (base) | `hasName`, `hasKGraphDescription`, `hasKGTypeVersion`, `hasKGModelVersion` |
| `haley-ai-kg#KGEntityType` | `KGEntityType` | + `hasKGEntityTypeDescription`, `hasKGEntityTypeExternIdentifier` |
| `haley-ai-kg#KGFrameType` | `KGFrameType` | + `hasKGFrameTypeDescription`, `hasKGFrameTypeExternIdentifier` |
| `haley-ai-kg#KGRelationType` | `KGRelationType` | + `hasKGRelationTypeSymmetric` (boolean, not text) |
| `haley-ai-kg#KGSlotType` | `KGSlotType` | + `hasKGSlotTypeName`, `hasKGSlotTypeLabel`, `hasKGSlotTypeExternIdentifier` |
| `haley-ai-kg#KGSlotRoleType` | `KGSlotRoleType` | (inherits base properties) |

### Property URIs (haley-ai-kg namespace)

```
# Common to all KGType subclasses
http://vital.ai/ontology/vital-core#hasName
http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription
http://vital.ai/ontology/haley-ai-kg#hasKGTypeVersion
http://vital.ai/ontology/haley-ai-kg#hasKGModelVersion

# KGEntityType-specific
http://vital.ai/ontology/haley-ai-kg#hasKGEntityTypeDescription
http://vital.ai/ontology/haley-ai-kg#hasKGEntityTypeExternIdentifier

# KGFrameType-specific
http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeDescription
http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeExternIdentifier

# KGSlotType-specific
http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeName
http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeLabel
http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeExternIdentifier
```

---

## 3. Vector Index & Mapping Configuration

### 3.1 Index Registration

A single vector index named `kgtype_default` is used at any given time.
Testing is **sequential** — run all tests with VitalSigns first, then tear
down the index and recreate it with OpenAI to validate that provider
integration. This avoids maintaining parallel mappings and tables.

#### Phase 1: VitalSigns (local, no API key)

```sql
INSERT INTO {space_id}_vector_index
  (index_name, dimensions, distance_metric, provider, model_name, description)
VALUES
  ('kgtype_default', 384, 'cosine', 'vitalsigns',
   'paraphrase-multilingual-MiniLM-L12-v2',
   'KG Type embeddings — VitalSigns ONNX (384d, local)');
```

Creates `{space}_vec_kgtype_default` with `vector(384)` + HNSW + GIN.

#### Phase 2: Swap to OpenAI (requires OPENAI_API_KEY)

```sql
-- Drop the VitalSigns index + data table
DROP TABLE IF EXISTS {space_id}_vec_kgtype_default;
DELETE FROM {space_id}_vector_index WHERE index_name = 'kgtype_default';

-- Recreate with OpenAI provider
INSERT INTO {space_id}_vector_index
  (index_name, dimensions, distance_metric, provider, model_name,
   provider_config, description)
VALUES
  ('kgtype_default', 1536, 'cosine', 'openai',
   'text-embedding-3-small',
   '{"api_key_env": "OPENAI_API_KEY"}'::jsonb,
   'KG Type embeddings — OpenAI 3-small (1536d, API)');
```

Creates `{space}_vec_kgtype_default` with `vector(1536)` + HNSW + GIN.

#### Provider summary

| Phase | Provider | Dims | HNSW limit (2,000) | Notes |
|-------|----------|-----:|:------------------:|-------|
| 1 | vitalsigns | 384 | ✅ well within | No cost, no network |
| 2 | openai | 1,536 | ✅ within | Requires `OPENAI_API_KEY` |

The data table always has:
- `embedding vector(N)` — HNSW-indexed (cosine)
- `search_text TEXT` — source text for debugging/re-vectorization
- `tsv tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, COALESCE(search_text, ''))) STORED` — GIN-indexed

### 3.2 Vector Mapping Rules

Use the `SearchMappingManager` to register per-class mapping rules.
Each rule defines which properties to concatenate into `search_text`.

#### Class-Level Mapping (applies to all KGType subclasses)

```python
manager = SearchMappingManager(conn, space_id)

# Base mapping: name + description (covers KGType, KGRelationType, KGSlotRoleType)
base_mid = await manager.create_mapping(
    index_name="kgtype_default",
    mapping_type="kgtype",           # class-level, no type_uri
    source_type="properties",
    enabled=True,
    separator=". ",
    include_pred_name=False,
    include_type_desc=False,
)
await manager.add_property(base_mid, "http://vital.ai/ontology/vital-core#hasName", ordinal=1)
await manager.add_property(base_mid, "http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription", ordinal=2)
```

#### Type-Specific Overrides (optional — richer text for subclasses)

```python
# KGEntityType: add entity-specific description
entity_mid = await manager.create_mapping(
    index_name="kgtype_default",
    mapping_type="kgtype",
    type_uri="http://vital.ai/ontology/haley-ai-kg#KGEntityType",
    source_type="properties",
    enabled=True,
)
await manager.add_property(entity_mid, "http://vital.ai/ontology/vital-core#hasName", ordinal=1)
await manager.add_property(entity_mid, "http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription", ordinal=2)
await manager.add_property(entity_mid, "http://vital.ai/ontology/haley-ai-kg#hasKGEntityTypeDescription", ordinal=3)

# KGFrameType: add frame-specific description
frame_mid = await manager.create_mapping(
    index_name="kgtype_default",
    mapping_type="kgtype",
    type_uri="http://vital.ai/ontology/haley-ai-kg#KGFrameType",
    source_type="properties",
    enabled=True,
)
await manager.add_property(frame_mid, "http://vital.ai/ontology/vital-core#hasName", ordinal=1)
await manager.add_property(frame_mid, "http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription", ordinal=2)
await manager.add_property(frame_mid, "http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeDescription", ordinal=3)

# KGSlotType: add slot name + label
slot_mid = await manager.create_mapping(
    index_name="kgtype_default",
    mapping_type="kgtype",
    type_uri="http://vital.ai/ontology/haley-ai-kg#KGSlotType",
    source_type="properties",
    enabled=True,
)
await manager.add_property(slot_mid, "http://vital.ai/ontology/vital-core#hasName", ordinal=1)
await manager.add_property(slot_mid, "http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeName", ordinal=2)
await manager.add_property(slot_mid, "http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeLabel", ordinal=3)
await manager.add_property(slot_mid, "http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription", ordinal=4)
```

### 3.3 Mapping Resolution Precedence

From `search_text_builder.resolve_search_mapping()`:
1. **Type-specific match** (`mapping_type='kgtype'` AND `type_uri='...#KGFrameType'`) → most specific
2. **Class-level match** (`mapping_type='kgtype'` AND `type_uri IS NULL`) → fallback
3. **No match** → `None` → vectorization skipped (opt-in model)

---

## 4. Indexing Pipeline

### 4.1 Bulk Population

Use `vector_populator.populate_index()` for initial/full indexing.
```python
from vitalgraph.vectorization.vector_populator import populate_index

# Index all KGType objects in a graph
stats = await populate_index(
    conn=conn,
    space_id=space_id,
    index_name="kgtype_default",
    context_uuid=graph_context_uuid,
    type_uri=None,               # all types in graph (or filter by subclass)
    mapping_type="kgtype",
    batch_size=200,
)
```

For type-specific indexing (e.g. only KGFrameType):

```python
stats = await populate_index(
    conn=conn,
    space_id=space_id,
    index_name="kgtype_default",
    context_uuid=graph_context_uuid,
    type_uri="http://vital.ai/ontology/haley-ai-kg#KGFrameType",
    mapping_type="kgtype",
    batch_size=200,
)
```

The same `populate_index()` call works for both VitalSigns and OpenAI — it
reads the provider from the `vector_index` registry row automatically.

### 4.2 Incremental Sync (auto_sync)

The `schedule_sync()` hook in `vitalgraph/vectorization/auto_sync.py` already
fires on entity create/update/delete. It needs to be wired into the KGType
create/update/delete endpoint handlers:

```python
from vitalgraph.vectorization.auto_sync import schedule_sync

# After KGType create/update:
schedule_sync(
    db_impl=backend_impl.db_impl,
    space_id=space_id,
    subject_uris=[type_uri],
    graph_uri=graph_id,
    operation="upsert",
)

# After KGType delete:
schedule_sync(
    db_impl=backend_impl.db_impl,
    space_id=space_id,
    subject_uris=[type_uri],
    graph_uri=graph_id,
    operation="delete",
)
```

### 4.3 Admin CLI

Extend `vitalgraphsearchutil` with a KG Type-specific populate command:

```
search populate -s SPACE --index kgtype_default --graph urn:my:graph [--type KGFrameType]
```

Works identically regardless of which provider is currently registered.

---

## 5. Query Modes

### 5.1 Full-Text Search (tsvector)

FTS uses the GIN index on the `tsv` column.

```sql
SELECT v.subject_uuid,
       ts_rank_cd(v.tsv, q) AS rank,
       v.search_text
FROM {space}_vec_kgtype_default v,
     plainto_tsquery('english', $1) q
WHERE v.tsv @@ q
  AND v.context_uuid = $2
ORDER BY rank DESC
LIMIT $3;
```

Join back to `rdf_quad` + `term` to get `hasName`, `vitaltype`, etc.:

```sql
SELECT v.subject_uuid,
       ts_rank_cd(v.tsv, q) AS rank,
       name_t.term_text AS name,
       vtype_t.term_text AS vitaltype
FROM {space}_vec_kgtype_default v,
     plainto_tsquery('english', $1) q
JOIN {space}_rdf_quad name_q
  ON name_q.subject_uuid = v.subject_uuid
 AND name_q.context_uuid = v.context_uuid
JOIN {space}_term name_p ON name_q.predicate_uuid = name_p.term_uuid
 AND name_p.term_text = 'http://vital.ai/ontology/vital-core#hasName'
JOIN {space}_term name_t ON name_q.object_uuid = name_t.term_uuid
JOIN {space}_rdf_quad vtype_q
  ON vtype_q.subject_uuid = v.subject_uuid
 AND vtype_q.context_uuid = v.context_uuid
JOIN {space}_term vtype_p ON vtype_q.predicate_uuid = vtype_p.term_uuid
 AND vtype_p.term_text = 'http://vital.ai/ontology/vital-core#vitaltype'
JOIN {space}_term vtype_t ON vtype_q.object_uuid = vtype_t.term_uuid
WHERE v.tsv @@ q
  AND v.context_uuid = $2
ORDER BY rank DESC
LIMIT $3;
```

### 5.2 Vector Similarity Search

The SQL is the same regardless of provider — only the embedding dimensions
and the query vector (produced by the current provider) differ.

```sql
-- Embed query text via current provider, then:
SELECT v.subject_uuid,
       1 - (v.embedding <=> $1::vector) AS cosine_sim,
       v.search_text
FROM {space}_vec_kgtype_default v
WHERE v.context_uuid = $2
ORDER BY v.embedding <=> $1::vector
LIMIT $3;
```

### 5.3 Hybrid Search (FTS + Vector Re-rank)

Two-phase approach:
1. **Retrieve candidates** via FTS (`tsv @@ query`, top 100)
2. **Re-rank** candidates by cosine similarity to query embedding

```sql
WITH fts_candidates AS (
    SELECT v.subject_uuid, v.embedding,
           ts_rank_cd(v.tsv, plainto_tsquery('english', $1)) AS fts_rank
    FROM {space}_vec_kgtype_default v
    WHERE v.tsv @@ plainto_tsquery('english', $1)
      AND v.context_uuid = $2
    ORDER BY fts_rank DESC
    LIMIT 100
)
SELECT c.subject_uuid,
       c.fts_rank,
       1 - (c.embedding <=> $3::vector) AS cosine_sim,
       (0.4 * c.fts_rank + 0.6 * (1 - (c.embedding <=> $3::vector))) AS combined_score
FROM fts_candidates c
ORDER BY combined_score DESC
LIMIT $4;
```

### 5.4 Type-Filtered Search

All queries above can be extended with a type filter by joining to the
`rdf_quad` + `term` tables for `vitaltype`:

```sql
  AND EXISTS (
      SELECT 1 FROM {space}_rdf_quad tq
      JOIN {space}_term tp ON tq.predicate_uuid = tp.term_uuid
        AND tp.term_text = 'http://vital.ai/ontology/vital-core#vitaltype'
      JOIN {space}_term tv ON tq.object_uuid = tv.term_uuid
        AND tv.term_text = $type_uri
      WHERE tq.subject_uuid = v.subject_uuid
        AND tq.context_uuid = v.context_uuid
  )
```

---

## 6. Integration with Existing search_types() Endpoint — ✅ IMPLEMENTED

All search modes route through the **SPARQL pipeline**. There are no
standalone raw-SQL search modules — `kgtypes_read_impl.py` builds SPARQL
with `vg:` functions and the SPARQL-to-SQL compiler handles the rest.

See `text_hybrid_search_plan.md` §4 for the complete SPARQL integration
architecture.

### 6.1 Backend (Implemented)

`kgtypes_read_impl.py`:

```python
async def search_types(
    self, backend, space_id, graph_id, query,
    type_filter=None, search_mode="keyword",
    limit=100, alpha=None,
) -> Dict[str, Any]:
    if search_mode in ("fts", "vector", "hybrid"):
        return await self._search_types_vg(...)   # builds SPARQL with vg: function
    return await self._search_types_keyword(...)   # SPARQL CONTAINS fallback
```

| Mode | SPARQL Function | FTS Index | Vector Index | Vectorization |
|------|----------------|-----------|--------------|---------------|
| `keyword` | `FILTER(CONTAINS(...))` | No | No | No |
| `fts` | `vg:textSearch` | Yes (`_fts_` table) | No | No |
| `vector` | `vg:vectorSimilarity` | No | Yes (`_vec_` table) | Yes |
| `hybrid` | `vg:hybridSearch` | Yes | Yes | Yes |

### 6.2 REST API (Implemented)

```
GET /api/graphs/kgtypes/search?space_id=X&graph_id=Y&q=Z&search_mode=vector&alpha=0.6
```

The `alpha` parameter (hybrid only) is configurable: 0.0=pure BM25,
1.0=pure vector, default 0.5.

### 6.3 Python Client (Implemented)

```python
response = await client.kgtypes.search_types(
    space_id, graph_id, query="Commerce",
    search_mode="vector",    # "keyword", "fts", "vector", "hybrid"
    type="frame",            # optional type filter shorthand
)
```

---

## 7. Implementation Tasks

### Phase A: Index Setup & Mapping Configuration

| # | Task | Status |
|---|------|--------|
| A1 | Register `kgtype_default` vector index in space setup | ✅ Done — test script self-provisions via REST API |
| A2 | Create class-level mapping rule (`mapping_type='kgtype'`) | ✅ Done — shared search mapping created via REST API |
| A3 | Create type-specific mapping overrides (Entity, Frame, Slot) | ✅ Done — subclass overrides created for KGEntityType, KGFrameType, KGSlotType |
| A4 | Admin CLI command: `search populate --index kgtype_default` | ✅ Done — `vitalgraphsearchutil` supports `search populate` with `--index` and `--type` |
| A5 | Implement `swap_vector_index()` helper: drops table + index row + mappings, re-registers with new provider, recreates mappings, repopulates | ✅ Done — `vector_index_lifecycle.py` handles setup/teardown/swap |

### Phase B: Full-Text Search (validates PostgreSQL tsvector + GIN indexing)

FTS now uses decoupled `{space}_fts_{idx}` tables with `vg:textSearch` SPARQL
function (see `text_hybrid_search_plan.md` Phase 6A–6D). No raw SQL in
`kgtypes_read_impl.py` — all modes go through SPARQL pipeline.

| # | Task | Status |
|---|------|--------|
| B1 | Implement `_search_types_fts()` in `kgtypes_read_impl.py` | ✅ Done — `_search_types_vg()` builds SPARQL with `vg:textSearch` |
| B2 | Wire FTS as default when `kgtype_default` index exists | ✅ Done — `search_mode=fts` dispatches to `_search_types_vg()` |
| B3 | FTS test: single keyword search ("Commerce") — validates GIN index hit | ✅ Verified (11/11 REST tests pass) |
| B4 | FTS test: multi-word search ("commercial transaction") — validates `plainto_tsquery` | ✅ Verified |
| B5 | FTS test: search with type filter (e.g. frames only) | ✅ Verified |
| B6 | FTS test: verify `ts_rank_cd` ordering (top result is best match) | ✅ Verified |
| B7 | FTS test: long description text is searchable (validates `search_text` stored correctly) | ✅ Verified |
| B8 | FTS test: no-results query returns empty | ✅ Verified |

### Phase C: Vector Search

| # | Task | Status |
|---|------|--------|
| C1 | Implement `_search_types_vector()` in `kgtypes_read_impl.py` | ✅ Done — `_search_types_vg()` builds SPARQL with `vg:vectorSimilarity` |
| C2 | Embed query text using provider from `kgtype_default` index config | ✅ Done — `vg_resolve.py` handles vectorization via placeholder substitution |
| C3 | Add vector search test: "types about buying things" → Commerce | ✅ Verified — 4 vector tests pass (hiring, movement, payment, slot agent) |

### Phase D: Hybrid Search

| # | Task | Status |
|---|------|--------|
| D1 | Implement `_search_types_hybrid()` — FTS retrieve + vector re-rank | ✅ Done — `_search_types_vg()` builds SPARQL with `vg:hybridSearch`; uses FTS+vector JOIN |
| D2 | Tune score weighting (FTS weight vs. cosine weight) | ✅ Done — configurable `alpha` param (0.0=BM25, 1.0=vector); REST + SPARQL 4th arg |
| D3 | Add hybrid search test with quality comparison | ✅ Verified — 2 hybrid tests pass (cooking, commercial transaction) |

### Phase E: Auto-Sync Integration

| # | Task | Status |
|---|------|--------|
| E1 | Wire `schedule_sync()` into KGType create endpoint | ✅ Done — `_trigger_sync()` in `kgtypes_endpoint.py` |
| E2 | Wire `schedule_sync()` into KGType update endpoint | ✅ Done |
| E3 | Wire `schedule_sync()` into KGType delete endpoint | ✅ Done |
| E4 | Test: create type → immediately searchable via FTS + vector | ✅ Done — 24/24 tests pass (see bug fix below) |

### Phase F: Client Integration Tests

FrameNet integration tests split into two scripts:
- **`setup_kgtype_search_framenet.py`** — creates space, imports data, creates indexes, triggers async population, polls until ready
- **`test_kgtype_search_framenet.py`** — runs 21 search tests (assumes setup is done)

All 24/24 tests pass:
- 6 keyword tests via REST: ✅
- 4 FTS tests via REST: ✅
- 4 vector tests via REST: ✅
- 2 hybrid tests via REST: ✅
- 1 no-results + 1 type-filter: ✅
- 4 direct SPARQL tests (keyword, FTS, vector, hybrid): ✅
- 3 auto-sync tests (create verified, FTS found, vector found): ✅

| # | Task | Status |
|---|------|--------|
| F1 | Extend `case_kgtype_search.py` with FTS mode tests (keyword, multi-word, type-filtered) | ✅ Done — `test_kgtype_search_framenet.py` covers 6 keyword + 4 FTS tests |
| F2 | Add vector search mode test (VitalSigns phase) | ✅ Verified — 4 vector tests pass |
| F3 | Add hybrid search mode test (VitalSigns phase) | ✅ Verified — 2 hybrid tests pass |
| F4 | Test no-results edge case for each mode | ✅ Verified (nonsense query → 0 results) |

### Phase G: OpenAI Provider Validation (sequential — runs after Phase F)

Runs against the **FrameNet** dataset (~2,500 types, ~$0.003 via OpenAI).
Requires `OPENAI_API_KEY` set in `.env` (local testing only).

| # | Task | Status |
|---|------|--------|
| G1 | Clean-slate swap: drop table, delete index row & mappings, re-register with OpenAI, recreate mappings | ✅ Done |
| G2 | Populate `kgtype_default` with OpenAI embeddings (FrameNet, 2506 vectors, ~100s) | ✅ Done |
| G3 | Run FTS tests (validates `search_text` + tsvector GIN indexing with new table) | ✅ Verified |
| G4 | Run vector search tests (validates OpenAI embed → store → HNSW query) | ✅ Verified |
| G5 | Run hybrid search tests | ✅ Verified |
| G6 | Log OpenAI top-5 vs. VitalSigns top-5 for same queries (informational, not asserted) | ✅ Done |
| G7 | Clean-slate swap back to VitalSigns + repopulate (restore known-good state) | ✅ Done (2506 vectors, ~296s) |

Test script: `test_scripts/sparql/test_kgtype_search_openai.py` — **9/9 tests pass**
- 5 comparison queries captured (3 vector, 2 hybrid)
- 8 OpenAI search tests (vector + hybrid + FTS + type-filtered): ✅
- 1 VitalSigns restore sanity check ("Hiring" found): ✅

### Summary: Overall Progress

| Phase | Status | Notes |
|-------|--------|-------|
| A (Index Setup) | ✅ Complete | 5/5 — all index setup tasks done |
| B (FTS) | ✅ Complete | 8/8 — all FTS tasks done and tested |
| C (Vector) | ✅ Complete | 3/3 — all vector tasks done and tested |
| D (Hybrid) | ✅ Complete | 3/3 — all hybrid tasks done and tested |
| E (Auto-Sync) | ✅ Complete | 4/4 — all auto-sync tasks done and tested |
| F (Client Tests) | ✅ Complete | 24/24 tests pass (keyword, FTS, vector, hybrid, SPARQL, auto-sync) |
| G (OpenAI) | ✅ Complete | 7/7 — 9/9 tests pass; provider swap validated end-to-end |

---

## 8. Test Datasets

### 8.1 FrameNet Types (existing)

**Space:** `framenet_kgtypes_test`
**Graph:** `urn:vitalgraph:framenet_kgtypes_test:kg_types`

| Class | Count | Good for testing |
|-------|-------|-----------------|
| KGFrameType | 1,221 | Name search ("Commerce", "Motion"), semantic search ("buying things") |
| KGSlotType | 1,285 | Slot name/label search |
| Edge_hasSubKGFrameType | 781 | (not directly searchable, but validates relationship context) |

### 8.2 Client Test Types (existing)

**Space:** `space_client_test`
**Graph:** `urn:test_kgtypes`

20 mixed types (5 base, 5 entity, 4 frame, 3 relation, 3 slot) with
description text set by `ClientTestDataCreator`.

### 8.3 Expected Search Results

| Query | Mode | Expected Top Results |
|-------|------|---------------------|
| `"Commerce"` | keyword | Commerce_buying, Commerce_sell, Commercial_transaction |
| `"buying things"` | vector | Commerce_buying, Shopping, Commercial_transaction |
| `"employee"` | keyword | EmployeeEntity (test data) |
| `"address"` | keyword | AddressFrame (test data) |
| `"zzz_nonexistent"` | any | 0 results |

**Provider comparison (Phase G):** After swapping to OpenAI, re-run the
same vector queries and log the top-5 alongside the VitalSigns top-5.
Differences in ranking are expected (different models) but the same types
should appear in the result set.

---

## 9. Performance Considerations

- **FrameNet scale (2,500 types)**: Both FTS and vector search should complete in < 10ms.
  HNSW index is overkill at this scale but ensures consistent performance as
  type catalogs grow.
- **Large catalogs (100k+ types)**: HNSW `ef_search` tuning may be needed.
  Default PostgreSQL `SET hnsw.ef_search = 40` should be adequate for top-20.
- **Index build time (VitalSigns)**: ~2,500 types × 384-dim ≈ 3.8 MB.
  Full population < 30 seconds on CPU (no network).
- **Index build time (OpenAI)**: ~2,500 types × 1,536-dim ≈ 15.4 MB.
  Full population limited by API rate (~3,000 texts/min on tier-1).
  At batch_size=100, expect ~1–2 minutes for 2,500 types.
- **Incremental sync**: Single-type upsert < 100ms (VitalSigns, local) or
  ~200ms (OpenAI, includes API round-trip).
- **Index swap overhead**: Clean-slate swap drops the table, index
  registry row, and mapping rows, then recreates everything from scratch.
  The DDL is fast (< 1s); repopulation dominates.

---

## 10. Related Documents

- `planning_visualization/kg_types_plan.md` — Overall KG Types implementation plan
- `planning_vector_geo/vector_geo_plan.md` — Vector & geo infrastructure (storage design, HNSW, tsvector)
- `planning_vector_geo/vector_geo_ui_plan.md` — Vector & geo UI integration
- `vitalgraph/vectorization/search_text_builder.py` — Search text construction from RDF properties
- `vitalgraph/vectorization/vector_populator.py` — Batch vectorization pipeline
- `vitalgraph/vectorization/search_mapping_manager.py` — Search mapping CRUD (shared by vector + FTS)
- `vitalgraph/vectorization/auto_sync.py` — Post-CRUD vector sync hooks
- `vitalgraph/db/sparql_sql/sparql_sql_schema.py` — Vector data table DDL
- `planning_visualization/btree_term_index_plan.md` — Btree row-size limit
  on `term_text` (hash index fix pending; FrameNet descriptions currently
  truncated to 2,500 chars in generator as workaround)

---

## 11. Architecture Changes (Jun 2025)

### 11.1 vector_mapping → search_mapping Migration

All mapping operations now use the shared `{space}_search_mapping` table:
- **DDL**: `vector_mapping` and `vector_mapping_property` removed from `sparql_sql_schema.py`
- **Runtime**: `vector_populator.py` uses `resolve_search_mapping()` exclusively
- **CLI**: `vitalgraphsearchutil_cmd.py` uses `SearchMappingManager`
- **Lifecycle**: `vector_index_lifecycle.py` uses `SearchMappingManager`
- **Documents**: `vector_index_setup.py` writes to `_search_mapping` tables
- **drop_space**: explicitly drops legacy `_vector_mapping` tables from pre-migration spaces

### 11.2 Async Reindex & FTS Populate Endpoints

- `POST /api/vector-indexes/reindex` — validates inputs, spawns `_run_reindex()` background task, returns immediately with `"Reindex started"`
- `POST /api/fts-indexes/populate` — validates inputs, spawns `_run_populate()` background task, returns immediately with `"FTS population started"`
- Background workers acquire their own DB connections from the pool
- Progress is observable via `GET /api/vector-indexes?index_name=X` (embedding_count) and `GET /api/fts-indexes/stats` (row count)

### 11.3 Test Script Split

- `setup_kgtype_search_framenet.py` — space creation, data import, index setup, async population with polling
- `test_kgtype_search_framenet.py` — 24 search tests (21 search + 3 auto-sync), fails fast if indexes not populated

### 11.4 Bug Fix: Literal Term Type in KGType Create (Jun 2026)

**Root cause:** `kgtypes_create_impl.py` `_build_insert_quads_for_kgtype()` was converting
rdflib `URIRef`/`Literal` objects to plain strings before passing to `add_rdf_quads_batch_bulk()`.
The bulk insert's `_classify()` function then treated all terms as `term_type='U'` (URI),
so literal values (names, descriptions) were stored with the wrong type.

**Impact:**
- `fetch_literal_properties()` (filters `term_type='L'`) returned empty → auto-sync had no text to vectorize/FTS-index
- SPARQL `CONTAINS(LCASE())` failed on newly created types (typed literal mismatch)
- Keyword search mode could not find newly created KGTypes

**Fix:** Preserve rdflib types (`URIRef`, `Literal`, `BNode`) in the quad tuples returned by
`_build_insert_quads_for_kgtype()`. Only fix malformed CombinedProperty URIs while keeping
`Literal` objects intact.

**Secondary fix:** Client-side `delete_kgtype()` in `client/endpoint/kgtypes_endpoint.py`
now converts `uri` to `str()` before building `deleted_uris` list, preventing Pydantic
validation errors when VitalSigns `CombinedProperty` objects are passed.

### 11.5 Bug Fixes: Vector Index Swap (Jun 2026)

Multiple issues discovered and fixed during Phase G OpenAI provider validation:

1. **`vector_indexes_endpoint.py` — delete_index**: Referenced legacy `_vector_mapping` table
   (removed during migration). Fixed to use `_search_mapping` / `_search_mapping_property`
   with try/except to handle spaces that may not have the tables.

2. **`vector_indexes_endpoint.py` — create_index**: `provider_config` JSONB column returned
   as raw string by asyncpg, causing `dict("string")` → `ValueError`. Added
   `_parse_provider_config()` helper that handles dict, string, or None.

3. **`vector_indexes_endpoint.py` — create_index**: `CREATE TABLE IF NOT EXISTS` silently
   kept old table with wrong vector dimensions after a partially-failed delete. Fixed by
   adding `DROP TABLE IF EXISTS` before create.

4. **`vector_indexes_endpoint.py` — delete_index**: Added provider cache eviction
   (`_provider_cache.pop(cache_key)`) so re-created indexes don't reuse stale embedders.

5. **`vectorization/registry.py` — get_provider()**: Cache lookup returned stale provider
   when `cache_key` matched but `provider_name` didn't (e.g. VitalSigns cached, OpenAI
   requested). Fixed to validate `cached.provider_name == provider_name` and auto-evict
   stale entries. This is the definitive fix for provider swap correctness.
