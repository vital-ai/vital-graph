# Entity Registry Implementation Plan

## Implementation Status

> **All phases complete. 117/117 endpoint tests passing.**

| Component | Status | Tests |
|-----------|--------|-------|
| Schema & Core (`entity_registry_schema.py`, `entity_registry_id.py`, `entity_registry_impl.py`) | ✅ Complete | 93/93 direct tests passing |
| Pydantic Models (`entity_registry_model.py`) | ✅ Complete | Includes lat/lng, categories, topic search |
| FastAPI Endpoints (`entity_registry_endpoint.py`) | ✅ Complete | Includes geo params, topic search |
| App Integration (`vitalgraphapp_impl.py`) | ✅ Complete | — |
| Client Endpoint (`client/endpoint/entity_registry_endpoint.py`) | ✅ Complete | Includes geo + topic search |
| Client Integration (`VitalGraphClient`) | ✅ Complete | — |
| Near-Duplicate Detection (`entity_dedup.py`) | ✅ Complete | MinHash LSH + RapidFuzz + type_key filter |
| Weaviate Vector Search (`entity_weaviate.py`, `entity_weaviate_schema.py`) | ✅ Complete | Unified search + geo + identifiers |
| Entity Categories (`entity_category` + `entity_category_map` tables) | ✅ Complete | CRUD + category filtering |
| CLI Admin Tool (`entity_admin.py`) | ✅ Complete | stats, dedup, weaviate, search, export, types, migrate |
| Schema Migration (`migrate.py`) | ✅ Complete | Explicit migration script, service never modifies schema |
| Geo Support (lat/lng) | ✅ Complete | PostgreSQL columns + Weaviate geo_location + endpoints |
| Test Data Scripts (`load_test_data.py`, `cleanup_test_data.py`) | ✅ Complete | 8 test entities, manifest-based |
| Endpoint Test Suite (`test_entity_registry_endpoint.py`) | ✅ Complete | 117/117 passing |

### Bugs Found & Fixed During Testing

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| `is_valid_entity_id('e_abc')` returned `True` | No length check on suffix | Added `len(suffix) != DEFAULT_LENGTH` check |
| `asyncpg.DataError` on update/delete | `TIMESTAMP` columns vs timezone-aware `datetime` | Migrated all columns to `TIMESTAMPTZ`, use `datetime.now(timezone.utc)` |
| 500 on changelog endpoint | `change_detail` JSONB returned as string by asyncpg | Added `_parse_row()` to JSON-decode string values |
| DUNS lookup returned wrong entity | `lookup_by_identifier` returned only first match | Changed to return a list (identifiers are not unique across entities) |
| Test flakiness on repeated runs | Hardcoded identifier values collided across runs | Added `run_suffix` for unique values per test run |
| Lat/lng not in GET responses | `_entity_to_response` missing latitude/longitude | Added fields to response builder |
| Identifier add failed after retract | Unique constraint covered retracted rows | Dropped unique constraint — identifiers like DUNS are not unique across entities |
| Weaviate geo coords returned as None | `isinstance(geo_location, dict)` check failed on GeoCoordinate object | Changed to `getattr()` extraction |

---

## Overview

The Entity Registry is a lightweight service for assigning globally unique identifiers to real-world entities (businesses, people, organizations, etc.). It is implemented as a new set of PostgreSQL tables integrated with the existing Fuseki-PostgreSQL hybrid backend, sharing the same `asyncpg` connection pool and transaction infrastructure.

A business uses this service to look up or create a stable ID for an entity like a customer or partner, ensuring consistent identification across systems. The registry stores minimal differentiating information — it is not a general-purpose knowledge base, just enough to disambiguate entities with the same or similar names.

### Entity ID Format

Each entity receives a unique string identifier (e.g., `e_7f3a9b2c`). This string is **not** a URI itself, but can be embedded in one:

```
urn:entity:e_7f3a9b2c
```

ID generation strategy: **prefixed nanoid** — a short, URL-safe, collision-resistant string with an `e_` prefix. Fixed at 10 chars after prefix (36^10 ≈ 3.6 × 10^15 unique values).

---

## Database Schema

All tables live in the same PostgreSQL database used by the Fuseki-PostgreSQL backend. They are **not** per-space; the entity registry is a global service.

### Table 1: `entity_type`

High-level classification of entities.

```sql
CREATE TABLE entity_type (
    type_id SERIAL PRIMARY KEY,
    type_key VARCHAR(50) UNIQUE NOT NULL,       -- e.g. 'business', 'person', 'organization'
    type_label VARCHAR(255) NOT NULL,            -- e.g. 'Business', 'Person'
    type_description TEXT,
    created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Seed data
INSERT INTO entity_type (type_key, type_label, type_description) VALUES
    ('person', 'Person', 'An individual person'),
    ('business', 'Business', 'A business or company'),
    ('organization', 'Organization', 'A non-commercial organization'),
    ('government', 'Government', 'A government body or agency');
```

### Table 2: `entity`

Main entity registry table.

**Status values**: `active`, `inactive`, `merged`, `deleted`. Note: `retracted` is used only on same-as mappings and aliases — it is semantically distinct from `deleted`. An entity marked `deleted` is soft-deleted; it still exists in the database but is excluded from default queries.

```sql
CREATE TABLE entity (
    entity_id VARCHAR(50) PRIMARY KEY,           -- e.g. 'e_7f3a9b2c1d'
    entity_type_id INTEGER NOT NULL REFERENCES entity_type(type_id),
    primary_name VARCHAR(500) NOT NULL,           -- canonical/primary name
    description TEXT,                              -- brief description
    country VARCHAR(100),                          -- country of origin/registration
    region VARCHAR(255),                           -- state/province/region
    locality VARCHAR(255),                         -- city/town
    website VARCHAR(500),                          -- primary website URL
    latitude DOUBLE PRECISION,                     -- geo latitude (WGS84)
    longitude DOUBLE PRECISION,                    -- geo longitude (WGS84)
    status VARCHAR(20) NOT NULL DEFAULT 'active',  -- active, inactive, merged, deleted
    created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(255),                       -- who/what created this entry
    notes TEXT                                     -- free-form notes
);

CREATE INDEX idx_entity_type ON entity(entity_type_id);
CREATE INDEX idx_entity_name ON entity(primary_name);
CREATE INDEX idx_entity_status ON entity(status);
CREATE INDEX idx_entity_country ON entity(country);
CREATE INDEX idx_entity_created ON entity(created_time);
```

### Table 3: `entity_identifier`

Mapped external identifiers. Each entity can have N identifiers across different namespaces (e.g. DUNS number, EIN, internal CRM ID, etc.). This table also supports lookups — find an entity by any of its external identifiers.

Identifiers are **not** held unique — the same DUNS number (or other external ID) can legitimately appear on multiple entities.

```sql
CREATE TABLE entity_identifier (
    identifier_id SERIAL PRIMARY KEY,
    entity_id VARCHAR(50) NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
    identifier_namespace VARCHAR(255) NOT NULL,      -- e.g. 'DUNS', 'EIN', 'CRM', 'SSN-last4'
    identifier_value VARCHAR(500) NOT NULL,           -- the external ID value
    is_primary BOOLEAN DEFAULT FALSE,                 -- whether this is the preferred ID in this namespace
    status VARCHAR(20) NOT NULL DEFAULT 'active',     -- active, inactive, retracted
    created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(255),
    notes TEXT
);

CREATE INDEX idx_identifier_entity ON entity_identifier(entity_id);
CREATE INDEX idx_identifier_namespace ON entity_identifier(identifier_namespace);
CREATE INDEX idx_identifier_value ON entity_identifier(identifier_value);
CREATE INDEX idx_identifier_ns_value ON entity_identifier(identifier_namespace, identifier_value);
```

### Table 4: `entity_alias`

Alternate names: AKA (also known as), DBA (doing business as), former names, abbreviations, etc.

```sql
CREATE TABLE entity_alias (
    alias_id SERIAL PRIMARY KEY,
    entity_id VARCHAR(50) NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
    alias_name VARCHAR(500) NOT NULL,
    alias_type VARCHAR(50) NOT NULL DEFAULT 'aka',  -- aka, dba, former, abbreviation, trade_name
    is_primary BOOLEAN DEFAULT FALSE,                -- whether this is a preferred alias
    status VARCHAR(20) NOT NULL DEFAULT 'active',    -- active, inactive, retracted
    created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(255),
    notes TEXT
);

CREATE INDEX idx_alias_entity ON entity_alias(entity_id);
CREATE INDEX idx_alias_name ON entity_alias(alias_name);
CREATE INDEX idx_alias_type ON entity_alias(alias_type);
```

### Table 5: `entity_same_as`

Maps one entity to another as being "the same" — supports merges, acquisitions, corrections.

```sql
CREATE TABLE entity_same_as (
    same_as_id SERIAL PRIMARY KEY,
    source_entity_id VARCHAR(50) NOT NULL REFERENCES entity(entity_id),
    target_entity_id VARCHAR(50) NOT NULL REFERENCES entity(entity_id),
    relationship_type VARCHAR(50) NOT NULL DEFAULT 'same_as',  -- same_as, merged_into, acquired_by, superseded_by
    status VARCHAR(20) NOT NULL DEFAULT 'active',               -- active, retracted
    confidence FLOAT,                                            -- optional confidence score 0.0-1.0
    reason TEXT,                                                  -- why this mapping was created
    created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    retracted_time TIMESTAMPTZ,                                    -- when retracted, if applicable
    created_by VARCHAR(255),                                     -- who/what created this mapping
    retracted_by VARCHAR(255),                                   -- who/what retracted this mapping
    notes TEXT,

    CONSTRAINT no_self_reference CHECK (source_entity_id != target_entity_id)
);

CREATE INDEX idx_same_as_source ON entity_same_as(source_entity_id);
CREATE INDEX idx_same_as_target ON entity_same_as(target_entity_id);
CREATE INDEX idx_same_as_status ON entity_same_as(status);
```

### Table 6: `entity_change_log`

Audit trail of all changes to the registry.

```sql
CREATE TABLE entity_change_log (
    log_id BIGSERIAL PRIMARY KEY,
    entity_id VARCHAR(50) REFERENCES entity(entity_id) ON DELETE SET NULL,
    change_type VARCHAR(50) NOT NULL,  -- entity_created, entity_updated, entity_deleted,
                                       -- alias_added, alias_retracted,
                                       -- identifier_added, identifier_retracted,
                                       -- same_as_created, same_as_retracted,
                                       -- status_changed
    change_detail JSONB,               -- structured details of the change
    changed_by VARCHAR(255),           -- who/what made the change (optional)
    comment TEXT,                       -- explanation (optional)
    created_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_changelog_entity ON entity_change_log(entity_id);
CREATE INDEX idx_changelog_type ON entity_change_log(change_type);
CREATE INDEX idx_changelog_time ON entity_change_log(created_time);
CREATE INDEX idx_changelog_changed_by ON entity_change_log(changed_by);
```

---

## Implementation Architecture

### Integration with Existing Backend

- **Connection Pool**: Reuse the existing `asyncpg` pool from `FusekiPostgreSQLDbImpl`. The `entity_registry_impl.py` receives the pool reference at initialization, same pattern as other fuseki-postgresql components.
- **Schema Setup**: `entity_registry_schema.py` follows the pattern of `postgresql_schema.py`. Tables are created during app startup via `FusekiPostgreSQLDbImpl.initialize()` or a dedicated `ensure_registry_tables()` call.
- **Transactions**: Uses `asyncpg` transactions directly (same as `FusekiPostgreSQLTransaction` pattern).

### ID Generation

```python
# entity_registry_id.py
import secrets
import string

ALPHABET = string.ascii_lowercase + string.digits  # a-z, 0-9
DEFAULT_LENGTH = 10  # 10 chars after prefix → 36^10 ≈ 3.6 × 10^15 possibilities

def generate_entity_id(length: int = DEFAULT_LENGTH) -> str:
    """Generate a unique entity ID like 'e_a7b3x9k2m1'."""
    suffix = ''.join(secrets.choice(ALPHABET) for _ in range(length))
    return f"e_{suffix}"

def entity_id_to_uri(entity_id: str) -> str:
    """Convert entity ID to URN format."""
    return f"urn:entity:{entity_id}"
```

Collision handling: On the rare chance of a duplicate, the insert will fail (PK constraint) and we retry with a new ID. At 10 chars with base-36, this is astronomically unlikely.

---

## Core Operations (`entity_registry_impl.py`)

### Entity CRUD

| Method | Description |
|--------|-------------|
| `create_entity(type_key, primary_name, ...)` | Create entity, generate ID, log change |
| `get_entity(entity_id)` | Get entity by ID |
| `get_entity_by_uri(uri)` | Extract ID from `urn:entity:<id>` and fetch |
| `update_entity(entity_id, ...)` | Update entity fields, log change |
| `delete_entity(entity_id)` | Soft-delete (set status='deleted'), log change |
| `search_entities(query, type_key, ...)` | Search by name (ILIKE), type, country, etc. |
| `list_entities(type_key, status, page, page_size)` | Paginated listing with filters |

### Identifier Operations

| Method | Description |
|--------|-------------|
| `add_identifier(entity_id, namespace, value)` | Add mapped identifier, log change |
| `remove_identifier(identifier_id)` | Soft-remove (retract) identifier, log change |
| `list_identifiers(entity_id)` | List all identifiers for entity |
| `lookup_by_identifier(namespace, value)` | Find entities by external identifier (returns list — identifiers are not unique across entities) |
| `lookup_by_identifier_value(value)` | Find entities by identifier value (any namespace) |

### Alias Operations

| Method | Description |
|--------|-------------|
| `add_alias(entity_id, alias_name, alias_type)` | Add AKA/DBA, log change |
| `remove_alias(alias_id)` | Soft-remove (retract) alias, log change |
| `list_aliases(entity_id)` | List all aliases for entity |
| `search_by_alias(query)` | Search entities via alias names (ILIKE) |

### Same-As Operations

| Method | Description |
|--------|-------------|
| `create_same_as(source_id, target_id, relationship_type, ...)` | Create mapping, log change |
| `retract_same_as(same_as_id, retracted_by, reason)` | Set status=retracted, log change |
| `get_same_as(entity_id)` | Get all active same-as mappings for entity |
| `resolve_entity(entity_id)` | Follow transitive same-as chain to canonical entity (A→B→C returns C) |

### Change Log

| Method | Description |
|--------|-------------|
| `get_change_log(entity_id, ...)` | Get change history for entity |
| `get_recent_changes(limit, change_type)` | Recent changes across all entities |

---

## REST API Endpoints

Base path: `/api/registry`

### Entity Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/entities` | Create a new entity |
| `GET` | `/entities/get?entity_id=X` | Get entity by ID |
| `GET` | `/entities` | List/search entities (query params for filtering) |
| `PUT` | `/entities/update?entity_id=X` | Update entity |
| `DELETE` | `/entities/delete?entity_id=X` | Soft-delete entity |

### Identifier Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/identifiers/add?entity_id=X` | Add identifier |
| `GET` | `/identifiers/list?entity_id=X` | List identifiers for entity |
| `DELETE` | `/identifiers/remove?identifier_id=X` | Retract identifier |
| `GET` | `/identifiers/lookup?namespace=X&value=Y` | Lookup entities by identifier. Returns a list |

### Alias Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/aliases/add?entity_id=X` | Add alias |
| `GET` | `/aliases/list?entity_id=X` | List aliases |
| `DELETE` | `/aliases/remove?alias_id=X` | Retract alias |

### Same-As Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/sameas` | Create same-as mapping |
| `GET` | `/sameas/list?entity_id=X` | Get same-as mappings for entity |
| `PUT` | `/sameas/retract?same_as_id=X` | Retract a same-as mapping |
| `GET` | `/sameas/resolve?entity_id=X` | Resolve entity to canonical ID |

### Entity Type Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/entity/types` | List all entity types |
| `POST` | `/entity/types` | Create custom entity type |

### Change Log Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/changelog/entity?entity_id=X` | Get change log for entity |
| `GET` | `/changelog` | Get recent changes (global) |

---

## Pydantic Models (`entity_registry_model.py`)

### Request Models

```python
class EntityCreateRequest(BaseModel):
    type_key: str                                   # e.g. 'business'
    primary_name: str
    description: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    locality: Optional[str] = None
    website: Optional[str] = None
    latitude: Optional[float] = None                # geo latitude (WGS84)
    longitude: Optional[float] = None               # geo longitude (WGS84)
    created_by: Optional[str] = None
    notes: Optional[str] = None
    aliases: Optional[List[AliasCreateRequest]] = None        # create with initial aliases
    identifiers: Optional[List[IdentifierCreateRequest]] = None  # create with initial identifiers

class EntityUpdateRequest(BaseModel):
    primary_name: Optional[str] = None
    description: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    locality: Optional[str] = None
    website: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    status: Optional[str] = None
    updated_by: Optional[str] = None
    notes: Optional[str] = None

class IdentifierCreateRequest(BaseModel):
    identifier_namespace: str                        # e.g. 'DUNS', 'EIN', 'CRM'
    identifier_value: str
    is_primary: bool = False
    created_by: Optional[str] = None
    notes: Optional[str] = None

class AliasCreateRequest(BaseModel):
    alias_name: str
    alias_type: str = 'aka'                         # aka, dba, former, abbreviation, trade_name
    is_primary: bool = False
    created_by: Optional[str] = None
    notes: Optional[str] = None

class SameAsCreateRequest(BaseModel):
    source_entity_id: str
    target_entity_id: str
    relationship_type: str = 'same_as'              # same_as, merged_into, acquired_by, superseded_by
    confidence: Optional[float] = None
    reason: Optional[str] = None
    created_by: Optional[str] = None
    notes: Optional[str] = None

class SameAsRetractRequest(BaseModel):
    retracted_by: Optional[str] = None
    reason: Optional[str] = None

class EntitySearchRequest(BaseModel):
    query: Optional[str] = None                     # text search on name/aliases
    type_key: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    status: Optional[str] = 'active'
    page: int = 1
    page_size: int = 20
```

### Response Models

```python
class IdentifierResponse(BaseModel):
    identifier_id: int
    entity_id: str
    identifier_namespace: str
    identifier_value: str
    is_primary: bool
    status: str
    created_time: datetime

class EntityResponse(BaseModel):
    entity_id: str
    entity_uri: str                                 # urn:entity:<entity_id>
    type_key: str
    type_label: str
    primary_name: str
    description: Optional[str]
    country: Optional[str]
    region: Optional[str]
    locality: Optional[str]
    website: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    status: str
    created_time: datetime
    updated_time: datetime
    created_by: Optional[str]
    notes: Optional[str]
    identifiers: Optional[List[IdentifierResponse]] = None  # included when fetching single entity
    aliases: Optional[List[AliasResponse]] = None            # included when fetching single entity

class EntityCreateResponse(BaseModel):
    success: bool
    entity_id: str
    entity_uri: str
    entity: EntityResponse

class EntityListResponse(BaseModel):
    success: bool
    entities: List[EntityResponse]
    total_count: int
    page: int
    page_size: int

class AliasResponse(BaseModel):
    alias_id: int
    entity_id: str
    alias_name: str
    alias_type: str
    is_primary: bool
    status: str
    created_time: datetime

class SameAsResponse(BaseModel):
    same_as_id: int
    source_entity_id: str
    target_entity_id: str
    relationship_type: str
    status: str
    confidence: Optional[float]
    reason: Optional[str]
    created_time: datetime
    retracted_time: Optional[datetime]

class ChangeLogEntry(BaseModel):
    log_id: int
    entity_id: Optional[str]
    change_type: str
    change_detail: Optional[dict]
    changed_by: Optional[str]
    comment: Optional[str]
    created_time: datetime

class ChangeLogResponse(BaseModel):
    success: bool
    entries: List[ChangeLogEntry]
    total_count: int
```

---

## Client Updates

### New Client Endpoint Class

`vitalgraph/client/endpoint/entity_registry_endpoint.py` — follows the same pattern as `spaces_endpoint.py`, `objects_endpoint.py`, etc.

```python
class EntityRegistryEndpoint(BaseEndpoint):
    """Client endpoint for Entity Registry operations."""

    # Entity CRUD
    def create_entity(self, request: EntityCreateRequest) -> EntityCreateResponse
    def get_entity(self, entity_id: str) -> EntityResponse
    def search_entities(self, **kwargs) -> EntityListResponse
    def update_entity(self, entity_id: str, request: EntityUpdateRequest) -> EntityResponse
    def delete_entity(self, entity_id: str) -> dict

    # Identifiers
    def add_identifier(self, entity_id: str, request: IdentifierCreateRequest) -> IdentifierResponse
    def list_identifiers(self, entity_id: str) -> List[IdentifierResponse]
    def remove_identifier(self, identifier_id: int) -> dict
    def lookup_by_identifier(self, namespace: str, value: str) -> List[EntityResponse]

    # Aliases
    def add_alias(self, entity_id: str, request: AliasCreateRequest) -> AliasResponse
    def list_aliases(self, entity_id: str) -> List[AliasResponse]
    def remove_alias(self, alias_id: int) -> dict

    # Same-as
    def create_same_as(self, request: SameAsCreateRequest) -> SameAsResponse
    def get_same_as(self, entity_id: str) -> List[SameAsResponse]
    def retract_same_as(self, same_as_id: int, request: SameAsRetractRequest) -> SameAsResponse
    def resolve_entity(self, entity_id: str) -> EntityResponse

    # Entity types
    def list_entity_types(self) -> List[EntityTypeResponse]

    # Change log
    def get_entity_changelog(self, entity_id: str, ...) -> ChangeLogResponse
```

### VitalGraphClient Integration

Add `entity_registry` property to `VitalGraphClient` and `VitalGraphClientInterface` that returns the `EntityRegistryEndpoint` instance, following the existing pattern for `spaces`, `objects`, `kgentities`, etc.

---

## Test Plan

### 1. Direct Registry Tests (`test_scripts/entity_registry/`)

Tests that hit the `entity_registry_impl.py` directly using an asyncpg pool (no REST layer).

| Test File | Coverage |
|-----------|----------|
| `test_entity_crud.py` | Create, get, update, soft-delete, search entities |
| `test_identifier_operations.py` | Add/remove/lookup identifiers, multi-namespace, lookup-by-value |
| `test_alias_operations.py` | Add/retract aliases, search by alias, DBA/AKA types |
| `test_same_as_operations.py` | Create/retract same-as, transitive resolution, cycle prevention |
| `test_change_log.py` | Verify log entries for all operations, filtering |
| `test_id_generation.py` | ID format, uniqueness, URI conversion |
| `test_search.py` | ILIKE search, multi-field filtering, pagination |

### 2. Endpoint Tests via Client (`vitalgraph_client_test/`)

Tests that use `VitalGraphClient` to hit the REST endpoints on a running server.

| Test File | Coverage |
|-----------|----------|
| `test_entity_registry_endpoint.py` | Full CRUD via REST, alias endpoints, same-as endpoints, changelog |
| `test_entity_registry_search.py` | Search and pagination via REST |
| `test_entity_registry_errors.py` | Invalid inputs, not-found, conflict scenarios |

---

## Implementation Phases

### Phase 1: Schema & Core (Foundation) — ✅ Complete
1. ✅ Create `entity_registry_schema.py` with all table DDL (migrated to `TIMESTAMPTZ`)
2. ✅ Create `entity_registry_id.py` with ID generation (fixed length validation)
3. ✅ Create `entity_registry_impl.py` with entity CRUD + alias + same-as + changelog
4. ✅ Integrate schema creation into app startup
5. ✅ Write direct tests — 93/93 passing across 7 test files

### Phase 2: REST Endpoints — ✅ Complete
1. ✅ Create `entity_registry_model.py` with Pydantic models
2. ✅ Create `entity_registry_endpoint.py` with FastAPI handlers
3. ✅ Register routes in `vitalgraphapp_impl.py`
4. ✅ Tested via client test suite

### Phase 3: Client & Client Tests — ✅ Complete
1. ✅ Create client `entity_registry_endpoint.py`
2. ✅ Add `entity_registry` property to `VitalGraphClient`
3. ✅ Write client test scripts — 42/42 passing
4. ✅ Full round-trip validated

### Phase 4: Polish — ✅ Complete
1. ✅ Same-as cycle prevention (detect A→B→C→A before insertion)
2. ✅ Duplicate name detection via MinHash LSH + RapidFuzz (see Phase 5)
3. ✅ Documentation: `docs/entity_registry.md` + updated `entity_registry/README.md`

### Phase 5: Near-Duplicate Detection — ✅ Complete
1. ✅ `entity_dedup.py` — MinHash LSH for candidate blocking, RapidFuzz for precise scoring
2. ✅ In-memory and Redis storage backends
3. ✅ `find_similar` endpoint — search by name with optional location filters
4. ✅ Score detail with ratio, token_sort, partial, weighted components, match_level (high/likely/possible)

### Phase 6: Entity Categories — ✅ Complete
1. ✅ `entity_category` and `entity_category_map` tables
2. ✅ CRUD endpoints for category assignment/removal
3. ✅ Seed categories: customer, vendor, partner, competitor, prospect, investor, regulator
4. ✅ List entities by category

### Phase 7: Weaviate Vector Search — ✅ Complete
1. ✅ `entity_weaviate.py` + `entity_weaviate_schema.py` — collection schema, upsert, delete, search
2. ✅ Topic search via `near_text` with type/country/region/category filters
3. ✅ Geo-range filtering using Weaviate `within_geo_range` on `geoCoordinates`
4. ✅ Full sync from PostgreSQL via admin CLI
5. ✅ Hybrid search (BM25 + vector) support
6. ✅ `/search/topic` REST endpoint + client method

### Phase 8: Geo Support & Schema Migration — ✅ Complete
1. ✅ `latitude`/`longitude` columns on `entity` table
2. ✅ Weaviate `geo_location` property with geoCoordinates type
3. ✅ `migrate.py` — standalone migration script (create, index, seed, alter)
4. ✅ Service never modifies schema at startup — read-only table check only
5. ✅ `entity_admin.py` CLI with migrate, stats, dedup, weaviate, search, export, types commands

### Phase 9: Test Refactoring — ✅ Complete
1. ✅ `load_test_data.py` — creates 8 test entities (4 persons, 4 businesses) with geo, aliases, identifiers
2. ✅ `cleanup_test_data.py` — hard-deletes test data via direct SQL
3. ✅ `test_data_manifest.json` — shared entity IDs across loader, tests, and cleanup
4. ✅ `test_entity_registry_endpoint.py` — 117/117 tests covering all endpoints

### Phase 10: Route Renames & Search Consolidation — ✅ Complete
1. ✅ Renamed `/entity-registry` → `/registry` (base path)
2. ✅ Renamed `/same-as` → `/sameas`, `/entity-types` → `/entity/types`, `/location-types` → `/location/types`, `/relationship-types` → `/relationship/types`
3. ✅ Consolidated `/search/topic`, `/search/topic-near`, `/search/entities-near` → `/search/entity`
4. ✅ Renamed `/search/locations-near` → `/search/location`
5. ✅ Updated client SDK and tests for all renames

### Phase 11: Enhanced Search — ✅ Complete
1. ✅ Added `type_key` filter to `/search/similar` (MinHash dedup index stores type_key, post-retrieval filter)
2. ✅ Added identifier search to `/search/entity` (native Weaviate filtering)
3. ✅ Added `identifier_keys` (TEXT_ARRAY, `namespace:value` composites) and `identifier_values` (TEXT_ARRAY) to Weaviate EntityIndex schema
4. ✅ Enriched full_sync with `_enrich_with_identifiers` to populate identifier fields
5. ✅ Single-entity upsert (`_weaviate_upsert_entity`) also fetches identifiers
6. ✅ All search methods (`search_topic`, `search_topic_near`, `search_entities_near`) accept `identifier_value`/`identifier_namespace` params
7. ✅ `weaviate rebuild` admin command (drop + recreate + full sync)

### Phase 12: Weaviate Auth Fix — ✅ Complete
1. ✅ Added `offline_access` to Keycloak scope to obtain refresh tokens
2. ✅ Pass `refresh_token` and `expires_in` to `Auth.bearer_token()` for auto-refresh
3. ✅ Confirmed token refresh works past 60s expiry
4. ✅ `test_weaviate_direct.py` — 9/9 direct Weaviate query tests

---

## Resolved Design Decisions

| Decision | Resolution |
|----------|------------|
| **ID length** | 10 chars (base-36), ~3.6×10^15 values |
| **Deletion semantics** | Soft-delete only. `deleted` is a terminal status on entities. `retracted` is a distinct status used on aliases, identifiers, and same-as mappings (reversible withdrawal, not destruction) |
| **Same-as resolution** | Transitive. `resolve_entity(A)` follows A→B→C and returns C. Cycle prevention required at insertion time |
| **Authentication** | Same JWT auth as the rest of the VitalGraph API |
| **Scope** | Global registry across all spaces — not per-space or per-tenant |
| **External identifiers** | Separate `entity_identifier` table, no unique constraint — same DUNS/EIN can map to multiple entities. Supports lookup-by-identifier returning a list |
| **Search** | ILIKE for PostgreSQL text search; Weaviate `near_text` for semantic/topic search; MinHash LSH + RapidFuzz for dedup |
| **Geo support** | PostgreSQL `latitude`/`longitude` columns + Weaviate `geo_location` geoCoordinates for range filtering |
| **Schema migration** | Explicit `migrate.py` script — the running service never alters the database schema |
| **Change log retention** | Retained forever. No archival or pruning policy |

---

## Source Files

```
vitalgraph/
  entity_registry/
    __init__.py
    entity_registry_schema.py        # table DDL, indexes, seed data, migrations
    entity_registry_impl.py          # core registry operations (async, asyncpg)
    entity_registry_id.py            # ID generation logic
    entity_dedup.py                  # MinHash LSH + RapidFuzz dedup
    entity_weaviate.py               # Weaviate integration (search, sync)
    entity_weaviate_schema.py        # Weaviate collection schema + helpers
  endpoint/
    entity_registry_endpoint.py      # FastAPI REST endpoint handlers
  model/
    entity_registry_model.py         # Pydantic request/response models
  client/
    endpoint/
      entity_registry_endpoint.py    # client-side endpoint class

entity_registry/
  entity_admin.py                    # CLI admin tool
  migrate.py                         # standalone schema migration script

vitalgraph_client_test/
  load_test_data.py                  # creates test entities + manifest
  cleanup_test_data.py               # hard-deletes test data via SQL
  test_entity_registry_endpoint.py   # 117/117 endpoint tests
  test_weaviate_direct.py            # 9/9 direct Weaviate query tests
  test_data_manifest.json            # entity IDs shared across scripts

test_scripts/entity_registry/
  test_entity_weaviate.py            # direct Weaviate integration tests
```
