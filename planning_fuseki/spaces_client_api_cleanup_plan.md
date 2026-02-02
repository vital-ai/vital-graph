# Spaces Client API Cleanup Plan

## Overview

This document outlines the plan to refactor the Spaces client API to provide a clean, consistent interface while maintaining 100% compatibility with the existing server implementation. No server-side changes will be made - this is purely a client-side API cleanup.

## Current State Analysis

### Current API (spaces_endpoint.py)

**Methods:**
1. `list_spaces(tenant: Optional[str] = None) -> SpacesListResponse`
2. `add_space(space: Space) -> SpaceCreateResponse`
3. `get_space(space_id: str) -> Space`
4. `get_space_info(space_id: str) -> Dict[str, Any]`
5. `update_space(space_id: str, space: Space) -> SpaceUpdateResponse`
6. `delete_space(space_id: str) -> SpaceDeleteResponse`
7. `filter_spaces(name_filter: str, tenant: Optional[str] = None) -> SpacesListResponse`

### Current Response Models (spaces_model.py)

**Models:**
- `Space` - Space data model
- `SpacesListResponse` - List response (extends BasePaginatedResponse)
- `SpaceCreateResponse` - Create response (extends BaseCreateResponse)
- `SpaceUpdateResponse` - Update response (extends BaseUpdateResponse)
- `SpaceDeleteResponse` - Delete response (extends BaseDeleteResponse)
- `SpaceOperationResponse` - General operation response (extends BaseOperationResponse)

### Issues with Current API

1. **Inconsistent Response Handling**
   - `get_space()` returns raw `Space` model instead of wrapped response
   - `get_space_info()` returns raw `Dict[str, Any]` instead of typed response
   - Tests have complex conditional logic to check response success

2. **Inconsistent Naming**
   - `add_space()` vs `create_space()` (should be consistent with other endpoints)
   - `get_space()` vs `get_space_info()` (unclear distinction)

3. **Missing Response Wrappers**
   - No `SpaceResponse` for single space retrieval
   - No `SpaceInfoResponse` for space info/statistics

4. **Complex Test Code**
   - Tests check multiple conditions: `hasattr(response, 'success')`, `hasattr(response, 'created_count')`, etc.
   - Inconsistent success checking patterns across different operations

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
# Spaces Response Classes
# ============================================================================

class SpaceResponse(VitalGraphResponse):
    """Response for single space retrieval operations."""
    space: Optional[Space] = Field(None, description="Retrieved space")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.space is not None and not self.error_code


class SpaceInfoResponse(VitalGraphResponse):
    """Response for space info/statistics operations."""
    space: Optional[Space] = Field(None, description="Space information")
    statistics: Optional[Dict[str, Any]] = Field(None, description="Space statistics")
    quad_dump: Optional[List[str]] = Field(None, description="Quad logging dump if enabled")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.space is not None and not self.error_code


class SpacesListResponse(VitalGraphResponse):
    """Response for spaces listing operations."""
    spaces: List[Space] = Field(default_factory=list, description="List of spaces")
    total: int = Field(0, description="Total number of spaces")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return not self.error_code
    
    @property
    def count(self) -> int:
        """Get count of spaces."""
        return len(self.spaces)


class SpaceCreateResponse(VitalGraphResponse):
    """Response for space creation operations."""
    space: Optional[Space] = Field(None, description="Created space")
    created_count: int = Field(0, description="Number of spaces created (always 1)")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.created_count > 0 and not self.error_code


class SpaceUpdateResponse(VitalGraphResponse):
    """Response for space update operations."""
    space: Optional[Space] = Field(None, description="Updated space")
    updated_count: int = Field(0, description="Number of spaces updated (always 1)")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.updated_count > 0 and not self.error_code


class SpaceDeleteResponse(VitalGraphResponse):
    """Response for space deletion operations."""
    deleted_count: int = Field(0, description="Number of spaces deleted (always 1)")
    space_id: Optional[str] = Field(None, description="ID of deleted space")
    
    @property
    def is_success(self) -> bool:
        """Check if operation was successful."""
        return self.deleted_count > 0 and not self.error_code
```

### Refactored API Methods

Update `spaces_endpoint.py`:

```python
class SpacesEndpoint(BaseEndpoint):
    """Client endpoint for Spaces operations."""
    
    def list_spaces(self, tenant: Optional[str] = None) -> SpacesListResponse:
        """
        List all spaces.
        
        Args:
            tenant: Optional tenant filter
            
        Returns:
            SpacesListResponse with spaces list
        """
        # Implementation wraps server response in SpacesListResponse
        # Server call remains unchanged
        pass
    
    def create_space(self, space: Space) -> SpaceCreateResponse:
        """
        Create a new space.
        
        Args:
            space: Space object with space data
            
        Returns:
            SpaceCreateResponse with created space
        """
        # Renamed from add_space() for consistency
        # Server call remains unchanged (POST /api/spaces)
        pass
    
    def get_space(self, space_id: str) -> SpaceResponse:
        """
        Get a space by ID.
        
        Args:
            space_id: Space ID
            
        Returns:
            SpaceResponse with space data
        """
        # Now returns SpaceResponse instead of raw Space
        # Server call remains unchanged (GET /api/spaces/{space_id})
        pass
    
    def get_space_info(self, space_id: str) -> SpaceInfoResponse:
        """
        Get detailed space information including statistics.
        
        Args:
            space_id: Space ID
            
        Returns:
            SpaceInfoResponse with space info and statistics
        """
        # Now returns SpaceInfoResponse instead of Dict[str, Any]
        # Server call remains unchanged (GET /api/spaces/{space_id}/info)
        pass
    
    def update_space(self, space_id: str, space: Space) -> SpaceUpdateResponse:
        """
        Update a space.
        
        Args:
            space_id: Space ID
            space: Updated space object
            
        Returns:
            SpaceUpdateResponse with update result
        """
        # Server call remains unchanged (PUT /api/spaces/{space_id})
        pass
    
    def delete_space(self, space_id: str) -> SpaceDeleteResponse:
        """
        Delete a space.
        
        Args:
            space_id: Space ID
            
        Returns:
            SpaceDeleteResponse with deletion result
        """
        # Server call remains unchanged (DELETE /api/spaces/{space_id})
        pass
    
    def filter_spaces(self, name_filter: str, tenant: Optional[str] = None) -> SpacesListResponse:
        """
        Filter spaces by name.
        
        Args:
            name_filter: Name filter string
            tenant: Optional tenant filter
            
        Returns:
            SpacesListResponse with filtered spaces
        """
        # Server call remains unchanged (GET /api/spaces/filter/{name_filter})
        pass
```

## Implementation Plan

### Phase 1: Create Response Classes
- [ ] Add new response classes to `client_response.py`
- [ ] Add imports to `response_builder.py`
- [ ] Ensure all responses have `.is_success`, `.is_error`, `.error_message` properties

### Phase 2: Refactor SpacesEndpoint
- [ ] Backup original `spaces_endpoint.py` to `spaces_endpoint_old.py`
- [ ] Update `list_spaces()` to return enhanced `SpacesListResponse`
- [ ] Rename `add_space()` to `create_space()` (keep `add_space()` as deprecated alias)
- [ ] Update `get_space()` to return `SpaceResponse`
- [ ] Update `get_space_info()` to return `SpaceInfoResponse`
- [ ] Update `update_space()` to return enhanced `SpaceUpdateResponse`
- [ ] Update `delete_space()` to return enhanced `SpaceDeleteResponse`
- [ ] Update `filter_spaces()` to return enhanced `SpacesListResponse`

### Phase 3: Update Test Files

#### Test Files to Update

1. **`test_multiple_organizations_crud.py`**
   - Location: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph_client_test/test_multiple_organizations_crud.py`
   - Lines to update: ~117-142 (space creation), ~275+ (space deletion)
   - Changes: Update space creation/deletion to use new response objects

2. **`test_lead_entity_graph.py`**
   - Location: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph_client_test/test_lead_entity_graph.py`
   - Lines to update: ~166-178 (space creation), ~267-270 (space deletion)
   - Changes: Update space creation/deletion to use new response objects

3. **`test_lead_entity_graph_dataset.py`**
   - Location: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph_client_test/test_lead_entity_graph_dataset.py`
   - Lines to update: ~167-180 (space creation), ~259-262 (space deletion)
   - Changes: Update space creation/deletion to use new response objects

4. **`test_files_endpoint.py`**
   - Location: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph_client_test/test_files_endpoint.py`
   - Lines to update: ~84-125 (space creation), ~271-274 (space deletion)
   - Changes: Update space creation/deletion to use new response objects

5. **`test_kgentities_endpoint.py`**
   - Lines to update: ~91-127 (space creation), ~308-312 (space deletion)
   - Changes: Update space creation/deletion to use new response objects

6. **`test_realistic_persistent.py`**
   - Lines to update: ~387-407 (space creation/deletion), ~326-330 (get_space)
   - Changes: Update space operations to use new response objects

7. **`test_clean_spaces.py`**
   - Location: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph_client_test/test_clean_spaces.py`
   - Lines to update: ~33-36 (list_spaces)
   - Changes: Update space listing to use new response objects

8. **`delete_test_space.py`**
   - Location: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph_client_test/delete_test_space.py`
   - Lines to update: ~69-72 (list_spaces), ~87-104 (delete_space), ~114-130 (verify deletion)
   - Changes: Update to use enhanced response objects with `.is_success`

9. **`create_test_space_with_data.py`**
   - Location: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph_client_test/create_test_space_with_data.py`
   - Lines to update: Space creation and listing operations
   - Changes: Update to use `create_space()` and enhanced response objects

#### Detailed Update Patterns

**Pattern 1: Space Creation (add_space → create_space)**

Before:
```python
space_data = Space(
    space=space_id,
    space_name="Test Space",
    space_description="Test space description",
    tenant="test_tenant"
)
create_response = client.spaces.add_space(space_data)
if not (create_response and (
    (hasattr(create_response, 'success') and create_response.success) or
    (hasattr(create_response, 'created_count') and create_response.created_count == 1) or
    (hasattr(create_response, 'message') and "created successfully" in str(create_response.message))
)):
    logger.error(f"❌ Failed to create space")
    return False
logger.info(f"✅ Test space created")
```

After:
```python
space_data = Space(
    space=space_id,
    space_name="Test Space",
    space_description="Test space description",
    tenant="test_tenant"
)
create_response = client.spaces.create_space(space_data)
if not create_response.is_success:
    logger.error(f"❌ Failed to create space: {create_response.error_message}")
    return False
logger.info(f"✅ Test space created: {create_response.space.space}")
```

**Pattern 2: Space Deletion**

Before:
```python
delete_response = client.spaces.delete_space(space_id)
if delete_response and (
    (hasattr(delete_response, 'success') and delete_response.success) or
    (hasattr(delete_response, 'message') and "deleted successfully" in str(delete_response.message))
):
    logger.info(f"✅ Test space deleted successfully")
```

After:
```python
delete_response = client.spaces.delete_space(space_id)
if delete_response.is_success:
    logger.info(f"✅ Test space deleted: {delete_response.space_id}")
else:
    logger.warning(f"⚠️  Could not delete space: {delete_response.error_message}")
```

**Pattern 3: Space Listing**

Before:
```python
spaces_response = client.spaces.list_spaces()
existing_spaces = spaces_response.spaces
existing_space = next((s for s in existing_spaces if s.space == space_id), None)
```

After:
```python
spaces_response = client.spaces.list_spaces()
if not spaces_response.is_success:
    logger.error(f"Failed to list spaces: {spaces_response.error_message}")
    return False
existing_space = next((s for s in spaces_response.spaces if s.space == space_id), None)
logger.info(f"Found {spaces_response.count} spaces")
```

**Pattern 4: Get Space**

Before:
```python
space = client.spaces.get_space(space_id)
if space:
    # Use space directly
    logger.info(f"Space: {space.space_name}")
```

After:
```python
response = client.spaces.get_space(space_id)
if response.is_success:
    logger.info(f"Space: {response.space.space_name}")
else:
    logger.error(f"Failed to get space: {response.error_message}")
```

**Pattern 5: Get Space Info**

Before:
```python
space_info = client.spaces.get_space_info(space_id)
if space_info:
    stats = space_info.get('statistics', {})
    # Access dict keys
```

After:
```python
response = client.spaces.get_space_info(space_id)
if response.is_success:
    logger.info(f"Space: {response.space.space_name}")
    if response.statistics:
        logger.info(f"Statistics: {response.statistics}")
    if response.quad_dump:
        logger.info(f"Quad dump: {len(response.quad_dump)} quads")
else:
    logger.error(f"Failed to get space info: {response.error_message}")
```

**Pattern 6: delete_test_space.py - List and Delete**

Before:
```python
spaces_response: SpacesListResponse = client.list_spaces()
existing_spaces = spaces_response.spaces
print(f"   📊 Found {len(existing_spaces)} total spaces (total: {spaces_response.total_count})")

# Delete space
delete_result: SpaceDeleteResponse = client.delete_space(space_id)
print(f"   ✓ Test space deleted successfully!")
print(f"   📋 Deletion result:")
print(f"     - Message: {delete_result.message}")
print(f"     - Deleted count: {delete_result.deleted_count}")
```

After:
```python
spaces_response = client.spaces.list_spaces()
if not spaces_response.is_success:
    print(f"   ❌ Failed to list spaces: {spaces_response.error_message}")
    return False
print(f"   📊 Found {spaces_response.count} total spaces")

# Delete space
delete_response = client.spaces.delete_space(space_id)
if delete_response.is_success:
    print(f"   ✓ Test space deleted successfully!")
    print(f"   📋 Deletion result:")
    print(f"     - Space ID: {delete_response.space_id}")
    print(f"     - Deleted count: {delete_response.deleted_count}")
else:
    print(f"   ❌ Failed to delete space: {delete_response.error_message}")
    return False
```

**Pattern 7: test_clean_spaces.py - List Spaces**

Before:
```python
spaces_response = client.spaces.list_spaces()

# Get space list (SpacesListResponse has spaces attribute directly)
spaces = spaces_response.spaces
total_count = len(spaces)

print(f"📊 Total Spaces: {total_count}")
```

After:
```python
spaces_response = client.spaces.list_spaces()
if not spaces_response.is_success:
    print(f"❌ Failed to list spaces: {spaces_response.error_message}")
    return

spaces = spaces_response.spaces
total_count = spaces_response.count

print(f"📊 Total Spaces: {total_count}")
```

#### Update Checklist

- [ ] **test_multiple_organizations_crud.py**
  - [ ] Update space creation (lines ~117-142)
  - [ ] Update space deletion (lines ~275+)
  - [ ] Change `add_space()` to `create_space()`
  - [ ] Replace complex conditionals with `.is_success`
  
- [ ] **test_lead_entity_graph.py**
  - [ ] Update space creation (lines ~166-178)
  - [ ] Update space deletion (lines ~267-270)
  - [ ] Change `add_space()` to `create_space()`
  - [ ] Replace complex conditionals with `.is_success`
  
- [ ] **test_lead_entity_graph_dataset.py**
  - [ ] Update space creation (lines ~167-180)
  - [ ] Update space deletion (lines ~259-262)
  - [ ] Change `add_space()` to `create_space()`
  - [ ] Replace complex conditionals with `.is_success`
  
- [ ] **test_files_endpoint.py**
  - [ ] Update space listing (lines ~84-86)
  - [ ] Update space creation (lines ~112-125)
  - [ ] Update space deletion (lines ~271-274)
  - [ ] Change `add_space()` to `create_space()`
  - [ ] Replace complex conditionals with `.is_success`
  
- [ ] **test_kgentities_endpoint.py**
  - [ ] Update space listing (lines ~91-93)
  - [ ] Update space creation (lines ~120-127)
  - [ ] Update space deletion (lines ~308-312)
  - [ ] Change `add_space()` to `create_space()`
  - [ ] Replace complex conditionals with `.is_success`
  
- [ ] **test_realistic_persistent.py**
  - [ ] Update space deletion (lines ~387-390)
  - [ ] Update space creation (lines ~403-407)
  - [ ] Update get_space (lines ~326-330)
  - [ ] Change `add_space()` to `create_space()`
  - [ ] Replace complex conditionals with `.is_success`
  
- [ ] **test_clean_spaces.py**
  - [ ] Update list_spaces (lines ~33-36)
  - [ ] Add error checking with `.is_success`
  
- [ ] **delete_test_space.py**
  - [ ] Update list_spaces calls (lines ~69-72, ~114-130)
  - [ ] Update delete_space call (lines ~87-104)
  - [ ] Replace complex conditionals with `.is_success`
  - [ ] Update response property access (`.deleted_count`, `.message`)
  
- [ ] **create_test_space_with_data.py**
  - [ ] Update space creation operations
  - [ ] Change `add_space()` to `create_space()` if used
  - [ ] Replace complex conditionals with `.is_success`

### Phase 4: Testing
- [ ] Run all test files to ensure compatibility
- [ ] Verify no server-side changes required
- [ ] Confirm all operations work as before

## Test Code Improvements

### Before (Current Pattern)

```python
# Complex conditional checking
create_response = client.spaces.add_space(space_data)
if create_response and (
    (hasattr(create_response, 'success') and create_response.success) or
    (hasattr(create_response, 'created_count') and create_response.created_count == 1) or
    (hasattr(create_response, 'message') and "created successfully" in str(create_response.message))
):
    print("✅ Space created")
else:
    print("❌ Failed to create space")

# Raw dict response
space_info = client.spaces.get_space_info(space_id)
if space_info:
    # Access dict keys directly
    stats = space_info.get('statistics', {})
```

### After (Clean Pattern)

```python
# Simple, consistent checking
response = client.spaces.create_space(space_data)
if response.is_success:
    print(f"✅ Space created: {response.space.space}")
    print(f"   Created count: {response.created_count}")
else:
    print(f"❌ Failed: {response.error_message}")

# Typed response
response = client.spaces.get_space_info(space_id)
if response.is_success:
    print(f"✅ Space: {response.space.space_name}")
    print(f"   Statistics: {response.statistics}")
    if response.quad_dump:
        print(f"   Quad dump: {len(response.quad_dump)} quads")
else:
    print(f"❌ Failed: {response.error_message}")
```

## Server Communication (Unchanged)

All server API calls remain identical:

- `GET /api/spaces` - List spaces
- `POST /api/spaces` - Create space
- `GET /api/spaces/{space_id}` - Get space
- `GET /api/spaces/{space_id}/info` - Get space info
- `PUT /api/spaces/{space_id}` - Update space
- `DELETE /api/spaces/{space_id}` - Delete space
- `GET /api/spaces/filter/{name_filter}` - Filter spaces

The refactoring only changes:
1. How responses are wrapped on the client side
2. Method naming for consistency (`add_space` → `create_space`)
3. Response object structure for easier access

## Benefits

1. **Consistent API**: All operations follow the same pattern
2. **Easier Testing**: Simple `.is_success` checks instead of complex conditionals
3. **Better Type Safety**: Typed responses instead of raw dicts
4. **Clear Documentation**: Response objects document what's available
5. **Maintainable**: Follows same pattern as Files and KGEntities refactoring
6. **No Breaking Changes**: Server communication unchanged, backward compatible

## Success Criteria

- [ ] All test files pass with updated code
- [ ] Response objects have consistent `.is_success`, `.is_error`, `.error_message`
- [ ] No server-side changes required
- [ ] Test code is simpler and more readable
- [ ] API follows same patterns as Files and KGEntities endpoints

## Notes

- Keep `add_space()` as deprecated alias to `create_space()` for backward compatibility
- Ensure all response builders handle server responses correctly
- Document migration path for existing code using old patterns
- Consider adding deprecation warnings for old patterns in future release
