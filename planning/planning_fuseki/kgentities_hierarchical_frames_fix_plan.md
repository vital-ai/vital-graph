# KGEntities Hierarchical Frames Fix Plan

## Executive Summary

**Problem:** Child frame operations (create, update, get, list, delete) within the KGEntities context are failing because the `parent_frame_uri` parameter is not being properly passed through the processing chain to the backend operations.

**Root Cause:** The endpoint validates and uses `parent_frame_uri` for edge creation, but doesn't pass it to the frame processors, preventing proper scoping of hierarchical frame operations.

**Impact:** 
- Test results: 55/60 passing (92%) in lead entity graph tests
- Child frame updates fail with "Failed to create/update frames" or report success but don't persist
- Top-level frame operations work perfectly (100% success in multi_kgentity tests)

## Current Architecture Analysis

### Code Flow for Frame Operations

```
Client Request (with parent_frame_uri)
  ↓
KGEntitiesEndpoint._update_entity_frames() [Lines 1454-1720]
  ↓ Validates parent_frame_uri (Lines 1582-1599) ✅
  ↓ Creates hierarchical edges (Lines 1602-1626) ✅
  ↓ Calls frame_processor.update_frames() WITHOUT parent_frame_uri ❌
  ↓
KGEntityFrameUpdateProcessor.update_frames() [Lines 56-162]
  ↓ No parent_frame_uri parameter in signature ❌
  ↓ Calls KGEntityFrameCreateProcessor.create_entity_frame()
  ↓
KGEntityFrameCreateProcessor.create_entity_frame() [Lines 63-783]
  ↓ No parent_frame_uri parameter ❌
  ↓ Executes atomic update via backend.update_quads()
  ↓
Backend → Database (PostgreSQL quad operations)
```

### Files Involved

1. **Endpoint Layer:**
   - `/vitalgraph/endpoint/kgentities_endpoint.py`
   - Methods: `_create_or_update_frames()`, `_update_entity_frames()`, `_delete_entity_frames()`

2. **Processor Layer:**
   - `/vitalgraph/kg_impl/kgentity_frame_create_impl.py` - Frame creation
   - `/vitalgraph/kg_impl/kgentity_frame_update_impl.py` - Frame updates
   - `/vitalgraph/kg_impl/kgentity_frame_delete_impl.py` - Frame deletion
   - `/vitalgraph/kg_impl/kgentity_frame_discovery_impl.py` - Frame listing/discovery
   - `/vitalgraph/kg_impl/kgentity_hierarchical_frame_impl.py` - Hierarchical operations

3. **Backend Layer:**
   - `/vitalgraph/kg_impl/kg_backend_utils.py` - Backend adapter

## Comprehensive Fix Plan

### Phase 1: Update Processor Signatures (CRITICAL)

#### 1.1 KGEntityFrameUpdateProcessor
**File:** `/vitalgraph/kg_impl/kgentity_frame_update_impl.py`

**Change:** Add `parent_frame_uri` parameter to method signature

```python
# BEFORE (Line 56-57):
async def update_frames(self, space_id: str, graph_id: str, entity_uri: str, 
                       frame_objects: List[GraphObject]) -> UpdateFrameResult:

# AFTER:
async def update_frames(self, space_id: str, graph_id: str, entity_uri: str, 
                       frame_objects: List[GraphObject],
                       parent_frame_uri: Optional[str] = None) -> UpdateFrameResult:
```

**Impact:** Pass `parent_frame_uri` to `KGEntityFrameCreateProcessor.create_entity_frame()` at line 115

#### 1.2 KGEntityFrameCreateProcessor
**File:** `/vitalgraph/kg_impl/kgentity_frame_create_impl.py`

**Change:** Add `parent_frame_uri` parameter to method signature

```python
# BEFORE (Line 63-70):
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

**Impact:** Use `parent_frame_uri` for:
- Hierarchical frame validation
- Proper scoping of delete operations in UPDATE mode
- Connection edge creation/validation

### Phase 2: Update Endpoint Calls

#### 2.1 Update Frame Endpoint
**File:** `/vitalgraph/endpoint/kgentities_endpoint.py`

**Location:** Line 1680-1685 in `_update_entity_frames()`

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
    parent_frame_uri=parent_frame_uri  # Pass through from endpoint parameter
)
```

#### 2.2 Create Frame Endpoint
**File:** `/vitalgraph/endpoint/kgentities_endpoint.py`

**Location:** Line 1028-1400 in `_create_or_update_frames()`

**Review:** Ensure `parent_frame_uri` is passed to `KGEntityFrameCreateProcessor.create_entity_frame()`

### Phase 3: Hierarchical Frame Operations

#### 3.1 Frame Discovery with Parent Scoping
**File:** `/vitalgraph/kg_impl/kgentity_frame_discovery_impl.py`

**Enhancement:** Add `parent_frame_uri` filtering to discovery queries

```python
async def discover_entity_frames(
    self, 
    space_id: str, 
    graph_id: str, 
    entity_uri: str,
    parent_frame_uri: Optional[str] = None  # NEW parameter
) -> List[str]:
```

**Logic:**
- If `parent_frame_uri` is None: Return top-level frames (connected via Edge_hasEntityKGFrame)
- If `parent_frame_uri` is provided: Return child frames (connected via Edge_hasKGFrame from parent)

#### 3.2 Frame Deletion with Parent Validation
**File:** `/vitalgraph/kg_impl/kgentity_frame_delete_impl.py`

**Current Status:** Already has parent validation logic (lines 164-203)

**Enhancement:** Ensure `parent_frame_uri` is used for:
- Validating frame belongs to specified parent
- Preventing deletion of frames with wrong parent
- Proper error messages for validation failures

### Phase 4: GET Operations (Frame Retrieval)

#### 4.1 Endpoint GET Handler
**File:** `/vitalgraph/endpoint/kgentities_endpoint.py`

**Current:** Line 737 in `get_entity_frames()` route already accepts `parent_frame_uri`

**Review:** Ensure the parameter is properly used for:
- Scoping frame retrieval to specific parent
- Filtering child frames
- Proper error handling when parent doesn't exist

#### 4.2 Frame Retrieval Processor
**File:** `/vitalgraph/kg_impl/kgentity_get_impl.py` or frame discovery

**Enhancement:** Use `parent_frame_uri` to:
- Build SPARQL queries that filter by parent-child relationships
- Return only frames that are children of the specified parent
- Include parent validation in the query

### Phase 5: LIST Operations (Frame Enumeration)

#### 5.1 List Frames with Parent Filter
**File:** `/vitalgraph/endpoint/kgentities_endpoint.py`

**Enhancement:** Support listing frames with optional parent filter:
- `parent_frame_uri=None`: List all top-level frames
- `parent_frame_uri="<uri>"`: List child frames of specified parent
- `parent_frame_uri="*"`: List all frames (both top-level and children)

#### 5.2 Discovery Processor Enhancement
**File:** `/vitalgraph/kg_impl/kgentity_frame_discovery_impl.py`

**SPARQL Query Pattern:**

```sparql
# Top-level frames (parent_frame_uri is None):
SELECT DISTINCT ?frame_uri WHERE {
    GRAPH <graph_id> {
        ?edge a <Edge_hasEntityKGFrame> .
        ?edge <hasEdgeSource> <entity_uri> .
        ?edge <hasEdgeDestination> ?frame_uri .
    }
}

# Child frames (parent_frame_uri provided):
SELECT DISTINCT ?frame_uri WHERE {
    GRAPH <graph_id> {
        ?edge a <Edge_hasKGFrame> .
        ?edge <hasEdgeSource> <parent_frame_uri> .
        ?edge <hasEdgeDestination> ?frame_uri .
    }
}
```

### Phase 6: CREATE Operations Enhancement

#### 6.1 Create with Parent Validation
**File:** `/vitalgraph/kg_impl/kgentity_frame_create_impl.py`

**Enhancement:** When `parent_frame_uri` is provided:

1. **Validate parent exists** (Line ~100):
   ```python
   if parent_frame_uri:
       parent_exists = await self.validate_parent_frame_exists(
           backend_adapter, space_id, graph_id, entity_uri, parent_frame_uri
       )
       if not parent_exists:
           return CreateFrameResult(
               success=False,
               created_uris=[],
               message=f"Parent frame {parent_frame_uri} does not exist or doesn't belong to entity {entity_uri}",
               frame_count=0
           )
   ```

2. **Create proper connection edges** (Line ~1019-1040):
   - If `parent_frame_uri` is None: Create `Edge_hasEntityKGFrame` (entity → frame)
   - If `parent_frame_uri` is provided: Create `Edge_hasKGFrame` (parent → child)

3. **Set proper grouping URIs**:
   - `kGGraphURI`: Always set to `entity_uri` (entity-level grouping)
   - `frameGraphURI`: Set to frame's own URI (frame-level grouping)

### Phase 7: Integration with Hierarchical Processor

#### 7.1 Use KGEntityHierarchicalFrameProcessor
**File:** `/vitalgraph/kg_impl/kgentity_frame_create_impl.py` and `kgentity_frame_update_impl.py`

**Enhancement:** Leverage existing hierarchical processor methods:

```python
from vitalgraph.kg_impl.kgentity_hierarchical_frame_impl import KGEntityHierarchicalFrameProcessor

# In create/update methods:
if parent_frame_uri:
    hierarchical_processor = KGEntityHierarchicalFrameProcessor(backend_adapter, self.logger)
    
    # Validate parent frame
    parent_valid = await hierarchical_processor.validate_parent_frame(
        space_id, graph_id, entity_uri, parent_frame_uri
    )
    
    if not parent_valid:
        return error_result
    
    # Create connection edges
    connection_edges = hierarchical_processor.create_connection_edges(
        entity_uri, frame_objects, parent_frame_uri
    )
    
    # Apply hierarchical grouping URIs
    processed_objects = hierarchical_processor.apply_hierarchical_grouping_uris(
        entity_uri, frame_objects
    )
```

### Phase 8: Testing Strategy

#### 8.1 Unit Tests
Create/update tests for each operation with hierarchical frames:

1. **Create Tests:**
   - Create top-level frame (parent_frame_uri=None)
   - Create child frame (parent_frame_uri=valid_parent)
   - Create child frame with invalid parent (should fail)
   - Create child frame with parent from different entity (should fail)

2. **Update Tests:**
   - Update top-level frame
   - Update child frame with correct parent_frame_uri
   - Update child frame without parent_frame_uri (should work - inferred from edges)
   - Update child frame with wrong parent_frame_uri (should fail)

3. **Get Tests:**
   - Get top-level frame
   - Get child frame with parent_frame_uri
   - Get child frame without parent_frame_uri (should work)
   - Get child frame with wrong parent_frame_uri (should fail/return empty)

4. **List Tests:**
   - List all top-level frames (parent_frame_uri=None)
   - List child frames of specific parent
   - List with non-existent parent (should return empty)

5. **Delete Tests:**
   - Delete top-level frame
   - Delete child frame with correct parent_frame_uri
   - Delete child frame with wrong parent_frame_uri (should fail)
   - Delete parent frame (should handle cascade or prevent)

#### 8.2 Integration Tests
Use existing test files:

1. **test_lead_entity_graph.py** - Should achieve 60/60 passing after fix
2. **test_multiple_organizations_crud.py** - Should maintain 43/43 passing

#### 8.3 Validation Criteria
- All 60 tests in lead entity graph test pass
- No regression in multi_kgentity test (maintain 100%)
- Child frame updates persist correctly
- Parent validation works for all operations
- Proper error messages for invalid parent references

## Implementation Order

### Priority 1: Critical Path (Frame Updates)
1. Update `KGEntityFrameUpdateProcessor.update_frames()` signature
2. Update `KGEntityFrameCreateProcessor.create_entity_frame()` signature
3. Update endpoint call in `_update_entity_frames()`
4. Test with lead entity graph test

### Priority 2: Complete Frame Operations
5. Enhance frame discovery with parent filtering
6. Update GET operations to use parent scoping
7. Update CREATE operations with parent validation
8. Update DELETE operations (already has validation, ensure it works)

### Priority 3: LIST Operations
9. Implement parent filtering in list operations
10. Add SPARQL queries for hierarchical frame listing

### Priority 4: Testing & Validation
11. Run all existing tests
12. Add new hierarchical frame tests
13. Document hierarchical frame patterns

## Expected Outcomes

### After Priority 1 (Critical Path):
- **test_lead_entity_graph.py:** 60/60 passing (100%) ✅
- **test_multiple_organizations_crud.py:** 43/43 passing (100%) ✅
- Child frame updates work correctly
- Server properly handles parent_frame_uri parameter

### After Priority 2 (Complete Operations):
- All CRUD operations support hierarchical frames
- Proper validation and error handling
- Consistent behavior across all operations

### After Priority 3 (LIST Operations):
- Can list top-level frames separately from child frames
- Can enumerate children of specific parent frame
- Proper filtering and scoping

### After Priority 4 (Testing):
- Comprehensive test coverage
- Documentation for hierarchical frame patterns
- Production-ready implementation

## Risk Assessment

### Low Risk:
- Adding optional `parent_frame_uri` parameter (backward compatible)
- Using existing hierarchical processor methods
- Endpoint already validates parent_frame_uri

### Medium Risk:
- Changes to frame discovery/listing logic
- SPARQL query modifications for parent filtering

### Mitigation:
- Make `parent_frame_uri` optional (default=None)
- Maintain backward compatibility for top-level frames
- Extensive testing before deployment
- Incremental rollout (Priority 1 first, then 2, 3, 4)

## Success Metrics

1. **Test Pass Rate:** 100% (60/60 in lead test, 43/43 in multi test)
2. **Frame Update Success:** Child frame updates persist correctly
3. **Parent Validation:** Proper error handling for invalid parents
4. **Performance:** No degradation in frame operation performance
5. **Code Quality:** Clean integration with existing architecture

## Timeline Estimate

- **Priority 1 (Critical):** 2-3 hours
- **Priority 2 (Complete):** 3-4 hours
- **Priority 3 (LIST):** 2-3 hours
- **Priority 4 (Testing):** 2-3 hours
- **Total:** 9-13 hours

## Notes

- The client-side code is already correct and passes `parent_frame_uri` properly
- The endpoint validates `parent_frame_uri` but doesn't pass it through
- The hierarchical processor exists and has the right methods, just not integrated
- This is a server-side implementation gap, not a design flaw
- The fix is straightforward: thread `parent_frame_uri` through the processing chain
