# Space Analytics Feature Plan

## Overview

Add two complementary sub-endpoints under `/api/spaces`:

1. **`/info?space_id=...`** — lightweight, real-time basic stats (already partially exists)
2. **`/analytics?space_id=...`** — richer KG-level analytics, computed periodically (~once/day)

> **API Consistency Policy (June 2026)**: All REST endpoints use static URL paths with query parameters only — no dynamic path segments (`{param}`). See `planning_client/client_api_sync_plan.md §7`.

Both feed a redesigned Space Detail UI that surfaces useful data at a glance.

---

## 1. Current State

### Backend

| Component | Status |
|-----------|--------|
| `GET /api/spaces/info?space_id=...` route | Exists in `spaces_endpoint.py` |
| `SpaceInfoResponse` model | Exists — returns `space`, `statistics` (dict), `quad_dump` |
| `SpaceManager.get_space_info()` | Delegates to backend `.get_space_info()` |
| `sparql_sql` backend `get_space_info()` | Returns `quad_count`, `term_count`, list of graph records |
| `fuseki_postgresql` backend `get_space_info()` | Returns metadata, Fuseki dataset info, consistency check, per-graph stats — **not active** |
| `fuseki` backend `get_space_info()` | Returns space_id, name, created_date, is_active — **not active** |
| `GET /api/spaces/analytics?space_id=...` route | ✓ Done |
| Analytics computation/storage | ✓ Done — `SpaceAnalyticsJob` runs via ProcessScheduler; results stored in PostgreSQL |
| ProcessScheduler infrastructure | **Exists** — periodic job runner with PostgreSQL advisory locks for distributed leader election across instances |
| ProcessLockManager | **Exists** — advisory lock acquire/release; ensures only one instance runs a job |
| MaintenanceJob | **Exists** — concrete example: registered at 5 min interval, uses `trigger_now()` for on-demand; pattern to follow exactly |
| `trigger_now()` support | **Exists** — scheduler can run any registered job on-demand with lock gating |

### Frontend

| Component | Status |
|-----------|--------|
| `SpaceDetail.tsx` | ✓ Done — shows info, metrics, and analytics tabs; delegates to `vgClient` |
| `SpaceMetrics.tsx` | ✓ Done — query metrics dashboard with time-range selector |
| `SpaceAnalytics.tsx` | ✓ Done — KG analytics display (entity types, relations, temporal) |
| `SpaceOverview.tsx` | ✓ Done — summary cards for quick stats |

---

## 2. Info Endpoint — Complete the Basics

The `/info` endpoint should return fast, real-time (no caching) stats. Current `sparql_sql` implementation already has `quad_count` and `term_count`. Gaps:

### 2.1 Data to Add (all backends)

| Field | Description | SQL (sparql_sql) |
|-------|-------------|------------------|
| `total_quad_count` | Total RDF quads in space | `SELECT COUNT(*) FROM {space}_rdf_quad` (exists) |
| `total_term_count` | Total unique terms | `SELECT COUNT(*) FROM {space}_term` (exists) |
| `graph_count` | Number of named graphs | `SELECT COUNT(*) FROM graph WHERE space_id = $1` |
| `graphs` | Per-graph summary (uri, name, quad_count) | Exists partially |
| `unique_subject_count` | Distinct subjects | `SELECT COUNT(DISTINCT subject_uuid) FROM {space}_rdf_quad` |
| `unique_predicate_count` | Distinct predicates | `SELECT COUNT(DISTINCT predicate_uuid) FROM {space}_rdf_quad` |
| `created_time` | Space creation timestamp | From `space` admin table |
| `last_modified_time` | Space last update timestamp | From `space.update_time` |
| `storage_size_bytes` | Approximate table sizes | `pg_total_relation_size()` |

### 2.2 Response Model Update

```python
class SpaceInfoResponse(BaseOperationResponse):
    space: Optional[Space] = None
    info: Optional[SpaceInfoData] = None  # new structured model

class SpaceInfoData(BaseModel):
    total_quad_count: int = 0
    total_term_count: int = 0
    graph_count: int = 0
    unique_subject_count: int = 0
    unique_predicate_count: int = 0
    created_time: Optional[str] = None
    last_modified_time: Optional[str] = None
    storage_size_bytes: Optional[int] = None
    graphs: List[GraphSummary] = []

class GraphSummary(BaseModel):
    graph_uri: str
    graph_name: Optional[str] = None
    quad_count: int = 0
```

### 2.3 Implementation Tasks

- [ ] Add missing columns to `sparql_sql` `get_space_info()` (unique subjects/predicates, storage size)
- [ ] Normalize return format across all backends to match `SpaceInfoData`
- [ ] Update `SpaceInfoResponse` model (keep backward compat)
- [ ] Add `created_time` / `update_time` from space admin table
- [ ] Remove `quad_dump` from the public response (debug-only, move to separate debug endpoint)

> **Status**: Info endpoint exists and returns basic stats. Extended fields above are future enhancements.

---

## 3. Analytics Endpoint — New Feature

### 3.1 Analytics Data Design

The analytics endpoint returns pre-computed KG-aware statistics. More expensive queries that don't need to run in real-time.

#### A. Entity Analytics

| Metric | Description |
|--------|-------------|
| `total_entity_count` | Total KGEntity instances |
| `entity_type_distribution` | Count per vitaltype URI (e.g., KGNewsEntity: 50, KGProductEntity: 120) |
| `entities_with_frames_count` | Entities that have at least one frame |
| `orphan_entity_count` | Entities with no frames attached |
| `avg_frames_per_entity` | Average frame count per entity |

#### B. Frame Analytics

| Metric | Description |
|--------|-------------|
| `total_frame_count` | Total KGFrame instances |
| `frame_type_distribution` | Count per frame vitaltype |
| `total_slot_count` | Total KGSlot instances (all types) |
| `slot_type_distribution` | Count per slot vitaltype (KGTextSlot, KGDoubleSlot, etc.) |
| `avg_slots_per_frame` | Average slot count per frame |
| `frames_without_slots_count` | Frames that have no slots |

#### C. Relation Analytics

| Metric | Description |
|--------|-------------|
| `total_edge_count` | Total edge instances |
| `edge_type_distribution` | Count per edge vitaltype (Edge_hasKGRelation, Edge_hasEntityKGFrame, etc.) |
| `inter_entity_relation_count` | Edges between entities (Edge_hasKGRelation) |
| `entity_frame_edge_count` | Entity-to-frame edges (Edge_hasEntityKGFrame) |
| `frame_slot_edge_count` | Frame-to-slot edges (Edge_hasKGSlot) |
| `most_connected_entities` | Top N entities by edge count (in + out) |

#### D. Property Analytics

| Metric | Description |
|--------|-------------|
| `distinct_predicate_count` | Number of distinct predicates used |
| `top_predicates` | Top N predicates by usage frequency |
| `literal_type_distribution` | Count by datatype (xsd:string, xsd:integer, etc.) |

#### E. Temporal Analytics

| Metric | Description |
|--------|-------------|
| `last_analytics_run` | Timestamp of last computation |
| `data_age_summary` | Oldest/newest entity creation dates if available |

### 3.2 Response Model

```python
class SpaceAnalyticsResponse(BaseOperationResponse):
    space_id: str
    computed_at: str  # ISO timestamp
    stale: bool = False  # True if data is older than threshold
    entity_analytics: Optional[EntityAnalytics] = None
    frame_analytics: Optional[FrameAnalytics] = None
    relation_analytics: Optional[RelationAnalytics] = None
    property_analytics: Optional[PropertyAnalytics] = None

class EntityAnalytics(BaseModel):
    total_count: int = 0
    type_distribution: List[TypeCount] = []  # [{type_uri, type_name, count}]
    with_frames_count: int = 0
    orphan_count: int = 0
    avg_frames_per_entity: float = 0.0

class FrameAnalytics(BaseModel):
    total_count: int = 0
    type_distribution: List[TypeCount] = []
    total_slot_count: int = 0
    slot_type_distribution: List[TypeCount] = []
    avg_slots_per_frame: float = 0.0
    without_slots_count: int = 0

class RelationAnalytics(BaseModel):
    total_edge_count: int = 0
    edge_type_distribution: List[TypeCount] = []
    inter_entity_relation_count: int = 0
    entity_frame_edge_count: int = 0
    frame_slot_edge_count: int = 0
    most_connected_entities: List[ConnectedEntity] = []  # [{uri, name, edge_count}]

class PropertyAnalytics(BaseModel):
    distinct_predicate_count: int = 0
    top_predicates: List[PredicateCount] = []  # [{uri, short_name, count}]
    literal_type_distribution: List[TypeCount] = []

class TypeCount(BaseModel):
    type_uri: str
    type_name: str  # short/display name
    count: int

class ConnectedEntity(BaseModel):
    entity_uri: str
    entity_name: Optional[str] = None
    edge_count: int

class PredicateCount(BaseModel):
    predicate_uri: str
    short_name: str
    count: int
```

### 3.3 Storage

**Separate `space_analytics` admin table** — one row per computation cycle, enabling historical tracking:

```sql
CREATE TABLE IF NOT EXISTS space_analytics (
    id SERIAL PRIMARY KEY,
    space_id VARCHAR(255) NOT NULL REFERENCES space(space_id) ON DELETE CASCADE,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    computation_time_ms INTEGER,
    analytics_json JSONB NOT NULL,
    CONSTRAINT idx_space_analytics_space_time UNIQUE (space_id, computed_at)
);

CREATE INDEX idx_space_analytics_space_id ON space_analytics (space_id);
CREATE INDEX idx_space_analytics_latest ON space_analytics (space_id, computed_at DESC);
```

Read latest:
```sql
SELECT analytics_json, computed_at, computation_time_ms
FROM space_analytics
WHERE space_id = $1
ORDER BY computed_at DESC
LIMIT 1
```

Write (after each computation cycle):
```sql
INSERT INTO space_analytics (space_id, computed_at, computation_time_ms, analytics_json)
VALUES ($1, NOW(), $2, $3)
```

**Benefits of per-cycle history:**
- Track how the space evolves over time (entity growth, new types appearing, etc.)
- UI can show trends (e.g., "entity count grew 20% this week")
- Easier debugging if analytics seem wrong — can compare to previous runs

#### Computation Job

Create `AnalyticsJob` following the `MaintenanceJob` pattern:

```python
class AnalyticsJob:
    """Computes KG analytics for all spaces periodically."""
    
    async def run(self):
        """Compute analytics for all spaces."""
        spaces = await self._list_spaces()
        for space_id in spaces:
            await self._compute_space_analytics(space_id)
    
    async def trigger_compute(self, space_id: str):
        """On-demand computation for a single space."""
        await self._compute_space_analytics(space_id)
```

Register with ProcessScheduler:
```python
scheduler.register_job(
    name="space_analytics",
    interval_seconds=86400,  # 24 hours
    handler=analytics_job,
    process_type="analytics",
)
```

#### SQL Queries for Analytics (sparql_sql backend)

**Entity type distribution:**
```sql
SELECT o_term.term_text AS type_uri, COUNT(DISTINCT q.subject_uuid) AS cnt
FROM {space}_rdf_quad q
JOIN {space}_term p_term ON q.predicate_uuid = p_term.term_uuid
JOIN {space}_term o_term ON q.object_uuid = o_term.term_uuid
WHERE p_term.term_text = 'http://vital.ai/ontology/vital-core#vitaltype'
  AND o_term.term_text LIKE '%KG%Entity%'
GROUP BY o_term.term_text
ORDER BY cnt DESC
```

**Edge type distribution:**
```sql
SELECT o_term.term_text AS type_uri, COUNT(DISTINCT q.subject_uuid) AS cnt
FROM {space}_rdf_quad q
JOIN {space}_term p_term ON q.predicate_uuid = p_term.term_uuid
JOIN {space}_term o_term ON q.object_uuid = o_term.term_uuid
WHERE p_term.term_text = 'http://vital.ai/ontology/vital-core#vitaltype'
  AND o_term.term_text LIKE '%Edge_%'
GROUP BY o_term.term_text
ORDER BY cnt DESC
```

**Entities with frames (via Edge_hasEntityKGFrame):**
```sql
SELECT COUNT(DISTINCT src_term.term_text) AS entities_with_frames
FROM {space}_rdf_quad type_q
JOIN {space}_term type_p ON type_q.predicate_uuid = type_p.term_uuid
JOIN {space}_term type_o ON type_q.object_uuid = type_o.term_uuid
JOIN {space}_rdf_quad src_q ON type_q.subject_uuid = src_q.subject_uuid
JOIN {space}_term src_p ON src_q.predicate_uuid = src_p.term_uuid
JOIN {space}_term src_term ON src_q.object_uuid = src_term.term_uuid
WHERE type_p.term_text = 'http://vital.ai/ontology/vital-core#vitaltype'
  AND type_o.term_text = 'http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame'
  AND src_p.term_text = 'http://vital.ai/ontology/vital-core#hasEdgeSource'
```

**Top predicates:**
```sql
SELECT p_term.term_text AS predicate_uri, COUNT(*) AS cnt
FROM {space}_rdf_quad q
JOIN {space}_term p_term ON q.predicate_uuid = p_term.term_uuid
GROUP BY p_term.term_text
ORDER BY cnt DESC
LIMIT 20
```

### 3.4 Endpoint Design

```
GET /api/spaces/analytics?space_id=...
    Query params:
        space_id: str (required)
        refresh: bool = false  (force recomputation)
        graph_uri: str (optional, filter analytics to specific graph)
    
    Response: SpaceAnalyticsResponse
        - If cached analytics exist and are < 24h old → return cached
        - If stale or missing → return cached (if any) with stale=true
        - If refresh=true → recompute synchronously and return fresh data
```

### 3.5 Implementation Tasks

- [x] Create `SpaceAnalyticsResponse` and sub-models in `vitalgraph/model/spaces_model.py`
- [x] Add `space_analytics` table to admin DDL in `sparql_sql_schema.py`
- [x] Create `vitalgraph/process/analytics_job.py` with SQL computation logic
- [x] Implement all analytics SQL queries (entity, frame, relation, property categories)
- [x] Register analytics job with ProcessScheduler (24h interval) in `vitalgraphapp_impl.py`
- [x] Add `GET /api/spaces/analytics?space_id=...` route to `spaces_endpoint.py`
- [x] Add `refresh` trigger support (on-demand via ProcessScheduler.trigger_now)
- [x] Handle empty/new spaces gracefully (return zero counts, analytics_json = NULL)

---

## 4. UI Design

### 4.1 Space Detail Page Redesign

The current `SpaceDetail.tsx` shows only name/description. Redesign with tabbed layout:

```
┌──────────────────────────────────────────────────────┐
│ Space: My Knowledge Base                    [Edit] [Delete] │
├──────────────────────────────────────────────────────┤
│ [Overview]  [Analytics]  [Settings]                         │
├──────────────────────────────────────────────────────┤
│                                                             │
│  OVERVIEW TAB:                                              │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐      │
│  │  12,450 │  │   3,200 │  │      5  │  │  1.2 MB │      │
│  │  Triples│  │  Terms  │  │  Graphs │  │  Size   │      │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘      │
│                                                             │
│  Graphs:                                                    │
│  ┌─────────────────────────────────────────────────┐       │
│  │ Graph URI               │ Quads  │ Subjects     │       │
│  │ urn:graph/main           │  8,200 │      420     │       │
│  │ urn:graph/entities       │  4,250 │      180     │       │
│  └─────────────────────────────────────────────────┘       │
│                                                             │
│  Created: 2025-01-22  │  Last Modified: 2025-06-05         │
│                                                             │
│  ANALYTICS TAB:                                             │
│  ┌─────────────────────────────────────────────────┐       │
│  │ Entity Type Distribution              [Refresh] │       │
│  │ ─────────────────────────────────────           │       │
│  │ KGNewsEntity         ████████████  350          │       │
│  │ KGProductEntity      ██████       180          │       │
│  │ KGWebEntity          ████         120          │       │
│  └─────────────────────────────────────────────────┘       │
│                                                             │
│  ┌────────────────────┐  ┌────────────────────┐           │
│  │ Frames & Slots     │  │ Relations          │           │
│  │ 850 frames         │  │ 1,200 edges        │           │
│  │ 2,400 slots        │  │ 450 inter-entity   │           │
│  │ 2.8 avg slots/frame│  │ 850 entity→frame   │           │
│  └────────────────────┘  └────────────────────┘           │
│                                                             │
│  ┌─────────────────────────────────────────────────┐       │
│  │ Edge Type Distribution                          │       │
│  │ Edge_hasEntityKGFrame    ██████████  850         │       │
│  │ Edge_hasKGRelation       █████      450         │       │
│  │ Edge_hasKGSlot           ██████████████  2,400  │       │
│  └─────────────────────────────────────────────────┘       │
│                                                             │
│  ┌─────────────────────────────────────────────────┐       │
│  │ Top Predicates                                  │       │
│  │ vitaltype                    ████████████  4,200 │       │
│  │ hasEdgeSource                ██████       1,200 │       │
│  │ hasName                      █████        980   │       │
│  └─────────────────────────────────────────────────┘       │
│                                                             │
│  Last computed: 2025-06-05 03:00 UTC                        │
│                                                             │
│  SETTINGS TAB:                                              │
│  (Space name, description, identifier — existing edit form) │
└──────────────────────────────────────────────────────┘
```

### 4.2 UI Choices/Controls to Expose

| Control | Purpose |
|---------|---------|
| **Refresh Analytics** button | Triggers on-demand recomputation (`?refresh=true`) |
| **Tab selector** (Overview / Analytics / Settings) | Organize different information levels |
| **Time range indicator** | Show when analytics were last computed + staleness warning |
| **Graph filter** (dropdown) | Filter analytics to specific graph (future enhancement) |
| **Export** button | Download analytics as JSON (future enhancement) |

### 4.3 Frontend Implementation Tasks

- [x] Refactor `SpaceDetail.tsx` into tabbed layout (Settings / Analytics / Metrics)
- [x] Create `SpaceOverview` component — stat cards from `/info` endpoint
- [x] Create `SpaceAnalytics` component — ApexCharts bar/donut charts from `/analytics`
- [x] Move edit/delete form into Settings tab
- [x] Add loading/stale states for analytics data
- [x] Add Refresh button with loading indicator
- [x] Create chart components (ApexCharts horizontal bar + donut charts)
- [x] Add API service methods for info and analytics endpoints
- [x] Handle empty spaces gracefully (no data yet messaging)
- [x] Create `SpaceMetrics` component — time-series charts from `/metrics` (query tracking)
- [x] Add Metrics tab with ApexCharts area/line charts + slow query table

---

## 5. Implementation Phases

### Phase 1: Info Endpoint Completion — Mostly Complete
1. ✓ Normalize `get_space_info()` across backends (basic version exists)
2. ✓ Update response model
3. Add missing metrics (unique subjects/predicates, storage size) — **TODO** (enhancement)
4. ✓ Build Overview tab in UI (`SpaceOverview.tsx`)

### Phase 2: Analytics Computation — COMPLETE ✓
1. ✓ Create `space_analytics` table
2. ✓ Implement `AnalyticsJob` with entity/frame/relation/property queries
3. ✓ Register with ProcessScheduler
4. ✓ Add manual trigger support

### Phase 3: Analytics Endpoint & UI — COMPLETE ✓
1. ✓ Add `/analytics` route
2. ✓ Implement caching/staleness logic
3. ✓ Build Analytics tab with ApexCharts distribution charts
4. ✓ Add refresh control

### Phase 3b: Query Tracking & Metrics — COMPLETE ✓
1. ✓ PostgreSQL metrics collector (`vitalgraph/metrics/postgres_metrics_collector.py`) — replaced Redis-based collector
2. ✓ FastAPI middleware for request timing (`vitalgraph/metrics/metrics_middleware.py`) — static paths, query-param space_id
3. ✓ Hourly rollup job in PostgreSQL (`vitalgraph/process/metrics_rollup_job.py`) — no Redis dependency
4. ✓ API endpoints for metrics + slow queries (`vitalgraph/endpoint/metrics_endpoint.py`) — `GET /api/metrics?space_id=...`
5. ✓ Frontend Metrics tab with time-series charts (`frontend/src/components/SpaceMetrics.tsx`)
6. ✓ Frontend ApiService delegates to TS client (`vgClient.metrics.*`)

See: `planning_space_analytics/query_tracking_plan.md` and `metrics_postgres_migration_plan.md` for full details.

### Phase 4: Polish — MOSTLY COMPLETE
1. ✓ Add graph-level filtering to analytics (dropdown → `graph_uri` query param → filtered SQL)
2. ✓ Improve chart visualizations (gradient fills, animations, data labels, donut totals, truncated labels)
3. Add export functionality — **SKIPPED** (per user request)
4. ✓ Performance tuning for large spaces (60s statement_timeout, LIMIT 50 on all aggregation queries)
5. ✓ Build dedicated Overview tab (stat cards from `/info`)

**Verification**: Frontend compiles cleanly (`npx tsc --noEmit` — 0 errors). Python parses cleanly (`ast.parse` — 0 errors).

---

## 6. Open Questions

1. **Scope of analytics per-graph vs per-space?** — Start with per-space (across all graphs); add optional graph filter later.
2. **Should analytics be graph-aware?** — Yes for type distributions (filter by graph), but totals are space-wide.
3. **What about the existing `GraphAnalysis.tsx`?** — Merge concept into space-level analytics or keep as separate graph drill-down?
4. **Computation timeout for huge spaces?** — Add configurable timeout; partial results with error flag.
5. **How many "most connected entities" to show?** — Start with top 10.
6. **Should we show property-level stats per entity type?** — Defer to Phase 4; useful but complex.
7. **Multi-tenant considerations?** — Analytics table needs tenant column if multi-tenant.

---

## 7. File Locations

| New/Modified | Path | Status |
|--------------|------|--------|
| Analytics models | `vitalgraph/model/spaces_model.py` | ✓ |
| Analytics job | `vitalgraph/process/analytics_job.py` | ✓ |
| Metrics rollup job | `vitalgraph/process/metrics_rollup_job.py` | ✓ (PG-only, no Redis) |
| PG metrics collector | `vitalgraph/metrics/postgres_metrics_collector.py` | ✓ |
| Legacy Redis collector | `vitalgraph/metrics/query_metrics.py` | Legacy — no longer instantiated |
| Metrics middleware | `vitalgraph/metrics/metrics_middleware.py` | ✓ (static paths) |
| Metrics endpoint | `vitalgraph/endpoint/metrics_endpoint.py` | ✓ (`/api/metrics?space_id=...`) |
| Scheduler registration | `vitalgraph/impl/vitalgraphapp_impl.py` | ✓ |
| Spaces endpoint update | `vitalgraph/endpoint/spaces_endpoint.py` | ✓ (query-param routes) |
| Schema (admin tables) | `vitalgraph/db/sparql_sql/sparql_sql_schema.py` | ✓ |
| Space impl (read/write) | `vitalgraph/db/sparql_sql/sparql_sql_space_impl.py` | ✓ |
| Frontend overview | `frontend/src/components/SpaceOverview.tsx` | ✓ |
| Frontend analytics | `frontend/src/components/SpaceAnalytics.tsx` | ✓ |
| Frontend metrics | `frontend/src/components/SpaceMetrics.tsx` | ✓ |
| Frontend detail refactor | `frontend/src/pages/SpaceDetail.tsx` | ✓ |
| API service | `frontend/src/services/ApiService.ts` | ✓ (delegates to TS client `vgClient.*`) |
| TS client | `vitalgraph-client-ts/src/endpoint/` | ✓ (26 endpoint classes, query-param routes) |
| Python client | `vitalgraph/client/endpoint/` | ✓ (25 endpoint classes, query-param routes) |
