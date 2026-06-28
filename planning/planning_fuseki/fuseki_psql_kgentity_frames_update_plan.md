# KGEntity Frames Endpoint - Hierarchical Frame URI Parameter Update Plan

## Overview
Add `frame_uri` parameter to KGEntity frames endpoint operations to support hierarchical frame navigation and operations within an entity's frame graph.

## Current State

### Existing Parameters
- **List/Get Frames**: `entity_uri`, `frame_uris` (list), `page_size`, `offset`, `search`
- **Create Frames**: `entity_uri`, `parent_frame_uri`, `document`
- **Update Frames**: `entity_uri`, `document`, `operation_mode`
- **Delete Frames**: `entity_uri`, `frame_uris` (list)

### Current Behavior
- List: Returns all frames for an entity (flat list)
- Get: Returns specific frames by URI list
- Create: Can attach to parent via `parent_frame_uri`
- Update: Updates frames by matching URIs in document
- Delete: Deletes specific frames by URI list

## Proposed Changes

### New Parameter: `parent_frame_uri`
Add `parent_frame_uri: Optional[str]` parameter to specify a parent frame context for hierarchical operations.

### Updated Operation Behaviors

#### 1. List Frames (`GET`)
**Current**: Lists all frames for entity (flat)
```python
get_kgentity_frames(space_id, graph_id, entity_uri=entity_uri)
# Returns: All frames for entity
```

**Proposed**: Add hierarchical filtering
```python
get_kgentity_frames(space_id, graph_id, entity_uri=entity_uri, parent_frame_uri=parent_frame_uri)
# Returns: Only child frames of specified parent frame
```

**Logic**:
- If `parent_frame_uri` is None: Return top-level frames (children of entity via `Edge_hasEntityKGFrame`)
- If `parent_frame_uri` is provided: Return only frames that are children of the specified frame
- Child relationship determined by `Edge_hasKGFrame` edges where source is `parent_frame_uri`
- Entity is the implicit parent when `parent_frame_uri` is None

---

#### 2. Get Specific Frames (`GET` with `frame_uris`)
**Current**: Gets specific frames by URI list
```python
get_kgentity_frames(space_id, graph_id, entity_uri=entity_uri, frame_uris=[frame1, frame2])
# Returns: Specified frames with full graphs
```

**Proposed**: Add parent frame context
```python
get_kgentity_frames(space_id, graph_id, entity_uri=entity_uri, frame_uris=[frame1], parent_frame_uri=parent_frame_uri)
# Returns: Specified frame(s) that are children of parent frame
```

**Logic**:
- If `parent_frame_uri` is None: Return requested frames (must be top-level frames, children of entity)
- If `parent_frame_uri` is provided: Validate that requested frames are children of parent frame
- Return error if requested frames are not children of specified parent
- Entity is the implicit parent when `parent_frame_uri` is None

---

#### 3. Create Frames (`POST`)
**Current**: Uses `parent_frame_uri` parameter
```python
create_entity_frames(space_id, graph_id, entity_uri=entity_uri, document=doc, parent_frame_uri=parent_uri)
# Creates frames attached to parent
```

**Proposed**: Keep `parent_frame_uri` parameter (no change to signature)
```python
create_entity_frames(space_id, graph_id, entity_uri=entity_uri, document=doc, parent_frame_uri=parent_uri)
# Creates frames as children of specified parent frame
```

**Logic**:
- If `parent_frame_uri` is None: Create top-level frames (attached directly to entity)
- If `parent_frame_uri` is provided: Create frames as children of specified parent frame
- Automatically create `Edge_hasKGFrame` from parent to new frames
- **NO BREAKING CHANGE**: Parameter name remains `parent_frame_uri`

---

#### 4. Update Frames (`POST` with `operation_mode=update`)
**Current**: Updates frames by matching URIs in document
```python
update_entity_frames(space_id, graph_id, entity_uri=entity_uri, document=doc)
# Updates frames found in document
```

**Proposed**: Add parent frame context for scoped updates
```python
update_entity_frames(space_id, graph_id, entity_uri=entity_uri, document=doc, parent_frame_uri=parent_uri)
# Updates frames that are children of specified parent
```

**Logic**:
- If `parent_frame_uri` is None: Update top-level frames (children of entity via `Edge_hasEntityKGFrame`)
- If `parent_frame_uri` is provided: Only update frames that are children of specified parent frame
- Validate frame ownership before updating
- Return error if frames to update are not children of specified parent
- Entity is the implicit parent when `parent_frame_uri` is None

---

#### 5. Delete Frames (`DELETE`)
**Current**: Deletes specific frames by URI list
```python
delete_entity_frames(space_id, graph_id, entity_uri=entity_uri, frame_uris=[frame1, frame2])
# Deletes specified frames
```

**Proposed**: Add parent frame context for scoped deletion
```python
delete_entity_frames(space_id, graph_id, entity_uri=entity_uri, frame_uris=[frame1], parent_frame_uri=parent_uri)
# Deletes specified frames that are children of parent
```

**Logic**:
- If `parent_frame_uri` is None: Delete specified top-level frames (children of entity via `Edge_hasEntityKGFrame`)
- If `parent_frame_uri` is provided: Validate frames are children of parent frame before deletion
- Return error if frames to delete are not children of specified parent
- Provides safety check against accidental deletion of wrong frames
- Entity is the implicit parent when `parent_frame_uri` is None

---

## Implementation Plan

### Phase 1: Client Updates
**Files to Modify**:
- `/vitalgraph/client/endpoint/kgentities_endpoint.py`

**Changes**:
1. Add `parent_frame_uri: Optional[str] = None` parameter to all frame methods
2. Update `get_kgentity_frames()` signature to include `parent_frame_uri`
3. Update `create_entity_frames()` - parameter already exists, no change needed
4. Update `update_entity_frames()` - add `parent_frame_uri` parameter
5. Update `delete_entity_frames()` - add `parent_frame_uri` parameter
6. Update docstrings to document hierarchical behavior

### Phase 2: Server Endpoint Updates
**Files to Modify**:
- `/vitalgraph/endpoint/kgentities_endpoint.py`

**Changes**:
1. Update route handlers to accept `parent_frame_uri` query parameter
2. Pass `parent_frame_uri` to implementation layer
3. Update request validation to handle `parent_frame_uri`
4. Update response handling for hierarchical operations

### Phase 3: Implementation Layer Updates
**Files to Modify**:
- `/vitalgraph/endpoint/impl/kgentity_frame_impl.py` (or similar)
- `/vitalgraph/kg_impl/kgentity_frame_*.py` files

**Changes**:

#### List Frames
1. Add `parent_frame_uri` parameter to list implementation
2. If `parent_frame_uri` provided:
   - Query for `Edge_hasKGFrame` edges where source = `parent_frame_uri`
   - Extract destination frame URIs (children)
   - Filter frame list to only include children
3. Return filtered results

#### Get Frames
1. Add `parent_frame_uri` parameter to get implementation
2. If `parent_frame_uri` provided:
   - Validate requested frames are children of parent
   - Query `Edge_hasKGFrame` to verify parent-child relationship
   - Return error if validation fails
3. Return requested frames with validation

#### Create Frames
1. Keep `parent_frame_uri` parameter (already exists)
2. If `parent_frame_uri` provided:
   - Create `Edge_hasKGFrame` from parent to new frames
   - Set proper `hasFrameGraphURI` for hierarchical context
3. Maintain backward compatibility (treat null as top-level)

#### Update Frames
1. Add `parent_frame_uri` parameter to update implementation
2. If `parent_frame_uri` provided:
   - Validate frames to update are children of parent
   - Query `Edge_hasKGFrame` for validation
   - Return error if validation fails
3. Proceed with update if validation passes

#### Delete Frames
1. Add `parent_frame_uri` parameter to delete implementation
2. If `parent_frame_uri` provided:
   - Validate frames to delete are children of parent
   - Query `Edge_hasKGFrame` for validation
   - Return error if validation fails
3. Proceed with deletion if validation passes

### Phase 4: SPARQL Query Updates
**Files to Modify**:
- `/vitalgraph/kg_impl/kg_sparql_query.py` (or frame-specific query files)

**Changes**:
1. Add helper function to query child frames:
```sparql
SELECT ?childFrame WHERE {
    GRAPH <{graph_id}> {
        ?edge a <{haley_prefix}Edge_hasKGFrame> .
        ?edge <{vital_prefix}hasEdgeSource> <{parent_frame_uri}> .
        ?edge <{vital_prefix}hasEdgeDestination> ?childFrame .
    }
}
```

2. Add validation query for parent-child relationship:
```sparql
ASK WHERE {
    GRAPH <{graph_id}> {
        ?edge a <{haley_prefix}Edge_hasKGFrame> .
        ?edge <{vital_prefix}hasEdgeSource> <{parent_frame_uri}> .
        ?edge <{vital_prefix}hasEdgeDestination> <{child_frame_uri}> .
    }
}
```

3. Integrate queries into frame operations

### Phase 5: Model Updates
**Files to Modify**:
- `/vitalgraph/model/kgframes_model.py`

**Changes**:
1. Update request models if needed to include `parent_frame_uri`
2. Update response models if hierarchical context needs to be returned
3. Add validation for `parent_frame_uri` format

### Phase 6: Testing
**Files to Create/Modify**:
- `/vitalgraph_client_test/entity_graph_lead/case_frame_operations.py`
- New test cases for hierarchical operations

**Test Cases**:
1. **List child frames**: Verify only children of parent are returned
2. **Get frame with parent context**: Verify validation works
3. **Create child frame**: Verify proper edge creation
4. **Update child frame**: Verify scoped updates work
5. **Delete child frame**: Verify validation prevents wrong deletions
6. **Error cases**: Test invalid parent-child relationships

### Phase 7: Documentation
**Files to Update**:
- API documentation
- Client library documentation
- Migration guide for `parent_frame_uri` → `frame_uri` change

---

## Breaking Changes

### No Breaking Changes
The `parent_frame_uri` parameter name is kept consistent across all operations:
- **Create**: Already uses `parent_frame_uri` (no change)
- **List/Get/Update/Delete**: Adding `parent_frame_uri` as optional parameter (backward compatible)

**Migration**: No migration needed - all changes are backward compatible

---

## Backward Compatibility

### Maintaining Compatibility
1. `parent_frame_uri` is optional (defaults to None)
2. When None, operations behave as before (no filtering/validation)
3. No breaking changes - parameter name consistent across all operations

### Migration Path
1. No migration needed - all changes are backward compatible
2. Existing code without `parent_frame_uri` continues to work
3. New hierarchical features are opt-in via `parent_frame_uri` parameter

---

## Benefits

### 1. Hierarchical Navigation
- Navigate frame trees by parent-child relationships
- List children of specific frames
- Build frame tree UI components

### 2. Safety and Validation
- Prevent accidental operations on wrong frames
- Validate parent-child relationships before operations
- Scoped operations reduce errors

### 3. Performance
- Filter frames at query level (not client-side)
- Reduce data transfer for large frame graphs
- Enable efficient tree navigation

### 4. Consistency
- Single parameter name (`parent_frame_uri`) across all operations
- Uniform behavior for hierarchical context
- Clear semantic meaning indicating parent relationship

---

## Example Usage

### Navigate Frame Hierarchy
```python
# Get top-level frames for entity
top_frames = client.kgentities.get_kgentity_frames(
    space_id="space1",
    graph_id="graph1",
    entity_uri="urn:entity:123"
)

# Get children of a specific frame
company_frame_uri = "urn:entity:123:frame:companyframe:0"
child_frames = client.kgentities.get_kgentity_frames(
    space_id="space1",
    graph_id="graph1",
    entity_uri="urn:entity:123",
    parent_frame_uri=company_frame_uri  # Only get children of this frame
)
```

### Create Nested Frame
```python
# Create a child frame under company frame
new_address_frame = create_address_frame_document()
client.kgentities.create_entity_frames(
    space_id="space1",
    graph_id="graph1",
    entity_uri="urn:entity:123",
    document=new_address_frame,
    parent_frame_uri=company_frame_uri  # Attach as child of company frame
)
```

### Safe Scoped Update
```python
# Update only frames under company frame
updated_data = update_company_data()
client.kgentities.update_entity_frames(
    space_id="space1",
    graph_id="graph1",
    entity_uri="urn:entity:123",
    document=updated_data,
    parent_frame_uri=company_frame_uri  # Only update children of company frame
)
```

### Safe Scoped Deletion
```python
# Delete specific child frame with parent validation
client.kgentities.delete_entity_frames(
    space_id="space1",
    graph_id="graph1",
    entity_uri="urn:entity:123",
    frame_uris=["urn:entity:123:frame:companyframe:0:frame:oldaddress:0"],
    parent_frame_uri=company_frame_uri  # Validate it's a child before deleting
)
```

---

## Implementation Priority

### High Priority
1. ✅ Client parameter updates (Phase 1)
2. ✅ Server endpoint updates (Phase 2)
3. ✅ List frames with parent filtering (Phase 3)
4. ✅ Create frames with parent context (Phase 3)

### Medium Priority
5. ⬜ Get frames with parent validation (Phase 3)
6. ⬜ Update frames with parent scoping (Phase 3)
7. ⬜ Delete frames with parent validation (Phase 3)
8. ⬜ SPARQL query helpers (Phase 4)

### Low Priority
9. ⬜ Comprehensive testing (Phase 6)
10. ⬜ Documentation updates (Phase 7)

---

## Notes

### Design Decisions
1. **Parameter name**: `frame_uri` chosen over `parent_frame_uri` for brevity and consistency
2. **Optional parameter**: Maintains backward compatibility
3. **Validation approach**: Server-side validation prevents invalid operations
4. **Query optimization**: Filter at SPARQL level for performance

### Edge Cases
1. **Circular references**: Not possible with current frame model (frames are DAG)
2. **Deep hierarchies**: No depth limit, queries handle arbitrary depth
3. **Multiple parents**: Current model supports single parent per frame
4. **Orphaned frames**: Frames without parent edges are top-level

### Future Enhancements
1. Recursive child listing (all descendants)
2. Frame path queries (root to leaf)
3. Frame tree structure in response
4. Bulk hierarchical operations
