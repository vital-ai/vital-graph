# Web UI Update Plan

## Overview

The VitalGraph web UI (React + Flowbite + Vite) is significantly out of date relative to the current REST API surface. This plan catalogs every gap and outlines the work required to bring the frontend into alignment.

**Frontend stack**: React 19, Flowbite-React 0.11, TailwindCSS 4, Vite 6, Axios, React Router 7  
**Backend stack**: FastAPI, JWT auth, PostgreSQL (sparql_sql / fuseki_postgresql backends)  
**Build output**: `frontend/dist` → `vitalgraph/api/frontend/`

---

## 1. Current State Summary

### 1.1 Pages That Exist in the Frontend

| Page | File | Data Source | Status |
|------|------|-------------|--------|
| Home | `Home.tsx` | Static | OK — minor updates needed |
| Login | `Login.tsx` | `/api/login` | ✅ Working |
| Spaces | `Spaces.tsx` | `/api/spaces` (real) | Partially working |
| SpaceDetail | `SpaceDetail.tsx` | `/api/spaces/{id}` (real) | Partially working |
| Users | `Users.tsx` | `/api/users` (real) | Partially working |
| UserDetail | `UserDetail.tsx` | `/api/users/{id}` (real) | Partially working |
| Graphs | `Graphs.tsx` | `/api/graphs/sparql/{space}/graphs` (real) | Partially working |
| GraphDetail | `GraphDetail.tsx` | Real API | Partially working |
| GraphAnalysis | `GraphAnalysis.tsx` | Mock data | ❌ Needs real API |
| Objects (list) | `GraphObjects.tsx` | Real API (partial) | Needs updates |
| ObjectsLayout | `ObjectsLayout.tsx` | Real API (partial) | Needs updates |
| ObjectDetail | `ObjectDetail.tsx` | Real API (partial) | Needs updates |
| KGEntities | `KGEntities.tsx` | Real API (partial) | Needs updates |
| KGEntityDetail | `KGEntityDetail.tsx` | Real API (partial) | Needs major updates |
| KGFrames | `KGFrames.tsx` | Real API (partial) | Needs updates |
| KGFrameDetail | `KGFrameDetail.tsx` | Real API (partial) | Needs major updates |
| KGTypes | `KGTypes.tsx` | Real API | Partially working |
| KGTypeDetail | `KGTypeDetail.tsx` | Real API | Partially working |
| Triples | `Triples.tsx` | Real API | Partially working |
| SPARQL | `SPARQL.tsx` | Real API | Partially working |
| Files | `Files.tsx` | **Mock data** | ❌ Needs real API |
| FileDetail | `FileDetail.tsx` | **Mock data** | ❌ Needs real API |
| FileUpload | `FileUpload.tsx` | **Mock data** | ❌ Needs real API |
| Data (Import) | `Data.tsx` | **Mock data** | ❌ Needs real API |
| DataImportDetail | `DataImportDetail.tsx` | **Mock data** | ❌ Needs real API |
| DataExportDetail | `DataExportDetail.tsx` | **Mock data** | ❌ Needs real API |
| DataMigrationDetail | `DataMigrationDetail.tsx` | **Mock data** | ❌ Needs real API |
| DataTrackingDetail | `DataTrackingDetail.tsx` | **Mock data** | ❌ Needs real API |
| DataCheckpointDetail | `DataCheckpointDetail.tsx` | **Mock data** | ❌ Needs real API |

### 1.2 API Endpoints With No Frontend Page

| API Endpoint Group | Prefix | Status in UI |
|---------------------|--------|-------------|
| **Entity Registry** | `/api/registry/entities`, `/api/registry/aliases`, `/api/registry/identifiers`, `/api/registry/categories`, `/api/registry/locations`, `/api/registry/relationships`, `/api/registry/sameas`, `/api/registry/search/*`, `/api/registry/changelog` | ❌ No UI at all |
| **Agent Registry** | `/api/agents/` (CRUD for agents, agent types, agent endpoints) | ❌ No UI at all |
| **KG Relations** | `/api/graphs/kgrelations` (CRUD + query) | ❌ No UI at all |
| **KG Queries** | `/api/graphs/kgqueries` (criteria-based entity/frame queries) | ❌ No UI at all |
| **Processes** | `/api/processes` (list, detail, trigger, scheduler status) | ❌ No UI at all |
| **Admin** | `/api/admin/resync` | ❌ No UI at all |
| **SPARQL Insert** | `/api/graphs/sparql/{space}/insert` | ❌ No UI (SPARQL page only does query) |
| **SPARQL Update** | `/api/graphs/sparql/{space}/update` | ❌ No UI |
| **SPARQL Delete** | `/api/graphs/sparql/{space}/delete` | ❌ No UI |
| **File Upload/Download** | `/api/files/{space}/upload`, `/api/files/{space}/download` | ❌ No UI (file pages use mock) |

### 1.3 Mock Data Still in Use

The `frontend/src/mock/` directory contains hardcoded mock data used by many pages:
- `spaces.ts` — Space type with numeric `id` field (API uses string `space` field)
- `graphs.ts` — Graph type with numeric `id` (API uses `graph_uri` string)
- `objects.ts` — Hardcoded RDF objects
- `files.ts` — Hardcoded file listings
- `triples.ts` — Hardcoded triple data
- `kgtypes.ts` — Hardcoded KG type data

**20 pages** still import from `../mock`. These mock types are used as component prop types even in pages that make real API calls, causing type mismatches.

### 1.4 ApiService Coverage Gap

`ApiService.ts` only covers:
- Spaces CRUD
- Users list
- SPARQL query execution
- Graphs CRUD
- Triples CRUD
- Health check

Missing from ApiService:
- Objects CRUD
- KGEntities CRUD (frames sub-endpoints)
- KGFrames CRUD (slots sub-endpoints)
- KGTypes CRUD
- KGRelations CRUD
- KGQuery
- Files CRUD + upload/download
- Import/Export jobs
- Entity Registry (all sub-resources)
- Agent Registry
- Processes
- Admin operations

---

## 2. Work Items — Prioritized

### Phase 1: Foundation & Type System (HIGH PRIORITY)

#### 1.1 Replace Mock Types with API-Aligned Types
- **Create `types/spaces.ts`** — `SpaceInfo` type matching API response (`space: string`, no numeric `id`)
- **Create `types/graphs.ts`** — `GraphInfo` type matching API (`graph_uri`, `triple_count`)
- **Create `types/objects.ts`** — Quad-based object types matching `QuadRequest`/`QuadResponse`
- **Create `types/kgentities.ts`** — Entity types matching `EntityCreateResponse`, `EntityDeleteResponse`, etc.
- **Create `types/kgframes.ts`** — Frame types matching `FrameCreateResponse`, etc.
- **Create `types/kgtypes.ts`** — KGType types matching `KGTypeCreateResponse`, etc.
- **Create `types/files.ts`** — File types matching `FileCreateResponse`, etc.
- **Create `types/kgrelations.ts`** — Relation types matching API models
- **Create `types/import_export.ts`** — Import/Export job types
- **Create `types/entity_registry.ts`** — Entity, Alias, Identifier, Category, Location, Relationship, SameAs types
- **Create `types/agent_registry.ts`** — Agent, AgentType, AgentEndpoint types
- **Create `types/processes.ts`** — Process, SchedulerStatus types
- **Update `types/api.ts`** — Consolidate existing types, remove duplicates
- **Delete `mock/` directory** after all pages are migrated

#### 1.2 Expand ApiService
Add methods to `ApiService.ts` for every endpoint group:

- **Objects**: `getObjects()`, `createObjects()`, `updateObjects()`, `deleteObjects()`
- **KGEntities**: `getEntities()`, `createEntity()`, `updateEntity()`, `deleteEntity()`, `getEntityFrames()`, `createEntityFrame()`, `deleteEntityFrames()`, `queryEntities()`
- **KGFrames**: `getFrames()`, `createFrame()`, `updateFrame()`, `deleteFrame()`, `createSlot()`, `updateSlot()`, `deleteSlot()`
- **KGTypes**: `getKGTypes()`, `createKGType()`, `updateKGType()`, `deleteKGType()`
- **KGRelations**: `getRelations()`, `createRelation()`, `updateRelation()`, `deleteRelation()`, `queryRelations()`
- **Files**: `getFiles()`, `createFileNode()`, `updateFileNode()`, `deleteFileNode()`, `uploadFileContent()`, `downloadFileContent()`
- **Import/Export**: `createImportJob()`, `listImportJobs()`, `getImportJob()`, `executeImport()`, `getImportStatus()` (same for export)
- **Entity Registry**: Full CRUD for entities, aliases, identifiers, categories, locations, relationships, same-as, search (similar + semantic + geo), entity types, location types, relationship types, changelog
- **Agent Registry**: `listAgents()`, `createAgent()`, `updateAgent()`, `deleteAgent()`, `listAgentTypes()`, `createAgentType()`, agent endpoints CRUD
- **Processes**: `listProcesses()`, `getProcess()`, `triggerProcess()`, `getSchedulerStatus()`
- **Admin**: `resyncSpace()`
- **SPARQL**: `executeSparqlInsert()`, `executeSparqlUpdate()`, `executeSparqlDelete()`

---

### Phase 2: Fix Existing Pages (HIGH PRIORITY)

#### 2.1 Spaces Page
- Replace mock `Space` type with API-aligned type (string `space` field, not numeric `id`)
- Ensure create/update/delete use `ApiService` methods
- Add `space_description` display
- Fix navigation links to use `space` string ID

#### 2.2 Graphs Page
- Replace mock `Graph` type with API-aligned type (`graph_uri` string)
- Display `triple_count`, `created_time`, `updated_time` from API
- Fix graph selection to use `graph_uri` consistently
- Add graph operation buttons (CLEAR, COPY, MOVE)

#### 2.3 Objects Pages (`GraphObjects.tsx`, `ObjectDetail.tsx`, `ObjectsLayout.tsx`)
- Migrate from mock data imports to real API calls
- Use Quad format (`QuadRequest`/`QuadResponse`) for create/update
- Add proper vitaltype filtering
- Fix pagination to use API `offset`/`page_size`
- Add search functionality using API `search` parameter
- Support `uri` and `uri_list` query parameters

#### 2.4 KGEntities Pages
- **`KGEntities.tsx`**: Uses `KGType` mock type for entities (wrong) — replace with proper entity type
- **`KGEntityDetail.tsx`**: Uses old JSON-LD format — update to use Quad format with `QuadRequest`
- Add entity type filtering (`entity_type_uri` parameter)
- Add `include_entity_graph` toggle
- Add entity search
- Add frame management sub-section (list/create/delete frames within entity)
- Support reference ID lookup (`id`/`id_list` parameters)

#### 2.5 KGFrames Pages
- **`KGFrames.tsx`**: Fix mock type import, use real API
- **`KGFrameDetail.tsx`**: Uses old JSON-LD format — update to Quad format
- Add slot management sub-section (list/create/update/delete slots)
- Add hierarchical frame navigation (`parent_frame_uri`)
- Add frame query capability

#### 2.6 KGTypes Page
- Already partially working with real API
- Verify Quad format create/update works correctly
- Add search functionality
- Fix batch delete

#### 2.7 Files Pages
- **`Files.tsx`**: Currently 100% mock data — wire to `/api/files` endpoints
- **`FileDetail.tsx`**: Wire to real API
- **`FileUpload.tsx`**: Implement real file upload using `/api/files/{space}/upload` with multipart form
- Add file download functionality
- Support file content streaming

#### 2.8 Triples Page
- Already partially working
- Verify pagination works with API `offset`/`page_size`
- Add subject/predicate/object filter inputs
- Fix triple add/delete to use `ApiService`

#### 2.9 SPARQL Page
- Already partially working for queries
- Add tabs for INSERT, UPDATE, DELETE operations
- Add result format selector
- Add query history (local storage)
- Improve results table rendering for large result sets

#### 2.10 Data Pages (Import/Export/Migration/Tracking/Checkpoint)
- **5 detail pages + 1 hub page** — all use mock data
- Wire to `/api/data/import` and `/api/data/export` endpoints
- Implement job creation forms
- Add job execution and status polling
- Add file upload for import data
- Migration, Tracking, and Checkpoint pages may need new backend endpoints or removal if not supported

---

### Phase 3: New Pages (MEDIUM PRIORITY)

#### 3.1 Entity Registry Section

Create a new top-level navigation section "Entity Registry" (`/registry/*`).

##### 3.1.1 Entity List Page (`pages/EntityRegistry.tsx`)
- **Route**: `/registry/entities`
- **API**: `GET /api/registry/entities` — paginated list with filters
- **Features**:
  - Search bar: `query` param (ILIKE on name/aliases)
  - Filters: `type_key` dropdown, `country`, `region`, `status` (active/inactive/merged)
  - Pagination: `page`/`page_size` params (API returns `total_count`)
  - Table columns: primary_name, type_label, country/region, status, created_time
  - Row click → Entity Detail
  - "Create Entity" button → Entity Detail in create mode

##### 3.1.2 Entity Detail Page (`pages/EntityRegistryDetail.tsx`)
- **Route**: `/registry/entity/:entityId`
- **API**: `GET /api/registry/entities/get?entity_id=...`
- **Tabbed layout** with sub-sections:

**Tab 1: Basic Info**
- View/edit: primary_name, description, type_key (dropdown from `GET /api/registry/entity/types`), country, region, locality, website, latitude, longitude, metadata (JSON editor), verified checkbox, notes
- Create: `POST /api/registry/entities` with `EntityCreateRequest` (supports inline aliases, identifiers, locations)
- Update: `PUT /api/registry/entities/update?entity_id=...` with `EntityUpdateRequest`
- Delete: `DELETE /api/registry/entities/delete?entity_id=...`

**Tab 2: Aliases**
- List: `GET /api/registry/aliases/list?entity_id=...` → table (alias_name, alias_type, is_primary)
- Add: `POST /api/registry/aliases/add?entity_id=...` with `AliasCreateRequest` (alias_name, alias_type, is_primary)
- Remove: `DELETE /api/registry/aliases/remove?alias_id=...`

**Tab 3: Identifiers**
- List: `GET /api/registry/identifiers/list?entity_id=...` → table (namespace, value, is_primary)
- Add: `POST /api/registry/identifiers/add?entity_id=...` with `IdentifierCreateRequest` (identifier_namespace, identifier_value, is_primary)
- Remove: `DELETE /api/registry/identifiers/remove?identifier_id=...`
- Lookup: `GET /api/registry/identifiers/lookup?namespace=...&value=...` → navigate to matched entity

**Tab 4: Categories**
- List: `GET /api/registry/categories/entity?entity_id=...` → badge list
- Assign: `POST /api/registry/categories/assign?entity_id=...` with `EntityCategoryRequest` (category_key dropdown from `GET /api/registry/categories`)
- Remove: `DELETE /api/registry/categories/remove?entity_id=...&category_key=...`

**Tab 5: Locations**
- List: `GET /api/registry/locations/list?entity_id=...&include_expired=false` → table with map pins
- Add: `POST /api/registry/locations/add?entity_id=...` with `LocationCreateRequest` (location_type_key, location_name, address fields, lat/lng, is_primary, external_location_id, effective_from/to)
- Update: `PUT /api/registry/locations/update?location_id=...` with `LocationUpdateRequest`
- Remove: `DELETE /api/registry/locations/remove?location_id=...`
- Location categories: assign/remove via `/api/registry/locations/categories/*`
- Location type dropdown from `GET /api/registry/location/types`

**Tab 6: Relationships**
- List: `GET /api/registry/relationships/list?entity_id=...&direction=both&include_expired=false` → table (source, destination, type_label, description, dates)
- Create: `POST /api/registry/relationships` with `RelationshipCreateRequest` (entity_source, entity_destination, relationship_type_key dropdown from `GET /api/registry/relationship/types`, start/end datetime, description)
- Update: `PUT /api/registry/relationships/update?relationship_id=...` with `RelationshipUpdateRequest`
- Remove: `DELETE /api/registry/relationships/remove?relationship_id=...`
- Direction toggle: outgoing / incoming / both

**Tab 7: Same-As**
- List: `GET /api/registry/sameas/list?entity_id=...` → table (source ↔ target, type, confidence, status)
- Create: `POST /api/registry/sameas` with `SameAsCreateRequest` (source_entity_id, target_entity_id, relationship_type, confidence, reason)
- Retract: `PUT /api/registry/sameas/retract?same_as_id=...` with `SameAsRetractRequest` (retracted_by, reason)
- Resolve: `GET /api/registry/sameas/resolve?entity_id=...` → shows canonical entity

**Tab 8: Change Log**
- `GET /api/registry/changelog/entity?entity_id=...&limit=50&offset=0` → paginated list (change_type, details, changed_by, timestamp)
- Filter by `change_type`

##### 3.1.3 Entity Search Page (`pages/EntityRegistrySearch.tsx`)
- **Route**: `/registry/search`
- **API**: `GET /api/registry/search/entity`
- **Features**:
  - Semantic query input: `q` param (vectorized via Weaviate)
  - Identifier lookup: `identifier_value` + optional `identifier_namespace`
  - Geo radius: latitude, longitude, radius_km (map click to set center)
  - Filters: `type_key`, `category_key`, `country`, `region`, `locality`
  - Tuning: `limit`, `min_certainty`
  - Results: cards showing entity_id, primary_name, certainty score, distance_km (if geo)

##### 3.1.4 Location Search Page (`pages/LocationSearch.tsx`)
- **Route**: `/registry/locations`
- **API**: `GET /api/registry/search/location`
- **Features**:
  - External ID lookup: `external_location_id`
  - Geo search: latitude, longitude, radius_km
  - Semantic: `q` (location name/description)
  - Address BM25: `address` keyword search
  - Filters: `location_type_key`, `country_code`, `locality`, `admin_area_1`, `postal_code`, `location_name`, `entity_id`, `is_primary`
  - Results: list with map pins, distance_km, entity cross-reference link

##### 3.1.5 Similar Entity Finder (`pages/SimilarEntities.tsx`)
- **Route**: `/registry/similar`
- **API**: `GET /api/registry/search/similar`
- **Params**: `name` (required), `type_key`, `country`, `region`, `locality`, `limit`, `min_score`
- **Results**: candidate entities with similarity score — link to merge/same-as workflow

##### 3.1.6 Registry Admin Pages
- **Entity Types** (`pages/EntityTypesAdmin.tsx`, route `/registry/admin/entity-types`):
  - List: `GET /api/registry/entity/types` → table (type_key, type_label, type_description)
  - Create: `POST /api/registry/entity/types` with `EntityTypeCreateRequest`
- **Location Types** (`pages/LocationTypesAdmin.tsx`, route `/registry/admin/location-types`):
  - List: `GET /api/registry/location/types`
  - Create: `POST /api/registry/location/types` with `LocationTypeCreateRequest`
- **Relationship Types** (`pages/RelationshipTypesAdmin.tsx`, route `/registry/admin/relationship-types`):
  - List: `GET /api/registry/relationship/types`
  - Create: `POST /api/registry/relationship/types` with `RelationshipTypeCreateRequest` (includes `inverse_key`)
- **Categories** (`pages/CategoriesAdmin.tsx`, route `/registry/admin/categories`):
  - List: `GET /api/registry/categories`
  - Create: `POST /api/registry/categories` with `CategoryCreateRequest`
  - Browse entities by category: `GET /api/registry/categories/entities?category_key=...`
- **Recent Changes** (widget or page, route `/registry/admin/changelog`):
  - `GET /api/registry/changelog?limit=50&change_type=...` → recent activity feed
- **Index Rebuild** (button on admin page):
  - `POST /api/registry/admin/rebuild?rebuild_dedup=true&rebuild_weaviate=false&notify_workers=true`
  - Shows results: entities_indexed, duration, workers_notified
  - Weaviate rebuild option: entities_upserted/deleted, locations_upserted/deleted

---

#### 3.2 Agent Registry Section

Create a new top-level navigation section "Agents" (`/agents/*`).

##### 3.2.1 Agent List Page (`pages/Agents.tsx`)
- **Route**: `/agents`
- **API**: `GET /api/agents/agent` — paginated list with filters
- **Query params**: `query` (ILIKE on name/uri/description), `type_key`, `entity_id`, `capability`, `protocol_format_uri`, `status` (default: active), `page`, `page_size`
- **Response**: `AgentListResponse` with `agents[]`, `total_count`, `page_size`, `offset`
- **Table columns**: agent_name, agent_type_label, agent_uri, status (badge: active/inactive/deprecated), version, capabilities (tag list), endpoint count
- **Features**:
  - Search bar with debounce
  - Filter dropdowns: type (from `GET /api/agents/agent/types`), status, capability
  - "Create Agent" button → Agent Detail in create mode

##### 3.2.2 Agent Detail Page (`pages/AgentDetail.tsx`)
- **Route**: `/agents/:agentId`
- **API**: `GET /api/agents/agent?agent_id=...`

**Section 1: Basic Info**
- View/edit: agent_name, agent_uri, agent_type_key (dropdown from `GET /api/agents/agent/types`), entity_id (optional, entity registry link), description, version, status, notes
- Protocol config: protocol_format_uri, auth_service_uri, auth_service_config (JSON editor)
- Capabilities: tag input (array of strings)
- Metadata: JSON editor
- Create: `POST /api/agents/agent` with `AgentCreate`
- Update: `PUT /api/agents/agent?agent_id=...` with `AgentUpdate`
- Delete: `DELETE /api/agents/agent?agent_id=...` (with confirmation modal)

**Section 2: Status Management**
- Current status badge (active/inactive/deprecated)
- Quick toggle: `PUT /api/agents/agent/status?agent_id=...` with `AgentStatusChange` (status field)
- Color-coded: green=active, yellow=inactive, red=deprecated

**Section 3: Endpoints**
- List: `GET /api/agents/agent/endpoints?agent_id=...` → table (endpoint_uri, endpoint_url, protocol, status)
- Create: `POST /api/agents/agent/endpoints?agent_id=...` with `AgentEndpointCreate` (endpoint_uri, endpoint_url, protocol, notes)
- Update: `PUT /api/agents/agent/endpoints?endpoint_id=...` with `AgentEndpointUpdate` (endpoint_url, protocol, status, notes)
- Delete: `DELETE /api/agents/agent/endpoints?endpoint_id=...`
- Inline editing for endpoint URL and status

**Section 4: Change Log**
- `GET /api/agents/agent/changelog?agent_id=...&limit=50` → chronological event list
- Display: timestamp, event description

##### 3.2.3 Agent Types Admin Page (`pages/AgentTypesAdmin.tsx`)
- **Route**: `/agents/types`
- List: `GET /api/agents/agent/types` → table (type_key, type_label, type_description)
- Create: `POST /api/agents/agent/types` with `AgentTypeCreate` (type_key, type_label, type_description)
- Handle 409 conflict for duplicate type_key

---

#### 3.3 KG Relations Page
- **Relations List** — list relations for a graph with filtering by source/destination/type/direction
- **Relation Detail** — view/edit a single relation (source entity, destination entity, type)
- **Relation Query** — criteria-based relation search

#### 3.4 KG Query Page
- **Query Builder** — UI for building `EntityQueryRequest` criteria
- **Frame Query Builder** — UI for building `FrameQueryRequest` criteria
- Results display with Quad format rendering

#### 3.5 Process Monitoring Page
- **Process List** — list recent processes with status filtering
- **Process Detail** — view process details, progress, errors
- **Manual Trigger** — button to trigger maintenance jobs (analyze, vacuum, stats_rebuild)
- **Scheduler Status** — show scheduler state and job configs

#### 3.6 Admin Page

Create a new top-level navigation section "Admin" (`/admin/*`).

##### 3.6.1 Admin Dashboard (`pages/Admin.tsx`)
- **Route**: `/admin`
- Consolidates all administrative functions into one page with sections

##### 3.6.2 Resync Tool
- **API**: `POST /api/admin/resync?space_id=...`
- **UI**:
  - Space selector dropdown (from `GET /api/spaces`)
  - "Resync" button with confirmation dialog
  - Results display: `ResyncResponse` fields — space_id, edge_rows, frame_entity_rows, pred_stats_rows, quad_stats_rows, elapsed_ms
  - Warning text: "Rebuilds auxiliary tables from rdf_quad. Use after bulk loads or manual DB edits."
  - Progress indicator (request may take seconds to minutes depending on data size)

##### 3.6.3 System Health
- **API**: `GET /api/health` (existing)
- Display: backend type, database connectivity, uptime

##### 3.6.4 User Management Link
- Quick link to `/users` for user CRUD (existing page)

##### 3.6.5 Entity Registry Index Rebuild
- `POST /api/registry/admin/rebuild` — dedup + optional Weaviate sync
- (Also accessible from Entity Registry admin section)

---

### Phase 4: UX & Infrastructure Improvements (LOWER PRIORITY)

#### 4.1 Navigation Updates
- Add sidebar entries for: Entity Registry, Agents, KG Relations, Processes, Admin
- Group items logically: Data Management (Spaces, Graphs, Objects, Triples), Knowledge Graph (Entities, Frames, Types, Relations, Queries), Files, SPARQL, Registries (Entity, Agent), System (Processes, Admin, Users)
- Add breadcrumb improvements for deep navigation paths
- Add space/graph context selector to navbar (persistent across pages)

#### 4.2 Quad Format Rendering
- Create a reusable `QuadViewer` component for displaying Quad-format objects
- Create a `QuadEditor` component for editing Quad-format objects
- Support both table and JSON tree views
- Handle VitalSigns type-specific property rendering

#### 4.3 Error Handling
- Unified error display component
- API error response parsing (422 validation errors, 401 auth errors, 500 server errors)
- Retry logic for transient failures
- Connection status indicator

#### 4.4 WebSocket Integration
- `WebSocketManager.tsx` and `WebSocketContext.tsx` exist but appear lightly used
- Wire change notifications to auto-refresh relevant pages
- Show real-time process progress updates
- Add notification toast for background operations

#### 4.5 Remove Mock Data
- Delete `frontend/src/mock/` directory entirely
- Remove all mock data imports from pages
- Ensure all pages use `ApiService` for data access
- Remove `data.ts` (17KB of hardcoded data)

#### 4.6 Authentication Improvements
- Token refresh is implemented but verify edge cases
- Add session timeout warning
- Add role-based UI element visibility (admin vs. user)

---

## 3. File Change Summary

### New Files to Create
- **Types**: `types/spaces.ts`, `types/graphs.ts`, `types/objects.ts`, `types/kgentities.ts`, `types/kgframes.ts`, `types/kgtypes.ts`, `types/files.ts`, `types/kgrelations.ts`, `types/import_export.ts`, `types/entity_registry.ts`, `types/agent_registry.ts`, `types/processes.ts`, `types/admin.ts`
- **Entity Registry** (10 pages): `pages/EntityRegistry.tsx`, `pages/EntityRegistryDetail.tsx`, `pages/EntityRegistrySearch.tsx`, `pages/LocationSearch.tsx`, `pages/SimilarEntities.tsx`, `pages/EntityTypesAdmin.tsx`, `pages/LocationTypesAdmin.tsx`, `pages/RelationshipTypesAdmin.tsx`, `pages/CategoriesAdmin.tsx`, `pages/RegistryChangelog.tsx`
- **Agent Registry** (3 pages): `pages/AgentList.tsx`, `pages/AgentDetail.tsx`, `pages/AgentTypesAdmin.tsx`
- **Admin**: `pages/Admin.tsx`
- **KG**: `pages/KGRelations.tsx`, `pages/KGRelationDetail.tsx`, `pages/KGQuery.tsx`
- **Processes**: `pages/Processes.tsx`, `pages/ProcessDetail.tsx`
- **Components**: `components/QuadViewer.tsx`, `components/QuadEditor.tsx`, `components/JsonEditor.tsx`, `components/TagInput.tsx`

### Files to Significantly Modify
- `services/ApiService.ts` — expand with all endpoint methods
- `App.tsx` — add routes for new pages
- `components/Layout.tsx` — update sidebar navigation
- All 20 pages currently importing from `mock/`
- `KGEntityDetail.tsx`, `KGFrameDetail.tsx` — rewrite for Quad format
- `Files.tsx`, `FileDetail.tsx`, `FileUpload.tsx` — rewrite from mock to real API
- `Data.tsx` and all 5 data detail pages — rewrite from mock to real API
- `SPARQL.tsx` — add insert/update/delete tabs
- `ObjectsLayout.tsx` — fix type system

### Files to Delete
- `mock/data.ts`, `mock/files.ts`, `mock/graphs.ts`, `mock/index.ts`, `mock/kgtypes.ts`, `mock/objects.ts`, `mock/spaces.ts`, `mock/triples.ts`

---

## 4. Implementation Order

1. **Phase 1.1** — Create proper TypeScript types aligned with API response models
2. **Phase 1.2** — Expand `ApiService.ts` with all endpoint methods
3. **Phase 2.1–2.3** — Fix Spaces, Graphs, Objects pages (core navigation)
4. **Phase 2.4–2.6** — Fix KGEntities, KGFrames, KGTypes pages (knowledge graph)
5. **Phase 2.7** — Fix Files pages (file management)
6. **Phase 2.8–2.9** — Fix Triples and SPARQL pages
7. **Phase 2.10** — Fix Data import/export pages
8. **Phase 4.5** — Remove all mock data
9. **Phase 3.1** — Entity Registry section (largest new section)
10. **Phase 3.2** — Agent Registry section
11. **Phase 3.3–3.4** — KG Relations and KG Query pages
12. **Phase 3.5–3.6** — Process monitoring and Admin pages
13. **Phase 4.1–4.4** — Navigation, components, error handling, WebSocket

---

## 5. Key API Patterns the UI Must Follow

### 5.1 Quad Format
All KG object endpoints (Objects, KGEntities, KGFrames, KGTypes, KGRelations) use `QuadRequest`/`QuadResponse` for create/update operations. The UI must serialize VitalSigns graph objects to Quad format for writes and parse Quad format for reads.

```typescript
interface Quad {
  subject: string;
  predicate: string;
  object: string;
  context: string;
}

interface QuadRequest {
  quads: Quad[];
}
```

### 5.2 Space + Graph Context
Most data endpoints require `space_id` and `graph_id` query parameters. The UI should maintain a persistent space/graph selector context.

### 5.3 Pagination
All list endpoints support `page_size` and `offset` parameters. Responses include total count for computing page numbers.

### 5.4 URI-Based Operations
Get/delete operations support both `uri` (single) and `uri_list` (comma-separated) query parameters. Reference ID lookup via `id`/`id_list` is also supported for KGEntities.

### 5.5 Operation Modes
Create/update endpoints for KGEntities, KGFrames, KGRelations support `operation_mode` enum: `create`, `update`, `upsert`.

### 5.6 Authentication
All API calls require `Authorization: Bearer <token>` header. The existing `AuthService` + `ApiService` handle this with automatic token refresh on 401.
