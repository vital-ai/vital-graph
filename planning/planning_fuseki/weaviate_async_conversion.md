# Weaviate Async Client Conversion Plan

**Status: COMPLETE** — Rebuild verified 2026-02-26

## Objective
Convert `EntityWeaviateIndex` from sync `WeaviateClient` to async `WeaviateAsyncClient`.

## Key API Differences (from docs)

| Sync | Async |
|------|-------|
| `weaviate.connect_to_custom(...)` | `weaviate.use_async_with_custom(...)` + `await client.connect()` |
| `client.collections.get("name")` | `client.collections.use("name")` (sync, local handle) |
| `client.collections.exists(name)` | `await client.collections.exists(name)` |
| `client.collections.create(**cfg)` | `await client.collections.create(**cfg)` |
| `client.collections.delete(name)` | `await client.collections.delete(name)` |
| `collection.data.insert(...)` | `await collection.data.insert(...)` |
| `collection.data.insert_many(...)` | `await collection.data.insert_many(...)` |
| `collection.data.update(...)` | `await collection.data.update(...)` |
| `collection.data.delete_by_id(...)` | `await collection.data.delete_by_id(...)` |
| `collection.data.reference_replace(...)` | `await collection.data.reference_replace(...)` |
| `collection.query.near_text(...)` | `await collection.query.near_text(...)` |
| `collection.query.hybrid(...)` | `await collection.query.hybrid(...)` |
| `collection.query.fetch_objects(...)` | `await collection.query.fetch_objects(...)` |
| `collection.query.fetch_object_by_id(...)` | `await collection.query.fetch_object_by_id(...)` |
| `collection.aggregate.over_all(...)` | `await collection.aggregate.over_all(...)` |
| `collection.config.get()` | `await collection.config.get()` |
| `collection.config.add_reference(...)` | `await collection.config.add_reference(...)` |
| `with collection.batch.dynamic() as b:` | **NOT available on async** — use `insert_many()` or `stream()` |
| `collection.iterator()` | Use cursor-based `fetch_objects(after=...)` pagination |
| `client.close()` | `await client.close()` |

## Batch Strategy Change
- Sync client used `batch.dynamic()` context manager for bulk inserts
- Async client does NOT support `dynamic()`, `fixed_size()`, `rate_limit()`
- **Use `insert_many()` instead**: pass list of `DataObject(properties=..., uuid=...)` per batch
- This is actually simpler and gives explicit control over batch boundaries

## Token Refresh Thread
- Current: background thread calls `_reconnect()` which creates a new sync client
- Async: thread can create the client object (sync) but NOT `await connect()`
- Solution: thread stores new client + sets `_needs_reconnect` flag; next async method calls `await _ensure_connected()` which connects if needed

## Files to Modify

### 1. `vitalgraph/entity_registry/entity_weaviate.py` (PRIMARY — 1606 lines)

Every method touching the Weaviate client becomes `async`:

- **Imports**: add `asyncio`, `DataObject`; type hint `WeaviateAsyncClient`
- **`__init__`**: add `_needs_reconnect`, `_pending_client` fields
- **`_create_client`**: `connect_to_custom` → `use_async_with_custom` (returns unconnected client)
- **`from_env`**: becomes `async`, calls `await client.connect()`
- **`_reconnect`**: creates async client, sets `_needs_reconnect = True`
- **`_ensure_connected`**: new async method, checks flag, calls `await connect()`
- **`collection` / `location_collection` properties**: use `client.collections.use(name)` (sync)
- **`ensure_collection`**: → `async`
- **`_ensure_cross_references`**: → `async`
- **`rebuild_collection`**: → `async`
- **`upsert_entity`**: → `async`
- **`delete_entity`**: → `async`
- **`upsert_entities_batch`**: → `async`, use `insert_many()`
- **`upsert_location`**: → `async`
- **`delete_location`**: → `async`
- **`upsert_locations_batch`**: → `async`, use `insert_many()`
- **`set_entity_location_refs`**: → `async`
- **`full_sync`**: already async, replace `batch.dynamic()` with `insert_many()`
- **`location_sync`**: already async, replace `batch.dynamic()` with `insert_many()`
- **`search_topic`**: → `async`
- **`search_hybrid`**: → `async`
- **`search_locations_near`**: → `async`
- **`search_topic_near`**: → `async`
- **`search_entities_near`**: → `async`
- **`get_status`**: → `async`
- **`list_all_collections`**: → `async`
- **`close`**: → `async`

Stale object detection in `full_sync`/`location_sync`:
- Replace `collection.iterator()` with cursor-based pagination using `fetch_objects(after=cursor_uuid, limit=1000)`

### 2. `vitalgraph/entity_registry/entity_weaviate_ops.py` (WeaviateMixin)

Add `await` to all weaviate method calls:
- `self.weaviate_index.upsert_entity(entity)` → `await self.weaviate_index.upsert_entity(entity)`
- `self.weaviate_index.delete_entity(...)` → `await ...` (also make `_weaviate_delete_entity` async)
- `self.weaviate_index.upsert_location(...)` → `await ...`
- `self.weaviate_index.delete_location(...)` → `await ...`
- `self.weaviate_index.set_entity_location_refs(...)` → `await ...`

### 3. `vitalgraph/impl/vitalgraphapp_impl.py`

- `EntityWeaviateIndex.from_env()` → `await EntityWeaviateIndex.from_env()`

### 4. `entity_registry/entity_admin.py`

- `self.weaviate = EntityWeaviateIndex.from_env()` → `self.weaviate = await EntityWeaviateIndex.from_env()` (already in async `connect()`)
- `self.weaviate.rebuild_collection()` → `await self.weaviate.rebuild_collection()`
- `self.weaviate.get_status()` → `await self.weaviate.get_status()`
- `self.weaviate.list_all_collections()` → `await self.weaviate.list_all_collections()`
- `self.weaviate.close()` → `await self.weaviate.close()`
- Search methods: `self.weaviate.search_topic(...)` → `await ...`
- `self.weaviate.search_hybrid(...)` → `await ...`

### 5. `entity_registry/weaviate_admin.py`

- All method calls on `weaviate_index` need `await`
- Functions calling them need to become `async`

### 6. `entity_registry/weaviate_sync.py`

- `weaviate_index.rebuild_collection()` → `await ...`
- Already uses async functions

### 7. Test files (low priority, update as needed)

- `test_scripts/entity_registry/test_entity_weaviate.py`
- `test_scripts/entity_registry/test_entity_weaviate_location.py`
- `vitalgraph_client_test/test_weaviate_direct.py`

## Execution Order

1. Convert `entity_weaviate.py` (the core class)
2. Update `entity_weaviate_ops.py` (WeaviateMixin used by EntityRegistryImpl)
3. Update `vitalgraphapp_impl.py` (production app startup)
4. Update `entity_admin.py` (admin CLI)
5. Update `weaviate_admin.py` (standalone admin)
6. Update `weaviate_sync.py` (standalone sync)
7. Test with `entity_admin.py weaviate rebuild`

## Completion Results (2026-02-26)

### Rebuild Output
- **4,211 entities** upserted, 0 deleted (423s)
- **3,282 locations** upserted, 0 deleted (280s)
- **3,278 entity→location cross-refs** set
- **Total time**: 702.7s (~11.7 min) with batch_size=200
- **Two token refreshes** occurred mid-sync — both handled seamlessly

### Client Version
- Upgraded from `weaviate-client` **4.19.2** → **4.20.1**
- v4.20.0 added `batch.stream()` for async server-side batching (SSB)

### Server Version Issue
- Weaviate server is **v1.34.0**
- `batch.stream()` requires **server v1.36.0+** (server-side batching GA)
- Current approach uses `insert_many()` which works on all server versions
- **When the server is upgraded to 1.36+**, `full_sync` and `location_sync` can be
  refactored to use `async with collection.batch.stream() as batch:` for
  auto-tuned server-side batching with feedback flow

### Token Refresh Fix
- Initial run failed at ~5 min: token expired mid-sync because `_ensure_connected()`
  was only called once at the start of `full_sync`
- Fix: added `await self._ensure_connected()` inside `_flush_batch()` and
  `_flush_loc_batch()` so the client swaps to the refreshed token between batches
- Refresh thread runs every 270s (token expires in 300s), reconnect happens
  at the next batch boundary (~10-20s latency)

## Risks (resolved)
- ~~Breaking production callers if any sync path remains~~ — All callers updated, grep verified
- ~~Token refresh thread race conditions~~ — Lazy reconnect with `_needs_reconnect` flag works reliably
- ~~`iterator()` replacement may behave differently for stale detection~~ — Cursor-based pagination works
- ~~`insert_many` error handling differs from `batch.dynamic()`~~ — Errors checked via `response.has_errors`

## Future Work
- Upgrade Weaviate server to v1.36+ and switch to `batch.stream()` for SSB
- Update test files (`test_entity_weaviate.py`, `test_entity_weaviate_location.py`)
- Address `Dep024` deprecation warning: migrate `vectorizer_config` → `vector_config` in schema
