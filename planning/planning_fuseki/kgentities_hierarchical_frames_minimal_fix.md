# KGEntities Hierarchical Frames - Minimal Fix Plan

## Problem Statement

Child frame UPDATE operations in the lead entity graph test are failing because `parent_frame_uri` is not being passed from the endpoint to the frame update processor.

**Test Results:**
- **test_lead_entity_graph.py:** 55/60 passing (92%) - 5 child frame update failures
- **test_multiple_organizations_crud.py:** 43/43 passing (100%) - top-level frames work perfectly

## Root Cause

The endpoint receives and validates `parent_frame_uri`, but doesn't pass it to the processor:

```python
# vitalgraph/endpoint/kgentities_endpoint.py, Line 1680-1685
result = await frame_processor.update_frames(
    space_id=space_id,
    graph_id=graph_id,
    entity_uri=entity_uri,
    frame_objects=all_frame_components
    # ❌ Missing: parent_frame_uri=parent_frame_uri
)
```

## What Already Works

Based on the test files, these operations already handle `parent_frame_uri` correctly:

1. **GET operations** - `get_kgentity_frames()` with `parent_frame_uri` parameter
2. **LIST operations** - Frame discovery with parent filtering
3. **DELETE operations** - Frame deletion with parent validation (lines 164-203 in delete processor)
4. **CREATE operations** - Hierarchical edge creation via `KGEntityHierarchicalFrameProcessor`

The filtering, validation, and hierarchical logic is already implemented and working.

## The Minimal Fix

Only 3 changes needed:

### Change 1: Update Processor Signature
**File:** `/vitalgraph/kg_impl/kgentity_frame_update_impl.py`
**Line:** 56-57

```python
# BEFORE:
async def update_frames(self, space_id: str, graph_id: str, entity_uri: str, 
                       frame_objects: List[GraphObject]) -> UpdateFrameResult:

# AFTER:
async def update_frames(self, space_id: str, graph_id: str, entity_uri: str, 
                       frame_objects: List[GraphObject],
                       parent_frame_uri: Optional[str] = None) -> UpdateFrameResult:
```

### Change 2: Pass to Create Processor
**File:** `/vitalgraph/kg_impl/kgentity_frame_update_impl.py`
**Line:** 115-122

```python
# BEFORE:
create_result = await frame_create_processor.create_entity_frame(
    backend_adapter=self.backend,
    space_id=space_id,
    graph_id=graph_id,
    entity_uri=entity_uri,
    frame_objects=validated_frame_objects,
    operation_mode="UPDATE"
)

# AFTER:
create_result = await frame_create_processor.create_entity_frame(
    backend_adapter=self.backend,
    space_id=space_id,
    graph_id=graph_id,
    entity_uri=entity_uri,
    frame_objects=validated_frame_objects,
    operation_mode="UPDATE",
    parent_frame_uri=parent_frame_uri  # Pass through
)
```

### Change 3: Update Create Processor Signature
**File:** `/vitalgraph/kg_impl/kgentity_frame_create_impl.py`
**Line:** 63-71

```python
# BEFORE:
async def create_entity_frame(
    self,
    backend_adapter: FusekiPostgreSQLBackendAdapter,
    space_id: str,
    graph_id: str,
    entity_uri: str,
    frame_objects: List[GraphObject],
    operation_mode: str = "CREATE"
) -> CreateFrameResult:

# AFTER:
async def create_entity_frame(
    self,
    backend_adapter: FusekiPostgreSQLBackendAdapter,
    space_id: str,
    graph_id: str,
    entity_uri: str,
    frame_objects: List[GraphObject],
    operation_mode: str = "CREATE",
    parent_frame_uri: Optional[str] = None
) -> CreateFrameResult:
```

### Change 4: Call from Endpoint
**File:** `/vitalgraph/endpoint/kgentities_endpoint.py`
**Line:** 1680-1685

```python
# BEFORE:
result = await frame_processor.update_frames(
    space_id=space_id,
    graph_id=graph_id,
    entity_uri=entity_uri,
    frame_objects=all_frame_components
)

# AFTER:
result = await frame_processor.update_frames(
    space_id=space_id,
    graph_id=graph_id,
    entity_uri=entity_uri,
    frame_objects=all_frame_components,
    parent_frame_uri=parent_frame_uri
)
```

## Why This is Sufficient

1. **Validation already exists** - Endpoint validates parent at lines 1582-1599
2. **Edge creation already exists** - Endpoint creates hierarchical edges at lines 1602-1626
3. **Filtering already works** - GET/LIST operations already use parent_frame_uri correctly
4. **Delete validation works** - Delete processor already validates parent relationships

The only missing piece is passing `parent_frame_uri` through the update chain so the processor knows it's operating on a child frame.

## Optional Enhancement in Create Processor

If the create processor needs to use `parent_frame_uri` for additional logic:

**File:** `/vitalgraph/kg_impl/kgentity_frame_create_impl.py`

```python
# Around line 100-120, if needed:
if parent_frame_uri:
    # Log that this is a child frame operation
    self.logger.info(f"Processing child frame update for parent {parent_frame_uri}")
    
    # The parent validation and edge creation is already done by the endpoint
    # The processor just needs to know this context for proper scoping
```

## Expected Outcome

After these 4 changes:
- **test_lead_entity_graph.py:** 60/60 passing (100%) ✅
- **test_multiple_organizations_crud.py:** 43/43 passing (100%) ✅
- Child frame updates persist correctly
- No other operations affected (backward compatible)

## Implementation Time

**Estimated:** 15-30 minutes

## Testing

Run existing tests:
```bash
python vitalgraph_client_test/test_lead_entity_graph.py
python vitalgraph_client_test/test_multiple_organizations_crud.py
```

No new tests needed - existing tests will validate the fix.
