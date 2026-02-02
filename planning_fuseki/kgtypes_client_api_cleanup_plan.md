# KGTypes Client API Cleanup Plan

## Overview

This document outlines the plan to refactor the KGTypes client API to provide a clean, consistent interface similar to the Files, KGEntities, Spaces, and Graphs endpoints. The refactoring focuses on **client-side only** changes - no server API modifications.

## Current State Analysis

### Existing Client API (vitalgraph/client/endpoint/kgtypes_endpoint.py)

**Current Methods:**
1. `list_kgtypes(space_id, graph_id, page_size, offset, search)` → `KGTypeListResponse`
2. `get_kgtype(space_id, graph_id, uri)` → `Union[KGTypeGetResponse, KGTypeListResponse]`
3. `get_kgtypes_by_uris(space_id, graph_id, uri_list)` → `KGTypeListResponse`
4. `create_kgtypes(space_id, graph_id, data)` → `KGTypeCreateResponse`
5. `update_kgtypes(space_id, graph_id, data)` → `KGTypeUpdateResponse`
6. `delete_kgtype(space_id, graph_id, uri)` → `KGTypeDeleteResponse`
7. `delete_kgtypes_batch(space_id, graph_id, uri_list)` → `KGTypeDeleteResponse`

**Current Response Models (vitalgraph/model/kgtypes_model.py):**
- `KGTypeListResponse` - List operations
- `KGTypeGetResponse` - Single type retrieval
- `KGTypeCreateResponse` - Create operations
- `KGTypeUpdateResponse` - Update operations
- `KGTypeDeleteResponse` - Delete operations

### Issues with Current API

1. **Inconsistent Response Handling:**
   - `get_kgtype()` returns `Union[KGTypeGetResponse, KGTypeListResponse]` with try/except fallback
   - No unified response pattern with `.is_success` property
   - Complex error checking required by clients

2. **No Typed Response Objects:**
   - Responses don't follow the pattern established in Files/Entities/Spaces/Graphs
   - Missing `.is_success`, `.error_message`, `.count` properties
   - Clients must check multiple conditions for success/failure

3. **Inconsistent Naming:**
   - Uses `create_kgtypes` (plural) but `delete_kgtype` (singular)
   - `delete_kgtypes_batch` is verbose compared to other endpoints

4. **Test File Complexity:**
   - Test file: `vitalgraph_client_test/test_kgtypes_endpoint.py`
   - Tests use complex success checking logic
   - No simple `.is_success` pattern

## Refactoring Goals

### Primary Objectives

1. **Create Unified Response Classes** with consistent properties:
   - `.is_success` - Boolean indicating success/failure
   - `.error_message` - Error message if failed
   - `.error_code` - Error code if failed
   - `.count` - Count of items (for list operations)
   - `.type` / `.types` - Single or multiple KGType data

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

Add new response classes following the pattern from Files/Entities/Spaces/Graphs:

```python
class KGTypeResponse(VitalGraphResponse):
    """Response for single KGType retrieval operations."""
    type: Optional[Any] = Field(None, description="Retrieved KGType data")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.type is not None and not self.error_code

class KGTypesListResponse(VitalGraphResponse):
    """Response for KGType list operations."""
    types: List[Any] = Field(default_factory=list, description="List of KGTypes")
    count: int = Field(0, description="Total count of types")
    page_size: Optional[int] = Field(None, description="Page size for pagination")
    offset: Optional[int] = Field(None, description="Offset for pagination")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return not self.error_code

class KGTypeCreateResponse(VitalGraphResponse):
    """Response for KGType create operations."""
    created: bool = Field(False, description="Whether types were created")
    created_count: int = Field(0, description="Number of types created")
    created_uris: List[str] = Field(default_factory=list, description="URIs of created types")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.created and self.created_count > 0 and not self.error_code

class KGTypeUpdateResponse(VitalGraphResponse):
    """Response for KGType update operations."""
    updated: bool = Field(False, description="Whether types were updated")
    updated_count: int = Field(0, description="Number of types updated")
    updated_uris: List[str] = Field(default_factory=list, description="URIs of updated types")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.updated and self.updated_count > 0 and not self.error_code

class KGTypeDeleteResponse(VitalGraphResponse):
    """Response for KGType delete operations."""
    deleted: bool = Field(False, description="Whether types were deleted")
    deleted_count: int = Field(0, description="Number of types deleted")
    deleted_uris: List[str] = Field(default_factory=list, description="URIs of deleted types")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.deleted and not self.error_code
```

### Phase 2: Update KGTypesEndpoint Methods

**Location:** `vitalgraph/client/endpoint/kgtypes_endpoint.py`

Update all methods to return new response classes:

**Before:**
```python
def list_kgtypes(self, space_id, graph_id, page_size=10, offset=0, search=None) -> KGTypeListResponse:
    return self._make_typed_request('GET', url, KGTypeListResponse, params=params)
```

**After:**
```python
def list_kgtypes(self, space_id, graph_id, page_size=10, offset=0, search=None) -> KGTypesListResponse:
    try:
        server_response = self._make_typed_request('GET', url, KGTypeListResponse, params=params)
        
        # Wrap server response in new client response
        return KGTypesListResponse(
            types=server_response.types if hasattr(server_response, 'types') else [],
            count=len(server_response.types) if hasattr(server_response, 'types') else 0,
            page_size=page_size,
            offset=offset,
            status_code=200,
            message="KGTypes retrieved successfully"
        )
    except VitalGraphClientError as e:
        return KGTypesListResponse(
            error_code=e.status_code or 500,
            error_message=str(e),
            status_code=e.status_code or 500
        )
```

**Changes for each method:**

1. **`list_kgtypes()`** → Returns `KGTypesListResponse` with `.count` property
2. **`get_kgtype()`** → Returns `KGTypeResponse` with `.type` property (remove Union return type)
3. **`get_kgtypes_by_uris()`** → Returns `KGTypesListResponse` with `.count` property
4. **`create_kgtypes()`** → Returns `KGTypeCreateResponse` with `.created_count` property
5. **`update_kgtypes()`** → Returns `KGTypeUpdateResponse` with `.updated_count` property
6. **`delete_kgtype()`** → Returns `KGTypeDeleteResponse` with `.deleted` property
7. **`delete_kgtypes_batch()`** → Returns `KGTypeDeleteResponse` with `.deleted_count` property

### Phase 3: Update Test File

**Location:** `vitalgraph_client_test/test_kgtypes_endpoint.py`

**Current Pattern:**
```python
response = client.list_kgtypes(space_id, graph_id)
if response and hasattr(response, 'types') and response.types:
    # Success
```

**New Pattern:**
```python
response = client.list_kgtypes(space_id, graph_id)
if response.is_success:
    print(f"Found {response.count} types")
    for kgtype in response.types:
        # Process type
```

**Test Case Modules to Update:**
1. `vitalgraph_client_test/kgtypes/case_kgtype_create.py`
2. `vitalgraph_client_test/kgtypes/case_kgtype_list.py`
3. `vitalgraph_client_test/kgtypes/case_kgtype_get.py`
4. `vitalgraph_client_test/kgtypes/case_kgtype_update.py`
5. `vitalgraph_client_test/kgtypes/case_kgtype_delete.py`

### Phase 4: Response Builder Integration

**Location:** `vitalgraph/client/response/response_builder.py`

Add imports for new response classes:

```python
from .client_response import (
    # ... existing imports ...
    KGTypeResponse,
    KGTypesListResponse,
    KGTypeCreateResponse,
    KGTypeUpdateResponse,
    KGTypeDeleteResponse
)
```

## Implementation Plan

### Step-by-Step Execution

**Phase 1: Response Classes (30 minutes)**
- [ ] Add 5 new response classes to `client_response.py`
- [ ] Add imports to `response_builder.py`
- [ ] Verify Pydantic models validate correctly

**Phase 2: Endpoint Refactoring (45 minutes)**
- [ ] Backup original `kgtypes_endpoint.py`
- [ ] Update `list_kgtypes()` method
- [ ] Update `get_kgtype()` method (remove Union return type)
- [ ] Update `get_kgtypes_by_uris()` method
- [ ] Update `create_kgtypes()` method
- [ ] Update `update_kgtypes()` method
- [ ] Update `delete_kgtype()` method
- [ ] Update `delete_kgtypes_batch()` method
- [ ] Add consistent error handling to all methods

**Phase 3: Test File Updates (60 minutes)**
- [ ] Update `test_kgtypes_endpoint.py` main orchestrator
- [ ] Update `case_kgtype_create.py` test module
- [ ] Update `case_kgtype_list.py` test module
- [ ] Update `case_kgtype_get.py` test module
- [ ] Update `case_kgtype_update.py` test module
- [ ] Update `case_kgtype_delete.py` test module
- [ ] Simplify all success checking to use `.is_success`

**Phase 4: Testing & Verification (30 minutes)**
- [ ] Run `test_kgtypes_endpoint.py`
- [ ] Verify all 16 tests pass
- [ ] Check error handling works correctly
- [ ] Verify no server API changes needed

## Expected Benefits

### For Developers

1. **Consistent API Pattern:**
   ```python
   # All endpoints follow same pattern
   response = client.kgtypes.list_kgtypes(space_id, graph_id)
   if response.is_success:
       print(f"Found {response.count} types")
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
   if response and hasattr(response, 'types') and response.types:
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

For existing code using the KGTypes endpoint:

**Old Code:**
```python
response = client.list_kgtypes(space_id, graph_id)
if response and hasattr(response, 'types'):
    for kgtype in response.types:
        process(kgtype)
```

**New Code:**
```python
response = client.list_kgtypes(space_id, graph_id)
if response.is_success:
    for kgtype in response.types:
        process(kgtype)
```

## Testing Strategy

### Test Coverage

1. **Unit Tests:**
   - Test each response class `.is_success` property
   - Test error handling in each method
   - Test response wrapping logic

2. **Integration Tests:**
   - Run full `test_kgtypes_endpoint.py` suite
   - Verify all 16 tests pass
   - Test error scenarios

3. **Regression Tests:**
   - Verify server API calls unchanged
   - Verify request formats unchanged
   - Verify response data integrity

## Success Criteria

- [ ] All 5 new response classes created with `.is_success` properties
- [ ] All 7 KGTypesEndpoint methods updated to return new response types
- [ ] All 5 test case modules updated to use new API patterns
- [ ] `test_kgtypes_endpoint.py` runs with 16/16 tests passing (100%)
- [ ] No server-side changes required
- [ ] No changes to server API request/response formats
- [ ] API follows same patterns as Files, KGEntities, Spaces, and Graphs endpoints

## Notes

- This refactoring is **client-side only** - no server changes
- Server API endpoints remain unchanged
- Request/response formats to server remain unchanged
- Only the client response wrapping and convenience methods are updated
- KGTypes operations are simpler than entity operations (no complex object graphs)
- The test file `test_kgtypes_endpoint.py` will be the primary validation tool

## Related Documentation

- Files Client API Cleanup: `planning_fuseki/files_client_api_cleanup_plan.md`
- KGEntities Client API Cleanup: `planning_fuseki/kgentities_client_api_cleanup_plan.md`
- Spaces Client API Cleanup: `planning_fuseki/spaces_client_api_cleanup_plan.md`
- Graphs Client API Cleanup: `planning_fuseki/graphs_client_api_cleanup_plan.md`
- Test File: `vitalgraph_client_test/test_kgtypes_endpoint.py`
- Current Endpoint: `vitalgraph/client/endpoint/kgtypes_endpoint.py`
- Response Models: `vitalgraph/model/kgtypes_model.py`
