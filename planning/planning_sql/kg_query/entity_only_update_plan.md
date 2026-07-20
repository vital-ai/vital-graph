# Entity-Only Update Mode

## Problem

The current `POST /api/graphs/kgentities?operation_mode=update` endpoint performs a **full entity graph replacement**. When a caller sends only the KGEntity object (without frames/slots/edges), the backend:

1. Finds ALL subjects with `hasKGGraphURI = entity_uri` (entity + frames + slots + edges)
2. Deletes ALL their quads
3. Inserts only the quads from the payload

This destroys the entire frame graph if the caller only intends to update entity-level properties (e.g. `hasName`, `hasKGActionTypeList`, status).

### Observed Behavior

```
POST /api/graphs/kgentities?space_id=acme_kg&graph_id=urn%3Aacme_kg&operation_mode=update

Payload: 1 KGEntity object (10 quads)
Result:  deleted 485 quads for 69 subjects → inserted 10 quads
         All frames, slots, and edges wiped
```

### Root Cause

`KGEntityUpdateProcessor.update_entity()` calls `backend.update_entity_graph()` which does:

```sql
-- Finds ALL subjects in entity graph
SELECT DISTINCT subject_uuid FROM rdf_quad
WHERE predicate_uuid = hasKGGraphURI_uuid
  AND object_uuid = entity_uuid
  AND context_uuid = graph_uuid;

-- Deletes ALL quads for those subjects
DELETE FROM rdf_quad
WHERE subject_uuid = ANY($subjects) AND context_uuid = $graph;
```

This is correct for a full graph replacement but destructive when only the entity properties need updating.

## Existing API Surface

| Endpoint | Mode | Scope |
|----------|------|-------|
| `POST /kgentities?operation_mode=update` | Full graph replace | Entity + all frames/slots/edges |
| `POST /kgentities/kgframes?operation_mode=update` | Frame-level replace | Individual frame(s) + their slots/edges |
| `POST /kgframes?operation_mode=update` | Frame-level replace | Same as above, standalone |

**Gap**: No mode to update only the KGEntity subject without touching its graph members.

## Proposed Solution

### New Operation Mode: `entity_only`

Add `ENTITY_ONLY` to the `OperationMode` enum and handle it in the entity endpoint.

### Behavior

When `operation_mode=entity_only`:
- Accept only KGEntity objects in the payload (reject if frames/slots/edges present)
- Delete and re-insert quads **only where `subject_uuid = entity_uuid`**
- Leave all other subjects in the entity graph untouched

### Implementation Changes

#### 1. `OperationMode` Enum

File: `vitalgraph/model/kgentities_model.py` (or wherever OperationMode is defined)

```python
class OperationMode(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    UPSERT = "upsert"
    REPLACE = "replace"
    ENTITY_ONLY = "entity_only"  # NEW: update only entity subject triples
```

#### 2. Server Endpoint Routing

File: `vitalgraph/endpoint/kgentities_endpoint.py`

In `_create_or_update_entities` (around line 780):

```python
if operation_mode == OperationMode.UPDATE:
    return await self._handle_update_mode(...)
elif operation_mode == OperationMode.ENTITY_ONLY:
    return await self._handle_entity_only_update(...)
```

#### 3. New Handler: `_handle_entity_only_update`

File: `vitalgraph/endpoint/kgentities_endpoint.py`

```python
async def _handle_entity_only_update(self, backend_adapter, space_id, graph_id,
                                      vitalsigns_objects, current_user):
    """Update only the KGEntity subject triples, preserving all frames/slots/edges."""
    # Validate: only KGEntity objects allowed
    non_entity = [obj for obj in vitalsigns_objects if not isinstance(obj, KGEntity)]
    if non_entity:
        return EntityUpdateResponse(
            message="entity_only mode only accepts KGEntity objects, not frames/slots/edges",
            updated_uri="", updated_count=0
        )

    # Single entity per request (matches frame update pattern)
    if len(vitalsigns_objects) != 1:
        return EntityUpdateResponse(
            message="entity_only mode accepts exactly one KGEntity per request",
            updated_uri="", updated_count=0
        )

    entity_obj = vitalsigns_objects[0]
    entity_uri = str(entity_obj.URI)

    # Stamp server properties (preserve creation time, update modification time)
    # ... same as existing _handle_update_mode ...

    # Call entity-subject-only update
    result = await update_processor.update_entity_subject_only(
        backend_adapter, space_id, graph_id, entity_uri, [entity_obj]
    )
    return result
```

#### 4. New Backend Method: `update_entity_subject_only`

File: `vitalgraph/kg_impl/kg_backend_utils.py`

The handler receives GraphObjects (from the normal deserialization path), converts them
to quads via VitalSigns serialization (same as all other create/update paths), then
calls this method with the resulting quad rows.

```python
async def update_entity_subject_only(self, space_id: str, graph_id: str,
                                      entity_uri: str,
                                      quad_rows: List[tuple]) -> bool:
    """Replace only the entity's own quads (subject = entity_uri).

    Unlike update_entity_graph which deletes ALL subjects with hasKGGraphURI,
    this only deletes quads where the subject IS the entity itself.
    """
    schema = self.backend.schema
    t = schema.get_table_names(space_id)
    from ..db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
    g_uuid = _generate_term_uuid(graph_id, 'U')
    entity_uuid = _generate_term_uuid(entity_uri, 'U')

    async with self.backend.db_impl.connection_pool.acquire() as conn:
        async with conn.transaction():
            # Sync stats before delete (decrement counts for old quads)
            from .sync_stats_tables import sync_stats_for_deleted_subjects
            await sync_stats_for_deleted_subjects(
                conn, space_id, [entity_uuid], context_uuid=g_uuid)

            # Delete only entity's own quads
            await conn.execute(
                f"DELETE FROM {t['rdf_quad']} "
                f"WHERE subject_uuid = $1 AND context_uuid = $2",
                entity_uuid, g_uuid,
            )

            # Insert new entity quads
            if quad_rows:
                await self.backend.add_rdf_quads_batch_bulk(
                    space_id, quad_rows, connection=conn)

            # Sync stats after insert (increment counts for new quads)
            from .sync_stats_tables import sync_stats_after_insert
            await sync_stats_after_insert(conn, space_id, quad_rows)
    return True
```

#### 5. Client Method

File: `vitalgraph/client/endpoint/kgentities_endpoint.py`

```python
async def update_entity_only(self, space_id: str, graph_id: str,
                              objects: List[GraphObject]) -> EntityUpdateResponse:
    """Update only entity properties without touching frames/slots/edges."""
    # Calls POST /api/graphs/kgentities?operation_mode=entity_only
    ...
```

### Auxiliary Table Sync

The entity subject has no edge-source/dest properties and is not a frame, so:

| Table | Needed? | Reason |
|-------|---------|--------|
| `{space}_edge` | **No** | Entity subjects don't have `hasEdgeSource`/`hasEdgeDestination` |
| `{space}_frame_entity` | **No** | This tracks frame→entity relationships; entity subject isn't a frame |
| `{space}_rdf_pred_stats` / `{space}_rdf_stats` | **Yes** | Entity quads contribute to predicate/object stats; must decrement before delete, increment after insert |

### Server-Managed Properties

`hasKGGraphURI`, `hasObjectCreationTime`, `hasObjectModificationDateTime` are all
server-stamped. The existing `stamp_entity_server_properties` flow handles these —
the client doesn't need to send them and the server ensures they're present in the
re-inserted quads.

### Response Model

`EntityUpdateResponse` (inherits `BaseUpdateResponse`) already exists with fields:
`success`, `message`, `updated_uri`. Sufficient for single-entity-only updates.

### Validation

- Reject payloads containing non-KGEntity objects (frames, slots, edges)
- Reject payloads with more than one KGEntity (single entity per request)
- Verify entity exists before updating (same as current `_handle_update_mode`)
- Server stamps `hasObjectCreationTime` (preserved), `hasObjectModificationDateTime` (updated), `hasKGGraphURI` (re-stamped)

## Alternative Considered: Smart Detection

Instead of a new mode, detect when only KGEntity objects are in the payload and automatically scope the delete. Rejected because:
- Implicit behavior is harder to reason about
- A caller might intentionally want to strip all frames (current `update` behavior)
- Explicit modes are easier to document and test

## Test Plan

1. Create entity with frames → update with `entity_only` → verify frames preserved
2. Attempt `entity_only` with frame objects in payload → verify rejection
3. Attempt `entity_only` with multiple entities in payload → verify rejection
4. Verify entity properties are updated correctly
5. Verify `hasObjectModificationDateTime` is updated
6. Verify `hasObjectCreationTime` is preserved

## Implementation Status: ✅ COMPLETE

All components implemented and wired together.

### Files Modified

| File | Change |
|------|--------|
| `vitalgraph/endpoint/kgentities_endpoint.py` | Added `ENTITY_ONLY = "entity_only"` to `OperationMode` enum; routing at line 784; `_handle_entity_only_update` handler |
| `vitalgraph/kg_impl/kg_backend_utils.py` | Added `update_entity_subject_only` method (line ~1036) — subject-scoped delete + insert with stats sync |
| `vitalgraph/client/endpoint/kgentities_endpoint.py` | Added `update_entity_only` client method (line ~620) |

### Files Created

| File | Purpose |
|------|---------|
| `vitalgraph_client_test/kgentities/case_kgentity_entity_only_update.py` | 4 integration tests |
| (wired in `test_kgentities_endpoint.py` as section 13c) | |

### Test Coverage

| Test | Validates |
|------|-----------|
| `test_entity_only_preserves_frames` | Frames/slots survive entity-only update |
| `test_entity_only_updates_properties` | Entity name actually changes |
| `test_entity_only_rejects_non_entity` | Payload with frames/slots rejected |
| `test_entity_only_preserves_creation_time` | `hasObjectCreationTime` not overwritten |

### Key Design Decisions

1. **Single entity per request** — matches frame update pattern; simplifies error handling
2. **Stats-only aux sync** — entity subjects never have edge/frame relationships
3. **Reuses `_build_insert_quads_for_objects`** from `KGEntityUpdateProcessor` — normal VitalSigns→quad serialization
4. **Server stamps all managed properties** — client doesn't need to provide them
