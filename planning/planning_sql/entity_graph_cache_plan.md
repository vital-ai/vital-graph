# Entity Graph Cache — In-Memory Caching with NOTIFY Invalidation

**Date**: 2026-04-25
**Backend**: `sparql_sql` (primary), `fuseki_postgresql` (same pattern)
**Status**: Planning
**Depends on**: `signal_management_plan.md` (NOTIFY/LISTEN infrastructure)

---

## 1. Problem Statement

Every `GET /kgentities?include_entity_graph=true` request executes a full SPARQL query
against PostgreSQL, converts bindings to GraphObjects, and serializes to quads — even
when the entity graph has not changed since the last request. Entity graphs are read-heavy
and write-infrequent, making them ideal candidates for caching.

### Current Call Chain (no caching)

```
KGEntitiesEndpoint._get_entity_by_uri(include_entity_graph=True)
  → KGEntityGetProcessor.get_entity(mode=WITH_GRAPH)
    → backend_adapter.get_entity_graph(space_id, graph_id, entity_uri)
      → GraphObjectRetriever.get_entity_graph_as_objects()
        → execute SPARQL query (every time)
        → _bindings_to_objects (every time)
```

### Performance Impact

- Entity graph SPARQL query: ~15–50ms (depending on graph size)
- `_bindings_to_objects` conversion: ~1–5ms
- Quad serialization: ~1–3ms
- **Total per request**: ~20–60ms, fully avoidable on cache hit

---

## 2. Design

### 2.1 Cache Location and Format

In-memory LRU cache at the endpoint level, keyed by
`(space_id, graph_id, entity_uri)`. Stores **compressed serialized quads** —
the JSON-serialized quad list is compressed with `zlib` before caching.

This means a cache hit skips the entire pipeline: SPARQL query → `_bindings_to_objects`
→ `graphobjects_to_quad_list` → JSON serialization. On cache hit we decompress
and return the quad list directly.

```python
import zlib, json

class EntityGraphCache:
    # Cache: (space_id, graph_id, entity_uri) → (compressed_bytes, byte_size, timestamp)
    _cache: OrderedDict = OrderedDict()
    _CACHE_MAX_SIZE: int = 1000          # max entries (LRU eviction)
    _CACHE_TTL_SECONDS: float = 900      # 15 minutes safety net
    _CACHE_MAX_BYTES: int = 256 * 1024 * 1024  # 256 MB total cache memory cap
    _total_bytes: int = 0                # tracked sum of compressed sizes
```

**Why compressed quads**:
- Quad dicts are flat JSON — `zlib` typically achieves 5–10× compression on
  repetitive RDF property URIs
- Cache hit returns `List[dict]` directly — no GraphObject conversion needed
- Memory is precisely tracked via `len(compressed_bytes)` per entry
- `zlib.compress`/`zlib.decompress` adds <1ms for typical entity graphs

### 2.2 Cache Key

```python
cache_key = (space_id, graph_id, entity_uri)
```

This is specific enough to avoid cross-space/cross-graph collisions while being the
natural lookup key for entity graph retrieval.

### 2.3 Cached Path

The cache sits in the endpoint's `_get_entity_by_uri` method, wrapping the
full get → convert → serialize pipeline:

```
Cache HIT:  decompress → return quads          (~0.5ms)
Cache MISS: SPARQL → GraphObjects → quads → compress + store → return quads (~20–60ms)
```

| Call | Cached? | Notes |
|------|---------|-------|
| `_get_entity_by_uri(include_entity_graph=True)` | Yes | Primary target |
| `_get_entities_by_uris(include_entity_graph=True)` | Yes | Per-entity cache lookup |
| `get_entity_graph_as_objects()` | No (downstream) | Skipped entirely on cache hit |
| `list_objects()` | No | Paginated listing, not cacheable |

### 2.4 Cache Invalidation

Three invalidation triggers:

#### A. Local Write Path (same instance)

Entity CRUD operations invalidate the cache entry for the affected entity_uri
immediately after the write completes.

**Write paths that must invalidate**:
- `kgentities_endpoint.py` — create, update, delete entity
- `kgentities_endpoint.py` — create, update, delete frames (frame writes change the entity graph)
- `kgentities_endpoint.py` — batch operations

```python
_entity_graph_cache.invalidate(space_id, graph_id, entity_uri)
```

#### B. Cross-Instance NOTIFY (other instances)

A new notification channel carries the entity URI so other instances can invalidate
their local cache entry.

**New channel**: `vitalgraph_entity_graph`
**Constant**: `CHANNEL_ENTITY_GRAPH = "vitalgraph_entity_graph"`

**Payload**:
```json
{
  "type": "updated|deleted",
  "space_id": "my_space",
  "graph_id": "urn:my_graph",
  "entity_uri": "http://example.org/entity/123",
  "timestamp": "..."
}
```

**Signal flow**:
```
Instance A: update entity graph
  → write to PostgreSQL
  → invalidate local cache entry
  → NOTIFY vitalgraph_entity_graph,
      '{"type":"updated","space_id":"...","graph_id":"...","entity_uri":"..."}'

Instance B: receive NOTIFY
  → _handle_entity_graph_signal(data)
  → invalidate_entity_graph(space_id, graph_id, entity_uri)
  → next GET reloads from DB
```

#### C. TTL Safety Net

Cache entries expire after `_CACHE_TTL_SECONDS` (15 minutes) regardless of
invalidation signals. This bounds staleness if a NOTIFY is lost (connection drop
during reconnect window).

### 2.5 Graph-Level Invalidation

When a graph is cleared or deleted (`notify_graph_changed`), all cache entries for
that graph must be invalidated. This uses the existing `CHANNEL_GRAPH` signal:

```python
# On CHANNEL_GRAPH signal with type "deleted" or "updated":
_entity_graph_cache.invalidate_graph(space_id, graph_id)
# → removes ALL entity graph cache entries for that graph
```

### 2.6 Space-Level Invalidation

When a space is deleted (`notify_space_changed`), all cache entries for that space
must be invalidated:

```python
# On CHANNEL_SPACE signal with type "deleted":
_entity_graph_cache.invalidate_space(space_id)
# → removes ALL entity graph cache entries for that space
```

---

## 3. Notification Channel Addition

### 3.1 SignalManager Changes

Add to `signal_manager.py`:

```python
CHANNEL_ENTITY_GRAPH = "vitalgraph_entity_graph"

# In SignalManager.__init__ callbacks dict:
CHANNEL_ENTITY_GRAPH: [],

# New method:
async def notify_entity_graph_changed(
    self, space_id: str, graph_id: str, entity_uri: str,
    signal_type: str = SIGNAL_TYPE_UPDATED
):
    payload = json.dumps({
        "type": signal_type,
        "space_id": space_id,
        "graph_id": graph_id,
        "entity_uri": entity_uri,
        "timestamp": str(asyncio.get_event_loop().time()),
    })
    await self._send_notification(CHANNEL_ENTITY_GRAPH, payload)
```

### 3.2 Startup Wiring

Add to `vitalgraphapp_impl.py` startup_event(), alongside existing cache invalidation
registration:

```python
# Entity graph cache invalidation callback
from vitalgraph.signal.signal_manager import CHANNEL_ENTITY_GRAPH

async def _handle_entity_graph_signal(data: dict):
    space_id = data.get("space_id", "")
    graph_id = data.get("graph_id", "")
    entity_uri = data.get("entity_uri", "")
    if space_id and graph_id and entity_uri:
        _entity_graph_cache.invalidate(space_id, graph_id, entity_uri)

signal_manager.register_callback(CHANNEL_ENTITY_GRAPH, _handle_entity_graph_signal)
```

Also register handlers for existing channels that should cascade-invalidate:

```python
# Graph deletion/clear → invalidate all entity graph cache entries for that graph
# (register on CHANNEL_GRAPH, in addition to existing handlers)

# Space deletion → invalidate all entity graph cache entries for that space
# (register on CHANNEL_SPACE, in addition to existing handlers)
```

---

## 4. Write Path Integration

### 4.1 Entity CRUD

Every entity write must:
1. Perform the database write
2. Invalidate the local cache entry
3. Send NOTIFY for cross-instance invalidation

**Files to modify**:

| File | Operations | Invalidation |
|------|-----------|-------------|
| `kgentities_endpoint.py` | create, update, upsert, delete, batch | `_entity_graph_cache.invalidate(space_id, graph_id, entity_uri)` + NOTIFY |
| `kgentity_frame_create_impl.py` | create frames | `_entity_graph_cache.invalidate(space_id, graph_id, entity_uri)` + NOTIFY |
| `kgentity_frame_update_impl.py` | update frames | `_entity_graph_cache.invalidate(space_id, graph_id, entity_uri)` + NOTIFY |

### 4.2 Batch Operations

For batch create/update/delete, invalidate each affected entity_uri individually.
A single NOTIFY per entity is acceptable since batch sizes are typically small (10–50).

For bulk imports (hundreds+), consider a graph-level invalidation instead:
```python
_entity_graph_cache.invalidate_graph(space_id, graph_id)
# + NOTIFY with entity_uri="" to signal graph-wide invalidation
```

### 4.3 SPARQL UPDATE Path

Direct SPARQL UPDATE operations (`sparql_update_endpoint.py`) bypass the entity
endpoint layer. The V2 pipeline knows exactly which quads are inserted, deleted,
or modified. We use the grouping property `hasKGGraphURI` to resolve affected
subjects back to their owning entity URIs for targeted cache invalidation.

#### Entity Membership via `hasKGGraphURI`

Every object in an entity graph (frames, slots, edges) carries a grouping property:

```
<frame_uri> haley:hasKGGraphURI <entity_uri> .
<slot_uri>  haley:hasKGGraphURI <entity_uri> .
<edge_uri>  haley:hasKGGraphURI <entity_uri> .
```

Full predicate: `http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI`

If a SPARQL UPDATE touches subject `?s`, and `?s` has `hasKGGraphURI ?entity_uri`
in the store, then `?entity_uri` is the entity whose cached graph must be
invalidated.

#### Available Data: The Update Ops

The V2 pipeline compiles SPARQL to typed update ops (`jena_types.py`), each
carrying `QuadPattern` lists with concrete `RDFNode` fields:

```python
@dataclass
class QuadPattern:
    graph: Optional[RDFNode]
    subject: RDFNode          # ← the affected subject
    predicate: RDFNode
    object: RDFNode
```

| Op Type | Quads Available |
|---------|----------------|
| `UpdateDataInsert` | `op.quads` — concrete inserted quads |
| `UpdateDataDelete` | `op.quads` — concrete deleted quads |
| `UpdateModify` | `op.delete_quads` + `op.insert_quads` — concrete templates |
| `UpdateDeleteWhere` | `op.quads` — pattern quads (may have variables) |
| `UpdateClear/Drop` | Graph-level — no individual quads |

#### Resolution Strategy

Pure in-memory — no extra DB queries. Two rules applied to every quad in the
update ops:

1. **Subject is a cached entity**: if the subject URI matches a key in the
   entity graph cache, invalidate that cache entry directly.
2. **Quad is a `hasKGGraphURI` triple**: if `predicate == hasKGGraphURI`,
   then `object` is the entity URI — invalidate that cache entry.

```python
HAS_KG_GRAPH_URI = "http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI"

def collect_entity_uris_to_invalidate(
    ops: List[UpdateOp],
    space_id: str,
    cache: OrderedDict,   # EntityGraphCache._cache
) -> Set[str]:
    """Scan changed quads and return entity URIs that need cache invalidation.
    
    No DB queries — only checks the in-memory cache and inspects quad predicates.
    """
    entity_uris = set()
    
    for op in ops:
        quads = []
        if isinstance(op, UpdateDataInsert):
            quads = op.quads
        elif isinstance(op, UpdateDataDelete):
            quads = op.quads
        elif isinstance(op, UpdateModify):
            quads = op.delete_quads + op.insert_quads
        elif isinstance(op, UpdateDeleteWhere):
            quads = op.quads
        # UpdateClear/Drop are graph-level, handled separately
        
        for q in quads:
            sub_uri = getattr(q.subject, 'uri', None)
            pred_uri = getattr(q.predicate, 'uri', None)
            obj_uri = getattr(q.object, 'uri', None)
            
            # Rule 1: subject is a cached entity → invalidate it
            # Cache key is (space_id, graph_id, entity_uri)
            if sub_uri and (space_id, graph_id, sub_uri) in cache:
                entity_uris.add(sub_uri)
            
            # Rule 2: quad is ?sub hasKGGraphURI ?entity_uri → invalidate ?entity_uri
            if pred_uri == HAS_KG_GRAPH_URI and obj_uri:
                entity_uris.add(obj_uri)
    
    return entity_uris
```

#### Integration Point

```python
# In sparql_sql_space_impl.py execute_sparql_update(), after successful SQL execution:
entity_uris = collect_entity_uris_to_invalidate(
    cr.update_ops, space_id, _entity_graph_cache._cache
)
for entity_uri in entity_uris:
    _entity_graph_cache.invalidate(space_id, graph_id, entity_uri)
    await sm.notify_entity_graph_changed(space_id, graph_id, entity_uri,
                                          SIGNAL_TYPE_UPDATED)
```

#### Coverage by UPDATE Type

| SPARQL Pattern | Invalidation |
|----------------|--------------|
| `INSERT DATA { <entity_uri> <p> <o> }` | Rule 1: subject found in cache → invalidate |
| `DELETE DATA { <entity_uri> <p> <o> }` | Rule 1: subject found in cache → invalidate |
| `INSERT DATA { <sub> hasKGGraphURI <entity_uri> }` | Rule 2: predicate match → invalidate object |
| `DELETE DATA { <sub> hasKGGraphURI <entity_uri> }` | Rule 2: predicate match → invalidate object |
| `DELETE/INSERT WHERE` with concrete subjects | Rule 1 + Rule 2 as applicable |
| `DELETE WHERE { ?s ?p ?o }` (variable-only) | No concrete URIs → TTL safety net (15 min) |
| `CLEAR GRAPH <g>` | Existing `CHANNEL_GRAPH` → `invalidate_graph()` |
| `DROP GRAPH <g>` | Existing `CHANNEL_GRAPH` → `invalidate_graph()` |

The variable-only case (`DELETE WHERE { ?s ?p ?o }`) is rare in practice. The
15-minute TTL bounds staleness for these edge cases.

---

## 5. Cache Implementation

### 5.1 EntityGraphCache Class

Standalone cache class storing compressed serialized quads with precise memory
tracking. Two eviction triggers: LRU entry count and total byte cap.

```python
import time, zlib, json
from collections import OrderedDict
from typing import Optional, List, Dict, Tuple

class EntityGraphCache:
    """LRU cache for entity graph quads with zlib compression and memory tracking."""

    def __init__(
        self,
        max_entries: int = 1000,
        ttl_seconds: float = 900,
        max_bytes: int = 256 * 1024 * 1024,  # 256 MB
    ):
        self._cache: OrderedDict = OrderedDict()
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._max_bytes = max_bytes
        self._total_bytes: int = 0

    def get(self, space_id: str, graph_id: str, entity_uri: str) -> Optional[List[Dict]]:
        key = (space_id, graph_id, entity_uri)
        entry = self._cache.get(key)
        if entry is None:
            return None
        compressed, byte_size, ts = entry
        if time.time() - ts > self._ttl_seconds:
            self._remove(key)
            return None
        self._cache.move_to_end(key)
        return json.loads(zlib.decompress(compressed))

    def put(self, space_id: str, graph_id: str, entity_uri: str, quads: List[Dict]):
        key = (space_id, graph_id, entity_uri)
        # Remove old entry if present (reclaim bytes)
        if key in self._cache:
            self._remove(key)
        compressed = zlib.compress(json.dumps(quads).encode(), level=1)  # fast compression
        byte_size = len(compressed)
        # Skip caching if total memory would exceed cap
        if self._total_bytes + byte_size > self._max_bytes:
            return
        self._cache[key] = (compressed, byte_size, time.time())
        self._cache.move_to_end(key)
        self._total_bytes += byte_size
        # Evict oldest if over entry count
        while len(self._cache) > self._max_entries:
            self._evict_oldest()

    def invalidate(self, space_id: str, graph_id: str, entity_uri: str):
        self._remove((space_id, graph_id, entity_uri))

    def invalidate_graph(self, space_id: str, graph_id: str):
        keys = [k for k in self._cache if k[0] == space_id and k[1] == graph_id]
        for k in keys:
            self._remove(k)

    def invalidate_space(self, space_id: str):
        keys = [k for k in self._cache if k[0] == space_id]
        for k in keys:
            self._remove(k)

    def _remove(self, key: Tuple):
        entry = self._cache.pop(key, None)
        if entry:
            self._total_bytes -= entry[1]  # entry[1] = byte_size

    def _evict_oldest(self):
        if self._cache:
            _, entry = self._cache.popitem(last=False)
            self._total_bytes -= entry[1]

    @property
    def stats(self) -> Dict:
        return {
            "entries": len(self._cache),
            "total_bytes": self._total_bytes,
            "total_mb": round(self._total_bytes / (1024 * 1024), 2),
        }
```

### 5.2 Endpoint Integration

```python
# In kgentities_endpoint.py — cache instance shared across requests
_entity_graph_cache = EntityGraphCache()

async def _get_entity_by_uri(self, space_id, graph_id, uri, include_entity_graph, ...):
    if include_entity_graph:
        cached_quads = _entity_graph_cache.get(space_id, graph_id, uri)
        if cached_quads is not None:
            return QuadResultsResponse(results=cached_quads, total_count=len(cached_quads))

    # Normal path: query → GraphObjects → quads
    graph_objects = await get_processor.get_entity(...)
    quads = await asyncio.to_thread(graphobjects_to_quad_list, graph_objects or [], graph_id)

    if include_entity_graph and quads:
        _entity_graph_cache.put(space_id, graph_id, uri, quads)

    return QuadResultsResponse(results=quads, total_count=len(graph_objects) if graph_objects else 0)
```

### 5.3 Thread Safety

`EntityGraphCache` is accessed from the single asyncio event loop. The cache is accessed
only from async code (no thread-pool access), so no locking is needed. The
`_bindings_to_objects` call runs in `asyncio.to_thread` but the cache get/put happens
before/after that call, always on the event loop thread.

---

## 6. Signal Management Plan Updates

### 6.1 New Channel in Channel Table (§3)

| Channel | Constant | Payload Shape | Purpose |
|---------|----------|---------------|---------|
| `vitalgraph_entity_graph` | `CHANNEL_ENTITY_GRAPH` | `{"type": "...", "space_id": "...", "graph_id": "...", "entity_uri": "...", "timestamp": "..."}` | Cross-instance entity graph cache invalidation |

### 6.2 New Entry in Cache Inventory (§11.1)

| Cache | Location | Signal Channel | Callback |
|-------|----------|---------------|----------|
| `EntityGraphCache` | `kgentities_endpoint.py` | `CHANNEL_ENTITY_GRAPH` + `CHANNEL_GRAPH` + `CHANNEL_SPACE` | `invalidate` / `invalidate_graph` / `invalidate_space` |

### 6.3 New Write Paths in Notification Table (§5.3)

| Operation | File | Channels Notified |
|-----------|------|-------------------|
| Entity create/update/delete | `kgentities_endpoint.py` | `CHANNEL_ENTITY_GRAPH` (updated/deleted, entity_uri) |
| Frame create/update | `kgentity_frame_create_impl.py`, `kgentity_frame_update_impl.py` | `CHANNEL_ENTITY_GRAPH` (updated, entity_uri) |
| Batch entity operations | `kgentities_endpoint.py` | `CHANNEL_ENTITY_GRAPH` per entity_uri |
| Bulk import | `sparql_sql_space_impl.py` | `CHANNEL_GRAPH` (graph-wide invalidation) |

---

## 7. Implementation Phases

### Phase 1: Cache Infrastructure
- Create `EntityGraphCache` class with LRU + TTL + zlib compression + byte cap
- Instantiate `_entity_graph_cache` in `kgentities_endpoint.py`
- Wire `_get_entity_by_uri()` and `_get_entities_by_uris()` to use cache
- Add logging for cache hit/miss/invalidation/stats

### Phase 2: Local Invalidation
- Add invalidation calls to entity create/update/delete paths
- Add invalidation calls to frame create/update paths
- Wire existing `CHANNEL_GRAPH` and `CHANNEL_SPACE` signals to cascade-invalidate

### Phase 3: Cross-Instance NOTIFY
- Add `CHANNEL_ENTITY_GRAPH` to `SignalManager`
- Add `notify_entity_graph_changed()` method
- Register callback in `vitalgraphapp_impl.py` startup
- Send NOTIFY from entity/frame write paths
- Update `signal_management_plan.md` cache inventory

### Phase 4: Verification
- Load test: confirm cache hit rate and latency improvement
- Multi-instance test: confirm cross-instance invalidation via NOTIFY
- Edge cases: bulk import, SPARQL UPDATE, graph clear/delete

---

## 8. Metrics

Instrumentation to add:
- Cache hit/miss counters (logged periodically)
- Cache size (number of entries)
- Cache eviction count (TTL vs LRU)
- Invalidation count (by trigger: local write, NOTIFY, graph-level, space-level)

---

## 9. Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Stale cache if NOTIFY lost during reconnect | TTL safety net (15 minutes) |
| Memory growth for large deployments | LRU cap at 1000 entries + 256 MB total byte cap; zlib compression reduces footprint 5–10× |
| SPARQL UPDATE bypasses entity endpoint | Quad-level inspection: Rule 1 (subject in cache) + Rule 2 (`hasKGGraphURI` predicate); TTL for variable-only patterns |
| Cache key collision | Key includes space_id + graph_id + entity_uri — no collision possible |
| Thread safety | Single event loop access only; no locking needed |
| Bulk import floods NOTIFY | Use graph-level invalidation for bulk operations |
