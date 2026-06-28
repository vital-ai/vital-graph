# Semantic Search UI Plan

> **Created**: Jun 14, 2026
> **Supersedes**: The current "Vector Search" page (`/vector-search`, `VectorSearch.tsx`)
> **Related**: `search_ui_plan.md`, `text_hybrid_search_plan.md`, `fuzzy_search_implementation_plan.md`

This document covers **two distinct features**:

1. **Semantic Search UI** (§2–§6) — A SPARQL-based index testing tool that exercises
   all search functions across all object types (entities, documents, types)
2. **KG Entity Semantic Search** (§7–§9) — Criteria-based search integration on the
   KG Entities page for production entity discovery

---

# Part A: Semantic Search UI (Index Testing)

## 1. Purpose

The Semantic Search page is a **testing and exploration tool** for exercising
search indexes. It uses the **general-purpose SPARQL endpoint** directly
(`POST /api/sparql/query`) to run SPARQL queries containing search functions
across all object types.

This is NOT an entity search UI — it's a tool for:
- Verifying that vector, FTS, hybrid, fuzzy, and geo indexes are working
- Testing search quality across KGEntities, KGDocuments, and KGTypes
- Debugging search results and scores
- Experimenting with search parameters (top-K, min score, alpha, radius)

---

## 2. Route & Naming

| Current | New |
|---------|-----|
| Route: `/vector-search` | Route: `/semantic-search` |
| File: `VectorSearch.tsx` | File: `SemanticSearch.tsx` |
| Sidebar label: "Vector Search" | Sidebar label: "Semantic Search" |


---

## 3. Architecture: Direct SPARQL Execution

The Semantic Search UI builds SPARQL queries client-side (or from templates)
and executes them via the general-purpose SPARQL endpoint:

```
POST /api/sparql/query?space_id=X
Body: { "query": "<SPARQL string>" }
```

This is the same endpoint used by the SPARQL console. The UI simply provides
a structured form that generates the appropriate SPARQL for each search mode.

### 3.1 Search Modes & SPARQL Templates

| Mode | SPARQL Function | Target Types | Index Required |
|------|----------------|-------------|----------------|
| **Vector** | `vg:vectorSimilarity` | Entities, Documents, Types | Vector index |
| **FTS** | `vg:textSearch` | Entities, Documents, Types | FTS index |
| **Hybrid** | `vg:hybridSearch` | Entities, Documents, Types | Both |
| **Fuzzy** | `vg:fuzzyMatch` | Entities | Fuzzy mapping |
| **Keyword** | `FILTER(CONTAINS(...))` | Entities, Documents, Types | None |
| **Geo** | `vg:withinRadius` | Entities (with geo data) | Geo data |

### 3.2 Generated SPARQL Examples

**Vector search over KGEntities:**
```sparql
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?entity ?name ?score
WHERE {
  GRAPH <urn:graph:default> {
    ?entity a haley:KGEntity .
    ?entity haley:hasKGEntityName ?name .
  }
  BIND(vg:vectorSimilarity(?entity, "search text", "entity_default", 10) AS ?score)
  FILTER(BOUND(?score))
  FILTER(?score > 0.5)
}
ORDER BY DESC(?score)
LIMIT 10
```

**FTS search over KGDocuments:**
```sparql
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?doc ?name ?score
WHERE {
  GRAPH <urn:graph:default> {
    ?doc a haley:KGDocument .
    ?doc haley:hasKGDocumentName ?name .
  }
  BIND(vg:textSearch(?doc, "search text", "fulltext_en") AS ?score)
  FILTER(BOUND(?score))
}
ORDER BY DESC(?score)
LIMIT 10
```

**Hybrid search over KGTypes:**
```sparql
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?type ?name ?score
WHERE {
  GRAPH <urn:graph:default> {
    ?type a haley:KGType .
    ?type haley:hasKGTypeName ?name .
  }
  BIND(vg:hybridSearch(?type, "search text", "kgtype_default", 0.5) AS ?score)
  FILTER(BOUND(?score))
}
ORDER BY DESC(?score)
LIMIT 10
```

**Fuzzy search:**
```sparql
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?entity ?name ?score
WHERE {
  GRAPH <urn:graph:default> {
    ?entity a haley:KGEntity .
    ?entity haley:hasKGEntityName ?name .
  }
  BIND(vg:fuzzyMatch(?entity, "search name", 50) AS ?score)
  FILTER(BOUND(?score))
}
ORDER BY DESC(?score)
LIMIT 10
```

**Geo search (radius):**
```sparql
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?entity ?name ?distance
WHERE {
  GRAPH <urn:graph:default> {
    ?entity a haley:KGEntity .
    ?entity haley:hasKGEntityName ?name .
  }
  BIND(vg:geoDistance(?entity, 40.7128, -74.0060) AS ?distance)
  FILTER(vg:withinRadius(?entity, 40.7128, -74.0060, 5000))
}
ORDER BY ?distance
LIMIT 10
```

**Geo search (bounding box):**
```sparql
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?entity ?name
WHERE {
  GRAPH <urn:graph:default> {
    ?entity a haley:KGEntity .
    ?entity haley:hasKGEntityName ?name .
  }
  FILTER(vg:withinBounds(?entity, 40.70, -74.02, 40.75, -73.97))
}
LIMIT 50
```

**Geo search (polygon):**
```sparql
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?entity ?name
WHERE {
  GRAPH <urn:graph:default> {
    ?entity a haley:KGEntity .
    ?entity haley:hasKGEntityName ?name .
  }
  FILTER(vg:withinPolygon(?entity, "POLYGON((-74.0 40.7, -73.9 40.7, -73.9 40.8, -74.0 40.8, -74.0 40.7))"))
}
LIMIT 50
```

---

## 4. UI Design

### 4.1 Layout

```
┌─────────────────────────────────────────────────────────┐
│ Breadcrumb: Home > Semantic Search                      │
├─────────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────────┐ │
│ │ Search Mode:  [Vector] [FTS] [Hybrid] [Fuzzy] [Keyword] [Geo] │
│ └─────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ Object Type:  [Entities] [Documents] [Types]        │ │
│ └─────────────────────────────────────────────────────┘ │
│                                                         │
│ ┌──────────────────────────┐ ┌────────────────────────┐ │
│ │ Search Input             │ │ Controls               │ │
│ │ ┌──────────────────────┐ │ │ • Space selector       │ │
│ │ │ Text input           │ │ │ • Graph selector       │ │
│ │ └──────────────────────┘ │ │ • Index/mapping name   │ │
│ │                          │ │ • Top-K                │ │
│ │ [Search] [Show SPARQL]   │ │ • Min Score            │ │
│ │                          │ │ • Alpha (hybrid)       │ │
│ └──────────────────────────┘ │ • Lat/Lon/Radius (geo) │ │
│                              └────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ Generated SPARQL (collapsible)                      │ │
│ │ Shows the query that will be / was executed         │ │
│ └─────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ Results Table                                       │ │
│ │ URI | Name | Type | Score | Query Time              │ │
│ └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### 4.2 Key UI Elements

- **Object Type selector** — Choose what to search: Entities, Documents, Types
- **Search Mode tabs** — Vector, FTS, Hybrid, Fuzzy, Keyword, Geo
- **Show SPARQL toggle** — Displays the generated SPARQL (read-only, for debugging)
- **Index/mapping name** — Text input (user types the index name directly)
- **Results** — Raw SPARQL results displayed as a table

### 4.3 Mode-Specific Controls

| Control | Vector | FTS | Hybrid | Fuzzy | Keyword | Geo |
|---------|--------|-----|--------|-------|---------|-----|
| Text input | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Index name | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| Top-K | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Min Score | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| Alpha | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| Geo shape type | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Lat/Lon/Radius | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ (radius) |
| Bounds (SW/NE) | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ (bounds) |
| Polygon (WKT) | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ (polygon) |

**Geo sub-modes:**
- **Radius** — lat, lon, radius (meters)
- **Bounds** — minLat, minLon, maxLat, maxLon
- **Polygon** — WKT or GeoJSON polygon string

---

## 5. Implementation

### 5.1 Backend

No new backend work needed. Uses the existing SPARQL query endpoint:

```
POST /api/sparql/query?space_id=X
Body: { "query": "<generated SPARQL>" }
Response: { "results": { "bindings": [...] } }
```

The SPARQL pipeline already handles all `vg:` functions. The UI just
generates the correct SPARQL string and parses the bindings response.

### 5.2 Frontend Tasks

- [ ] **1** Create `SemanticSearch.tsx` (replaces `VectorSearch.tsx`)
- [ ] **2** Add route `/semantic-search`, redirect `/vector-search`
- [ ] **3** Update sidebar label
- [ ] **4** Implement SPARQL template generation per mode + object type
- [ ] **5** Call `POST /api/sparql/query` with generated SPARQL
- [ ] **6** Parse SPARQL results bindings into results table
- [ ] **7** Show generated SPARQL in collapsible panel
- [ ] **8** Mode-specific control visibility
- [ ] **9** Index name populated from available indexes (optional autocomplete)

### 5.3 Client Code

The frontend calls the SPARQL endpoint directly (no criteria wrappers needed):

```typescript
const response = await vgClient.sparql.query(spaceId, { query: generatedSparql });
// response.results.bindings → table rows
```

---

## 6. Navigation & Sidebar

```
Semantic Indexes
├─ Semantic Search      ← SPARQL-based index testing
├─ Index Mappings       ← all mappings (FTS/vector + fuzzy)
├─ Vector Indexes       ← index management
├─ FTS Indexes          ← index management
└─ Geo Shapes           ← geo data viewer + config
```

---

# Part B: KG Entity Semantic Search (Production Search)

## 7. Purpose

Add search capabilities to the **KG Entities page** (`/kgentities`) so users
can find entities using vector, FTS, hybrid, fuzzy, keyword, and geo search.
This is a production feature — not a testing tool.

Unlike the Semantic Search UI (which uses raw SPARQL), this integrates into
the existing kgqueries criteria system that already powers entity listing,
filtering, and sorting.

---

## 8. Architecture: Extend Entity Criteria

The kgqueries endpoint (`POST /api/graphs/kgqueries`, `query_type: "entity"`)
already supports `vector_criteria` and `geo_criteria` on `EntityQueryCriteria`.
Add the remaining search modes:

| Criteria Field | SPARQL Function Generated | Status |
|---------------|--------------------------|--------|
| `vector_criteria` | `vg:vectorSimilarity(?e, text, index, topK)` | ✅ Exists |
| `geo_criteria` | `vg:withinRadius(?e, lat, lon, radiusKm)` | ✅ Exists |
| `fts_criteria` | `vg:textSearch(?e, text, index)` | Needs adding |
| `hybrid_criteria` | `vg:hybridSearch(?e, text, index, alpha)` | Needs adding |
| `fuzzy_criteria` | `vg:fuzzyMatch(?e, text, minScore)` | Needs adding |
| `keyword_criteria` | `FILTER(CONTAINS(LCASE(?name), LCASE(text)))` | Needs adding |

These are added to `EntityQueryCriteria` in `kgentities_model.py`, and the
`KGQueryCriteriaBuilder` SPARQL builder handles them when generating queries.

### 8.1 Backend Changes

1. Add Pydantic models for `FtsSearchCriteria`, `HybridSearchCriteria`,
   `FuzzySearchCriteria`, `KeywordSearchCriteria` to `kgentities_model.py`
2. Add optional fields to `EntityQueryCriteria`
3. Update `KGQueryCriteriaBuilder` to emit the corresponding SPARQL BIND/FILTER
4. The kgqueries endpoint needs no changes — it already passes criteria through

### 8.2 Client Library Changes

Add convenience wrappers in `KGQueriesEndpoint.ts`:

```typescript
async textSearch(spaceId, graphId, opts) {
  return this.queryEntities(spaceId, graphId, {
    criteria: { query_type: "entity", fts_criteria: { search_text: opts.searchText, index_name: opts.indexName, top_k: opts.topK } }
  }, opts.topK);
}

async hybridSearch(spaceId, graphId, opts) {
  return this.queryEntities(spaceId, graphId, {
    criteria: { query_type: "entity", hybrid_criteria: { search_text: opts.searchText, index_name: opts.indexName, alpha: opts.alpha, top_k: opts.topK } }
  }, opts.topK);
}

async fuzzySearch(spaceId, graphId, opts) {
  return this.queryEntities(spaceId, graphId, {
    criteria: { query_type: "entity", fuzzy_criteria: { search_text: opts.searchText, min_score: opts.minScore } }
  }, opts.topK);
}

async keywordSearch(spaceId, graphId, opts) {
  return this.queryEntities(spaceId, graphId, {
    criteria: { query_type: "entity", keyword_criteria: { search_text: opts.searchText } }
  }, opts.topK);
}
```

(`vectorSearch` and geo already exist)

### 8.3 Frontend: KG Entities Page Integration

Add a search panel to the KG Entities list page:

- **Search mode selector** — dropdown or tabs on the entities page
- **Search input** — text field for search query
- **Integrated with existing filters** — search criteria combines with
  entity_type_uri filter, sorting, pagination
- Results show in the same entities table (with score column added)

This keeps entity search in context with entity browsing — users can
switch between browsing all entities and searching.

---

## 9. Implementation Priority

| Task | Part | Priority |
|------|------|----------|
| Rename Vector Search → Semantic Search | A | High |
| SPARQL template generation for all modes | A | High |
| Object type selector (entity/document/type) | A | High |
| Show generated SPARQL panel | A | Medium |
| Add `fts_criteria` to EntityQueryCriteria | B | Medium |
| Add `hybrid_criteria` to EntityQueryCriteria | B | Medium |
| Add `fuzzy_criteria` to EntityQueryCriteria | B | Medium |
| Add `keyword_criteria` to EntityQueryCriteria | B | Medium |
| Client library wrappers | B | Medium |
| KG Entities page search panel | B | Lower |

---

# Part C: Multi-Space Scope (Entity Registry & Agent Registry)

## 10. Registry Spaces as First-Class Citizens

The entity registry and agent registry are **pseudo-spaces** — they use the
exact same per-space table schema (`{space_id}_vector_index`, `{space_id}_vec_*`,
`{space_id}_fts_index`, `{space_id}_fts_*`, etc.) as regular user spaces.
They just have their own `space_id` values (e.g., `entity_registry`,
`agent_registry`) and are not user-created.

This means all UI screens under "Semantic Indexes" must be aware of and
able to manage indexes across **all** space types:

| Space Type | Example space_id | Contains |
|-----------|-----------------|----------|
| User space | `my_project` | KGEntities, KGDocuments, KGTypes |
| Entity Registry | `entity_registry` | Registry entities, locations |
| Agent Registry | `agent_registry` | Agents, endpoints |

### 10.1 Space Selector Behavior

All screens that currently have a "Space" selector must include the registry
spaces alongside user spaces:

- **Semantic Search** — space selector shows all spaces (user + registry)
- **Index Mappings** — can create/view mappings for registry spaces
- **Vector Indexes** — lists/manages vector indexes for registry spaces
- **FTS Indexes** — lists/manages FTS indexes for registry spaces
- **Fuzzy Mappings** — lists/manages fuzzy mappings for registry spaces

The space selector should visually distinguish registry spaces from user
spaces (e.g., with a badge or grouping):

```
Space: [▼]
  ── User Spaces ──
  my_project
  demo_space
  ── System Spaces ──
  entity_registry
  agent_registry
```

### 10.2 API Calls

All existing endpoints already accept `space_id` as a parameter. No backend
changes are needed — the frontend just needs to pass the registry space_id:

```
GET /api/vector-indexes?space_id=entity_registry
GET /api/fts-indexes?space_id=entity_registry
GET /api/search-mappings?space_id=entity_registry
POST /api/sparql/query?space_id=entity_registry
```

### 10.3 Semantic Search with Registries

When searching the entity registry space, the SPARQL templates change to
target registry objects instead of KG objects:

**Vector search over entity registry:**
```sparql
PREFIX vg: <http://vital.ai/ontology/vitalgraph#>

SELECT ?entity ?name ?score
WHERE {
  ?entity <http://vital.ai/ontology/vital-core#hasName> ?name .
  BIND(vg:vectorSimilarity(?entity, "search text", "entity_default", 10) AS ?score)
  FILTER(BOUND(?score))
}
ORDER BY DESC(?score)
LIMIT 10
```

The object type selector on the Semantic Search page adapts based on space:

| Space Type | Object Types Available |
|-----------|----------------------|
| User space | KGEntities, KGDocuments, KGTypes |
| Entity Registry | Entities, Locations |
| Agent Registry | Agents |

### 10.4 Implementation Tasks

- [ ] Include registry spaces in space selector dropdown (all screens)
- [ ] Group/badge registry spaces distinctly from user spaces
- [ ] Adapt object type selector on Semantic Search by space type
- [ ] Ensure Vector Indexes page works with registry space_ids
- [ ] Ensure FTS Indexes page works with registry space_ids
- [ ] Ensure Index Mappings page works with registry space_ids
- [ ] Test SPARQL query execution against registry spaces

---

# Part C2: Search Result Detail Screen

## 10.5 Search Result Detail

Clicking "Detail" on a search result navigates to a **Search Result Detail**
screen that displays **all quads for the subject** (within that space and graph).
This is a generic viewer — the indexed items are arbitrary nodes (KGEntity,
KGFrame, KGDocument, KGType, or any other RDF subject).

### 10.5.1 Route

```
/space/:spaceId/graph/:graphId/search-result/:subjectUri
```

### 10.5.2 Behavior

1. **Fetch all quads** for the given `subjectUri` in the specified space/graph:
   ```
   GET /api/objects/:spaceId/:graphId/:subjectUri
   ```
   (or via SPARQL: `SELECT ?p ?o WHERE { <subjectUri> ?p ?o }`)

2. **Display as a properties table** — predicate URI | object value | object type

3. **Type-aware deep link**: If the quads contain a `vitaltype` triple
   (`http://vital.ai/ontology/vital-core#vitaltype`), and that type maps
   to a known detail screen, show a "View as [TypeName]" link:

   | `vitaltype` value | Deep-link target |
   |-----------------|------------------|
   | `haley:KGEntity` (or subclass) | `/space/:s/graph/:g/entity/:uri` |
   | `haley:KGFrame` | `/space/:s/graph/:g/frame/:uri` |
   | `haley:KGDocument` | `/space/:s/graph/:g/document/:uri` |
   | `haley:KGType` | `/space/:s/graph/:g/kg-types/:uri` |
   | `haley:KGSlot` (or subclass) | **Navigate to enclosing entity or frame** (see below) |
   | (other/unknown) | No deep link — just show quads |

   This link is **optional** and supplementary. The primary view is always
   the full quad listing.

   **KGSlot special case**: Slots are not standalone detail screens. When
   the subject is a KGSlot (or subclass), the deep link resolves to the
   enclosing container using the **grouping URI properties** on the slot:

   - `haley:hasKGGraphURI` — points to the enclosing **entity** URI
   - `haley:hasFrameGraphURI` — points to the enclosing **frame** URI

   These are direct properties on the slot object itself. Resolution:

   1. If the slot has `hasKGGraphURI` → link to that entity:
      `/space/:s/graph/:g/entity/:entityUri`
   2. Else if the slot has `hasFrameGraphURI` → link to that frame:
      `/space/:s/graph/:g/frame/:frameUri`
   3. Else → no deep link (just show quads)

   No extra SPARQL query needed — the grouping URIs are already present
   in the slot's own quads fetched by the detail screen.

4. **Back to results** — breadcrumb link back to the search results page.

### 10.5.3 Implementation Tasks

- [x] Create `SearchResultDetail.tsx` page component
- [x] Add route `/space/:spaceId/graph/:graphId/search-result/:subjectUri` in `App.tsx`
- [x] Fetch all quads for the subject URI via SPARQL (`SELECT ?p ?o WHERE { <uri> ?p ?o }`)
- [x] Render properties table (predicate, object, type)
- [x] Detect `vitaltype` and show conditional deep-link button
- [x] For KGSlot types: resolve enclosing entity/frame via `hasKGGraphURI`/`hasFrameGraphURI`
- [x] Wire SemanticSearch results "Detail" button to this route

---

## 10.6 Index Space & Graph Tracking

**Requirement**: All vector, FTS, and fuzzy indexes must always store the
`space_id` and `graph_uri` of the items they index. This information is
essential for:

- Navigating from search results to the correct detail screen
- Scoping searches to specific graphs within a space
- Ensuring consistency between the index and the source data

### 10.6.1 Regular Spaces (per-space indexes)

The per-space index tables (`{space_id}_vec_{index}`, `{space_id}_fts_{index}`)
already implicitly encode the `space_id` in the table name. The `context_uuid`
column encodes the graph URI (via deterministic UUID from the graph URI).

The SPARQL search results always include the `?entity` (subject URI) binding.
The UI knows the `space_id` (from the selector) and can resolve the `graph_uri`
from the loaded graphs list.

**Key invariant**: The search result detail link must include both `space_id`
and `graph_uri` so the detail screen can fetch the correct quads.

### 10.6.2 Entity Registry & Agent Registry (exceptions)

The entity registry and agent registry are **not** organized into spaces/graphs.
They use dedicated global tables:

- `entity_registry_vec_entity`, `entity_registry_fts_entity`, etc.
- `agent_registry_vec_agent`, `agent_registry_fts_agent`, etc.

These indexes do NOT have space/graph context — the `entity_id` or `agent_id`
column directly references the registry's relational tables. Detail navigation
for these uses registry-specific routes (`/entity-registry/:id`,
`/agent-registry/:id`).

### 10.6.3 Summary

| Index Location | Space Tracking | Graph Tracking | Detail Route |
|---------------|---------------|----------------|--------------|
| Per-space tables | Implicit (table name) | `context_uuid` column | `/space/:s/graph/:g/search-result/:uri` |
| Entity Registry | N/A | N/A | `/entity-registry/:id` |
| Agent Registry | N/A | N/A | `/agent-registry/:id` |

---

# Part D: Unified Mappings & Indexes Screens

## 11. Fuzzy Search: Separate Mapping vs Index

Currently the `fuzzy_mapping` table conflates the mapping (which properties)
with the index config (shingle_k, num_perm, lsh_threshold). For UI consistency
with vector/FTS, split the detail view into two tabs or sections:

**Mapping detail** (what to index):
- Properties (property_uri, property_role, ordinal)
- Mapping type, type_uri, enabled

**Index detail** (how it's indexed + status):
- Parameters: shingle_k, num_perm, lsh_threshold, phonetic_bonus
- Band table stats: band count, entity count, phonetic band count
- Rebuild/populate action button
- Last populated timestamp

This is a **UI-only separation** — the backend remains the single
`fuzzy_mapping` + `fuzzy_mapping_property` tables. The detail screen just
presents them as two logical sections.

---

## 12. Unified Mappings Screen

Merge **Index Mappings** (`/search-mappings`) and **Fuzzy Mappings**
(`/fuzzy-mappings`) into a single "Index Mappings" screen.

### 12.1 Merged List View

| Mapping Name | Type | Properties | Linked Indexes | Created |
|-------------|------|-----------|---------------|---------|
| `entity_search` | FTS + Vector | 3 | 2 | Jun 10, 2026 |
| `entity_names` | Fuzzy | 2 | 1 (bands) | Jun 8, 2026 |
| `doc_search` | FTS + Vector | 5 | 3 | Jun 5, 2026 |
| `agent_names` | Fuzzy | 1 | 1 (bands) | Jun 12, 2026 |

**Type badges:**
- `FTS + Vector` — search mapping (has associated FTS/vector indexes)
- `Fuzzy` — fuzzy name-matching mapping (MinHash LSH bands)

### 12.2 Create Mapping Flow

```
Create Mapping
─────────────────────────
Mapping Type:  (●) FTS / Vector    ( ) Fuzzy

[... type-specific fields below ...]
```

**FTS / Vector mapping fields:**
- Mapping name
- Properties to index (see §12.5 Property Selector below)
- Source type: `properties` (explicit list) or `default` (all literals)
- Separator string (default `. `)
- Include predicate name in text (boolean)
- Associated indexes (link to vector/FTS indexes)

**Fuzzy mapping fields:**
- Mapping name
- Properties: primary_name, aliases (see §12.5 Property Selector below)
- Fuzzy config (shingle_k, threshold, phonetic bonus)

### 12.5 Property Selector

The property selector lets users choose **which properties** are included in the
search text for vectorization/FTS/fuzzy indexing. Properties are selected from
those available on the chosen Object Type (and optionally narrowed by selected
KG Types).

```
┌─────────────────────────────────────────────────┐
│ Properties                                      │
├─────────────────────────────────────────────────┤
│ Source:  (●) Selected properties  ( ) All       │
│                                                 │
│ [Search properties...                    ▼]     │
│ ┌─────────────────────────────────────────────┐ │
│ │ 🔍 Filter...                               │ │
│ │ ☑ hasName                                  │ │
│ │ ☑ hasKGraphDescription                     │ │
│ │ ☐ hasKGEntityTypeURI                       │ │
│ │ ☐ hasKGEntityName                          │ │
│ │   ... (scrollable)                         │ │
│ └─────────────────────────────────────────────┘ │
│                                                 │
│ Selected (2):                                   │
│  1. hasName                          [↑] [↓] [✕]│
│  2. hasKGraphDescription             [↑] [↓] [✕]│
│                                                 │
│ For Fuzzy: assign roles per property:           │
│  1. hasName              [primary_name ▼]       │
│  2. hasKGEntityName      [alias ▼]              │
└─────────────────────────────────────────────────┘
```

**Property Selector requirements:**
- Searchable dropdown populated from properties available on the Object Type class
- Properties sourced from VitalSigns ontology for the class (e.g., KGEntity properties)
- Orderable list — ordinal determines concatenation order in search text
- For FTS/Vector: selected properties are included (no role needed — presence = include)
- For Fuzzy: each property has a role assignment (`primary_name` or `alias`)
- "All" source mode disables the property list (uses all literals on the subject)

**Data source:**
```
GET /api/ontology/properties?class_uri=haley-ai-kg#KGEntity
→ returns list of property URIs + labels available on KGEntity and subclasses
```

### 12.3 Detail Views

Clicking a mapping opens the appropriate detail:
- FTS/Vector → `SearchMappingDetail.tsx` (existing)
- Fuzzy → `FuzzyMappingDetail.tsx` (refactored with mapping + index sections per §11)

### 12.4 Type URI Picker (KG Type Multi-Select)

Both FTS/Vector and Fuzzy mapping forms on the Index Mapping screen include:

- **Object Type** — dropdown: `Entity`, `Document`, `Type` (maps to `mapping_type`)
- **Type URI(s)** — multi-select picker populated from **KG Type data** in the space

The Type URI picker determines **which subjects get indexed** for any mapping type:

```
┌─────────────────────────────────────────────────┐
│ Create / Edit Mapping                           │
├─────────────────────────────────────────────────┤
│ Mapping Kind:  (●) FTS / Vector    ( ) Fuzzy    │  ← selected first
│                                                 │
│ Object Type:   [Entity ▼]                       │
│                                                 │
│ Type URIs:     [Search types...          ▼]     │
│                ┌────────────────────────────┐    │
│                │ 🔍 Filter types...         │    │
│                │ ☑ Lead                     │    │
│                │ ☑ Contact                  │    │
│                │ ☐ Organization             │    │
│                │ ☐ Product                  │    │
│                │ ☐ Location                 │    │
│                │   ... (scrollable)         │    │
│                └────────────────────────────┘    │
│                Selected: Lead, Contact (2)       │
│                                                 │
│ [... mapping-kind-specific fields below ...]    │
└─────────────────────────────────────────────────┘
```

**Type URI Picker requirements** (assumes hundreds of types):
- Searchable dropdown with text filter (debounced, case-insensitive)
- Virtualized/scrollable list for performance
- Checkbox multi-select with "Select All" / "Clear All" actions
- Shows selected count and chip summary below the dropdown
- Paginated or lazy-loaded from API if type count is very large
- Displays type `hasName` as label, type URI as subtitle/tooltip

**Behavior (applies to both FTS/Vector and Fuzzy):**

The Object Type selection determines which KG Type instances populate the picker:

| Object Type | KG Type class shown in picker | Filter property on indexed subjects |
|-------------|-------------------------------|-------------------------------------|
| Entity | `KGEntityType` instances | `hasKGEntityTypeURI` |
| Document | `KGDocumentType` instances | `hasKGDocumentTypeURI` |
| Frame | `KGFrameType` instances | `hasKGFrameTypeURI` |
| Type | KGType subclasses (from VitalSigns ontology) | `vitaltype` |

- Selecting zero Type URIs = index **all** subjects of that Object Type family
- Selecting specific Type URIs = only index subjects whose filter property matches one of the selected URIs

**Backend impact:**
- Selected Type URIs stored in `search_mapping.type_uri` (one mapping row per type URI,
  plus a base row with `type_uri=NULL` as fallback)
- For FTS/Vector: the vector populator filters subjects by `vitaltype` for the Object Type
  class family, then optionally narrows by `hasKGEntityTypeURI = <type_uri>`
- For Fuzzy: the fuzzy populator applies the same filtering logic — `vitaltype` for
  class family, then `hasKGEntityTypeURI` for specific KG Types

**Data source for picker:**
```
GET /api/kgtypes?space_id=X&graph_id=G&vitaltype_filter=KGEntityType
→ returns list of KGEntityType instances with URI + hasName
```

---

## 13. Unified Indexes Screen

Merge **Vector Indexes**, **FTS Indexes**, and **Fuzzy Indexes** into a
single "Indexes" screen with list + detail pattern.

### 13.1 Combined Index List

| Index Name | Type | Dimensions/Config | Documents | Status | Created |
|-----------|------|------------------|-----------|--------|---------|
| `entity_default` | Vector | 384 (cosine) | 12,450 | ✅ | Jun 10 |
| `doc_search` | FTS | — | 8,200 | ✅ | Jun 8 |
| `entity_names` | Fuzzy | k=3, perm=64, t=0.3 | 12,450 | ✅ | Jun 5 |
| `openai_embed` | Vector | 1536 (cosine) | 3,100 | ⚠️ stale | Jun 1 |

**Type badges:** `Vector`, `FTS`, `Fuzzy`

### 13.2 Index Detail View

Clicking an index opens a detail panel/page with type-specific info:

**Vector index detail:**
- Dimensions, distance metric, provider, model
- Row count, staleness check
- Reindex / populate button

**FTS index detail:**
- Segment count, document count
- Language config (if applicable)
- Rebuild button

**Fuzzy index detail:**
- Parameters (shingle_k, num_perm, lsh_threshold, phonetic_bonus)
- Band count, entity count, phonetic band count
- Populate / rebuild button

### 13.3 Create Index Flow

```
Create Index
─────────────────────────
Index Type:  (●) Vector    ( ) FTS    ( ) Fuzzy

[... type-specific fields below ...]
```

### 13.4 Geo: Not an Index

Geo is **not** part of the unified Indexes screen. It has a different pattern:

- `{space}_geo_config` — single-row config (enabled, auto_sync, datatype URIs)
- `{space}_geo` — data table of extracted geo shapes (points, polygons, etc.)

There's no "geo mapping" or "geo index catalog." Population is automatic
(driven by detecting geo datatypes in the quad store). The existing
**Geo Shapes** screen remains separate as a data viewer / config toggle.

The geo data supports multiple shape types via WKT/GeoJSON:
- **Points** — `geography(Point, 4326)`
- **Polygons** — WKT `POLYGON((...))` or GeoJSON
- **Bounding boxes** — defined by SW/NE corners

SPARQL geo query functions:
- `vg:geoDistance(?e, lat, lon)` — distance score
- `vg:withinRadius(?e, lat, lon, meters)` — point within radius
- `vg:withinBounds(?e, minLat, minLon, maxLat, maxLon)` — within bounding box
- `vg:withinPolygon(?e, "POLYGON((...))" )` — within arbitrary polygon

---

## 14. Updated Sidebar (Final)

```
Semantic Indexes
├─ Semantic Search      ← SPARQL-based index testing
├─ Index Mappings       ← all mappings (FTS/vector + fuzzy)
├─ Indexes              ← all indexes (vector + FTS + fuzzy)
└─ Geo Shapes           ← geo data viewer + config
```

---

## 15. Implementation Tasks

### Mappings merge
- [x] Merge list data: fetch both search mappings and fuzzy mappings
- [x] Add "Type" column with badge
- [x] Add mapping type selector to create flow
- [x] Route to appropriate detail page based on type
- [x] Add Type URI multi-select picker (TypeURIPicker component)
- [x] Add Property Selector with source mode toggle (PropertySelector component)
- [x] Refactor fuzzy detail into mapping section + index section

### Indexes merge
- [x] Create unified Indexes page with combined list (`Indexes.tsx`)
- [x] Fetch vector indexes, FTS indexes in parallel (`Promise.all`)
- [x] Add "Type" column with badge (Vector=blue, FTS=green, Fuzzy=purple)
- [x] Create index type selector in create flow (Vector / FTS dropdown)
- [x] Type-specific detail views (routes to `/indexes/vector/` or `/indexes/fts/`)
- [x] Populate/rebuild actions per index type
- [x] Add fuzzy index stats to unified list (groups fuzzy mappings by index_name, shows counts)

### Sidebar
- [x] Remove separate "Vector Indexes", "FTS Indexes", "Fuzzy Mappings" entries
- [x] Add "Indexes" entry (combined under "Semantic Indexes" collapsible)

---

## 16. Migration Notes

- [x] `SemanticSearch.tsx` created as replacement for `VectorSearch.tsx`
- [x] `/geo-shapes` route active (`GeoShapes.tsx`); `/geo-points` route removed
- [x] Reindex button removed from search page (on Indexes page instead)
- [x] Semantic Search page is purely querying/testing
- [x] Index Mappings screen merges FTS/vector and fuzzy mapping management
- [x] Indexes screen merges vector, FTS, and fuzzy index management
- [x] Old redirect routes removed from `App.tsx`
- [x] Delete dead files: `VectorSearch.tsx`, `GeoPoints.tsx` (no longer routed)
- [ ] The KG Entity search is a separate enhancement to the existing entities page
- [x] All "Semantic Indexes" screens must surface entity_registry and agent_registry spaces

---

## Known Issues (Jun 14, 2026)

Issues discovered while debugging `test_scripts/semantic_search/step_04_verify_search.py`:

| # | Issue | File | Status |
|---|-------|------|--------|
| 1 | `STRSTARTS(STR(?seg), "{parent_uri}")` violates URI opacity rule — replaced with edge traversal via `vital:hasEdgeSource`/`vital:hasEdgeDestination` | `vitalgraph/kg_impl/kgdocuments_read_impl.py:182` | Fixed |
| 2 | Entity Registry geo/fuzzy/hybrid failures — root cause: `_pg_sync_entity` silently fails if vectorizer unavailable at creation time. Fix: added `POST /admin/populate-vectors` endpoint + client method, test now calls `populate_vectors()` after entity creation to force full rebuild of vec/FTS/geo tables. Fuzzy requires server fuzzy_index to be initialized. | `endpoint/entity_registry_endpoint.py`, `step_03_insert_data.py` | Fixed (vec/geo); fuzzy requires server config |
| 3 | SPARQL `vg:withinRadius` geo search (NYC radius) returns 0 — test passed `20` (meters) instead of `20000` (meters=20km) | `test_scripts/semantic_search/verify/verify_geo.py` | Fixed |
| 4 | `hybridSearch` was constructing FTS/vector table names directly from index_name arg without resolving via search_mapping_index junction table. Fix: (a) added `_resolve_index_name` helper + `search_mapping_meta` pre-load in generator.py, (b) added `add_index`/`remove_index` client methods, (c) test setup creates a search mapping with both vector+fts index associations via REST API | `vitalgraph/db/sparql_sql/vg_functions.py`, `generator.py`, `emit_context.py`, client endpoint | Fixed |
| 5 | `list_kgdocuments` returns 0 — `_exclude_segment_types` sentinel key treated as property URI in SPARQL generation | `vitalgraph/kg_impl/kg_graph_retrieval_utils.py` | Fixed |
| 6 | KG type queries used wrong namespace (`vg:KGEntityType` instead of `haley:KGEntityType`) | `test_scripts/semantic_search/verify/verify_kg_types.py` | Fixed |
| 7 | Missing `PREFIX vital:` in document_segments vector search SPARQL query | `test_scripts/semantic_search/verify/verify_kgdocuments.py` | Fixed |
| 8 | `list_segments` returns 0 — three root causes: (a) `segmentation_worker._store_segmentation_output` used `add_rdf_quads_batch` (no edge table sync); (b) `_SparqlSQLDbOpsAdapter` missing `add_rdf_quads_batch_bulk` delegation; (c) `hasKGDocumentSegmentTypeURI` queried as string literal but stored as URI | `segmentation_worker.py:579`, `sparql_sql_space_impl.py:224`, `kgdocuments_read_impl.py:186`, `kg_graph_retrieval_utils.py:728` | Fixed |

| 9 | `sp_semantic_search_test` space missing `kgtype_default` index mappings — other spaces (e.g. `framenet_kgtypes_test`) have them auto-created for `kgtype` with type URIs `KGEntityType`, `KGFrameType`, `KGSlotType`. The semantic search test space only has `kgentity` and `kgdocument_segment` mappings. Fix: mappings are now auto-created during space creation via `kgtype_index_setup.py`. Confirmed present in UI. | Space creation / `kgtype_index_setup.py` | Fixed |
| 10 | `EmbeddingModel.vectorize(list)` cache-ordering bug — when some texts are already cached, results returned as `[all cached, then newly computed]` instead of input order. Breaks positional correspondence, causing embeddings to be stored under wrong subject UUIDs. Fix: vectorize per-item in `_vectorize_batch_sync` to preserve order via individual cache lookups. | `vitalgraph/vectorization/vitalsigns_provider.py` | Fixed |
| 11 | Vector driving top-K optimization loses results — `_try_vector_driving_extend` does `child_sql INNER JOIN vector_top_k_subquery`. When the top-K vectors include subjects NOT in the child pattern (e.g., slots scoring high on "italian" but lacking `hasName`), the INNER JOIN filters them out, returning fewer than LIMIT results. Fix: push child set as `subject_uuid IN (SELECT DISTINCT uuid FROM child_sql)` filter into the vector driving subquery so top-K only considers subjects present in the child pattern. | `vitalgraph/db/sparql_sql/emit_extend.py`, `vg_functions.py` | Fixed |
| 12 | Vector populator indexes ALL subjects regardless of `mapping_type` — `populate_index` uses `ALL_SUBJECTS_SQL` when `type_uri` is None, indexing everything in the graph (entities, frames, slots, docs, edges). Fix: added `VITALTYPE_SUBJECTS_SQL` query that filters by `vital-core:vitaltype` property using `ANY($2::text[])`. Added `_resolve_vitaltype_filter(mapping_type)` which uses VitalSigns `ontology_manager.get_subclass_uri_list()` to dynamically discover all subclasses of the base class (e.g., `kgtype` → 44 KGType subclasses, `kgentity` → KGEntity + 3 subclasses). Results cached per base class. When `type_uri` is None but `mapping_type` is set, the populator now filters subjects to only those with matching vitaltypes. | `vitalgraph/vectorization/vector_populator.py` | Fixed |

### Test Setup: Required Index Mappings (`step_02_create_mappings.py`)

The test space `sp_semantic_search_test` requires the following index mappings to be created
before `step_03_insert_data` and `step_04_verify_search` can pass. The `step_02_create_mappings.py`
script creates these via the client API.

**Indexes created:**

| Index Name | Kind | Dimensions | Provider | Purpose |
|-----------|------|-----------|----------|---------|
| `entity_vector` | Vector | 384 (cosine) | vitalsigns | Semantic search on entities |
| `entity_fts` | FTS | — (english) | — | Full-text search on entities |
| `entity_fuzzy` | Fuzzy | k=3, perm=64 | — | Fuzzy name matching |
| `kgtype_default` | Vector | 384 (cosine) | vitalsigns | KG Type semantic search (auto-created) |
| `document_segments` | Vector | 384 (cosine) | vitalsigns | Document segment search (auto-created) |

**Mappings created:**

| Index Name | Mapping Type | Type URI | Properties | Notes |
|-----------|-------------|----------|-----------|-------|
| `entity_vector` | kgentity | — (all entities) | hasName, hasKGraphDescription, hasTextSlotValue | Vector mapping |
| `entity_fts` | kgentity | — (all entities) | hasName, hasKGraphDescription, hasTextSlotValue | FTS mapping |
| `entity_vector` | kgentity | — (all entities) | — | Hybrid mapping (links vector + FTS indexes) |
| `entity_fuzzy` | kgentity | — (all entities) | hasName | Fuzzy name matching |
| `kgtype_default` | kgtype | — (base, all types) | — | Auto-created, default properties |
| `kgtype_default` | kgtype | KGEntityType | — | Auto-created, entity type override |
| `kgtype_default` | kgtype | KGFrameType | — | Auto-created, frame type override |
| `kgtype_default` | kgtype | KGSlotType | — | Auto-created, slot type override |
| `document_segments` | kgdocument_segment | urn:kgdoctype:document_segment | — | Auto-created |

**KG Types inserted (14 total):**

| Class | Count | Examples |
|-------|-------|---------|
| KGEntityType | 3 | RestaurantEntity, LandmarkEntity, ArticleEntity |
| KGFrameType | 3 | LocationFrame, DescriptionFrame, MetadataFrame |
| KGSlotType | 5 | CitySlot, CountrySlot, SummarySlot, CategorySlot, YearSlot |
| KGRelationType | 2 | NearRelation, MentionsRelation |

**Fixed — duplicate `entity_vector` mapping:**
The hybrid mapping now uses a distinct `entity_hybrid` index name (see `config.py:HYBRID_INDEX_NAME`)
instead of reusing `entity_vector`. This eliminates the duplicate row in the UI.

**Properties used in mappings:**
- `http://vital.ai/ontology/vital-core#hasName` — entity/type name
- `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription` — entity description
- `http://vital.ai/ontology/haley-ai-kg#hasTextSlotValue` — slot text value

**Geo config:** Enabled with auto_sync. Detects `vital-core#geoLocation` and `geosparql#wktLiteral` datatypes.

### Outstanding Failures (62/71 passing)

| # | Test | Root Cause |
|---|------|------------|
| 1 | Fuzzy top result contains 'Pizza' | Fuzzy ranking returns 'CategorySlot' — trigram similarity not matching expected entity |
| 2 | LocationFrame query returns results: count=0 | **Fixed** — verified passing after reindex with vitaltype filtering. Reindex on `entity_vector` confirmed 16 LocationFrame results via `hasKGFrameType` SPARQL query. |
| 3 | DescriptionFrame query returns results: count=0 | **Fixed** — same as #2, passing after reindex. |
| 4 | Vector search on ArticleEntity returns results: count=0 | **Fixed** — verified passing after reindex. ArticleEntity type filter + vector search returns 1 result as expected. |
| 5 | list_kgdocuments filtered by type: got 0 | `hasKGDocumentType` filter uses string literal `"uri"` syntax — should use `<uri>` if stored as URI (same class as issue #8c) |
| 6 | ER keyword: has 3 test entities: count=20 | type_key filter not isolating test data from pre-existing entities |
| 7 | ER hybrid: London finds results: count=0 | Weaviate JWT auth failing (keycloak 401) — no vector search available |
| 8 | ER fuzzy: finds Tokyo Ramen: count=0 | Fuzzy index not matching short entity names |
| 9 | AR fuzzy: finds bot despite misspelling: count=0 | Agent registry keyword search doesn't do fuzzy matching — test design issue |

**New issue discovered:**

| 13 | `kgframes_endpoint.py` uses `hasKGFrameTypeURI` in SPARQL queries (line 1540) but this property doesn't exist in the ontology. The correct property is `hasKGFrameType` (per `kg_classes_properties.md`). This affects the REST API frame_type_uri filter but NOT the test SPARQL queries (which use the correct name). | `vitalgraph/endpoint/kgframes_endpoint.py:1540` | Fixed |

---

## 17. UI Implementation Status (Jun 16, 2026)

### Completed

**Type URI Picker** — `frontend/src/components/TypeURIPicker.tsx`
- Searchable multi-select dropdown with checkbox selection
- Loads KG Types from `GET /api/graphs/kgtypes?type_uri=<class>` filtered by Object Type
- Mapping: Entity→KGEntityType, Document→KGDocumentType, Frame→KGFrameType, Type→KGType
- Chip display of selected types, Select All / Clear All actions
- Outside-click dismissal, debounced text filter
- Creates one mapping row per selected type URI on submit

**Property Selector** — `frontend/src/components/PropertySelector.tsx`
- Radio toggle: "Selected properties" vs "All (default)"
- "Selected properties" mode: searchable dropdown with common property quick-picks
- Orderable list with up/down/remove controls
- Role assignment (primary_name / alias) for Fuzzy mappings
- Custom URI entry support
- Common properties pre-populated: hasName, hasKGraphDescription, hasTextSlotValue,
  hasKGEntityType, hasKGFrameType, hasKGSlotType, hasDescription, hasKGEntityName

**IndexMappings.tsx integration:**
- Create Mapping modal now uses TypeURIPicker instead of plain TextInput for type_uri
- PropertySelector controls source_type ("properties" → `concat_properties`, "All" → `default`)
- Mapping Kind (FTS/Vector vs Fuzzy) already existed
- Multiple type URI selection creates multiple mapping rows (one per type URI)
- Form state resets on modal close

**Build fix:** `ApiService.ts:187` — removed unsupported 6th arg (`filterOpts`) from
`kgframes.list()` call. The installed TS client only accepts 5 params. Filter options
type signature preserved on the wrapper method for future client update.

### Completed (Jun 17, 2026)

- [x] Property auto-creation after mapping creation (chained `addMappingProperty` calls after create)
- [x] Ontology properties endpoint (`GET /api/ontology/properties?class_uri=...`) — backend
  `vitalgraph/endpoint/ontology_endpoint.py` + TS client `OntologyEndpoint.ts` +
  `PropertySelector` `classUri` prop for dynamic property lists
- [x] Virtualized list for large type counts (>50) in `TypeURIPicker.tsx`
- [x] Type URI display in mapping list table (truncated with tooltip)
- [x] `entity_registry` and `agent_registry` pseudo-spaces in Index Mappings + Indexes screens
- [x] Fuzzy index stats (band_count, entity_count) shown in unified Indexes list
- [x] FuzzyMappingDetail refactored into "Mapping Configuration" + "Index" sections
- [x] Dead files deleted: `VectorSearch.tsx`, `GeoPoints.tsx`
