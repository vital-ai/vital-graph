# Entity Fuzzy: Redis/MemoryDB → PostgreSQL Migration Plan

## Status: ✅ COMPLETE

All phases implemented and tested. The PostgreSQL backend is production-ready.

| Phase | Status | Notes |
|-------|--------|-------|
| 1. DDL + `PostgreSQLFuzzyStorage` | ✅ Done | `entity_fuzzy_storage.py` |
| 2. `EntityFuzzyIndexPG` class | ✅ Done | `entity_fuzzy_pg.py` — full PG-backed index |
| 3. Native async API | ✅ Done | No thread offloading needed |
| 4. App integration + env config | ✅ Done | `ENTITY_FUZZY_BACKEND=postgresql` |
| 5. Integration tests | ✅ Done | `test_fuzzy_pg.py` — 5/5 pass, 212 entities indexed |
| 6. Rebuild script | ✅ Done | `scripts/migrate_fuzzy_redis_to_pg.py --rebuild` |

### Cutover Process

```bash
# 1. Build index from existing entity data (no Redis data needed)
python scripts/migrate_fuzzy_redis_to_pg.py --rebuild

# 2. Set environment variable
export ENTITY_FUZZY_BACKEND=postgresql

# 3. Restart service — Redis/MemoryDB is no longer needed for fuzzy
```

### Files Created

| File | Purpose |
|------|---------|
| `vitalgraph/entity_registry/entity_fuzzy_storage.py` | Async band/hash CRUD + advisory locks |
| `vitalgraph/entity_registry/entity_fuzzy_pg.py` | Full PG-backed MinHash LSH + RapidFuzz index |
| `test_scripts/entity_registry/test_fuzzy_pg.py` | Integration tests |
| `scripts/migrate_fuzzy_redis_to_pg.py` | Rebuild CLI (`--rebuild`, `--status`) |

### Files Modified

| File | Change |
|------|--------|
| `entity_registry_schema.py` | +3 fuzzy tables, +2 covering indexes |
| `entity_fuzzy_ops.py` | `FuzzyMixin` dispatches to PG or Redis backend |
| `entity_registry_impl.py` | Union type for fuzzy_index, PG init path |
| `entity_alias_ops.py` | PG backend dispatch for alias changes |
| `vitalgraphapp_impl.py` | `ENTITY_FUZZY_BACKEND` env switch |
| `.env.example` | Documents new config options |

---

## Motivation

The entity registry's near-duplicate detection currently uses **Redis/AWS MemoryDB** as a persistent backend for the datasketch MinHash LSH index. This adds infrastructure complexity, cost ($70-200/mo for MemoryDB), and operational overhead (TLS configuration, cluster mode handling, separate sync scripts, distributed locking). Since PostgreSQL is already the primary data store and we are consolidating search capabilities into PostgreSQL (pgvector, PostGIS, tsvector), migrating the fuzzy index to PostgreSQL eliminates the Redis dependency entirely.

### Current Pain Points

| Issue | Impact |
|-------|--------|
| Separate MemoryDB cluster ($70-200/mo) | Infrastructure cost |
| TLS + ACL + cluster mode configuration | Operational complexity |
| `fuzzy_sync.py` script to keep PG ↔ Redis in sync | Data consistency risk |
| 384-line `datasketch_cluster.py` for cluster compatibility | Code complexity |
| Distributed lock via Lua scripts | Fragile coordination |
| Event loop stalls from synchronous Redis calls | Latency spikes (350ms) |
| Two separate sync mechanisms (pg NOTIFY + Redis shared state) | Architectural confusion |

### Why PostgreSQL Works Here

- **Infrequent queries**: Fuzzy search happens on entity create/update and explicit "find similar" API calls — NOT on every read request
- **Small working set**: ~5.7M rows for 100k entities (fits in `shared_buffers`)
- **Acceptable latency**: 5-15ms per progressive query vs 3-10ms with Redis — negligible for the use case
- **Already connected**: asyncpg pool is available in every worker
- **Transactional consistency**: No divergence between entity data and fuzzy index
- **Cross-worker visibility**: Automatic (same database)
- **No cold-start problem**: Table is pre-populated, no init phase needed

---

## Current Architecture (Redis)

### Components

| Component | File | Purpose |
|-----------|------|---------|
| `EntityFuzzyIndex` | `vitalgraph/entity_registry/entity_fuzzy.py` (1603 lines) | Core MinHash LSH + RapidFuzz scoring |
| `datasketch_cluster.py` | `vitalgraph/entity_registry/datasketch_cluster.py` (384 lines) | Redis Cluster storage backend for datasketch |
| `entity_fuzzy_ops.py` | `vitalgraph/entity_registry/entity_fuzzy_ops.py` (214 lines) | Async mixin, cross-worker sync via pg NOTIFY |
| `fuzzy_sync.py` | `entity_registry/fuzzy_sync.py` (322 lines) | CLI sync script (PG → Redis) |
| `entity_registry_impl.py` | `vitalgraph/entity_registry/entity_registry_impl.py` | Integration: create/update/delete hooks |
| `entity_alias_ops.py` | `vitalgraph/entity_registry/entity_alias_ops.py` | Alias change → fuzzy re-index |

### Data Flow (Current)

```
Entity Create/Update
    │
    ├── Write to PostgreSQL (entity + entity_alias tables)
    │
    ├── Compute MinHash shingles (CPU, in-process)
    │   ├── Character trigram shingles (primary_name + aliases + location)
    │   └── Phonetic codes (Metaphone + Soundex per word)
    │
    ├── Insert into Redis (datasketch LSH)
    │   ├── Primary LSH: ~19 bands × variants
    │   ├── Phonetic LSH: ~19 bands × variants
    │   └── Fuzzy hash: entity_id → MD5
    │
    └── pg NOTIFY to other workers → they update their _entity_cache
```

### Query Flow (Current)

```
find_similar("Jonh Smth")
    │
    ├── Phase 1: Candidate Blocking (Redis)
    │   ├── Step 1: Primary LSH (progressive band query, 3 bands at a time)
    │   ├── Step 2: Phonetic LSH (if not enough candidates)
    │   └── Step 3: Typo variants (edit-distance-1, batch query)
    │   Result: set of candidate entity_ids
    │
    ├── Phase 1.5: Fetch candidate data from PostgreSQL
    │   └── SELECT entity + aliases for scoring
    │
    └── Phase 2: RapidFuzz scoring (in-process CPU)
        ├── token_sort_ratio, token_set_ratio
        ├── Phonetic bonus (+10 if codes match)
        └── Return ranked results
```

### Key Parameters

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `NUM_PERM` | 64 | MinHash permutations |
| `LSH_THRESHOLD` | 0.3 | Jaccard threshold for primary LSH |
| `PHONETIC_LSH_THRESHOLD` | 0.3 | Jaccard threshold for phonetic LSH |
| `SHINGLE_K` | 3 | Character n-gram size |
| `MIN_CANDIDATES` | 20 | Target candidate count for early stop |
| `MAX_CANDIDATES` | 5000 | Hard cap on candidates |
| `PHONETIC_BONUS` | 10.0 | Score bonus for phonetic match |
| `MIN_SCORE` | 50.0 | Default minimum result score |

### LSH Band Structure

With `num_perm=64` and `threshold=0.3`, datasketch calculates optimal band parameters (b bands of r rows each, where b×r = num_perm). Approximately 19-21 bands.

Each band stores: `band_hash → {entity_key_1, entity_key_2, ...}` where `entity_key = entity_id::variant_idx`.

---

## Target Architecture (PostgreSQL)

### New Tables

```sql
-- Band storage for primary MinHash LSH (character trigram shingles)
CREATE TABLE entity_fuzzy_band (
    band_id      SMALLINT NOT NULL,       -- 0..N (N ≈ 19 bands)
    band_hash    BYTEA NOT NULL,          -- MinHash band signature hash
    entity_key   TEXT NOT NULL,           -- entity_id::variant_idx
    PRIMARY KEY (band_id, band_hash, entity_key)
);

-- Band storage for phonetic MinHash LSH (Metaphone/Soundex codes)
CREATE TABLE entity_fuzzy_phonetic_band (
    band_id      SMALLINT NOT NULL,
    band_hash    BYTEA NOT NULL,
    entity_key   TEXT NOT NULL,
    PRIMARY KEY (band_id, band_hash, entity_key)
);

-- Fuzzy hash tracking (detects changes without full entity comparison)
CREATE TABLE entity_fuzzy_hash (
    entity_id    TEXT PRIMARY KEY,
    fuzzy_hash   CHAR(32) NOT NULL        -- MD5 of fuzzy-relevant fields
);

-- Covering indexes for fast band lookups
CREATE INDEX idx_fuzzy_band_lookup
    ON entity_fuzzy_band (band_id, band_hash) INCLUDE (entity_key);

CREATE INDEX idx_fuzzy_phonetic_lookup
    ON entity_fuzzy_phonetic_band (band_id, band_hash) INCLUDE (entity_key);
```

### Size Estimates (100k entities)

| Table | Rows | Est. Size |
|-------|------|-----------|
| `entity_fuzzy_band` | 100k × 3 variants × 19 bands = ~5.7M | ~200MB |
| `entity_fuzzy_phonetic_band` | 100k × 3 variants × 19 bands = ~5.7M | ~200MB |
| `entity_fuzzy_hash` | 100k | ~5MB |
| **Total** | | **~405MB** |

At this size, the working set fits entirely in `shared_buffers` (typically 4-8GB on RDS). All lookups will be in-memory after warm-up.

### Query Implementation

**Single band batch lookup** (replaces Redis `getmany` per band):

```sql
-- Progressive query: 3 bands at a time (equivalent to current band_batch_size=3)
SELECT entity_key
FROM entity_fuzzy_band
WHERE band_id = $1 AND band_hash = ANY($2::bytea[])
UNION ALL
SELECT entity_key
FROM entity_fuzzy_band
WHERE band_id = $3 AND band_hash = ANY($4::bytea[])
UNION ALL
SELECT entity_key
FROM entity_fuzzy_band
WHERE band_id = $5 AND band_hash = ANY($6::bytea[]);
```

**With candidate counting** (for progressive early-stop logic):

```sql
SELECT entity_key, COUNT(*) AS band_hits
FROM entity_fuzzy_band
WHERE (band_id, band_hash) IN (
    -- band 0 hashes
    ($1, $2), ($1, $3),
    -- band 1 hashes
    ($4, $5), ($4, $6),
    -- band 2 hashes
    ($7, $8), ($7, $9)
)
GROUP BY entity_key
HAVING COUNT(*) >= 2;
```

**Entity insert** (replaces Redis pipeline flush):

```sql
-- Insert one entity into all bands (single statement)
INSERT INTO entity_fuzzy_band (band_id, band_hash, entity_key)
VALUES ($1, $2, $3), ($4, $5, $6), ...  -- one row per band
ON CONFLICT DO NOTHING;
```

**Entity remove**:

```sql
DELETE FROM entity_fuzzy_band WHERE entity_key LIKE $1 || '::%';
DELETE FROM entity_fuzzy_phonetic_band WHERE entity_key LIKE $1 || '::%';
DELETE FROM entity_fuzzy_hash WHERE entity_id = $1;
```

Or with exact key knowledge:

```sql
DELETE FROM entity_fuzzy_band
WHERE entity_key = ANY($1::text[]);  -- ['eid::0', 'eid::1', 'eid::2']
```

### Performance Comparison

| Operation | Redis/MemoryDB | PostgreSQL (B-tree, hot cache) |
|-----------|---------------|-------------------------------|
| Single band lookup | ~0.5ms | ~1-2ms |
| Progressive query (3-9 bands) | 3-10ms | 5-15ms |
| Full query with typo variants | 200-600ms | 250-700ms |
| Bulk init (100k entities) | 30-60s (pipelines) | 10-30s (COPY/batch INSERT) |
| Single entity add | ~2ms (pipeline) | ~1ms (single INSERT) |
| Single entity remove | ~2ms | ~1ms |
| Cross-worker visibility | Immediate (shared Redis) | Immediate (same DB) |

**Key insight**: The 5-15ms difference per query is negligible because:
1. Fuzzy queries are infrequent (entity create/update, ~10/sec max)
2. Phase 2 scoring (RapidFuzz) takes 50-200ms regardless
3. The total user-facing latency is dominated by network + scoring, not band lookup

---

## New Class: `PostgreSQLFuzzyStorage`

Replace the datasketch Redis storage with a purpose-built PostgreSQL storage layer:

```python
class PostgreSQLFuzzyStorage:
    """PostgreSQL-backed storage for MinHash LSH band data.

    Replaces datasketch's Redis/MemoryDB storage with direct SQL,
    eliminating the Redis dependency entirely.
    """

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    # -- Band operations (replace datasketch storage) --

    async def insert_bands(
        self,
        table: str,  # 'entity_fuzzy_band' or 'entity_fuzzy_phonetic_band'
        entries: List[Tuple[int, bytes, str]],  # (band_id, band_hash, entity_key)
    ):
        """Batch insert entity into all LSH bands."""
        ...

    async def query_bands(
        self,
        table: str,
        band_queries: List[Tuple[int, List[bytes]]],  # (band_id, [hash1, hash2, ...])
    ) -> Dict[str, int]:
        """Batch band lookup. Returns entity_key → band_hit_count."""
        ...

    async def remove_entity(
        self,
        table: str,
        entity_keys: List[str],  # ['eid::0', 'eid::1', ...]
    ):
        """Remove all band entries for an entity."""
        ...

    # -- Fuzzy hash operations --

    async def get_fuzzy_hash(self, entity_id: str) -> Optional[str]:
        ...

    async def set_fuzzy_hash(self, entity_id: str, hash_val: str):
        ...

    async def set_fuzzy_hashes_batch(self, hashes: Dict[str, str]):
        ...

    async def delete_fuzzy_hash(self, entity_id: str):
        ...

    # -- Bulk operations --

    async def bulk_insert_bands(
        self,
        table: str,
        entries: List[Tuple[int, bytes, str]],
        batch_size: int = 5000,
    ):
        """COPY-based bulk insert for initialization."""
        ...

    async def truncate_bands(self, table: str):
        """Fast truncate for rebuild."""
        ...
```

---

## Migration Strategy

### Phase 1: Create PostgreSQL Tables + Storage Layer

1. Add table DDL to entity registry migration script (`entity_registry/migrate.py`)
2. Implement `PostgreSQLFuzzyStorage` class
3. Unit tests for storage operations

### Phase 2: Refactor `EntityFuzzyIndex`

Replace the datasketch LSH usage with direct PostgreSQL operations:

| Current (datasketch + Redis) | New (PostgreSQL) |
|------------------------------|------------------|
| `MinHashLSH(storage_config=redis_config)` | `PostgreSQLFuzzyStorage(pool)` |
| `lsh.insert(key, minhash)` | `storage.insert_bands(table, entries)` |
| `lsh.remove(key)` | `storage.remove_entity(table, keys)` |
| `hashtable.getmany(*hashes)` | `storage.query_bands(table, queries)` |
| `_bulk_write_lsh(lsh, entries)` | `storage.bulk_insert_bands(table, entries)` |
| `_get_redis_client()` | Not needed (use pool) |
| Lua lock script | `pg_advisory_lock()` or just transactions |
| `ClusterBuffer` pipeline flush | Single multi-row INSERT |

**What stays the same:**
- `build_shingles()` — unchanged (pure CPU)
- `_build_minhash()` — unchanged (datasketch MinHash for hashing only, no storage)
- `_phonetic_codes()` — unchanged
- `_score_pair()` — unchanged (RapidFuzz)
- `_progressive_query()` logic — adapted to use SQL instead of Redis getmany
- `_entity_cache` — unchanged (in-memory for RapidFuzz scoring)
- Cross-worker pg NOTIFY sync — still needed for `_entity_cache` invalidation

**Important**: We still use `datasketch.MinHash` for computing hash signatures — we only eliminate `MinHashLSH` (the storage/index layer). The band hash computation (`lsh._H(minhash.hashvalues[start:end])`) needs to be extracted or reimplemented as a standalone function.

### Phase 3: Update `EntityFuzzyIndex` API

Make all fuzzy operations natively async (no more `asyncio.to_thread` needed):

```python
class EntityFuzzyIndex:
    def __init__(self, pool: asyncpg.Pool, ...):
        self.storage = PostgreSQLFuzzyStorage(pool)
        ...

    # These become natively async (no thread offload)
    async def add_entity(self, entity_id: str, entity: Dict[str, Any]):
        ...

    async def remove_entity(self, entity_id: str):
        ...

    async def get_candidate_ids(self, entity: Dict[str, Any]) -> Set[str]:
        ...

    async def initialize(self, since=None, chunk_size=5000) -> int:
        ...
```

This eliminates the event loop stall problem entirely — no synchronous Redis calls, no thread offloading needed.

### Phase 4: Remove Redis Dependencies

Files to delete or simplify:

| File | Action |
|------|--------|
| `vitalgraph/entity_registry/datasketch_cluster.py` | **Delete** (384 lines) |
| `entity_registry/fuzzy_sync.py` | **Delete** (322 lines) — no longer needed |
| `scripts/sync_fuzzy_index.py` | **Delete** — no longer needed |
| `vitalgraph/entity_registry/entity_fuzzy.py` | **Major refactor** — remove all Redis code |

Environment variables to remove:

```
ENTITY_FUZZY_BACKEND          # no longer needed (always PostgreSQL)
ENTITY_FUZZY_REDIS_HOST       # removed
ENTITY_FUZZY_REDIS_PORT       # removed
ENTITY_FUZZY_REDIS_USERNAME   # removed
ENTITY_FUZZY_REDIS_PASSWORD   # removed
ENTITY_FUZZY_REDIS_SSL        # removed
ENTITY_FUZZY_REDIS_CLUSTER    # removed
```

### Phase 5: Update Tests

| Current Test | Action |
|--------------|--------|
| `test_fuzzy.py` (21 tests) | Update to use PostgreSQL backend |
| `test_fuzzy_standalone.py` (44 tests) | Update |
| `test_fuzzy_extensions.py` (52 tests) | Update |
| `test_fuzzy_redis.py` (22 tests) | **Replace** with PostgreSQL integration test |
| `test_fuzzy_typo_diagnostic.py` (6 tests) | Update |
| `test_fuzzy_thread_offload.py` | **Delete** — no longer relevant (natively async) |

---

## Distributed Locking

### Current (Redis)

```python
# Lua script for atomic release
_LUA_RELEASE = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""
```

### New (PostgreSQL Advisory Lock)

```python
async def _acquire_init_lock(self) -> bool:
    """Acquire advisory lock for fuzzy index initialization."""
    async with self.pool.acquire() as conn:
        # pg_try_advisory_lock returns immediately (non-blocking)
        # Lock ID: hash of 'entity_fuzzy_init'
        return await conn.fetchval(
            "SELECT pg_try_advisory_lock(hashtext('entity_fuzzy_init'))"
        )

async def _release_init_lock(self):
    """Release advisory lock."""
    async with self.pool.acquire() as conn:
        await conn.execute(
            "SELECT pg_advisory_unlock(hashtext('entity_fuzzy_init'))"
        )
```

Advisory locks are:
- Per-session (automatically released on disconnect)
- Cluster-safe (all workers share the same PostgreSQL instance)
- No TTL management needed (unlike Redis NX+EX pattern)
- No Lua scripts needed

---

## Cross-Worker Sync

### What Changes

The current system has two sync mechanisms:
1. **Redis shared state** — all workers read/write the same MemoryDB
2. **pg NOTIFY** — used for the in-memory `_entity_cache` on each worker

With PostgreSQL storage, mechanism #1 becomes unnecessary (the band tables ARE the shared state). Mechanism #2 remains for `_entity_cache` invalidation.

### What Stays

```python
# Still needed: pg NOTIFY for _entity_cache updates
async def _handle_fuzzy_notification(self, data: dict):
    """Other worker changed an entity → update our local scoring cache."""
    if action == 'add':
        entity = await self.get_entity(entity_id)
        self._entity_cache[entity_id] = {...}
    elif action == 'remove':
        self._entity_cache.pop(entity_id, None)
    elif action == 'reload_full':
        await self._reload_entity_cache()
```

The band table updates are transactional (part of the same DB write) and immediately visible to all workers without NOTIFY.

---

## Bulk Initialization

### Current (Redis)

```python
# Stream from PG → compute shingles → pipeline to Redis
# Requires separate fuzzy_sync.py script
# Distributed lock to prevent concurrent init across workers
```

### New (PostgreSQL)

```python
async def initialize(self, since=None, chunk_size=5000) -> int:
    """Rebuild fuzzy index from entity table.

    For full rebuild: TRUNCATE + COPY (fastest).
    For incremental: DELETE changed + INSERT.
    """
    async with self.pool.acquire() as conn:
        if not since:
            # Full rebuild — truncate is instant
            await conn.execute("TRUNCATE entity_fuzzy_band")
            await conn.execute("TRUNCATE entity_fuzzy_phonetic_band")
            await conn.execute("TRUNCATE entity_fuzzy_hash")

        # Stream entities and compute bands
        bands_buffer = []
        phonetic_buffer = []
        hash_buffer = {}

        async for row in conn.cursor(ENTITY_QUERY, ...):
            # Compute MinHash bands (pure CPU)
            for band_id, band_hash in compute_band_hashes(entity):
                bands_buffer.append((band_id, band_hash, entity_key))

            if len(bands_buffer) >= 50000:
                await self._flush_bands(conn, bands_buffer, phonetic_buffer, hash_buffer)
                bands_buffer.clear()
                ...

        # Final flush
        await self._flush_bands(conn, bands_buffer, phonetic_buffer, hash_buffer)
```

**No separate sync script needed** — initialization is part of the service startup (for in-memory cache) or a simple management command.

---

## Band Hash Computation (Extracted from datasketch)

Currently, band hashes are computed by datasketch internally via `lsh._H(minhash.hashvalues[start:end])`. We need to extract this:

```python
import struct
import hashlib

def compute_band_hashes(
    minhash_values: np.ndarray,  # from MinHash.hashvalues
    band_ranges: List[Tuple[int, int]],  # [(0, 3), (3, 6), ...] — b bands of r rows
) -> List[Tuple[int, bytes]]:
    """Compute band hash for each band range.

    Replicates datasketch's MinHashLSH._H() logic.
    Returns list of (band_id, band_hash_bytes).
    """
    results = []
    for band_id, (start, end) in enumerate(band_ranges):
        # datasketch uses sha1 of the packed band values
        band_values = minhash_values[start:end]
        h = hashlib.sha1(band_values.tobytes()).digest()
        results.append((band_id, h))
    return results
```

The band ranges are computed once at init time based on `num_perm` and `threshold` using datasketch's `_optimal_param` function (or we precompute and store them).

---

## Implementation Phases

| Phase | Scope | Files | Status |
|-------|-------|-------|--------|
| 1 | DDL + `PostgreSQLFuzzyStorage` class | `entity_fuzzy_storage.py`, `entity_registry_schema.py` | ✅ Done |
| 2 | New `EntityFuzzyIndexPG` class | `entity_fuzzy_pg.py` | ✅ Done |
| 3 | Native async API + integration | `entity_fuzzy_ops.py`, `entity_registry_impl.py`, `entity_alias_ops.py` | ✅ Done |
| 4 | App init + env config | `vitalgraphapp_impl.py`, `.env.example` | ✅ Done |
| 5 | Integration tests | `test_fuzzy_pg.py` | ✅ Done |
| 6 | Rebuild script | `scripts/migrate_fuzzy_redis_to_pg.py` | ✅ Done |

**Note**: No data migration from Redis is needed. The PostgreSQL entity table is the source of truth — we simply re-index from it using `--rebuild`. The old Redis/memory backends remain functional for backward compatibility.

---

## Dependencies Removed

After migration:

```diff
- redis>=4.0.0           # No longer needed for fuzzy (check if used elsewhere)
- datasketch>=1.6.0      # Still needed for MinHash computation (but not MinHashLSH storage)
```

Note: `datasketch` is still used for `MinHash` (signature computation). Only the `MinHashLSH` storage layer is replaced. If we want to fully eliminate `datasketch`, we can reimplement the MinHash permutation logic (~30 lines of numpy), but this is optional.

---

## AWS RDS Compatibility

All PostgreSQL features used are standard and available on RDS:

| Feature | Version | RDS Status |
|---------|---------|-----------|
| `BYTEA` type | All | ✅ Core |
| B-tree index with INCLUDE | PG 11+ | ✅ Supported |
| `TRUNCATE` | All | ✅ Core |
| `pg_advisory_lock` | All | ✅ Core |
| `ANY($1::bytea[])` array operations | All | ✅ Core |
| Async streaming cursors (asyncpg) | All | ✅ Supported |

No extensions required.

---

## Design Decisions (Resolved)

1. **Keep `_entity_cache` or fetch from PG on demand?**
   - **Decision**: Keep in-memory cache. Rebuilt on startup by streaming entity table.
   - Scoring needs all name variants per candidate — batch PG fetch for 5000 candidates would add 50ms.

2. **Incremental vs full rebuild on startup?**
   - **Decision**: Band tables persist across restarts. Only `_entity_cache` needs rebuilding on startup.
   - The `initialize()` method streams the entity table and populates both bands + cache.

3. **Band hash algorithm compatibility?**
   - **Decision**: Extracted `compute_band_hash()` uses SHA1 of packed band values — identical to datasketch's `_H()`. Verified by test.

4. **Migration from Redis needed?**
   - **Decision**: No. PostgreSQL entity table is the source of truth. Run `--rebuild` to index into PG band tables directly. No Redis data transfer needed.

---

## Related Planning Documents

| Document | Relevance |
|----------|-----------|
| `planning_fuseki/entity_fuzzy_plan.md` | Original fuzzy architecture (Phase 4a-4f, all complete) |
| `planning_fuseki/entity_fuzzy_extensions_plan.md` | Phonetic + typo extensions (Phase 5a-5f, all complete) |
| `planning/fuzzy_thread_offload_plan.md` | Event loop stall fix (will be obsoleted by native async) |
| `planning_vector_geo/vector_geo_plan.md` | Broader PostgreSQL search consolidation context |
