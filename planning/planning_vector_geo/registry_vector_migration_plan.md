# Entity Registry & Agent Registry — Vector/Geo Migration Plan

## 1. Problem Statement

The entity registry and agent registry use **dedicated relational tables** (not
per-space quad tables) to store their data. Vector search and geo search for the
entity registry currently depend on **Weaviate** (`entity_weaviate.py`,
`entity_weaviate_schema.py`, etc.). This Weaviate dependency must be removed and
replaced with **PostgreSQL pgvector/PostGIS** — using the same table patterns as
the per-space `vector_index`, `search_mapping`, `fts_index`, and `geo` tables.

The entity registry CLI (`vitalgraph_entity_registry_cmd.py`) currently has
vector/geo commands that assume data lives in per-space quad tables (the
`--space <space_id>` pattern). This is **incorrect** — the registries use their
own tables and need their own vector/geo infrastructure.

---

## 2. Current Architecture

### 2.1 Entity Registry Tables (global, not per-space)

```
entity              — core entity (entity_id PK, primary_name, description, latitude, longitude, ...)
entity_type         — entity type catalog
entity_identifier   — external identifiers (namespace:value)
entity_alias        — alternative names
entity_same_as      — same-as / merge relationships
entity_location     — entity locations (location_id, entity_id FK, latitude, longitude, ...)
entity_location_type— location type catalog
entity_category_map — entity ↔ category junction
entity_relationship — entity ↔ entity relationships
entity_change_log   — audit log
entity_fuzzy_band   — fuzzy matching bands
category            — category catalog
relationship_type   — relationship type catalog
```

### 2.2 Agent Registry Tables (global, not per-space)

```
agent               — core agent (agent_id PK, agent_name, agent_uri, description, ...)
agent_type          — agent type catalog
agent_endpoint      — agent endpoints (endpoint_uri, endpoint_url, protocol)
agent_function      — agent functions/capabilities
agent_change_log    — audit log
```

### 2.3 Weaviate Usage (entity registry only)

`EntityWeaviateIndex` class provides:

| Method | Description |
|--------|-------------|
| `search_topic(query, type_key, ...)` | Vector similarity on entity search text |
| `search_hybrid(query, alpha, ...)` | Hybrid BM25 + vector |
| `search_by_identifier(value, ns)` | Filter by identifier |
| `search_locations_near(lat, lon, radius_km)` | Geo-radius on locations |
| `search_topic_near(query, lat, lon, radius_km)` | Combined vector + geo |
| `search_entities_near(lat, lon, radius_km)` | Entities near a point (via locations) |

Weaviate collections:
- **EntityIndex**: vectorized entity text (name, description, type, categories, aliases)
- **LocationIndex**: vectorized location text + geo coordinates + cross-ref to entity

---

## 3. Target Architecture

### 3.1 Principle

- Entity and agent registries **keep their dedicated relational tables**.
- Vector, FTS, and geo search are provided by **new companion tables** that
  follow the same schema patterns as per-space tables.
- These companion tables are **global** (not per-space, since registries are global).
- The naming convention uses a registry prefix instead of a space_id prefix.

### 3.2 New Tables — Entity Registry

```sql
-- Vector index registry (same schema as {space}_vector_index)
CREATE TABLE IF NOT EXISTS entity_registry_vector_index (
    index_id        SERIAL PRIMARY KEY,
    index_name      VARCHAR(255) NOT NULL UNIQUE,
    dimensions      INT NOT NULL,
    distance_metric VARCHAR(20) NOT NULL DEFAULT 'cosine',
    provider        VARCHAR(100),
    provider_config JSONB DEFAULT '{}',
    model_name      VARCHAR(255),
    description     TEXT,
    created_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Vector data table (same schema as {space}_vec_{index_name})
CREATE TABLE IF NOT EXISTS entity_registry_vec_entity (
    id              BIGSERIAL PRIMARY KEY,
    subject_uuid    UUID NOT NULL,
    context_uuid    UUID,
    embedding       vector(384),     -- MiniLM default; column type set at creation
    search_text     TEXT,
    created_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (subject_uuid)
);
CREATE INDEX ON entity_registry_vec_entity USING hnsw (embedding vector_cosine_ops);

-- Location vector table (locations have separate embeddings)
CREATE TABLE IF NOT EXISTS entity_registry_vec_location (
    id              BIGSERIAL PRIMARY KEY,
    subject_uuid    UUID NOT NULL,
    context_uuid    UUID,
    embedding       vector(384),
    search_text     TEXT,
    created_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (subject_uuid)
);
CREATE INDEX ON entity_registry_vec_location USING hnsw (embedding vector_cosine_ops);

-- Geo table (same schema as {space}_geo)
CREATE TABLE IF NOT EXISTS entity_registry_geo (
    id              BIGSERIAL PRIMARY KEY,
    subject_uuid    UUID NOT NULL,
    predicate_uuid  UUID,
    latitude        DOUBLE PRECISION NOT NULL,
    longitude       DOUBLE PRECISION NOT NULL,
    location        geography(Point, 4326) NOT NULL,
    context_uuid    UUID,
    created_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (subject_uuid, context_uuid)
);
CREATE INDEX ON entity_registry_geo USING gist (location);

-- FTS data table (same pattern as {space}_fts_{index_name})
CREATE TABLE IF NOT EXISTS entity_registry_fts_entity (
    id              BIGSERIAL PRIMARY KEY,
    subject_uuid    UUID NOT NULL UNIQUE,
    search_text     TEXT NOT NULL,
    ts_vector       tsvector GENERATED ALWAYS AS (to_tsvector('english', search_text)) STORED,
    updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ON entity_registry_fts_entity USING gin (ts_vector);

-- No search_mapping table needed — text construction is hardcoded
-- (the fields to include are well-known and fixed for registries)
```

### 3.3 New Tables — Agent Registry

```sql
-- Vector index for agents
CREATE TABLE IF NOT EXISTS agent_registry_vector_index (
    index_id        SERIAL PRIMARY KEY,
    index_name      VARCHAR(255) NOT NULL UNIQUE,
    dimensions      INT NOT NULL,
    distance_metric VARCHAR(20) NOT NULL DEFAULT 'cosine',
    provider        VARCHAR(100),
    provider_config JSONB DEFAULT '{}',
    model_name      VARCHAR(255),
    description     TEXT,
    created_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Vector data table for agents
CREATE TABLE IF NOT EXISTS agent_registry_vec_agent (
    id              BIGSERIAL PRIMARY KEY,
    subject_uuid    UUID NOT NULL UNIQUE,
    embedding       vector(384),
    search_text     TEXT,
    created_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ON agent_registry_vec_agent USING hnsw (embedding vector_cosine_ops);

-- FTS for agents
CREATE TABLE IF NOT EXISTS agent_registry_fts_agent (
    id              BIGSERIAL PRIMARY KEY,
    subject_uuid    UUID NOT NULL UNIQUE,
    search_text     TEXT NOT NULL,
    ts_vector       tsvector GENERATED ALWAYS AS (to_tsvector('english', search_text)) STORED,
    updated_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ON agent_registry_fts_agent USING gin (ts_vector);
```

### 3.4 UUID Mapping

Entities and agents use string IDs (e.g., `ENT-0001`, `AGT-0001`). The vector/geo
tables use UUIDs. Mapping:

```python
import uuid
NAMESPACE = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')

def entity_id_to_uuid(entity_id: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"vitalgraph:entity:{entity_id}")

def location_id_to_uuid(location_id: int) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"vitalgraph:location:{location_id}")

def agent_id_to_uuid(agent_id: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"vitalgraph:agent:{agent_id}")
```

This matches the existing `entity_id_to_weaviate_uuid` pattern in
`entity_weaviate_schema.py` for backward-compatible deterministic IDs.

---

## 4. Search Text Construction

### 4.1 Entity Search Text (replaces `build_search_text()`)

Keep the same composite text strategy from `entity_weaviate_schema.py`:

```
"{primary_name}. {type_label}: {type_description}. {description}.
 Categories: {category_labels}. {locality}, {region}, {country}.
 Aliases: {aliases}. Locations: {location_summaries}"
```

### 4.2 Location Search Text (replaces `build_location_search_text()`)

```
"{location_name}. {location_type_label}. {description}. {formatted_address}"
```

### 4.3 Agent Search Text (new)

```
"{agent_name}. {agent_type_label}: {type_description}. {description}.
 Functions: {function_names}. Capabilities: {capabilities}"
```

---

## 5. Implementation Plan

### Phase 1: Schema & Migration Script

| Task | File | Status |
|------|------|--------|
| Create `entity_registry_vector_schema.py` with DDL for all entity registry vector/FTS/geo tables | `vitalgraph/entity_registry/entity_registry_vector_schema.py` | TODO |
| Create `agent_registry_vector_schema.py` with DDL for agent registry vector/FTS tables | `vitalgraph/agent_registry/agent_registry_vector_schema.py` | TODO |
| Create migration script for entity registry vector tables | `entity_registry/migrate_entity_vectors.py` | TODO |
| Create migration script for agent registry vector tables | `agent_registry/migrate_agent_vectors.py` | TODO |

### Phase 2: Populator — Entity Registry

Replace the Weaviate sync with a PostgreSQL populator that reads from the
entity registry's dedicated tables and populates the new vector/FTS/geo tables.

| Task | File | Status |
|------|------|--------|
| Create `EntityRegistryVectorPopulator` class | `vitalgraph/entity_registry/entity_registry_vector_populator.py` | TODO |
| Build search text from entity + joins (aliases, categories, locations) | Same file | TODO |
| Vectorize with VitalSigns ONNX model (same as per-space populator) | Same file | TODO |
| Populate `entity_registry_vec_entity` (full rebuild + incremental) | Same file | TODO |
| Populate `entity_registry_vec_location` (full rebuild + incremental) | Same file | TODO |
| Populate `entity_registry_geo` from `entity.latitude/longitude` + `entity_location.latitude/longitude` | Same file | TODO |
| Populate `entity_registry_fts_entity` (search_text → tsvector) | Same file | TODO |
| Hook into entity CRUD ops for auto-sync on insert/update/delete | `entity_registry_impl.py` | TODO |

### Phase 3: Populator — Agent Registry

| Task | File | Status |
|------|------|--------|
| Create `AgentRegistryVectorPopulator` class | `vitalgraph/agent_registry/agent_registry_vector_populator.py` | TODO |
| Build search text from agent + joins (functions, endpoints) | Same file | TODO |
| Populate `agent_registry_vec_agent` and `agent_registry_fts_agent` | Same file | TODO |
| Hook into agent CRUD ops for auto-sync | `agent_registry_impl.py` | TODO |

### Phase 4: Search Implementation

Replace the Weaviate search methods with PostgreSQL equivalents.

| Task | Details | Status |
|------|---------|--------|
| `search_topic(query)` → pgvector cosine similarity on `entity_registry_vec_entity` | Vector embed query, ORDER BY embedding <=> query_vec | TODO |
| `search_hybrid(query, alpha)` → weighted BM25 + vector | Combine ts_rank from FTS table + cosine from vec table | TODO |
| `search_locations_near(lat, lon, radius_km)` → PostGIS `ST_DWithin` on `entity_registry_geo` | Same pattern as per-space geo endpoint | TODO |
| `search_topic_near(query, lat, lon, radius_km)` → vector + geo combined | JOIN vec similarity with geo radius filter | TODO |
| `search_entities_near(lat, lon, radius_km)` → entities via location geo | JOIN entity_registry_geo → entity_location → entity | TODO |
| Agent search: vector similarity + FTS hybrid on `agent_registry_vec_agent` | Same pattern as entity | TODO |

### Phase 5: REST API Endpoint Migration

Existing search endpoints in `vitalgraph/endpoint/entity_registry_endpoint.py`
already expose the correct routes. They must be rewired from Weaviate to the
new PostgreSQL implementation:

| Existing Route | Current Backend | New Backend | Status |
|----------------|----------------|-------------|--------|
| `GET /search/entity?q=&lat=&lon=&radius_km=` | `entity_weaviate.search_topic` / `search_topic_near` / `search_entities_near` | `EntityRegistrySearch` (pgvector + PostGIS) | ✅ Done |
| `GET /search/location?lat=&lon=&radius_km=&q=` | `entity_weaviate.search_locations_near` | `EntityRegistrySearch.search_locations_near` (PostGIS + pgvector + FTS) | ✅ Done |
| `GET /search/similar?name=` | Fuzzy index (already PG-based) | No change needed | ✅ |
| `GET /entities?query=` | SQL ILIKE | No change needed | ✅ |

**Implementation details (Jun 14, 2026):**
- Added `search` property to `EntityRegistryEndpoint` (lazy-cached `EntityRegistrySearch` instance using `self.registry.pool`)
- `/search/entity` now dispatches to `search.search_topic()`, `search.search_topic_near()`, `search.search_entities_near()`, or `search.search_by_identifier()` based on query params
- `/search/location` now dispatches to `search.search_locations_near()` (extended to support all filter params: address BM25, geo radius, semantic q, property filters)
- Fixed `conn` scope bug in `search_topic_near()` (location enrichment was outside `async with` block)
- Weaviate admin rebuild section preserved for Phase 7

New endpoints needed:

| Task | Route | Status |
|------|-------|--------|
| Agent search endpoint | `GET /api/agent-registry/search?q=` | TODO |
| Entity vector rebuild trigger | `POST /api/entity-registry/vectors/rebuild` | TODO |
| Agent vector rebuild trigger | `POST /api/agent-registry/vectors/rebuild` | TODO |

### Phase 6: CLI Fixes

The entity registry CLI vector/geo commands must be rewritten to work with the
**dedicated registry tables** instead of the per-space `--space` pattern.

| Task | Status |
|------|--------|
| Remove `--space` requirement from registry vector commands | TODO |
| `vector-status` → query `entity_registry_vector_index` + `entity_registry_vec_*` | TODO |
| `vector-check` → compare `entity` row count vs `entity_registry_vec_entity` count | TODO |
| `vector-rebuild` → call `EntityRegistryVectorPopulator.full_rebuild()` | TODO |
| `geo-populate` → populate `entity_registry_geo` from entity + location tables | TODO |
| `geo-check` → compare entities/locations with lat/lon vs geo table count | TODO |

### Phase 7: Weaviate Removal

| Task | Status |
|------|--------|
| Delete `vitalgraph/entity_registry/entity_weaviate.py` | TODO |
| Delete `vitalgraph/entity_registry/entity_weaviate_schema.py` | TODO |
| Delete `vitalgraph/entity_registry/entity_weaviate_ops.py` | TODO |
| Remove Weaviate imports/usage from `entity_registry_impl.py` | TODO |
| Remove Weaviate imports/usage from `entity_location_ops.py` | TODO |
| Remove Weaviate imports/usage from `entity_alias_ops.py` | TODO |
| Remove Weaviate imports/usage from `entity_category_ops.py` | TODO |
| Refactor `entity_vectorizer.py` — keep text building, remove Weaviate specifics | TODO |
| Delete `entity_registry/weaviate_sync.py` | TODO |
| Delete `entity_registry/weaviate_admin.py` | TODO |
| Remove all `WEAVIATE_*` / `ENTITY_WEAVIATE_*` environment variables | TODO |
| Remove Weaviate from Docker Compose / ECS | TODO |
| Remove Weaviate Keycloak client | TODO |

---

## 6. Key Design Decisions

1. **Dedicated tables, not pseudo-spaces**: The registries do NOT use per-space
   quad tables. Their vector/FTS/geo tables are global and prefixed with
   `entity_registry_` or `agent_registry_`.

2. **Same table schemas**: The vector/geo/FTS table schemas are **identical** to
   the per-space equivalents — same columns, same index types. This means the
   same vectorization code (`vital-model-paraphrase-MiniLM-onnx`) and PostGIS
   functions work for both.

3. **Source data is relational**: The populator reads from relational tables (with
   JOINs for aliases, categories, locations) rather than from quads. The `search_text`
   column stores the composite text for vectorization — same role as in per-space
   vector tables.

4. **Auto-sync on CRUD**: When an entity or agent is created/updated/deleted, the
   corresponding vector/FTS/geo rows are updated immediately (same pattern as the
   per-space `auto_sync.py`).

5. **Geo is PostGIS-native**: Uses `geography(Point, 4326)` column with
   `ST_DWithin()` for radius queries — same as per-space geo tables. Populated
   directly from `latitude`/`longitude` columns on `entity` and `entity_location`.

6. **Backward compatibility**: The deterministic UUID generation matches the
   existing Weaviate pattern, so any external systems referencing UUIDs will
   continue to work.

---

## 7. Dependencies & Order

```
Phase 1 (schema)
    ↓
Phase 2 (entity populator)  +  Phase 3 (agent populator)
    ↓                              ↓
Phase 4 (search implementation)
    ↓
Phase 5 (REST endpoints)
    ↓
Phase 6 (CLI fixes)
    ↓
Phase 7 (Weaviate removal)
```

Phases 2 and 3 can proceed in parallel. Phase 7 can only begin once phases 4–6
are complete and verified.

---

## 8. Resolved Decisions

| Question | Decision |
|----------|----------|
| Entity registry search endpoint | **Exists** — `GET /search/entity` and `GET /search/location` in `entity_registry_endpoint.py`. Just rewire from Weaviate to PG. |
| Agent registry — vector search needed? | **Yes** — agent registry gets vector + FTS search |
| Embedding model | **Same 384-dim MiniLM** — VitalSigns ONNX model (same as per-space) |
| Search mapping configurability | **Hardcoded** — fields to include are well-known; no `search_mapping` table for registries |
| Entity registry CLI | **Fix it** — rewrite vector/geo commands to use registry-prefixed tables |
| Geo scope | **Both** — index `entity.latitude/longitude` AND each `entity_location.latitude/longitude` |

---

## 9. Testing

| Test | Validates |
|------|-----------|
| Full rebuild populator → verify vec table row count matches entity count | Population correctness |
| Insert entity → verify auto-sync creates vec + fts + geo rows | CRUD hooks |
| Update entity name → verify search_text + embedding updated | Incremental sync |
| Delete entity → verify vec + fts + geo rows removed | Cascade cleanup |
| `search_topic("renewable energy")` → returns matching entities | Vector search |
| `search_hybrid("pizza restaurant", alpha=0.5)` → relevant entities | Hybrid search |
| `search_locations_near(40.75, -73.98, 5)` → NYC entities | Geo search |
| `search_topic_near("museum", 51.5, -0.12, 10)` → London museums | Combined |
| Agent search → returns matching agents by description | Agent vector search |
| CLI `vector-status` → shows correct counts | CLI correctness |
| CLI `vector-rebuild` → populates from scratch | CLI rebuild |
