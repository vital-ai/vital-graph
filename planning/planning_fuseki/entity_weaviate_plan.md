# Entity Registry: Weaviate Vector Index Plan

## Implementation Status

> **All phases complete. 9/9 direct Weaviate tests + 117/117 endpoint tests passing.**

| Component | Status |
|-----------|--------|
| EntityIndex collection schema (19 properties) | ✅ Complete |
| LocationIndex collection schema (17 properties) | ✅ Complete |
| Entity→Location cross-references | ✅ Complete |
| Identifier properties (`identifier_keys`, `identifier_values`) | ✅ Complete |
| Full sync from PostgreSQL (entities + locations + identifiers) | ✅ Complete |
| Incremental sync (on entity/alias/category/identifier changes) | ✅ Complete |
| Unified `/search/entity` endpoint (semantic + geo + identifier) | ✅ Complete |
| `/search/location` endpoint (geo-radius) | ✅ Complete |
| `weaviate rebuild` admin command | ✅ Complete |
| Auth: Keycloak `offline_access` scope + refresh token | ✅ Complete |
| `test_weaviate_direct.py` (direct query tests) | ✅ Complete |

---

## Overview

Index entities in Weaviate to enable semantic topic and location queries such as:

> *"Find businesses in NJ that do plumbing"*

This leverages Weaviate's text2vec-transformers vectorizer (already deployed) for topic matching and property-level filtering for geo/type constraints. The entity table in PostgreSQL remains the source of truth; a sync process keeps Weaviate in sync.

---

## Architecture

```
PostgreSQL (entity tables)          Weaviate (vector index)
┌─────────────────────┐             ┌──────────────────────┐
│  entity             │  sync ──▶   │  EntityIndex         │
│  entity_type        │             │  (19 properties)     │
│  entity_alias       │             │  + identifier_keys   │
│  entity_identifier  │             │  + identifier_values │
│  entity_category    │             └──────────┬───────────┘
└─────────────────────┘                        │ cross-ref
                                    ┌──────────┴───────────┐
                                    │  LocationIndex       │
                                    │  (17 properties)     │
                                    └──────────────────────┘
                                             │
                                             ▼
                                   Unified queries via
                                   /api/registry/search/entity
                                   /api/registry/search/location
```

### Query Flow

1. Client sends: `GET /api/registry/search/entity?q=plumbing+contractor&country=US&type_key=business`
2. Endpoint builds a Weaviate hybrid query:
   - **Vector part**: `q` is embedded via text2vec-transformers and matched against the vectorized `search_text` property
   - **Filter part**: `country`, `region`, `locality`, `type_key` are exact-match property filters
3. Weaviate returns ranked results with distance scores
4. Endpoint enriches with full entity data from PostgreSQL if needed

---

## Weaviate Collection Schema

A single flat collection per environment, named `{env}xxxEntityIndex` (e.g. `devxxxEntityIndex`, `prodxxxEntityIndex`, `testxxxEntityIndex`). Uses `xxx` as separator since underscores are problematic in Weaviate. The env prefix is controlled by `ENTITY_WEAVIATE_ENV` (default: `dev`).

```python
{
    "class": "{env}xxxEntityIndex",  # e.g. devxxxEntityIndex, prodxxxEntityIndex
    "description": "Searchable index of entities from the Entity Registry",
    "vectorizer": "text2vec-transformers",
    "moduleConfig": {
        "text2vec-transformers": {
            "vectorizeClassName": False
        }
    },
    "properties": [
        # Identity
        {
            "name": "entity_id",
            "dataType": ["text"],
            "description": "Entity Registry ID (e.g. e_abc123)",
            "tokenization": "field",          # exact match, not tokenized
            "moduleConfig": {
                "text2vec-transformers": {"skip": True}
            }
        },

        # Core fields (vectorized for semantic search)
        {
            "name": "primary_name",
            "dataType": ["text"],
            "description": "Primary entity name",
            "tokenization": "word",
            "moduleConfig": {
                "text2vec-transformers": {"skip": False}
            }
        },
        {
            "name": "description",
            "dataType": ["text"],
            "description": "Entity description (topic/industry text)",
            "tokenization": "word",
            "moduleConfig": {
                "text2vec-transformers": {"skip": False}
            }
        },
        {
            "name": "aliases",
            "dataType": ["text"],
            "description": "Pipe-separated alias names (e.g. 'IBM|Big Blue')",
            "tokenization": "word",
            "moduleConfig": {
                "text2vec-transformers": {"skip": False}
            }
        },
        {
            "name": "notes",
            "dataType": ["text"],
            "description": "Free-text notes",
            "tokenization": "word",
            "moduleConfig": {
                "text2vec-transformers": {"skip": False}
            }
        },

        # Type fields (filterable, contribute to vector)
        {
            "name": "type_key",
            "dataType": ["text"],
            "description": "Entity type key (person, business, organization, government)",
            "tokenization": "field",
            "moduleConfig": {
                "text2vec-transformers": {"skip": True}
            }
        },
        {
            "name": "type_label",
            "dataType": ["text"],
            "description": "Entity type label",
            "tokenization": "word",
            "moduleConfig": {
                "text2vec-transformers": {"skip": False}
            }
        },
        {
            "name": "type_description",
            "dataType": ["text"],
            "description": "Entity type description",
            "tokenization": "word",
            "moduleConfig": {
                "text2vec-transformers": {"skip": False}
            }
        },

        # Location fields (filterable, not vectorized)
        {
            "name": "country",
            "dataType": ["text"],
            "description": "Country code or name",
            "tokenization": "field",
            "moduleConfig": {
                "text2vec-transformers": {"skip": True}
            }
        },
        {
            "name": "region",
            "dataType": ["text"],
            "description": "State/region",
            "tokenization": "field",
            "moduleConfig": {
                "text2vec-transformers": {"skip": True}
            }
        },
        {
            "name": "locality",
            "dataType": ["text"],
            "description": "City/locality",
            "tokenization": "field",
            "moduleConfig": {
                "text2vec-transformers": {"skip": True}
            }
        },

        # Category fields (filterable + vectorized labels)
        {
            "name": "category_keys",
            "dataType": ["text[]"],
            "description": "Category keys assigned to entity (e.g. ['customer', 'partner'])",
            "tokenization": "field",
            "moduleConfig": {
                "text2vec-transformers": {"skip": True}
            }
        },
        {
            "name": "category_labels",
            "dataType": ["text"],
            "description": "Pipe-separated category labels (e.g. 'Customer|Partner')",
            "tokenization": "word",
            "moduleConfig": {
                "text2vec-transformers": {"skip": False}
            }
        },

        # Identifier fields (not vectorized, for exact-match filtering)
        {
            "name": "identifier_keys",
            "dataType": ["text[]"],
            "description": "Composite namespace:value keys (e.g. ['DUNS:123456', 'EIN:47-001'])",
            "moduleConfig": {
                "text2vec-transformers": {"skip": True}
            }
        },
        {
            "name": "identifier_values",
            "dataType": ["text[]"],
            "description": "Identifier values only (cross-namespace lookup)",
            "moduleConfig": {
                "text2vec-transformers": {"skip": True}
            }
        },

        # Metadata (not vectorized)
        {
            "name": "website",
            "dataType": ["text"],
            "description": "Entity website URL",
            "tokenization": "field",
            "moduleConfig": {
                "text2vec-transformers": {"skip": True}
            }
        },
        {
            "name": "status",
            "dataType": ["text"],
            "description": "Entity status (active, deleted)",
            "tokenization": "field",
            "moduleConfig": {
                "text2vec-transformers": {"skip": True}
            }
        },

        # Composite search field (vectorized)
        {
            "name": "search_text",
            "dataType": ["text"],
            "description": "Concatenated text for vector embedding: name + type + description + location",
            "tokenization": "word",
            "moduleConfig": {
                "text2vec-transformers": {"skip": False}
            }
        },
    ]
}
```

### Field Design Rationale

- **Vectorized fields** (`skip: False`): `primary_name`, `description`, `aliases`, `notes`, `type_label`, `type_description`, `category_labels`, `search_text` — these contribute to the semantic vector so queries like "plumbing" match entities described as plumbing contractors.
- **Filter-only fields** (`skip: True`): `entity_id`, `type_key`, `country`, `region`, `locality`, `website`, `status`, `category_keys`, `identifier_keys`, `identifier_values` — used for exact-match filtering, not semantic similarity.
- **`identifier_keys`**: Text array of composite `namespace:value` strings (e.g. `["DUNS:123456", "EIN:47-001"]`). Searched via `contains_any` when both namespace and value are provided.
- **`identifier_values`**: Text array of values only (e.g. `["123456", "47-001"]`). Searched via `contains_any` when only value is provided (cross-namespace).
- **`search_text`**: A composite field that concatenates key fields into a single string for a rich embedding: `"{primary_name}. {type_label}: {type_description}. {description}. Categories: {category_labels}. {country} {region} {locality}"`. This gives the vector model full context in one place.
- **`aliases`**: Pipe-separated string of all active alias names, so alias terms appear in the vector.
- **`type_key`**: Used as a constant filter (e.g. `type_key == 'business'`) for queries scoped to a specific entity type.
- **`category_keys`**: Text array for exact-match filtering (e.g. `category_keys contains 'customer'`). Supports queries like "find all customers in NJ".
- **`category_labels`**: Pipe-separated labels (e.g. `'Customer|Partner'`) — vectorized so category semantics contribute to the embedding.

### `search_text` Construction

```python
def build_search_text(entity: dict) -> str:
    """Build composite search text for vectorization."""
    parts = []
    if entity.get('primary_name'):
        parts.append(entity['primary_name'])
    if entity.get('type_label'):
        type_str = entity['type_label']
        if entity.get('type_description'):
            type_str += f": {entity['type_description']}"
        parts.append(type_str)
    if entity.get('description'):
        parts.append(entity['description'])
    if entity.get('category_labels'):
        parts.append(f"Categories: {entity['category_labels']}")
    location_parts = []
    for field in ('locality', 'region', 'country'):
        val = entity.get(field)
        if val:
            location_parts.append(val)
    if location_parts:
        parts.append(', '.join(location_parts))
    return '. '.join(parts)
```

Example: `"ABC Plumbing LLC. Business: A business or company. Licensed plumbing contractor serving residential and commercial clients. Categories: Customer|Vendor. Newark, NJ, US"`

---

## Environment Variables

```bash
# Feature toggle
ENTITY_WEAVIATE_ENABLED=false          # set "true" to enable Weaviate entity indexing
ENTITY_WEAVIATE_ENV=dev                # collection prefix: devxxxEntityIndex, prodxxxEntityIndex, testxxxEntityIndex

# Weaviate connection (reuse existing env vars)
WEAVIATE_REST_URL=https://weaviate.example.com/v1
WEAVIATE_HTTP_HOST=weaviate.example.com
WEAVIATE_GRPC_HOST=grpc.weaviate.example.com
WEAVIATE_GRPC_PORT=50051

# Auth (reuse existing env vars)
WEAVIATE_KEYCLOAK_URL=https://keycloak.example.com/realms/.../token
WEAVIATE_CLIENT_ID=weaviate-client
WEAVIATE_CLIENT_SECRET=...
WEAVIATE_USERNAME=admin@example.com
WEAVIATE_PASSWORD=...

# Optional tuning
ENTITY_WEAVIATE_COLLECTION=EntityIndex   # collection name (default: EntityIndex)
ENTITY_WEAVIATE_SYNC_BATCH=100           # batch size for bulk sync (default: 100)
```

When `ENTITY_WEAVIATE_ENABLED=false` (default), no Weaviate connection is made and topic search endpoints return a 503 with a message indicating the feature is disabled.

---

## Sync Process

### Initial / Full Sync

A separate process (or management command) that:

1. Connects to PostgreSQL and fetches all active entities with type info and aliases
2. Connects to Weaviate and ensures the `EntityIndex` collection exists
3. Upserts all entities in batches (using `entity_id` as the deterministic UUID)
4. Optionally deletes Weaviate objects for entities that no longer exist in PostgreSQL

```python
class EntityWeaviateSync:
    """Sync entity table to Weaviate EntityIndex collection."""

    async def full_sync(self, pool, weaviate_client):
        """Full sync: PostgreSQL → Weaviate."""

    async def incremental_sync(self, entity_id: str, action: str):
        """Single entity sync on create/update/delete."""

    def entity_to_weaviate_object(self, entity: dict) -> dict:
        """Convert entity dict to Weaviate object properties."""

    def ensure_collection(self, weaviate_client):
        """Create EntityIndex collection if it doesn't exist."""
```

#### Admin Script Location

Sync scripts live in `entity_registry/` at the project root (not inside `vitalgraph/`):

```bash
# Full sync: PostgreSQL → Weaviate
python entity_registry/weaviate_sync.py --full

# Single entity sync
python entity_registry/weaviate_sync.py --entity-id e_abc123

# Dry run (report what would change)
python entity_registry/weaviate_sync.py --full --dry-run
```

### Incremental Sync (Real-Time)

On entity create/update/delete/alias change in `entity_registry_impl.py`:

1. After updating PostgreSQL and the local dedup index, also upsert/delete in Weaviate
2. Uses the same `entity_id` → deterministic UUID mapping for idempotent upserts
3. If Weaviate is unavailable, log a warning but don't fail the PostgreSQL operation

### Cross-Worker Sync

For the Weaviate case, cross-worker sync is not needed because Weaviate is a shared external service — all workers write to the same Weaviate instance. Unlike the in-memory dedup index, there's no per-worker state to synchronize.

### UUID Mapping

Weaviate uses UUIDs for object IDs. We derive a deterministic UUID from `entity_id`:

```python
import uuid

def entity_id_to_weaviate_uuid(entity_id: str) -> str:
    """Deterministic UUID from entity_id for idempotent upserts."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"vitalgraph:entity:{entity_id}"))
```

---

## Endpoints

### Unified Entity Search (`/search/entity`)

A single endpoint for semantic, geo, identifier, and combined searches. All modes go through Weaviate natively.

```
GET /api/registry/search/entity?q=plumbing+contractor&type_key=business&min_certainty=0.7
GET /api/registry/search/entity?q=manufacturing&latitude=37.78&longitude=-122.42&radius_km=10
GET /api/registry/search/entity?latitude=37.78&longitude=-122.42&radius_km=10
GET /api/registry/search/entity?identifier_value=DUNS-123&identifier_namespace=DUNS
```

**Parameters:**
| Param | Required | Description |
|-------|----------|-------------|
| `q` | no | Free-text query (vectorized). At least one of `q`, geo params, or `identifier_value` required |
| `identifier_value` | no | Search by external identifier value |
| `identifier_namespace` | no | Identifier namespace (requires `identifier_value`) |
| `type_key` | no | Filter by entity type key |
| `category_key` | no | Filter by entity category key |
| `country` | no | Filter by country |
| `region` | no | Filter by region/state |
| `locality` | no | Filter by city |
| `latitude` | no | Center latitude for geo range |
| `longitude` | no | Center longitude for geo range |
| `radius_km` | no | Radius in km for geo range filter |
| `limit` | no | Max results (default 20) |
| `min_certainty` | no | Minimum Weaviate certainty (default 0.7) |

**Search modes:**
- **q only**: Semantic vector search on entities
- **geo only**: Entities with a location within the radius (via cross-reference)
- **q + geo**: Semantic search restricted to entities near a point
- **identifier**: Find entities by external identifier (native Weaviate filter)
- **Any combination**: Results are filtered by all provided criteria

### Location Search (`/search/location`)

Supports three search modes (combinable with geo + property filters):
- **`q`**: Semantic vector search on location name, description, search_text (near_text)
- **`address`**: BM25 keyword search on address_line_1, address_line_2
- **Neither**: Geo + property filters only

```
GET /api/registry/search/location?latitude=37.78&longitude=-122.42&radius_km=10
    &location_type_key=headquarters&country_code=US
GET /api/registry/search/location?latitude=37.78&longitude=-122.42&radius_km=50
    &q=distribution+center
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

## Pydantic Models

```python
class EntityTopicSearchResult(BaseModel):
    entity_id: str
    primary_name: str
    description: Optional[str]
    type_key: str
    type_label: str
    country: Optional[str]
    region: Optional[str]
    locality: Optional[str]
    category_keys: List[str] = []
    score: float           # Weaviate certainty (0-1)
    distance: float        # Weaviate distance

class EntityTopicSearchResponse(BaseModel):
    success: bool
    query: str
    filters: Dict[str, str]
    results: List[EntityTopicSearchResult]
```

---

## Source Files

```
vitalgraph/
  entity_registry/
    entity_weaviate.py              # Weaviate sync + query logic
    entity_weaviate_schema.py       # Collection schema definition
  endpoint/
    entity_registry_endpoint.py     # Add /search/topic route

entity_registry/                      # Admin scripts (project root)
  weaviate_sync.py                    # Full + incremental Weaviate sync
  README.md                           # Admin script documentation

test_scripts/
  entity_registry/
    test_entity_weaviate.py         # Direct tests for sync + search
```

---

## Client Updates

`EntityRegistryClientEndpoint` provides two unified search methods:

```python
async def search_entity(
    self,
    q: Optional[str] = None,
    identifier_value: Optional[str] = None,
    identifier_namespace: Optional[str] = None,
    type_key: Optional[str] = None,
    category_key: Optional[str] = None,
    country: Optional[str] = None,
    region: Optional[str] = None,
    locality: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    radius_km: Optional[float] = None,
    limit: int = 20,
    min_certainty: float = 0.7,
) -> EntitySearchResponse:
    """Unified entity search: semantic, geo, identifier, or combinations."""

async def search_location(
    self,
    latitude: float,
    longitude: float,
    radius_km: float,
    location_type_key: Optional[str] = None,
    country: Optional[str] = None,
    limit: int = 20,
) -> LocationSearchResponse:
    """Find locations within a radius of a point."""
```

---

## Implementation Phases

### Phase 5a: Plan
- This document

### Phase 5b: Core Weaviate Integration
1. Create `entity_weaviate_schema.py` — collection schema definition
2. Create `entity_weaviate.py` — `EntityWeaviateIndex` class
   - `from_env()` — connect to Weaviate using env vars
   - `ensure_collection()` — create/validate collection
   - `upsert_entity(entity_id, entity)` — add/update single entity
   - `delete_entity(entity_id)` — remove from Weaviate
   - `search_topic(query, filters, limit)` — vector + filter search
   - `full_sync(pool)` — bulk sync from PostgreSQL
3. Add `ENTITY_WEAVIATE_ENABLED` env var check

### Phase 5c: Integration
1. Wire `EntityWeaviateIndex` into `entity_registry_impl.py` — upsert/delete on entity changes
2. Add `/search/topic` endpoint to `entity_registry_endpoint.py`
3. Add Pydantic models
4. Wire into app startup in `vitalgraphapp_impl.py`
5. Update client endpoint

### Phase 5d: Sync Process
1. Create management command / script for full sync
2. Add incremental sync hooks in `entity_registry_impl.py`
3. Handle Weaviate unavailability gracefully (log, don't fail)

### Phase 5e: Tests
1. Direct tests — schema creation, upsert, delete, topic search
2. Client tests — `/search/entity` and `/search/location` endpoints
3. Sync tests — full sync, incremental sync

### Phase 5f: Identifier Search — ✅ Complete
1. ✅ Added `identifier_keys` and `identifier_values` TEXT_ARRAY properties to EntityIndex
2. ✅ `_enrich_with_identifiers` in full_sync, `list_identifiers` in single-entity upsert
3. ✅ `_build_filters` supports `identifier_value` + `identifier_namespace`
4. ✅ All search methods pass identifier params to Weaviate natively
5. ✅ `/search/entity` endpoint uses Weaviate filters (no PostgreSQL intersect)

### Phase 5g: Auth Fix — ✅ Complete
1. ✅ Added `offline_access` to Keycloak scope
2. ✅ `_get_jwt_token()` returns full token data (access_token, refresh_token, expires_in)
3. ✅ `Auth.bearer_token()` receives refresh_token + expires_in for auto-refresh
4. ✅ Verified token refresh works past 60s / 300s expiry

---

## Query Examples

### "Find businesses in NJ that do plumbing"

```python
# Via client SDK
results = await client.entity_registry.search_entity(
    q="plumbing contractor", type_key="business", country="US",
    min_certainty=0.7, limit=10,
)
```

### "Find entity by DUNS number"

```python
results = await client.entity_registry.search_entity(
    identifier_value="123456", identifier_namespace="DUNS",
)
```

### "Find businesses near San Francisco doing consulting"

```python
results = await client.entity_registry.search_entity(
    q="consulting", type_key="business",
    latitude=37.78, longitude=-122.42, radius_km=20,
    min_certainty=0.5,
)
```

### "Find vendor businesses that do software consulting"

```python
results = await client.entity_registry.search_entity(
    q="software consulting services",
    type_key="business", category_key="vendor", limit=10,
)
```

### "Find entities near a point (geo only)"

```python
results = await client.entity_registry.search_entity(
    latitude=40.74, longitude=-74.17, radius_km=10,
    type_key="business",
)
```
