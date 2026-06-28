# KGFrame Standalone Processor Plan

## Problem

The top-level `/kgframes` endpoint incorrectly uses `KGEntityFrameCreateProcessor` for create/update/replace operations. This processor is entity-scoped — it requires `entity_uri`, sets `kGGraphURI` for entity-level grouping, and creates `Edge_hasEntityKGFrame` edges. None of these concepts belong on the top-level `/kgframes` endpoint.

### Current (incorrect) flow

```
POST /kgframes (operation_mode=create|update|replace)
  → _create_frames()
    → grouping_uri = entity_uri if entity_uri else parent_uri   # entity_uri leak
    → _set_frame_grouping_uris(frames, graph_id, grouping_uri)  # sets kGGraphURI
    → _handle_create_mode / _handle_update_mode / _handle_replace_mode
      → KGEntityFrameCreateProcessor.create_entity_frame(entity_uri=...)  # entity processor
```

This has been the case since at least v0.0.20.

### Correct architecture

| Endpoint | Root object | Grouping URI | Processor |
|---|---|---|---|
| `/kgentities/kgframes` | KGEntity | `kGGraphURI` → entity URI | `KGEntityFrameCreateProcessor` |
| `/kgframes` | KGFrame | `frameGraphURI` → frame URI | **`KGFrameCreateProcessor`** (new) |

Both endpoints share the same hierarchical frame structure (`Edge_hasKGFrame` parent→child). The only difference is what sits at the root:
- Entity-scoped: entity → `Edge_hasEntityKGFrame` → root frame → `Edge_hasKGFrame` → child frames
- Standalone: root frame → `Edge_hasKGFrame` → child frames (no entity involvement)

---

## Existing standalone frame processors

Already in `vitalgraph/kg_impl/`:

| File | Class | Purpose | Status |
|---|---|---|---|
| `kgframe_graph_impl.py` | `KGFrameGraphProcessor` | Frame graph retrieval + deletion (uses `frameGraphURI`) | Exists, used |
| `kgframe_hierarchical_impl.py` | `KGFrameHierarchicalProcessor` | Child frame creation with `Edge_hasKGFrame` | Exists, references `kGGraphURI` — needs review |
| `kgframe_query_impl.py` | `KGFrameQueryProcessor` | Frame search/filter/pagination | Exists |

**Missing**: A standalone frame create/update processor that uses `frameGraphURI` for grouping and does not involve entity concepts.

---

## Plan

### Task 1: Create `KGFrameCreateProcessor`

New file: `vitalgraph/kg_impl/kgframe_create_impl.py`

Responsibilities:
- Create standalone frames with `frameGraphURI` grouping
- Categorize objects (frames, slots, edges)
- Set `frameGraphURI` on all frame graph members (frame → own URI, slots/edges → parent frame URI)
- **No** `kGGraphURI` assignment
- **No** `entity_uri` parameter
- **No** `Edge_hasEntityKGFrame` creation
- Support CREATE, UPDATE, UPSERT operation modes
- Use `backend_adapter.store_objects()` for atomic writes

Interface:
```python
class KGFrameCreateProcessor:
    async def create_frame(
        self,
        backend_adapter: KGBackendInterface,
        space_id: str,
        graph_id: str,
        frame_objects: List[GraphObject],
        operation_mode: str = "CREATE"
    ) -> CreateFrameResult
```

Based on `KGEntityFrameCreateProcessor` but stripped of entity concepts.

### Task 2: Update `KGFrameHierarchicalProcessor`

File: `vitalgraph/kg_impl/kgframe_hierarchical_impl.py`

Current issue: `_assign_grouping_uris()` sets `kGGraphURI` (inherited from parent). For standalone frames, only `frameGraphURI` should be set.

Changes:
- Remove `kGGraphURI` assignment from `_assign_grouping_uris()`
- Set `frameGraphURI` on child frames and their components
- `Edge_hasKGFrame` edges: set `frameGraphURI` to parent frame URI (not `kGGraphURI`)

### Task 3: Refactor `kgframes_endpoint.py` mode handlers

Replace entity processor usage in `_handle_create_mode`, `_handle_update_mode`, `_handle_replace_mode`:

**Before** (all three handlers):
```python
from ..kg_impl.kgentity_frame_create_impl import KGEntityFrameCreateProcessor
self.frame_processor = KGEntityFrameCreateProcessor()
result = await self.frame_processor.create_entity_frame(entity_uri=..., ...)
```

**After**:
```python
from ..kg_impl.kgframe_create_impl import KGFrameCreateProcessor
self.frame_processor = KGFrameCreateProcessor()
result = await self.frame_processor.create_frame(frame_objects=..., ...)
```

Additional cleanup:
- Remove `entity_uri` parameter from mode handlers
- Remove `grouping_uri` / `entity_uri` from `_create_frames` dispatch
- `_set_frame_grouping_uris` should set `frameGraphURI` only (no `kGGraphURI`)
- Parent validation (`_handle_update_mode`, `_handle_replace_mode`) stays the same — it uses `Edge_hasKGFrame` which is correct for both entity and standalone frames

### Task 4: Update `_set_frame_grouping_uris`

Current implementation in `kgframes_endpoint.py` sets `kGGraphURI` on frames. Should only set `frameGraphURI`.

| Property | Before | After |
|---|---|---|
| `frame.kGGraphURI` | Set to `parent_uri` | **Not set** |
| `frame.frameGraphURI` | Set to frame URI | Set to frame URI (unchanged) |
| `slot.kGGraphURI` | Set to `parent_uri` | **Not set** |
| `slot.frameGraphURI` | Set to frame URI | Set to frame URI (unchanged) |

### Task 5: Update tests

`case_kgframe_hierarchy.py` currently passes `entity_uri` to `create_kgframes`. Update:
- Remove `entity_uri=entity_uri` from all `create_kgframes` calls
- Test setup still creates entities (for creating initial frames via entity endpoint), but the `/kgframes` operations should not reference entities
- Verify all 6 tests pass without entity_uri

### Task 6: Update client

`vitalgraph/client/endpoint/kgframes_endpoint.py` `create_kgframes()` currently accepts and sends `entity_uri`. Review whether this parameter should be removed from the client method signature or kept as optional context.

---

## Shared logic

The hierarchical frame structure is identical for both endpoints:
- `Edge_hasKGFrame`: parent frame → child frame
- `frameGraphURI`: groups immediate frame members (frame, slots, slot edges)
- Recursive delete: find descendants via `Edge_hasKGFrame`, delete via `frameGraphURI`
- Parent validation: `validate_frame_parent_relationship` checks `Edge_hasKGFrame`

Two differences:

1. **Root attachment**:
   - Entity-scoped: `Edge_hasEntityKGFrame` (entity → frame)
   - Standalone: no root attachment edge

2. **Grouping scope**:
   - Entity-scoped: `kGGraphURI` groups the **entire** entity graph (all frames, all slots, all edges under the entity — the whole tree). `frameGraphURI` groups individual frame members within that.
   - Standalone: **no whole-graph grouping**. Only `frameGraphURI` exists, grouping the immediate members of each individual frame (the frame itself, its slots, its slot edges). Each child/grandchild frame has its own independent `frameGraphURI` grouping — same structure as under an entity, just without the entity-level umbrella.

---

## Files to modify

| File | Change |
|---|---|
| `vitalgraph/kg_impl/kgframe_create_impl.py` | **New** — standalone frame create processor |
| `vitalgraph/kg_impl/kgframe_hierarchical_impl.py` | Remove `kGGraphURI` from grouping |
| `vitalgraph/endpoint/kgframes_endpoint.py` | Use new processor, remove entity_uri from handlers |
| `vitalgraph_client_test/kgframes/case_kgframe_hierarchy.py` | Remove entity_uri from `/kgframes` calls |

## Files unchanged

| File | Reason |
|---|---|
| `vitalgraph/kg_impl/kgentity_frame_create_impl.py` | Entity-scoped processor — correct as-is |
| `vitalgraph/endpoint/kgentities_endpoint.py` | Entity endpoint — correct as-is |
| `vitalgraph/kg_impl/kgframe_graph_impl.py` | Already uses `frameGraphURI` — correct as-is |

---

## Status

- [x] Task 1: Create `KGFrameCreateProcessor` — `kgframe_create_impl.py`
- [x] Task 2: Update `KGFrameHierarchicalProcessor` — removed `kGGraphURI`, now uses `frameGraphURI` only
- [x] Task 3: Refactor endpoint mode handlers — all 4 handlers use `KGFrameCreateProcessor.create_frame()`
- [x] Task 4: Update `_set_frame_grouping_uris` — sets `frameGraphURI` only, no `kGGraphURI`
- [x] Task 5: Update tests — removed `entity_uri` from all `/kgframes` calls
- [x] Task 6: Review client — `entity_uri` kept as optional param for backward compat, ignored server-side
