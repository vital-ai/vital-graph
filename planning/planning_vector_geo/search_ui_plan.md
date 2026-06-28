# Search UI Plan

> **Consolidated from**: `vector_geo_ui_plan.md` (renamed Jun 2026).
> This document covers ALL search-related UI: vector, FTS, fuzzy, geo, hybrid,
> and KGType search. UI content previously scattered across multiple planning
> docs is consolidated here.

> **Major architecture change (Jun 2025):** The legacy `{space}_vector_mapping`
> table has been **removed**. All mapping operations (vector AND FTS) now use
> the shared `{space}_search_mapping` / `{space}_search_mapping_property` tables.
> Reindex and FTS populate endpoints are now **async (fire-and-forget)**.
> See `text_hybrid_search_plan.md` §6.1 and `kg_types_search_plan.md` §11.

## 1. Overview

This document covers the frontend UI for **all search and indexing subsystems**:

1. **Search Mapping Management** — CRUD for `search_mapping` + `search_mapping_property` (shared by vector AND FTS)
2. **Vector Index Management** — view/create/delete vector indexes, trigger async re-index
3. **FTS Index Management** — view/create/delete FTS indexes, trigger async populate
4. **Fuzzy Mapping Management** — CRUD for fuzzy (MinHash LSH) mappings, populate, stats
5. **Geo Data Visibility** — view geo-populated entities on a list/map
6. **Search Integration** — vector, FTS, hybrid, and fuzzy search from the UI
7. **KGType Search** — multi-mode search over type definitions (keyword, FTS, vector, hybrid)

### Backend Architecture (as of 2026-06-14)

| Table | Purpose |
|-------|---------|
| `{space}_vector_index` | Vector index registry (provider, dims, model) |
| `{space}_vec_{name}` | Per-index vector data table (pgvector HNSW) |
| `{space}_fts_index` | FTS index registry (languages) |
| `{space}_fts_{name}` | Per-index FTS data table (tsvector + GIN) |
| `{space}_search_mapping` | **Shared** mapping rules for both vector and FTS |
| `{space}_search_mapping_index` | **Junction table**: associates mappings → indexes (vector/fts) |
| `{space}_search_mapping_property` | Property include/exclude rules per mapping |
| `{space}_fuzzy_mapping` | Fuzzy (MinHash LSH) mapping configuration |
| `{space}_fuzzy_mapping_property` | Property include list per fuzzy mapping |
| `{space}_fuzzy_band_{name}` | LSH band hash tables for fuzzy candidate lookup |
| `{space}_geo` | Geo points (PostGIS) |

**Key design principle (REVISED):**

A search mapping has an `index_name` which is its **logical identifier** —
the name used in SPARQL functions like `vg:hybridSearch(?e, "text", "entity_default", 0.5)`.
The mapping defines *what* gets indexed (entity types, predicates, source
strategy).  The *association* to concrete vector/FTS indexes is managed via
an explicit junction table `{space}_search_mapping_index`.

The names of vector indexes (in `{space}_vector_index`) and FTS indexes
(in `{space}_fts_index`) are **independent** of the mapping's `index_name`.
A mapping named `"entity_default"` might link to a vector index called
`"embeddings_v1"` and an FTS index called `"fulltext_en"`.  The SPARQL
function always references the **mapping name**; the system resolves which
concrete data tables to query via the junction table.

#### Junction Table: `{space}_search_mapping_index`

```sql
CREATE TABLE IF NOT EXISTS {space}_search_mapping_index (
    id              SERIAL PRIMARY KEY,
    mapping_id      INTEGER NOT NULL,
    index_type      VARCHAR(10) NOT NULL CHECK (index_type IN ('vector', 'fts')),
    index_name      VARCHAR(255) NOT NULL,  -- name of the vector_index or fts_index
    created_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (mapping_id, index_type, index_name),
    FOREIGN KEY (mapping_id) REFERENCES {space}_search_mapping(mapping_id) ON DELETE CASCADE
);
```

**Semantics:**
- A mapping with **no rows** in the junction table → defined but not yet activated
- A mapping with an `('fts', ...)` row → FTS enabled
- A mapping with a `('vector', ...)` row → vector enabled
- A mapping with both rows → hybrid-ready (`vg:hybridSearch` resolves both
  via the junction table — vector/FTS index names do NOT need to match)

**Query resolution (SPARQL):**
```
vg:hybridSearch(?e, "text", "entity_default", 0.5)
  → lookup search_mapping WHERE index_name = 'entity_default'
  → lookup search_mapping_index WHERE mapping_id = <found>
  → finds: ('vector', 'embeddings_v1'), ('fts', 'fulltext_en')
  → JOINs: {space}_vec_embeddings_v1 ⨝ {space}_fts_fulltext_en
```

**UI implications:**
- The Search Mapping Detail page shows "Associated Indexes" with add/remove
- The Create Mapping modal requires `index_name` (the mapping's logical name)
- Indexes are attached in the detail view or optionally during creation
- The list page shows associated indexes from the junction table

**Migration path:**
- Create junction table for all spaces
- For each existing mapping: insert junction row(s) based on whether
  `_vec_{index_name}` or `_fts_{index_name}` data tables exist
- Keep `index_name` on `search_mapping` (it remains the logical identifier)

**REST endpoints (new):**
```
GET    /api/search-mappings/{id}/indexes?space_id=X
POST   /api/search-mappings/{id}/indexes?space_id=X   body: {index_type, index_name}
DELETE /api/search-mappings/{id}/indexes/{junction_id}?space_id=X
```

### Backend Readiness Summary

| Feature | Backend Status | Endpoint(s) |
|---------|---------------|-------------|
| Vector Indexes CRUD | ✅ Complete | `GET/POST/DELETE /api/vector-indexes` |
| Vector Reindex (async) | ✅ Complete | `POST /api/vector-indexes/{name}/reindex` → returns immediately |
| FTS Indexes CRUD | ✅ Complete | `GET/POST/DELETE /api/fts-indexes` |
| FTS Stats | ✅ Complete | `GET /api/fts-indexes/{name}/stats` |
| FTS Languages | ✅ Complete | `PUT /api/fts-indexes/{name}/languages` |
| FTS Populate (async) | ✅ Complete | `POST /api/fts-indexes/{name}/populate` → returns immediately |
| Search Mappings CRUD | ✅ Complete | `GET/POST/GET/{id}/PUT/{id}/DELETE/{id} /api/search-mappings` |
| Mapping Properties | ✅ Complete | `POST/DELETE /api/search-mappings/{id}/properties` |
| Fuzzy Mappings CRUD | ✅ Complete | `GET/POST/PUT/DELETE /api/fuzzy-mappings` |
| Fuzzy Properties | ✅ Complete | `GET/POST/DELETE /api/fuzzy-mappings/properties` |
| Fuzzy Populate | ✅ Complete | `POST /api/fuzzy-mappings/populate` |
| Fuzzy Stats | ✅ Complete | `GET /api/fuzzy-mappings/stats` |
| Entity Similar Search | ✅ Complete | `GET /api/entity-registry/search/similar` |
| KGType Search (multi-mode) | ✅ Complete | `GET /api/graphs/kgtypes/search?search_mode=...` |
| Geo Config | ✅ Complete | `GET/PUT /api/geo-config` |
| Geo Points | ✅ Complete | `GET /api/geo?near_lat=...&radius_km=...` |
| SPARQL pipeline | ✅ Verified | `vg:textSearch`, `vg:vectorSimilarity`, `vg:hybridSearch`, `vg:fuzzyMatch`, `vg:withinRadius` |

---

## 2. Pages & Components

### 2.1 Search Mappings Page — ✅ EXISTS (needs update)

**Route**: `/search-mappings`
**Purpose**: CRUD for the shared `search_mapping` table (used by BOTH vector and FTS).

> **Migration note:** This page replaces the legacy "Vector Mappings" page.
> The `VectorMappings.tsx` and `VectorMappingDetail.tsx` pages are **dead code**
> and should be removed — the `_vector_mapping` table no longer exists.

| Column | Source | Notes |
|--------|--------|-------|
| Class | `mapping_type` | Badge: KGEntity, KGDocument, KGFrame, KGSlot, KGType |
| Type URI | `type_uri` | `NULL` → "All (class-level)" |
| Indexes | junction table | Badges: vector/fts index names; "(none)" if unlinked |
| Enabled | `enabled` | Toggle switch (inline PUT) |
| Source | `source_type` | `default` / `properties` / `slots` |
| Properties | child count | e.g., "3 properties" or "—" |
| Created | `created_time` | Relative timestamp |

**Actions**:
- **Create Mapping** button → modal (§2.2)
- Row click / eye icon → mapping detail (§2.3)
- Inline toggle for `enabled` → `PUT /api/search-mappings/{id}`
- Delete icon → confirm dialog → `DELETE` with CASCADE warning

**Filters**:
- Filter by class (kgentity / kgdocument / kgframe / kgslot / kgtype)
- Filter by index (vector or FTS index name, from junction table)
- Filter by enabled/disabled

**REST calls**:
```
GET    /api/search-mappings?space_id=X&mapping_type=Y&enabled=true
PUT    /api/search-mappings/{id}?space_id=X       (inline toggle)
DELETE /api/search-mappings/{id}?space_id=X
```

### 2.2 Create/Edit Mapping Modal

**Fields**:

| Field | Type | Validation |
|-------|------|------------|
| Index Name | Text input | Required. Logical name for this mapping (e.g. `entity_default`). Used in SPARQL functions. |
| Class | Select | Required. Options: `kgentity`, `kgdocument`, `kgframe`, `kgslot`, `kgtype` |
| Type URI | Text input | Optional. Placeholder: "Leave empty for class-level default" |
| Enabled | Checkbox | Default: true |
| Source Type | Select | `default`, `properties`, `slots`. Default: `default` |
| Separator | Text input | Default: `". "`. Only shown when source_type ≠ `default` |
| Include Predicate Name | Checkbox | Default: false |
| Include Type Description | Checkbox | Default: true |

> **Note:** `index_name` is the mapping's logical identifier — the name
> referenced in SPARQL queries (`vg:hybridSearch`, `vg:textSearch`, etc.).
> It does NOT need to match the name of any vector or FTS index.  The
> association to concrete indexes is managed via the junction table
> (see §2.3 detail view "Associated Indexes" section).

**Optional "Associate Index" section in create modal:**
- Dropdown: select an existing vector or FTS index to associate immediately
- Or leave empty — indexes can be attached later in the detail view

**Conditional properties section** (visible when source_type = `properties` or `slots`):
- Orderable list of property URIs with role (include/exclude) and drag handle
- "Add Property" button appends a row
- Delete icon removes a row

**REST calls**:
```
POST   /api/search-mappings?space_id=X
PUT    /api/search-mappings/{id}?space_id=X
POST   /api/search-mappings/{id}/properties?space_id=X
DELETE /api/search-mappings/{id}/properties/{pid}?space_id=X
POST   /api/search-mappings/{id}/indexes?space_id=X      (associate index)
DELETE /api/search-mappings/{id}/indexes/{jid}?space_id=X (disassociate index)
```

### 2.3 Mapping Detail View — ✅ PAGE EXISTS (needs junction table update)

**Route**: `/space/:spaceId/search-mappings/:mappingId`

**Sections**:
1. **Header** — class badge, type URI, enabled toggle, save/delete buttons
2. **Configuration** — source_type, separator, include flags (editable)
3. **Associated Indexes** — list of linked vector/FTS indexes from junction table
   - Each row shows: index type badge (vector/fts), index name, remove button
   - "Add Index" button → modal with:
     - Index Type selector: `vector` | `fts`
     - Index Name dropdown: populated from `GET /api/vector-indexes` or
       `GET /api/fts-indexes` depending on selected type
   - REST: `POST /api/search-mappings/{id}/indexes`, `DELETE .../indexes/{jid}`
4. **Properties Table** — ordered list of `search_mapping_property` rows
   - Columns: Ordinal, Property URI, Role
   - Drag-to-reorder (future)
   - Add/remove buttons

### 2.4 Vector Indexes Page — ✅ COMPLETE

**Route**: `/vector-indexes`
**Purpose**: List and manage vector indexes.

| Column | Source | Notes |
|--------|--------|-------|
| Index Name | `index_name` | Primary key |
| Provider | `provider` | `vitalsigns`, `openai`, etc. |
| Dimensions | `dimensions` | 384, 1536, etc. |
| Model | `model_name` | Embedding model identifier |
| Embeddings | `embedding_count` | Count from data table |
| Created | `created_time` | Relative timestamp |

**Actions**:
- **Create Index** → modal (name, provider, dimensions, model, metric, description)
- **Reindex** → fires async background task, shows "Reindex started" toast
- **Delete** → confirm with data-loss warning

**Reindex is async** — the endpoint returns immediately with
`{"message": "Reindex started", "index_name": "..."}`.
The UI should show a toast/banner and optionally poll `GET /api/vector-indexes`
to observe `embedding_count` increasing.

**REST calls**:
```
GET    /api/vector-indexes?space_id=X
POST   /api/vector-indexes?space_id=X
DELETE /api/vector-indexes?space_id=X&index_name=Y
POST   /api/vector-indexes/{name}/reindex?space_id=X   (async — returns immediately)
```

### 2.5 FTS Indexes Page — ✅ COMPLETE

**Route**: `/fts-indexes`
**Purpose**: List and manage FTS indexes.

| Column | Source | Notes |
|--------|--------|-------|
| Index Name | `index_name` | Primary key |
| Languages | `languages` | Badge per language |
| Row Count | `row_count` (from stats or list) | Documents indexed |
| Created | `created_time` | Relative timestamp |

**Actions**:
- **Create Index** → modal (name, languages comma-separated)
- **Stats** → modal showing row_count, distinct_entity_count, has_tsv_count
- **Populate** → fires async background task, shows "Population started" toast
- **Update Languages** → modal to change language list
- **Delete** → confirm with data-loss warning

**Populate is async** — the endpoint returns immediately with
`{"message": "FTS population started for '...'", "rows_populated": 0}`.
The UI should show a toast and optionally poll stats to observe row_count
increasing.

**REST calls**:
```
GET    /api/fts-indexes?space_id=X
POST   /api/fts-indexes?space_id=X
DELETE /api/fts-indexes?space_id=X&index_name=Y
GET    /api/fts-indexes/{name}/stats?space_id=X
PUT    /api/fts-indexes/{name}/languages?space_id=X
POST   /api/fts-indexes/{name}/populate?space_id=X     (async — returns immediately)
```

### 2.6 Geo Data Page — ✅ EXISTS (working)

**Route**: `/geo-points`
**Purpose**: Map + table view of geo-populated entities.

Features (all implemented):
- OpenStreetMap via react-leaflet (default) + Google Maps (if API key set)
- Point markers with click popups
- Radius circle overlay for spatial queries
- Geo search panel (lat/lon/radius inputs)
- Auto-fit bounds, pagination, table/map toggle

### 2.7 Search Integration — ✅ EXISTS (working)

**Route**: `/vector-search`
**Purpose**: Vector similarity + FTS search via SPARQL pipeline.

Features:
- Mode toggle: Vector / Full-Text / Hybrid
- Index selector, top-K, min-score controls
- Results table with similarity/rank scores
- All modes go through SPARQL pipeline (`vg:vectorSimilarity`, `vg:textSearch`, `vg:hybridSearch`)

---

## 3. Navigation (Current — needs cleanup)

Current sidebar under "Vector, Geo & Search":
```
├─ Vector Indexes        ← ✅ keep
├─ Vector Mappings       ← ❌ REMOVE (dead — table no longer exists)
├─ Vector Search         ← ✅ keep
├─ Geo Points            ← ✅ keep
├─ Fuzzy Mappings        ← ✅ keep
├─ Search Mappings       ← ✅ keep (this is the correct mapping page)
└─ FTS Indexes           ← ✅ keep
```

**Required changes:**
1. Remove "Vector Mappings" link → dead page referencing deleted table
2. Remove route `/vector-mappings` and `/vector-mappings/:id` from App.tsx
3. Delete `VectorMappings.tsx` and `VectorMappingDetail.tsx` (or mark deprecated)
4. Remove `vectorMappings.*` methods from `VectorGeoService.ts`

---

## 4. Component Inventory (Current)

| Component | Location | Status | Notes |
|-----------|----------|--------|-------|
| `SearchMappings.tsx` | `pages/` | ✅ Working | Replaces VectorMappings for shared mappings |
| `FtsIndexes.tsx` | `pages/` | ✅ Working | Async populate shows server message |
| `VectorIndexes.tsx` | `pages/` | ✅ Working | Async reindex shows server message |
| `VectorSearch.tsx` | `pages/` | ✅ Working | Multi-mode search |
| `GeoPoints.tsx` | `pages/` | ✅ Working | Map + table |
| `FuzzyMappings.tsx` | `pages/` | ✅ Working | Fuzzy search mappings |
| `FuzzyMappingDetail.tsx` | `pages/` | ✅ Working | Detail view |
| ~~`VectorMappings.tsx`~~ | — | ✅ Removed | Deleted (Jun 2026) |
| ~~`VectorMappingDetail.tsx`~~ | — | ✅ Removed | Deleted (Jun 2026) |

---

## 5. API Services (Current)

### `SearchFtsService.ts` — ✅ Correct
Manages search mappings and FTS indexes via `vgClient.searchMappings.*` and
`vgClient.ftsIndexes.*`.

### `VectorGeoService.ts` — ✅ Cleaned up
- **Vector Indexes section** — ✅ correct (reindex returns async message)
- **Geo section** — ✅ correct
- Dead `vectorMappings.*` methods removed (Jun 2026)

### TypeScript Types

**`types/searchFts.ts`** — ✅ Correct (SearchMapping, FtsIndex, etc.)

**`types/vectorGeo.ts`** — ✅ Cleaned up:
- Dead types removed: `VectorMapping`, `CreateVectorMappingRequest`, `UpdateVectorMappingRequest`,
  `MappingProperty`, `MappingListResponse` (Jun 2026)
- `ReindexResponse` updated to: `{ message: string; index_name: string }`

---

## 6. Required UI Fixes

### Fix 1: Vector Indexes — Async Reindex

**File**: `VectorIndexes.tsx`

The reindex endpoint now returns `{ message: "Reindex started", index_name: "..." }`.
The UI currently tries to display `result.subjects_processed` / `result.embeddings_stored`.

**Fix**: Show a success toast with the message string. Optionally poll
`GET /api/vector-indexes` to show embedding_count updates.

### Fix 2: FTS Indexes — Async Populate

**File**: `FtsIndexes.tsx`

The populate endpoint now returns immediately with `rows_populated: 0`.
The UI currently shows "Populated: 0 rows in 0.0s" which is misleading.

**Fix**: Show a success toast: "FTS population started for '{index_name}'".
Optionally poll stats endpoint to show row_count increasing.

### Fix 3: Remove Dead Vector Mappings

**Files to remove/deprecate**:
- `VectorMappings.tsx`
- `VectorMappingDetail.tsx`
- Sidebar link in `Layout.tsx`
- Routes in `App.tsx`
- `vectorMappings` methods in `VectorGeoService.ts`
- Dead types in `types/vectorGeo.ts`

---

## 7. UX Notes

- **Async operations**: Reindex and FTS populate are now fire-and-forget.
  Show "Started" toast immediately. Consider a polling mechanism or status
  badge that shows "Indexing..." based on embedding_count / row_count changes.
- **Enabled toggle**: Optimistic update — flip immediately, revert on API error.
- **Property ordering**: `@dnd-kit/sortable` for drag-and-drop.
- **Destructive actions**: Delete index warns about data loss AND associated
  search_mapping cascade.
- **Empty states**: Search Mappings page with no mappings shows explanatory card.

---

## 8. Dependencies

| Dependency | Purpose | Status |
|------------|---------|--------|
| `leaflet` + `react-leaflet` | OpenStreetMap | ✅ Installed |
| `@vis.gl/react-google-maps` | Google Maps (optional) | ✅ Installed |
| `@dnd-kit/sortable` | Property list drag-and-drop | ✅ Installed |
| Flowbite React | UI components | ✅ In project |

---

## 9. Fuzzy Mappings UI — ✅ COMPLETE

Consolidated from `fuzzy_search_implementation_plan.md` Phase 5.

**Route**: `/fuzzy-mappings` (list) and `/fuzzy-mappings/:id` (detail)
**Purpose**: Manage MinHash LSH fuzzy matching indexes per space.

### Pages

| Component | File | Status |
|-----------|------|--------|
| `FuzzyMappings.tsx` | `frontend/src/pages/` | ✅ Working |
| `FuzzyMappingDetail.tsx` | `frontend/src/pages/` | ✅ Working |
| `FuzzyMappingService.ts` | `frontend/src/services/` | ✅ Working |
| `types/fuzzyMappings.ts` | `frontend/src/types/` | ✅ Working |

### Features (all implemented)

| Feature | Description |
|---------|-------------|
| List fuzzy mappings | Table: index_name, type, enabled, shingle_k, threshold |
| Create mapping | Form: index name, mapping type, entity type URI, shingle_k, num_perm, lsh_threshold, phonetic_bonus |
| Edit mapping | Modal for tuning parameters |
| Delete mapping | Confirm dialog + cascade delete bands |
| Manage properties | Sub-table per mapping: property URIs with role (primary/alias/include) + ordinal |
| Enable/disable toggle | Quick toggle preserving bands |
| Populate index | Button triggers full re-population |
| Index stats | Band count, entity count, phonetic band count, last populated |

### REST Endpoints

```
GET    /api/fuzzy-mappings?space_id=X
POST   /api/fuzzy-mappings?space_id=X
GET    /api/fuzzy-mappings?space_id=X&mapping_id=Y
PUT    /api/fuzzy-mappings?space_id=X&mapping_id=Y
DELETE /api/fuzzy-mappings?space_id=X&mapping_id=Y
GET    /api/fuzzy-mappings/properties?space_id=X&mapping_id=Y
POST   /api/fuzzy-mappings/properties?space_id=X&mapping_id=Y
DELETE /api/fuzzy-mappings/properties?space_id=X&mapping_id=Y&property_id=Z
POST   /api/fuzzy-mappings/populate?space_id=X&mapping_id=Y
GET    /api/fuzzy-mappings/stats?space_id=X&mapping_id=Y
```

---

## 10. KGType Search UI — ✅ COMPLETE

Consolidated from `planning_visualization/kg_types_search_plan.md` §6.

**Location**: Integrated into `kgtypes_endpoint.py` — `GET /api/graphs/kgtypes/search`

The KGType search endpoint supports **four modes**, all routed through the SPARQL
pipeline. No dedicated UI page — search is embedded in the KGTypes list page
and the VectorSearch page.

| Mode | SPARQL Function | Index Required | Vectorization |
|------|----------------|----------------|---------------|
| `keyword` | `FILTER(CONTAINS(...))` | None | No |
| `fts` | `vg:textSearch` | FTS index (`_fts_` table) | No |
| `vector` | `vg:vectorSimilarity` | Vector index (`_vec_` table) | Yes |
| `hybrid` | `vg:hybridSearch` | Both FTS + vector | Yes |

### REST API

```
GET /api/graphs/kgtypes/search?space_id=X&q=Z&search_mode=vector&alpha=0.6
```

- `search_mode`: `keyword` (default), `fts`, `vector`, `hybrid`
- `alpha` (hybrid only): 0.0 = pure BM25, 1.0 = pure vector, default 0.5
- `type`: optional filter (`frame`, `entity`, `slot`, `relation`)
- `graph_id` parameter **removed** (Jun 2026) — server derives from space_id

### VectorSearch.tsx Integration

The existing Vector Search page (`/vector-search`) already supports:
- Mode toggle: Vector / Full-Text / Hybrid
- Index selector (populated from vector-indexes and fts-indexes endpoints)
- Top-K, min-score sliders
- Results table with similarity/rank scores
- Works for both entity-level and type-level search via index selection

---

## 11. Geo Data UI — ✅ COMPLETE

Consolidated from `vector_geo_plan.md` and `geo_fuzzy_search_testing_plan.md`.

**Route**: `/geo-points`
**Purpose**: Map + table view of geo-populated entities with spatial queries.

### Features

| Feature | Status |
|---------|--------|
| OpenStreetMap via `react-leaflet` (default) | ✅ |
| Google Maps via `@vis.gl/react-google-maps` (if API key set) | ✅ |
| Point markers with click-to-inspect popups | ✅ |
| Radius circle overlay for spatial queries | ✅ |
| Geo search panel (lat/lon/radius inputs) | ✅ |
| Auto-fit bounds on data change | ✅ |
| Pagination for large result sets | ✅ |
| Toggle between map and table view | ✅ |
| Entity detail mini-map (EntityGeoMiniMap component) | ✅ |
| Provider selection persisted in localStorage | ✅ |

### Map Provider Architecture

```tsx
interface MapViewProps {
  points: GeoPoint[];
  center?: [number, number];
  zoom?: number;
  radiusCircle?: { lat: number; lon: number; radiusKm: number };
  onPointClick?: (point: GeoPoint) => void;
}
// Delegates to <OSMMap> or <GoogleMap> based on preference
```

- Google Maps only shown if `VITE_GOOGLE_MAPS_API_KEY` env var is set
- Default: OpenStreetMap (free, no API key)

### REST Endpoints

```
GET /api/geo?space_id=X                                   (list all)
GET /api/geo?space_id=X&near_lat=40.7&near_lon=-74.0&radius_km=50  (spatial)
GET /api/geo?space_id=X&graph_uri=urn:graph:1&limit=50&offset=0    (scoped)
GET /api/geo-config?space_id=X                            (config)
PUT /api/geo-config?space_id=X                            (update config)
```

---

## 12. Implementation Status Summary

| Page / Feature | Route | Status | Notes |
|----------------|-------|--------|-------|
| Search Mappings | `/search-mappings` | ✅ Working | Shared mapping CRUD (vector + FTS) |
| Vector Indexes | `/vector-indexes` | ✅ Working | Async reindex shows server message |
| FTS Indexes | `/fts-indexes` | ✅ Working | Async populate shows server message |
| Fuzzy Mappings | `/fuzzy-mappings` | ✅ Working | LSH mapping CRUD + populate + stats |
| Fuzzy Mapping Detail | `/fuzzy-mappings/:id` | ✅ Working | Properties, stats, populate |
| Geo Points | `/geo-points` | ✅ Working | Map + table + spatial query |
| Vector Search | `/vector-search` | ✅ Working | Multi-mode: vector/FTS/hybrid |
| KGType Search | (embedded in kgtypes) | ✅ Working | keyword/fts/vector/hybrid modes |
| ~~Vector Mappings~~ | `/vector-mappings` | ✅ Removed | Deleted Jun 2026 |
| ~~Vector Mapping Detail~~ | `/vector-mappings/:id` | ✅ Removed | Deleted Jun 2026 |

---

## 13. Bug Fixes — `vg:fuzzyMatch` SPARQL Resolve (June 15, 2026)

Three bugs were identified and fixed in `vg_resolve.py` → `_fuzzy_via_minhash()`:

### Bug 1: Phonetic `P::` Prefix Corruption

**Root cause**: The phonetic LSH band table stores entity keys as `P::uuid::variant`.
When phonetic hits were merged into the shared `hits` dict without stripping the
`P::` prefix, `extract_entity_ids()` parsed them as entity ID `"P::uuid"` — which
then failed `UUID("P::uuid")` conversion silently, yielding 0 valid candidates.

**Fix**: Strip `P::` prefix from phonetic keys before merging into `hits`:
```python
if key.startswith("P::"):
    key = key[3:]
```

### Bug 2: Step 3 Guard Prevented Typo Variants

**Root cause**: Step 3 (typo variants) was guarded by `if not extract_entity_ids(hits)`.
After Step 2 (phonetic) produced `P::` prefixed hits, `extract_entity_ids()` returned
a non-empty set of INVALID IDs — fooling the guard into skipping Step 3 entirely.

**Fix**: Always run Step 3 unconditionally. All 3 steps accumulate candidates, then
the final `extract_entity_ids()` filters and scores them together.

### Bug 3: Description Indexed in Fuzzy Mapping

**Root cause**: The test setup (`step_02_create_mappings.py`) added both `hasName`
AND `hasKGraphDescription` to the fuzzy mapping. The description text became
variant `::0`, pushing the actual name to variant `::1`. This diluted the MinHash
signal — the description's shingles are very different from a misspelled name query.

**Fix**: Only index `hasName` in the fuzzy mapping for name-based fuzzy matching.

### Impact

All 71/71 semantic search tests now pass. The `vg:fuzzyMatch` SPARQL function
correctly resolves via MinHash LSH (phonetic + typo variants) + RapidFuzz scoring.
Query "Joes Piza" matches "Joe's Pizza" with score 100.0.

---

## 14. Cross-References

- **FTS Decoupling plan**: `planning_vector_geo/text_hybrid_search_plan.md` §6.1
- **KG Types Search**: `planning_visualization/kg_types_search_plan.md` §6, §11
- **Fuzzy Search**: `planning_vector_geo/fuzzy_search_implementation_plan.md` Phase 5
- **Geo/Fuzzy Gaps**: `planning_vector_geo/geo_fuzzy_search_gaps.md`
- **Backend vector_geo plan**: `planning_vector_geo/vector_geo_plan.md`
- **Auth**: All search admin pages gated to admin/space_admin roles
- **E2E tests**: `test_scripts/test_vector_geo_e2e.py`, `test_kgtype_search_framenet.py`, `test_fuzzy_mapping_endpoints.py`
