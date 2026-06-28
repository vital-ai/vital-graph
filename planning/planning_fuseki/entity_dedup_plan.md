# Entity Registry: Near-Duplicate Detection Plan

## Implementation Status

| Phase | Status | Notes |
|-------|--------|-------|
| **4a** Plan | ✅ Done | This document |
| **4b** Core `entity_dedup.py` | ✅ Done | `EntityDedupIndex` with per-variant LSH indexing |
| **4b** Dependencies | ✅ Done | `datasketch>=1.6.0`, `rapidfuzz>=3.0.0` in pyproject.toml |
| **4b** Wire into `entity_registry_impl.py` | ✅ Done | create/update/delete/alias lifecycle |
| **4c** `/similar` endpoint + Pydantic models | ✅ Done | `SimilarEntityResult`, `SimilarEntityResponse` |
| **4c** App startup wiring | ✅ Done | `EntityDedupIndex.from_env()` in `vitalgraphapp_impl.py` |
| **4c** Client `find_similar` | ✅ Done | `EntityRegistryClientEndpoint.find_similar()` |
| **4c** MemoryDB compatibility | ✅ Done | TLS, ACL auth, env vars in code + plan |
| **4d** Direct tests | ✅ Done | 21/21 passing (`test_scripts/entity_registry/test_dedup.py`) |
| **4d** Client tests | ✅ Done | Integrated into `test_entity_registry_endpoint.py` (117/117 total) |
| **4e** Cross-worker dedup sync | ✅ Done | PostgreSQL LISTEN/NOTIFY via SignalManager |
| **4f** `type_key` filter on `/search/similar` | ✅ Done | Stored in entity cache, post-retrieval filter |

---

## Overview

Add near-duplicate detection to the Entity Registry using a two-layer approach:

1. **datasketch MinHash LSH** — fast candidate blocking (sub-linear lookup)
2. **RapidFuzz** — precise string similarity scoring on candidates

This enables two workflows:
- **On-create check**: When adding a new entity, return potential duplicates in the response (non-blocking — entity is still created)
- **Standalone search**: A dedicated "find similar entities" endpoint for ad-hoc dedup queries (single or small batch)

---

## Architecture

### MinHash Signature

Each entity gets a MinHash signature built from:
- `primary_name` (shingled)
- All `alias_name` values (shingled)
- `country`, `region`, `locality` (as whole tokens, lowercased)

Shingling strategy: character n-grams (k=3) on lowercased, whitespace-normalized text. Location fields are added as whole tokens prefixed by field name (e.g. `country:us`, `region:california`) to avoid collisions with name shingles.

### Per-Variant LSH Indexing

Each name variant (primary_name, each alias) is indexed as a **separate LSH entry** with a compound key `entity_id::idx`. This ensures short names like "IBM" get their own MinHash signature and match queries with high Jaccard similarity, rather than being diluted in a combined signature with longer names.

During query, compound keys are collapsed back to unique entity IDs via a `set()`, so each entity appears at most once in the results regardless of how many of its variants matched. RapidFuzz scoring then picks the best match across all variants.

```python
def build_shingles(entity: dict, k: int = 3) -> set:
    """Build shingle set from entity fields for MinHash."""
    shingles = set()

    # Name shingles
    names = [entity['primary_name']]
    for alias in (entity.get('aliases') or []):
        names.append(alias['alias_name'])

    for name in names:
        normalized = name.lower().strip()
        for i in range(len(normalized) - k + 1):
            shingles.add(normalized[i:i+k])

    # Location tokens (whole values, prefixed)
    for field in ('country', 'region', 'locality'):
        val = entity.get(field)
        if val:
            shingles.add(f"{field}:{val.lower().strip()}")

    return shingles
```

### LSH Index Configuration

```python
from datasketch import MinHash, MinHashLSH

# Tuning parameters
NUM_PERM = 128          # number of permutations (higher = more accurate, more memory)
LSH_THRESHOLD = 0.3     # Jaccard similarity threshold for candidate retrieval
                        # 0.3 is intentionally loose — RapidFuzz refines later
```

- **`NUM_PERM = 128`**: Standard choice. Good accuracy/memory tradeoff for <1M entities.
- **`LSH_THRESHOLD = 0.3`**: Low threshold to cast a wide net. Better to have false positives (filtered by RapidFuzz) than miss true duplicates.

### RapidFuzz Scoring

Candidates from MinHash LSH are scored with RapidFuzz using multiple metrics:

```python
from rapidfuzz import fuzz

def score_candidate(query_name: str, candidate_name: str) -> dict:
    """Score a candidate match using multiple RapidFuzz metrics."""
    return {
        'ratio': fuzz.ratio(query_name, candidate_name),
        'partial_ratio': fuzz.partial_ratio(query_name, candidate_name),
        'token_sort_ratio': fuzz.token_sort_ratio(query_name, candidate_name),
        'token_set_ratio': fuzz.token_set_ratio(query_name, candidate_name),
    }
```

The **composite score** is the max of `token_sort_ratio` and `token_set_ratio` (these handle word reordering and subset matching well for entity names like "Acme Corp" vs "Corporation of Acme").

Default thresholds:
- **`score >= 90`**: High confidence duplicate
- **`score >= 70`**: Likely duplicate, review recommended
- **`score >= 50`**: Possible match

---

## Storage Backends

The LSH index supports two backends, selectable via configuration:

### In-Memory (default)

```python
lsh = MinHashLSH(threshold=0.3, num_perm=128)
```

- Rebuilt on app startup by loading all active entities from PostgreSQL
- New entities added to the index on creation
- Fast, simple, no external dependencies beyond datasketch
- Suitable for <1M entities

### Redis-Backed (local Redis)

```python
from datasketch import MinHashLSH

lsh = MinHashLSH(
    threshold=0.3, num_perm=128,
    storage_config={
        'type': 'redis',
        'redis': {'host': 'localhost', 'port': 6379},
    }
)
```

- Persists across restarts
- Shared across multiple app workers
- Required for large-scale deployments or multi-process setups

### AWS MemoryDB Compatibility

datasketch's Redis storage uses only basic Redis data structure commands, all of which are fully supported by AWS MemoryDB:

| Category | Commands Used |
|----------|-------------|
| **Hash** | `HSET`, `HDEL`, `HKEYS`, `HVALS`, `HEXISTS`, `HLEN` |
| **List** | `RPUSH`, `LRANGE`, `LREM`, `LLEN` |
| **Set** | `SADD`, `SMEMBERS`, `SREM`, `SCARD` |
| **Key** | `DELETE`, `EXISTS` |
| **Pipeline** | `MULTI`/`EXEC` transactions |

**No Lua scripting, no `KEYS` glob scan, no pub/sub** — all MemoryDB-safe.

#### MemoryDB-Specific Requirements

1. **TLS required**: MemoryDB enforces TLS. The `redis-py` client must be configured with `ssl=True` and optionally `ssl_cert_reqs='none'` for self-signed certs.
2. **ACL authentication**: MemoryDB uses Redis ACL. Provide `username` and `password` in the connection config.
3. **Cluster mode**: MemoryDB supports cluster mode. datasketch's storage uses key-prefixed hash/set operations which work in non-cluster (single-shard) mode. For cluster mode, all keys from a single LSH instance share a prefix and can be routed to the same shard using Redis hash tags if needed.
4. **Port**: MemoryDB default port is `6379` (same as Redis).

#### MemoryDB Connection Example

```python
lsh = MinHashLSH(
    threshold=0.3, num_perm=128,
    storage_config={
        'type': 'redis',
        'redis': {
            'host': 'my-cluster.xxxxxx.memorydb.us-east-1.amazonaws.com',
            'port': 6379,
            'username': 'default',
            'password': 'my-auth-token',
            'ssl': True,
            'ssl_cert_reqs': None,  # or path to CA bundle
        },
    }
)
```

### Configuration (environment variables)

```bash
# Feature toggle
ENTITY_DEDUP_ENABLED=true           # set "false" to disable minhash dedup entirely

# Backend selection
ENTITY_DEDUP_BACKEND=memory         # "memory" or "redis"

# Redis / MemoryDB connection (only when BACKEND=redis)
ENTITY_DEDUP_REDIS_HOST=localhost
ENTITY_DEDUP_REDIS_PORT=6379
ENTITY_DEDUP_REDIS_USERNAME=        # optional, for MemoryDB ACL
ENTITY_DEDUP_REDIS_PASSWORD=        # optional, for MemoryDB auth token
ENTITY_DEDUP_REDIS_SSL=false        # set "true" for MemoryDB

# Tuning (optional)
ENTITY_DEDUP_NUM_PERM=128           # MinHash permutations
ENTITY_DEDUP_THRESHOLD=0.3          # LSH Jaccard threshold
```

When `ENTITY_DEDUP_ENABLED=false`, no dedup index is created, the `/similar` endpoint returns an empty result set, and no cross-worker notifications are sent.

---

## New Source Files

```
vitalgraph/
  entity_registry/
    entity_dedup.py              # MinHash/LSH index + RapidFuzz scoring
```

No new endpoint file needed — the dedup functionality is exposed through:
- Existing `entity_registry_impl.py` (on-create integration)
- New route added to existing `entity_registry_endpoint.py`

---

## `entity_dedup.py` — Class Design

```python
class EntityDedupIndex:
    """Near-duplicate detection for the Entity Registry.

    Uses datasketch MinHash LSH for candidate blocking and
    RapidFuzz for precise string similarity scoring.
    """

    def __init__(self, num_perm=128, threshold=0.3, storage_config=None):
        ...

    # Index management
    async def initialize(self, pool):
        """Load all active entities from DB and build LSH index."""

    def add_entity(self, entity_id: str, entity: dict):
        """Add/update an entity in the LSH index."""

    def remove_entity(self, entity_id: str):
        """Remove an entity from the LSH index."""

    # Query
    def find_similar(self, entity: dict, limit: int = 10,
                     min_score: float = 50.0) -> list[dict]:
        """Find similar entities. Returns scored candidates sorted by score desc.

        Each result:
        {
            'entity_id': str,
            'primary_name': str,
            'score': float,           # 0-100, composite RapidFuzz score
            'score_detail': {         # individual metric scores
                'token_sort_ratio': float,
                'token_set_ratio': float,
                'ratio': float,
                'partial_ratio': float,
            },
            'match_level': str,       # 'high', 'likely', 'possible'
        }
        """

    # Internal
    def _build_minhash(self, entity: dict) -> MinHash:
        """Build MinHash signature for an entity."""

    def _score_pair(self, query: dict, candidate: dict) -> dict:
        """Score a query-candidate pair using RapidFuzz."""

    def _get_name_variants(self, entity: dict) -> list[str]:
        """Get all name variants (primary + aliases) for scoring."""
```

---

## Integration Points

### 1. On-Create Check

In `entity_registry_impl.py` → `create_entity()`:

```python
async def create_entity(self, ...) -> dict:
    # ... existing creation logic ...

    # After entity is created, check for potential duplicates
    if self.dedup_index:
        entity_data = await self.get_entity(entity_id, include_aliases=True)
        duplicates = self.dedup_index.find_similar(entity_data, limit=5, min_score=50.0)
        # Exclude self from results
        duplicates = [d for d in duplicates if d['entity_id'] != entity_id]
        # Add to index
        self.dedup_index.add_entity(entity_id, entity_data)
        entity_data['potential_duplicates'] = duplicates

    return entity_data
```

The `potential_duplicates` field is **informational only** — the entity is still created. The caller decides what to do (ignore, merge, create same-as, etc.).

### 2. Standalone Search Endpoint

New route in `entity_registry_endpoint.py`:

```
GET /api/registry/similar?name=Acme+Corp&country=US&limit=10&min_score=50
```

Response:
```json
{
    "success": true,
    "query": {"name": "Acme Corp", "country": "US"},
    "candidates": [
        {
            "entity_id": "e_abc123",
            "primary_name": "Acme Corporation",
            "score": 92.5,
            "match_level": "high",
            "score_detail": { ... }
        },
        ...
    ]
}
```

### 3. Index Lifecycle

- **Startup**: `EntityDedupIndex.initialize(pool)` called during app startup, after entity registry tables are ensured
- **Create**: `add_entity()` called after successful entity creation
- **Delete**: `remove_entity()` called after soft-delete (optional — soft-deleted entities could remain in index for matching)
- **Update**: `remove_entity()` + `add_entity()` on name/alias changes

### 4. Cross-Worker Sync (ECS Multi-Instance)

Each ECS instance keeps an in-memory dedup index. Changes are synchronized across instances via PostgreSQL `LISTEN/NOTIFY` using the existing `SignalManager`:

```
Channel: vitalgraph_entity_dedup
Payload: {"action": "add"|"remove", "entity_id": "e_xxx"}
```

**Flow:**
1. Instance A creates/updates/deletes entity → updates local index + sends `NOTIFY vitalgraph_entity_dedup`
2. PostgreSQL broadcasts to all listeners (including instance A)
3. Instances B, C receive notification → re-fetch entity from PostgreSQL → update local index
4. Instance A receives its own notification → idempotent re-apply (no-op effectively)

**Wiring:**
- `EntityRegistryImpl.__init__` accepts optional `signal_manager`
- `_notify_dedup_change(action, entity_id)` sends the NOTIFY after local index update
- `_handle_dedup_notification(data)` registered as callback on `CHANNEL_ENTITY_DEDUP`
- Callback registered at startup in `vitalgraphapp_impl.py`

**Properties:**
- No Redis/MemoryDB dependency needed
- Leverages existing PostgreSQL notification infrastructure
- Eventual consistency window: milliseconds (pg NOTIFY latency)
- Safe for restarts: full index rebuilt from PostgreSQL on startup

### 5. MemoryDB Sync Process (Production)

In production the dedup backend is AWS MemoryDB (`ENTITY_DEDUP_BACKEND=redis`). MemoryDB is a shared persistent store, so cross-worker pg NOTIFY sync is not needed for the index itself. However, a separate sync process is required to handle:

- **Initial population**: When a new MemoryDB cluster is provisioned or flushed
- **Drift recovery**: If MemoryDB data diverges from PostgreSQL (e.g. after a failover)
- **Bulk re-index**: After schema changes or MinHash parameter tuning

#### Sync Script

A management command that:
1. Connects to PostgreSQL and fetches all active entities with aliases
2. Connects to MemoryDB via the same env vars used by the app
3. Clears the existing LSH index keys (prefixed, safe)
4. Re-inserts all entities into the MinHash LSH index in batches

```bash
# Full sync: PostgreSQL → MemoryDB
python entity_registry/dedup_sync.py --full

# Single entity sync
python entity_registry/dedup_sync.py --entity-id e_abc123

# Dry run (report what would change)
python entity_registry/dedup_sync.py --full --dry-run
```

Admin scripts live in `entity_registry/` at the project root (alongside `weaviate_sync.py`). See also `entity_weaviate_plan.md` for the analogous Weaviate sync.

---

## Pydantic Models

```python
class SimilarEntityResult(BaseModel):
    entity_id: str
    primary_name: str
    type_key: Optional[str]         # entity type key
    score: float
    match_level: str                # 'high', 'likely', 'possible'
    score_detail: Dict[str, float]

class SimilarEntityResponse(BaseModel):
    success: bool
    candidates: List[SimilarEntityResult]

class EntityCreateResponse(BaseModel):  # updated
    success: bool
    entity_id: str
    entity_uri: str
    entity: EntityResponse
    potential_duplicates: Optional[List[SimilarEntityResult]] = None
```

---

## Client Updates

Add to `EntityRegistryEndpoint` (client):

```python
async def find_similar(self, name: str, country: str = None,
                       region: str = None, limit: int = 10,
                       min_score: float = 50.0) -> SimilarEntityResponse:
    """Find entities similar to the given name."""
```

The `create_entity` response already includes `potential_duplicates` when available — no client change needed for that.

---

## Dependencies

```
datasketch>=1.6.0
rapidfuzz>=3.0.0
```

Both are pure Python with C extensions (rapidfuzz) or numpy (datasketch). No heavy infrastructure required.

---

## Test Plan

### Direct Tests (`test_scripts/entity_registry/test_dedup.py`)

| Test | Description |
|------|-------------|
| `test_exact_name_match` | Same name → score ~100 |
| `test_similar_name` | "Acme Corp" vs "Acme Corporation" → high score |
| `test_abbreviation` | "IBM" vs "International Business Machines" → moderate score via aliases |
| `test_different_entities` | "Acme Corp" vs "Widget Inc" → low/no score |
| `test_location_boost` | Same name + same country scores higher than same name + different country |
| `test_index_add_remove` | Add entity, find it, remove it, gone |
| `test_on_create_duplicates` | Create similar entity, verify `potential_duplicates` in response |
| `test_min_score_filter` | Only candidates above threshold returned |
| `test_empty_index` | No crash on empty index |
| `test_redis_backend` | (optional) Verify Redis storage if available |

### Client Tests (`vitalgraph_client_test/test_entity_dedup.py`)

| Test | Description |
|------|-------------|
| `test_find_similar_endpoint` | Hit `/similar` endpoint, verify scored results |
| `test_create_with_duplicates` | Create entity, check `potential_duplicates` in response |

---

## Implementation Phases

### Phase 4b: Core Dedup Index ✅
1. ✅ Add `datasketch` and `rapidfuzz` to dependencies
2. ✅ Create `entity_dedup.py` with `EntityDedupIndex`
3. ✅ Implement `build_shingles`, `_name_shingles`, `_build_minhash`, `_score_pair`
4. ✅ Implement `find_similar` (per-variant query), `add_entity` (per-variant index), `remove_entity`
5. ✅ Implement `initialize` (load from DB)
6. ✅ Support both in-memory and Redis/MemoryDB backends

### Phase 4c: Integration ✅
1. ✅ Wire `EntityDedupIndex` into `entity_registry_impl.py`
2. ✅ Call `add_entity` on create, `remove_entity` on delete, re-index on update/alias changes
3. ✅ Return `potential_duplicates` from `create_entity`
4. ✅ Add `/similar` endpoint
5. ✅ Add Pydantic models
6. ✅ Update client endpoint
7. ✅ Wire `EntityDedupIndex.from_env()` into app startup
8. ✅ MemoryDB compatibility (TLS, ACL auth, env vars)

### Phase 4d: Tests — ✅ Complete
1. ✅ Direct tests for dedup index (21/21 passing)
2. ✅ Client tests integrated into `test_entity_registry_endpoint.py`
3. ✅ Edge cases covered in endpoint tests

### Phase 4f: Entity Type Filter — ✅ Complete
1. ✅ `type_key` stored in `_entity_cache` during `initialize()` and `add_entity()`
2. ✅ `find_similar()` accepts `type_key` param for post-retrieval filtering
3. ✅ `find_similar_by_name()` passes `type_key` through
4. ✅ `SimilarEntityResult` model includes `type_key` field
5. ✅ `/search/similar` endpoint accepts `type_key` query parameter
