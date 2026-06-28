# Child Frame Update Duplication Bug

## Problem

`update_entity_frames` with `parent_frame_uri=group_uri` duplicates child frames instead of updating them in place. A second `Edge_hasKGFrame` is created pointing to the same child frame URI, causing the frame to appear twice when the entity graph is reloaded.

### Observed Behavior

```
Before: 2 child frames (generated_message:0, generated_message:1)
After:  3 child frames (generated_message:0 ×2, generated_message:1)
```

The slot IS correctly updated on both copies, confirming the frame data itself was replaced. The duplication is purely an extra connecting edge.

## Root Cause

In `vitalgraph/endpoint/kgentities_endpoint.py` `_update_entity_frames` (line ~2188):

```python
# Create hierarchical connection edges if parent_frame_uri is provided using processor
if parent_frame_uri:
    hierarchical_processor = KGEntityHierarchicalFrameProcessor(...)
    hierarchical_edges = hierarchical_processor.create_connection_edges(
        entity_uri, frame_objects_for_edges, parent_frame_uri)
    for edge in hierarchical_edges:
        connecting_edges.append(edge)
```

This block **unconditionally creates new `Edge_hasKGFrame` edges** (with new URIs) when `parent_frame_uri` is set. These new edges get included in the frame group and written to the database alongside the frame update.

The downstream `KGEntityFrameCreateProcessor.create_entity_frame(operation_mode="UPDATE")` correctly skips edge creation at step 5:

```python
if not operation_mode or str(operation_mode).upper() not in ['UPDATE', 'UPSERT']:
    # Only create edges during CREATE, not UPDATE
    ...
```

But the **endpoint** has already injected duplicate edges before delegating to the processor.

### Why top-level frames aren't affected

When `parent_frame_uri=None`, the endpoint skips the hierarchical edge creation block entirely. Top-level frames are connected via `Edge_hasEntityKGFrame` which is only created in the processor's CREATE path. This is why Tests 1 and 2 work correctly.

## Affected Code Path

```
Client: update_entity_frames(parent_frame_uri=group_uri)
  → POST /api/graphs/kgentities/kgframes?operation_mode=update&parent_frame_uri=group_uri
  → endpoint: create_or_update_entity_frames()
  → endpoint: _update_entity_frames()                    ← BUG: creates new Edge_hasKGFrame
    → KGEntityFrameUpdateProcessor.update_frames()
      → KGEntityFrameCreateProcessor.create_entity_frame(operation_mode="UPDATE")
        → execute_atomic_frame_update()                  ← correctly skips edge creation
          → update_subjects_graph()                      ← deletes/re-inserts frame subjects only
```

## Fix

### Option A: Skip hierarchical edge creation for existing frames (minimal)

In `_update_entity_frames` (line ~2188), only create edges for frames that don't already have a connection:

```python
if parent_frame_uri:
    # Only create connection edges for NEW frames (not already connected)
    new_frame_uris = [uri for uri in frame_groups.keys() 
                      if uri not in {str(f.get('frame_uri', '')) for f in existing_frames}]
    if new_frame_uris:
        frame_objects_for_edges = []
        for frame_uri in new_frame_uris:
            mock_frame = KGFrame()
            mock_frame.URI = frame_uri
            frame_objects_for_edges.append(mock_frame)
        hierarchical_edges = hierarchical_processor.create_connection_edges(
            entity_uri, frame_objects_for_edges, parent_frame_uri)
        ...
```

### Option B: Remove the block entirely (simpler)

The `KGEntityFrameCreateProcessor` already handles edge creation correctly based on `operation_mode`. The endpoint shouldn't duplicate this logic.

```python
# DELETE THIS ENTIRE BLOCK (lines ~2188-2227):
# if parent_frame_uri:
#     ...hierarchical edge creation...
```

The processor at step 5 will:
- For CREATE: create the edges
- For UPDATE/UPSERT: skip edge creation (edges already exist)

### Option C: Include existing edge in subject_uris for atomic replacement

Instead of creating a new edge, find the existing `Edge_hasKGFrame` connecting parent → child and include it in the subjects being replaced. This ensures the edge is deleted and re-inserted with the same URI.

## Recommendation

**Option B** is cleanest. The endpoint's hierarchical edge creation was likely added before the processor had proper UPDATE handling. Now that the processor correctly skips edges for UPDATE mode, the endpoint block is redundant and harmful.

## Test Verification

After fix:
1. `update_entity_frames(parent_frame_uri=group_uri, objects=[child + slots + edges])` → child updated, no duplication
2. `create_entity_frames(parent_frame_uri=group_uri, objects=[child + slots + edges])` → new child created with edge
3. Verify child frame count stays at 2 after updating generated_message:0

### Test File Location

New test case: `vitalgraph_client_test/kgentities/case_kgentity_child_frame_update.py`

This fits alongside:
- `case_kgentity_frame_update.py` — existing top-level frame update tests
- `case_kgentity_frame_hierarchical.py` — existing hierarchical frame tests

### Test Cases to Implement

```python
class CaseChildFrameUpdateNoDuplication:
    """Verify child frame update does not create duplicate Edge_hasKGFrame."""

    async def test_update_child_frame_preserves_count(self):
        """Update child frame slot → child frame count stays the same."""

    async def test_update_child_frame_slot_persists(self):
        """Add slot to child frame via update → slot appears on reload."""

    async def test_update_child_frame_sibling_untouched(self):
        """Update child:0 → child:1 remains unchanged."""

    async def test_update_top_level_frame_no_parent(self):
        """Update top-level frame with parent_frame_uri=None → no duplication."""

    async def test_create_new_child_frame_creates_edge(self):
        """create_entity_frames with new child → Edge_hasKGFrame created correctly."""
```

## Files Modified

- `vitalgraph/endpoint/kgentities_endpoint.py` — Removed the redundant hierarchical edge creation block in `_update_entity_frames` (lines ~2188-2227) ✅ DONE

## Resolution (2026-05-29)

**Two separate issues were identified:**

### Issue 1: Real Server Bug — Duplicate Edge Creation (FIXED)

The endpoint unconditionally created new `Edge_hasKGFrame` hierarchical edges during frame updates. Since `KGEntityFrameCreateProcessor.create_entity_frame()` already handles edge creation and correctly **skips** it for `operation_mode="UPDATE"`, the endpoint's edge creation was redundant and caused duplication on every child frame update. Fix: removed the block (Option B).

### Issue 2: Correct API Usage — Frame Updates Require Full Frame Graph

Updating a frame (child or top-level) requires:
1. **Retrieve** the full frame graph via `get_kgentity_frames(frame_uris=[frame_uri])` → returns `FrameGraphResponse.frame_graph.objects` (frame + slots + edges)
2. **Modify** the desired slot/property values in-place on the existing objects
3. **Send back** the entire object list via `update_entity_frames(objects=frame_objects, ...)`

Sending NEW objects with fresh URIs does NOT replace the old ones — it appends, because the atomic update only deletes quads for subject URIs present in the payload. Old slot URIs not in the payload are untouched.

### Test Results — All 5 pass (77/77 total suite)

- ✅ `update_child_frame_preserves_count` — no duplicate `Edge_hasKGFrame`
- ✅ `update_child_frame_slot_persists` — retrieve → modify → send back → value persists
- ✅ `update_child_frame_sibling_untouched` — sibling frame unaffected
- ✅ `update_top_level_frame_no_duplication` — top-level frame count preserved
- ✅ `create_new_child_frame_creates_edge` — new child gets proper `Edge_hasKGFrame`

## Related Issues

- `entity_only_update_plan.md` — Entity-level update wiping frames (different endpoint, same theme of overly-broad replacement)
- The `KGGraph` parser may report duplicates even when only one edge exists if it traverses both `Edge_hasEntityKGFrame` and `Edge_hasKGFrame` paths to the same frame
