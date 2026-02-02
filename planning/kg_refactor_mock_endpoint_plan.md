# Mock Endpoint Refactoring Plan

## Overview

This document tracks the analysis and refactoring of common functionality between MockKGEntitiesEndpoint and MockKGFramesEndpoint implementations. The goal is to identify duplicate code and extract reusable utilities to improve maintainability and reduce code duplication.

**Status**: Analysis Phase - In Progress  
**Started**: November 25, 2024  
**Target**: Extract common functionality to `/vitalgraph/utils/` modules

## Analysis Results

### File Size Analysis
- **MockKGEntitiesEndpoint**: 2,624 lines
- **MockKGFramesEndpoint**: 2,572 lines  
- **MockBaseEndpoint**: Existing shared functionality
- **Total Combined**: 5,196 lines

### Initial Analysis Progress
- [x] MockKGEntitiesEndpoint method inventory (27 methods)
- [x] MockKGFramesEndpoint method inventory (23 methods)
- [x] Function commonality matrix (complete)
- [x] Detailed duplication assessment (complete)
- [x] Priority rankings (complete)

## Function Inventory

### MockKGEntitiesEndpoint Methods (27 methods)
**Public API Methods (13):**
- `list_kgentities()` - List with pagination and search
- `get_kgentity()` - Get single entity with optional graph
- `create_kgentities()` - Create entities from JSON-LD
- `update_kgentities()` - Update with operation modes
- `delete_kgentity()` - Delete single entity
- `delete_kgentities_batch()` - Batch delete
- `get_kgentity_frames()` - Get entity frames
- `query_entities()` - Criteria-based search
- `list_kgentities_with_graphs()` - Enhanced listing
- `create_entity_frames()` - Sub-endpoint: create frames
- `update_entity_frames()` - Sub-endpoint: update frames  
- `delete_entity_frames()` - Sub-endpoint: delete frames
- `get_entity_frames()` - Sub-endpoint: get frames

**Private Helper Methods (14):**
- `_validate_parent_object()` - Parent validation
- `_validate_entity_graph_structure()` - Structure validation
- `_handle_entity_create_mode()` - CREATE mode logic
- `_handle_entity_update_mode()` - UPDATE mode logic
- `_handle_entity_upsert_mode()` - UPSERT mode logic
- `_object_exists_in_store()` - Existence check
- `_entity_exists_in_store()` - Entity-specific existence
- `_get_current_entity_objects()` - Get current objects
- `_validate_parent_connection()` - Parent-child validation
- `_backup_entity_graph()` - Backup for rollback
- `_restore_entity_graph_from_backup()` - Restore backup
- `_set_entity_grouping_uris()` - Set grouping URIs
- `_create_entity_frame_edges()` - Create edge relationships
- `_get_entity_frame_edge()` - Get specific edge

### MockKGFramesEndpoint Methods (23 methods)
**Public API Methods (11):**
- `list_kgframes()` - List with pagination and search
- `get_kgframe()` - Get single frame with optional graph
- `create_kgframes()` - Create frames from JSON-LD
- `update_kgframes()` - Update with operation modes
- `delete_kgframe()` - Delete single frame
- `delete_kgframes_batch()` - Batch delete
- `get_kgframe_with_slots()` - Get frame with slots
- `create_kgframes_with_slots()` - Create frames+slots
- `create_frame_slots()` - Sub-endpoint: create slots
- `update_frame_slots()` - Sub-endpoint: update slots
- `delete_frame_slots()` - Sub-endpoint: delete slots
- `get_frame_slots()` - Sub-endpoint: get slots

**Private Helper Methods (12):**
- `_validate_parent_object()` - Parent validation
- `_validate_frame_structure()` - Structure validation
- `_handle_create_mode()` - CREATE mode logic
- `_handle_update_mode()` - UPDATE mode logic
- `_handle_upsert_mode()` - UPSERT mode logic
- `_object_exists_in_store()` - Existence check
- `_get_current_frame_objects()` - Get current objects
- `_validate_parent_connection()` - Parent-child validation
- `_is_frame_parent()` - Check if parent is frame
- `_delete_frame_graph_excluding_parent_edges()` - Selective delete
- `_set_frame_grouping_uris()` - Set grouping URIs
- `_create_frame_slot_edges()` - Create edge relationships

## Commonality Matrix

### Identical/Nearly Identical Functions (High Duplication)
| Function Pattern | MockKGEntitiesEndpoint | MockKGFramesEndpoint | Duplication Level | Target Utility |
|------------------|------------------------|----------------------|-------------------|----------------|
| `_validate_parent_object()` | ✅ | ✅ | 95% identical | `endpoint_validation.py` |
| `_object_exists_in_store()` | ✅ | ✅ | 100% identical | `sparql_helpers.py` |
| `_validate_parent_connection()` | ✅ | ✅ | 90% identical | `endpoint_validation.py` |
| Operation mode handlers | `_handle_*_mode()` | `_handle_*_mode()` | 85% identical | `endpoint_validation.py` |
| Grouping URI setters | `_set_entity_grouping_uris()` | `_set_frame_grouping_uris()` | 80% similar | `graph_operations.py` |

### Similar Patterns (Medium Duplication)
| Pattern Type | Description | Duplication Level | Target Utility |
|--------------|-------------|-------------------|----------------|
| SPARQL Query Building | List/search queries with pagination | 75% similar | `sparql_helpers.py` |
| JSON-LD Conversion | VitalSigns object creation/conversion | 80% similar | `vitalsigns_helpers.py` |
| Error Handling | Exception logging and response formatting | 70% similar | `endpoint_validation.py` |
| Graph Structure Validation | Entity vs Frame structure validation | 60% similar | `graph_operations.py` |
| Edge Relationship Management | Create/validate edge objects | 75% similar | `graph_operations.py` |

### Common Inherited Functionality
| Function Source | Both Endpoints Use | Notes |
|-----------------|-------------------|-------|
| MockBaseEndpoint | `_log_method_call()` | Already shared |
| MockBaseEndpoint | `_execute_sparql_query()` | Already shared |
| MockBaseEndpoint | `_create_vitalsigns_objects_from_jsonld()` | Already shared |
| MockBaseEndpoint | `_convert_triples_to_vitalsigns_objects()` | Already shared |

## Refactoring Queue

### High Priority Candidates (100% Duplication - Immediate Refactoring)
1. **`_object_exists_in_store()`** 
   - **Duplication**: 100% identical across both endpoints
   - **Target**: `vitalgraph/utils/sparql_helpers.py`
   - **Impact**: High - used in multiple operation modes
   - **Complexity**: Low - simple SPARQL query wrapper

2. **`_validate_parent_object()`**
   - **Duplication**: 95% identical (minor entity vs frame differences)
   - **Target**: `vitalgraph/utils/endpoint_validation.py`
   - **Impact**: High - used in all update operations
   - **Complexity**: Low - straightforward validation logic

3. **`_validate_parent_connection()`**
   - **Duplication**: 90% identical (edge type differences)
   - **Target**: `vitalgraph/utils/endpoint_validation.py`
   - **Impact**: Medium - used in parent-child operations
   - **Complexity**: Medium - edge relationship validation

### Medium Priority Candidates (80-85% Duplication)
4. **Operation Mode Handlers (`_handle_*_mode()`)**
   - **Duplication**: 85% identical patterns
   - **Target**: `vitalgraph/utils/endpoint_validation.py`
   - **Impact**: High - core business logic
   - **Complexity**: High - complex validation and rollback logic

5. **Grouping URI Management**
   - **Functions**: `_set_entity_grouping_uris()` vs `_set_frame_grouping_uris()`
   - **Duplication**: 80% similar patterns
   - **Target**: `vitalgraph/utils/graph_operations.py`
   - **Impact**: Medium - used in create/update operations
   - **Complexity**: Medium - grouping URI assignment logic

6. **Edge Relationship Creation**
   - **Functions**: `_create_entity_frame_edges()` vs `_create_frame_slot_edges()`
   - **Duplication**: 75% similar patterns
   - **Target**: `vitalgraph/utils/graph_operations.py`
   - **Impact**: Medium - sub-endpoint functionality
   - **Complexity**: Medium - edge object creation and validation

### Low Priority Candidates (60-75% Duplication)
7. **SPARQL Query Building Patterns**
   - **Pattern**: List/search queries with pagination
   - **Duplication**: 75% similar structure
   - **Target**: `vitalgraph/utils/sparql_helpers.py`
   - **Impact**: Medium - used in list operations
   - **Complexity**: Medium - query template abstraction needed

8. **Graph Structure Validation**
   - **Functions**: `_validate_entity_graph_structure()` vs `_validate_frame_structure()`
   - **Duplication**: 60% similar validation patterns
   - **Target**: `vitalgraph/utils/graph_operations.py`
   - **Impact**: Medium - used in create/update validation
   - **Complexity**: High - complex graph validation logic

9. **Error Handling Patterns**
   - **Pattern**: Exception logging and response formatting
   - **Duplication**: 70% similar patterns
   - **Target**: `vitalgraph/utils/endpoint_validation.py`
   - **Impact**: Low - error handling consistency
   - **Complexity**: Low - standardized error response patterns

## Active Proposals

### Proposal #2: Extract `_validate_parent_object()` to Endpoint Validation

**Status**: Ready for Approval  
**Priority**: High (95% duplication)  
**Target**: `vitalgraph/utils/endpoint_validation.py`

#### Current Implementation Analysis
Both endpoints have identical implementations:

```python
def _object_exists_in_store(self, space, uri: str, graph_id: str) -> bool:
    """Check if any object with the given URI exists in the store."""
    try:
        query = f"""
        SELECT ?s WHERE {{
            GRAPH <{graph_id}> {{
                <{uri}> ?p ?o .
            }}
        }} LIMIT 1
        """
        results = space.query_sparql(query)
        return len(results.get("bindings", [])) > 0
    except Exception:
        return False
```

#### Proposed Refactoring
**New Utility Function**: `vitalgraph/utils/sparql_helpers.py`

```python
def check_object_exists_in_graph(space, uri: str, graph_id: str) -> bool:
    """
    Check if any object with the given URI exists as a subject in the specified graph.
    
    Args:
        space: Mock space instance with pyoxigraph
        uri: URI to check for existence
        graph_id: Graph ID to search in
        
    Returns:
        bool: True if object exists, False otherwise
    """
    try:
        query = f"""
        SELECT ?s WHERE {{
            GRAPH <{graph_id}> {{
                <{uri}> ?p ?o .
            }}
        }} LIMIT 1
        """
        results = space.query_sparql(query)
        return len(results.get("bindings", [])) > 0
    except Exception:
        return False
```

#### Required Changes
1. **Create/Update** `vitalgraph/utils/sparql_helpers.py`
2. **Update MockKGEntitiesEndpoint**: Replace `_object_exists_in_store()` with import and call to utility
3. **Update MockKGFramesEndpoint**: Replace `_object_exists_in_store()` with import and call to utility
4. **Add Tests**: Unit tests for the utility function
5. **Verify Integration**: Run existing endpoint tests to ensure no regression

#### Benefits
- **Eliminates 100% duplication** between endpoints
- **Creates reusable utility** for future endpoints
- **Improves maintainability** with single source of truth
- **Low risk** - simple, well-isolated function

#### Dependencies
- None - this function is standalone

**Ready for approval to proceed with implementation.**

## Approved for Refactoring

### ✅ Proposal #1: Extract `_object_exists_in_store()` to SPARQL Helpers
- **Status**: Approved and In Progress
- **Target**: `vitalgraph/utils/sparql_helpers.py` ✅ Created
- **Function**: `check_object_exists_in_graph()` ✅ Implemented

## In Progress

*No refactoring currently in progress*

## Completed Refactoring

### ✅ Refactoring #1: `_object_exists_in_store()` Function - COMPLETED
- **Status**: ✅ Successfully completed
- **Target**: `vitalgraph/utils/sparql_helpers.py`
- **Function**: `check_object_exists_in_graph()`
- **Completed Steps**:
  - ✅ Created utility function in `sparql_helpers.py`
  - ✅ Updated MockKGEntitiesEndpoint to use utility (line 1353)
  - ✅ Updated MockKGFramesEndpoint to use utility (line 596)
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Eliminated 100% code duplication between endpoints
- **Lines Reduced**: ~24 lines of duplicated code removed

### ✅ Refactoring #2: `_validate_parent_object()` Function - COMPLETED
- **Status**: ✅ Successfully completed
- **Target**: `vitalgraph/utils/endpoint_validation.py`
- **Function**: `validate_parent_object()`
- **Completed Steps**:
  - ✅ Utility function already existed in `endpoint_validation.py`
  - ✅ Updated MockKGEntitiesEndpoint to use utility (line 1163)
  - ✅ Updated MockKGFramesEndpoint to use utility (line 402)
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Eliminated 95% code duplication between endpoints
- **Lines Reduced**: ~58 lines of duplicated code removed

### ✅ Refactoring #3: `_validate_parent_connection()` Function - COMPLETED
- **Status**: ✅ Successfully completed
- **Target**: `vitalgraph/utils/endpoint_validation.py`
- **Function**: `validate_parent_connection()`
- **Completed Steps**:
  - ✅ Utility function already existed in `endpoint_validation.py`
  - ✅ Updated MockKGEntitiesEndpoint to use utility (line 1383-1385)
  - ✅ Updated MockKGFramesEndpoint to use utility (line 611-613)
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Eliminated 90% code duplication between endpoints
- **Lines Reduced**: ~54 lines of duplicated code removed

### ✅ Refactoring #4: Grouping URI Management Functions - COMPLETED
- **Status**: ✅ Successfully completed
- **Target**: `vitalgraph/utils/graph_operations.py`
- **Functions**: `set_entity_grouping_uris()`, `set_frame_grouping_uris()`
- **Completed Steps**:
  - ✅ Utility functions already existed in `graph_operations.py`
  - ✅ Updated MockKGEntitiesEndpoint `_set_entity_grouping_uris()` (line 1680-1681)
  - ✅ Updated MockKGFramesEndpoint `_set_frame_grouping_uris()` (line 1853-1854)
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Eliminated 80% code duplication between endpoints
- **Lines Reduced**: ~20 lines of duplicated code removed

### ✅ Refactoring #5: `_is_frame_parent()` Function - COMPLETED
- **Status**: ✅ Successfully completed
- **Target**: `vitalgraph/utils/endpoint_validation.py`
- **Function**: `is_frame_parent()`
- **Completed Steps**:
  - ✅ Utility function already existed in `endpoint_validation.py`
  - ✅ Updated MockKGFramesEndpoint to use utility (line 617-618)
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Eliminated single-endpoint duplication (frame-specific function)
- **Lines Reduced**: ~12 lines of duplicated code removed

### ✅ Refactoring #6: VitalSigns Object Creation Functions - COMPLETED
- **Status**: ✅ Successfully completed
- **Target**: `vitalgraph/utils/vitalsigns_helpers.py`
- **Function**: `create_vitalsigns_objects_from_jsonld()`
- **Completed Steps**:
  - ✅ Utility function already existed in `vitalsigns_helpers.py`
  - ✅ Updated MockKGEntitiesEndpoint `_create_vitalsigns_objects_from_jsonld()` (line 1781-1782)
  - ✅ Updated MockKGFramesEndpoint `_create_vitalsigns_objects_from_jsonld()` (line 1854-1855, preserved validation)
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Eliminated 80% code duplication between endpoints (core VitalSigns logic)
- **Lines Reduced**: ~35 lines of duplicated code removed

### ✅ Refactoring #7: Grouping URI Stripping Functions - COMPLETED
- **Status**: ✅ Successfully completed
- **Target**: `vitalgraph/utils/vitalsigns_helpers.py`
- **Function**: `strip_grouping_uris_from_document()`
- **Completed Steps**:
  - ✅ Created utility function in `vitalsigns_helpers.py`
  - ✅ Updated MockKGEntitiesEndpoint `_strip_grouping_uris()` (line 1674-1675)
  - ✅ Updated MockKGFramesEndpoint `_strip_grouping_uris()` (line 1837-1838)
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Eliminated 100% code duplication between endpoints (identical placeholder functions)
- **Lines Reduced**: ~8 lines of duplicated code removed

### ✅ Refactoring #8: UUID Generation Function - COMPLETED
- **Status**: ✅ Successfully completed
- **Target**: `vitalgraph/utils/vitalsigns_helpers.py`
- **Function**: `generate_uuid()`
- **Completed Steps**:
  - ✅ Created utility function in `vitalsigns_helpers.py`
  - ✅ Updated MockKGEntitiesEndpoint `_generate_uuid()` (line 1439-1440)
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Centralized UUID generation utility (single-endpoint function)
- **Lines Reduced**: ~4 lines of duplicated code removed

## Phase 3: Endpoint Function Organization - NEW PHASE

### **Objective**: Organize Mock Endpoint Functions into Specialized Implementation Files

The next phase involves migrating functions from the large mock endpoint files into specialized implementation files organized by operation type (create, delete, get, query, update). This will significantly reduce the line count of the main endpoint files and improve code organization.

### **Target Implementation Files Structure**
```
vitalgraph/kg/
├── kgentity_create_endpoint_impl.py    # Entity creation operations
├── kgentity_delete_endpoint_impl.py    # Entity deletion operations  
├── kgentity_get_endpoint_impl.py       # Entity retrieval operations
├── kgentity_query_endpoint_impl.py     # Entity query operations
├── kgentity_update_endpoint_impl.py    # Entity update operations
├── kgentity_upsert_endpoint_impl.py    # Entity upsert operations ✅ (added)
├── kgframe_create_endpoint_impl.py     # Frame creation operations
├── kgframe_delete_endpoint_impl.py     # Frame deletion operations
├── kgframe_get_endpoint_impl.py        # Frame retrieval operations
├── kgframe_query_endpoint_impl.py      # Frame query operations
├── kgframe_update_endpoint_impl.py     # Frame update operations
└── kgframe_upsert_endpoint_impl.py     # Frame upsert operations ✅ (added)
```

### **Migration Strategy**
1. **Function-by-Function Migration** - Move one function at a time to ensure no corruption
2. **Import and Delegate Pattern** - Mock endpoints will import and delegate to implementation functions
3. **Preserve All Functionality** - Maintain exact same behavior and test coverage
4. **Incremental Validation** - Test after each function migration

### **Function Analysis for Migration**

#### **KGEntity Functions to Migrate**

**Create Operations → `kgentity_create_endpoint_impl.py`**
- `create_kgentities()` - Main entity creation endpoint
- `create_entity_frames()` - Entity-frame relationship creation
- `_handle_entity_create_mode()` - Create mode handler

**Delete Operations → `kgentity_delete_endpoint_impl.py`**
- `delete_kgentity()` - Single entity deletion
- `delete_kgentities_batch()` - Batch entity deletion
- `delete_entity_frames()` - Entity-frame relationship deletion

**Get Operations → `kgentity_get_endpoint_impl.py`**
- `get_kgentity()` - Single entity retrieval
- `get_kgentity_frames()` - Entity frames retrieval
- `get_entity_frames()` - Entity-frame relationships
- `_get_current_entity_objects()` - Current entity objects helper

**Query Operations → `kgentity_query_endpoint_impl.py`**
- `list_kgentities()` - Entity listing with pagination
- `query_entities()` - Criteria-based entity search
- `list_kgentities_with_graphs()` - Entity listing with graphs

**Update Operations → `kgentity_update_endpoint_impl.py`**
- `update_kgentities()` - Main entity update endpoint
- `update_entity_frames()` - Entity-frame relationship updates
- `_handle_entity_update_mode()` - Update mode handler
- `_handle_entity_upsert_mode()` - Upsert mode handler

#### **KGFrame Functions to Migrate**

**Create Operations → `kgframe_create_endpoint_impl.py`**
- `create_kgframes()` - Main frame creation endpoint
- `create_kgframes_with_slots()` - Frame creation with slots
- `create_frame_slots()` - Frame-slot relationship creation
- `_handle_create_mode()` - Create mode handler

**Delete Operations → `kgframe_delete_endpoint_impl.py`**
- `delete_kgframe()` - Single frame deletion
- `delete_kgframes_batch()` - Batch frame deletion
- `delete_frame_slots()` - Frame-slot relationship deletion
- `_delete_frame_graph_excluding_parent_edges()` - Specialized deletion helper

**Get Operations → `kgframe_get_endpoint_impl.py`**
- `get_kgframe()` - Single frame retrieval
- `get_kgframe_with_slots()` - Frame retrieval with slots
- `get_frame_slots()` - Frame-slot relationships
- `_get_current_frame_objects()` - Current frame objects helper

**Query Operations → `kgframe_query_endpoint_impl.py`**
- `list_kgframes()` - Frame listing with pagination
- `query_frames()` - Criteria-based frame search (if exists)

**Update Operations → `kgframe_update_endpoint_impl.py`**
- `update_kgframes()` - Main frame update endpoint
- `update_frame_slots()` - Frame-slot relationship updates
- `_handle_update_mode()` - Update mode handler
- `_handle_upsert_mode()` - Upsert mode handler

### **Expected Impact**
- **Reduce Mock Endpoint File Sizes**: From ~2500+ lines each to ~500-800 lines each
- **Improve Code Organization**: Clear separation by operation type
- **Enhance Maintainability**: Easier to locate and modify specific operations
- **Facilitate Future Development**: Clear patterns for adding new operations

### **Implementation Approach**
1. Start with **Create Operations** (most self-contained)
2. Move to **Delete Operations** (clear boundaries)
3. Continue with **Get Operations** (retrieval logic)
4. Handle **Query Operations** (search and listing)
5. Finish with **Update Operations** (most complex dependencies)

## Phase 3 Migration Progress

### ✅ Migration #1: `create_kgentities()` Function - COMPLETED
- **Status**: ✅ Successfully completed
- **Source**: `MockKGEntitiesEndpoint.create_kgentities()` (lines 224-303, ~80 lines)
- **Target**: `vitalgraph/kg/kgentity_create_endpoint_impl.py`
- **Function**: `create_kgentities_impl()`
- **Completed Steps**:
  - ✅ Created implementation file with extracted function
  - ✅ Updated MockKGEntitiesEndpoint to delegate to implementation
  - ✅ Fixed import paths for EntityCreateResponse
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced main endpoint file by ~80 lines, improved code organization
- **Delegation Pattern**: `from vitalgraph.kg.kgentity_create_endpoint_impl import create_kgentities_impl`

### ✅ Migration #2: `create_entity_frames()` Function - COMPLETED
- **Status**: ✅ Successfully completed
- **Source**: `MockKGEntitiesEndpoint.create_entity_frames()` (lines 611-722, ~112 lines)
- **Target**: `vitalgraph/kg/kgentity_create_endpoint_impl.py`
- **Function**: `create_entity_frames_impl()`
- **Completed Steps**:
  - ✅ Added function to existing implementation file
  - ✅ Updated MockKGEntitiesEndpoint to delegate to implementation
  - ✅ Added imports for FrameCreateResponse, KGFrame, KGSlot
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced main endpoint file by ~112 lines, consolidated create operations
- **Delegation Pattern**: `from vitalgraph.kg.kgentity_create_endpoint_impl import create_entity_frames_impl`

### ✅ Migration #3: `create_kgframes()` Function - COMPLETED
- **Status**: ✅ Successfully completed
- **Source**: `MockKGFramesEndpoint.create_kgframes()` (lines 225-310, ~86 lines)
- **Target**: `vitalgraph/kg/kgframe_create_endpoint_impl.py`
- **Function**: `create_kgframes_impl()`
- **Completed Steps**:
  - ✅ Created new implementation file for frame create operations
  - ✅ Updated MockKGFramesEndpoint to delegate to implementation
  - ✅ Added imports for FrameCreateResponse, KGFrame, GraphObject
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced main endpoint file by ~86 lines, established frame create organization
- **Delegation Pattern**: `from vitalgraph.kg.kgframe_create_endpoint_impl import create_kgframes_impl`

### ✅ Migration #4: `create_frame_slots()` Function - COMPLETED
- **Status**: ✅ Successfully completed
- **Source**: `MockKGFramesEndpoint.create_frame_slots()` (lines 795-890, ~96 lines)
- **Target**: `vitalgraph/kg/kgframe_create_endpoint_impl.py`
- **Function**: `create_frame_slots_impl()`
- **Completed Steps**:
  - ✅ Added function to existing frame create implementation file
  - ✅ Updated MockKGFramesEndpoint to delegate to implementation
  - ✅ Added imports for SlotCreateResponse, KGSlot types, Edge_hasKGSlot
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced main endpoint file by ~96 lines, consolidated frame create operations
- **Delegation Pattern**: `from vitalgraph.kg.kgframe_create_endpoint_impl import create_frame_slots_impl`

### ✅ Migration #5: `_handle_entity_create_mode()` Helper Function - COMPLETED
- **Status**: ✅ Successfully completed
- **Source**: `MockKGEntitiesEndpoint._handle_entity_create_mode()` (lines 987-1028, ~42 lines)
- **Target**: `vitalgraph/kg/kgentity_create_endpoint_impl.py`
- **Function**: `handle_entity_create_mode_impl()`
- **Completed Steps**:
  - ✅ Added helper function to existing entity create implementation file
  - ✅ Updated MockKGEntitiesEndpoint to delegate to implementation
  - ✅ Added EntityUpdateResponse import for helper function
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced main endpoint file by ~42 lines, consolidated create mode handling
- **Delegation Pattern**: `from vitalgraph.kg.kgentity_create_endpoint_impl import handle_entity_create_mode_impl`

### ✅ Migration #6: `_handle_create_mode()` Helper Function - COMPLETED
- **Status**: ✅ Successfully completed
- **Source**: `MockKGFramesEndpoint._handle_create_mode()` (lines 328-369, ~42 lines)
- **Target**: `vitalgraph/kg/kgframe_create_endpoint_impl.py`
- **Function**: `handle_create_mode_impl()`
- **Completed Steps**:
  - ✅ Added helper function to existing frame create implementation file
  - ✅ Updated MockKGFramesEndpoint to delegate to implementation
  - ✅ Added FrameUpdateResponse import for helper function
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced main endpoint file by ~42 lines, consolidated frame create mode handling
- **Delegation Pattern**: `from vitalgraph.kg.kgframe_create_endpoint_impl import handle_create_mode_impl`

## DELETE OPERATIONS PHASE - STARTED

### ✅ Migration #7: `delete_kgentity()` Function - COMPLETED
- **Status**: ✅ Successfully completed
- **Source**: `MockKGEntitiesEndpoint.delete_kgentity()` (lines 317-358, ~42 lines)
- **Target**: `vitalgraph/kg/kgentity_delete_endpoint_impl.py`
- **Function**: `delete_kgentity_impl()`
- **Completed Steps**:
  - ✅ Created new implementation file for entity delete operations
  - ✅ Updated MockKGEntitiesEndpoint to delegate to implementation
  - ✅ Added EntityDeleteResponse import for delete operations
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced main endpoint file by ~42 lines, established entity delete organization
- **Delegation Pattern**: `from vitalgraph.kg.kgentity_delete_endpoint_impl import delete_kgentity_impl`

### ✅ Migration #8: `delete_entity_frames()` Function - COMPLETED
- **Status**: ✅ Successfully completed
- **Source**: `MockKGEntitiesEndpoint.delete_entity_frames()` (lines 714-779, ~66 lines)
- **Target**: `vitalgraph/kg/kgentity_delete_endpoint_impl.py`
- **Function**: `delete_entity_frames_impl()`
- **Completed Steps**:
  - ✅ Added function to existing entity delete implementation file
  - ✅ Updated MockKGEntitiesEndpoint to delegate to implementation
  - ✅ Added FrameDeleteResponse import for delete operations
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced main endpoint file by ~66 lines, consolidated entity delete operations
- **Delegation Pattern**: `from vitalgraph.kg.kgentity_delete_endpoint_impl import delete_entity_frames_impl`

### ✅ Migration #9: `delete_kgframe()` Function - COMPLETED
- **Status**: ✅ Successfully completed
- **Source**: `MockKGFramesEndpoint.delete_kgframe()` (lines 511-551, ~41 lines)
- **Target**: `vitalgraph/kg/kgframe_delete_endpoint_impl.py`
- **Function**: `delete_kgframe_impl()`
- **Completed Steps**:
  - ✅ Created new implementation file for frame delete operations
  - ✅ Updated MockKGFramesEndpoint to delegate to implementation
  - ✅ Added FrameDeleteResponse import for delete operations
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced main endpoint file by ~41 lines, established frame delete organization
- **Delegation Pattern**: `from vitalgraph.kg.kgframe_delete_endpoint_impl import delete_kgframe_impl`

### ✅ Migration #10: `delete_frame_slots()` Function - COMPLETED
- **Status**: ✅ Successfully completed
- **Source**: `MockKGFramesEndpoint.delete_frame_slots()` (lines 787-851, ~65 lines)
- **Target**: `vitalgraph/kg/kgframe_delete_endpoint_impl.py`
- **Function**: `delete_frame_slots_impl()`
- **Completed Steps**:
  - ✅ Added function to existing frame delete implementation file
  - ✅ Updated MockKGFramesEndpoint to delegate to implementation
  - ✅ Added SlotDeleteResponse import for delete operations
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced main endpoint file by ~65 lines, consolidated frame delete operations
- **Delegation Pattern**: `from vitalgraph.kg.kgframe_delete_endpoint_impl import delete_frame_slots_impl`

## DUPLICATE FUNCTION CLEANUP PHASE - STARTED

### 🚨 Duplicate Function Issues Discovered
During migration work, multiple duplicate function definitions were discovered that need resolution:

#### **MockKGEntitiesEndpoint Duplicates:**
1. `create_entity_frames` - Line 573 (delegation) vs Line 1634 (complex with operation_mode)
2. `delete_entity_frames` - Line 714 (delegation) vs Line 1895 (complex implementation)
3. `get_entity_frames` - Line 719 (simple) vs Line 1783 (complex implementation)
4. `_set_dual_grouping_uris` - Multiple definitions need investigation

#### **MockKGFramesEndpoint Duplicates:**
1. `get_frame_slots` - Line 792 (slot_type param) vs Line 1716 (kGSlotType param)

### ✅ Migration #11: Fix `create_entity_frames()` Duplicates - COMPLETED
- **Status**: ✅ Successfully completed
- **Issue**: Two functions with same name, second overrides first
- **First Function**: Line 573 - Simple delegation to impl file
- **Second Function**: Line 1634 - Complex implementation with operation_mode parameter
- **Resolution Strategy**: Migrate complex implementation to impl file, remove duplicates
- **Target**: `vitalgraph/kg/kgentity_create_endpoint_impl.py`
- **Completed Steps**:
  - ✅ Added complex implementation as `create_entity_frames_complex_impl()` to impl file
  - ✅ Updated first function to delegate to complex implementation with operation_mode
  - ✅ Removed duplicate complex implementation from mock endpoint
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Resolved duplicate function issue, maintained complex functionality
- **Delegation Pattern**: `from vitalgraph.kg.kgentity_create_endpoint_impl import create_entity_frames_complex_impl`

### ✅ Migration #12: Fix `delete_entity_frames()` Duplicates - COMPLETED
- **Status**: ✅ Successfully completed
- **Issue**: Two functions with same name, second overrides first
- **First Function**: Line 714 - Simple delegation to impl file
- **Second Function**: Line 1747 - Complex implementation with validation
- **Resolution Strategy**: Migrate complex implementation to impl file, remove duplicates
- **Target**: `vitalgraph/kg/kgentity_delete_endpoint_impl.py`
- **Completed Steps**:
  - ✅ Added complex implementation as `delete_entity_frames_complex_impl()` to impl file
  - ✅ Updated first function to delegate to complex implementation
  - ✅ Removed duplicate complex implementation from mock endpoint
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Resolved duplicate function issue, maintained validation and graceful error handling
- **Delegation Pattern**: `from vitalgraph.kg.kgentity_delete_endpoint_impl import delete_entity_frames_complex_impl`

## 🎉 DUPLICATE FUNCTION CLEANUP - EXCELLENT PROGRESS!

### **✅ Completed Duplicate Fixes (2/5):**
1. **Migration #11**: `create_entity_frames()` duplicates ✅ **COMPLETED**
2. **Migration #12**: `delete_entity_frames()` duplicates ✅ **COMPLETED**

### ✅ Migration #13: Fix `get_entity_frames()` Duplicates - COMPLETED
- **Status**: ✅ Successfully completed
- **Issue**: Two functions with same name, second overrides first
- **First Function**: Line 719 - Simple implementation
- **Second Function**: Line 1635 - Complex implementation with advanced SPARQL queries
- **Resolution Strategy**: Migrate complex implementation to new get impl file, remove duplicates
- **Target**: `vitalgraph/kg/kgentity_get_endpoint_impl.py` (newly created)
- **Completed Steps**:
  - ✅ Created new `kgentity_get_endpoint_impl.py` file for get operations
  - ✅ Added complex implementation as `get_entity_frames_complex_impl()` to impl file
  - ✅ Updated first function to delegate to complex implementation
  - ✅ Removed duplicate complex implementation from mock endpoint
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Resolved duplicate function issue, maintained advanced SPARQL query functionality
- **Delegation Pattern**: `from vitalgraph.kg.kgentity_get_endpoint_impl import get_entity_frames_complex_impl`

### ✅ Migration #14: Fix `get_frame_slots()` Duplicates - COMPLETED
- **Status**: ✅ Successfully completed
- **Issue**: Two functions with same name but different parameter names
- **First Function**: Line 792 - Uses `slot_type` parameter
- **Second Function**: Line 1597 - Uses `kGSlotType` parameter with advanced SPARQL
- **Resolution Strategy**: Migrate complex implementation to new get impl file, standardize parameter name
- **Target**: `vitalgraph/kg/kgframe_get_endpoint_impl.py` (newly created)
- **Completed Steps**:
  - ✅ Created new `kgframe_get_endpoint_impl.py` file for frame get operations
  - ✅ Added complex implementation as `get_frame_slots_complex_impl()` to impl file
  - ✅ Updated first function to use `kGSlotType` parameter name (standardized)
  - ✅ Updated first function to delegate to complex implementation
  - ✅ Removed duplicate complex implementation from mock endpoint
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Resolved duplicate function issue, standardized parameter naming, maintained advanced SPARQL functionality
- **Delegation Pattern**: `from vitalgraph.kg.kgframe_get_endpoint_impl import get_frame_slots_complex_impl`

### ✅ Migration #15: Fix `_set_dual_grouping_uris()` Duplicates - COMPLETED
- **Status**: ✅ Successfully completed
- **Issue**: Two functions with same name, second overrides first
- **First Function**: Line 1205 - Complex implementation with frame structure analysis
- **Second Function**: Line 1687 - Simple implementation with basic grouping
- **Resolution Strategy**: Move complex implementation to utility file, remove duplicates
- **Target**: `vitalgraph/utils/graph_operations.py` (shared utility)
- **Completed Steps**:
  - ✅ Added complex implementation as `set_dual_grouping_uris()` to graph operations utility
  - ✅ Added fallback `set_entity_grouping_uris()` function to utility
  - ✅ Updated first function to delegate to utility function
  - ✅ Removed duplicate second implementation from mock endpoint
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Resolved duplicate function issue, created reusable utility for grouping URI management
- **Delegation Pattern**: `from vitalgraph.utils.graph_operations import set_dual_grouping_uris`

## 🎉 DUPLICATE FUNCTION CLEANUP - COMPLETED SUCCESSFULLY!

### **✅ ALL Duplicate Fixes Completed (5/5):**
1. **Migration #11**: `create_entity_frames()` duplicates ✅ **COMPLETED**
2. **Migration #12**: `delete_entity_frames()` duplicates ✅ **COMPLETED**
3. **Migration #13**: `get_entity_frames()` duplicates ✅ **COMPLETED**
4. **Migration #14**: `get_frame_slots()` duplicates ✅ **COMPLETED**
5. **Migration #15**: `_set_dual_grouping_uris()` duplicates ✅ **COMPLETED**

**📊 Progress: 100% Complete (5/5 duplicates resolved)** 🎉

---

# 🚀 PHASE 3: SYSTEMATIC FUNCTION MIGRATION

## Overview
With the duplicate function cleanup phase completed successfully, we now proceed to the systematic migration of remaining functions from the large mock endpoint files into specialized implementation files. This phase will continue the incremental, function-by-function approach that has proven highly effective.

## Current Status Assessment

### ✅ **Completed Infrastructure (Excellent Foundation)**
- **Utility Files**: All 4 utility modules completed and tested ✅
- **Implementation Files**: 6 implementation files created with proven delegation patterns ✅
- **Duplicate Cleanup**: All 5 duplicate function issues resolved ✅
- **Test Coverage**: All 13/13 tests passing consistently ✅

### 📊 **Current File Sizes (Need Reduction)**
Based on the large endpoint files, we need to continue systematic migration:

**MockKGEntitiesEndpoint**: ~1,700+ lines
- **Target**: Reduce to ~500-800 lines (delegation functions only)
- **Approach**: Migrate complex implementations to specialized files

**MockKGFramesEndpoint**: ~1,600+ lines  
- **Target**: Reduce to ~500-800 lines (delegation functions only)
- **Approach**: Continue migration pattern established in Phase 2

## 🎯 Phase 3 Migration Strategy

### **Migration Priorities (Function Complexity Analysis)**

#### **High Priority - Complex Functions (Migrate First)**
1. **Entity Graph Operations**
   - `_process_complete_entity_document()` - Complex VitalSigns processing
   - `_validate_entity_graph_structure()` - Multi-object validation
   - `_get_entity_with_complete_graph()` - Advanced SPARQL queries

2. **Frame Graph Operations**
   - `_get_frame_with_complete_graph()` - Complex graph retrieval
   - `_backup_frame_graph()` - Backup/restore functionality
   - `_restore_frame_graph_from_backup()` - Complex restoration logic

3. **Advanced Query Operations**
   - `_build_entity_search_query()` - Dynamic SPARQL generation
   - `_execute_entity_graph_query()` - Complex query execution
   - `_detect_stale_triples()` - Graph analysis functions

#### **Medium Priority - Helper Functions**
4. **Validation Functions**
   - `_validate_frame_exists()` - Existence checking
   - `_validate_entity_exists()` - Entity validation
   - Various `_validate_*` helper methods

5. **Conversion Functions**
   - `_convert_triples_to_vitalsigns_objects()` - VitalSigns conversion
   - `_objects_to_jsonld_document()` - JSON-LD formatting
   - Various conversion utilities

#### **Lower Priority - Simple Functions**
6. **Basic Helper Methods**
   - `_log_method_call()` - Simple logging
   - `_clean_uri()` - URI formatting
   - Simple getter/setter methods

### **Target Implementation Files (Expand Existing)**

#### **Entity Operations**
- `kgentity_create_endpoint_impl.py` - ✅ Exists, expand with more create operations
- `kgentity_delete_endpoint_impl.py` - ✅ Exists, expand with more delete operations  
- `kgentity_get_endpoint_impl.py` - ✅ Exists, expand with more get operations
- `kgentity_update_endpoint_impl.py` - 🆕 Create for update operations
- `kgentity_query_endpoint_impl.py` - 🆕 Create for complex query operations

#### **Frame Operations**
- `kgframe_create_endpoint_impl.py` - ✅ Exists, expand with more create operations
- `kgframe_delete_endpoint_impl.py` - ✅ Exists, expand with more delete operations
- `kgframe_get_endpoint_impl.py` - ✅ Exists, expand with more get operations  
- `kgframe_update_endpoint_impl.py` - 🆕 Create for update operations
- `kgframe_query_endpoint_impl.py` - 🆕 Create for complex query operations

### **Migration Methodology (Proven Approach)**

#### **Step-by-Step Process**
1. **Identify Target Function** - Select next complex function for migration
2. **Create/Expand Implementation File** - Add function to appropriate impl file
3. **Update Mock Endpoint** - Replace with delegation call
4. **Test Integration** - Run full test suite (must maintain 13/13 passing)
5. **Update Planning Document** - Track progress and note any issues
6. **Repeat** - Continue with next function

#### **Quality Gates**
- ✅ **All tests must pass** after each migration
- ✅ **No functionality changes** - maintain exact same behavior
- ✅ **Clean delegation pattern** - consistent import and call structure
- ✅ **Proper error handling** - maintain existing exception handling
- ✅ **Documentation updates** - keep docstrings and comments accurate

## 🎯 Next Steps

### ✅ Migration #16: `_process_complete_entity_document()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `_process_complete_entity_document()` - Complex VitalSigns processing (~58 lines)
- **Source**: MockKGEntitiesEndpoint (lines 1210-1267)
- **Target**: `kgentity_create_endpoint_impl.py` as `process_complete_entity_document_impl()`
- **Complexity**: High - VitalSigns object creation, categorization, validation, error handling
- **Completed Steps**:
  - ✅ Added complex implementation to `kgentity_create_endpoint_impl.py`
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained all VitalSigns object categorization logic (entities, frames, slots, edges)
  - ✅ Preserved dual grouping URI functionality
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced main endpoint file by ~58 lines, improved code organization
- **Delegation Pattern**: `from vitalgraph.kg.kgentity_create_endpoint_impl import process_complete_entity_document_impl`

### ✅ Migration #17: `_convert_triples_to_vitalsigns_objects()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `_convert_triples_to_vitalsigns_objects()` - Complex VitalSigns conversion (~54 lines)
- **Source**: MockKGEntitiesEndpoint (lines 1114-1168)
- **Target**: `vitalsigns_helpers.py` as `convert_triples_to_vitalsigns_objects()`
- **Complexity**: High - N-Triples formatting, URI validation, VitalSigns RDF conversion
- **Completed Steps**:
  - ✅ Added complex implementation to `vitalsigns_helpers.py` utility
  - ✅ Updated mock endpoint function to delegate to utility function
  - ✅ Maintained all N-Triples formatting logic and URI validation
  - ✅ Preserved VitalSigns RDF conversion functionality
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced main endpoint file by ~54 lines, created reusable utility function
- **Delegation Pattern**: `from vitalgraph.utils.vitalsigns_helpers import convert_triples_to_vitalsigns_objects`

### ✅ Migration #18: `_get_entity_with_complete_graph()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `_get_entity_with_complete_graph()` - Complex graph retrieval (~38 lines)
- **Source**: MockKGEntitiesEndpoint (lines 1041-1078)
- **Target**: `kgentity_get_endpoint_impl.py` as `get_entity_with_complete_graph_impl()`
- **Complexity**: High - SPARQL execution, graph retrieval, JSON-LD conversion
- **Completed Steps**:
  - ✅ Added complex implementation to `kgentity_get_endpoint_impl.py`
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained SPARQL executor functionality and graph retrieval logic
  - ✅ Preserved GroupingURIGraphRetriever integration
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced main endpoint file by ~38 lines, improved code organization
- **Delegation Pattern**: `from vitalgraph.kg.kgentity_get_endpoint_impl import get_entity_with_complete_graph_impl`

### ✅ Migration #19: JSON-LD Conversion Functions - COMPLETED
- **Status**: ✅ Successfully completed
- **Functions**: `_convert_triples_to_jsonld()` + `_simple_triples_to_jsonld()` (~57 lines total)
- **Source**: MockKGEntitiesEndpoint (lines 1046-1108)
- **Target**: `vitalsigns_helpers.py` as `convert_triples_to_jsonld()` and `simple_triples_to_jsonld()`
- **Complexity**: High - VitalSigns JSON-LD conversion, fallback logic, error handling
- **Completed Steps**:
  - ✅ Added both implementations to `vitalsigns_helpers.py` utility
  - ✅ Updated mock endpoint functions to delegate to utility functions
  - ✅ Maintained VitalSigns to JSON-LD conversion logic
  - ✅ Preserved fallback simple conversion functionality
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced main endpoint file by ~57 lines, created reusable JSON-LD utilities
- **Delegation Pattern**: `from vitalgraph.utils.vitalsigns_helpers import convert_triples_to_jsonld, simple_triples_to_jsonld`

### ✅ Migration #20: `_get_single_entity()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `_get_single_entity()` - Standard entity retrieval (~56 lines)
- **Source**: MockKGEntitiesEndpoint (lines 984-1039)
- **Target**: `kgentity_get_endpoint_impl.py` as `get_single_entity_impl()`
- **Complexity**: High - SPARQL queries, VitalSigns conversion, JSON-LD processing
- **Completed Steps**:
  - ✅ Added complex implementation to `kgentity_get_endpoint_impl.py`
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained SPARQL query logic and result processing
  - ✅ Preserved VitalSigns object conversion and JSON-LD functionality
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced main endpoint file by ~52 lines (1,483 → 1,431 lines)
- **Delegation Pattern**: `from vitalgraph.kg.kgentity_get_endpoint_impl import get_single_entity_impl`

### ✅ Migration #21: `_handle_entity_update_mode()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `_handle_entity_update_mode()` - Complex entity update logic (~50 lines)
- **Source**: MockKGEntitiesEndpoint (lines 737-787)
- **Target**: New file `kgentity_update_endpoint_impl.py` as `handle_entity_update_mode_impl()`
- **Complexity**: High - Entity existence validation, backup/rollback, atomic operations
- **Completed Steps**:
  - ✅ Created new specialized implementation file for update operations
  - ✅ Added complex implementation with full error handling and rollback logic
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained atomic update operations and backup/restore functionality
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced main endpoint file by ~46 lines (1,431 → 1,385 lines)
- **Delegation Pattern**: `from vitalgraph.kg.kgentity_update_endpoint_impl import handle_entity_update_mode_impl`

### ✅ Migration #22: `_handle_entity_upsert_mode()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `_handle_entity_upsert_mode()` - Complex entity upsert logic (~57 lines)
- **Source**: MockKGEntitiesEndpoint (lines 743-799)
- **Target**: New file `kgentity_upsert_endpoint_impl.py` as `handle_entity_upsert_mode_impl()`
- **Complexity**: High - Entity existence checking, URI validation, create-or-update logic
- **Completed Steps**:
  - ✅ Created new specialized implementation file for upsert operations (separate from update)
  - ✅ Added complex implementation with entity existence validation and URI consistency checks
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained create-or-update logic with proper action reporting
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced main endpoint file by ~52 lines (1,385 → 1,333 lines)
- **Delegation Pattern**: `from vitalgraph.kg.kgentity_upsert_endpoint_impl import handle_entity_upsert_mode_impl`

### ✅ Migration #23: `_get_current_entity_objects()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `_get_current_entity_objects()` - SPARQL entity object retrieval (~35 lines)
- **Source**: MockKGEntitiesEndpoint (lines 769-804)
- **Target**: `kgentity_get_endpoint_impl.py` as `get_current_entity_objects_impl()`
- **Complexity**: High - SPARQL queries, grouping URI logic, object reconstruction
- **Completed Steps**:
  - ✅ Added complex implementation to `kgentity_get_endpoint_impl.py`
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained SPARQL query logic with PREFIX declarations
  - ✅ Preserved URIPlaceholder object creation and subject deduplication
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced main endpoint file by ~32 lines (1,333 → 1,301 lines)
- **Delegation Pattern**: `from vitalgraph.kg.kgentity_get_endpoint_impl import get_current_entity_objects_impl`

### ✅ Migration #24: `list_kgentities()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `list_kgentities()` - Complex entity listing with pagination (~137 lines)
- **Source**: MockKGEntitiesEndpoint (lines 39-176)
- **Target**: New file `kgentity_list_endpoint_impl.py` as `list_kgentities_impl()`
- **Complexity**: Very High - SPARQL queries, pagination, search filtering, count queries
- **Completed Steps**:
  - ✅ Created new specialized implementation file for list operations
  - ✅ Added complex implementation with pagination and search functionality
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained SPARQL query logic with optional search filtering
  - ✅ Preserved count queries and typed literal handling
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced main endpoint file by ~121 lines (1,301 → 1,180 lines) - **BIGGEST SINGLE MIGRATION!**
- **Delegation Pattern**: `from vitalgraph.kg.kgentity_list_endpoint_impl import list_kgentities_impl`

### ✅ Migration #25: `get_kgentity()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `get_kgentity()` - Entity retrieval with optional complete graph (~45 lines)
- **Source**: MockKGEntitiesEndpoint (lines 57-101)
- **Target**: `kgentity_get_endpoint_impl.py` as `get_kgentity_impl()`
- **Complexity**: High - Space management, URI cleaning, conditional graph retrieval
- **Completed Steps**:
  - ✅ Added implementation to existing `kgentity_get_endpoint_impl.py`
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained space validation and URI cleaning logic
  - ✅ Preserved conditional logic for standard vs complete graph retrieval
  - ✅ Fixed import issues and tested integration - all 13/13 tests passing
- **Impact**: Reduced main endpoint file by ~30 lines (1,180 → 1,150 lines)
- **Delegation Pattern**: `from vitalgraph.kg.kgentity_get_endpoint_impl import get_kgentity_impl`

### ✅ Migration #26: `update_kgentities()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `update_kgentities()` - Complex entity lifecycle management (~87 lines)
- **Source**: MockKGEntitiesEndpoint (lines 78-164)
- **Target**: `kgentity_update_endpoint_impl.py` as `update_kgentities_impl()`
- **Complexity**: Very High - Parent validation, structure validation, operation mode routing
- **Completed Steps**:
  - ✅ Added implementation to existing `kgentity_update_endpoint_impl.py`
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained complete entity lifecycle management logic
  - ✅ Preserved parent object validation and structure validation
  - ✅ Maintained operation mode routing (create/update/upsert)
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced main endpoint file by ~63 lines (1,150 → 1,087 lines) - **MAJOR MIGRATION!**
- **Delegation Pattern**: `from vitalgraph.kg.kgentity_update_endpoint_impl import update_kgentities_impl`

### ✅ Migration #27: `delete_kgentities_batch()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `delete_kgentities_batch()` - Batch entity deletion (~49 lines)
- **Source**: MockKGEntitiesEndpoint (lines 108-156)
- **Target**: `kgentity_delete_endpoint_impl.py` as `delete_kgentities_batch_impl()`
- **Complexity**: Medium-High - Space management, URI parsing, batch operations
- **Completed Steps**:
  - ✅ Added implementation to existing `kgentity_delete_endpoint_impl.py`
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained URI list parsing and validation logic
  - ✅ Preserved batch deletion operations with proper counting
  - ✅ Maintained error handling and response formatting
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced main endpoint file by ~35 lines (1,087 → 1,052 lines)
- **Delegation Pattern**: `from vitalgraph.kg.kgentity_delete_endpoint_impl import delete_kgentities_batch_impl`

### ✅ Migration #28: `get_kgentity_frames()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `get_kgentity_frames()` - Entity-frame relationship queries (~78 lines)
- **Source**: MockKGEntitiesEndpoint (lines 123-199)
- **Target**: `kgentity_get_endpoint_impl.py` as `get_kgentity_frames_impl()`
- **Complexity**: High - SPARQL queries, conditional logic, result processing
- **Completed Steps**:
  - ✅ Added implementation to existing `kgentity_get_endpoint_impl.py`
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained complex SPARQL query logic for entity-frame relationships
  - ✅ Preserved conditional query building (with/without entity_uri)
  - ✅ Maintained result processing and pagination logic
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced main endpoint file by ~59 lines (1,052 → 993 lines) - **MAJOR MIGRATION!**
- **Delegation Pattern**: `from vitalgraph.kg.kgentity_get_endpoint_impl import get_kgentity_frames_impl`

### ✅ Migration #29: `query_entities()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `query_entities()` - Criteria-based entity search (~59 lines)
- **Source**: MockKGEntitiesEndpoint (lines 142-200)
- **Target**: NEW `kgentity_query_endpoint_impl.py` as `query_entities_impl()`
- **Complexity**: Medium-High - SPARQL query building, result processing, pagination
- **Completed Steps**:
  - ✅ Created new specialized implementation file for query operations
  - ✅ Added implementation with criteria-based search functionality
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained SPARQL query building from criteria
  - ✅ Preserved result extraction and URI deduplication logic
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced main endpoint file by ~45 lines (993 → 948 lines)
- **Delegation Pattern**: `from vitalgraph.kg.kgentity_query_endpoint_impl import query_entities_impl`

### ✅ Migration #30: `list_kgentities_with_graphs()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `list_kgentities_with_graphs()` - Entity listing with optional complete graphs (~59 lines)
- **Source**: MockKGEntitiesEndpoint (lines 157-216)
- **Target**: `kgentity_list_endpoint_impl.py` as `list_kgentities_with_graphs_impl()`
- **Complexity**: Medium-High - Entity listing, conditional graph inclusion, response formatting
- **Completed Steps**:
  - ✅ Added implementation to existing `kgentity_list_endpoint_impl.py`
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained entity listing with optional complete graphs logic
  - ✅ Preserved conditional graph inclusion and response formatting
  - ✅ Maintained error handling with proper fallbacks
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced main endpoint file by ~42 lines (948 → 906 lines)
- **Delegation Pattern**: `from vitalgraph.kg.kgentity_list_endpoint_impl import list_kgentities_with_graphs_impl`

### ✅ Migration #31: `update_entity_frames()` - COMPLETED - **🎉 50% MILESTONE CROSSED!**
- **Status**: ✅ Successfully completed
- **Function**: `update_entity_frames()` - Complex frame update with JSON-LD parsing (~135 lines)
- **Source**: MockKGEntitiesEndpoint (lines 183-317)
- **Target**: `kgentity_update_endpoint_impl.py` as `update_entity_frames_impl()`
- **Complexity**: Very High - JSON-LD parsing, VitalSigns conversion, SPARQL operations
- **Completed Steps**:
  - ✅ Added implementation to existing `kgentity_update_endpoint_impl.py`
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained complex JSON-LD document parsing logic
  - ✅ Preserved multiple format handling (@graph arrays, single objects, VitalSigns format)
  - ✅ Maintained SPARQL DELETE/INSERT operations for frame updates
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced main endpoint file by ~120 lines (906 → 786 lines) - **MASSIVE MIGRATION!**
- **Delegation Pattern**: `from vitalgraph.kg.kgentity_update_endpoint_impl import update_entity_frames_impl`

### **🎉 Phase 3 Progress Summary - 50% MILESTONE ACHIEVED!**
**Migrations Completed**: 16/16 planned migrations
1. **Migration #16**: `_process_complete_entity_document()` ✅ (58 lines migrated)
2. **Migration #17**: `_convert_triples_to_vitalsigns_objects()` ✅ (54 lines migrated)
3. **Migration #18**: `_get_entity_with_complete_graph()` ✅ (38 lines migrated)
4. **Migration #19**: JSON-LD conversion functions ✅ (57 lines migrated)
5. **Migration #20**: `_get_single_entity()` ✅ (52 lines migrated)
6. **Migration #21**: `_handle_entity_update_mode()` ✅ (46 lines migrated)
7. **Migration #22**: `_handle_entity_upsert_mode()` ✅ (52 lines migrated)
8. **Migration #23**: `_get_current_entity_objects()` ✅ (32 lines migrated)
9. **Migration #24**: `list_kgentities()` ✅ (121 lines migrated) - **BIGGEST MIGRATION!**
10. **Migration #25**: `get_kgentity()` ✅ (30 lines migrated)
11. **Migration #26**: `update_kgentities()` ✅ (63 lines migrated) - **MAJOR MIGRATION!**
12. **Migration #27**: `delete_kgentities_batch()` ✅ (35 lines migrated)
13. **Migration #28**: `get_kgentity_frames()` ✅ (59 lines migrated) - **MAJOR MIGRATION!**
14. **Migration #29**: `query_entities()` ✅ (45 lines migrated)
15. **Migration #30**: `list_kgentities_with_graphs()` ✅ (42 lines migrated)
16. **Migration #31**: `update_entity_frames()` ✅ (120 lines migrated) - **MASSIVE MIGRATION!**

**🎉 MILESTONE ACHIEVED**: **904 lines** of complex code successfully migrated!
**File Size Progress**: **1,700+ → 786 lines** (~53.8% reduction achieved) - **50% MILESTONE CROSSED!**

### **Architecture Enhancement Summary**
**New Implementation Files Created**:
- `kgentity_create_endpoint_impl.py` - Entity creation operations
- `kgentity_get_endpoint_impl.py` - Entity retrieval operations  
- `kgentity_update_endpoint_impl.py` - Entity update operations
- `kgentity_upsert_endpoint_impl.py` - Entity upsert operations
- `kgentity_list_endpoint_impl.py` - Entity listing operations with pagination
- `kgentity_query_endpoint_impl.py` - Entity query operations with criteria-based search
- Enhanced `vitalsigns_helpers.py` - JSON-LD and VitalSigns utilities

---

## **🎯 PHASE 4: KGFRAMES ENDPOINT REFACTORING**

### ✅ Migration #32: `list_kgframes()` - COMPLETED - **NEW FOCUS: KGFRAMES ENDPOINT**
- **Status**: ✅ Successfully completed
- **Function**: `list_kgframes()` - Frame listing with SPARQL queries and pagination (~138 lines)
- **Source**: MockKGFramesEndpoint (lines 47-183)
- **Target**: NEW `kgframe_list_endpoint_impl.py` as `list_kgframes_impl()`
- **Complexity**: High - SPARQL queries, result processing, VitalSigns conversion, pagination
- **Completed Steps**:
  - ✅ Created new specialized implementation file for KGFrame list operations
  - ✅ Added implementation with complex SPARQL query building and search functionality
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained SPARQL result grouping and VitalSigns object conversion
  - ✅ Preserved pagination and total count calculation logic
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced KGFrames endpoint file by ~121 lines (1,752 → 1,631 lines)
- **Delegation Pattern**: `from vitalgraph.kg.kgframe_list_endpoint_impl import list_kgframes_impl`

### ✅ Migration #33: `get_kgframe()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `get_kgframe()` - Frame retrieval with optional complete graph (~39 lines)
- **Source**: MockKGFramesEndpoint (lines 64-102)
- **Target**: `kgframe_get_endpoint_impl.py` as `get_kgframe_impl()`
- **Complexity**: Medium - URI handling, conditional graph retrieval, error handling
- **Completed Steps**:
  - ✅ Added implementation to existing `kgframe_get_endpoint_impl.py`
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained URI cleaning and conditional graph retrieval logic
  - ✅ Preserved complete frame graph functionality
  - ✅ Maintained error handling with proper fallbacks
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced KGFrames endpoint file by ~24 lines (1,631 → 1,607 lines)
- **Delegation Pattern**: `from vitalgraph.kg.kgframe_get_endpoint_impl import get_kgframe_impl`

### ✅ Migration #34: `update_kgframes()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `update_kgframes()` - Complex frame lifecycle management (~87 lines)
- **Source**: MockKGFramesEndpoint (lines 85-171)
- **Target**: NEW `kgframe_update_endpoint_impl.py` as `update_kgframes_impl()`
- **Complexity**: Very High - Parent validation, structure validation, operation modes
- **Completed Steps**:
  - ✅ Created new specialized implementation file for KGFrame update operations
  - ✅ Added implementation with complex frame lifecycle management
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained parent object validation and grouping URI stripping
  - ✅ Preserved complete frame structure validation and operation mode handling
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced KGFrames endpoint file by ~63 lines (1,607 → 1,544 lines)
- **Delegation Pattern**: `from vitalgraph.kg.kgframe_update_endpoint_impl import update_kgframes_impl`

### ✅ Migration #35: `_handle_update_mode()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `_handle_update_mode()` - Complex update mode handling with atomic operations (~48 lines)
- **Source**: MockKGFramesEndpoint (lines 126-176)
- **Target**: `kgframe_update_endpoint_impl.py` as `handle_update_mode_impl()`
- **Complexity**: Very High - Frame existence validation, parent connection validation, atomic backup/restore
- **Completed Steps**:
  - ✅ Added implementation to existing `kgframe_update_endpoint_impl.py`
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained frame existence validation and parent connection logic
  - ✅ Preserved atomic backup/delete/insert operations with rollback capability
  - ✅ Maintained comprehensive error handling and rollback mechanisms
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced KGFrames endpoint file by ~46 lines (1,544 → 1,498 lines)
- **Delegation Pattern**: `from vitalgraph.kg.kgframe_update_endpoint_impl import handle_update_mode_impl`

### ✅ Migration #36: `_handle_upsert_mode()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `_handle_upsert_mode()` - Complex upsert mode handling with frame consistency (~60 lines)
- **Source**: MockKGFramesEndpoint (lines 132-192)
- **Target**: `kgframe_upsert_endpoint_impl.py` as `handle_upsert_mode_impl()`
- **Complexity**: Very High - Frame existence checks, URI consistency validation, conditional deletion
- **Completed Steps**:
  - ✅ Added implementation to correct `kgframe_upsert_endpoint_impl.py` file
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained frame existence validation and URI consistency checks
  - ✅ Preserved conditional deletion logic for frame-to-frame connections
  - ✅ Maintained parent connection validation and grouping URI management
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced KGFrames endpoint file by ~56 lines (1,498 → 1,442 lines)
- **Delegation Pattern**: `from vitalgraph.kg.kgframe_upsert_endpoint_impl import handle_upsert_mode_impl`

### ✅ Migration #37: `get_kgframe_with_slots()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `get_kgframe_with_slots()` - Complex frame and slot retrieval with SPARQL UNION (~87 lines)
- **Source**: MockKGFramesEndpoint (lines 256-342)
- **Target**: `kgframe_get_endpoint_impl.py` as `get_kgframe_with_slots_impl()`
- **Complexity**: Very High - Complex SPARQL UNION queries, subject grouping, dual object type handling
- **Completed Steps**:
  - ✅ Added implementation to existing `kgframe_get_endpoint_impl.py`
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained complex SPARQL UNION query for frame and slot retrieval
  - ✅ Preserved subject grouping logic and dual VitalSigns object type handling
  - ✅ Maintained comprehensive error handling and empty result fallbacks
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced KGFrames endpoint file by ~73 lines (1,442 → 1,369 lines)
- **Delegation Pattern**: `from vitalgraph.kg.kgframe_get_endpoint_impl import get_kgframe_with_slots_impl`

### ✅ Migration #38: `create_kgframes_with_slots()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `create_kgframes_with_slots()` - Complex frame and slot creation with object filtering (~64 lines)
- **Source**: MockKGFramesEndpoint (lines 271-334)
- **Target**: `kgframe_create_endpoint_impl.py` as `create_kgframes_with_slots_impl()`
- **Complexity**: High - JSON-LD to VitalSigns conversion, object filtering, batch storage
- **Completed Steps**:
  - ✅ Added implementation to existing `kgframe_create_endpoint_impl.py`
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained JSON-LD to VitalSigns object conversion logic
  - ✅ Preserved complex object filtering for KGFrame, KGSlot, and Edge objects
  - ✅ Maintained batch storage operations and URI collection
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced KGFrames endpoint file by ~50 lines (1,369 → 1,319 lines)
- **Delegation Pattern**: `from vitalgraph.kg.kgframe_create_endpoint_impl import create_kgframes_with_slots_impl`

### ✅ Migration #39: `update_frame_slots()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `update_frame_slots()` - Frame slot update with object filtering (~60 lines)
- **Source**: MockKGFramesEndpoint (lines 293-352)
- **Target**: `kgframe_update_endpoint_impl.py` as `update_frame_slots_impl()`
- **Complexity**: High - JSON-LD to VitalSigns conversion, KGSlot filtering, batch update
- **Completed Steps**:
  - ✅ Added implementation to existing `kgframe_update_endpoint_impl.py`
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained JSON-LD to VitalSigns object conversion logic
  - ✅ Preserved KGSlot object filtering and validation
  - ✅ Maintained batch update operations and URI handling
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced KGFrames endpoint file by ~45 lines (1,319 → 1,274 lines)
- **Delegation Pattern**: `from vitalgraph.kg.kgframe_update_endpoint_impl import update_frame_slots_impl`

### ✅ Migration #40: `_get_single_frame()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `_get_single_frame()` - Complex single frame retrieval with debugging (~90 lines)
- **Source**: MockKGFramesEndpoint (lines 321-410)
- **Target**: `kgframe_get_endpoint_impl.py` as `get_single_frame_impl()`
- **Complexity**: Very High - SPARQL queries, property reconstruction, VitalSigns conversion, JSON-LD formatting
- **Completed Steps**:
  - ✅ Added implementation to existing `kgframe_get_endpoint_impl.py`
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained complex SPARQL query logic with alternative search fallback
  - ✅ Preserved detailed property reconstruction and URI cleaning
  - ✅ Maintained VitalSigns object conversion and JSON-LD @graph structure handling
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced KGFrames endpoint file by ~86 lines (1,274 → 1,188 lines)
- **Delegation Pattern**: `from vitalgraph.kg.kgframe_get_endpoint_impl import get_single_frame_impl`

### ✅ Migration #41: `_get_frame_with_complete_graph()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `_get_frame_with_complete_graph()` - Complex complete graph retrieval with fallback (~55 lines)
- **Source**: MockKGFramesEndpoint (lines 326-380)
- **Target**: `kgframe_get_endpoint_impl.py` as `get_frame_with_complete_graph_impl()`
- **Complexity**: Very High - Multi-step retrieval, SPARQL queries, triples conversion, fallback logic
- **Completed Steps**:
  - ✅ Added implementation to existing `kgframe_get_endpoint_impl.py`
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained multi-step retrieval process (single frame + complete graph)
  - ✅ Preserved complex SPARQL query for hasFrameGraphURI grouping
  - ✅ Maintained triples conversion and VitalSigns object processing with fallback logic
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced KGFrames endpoint file by ~51 lines (1,188 → 1,137 lines)
- **Delegation Pattern**: `from vitalgraph.kg.kgframe_get_endpoint_impl import get_frame_with_complete_graph_impl`

### ✅ Migration #42: `_backup_frame_graph()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `_backup_frame_graph()` - Complex frame graph backup with multi-query operations (~80 lines)
- **Source**: MockKGFramesEndpoint (lines 354-433)
- **Target**: `kgframe_update_endpoint_impl.py` as `backup_frame_graph_impl()`
- **Complexity**: Very High - Multi-query operations, triples collection, comprehensive backup
- **Completed Steps**:
  - ✅ Added implementation to existing `kgframe_update_endpoint_impl.py`
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained complex multi-query backup operations (frame + slots + edges)
  - ✅ Preserved comprehensive triples collection and data structure organization
  - ✅ Maintained detailed logging and error handling for backup operations
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced KGFrames endpoint file by ~76 lines (1,137 → 1,061 lines)
- **Delegation Pattern**: `from vitalgraph.kg.kgframe_update_endpoint_impl import backup_frame_graph_impl`

### ✅ Migration #43: `_delete_frame_graph_from_store()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `_delete_frame_graph_from_store()` - Complex multi-step frame graph deletion (~68 lines)
- **Source**: MockKGFramesEndpoint (lines 359-426)
- **Target**: `kgframe_delete_endpoint_impl.py` as `delete_frame_graph_from_store_impl()`
- **Complexity**: Very High - Multi-step deletion, SPARQL DELETE operations, atomic cleanup
- **Completed Steps**:
  - ✅ Added implementation to existing `kgframe_delete_endpoint_impl.py`
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained complex multi-step deletion process (slots → edges → frame)
  - ✅ Preserved atomic SPARQL DELETE operations with proper ordering
  - ✅ Maintained comprehensive logging and error handling for deletion operations
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced KGFrames endpoint file by ~64 lines (1,061 → 997 lines)
- **Delegation Pattern**: `from vitalgraph.kg.kgframe_delete_endpoint_impl import delete_frame_graph_from_store_impl`

### ✅ Migration #44: `_restore_frame_graph_from_backup()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `_restore_frame_graph_from_backup()` - Complex frame graph restoration with quad operations (~40 lines)
- **Source**: MockKGFramesEndpoint (lines 364-404)
- **Target**: `kgframe_update_endpoint_impl.py` as `restore_frame_graph_from_backup_impl()`
- **Complexity**: High - PyOxigraph quad operations, multi-type restoration, atomic rollback
- **Completed Steps**:
  - ✅ Added implementation to existing `kgframe_update_endpoint_impl.py`
  - ✅ Updated mock endpoint function to delegate to impl function
  - ✅ Maintained complex PyOxigraph quad creation and restoration logic
  - ✅ Preserved multi-type restoration (frame + slot + edge triples)
  - ✅ Maintained atomic rollback operations and comprehensive logging
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced KGFrames endpoint file by ~37 lines (997 → 960 lines)
- **Delegation Pattern**: `from vitalgraph.kg.kgframe_update_endpoint_impl import restore_frame_graph_from_backup_impl`

### ✅ Migration #45: `detect_stale_triples()` - COMPLETED - **🎉 50% MILESTONE CROSSED!**
- **Status**: ✅ Successfully completed
- **Function**: `detect_stale_triples()` - Complex diagnostic function with multiple SPARQL queries (~138 lines)
- **Source**: MockKGFramesEndpoint (lines 369-506)
- **Target**: NEW `vitalgraph/utils/kgframe_diagnostics_impl.py` as `detect_stale_triples_impl()`
- **Complexity**: Very High - Multiple complex SPARQL queries, comprehensive diagnostics, detailed reporting
- **Completed Steps**:
  - ✅ Created new specialized diagnostics implementation file
  - ✅ Added comprehensive stale triple detection implementation
  - ✅ Maintained complex multi-query diagnostic operations (orphaned slots/edges, broken references, inconsistent grouping)
  - ✅ Preserved detailed SPARQL UNION queries and comprehensive error categorization
  - ✅ Maintained summary generation and conditional logging based on findings
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced KGFrames endpoint file by ~129 lines (960 → 831 lines) - **🎉 CROSSED 50% MILESTONE!**
- **Delegation Pattern**: `from vitalgraph.utils.kgframe_diagnostics_impl import detect_stale_triples_impl`

### ✅ Migration #46: `cleanup_stale_triples()` - COMPLETED - **🎉 PUSHING TOWARD 60%!**
- **Status**: ✅ Successfully completed
- **Function**: `cleanup_stale_triples()` - Complex cleanup function with multiple SPARQL DELETE operations (~104 lines)
- **Source**: MockKGFramesEndpoint (lines 379-482)
- **Target**: Enhanced `vitalgraph/utils/kgframe_diagnostics_impl.py` as `cleanup_stale_triples_impl()`
- **Complexity**: Very High - Multiple SPARQL DELETE operations, iterative cleanup, comprehensive error handling
- **Completed Steps**:
  - ✅ Enhanced existing diagnostics implementation file with cleanup functionality
  - ✅ Added comprehensive stale triple cleanup implementation
  - ✅ Maintained complex multi-step cleanup operations (orphaned slots/edges, broken references)
  - ✅ Preserved detailed SPARQL DELETE queries and comprehensive error collection
  - ✅ Maintained cleanup statistics and detailed logging of operations
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced KGFrames endpoint file by ~90 lines (831 → 741 lines) - **🎉 PUSHING TOWARD 60%!**
- **Delegation Pattern**: `from vitalgraph.utils.kgframe_diagnostics_impl import cleanup_stale_triples_impl`

### ✅ Migration #47: `_get_current_frame_objects()` - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `_get_current_frame_objects()` - Frame object retrieval with SPARQL and object reconstruction (~36 lines)
- **Source**: MockKGFramesEndpoint (lines 143-178)
- **Target**: Enhanced `kgframe_get_endpoint_impl.py` as `get_current_frame_objects_impl()`
- **Complexity**: High - SPARQL queries, object reconstruction, URI placeholder logic
- **Completed Steps**:
  - ✅ Enhanced existing get implementation file with current frame objects functionality
  - ✅ Added comprehensive frame object retrieval implementation
  - ✅ Maintained complex SPARQL query for hasFrameGraphURI grouping
  - ✅ Preserved object reconstruction logic with URI placeholder pattern
  - ✅ Maintained error handling and empty result fallbacks
  - ✅ Tested integration - all functionality preserved
- **Impact**: Reduced KGFrames endpoint file by ~36 lines
- **Delegation Pattern**: `from vitalgraph.kg.kgframe_get_endpoint_impl import get_current_frame_objects_impl`

### ✅ Migration #48: `delete_kgframes_batch()` - COMPLETED - **🎉 EXCEEDED 60% UPPER BOUND!**
- **Status**: ✅ Successfully completed
- **Function**: `delete_kgframes_batch()` - Batch frame deletion with URI parsing (~48 lines)
- **Source**: MockKGFramesEndpoint (lines 174-221)
- **Target**: Enhanced `kgframe_delete_endpoint_impl.py` as `delete_kgframes_batch_impl()`
- **Complexity**: High - Batch operations, URI parsing, iterative deletion
- **Completed Steps**:
  - ✅ Enhanced existing delete implementation file with batch deletion functionality
  - ✅ Added comprehensive batch deletion implementation
  - ✅ Maintained URI list parsing and validation logic
  - ✅ Preserved iterative deletion with success counting
  - ✅ Maintained comprehensive error handling and response formatting
  - ✅ Tested integration - all functionality preserved
- **Impact**: Reduced KGFrames endpoint file by ~67 lines (741 → 674 lines) - **🎉 EXCEEDED 60% UPPER BOUND!**
- **Delegation Pattern**: `from vitalgraph.kg.kgframe_delete_endpoint_impl import delete_kgframes_batch_impl`

### ✅ Migration #49: VitalSigns Conversion Utilities - COMPLETED - **🎉 UNPRECEDENTED 70% ACHIEVEMENT!**
- **Status**: ✅ Successfully completed
- **Functions**: 4 utility methods migrated to new specialized utility module (~151 lines total)
  - `_create_vitalsigns_objects_from_jsonld()` - VitalSigns object creation with validation (~42 lines)
  - `_object_to_triples()` - Object to RDF triples conversion (~37 lines)
  - `_store_triples()` - PyOxigraph storage operations (~28 lines)
  - `_convert_triples_to_vitalsigns_objects()` - Triples to VitalSigns conversion (~55 lines)
- **Source**: MockKGFramesEndpoint (lines 339-512)
- **Target**: NEW `vitalgraph/utils/vitalsigns_conversion_utils.py` - Complete VitalSigns conversion suite
- **Complexity**: Very High - Complex VitalSigns operations, RDF processing, PyOxigraph integration
- **Completed Steps**:
  - ✅ Created new specialized VitalSigns conversion utility module
  - ✅ Added comprehensive VitalSigns conversion implementations
  - ✅ Maintained complex JSON-LD to VitalSigns object creation with validation
  - ✅ Preserved RDF triples conversion and PyOxigraph storage operations
  - ✅ Maintained N-Triples formatting and VitalSigns list processing
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced KGFrames endpoint file by ~151 lines (674 → 523 lines) - **🎉 ACHIEVED UNPRECEDENTED 70% REDUCTION!**
- **Delegation Pattern**: `from vitalgraph.utils.vitalsigns_conversion_utils import [function_name]_impl`

### **🎯 Phase 4 Focus: MockKGFramesEndpoint Refactoring - 🎉 UNPRECEDENTED SUCCESS!**
**Target File**: `mock_kgframes_endpoint.py` (1,752 → 523 lines after 18 migrations)
**Goal**: Apply same systematic migration approach to achieve 50-60% reduction (~875-1,050 lines)
**Current Progress**: 70.1% reduction achieved (1,229 lines migrated) - **🎉 UNPRECEDENTED 70% ACHIEVEMENT! FAR BEYOND ALL EXPECTATIONS!**

### ✅ Migration #50: KGEntities JSON-LD Conversion Utility - COMPLETED
- **Status**: ✅ Successfully completed
- **Function**: `_jsonld_to_triples()` - JSON-LD to triples conversion utility (~56 lines)
- **Source**: MockKGEntitiesEndpoint (lines 389-455)
- **Target**: Enhanced `vitalgraph/utils/vitalsigns_conversion_utils.py` as `jsonld_to_triples_impl()`
- **Complexity**: High - PyOxigraph integration, JSON-LD parsing, URI formatting
- **Completed Steps**:
  - ✅ Enhanced existing VitalSigns conversion utility module
  - ✅ Added comprehensive JSON-LD to triples conversion implementation
  - ✅ Maintained complex PyOxigraph store operations and JSON-LD parsing
  - ✅ Preserved URI formatting logic and VitalSigns-specific triple generation
  - ✅ Maintained debug logging and comprehensive error handling
  - ✅ Tested integration - all 13/13 tests passing
- **Impact**: Reduced KGEntities endpoint file by ~56 lines (787 → 731 lines) - **Maintaining 53.8% reduction**
- **Delegation Pattern**: `from vitalgraph.utils.vitalsigns_conversion_utils import jsonld_to_triples_impl`

### **Next Action: Continue Cross-Endpoint Utility Migration**
**Target**: Identify more utility functions for migration across both endpoints
- **Approach**: Search for more utility functions in both KGEntities and KGFrames endpoints
- **Focus**: Utility functions that can be shared between endpoints
- **Goal**: Continue systematic utility consolidation and code reduction

### **Success Metrics for Phase 3**
- **File Size Reduction**: Reduce endpoint files by 50-60% (target ~800 lines each)
- **Test Stability**: Maintain 13/13 tests passing throughout
- **Implementation Files**: Create 4-6 new specialized implementation files
- **Code Organization**: Clear separation of concerns with proper delegation
- **Maintainability**: Easier to locate and modify specific functionality

### **Estimated Timeline**
- **Migration #16-20**: Entity processing functions (5 migrations)
- **Migration #21-25**: Frame processing functions (5 migrations)  
- **Migration #26-30**: Query and validation functions (5 migrations)
- **Total Estimate**: 15-20 function migrations for significant improvement

The foundation is excellent, the methodology is proven, and we're ready to continue the systematic migration with confidence! 🚀

## Target Utility Files

### Utility Modules (Phase 1 & 2 - COMPLETED)
- `vitalgraph/utils/sparql_helpers.py` - Common SPARQL operations ✅
- `vitalgraph/utils/vitalsigns_helpers.py` - VitalSigns object utilities ✅
- `vitalgraph/utils/graph_operations.py` - Graph traversal and grouping URI utilities ✅
- `vitalgraph/utils/endpoint_validation.py` - Common validation patterns ✅

### Function to File Mapping
*To be populated as analysis progresses...*

## Dependencies and Considerations

### Existing Dependencies
- VitalSigns integration patterns
- pyoxigraph SPARQL operations
- JSON-LD conversion workflows
- Edge relationship management
- Grouping URI functionality

### Refactoring Constraints
- Must maintain backward compatibility
- All existing tests must continue to pass
- No breaking changes to public interfaces
- Preserve error handling patterns

## Testing Strategy

### Test Requirements
- Unit tests for extracted utility functions
- Integration tests to verify endpoint functionality unchanged
- Performance tests to ensure no regression
- Error handling validation

### Test Files to Update
*To be identified as refactoring progresses...*

## Progress Log

### 2024-11-25
- ✅ Created refactoring plan document
- ✅ Completed analysis of MockKGEntitiesEndpoint (27 methods identified)
- ✅ Completed analysis of MockKGFramesEndpoint (23 methods identified)
- ✅ Built comprehensive commonality matrix
- ✅ Identified 9 refactoring candidates with priority rankings
- ✅ Created first refactoring proposal for `_object_exists_in_store()`

**Analysis Phase Complete** - Ready to proceed with function-by-function refactoring

---

*This document will be updated as the analysis and refactoring progresses*