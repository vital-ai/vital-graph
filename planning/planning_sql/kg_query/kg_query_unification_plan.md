# KG Query Unification Plan

## Status: Phases 1-3 + 2b Complete — All Tests Green

**Date**: 2026-04-23 (updated 2026-04-23)

---

## Problem Statement

There are currently **three overlapping systems** that query entities with frame/slot criteria, each returning different response shapes. This causes confusion for both portal developers and API consumers about which endpoint to use and what to expect back.

### Current Architecture

#### 1. Entity Query — `POST /api/graphs/kgentities/query`

| Layer | Location | Notes |
|-------|----------|-------|
| Server endpoint | `kgentities_endpoint.py:255-265` | Route on `KGEntitiesEndpoint`, calls `_query_kgentities` |
| Server impl | `kgentities_endpoint.py:1782-1840` | Uses `KGSparqlQueryProcessor` → fetches full entity objects → returns `QuadResponse` |
| SPARQL builder | `kg_query_builder.py` → `build_entity_query_sparql` | Paginated SPARQL with LIMIT/OFFSET |
| Count query | `kg_query_builder.py` → `build_entity_count_query_sparql` | ✅ Now includes frame criteria |
| Request model | `EntityQueryRequest` (criteria + page_size + offset) | |
| Response model | `QuadResponse` (serialized quads, not URIs) | Returns full serialized entity objects |
| Client method | `kgentities_endpoint.py:1037-1102` → `query_entities()` | Deserializes quads into `GraphObjects` |

**Response shape**: Full serialized entity objects as quads. Heavy payload.

#### 2. Connection Query — `POST /api/graphs/kgqueries`

| Layer | Location | Notes |
|-------|----------|-------|
| Server endpoint | `kgquery_endpoint.py:61-86` | Route on `KGQueriesEndpoint` |
| Server impl | `_execute_frame_query` / `_execute_relation_query` / `_execute_entity_query` | Three separate code paths by `query_type` |
| Request model | `KGQueryRequest` with `KGQueryCriteria(query_type="frame"\|"relation"\|"entity")` | |
| Response model | `KGQueryResponse` with `frame_connections` or `relation_connections` or `entity_uris` | |
| Client methods | `kgqueries_endpoint.py:97-265` | `query_frame_connections()`, `query_relation_connections()`, `query_entities()` |

**Response shapes**:
- `query_type="relation"`: `relation_connections` — `[{source_uri, dest_uri, relation_edge_uri, relation_type_uri}]`
- `query_type="frame"`: `frame_connections` — `[{source_uri, dest_uri, shared_frame_uri, frame_type_uri}]`
- `query_type="entity"`: `entity_uris` — `["urn:...", "urn:..."]` + `total_count` (NEW, just added)

#### 3. Legacy path — `kgentity_query_endpoint_impl.py`

| Layer | Location | Notes |
|-------|----------|-------|
| Impl | `kgentity_query_endpoint_impl.py:20-116` | `query_entities_impl()` — returns `EntityQueryResponse` (URIs only) |
| Response model | `EntityQueryResponse(entity_uris=[], total_count=...)` | Just URIs, no full objects |

Not wired to any active endpoint. Dead code.

### The Confusion

The **frame query** (`query_type="frame"` on `/kgqueries`) is being misused for what is really a **plain entity query with frame criteria filtering**. It:

1. Takes `EntityQueryCriteria` with `frame_criteria`
2. Runs `build_entity_query_sparql` (the entity query builder, **not** the connection query builder)
3. Returns entities stuffed into `FrameConnection(source_entity_uri=entity_uri, destination_entity_uri="", shared_frame_uri="", frame_type_uri=...)` — **fake connection objects**

Meanwhile, the **real entity query** at `/kgentities/query` returns full `QuadResponse` with serialized entity objects — a completely different response format.

The portal calls `query_frame_connections` when it really just wants to **search entities by criteria**.

---

## Three Query Cases

The three cases are distinguished by what serves as the **top-most object** in the query:

### Case 1: Frame as top-most object

```
         Frame (top-most)
        /     |      \
EntitySlot  EntitySlot  TextSlot
   |            |          |
 Entity-A    Entity-B    "details"
```

The **frame** is the central object. It models a **complex relationship between entities** — the entity slots point to the participating entities while the frame's own slots and child frames capture the details of the relationship.

This is richer than a simple edge: a frame can hold multiple slots describing the relationship (e.g. role, start date, weight) and can have child frames for nested structure.

**Query pattern**: Find frames matching criteria, where entity slots point to specific entities.

**Example** — an EmploymentFrame connecting a person and a company:
```
EmploymentFrame
  → PersonSlot (KGEntitySlot) eq <urn:person:marc>
  → CompanySlot (KGEntitySlot) eq <urn:company:acme>
  → RoleSlot (KGTextSlot) = "Engineer"
  → StartDateSlot (KGDateTimeSlot) = "2024-01-15"
```

**Implementation**: `_get_slot_value_property()` in `kg_query_builder.py` handles `KGEntitySlot` → `haley:hasEntitySlotValue` and `KGURISlot` → `haley:hasUriSlotValue`. `build_frame_query_sparql` exists for frame-centric queries.

**Endpoint**: New `query_type="frame_query"` on `/kgqueries` (separate from existing `query_type="frame"` which is misused for entity search and must not be broken).

**Response shape**: Each result is a frame URI plus the entity URIs connected to that frame (via entity slots). Optionally includes the full frame graph objects.

```python
# Proposed response model:
class EntitySlotRef(BaseModel):
    slot_type_uri: str   # e.g. "urn:ontology#PersonSlot" — identifies the role
    entity_uri: str      # e.g. "urn:entity:sam-altman"

class FrameQueryResult(BaseModel):
    frame_uri: str                           # The matching frame
    frame_type_uri: str                      # e.g. "urn:ontology#EmploymentFrame"
    entity_refs: List[EntitySlotRef]          # Entities + their slot roles
    frame_graph: Optional[Any] = None        # Structured frame data (when include_frame_graph=True)

# On KGQueryResponse:
frame_results: Optional[List[FrameQueryResult]] = None
```

The `entity_refs` list preserves which slot type points to which entity, so the caller can distinguish roles (e.g. PersonSlot vs CompanySlot) without needing the full frame graph.

When `include_frame_graph=True`, `frame_graph` contains the full structured frame with all slots (entity + detail), child frames, and values.

**Status**: ✅ **Complete.** `query_type="frame_query"` handler, `FrameQueryResult` response shape, `query_frames()` client method, entity slot refs with `slot_type_uri`, `frame_type_uri` populated from `hasKGFrameType`. Tested on WordNet (285k frames). Edge-based slot pattern (`hasEdgeSource`/`hasEdgeDestination`) used throughout — `kGFrameSlotFrame` fully replaced.

### Case 2: Entity as top-most object

```
       Entity (top-most)
      /       |        \
  Frame-A   Frame-B   Frame-C
    |          |         |
  Slots      Slots     Slots
```

The **entity** is the central object. Information is localized within the entity graph — frames and slots describe the entity's properties without any direct cross-entity or cross-frame linkages.

This is the most common query pattern. The portal's primary use case: "show me leads in California" or "show me MQL leads."

**Query pattern**: Find entities matching frame/slot criteria within their own entity graph.

**Example** — find leads in California:
```
KGEntity (Lead)
  → CompanyFrame
    → CompanyAddressFrame
      → CompanyStateCode (KGTextSlot) eq "CA"
```

**Slot value types supported**: Text, Boolean, Double, Integer, DateTime.

**Status**: ✅ Fully tested. Lead dataset, multi-org dataset. All slot types covered.

### Case 3: Relation (Edge_hasKGRelation) as top-most object

```
 Entity-A  --Edge_hasKGRelation(type)--> Entity-B
    |                                       |
  Frames/Slots                          Frames/Slots
  (optional filter)                     (optional filter)
```

The **relation edge** is the central object. It handles simple directed edges between top-most entities. Each side can optionally be filtered by frame/slot criteria on the connected entity.

**Query pattern**: Find relation edges by type, with optional frame criteria on source and/or destination entities.

**Example** — simple relation:
```
Marc --lives-in--> Brooklyn
```

**Example** — relation with frame criteria on both sides:
```
Org1 --MakesProduct--> Product1
  Org1 → IndustryFrame → IndustryType eq "Technology"
  Product1 → ProductFrame → Category eq "Software"
```

**Implementation**: `kg_connection_query_builder.py` — `_build_source_frame_patterns()` / `_build_destination_frame_patterns()`. `KGQueryCriteria` model has `source_frame_criteria` and `destination_frame_criteria` fields.

**Status**:
- Simple relation (type + direction only): ✅ Tested via multi-org and WordNet datasets
- Relation + frame criteria on both sides: ✅ **Tested** — 8/8 tests passing (industry filter, employee count gt, both-sides filter, city contains, combined criteria)

---

## Current Implementation Status

### What exists and works

| Case | Server | Client | Tests | Status |
|------|--------|--------|-------|--------|
| Case 1 (frame query) | ✅ `_execute_frame_query_case` with `frame_type_uri` + `entity_refs` | ✅ `kgqueries.query_frames()` | ✅ WordNet (10/10) | **Complete** |
| Case 2 (text/boolean/numeric slot) | ✅ `_execute_entity_query` with `include_entity_graph` | ✅ `kgqueries.query_entities(include_entity_graph=True)` | ✅ Lead (entity graph verified) | **Complete** |
| Case 3 (relation + frame criteria) | ✅ `_build_source/dest_frame_patterns` | ✅ `kgqueries.query_relation_connections()` | ✅ Multi-org (8/8) | **Complete** |

### What needs improvement

1. ~~**Case 1 (frame query) has no endpoint**~~ → ✅ Done. `query_type="frame_query"` added.
2. ~~**Case 1 entity-ref slot untested**~~ → ✅ Done. 10/10 tests on WordNet with `KGEntitySlot` + `slot_class_uri`.
3. ~~**Case 3 (relation + frame criteria) untested**~~ → ✅ Done. 8/8 tests on multi-org dataset.
4. ~~**No `include_entity_graph` on entity query**~~ → ✅ Done. Single batched SPARQL via `hasKGGraphURI` + `VALUES`. Returns property maps grouped by entity URI.
5. **Client typing is confusing** — `query_frame_connections()` is really being used for entity queries; `query_entities()` exists on both `kgentities` and `kgqueries` with completely different return types

---

## Proposed Changes

### Phase 1: Frame Query Case (Priority: High)

**Goal**: Add `query_type="frame_query"` as a new, clean path for Case 1 — querying with the frame as the top-most object.

This is a **new query_type**, separate from `query_type="frame"` which continues to work as-is (even though it's misused for entity search).

#### 1a. Server handler for `query_type="frame_query"`

Add `_execute_frame_query_case()` to `kgquery_endpoint.py`:

```python
async def _execute_frame_query_case(self, backend, space_id, graph_id, query_request):
    # Uses build_frame_query_sparql with entity-slot criteria
    # Returns frame_uris + total_count
    # Optionally fetches structured frame graphs
    pass
```

**Request model**: Reuse `KGQueryCriteria` with `query_type="frame_query"`. Frame criteria with `SlotCriteria` where `slot_class_uri` is `KGEntitySlot` or `KGURISlot`.

Add `include_frame_graph: bool = False` to `KGQueryRequest` (symmetric with `include_entity_graph`). When true, the response includes structured frame data for each matching frame.

**Response fields** (added to `KGQueryResponse`):
```python
frame_results: Optional[List[FrameQueryResult]] = None  # Each: {frame_uri, frame_type_uri, entity_refs[], frame_graph?}
```

#### 1b. Client method

Add `query_frames()` to `kgqueries_endpoint.py`:

```python
async def query_frames(
    self,
    space_id: str,
    graph_id: str,
    frame_type: Optional[str] = None,
    slot_criteria: Optional[List[SlotCriteria]] = None,
    include_frame_graph: bool = False,
    page_size: int = 10,
    offset: int = 0
) -> KGQueryResponse:
```

### Phase 2: Entity Query Enhancement (Priority: High)

**Goal**: Make `query_type="entity"` the clean, primary path for entity search.

#### 2a. Add `include_entity_graph` parameter

Add `include_entity_graph: bool = False` to `KGQueryRequest`. When true, the entity query path fetches full entity graphs for the returned URIs and includes them in the response.

**Server implementation** (`kgquery_endpoint.py`):
```python
# After getting entity_uris from SPARQL:
if query_request.include_entity_graph and entity_uris:
    # Use kGGraphURI property to efficiently fetch all quads for each entity graph
    # This is a single SPARQL query per entity using the graph membership property
    entity_graphs = await self._fetch_entity_graphs(backend, space_id, graph_id, entity_uris)
```

**Performance note**: Entity graph membership is stored as a property (`hasKGGraphURI`), so fetching all quads for an entity graph is a single indexed lookup per entity — not a traversal. For a page of 20 entities, this is 20 parallel single-index lookups.

**Response model update**:
```python
class KGQueryResponse(BasePaginatedResponse):
    query_type: str
    # Case 1 (frame_query)
    frame_results: Optional[List[FrameQueryResult]] = None  # {frame_uri, frame_type_uri, entity_refs[], frame_graph?}
    # Case 2 (entity)
    entity_uris: Optional[List[str]] = None
    entity_graphs: Optional[Dict[str, Any]] = None  # URI -> structured entity graph
    # Case 3 (relation)
    relation_connections: Optional[List[RelationConnection]] = None
    # Legacy (query_type="frame" — unchanged)
    frame_connections: Optional[List[FrameConnection]] = None
```

**Client update** (`kgqueries_endpoint.py`):
```python
async def query_entities(
    self, ...,
    include_entity_graph: bool = False  # NEW parameter
) -> KGQueryResponse:
```

#### 2b. Strongly-typed client response models

Replace the generic `KGQueryResponse` with discriminated response types on the client side:

```python
class EntitySlotRef:
    """Entity reference with its slot role"""
    slot_type_uri: str   # Identifies the role (e.g. PersonSlot, CompanySlot)
    entity_uri: str

class FrameQueryResult:
    """Single frame result — Case 1"""
    frame_uri: str
    frame_type_uri: str
    entity_refs: List[EntitySlotRef]     # Entities + slot roles
    frame_graph: Optional[Any] = None   # Structured frame data when include_frame_graph=True

class FrameQueryResponse:
    """Result from query_frames() — Case 1"""
    results: List[FrameQueryResult]
    total_count: int
    page_size: int
    offset: int

class EntityQueryResult:
    """Result from query_entities() — Case 2"""
    entity_uris: List[str]
    total_count: int
    entity_graphs: Optional[Dict[str, Any]] = None  # When include_entity_graph=True
    page_size: int
    offset: int

class RelationQueryResult:
    """Result from query_relation_connections() — Case 3"""
    connections: List[RelationConnection]
    total_count: int
    page_size: int
    offset: int
```

Each client method returns its specific type instead of the generic `KGQueryResponse`.

### Phase 3: Test Coverage (Priority: High)

#### 3a. Frame query with entity-slot criteria (Case 1)

Use the **WordNet dataset** which has entity-reference slots:

```python
# Find frames where an entity slot points to a specific entity
criteria = KGQueryCriteria(
    query_type="frame_query",
    frame_criteria=[FrameCriteria(
        frame_type="urn:wordnet:frame:...",
        slot_criteria=[SlotCriteria(
            slot_type="urn:wordnet:slot:...",
            slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGEntitySlot",
            value="urn:wordnet:synset:...",
            comparator="eq"
        )]
    )]
)
```

**Test file**: `vitalgraph_client_test/multi_kgentity/case_kgquery_frame_query.py`

#### 3b. Relation query with frame criteria on both sides (Case 3)

Use the **multi-org dataset** which has organizations related to products:

```python
# Find MakesProduct relations where:
#   source org has IndustryFrame → IndustryType = "Technology"
#   destination product has ProductFrame → Category = "Software"
criteria = KGQueryCriteria(
    query_type="relation",
    relation_type_uris=["urn:MakesProduct"],
    source_frame_criteria=[FrameCriteria(...)],
    destination_frame_criteria=[FrameCriteria(...)],
)
```

**Test file**: `vitalgraph_client_test/multi_kgentity/case_kgquery_relation_frame_queries.py`

### Phase 4: Cleanup and Deprecation (Priority: Medium)

#### 4a. Portal migration (no urgency)

Once `include_entity_graph` is available, the portal can optionally migrate from:
```python
response = client.kgqueries.query_frame_connections(...)
entities = [fc.source_entity_uri for fc in response.frame_connections]
```
To:
```python
response = client.kgqueries.query_entities(..., include_entity_graph=True)
entities = response.entity_uris
graphs = response.entity_graphs  # Structured entity data included
```

**No changes to `query_type="frame"` are planned.** It continues to work as-is.

#### 4b. Remove legacy `kgentity_query_endpoint_impl.py`

Dead code — not wired to any endpoint. Safe to delete.

---

## Test Datasets

| Dataset | Location | Cases Covered | Notes |
|---------|----------|---------------|-------|
| **Lead dataset** | `lead_test_data/` (100 .nt files) | Case 2: text, boolean, double slots | Hierarchical frames, 100 entities |
| **Multi-org dataset** | Created in-memory by test setup | Case 2: frame queries, Case 3: relation queries | 10 orgs, 6 products, 16 relations |
| **WordNet dataset** | Loaded via `load_wordnet_frames.py` | Case 1: entity slot values, Case 3: relation queries | Large dataset (~570k edges) |

### Test Coverage Matrix

| Query Pattern | Slot Type | Dataset | Test File | Status |
|--------------|-----------|---------|-----------|--------|
| **Case 1**: Frame → entity slot eq (frame as top-most) | KGEntitySlot | WordNet | `test_frame_query_slot_criteria.py` | ✅ 10/10 |
| **Case 1**: Frame → URI slot eq (frame as top-most) | KGURISlot | — | — | ❌ Not tested |
| **Case 2**: Entity → frame → text slot eq | KGTextSlot | Lead | `case_query_lead_data.py` | ✅ Tested |
| **Case 2**: Entity → frame → boolean slot eq | KGBooleanSlot | Lead | `case_query_lead_data.py` | ✅ Tested |
| **Case 2**: Entity → frame → double slot gte/lte | KGDoubleSlot | Lead | `case_kgquery_lead_queries.py` | ✅ Tested |
| **Case 3**: Relation + source frame criteria | KGTextSlot | Multi-org | `case_relation_queries.py` (T4,T5,T7,T8) | ✅ Tested |
| **Case 3**: Relation + dest frame criteria | KGTextSlot | Multi-org | `case_relation_queries.py` (T6) | ✅ Tested |
| **Case 3**: Relation + both sides frame criteria | KGTextSlot | Multi-org | `case_relation_queries.py` (T6) | ✅ Tested |
| Relation simple (no frame criteria) | — | Multi-org | `case_kgquery_relation_queries.py` | ✅ Tested |
| Entity query with `include_entity_graph` | — | Lead | `test_include_entity_graph.py` | ✅ Tested |
| Pagination total_count consistency | — | Lead | `case_query_lead_data.py` | ✅ Tested |
| Entity vs frame total_count cross-validation | — | Lead | `case_query_lead_data.py` | ✅ Tested |
| Hierarchical frames (parent → child → slot) | Mixed | Lead | `case_kgquery_lead_queries.py` | ✅ Tested |
| Frame negation (FILTER NOT EXISTS) | — | — | — | See `slot_negation_plan.md` |
| Slot `not_exists` comparator | — | — | — | See `slot_negation_plan.md` |
| **Sorting**: entity_frame_slot double ASC/DESC | KGDoubleSlot | Lead | `case_kgquery_sort_queries.py` (T1,T2) | ✅ Tested |
| **Sorting**: entity_frame_slot text ASC | KGTextSlot | Lead | `case_kgquery_sort_queries.py` (T3) | ✅ Tested |
| **Sorting**: entity_frame_slot boolean ASC | KGBooleanSlot | Lead | `case_kgquery_sort_queries.py` (T13) | ✅ Tested |
| **Sorting**: hierarchical frame slot | Mixed | Lead | `case_kgquery_sort_queries.py` (T4) | ✅ Tested |
| **Sorting**: multi-level (2 slot criteria) | Mixed | Lead | `case_kgquery_sort_queries.py` (T5) | ✅ Tested |
| **Sorting**: sort + filter combined | Mixed | Lead | `case_kgquery_sort_queries.py` (T6) | ✅ Tested |
| **Sorting**: pagination with sort | KGDoubleSlot | Lead | `case_kgquery_sort_queries.py` (T7) | ✅ Tested |
| **Sorting**: frame_query sort | KGDoubleSlot | Lead | `case_kgquery_sort_queries.py` (T8) | ✅ Tested |
| **Sorting**: entity_property (hasName) | — | Lead | `case_kgquery_sort_queries.py` (T9) | ✅ Tested |
| **Sorting**: entity_property (modificationDate) | — | Lead | `case_kgquery_sort_queries.py` (T10) | ✅ Tested |
| **Sorting**: entity_property + frame filter | — | Lead | `case_kgquery_sort_queries.py` (T11) | ✅ Tested |
| **Sorting**: entity_property (creationTime) | — | Lead | `case_kgquery_sort_queries.py` (T14) | ✅ Tested |
| **Sorting**: mixed entity_property + frame_slot | Mixed | Lead | `case_kgquery_sort_queries.py` (T15) | ✅ Tested |
| **Sorting**: model validation | — | — | `case_kgquery_sort_queries.py` (T12) | ✅ Tested |
| **Sorting**: relation by source slot | — | Multi-org | — | ❌ Not tested |
| **Sorting**: relation by dest slot | — | Multi-org | — | ❌ Not tested |

---

## Implementation Files

### Server-side

| File | Purpose |
|------|---------|
| `vitalgraph/endpoint/kgquery_endpoint.py` | KGQueries REST endpoint — three query_type handlers |
| `vitalgraph/endpoint/kgentities_endpoint.py` | KGEntities REST endpoint — includes `/query` route |
| `vitalgraph/sparql/kg_query_builder.py` | SPARQL builder for entity queries with frame/slot criteria |
| `vitalgraph/sparql/kg_connection_query_builder.py` | SPARQL builder for relation and frame connection queries |
| `vitalgraph/model/kgqueries_model.py` | `KGQueryCriteria`, `KGQueryResponse`, `RelationConnection`, `FrameConnection` |
| `vitalgraph/model/kgentities_model.py` | `EntityQueryCriteria`, `FrameCriteria`, `SlotCriteria`, `EntityQueryResponse` |

### Client-side

| File | Purpose |
|------|---------|
| `vitalgraph/client/endpoint/kgqueries_endpoint.py` | Client methods: `query_connections()`, `query_frame_connections()`, `query_relation_connections()`, `query_entities()` |
| `vitalgraph/client/endpoint/kgentities_endpoint.py` | Client method: `query_entities()` (different return type — `QueryResponse` with `GraphObjects`) |

### Tests

| File | Purpose |
|------|---------|
| `vitalgraph_client_test/entity_graph_lead_dataset/case_query_lead_data.py` | Entity + frame queries on lead data, total_count validation |
| `vitalgraph_client_test/entity_graph_lead_dataset/case_kgquery_lead_queries.py` | Frame-based lead queries (11 tests) |
| `vitalgraph_client_test/multi_kgentity/case_kgquery_frame_queries.py` | Frame queries on multi-org data |
| `vitalgraph_client_test/multi_kgentity/case_kgquery_entity_queries.py` | Entity queries on multi-org data |
| `vitalgraph_client_test/multi_kgentity/case_kgquery_relation_queries.py` | Relation queries (no frame criteria on source/dest) |
| `vitalgraph_client_test/test_query_lead_data.py` | Runner for lead data query tests |

---

## Recent Changes (This Session)

1. **Added `query_type="entity"` to server** — `kgquery_endpoint.py:_execute_entity_query()` runs entity SPARQL + count query concurrently, returns `entity_uris` + `total_count`
2. **Added `entity_uris` field to `KGQueryResponse`** — `kgqueries_model.py`
3. **Added `query_entities()` client method** — `kgqueries_endpoint.py:216-264`
4. **Created lead data query tests** — `case_query_lead_data.py` (10 tests, all passing)
5. **Verified total_count fix** — pagination returns consistent total_count across pages

## Changes (Apr 23, 2026 — Phase 1-3 Completion)

### Phase 1: Frame Query (Case 1)
6. **Fixed `frame_type_uri` being empty** — moved `OPTIONAL { ?frame haley:hasKGFrameType ?frame_type }` from main listing query (too expensive on 285k frames) to `_build_entity_slot_refs_query` (only runs for paged results)
7. **Replaced all `kGFrameSlotFrame` with edge-based pattern** — `hasEdgeSource`/`hasEdgeDestination` throughout `kg_query_builder.py`
8. **Tested frame_query on WordNet** — `test_frame_query_wordnet.py` and `test_frame_query_slot_criteria.py` (10/10 slot criteria tests)

### Phase 2: Entity Graph Inclusion (Case 2)
9. **Added `include_entity_graph` to `KGQueryRequest`** — `kgqueries_model.py`
10. **Added `entity_graphs` field to `KGQueryResponse`** — `Dict[str, List[Dict[str, Any]]]` (URI → property maps)
11. **Added `_fetch_entity_graphs()` on server** — single batched SPARQL using `hasKGGraphURI` + `VALUES` for all entity URIs. No rdflib dependency. Returns property maps: `{uri, type, properties}`
12. **Added `include_entity_graph` to client** — `query_connections()` and `query_entities()` pass-through
13. **Tested on lead dataset** — `test_include_entity_graph.py`, 3 entities × ~400 graph objects each, fetched in one query

### Phase 3: Test Coverage (Case 3)
14. **Ran full relation test suite** — `test_kgqueries_endpoint.py`, 35/35 tests passed
15. **Relation + frame criteria tests all pass** — Tests 4-8 in `case_relation_queries.py`: industry filter, employee count gt, both-sides filter, city contains, combined criteria

### Phase 2b: Strongly-Typed Client Response Models
16. **Removed dead `kgentity_query_endpoint_impl.py`** — only used by mock, inlined empty stub in `mock_kgentities_endpoint.py`
17. **Added typed response models** — `FrameQueryResponse`, `KGEntityQueryResponse`, `RelationQueryResponse` in `kgqueries_model.py`, each with `from_raw()` factory
18. **Updated client methods** — `query_frames()` → `FrameQueryResponse`, `query_entities()` → `KGEntityQueryResponse`, `query_relation_connections()` → `RelationQueryResponse`
19. **Updated all test files** — `.frame_results` → `.results`, `.relation_connections` → `.connections`, removed `.query_type` checks on typed responses
20. **All tests pass** — `test_query_lead_data.py` (10/10), `test_frame_query_slot_criteria.py` (10/10), `test_include_entity_graph.py`, `test_frame_query_wordnet.py`
21. **Fixed frame query test failures** — `test_kgqueries_endpoint.py` frame tests used `query_mode="direct"` (generates `vg-direct:hasEntityFrame`) but multi-org data only has edge objects. Switched to `query_mode="edge"` → 35/35
22. **Full lead dataset re-verified** — `test_lead_entity_graph_dataset.py` 21/21 (bulk load 100 entities + list/query + retrieve + KGQuery frame queries)

---

## Decisions

1. **`include_entity_graph` returns structured form**, not raw quads. Response: `{entity: {...}, frames: [...], slots: [...]}` per entity.

2. **`query_type="frame"` is unchanged.** No breaking changes. Portal continues using `query_frame_connections()`. Migration to `query_entities()` is optional.

3. **Shared frame connections** (original `query_type="frame"` design intent) has no current consumer. Not an action item.

4. **Case 1 uses new `query_type="frame_query"`**, not repurposing existing `query_type="frame"`.

5. **`FrameQueryResult` includes `entity_refs` with `slot_type_uri`** per entity, so callers can distinguish entity roles without parsing the full frame graph.
