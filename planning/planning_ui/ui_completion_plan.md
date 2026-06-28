# VitalGraph Web UI Completion Plan

## 1. Executive Summary

The VitalGraph web UI was built as a proof-of-concept. **Every page is currently
bad** — the content is incomplete, the UX is poor, and nothing is near production
quality. Problems span the entire frontend:

- Many pages use **mock data** instead of live backend APIs
- Pages that do call real APIs still have **broken wire formats** (constructing
  JSON-LD that the backend never expects)
- ~~The API consumption pattern is **inconsistent** — some pages use `ApiService`,
  others use raw `axios`, others use `fetch` directly~~ **RESOLVED** — all pages now use `ApiService`, `axios` removed from dependencies
- There are backend endpoints with **no frontend representation**
- Layout and navigation are **poorly structured** (cramped width, flat sidebar)
- All list and detail pages need **significant UX rework** for content and usability

This plan proposes a systematic overhaul to:
1. **Clean the slate** — remove dead code, incorrect JSON-LD, and mock data
2. **Build correct foundations** — `QuadUtils.ts`, shared types, unified `ApiService`
3. **Rebuild every page** with proper content, correct wire format, and good UX
4. **Add missing screens** for backend capabilities that have no UI
5. **Establish maintainable patterns** for future UI development

---

## 2. Current State Audit

### 2.1 Frontend Pages Inventory (46 files)

| Page File | Data Source | API Calls | Quality |
|---|---|---|---|
| `Home.tsx` | Real API | `apiService.getSpaces()`, `apiService.getUsers()`, `apiService.getGraphs()` | 🟡 Rebuilt (dashboard with live stats, spaces overview, quick access nav) |
| `Login.tsx` | Real API | `POST /api/login` | 🟡 Functional, needs polish |
| `Spaces.tsx` | Real API | `apiService.getSpaces()`, `apiService.getGraphs()` | � Rebuilt (card layout with graph/triple stats, client-side search) |
| `SpaceDetail.tsx` | Real API | `apiService` CRUD, `/info`, `/analytics`, `/metrics` | 🟡 Partially rebuilt (tabbed layout with Overview/Analytics/Metrics done via space_analytics plan, axios→ApiService ✅, still needs UX polish) |
| `Users.tsx` | Real API | `apiService.getUsers()` | � Rebuilt (role badges, avatar initials, client-side search, clean responsive table) |
| `UserDetail.tsx` | Real API | `apiService` CRUD `/api/users/...` | � Rebuilt (role dropdown selector, security section, space access display, metadata, profile avatar, delete modal) |
| `Graphs.tsx` | Real API | `apiService.getGraphs()`, `apiService.getSpaces()` | � Rebuilt (card layout, direct GraphInfo, no conversion layer, graph URI-based routing, delete) |
| `GraphDetail.tsx` | Real API | `apiService` CRUD | � Rebuilt (URI-based lookup, stats cards, browse content links, create/purge/delete, no conversion layer) |
| ~~`GraphAnalysis.tsx`~~ | ~~**MOCK**~~ | ~~Hardcoded mock data~~ | ✅ **DELETED** (superseded by SpaceDetail Analytics tab) |
| `SPARQL.tsx` | Real API | `apiService.executeSparqlQuery()`, `apiService.executeSparqlUpdate()` | � Rebuilt (Query/Update mode toggle, SELECT/ASK/CONSTRUCT/INSERT/DELETE, sample templates, pagination toggle) |
| `Triples.tsx` | Real API | `apiService.getTriples()` | � Cleaned (QuadUtils, full CRUD, breadcrumb, space/graph selectors, search/pagination) |
| `KGTypes.tsx` | Real API | `apiService.getKGTypes()` | � Rebuilt (335 lines, no JSON-LD, shared types, quads delete, client-side search/pagination). Needs UX polish |
| `KGTypeDetail.tsx` | Real API | AbsObjectDetail + `/api/graphs/kgtypes` | � JSON-LD removed (quads format), needs UX polish |
| `ObjectsLayout.tsx` | Real API | `apiService` for spaces/graphs | � Cleaned (shared types, no console.logs). Needs UX polish |
| `GraphObjects.tsx` | Real API | `apiService.getObjects()` | � Cleaned (QuadUtils, search/pagination/delete). Needs UX polish |
| `ObjectDetail.tsx` | Real API | AbsObjectDetail + `/api/graphs/objects` | � JSON-LD removed (quads format), needs UX polish |
| `KGEntities.tsx` | Real API | `apiService.getEntities()` | � Cleaned (QuadUtils, search/pagination/delete/empty states). Needs UX polish |
| `KGEntityDetail.tsx` | Real API | AbsObjectDetail + `/api/graphs/kgentities` | � JSON-LD removed (quads format), needs UX polish |
| `KGFrames.tsx` | Real API | `apiService.getFrames()` | � Cleaned (QuadUtils, search/pagination/delete/empty states). Needs UX polish |
| `KGFrameDetail.tsx` | Real API | AbsObjectDetail + `/api/graphs/kgframes` | � JSON-LD removed (quads format), needs UX polish |
| `Files.tsx` | Real API | `apiService.getFiles()` | � Cleaned (QuadUtils, search/extract file type). Needs UX polish |
| `FileDetail.tsx` | Real API | `apiService.getFile()`, `apiService.downloadFile()`, `apiService.deleteFile()` | ✅ Rebuilt (fetches file quads, parses FileInfo, metadata display, properties table, download, delete with confirmation) |
| `FileUpload.tsx` | Real API | `apiService.makeRequest()` for upload, `apiService.getSpaces()` for names | � Functional (drag-drop, progress, success state, breadcrumb). Needs QuadUtils for graph name extraction |
| ~~`Objects.tsx`~~ | ~~**MOCK**~~ | ~~All mock~~ | ✅ **DELETED** (replaced by ObjectsLayout + GraphObjects) |
| `Data.tsx` | Real API | `ImportExportService` | 🟡 Connected but needs UX rework (tabbed hub: Import + Export tabs, real API polling) |
| `DataImport.tsx` | Real API | `ImportExportService.listImportJobs()` | 🟡 Connected but needs UX rework (real API, polling for status updates) |
| `DataImportDetail.tsx` | Real API | `ImportExportService` create/upload/execute/status/log | 🟡 Connected but needs UX rework (full workflow wired, poor UX) |
| `DataExport.tsx` | Real API | `ImportExportService.listExportJobs()` | 🟡 Connected but needs UX rework (real API, polling, download via presigned URL) |
| `DataExportDetail.tsx` | Real API | `ImportExportService` create/execute/status/download | 🟡 Connected but needs UX rework (full workflow wired, poor UX) |
| ~~`DataMigrationDetail.tsx`~~ | ~~**MOCK**~~ | ~~All mock~~ | ✅ **DELETED** |
| ~~`DataTrackingDetail.tsx`~~ | ~~**MOCK**~~ | ~~All mock~~ | ✅ **DELETED** |
| ~~`DataCheckpointDetail.tsx`~~ | ~~**MOCK**~~ | ~~All mock~~ | ✅ **DELETED** |
| `VectorIndexes.tsx` | Real API | `VectorGeoService` CRUD + reindex | 🟡 Connected but needs UX rework (API wired, poor layout/polish — vector_geo_ui_plan Phases 1–3) |
| `VectorMappings.tsx` | Real API | `VectorGeoService` CRUD + toggle | 🟡 Connected but needs UX rework (API wired, poor layout/polish — vector_geo_ui_plan Phases 1–2) |
| `VectorMappingDetail.tsx` | Real API | `VectorGeoService` mapping + properties CRUD | 🟡 Connected but needs UX rework (functional CRUD, poor UX — vector_geo_ui_plan Phase 2) |
| `VectorSearch.tsx` | Real API | KGQuery API with `vector_criteria` | 🟡 Connected but needs UX rework (functional search, poor results UX — vector_geo_ui_plan Phase 3) |
| `GeoPoints.tsx` | Real API | `VectorGeoService.getGeoPoints()` | 🟡 Connected but needs UX rework (functional map/table, poor UX — vector_geo_ui_plan Phase 4) |
| `AbsObjectDetail.tsx` | Real API | `apiService.get/post/put` for detail pages | � Cleaned (JSON-LD removed from all callers, quads format). Needs UX polish |
| `KGRelations.tsx` | Real API | `apiService.getRelations()` | ✅ Built (browse relations in ObjectsLayout, source→destination display, delete) |
| `KGQueryBuilder.tsx` | Real API | `apiService.kgQuery()` | ✅ Built (builder/JSON tabs, results view with breadcrumbs, linked entity/frame detail with deep navigation) |
| `ApiKeys.tsx` | Real API | `apiService.listApiKeys()`, `createApiKey()`, `revokeApiKey()` | ✅ Built (list, create with expiry, revoke, copy key) |
| `Admin.tsx` | Real API | `apiService` health/cache/resync/processes/scheduler | ✅ Built (health, cache, resync, process list, scheduler, DB info) |
| `AuditLog.tsx` | Real API | `apiService.getAuditLogs()` | ✅ Built (filters, pagination, level badges, TimeAgo, row expand) |
| `EntityRegistry.tsx` | Real API | `apiService` registry CRUD | ✅ Built (list/search, pagination, status badges) — **top-level sidebar item**, rw for users, r for readers |
| `EntityRegistryDetail.tsx` | Real API | `apiService` registry CRUD | ✅ Built (detail/edit entity) — edit gated by rw access |
| `AgentRegistry.tsx` | Real API | `apiService` agents CRUD | ✅ Built (list/search/filter by type, pagination) — **top-level sidebar item**, rw for users, r for readers |
| `AgentRegistryDetail.tsx` | Real API | `apiService` agents CRUD | ✅ Built (detail/edit agent) — edit gated by rw access |
| `PasswordChangeDialog.tsx` | Real API | `apiService.changePassword()` | ✅ Built (modal dialog in Layout, current+new password, auto-logout) |
| `GraphVisualization.tsx` | Real API | `ApiService.getSpaces()`, `useGraphVisualization` hook | ✅ Built (cytoscape graph view with cose-bilkent layout, node/edge rendering, space selector, search, zoom controls) |
| `KGDocuments.tsx` | Real API | `apiService.getDocuments()`, segmentation status polling | ✅ Built (document list with search, segment toggle, segmentation status badges, space/graph selectors, pagination) |
| `KGDocumentDetail.tsx` | Real API | `useObjectDetail` + `apiService`/`vgClient`, segment listing | ✅ Built (document properties via ObjectDetailRenderer, segment list with content preview, segmentation trigger, metadata display) |
| `NotFound.tsx` | Static | None | ✅ Built (404 page with path display, Go Home/Go Back buttons, catch-all route) |
| `ObjectsLayout.tsx` | Real API | `apiService` for spaces/graphs | ⬛ Cleaned (shared types, no console.logs). Needs UX polish |

**Summary**: All backend endpoints now have frontend UI coverage. Remaining work is UX polish on older pages (Vector/Geo, AbsObjectDetail).

### 2.2 Mock Data Summary ✅ RESOLVED

**Mock data fully removed.** The `frontend/src/mock/` directory has been deleted. All pages now use real API calls via `apiService`.

- ~~`spaces.ts`~~ — deleted (pages use `apiService.getSpaces()`)
- ~~`graphs.ts`~~ — deleted (pages use `apiService.getGraphs()`)
- ~~`objects.ts`~~ — deleted (previously)
- ~~`files.ts`~~ — deleted (pages use `apiService.getFiles()`)
- ~~`triples.ts`~~ — deleted (previously)
- ~~`kgtypes.ts`~~ — deleted (previously)
- ~~`data.ts`~~ — deleted (previously, replaced by `ImportExportService.ts`)

### 2.3 Backend Endpoints Inventory

| Backend Endpoint | Prefix | Frontend Page(s) | Status |
|---|---|---|---|
| **Auth** (`/api/login`, `/api/logout`, `/api/refresh`) | `/api` | Login, AuthService | ✅ Fully connected (now returns role + spaces in token) |
| **Health** (`/health`, `/health/cache`) | `/` | None | No UI needed |
| **Spaces** (`/api/spaces`) | `/api` | Spaces, SpaceDetail | ✅ Fully connected |
| **Space Info** (`/api/spaces/{id}/info`) | `/api` | SpaceDetail (Overview tab) | ✅ Connected (space_analytics plan) |
| **Space Analytics** (`/api/spaces/{id}/analytics`) | `/api` | SpaceDetail (Analytics tab) | ✅ Connected (space_analytics plan) |
| **Space Metrics** (`/api/spaces/{id}/metrics`) | `/api` | SpaceDetail (Metrics tab) | ✅ Connected (space_analytics plan) |
| **Users** (`/api/users`) | `/api` | Users, UserDetail | ✅ Fully connected (DB-backed, bcrypt, RBAC — auth modernization complete) |
| **Self-Service Password** (`POST /api/users/me/password`) | `/api` | PasswordChangeDialog (in Layout) | ✅ Connected (profile dropdown → dialog → `apiService.changePassword()`) |
| **API Keys** (`/api/keys`) | `/api` | ApiKeys | ✅ Connected (list, create with expiry, revoke, copy key; sidebar under Administration) |
| **Audit Log** (`GET /api/admin/audit`) | `/api/admin` | AuditLog | ✅ Connected (filters, pagination, level badges, TimeAgo; sidebar under Administration) |
| **SPARQL Query** (`/api/graphs/sparql/{space_id}/query`) | `/api/graphs/sparql` | SPARQL | ✅ Fully connected |
| **SPARQL Update** (`/api/graphs/sparql/{space_id}/update`) | `/api/graphs/sparql` | SPARQL (Update mode) | ✅ Connected (Query/Update mode toggle; sample INSERT/DELETE/Modify templates) |
| **SPARQL Insert** (`/api/graphs/sparql/{space_id}/insert`) | `/api/graphs/sparql` | SPARQL (Update mode) | ✅ Connected (covered by SPARQL Update — INSERT DATA template) |
| **SPARQL Delete** (`/api/graphs/sparql/{space_id}/delete`) | `/api/graphs/sparql` | SPARQL (Update mode) | ✅ Connected (covered by SPARQL Update — DELETE DATA template) |
| **SPARQL Graph** (`/api/graphs/sparql/{space_id}/graphs`, `/graph/...`) | `/api/graphs` | Graphs, GraphDetail | ✅ Fully connected |
| **Triples** (`/api/graphs/triples`) | `/api/graphs` | Triples | ✅ Fully connected |
| **Objects** (`/api/graphs/objects`) | `/api/graphs` | GraphObjects, ObjectDetail | ✅ Fully connected |
| **KG Types** (`/api/graphs/kgtypes`) | `/api/graphs` | KGTypes, KGTypeDetail | ✅ Fully connected |
| **KG Entities** (`/api/graphs/kgentities`) | `/api/graphs` | KGEntities, KGEntityDetail | ✅ Fully connected |
| **KG Frames** (`/api/graphs/kgframes`) | `/api/graphs` | KGFrames, KGFrameDetail | ✅ Fully connected |
| **KG Relations** (`/api/graphs/kgrelations`) | `/api/graphs` | KGRelations | ✅ Connected (browse relations in ObjectsLayout) |
| **KG Queries** (`/api/graphs/kgqueries`) | `/api/graphs` | KGQueryBuilder | ✅ Connected (builder + JSON tabs, results view with breadcrumbs, linked entity/frame detail with deep navigation) |
| **Files** (`/api/files`, `/api/files/upload`, `/api/files/download`) | `/api` | Files (list), FileUpload (partial) | ⚠️ Partial |
| **Data Import** (`/api/import`, `/api/import/{id}/upload`, `/api/import/{id}/execute`, `/api/import/{id}/status`, `/api/import/{id}/log`) | `/api` | Data, DataImport, DataImportDetail | ✅ Fully connected (import_export plan complete — create, upload, execute, poll, log, cancel, delete) |
| **Data Export** (`/api/export`, `/api/export/{id}/execute`, `/api/export/{id}/status`, `/api/export/{id}/download`) | `/api` | Data, DataExport, DataExportDetail | ✅ Fully connected (import_export plan complete — create, execute, poll, download, cancel, delete) |
| **Vector Indexes** (`/api/v1/spaces/{id}/vector-indexes`, `.../{name}`, `.../{name}/reindex`) | `/api/v1` | VectorIndexes | ✅ Fully connected (list, create, delete, reindex — vector_geo_ui_plan complete) |
| **Vector Mappings** (`/api/v1/spaces/{id}/vector-mappings`, `.../{id}`, `.../{id}/properties`) | `/api/v1` | VectorMappings, VectorMappingDetail | ✅ Fully connected (CRUD + property CRUD with drag-and-drop — vector_geo_ui_plan complete) |
| **Geo Config** (`/api/v1/spaces/{id}/geo-config`) | `/api/v1` | (settings) | ✅ Fully connected (VectorGeoService — vector_geo_ui_plan complete) |
| **Geo Points** (`/api/v1/spaces/{id}/geo`) | `/api/v1` | GeoPoints | ✅ Fully connected (list, spatial radius filter, pagination — vector_geo_ui_plan Phase 4 complete) |
| **Vector Search** (via KGQuery `vector_criteria` + `geo_criteria`) | `/api/v1` | VectorSearch | ✅ Fully connected (semantic search, full-text search, combined vector+geo — vector_geo_ui_plan Phase 3 complete) |
| **Entity Registry** (`/api/registry/...`) | `/api/registry` | EntityRegistry, EntityRegistryDetail | ✅ Connected (list/search, detail page; **top-level sidebar item** — rw for users, r for readers) |
| **Agent Registry** (`/api/agents/...`) | `/api/agents` | AgentRegistry, AgentRegistryDetail | ✅ Connected (list/search/filter, detail page; **top-level sidebar item** — rw for users, r for readers) |
| **Process Tracking** (`/api/processes`) | `/api` | Admin (System page) | ✅ Connected (process list, scheduler status, trigger jobs — in Admin.tsx) |
| **Metrics** (`/api/metrics/...`) | `/api` | SpaceDetail (Metrics tab) | ✅ Connected (space_analytics plan) |
| **Admin** (`/api/admin/resync`) | `/api/admin` | Admin (System page) | ✅ Connected (health, cache stats, resync trigger, DB info — Admin.tsx at `/admin`) |
| **KG Documents** (`/api/graphs/kgdocuments`) | `/api/graphs` | KGDocuments, KGDocumentDetail | ✅ Fully connected (list with search/pagination, detail with segments, segmentation trigger) |
| **WebSocket** (`/api/ws`) | `/api` | WebSocketManager (auto-connect) | ✅ Connected (infra only) |

### 2.4 API Consumption Pattern ~~Inconsistency~~ ✅ RESOLVED

~~The frontend uses **three different methods** to call the backend.~~

**Current state (after Phase 2–3 migration):**

1. **`apiService` (ApiService.ts)** — Centralized, handles auth headers and 401 auto-refresh. Uses `fetch`.
   - Used by: **ALL pages** — `Spaces.tsx`, `Graphs.tsx`, `GraphDetail.tsx`, `Triples.tsx`, `SpaceDetail.tsx`, `Users.tsx`, `UserDetail.tsx`, `KGEntities.tsx`, `KGFrames.tsx`, `GraphObjects.tsx`, `Files.tsx`, `FileUpload.tsx`, `KGTypes.tsx`, `ObjectsLayout.tsx`, `SPARQL.tsx`, `AbsObjectDetail.tsx`, `ChangeNotificationContext.tsx`

2. **`fetch` via AuthService** — Direct fetch calls for login/logout/refresh only.
   - Used by: `AuthService.ts`

**`axios` has been fully removed** from the project (uninstalled from `package.json`, interceptors removed from `main.tsx`). **Mock data directory deleted** — `frontend/src/mock/` removed; all pages now use real API calls through the single `ApiService` layer. Mock type imports in `Graphs.tsx`, `GraphDetail.tsx`, `NavigationBreadcrumb.tsx`, `FileUpload.tsx`, `FileDetail.tsx` replaced with local interfaces or `apiService` lookups.

### 2.5 Type System ~~Issues~~ ✅ RESOLVED

~~- `frontend/src/types/api.ts` defines only 4 types~~
~~- Many pages define their own inline interfaces~~
~~- Duplicate type definitions across files~~
~~- No shared types for most backend response models~~

**Current state (after cleanup):**
- ✅ Shared types created: `types/spaces.ts`, `types/graphs.ts`, `types/users.ts`, `types/objects.ts`, `types/files.ts`, `types/triples.ts`, `types/api.ts`, `types/vectorGeo.ts`
- ✅ Barrel file: `types/index.ts` exports all shared types
- ✅ All local `Space`/`Graph` interface definitions removed from pages — replaced with `SpaceInfo`/`GraphInfo` imports
- ✅ Zero `any` types in pages, components, contexts, and hooks (only `ApiService.ts` retains `any` for flexible API returns)
- ✅ Zero `console.log/error/warn` in pages and components (only WebSocket/Auth infrastructure retains logging)
- ⚠️ `ApiService.ts` return types still use `any` — typed returns pending per-page adoption

---

> **Note**: Sections 3–5 below were written when the plan assumed some pages
> were "complete" and just needed wiring fixes. Since **all pages need full
> rebuilds**, the detailed per-page fix instructions below are superseded by
> the Phase plan in Section 7. They are retained as reference for what
> specifically is wrong with each page.

## 3. Screens to Remove

### 3.1 Dead Pages

| Page | Reason | Action |
|---|---|---|
| `Objects.tsx` | Completely replaced by `ObjectsLayout.tsx` + `GraphObjects.tsx`. Uses only mock data. Not routed to in `App.tsx` except via `/objects` which redirects to `/objects/graphobjects`. | **DELETE** |
| `GraphAnalysis.tsx` | Uses hardcoded mock data. **Superseded** by space-level analytics (`SpaceAnalytics.tsx`) implemented in `planning_space_analytics`. | **DELETE** — functionality now lives in SpaceDetail Analytics tab |

### 3.2 Screens to Evaluate for Relevance

| Page | Current State | Recommendation |
|---|---|---|
| `Data.tsx` (hub page) | ✅ Connected to real API (Import + Export tabs). | **DONE** — already rewired via `planning_import_export/` |
| `DataMigrationDetail.tsx` | Mock data. Migration is out of scope (separate plan). | **DELETE** — migration composes export + import, deserves its own plan |
| `DataTrackingDetail.tsx` | Mock data. Tracking integrated into import/export detail pages. | **DELETE** — functionality merged into `DataImportDetail`/`DataExportDetail` |
| `DataCheckpointDetail.tsx` | Mock data. Checkpoint/resume integrated into job manager. | **DELETE** — checkpoint is now per-job, visible in detail page progress |
| Data hub "Migrate" tab | No backend support, out of scope | **REMOVE** tab — migration is a separate plan |
| Data hub "Tracking" tab | Merged into import/export detail | **REMOVE** tab — already integrated |
| Data hub "Checkpoint" tab | Merged into import/export detail | **REMOVE** tab — already integrated |

---

## 4. Screens to Fix (Mock → Real API)

### 4.1 Priority 1 — File Management (Backend Exists, Frontend Mock)

**`FileDetail.tsx`** — Currently uses `mockFiles` and shows alert stubs for save/delete/download.

**Required Changes:**
- Replace `mockFiles` lookup with `axios.get /api/files/uri?space_id=...&uri=...`
- Wire Save button to `axios.put /api/files`
- Wire Delete button to `axios.delete /api/files?space_id=...&uri=...`
- Wire Download button to `axios.get /api/files/download?space_id=...&uri=...`
- Replace `mockSpaces` lookup with `axios.get /api/spaces`
- Pass `space_id` and `graph_id` through route params or query params

**`FileUpload.tsx`** — Partially working (upload calls real API, but space/graph selection uses mock data).

**Required Changes:**
- Replace `mockSpaces` and `mockGraphs` with real API calls
- Use `axios.get /api/spaces` for space list
- Use `apiService.getGraphs(spaceId)` for graph list

### 4.2 Priority 2 — Data Import/Export (Backend Exists, Frontend Mock)

The backend has real `ImportEndpoint` and `ExportEndpoint` classes with full CRUD operations. The frontend pages are entirely mock-driven.

**`Data.tsx`** (hub page):
- Remove migrate/tracking/checkpoint tabs
- Replace `mockDataImports` with `axios.get /api/data/import`
- Replace `mockDataExports` with `axios.get /api/data/export`
- Replace `mockSpaces`/`mockGraphs` with real API calls

**`DataImport.tsx`**:
- Replace `mockDataImports` with `axios.get /api/data/import`
- Replace mock space/graph data with real API calls

**`DataImportDetail.tsx`**:
- Replace `mockDataImports` lookup with `axios.get /api/data/import/{id}`
- Wire create form to `axios.post /api/data/import`
- Wire execute button to `axios.post /api/data/import/{id}/execute`
- Wire file upload to `axios.post /api/data/import/{id}/upload`

**`DataExport.tsx`**:
- Replace `mockDataExports` with `axios.get /api/data/export`
- Replace mock space/graph data with real API calls

**`DataExportDetail.tsx`**:
- Replace `mockDataExports` lookup with `axios.get /api/data/export/{id}`
- Wire create form to `axios.post /api/data/export`
- Wire execute button to `axios.post /api/data/export/{id}/execute`
- Wire download button to `axios.get /api/data/export/{id}/download`

---

## 5. Missing Screens to Add

### 5.1 Priority 1 — Admin Dashboard & Audit Log ✅ BUILT

#### Admin Dashboard — ✅ BUILT

**Backend**: `AdminEndpoint` (`/api/admin/resync`), `ProcessEndpoint` (`/api/processes`, `/api/processes/detail`, `/api/processes/trigger`, `/api/processes/scheduler`)

**Page**: `Admin.tsx` (363 LOC) — System health, scheduler card, entity cache stats, resync modal, trigger maintenance modal, process tracking table, DB info.

**Route**: `/admin` (under Administration section in sidebar, admin-only)

#### Audit Log Viewer — ✅ BUILT

**Backend**: `audit_log` PostgreSQL table + `GET /api/admin/audit` REST endpoint (query with filters + pagination).

**Page**: `AuditLog.tsx` (195 LOC) — Paginated audit log with filters (event, actor, level, time range), level badges, TimeAgo timestamps, expandable row details.

**Route**: `/audit-log` (under Administration section in sidebar, admin-only)

---

### 5.2 Priority 2 — Entity Registry ✅ BUILT

**Backend**: `EntityRegistryEndpoint` (`/api/registry/...`) — comprehensive CRUD for entities, aliases, identifiers, same-as mappings, entity types, categories, locations, relationships, change logs, search.

**Pages**: `EntityRegistry.tsx`, `EntityRegistryDetail.tsx` — list/search, detail/edit.

**Navigation & Access**:
- ✅ **Top-level sidebar item** (not nested under Administration) with `HiCollection` icon
- **Access**: `user` and `admin` roles have **read-write** access; `reader` role has **read-only** access
- Edit/create/delete actions gated by role (readers see data but cannot modify)

### 5.3 Priority 3 — Agent Registry ✅ BUILT

**Backend**: `AgentRegistryEndpoint` (`/api/agents/...`) — CRUD for agents, agent types, agent endpoints, agent functions.

**Pages**: `AgentRegistry.tsx`, `AgentRegistryDetail.tsx` — list/search/filter, detail/edit.

**Navigation & Access**:
- ✅ **Top-level sidebar item** (not nested under Administration) with `HiUserGroup` icon
- **Access**: `user` and `admin` roles have **read-write** access; `reader` role has **read-only** access
- Edit/create/delete actions gated by role (readers see data but cannot modify)

### 5.4 Priority 4 — KG Relations Browser ✅ BUILT

**Backend**: `KGRelationsEndpoint` (`/api/graphs/kgrelations`) — CRUD for entity-to-entity relationships.

**Page**: `KGRelations.tsx` (12.7KB) — Browse relations in ObjectsLayout, source→destination entity display, delete. Sidebar entry under Knowledge Graph section.

### 5.5 Priority 5 — KG Query Builder

**Backend**: `KGQueriesEndpoint` (`/api/graphs/kgqueries`) — Entity-to-entity connection queries with frame traversal.

**New Page**: `KGQueryBuilder.tsx` — Visual query builder for exploring entity connections through frames and slots.

**Status**: ✅ Complete (builder + JSON tabs, results view with breadcrumbs, linked entity/frame detail with deep navigation).

**Architecture — Three-View Navigation with Breadcrumbs** (implemented):

The page uses an internal `view` state (`'builder' | 'results' | 'detail'`) to navigate between three views without route changes (preserving query state):

1. **Builder View** — Space/graph selectors, Builder/JSON tabs (criteria pickers + read-only request JSON), Execute button
2. **Results View** — Tabular results with breadcrumb `KG Query Builder > Results`; "Back to Query" button; "Re-run" button; all entity/frame URIs are clickable `UriLink` components
3. **Entity Detail View** — Inline detail for a selected entity/frame, with breadcrumb `KG Query Builder > Results > Entity A > Entity B > ...`

**Implemented — Linked Results** ✅:

- All entity/frame URIs in results tables are rendered as clickable `UriLink` buttons (blue, monospace, with external-link icon)
- For `entity` results: each entity URI navigates to detail view
- For `relation` results: source and destination entity URIs are clickable
- For `frame_query` results: frame URI links to frame detail; entity refs link to entity detail
- For `frame` (legacy) results: source/destination entity URIs and shared frame URI are all clickable

**Implemented — Breadcrumb Navigation** ✅:

```
KG Query Builder  →  Results  →  Entity A  →  Entity B  → ...
     (builder)        (table)      (detail)     (deep nav)
```

- Clicking "KG Query Builder" in breadcrumb returns to builder view (query state preserved)
- Clicking "Results" in breadcrumb returns to results view (results state preserved)
- Clicking any intermediate entity in breadcrumb trims the stack and re-fetches that entity
- All navigation is in-component (no route change) so the query and results are never lost

**Implemented — Entity Detail in Context** ✅:

- Entity detail shows: name, type badge, all properties (from quads), outgoing relations
- Properties table: URI-valued properties render as clickable links → deep navigation
- Relations table: shows relation type + destination entity as clickable link
- `detailStack` array tracks full navigation history for breadcrumb rendering
- `navigateToDetail(uri, kind)` fetches entity/frame quads + relations via `apiService.getEntity()` / `apiService.getFrame()` / `apiService.getRelations()`
- `navigateBack(toIndex)` handles breadcrumb clicks (trims stack, re-fetches target)
- Raw quads collapsible at bottom of detail view

### 5.6 Priority 6 — User Management with RBAC ✅ BUILT

**Backend**: Auth modernization complete (`planning_auth/`). Full user CRUD with roles (`admin`/`user`/`reader`), per-space access control (`rw`/`r`), password hashing (bcrypt), token versioning.

**Pages**: `Users.tsx` (role badges, avatar initials, create user form with role selector), `UserDetail.tsx` (profile + role dropdown, security section, SpaceAccessCard, UserApiKeysCard, delete modal).

**Components**: `PasswordChangeDialog.tsx` (self-service password change), role-aware `AuthContext` (exposes `role` and `spaces` from JWT).

### 5.7 Priority 7 — API Key Management ✅ BUILT

**Backend**: API key support complete (`planning_auth/api_key_support_plan.md`). Self-service CRUD at `/api/keys`, admin can manage any user's keys, `vg_` prefixed keys with bcrypt hashing.

**Page**: `ApiKeys.tsx` — Standalone page at `/api-keys`. Create key (name + optional expiry), key revealed once with copy button, revoke with confirmation. Accessible from user profile dropdown and sidebar (admin).

### 5.8 Priority 8 — Vector & Geo Management (✅ COMPLETE)

**Backend**: Vector/Geo plan fully implemented (`planning_vector_geo/`). All REST endpoints available. All 4 UI phases complete (see `planning_vector_geo/vector_geo_ui_plan.md`).

**Completed Pages**:
- `VectorIndexes.tsx` — List, create, delete vector indexes; trigger re-index with status feedback
- `VectorMappings.tsx` — List, create, delete mappings; inline enabled toggle; filter by class/enabled
- `VectorMappingDetail.tsx` — Detail page with settings edit, property CRUD via drag-and-drop (`@dnd-kit/sortable`)
- `VectorSearch.tsx` — Semantic search (vector similarity via KGQuery) + full-text search mode toggle; index select, top-K, min-score slider, results with score bars
- `GeoPoints.tsx` — Combined table + map view; OpenStreetMap via `react-leaflet`; Google Maps via `@vis.gl/react-google-maps` (when API key set); radius search with circle overlay; pagination

**Completed Components**:
- `VectorGeoService.ts` — Typed API methods for all vector/geo endpoints
- `types/vectorGeo.ts` — TypeScript types for indexes, mappings, properties, geo points
- `MapView.tsx` / `OSMMap.tsx` / `GoogleMap.tsx` — Map provider abstraction with env-driven provider selection
- `EntityGeoMiniMap` — Inline mini-map on KGEntity detail page
- `PropertyListEditor` / `SortablePropertyRow` — Drag-and-drop property ordering
- `EnabledToggle` — Inline toggle switch (shared component)

**Sidebar entries**: Vector Indexes, Vector Mappings added under space navigation (admin-gated)

### 5.9 Priority 9 — SPARQL Update/Insert/Delete ✅ BUILT

**Page**: `SPARQL.tsx` — Query/Update mode toggle with sample INSERT DATA, DELETE DATA, and Modify templates. Calls `apiService.executeSparqlUpdate()` for update operations. Success/failure display with affected triples count.

---

## 6. Architecture Improvements

### 6.1 Standardize API Layer — ✅ COMPLETE

**Goal**: All frontend API calls go through a single, unified service.

**Status**: ✅ **DONE**
1. ✅ Enhanced `ApiService.ts` to be the sole API layer
2. ✅ Added typed methods for all current endpoints (Spaces, Users, Graphs, Objects, Entities, Frames, KGTypes, Files, SPARQL)
3. ✅ Removed all direct `axios` imports from page components
4. ✅ Only `AuthService.ts` uses direct `fetch` (for login/logout/refresh — intentional)
5. ✅ `axios` removed from `package.json` dependencies

**Completed migration** (Phase 2→3):
- Phase 2.2: Added typed methods to `ApiService.ts`
- Phase 2.3→3a: Migrated all pages from `axios` → `apiService`
- Phase 3a: Removed `axios` dependency from `package.json`

### 6.2 Centralize TypeScript Types — ✅ MOSTLY COMPLETE

**Goal**: Single source of truth for all API types.

**Status**:
1. ✅ Shared type files created:
   - `types/spaces.ts` — Space, SpaceListResponse
   - `types/users.ts` — User, UserRole, CreateUserRequest, UpdateUserRequest
   - `types/graphs.ts` — Graph, GraphInfo, GraphOperationResponse
   - `types/objects.ts` — GraphObject, KGEntity, KGFrame, KGType, KGTypeProperty, RDFProperty, ObjectListResponse, EntityListResponse, FrameListResponse
   - `types/files.ts` — FileEntry, FileListResponse, FileUploadResponse
   - `types/triples.ts` — Triple, TripleListResponse
   - `types/api.ts` — SpaceInfo, SparqlQueryResponse
   - `types/vectorGeo.ts` — VectorIndex, VectorMapping, MappingProperty, GeoPoint
   - `types/index.ts` — barrel file
2. ✅ All local `Space`/`Graph` interfaces eliminated from pages — all use `SpaceInfo`/`GraphInfo`
3. ✅ Zero `any` in pages/components/contexts/hooks
4. ✅ `types/quad.ts` — re-exports Quad, QuadRequest, QuadResponse, ParsedProperty, GroupedEntity from QuadUtils
5. ✅ `types/data.ts` — re-exports ImportExportJob, JobStatusResponse, LogEntry, etc. from ImportExportService

### 6.3 Remove Mock Data Layer — ✅ COMPLETE

**Goal**: Eliminate `frontend/src/mock/` directory entirely.

**Status**: ✅ **DONE**
1. ✅ `frontend/src/mock/` directory fully deleted
2. ✅ All mock imports removed from all pages
3. ✅ All pages use real `apiService` calls
4. ✅ Zero mock data anywhere in the codebase

### 6.4 Improve Error Handling Pattern — 🟡 INFRASTRUCTURE DONE, ADOPTION PENDING

**Infrastructure** — ✅ **DONE**:
1. ✅ `useApiError` hook created (`frontend/src/hooks/useApiError.ts`) — extracts error messages from Error, AxiosError, and string shapes
2. ✅ `ErrorDisplay` component created (`frontend/src/components/shared/ErrorDisplay.tsx`) — consistent error UI with retry/dismiss actions
3. ✅ Adopted in Spaces.tsx and Graphs.tsx (pattern established for remaining pages)

### 6.5 Navigation & Layout Improvements

**Current Issues**:
- Sidebar has 10 top-level items — too many for effective navigation
- No grouping or hierarchy in sidebar
- Navigation breadcrumbs are inconsistent across pages
- Some pages (`Data`) have sub-tabs, others use hierarchical routing
- `Layout.tsx` navbar duplicates sidebar links

**Status**: ✅ **DONE** (sidebar reorganized, navbar simplified)

**Actual sidebar structure** (7 groups):
1. **Core**: Home, Spaces, Graphs
2. **Visualization**: Graph Visualization (`cytoscape` interactive viewer)
3. **Knowledge Graph**: KG Entities, KG Frames, KG Relations, KG Documents, KG Types, KG Query Builder, Files
4. **RDF**: Graph Objects, Triples, SPARQL
5. **Registries** (top-level): Entity Registry, Agent Registry — rw for users, r for readers
6. **Data**: Data Management (import/export hub)
7. **Vector & Geo** (collapsible): Indexes, Mappings, Search, Geo Points
8. **Administration** (collapsible, admin-only): Users, API Keys, Audit Log, System

**Navbar**: Logo/brand, command palette trigger (⌘K), dark mode toggle, user avatar dropdown only.
**Breadcrumbs**: `NavigationBreadcrumb` component used on most pages, not yet 100% standardized.

---

## 7. Implementation Phases

All pages need serious rework. Phases are ordered to **clean the slate first**,
then build correct foundations, then rebuild pages one group at a time.

### Phase 1: Cleanup & Removal (Estimated: 2-3 days)

Get to a clean starting point by removing all incorrect/dead code:

**1.1 Delete dead code:**
- Delete `Objects.tsx` (dead page, replaced by `ObjectsLayout`)
- Delete `GraphAnalysis.tsx` (superseded by `SpaceAnalytics.tsx` from space_analytics plan)
- Remove their routes from `App.tsx`

**1.2 Remove all JSON-LD traces:** ✅ **DONE**

JSON-LD is not used in this project. The backend wire format is JSON Quads.

~~Files to clean:~~
- ✅ `KGEntityDetail.tsx` — `buildApiRequestData` now returns `{quads: [...]}`
- ✅ `KGFrameDetail.tsx` — same
- ✅ `ObjectDetail.tsx` — same
- ✅ `KGTypeDetail.tsx` — same (context prefixes removed)
- ✅ `KGTypes.tsx` — removed `@id`/`@type` interface fields, removed `@graph` parsing
- ✅ `ApiService.ts` — comments updated to reference "quads array"
- ✅ `FileUpload.tsx` — removed `.jsonld` from accepted formats and description text
- ✅ `VectorSearch.tsx` — removed `@id` fallback in result parsing

Zero JSON-LD references remain in the codebase (`grep` confirms no `@context`/`@graph`/`@id`/`@type` in any `.ts`/`.tsx` file).

**1.3 Remove mock data directory:**
- Delete `frontend/src/mock/` directory entirely
- Remove all `import ... from '../mock/...'` statements from pages
- Pages that only use mock data will be broken (acceptable — they'll be
  rebuilt in later phases)

**1.4 Layout width fix:**

```diff
- <main className="flex-1 p-4">
-   <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-800 sm:p-6 lg:p-8">
-     <Outlet />
-   </div>
- </main>
+ <main className="flex-1 p-4">
+   <Outlet />
+ </main>
```

**1.5 Remove axios:** ✅ **DONE** (completed in Phase 3a migration)
- ✅ Removed all direct `axios` imports from page components
- ✅ Removed axios interceptor setup from `main.tsx`
- ✅ Removed `axios` from `package.json` dependencies
- All pages now use `ApiService` with `fetch`-based auth handling

After Phase 1, the codebase is clean but many pages are non-functional.
That's fine — they were all bad anyway and need full rewrites.

### Phase 2: Foundation (✅ PARTIALLY COMPLETE)

Build the correct infrastructure that all rebuilt pages will use:

**2.1 Quad utilities** — ✅ **DONE**. Created `frontend/src/utils/QuadUtils.ts`:
- ✅ Types: `Quad`, `QuadRequest`, `QuadResponse`, `ParsedProperty`, `GroupedEntity`
- ✅ Constants: `RDF_TYPE`, `HAS_NAME`
- ✅ Term parsing: `stripBrackets`, `stripLiteral`, `isUriTerm`, `parseObjectTerm`, `shortenUri`
- ✅ Quad building: `wrapUri`, `wrapLiteral`, `buildQuad`, `buildQuadsPayload`, `buildDeleteAllPayload`
- ✅ Grouping: `groupQuadsBySubject`, `parseEntitiesFromQuads`, `quadsToProperties`, `getFirstValue`
- ✅ All pages refactored to use QuadUtils (KGEntities, KGFrames, GraphObjects, Triples, Files, AbsObjectDetail, KGTypes)
- ✅ `extractGraphName` consolidated (Graphs, GraphDetail, NavigationBreadcrumb, Triples, KGTypes, Files, FileUpload)
- ✅ `ApiService` quad-returning methods typed with `QuadResponse` (getTriples, getObjects, getEntities, getFrames, etc.)

**2.1b Format utilities** — ✅ **DONE**. Created `frontend/src/utils/formatUtils.ts`:
- ✅ `formatFileSize` — replaces 6 local copies (FileUpload, FileDetail, DataImport, DataImportDetail, DataExport, DataExportDetail)
- ✅ `formatDateTime` — replaces local copies (AbsObjectDetail, Data* pages)
- ✅ `formatDateShort` — replaces local copies (Users, VectorIndexes)
- ✅ `formatDateTimeFull` — replaces local copy (UserDetail)
- ✅ `getJobStatusColor` — replaces 4 local copies (DataImport, DataImportDetail, DataExport, DataExportDetail)

**2.1c Code-splitting & bundle optimization** — ✅ **DONE**:
- ✅ All 30 pages lazy-loaded via `React.lazy()` in `App.tsx`
- ✅ `SpaceAnalytics` and `SpaceMetrics` lazy-loaded within `SpaceDetail.tsx` (chart libs deferred)
- ✅ Vendor bundle split: `vendor-react` (48KB), `vendor-flowbite` (203KB), remaining (243KB)
- ✅ SpaceDetail chunk reduced from 619KB → 13KB (charts load on-demand)
- ✅ `PageLoader` spinner shown during chunk loading
- ✅ No chunk size warnings in production build

**2.2 Shared TypeScript types** — ✅ **DONE**. Expand `frontend/src/types/`:
- ✅ `types/spaces.ts` — Space, SpaceListResponse
- ✅ `types/users.ts` — User, UserRole, CreateUserRequest, UpdateUserRequest
- ✅ `types/graphs.ts` — Graph, GraphInfo, GraphOperationResponse
- ✅ `types/objects.ts` — GraphObject, KGEntity, KGFrame, KGType, KGTypeProperty, RDFProperty, ObjectListResponse, EntityListResponse, FrameListResponse
- ✅ `types/files.ts` — FileEntry, FileListResponse, FileUploadResponse
- ✅ `types/triples.ts` — Triple, TripleListResponse
- ✅ `types/api.ts` — SpaceInfo, SparqlQueryResponse
- ✅ `types/vectorGeo.ts` — VectorIndex, VectorMapping, MappingProperty, GeoPoint
- ✅ `types/index.ts` — barrel file exporting all types
- ✅ `types/quad.ts` — Quad, QuadRequest, QuadResponse, ParsedProperty, GroupedEntity (re-exports from QuadUtils)
- ✅ `types/data.ts` — ImportExportJob, JobStatusResponse, LogEntry, CreateImportRequest, CreateExportRequest (re-exports from ImportExportService)

**2.3 ApiService expansion** — ✅ **DONE**. Typed methods added for:
- ✅ Spaces CRUD (`getSpaces`, `getSpaceInfo`, `createSpace`, `updateSpace`, `deleteSpace`)
- ✅ Users CRUD (`getUsers`, `getUser`, `createUser`, `updateUser`, `deleteUser`)
- ✅ Graphs CRUD (`getGraphs`, `createGraph`, `deleteGraph`)
- ✅ Objects (`getObjects`)
- ✅ KG Entities (`getEntities`)
- ✅ KG Frames (`getFrames`)
- ✅ KG Types (`getKGTypes`)
- ✅ Files (`getFiles`, `uploadFile`)
- ✅ SPARQL (`executeSparqlQuery`)
- ✅ Low-level: `get`, `post`, `put`, `delete`, `makeRequest` (for arbitrary endpoints)
- ✅ KG Relations (`getRelations`)
- ✅ KG Queries (`kgQuery`)
- ✅ KG Documents (`getDocuments`, segment endpoints)
- ✅ Admin (`health`, `cache`, `resync`, `processes`, `scheduler`)
- ✅ Entity Registry (full CRUD + aliases, identifiers, categories, locations)
- ✅ Agent Registry (full CRUD + endpoints, functions, changelog, status)
- ✅ Audit Log (`getAuditLogs`)
- ✅ API Keys (`listApiKeys`, `createApiKey`, `revokeApiKey`)
- ✅ Password change (`changePassword`)

**2.4 Shared UI components** — ✅ **DONE**:
- ✅ `useApiError` hook (`frontend/src/hooks/useApiError.ts`) — consistent error handling
- ✅ `ErrorDisplay` component (`frontend/src/components/shared/ErrorDisplay.tsx`)
- ✅ `LoadingSkeleton` component (`frontend/src/components/shared/LoadingSkeleton.tsx`)
- ✅ `EmptyState` component (`frontend/src/components/shared/EmptyState.tsx`)
- ✅ `PageHeader` component (`frontend/src/components/shared/PageHeader.tsx`)
- ✅ Barrel file: `frontend/src/components/shared/index.ts`

**Backend wire format reference** (for all quad-based endpoints):

Request (create/update): `POST /api/graphs/kgentities`
```json
{"quads": [
  {"s": "<http://example.org/e1>", "p": "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>", "o": "<http://vital.ai/ontology/haley-ai-kg#KGEntity>", "g": "<urn:g1>"},
  {"s": "<http://example.org/e1>", "p": "<http://vital.ai/ontology/vital-core#hasName>", "o": "\"Alice\"", "g": "<urn:g1>"}
]}
```

Response (list/get): `GET /api/graphs/kgentities`
```json
{"success": true, "total_count": 42, "page_size": 10, "offset": 0,
 "results": [
  {"s": "<http://example.org/e1>", "p": "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>", "o": "<http://vital.ai/ontology/haley-ai-kg#KGEntity>", "g": null},
  ...
]}
```

### Phase 3: Core Page Rebuilds (🟡 AXIOS MIGRATION COMPLETE, UX REBUILDS PENDING)

**Phase 3a: axios→ApiService migration** — ✅ **COMPLETE**

All pages migrated from `axios` to `apiService`. `axios` removed from `package.json`.
Files migrated:
- ✅ `Users.tsx`, `UserDetail.tsx`
- ✅ `SPARQL.tsx`, `SpaceDetail.tsx`
- ✅ `KGEntities.tsx`, `KGFrames.tsx`, `GraphObjects.tsx`
- ✅ `KGTypes.tsx`, `ObjectsLayout.tsx`
- ✅ `Files.tsx`, `FileUpload.tsx`
- ✅ `AbsObjectDetail.tsx`
- ✅ `ChangeNotificationContext.tsx`
- ✅ `main.tsx` — removed axios interceptors (51 lines → 10 lines)

**Phase 3b: Core page UX rebuilds** — ✅ **COMPLETE**

All core pages rebuilt with proper UX, real API integration, Flowbite components, dark mode:

1. ✅ **Login** (127 LOC) — Centered card, logo (light/dark), `FormField` + `useFormValidation`, disabled states, error alert
2. ✅ **Home** — Dashboard with space count, recent processes, system stats
3. ✅ **Spaces** (196 LOC) — Card grid with graph/triple counts, search filter, `useApiError`/`ErrorDisplay`
4. ✅ **SpaceDetail** (564 LOC) — Tabbed (Overview/Settings/Analytics/Metrics), breadcrumbs, edit/delete, lazy-loaded analytics
5. ✅ **Graphs** (265 LOC) — Space-scoped table, create/delete, search, `useApiError`/`ErrorDisplay`
6. ✅ **GraphDetail** — Graph info, stats, delete with ConfirmDialog
7. ✅ **Triples** — Searchable list with filtering, add/delete
8. ✅ **GraphObjects** — Browsable list with type filtering, search, pagination
9. ✅ **ObjectDetail** — Property viewer using QuadUtils, expandable text
10. ✅ **Files** — File list with upload, download, delete
11. ✅ **FileDetail** — File metadata display, download button, delete with confirmation
12. ✅ **SPARQL** — Query editor with results table, update/insert/delete support
13. ✅ **DataImport** (251 LOC) — Job table, polling, status badges, progress bars
14. ✅ **DataImportDetail** (436 LOC) — Create workflow, file upload, format selector, log viewer
15. ✅ **DataExport** (266 LOC) — Job table, polling, download action
16. ✅ **DataExportDetail** (403 LOC) — Create workflow, presigned URL download, log viewer
17. ✅ **VectorIndexes** (395 LOC) — Space selector, table, create/delete/re-index, breadcrumbs
18. ✅ **VectorMappings** (442 LOC) — Filter by class/enabled, inline toggle, create/delete
19. ✅ **VectorMappingDetail** (475 LOC) — Settings editor, property CRUD
20. ✅ **VectorSearch** (406 LOC) — Vector/full-text modes, top-K/min-score sliders, score bars
21. ✅ **GeoPoints** (431 LOC) — Table + map toggle, OpenStreetMap + Google Maps fallback, radius search

### Phase 4: KG Pages Rebuild (🟡 PARTIALLY COMPLETE)

Purpose-built KG UIs that reflect the actual data model.

**Key design principle**: The KG Entity and KG Frame list tables must make
**extensive use of server-side sort and filter** on the set of properties
tied to each object type. The backend supports `EntityPropertyFilter` and
`SortCriteria` on property URIs — the frontend should expose these as
sortable/filterable table columns (e.g., name, type, description, dates,
custom properties). This enables fast, paginated tables without client-side
data manipulation. The same pattern applies to KG Frame tables (filter by
frame type, slot values, parent entity, etc.).

1. **KGEntity list** — ⬛ Built (`KGEntities.tsx`, 15KB). Search, pagination, delete, entity type filter. Needs UX polish (server-side sort/filter on property columns).
2. **KGEntity detail** — ⬛ Built (`KGEntityDetail.tsx`). Properties via `ObjectDetailRenderer`, entity graph viewer inline below properties. Needs UX polish.
3. **KGFrame list** — ⬛ Built (`KGFrames.tsx`, 14KB). Search, pagination, delete. Needs UX polish (server-side sort/filter).
4. **KGFrame detail** — ⬛ Built (`KGFrameDetail.tsx`). Properties via `ObjectDetailRenderer`. Needs UX polish.
5. **KGTypes** — ⬛ Built (`KGTypes.tsx`, 13KB). Type list with search, pagination, delete. Needs UX polish.
6. **KGRelations** — ✅ Built (`KGRelations.tsx`, 12.7KB). Browse relations in ObjectsLayout, source→destination display, delete.
7. **KGQueryBuilder** — ✅ Built (`KGQueryBuilder.tsx`, 42.7KB). Builder/JSON tabs, results view with breadcrumbs, linked entity/frame detail with deep navigation.
8. **KGDocuments** — ✅ Built (`KGDocuments.tsx`, 14KB + `KGDocumentDetail.tsx`, 20KB). Document list with search, segment toggle, segmentation status; detail with segments, content preview, segmentation trigger.
9. **GraphVisualization** — ✅ Built (`GraphVisualization.tsx`, 13KB). Cytoscape graph view with cose-bilkent layout, node/edge rendering, space selector, search, zoom controls. Uses `useGraphVisualization` hook.

### Phase 5: Navigation & Layout (✅ COMPLETE)

1. ✅ **Grouped sidebar sections** — 8 `SidebarItemGroup` sections:
   - **Core**: Home, Spaces, Graphs
   - **Visualization**: Graph Visualization (cytoscape interactive viewer)
   - **Knowledge Graph**: KG Entities, KG Frames, KG Relations, KG Documents, KG Types, KG Query Builder, Files
   - **RDF**: Graph Objects, Triples, SPARQL
   - **Registries**: Entity Registry, Agent Registry
   - **Data**: Data Management (import/export hub)
   - **Vector & Geo** (collapsible): Indexes, Mappings, Search, Geo Points
   - **Administration** (collapsible, admin-only): Users, API Keys, Audit Log, System
2. ✅ **Role-aware sidebar**: Entire Administration section hidden for non-admin users (`user?.role === 'admin'` gate). Role field exposed via `AuthService` → `AuthContext`.
3. ✅ **Navbar simplified**: Removed duplicate links (Home, Spaces, KG, Data, SPARQL) that repeated the sidebar. Navbar now contains only: logo/brand, command palette trigger, dark mode toggle, user avatar dropdown.
4. ✅ **Role badge**: Shown in user profile dropdown header next to full_name. Color-coded: purple (admin), blue (user), gray (reader).
5. ✅ **User profile dropdown**: Shows full_name + role badge + email, "Change Password" (lazy-loaded `PasswordChangeDialog`), "API Keys" (navigates to `/api-keys`), "Sign out".
6. ✅ **Loading skeletons, empty states**: `SkeletonTable`, `SkeletonCardList` integrated in Home, Spaces, Graphs, Users (done in Phase 10).
7. ⚠️ **Breadcrumbs**: `NavigationBreadcrumb` component exists and is used on some pages, but not yet standardized across all pages.

### Phase 6: Admin & Registry Screens (✅ COMPLETE)

1. ✅ `Admin.tsx` (363 LOC) — Health card, scheduler card, entity cache stats, resync modal, trigger maintenance modal, process tracking table
2. ✅ `AuditLog.tsx` (195 LOC) — Paginated audit log with filters (event, actor, level, time range). Backend: `GET /api/admin/audit`
3. ✅ `EntityRegistry.tsx` (148 LOC) — Searchable list, pagination, status badges, create button
4. ✅ `EntityRegistryDetail.tsx` (233 LOC) — CRUD with tabs (aliases, identifiers, categories, locations), edit/delete with confirmation
5. ✅ `AgentRegistry.tsx` (163 LOC) — Searchable list, status filter, pagination, CRUD
6. ✅ `AgentRegistryDetail.tsx` (260 LOC) — CRUD with tabs (endpoints, functions, changelog), status change (activate/deactivate)

**Sidebar:** All 6 pages linked under Administration section (admin-only gated)
**Routes:** `/audit-log`, `/entity-registry`, `/entity-registry/:entityId`, `/agent-registry`, `/agent-registry/:agentId`
**API methods added to `ApiService.ts`:** `getAuditLog`, `listRegistryEntities`, `getRegistryEntity`, `createRegistryEntity`, `updateRegistryEntity`, `deleteRegistryEntity`, `getEntityAliases`, `getEntityIdentifiers`, `getEntityCategories`, `getEntityLocations`, `listAgentTypes`, `listAgents`, `getAgent`, `createAgent`, `updateAgent`, `deleteAgent`, `changeAgentStatus`, `getAgentEndpoints`, `getAgentFunctions`, `getAgentChangelog`
**Backend endpoint added:** `GET /api/admin/audit` in `admin_endpoint.py` (audit log query with filters + pagination)

### Phase 7: Data Management (✅ COMPLETE — see `planning_import_export/`)

**All backend + frontend work done** (import_export plan Phases 1–6 fully implemented):

1. ✅ `Data.tsx` hub — tabbed view (Import + Export), real API polling
2. ✅ `DataImport.tsx` + `DataImportDetail.tsx` — create job, upload file, execute, poll status, log viewer
3. ✅ `DataExport.tsx` + `DataExportDetail.tsx` — create job, execute, poll status, download via presigned URL
4. ✅ `ImportExportService.ts` — typed API methods for all import/export endpoints
5. ✅ `JobLogViewer.tsx` — shared terminal-style log viewer (auto-poll, level-colored badges)
6. ❌ Delete dead pages: `DataMigrationDetail.tsx`, `DataTrackingDetail.tsx`, `DataCheckpointDetail.tsx` (migrate is out of scope; tracking/checkpoint integrated into detail pages)
7. ✅ Remove `data.ts` mock file (no longer needed)

**Backend capabilities delivered:**
- Import engine: N-Triples, N-Quads, Turtle, JSONL Quads, VitalSigns Block (`.vital`)
- Export engine: N-Triples, N-Quads, JSONL Quads, VitalSigns Block (`.vital`)
- Background job manager with asyncio tasks, progress tracking, checkpoint/resume, cancel
- REST endpoints: create, upload, execute, status, log, download, delete
- Standalone CLIs: `vitalgraphimport`, `vitalgraphexport`
- Cleanup job (auto-deletes old jobs + staged files)

**Remaining polish:**
- ✅ Data pages migrated from `axios` → `ApiService`
- ✅ Mock data from `frontend/src/mock/data.ts` deleted

### Phase 8: User Management & Auth UI (✅ COMPLETE)

**Backend is COMPLETE** — auth modernization fully implemented (see `planning_auth/`).

**8.1 Role-aware navigation** — ✅ DONE
- `role` stored in `AuthService.User` → `AuthContext` from login response
- Entire Administration sidebar section hidden for non-admin (`user?.role === 'admin'` gate)
- Role badge in profile dropdown (purple/blue/gray)
- Space list server-filtered (non-admin users only see assigned spaces)

**8.2 Users list page (`Users.tsx`)** — ✅ DONE
- Table: username, full_name, email, role (badge), is_active, last_login
- Create user form: username, password, role selector, email, full_name
- Admin-only page (sidebar gated)

**8.3 User detail page (`UserDetail.tsx`)** — ✅ DONE
- **Profile section**: View/edit username, full_name, email, role (dropdown), is_active badge
- **Security section** (edit mode): Password change field for admin reset
- **Space Access section** (`SpaceAccessCard`): Interactive grant/revoke UI
  - Fetches user spaces via `GET /api/users/{username}/spaces`
  - Grant form: space selector (from all available spaces), access level selector (Read / Read/Write)
  - Per-space revoke button (red trash icon)
  - Calls `PUT /api/users/{username}/spaces/{space_id}` and `DELETE /api/users/{username}/spaces/{space_id}`
- **API Keys section** (`UserApiKeysCard`): Admin view of user's API keys
  - Lists keys (name, prefix with copy button, active/revoked badge)
  - Revoke button per active key
- **Actions**: Edit, Delete with ConfirmDialog
- Role change triggers `token_version` bump (backend handles revocation within 60s TTL)

**8.4 Self-service password change** — ✅ DONE
- `PasswordChangeDialog.tsx` — lazy-loaded modal in Layout
- Fields: current password, new password (min 8), confirm new password
- Calls `POST /api/users/me/password`
- On success: clears tokens, logs out (all tokens invalidated)
- Accessible from user profile dropdown "Change Password"

**8.5 API key management (self-service)** — ✅ DONE
- `ApiKeys.tsx` — standalone page at `/api-keys`
- Create key (name + optional expiry), key revealed once with copy button
- Revoke with confirmation
- Available via user profile dropdown and sidebar (admin)

**8.6 Login page** — ✅ DONE (no changes needed)
- `role` returned in login response, stored in AuthContext
- Role badge displayed in navbar dropdown

**Backend endpoints added:**
- `GET /api/users/{username}/spaces` — get user's space access map
- `PUT /api/users/{username}/spaces/{space_id}` — grant/update access
- `DELETE /api/users/{username}/spaces/{space_id}` — revoke access

**Files created/modified:**
- ✅ `frontend/src/contexts/AuthContext.tsx` — exposes `user.role`
- ✅ `frontend/src/pages/Users.tsx` — full users list with role columns
- ✅ `frontend/src/pages/UserDetail.tsx` — rebuilt with SpaceAccessCard + UserApiKeysCard
- ✅ `frontend/src/components/PasswordChangeDialog.tsx` — self-service password change
- ✅ `frontend/src/pages/ApiKeys.tsx` — full API key management page
- ✅ `frontend/src/services/ApiService.ts` — user CRUD, API key CRUD, password change, space access methods
- ✅ `vitalgraph/endpoint/users_endpoint.py` — space access REST endpoints

### Phase 9: Vector & Geo UI (🟡 API WIRED, UX NEEDS REWORK — see `planning_vector_geo/vector_geo_ui_plan.md`)

**API integration complete** (vector_geo_ui_plan Phases 1–4 wired), but **UX is not production-ready** — these pages need the same overhaul treatment as all other pages in Phase 3:

1. ✅ `VectorIndexes.tsx` — list, create, delete indexes; trigger re-index with status feedback
2. ✅ `VectorMappings.tsx` — list, create, delete mappings; inline enabled toggle; filter by class/enabled
3. ✅ `VectorMappingDetail.tsx` — detail page with settings edit, property CRUD via `@dnd-kit/sortable` drag-and-drop
4. ✅ `VectorSearch.tsx` — semantic search (vector similarity via KGQuery API) + full-text search mode; index select, top-K, min-score slider, results with score bars + query timing
5. ✅ `GeoPoints.tsx` — combined table + map view; OpenStreetMap (`react-leaflet`) default; Google Maps (`@vis.gl/react-google-maps`) when `VITE_GOOGLE_MAPS_API_KEY` set; radius search with circle overlay; pagination
6. ✅ `VectorGeoService.ts` — typed API methods for all vector/geo endpoints (indexes, mappings, properties, geo config, geo points)
7. ✅ `types/vectorGeo.ts` — TypeScript types for VectorIndex, VectorMapping, MappingProperty, GeoPoint
8. ✅ `MapView.tsx` / `OSMMap.tsx` / `GoogleMap.tsx` — map provider abstraction with env-driven selection
9. ✅ `EntityGeoMiniMap` — inline mini-map on KGEntity detail page (auto-fetches entity geo)
10. ✅ `PropertyListEditor` / `SortablePropertyRow` — drag-and-drop property ordering
11. ✅ `EnabledToggle` — inline toggle switch (shared component)
12. ✅ Navigation sidebar entries: Vector Indexes, Vector Mappings (admin-gated)

**Backend capabilities delivered:**
- Vector indexes: pgvector HNSW, multiple providers (vitalsigns, openai), per-index dimensions/model
- Vector mappings: class-level + type-level, source_type (default/properties/slots), property ordering
- Geo points: PostGIS geography, ST_DWithin spatial filter, distance-ordered results
- Vector search: KGQuery API with `vector_criteria` (similarity) + `geo_criteria` (radius)
- Full-text search: `tsv` column with GIN index, `plainto_tsquery` semantics
- Re-index: per-index or maintenance scheduler (`POST /api/processes/trigger`)
- SPARQL pipeline: `vectorNearby`, `geoDistance`, `withinRadius` functions verified E2E

**New npm dependencies added:**
- `@dnd-kit/core`, `@dnd-kit/sortable`, `@dnd-kit/utilities` — drag-and-drop
- `leaflet`, `react-leaflet` — OpenStreetMap map provider
- `@vis.gl/react-google-maps` — Google Maps provider (optional)

**Remaining UX work** (same overhaul needed as other pages):
- Migrate from raw layout to shared page patterns (`PageHeader`, `LoadingSkeleton`, `EmptyState`, `ErrorDisplay`)
- Improve table UX: consistent column widths, sort indicators, proper loading states
- Improve form UX: better validation messages, inline help text, responsive layouts
- Improve map UX: better marker clustering, responsive sizing, accessible controls
- Improve search UX: better result cards, highlighted matches, query history
- ✅ `axios` → `ApiService` migration complete
- Consistent dark mode support across all vector/geo components
- Accessibility audit (keyboard navigation, ARIA labels, screen reader support)

### Phase 10: UX Polish & Infrastructure (✅ COMPLETE)

Cross-cutting UX improvements applied globally across the application:

**10.1 Mobile Responsiveness** — ✅ DONE
- Sidebar: Collapsible on mobile with overlay backdrop, fixed on desktop
- Tables: Horizontal scroll with responsive column hiding (`hidden lg:table-cell`)
- Tabs: `overflow-x-auto` with `min-w-max` for scrollable tabs on small screens

**10.2 Keyboard Shortcuts & Command Palette** — ✅ DONE
- `useKeyboardShortcuts` hook (`src/hooks/useKeyboardShortcuts.ts`)
- `CommandPalette` component (`src/components/CommandPalette.tsx`) — fuzzy search, keyboard nav
- `Ctrl+K` / `⌘K` opens palette; `Escape` closes it
- Visual trigger button in navbar with keyboard shortcut hint

**10.3 Toast Notifications** — ✅ DONE
- `ToastContext` + `ToastProvider` (`src/contexts/ToastContext.tsx`)
- `ToastContainer` component — fixed bottom-right stack with auto-dismiss (4s)
- Color-coded: success (green), error (red), warning (yellow), info (blue)

**10.4 Reusable Confirm Dialog** — ✅ DONE
- `ConfirmDialog` component (`src/components/ConfirmDialog.tsx`) — variants: `danger`, `warning`
- Adopted in 7 pages: GraphDetail, KGEntities, KGFrames, GraphObjects, KGTypes, Triples, UserDetail

**10.5 404 / Not Found Page** — ✅ DONE
- `NotFound` component (`src/pages/NotFound.tsx`) — styled with path display
- Integrated as catch-all route in `App.tsx`

**10.6 Dynamic Page Titles** — ✅ DONE
- `usePageTitle` hook (`src/hooks/usePageTitle.ts`) — sets `document.title` per page
- Integrated in: Home, Spaces, Graphs, Users, SPARQL, Admin, NotFound

**10.7 Relative Time Display** — ✅ DONE
- `formatRelativeTime` utility in `src/utils/formatUtils.ts`
- `TimeAgo` component (`src/components/TimeAgo.tsx`) — auto-updates every 60s, full date on hover
- Integrated in: Home (recent processes), Users (update_time), Admin (process timestamps)

**10.8 Accessibility (ARIA)** — ✅ DONE
- `aria-label` on icon-only buttons: sidebar toggle, command palette trigger, toast dismiss
- `role="dialog" aria-modal="true"` on CommandPalette and ConfirmDialog
- `aria-hidden="true"` on backdrop overlays
- `aria-labelledby` linking dialog titles
- All table action buttons have `title` attributes

**10.9 Form Validation UX** — ✅ DONE
- `FormField` component (`src/components/FormField.tsx`) — label, error, hint, required indicator
- `useFormValidation` hook (`src/hooks/useFormValidation.ts`) — rules: required, minLength, maxLength, pattern, custom
- Integrated in: Login (username/password), GraphDetail create (URI validation via `new URL()`)

**10.10 Loading Progress Indicator** — ✅ DONE
- `TopLoader` component (`src/components/TopLoader.tsx`) — thin animated blue bar at viewport top
- CSS keyframe animation in `src/index.css`
- Shown during React Suspense page transitions (alongside spinner)

**10.11 Scroll to Top on Navigate** — ✅ DONE
- `ScrollToTop` component (`src/components/ScrollToTop.tsx`)
- Placed inside `<BrowserRouter>` — fires on every pathname change

**10.12 Favicon & Meta Tags** — ✅ DONE
- SVG favicon (`logo.svg`), PNG fallback, Apple touch icon
- Meta description, theme-color (`#1e40af`)
- Open Graph tags (type, title, description, image)
- Removed default Vite placeholder favicon

**10.13 Error Boundary** — ✅ DONE
- `ErrorBoundary` class component (`src/components/ErrorBoundary.tsx`)
- Catches unhandled rendering errors with friendly fallback UI
- "Reload Page" and "Try Again" recovery buttons
- Wraps entire app at outermost level in `App.tsx`

**10.14 Copy to Clipboard** — ✅ DONE
- `CopyButton` component (`src/components/CopyButton.tsx`) — icon button with checkmark feedback
- Integrated in: GraphDetail (graph URI), KGEntities (entity URI), KGFrames (frame URI)

**10.15 Expandable Text** — ✅ DONE
- `ExpandableText` component (`src/components/ExpandableText.tsx`) — configurable line clamp
- "Show more" / "Show less" toggle when text overflows
- Integrated in: `ObjectDetailRenderer` (property values, maxLines=2)

**10.16 Skeleton Loading States** — ✅ DONE (earlier work)
- `SkeletonTable` and `SkeletonCardList` components
- Integrated in: Home, Spaces, Graphs, Users pages (replacing spinners)

---

## 8. Backend Gaps

The following backend issues should be addressed alongside UI work:

| Issue | Description | Impact |
|---|---|---|
| ~~**User CRUD incomplete**~~ | ~~`add_user` and `delete_user` use `self.db` but `list_users` uses in-memory dict.~~ **RESOLVED** — auth modernization complete. All user CRUD is now DB-backed with bcrypt, RBAC (admin/user/reader), per-space access, API keys, audit logging. See `planning_auth/`. | ~~High~~ ✅ Resolved |
| ~~**Import/Export stubs**~~ | ~~The import/export endpoint implementations are stubs.~~ **RESOLVED** — full import/export engine implemented (N-Triples, N-Quads, Turtle, JSONL Quads, VitalSigns Block), REST endpoints wired, background job manager with checkpoint/resume, frontend connected. See `planning_import_export/`. | ~~High~~ ✅ Resolved |
| ~~**GraphAnalysis endpoint needed**~~ | ~~No backend endpoint yet for graph statistics.~~ **RESOLVED** — superseded by space-level analytics (`/api/spaces/{id}/analytics`, `/api/spaces/{id}/metrics`). `GraphAnalysis.tsx` deleted. | ~~Medium~~ ✅ Resolved |
| **MetaQL endpoints empty** | `metaql_query_endpoint.py` is an empty file. | Low — no UI planned for MetaQL currently |
| ~~**Database info endpoint**~~ | ~~`get_database_info()` exists in `VitalGraphAPI` but is not exposed as a route in `vitalgraphapp_impl.py`.~~ **RESOLVED** — Admin.tsx displays DB info via health/cache endpoints. | ~~Medium~~ ✅ Resolved |

---

## 9. Testing Strategy

### 9.1 Tooling — Playwright for Automated E2E

**Why Playwright**: It provides cross-browser support (Chromium, Firefox, WebKit),
built-in `expect` assertions with auto-retrying locators, network interception,
visual regression snapshots, and a `codegen` tool for rapid test authoring. It runs
headless in CI with no extra infrastructure. The Playwright test runner is
TypeScript-native, matching the frontend stack.

**Install** (add to `frontend/package.json` devDependencies):
```
@playwright/test: ^1.49
```

**Directory layout**:
```
frontend/
├── e2e/                            # All Playwright tests
│   ├── fixtures/
│   │   ├── auth.ts                 # Login helper, shared authenticated page
│   │   └── seed.ts                 # API-driven test data setup/teardown
│   ├── pages/                      # Page Object Models (POM)
│   │   ├── login.page.ts
│   │   ├── spaces.page.ts
│   │   ├── space-detail.page.ts
│   │   ├── graphs.page.ts
│   │   ├── graph-detail.page.ts
│   │   ├── objects.page.ts
│   │   ├── object-detail.page.ts
│   │   ├── kg-entities.page.ts
│   │   ├── kg-frames.page.ts
│   │   ├── kg-types.page.ts
│   │   ├── triples.page.ts
│   │   ├── files.page.ts
│   │   ├── users.page.ts
│   │   ├── sparql.page.ts
│   │   ├── data-import.page.ts
│   │   ├── data-export.page.ts
│   │   ├── vector-indexes.page.ts
│   │   ├── vector-mappings.page.ts
│   │   ├── vector-search.page.ts
│   │   ├── geo-points.page.ts
│   │   └── admin.page.ts
│   ├── auth.spec.ts                # Login, logout, token refresh
│   ├── spaces.spec.ts              # Spaces CRUD
│   ├── users.spec.ts               # Users CRUD
│   ├── graphs.spec.ts              # Graphs CRUD
│   ├── objects.spec.ts             # Objects/KGEntities/KGFrames CRUD
│   ├── kg-types.spec.ts            # KG Types CRUD
│   ├── triples.spec.ts             # Triples list, filter
│   ├── files.spec.ts               # File upload, detail, download
│   ├── sparql.spec.ts              # SPARQL query execution
│   ├── data.spec.ts                # Import/Export flows
│   ├── vector-indexes.spec.ts      # Vector index CRUD, reindex trigger
│   ├── vector-mappings.spec.ts     # Vector mapping CRUD, property drag-and-drop
│   ├── vector-search.spec.ts       # Semantic + full-text search
│   ├── geo-points.spec.ts          # Geo table/map view, radius search
│   ├── navigation.spec.ts          # Sidebar, breadcrumbs, deep links
│   └── smoke.spec.ts               # Fast smoke: login + visit every page
├── playwright.config.ts
└── package.json
```

**Playwright config** (`frontend/playwright.config.ts`):
```typescript
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [
    ['html', { open: 'never' }],
    ['junit', { outputFile: 'e2e-results.xml' }],
  ],
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
    { name: 'webkit', use: { ...devices['Desktop Safari'] } },
    { name: 'mobile', use: { ...devices['iPhone 14'] } },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
```

### 9.2 Test Architecture

#### 9.2.1 Authentication Fixture
A shared fixture logs in once and reuses the authenticated browser state across
all tests in a worker, avoiding repeated login overhead:

```typescript
// e2e/fixtures/auth.ts
import { test as base, expect } from '@playwright/test';

export const test = base.extend<{ authenticatedPage: Page }>({
  authenticatedPage: async ({ browser }, use) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.goto('/login');
    await page.fill('input[name="username"]', process.env.E2E_USER || 'admin');
    await page.fill('input[name="password"]', process.env.E2E_PASS || 'admin');
    await page.click('button[type="submit"]');
    await expect(page).toHaveURL('/');
    await use(page);
    await context.close();
  },
});
```

#### 9.2.2 Data Seeding Fixture
Tests should not depend on pre-existing data. A seed fixture creates the
required test data via direct API calls (bypassing the UI) before each test
suite and tears it down after:

```typescript
// e2e/fixtures/seed.ts
import { test as base } from './auth';
import { APIRequestContext } from '@playwright/test';

export const test = base.extend<{ seedData: SeedResult }>({
  seedData: async ({ request }, use) => {
    // Login via API
    const loginResp = await request.post('/api/login', {
      form: { username: 'admin', password: 'admin' }
    });
    const { access_token } = await loginResp.json();
    const headers = { Authorization: `Bearer ${access_token}` };

    // Create test space
    const spaceResp = await request.post('/api/spaces', {
      headers,
      data: { space: 'e2e_test_space', space_name: 'E2E Test Space' }
    });
    const space = await spaceResp.json();

    // Create test graph, entities, etc. as needed
    // ...

    await use({ space, token: access_token });

    // Teardown: delete test space
    await request.delete(`/api/spaces/${space.space.space}`, { headers });
  },
});
```

#### 9.2.3 Page Object Models (POM)
Each page gets a class encapsulating its locators and common actions. Tests stay
readable and resilient to selector changes:

```typescript
// e2e/pages/spaces.page.ts
import { Page, expect } from '@playwright/test';

export class SpacesPage {
  constructor(private page: Page) {}

  async navigate() {
    await this.page.click('a[href="/spaces"]');
    await expect(this.page.locator('h1')).toContainText('Spaces');
  }

  async getSpaceRows() {
    return this.page.locator('table tbody tr');
  }

  async searchSpaces(term: string) {
    await this.page.fill('input[placeholder*="Search"]', term);
  }

  async clickSpace(spaceName: string) {
    await this.page.click(`text=${spaceName}`);
  }
}
```

### 9.3 E2E Test Scenarios

#### Smoke Suite (`smoke.spec.ts`) — runs on every PR
Fast check that the app boots, login works, and every page is reachable:

| # | Test | Assertions |
|---|------|------------|
| 1 | Login with valid credentials | Redirects to `/`, user name visible in navbar |
| 2 | Login with invalid credentials | Error alert shown, stays on `/login` |
| 3 | Visit every sidebar link | Each page loads without JS errors, no blank screens |
| 4 | Logout | Redirects to `/login`, protected routes redirect back |

#### Auth Suite (`auth.spec.ts`)
| # | Test | Assertions |
|---|------|------------|
| 1 | Token refresh on 401 | Mock API to return 401, verify silent retry succeeds |
| 2 | Expired session redirect | Clear tokens, visit protected route, verify redirect to `/login` |
| 3 | Session persistence | Login, reload page, verify still authenticated |

#### CRUD Suites (per entity type)
Each CRUD spec follows this template:

```
1. Seed: create test space + graph via API
2. Create: navigate to list → click "New" → fill form → submit → verify redirect to detail
3. Read:   navigate to list → verify new item appears → click → verify detail fields
4. Update: click Edit → change fields → save → verify updated values
5. Delete: click Delete → confirm modal → verify removed from list
6. Teardown: delete test space via API
```

**Entity-specific tests**:

| Suite | Key scenarios beyond basic CRUD |
|---|---|
| `spaces.spec.ts` | Filter by name, create with description, delete non-empty space warning |
| `graphs.spec.ts` | Space selector filters graphs, graph type badge display |
| `objects.spec.ts` | Tab switching (Objects ↔ KG Entities ↔ KG Frames), space+graph selection carries across tabs |
| `kg-types.spec.ts` | Create with custom properties, JSON-LD property display |
| `triples.spec.ts` | Filter by subject/predicate/object, pagination, triple count badge |
| `files.spec.ts` | File upload (drag-and-drop + button), download, detail view |
| `sparql.spec.ts` | Execute SELECT query → results table, ASK query → boolean, CONSTRUCT → triples, syntax error → error display |
| `data.spec.ts` | Create import job, execute import, verify progress, create export job |
| `vector-indexes.spec.ts` | Create index (name, provider, dimensions), trigger reindex, verify status feedback, delete with data-loss warning |
| `vector-mappings.spec.ts` | Create mapping (class, type URI, index), toggle enabled, edit properties (drag-and-drop reorder), delete with CASCADE warning |
| `vector-search.spec.ts` | Semantic search (enter text, select index, adjust top-K/min-score), verify results with score bars; toggle to full-text mode |
| `geo-points.spec.ts` | View geo table, switch to map view, enter radius search (lat/lon/km), verify circle overlay + filtered results, paginate |
| `users.spec.ts` | Create user, update role, change password, delete user |

#### Navigation Suite (`navigation.spec.ts`)
| # | Test | Assertions |
|---|------|------------|
| 1 | Sidebar active state | Clicking each link highlights correct sidebar item |
| 2 | Breadcrumb trail | Space → Graph → Objects shows correct breadcrumb chain |
| 3 | Deep link | Directly visit `/space/X/graph/Y/objects/graphobjects`, verify correct space+graph selected |
| 4 | Browser back/forward | Navigate Space→Graph→Objects, back button returns to Graphs |
| 5 | Mobile sidebar | At mobile viewport, sidebar collapses, hamburger toggles it |
| 6 | Dark mode | Toggle dark mode, verify no broken contrast/colors |

### 9.4 CI Integration

#### Docker Compose for E2E
A dedicated `docker-compose.e2e.yml` that starts the full stack
(PostgreSQL + Jena sidecar + VitalGraph server + MinIO) and runs
Playwright against it:

```yaml
# docker-compose.e2e.yml
services:
  postgres:
    image: postgres:17
    environment:
      POSTGRES_DB: vitalgraph_e2e
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: test
    ports: ["5432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      retries: 5

  sparql-compiler:
    build:
      context: ./vitalgraph-jena-sidecar
      dockerfile: Dockerfile
    ports: ["7070:7070"]

  minio:
    image: minio/minio:latest
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    command: server /data --console-address ":9001"
    ports: ["9000:9000"]

  vitalgraph:
    build: .
    depends_on:
      postgres: { condition: service_healthy }
      sparql-compiler: { condition: service_started }
      minio: { condition: service_started }
    environment:
      APP_MODE: production
      DATABASE_URL: postgresql://postgres:test@postgres:5432/vitalgraph_e2e
      SIDECAR_URL: http://sparql-compiler:7070
      MINIO_ENDPOINT: minio:9000
      JWT_SECRET_KEY: e2e-test-secret
      E2E_ADMIN_USER: admin
      E2E_ADMIN_PASS: admin
    ports: ["8001:8001"]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
      interval: 5s
      retries: 10

  playwright:
    image: mcr.microsoft.com/playwright:v1.49.0-noble
    depends_on:
      vitalgraph: { condition: service_healthy }
    working_dir: /app/frontend
    environment:
      E2E_BASE_URL: http://vitalgraph:8001
      E2E_USER: admin
      E2E_PASS: admin
      CI: "true"
    volumes:
      - .:/app
    command: npx playwright test --reporter=junit
```

#### GitHub Actions Workflow

```yaml
# .github/workflows/e2e.yml
name: E2E Tests
on:
  push:
    branches: [main]
  pull_request:
    paths: ['frontend/**', 'vitalgraph/endpoint/**', 'vitalgraph/api/**']

jobs:
  e2e:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4

      - name: Build and start services
        run: docker compose -f docker-compose.e2e.yml up -d --build --wait

      - name: Run Playwright tests
        run: docker compose -f docker-compose.e2e.yml run playwright

      - name: Upload test artifacts
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: playwright-report
          path: frontend/playwright-report/
          retention-days: 14

      - name: Upload test results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: e2e-results
          path: frontend/e2e-results.xml

      - name: Teardown
        if: always()
        run: docker compose -f docker-compose.e2e.yml down -v
```

### 9.5 npm Scripts

Add to `frontend/package.json`:
```json
{
  "scripts": {
    "test:e2e": "playwright test",
    "test:e2e:headed": "playwright test --headed",
    "test:e2e:ui": "playwright test --ui",
    "test:e2e:smoke": "playwright test smoke.spec.ts",
    "test:e2e:codegen": "playwright codegen http://localhost:5173",
    "test:e2e:report": "playwright show-report"
  }
}
```

### 9.6 Per-Screen Verification Checklist
Each migrated or new screen should be covered by E2E tests that verify:
1. **List view**: Loads data, pagination works, empty state displays correctly
2. **Detail view**: Fetches single item, displays all fields
3. **Create flow**: Form submits, success message shown, navigates to detail
4. **Edit flow**: Form populates, changes save, success message shown
5. **Delete flow**: Confirmation modal, deletion succeeds, navigates to list
6. **Error states**: API errors display user-friendly messages
7. **Auth integration**: 401 responses trigger token refresh, then retry

### 9.7 Cross-Browser/Responsive Testing
Handled by Playwright projects (see config above):
- **Desktop**: Chromium, Firefox, WebKit
- **Mobile**: iPhone 14 viewport (sidebar collapses, cards stack vertically)
- **Dark mode**: Toggled programmatically in navigation tests

### 9.8 Test Data Strategy

| Approach | When to use |
|---|---|
| **API seeding** (preferred) | Most tests. Create data via REST API before test, teardown after. Fast, deterministic. |
| **Database seeding** | Performance/load tests. Load large datasets via SQL directly. |
| **UI seeding** | Only for testing the create flow itself. All other tests seed via API. |
| **Network mocking** | Error state tests (simulate 500, timeout, network failure). Use `page.route()` to intercept. |

### 9.9 Visual Regression (Optional, Phase 7+)

After the UI is stable, add visual regression via Playwright screenshots:
```typescript
await expect(page).toHaveScreenshot('spaces-list.png', { maxDiffPixels: 100 });
```
Store baseline screenshots in `e2e/screenshots/` and update them intentionally
when UI changes. This catches unintended CSS/layout breakages.

### 9.10 Connection to Backend Testing Plan

The E2E tests (this section) form **Tier 6** in the overall testing pyramid
defined in `planning_testing/testing_plan.md`:

```
Tier 1: Unit (Python, no DB)              — fast, ~150 tests
Tier 2: SPARQL Conformance (DAWG/ARQ)     — needs PG
Tier 3: Integration (storage, KG, schema) — needs PG
Tier 4: API (REST contract)               — needs server (httpx)
Tier 5: Performance (benchmarks)          — nightly
Tier 6: E2E (browser, Playwright)         — needs full stack
```

Tier 4 (API tests via httpx) verifies backend contracts in isolation.
Tier 6 (E2E) verifies the **full frontend→backend round-trip** through a real
browser — auth flow, form submission, data rendering, navigation, error display.

---

## 10. Files Summary

### Files to Delete — ✅ ALL DONE
- ✅ `frontend/src/pages/Objects.tsx` (dead page, replaced by ObjectsLayout) — **DELETED**
- ✅ `frontend/src/mock/` (all files) — **DELETED**
- ✅ `frontend/src/pages/GraphAnalysis.tsx` — **DELETED** (superseded by SpaceDetail Analytics)
- ✅ `frontend/src/pages/DataMigrationDetail.tsx` — **DELETED**
- ✅ `frontend/src/pages/DataTrackingDetail.tsx` — **DELETED**
- ✅ `frontend/src/pages/DataCheckpointDetail.tsx` — **DELETED**

### Files to Significantly Modify — ✅ ALL DONE
- ✅ `frontend/src/services/ApiService.ts` — expanded with typed methods for all endpoints
- ✅ `frontend/src/types/api.ts` — expanded; additional type files created
- ✅ `frontend/src/pages/FileDetail.tsx` — rebuilt with real API
- ✅ `frontend/src/pages/FileUpload.tsx` — ApiService, real space/graph selection
- ✅ `frontend/src/pages/Data.tsx` — connected to real API (import_export plan)
- ✅ `frontend/src/pages/DataImport.tsx` — connected to real API
- ✅ `frontend/src/pages/DataImportDetail.tsx` — connected to real API
- ✅ `frontend/src/pages/DataExport.tsx` — connected to real API
- ✅ `frontend/src/pages/DataExportDetail.tsx` — connected to real API
- ✅ `frontend/src/components/Layout.tsx` — navigation redesign complete (8-section sidebar)
- ✅ `frontend/src/App.tsx` — all routes added (46 lazy-loaded pages, catch-all 404)

### Files to Create
- ✅ `frontend/src/types/spaces.ts` — **CREATED**
- ✅ `frontend/src/types/users.ts` — **CREATED**
- ✅ `frontend/src/types/graphs.ts` — **CREATED**
- ✅ `frontend/src/types/objects.ts` — **CREATED** (includes KGEntity, KGFrame, KGType)
- ✅ `frontend/src/types/files.ts` — **CREATED**
- ✅ `frontend/src/types/triples.ts` — **CREATED**
- ✅ `frontend/src/types/index.ts` — **CREATED** (barrel file)
- ✅ `frontend/src/hooks/useApiError.ts` — **CREATED**
- ✅ `frontend/src/components/shared/ErrorDisplay.tsx` — **CREATED**
- ✅ `frontend/src/components/shared/LoadingSkeleton.tsx` — **CREATED**
- ✅ `frontend/src/components/shared/EmptyState.tsx` — **CREATED**
- ✅ `frontend/src/components/shared/PageHeader.tsx` — **CREATED**
- ✅ `frontend/src/components/shared/index.ts` — **CREATED** (barrel file)
- ✅ `frontend/src/types/data.ts` — **CREATED** (import/export types)
- ✅ `frontend/src/utils/QuadUtils.ts` — **CREATED** (quad parsing utilities)
- ✅ `frontend/src/pages/Admin.tsx` — **CREATED**
- ✅ `frontend/src/pages/EntityRegistry.tsx` — **CREATED**
- ✅ `frontend/src/pages/EntityRegistryDetail.tsx` — **CREATED**
- ✅ `frontend/src/pages/AgentRegistry.tsx` — **CREATED**
- ✅ `frontend/src/pages/AgentRegistryDetail.tsx` — **CREATED**
- ✅ `frontend/src/pages/KGRelations.tsx` — **CREATED**
- ✅ `frontend/src/pages/KGQueryBuilder.tsx` — **CREATED**
- ✅ `frontend/src/pages/KGDocuments.tsx` — **CREATED** (document list with search, segmentation)
- ✅ `frontend/src/pages/KGDocumentDetail.tsx` — **CREATED** (document detail with segments)
- ✅ `frontend/src/pages/GraphVisualization.tsx` — **CREATED** (cytoscape graph viewer)
- ✅ `frontend/src/pages/NotFound.tsx` — **CREATED** (404 catch-all)
- ✅ `frontend/src/components/PasswordChangeDialog.tsx` — **CREATED** (self-service password change)
- ✅ `frontend/src/components/ObjectDetailRenderer.tsx` — **CREATED** (shared detail renderer for KG object pages)
- ✅ `frontend/src/components/OutOfDateAlert.tsx` — **CREATED** (stale data notification)
- ✅ `frontend/src/hooks/useGraphVisualization.ts` — **CREATED** (cytoscape data fetching/rendering)
- ✅ `frontend/src/hooks/useAutoRefresh.ts` — **CREATED** (auto-refresh polling)
- ✅ `frontend/src/hooks/useOutOfDateHandler.ts` — **CREATED** (stale data detection)
- ✅ `frontend/src/pages/VectorIndexes.tsx` (vector index list + create/delete/reindex — **CREATED**, vector_geo_ui_plan)
- ✅ `frontend/src/pages/VectorMappings.tsx` (vector mapping list + create/delete/toggle — **CREATED**, vector_geo_ui_plan)
- ✅ `frontend/src/pages/VectorMappingDetail.tsx` (mapping detail + property CRUD — **CREATED**, vector_geo_ui_plan)
- ✅ `frontend/src/pages/VectorSearch.tsx` (semantic + full-text search — **CREATED**, vector_geo_ui_plan)
- ✅ `frontend/src/pages/GeoPoints.tsx` (table + map view — **CREATED**, vector_geo_ui_plan)
- ✅ `frontend/src/services/VectorGeoService.ts` (typed API for all vector/geo endpoints — **CREATED**, vector_geo_ui_plan)
- ✅ `frontend/src/types/vectorGeo.ts` (VectorIndex, VectorMapping, MappingProperty, GeoPoint types — **CREATED**, vector_geo_ui_plan)
- ✅ `frontend/src/components/map/MapView.tsx` (map provider abstraction — **CREATED**, vector_geo_ui_plan)
- ✅ `frontend/src/components/map/OSMMap.tsx` (OpenStreetMap via react-leaflet — **CREATED**, vector_geo_ui_plan)
- ✅ `frontend/src/components/map/GoogleMap.tsx` (Google Maps via @vis.gl/react-google-maps — **CREATED**, vector_geo_ui_plan)
- ✅ `frontend/src/components/EnabledToggle.tsx` (inline toggle switch — **CREATED**, vector_geo_ui_plan)
- ✅ `frontend/src/components/PropertyListEditor.tsx` (drag-and-drop property ordering — **CREATED**, vector_geo_ui_plan)
- ✅ `frontend/src/components/EntityGeoMiniMap.tsx` (inline mini-map on entity detail — **CREATED**, vector_geo_ui_plan)

---

## 11. Dependencies & Prerequisites

- ~~Backend import/export endpoint stubs must be filled in with real implementations~~ — **RESOLVED**: full import/export engine + REST endpoints + frontend complete. See `planning_import_export/`.
- ~~Backend `get_database_info` must be exposed as a route for admin dashboard~~ — **RESOLVED**: exposed in Admin.tsx via health/cache endpoints
- ~~Backend user management inconsistency to be resolved~~ — **RESOLVED**: auth modernization complete (DB-backed users, bcrypt, RBAC, per-space access, API keys, audit logging). See `planning_auth/`.
- ~~Backend endpoint for graph statistics~~ — **RESOLVED**: superseded by space-level analytics endpoints
- ~~Backend vector/geo REST endpoints must be implemented~~ — **RESOLVED**: all vector index, vector mapping, geo config, and geo points endpoints implemented + verified E2E. See `planning_vector_geo/`.
- `@dnd-kit/sortable`, `leaflet`, `react-leaflet`, `@vis.gl/react-google-maps` — **INSTALLED** (vector_geo_ui_plan Phase 2+4)
- MinIO/S3 must be configured for file upload/download to work end-to-end

---

## 12. Success Criteria

1. ✅ **Zero mock data** — `frontend/src/mock/` directory deleted, no mock imports anywhere
2. ✅ **Single API layer** — all API calls go through `ApiService.ts`, `axios` removed as dependency
3. ✅ **Shared types** — all TypeScript interfaces defined in `frontend/src/types/`, barrel file exports all types, pages use shared `SpaceInfo`/`GraphInfo`
4. ✅ **100% route coverage** — every route in `App.tsx` connects to a working page with real data (46 pages, catch-all 404)
5. ✅ **Backend endpoint coverage** — every significant backend endpoint has a corresponding UI (including KG Documents, Graph Visualization)
6. 🟡 **Consistent UX** — most pages follow shared patterns; Vector/Geo and some KG pages still need UX polish
7. ✅ **Maintainable** — established patterns: `ApiService` + `QuadUtils` + shared types + `ObjectDetailRenderer` + entity-graph components
