# Graphs Client API Cleanup Plan

## Overview

This document outlines the plan to refactor the Graphs client API to provide a clean, consistent interface while maintaining 100% compatibility with the existing server implementation. No server-side changes will be made - this is purely a client-side API cleanup following the same successful pattern used for Files, KGEntities, and Spaces endpoints.

## Current State Analysis

### Current API (graphs_endpoint.py)

**Methods:**
1. `list_graphs(space_id: str) -> List[GraphInfo]`
2. `get_graph_info(space_id: str, graph_uri: str) -> Optional[GraphInfo]`
3. `create_graph(space_id: str, graph_uri: str) -> SPARQLGraphResponse`
4. `drop_graph(space_id: str, graph_uri: str, silent: bool = False) -> SPARQLGraphResponse`
5. `clear_graph(space_id: str, graph_uri: str) -> SPARQLGraphResponse`

### Current Response Models

**Models in use:**
- `GraphInfo` - Graph metadata model (from sparql_model.py)
- `SPARQLGraphResponse` - Generic SPARQL graph operation response
- `SPARQLGraphRequest` - Request model for graph operations

### Issues with Current API

1. **Inconsistent Response Handling**
   - `list_graphs()` returns raw `List[GraphInfo]` instead of wrapped response
   - `get_graph_info()` returns raw `Optional[GraphInfo]` instead of wrapped response
   - Other methods return `SPARQLGraphResponse` which may not have consistent properties
   - No standard `.is_success`, `.error_message` pattern

2. **Complex Test Code**
   - Tests check multiple conditions: `hasattr(response, 'success')`, etc.
   - Inconsistent success checking patterns across different operations
   - No unified error handling approach

3. **Missing Response Wrappers**
   - No `GraphResponse` for single graph retrieval
   - No `GraphsListResponse` for graph listing
   - No `GraphCreateResponse`, `GraphDeleteResponse`, `GraphClearResponse` for operations

4. **Space Operations Mixed In**
   - Test file uses old Spaces API patterns (`add_space()`, complex conditionals)
   - Needs update to use new Spaces API (`create_space()`, `.is_success`)

## Goals

1. **Consistent Response Objects**: All operations return typed response objects with standard properties
2. **Clean API**: Simple, predictable method signatures
3. **Standard Success Checking**: All responses have `.is_success`, `.is_error`, `.error_message`
4. **No Server Changes**: Internal server communication remains identical
5. **Backward Compatible**: Existing response models extended, not replaced

## Proposed Changes

### New Response Classes

Add to `client_response.py`:

```python
# ============================================================================
# Graphs Response Classes
# ============================================================================

class GraphResponse(VitalGraphResponse):
    """Response for single graph retrieval operations."""
    graph: Optional[Any] = Field(None, description="Retrieved graph info")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.graph is not None and not self.error_code


class GraphsListResponse(VitalGraphResponse):
    """Response for graphs listing operations."""
    graphs: List[Any] = Field(default_factory=list, description="List of graphs")
    total: int = Field(0, description="Total number of graphs")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return not self.error_code
    
    @property
    def count(self) -> int:
        """Get count of graphs."""
        return len(self.graphs)


class GraphCreateResponse(VitalGraphResponse):
    """Response for graph creation operations."""
    graph_uri: Optional[str] = Field(None, description="Created graph URI")
    created: bool = Field(False, description="Whether graph was created")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.created and not self.error_code


class GraphDeleteResponse(VitalGraphResponse):
    """Response for graph deletion operations."""
    graph_uri: Optional[str] = Field(None, description="Deleted graph URI")
    deleted: bool = Field(False, description="Whether graph was deleted")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.deleted and not self.error_code


class GraphClearResponse(VitalGraphResponse):
    """Response for graph clear operations."""
    graph_uri: Optional[str] = Field(None, description="Cleared graph URI")
    cleared: bool = Field(False, description="Whether graph was cleared")
    triples_removed: int = Field(0, description="Number of triples removed")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.cleared and not self.error_code
```

### Refactored API Methods

Update `graphs_endpoint.py`:

```python
class GraphsEndpoint(BaseEndpoint):
    """Client endpoint for Graph management operations."""
    
    def list_graphs(self, space_id: str) -> GraphsListResponse:
        """
        List graphs in a space.
        
        Args:
            space_id: Space identifier
            
        Returns:
            GraphsListResponse with graphs list
        """
        # Implementation wraps server response in GraphsListResponse
        # Server call remains unchanged (GET /api/graphs/sparql/{space_id}/graphs)
        pass
    
    def get_graph_info(self, space_id: str, graph_uri: str) -> GraphResponse:
        """
        Get information about a specific graph.
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI
            
        Returns:
            GraphResponse with graph info
        """
        # Now returns GraphResponse instead of Optional[GraphInfo]
        # Server call remains unchanged (GET /api/graphs/sparql/{space_id}/graph/{graph_uri})
        pass
    
    def create_graph(self, space_id: str, graph_uri: str) -> GraphCreateResponse:
        """
        Create a new graph.
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI to create
            
        Returns:
            GraphCreateResponse with creation result
        """
        # Server call remains unchanged (PUT /api/graphs/sparql/{space_id}/graph/{graph_uri})
        pass
    
    def drop_graph(self, space_id: str, graph_uri: str, silent: bool = False) -> GraphDeleteResponse:
        """
        Drop (delete) a graph.
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI to drop
            silent: Execute silently (optional)
            
        Returns:
            GraphDeleteResponse with deletion result
        """
        # Server call remains unchanged (DELETE /api/graphs/sparql/{space_id}/graph/{graph_uri})
        pass
    
    def clear_graph(self, space_id: str, graph_uri: str) -> GraphClearResponse:
        """
        Clear a graph (remove all triples but keep the graph).
        
        Args:
            space_id: Space identifier
            graph_uri: Graph URI to clear
            
        Returns:
            GraphClearResponse with clear operation result
        """
        # Server call remains unchanged (POST /api/graphs/sparql/{space_id}/graph)
        pass
```

## Implementation Plan

### Phase 1: Create Response Classes
- [ ] Add new response classes to `client_response.py`
- [ ] Add imports to `response_builder.py`
- [ ] Ensure all responses have `.is_success`, `.is_error`, `.error_message` properties

### Phase 2: Refactor GraphsEndpoint
- [ ] Backup original `graphs_endpoint.py` to `graphs_endpoint_old.py`
- [ ] Update `list_graphs()` to return `GraphsListResponse`
- [ ] Update `get_graph_info()` to return `GraphResponse`
- [ ] Update `create_graph()` to return `GraphCreateResponse`
- [ ] Update `drop_graph()` to return `GraphDeleteResponse`
- [ ] Update `clear_graph()` to return `GraphClearResponse`

### Phase 3: Update Test Files

#### Main Test File to Update

**`test_graphs_endpoint.py`**
- Location: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph_client_test/test_graphs_endpoint.py`
- Lines to update:
  - ~103-119: Space listing and deletion (update to new Spaces API)
  - ~132-140: Space creation (change `add_space()` to `create_space()`)
  - ~246-253: Space deletion cleanup (update to new Spaces API)
  - Graph operations throughout (update to use new response objects)

#### Detailed Update Patterns

**Pattern 1: Update Space Operations (Spaces API)**

Before:
```python
spaces_response: SpacesListResponse = client.list_spaces()
existing_spaces = spaces_response.spaces
existing_space = next((s for s in existing_spaces if s.space == test_space_id), None)

if existing_space:
    delete_response = client.delete_space(test_space_id)
    if delete_response and hasattr(delete_response, 'success') and delete_response.success:
        print(f"   ✓ Existing space deleted successfully")

create_response = client.add_space(space_data)
if create_response and create_response.created_count == 1:
    print(f"   ✓ Test space created successfully")
```

After:
```python
spaces_response = client.spaces.list_spaces()
if spaces_response.is_success:
    existing_space = next((s for s in spaces_response.spaces if s.space == test_space_id), None)
    
    if existing_space:
        delete_response = client.spaces.delete_space(test_space_id)
        if delete_response.is_success:
            print(f"   ✓ Existing space deleted successfully")

create_response = client.spaces.create_space(space_data)
if create_response.is_success:
    print(f"   ✓ Test space created successfully: {create_response.space.space if create_response.space else test_space_id}")
```

**Pattern 2: Graph Listing**

Before:
```python
graphs = client.list_graphs(space_id)
print(f"Found {len(graphs)} graphs")
for graph in graphs:
    print(f"  - {graph.graph_uri}")
```

After:
```python
response = client.graphs.list_graphs(space_id)
if response.is_success:
    print(f"Found {response.count} graphs")
    for graph in response.graphs:
        print(f"  - {graph.graph_uri}")
else:
    print(f"Failed to list graphs: {response.error_message}")
```

**Pattern 3: Graph Creation**

Before:
```python
response = client.create_graph(space_id, graph_uri)
# Check response.success or similar
```

After:
```python
response = client.graphs.create_graph(space_id, graph_uri)
if response.is_success:
    print(f"✅ Graph created: {response.graph_uri}")
else:
    print(f"❌ Failed: {response.error_message}")
```

**Pattern 4: Graph Deletion**

Before:
```python
response = client.drop_graph(space_id, graph_uri)
# Check response
```

After:
```python
response = client.graphs.drop_graph(space_id, graph_uri)
if response.is_success:
    print(f"✅ Graph deleted: {response.graph_uri}")
else:
    print(f"❌ Failed: {response.error_message}")
```

**Pattern 5: Graph Info Retrieval**

Before:
```python
graph_info = client.get_graph_info(space_id, graph_uri)
if graph_info:
    print(f"Graph: {graph_info.graph_uri}")
else:
    print("Graph not found")
```

After:
```python
response = client.graphs.get_graph_info(space_id, graph_uri)
if response.is_success and response.graph:
    print(f"Graph: {response.graph.graph_uri}")
else:
    print(f"Graph not found: {response.error_message if response.error_message else 'Not found'}")
```

**Pattern 6: Graph Clear**

Before:
```python
response = client.clear_graph(space_id, graph_uri)
# Check response
```

After:
```python
response = client.graphs.clear_graph(space_id, graph_uri)
if response.is_success:
    print(f"✅ Graph cleared: {response.graph_uri}")
    print(f"   Removed {response.triples_removed} triples")
else:
    print(f"❌ Failed: {response.error_message}")
```

#### Update Checklist

- [ ] **test_graphs_endpoint.py**
  - [ ] Update space listing (lines ~103-106)
  - [ ] Update space deletion (lines ~110-119)
  - [ ] Update space creation (lines ~132-140, change `add_space()` to `create_space()`)
  - [ ] Update space cleanup deletion (lines ~246-253)
  - [ ] Update graph operations to use new response objects
  - [ ] Replace complex conditionals with `.is_success`
  - [ ] Update all test case modules in `graphs/` directory if they exist

### Phase 4: Testing
- [ ] Run `test_graphs_endpoint.py` to ensure compatibility
- [ ] Verify no server-side changes required
- [ ] Confirm all operations work as before

## Test Code Improvements

### Before (Current Pattern)

```python
# Complex space operations
spaces_response: SpacesListResponse = client.list_spaces()
existing_spaces = spaces_response.spaces
existing_space = next((s for s in existing_spaces if s.space == test_space_id), None)

if existing_space:
    delete_response = client.delete_space(test_space_id)
    if delete_response and hasattr(delete_response, 'success') and delete_response.success:
        print(f"   ✓ Existing space deleted successfully")

# Raw list response
graphs = client.list_graphs(space_id)
for graph in graphs:
    print(f"  - {graph.graph_uri}")

# Optional return
graph_info = client.get_graph_info(space_id, graph_uri)
if graph_info:
    print(f"Graph exists")
```

### After (Clean Pattern)

```python
# Simple space operations
spaces_response = client.spaces.list_spaces()
if spaces_response.is_success:
    existing_space = next((s for s in spaces_response.spaces if s.space == test_space_id), None)
    
    if existing_space:
        delete_response = client.spaces.delete_space(test_space_id)
        if delete_response.is_success:
            print(f"   ✓ Existing space deleted")

# Typed response
response = client.graphs.list_graphs(space_id)
if response.is_success:
    print(f"Found {response.count} graphs")
    for graph in response.graphs:
        print(f"  - {graph.graph_uri}")
else:
    print(f"Failed: {response.error_message}")

# Typed response
response = client.graphs.get_graph_info(space_id, graph_uri)
if response.is_success and response.graph:
    print(f"Graph exists: {response.graph.graph_uri}")
else:
    print(f"Graph not found")
```

## Server Communication (Unchanged)

All server API calls remain identical:

- `GET /api/graphs/sparql/{space_id}/graphs` - List graphs
- `GET /api/graphs/sparql/{space_id}/graph/{graph_uri}` - Get graph info
- `PUT /api/graphs/sparql/{space_id}/graph/{graph_uri}` - Create graph
- `DELETE /api/graphs/sparql/{space_id}/graph/{graph_uri}` - Delete graph
- `POST /api/graphs/sparql/{space_id}/graph` - Clear graph (with operation=CLEAR)

The refactoring only changes:
1. How responses are wrapped on the client side
2. Response object structure for easier access
3. Space operations updated to use new Spaces API

## Benefits

1. **Consistent API**: All operations follow the same pattern as Files, KGEntities, and Spaces
2. **Easier Testing**: Simple `.is_success` checks instead of complex conditionals
3. **Better Type Safety**: Typed responses instead of raw lists/optionals
4. **Clear Documentation**: Response objects document what's available
5. **Maintainable**: Follows same pattern across all endpoints
6. **No Breaking Changes**: Server communication unchanged

## Success Criteria

- [ ] Test file passes with updated code
- [ ] Response objects have consistent `.is_success`, `.is_error`, `.error_message`
- [ ] No server-side changes required
- [ ] Test code is simpler and more readable
- [ ] API follows same patterns as Files, KGEntities, and Spaces endpoints
- [ ] Space operations use new Spaces API (`create_space()`, `.is_success`)

## Notes

- Update test file to use new Spaces API patterns
- Ensure all response builders handle server responses correctly
- Document migration path for existing code using old patterns
- Consider adding deprecation warnings for old patterns in future release
- Graph operations are simpler than entity/file operations (no complex object graphs)

## Outstanding Issues

### Issue: Entity graph_id vs SPARQL Graphs

**Discovered During:** Integration of graphs test case into `test_multiple_organizations_crud.py`

**Problem:**
Entity creation with `graph_id` parameter does NOT automatically create SPARQL graphs in the graph store. The `graph_id` is used as a logical grouping identifier for entities but does not result in a SPARQL graph being created.

**Test Case Created:**
- File: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph_client_test/multi_kgentity/case_list_graphs.py`
- Integrated into: `test_multiple_organizations_crud.py` (Step 2.5)
- Tests: Graph listing and get_graph_info using new Graphs API

**Test Failure:**
```
❌ FAIL: List and Verify Graphs
   Tests: 0/2 passed
   Errors:
      • List graphs in space: Expected graph not found in list: urn:multi_org_crud_graph
      • Get graph info: Failed to get graph info: 500 Server Error
```

**Root Cause:**
- Entity creation stores `graph_id` with entity data as a logical grouping
- SPARQL graphs must be explicitly created via `client.graphs.create_graph()`
- The Graphs endpoint lists SPARQL graphs from the graph store, not entity `graph_id` values
- These are two separate concepts that happen to use similar terminology

**Expected Behavior:**
Graphs should be created automatically when data is inserted for a graph URI. This is the correct architectural approach.

**Current Behavior:**
Entity creation with `graph_id` parameter does not automatically create the corresponding SPARQL graph in the graph store.

**Required Fix:**
Update the entity creation implementation to automatically create SPARQL graphs when entities are inserted with a `graph_id` that doesn't yet exist as a SPARQL graph.

**Impact:**
- Entity operations will automatically ensure the target graph exists
- Aligns entity `graph_id` with SPARQL graph management
- Test case will pass once this fix is implemented

**Status:** Bug identified - requires implementation fix in entity creation logic
