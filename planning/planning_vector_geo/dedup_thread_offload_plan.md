# Entity Dedup Thread-Offload Plan

## Problem

Synchronous `datasketch` MinHash LSH operations with MemoryDB (Redis) storage
block the asyncio event loop during entity registry CRUD. Production logs show
~350ms stall bursts every time entity registry traffic spikes (e.g., Salesforce
sync batches every ~5 minutes).

### Blocking call sites

All in `vitalgraph/entity_registry/`:

| Call | File | Sync Redis ops |
|------|------|----------------|
| `dedup_index.add_entity()` | `entity_registry_impl.py:277` (create) | `lsh.insert()` × N variants + `phonetic_lsh.insert()` × N + `hset()` |
| `dedup_index.add_entity()` | `entity_registry_impl.py:472` (update) | same |
| `dedup_index.add_entity()` | `entity_alias_ops.py:77,111` (alias add/remove) | same |
| `dedup_index.add_entity()` | `entity_dedup_ops.py:207` (cross-worker sync) | same |
| `dedup_index.remove_entity()` | `entity_registry_impl.py:503` (delete) | `lsh.remove()` × N + `phonetic_lsh.remove()` × N + `hdel()` |
| `dedup_index.remove_entity()` | `entity_dedup_ops.py:202,211` (cross-worker sync) | same |
| `dedup_index.get_candidate_ids()` | `entity_dedup_ops.py:134` (find dupes) | `lsh.query()` × M + `phonetic_lsh.query()` × M |

Each `lsh.insert()` / `lsh.remove()` / `lsh.query()` issues one or more
synchronous Redis commands via the `datasketch` library. With MemoryDB backend,
each round-trip is ~1-5ms, but they accumulate to 50-350ms+ under concurrent
entity creation with multiple name variants.

## Approach

Wrap all synchronous dedup index calls in `asyncio.to_thread()` at the call
sites. The `datasketch` library and its Redis storage are inherently synchronous,
so the cleanest fix is to offload the entire call to a thread pool worker.

### Why not make datasketch async

- `datasketch.MinHashLSH` with Redis storage uses the synchronous `redis-py`
  client internally. Making it async would require forking datasketch or
  replacing it with a custom implementation — not worth the effort for this
  use case.
- `asyncio.to_thread()` is the same pattern used successfully for the
  ANALYZE/VACUUM thread-offload fix.

## Implementation Steps

### Step 1: Add async wrappers to EntityDedupIndex

Add three async methods to `entity_dedup.py`:

```python
async def async_add_entity(self, entity_id: str, entity: Dict[str, Any]):
    """Thread-offloaded add_entity for use from async code."""
    await asyncio.to_thread(self.add_entity, entity_id, entity)

async def async_remove_entity(self, entity_id: str):
    """Thread-offloaded remove_entity for use from async code."""
    await asyncio.to_thread(self.remove_entity, entity_id)

async def async_get_candidate_ids(self, entity: Dict[str, Any],
                                   query_names=None) -> set:
    """Thread-offloaded get_candidate_ids for use from async code."""
    return await asyncio.to_thread(
        self.get_candidate_ids, entity, query_names
    )
```

### Step 2: Update call sites

Replace synchronous calls with async wrappers:

**`entity_registry_impl.py`** (create_entity, update_entity, delete_entity):
```python
# Before:
self.dedup_index.add_entity(entity_id, entity_for_index)

# After:
await self.dedup_index.async_add_entity(entity_id, entity_for_index)
```

**`entity_alias_ops.py`** (add_alias, remove_alias):
```python
# Before:
self.dedup_index.add_entity(entity_id, entity)

# After:
await self.dedup_index.async_add_entity(entity_id, entity)
```

**`entity_dedup_ops.py`** (_handle_dedup_notification, find_duplicates_for_entity):
```python
# Before:
self.dedup_index.remove_entity(entity_id)
self.dedup_index.add_entity(entity_id, entity)
candidate_ids = self.dedup_index.get_candidate_ids(entity)

# After:
await self.dedup_index.async_remove_entity(entity_id)
await self.dedup_index.async_add_entity(entity_id, entity)
candidate_ids = await self.dedup_index.async_get_candidate_ids(entity)
```

### Step 3: Thread safety

`add_entity()` and `remove_entity()` mutate `self._entity_cache` (a plain
Python dict) and call `self.lsh.insert()` / `self.lsh.remove()`. Since
`asyncio.to_thread()` runs on the default thread pool executor, two concurrent
calls could race on the cache.

`get_candidate_ids()` does **not** need locking:
- It only calls `lsh.query()` / `phonetic_lsh.query()`, which issue Redis
  `SMEMBERS`/`LRANGE` reads via pipeline — pure reads, atomic server-side.
- It does not touch `_entity_cache`.
- A query seeing a partially-inserted entity (one LSH band written, not all)
  would just return a slightly incomplete candidate set, which is harmless
  since candidates go through a scoring step afterward.

**Implementation**: Add a `threading.Lock` to `EntityDedupIndex.__init__` that
guards only `add_entity` and `remove_entity`. Leave `get_candidate_ids`
unlocked so queries can run concurrently with each other and with writes.

```python
self._mutation_lock = threading.Lock()

def add_entity(self, ...):
    with self._mutation_lock:
        ...  # existing body

def remove_entity(self, ...):
    with self._mutation_lock:
        ...  # existing body

# get_candidate_ids — no lock needed
```

This is sufficient because:
- Individual mutations are short (5-50ms)
- The lock only blocks other thread pool workers, not the event loop
- `_entity_cache` is a plain dict, not thread-safe — must serialize writes
- Reads (queries) are Redis-level atomic and don't touch the cache

### Step 4: Preserve bulk init path

The existing bulk initialization in `entity_dedup.py` (`initialize()` and
`_bulk_insert_entities()`) already runs via `asyncio.to_thread()` at line 540.
No changes needed there.

### Step 5: Create tests

Create `test_scripts/test_dedup_thread_offload.py` — an integration test that
exercises the async dedup wrappers and verifies event loop health.

#### Test 1: Basic async CRUD (no stalls)

- Create an entity via the API, verify `async_add_entity` was used (check logs)
- Update the entity (change name), verify dedup index updated
- Delete the entity, verify removed from dedup index
- **Assert**: event loop monitor reports zero stalls throughout

#### Test 2: Concurrent entity creation

- Spawn N (e.g., 20) concurrent `POST /api/registry/entities` requests using
  `asyncio.gather()` with an `httpx.AsyncClient`
- Each entity has 2-3 aliases (multiple name variants = multiple LSH inserts)
- **Assert**: all creates succeed, no 500 errors
- **Assert**: dedup index contains all N entities (query each)
- **Assert**: event loop monitor reports zero stalls (or stalls < 50ms)

#### Test 3: Thread safety under contention

- Directly instantiate `EntityDedupIndex` with MemoryDB config
- Spawn 10 threads via `concurrent.futures.ThreadPoolExecutor`, each calling
  `add_entity()` with different entity IDs simultaneously
- **Assert**: `_entity_cache` has all 10 entities
- **Assert**: LSH index has correct number of entries (no missing/corrupt keys)
- Then spawn 10 threads calling `remove_entity()` for half the entities
- **Assert**: only the remaining 5 are in the cache and LSH

#### Test 4: Duplicate detection still works

- Create 2 entities with similar names (e.g., "Acme Corp" and "Acme Corporation")
- Call `find_duplicates_for_entity()` on the first entity
- **Assert**: second entity appears as a candidate
- This confirms `async_get_candidate_ids` returns correct results through the
  thread-offload path

#### Test 5: Event loop stall regression test

- Start the VitalGraph server locally (Docker)
- Run a burst of 50 entity creates via the API in rapid succession
- Scrape Docker logs for `EVENT LOOP STALL` warnings
- **Assert**: zero stall events during the burst
- This is the key regression test — it should fail before the fix and pass after

### Step 6: Run existing tests

Run the existing entity registry client tests to verify no regressions:

```bash
VITALGRAPH_CLIENT_ENVIRONMENT=local python vitalgraph_client_test/test_entity_registry.py
```

### Step 7: Production verification

After deploy, check CloudWatch for stall events during entity registry traffic:

```bash
AWS_PROFILE=cardiffprod aws logs filter-log-events \
  --log-group-name /ecs/vitalgraph-prod \
  --filter-pattern "EVENT LOOP STALL" \
  --start-time <deploy_timestamp_ms> \
  --region us-east-1
```

## Files to modify

| File | Changes |
|------|---------|
| `vitalgraph/entity_registry/entity_dedup.py` | Add `threading.Lock`, add `async_add_entity()`, `async_remove_entity()`, `async_get_candidate_ids()` |
| `vitalgraph/entity_registry/entity_registry_impl.py` | 3 call sites → async wrappers |
| `vitalgraph/entity_registry/entity_alias_ops.py` | 2 call sites → async wrappers |
| `vitalgraph/entity_registry/entity_dedup_ops.py` | 3 call sites → async wrappers |

## Test files to create

| File | Purpose |
|------|---------|
| `test_scripts/test_dedup_thread_offload.py` | Tests 1-5: async wrapper correctness, concurrency, thread safety, duplicate detection, stall regression |

## Risk

- **Low**: Same `asyncio.to_thread()` pattern already proven for ANALYZE/VACUUM.
- **Thread safety**: Mitigated by the `threading.Lock` in Option A.
- **Latency**: No increase — the operations take the same time, they just don't
  block the event loop anymore.
- **Bulk init**: Unchanged — already threaded.

## Expected impact

- Eliminates ~350ms event loop stalls during entity registry traffic
- Combined with the ANALYZE thread-offload fix, should eliminate all known
  production stall sources
