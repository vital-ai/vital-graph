# Entity Registry — Location & Relationship Plan

## Implementation Progress

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 0 | Entity table enhancements (`metadata`, `verified`) | ✅ Complete |
| Phase 1 | New tables, indexes, views, seed data via `migrate.py` | ✅ Complete |
| Phase 2 | REST API endpoints (server) | ✅ Complete |
| Phase 3 | Client SDK methods | ✅ Complete |
| Phase 4 | Weaviate/dedup sync integration | ✅ Complete |
| Phase 5 | Weaviate Location class + Entity↔Location cross-refs + geo queries | ✅ Complete |
| — | Pydantic models (`entity_registry_model.py`) | ✅ Complete |
| — | Impl refactor into mixin files | ✅ Complete |
| — | Documentation (`docs/entity_registry.md`) | ✅ Complete |
| — | Data migration (backfill `entity_location` from `entity`) | ⬜ Not started |

### Deviations from Plan

- **API paths**: The plan proposed `/locations/create`, `/location-categories/add`, etc. The actual implementation uses paths consistent with the existing API style:
  - `/locations/add` (not `/locations/create`)
  - `/locations/categories/assign` (not `/location-categories/add`)
  - `/locations/categories/remove` (not `/location-categories/remove`)
  - `/locations/categories/list` (not `/location-categories/list-for-location`)
  - `/location-types` for GET and POST (not `/location-types/list` / `/location-types/create`)
  - `/relationship-types` for GET and POST (not `/relationship-types/list` / `/relationship-types/create`)
  - `/relationships` for POST (not `/relationships/create`)
- **Code organization**: `entity_registry_impl.py` was refactored into 9 mixin files (`entity_changelog_ops.py`, `entity_identifier_ops.py`, `entity_alias_ops.py`, `entity_category_ops.py`, `entity_location_ops.py`, `entity_relationship_ops.py`, `entity_same_as_ops.py`, `entity_dedup_ops.py`, `entity_weaviate_ops.py`) with the main class composing them all. This was not in the original plan.
- **Pydantic model names**: Actual models use `LocationCreateRequest`/`LocationResponse`/`RelationshipCreateRequest` etc. (with `Request`/`Response` suffixes) rather than the bare `LocationCreate`/`LocationUpdate` names in the plan.
- **Weaviate cross-reference creation order**: The plan assumed cross-references could be set during `collections.create()`. In practice, Weaviate requires both collections to exist before adding cross-references. The implementation creates both collections first, then adds references via `collection.config.add_reference()`.
- **Location data removed from entity search_text**: The plan originally included location data in the EntityIndex `search_text` composite field. This was removed — location search is now handled entirely via the LocationIndex cross-reference, keeping entity vectors focused on entity semantics.
- **Additional search endpoint**: `/search/topic-near` was added beyond what was originally planned in 5f. This is the primary combined query (entity vector + location geo via cross-ref traversal).
- **Cross-reference idempotency**: `_ensure_cross_references()` was changed to always attempt adding both cross-refs (catching "already exists"), rather than only adding them for newly created collections. This fixes the case where EntityIndex pre-existed Phase 5 and never received the `locations` cross-ref.
- **Metadata column type**: asyncpg returns `JSONB` columns as JSON strings, not dicts. `_entity_to_response()` in the server endpoint now parses the `metadata` field via `json.loads()` when it arrives as a string.
- **Admin tooling**: A standalone `entity_registry/weaviate_admin.py` script was added for Weaviate collection management (status, collections, delete, load, check). This was not in the original plan.

### Remaining Work

1. **Data migration**: Run the backfill SQL to copy existing `entity.country`/`region`/`locality`/`latitude`/`longitude` into `entity_location` rows.
2. **Production deployment**: Rebuild Weaviate collections (both EntityIndex + LocationIndex) and run `full_sync` + `location_sync` to populate.

### Testing Summary

- **Isolated Weaviate tests** (`test_entity_weaviate_location.py`): 53/53 passing — tests LocationIndex schema, upsert/delete, geo queries, cross-reference traversal, combined vector+geo in isolated test collections.
- **Client endpoint tests** (`test_entity_registry_endpoint.py`): 117/117 passing — includes Location CRUD (list, get, create, update, remove) and all three geo search endpoints (`search_locations_near`, `search_topic_near`, `search_entities_near`) against the live server.
- **Admin script** (`entity_registry/weaviate_admin.py`): `status` shows properties/refs/object counts for both collections, `collections` lists all Weaviate collections, `delete` drops+recreates with cross-refs, `load` syncs entities+locations from PostgreSQL, `check` compares Weaviate vs PostgreSQL counts.

---

## Overview

Two additions to the Entity Registry:

1. **Location** — a first-class location model with N locations per entity,
   full street-level address granularity, and location types. Complements the
   existing flat `country`, `region`, `locality`, `latitude`, `longitude`
   columns on `entity` (which are kept as-is for high-level queries).

2. **Relationship** — typed, directed relationships between entities
   (parent/subsidiary, employer/employee, investor, advisor, etc.) with
   temporal validity and status tracking.

Categorization uses a shared `category` table (renamed from `entity_category`)
that applies to both entities and locations via their respective join tables.

---

## Current State

The `entity` table has five inline location fields:

```
country       VARCHAR(100)
region        VARCHAR(255)
locality      VARCHAR(255)
latitude      DOUBLE PRECISION
longitude     DOUBLE PRECISION
```

The `entity` table also has:

```
metadata      JSONB DEFAULT '{}'
verified      BOOLEAN DEFAULT FALSE
verified_by   VARCHAR(255)
verified_time TIMESTAMPTZ
```

- **`metadata`** — flexible key-value store for domain-specific attributes
  (e.g. `founding_year`, `employee_count`, `sic_code`). Queryable via GIN index.
- **`verified`** / **`verified_by`** / **`verified_time`** — has a human
  confirmed this entity is real and accurate? Separate from `status` (an entity
  can be `active` but unverified).

These provide a **high-level location** for the entity itself — useful for
broad queries like "which businesses are in NJ?" or "all entities in London".
These fields are **kept as-is** and are NOT deprecated or replaced.

The new `entity_location` table provides **specific, detailed addresses**
(e.g. mailing address, branch office, warehouse) with full street-level
granularity. An entity may have N such locations.

---

## New Tables

### `entity_location_type`

Lookup table for location types (e.g. headquarters, branch, warehouse, mailing).

```sql
CREATE TABLE IF NOT EXISTS entity_location_type (
    location_type_id  SERIAL PRIMARY KEY,
    type_key          VARCHAR(50) UNIQUE NOT NULL,
    type_label        VARCHAR(255) NOT NULL,
    type_description  TEXT,
    created_time      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_time      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
```

**Seed data:**

| type_key       | type_label        |
|---------------|-------------------|
| headquarters  | Headquarters      |
| branch        | Branch Office     |
| warehouse     | Warehouse         |
| mailing       | Mailing Address   |
| residence     | Residence         |
| registered    | Registered Office |

### `entity_location`

One row per location. An entity may have N locations.

```sql
CREATE TABLE IF NOT EXISTS entity_location (
    location_id       SERIAL PRIMARY KEY,
    entity_id         VARCHAR(50) NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
    location_type_id  INTEGER NOT NULL REFERENCES entity_location_type(location_type_id),
    location_name     VARCHAR(255),
    description       TEXT,
    address_line_1    VARCHAR(500),
    address_line_2    VARCHAR(500),
    locality          VARCHAR(255),
    admin_area_2      VARCHAR(255),
    admin_area_1      VARCHAR(255),
    country           VARCHAR(100),
    country_code      VARCHAR(2),
    postal_code       VARCHAR(50),
    formatted_address VARCHAR(1000),
    latitude          DOUBLE PRECISION,
    longitude         DOUBLE PRECISION,
    timezone          VARCHAR(100),
    google_place_id   VARCHAR(255),
    effective_from    DATE,
    effective_to      DATE,
    is_primary        BOOLEAN DEFAULT FALSE,
    status            VARCHAR(20) NOT NULL DEFAULT 'active',
    created_time      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_time      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_by        VARCHAR(255),
    notes             TEXT
);
```

**Field semantics:**

| Column          | Meaning                                      | Example                  |
|----------------|----------------------------------------------|--------------------------|
| location_name  | Short label for display                       | NYC Office               |
| address_line_1 | Street address / PO Box                      | 123 Main St, Suite 400   |
| address_line_2 | Secondary line (apt, floor, building)         | Building C, Floor 3      |
| locality       | City / town                                   | San Francisco            |
| admin_area_2   | County / district / borough                   | San Francisco County     |
| admin_area_1   | State / province / region                     | California               |
| country        | Country name or ISO code                      | United States            |
| country_code   | ISO 3166-1 alpha-2 code                       | US                       |
| postal_code    | ZIP / postal code                             | 94105                    |
| formatted_address | Normalized full address string              | 1600 Amphitheatre Pkwy, Mountain View, CA 94043, US |
| latitude       | WGS84 latitude                                | 37.7749                  |
| longitude      | WGS84 longitude                               | -122.4194                |
| timezone       | IANA timezone identifier                      | America/New_York         |
| google_place_id| Google Places API place ID                    | ChIJj61dQgK6j4AR4GeTYWZsKWw |
| effective_from | Date location became valid (optional)         | 2024-01-15               |
| effective_to   | Date location stopped being valid (optional)  | NULL (still current)     |
| is_primary     | Whether this is the primary/default location  | true                     |

### `relationship_type`

Lookup table for relationship types.

```sql
CREATE TABLE IF NOT EXISTS relationship_type (
    relationship_type_id  SERIAL PRIMARY KEY,
    type_key              VARCHAR(50) UNIQUE NOT NULL,
    type_label            VARCHAR(255) NOT NULL,
    type_description      TEXT,
    inverse_key           VARCHAR(50),
    created_time          TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_time          TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
```

`inverse_key` is optional — it names the reverse perspective. For example,
`parent_of` has inverse `subsidiary_of`. This lets the API show the
relationship label from either entity's point of view.

**Seed data:**

| type_key         | type_label          | inverse_key        |
|-----------------|---------------------|--------------------||
| parent_of        | Parent Of           | subsidiary_of      |
| subsidiary_of    | Subsidiary Of       | parent_of          |
| employer_of      | Employer Of         | employee_of        |
| employee_of      | Employee Of         | employer_of        |
| investor_in      | Investor In         | funded_by          |
| funded_by        | Funded By           | investor_in        |
| partner_of       | Partner Of          | partner_of         |
| advisor_to       | Advisor To          | advised_by         |
| advised_by       | Advised By          | advisor_to         |
| supplier_to      | Supplier To         | customer_of        |
| customer_of      | Customer Of         | supplier_to        |
| board_member_of  | Board Member Of     | has_board_member   |
| has_board_member | Has Board Member    | board_member_of    |

### `entity_relationship`

Directed edge between two entities.

- **`start_datetime` / `end_datetime`** — when the relationship is/was true
  in the real world (e.g. employment from 2020-01 to 2023-06).
- **`status`** — `active` or `retracted`. `retracted` means the relationship
  record was found to be wrong (data quality), regardless of dates.

```sql
CREATE TABLE IF NOT EXISTS entity_relationship (
    relationship_id       SERIAL PRIMARY KEY,
    entity_source         VARCHAR(50) NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
    entity_destination    VARCHAR(50) NOT NULL REFERENCES entity(entity_id) ON DELETE CASCADE,
    relationship_type_id  INTEGER NOT NULL REFERENCES relationship_type(relationship_type_id),
    status                VARCHAR(20) NOT NULL DEFAULT 'active',
    start_datetime        TIMESTAMPTZ,
    end_datetime          TIMESTAMPTZ,
    description           TEXT,
    created_time          TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_time          TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_by            VARCHAR(255),
    notes                 TEXT,
    CONSTRAINT uq_entity_relationship UNIQUE (entity_source, entity_destination, relationship_type_id)
);
```

### `entity_location_category_map`

Join table: a location may belong to N categories from the shared
`category` table (renamed from `entity_category`).

```sql
CREATE TABLE IF NOT EXISTS entity_location_category_map (
    location_category_map_id  SERIAL PRIMARY KEY,
    location_id               INTEGER NOT NULL REFERENCES entity_location(location_id) ON DELETE CASCADE,
    category_id               INTEGER NOT NULL REFERENCES category(category_id),
    status                    VARCHAR(20) NOT NULL DEFAULT 'active',
    created_time              TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_by                VARCHAR(255),
    notes                     TEXT,
    CONSTRAINT uq_location_category UNIQUE (location_id, category_id)
);
```

---

## Indexes

```sql
CREATE INDEX IF NOT EXISTS idx_location_entity      ON entity_location(entity_id);
CREATE INDEX IF NOT EXISTS idx_location_type         ON entity_location(location_type_id);
CREATE INDEX IF NOT EXISTS idx_location_country      ON entity_location(country);
CREATE INDEX IF NOT EXISTS idx_location_admin1       ON entity_location(admin_area_1);
CREATE INDEX IF NOT EXISTS idx_location_locality     ON entity_location(locality);
CREATE INDEX IF NOT EXISTS idx_location_postal       ON entity_location(postal_code);
CREATE INDEX IF NOT EXISTS idx_location_status       ON entity_location(status);
CREATE INDEX IF NOT EXISTS idx_location_primary      ON entity_location(entity_id, is_primary) WHERE is_primary = TRUE;
CREATE INDEX IF NOT EXISTS idx_location_latlon       ON entity_location(latitude, longitude) WHERE latitude IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_location_country_code ON entity_location(country_code);
CREATE INDEX IF NOT EXISTS idx_location_place_id     ON entity_location(google_place_id) WHERE google_place_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_location_effective    ON entity_location(effective_from, effective_to);

CREATE INDEX IF NOT EXISTS idx_loc_type_key          ON entity_location_type(type_key);

CREATE INDEX IF NOT EXISTS idx_loc_catmap_location   ON entity_location_category_map(location_id);
CREATE INDEX IF NOT EXISTS idx_loc_catmap_category   ON entity_location_category_map(category_id);
CREATE INDEX IF NOT EXISTS idx_loc_catmap_status     ON entity_location_category_map(status);

CREATE INDEX IF NOT EXISTS idx_rel_type_key          ON relationship_type(type_key);
CREATE INDEX IF NOT EXISTS idx_rel_source            ON entity_relationship(entity_source);
CREATE INDEX IF NOT EXISTS idx_rel_destination       ON entity_relationship(entity_destination);
CREATE INDEX IF NOT EXISTS idx_rel_type              ON entity_relationship(relationship_type_id);
CREATE INDEX IF NOT EXISTS idx_rel_status            ON entity_relationship(status);
CREATE INDEX IF NOT EXISTS idx_rel_dates             ON entity_relationship(start_datetime, end_datetime);
```

### `entity_location_view`

A view that adds a computed `is_active` column — always accurate, no cron needed.
Application code should read from this view instead of the base table.

```sql
CREATE OR REPLACE VIEW entity_location_view AS
SELECT *,
    (effective_to IS NULL OR effective_to >= CURRENT_DATE) AS is_active
FROM entity_location;
```

Queries for active locations:

```sql
-- All current locations for an entity
SELECT * FROM entity_location_view
WHERE entity_id = $1 AND status = 'active' AND is_active = TRUE;

-- Full history (including expired)
SELECT * FROM entity_location_view
WHERE entity_id = $1 AND status = 'active';
```

### `entity_relationship_view`

Adds a computed `is_current` column — `TRUE` when the relationship is
currently true: status is `active` AND the current time falls within
`start_datetime`..`end_datetime`.

```sql
CREATE OR REPLACE VIEW entity_relationship_view AS
SELECT *,
    (
        status = 'active'
        AND (start_datetime IS NULL OR start_datetime <= CURRENT_TIMESTAMP)
        AND (end_datetime IS NULL OR end_datetime >= CURRENT_TIMESTAMP)
    ) AS is_current
FROM entity_relationship;
```

> **Why views?** `CURRENT_DATE`/`CURRENT_TIMESTAMP` are not immutable, so they
> cannot be used in generated columns. Views compute values at query
> time — always correct, zero maintenance.

---

## ER Diagram (text)

```
entity (1) ──── (N) entity_location (N) ──── (1) entity_location_type
  │                      │
  │                 (N) ──── (N) category
  │                           (via entity_location_category_map)
  │
  ├── (source 1) ──── (N) entity_relationship (N) ──── (1 destination) entity
  │                            │
  │                       (N) ──── (1) relationship_type
```

---

## Migration Strategy

### Phase 0: Entity table enhancements (non-breaking migrations) ✅

```sql
-- Flexible key-value metadata (queryable via GIN index)
ALTER TABLE entity ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';
CREATE INDEX IF NOT EXISTS idx_entity_metadata ON entity USING gin(metadata);

-- Verification tracking
ALTER TABLE entity ADD COLUMN IF NOT EXISTS verified BOOLEAN DEFAULT FALSE;
ALTER TABLE entity ADD COLUMN IF NOT EXISTS verified_by VARCHAR(255);
ALTER TABLE entity ADD COLUMN IF NOT EXISTS verified_time TIMESTAMPTZ;
```

> **Implemented** in `entity_registry_schema.py` migrations and `migrate.py`. The `create_entity` and `update_entity` methods handle `metadata` (with `::jsonb` cast) and `verified`/`verified_by`/`verified_time`.

### Phase 1: Add new tables (non-breaking) ✅

1. Add `entity_location_type`, `entity_location`,
   `entity_location_category_map`, `relationship_type`, and
   `entity_relationship` tables, indexes, and views via `migrate.py`.
2. Insert seed data for location types and relationship types.
3. **Migrate existing data**: For every entity with non-null `country`, `region`,
   `locality`, or `latitude`/`longitude`, insert a row into `entity_location`
   with `location_type_id` = `headquarters` (default) and `is_primary = TRUE`.

### `is_primary` enforcement

When a location is created or updated with `is_primary = TRUE`, the API
automatically sets `is_primary = FALSE` on all other locations for the same
entity. This ensures at most one primary location per entity.

### Change log coverage

Location changes are logged to the existing `entity_change_log` table using
the entity's `entity_id` as the reference. New `change_type` values:

| change_type                 | Detail                                    |
|----------------------------|-------------------------------------------|
| `location_created`         | `{location_id, location_name, type_key}`  |
| `location_updated`         | `{location_id, changed_fields}`           |
| `location_removed`         | `{location_id, location_name}`            |
| `location_category_added`  | `{location_id, category_key}`             |
| `location_category_removed`| `{location_id, category_key}`             |
| `relationship_created`     | `{relationship_id, type_key, dest_id}`    |
| `relationship_updated`     | `{relationship_id, changed_fields}`       |
| `relationship_removed`     | `{relationship_id, type_key, dest_id}`    |

### Bulk location create on entity create

The existing `create_entity` endpoint accepts `aliases` and `identifiers`
inline. It will also accept an optional `locations` list to create locations
in the same transaction:

```python
{
    "type_key": "business",
    "primary_name": "Acme Corp",
    "locations": [
        {
            "location_type_key": "headquarters",
            "location_name": "Main Office",
            "address_line_1": "123 Main St",
            "locality": "Newark",
            "admin_area_1": "NJ",
            "country": "US",
            "is_primary": true
        }
    ]
}
```

### Phase 2: API endpoints ✅

Implemented REST endpoints (actual paths — slightly adjusted from plan for consistency):

| Method | Path                                     | Description                          |
|--------|------------------------------------------|--------------------------------------|
| GET    | /locations/list                          | List locations for an entity         |
| POST   | /locations/add                           | Add a location to an entity          |
| GET    | /locations/get                           | Get a single location by ID          |
| PUT    | /locations/update                        | Update a location                    |
| DELETE | /locations/remove                        | Soft-remove a location               |
| POST   | /locations/categories/assign             | Add a category to a location         |
| DELETE | /locations/categories/remove             | Remove a category from a location    |
| GET    | /locations/categories/list               | List categories for a location       |
| GET    | /location-types                          | List all location types              |
| POST   | /location-types                          | Create a location type               |
| GET    | /relationships/list                      | List relationships for an entity     |
| POST   | /relationships                           | Create a relationship                |
| GET    | /relationships/get                       | Get a relationship by ID             |
| PUT    | /relationships/update                    | Update a relationship                |
| DELETE | /relationships/remove                    | Soft-remove (retract) a relationship |
| GET    | /relationship-types                      | List all relationship types          |
| POST   | /relationship-types                      | Create a relationship type           |

Query parameters:

- `entity_id` — required for list, create
- `location_id` — required for get, update, remove, add/remove/list category
- `category_key` — required for add/remove category (uses shared `category` table)
- `location_type_key` — required for create (resolves to location_type_id)
- `include_expired` — optional bool on list (default false); when true, includes locations where `is_active = FALSE`
- `entity_source` / `entity_destination` — for relationship create
- `relationship_type_key` — for relationship create
- `direction` — optional on relationships/list: `outgoing`, `incoming`, or `both` (default `both`)

### Phase 3: Client methods ✅

Async methods added to `vitalgraph/client/endpoint/entity_registry_endpoint.py`:

- `list_locations(entity_id, include_expired=False)` → `List[LocationResponse]`
- `create_location(entity_id, ...)` → `LocationResponse`
- `get_location(location_id)` → `LocationResponse`
- `update_location(location_id, ...)` → `LocationResponse`
- `remove_location(location_id)` → `bool`
- `add_location_category(location_id, category_key)` → `dict`
- `remove_location_category(location_id, category_key)` → `bool`
- `list_location_categories(location_id)` → `List[dict]`
- `list_location_types()` → `List[LocationTypeResponse]`
- `create_location_type(...)` → `LocationTypeResponse`
- `list_relationships(entity_id, direction='both', include_expired=False)` → `List[RelationshipResponse]`
- `create_relationship(entity_source, entity_destination, relationship_type_key, ...)` → `RelationshipResponse`
- `get_relationship(relationship_id)` → `RelationshipResponse`
- `update_relationship(relationship_id, ...)` → `RelationshipResponse`
- `remove_relationship(relationship_id)` → `bool`
- `list_relationship_types()` → `List[RelationshipTypeResponse]`
- `create_relationship_type(...)` → `RelationshipTypeResponse`

### Phase 4: Sync integration ✅

- Update Weaviate `full_sync()` bulk query to LEFT JOIN `entity_location` so
  detailed location data is included in the vector index.
- The existing entity-level `country`, `region`, `locality`, `latitude`,
  `longitude` fields continue to be synced as before (high-level location).
- Update dedup `initialize()` if location fields are used for dedup scoring.
- Update sync scripts if location data affects search/matching.

> **Note:** The flat location fields on `entity` are kept permanently. They
> represent the entity's high-level location and are complementary to the
> detailed `entity_location` rows.

~~Also update `get_entity` response to include the entity's locations (at minimum
the primary location) alongside aliases, identifiers, and categories.~~
**Done** — `get_entity` now returns `locations` (all active, with categories) and
`relationships` (current, with type info) alongside aliases, identifiers, and categories.

### Phase 5: Weaviate Location class + geo queries ✅

Add a dedicated Weaviate collection for locations with full address properties,
geo coordinates, and a cross-reference to the `EntityIndex` collection. This
enables geo-radius queries directly on locations ("find all locations within
10 km of this point") and entity-location joins ("find entities with a location
near this point").

#### 5a. `LocationIndex` Weaviate collection

A new Weaviate collection alongside the existing `EntityIndex`.

**Properties:**

| Property | Type | Vectorized | Description |
|----------|------|------------|-------------|
| `location_id` | `TEXT` (FIELD) | No | PostgreSQL location_id (as string) |
| `entity_id` | `TEXT` (FIELD) | No | Owning entity ID |
| `location_type_key` | `TEXT` (FIELD) | No | e.g. headquarters, branch, warehouse |
| `location_type_label` | `TEXT` (WORD) | Yes | Human-readable type label |
| `location_name` | `TEXT` (WORD) | Yes | Short display name |
| `description` | `TEXT` (WORD) | Yes | Location description |
| `address_line_1` | `TEXT` (WORD) | No | Street address |
| `locality` | `TEXT` (FIELD) | No | City |
| `admin_area_1` | `TEXT` (FIELD) | No | State/province |
| `country` | `TEXT` (FIELD) | No | Country name |
| `country_code` | `TEXT` (FIELD) | No | ISO 3166-1 alpha-2 |
| `postal_code` | `TEXT` (FIELD) | No | ZIP/postal code |
| `formatted_address` | `TEXT` (WORD) | Yes | Full normalized address |
| `geo_location` | `GEO_COORDINATES` | No | lat/long for radius queries |
| `is_primary` | `BOOL` | No | Primary location flag |
| `status` | `TEXT` (FIELD) | No | active/removed |
| `search_text` | `TEXT` (WORD) | Yes | Composite: "{name}. {type_label}. {description}. {formatted_address}" |

Collection name follows the existing pattern: `{env}xxxLocationIndex`
(e.g. `devxxxLocationIndex`).

Deterministic UUID: `uuid5(NAMESPACE_URL, "vitalgraph:location:{location_id}")`

#### 5b. Cross-reference: Entity ↔ Location

Add a Weaviate cross-reference from `LocationIndex` to `EntityIndex`:

```python
wvc.ReferenceProperty(
    name="entity",
    target_collection="{env}xxxEntityIndex",
    description="The entity that owns this location",
)
```

Optionally, add the inverse cross-reference on `EntityIndex`:

```python
wvc.ReferenceProperty(
    name="locations",
    target_collection="{env}xxxLocationIndex",
    description="Locations belonging to this entity",
)
```

Cross-references are set during upsert by linking the location’s UUID
to the entity’s UUID (both deterministic from their IDs).

#### 5c. Location geo-radius query

New search method: find locations within a radius of a lat/long point.

```
GET /api/registry/search/locations-near
    ?latitude=37.78&longitude=-122.42&radius_km=10
    &location_type_key=headquarters   (optional)
    &country=US                        (optional)
    &limit=20                          (optional)
```

Implementation: Weaviate `Filter.by_property("geo_location").within_geo_range(...)`
on the `LocationIndex` collection. Returns location objects with their
`entity_id` for client-side join or follow-up entity fetch.

#### 5d. Combined entity topic + location geo query (single GraphQL)

The primary use case: **semantic search on entity descriptions combined with
geo-radius filtering on their locations — in a single Weaviate GraphQL query**
that traverses the `locations` cross-reference.

Example: *"Find plumbers with a location within 10 km of (37.78, -122.42)"*

```
GET /api/registry/search/topic-near
    ?q=plumbers
    &latitude=37.78&longitude=-122.42&radius_km=10
    &type_key=business                 (optional entity type filter)
    &min_certainty=0.7                 (optional, default 0.7)
    &limit=20                          (optional)
```

**Implementation — single GraphQL query via cross-reference:**

The `EntityIndex` collection has a `locations` cross-reference pointing to
`LocationIndex`. A single Weaviate GraphQL query performs vector search on
entities and traverses the cross-ref to filter/return location data:

```graphql
{
  Get {
    EntityIndex(
      nearText: { concepts: ["plumbers"], certainty: 0.7 }
      where: { operator: And, operands: [
        { path: ["type_key"], operator: Equal, valueText: "business" },
        { path: ["locations", "LocationIndex", "geo_location"],
          operator: WithinGeoRange,
          valueGeoRange: {
            geoCoordinates: { latitude: 37.78, longitude: -122.42 },
            distance: { max: 10000 }
          }
        }
      ]}
      limit: 20
    ) {
      entity_id
      primary_name
      description
      type_key
      _additional { certainty distance }
      locations {
        ... on LocationIndex {
          location_id
          location_name
          formatted_address
          locality
          admin_area_1
          geo_location { latitude longitude }
          is_primary
          location_type_key
        }
      }
    }
  }
}
```

This is a **single round-trip** to Weaviate that:
1. Performs `near_text` vector search on `EntityIndex` (ranks entities by
   semantic similarity to "plumbers")
2. Filters to entities whose `locations` cross-ref contains at least one
   `LocationIndex` object with `geo_location` within the radius
3. Returns the matched entities with their location details inline

The Python implementation uses the Weaviate v4 client's `query.near_text()`
with `Filter.by_ref("locations").by_property("geo_location").within_geo_range()`
and `QueryReference` to include location properties in the response.

**Key requirement:** The `locations` cross-reference on `EntityIndex` (5b)
is **required** for this query pattern. It must be set during sync/upsert.

#### 5d-alt. Entity-only geo query (no vector)

Simpler variant: find entities with a location near a point, without
semantic ranking. Uses the same cross-ref traversal but without `nearText`.

```
GET /api/registry/search/entities-near
    ?latitude=37.78&longitude=-122.42&radius_km=10
    &type_key=business                 (optional)
    &limit=20                          (optional)
```

Implementation: query `EntityIndex` with a `where` filter on the `locations`
cross-ref `geo_location`, no vector search. Returns entities ordered by name.

#### 5e. Sync

- **`full_sync`**: Add a `location_sync()` method (or extend existing
  `full_sync`) that bulk-loads `entity_location` rows into `LocationIndex`
  and sets cross-references.
- **Single upsert**: When a location is created/updated/removed, upsert or
  delete from `LocationIndex`. Wire into `LocationMixin` CRUD methods.
- **Stale cleanup**: On full sync, remove `LocationIndex` objects whose
  `location_id` no longer exists in PostgreSQL.

#### 5f. Schema file changes

| File | Change |
|------|--------|
| `entity_weaviate_schema.py` | Add `get_location_collection_name()`, `get_location_collection_config()`, `location_to_weaviate_properties()`, `location_id_to_weaviate_uuid()` |
| `entity_weaviate.py` | Add `ensure_location_collection()`, `upsert_location()`, `delete_location()`, `upsert_locations_batch()`, `location_sync()`, `search_locations_near()`, `search_entities_near()` |
| `entity_weaviate_ops.py` | Add `_weaviate_upsert_location()`, `_weaviate_delete_location()` helpers |
| `entity_location_ops.py` | Wire location CRUD to call Weaviate upsert/delete |
| `entity_registry_endpoint.py` (server) | Add `/search/locations-near` and `/search/entities-near` routes |
| `entity_registry_model.py` | Add `LocationNearRequest`/`LocationNearResponse` Pydantic models |
| `entity_registry_endpoint.py` (client) | Add `search_locations_near()` and `search_entities_near()` methods |

#### 5g. Collection migration

Since this adds a new collection (not modifying an existing one), no
recreation of `EntityIndex` is needed. If the inverse cross-reference
(`locations` on `EntityIndex`) is desired, the existing `EntityIndex`
collection would need to be recreated or the reference added via the
Weaviate REST API.

> **Implementation note:** Both cross-references (Entity→Location and
> Location→Entity) are added automatically by `ensure_collection()` using
> `config.add_reference()` after both collections are created. The
> `rebuild_collection()` method handles the full drop/recreate/add-refs cycle.
> `_ensure_cross_references()` is idempotent — safe to call on existing
> collections (catches "already exists" errors).
> Verified with 53/53 isolated tests + 117/117 client endpoint tests passing.

---

## Pydantic Models

```python
class LocationCreate(BaseModel):
    entity_id: str
    location_type_key: str
    location_name: Optional[str] = None
    description: Optional[str] = None
    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    locality: Optional[str] = None
    admin_area_2: Optional[str] = None
    admin_area_1: Optional[str] = None
    country: Optional[str] = None
    postal_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    formatted_address: Optional[str] = None
    timezone: Optional[str] = None
    google_place_id: Optional[str] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    is_primary: bool = False
    created_by: Optional[str] = None
    notes: Optional[str] = None

class LocationUpdate(BaseModel):
    location_name: Optional[str] = None
    description: Optional[str] = None
    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    locality: Optional[str] = None
    admin_area_2: Optional[str] = None
    admin_area_1: Optional[str] = None
    country: Optional[str] = None
    country_code: Optional[str] = None
    postal_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    formatted_address: Optional[str] = None
    timezone: Optional[str] = None
    google_place_id: Optional[str] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    is_primary: Optional[bool] = None
    notes: Optional[str] = None

class LocationResponse(BaseModel):
    location_id: int
    entity_id: str
    location_type_key: str
    location_type_label: str
    location_name: Optional[str]
    description: Optional[str]
    address_line_1: Optional[str]
    address_line_2: Optional[str]
    locality: Optional[str]
    admin_area_2: Optional[str]
    admin_area_1: Optional[str]
    country: Optional[str]
    country_code: Optional[str]
    postal_code: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    formatted_address: Optional[str]
    timezone: Optional[str]
    google_place_id: Optional[str]
    effective_from: Optional[date]
    effective_to: Optional[date]
    is_active: bool          # computed from view
    is_primary: bool
    status: str
    categories: List[dict]  # [{category_key, category_label}] from category table
    created_time: datetime
    updated_time: datetime
```

class RelationshipTypeResponse(BaseModel):
    relationship_type_id: int
    type_key: str
    type_label: str
    type_description: Optional[str]
    inverse_key: Optional[str]
    created_time: datetime
    updated_time: datetime

class RelationshipCreate(BaseModel):
    entity_source: str
    entity_destination: str
    relationship_type_key: str
    status: str = 'active'
    start_datetime: Optional[datetime] = None
    end_datetime: Optional[datetime] = None
    description: Optional[str] = None
    created_by: Optional[str] = None
    notes: Optional[str] = None

class RelationshipUpdate(BaseModel):
    status: Optional[str] = None
    start_datetime: Optional[datetime] = None
    end_datetime: Optional[datetime] = None
    description: Optional[str] = None
    notes: Optional[str] = None

class RelationshipResponse(BaseModel):
    relationship_id: int
    entity_source: str
    entity_destination: str
    relationship_type_key: str
    relationship_type_label: str
    inverse_key: Optional[str]
    status: str
    is_current: bool          # computed from view (active + in temporal window)
    start_datetime: Optional[datetime]
    end_datetime: Optional[datetime]
    description: Optional[str]
    created_time: datetime
    updated_time: datetime
```

---

## Data Migration SQL ⬜

This has **not yet been run**. Execute after verifying the new tables are correct.

```sql
-- Migrate existing entity location data into entity_location table
INSERT INTO entity_location (
    entity_id, location_type_id, locality, admin_area_1, country,
    latitude, longitude, is_primary, status
)
SELECT
    e.entity_id,
    (SELECT location_type_id FROM entity_location_type WHERE type_key = 'headquarters'),
    e.locality,
    e.region,
    e.country,
    e.latitude,
    e.longitude,
    TRUE,
    'active'
FROM entity e
WHERE e.status != 'deleted'
  AND (e.country IS NOT NULL OR e.region IS NOT NULL OR e.locality IS NOT NULL
       OR e.latitude IS NOT NULL OR e.longitude IS NOT NULL);
```

---

## Open Questions (Resolved)

1. **Geocoding**: ~~Should we auto-geocode addresses to lat/long on create/update?~~ **No** — geocoding is not handled by the entity registry. Callers are responsible for providing lat/long and other geo fields.
2. **Uniqueness**: ~~Should there be a constraint preventing duplicate addresses per entity?~~ **No constraint** — an entity can have the same address multiple times with different types (e.g. headquarters and mailing at the same address).
3. **Google Place enrichment**: ~~Should we auto-fetch place details when a `google_place_id` is provided?~~ **No** — the `google_place_id` field is stored as-is for external reference only.
