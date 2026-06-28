# Entity Registry

The Entity Registry is a global service for assigning stable, unique identifiers to real-world entities (businesses, people, organizations, etc.) and managing their metadata, relationships, and external identifiers. It is integrated with the VitalGraph backend, sharing the same PostgreSQL connection pool and JWT authentication.

## Quick Start

### 1. Schema Setup

The Entity Registry schema is managed by an explicit migration script. The running service **never** modifies the database schema.

```bash
# Full setup: create tables, indexes, seed data, and apply migrations
python entity_registry/migrate.py

# Preview what would run
python entity_registry/migrate.py --dry-run

# Only run ALTER TABLE migrations (skip table creation)
python entity_registry/migrate.py --migrate-only
```

### 2. Load Test Data

```bash
python vitalgraph_client_test/load_test_data.py
```

Creates 10 test entities (5 persons, 5 businesses) with full addresses, geo coordinates, aliases, identifiers, metadata, locations, and relationships. Writes a manifest file (`test_data_manifest.json`) used by the test suite.

### 3. Run Tests

```bash
# Endpoint tests (requires running server)
python vitalgraph_client_test/test_entity_registry_endpoint.py

# Direct Weaviate integration tests
python test_scripts/entity_registry/test_entity_weaviate.py

# Weaviate LocationIndex + cross-reference tests (isolated collections)
ENTITY_WEAVIATE_ENABLED=true python test_scripts/entity_registry/test_entity_weaviate_location.py
```

### 4. Clean Up Test Data

```bash
python vitalgraph_client_test/cleanup_test_data.py
```

---

## Entity ID Format

Each entity receives a unique string identifier: `e_` prefix + 10 alphanumeric characters (base-36).

```
e_7f3a9b2c1d
```

Embeddable as a URN: `urn:entity:e_7f3a9b2c1d`

Collision probability is negligible (36^10 ≈ 3.6 × 10^15 unique values).

---

## REST API

Base path: `/api/registry`

### Entities

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/entities` | Create entity (with optional aliases, identifiers, locations, metadata) |
| `GET` | `/entities/get?entity_id=X` | Get entity by ID (includes identifiers, aliases, locations, relationships) |
| `GET` | `/entities` | List/search entities (query params for filtering) |
| `PUT` | `/entities/update?entity_id=X` | Update entity fields |
| `DELETE` | `/entities/delete?entity_id=X` | Soft-delete entity |

### Identifiers

External IDs (DUNS, EIN, CRM IDs, etc.) mapped to entities. Not held unique — the same external ID can map to multiple entities.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/identifiers/add?entity_id=X` | Add identifier |
| `GET` | `/identifiers/list?entity_id=X` | List identifiers |
| `DELETE` | `/identifiers/remove?identifier_id=X` | Retract identifier |
| `GET` | `/identifiers/lookup?namespace=X&value=Y` | Lookup entities by identifier |

### Aliases

Alternate names: AKA, DBA, former names, abbreviations, trade names.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/aliases/add?entity_id=X` | Add alias |
| `GET` | `/aliases/list?entity_id=X` | List aliases |
| `DELETE` | `/aliases/remove?alias_id=X` | Retract alias |

### Categories

Categories are a shared concept used by both entities and locations. Common tags include customer, vendor, partner, headquarters, branch, etc.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/categories/assign?entity_id=X` | Assign category |
| `GET` | `/categories/entity?entity_id=X` | List entity's categories |
| `DELETE` | `/categories/remove?entity_id=X&category_key=Y` | Remove category |
| `GET` | `/categories` | List all available categories |
| `POST` | `/categories` | Create a new category |
| `GET` | `/categories/entities?category_key=X` | List entities in a category |

### Location Types

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/location/types` | List all location types |
| `POST` | `/location/types` | Create a new location type |

### Locations

Structured, typed locations attached to entities. Each location has detailed address fields, geo coordinates, temporal validity (`effective_from`/`effective_to`), and can be tagged with categories.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/locations/add?entity_id=X` | Add a location to an entity |
| `GET` | `/locations/get?location_id=X` | Get location by ID (includes type + categories) |
| `GET` | `/locations/list?entity_id=X` | List locations for entity (optionally include expired) |
| `PUT` | `/locations/update?location_id=X` | Update location fields |
| `DELETE` | `/locations/remove?location_id=X` | Soft-remove a location |

### Location Categories

Locations can be tagged with the same shared categories used by entities.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/locations/categories/assign?location_id=X` | Assign category to a location |
| `GET` | `/locations/categories/list?location_id=X` | List location's categories |
| `DELETE` | `/locations/categories/remove?location_id=X&category_key=Y` | Remove category from location |

### Relationship Types

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/relationship/types` | List all relationship types |
| `POST` | `/relationship/types` | Create a new relationship type (with optional `inverse_key`) |

### Relationships

Typed, directed relationships between entities with optional temporal validity (`start_datetime`/`end_datetime`). The `entity_relationship_view` computes an `is_current` flag automatically.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/relationships` | Create a relationship between two entities |
| `GET` | `/relationships/get?relationship_id=X` | Get relationship by ID (includes type info) |
| `GET` | `/relationships/list?entity_id=X` | List relationships (filter by `direction`: outgoing/incoming/both) |
| `PUT` | `/relationships/update?relationship_id=X` | Update relationship fields |
| `DELETE` | `/relationships/remove?relationship_id=X` | Retract a relationship |

### Same-As Mappings

Link entities as duplicates, merges, or acquisitions. Supports transitive resolution.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/sameas` | Create same-as mapping |
| `GET` | `/sameas/list?entity_id=X` | Get mappings for entity |
| `PUT` | `/sameas/retract?same_as_id=X` | Retract a mapping |
| `GET` | `/sameas/resolve?entity_id=X` | Resolve to canonical entity (follows A→B→C) |

### Entity Types

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/entity/types` | List all entity types |
| `POST` | `/entity/types` | Create custom entity type |

Seed types: `person`, `business`, `organization`, `government`, `nonprofit`, `educational`, `media`, `religious`, `political`, `military`, `sports`, `other`.

### Change Log

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/changelog/entity?entity_id=X` | Entity change history |
| `GET` | `/changelog` | Recent changes (global) |

### Search

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/entities` | PostgreSQL text search (ILIKE on name/aliases) |
| `GET` | `/search/similar` | Near-duplicate detection (MinHash LSH + RapidFuzz). Supports `type_key` filter |
| `GET` | `/search/entity` | Unified entity search: semantic (q), geo (lat/lon/radius), identifier, or combinations |
| `GET` | `/search/location` | Find locations within a radius of a lat/long point |

---

## Search Capabilities

### Text Search (PostgreSQL)

Simple `ILIKE` search on `primary_name` and aliases. Supports filtering by `type_key`, `country`, `region`, `status`, with pagination.

```
GET /api/registry/entities?query=Acme&type_key=business&country=US
```

### Near-Duplicate Detection (MinHash LSH + RapidFuzz)

Finds entities with similar names. Returns candidates with match scores and confidence levels.

```
GET /api/registry/search/similar?name=Acme+Corporation&min_score=60&type_key=business
```

Response includes per-candidate:
- **score**: weighted combination of ratio, token_sort, and partial match (0-100)
- **match_level**: `high` (≥90), `likely` (≥80), `possible` (≥60)
- **score_detail**: breakdown of individual scoring components
- **type_key**: entity type of the candidate

Supports optional filters: `country`, `region`, `locality`, `type_key`.

### Unified Entity Search (`/search/entity`)

A single endpoint for semantic, geo, identifier, and combined searches. All modes go through Weaviate natively.

**Semantic search:**

```
GET /api/registry/search/entity?q=plumbing+contractor&type_key=business&min_certainty=0.7
```

**Filters**: `type_key`, `category_key`, `country`, `region`, `locality`

**Geo-range filter** (combined with semantic):

```
GET /api/registry/search/entity?q=manufacturing&latitude=37.78&longitude=-122.42&radius_km=10
```

**Geo-only** (no semantic query):

```
GET /api/registry/search/entity?latitude=37.78&longitude=-122.42&radius_km=10&type_key=business
```

**Identifier search** (find entities by external ID):

```
GET /api/registry/search/entity?identifier_value=DUNS-123&identifier_namespace=DUNS
GET /api/registry/search/entity?identifier_value=DUNS-123  # cross-namespace
```

Identifiers are stored in Weaviate as composite `namespace:value` keys (`identifier_keys` TEXT_ARRAY) and value-only strings (`identifier_values` TEXT_ARRAY), enabling native Weaviate filtering via `contains_any`.

**Combined modes**: Any combination of `q`, geo params, and `identifier_value` can be used together. Results are filtered by all provided criteria.

### Location Search (`/search/location`)

Geo queries on the `LocationIndex` Weaviate collection with optional semantic and keyword search.

**Geo only:**
```
GET /api/registry/search/location?latitude=37.78&longitude=-122.42&radius_km=10
    &location_type_key=headquarters&country_code=US
```

**Semantic search** (near_text on location name + description):
```
GET /api/registry/search/location?latitude=37.78&longitude=-122.42&radius_km=50
    &q=distribution+center
```

**Address keyword search** (BM25 on address_line_1 + address_line_2):
```
GET /api/registry/search/location?latitude=37.78&longitude=-122.42&radius_km=10
    &address=Market+Street
```

| Param | Required | Description |
|-------|----------|-------------|
| `latitude` | yes | Center latitude (-90 to 90) |
| `longitude` | yes | Center longitude (-180 to 180) |
| `radius_km` | yes | Search radius in kilometers |
| `q` | no | Semantic search on location name/description (near_text) |
| `address` | no | Keyword search on address_line_1/address_line_2 (BM25) |
| `location_type_key` | no | Filter by location type (e.g. `headquarters`, `branch`, `warehouse`) |
| `country_code` | no | Filter by country code (e.g. `US`, `GB`) |
| `locality` | no | Filter by city/locality |
| `admin_area_1` | no | Filter by state/province |
| `postal_code` | no | Filter by postal code |
| `location_name` | no | Filter by exact location name |
| `entity_id` | no | Filter to locations of a specific entity |
| `is_primary` | no | Filter primary locations only (`true`/`false`) |
| `min_certainty` | no | Min certainty for semantic search (default 0.5) |
| `limit` | no | Max results (default 20, max 100) |

---

## Geo Support

Entities can have `latitude` and `longitude` (WGS84). These are:
- Stored in PostgreSQL `DOUBLE PRECISION` columns
- Indexed in Weaviate as `geoCoordinates` for range filtering
- Returned in entity responses and topic search results
- Set via `POST /entities` (create) or `PUT /entities/{id}` (update)

Locations (`entity_location`) have their own `latitude`/`longitude` stored in both PostgreSQL and the Weaviate `LocationIndex` collection as `geoCoordinates`. The `EntityIndex` → `LocationIndex` cross-reference enables combined vector + geo queries in a single Weaviate round-trip.

---

## Admin CLI

The `entity_admin.py` CLI provides operational commands. Run from the project root.

### Stats

```bash
python entity_registry/entity_admin.py stats              # Overview
python entity_registry/entity_admin.py stats types        # Entities per type
python entity_registry/entity_admin.py stats aliases      # Alias stats
python entity_registry/entity_admin.py stats categories   # Category stats
python entity_registry/entity_admin.py stats identifiers  # Identifier stats
python entity_registry/entity_admin.py stats changelog    # Recent changes
```

### Search

```bash
python entity_registry/entity_admin.py search sql --name "Acme"
python entity_registry/entity_admin.py search similar --name "Acme Corp"
python entity_registry/entity_admin.py search topic --query "plumbing contractor"
```

### Dedup Index

```bash
python entity_registry/entity_admin.py dedup status       # Index size + backend
python entity_registry/entity_admin.py dedup sync         # Rebuild from PostgreSQL
python entity_registry/entity_admin.py dedup check        # Scan for duplicates
```

### Weaviate Index

```bash
python entity_registry/entity_admin.py weaviate status    # Collection info
python entity_registry/entity_admin.py weaviate rebuild   # Drop, recreate collections, full sync
python entity_registry/entity_admin.py weaviate sync      # Full sync from PostgreSQL
python entity_registry/entity_admin.py weaviate check     # Verify consistency
```

### Entity Types

```bash
python entity_registry/entity_admin.py types list
python entity_registry/entity_admin.py types add --key vendor --label "Vendor" --description "A vendor"
```

### Export

```bash
python entity_registry/entity_admin.py export --format json -o entities.json
python entity_registry/entity_admin.py export --format csv -o entities.csv
```

### Migrate

```bash
python entity_registry/entity_admin.py migrate            # Apply pending migrations
```

---

## Database Schema

All tables are global (not per-space). See `entity_registry_schema.py` for full DDL.

| Table | Purpose |
|-------|--------|
| `entity_type` | Entity type classification (person, business, etc.) |
| `entity` | Main entity table with name, geo coords, status, `metadata` JSONB, `verified` flag |
| `entity_identifier` | External IDs (DUNS, EIN, CRM) — not uniquely constrained |
| `entity_alias` | Alternate names (AKA, DBA, former, abbreviation) |
| `entity_same_as` | Duplicate/merge mappings with transitive resolution |
| `category` | Shared categories used by entities and locations |
| `entity_category_map` | Entity-to-category assignments |
| `entity_location_type` | Location type classification (headquarters, branch, etc.) |
| `entity_location` | Structured locations with address, geo, temporal validity |
| `entity_location_view` | View computing `is_active` from effective dates |
| `entity_location_category_map` | Location-to-category assignments |
| `relationship_type` | Relationship type definitions with optional `inverse_key` |
| `entity_relationship` | Directed relationships between entities with temporal validity |
| `entity_relationship_view` | View computing `is_current` from date range |
| `entity_change_log` | Audit trail of all changes |

### Key Design Decisions

- **Identifiers are not unique**: The same DUNS number can appear on multiple entities. Lookup returns a list.
- **Soft-delete only**: Entities are set to `status='deleted'`, never physically removed (except by cleanup scripts).
- **`retracted` vs `deleted`**: `retracted` is used on aliases, identifiers, relationships, and same-as (reversible). `deleted` is terminal on entities.
- **`metadata` JSONB**: Arbitrary key-value metadata on entities, stored as JSONB.
- **`verified` flag**: Entities can be marked verified with `verified_by` and `verified_time`.
- **Locations have temporal validity**: `effective_from`/`effective_to` determine `is_active` via a database view.
- **Relationships are directed**: `entity_source` → `entity_destination` with a typed relationship. `is_current` is computed from `start_datetime`/`end_datetime`.
- **Categories are shared**: The `category` table is used by both entity and location category mappings.
- **Same-as is transitive**: `resolve_entity(A)` follows A→B→C and returns C. Cycle prevention at insertion time.
- **Schema migration is explicit**: The service checks tables exist at startup but never creates or alters them. Use `migrate.py`.

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `LOCAL_DB_HOST` | PostgreSQL host | `localhost` |
| `LOCAL_DB_PORT` | PostgreSQL port | `5432` |
| `LOCAL_DB_NAME` | Database name | `fuseki_sql_graph` |
| `LOCAL_DB_USERNAME` | Database user | `postgres` |
| `ENTITY_WEAVIATE_ENABLED` | Enable Weaviate integration | `false` |
| `WEAVIATE_KEYCLOAK_URL` | Keycloak token endpoint | — |
| `WEAVIATE_CLIENT_ID` | OAuth client ID | — |
| `WEAVIATE_CLIENT_SECRET` | OAuth client secret | — |
| `WEAVIATE_USERNAME` | Keycloak username | — |
| `WEAVIATE_PASSWORD` | Keycloak password | — |
| `WEAVIATE_HTTP_HOST` | Weaviate HTTP host | — |
| `WEAVIATE_GRPC_HOST` | Weaviate gRPC host | — |
| `WEAVIATE_GRPC_PORT` | Weaviate gRPC port | `50051` |
| `ENTITY_DEDUP_BACKEND` | Dedup backend: `memory` or `redis` | `memory` |

---

## Source Files

```
vitalgraph/
  entity_registry/
    entity_registry_schema.py        # DDL, indexes, seed data, migrations
    entity_registry_impl.py          # Main class composing all mixins below
    entity_registry_id.py            # ID generation
    entity_changelog_ops.py          # ChangeLogMixin: audit log + helpers
    entity_identifier_ops.py         # IdentifierMixin: external identifier CRUD
    entity_alias_ops.py              # AliasMixin: alias CRUD + search
    entity_category_ops.py           # CategoryMixin: entity category operations
    entity_location_ops.py           # LocationMixin: location types, CRUD, categories
    entity_relationship_ops.py       # RelationshipMixin: relationship types + CRUD
    entity_same_as_ops.py            # SameAsMixin: same-as mappings + resolution
    entity_dedup_ops.py              # DedupMixin: near-duplicate detection + sync
    entity_weaviate_ops.py           # WeaviateMixin: Weaviate upsert/delete helpers
    entity_dedup.py                  # MinHash LSH + RapidFuzz dedup engine
    entity_weaviate.py               # Weaviate integration engine
    entity_weaviate_schema.py        # Weaviate collection schema + helpers
  endpoint/
    entity_registry_endpoint.py      # FastAPI REST handlers
  model/
    entity_registry_model.py         # Pydantic models
  client/
    endpoint/
      entity_registry_endpoint.py    # Client endpoint class

entity_registry/
  entity_admin.py                    # CLI admin tool
  migrate.py                         # Schema migration script

vitalgraph_client_test/
  load_test_data.py                  # Test data loader (8 entities)
  cleanup_test_data.py               # Test data cleanup (hard-delete via SQL)
  test_entity_registry_endpoint.py   # 117 endpoint tests
  test_weaviate_direct.py            # Direct Weaviate query tests (bypass server)
```
