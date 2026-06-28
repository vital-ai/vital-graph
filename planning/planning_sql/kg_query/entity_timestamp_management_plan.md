# KG Entity Server-Managed Properties

## Status: Implemented

**Date**: 2026-04-28

---

## Problem Statement

Several properties on KG entities should be **server-managed** rather than
trusted from the client:

### Timestamps

The `hasObjectCreationTime` and `hasObjectModificationDateTime` properties
are currently set by whoever sends the data — typically the client.  This
is unreliable:

- Clients can send arbitrary timestamps (past, future, or missing).
- There is no guarantee of consistency across create/update paths.
- There is no enforcement that creation time is immutable after the
  initial create.
- Frame or slot modifications do not update the parent entity's
  modification timestamp.

Timestamps should be set authoritatively by the service at write time,
with client-supplied values ignored.

### Status

The `hasObjectStatusType` property has no server-side default.  A newly
created entity should default to `ObjectStatusType_ACTIVE` unless the
client explicitly provides a value.  On update, if the client omits the
status, the existing DB value must be preserved (not wiped out).

### Entity type

The `hasKGEntityType` property has no server-side default.  A newly
created entity should default to `KGEntityType_KGEntity` unless the
client explicitly provides a value.  Like status, the client may set
any valid URI but it must always have a value.

---

## Properties

| Property | URI | Python accessor | Semantics |
|----------|-----|-----------------|----------|
| Creation time | `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime` | `obj.objectCreationTime` | Set once on create, never changed |
| Modification time | `http://vital.ai/ontology/vital#hasObjectModificationDateTime` | `obj.objectModificationDateTime` | Updated on every mutation |
| Status | `http://vital.ai/ontology/vital-aimp#hasObjectStatusType` | `obj.objectStatusType` | Defaults to ACTIVE on create; client may set any valid URI |
| Entity type | `http://vital.ai/ontology/haley-ai-kg#hasKGEntityType` | `obj.kGEntityType` | Defaults to KGEntityType_KGEntity on create; client may set any valid URI |

---

## Rules

### R1: Create entity

When a new KG entity is created:

- `hasObjectCreationTime` = **now** (server UTC)
- `hasObjectModificationDateTime` = **now** (server UTC, same value)
- Any values for these timestamp properties supplied by the client are
  **ignored** and overwritten.
- `hasObjectStatusType` = if the client supplies a value, **use it**;
  otherwise default to
  `http://vital.ai/ontology/vital-aimp#ObjectStatusType_ACTIVE`.
- `hasKGEntityType` = if the client supplies a value, **use it**;
  otherwise default to
  `http://vital.ai/ontology/haley-ai-kg#KGEntityType_KGEntity`.

The entity must always have a status and entity type value after create.

### R2: Update entity (KGEntity object included)

When an update includes the KGEntity object itself:

1. **Fetch** the existing KGEntity from the database.
2. **Preserve** the existing `hasObjectCreationTime` value (the original
   creation timestamp is immutable).
3. **Set** `hasObjectModificationDateTime` = **now** (server UTC).
4. **Override** whatever the client sent for both timestamp properties.
5. **Status**: if the incoming entity has a non-null `objectStatusType`,
   **use the client's value** (the client may change status to any valid
   URI).  If the client omits it (null/missing), **preserve the existing
   DB value** — status must never become null.
6. **Entity type**: same rule as status — if the incoming entity has a
   non-null `kGEntityType`, use it.  If omitted, preserve the existing
   DB value.  Entity type must never become null.

This means the update path performs a read-before-write for the entity
object.  The `entity_exists()` boolean check is **replaced** by
`fetch_entity_server_props()`, which serves double duty: it confirms
the entity exists and retrieves creation time, status, and entity type
in a single round-trip.

### R3: Update entity frames / slots (no KGEntity object)

When a frame or slot belonging to an entity is created, updated, or
deleted — but the KGEntity object itself is not part of the request:

1. The frame/slot write proceeds normally.
2. The parent entity's `hasObjectModificationDateTime` is updated to
   **now** (server UTC) via a targeted SPARQL UPDATE or property patch.
3. The entity's `hasObjectCreationTime` is **not** touched.

This covers:
- `POST /kgentities/kgframes` (create frames)
- `POST /kgentities/kgframes` with `operation_mode=update` (update frames)
- `DELETE /kgentities/kgframes` (delete frames)
- Any sub-frame or slot modifications that change the entity graph.

### R4: Batch operations

For batch create/update operations that process multiple entities:

- All entities in the batch share the **same timestamp** (captured once
  at the start of the batch request).
- This ensures consistency within a batch — all entities created or
  modified in the same API call have identical timestamps.

### R5: Low-level imports / SPARQL UPDATE

Low-level bulk import paths (e.g. direct SPARQL UPDATE, data migration
scripts) are **exempt** from this enforcement.  These paths may set
timestamps explicitly for data migration purposes.

The SPARQL UPDATE path already has entity change detection via
`collect_invalidation_targets()` in `entity_graph_cache.py`.  This same
mechanism can be used to trigger modification timestamp updates if
desired in the future, but is not required for the initial
implementation.

### R6: Deletion

Entity deletion does not require timestamp management — the entity and
all its data are removed.

### R7: Upsert

Upsert dynamically selects R1 or R2 based on whether the entity exists:

- If the entity does **not** exist → apply R1 (create defaults).
- If the entity **does** exist → apply R2 (fetch existing props, preserve
  creation time, preserve status/entity-type if client omits).

The `fetch_entity_server_props()` call doubles as the existence check:
if it returns no results, the entity is new.

### R8: Relation CRUD

Creating, updating, or deleting a KG relation does **not** touch the
modification time of either the source or destination entity.  Relations
are a separate concern from the entity's own data.

---

## Current Code Paths

### Entity create

**File**: `kgentities_endpoint.py` → `_create_or_update_entities()` (line 537)

Flow:
1. `quad_list_to_graphobjects(quads)` — deserialize client payload
2. Validate, set grouping URIs
3. `KGEntityCreateProcessor.create_or_update_entities()` →
   `_handle_create_mode()` → `backend.store_objects()`

**Injection point**: After step 1 (deserialize) and before step 3
(store), stamp the KGEntity objects with server timestamps.

### Entity update (with KGEntity object)

**File**: `kgentities_endpoint.py` → `_handle_update_mode()` (line 636)

Flow:
1. `quad_list_to_graphobjects(quads)` — deserialize
2. Check entity exists
3. Ownership validation
4. Stamp grouping URIs
5. `KGEntityUpdateProcessor.update_entity()` → DELETE + INSERT

**Injection point**: Between step 2 (exists check) and step 5 (update).
Fetch the existing KGEntity, read its `objectCreationTime`, then stamp
the incoming KGEntity with preserved creation time + new modification
time.

### Frame create / update / delete

**File**: `kgentities_endpoint.py` → `_create_or_update_frames()` (line 1062)
**File**: `kgentities_endpoint.py` → `_update_entity_frames()` (line 1556)
**File**: `kgentities_endpoint.py` → `delete_entity_frames` route (line 279)

All three paths already know the `entity_uri` and already call
`_invalidate_entity_cache()` after the write.  The modification timestamp
update can be placed alongside the cache invalidation.

### SPARQL UPDATE change detection

**File**: `sparql_sql_space_impl.py` → `execute_sparql_update()` (line 1375)

Uses `collect_invalidation_targets()` to find affected entity URIs.  This
same set of targets could be used to touch modification timestamps, but
this is deferred (Rule R5).

---

## Implementation Approach

### Timestamp stamping utility

A small utility function that stamps KGEntity objects:

```python
from datetime import datetime, timezone

CREATION_TIME_URI = "http://vital.ai/ontology/vital-aimp#hasObjectCreationTime"
MODIFICATION_TIME_URI = "http://vital.ai/ontology/vital#hasObjectModificationDateTime"
STATUS_TYPE_URI = "http://vital.ai/ontology/vital-aimp#hasObjectStatusType"
DEFAULT_STATUS = "http://vital.ai/ontology/vital-aimp#ObjectStatusType_ACTIVE"
ENTITY_TYPE_URI = "http://vital.ai/ontology/haley-ai-kg#hasKGEntityType"
DEFAULT_ENTITY_TYPE = "http://vital.ai/ontology/haley-ai-kg#KGEntityType_KGEntity"

def stamp_entity_server_properties(
    entity: KGEntity,
    now: datetime,
    existing_creation_time: datetime = None,
    existing_status: str = None,
    existing_entity_type: str = None,
    is_create: bool = False,
):
    """Stamp server-managed properties on a KGEntity.

    Args:
        entity: The KGEntity to stamp.
        now: The current server time (UTC).
        existing_creation_time: If provided, preserves this as the
            creation time (for updates). If None, uses `now` (for creates).
        existing_status: The status URI currently in the DB (for updates).
        existing_entity_type: The entity type URI currently in the DB.
        is_create: True for entity creation, False for update.
    """
    # Timestamps — always server-set
    entity.objectCreationTime = existing_creation_time or now
    entity.objectModificationDateTime = now

    # Status — default on create, preserve on update if client omits
    if is_create:
        if not entity.objectStatusType:
            entity.objectStatusType = DEFAULT_STATUS
    else:
        if not entity.objectStatusType:
            entity.objectStatusType = existing_status or DEFAULT_STATUS

    # Entity type — default on create, preserve on update if client omits
    if is_create:
        if not entity.kGEntityType:
            entity.kGEntityType = DEFAULT_ENTITY_TYPE
    else:
        if not entity.kGEntityType:
            entity.kGEntityType = existing_entity_type or DEFAULT_ENTITY_TYPE
```

### Fetching existing server-managed properties

For updates, fetch the existing KGEntity's creation time and status:

```python
@dataclass
class ExistingEntityProps:
    creation_time: Optional[datetime] = None
    status: Optional[str] = None
    entity_type: Optional[str] = None

async def fetch_entity_server_props(
    backend, space_id: str, graph_id: str, entity_uri: str
) -> ExistingEntityProps:
    """Fetch creation time, status, and entity type from an existing entity.

    Uses a single SPARQL query with OPTIONAL to retrieve all three.
    Returns defaults if properties are missing.
    """
    sparql = f"""
    SELECT ?ct ?st ?et WHERE {{
        GRAPH <{graph_id}> {{
            OPTIONAL {{ <{entity_uri}> <{CREATION_TIME_URI}> ?ct . }}
            OPTIONAL {{ <{entity_uri}> <{STATUS_TYPE_URI}> ?st . }}
            OPTIONAL {{ <{entity_uri}> <{ENTITY_TYPE_URI}> ?et . }}
        }}
    }}
    """
    results = await backend.execute_sparql_query(space_id, sparql)
    # Extract creation_time, status, and entity_type from results...


async def batch_fetch_entity_server_props(
    backend, space_id: str, graph_id: str, entity_uris: List[str]
) -> Dict[str, ExistingEntityProps]:
    """Fetch server-managed props for multiple entities in one query.

    Returns a dict keyed by entity URI.  Missing URIs (entity doesn't
    exist) are absent from the dict.
    """
    values_clause = " ".join(f"<{uri}>" for uri in entity_uris)
    sparql = f"""
    SELECT ?entity ?ct ?st ?et WHERE {{
        VALUES ?entity {{ {values_clause} }}
        GRAPH <{graph_id}> {{
            ?entity ?_any_pred ?_any_obj .
            OPTIONAL {{ ?entity <{CREATION_TIME_URI}> ?ct . }}
            OPTIONAL {{ ?entity <{STATUS_TYPE_URI}> ?st . }}
            OPTIONAL {{ ?entity <{ENTITY_TYPE_URI}> ?et . }}
        }}
    }}
    """
    results = await backend.execute_sparql_query(space_id, sparql)
    # Build dict of ExistingEntityProps per entity URI...
```

The batch variant is used for update/upsert requests containing multiple
KGEntity objects, avoiding N sequential round-trips.

Alternatively, when the update path already fetches the full entity
(e.g. for ownership validation), all properties can be read from
that fetched object.

### Updating modification time without full entity rewrite

For frame modifications where the KGEntity object is not part of the
request, a targeted SPARQL UPDATE patches just the modification time:

```python
async def touch_entity_modification_time(
    backend, space_id: str, graph_id: str, entity_uri: str,
    now: datetime,
):
    """Update only the modification timestamp on an entity."""
    now_str = now.isoformat()
    sparql = f"""
    DELETE {{
        GRAPH <{graph_id}> {{
            <{entity_uri}> <{MODIFICATION_TIME_URI}> ?old_mod .
        }}
    }}
    INSERT {{
        GRAPH <{graph_id}> {{
            <{entity_uri}> <{MODIFICATION_TIME_URI}> "{now_str}"^^<http://www.w3.org/2001/XMLSchema#dateTime> .
        }}
    }}
    WHERE {{
        GRAPH <{graph_id}> {{
            OPTIONAL {{ <{entity_uri}> <{MODIFICATION_TIME_URI}> ?old_mod . }}
        }}
    }}
    """
    await backend.execute_sparql_update(space_id, sparql)
```

This is a lightweight operation — a single DELETE/INSERT on one triple.
It can run after the frame write, before cache invalidation.

---

## Implementation Steps

| Step | File | Change | Status |
|------|------|--------|--------|
| T0 | `cache/entity_graph_cache.py` | **Fix cache invalidation — two issues.** (1) **Attribute bug**: `getattr(node, 'uri', None)` should be `isinstance(node, URINode)` + `.value` — `URINode` has field `value`, not `uri`.  Both existing rules were dead code.  (2) **Missing subject→entity index**: A raw SPARQL UPDATE that modifies a sub-object (frame/slot property) typically does NOT include `hasKGGraphURI` in its quads — only the changed triple.  Rule 2 (`hasKGGraphURI` in SPARQL) cannot fire.  **Fix**: At `put()` time, index every unique subject URI from the cached entity graph quads.  Map `(space_id, subject_uri) → {(graph_id, entity_uri)}`.  At `collect_invalidation_targets()` time, look up each subject URI in this index to resolve back to the owning entity.  Index is purged when a cache entry is removed (invalidation, TTL, LRU eviction).  Regression tests (8 cases) in `test_scripts/test_entity_graph_cache_invalidation.py`. | ✅ Done |
| T1 | `kg_impl/kg_server_properties.py` (new) | Create utility module: `stamp_entity_server_properties()`, `fetch_entity_server_props()`, `batch_fetch_entity_server_props()`, `touch_entity_modification_time()`, constants for property URIs and defaults | ✅ Done |
| T2 | `kgentities_endpoint.py` | In `_create_or_update_entities()`, after deserialisation and before `KGEntityCreateProcessor`, call `stamp_entity_server_properties(is_create=True)` on all KGEntity objects (batch timestamp, status default) | ✅ Done |
| T3 | `kgentities_endpoint.py` | In `_handle_update_mode()`, replace `entity_exists()` with `fetch_entity_server_props()` / `batch_fetch_entity_server_props()` (combined existence + property fetch, Decision 4), then `stamp_entity_server_properties(is_create=False)` with preserved creation time + DB status/entity-type fallback | ✅ Done |
| T4 | `kgentities_endpoint.py` | In `_create_or_update_frames()`, after successful frame write and before cache invalidation, call `touch_entity_modification_time()` (try/except, non-critical) | ✅ Done |
| T5 | `kgentities_endpoint.py` | In `_update_entity_frames()`, after successful frame update and before cache invalidation, call `touch_entity_modification_time()` (try/except, non-critical) | ✅ Done |
| T6 | `kgentities_endpoint.py` | In `_delete_entity_frames()`, after successful delete and before cache invalidation, call `touch_entity_modification_time()` using `full_graph_uri` (try/except, non-critical) | ✅ Done |
| T7 | `kg_impl/kgentity_create_impl.py` | Defence-in-depth: stamp server properties inside `KGEntityCreateProcessor.create_or_update_entities()` after entity extraction, before validation.  Catches callers that bypass the endpoint. | ✅ Done |

---

## Testing

| Test | Description |
|------|-------------|
| Create sets both timestamps | Create entity → both timestamps are set and ≈ now |
| Create ignores client timestamps | Create with client-supplied timestamps → server overrides |
| Create defaults status to ACTIVE | Create entity with no status → `objectStatusType` = ACTIVE |
| Create honours explicit status | Create entity with status=PENDING → `objectStatusType` = PENDING |
| Update preserves creation time | Update entity → `objectCreationTime` unchanged |
| Update sets modification time | Update entity → `objectModificationDateTime` ≈ now |
| Update ignores client timestamps | Update with client-supplied timestamps → server overrides |
| Update preserves status when omitted | Update entity without status → `objectStatusType` unchanged from DB |
| Update allows status change | Update entity with status=INACTIVE → `objectStatusType` = INACTIVE |
| Frame create touches modification | Create frame → parent entity `objectModificationDateTime` ≈ now, `objectCreationTime` unchanged |
| Frame update touches modification | Update frame → parent entity `objectModificationDateTime` ≈ now |
| Frame delete touches modification | Delete frame → parent entity `objectModificationDateTime` ≈ now |
| Frame write does not change status | Create/update frame → parent entity `objectStatusType` unchanged |
| Create defaults entity type | Create entity with no entity type → `kGEntityType` = KGEntityType_KGEntity |
| Create honours explicit entity type | Create entity with type=KGEntityType_Person → `kGEntityType` = KGEntityType_Person |
| Update preserves entity type when omitted | Update entity without entity type → `kGEntityType` unchanged from DB |
| Update allows entity type change | Update entity with type=KGEntityType_Organization → `kGEntityType` = KGEntityType_Organization |
| Entity type never null | Create → update without type → all reads show non-null entity type |
| Batch uses same timestamp | Create 3 entities in batch → all have identical timestamps |
| Creation time immutable across updates | Create entity, update 3 times → `objectCreationTime` never changes |
| Status never null after create+updates | Create → update without status → update with status → all reads show non-null status |
| Round-trip datetime precision | Create → read back → timestamps match with at least second precision |

**Test file**: `vitalgraph_client_test/entity_graph_lead/case_entity_server_properties.py`

**Test orchestrator**: Wired into `vitalgraph_client_test/test_kgentities_endpoint.py` as step 14.

**Results**: 22/22 tests passing (2026-04-30).  All entity + frame CRUD tests (60 total) pass at 100%.

---

## Decisions

1. **Server-side only** — Timestamps are set exclusively by the service.
   Client values are silently overwritten, not rejected (no 400 error).

2. **UTC with microsecond precision** — All timestamps use
   `datetime.now(timezone.utc)` at full microsecond precision.
   Consistency is maintained by using the same serialisation path
   everywhere (Python `isoformat()` → xsd:dateTime literal).

3. **Batch consistency** — A single `now` value is captured once per API
   request and shared across all entities in the batch.

4. **Combined existence check + property fetch** — The update path
   replaces the separate `entity_exists()` boolean check with
   `fetch_entity_server_props()`.  One SPARQL SELECT returns creation
   time, status, and entity type (or no rows if the entity doesn't
   exist).  No additional round-trip cost.

5. **Frame modifications touch parent entity** — Any frame/slot
   create/update/delete updates the parent entity's modification time.
   This uses a targeted SPARQL DELETE/INSERT (single triple) which is
   cheap.

6. **Low-level imports exempt** — Direct SPARQL UPDATE and bulk import
   paths do not enforce timestamp management.  This allows data migration
   with original timestamps.

7. **Defence in depth** — The primary enforcement is in
   `kgentities_endpoint.py` (the API layer).  Optional secondary
   enforcement can be added in `kgentity_create_impl.py` for callers
   that bypass the endpoint.

8. **Cache invalidation and change detection — two fixes applied (T0).**

   **Bug 1 — attribute mismatch**: `getattr(node, 'uri', None)` but
   `URINode` has field `value`, not `uri`.  Every call silently returned
   `None`, making all rules dead code.  **Fix**: `isinstance(node, URINode)`
   + `.value` via `_uri_of()` helper.

   **Bug 2 — missing subject→entity index**: A raw SPARQL UPDATE that
   modifies a sub-object (e.g. changing a slot value) typically only
   contains the changed triple.  `hasKGGraphURI` is NOT in the update
   quads because it didn’t change.  Without an index, there is no way
   to resolve a sub-object subject URI back to its parent entity.

   **Fix**: At `put()` time, build a subject→entity index from ALL
   unique subject URIs in the cached entity graph quads.  At SPARQL
   UPDATE time, look up each subject URI in the index.  Index is purged
   when a cache entry is removed (invalidation, TTL, LRU eviction).

   Data structures:
   - `_sub_to_entity`: `(space_id, subject_uri) → {(graph_id, entity_uri)}`
   - `_entity_subs`: `cache_key → {subject_uri, …}` (for cleanup)

   The explicit `_invalidate_entity_cache()` calls in the endpoint remain
   as defence in depth — they cover the entity create/update path (which
   stores objects directly, not via SPARQL UPDATE) and provide a safety
   net for frame writes.

9. **Status default on create** — If the client does not provide a
   `hasObjectStatusType` value, the server defaults to
   `ObjectStatusType_ACTIVE`.  If the client provides any valid URI,
   that value is used as-is.  This means the client can create entities
   in non-active states (e.g. PENDING) if needed.

10. **Status preserved on update when omitted** — Unlike timestamps
    (which are always server-overridden), status is **client-settable**.
    The rule is: if the incoming entity has a non-null status, use it;
    if null/missing, preserve whatever is in the DB.  Status must never
    become null — if somehow both the client and DB have no value, fall
    back to `ObjectStatusType_ACTIVE`.

11. **Entity type default on create** — If the client does not provide a
    `hasKGEntityType` value, the server defaults to
    `http://vital.ai/ontology/haley-ai-kg#KGEntityType_KGEntity`.
    The client may provide any valid URI.

12. **Entity type preserved on update when omitted** — Same rule as
    status: if the incoming entity has a non-null `kGEntityType`, use it;
    if null/missing, preserve the DB value.  Entity type must never
    become null.

---

## Implementation Summary (2026-04-28)

All steps T0–T7 implemented and verified with 16 integration tests (100% pass rate).

### Files modified

- `vitalgraph/cache/entity_graph_cache.py` — T0: `_uri_of()` helper, `_sub_to_entity` / `_entity_subs` indexes, updated `collect_invalidation_targets()`
- `vitalgraph/kg_impl/kg_server_properties.py` — T1: New module (263 lines) with `stamp_entity_server_properties()`, `fetch_entity_server_props()`, `batch_fetch_entity_server_props()`, `touch_entity_modification_time()`
- `vitalgraph/endpoint/kgentities_endpoint.py` — T2–T6: Stamping in create/update paths, `touch_entity_modification_time()` in all three frame write paths
- `vitalgraph/kg_impl/kgentity_create_impl.py` — T7: Defence-in-depth stamping in processor

### Files created

- `test_scripts/test_entity_graph_cache_invalidation.py` — 8 regression tests for cache invalidation
- `vitalgraph_client_test/entity_graph_lead/case_entity_server_properties.py` — 16 integration tests for server properties

### Key design notes

- **T3** replaces `entity_exists()` with `fetch_entity_server_props()` / `batch_fetch_entity_server_props()` — zero extra round-trips (Decision 4)
- **T4/T5/T6** wrap `touch_entity_modification_time()` in try/except — frame write succeeds even if the touch fails (non-critical)
- **T6** uses `full_graph_uri` (computed from backend) rather than the `graph_id` parameter, matching what the delete processor uses
- **T7** is idempotent with the endpoint stamping — if already stamped, the processor re-stamps with ≈ same values
- VitalSigns properties return `CombinedProperty` wrappers; tests use `.get_value()` to extract raw `datetime` values

---

## Risks

- **Performance** — The update path adds one SPARQL SELECT (fetch
  creation time).  For frame modifications, one additional SPARQL UPDATE
  (touch modification time).  Both are single-triple operations and
  should be sub-millisecond on the PostgreSQL backend.

- **Concurrency** — Two concurrent frame updates on the same entity
  could race on the modification timestamp.  The entity advisory lock
  already serialises writes, so the last writer wins — which is the
  correct behaviour for a "last modified" timestamp.

- **Existing data** — Entities created before this feature is deployed
  will have missing timestamps, status, or entity type.  See the
  Backfill section below.

---

## Backfill Migration

**Status**: ✅ Implemented (direct SQL — no Jena sidecar required)

Existing entities may lack one or more of the four server-managed
properties.  Two complementary mechanisms are provided:

1. **Standalone CLI script** — for operator-driven one-off backfills.
2. **Internal incremental backfill task** — runs inside the service
   and continuously backfills entities across all spaces.

### Design: Direct SQL (no SPARQL / sidecar)

The backfill operates directly on the PostgreSQL `{space}_rdf_quad` and
`{space}_term` tables via `asyncpg`.  This avoids any dependency on the
Jena sidecar for SPARQL parsing, making the CLI script and background
task fully self-contained.

**Key insight**: finding entities and inserting missing quads is a
straightforward table sweep — we know the exact predicate URIs and can
compute deterministic term UUIDs client-side using the same UUID v5
function used by `sparql_sql_space_impl._generate_term_uuid()`.

### Shared core logic

All backfill functions live in `vitalgraph/kg_impl/kg_server_properties.py`
and accept an `asyncpg.Pool` + `space_id` (no backend adapter needed):

| Function | Purpose |
|----------|---------|
| `discover_graphs_sql(pool, space_id)` | Find graph URIs containing KGEntity instances |
| `count_entities_needing_backfill_sql(pool, space_id, graph_id)` | Count entities missing any managed property |
| `backfill_entity_server_properties_sql(pool, space_id, graph_id, ...)` | Batch loop: find + patch entities |

**How it works**:

1. **Compute term UUIDs** for the known predicate URIs (`rdf:type`,
   `hasObjectCreationTime`, etc.) and the `KGEntity` class URI using
   deterministic UUID v5.  No database lookup needed for these — the
   UUIDs are derived from the term text.

2. **Find entities missing any property** via a single SQL query:
   ```sql
   SELECT q.subject_uuid
   FROM {space}_rdf_quad q
   WHERE q.predicate_uuid = <rdf:type>
     AND q.object_uuid = <KGEntity>
     AND q.context_uuid = <graph_uuid>
     AND (
       NOT EXISTS (SELECT 1 FROM {space}_rdf_quad x
                   WHERE x.subject_uuid = q.subject_uuid
                     AND x.predicate_uuid = <hasObjectCreationTime>
                     AND x.context_uuid = <graph_uuid>)
       OR NOT EXISTS (...)  -- same for the other 3 properties
     )
   LIMIT <batch_size>
   ```

3. **For each entity**, check which of the 4 predicate UUIDs already
   exist (single query with `predicate_uuid = ANY(...)`) and build a
   list of missing quad rows.

4. **Insert missing quads** via `executemany` with `ON CONFLICT DO
   NOTHING`:
   - `hasObjectCreationTime` → `1970-01-01T00:00:00Z` (epoch sentinel)
   - `hasObjectModificationDateTime` → now
   - `hasObjectStatusType` → `ObjectStatusType_ACTIVE`
   - `hasKGEntityType` → `KGEntityType_KGEntity`

5. **Ensure term rows exist** for the literal/URI object values
   (`_ensure_term_row()`) — uses the same upsert pattern as the main
   write path.

6. **Repeat** until the batch query returns zero results.
7. **Throttle** with `batch_delay` seconds between batches.

### Helper functions

```python
def _term_uuid(text, term_type='U', lang=None, datatype_id=None) -> uuid.UUID
    """Deterministic UUID v5 — mirrors _generate_term_uuid."""

async def _resolve_xsd_datetime_id(conn, space_id) -> int
    """Get/create xsd:dateTime datatype_id."""

async def _ensure_term_row(conn, term_table, text, term_type, ...) -> uuid.UUID
    """Upsert a term row, return its UUID."""
```

---

### Deliverable 1: Standalone CLI script

**File**: `scripts/backfill_entity_server_properties.py`

**Status**: ✅ Implemented

A standalone script that connects directly to PostgreSQL via `asyncpg`
(from `DATABASE_URL` or `VitalGraphConfig`).  No VitalGraphImpl, no
SpaceManager, no backend adapters, no sidecar.

Spaces are resolved from the admin `space` table; graphs are discovered
via `discover_graphs_sql()`.

**Usage**:
```bash
# Backfill all graphs in a specific space:
python scripts/backfill_entity_server_properties.py --space space_production

# Backfill a specific graph in a space:
python scripts/backfill_entity_server_properties.py --space space_production --graph urn:my_graph

# Backfill all graphs in all spaces:
python scripts/backfill_entity_server_properties.py --all-spaces

# Dry run (count entities needing backfill without modifying):
python scripts/backfill_entity_server_properties.py --space space_production --dry-run

# Adjust batch size and delay:
python scripts/backfill_entity_server_properties.py --space space_production --batch-size 500 --batch-delay 0.05
```

**Parameters**:

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--space` | Yes (unless `--all-spaces`) | — | Space ID to backfill |
| `--graph` | No | all graphs | Specific graph ID to backfill |
| `--all-spaces` | No | false | Iterate over all spaces |
| `--batch-size` | No | 200 | Entities per batch |
| `--batch-delay` | No | 0.1 | Seconds between batches |
| `--dry-run` | No | false | Count only, no modifications |

**Implementation**:

1. Create `asyncpg.Pool` from `DATABASE_URL` or `VitalGraphConfig`
2. Resolve target spaces from the admin `space` table
3. For each space, call `discover_graphs_sql()` (or use `--graph`)
4. For each (space, graph) pair, call
   `backfill_entity_server_properties_sql()`
5. Print per-graph and overall summary with counts

---

### Deliverable 2: Internal incremental backfill task

**File**: `vitalgraph/tasks/backfill_server_properties_task.py`

**Status**: ✅ Implemented

A background task that runs inside the VitalGraph service process.
It incrementally backfills entities across **all spaces**, processing
a small bounded batch on each iteration.

Takes an `asyncpg` pool and a `SpaceManager` (for listing space_ids).
Uses `discover_graphs_sql()` and `backfill_entity_server_properties_sql()`
directly — no SPARQL, no sidecar.

**Behaviour**:

1. On service startup, the task is registered as a periodic coroutine
   (configurable interval, default: 60 seconds).
2. Each iteration:
   a. List all spaces via `space_manager.list_spaces()`.
   b. For each space, discover graphs via `discover_graphs_sql()`.
   c. For each (space, graph) pair, run **one batch** of backfill
      (e.g. 200 entities).  If a batch is fully processed (returned
      < batch_size results), move to the next graph/space.  If a
      batch is full, **stop** and resume from the same point on the
      next iteration.
3. Track a cursor `(space_id, graph_id)` so progress across iterations
   is deterministic and no graph is starved.
4. When all entities across all spaces are backfilled (no batch returns
   results), the task enters a low-frequency check mode (e.g. every
   10 minutes) to pick up newly problematic entities.

**Configuration** (via `VitalGraphConfig` / environment):

| Config | Default | Description |
|--------|---------|-------------|
| `BACKFILL_ENABLED` | `true` | Enable/disable the task |
| `BACKFILL_INTERVAL_SECONDS` | `60` | Seconds between iterations |
| `BACKFILL_BATCH_SIZE` | `200` | Entities per batch per iteration |
| `BACKFILL_IDLE_INTERVAL_SECONDS` | `600` | Interval when no work remains |

**Concurrency safety**:

- All quad inserts use `ON CONFLICT DO NOTHING` — concurrent writes
  and backfill cannot produce duplicates.
- If multiple service instances run simultaneously, each instance runs
  its own backfill task.  `ON CONFLICT DO NOTHING` means duplicate work
  is harmless.  In practice, different instances will naturally pick up
  different batches because the first batch of un-backfilled entities
  is claimed by whichever instance queries first.
- The task is **leader-election-free** — all instances can safely run
  the backfill.  Duplicate work is harmless (idempotent) and unlikely
  due to batch ordering.

---

### Graceful handling of missing values

Until backfill completes, some entities will lack one or more managed
properties.  The system must tolerate this:

- **Read path** — Getting a KG entity with missing timestamps, status,
  or entity type must **not** break.  The API returns whatever is stored;
  null/missing fields are simply absent from the response.
- **Filter/sort** — Queries that filter or sort by `modificationDateTime`,
  `creationTime`, `statusType`, or `entityType` will **not match**
  entities missing those values.  This is expected and acceptable —
  those entities will appear once backfill fills in the values.
- **Write path** — Creating or updating an entity that currently has
  missing values works normally.  The `stamp_entity_server_properties()`
  function fills in defaults for any missing property, so the first
  write after deployment effectively backfills that entity.
- **Lock contention** — The backfill uses `ON CONFLICT DO NOTHING`
  rather than advisory locks.  A concurrent write that stores the same
  property simply wins; the backfill insert is a no-op.  No lock
  contention, no waiting.

### Properties

- **Idempotent** — re-running is safe; only missing values are filled
  (`ON CONFLICT DO NOTHING`).
- **Incremental** — processes a bounded batch per iteration.
- **Self-contained** — operates directly on PostgreSQL tables; no Jena
  sidecar, no SPARQL parsing, no backend adapters needed.
- **Restartable** — progress cursor means interruption loses at most
  one batch of work.
- **Tolerant** — the system operates correctly before, during, and after
  backfill.  Missing values are not errors.
