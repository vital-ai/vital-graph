# Document Segmentation End-to-End Test Plan

## 1. Objective

Create `tests/api/test_document_segmentation_search_integration.py` — an end-to-end
integration test that exercises the full KGDocument lifecycle:

**Document Create → Auto-Segmentation → Vector Embedding → Semantic Search**

This is the last major untested pipeline in the system. All server-side components
are implemented (see `planning/planning_kgdocument/kgdocument_plan.md` §11).

---

## 2. Architecture Reference

### Three-Tier Segmentation Model

```
Original KGDocument (never modified)
    │
    ├── Edge_hasKGDocumentSegment ──→ Parent Copy (segType=segmentation_parent)
    │                                      │
    │                                      ├── Edge_hasKGDocumentSegment ──→ Segment 1
    │                                      ├── Edge_hasKGDocumentSegment ──→ Segment 2
    │                                      └── Edge_hasKGDocumentSegment ──→ Segment N
```

### Key Server Components

| Component | File | Role |
|-----------|------|------|
| Config manager | `vitalgraph/document/segmentation_config_manager.py` | Stores document_type → segment_method mappings |
| Auto-segmentation hook | `vitalgraph/document/auto_segmentation.py` | Fires on document CRUD when type matches a config |
| Segmentation processor | `vitalgraph/document/kgdocument_segmentation_processor.py` | Three-tier split: original → parent copy → segments |
| Job manager | `vitalgraph/document/segmentation_job_manager.py` | Queue table for async segmentation jobs |
| Background worker | `vitalgraph/document/segmentation_worker.py` | Processes pending jobs (LISTEN/NOTIFY) |
| Vector index setup | `vitalgraph/document/vector_index_setup.py` | Creates `document_segments` HNSW index |
| Client endpoint | `vitalgraph/client/endpoint/kgdocuments_endpoint.py` | All client methods for docs + segmentation |

### Segmentation Methods

| URI | Description |
|-----|-------------|
| `urn:segmethod:plain_recursive_split` | Splits at `\n\n` → `\n` → `. ` → ` ` → hard-chunk |
| `urn:segmethod:markdown_heading_split` | Splits at `#{1-3}` headings, recursively sub-splits oversized sections |

### Vector Configuration

**Production defaults** (OpenAI):

| Setting | Value |
|---------|-------|
| Index name | `document_segments` |
| Dimensions | 1536 |
| Provider | `openai` |
| Model | `text-embedding-3-small` |
| Mapping type | `kgdocument_segment` |
| Source type | `default` |

**Local testing** (override for tests without API key):

| Setting | Value |
|---------|-------|
| Dimensions | 384 |
| Provider | `vitalsigns` |
| Model | `paraphrase-multilingual-MiniLM-L12-v2` |
| max_segment_tokens | 128 (fits MiniLM 128-token input window) |

---

## 3. Test Steps (Detailed)

### 3.1 Setup Phase

```python
# 1. Create segmentation config
config = await vg_client.kgdocuments.create_segmentation_config(
    space_id=test_space,
    document_type_uri="urn:kgdoctype:test_article",
    segment_method_uri="urn:segmethod:plain_recursive_split",
    max_segment_tokens=128,   # small to force multiple segments
    min_segment_tokens=20,
    overlap_tokens=0,
    enabled=True,
    auto_vectorize=True,
)

# 2. Create vector index (or use auto-created document_segments)
idx = await vg_client.vector_indexes.create_index(
    space_id=test_space,
    index_name="document_segments",
    dimensions=384,
    distance_metric="cosine",
    provider="vitalsigns",
    model_name="paraphrase-multilingual-MiniLM-L12-v2",
    description="Test segment embeddings",
)

# 3. Create search mapping
mapping = await vg_client.search_mappings.create_mapping(
    space_id=test_space,
    index_name="document_segments",
    mapping_type="kgdocument_segment",
    enabled=True,
    source_type="default",
)

# 4. Attach index to mapping
await vg_client.search_mappings.add_index(
    space_id=test_space,
    mapping_id=mapping.mapping_id,
    index_type="vector",
    index_name="document_segments",
)
```

### 3.2 Document Ingest Phase

```python
from ai_haley_kg_domain.model.KGDocument import KGDocument

doc = KGDocument()
doc.URI = f"urn:test:doc:{uuid.uuid4().hex[:12]}"
doc.name = "Climate and Energy Article"
doc.kGDocumentType = "urn:kgdoctype:test_article"
doc.kGDocumentContent = CLIMATE_ARTICLE   # ~300 words, 3 distinct topics
doc.kGraphDescription = CLIMATE_ARTICLE   # vectorization text

# 5. Create via client
resp = await vg_client.kgdocuments.create_kgdocuments(
    test_space, test_graph, [doc]
)
assert resp.is_success
```

### 3.3 Polling Phase

```python
# 6. Poll segmentation status
for _ in range(30):
    await asyncio.sleep(2.0)
    status = await vg_client.kgdocuments.get_segmentation_status(
        space_id=test_space,
        document_uri=doc.URI,
    )
    # Check if completed
    jobs = status.get("jobs", [])
    if any(j.get("status") == "completed" for j in jobs):
        break

# 7. List segments
segments = await vg_client.kgdocuments.list_segments(
    test_space, test_graph, parent_uri=doc.URI
)
assert segments.count > 1
```

### 3.4 Vectorization Phase

```python
# 8. Trigger reindex for segments
await vg_client.vector_indexes.reindex(
    space_id=test_space,
    index_name="document_segments",
    graph_uri=test_graph,
    mapping_type="kgdocument_segment",
)

# 9. Poll vectors
for _ in range(30):
    await asyncio.sleep(2.0)
    vecs = await vg_client.vector_indexes.get_vectors(
        space_id=test_space,
        index_name="document_segments",
        graph_uri=test_graph,
    )
    if vecs.total_count >= segments.count:
        break

# 10. Verify dimensions
assert len(vecs.vectors[0].embedding) == 384
```

### 3.5 Search Phase

**IMPORTANT**: The `query_connections` endpoint (KGQuery) generates SPARQL with
`vitaltype` filters targeting KGEntity subclasses. KGDocument segments are NOT
KGEntities — they are KGNode/KGDocument objects. Therefore, semantic search for
document segments **must use raw SPARQL** with `vg:vectorSimilarity`.

```python
from vitalgraph.model.sparql_model import SPARQLQueryRequest

# 11. SPARQL vector similarity search for renewable energy content
sparql = '''
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?segment ?score ?content WHERE {
    BIND(vg:vectorSimilarity(?segment, "solar panel efficiency renewable energy", "document_segments") AS ?score)
    FILTER(?score > 0.0)
    ?segment haley:hasKGDocumentContent ?content .
}
ORDER BY DESC(?score)
LIMIT 5
'''
req = SPARQLQueryRequest(query=sparql)
resp = await vg_client.sparql.execute_sparql_query(space_id=test_space, request=req)
bindings = (resp.results or {}).get("bindings", [])
assert len(bindings) > 0
top_content = bindings[0]["content"]["value"].lower()
assert "solar" in top_content or "renewable" in top_content

# 12. Search for climate content (same SPARQL pattern, different search text)
sparql2 = '''
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?segment ?score ?content WHERE {
    BIND(vg:vectorSimilarity(?segment, "ocean temperature coral bleaching sea level", "document_segments") AS ?score)
    FILTER(?score > 0.0)
    ?segment haley:hasKGDocumentContent ?content .
}
ORDER BY DESC(?score)
LIMIT 5
'''
req2 = SPARQLQueryRequest(query=sparql2)
resp2 = await vg_client.sparql.execute_sparql_query(space_id=test_space, request=req2)
bindings2 = (resp2.results or {}).get("bindings", [])
assert len(bindings2) > 0
top_content2 = bindings2[0]["content"]["value"].lower()
assert "ocean" in top_content2 or "temperature" in top_content2
```

### 3.6 Cleanup Phase

```python
# 13. Delete document (cascades to parent copy + segments)
await vg_client.kgdocuments.delete_kgdocument(test_space, test_graph, doc.URI)

# Delete mapping, index, config
await vg_client.search_mappings.delete_mapping(test_space, mapping.mapping_id)
await vg_client.vector_indexes.delete_index(test_space, "document_segments")
await vg_client.kgdocuments.delete_segmentation_config(
    test_space, config["config_id"]
)
```

---

## 4. Test Data

```python
CLIMATE_ARTICLE = """
Global temperatures have risen by approximately 1.1 degrees Celsius above
pre-industrial levels. Ocean temperatures are increasing dramatically, leading
to widespread coral bleaching events and rising sea levels that threaten
coastal communities around the world. Arctic ice sheets are melting at
unprecedented rates, contributing to sea level rise projections of up to
one meter by 2100.

Renewable energy adoption has accelerated significantly in the past decade.
Solar panel efficiency has improved from 15 percent to over 25 percent in
commercial installations. Wind turbine capacity factors now routinely exceed
50 percent in optimal locations, making wind power cost-competitive with
natural gas and coal. Battery storage technology has dropped in price by
over 80 percent since 2010.

Carbon capture and storage technologies represent a third pillar of climate
mitigation. Direct air capture facilities can now remove carbon dioxide at
costs below 200 dollars per tonne. Underground geological sequestration has
proven safe in multiple pilot projects. However, significant scaling of these
technologies is needed to meaningfully impact global emissions trajectories.
"""
```

Using `max_segment_tokens=128` with this ~200-word text should produce 3+ segments,
each roughly corresponding to one paragraph/topic.

---

## 5. Test Classes / Methods

| Class | Method | Assertion |
|-------|--------|-----------|
| `TestDocumentSegmentation` | `test_segmentation_completes` | Job status reaches `completed` |
| `TestDocumentSegmentation` | `test_segments_created` | Segment count >= 3 |
| `TestDocumentSegmentation` | `test_segment_content` | Each segment has non-empty content |
| `TestDocumentSegmentation` | `test_segment_parent_edges` | `Edge_hasKGDocumentSegment` edges exist |
| `TestSegmentVectorization` | `test_vectors_populated` | Vector count >= segment count |
| `TestSegmentVectorization` | `test_embedding_dimensions` | All embeddings are 384-dim |
| `TestSegmentSemanticSearch` | `test_search_renewable_energy` | "solar"/"renewable" segment ranks first |
| `TestSegmentSemanticSearch` | `test_search_climate_ocean` | "ocean"/"temperature" segment ranks first |
| `TestSegmentSemanticSearch` | `test_search_carbon_capture` | "carbon"/"capture" segment ranks first |
| `TestSegmentCleanup` | `test_delete_cascades` | Deleting original removes all segments |

---

## 6. Prerequisites / Blockers

| Item | Status | Notes |
|------|--------|-------|
| Segmentation config CRUD | ✅ Done | `test_kgdocuments_api.py` already tests this |
| Auto-segmentation hook | ⚠️ Partial | Hook class exists but is NOT wired into endpoint (see §9) |
| Background worker | ✅ Done | Auto-started in `vitalgraphapp_impl.py` |
| Vector index for segments | ✅ Done | `vector_index_setup.py` creates `document_segments` |
| `list_segments` client method | ✅ Done | Returns `KGDocumentSegmentsResponse` |
| `get_segmentation_status` client | ✅ Done | Returns job list with status |
| `mapping_type="kgdocument_segment"` | ✅ Done | Supported in vector_populator |
| KGDocument domain model | ✅ Done | `ai_haley_kg_domain.model.KGDocument` |

**No blockers identified.** Test can be implemented immediately.

---

## 7. Risks / Open Questions

1. **Worker timing**: The segmentation worker uses LISTEN/NOTIFY for instant wake.
   In test environments, there may be a delay if the worker isn't running.
   The polling loop (30 iterations × 2s = 60s timeout) should handle this.

2. **`source_type="default"` behavior**: Need to verify what text the vector
   populator extracts for `kgdocument_segment` + `source_type="default"`. It
   should use `kGraphDescription` (set to segment content by the processor).

3. **Cascade delete**: Verify that `delete_kgdocument` correctly cascades to
   parent copies and segments. The plan says it does (§5.6 in kgdocument_plan),
   but this hasn't been tested end-to-end.

4. **Search result format**: ~~The `query_connections` endpoint returns entities.~~
   **RESOLVED**: `query_connections` (KGQuery) only works for KGEntity objects.
   KGDocument segments must be searched via raw SPARQL using
   `vg:vectorSimilarity(?segment, "text", "index_name")` with a triple pattern
   on `haley:hasKGDocumentContent`. This returns SPARQL bindings, not entity objects.

---

## 9. Implementation Gaps Discovered

### 9.1 Auto-Segmentation Hook Not Wired Into Endpoint

**Plan says** (kgdocument_plan.md §5.4, line 893):
> Create: Store KGDocument quads → check segmentation config → if auto-segment
> enabled, call `AutoSegmentationHook.on_document_upsert()`

**Actual implementation**: The `_create()` method in
`vitalgraph/endpoint/kgdocuments_endpoint.py` (line 1017-1019) calls
`_schedule_auto_sync()` which delegates to `vectorization/auto_sync.py`.
That module handles vector/geo/fuzzy/FTS sync only — it does **NOT** call
`AutoSegmentationHook` or enqueue a segmentation job.

The `AutoSegmentationHook` class exists in `vitalgraph/document/auto_segmentation.py`
but is never imported or called from any endpoint or auto_sync path.

**Impact on test**: The e2e test must use the explicit `segment_document()` client
method to trigger segmentation manually after document creation:

```python
await vg_client.kgdocuments.segment_document(
    space_id=test_space,
    graph_id=test_graph,
    document_uri=doc_uri,
    segment_method_uri="urn:segmethod:plain_recursive_split",
    max_segment_tokens=128,
)
```

**To fix (future work)**: Wire `AutoSegmentationHook.on_document_upsert()` into
`_create()` and `_update()` in `kgdocuments_endpoint.py`, or add a segmentation
check to `auto_sync.py`. This would require:
1. Loading the segmentation config for the space
2. Checking if the document's `kGDocumentType` matches any enabled config
3. Enqueuing a segmentation job via `_enqueue_segmentation_job()`

### 9.2 Semantic Search Requires Raw SPARQL for KGDocuments

**Plan assumed**: `query_connections` with `VectorSearchCriteria` would work.

**Actual behavior**: `query_connections` uses `query_type="entity"` which generates
SPARQL with `?entity vital:vitaltype ?type` patterns that filter for KGEntity
subclasses only. KGDocument segments have `vitaltype = KGDocument`, which is NOT
a KGEntity subclass — it's a direct KGNode subclass.

**Resolution**: Use the SPARQL endpoint directly with `vg:vectorSimilarity`:
```sparql
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?segment ?score ?content WHERE {
    BIND(vg:vectorSimilarity(?segment, "search text", "document_segments") AS ?score)
    FILTER(?score > 0.0)
    ?segment haley:hasKGDocumentContent ?content .
}
ORDER BY DESC(?score)
LIMIT 10
```

This works because `vg:vectorSimilarity` is a custom function that directly queries
the vector index by name — it does not rely on vitaltype filtering.

**UPDATE (July 2026)**: `query_type="document"` has been implemented in the
KGQuery endpoint (Phase 20). The client convenience method is
`vg_client.kgqueries.query_documents()`. Raw SPARQL is still needed for
custom search patterns but the standard query path now works for documents.

---

## 8. Implementation Status

**Status: ✅ COMPLETE** (July 2026)

| Item | Status |
|------|--------|
| E2e test file | `tests/api/test_document_segmentation_search_integration.py` — ✅ implemented |
| Wikipedia e2e test | `tests/api/test_wikipedia_document_e2e.py` — ✅ 31 passed, 1 skipped (83s) |
| Config CRUD tests | `tests/api/test_kgdocuments_api.py::TestSegmentationConfigCrud` — ✅ updated to typed responses |
| Trigger/status tests | `tests/api/test_kgdocuments_api.py::TestSegmentationTriggerAndStatus` — ✅ updated to typed responses |
| Client typed responses | `client_response.py` — 5 new classes (`SegmentDocumentClientResponse`, `SegmentationStatusClientResponse`, `SegmentationConfigClientResponse`, `SegmentationConfigListClientResponse`, `SegmentationConfigDeleteClientResponse`) |
| Client endpoint methods | `kgdocuments_endpoint.py` — all 6 segmentation methods return typed responses |
| Server Pydantic models | `kgdocuments_model.py` — `max_segment_tokens` default updated 512→1024 |
| Default vector provider | OpenAI `text-embedding-3-small` (1536d) for production; local `vitalsigns` (384d) for CI |
| `query_type="document"` | KGQuery endpoint Phase 20 — ✅ implemented |
| Issue #014 | Connection pool leak in segmentation endpoints — ✅ fixed |
| Issue #015 | `vg:vectorSimilarity` unresolved subject variable — ✅ fixed (Pattern 4 deferred UUID) |
| Issue #016 | `search_text` headline-only filter — ✅ fixed (FTS + CONTAINS fallback) |

### 8.1 Wikipedia E2E Test Results (July 4 2026)

`tests/api/test_wikipedia_document_e2e.py` — **31 passed, 1 skipped** in 83s.

Tests 3 full Wikipedia articles (AI, Solar System, Coffee) through the complete
pipeline: ingest → segmentation → vectorization → query.

Key outcomes:
- **150 segments** across 3 articles via `markdown_heading_split`
- **Inline vectorization** by segmentation worker (vectors ready ~2s after segmentation)
- **No redundant reindex** — worker vectorizes inline, explicit reindex removed
- **FTS search** via `vg:textSearch` with GIN index (BM25 ranking)
- **Parent document query** correctly traverses two-hop edges (original → parent → segment)

### 8.2 Fixes Applied During Wikipedia E2E Testing

| Fix | File | Description |
|-----|------|-------------|
| B-tree → hash index | `sparql_sql_schema.py` | `term_text` index changed to hash (no size limit) |
| Silent failure on 0 quads | `kg_backend_utils.py` | `store_objects` reports failure instead of success |
| Parent document query | `kg_query_builder.py` | Two-hop UNION for `parent_document_uri` |
| `get_vectors` pagination | `vector_indexes_endpoint.py` | True `total_count` + `page_size`/`offset` |
| FTS `search_text` | `kg_query_builder.py` | `fts_index_name` → `vg:textSearch`; CONTAINS fallback |
| FTS index in test | `test_wikipedia_document_e2e.py` | Creates FTS index + attaches to mapping |
| Migration script | `apps/migrate_term_index_to_hash.py` | Standalone btree→hash migration for existing spaces |

### 8.3 Vectorization Phase Updated

**Original plan** (§3.4) called for explicit reindex after segmentation:
```python
await vg_client.vector_indexes.reindex(...)  # No longer needed
```

**Actual behavior**: The segmentation worker calls `_schedule_vectorization()`
inline after storing segments. This invokes `auto_sync.schedule_sync()` which
vectorizes each segment immediately. No explicit reindex is required — the test
polls `get_vectors` and vectors appear within ~2s of segmentation completing.

The `get_vectors` endpoint now returns a true `total_count` (via COUNT(*) query)
independent of the paginated result set, with proper `page_size`/`offset` support.

### 8.4 Text Search Updated

**Original plan**: Assumed `CONTAINS(LCASE(...))` on `hasKGDocumentHeadline`.

**Actual behavior**: `DocumentSearchCriteria.search_text` now supports two modes:
1. **FTS mode** (`fts_index_name` set): Emits `BIND(vg:textSearch(?entity, "text", "index") AS ?_fts_score)` — uses GIN tsvector index, BM25 ranking, language stemming
2. **Fallback mode** (no `fts_index_name`): OPTIONAL on headline + content with `CONTAINS(LCASE(COALESCE(...)))` — brute-force scan, no ranking

The test fixture creates an FTS index (`document_segments`) and attaches it to the
search mapping alongside the vector index. Auto-sync populates both.

---

## 9. Related Docs

- `planning/planning_kgdocument/kgdocument_plan.md` — full architecture + implementation status (Phases 20–22)
- `planning/planning_visualization/btree_term_index_plan.md` — hash index fix plan + implementation status
- `planning/planning_cleanup/integration_workflow_tests_plan.md` §3.2 — summary entry
- `vitalgraph/document/vector_index_setup.py` — index constants
- `tests/api/test_kgdocuments_api.py` — config CRUD + status tests
- `tests/api/test_document_segmentation_search_integration.py` — full e2e test
- `tests/api/test_wikipedia_document_e2e.py` — Wikipedia 3-article e2e test
- `apps/migrate_term_index_to_hash.py` — standalone btree→hash migration script
- `issues/014_segmentation_endpoint_sync_fallback_hang.md` — connection leak fix
- `issues/015_vector_similarity_unresolved_subject_variable.md` — UUID deferral fix
- `issues/016_document_search_text_headline_only.md` — FTS search_text fix
