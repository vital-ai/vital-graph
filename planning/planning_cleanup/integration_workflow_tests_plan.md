# Integration Workflow Tests — End-to-End Scenario Tracker

## 1. Summary

This document tracks API integration tests that chain multiple endpoint
steps into end-to-end workflows.  Each scenario creates data, transforms
it through one or more subsystems, and asserts downstream results — not
just individual endpoint correctness, but cross-subsystem consistency.

---

## 2. Existing End-to-End Workflow Tests

### 2.1 KGTypes → Entity Vectorization (cross-space)

| Item | Detail |
|------|--------|
| **File** | `tests/api/test_kgtypes_entity_integration.py` |
| **Tests** | 5 |
| **Steps** | Create KGEntityTypes in sp_kg_types → create vector index + mapping (source_type=type_description) → create typed KGEntities → reindex → poll vectors → semantic search → verify ranking |
| **Key assertion** | Entities rank by semantic similarity of their *type description*, not their name |

### 2.2 Entity → Vector Reindex → Vector Search

| Item | Detail |
|------|--------|
| **File** | `tests/api/test_integration_workflows.py` — `TestEntityVectorSearchWorkflow` |
| **Tests** | 2 |
| **Steps** | Create vector index + mapping → create entity with searchable text → reindex → poll get_vectors → verify vector stored with correct dimensions |

### 2.3 Entity → FTS Populate → Text Search

| Item | Detail |
|------|--------|
| **File** | `tests/api/test_integration_workflows.py` — `TestEntityTextSearchWorkflow` |
| **Tests** | 2 |
| **Steps** | Create FTS index → create search mapping → create entity → populate → poll stats → text search for unique term |

### 2.4 Entity CRUD Round-Trip

| Item | Detail |
|------|--------|
| **File** | `tests/api/test_integration_workflows.py` — `TestEntityCrudRoundTrip` |
| **Tests** | 1 |
| **Steps** | Create → get → update → get (verify) → count → delete → get (verify gone) |

### 2.5 Multi-Vector Fusion (pre-computed)

| Item | Detail |
|------|--------|
| **File** | `tests/api/test_multi_vector_search_api.py` |
| **Tests** | 9 |
| **Steps** | Create entities → create index A + index B → upsert vectors (4 in A, 3 in B) → multi-vector query with weight/fusion/threshold/intersect variations |
| **Key assertion** | INTERSECT semantics exclude entity missing from one index; weight shift changes top-ranked entity; all fusion strategies return consistent sets |

### 2.6 Multi-Vector Semantic (real embeddings)

| Item | Detail |
|------|--------|
| **File** | `tests/api/test_multi_vector_semantic_api.py` |
| **Tests** | 4 |
| **Steps** | Create entities → create profession index + food index → embed different text per index per entity → upsert → multi-vector search_text → verify cross-dimensional ranking |
| **Key assertion** | "engineer who likes sushi" ranks Alice #1, Dave (chef+pizza) last |

### 2.7 Entity-Frame CRUD

| Item | Detail |
|------|--------|
| **File** | `tests/api/test_entity_frames_api.py` |
| **Tests** | 5 |
| **Steps** | Create entity → create frame + slots + edges → list frames → get frame → update slot → delete frame |

### 2.8 Entity Graph Cache Lifecycle

| Item | Detail |
|------|--------|
| **File** | `tests/api/test_entity_graph_cache_api.py` |
| **Tests** | 5 |
| **Steps** | Create entity → get (cache miss, populate) → get (cache hit) → update entity (invalidation) → get (re-populate) → delete (invalidation) → verify stats |

### 2.9 Entity Graph Reference ID Regression

| Item | Detail |
|------|--------|
| **File** | `tests/api/test_entity_graph_ref_id_api.py` |
| **Tests** | 5 |
| **Steps** | Create entity + frame + slots + edges → get with include_entity_graph → verify no triple duplication from self-referencing kGGraphURI |

### 2.10 Connection Queries (relation / entity / frame)

| Item | Detail |
|------|--------|
| **File** | `tests/api/test_kgqueries_api.py` |
| **Tests** | 9 |
| **Steps** | Create entities → create relations (Edge_hasKGRelation) → query_connections with relation/entity/frame criteria |

### 2.11 FTS + Fuzzy Full Lifecycle

| Item | Detail |
|------|--------|
| **File** | `tests/api/test_text_search_api.py` |
| **Tests** | 40 |
| **Steps** | Create FTS index → create search mapping → add property → create entities → populate → text search → fuzzy index lifecycle → fuzzy populate → fuzzy search |

### 2.12 Import / Export Round-Trip

| Item | Detail |
|------|--------|
| **File** | `tests/api/test_import_export_api.py` |
| **Tests** | 25 |
| **Steps** | Export data → import data → verify entities → list jobs → poll job status |

---

## 3. Planned New Workflow Tests

### 3.1 OpenAI Vector Model — End-to-End ✅ VERIFIED (Jul 2026)

> **Status**: Fully verified. 8/8 tests pass with live `OPENAI_API_KEY` (9.4s).
>
> **Completed**:
> 1. ✅ Rewritten test to use correct order: mapping → index → attach via `add_index()`
> 2. ✅ `OPENAI_API_KEY` passed into Docker container
> 3. ✅ Legacy `vector_mappings` endpoint removed from Python client + server route registration
> 4. ✅ Legacy `VectorMappingsEndpoint` removed from TypeScript client
> 5. ✅ All tests migrated from `vector_mappings` to `search_mappings`
> 6. ✅ End-to-end run with live OpenAI key — embeddings stored, semantic rankings correct

**Goal**: Verify the full lifecycle using OpenAI as the embedding provider
instead of the default local VitalSigns model.

| Item | Detail |
|------|--------|
| **File** | `tests/api/test_openai_vector_integration.py` (exists, unverified) |
| **Priority** | Medium |
| **Requires** | `OPENAI_API_KEY` env var on both client AND server (Docker container) |

**Steps** (correct order per `search_ui_plan.md` architecture):

1. Create search mapping for `kgentity` with `source_type="properties"`
   (the mapping is the primary entity — defines what to vectorize)
2. Create vector index with `provider="openai"`, `model_name="text-embedding-3-small"`,
   `dimensions=1536`
3. Attach the vector index to the mapping via the `search_mapping_index` junction
   (`POST /api/search-mappings/{id}/indexes` with `{index_type: "vector", index_name: ...}`)
4. Create 4–5 KGEntities with semantically distinct names/descriptions
   (e.g. "quantum physics researcher", "Italian chef", "jazz musician",
   "marine biologist", "financial analyst")
5. Trigger reindex — server calls OpenAI API to embed entity text
6. Poll `get_vectors` until all entities have stored embeddings
7. Verify embedding dimensions == 1536
8. Run vector similarity search with `search_text="cooking recipes pasta"`
   — assert chef entity ranks first
9. Run vector similarity search with `search_text="stock market trading"`
   — assert financial analyst ranks first
10. Run multi-vector search combining OpenAI index + a second local index
    (if applicable) — verify fusion works across providers
11. Cleanup: delete entities, detach index from mapping, delete mapping, delete index

> **✅ DONE**: The test has been rewritten to use the correct order (mapping → index →
> attach via `add_index()`). The legacy `vector_mappings` endpoint has been removed from
> the Python client, server route registration, and TypeScript client. All tests
> (`test_kgtypes_entity_integration.py`, `test_integration_workflows.py`,
> `test_openai_vector_integration.py`, `test_vector_search_api.py`, `test_mappings_api.py`)
> now use `search_mappings` + `add_index()`. See
> `planning/planning_cleanup/openai_vector_test_and_mapping_cleanup_plan.md` for details.

**Assertions**:
- Embeddings are stored with correct dimensions (1536)
- Semantic ranking is correct (domain-relevant entity ranks first)
- No errors from OpenAI provider path
- Works with `search_text` (server-side embedding) not just pre-computed vectors

**Test fixture pattern**:
```python
@pytest.fixture(autouse=True)
def _require_openai_key():
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")
```

### 3.2 Document Ingest → Segmentation → Search ❌ NOT IMPLEMENTED

> **Status**: Test does not exist. All server-side components are ✅ Done
> (see `planning/planning_kgdocument/kgdocument_plan.md` §11). No end-to-end
> integration test exercises the full pipeline yet.
>
> **Tracking doc**: `planning/planning_cleanup/document_segmentation_e2e_test_plan.md`

**Goal**: Verify the full document lifecycle from upload through automatic
segmentation into searchable segments, ending with semantic search that
finds relevant segments.

| Item | Detail |
|------|--------|
| **File** | `tests/api/test_document_segmentation_search_integration.py` (new) |
| **Priority** | High |
| **Requires** | Running segmentation worker (auto-started on app boot) |

**Corrected steps** (based on actual architecture):

1. **Create segmentation config** — register `document_type_uri` +
   `segment_method_uri` via `create_segmentation_config()`. This tells
   the auto-segmentation hook to fire when a matching doc is created.
2. **Create vector index** — `provider="vitalsigns"`, 384 dims, or use
   the auto-created `document_segments` index (`vector_index_setup.py`).
3. **Create search mapping** — `mapping_type="kgdocument_segment"`,
   `source_type="default"` (NOT `"properties"` — `"default"` pulls
   `kGBody`/content directly).
4. **Attach index to mapping** — `add_index(mapping_id, index_type="vector",
   index_name="document_segments")`.
5. **Create KGDocument** — with `kGDocumentType` matching the config's
   `document_type_uri` and substantial multi-paragraph content.
6. **Poll segmentation status** — `get_segmentation_status(space_id,
   document_uri=...)` until status is `completed`.
7. **List segments** — `list_segments(space_id, graph_id, parent_uri)`.
   Verify: count > 1, each segment has content, parent refs correct.
8. **Trigger reindex** — `reindex(space_id, index_name, graph_uri,
   mapping_type="kgdocument_segment")`.
9. **Poll get_vectors** — until segment vector count matches segment count.
10. **Verify dimensions** — embedding length == 384.
11. **Semantic search** — `search_text="solar panel efficiency"` → assert
    renewable-energy segment ranks first.
12. **Second semantic search** — `search_text="ocean temperature rise"` →
    assert climate segment ranks first.
13. **Cleanup** — delete document (cascades to parent copy + segments),
    delete mapping, delete index, delete segmentation config.

**Key architecture points**:
- Segmentation uses a **three-tier model**: Original → Parent Copy → Segments
- Auto-segmentation fires via `AutoSegmentationHook.on_document_upsert()`
  inline during document CRUD, or via `SegmentationWorker` picking up
  `pending` jobs from the `segmentation_jobs` queue table.
- Segment method URIs: `urn:segmethod:plain_recursive_split` (plain text),
  `urn:segmethod:markdown_heading_split` (markdown).
- Segments are stored as full KGDocument objects in the RDF quad store.
- `Edge_hasKGDocumentSegment` links original → parent copy → segments.

**Assertions**:
- Segmentation config created successfully
- Segmentation job completes (status `completed`)
- Document is segmented into multiple child segments
- Segment parent references are correct (via edges)
- Segment vectors have correct dimensions (384)
- Semantic search returns relevant segments (not irrelevant ones)
- Cleanup cascades properly (deleting parent removes segments)

**Fixture pattern**:
```python
DOC_TYPE = "urn:kgdoctype:test_article"
SEG_METHOD = "urn:segmethod:plain_recursive_split"

CLIMATE_ARTICLE = """
Global temperatures have risen by approximately 1.1°C above pre-industrial
levels. Ocean temperatures are increasing, leading to coral bleaching and
rising sea levels that threaten coastal communities worldwide.

Renewable energy adoption has accelerated dramatically. Solar panel
efficiency has improved from 15% to over 25% in commercial installations.
Wind turbine capacity factors now exceed 50% in optimal locations, making
wind power cost-competitive with fossil fuels.

Carbon capture and storage technologies are being deployed at scale.
Direct air capture facilities can now remove CO2 at costs below $200 per
tonne, though significant scaling is needed to impact global emissions.
"""
```

### 3.3 Large Batch Import → SPARQL Query (WordNet Frames)

**Goal**: Verify that a large N-Triples file can be imported via the
import job API, that the data is fully queryable via SPARQL and entity
listing after import completes, and that auxiliary tables (edge, stats)
are correctly synced.

| Item | Detail |
|------|--------|
| **File** | `tests/api/test_wordnet_import_integration.py` (new) |
| **Priority** | High |
| **Data source** | `test_data/kgframe-wordnet-0.0.1.nt` (~7M triples, KGFrame WordNet) |

**Steps**:

1. Create a dedicated test space (e.g. `wn_import_test`)
2. Create an import job with `mode=APPEND`,
   `graph_uri="http://vital.ai/graph/kgwordnetframes"`
3. Upload `test_data/kgframe-wordnet-0.0.1.nt` to the import job
4. Execute the import job
5. Poll job status until `COMPLETED` (timeout ~5 min for 7M triples)
6. Verify triple count — SPARQL `SELECT (COUNT(*) AS ?c) WHERE { ?s ?p ?o }` in graph
   should return ~7M
7. Verify entity listing — `list_kgentities` should return entities
   with correct kGEntityType URIs from the WordNet data
8. Run a representative SPARQL query that exercises the edge table
   (e.g. find frames with a specific synset relation):
   ```sparql
   SELECT ?frame ?slot ?value WHERE {
     ?frame a <http://vital.ai/ontology/haley-ai-kg#KGFrame> .
     ?frame <http://vital.ai/ontology/haley-ai-kg#hasKGSlot> ?slot .
     ?slot <http://vital.ai/ontology/haley-ai-kg#kGSlotValue> ?value .
   } LIMIT 20
   ```
9. Verify stats tables are populated — at least predicate stats rows exist
10. Run a second SPARQL query for a specific WordNet word (e.g. "happy")
    to verify term-level fidelity
11. Export the graph to N-Triples via an export job
12. Verify exported file is non-empty and triple count matches import count
13. Delete the test space (cleanup)

**Assertions**:
- Import job completes without error
- Triple count matches expected (~7M)
- SPARQL queries return correct frame/slot/value triples
- Entity listing returns entities with correct types
- Edge and stats auxiliary tables are synced (non-zero row counts)
- Export round-trips the data (export triple count ≈ import triple count)
- Space deletion cleans up all tables

**Performance baseline** (informational, not hard assertion):
- Bulk path: drop indexes → COPY terms → COPY quads (50k batches) →
  recreate indexes → resync aux tables.  Should complete in under 60s
  for 7M triples.
- Incremental path (REST API): INSERT ON CONFLICT in 5k batches, no
  index drops.  Slower but production-safe.  Expect ~2–5 min for 7M.
- SPARQL query response under 500ms after import

**Notes**:
- This test is heavy (~7M triples) and should be marked with a
  `pytest.mark.slow` marker so it can be excluded from fast CI runs
- The `test_data/kgframe-wordnet-0.0.1.nt` file is already in the repo
- A lighter variant could use `kgentity_wordnet.nt` (~2.8M triples) instead

### 3.4 Geo Search End-to-End — Entity Create → Geo Populate → Radius Search ✅ IMPLEMENTED

> **Status**: Implemented (Jul 2026). 13/13 tests passing.

| Item | Detail |
|------|--------|
| **File** | `tests/api/test_geo_search_integration.py` |
| **Tests** | 13 |
| **Steps** | Enable geo config (auto_sync) → create 4 KGEntities with KGGeoLocationSlot (WKT POINT) → wait for geo population → radius searches at increasing distances → verify distance ordering → slot-level geo queries → dual-entry verification |

**Test classes**:
- `TestGeoPopulation` (2 tests): Verify geo points populated via auto_sync, verify point count
- `TestGeoKGQuery` (7 tests): Radius searches at 10km/200km/400km/6000km, distance ordering, graph filter, sort consistency
- `TestGeoSlotTarget` (3 tests): Slot-level geo query with `geo_target="slot"` + frame_criteria, slot-level distance ordering, entity-level backward compat with `geo_target="entity"`
- `TestGeoDualEntry` (1 test): Verify geo table has 2× entries (both slot-keyed and entity-keyed rows)

**Key implementation details**:
- Uses `KGGeoLocationSlot` domain objects with WKT POINT values (not raw lat/lon properties)
- Requires `hasKGSlotType` explicitly set on slot objects for SPARQL pattern matching
- Exercises dual-entry geo architecture: slot-keyed rows for `vg:geoDistance(?slot, ...)` and entity-keyed rows for `vg:geoDistance(?entity, ...)`
- See `planning/planning_cleanup/geo_query_architecture_plan.md` for full architecture

**Known distances** (for assertion thresholds):
- Bristol → London: ~190 km
- Bristol → Paris: ~470 km
- Bristol → New York: ~5,300 km
- London → Paris: ~340 km

### 3.5 Staged Bulk Import via UNLOGGED Tables

See **`planning/planning_cleanup/import_staging_table_plan.md`** for the
full plan to review, modernize, and integrate the archived UNLOGGED
staging table import path as a third import mode (`ImportMode.STAGED`).

---

## 4. Coverage Gaps to Consider

| Gap | Notes |
|-----|-------|
| **Concurrent write + search** | No test for search consistency during concurrent entity writes |
| **Large batch import → search** | Covered by §3.3 above |
| **SPARQL federation across spaces** | Spaces are independent, but as SPARQL servers they can be federated via SERVICE clauses — no test for cross-space federated queries |
