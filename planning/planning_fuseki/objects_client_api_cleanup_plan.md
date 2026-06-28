# Objects Client API Cleanup Plan

## Overview

This document outlines the plan to refactor the Objects client API to provide a clean, consistent interface similar to the Files, KGEntities, KGTypes, Spaces, and Graphs endpoints. The refactoring focuses on **client-side only** changes - no server API modifications.

## Current State Analysis

### Existing Client API (vitalgraph/client/endpoint/objects_endpoint.py)

**Current Methods:**
1. `list_objects(space_id, graph_id, page_size, offset, search)` → `ObjectsResponse`
2. `get_object(space_id, graph_id, uri)` → `ObjectsResponse`
3. `create_objects(space_id, graph_id, document)` → `ObjectCreateResponse`
4. `update_objects(space_id, graph_id, document)` → `ObjectUpdateResponse`
5. `delete_object(space_id, graph_id, uri)` → `ObjectDeleteResponse`
6. `delete_objects_batch(space_id, graph_id, uri_list)` → `ObjectDeleteResponse`

**Current Response Models (vitalgraph/model/objects_model.py):**
- `ObjectsResponse` - List and retrieval operations (extends `BasePaginatedResponse`)
- `SingleObjectResponse` - Single object retrieval (not currently used)
- `ObjectCreateResponse` - Create operations (extends `BaseCreateResponse`)
- `ObjectUpdateResponse` - Update operations (extends `BaseUpdateResponse`)
- `ObjectDeleteResponse` - Delete operations (extends `BaseDeleteResponse`)

### Issues with Current API

1. **Inconsistent Response Handling:**
   - `ObjectsResponse` returns `Union[JsonLdObject, JsonLdDocument]` in `objects` field
   - No unified response pattern with `.is_success` property
   - Server response models directly returned without client-side wrapping
   - Complex error checking required by clients

2. **No Typed Response Objects:**
   - Responses don't follow the pattern established in Files/Entities/Spaces/Graphs/KGTypes
   - Missing `.is_success`, `.error_message`, `.count` properties
   - Clients must check multiple conditions for success/failure

3. **Inconsistent Return Types:**
   - Both `list_objects()` and `get_object()` return `ObjectsResponse`
   - No distinction between single object vs multiple objects responses
   - `SingleObjectResponse` model exists but is not used

4. **Missing Convenience Methods:**
   - No `get_objects_by_uris()` method (though test script uses it - may be added elsewhere)
   - No clear separation between single and batch operations

5. **Test File Complexity:**
   - Test file: `vitalgraph_client_test/test_objects_endpoint.py`
   - Tests use complex success checking logic
   - No simple `.is_success` pattern

## Refactoring Goals

### Primary Objectives

1. **Create Unified Response Classes** with consistent properties:
   - `.is_success` - Boolean indicating success/failure
   - `.error_message` - Error message if failed
   - `.error_code` - Error code if failed
   - `.count` - Count of items (for list operations)
   - `.object` / `.objects` - Single or multiple object data

2. **Maintain Server API Compatibility:**
   - No changes to server endpoints
   - No changes to request/response formats
   - Only client-side response wrapping

3. **Simplify Client Usage:**
   - Consistent `.is_success` checking
   - Clear error messages
   - Type-safe responses

4. **Update Test File:**
   - Simplify success checking
   - Use new response patterns
   - Maintain 100% test coverage

## Proposed Changes

### Phase 1: Create New Response Classes

**Location:** `vitalgraph/client/response/client_response.py`

Add new response classes following the pattern from Files/Entities/Spaces/Graphs/KGTypes:

```python
class ObjectResponse(VitalGraphResponse):
    """Response for single object retrieval operations."""
    object: Optional[Any] = Field(None, description="Retrieved object data")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.object is not None and not self.error_code


class ObjectsListResponse(VitalGraphResponse):
    """Response for object list operations."""
    objects: List[Any] = Field(default_factory=list, description="List of objects")
    count: int = Field(0, description="Total count of objects")
    page_size: Optional[int] = Field(None, description="Page size for pagination")
    offset: Optional[int] = Field(None, description="Offset for pagination")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return not self.error_code


class ObjectCreateResponse(VitalGraphResponse):
    """Response for object create operations."""
    created: bool = Field(False, description="Whether objects were created")
    created_count: int = Field(0, description="Number of objects created")
    created_uris: List[str] = Field(default_factory=list, description="URIs of created objects")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.created and self.created_count > 0 and not self.error_code


class ObjectUpdateResponse(VitalGraphResponse):
    """Response for object update operations."""
    updated: bool = Field(False, description="Whether objects were updated")
    updated_count: int = Field(0, description="Number of objects updated")
    updated_uris: List[str] = Field(default_factory=list, description="URIs of updated objects")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.updated and self.updated_count > 0 and not self.error_code


class ObjectDeleteResponse(VitalGraphResponse):
    """Response for object delete operations."""
    deleted: bool = Field(False, description="Whether objects were deleted")
    deleted_count: int = Field(0, description="Number of objects deleted")
    deleted_uris: List[str] = Field(default_factory=list, description="URIs of deleted objects")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.deleted and not self.error_code
```

### Phase 2: Update ObjectsEndpoint Methods

**Location:** `vitalgraph/client/endpoint/objects_endpoint.py`

Update all methods to return new response classes:

**Before:**
```python
def list_objects(self, space_id, graph_id, page_size=10, offset=0, search=None) -> ObjectsResponse:
    return self._make_typed_request('GET', url, ObjectsResponse, params=params)
```

**After:**
```python
def list_objects(self, space_id, graph_id, page_size=10, offset=0, search=None) -> ObjectsListResponse:
    try:
        server_response = self._make_typed_request('GET', url, ServerObjectsResponse, params=params)
        
        # Extract objects from server response - handle data field
        objects = []
        if hasattr(server_response, 'objects'):
            if isinstance(server_response.objects, JsonLdObject):
                objects = [server_response.objects]
            elif isinstance(server_response.objects, JsonLdDocument):
                objects = server_response.objects.graph if server_response.objects.graph else []
        count = len(objects)
        
        return build_success_response(
            ObjectsListResponse,
            status_code=200,
            message=f"Retrieved {count} objects",
            objects=objects,
            count=count,
            page_size=page_size,
            offset=offset
        )
        
    except VitalGraphClientError as e:
        return build_error_response(
            ObjectsListResponse,
            error_code=e.status_code or 500,
            error_message=str(e),
            status_code=e.status_code or 500
        )
```

**Changes for each method:**

1. **`list_objects()`** → Returns `ObjectsListResponse` with `.count` property
2. **`get_object()`** → Returns `ObjectResponse` with `.object` property (single object)
3. **`get_objects_by_uris()`** → Returns `ObjectsListResponse` with `.count` property (if method exists)
4. **`create_objects()`** → Returns `ObjectCreateResponse` with `.created_count` property
5. **`update_objects()`** → Returns `ObjectUpdateResponse` with `.updated_count` property
6. **`delete_object()`** → Returns `ObjectDeleteResponse` with `.deleted` property
7. **`delete_objects_batch()`** → Returns `ObjectDeleteResponse` with `.deleted_count` property

### Phase 3: Update Test File

**Location:** `vitalgraph_client_test/test_objects_endpoint.py`

**Current Pattern:**
```python
response = client.objects.list_objects(space_id, graph_id)
if response and hasattr(response, 'objects'):
    # Success
```

**New Pattern:**
```python
response = client.objects.list_objects(space_id, graph_id)
if response.is_success:
    print(f"Found {response.count} objects")
    for obj in response.objects:
        # Process object
```

**Test Updates Needed:**
- Update all success checking to use `.is_success`
- Use `.count` property for object counts
- Use `.object` for single object retrieval
- Use `.objects` for list operations
- Simplify error handling with `.error_message`

### Phase 4: Response Builder Integration

**Location:** `vitalgraph/client/response/response_builder.py`

Add imports for new response classes:

```python
from .client_response import (
    # ... existing imports ...
    ObjectResponse,
    ObjectsListResponse,
    ObjectCreateResponse,
    ObjectUpdateResponse,
    ObjectDeleteResponse
)
```

## Implementation Plan

### Step-by-Step Execution

**Phase 1: Response Classes (30 minutes)**
- [ ] Add 5 new response classes to `client_response.py`
- [ ] Add imports to `response_builder.py`
- [ ] Verify Pydantic models validate correctly

**Phase 2: Endpoint Refactoring (45 minutes)**
- [ ] Backup original `objects_endpoint.py`
- [ ] Update imports to alias server response models
- [ ] Update `list_objects()` method
- [ ] Update `get_object()` method
- [ ] Update `create_objects()` method
- [ ] Update `update_objects()` method
- [ ] Update `delete_object()` method
- [ ] Update `delete_objects_batch()` method
- [ ] Add consistent error handling to all methods
- [ ] Preserve exact server request/response handling

**Phase 3: Test File Updates (60 minutes)**
- [ ] Update `test_objects_endpoint.py` main test flow
- [ ] Update list objects tests to use `.is_success` and `.count`
- [ ] Update get object tests to use `.object` property
- [ ] Update create tests to use `.created_count`
- [ ] Update update tests to use `.updated_count`
- [ ] Update delete tests to use `.deleted` property
- [ ] Simplify all success checking to use `.is_success`

**Phase 4: Testing & Verification (30 minutes)**
- [ ] Run `test_objects_endpoint.py`
- [ ] Verify all tests pass
- [ ] Check error handling works correctly
- [ ] Verify no server API changes needed

## Expected Benefits

### For Developers

1. **Consistent API Pattern:**
   ```python
   # All endpoints follow same pattern
   response = client.objects.list_objects(space_id, graph_id)
   if response.is_success:
       print(f"Found {response.count} objects")
   else:
       print(f"Error: {response.error_message}")
   ```

2. **Type Safety:**
   - Clear return types
   - IDE autocomplete support
   - Compile-time type checking

3. **Simplified Error Handling:**
   - Single `.is_success` check
   - Clear `.error_message` property
   - Consistent error codes

### For Testing

1. **Cleaner Test Code:**
   ```python
   # Before
   if response and hasattr(response, 'objects'):
       # Complex checking
   
   # After
   if response.is_success:
       # Simple checking
   ```

2. **Better Assertions:**
   ```python
   assert response.is_success, f"Failed: {response.error_message}"
   assert response.count == expected_count
   ```

## Compatibility Notes

### Backward Compatibility

- **Server API:** No changes - fully compatible
- **Request Format:** No changes - fully compatible
- **Response Format:** Wrapped in new client response objects
- **Existing Code:** Will need updates to use new response properties

### Migration Path

For existing code using the Objects endpoint:

**Old Code:**
```python
response = client.objects.list_objects(space_id, graph_id)
if response and hasattr(response, 'objects'):
    objects = response.objects
    if isinstance(objects, JsonLdDocument):
        for obj in objects.graph:
            process(obj)
```

**New Code:**
```python
response = client.objects.list_objects(space_id, graph_id)
if response.is_success:
    for obj in response.objects:
        process(obj)
```

## Testing Strategy

### Test Coverage

1. **Unit Tests:**
   - Test each response class `.is_success` property
   - Test error handling in each method
   - Test response wrapping logic

2. **Integration Tests:**
   - Run full `test_objects_endpoint.py` suite
   - Verify all operations pass
   - Test error scenarios

3. **Regression Tests:**
   - Verify server API calls unchanged
   - Verify request formats unchanged
   - Verify response data integrity

## Success Criteria

- [ ] All 5 new response classes created with `.is_success` properties
- [ ] All 6-7 ObjectsEndpoint methods updated to return new response types
- [ ] Test file `test_objects_endpoint.py` updated to use new API patterns
- [ ] All tests in `test_objects_endpoint.py` passing (100%)
- [ ] No server-side changes required
- [ ] No changes to server API request/response formats
- [ ] API follows same patterns as Files, KGEntities, KGTypes, Spaces, and Graphs endpoints

## Key Differences from Other Endpoints

### Objects vs KGTypes/KGEntities

1. **Simpler Data Model:**
   - Objects are generic GraphObjects
   - No complex entity graphs or frame relationships
   - Simpler response structure

2. **Direct JSON-LD Handling:**
   - Objects work directly with JSON-LD documents
   - Less transformation needed
   - More straightforward response wrapping

3. **Existing Test Coverage:**
   - `test_objects_endpoint.py` already comprehensive
   - Tests all CRUD operations
   - Good baseline for validation

## Notes

- This refactoring is **client-side only** - no server changes
- Server API endpoints remain unchanged
- Request/response formats to server remain unchanged
- Only the client response wrapping and convenience methods are updated
- Objects operations are simpler than entity operations (no complex object graphs)
- The test file `test_objects_endpoint.py` will be the primary validation tool

## Related Documentation

- Files Client API Cleanup: `planning_fuseki/files_client_api_cleanup_plan.md`
- KGEntities Client API Cleanup: `planning_fuseki/kgentities_client_api_cleanup_plan.md`
- KGTypes Client API Cleanup: `planning_fuseki/kgtypes_client_api_cleanup_plan.md`
- Spaces Client API Cleanup: `planning_fuseki/spaces_client_api_cleanup_plan.md`
- Graphs Client API Cleanup: `planning_fuseki/graphs_client_api_cleanup_plan.md`
- Test File: `vitalgraph_client_test/test_objects_endpoint.py`
- Current Endpoint: `vitalgraph/client/endpoint/objects_endpoint.py`
- Response Models: `vitalgraph/model/objects_model.py`

## Implementation Timeline

**Estimated Total Time:** 2.5 hours

- Phase 1: 30 minutes
- Phase 2: 45 minutes
- Phase 3: 60 minutes
- Phase 4: 30 minutes (testing & verification)

## Risk Assessment

**Low Risk:**
- Client-side only changes
- Server API unchanged
- Comprehensive test coverage exists
- Pattern proven successful in 5 other endpoints

**Mitigation:**
- Backup original files before changes
- Test after each phase
- Preserve exact server communication patterns
- Use proven response builder patterns
