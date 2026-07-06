# VitalGraph UI Testing Plan

## Recommended Strategy: Playwright E2E Tests

**Why Playwright** (over Cypress, Selenium, or component-only testing):

| Criterion | Playwright |
|-----------|-----------|
| **Headless CI** | Native — runs Chrome/Firefox/WebKit headless, no display server needed |
| **No human inspection** | Built-in assertion library + screenshot comparison + accessibility checks |
| **React 19 + Vite** | First-class support, auto-waits for hydration |
| **Auth handling** | `storageState` persists JWT across tests without re-login per test |
| **Visual regression** | `toHaveScreenshot()` with configurable thresholds — detects layout drift |
| **Network mocking** | `page.route()` can intercept API calls for deterministic data |
| **Parallel execution** | Worker-based parallelism, runs 54 page tests in < 60s |
| **TypeScript native** | Matches frontend stack exactly |

---

## Architecture

```
frontend/
├── e2e/
│   ├── playwright.config.ts    # Config: base URL, projects, retries
│   ├── global-setup.ts         # Start docker compose, wait for health
│   ├── auth.setup.ts           # Login once, save storageState
│   ├── fixtures/
│   │   ├── authenticated.ts    # Fixture: pre-authenticated page
│   │   └── seeded-data.ts      # Fixture: ensure test space/graph/entities exist
│   ├── pages/                  # Page Object Models
│   │   ├── login.page.ts
│   │   ├── home.page.ts
│   │   ├── spaces.page.ts
│   │   ├── ...
│   │   └── admin.page.ts
│   └── tests/                  # Test specs organized by area
│       ├── auth.spec.ts
│       ├── dashboard.spec.ts
│       ├── spaces.spec.ts
│       ├── graphs.spec.ts
│       ├── objects.spec.ts
│       ├── search.spec.ts
│       ├── indexes.spec.ts
│       ├── data-io.spec.ts
│       ├── admin.spec.ts
│       └── visualization.spec.ts
```

---

## Test Categories

### 1. Autonomous Validation Methods (no human inspection)

| Method | What it catches |
|--------|----------------|
| **DOM assertions** (`toBeVisible`, `toHaveText`, `toHaveCount`) | Missing/broken content |
| **Visual regression** (`toHaveScreenshot`) | CSS regressions, layout breaks |
| **Accessibility audit** (`@axe-core/playwright`) | WCAG violations, missing aria |
| **Network assertions** (`waitForResponse`) | API calls made correctly, no 4xx/5xx |
| **Console error capture** (`page.on('console')`) | Runtime JS exceptions |
| **Navigation checks** (`toHaveURL`) | Routing and redirect correctness |

---

## Screen-by-Screen Test Coverage

### Tier 1: Authentication & Navigation (Priority: Critical)

| # | Screen | Route | Tests |
|---|--------|-------|-------|
| 1 | **Login** | `/login` | Valid login → redirect to `/`, invalid credentials → error alert, empty fields → validation, already-authenticated → redirect, remember me checkbox |
| 2 | **Protected routes** | `/*` | Unauthenticated access → redirect to `/login`, expired token → refresh or redirect |
| 3 | **Layout/Nav** | all pages | Sidebar renders all nav items, breadcrumb updates on navigate, dark mode toggle, command palette (Ctrl+K), responsive mobile collapse |

**Est. tests: 12**

---

### Tier 2: Dashboard & Spaces (Priority: High)

| # | Screen | Route | Tests |
|---|--------|-------|-------|
| 4 | **Home/Dashboard** | `/` | Stat cards render (spaces, users, graphs, triples counts), recent processes list, space summaries, links navigate correctly |
| 5 | **Spaces List** | `/spaces` | Table renders with space names, create button present, filter/search works, pagination, click row → detail |
| 6 | **Space Detail** | `/space/:id` | Name + metadata displayed, analytics tab (charts render), overview tab, edit name, delete confirmation dialog |

**Est. tests: 18**

---

### Tier 3: Graph & Object Management (Priority: High)

| # | Screen | Route | Tests |
|---|--------|-------|-------|
| 7 | **Graphs List** | `/graphs`, `/space/:spaceId/graphs` | Table shows graph names/stats, create new graph, space filter, pagination |
| 8 | **Graph Detail** | `/space/:spaceId/graph/:graphId` | Graph metadata, edit form, delete, navigation to objects/triples |
| 9 | **Graph Objects** | `.../objects/graphobjects` | Object list loads, pagination, type filter, click → detail |
| 10 | **KG Entities** | `.../objects/kgentities` | Entity list, search, type filter, pagination, bulk actions |
| 11 | **KG Entity Detail** | `.../entity/:entityId` | Properties rendered, entity graph, edit capability |
| 12 | **KG Frames** | `.../objects/kgframes` | Frame list, pagination, slot display |
| 13 | **KG Frame Detail** | `.../frame/:frameId` | Frame properties, slots list, navigation to related entities |
| 14 | **KG Relations** | `.../objects/kgrelations` | Relation list, source/destination display, filters |
| 15 | **KG Documents** | `.../objects/kgdocuments` | Document list, pagination, search |
| 16 | **KG Document Detail** | `.../document/:documentId` | Document content, metadata, segments |
| 17 | **Object Detail** | `.../object/:objectId` | Generic object renderer, properties table, JSON-LD view |

**Est. tests: 40**

---

### Tier 4: KG Types & Ontology (Priority: High)

| # | Screen | Route | Tests |
|---|--------|-------|-------|
| 18 | **KG Types List** | `/kg-types` | Type list with class hierarchy, search, create new type |
| 19 | **KG Type Detail** | `/kg-types/:kgTypeId` | Type properties, documentation panel, relationships panel, edit/create form |

**Est. tests: 10**

---

### Tier 5: Search & Semantic Features (Priority: High)

| # | Screen | Route | Tests |
|---|--------|-------|-------|
| 20 | **Semantic Search** | `/semantic-search` | Search input, results list, filters (space/graph/index), result detail navigation, vector/FTS/fuzzy tabs |
| 21 | **Search Result Detail** | `.../search-result/:subjectUri` | Result properties, score display, source entity link |
| 22 | **KG Query Builder** | `/kg-query-builder` | Query type selector, criteria builder form, execute query, results table, pagination |

**Est. tests: 18**

---

### Tier 6: Indexes & Mappings (Priority: Medium)

| # | Screen | Route | Tests |
|---|--------|-------|-------|
| 23 | **Indexes** | `/indexes` | Tabs for vector/FTS/fuzzy, list per type, create buttons |
| 24 | **Vector Index Detail** | `.../indexes/vector/:indexName` | Index stats, dimension, provider, distance metric, delete |
| 25 | **FTS Indexes** | `/indexes` (FTS tab) | FTS index list, languages display |
| 26 | **FTS Index Detail** | nested | Language config, mapping stats |
| 27 | **Index Mappings** | `/index-mappings` | Mapping list across types, filter by index/type |
| 28 | **Search Mapping Detail** | `.../index-mappings/:mappingId` | Properties selector (drag-and-drop), source type, enable/disable toggle |
| 29 | **Fuzzy Mappings** | (in indexes) | Fuzzy mapping list, parameters display |
| 30 | **Fuzzy Mapping Detail** | `.../fuzzy-mappings/:mappingId` | Shingle K, Num Perm, LSH threshold, phonetic bonus config |
| 31 | **Geo Shapes** | `/geo-shapes` | Geo config list, map visualization (Leaflet renders), spatial query UI |

**Est. tests: 28**

---

### Tier 7: Data Import/Export (Priority: Medium)

| # | Screen | Route | Tests |
|---|--------|-------|-------|
| 32 | **Data Import List** | `/data/import` | Import jobs list, status badges, create new |
| 33 | **Data Import Detail** | `/data/import/:importId` | Job config form, file upload, start import, progress/log viewer |
| 34 | **Data Export List** | `/data/export` | Export jobs list, download links |
| 35 | **Data Export Detail** | `/data/export/:exportId` | Export config, format selection, start export |

**Est. tests: 14**

---

### Tier 8: Files & Triples (Priority: Medium)

| # | Screen | Route | Tests |
|---|--------|-------|-------|
| 36 | **Files List** | `/files` | File table, upload button, type/size display, pagination |
| 37 | **File Detail** | `.../file/:fileId` | File metadata, download, delete |
| 38 | **File Upload** | `.../file/new` | Drag-and-drop zone, file type selection, upload progress |
| 39 | **Triples** | `/triples` | Triple table (subject, predicate, object, graph), pagination, search, SPARQL link |
| 40 | **SPARQL** | `/sparql` | Query editor (syntax highlighting), execute button, results table, error display, saved queries |

**Est. tests: 20**

---

### Tier 9: Administration (Priority: Medium)

| # | Screen | Route | Tests |
|---|--------|-------|-------|
| 41 | **Users List** | `/users` | User table, create button, role badges |
| 42 | **User Detail** | `/user/:id` | User profile, role editor, password change dialog, delete |
| 43 | **API Keys** | `/api-keys` | Key list, create new, copy key, revoke |
| 44 | **Admin** | `/admin` | Resync button, system info, settings |
| 45 | **Audit Log** | `/audit-log` | Log table, actor filter, time range, event type filter |
| 46 | **Entity Registry** | `/entity-registry` | Entity list, identifiers/aliases display |
| 47 | **Entity Registry Detail** | `/entity-registry/:entityId` | Full entity profile, identifiers CRUD, aliases CRUD, categories, locations |
| 48 | **Agent Registry** | `/agent-registry` | Agent list, status badges |
| 49 | **Agent Registry Detail** | `/agent-registry/:agentId` | Agent config, capabilities, enable/disable |

**Est. tests: 30**

---

### Tier 10: Visualization & Advanced (Priority: Low)

| # | Screen | Route | Tests |
|---|--------|-------|-------|
| 50 | **Graph Visualization** | `/visualization` | Cytoscape canvas renders, node/edge counts, zoom/pan, layout controls, node click → detail |
| 51 | **Object Layout Tabs** | `.../objects` | Tab navigation (graphobjects/kgentities/kgframes/kgrelations/kgdocuments), active tab highlighting |
| 52 | **404 / Not Found** | `/nonexistent` | 404 page renders, home link works |

**Est. tests: 10**

---

## Summary

| Tier | Area | Est. Tests |
|------|------|-----------|
| 1 | Auth & Navigation | 12 |
| 2 | Dashboard & Spaces | 18 |
| 3 | Graph & Object Management | 40 |
| 4 | KG Types & Ontology | 10 |
| 5 | Search & Semantic | 18 |
| 6 | Indexes & Mappings | 28 |
| 7 | Data Import/Export | 14 |
| 8 | Files & Triples | 20 |
| 9 | Administration | 30 |
| 10 | Visualization & Advanced | 10 |
| **Total** | | **~200** |

---

## Implementation Strategy

### Phase 0: Test-Readiness Instrumentation (Pre-requisite)

Before writing any Playwright tests, instrument the UI with stable selectors and
semantic attributes. This eliminates flaky selectors and makes all subsequent
test authoring dramatically faster.

#### 0.1 Add `data-testid` Attributes

Add `data-testid` to every interactive/assertable element using this naming convention:

| Element | Pattern | Example |
|---------|---------|---------|
| Page container | `page-{name}` | `data-testid="page-spaces"` |
| Action button | `{action}-{noun}-btn` | `data-testid="create-space-btn"` |
| Table | `{noun}-table` | `data-testid="spaces-table"` |
| Table row | `{noun}-row-{id}` | `data-testid="space-row-sp_abc"` |
| Form input | `input-{field}` | `data-testid="input-space-name"` |
| Modal/Dialog | `dialog-{action}` | `data-testid="dialog-delete-confirm"` |
| Tab | `tab-{name}` | `data-testid="tab-kgentities"` |
| Nav item | `nav-{name}` | `data-testid="nav-spaces"` |
| Empty state | `empty-{context}` | `data-testid="empty-entities"` |
| Error state | `error-{context}` | `data-testid="error-load-spaces"` |
| Loading state | `loading-{context}` | `data-testid="loading-entities"` |

**Priority order for `data-testid` rollout:**
1. Login form (username, password, submit)
2. Layout sidebar nav items
3. All list pages (tables, create buttons, pagination)
4. All detail pages (edit/delete buttons, form fields)
5. Modals and confirmation dialogs
6. Search inputs and filter controls

#### 0.2 Add Semantic ARIA Roles & Labels

Enables Playwright's `getByRole()` and `getByLabel()` — the most resilient locators:

```tsx
// Navigation landmarks
<nav aria-label="Main navigation">
<main aria-label="Page content">

// Tables (enables getByRole('table', { name: 'Spaces list' }))
<table aria-label="Spaces list">

// Dialogs (enables getByRole('dialog'))
<div role="dialog" aria-label="Delete confirmation">

// Form labels (enables getByLabel('Space Name'))
<Label htmlFor="space-name">Space Name</Label>
<TextInput id="space-name" ... />
```

#### 0.3 Add `aria-busy` Loading States

Lets Playwright auto-wait for content readiness without fragile `waitForTimeout`:

```tsx
<div aria-busy={isLoading}>
  {isLoading ? <Spinner /> : <DataTable ... />}
</div>
```

#### 0.4 Add `data-status` / `data-state` on Stateful Elements

Allows assertions on element state without inspecting CSS classes:

```tsx
<tr data-testid="import-job-row" data-status={job.status}>  {/* "running"|"complete"|"failed" */}
<div data-testid="toast" data-state={toast.type}>           {/* "success"|"error"|"info" */}
<button data-testid="toggle-index" data-state={enabled ? "on" : "off"}>
```

#### 0.5 Ensure All Forms Have Proper `id`/`htmlFor` Pairing

Audit every `<TextInput>`, `<Select>`, `<Textarea>` and ensure:
- Each has a unique `id`
- The corresponding `<Label>` has `htmlFor` matching that `id`

This enables `page.getByLabel('Space Name')` which is the cleanest and most accessible locator.

#### 0.6 Estimated Scope

| Page group | Files to instrument | Est. effort |
|-----------|-------------------|-------------|
| Auth & Layout | `Login.tsx`, `Layout.tsx`, nav components | 1 hr |
| Spaces/Graphs | `Spaces.tsx`, `SpaceDetail.tsx`, `Graphs.tsx`, `GraphDetail.tsx` | 2 hr |
| Objects (entities, frames, relations, docs) | 10 files | 3 hr |
| Search & Indexes | `SemanticSearch.tsx`, `KGQueryBuilder.tsx`, index pages | 3 hr |
| Data, Files, Admin | remaining pages | 3 hr |
| **Total** | **~54 page files** | **~12 hr** |

> **Key principle**: These additions are invisible to users, have zero runtime
> cost, never break existing functionality, and can be done incrementally —
> instrument a page right before writing its tests.

---

### Phase 0.5: Clean-Database Test Infrastructure

The UI tests need a **deterministic, from-scratch database** — not one polluted by
previous dev sessions. This is especially important because KG types, entity
registry entries, agent registry entries, and users are **global** (not per-space).

#### Architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│  docker-compose.test.yml                                                  │
│                                                                           │
│  ┌──────────────┐  ┌───────────────────┐  ┌──────────┐  ┌──────────────┐ │
│  │  PostgreSQL   │  │ VitalGraph Server │  │  Sidecar  │  │    MinIO     │ │
│  │  (ephemeral   │  │ (auto-init on     │  │  (SPARQL  │  │  (object     │ │
│  │   volume)     │  │  first connect)   │  │  compile) │  │   store)     │ │
│  └──────┬───────┘  └───────┬───────────┘  └──────────┘  └──────────────┘ │
│         │                  │                                              │
│         │     init tables + seed admin user                               │
│         │◄─────────────────┘                                              │
│         │                                                                 │
│         │     POST /api/... (seed test data)                              │
│         │◄──────────────────────────────────────────┐                     │
│         │                                           │                     │
│  ┌──────┴─────────────────────────────────────────┐ │                     │
│  │  tests/shared/seed_ui_test_data.py             │ │                     │
│  │  (runs via Playwright global-setup.ts)         │─┘                     │
│  └────────────────────────────────────────────────┘                       │
└────────────────────────────────────────────────────────────────────────────┘
```

#### 1. `docker-compose.test.yml` — Ephemeral Test Stack

A test-specific compose file that adds PostgreSQL (not in the main compose)
and uses **no persistent volumes** so every `docker compose down && up` starts
from a blank database. The VitalGraph server runs `init` automatically on
first connection (via `SparqlSQLAdmin.init_tables()`).

```yaml
# docker-compose.test.yml
version: '3.8'

services:
  postgres:
    image: pgvector/pgvector:pg17
    container_name: vitalgraph-test-pg
    environment:
      POSTGRES_DB: sparql_sql_graph
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: testpass
    ports:
      - "5433:5432"       # non-default port to avoid clashing with dev PG
    # NO volumes — starts empty every time
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 2s
      timeout: 5s
      retries: 10
    networks:
      - vitalgraph_test

  vitalgraph:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: vitalgraph-test-app
    ports:
      - "8002:8001"       # non-default port to avoid clashing with dev server
    environment:
      - APP_MODE=production
      - PORT=8001
      - HOST=0.0.0.0
      - WORKERS=1
      - SECRET_KEY=test-secret-key
      - JWT_SECRET_KEY=test-jwt-secret
      # Point to test PostgreSQL
      - VG_BACKEND_TYPE=sparql_sql
      - VG_PG_HOST=postgres
      - VG_PG_PORT=5432
      - VG_PG_DATABASE=sparql_sql_graph
      - VG_PG_USER=postgres
      - VG_PG_PASSWORD=testpass
      - VG_SIDECAR_URL=http://sparql-compiler:7070
      # Auto-init on startup
      - VG_AUTO_INIT=true
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - vitalgraph_test

  sparql-compiler:
    build:
      context: ./vitalgraph-jena-sidecar
      dockerfile: Dockerfile
    container_name: vitalgraph-test-sidecar
    ports:
      - "7071:7070"
    environment:
      - PORT=7070
    networks:
      - vitalgraph_test

  minio:
    image: minio/minio:latest
    container_name: vitalgraph-test-minio
    command: server /data --console-address ":9001"
    environment:
      - MINIO_ROOT_USER=minioadmin
      - MINIO_ROOT_PASSWORD=minioadmin
    networks:
      - vitalgraph_test

networks:
  vitalgraph_test:
    driver: bridge
```

**Key differences from `docker-compose.yml`:**
- **PostgreSQL included** (dev compose relies on host-local PG)
- **No persistent volumes** — every `up` is a clean slate
- **Non-default ports** (8002, 5433, 7071) — can run alongside dev stack
- **`VG_AUTO_INIT=true`** — triggers the equivalent of `vitalgraphadmin init`
  which calls `SparqlSQLAdmin.init_tables()` → creates admin tables, indexes,
  and seed data (install record, default admin user, default agent types)

#### 2. Shared Seed Script — `tests/shared/seed_ui_test_data.py`

After `init` creates the empty schema, this script populates it with
deterministic test data. Both the existing pytest API tests and the new
Playwright UI tests can reuse this.

```python
"""Seed deterministic test data for UI and API tests.

Run via: python -m tests.shared.seed_ui_test_data

Produces a known set of:
  - Spaces (global)
  - Graphs (per-space)
  - KG Types (global)
  - KG Entities + Relations (per-graph)
  - Entity Registry entries (global)
  - Users (global)
  - Vector indexes + mappings
  - Sample import/export jobs

All URIs, names, and counts are constants importable by both
pytest fixtures and Playwright global-setup.
"""

# --- Constants (importable by test files) ---
SPACE_ID = "e2e_test_space"
GRAPH_ID = "urn:e2e:graph:main"
ADMIN_USER = "admin"
ADMIN_PASS = "admin"

ENTITY_URIS = {
    "alice": "urn:e2e:entity:alice",
    "bob": "urn:e2e:entity:bob",
    "carol": "urn:e2e:entity:carol",
}

EXPECTED_COUNTS = {
    "spaces": 1,
    "graphs": 1,
    "entities": 3,
    "relations": 2,
    "kg_types": 5,       # including built-in types
    "users": 1,           # admin
}

async def seed(server_url: str = "http://localhost:8002"):
    """Seed all test data via the REST API."""
    from vitalgraph.client.vitalgraph_client import VitalGraphClient

    client = VitalGraphClient(server_url=server_url,
                               username=ADMIN_USER, password=ADMIN_PASS)
    await client.open()

    try:
        # 1. Create space
        from vitalgraph.model.spaces_model import Space
        space = Space(space=SPACE_ID, space_name="E2E Test Space")
        await client.spaces.create_space(space)

        # 2. Create graph
        await client.graphs.create_graph(SPACE_ID, GRAPH_ID)

        # 3. Create KG entities
        # ... (entity creation using VitalSigns objects)

        # 4. Create relations between entities
        # ...

        # 5. Create vector indexes + upsert sample embeddings
        # ...

        # 6. Entity registry entries (global)
        # ...

    finally:
        await client.close()
```

#### 3. Reuse by Existing API Tests

The existing `tests/api/conftest.py` creates ephemeral per-module spaces. For
**shared** tests (UI + API), the seed script's constants can be imported:

```python
# tests/api/conftest.py — option to reuse seeded data
from tests.shared.seed_ui_test_data import SPACE_ID, GRAPH_ID, ENTITY_URIS
```

The per-module ephemeral approach continues to work for API-only tests that
need isolation. The shared seed data is for scenarios where both the UI tests
and API tests need to agree on what exists in the database.

#### 4. Global vs Per-Space Data

| Data type | Scope | Seeded by |
|-----------|-------|-----------|
| Admin tables (install, user) | Global | `SparqlSQLAdmin.init_tables()` (auto-init) |
| KG Types | Global | `seed_ui_test_data.py` |
| Entity Registry | Global | `seed_ui_test_data.py` |
| Agent Registry + Agent Types | Global | `init_tables()` seeds default type; script adds agents |
| Users | Global | `init_tables()` seeds admin; script adds test users |
| Spaces | Global | `seed_ui_test_data.py` |
| Graphs | Per-space | `seed_ui_test_data.py` |
| Entities, Relations, Frames | Per-graph | `seed_ui_test_data.py` |
| Vector indexes, Mappings | Per-space | `seed_ui_test_data.py` |
| Import/Export jobs | Per-space | `seed_ui_test_data.py` |

#### 5. CI Lifecycle

```
1. docker compose -f docker-compose.test.yml up -d --build --wait
2. python -m tests.shared.seed_ui_test_data           # seed via REST API
3. npx playwright test                                  # UI tests
4. python -m pytest tests/api/ -m api                   # API tests (optional, same DB)
5. docker compose -f docker-compose.test.yml down        # destroy everything
```

Every CI run gets a **completely fresh database** — no state leaks between runs.
The same compose file works identically on developer machines.

#### 6. Larger Datasets for Realistic UI Testing

The minimal seed data (a handful of entities/relations) is sufficient for basic
CRUD and navigation tests, but several UI screens are only meaningful with
larger, real-world datasets:

| Screen | Why it needs volume | Recommended dataset |
|--------|-------------------|---------------------|
| **Home / Dashboard** | Stat cards, space summaries, and charts are trivial with 3 entities | WordNet (~570k edges, ~120k entities) |
| **Space Analytics** | Charts (ApexCharts) need enough data to render meaningful distributions | WordNet or FrameNet |
| **Graph Visualization** | Cytoscape graph layout needs a non-trivial node/edge count to exercise zoom, pan, clustering | FrameNet (~1k frames, ~13k frame-entity edges) |
| **KG Query Builder** | Complex multi-hop queries, frame queries, and relation traversals return empty on tiny data | FrameNet (frame structure with slots + entities) |
| **Semantic Search** | Vector search ranking is meaningless with < 10 entities | WordNet (diverse vocabulary for embedding tests) |
| **Triples** | Pagination, filtering, and SPARQL queries need enough rows to exercise the UI | Either dataset |
| **KG Frames** | Frame list and frame detail pages need real frame data with multiple slots | FrameNet |
| **KG Types** | Type hierarchy tree is trivial without a rich ontology | WordNet (44+ KGType subclasses) |

**Implementation approach:**
- Create a second seed profile: `seed_ui_test_data.py --profile full`
- The `full` profile imports WordNet and/or FrameNet via the `vitalgraphimport` CLI
  (N-Triples files already exist in `test_data/`)
- CI runs the `minimal` profile by default (fast); `full` profile runs on nightly or
  dedicated test jobs
- The `docker-compose.test.yml` stack is the same — only the seed step changes

```
# Minimal (CI, ~10s seed)
python -m tests.shared.seed_ui_test_data --profile minimal

# Full (nightly, ~2-5min seed including WordNet + FrameNet import)
python -m tests.shared.seed_ui_test_data --profile full
```

---

### Phase 1: Foundation (Week 1)
1. Install Playwright: `npm init playwright@latest` in `frontend/`
2. Create `docker-compose.test.yml` with ephemeral PostgreSQL
3. Implement seed script (`tests/shared/seed_ui_test_data.py`)
4. Configure `playwright.config.ts` with base URL `http://localhost:8002`
5. Implement `auth.setup.ts` — login once, persist `storageState`
6. Wire `global-setup.ts` to run the seed script

### Phase 1.5: Single-Flow End-to-End Proof (Week 1–2)

Before testing all 54 pages, prove the entire pipeline works by automating
**one complete user journey** that touches login → navigation → CRUD → detail →
search → back. This validates every layer at once: auth, routing, API calls,
data rendering, form submission, and cleanup.

**Recommended flow: Entity Lifecycle**

```
Login → Home (dashboard stats visible)
  → Navigate to Spaces → click into seeded space
  → Navigate to Graphs → click into seeded graph
  → Navigate to KG Entities tab
  → Assert seeded entities appear in the table
  → Click "Create" → fill entity form → submit
  → Assert new entity appears in list
  → Click into new entity → detail page renders
  → Edit entity name → save → assert updated name
  → Delete entity → confirm dialog → assert removed from list
  → Navigate to Semantic Search → search for remaining entity by name
  → Assert search result appears
```

**What this single test proves:**
- `docker-compose.test.yml` + seed script produce a working environment
- Auth setup (`storageState`) works across all pages
- `data-testid` attributes work for locating elements
- Page Object Models pattern is viable
- API calls succeed (POST create, PUT update, DELETE, GET list)
- Navigation between list → detail → list works
- Form submission and validation work
- Confirmation dialogs work
- Search returns real results from seeded data

**Deliverables:**
7. `e2e/tests/entity-lifecycle.spec.ts` — single spec, ~10 assertions
8. Page Object Models for the pages in this flow:
   `login.page.ts`, `home.page.ts`, `spaces.page.ts`, `graphs.page.ts`,
   `entities.page.ts`, `entity-detail.page.ts`, `semantic-search.page.ts`
9. Instrument only these 7 pages with `data-testid` (Phase 0 subset)

**Gate**: This test must pass green before proceeding to Phase 2. If it fails,
it reveals infrastructure issues (compose, seed, auth, selectors) that would
otherwise surface across dozens of tests simultaneously.

---

### Phase 2: Core CRUD (Week 2)
10. Remaining Page Object Models for: SpaceDetail, GraphDetail, Objects, Frames
11. Tiers 2–4 tests (dashboard, graphs, objects, types)
12. Add visual regression baselines (`npx playwright test --update-snapshots`)

### Phase 3: Search & Indexes (Week 3)
13. Tiers 5–6 (semantic search, query builder, indexes, mappings)
14. Network mocking for deterministic search results

### Phase 4: Data & Admin (Week 4)
15. Tiers 7–9 (import/export, files, triples, SPARQL, admin)
16. Tier 10 (visualization — Cytoscape canvas assertions)

### Phase 5: CI Integration
17. Add `playwright.yml` GitHub Actions workflow
18. Configure visual regression snapshot storage
19. Add accessibility audit step (axe-core)

---

## Configuration

```typescript
// playwright.config.ts
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e/tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: [['html'], ['json', { outputFile: 'test-results.json' }]],
  
  use: {
    // Test compose exposes on port 8002 to avoid clashing with dev
    baseURL: process.env.VG_TEST_URL || 'http://localhost:8002',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  // Auth setup project — login once, save storageState
  projects: [
    { name: 'setup', testMatch: /auth\.setup\.ts/, teardown: 'cleanup' },
    { name: 'cleanup', testMatch: /global\.teardown\.ts/ },
    
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], storageState: '.auth/user.json' },
      dependencies: ['setup'],
    },
    {
      name: 'mobile',
      use: { ...devices['iPhone 14'], storageState: '.auth/user.json' },
      dependencies: ['setup'],
    },
  ],

  // Global setup seeds the database via REST API
  globalSetup: './e2e/global-setup.ts',
});
```

```typescript
// e2e/global-setup.ts
import { execSync } from 'child_process';

export default async function globalSetup() {
  const serverUrl = process.env.VG_TEST_URL || 'http://localhost:8002';

  // Wait for server health
  for (let i = 0; i < 30; i++) {
    try {
      const res = await fetch(`${serverUrl}/health`);
      if (res.ok) break;
    } catch { /* not ready */ }
    await new Promise(r => setTimeout(r, 2000));
  }

  // Seed test data via the shared Python script
  execSync(
    `python -m tests.shared.seed_ui_test_data --server-url ${serverUrl}`,
    { cwd: '..', stdio: 'inherit' }
  );
}
```

---

## Key Test Patterns

### 1. Page Object Model (reusable)
```typescript
// e2e/pages/spaces.page.ts
export class SpacesPage {
  constructor(private page: Page) {}
  
  async goto() { await this.page.goto('/spaces'); }
  get table() { return this.page.getByTestId('spaces-table'); }
  get rows() { return this.table.locator('tbody tr'); }
  get createButton() { return this.page.getByTestId('create-space-btn'); }
  
  async getRowByName(name: string) {
    return this.rows.filter({ hasText: name });
  }
}
```

### 2. Visual Regression (no human needed)
```typescript
test('dashboard renders correctly', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveScreenshot('dashboard.png', { maxDiffPixels: 100 });
});
```

### 3. API Response Validation (real backend, seeded data)
```typescript
test('spaces list shows seeded space', async ({ page }) => {
  const responsePromise = page.waitForResponse('**/api/spaces*');
  await page.goto('/spaces');
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  // Assert seeded data is visible in the UI
  await expect(page.getByTestId('space-row-e2e_test_space')).toBeVisible();
});
```

### 4. Accessibility (automated WCAG checks)
```typescript
import AxeBuilder from '@axe-core/playwright';

test('login page is accessible', async ({ page }) => {
  await page.goto('/login');
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});
```

### 5. Console Error Detection
```typescript
test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
  page.on('pageerror', err => errors.push(err.message));
  // After test: expect(errors).toEqual([]);
});
```

---

## Prerequisites

- `docker-compose.test.yml` stack running (PostgreSQL + VitalGraph + Sidecar + MinIO)
- Seed script executed (`tests/shared/seed_ui_test_data.py`)
- Node.js 18+ for Playwright
- No dependency on developer's local database state

**Quick start:**
```bash
# Start clean test stack
docker compose -f docker-compose.test.yml up -d --build --wait

# Seed data
python -m tests.shared.seed_ui_test_data

# Run UI tests
cd frontend && npx playwright test

# Tear down (destroys all data)
docker compose -f docker-compose.test.yml down
```

---

## Success Criteria

- **Zero human inspection**: All tests are fully automated assertions
- **Deterministic**: Every run starts from identical seeded state
- **< 3 minutes total runtime** in CI (parallel workers)
- **Visual baselines** committed — any CSS/layout change flagged automatically
- **Accessibility score**: Zero WCAG A/AA violations
- **Console clean**: No unhandled JS errors across all pages
- **Coverage**: Every route in `App.tsx` hit by at least one test
- **Shared data**: Seed constants importable by both Playwright and pytest

---

## Resolved Decisions

### Infrastructure

1. **`VG_AUTO_INIT`** — Does not exist today. Must be implemented in the server
   startup path (e.g. `vitalgraphdb_cmd.py`) to call `SparqlSQLAdmin.init_tables()`
   when the env var is set. **This feature is test-only** — must be gated so it
   cannot run in production. Implementation: check `VG_AUTO_INIT=true` env var
   after DB connect, before starting the HTTP server.

2. **Config via env vars** — All config should come from environment variables.
   `VitalGraphConfig` / `config_loader` must support env var–based configuration
   (verify current support and fill gaps as needed).

### Data

3. **WordNet / FrameNet data** — N-Triples files can be committed to git if
   needed (e.g. `test_data/wordnet.nt`, `test_data/framenet.nt`). This keeps
   CI self-contained with no external artifact dependencies.

4. **Admin user seeding** — `init_tables()` does **not** seed an admin user in the
   DB. Instead, `VitalGraphAuth` provides a **bootstrap admin** — an in-memory
   fallback configured via `AUTH_ROOT_USERNAME` / `AUTH_ROOT_PASSWORD` env vars
   (see `vitalgraphapp_impl.py` line 97–100). When the DB `"user"` table is empty,
   login falls back to this bootstrap admin. On first real use, the admin should
   be persisted to the DB. For tests, set these env vars in
   `docker-compose.test.yml` and the seed script can log in immediately.

### Playwright

5. **Installation location** — Separate top-level `e2e/` directory with its own
   `package.json`. This isolates test dependencies from the frontend build and
   avoids polluting the production dependency tree.

6. **Visual regression baselines** — Chromium only. Single browser simplifies
   baseline maintenance and CI time.

7. **Mobile testing** — Deferred. Remove the `iPhone 14` project from the initial
   Playwright config. Can be added later as a separate project.

### Process

8. **Test data mutation & parallelism** — Use unique entity names per worker,
   based on a common prefix + `test.info().parallelIndex`. Example:
   `urn:e2e:entity:worker_${workerIndex}:${testName}`. This avoids CRUD
   collisions without sacrificing parallel execution speed.

9. **CI platform** — GitHub Actions. Use the official
   `mcr.microsoft.com/playwright` Docker image or the `playwright install --with-deps`
   step in the workflow.

10. **Instrumentation strategy** — Two phases (not incremental):
    - **Phase 0 batch 1**: Instrument the 7 pages used by the Phase 1.5
      single-flow proof (Login, Home, Spaces, Graphs, Entities, EntityDetail,
      SemanticSearch)
    - **Phase 0 batch 2**: Instrument all remaining ~47 pages in one pass before
      Phase 2 begins

---

## Alignment Audit — Backend API vs Frontend UI

The table below maps every backend endpoint module to its frontend coverage.
**Coverage** = the UI page surfaces the endpoint's CRUD operations (list, get,
create, update, delete) to the user.

| Backend Endpoint | Prefix | Frontend Page(s) | Coverage | Gaps |
|---|---|---|---|---|
| spaces | `/api/spaces` | Spaces, SpaceDetail | ✅ Full | — |
| graphs (via spaces) | `/api/spaces` | Graphs, GraphDetail | ✅ Full | — |
| kgentities | `/api/graphs/kgentities` | KGEntities, KGEntityDetail | ✅ Full | Batch count UI not exposed |
| kgframes | `/api/graphs/kgframes` | KGFrames, KGFrameDetail | ✅ Full | Frame query POST not in UI |
| kgrelations | `/api/graphs/kgrelations` | KGRelations | ✅ Full | Relation query POST not in UI |
| kgtypes | `/api/graphs/kgtypes` | KGTypes, KGTypeDetail | ✅ Full | — |
| kgdocuments | `/api/graphs/kgdocuments` | KGDocuments, KGDocumentDetail | ✅ Full | — |
| objects | `/api/graphs/objects` | GraphObjects, ObjectDetail | ✅ Full | — |
| triples | `/api/graphs/triples` | Triples | ✅ Full | — |
| sparql (query/update) | `/api/graphs/sparql` | SPARQL | ✅ Full | — |
| sparql (graph store) | `/api/graphs/sparql` | — | ❌ None | No SPARQL Graph Store Protocol UI |
| files | `/api/files` | Files, FileDetail, FileUpload | ✅ Full | Streaming upload/download not exposed |
| users | `/api/users` | Users, UserDetail | ✅ Full | — |
| api_keys | `/api/keys` | ApiKeys | ✅ Full | — |
| import | `/api/data/import` | DataImport, DataImportDetail | ✅ Full | — |
| export | `/api/data/export` | DataExport, DataExportDetail | ✅ Full | — |
| kgquery | `/api/graphs/kgqueries` | KGQueryBuilder | ✅ Full | — |
| admin (resync) | `/api/admin` | Admin | ⚠️ Partial | Only resync; no cache/health detail |
| admin (audit) | `/api/admin/audit` | AuditLog | ✅ Full | — |
| entity_registry | `/api/registry` | EntityRegistry, EntityRegistryDetail | ⚠️ Partial | Identifiers, aliases, categories, location types CRUD in API but limited in UI |
| agent_registry | `/api/agents` | AgentRegistry, AgentRegistryDetail | ✅ Full | — |
| search_mappings | `/api/search-mappings` | SearchMappings, SearchMappingDetail, IndexMappings | ✅ Full | — |
| fuzzy_mappings | `/api/fuzzy-mappings` | FuzzyMappings, FuzzyMappingDetail, IndexMappings | ✅ Full | — |
| vector_mappings | `/api/vector-mappings` | IndexMappings | ✅ Full | — |
| vector_indexes | `/api/vector-indexes` | VectorIndexes, VectorIndexDetail | ✅ Full | — |
| fts_indexes | `/api/fts-indexes` | FtsIndexes, FtsIndexDetail, Indexes | ✅ Full | — |
| geo_config | `/api/geo-config` | GeoShapes | ✅ Full | — |
| geo_points | `/api/geo-points` | GeoShapes, SemanticSearch | ✅ Full | — |
| ontology | `/api/ontology` | (used internally by KGTypeDetail) | ⚠️ Indirect | No standalone ontology browser |
| processes | `/api/processes` | Admin (scheduler panel) | ⚠️ Partial | No dedicated process list page |
| metrics | `/api/metrics` | Home (dashboard charts) | ⚠️ Partial | No dedicated metrics page; slow query log not shown |
| metaql_query | — | — | ❌ N/A | Endpoint stubs; no routes registered |
| metaql_update | — | — | ❌ N/A | Endpoint stubs; no routes registered |

### Key Gaps Identified

1. **SPARQL Graph Store Protocol** — Backend supports `GET/PUT/DELETE` on named
   graphs via the graph store endpoint. No UI for this; users must use SPARQL or
   the API directly. Low priority since it is a protocol-level feature.

2. **Entity Registry sub-resources** — Backend provides full CRUD for identifiers,
   aliases, categories, and location types. The UI detail page shows some of these
   but may not expose all operations (e.g., add/remove identifiers, category
   assignment). Worth expanding.

3. **Ontology browser** — The ontology endpoint provides class and property
   introspection. KGTypeDetail uses it internally, but there is no standalone
   ontology explorer page.

4. **Process management** — Backend has process listing, detail, scheduler status,
   and cancel. Only the scheduler panel in Admin surfaces this. A dedicated
   background-process page would improve visibility.

5. **Metrics / slow queries** — Backend provides per-space metrics and a slow-query
   log. Home shows aggregate charts but the slow-query endpoint has no UI.

6. **MetaQL** — Endpoint files exist but have zero routes registered. Not a gap —
   just not implemented yet.

7. **Batch entity counts** — The `POST /kgentities/counts` endpoint allows
   multiple filter combinations in one call. The UI uses individual count calls.
   Not a user-facing gap, but a performance optimization opportunity.

---

## Implementation Progress

### Infrastructure (complete)

| Item | Status |
|------|--------|
| `e2e/` directory with `package.json` and Playwright config | ✅ Done |
| `e2e/playwright.config.ts` — projects, auth setup, global setup/teardown | ✅ Done |
| `e2e/global-setup.ts` — waits for backend health | ✅ Done |
| `e2e/tests/auth.setup.ts` — persists auth state to `.auth/user.json` | ✅ Done |
| `e2e/seed-constants.ts` — shared test data constants | ✅ Done |
| `tests/shared/seed_ui_test_data.py` — deterministic seed script | ✅ Done |
| `docker-compose.test.yml` + `e2e/run-tests.sh` — one-shot test runner | ✅ Done |
| `data-testid` instrumentation — 49/49 routed pages | ✅ Done |
| `data-testid` instrumentation — row/card-level selectors | ✅ Done |

### Test Spec Files (14 files, 91 tests)

| File | Tests | Coverage |
|------|-------|----------|
| `page-navigation.spec.ts` | ~33 (loop-generated) | Smoke: 22 top-level + 2 space + 8 graph + 1 NotFound pages load container |
| `entity-lifecycle.spec.ts` | 2 | CRUD flow through seeded entities; console error check |
| `auth.spec.ts` | 5 | Login form, valid/invalid credentials, protected route redirects |
| `dashboard-spaces.spec.ts` | 9 | Dashboard stats, space cards, navigation; Spaces list+detail; Users list+detail |
| `graphs-objects.spec.ts` | 17 | Graphs list+detail, Objects Layout tabs, KGEntity/Frame/Document detail, Object detail, File detail |
| `kg-objects.spec.ts` | 10 | KG Entities/Frames/Relations/Documents/Types lists with seeded data; KGType detail; Graph Objects; Triples |
| `search-query.spec.ts` | 3 | Semantic Search, Search Result Detail, KG Query Builder |
| `indexes-mappings.spec.ts` | 11 | Indexes tabs, Vector/FTS index detail, Search/Fuzzy mapping detail, GeoShapes |
| `files-triples-sparql.spec.ts` | 6 | Files (graph + standalone), File Upload, Triples, SPARQL |
| `data-import-export.spec.ts` | 4 | Data Import/Export sub-components, import/export detail pages |
| `admin-detail.spec.ts` | 8 | Admin, AuditLog, ApiKeys, EntityRegistry+Detail, AgentRegistry+Detail, UserDetail |
| `admin-pages.spec.ts` | 5 | Admin section pages load |
| `space-graph-navigation.spec.ts` | 4 | Drill-down: Spaces → Space Detail → Graphs → Graph Detail |
| `visualization-layout.spec.ts` | 3 | Graph Visualization, NotFound + back link |

### Page Coverage Summary

- **49 routed pages** — all have at least a smoke test verifying `data-testid` container loads
- **4 unrouted page components** (`VectorIndexes`, `FtsIndexes`, `SearchMappings`, `FuzzyMappings`) — standalone `.tsx` files with `data-testid` but no routes in `App.tsx`; functionality covered by parent pages `Indexes` and `IndexMappings`

### Remaining Work

| Item | Status |
|------|--------|
| Expand seed data (files, indexes, registry entries) for conditional tests | ❌ Pending |
| CRUD write tests (see tracker below) | 🔶 In Progress |
| Error state tests (network mocking for 500/timeout scenarios) | ❌ Pending |
| Run full suite against Docker test stack and fix failures | ✅ Done (132 passing) |
| Visual regression baselines (`toHaveScreenshot`) | ❌ Deferred |
| Accessibility audit (`@axe-core/playwright`) | ❌ Deferred |
| CI integration (GitHub Actions) | ❌ Deferred |
| Multi-browser (Firefox/WebKit) | ❌ Deferred |
| Mobile viewport / responsive layout tests | ❌ Deferred |

### CRUD Write Test Tracker

Each row represents a UI entity with its available CRUD operations and test status.

| Entity | Spec File | Create | Read/List | Update | Delete | Notes |
|--------|-----------|--------|-----------|--------|--------|-------|
| **Spaces** | `spaces-crud.spec.ts` | ✅ | ✅ | ✅ | ✅ | Full lifecycle |
| **Graphs** | `graphs-crud.spec.ts` | ✅ | ✅ | — | ✅ | No update UI (immutable URI) |
| **KG Entities** | `kgentities-crud.spec.ts` | ✅ | ✅ | ✅ | ✅ | Full lifecycle + frontend fixes (listRoute, auto-generate URI) |
| **KG Frames** | `kgframes-crud.spec.ts` | ✅ | ✅ | ✅ | ✅ | Full lifecycle + frontend fix (listRoute) |
| **KG Documents** | — | ❌ | ❌ | — | ❌ | Create via upload; no edit |
| **KG Types** | `kgtypes-crud.spec.ts` | ✅ | ✅ | ✅ | ✅ | Full lifecycle; uses sp_kg_types space |
| **KG Relations** | — | — | ❌ | — | — | Read-only in UI |
| **Graph Objects** | `graph-objects-crud.spec.ts` | ✅ | ✅ | ✅ | ✅ | API-seeded + generic objects UI list/update/delete |
| **API Keys** | `api-keys-crud.spec.ts` | ✅ | ✅ | — | ✅ | Create + list + Revoke |
| **Users** | `users-crud.spec.ts` | ✅ | ✅ | ✅ | ✅ | Full lifecycle + frontend fix (PUT body) |
| **Entity Registry** | `entity-registry-crud.spec.ts` | ✅ | ✅ | ✅ | ✅ | Form-based CRUD; uses /api/registry/entities |
| **Agent Registry** | `agent-registry-crud.spec.ts` | ✅ | ✅ | ✅ | ✅ | Form-based CRUD; unique URI per run (soft-delete) |
| **Search Mappings** | `search-mappings-crud.spec.ts` | ✅ | ✅ | ✅ | ✅ | Via unified IndexMappings page; toggle=update |
| **Fuzzy Mappings** | `fuzzy-mappings-crud.spec.ts` | ✅ | ✅ | ✅ | ✅ | Via unified IndexMappings page; toggle=update |
| **FTS Indexes** | `indexes-crud.spec.ts` | ✅ | ✅ | — | ✅ | Via unified Indexes page |
| **Vector Indexes** | `indexes-crud.spec.ts` | ✅ | ✅ | — | ✅ | Via unified Indexes page |
| **Files** | `files-crud.spec.ts` | ✅ | ✅ | — | ✅ | Streaming round-trip (57B/100KB/1MB) + UI delete; issue 017 complete |

**Legend**: ✅ Done | ❌ Pending | — Not applicable (operation not available in UI)
