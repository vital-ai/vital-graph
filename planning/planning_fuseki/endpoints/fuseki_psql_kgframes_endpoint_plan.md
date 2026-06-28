# KGFrames Endpoint Implementation Plan

This document outlines the implementation plan for the KGFrames REST API endpoint in VitalGraph, focusing on comprehensive frame management with slot support and hierarchical relationships.

## Current Issues

### JSON-LD Model Usage
- Use `JsonLdObject` for single VitalSigns objects
- Use `JsonLdDocument` for multiple objects with `@graph` arrays
- Do NOT use `JsonLdDocument` for single objects

### CombinedProperty Iteration Errors
- Error: `'CombinedProperty' object is not iterable` 
- Occurs when VitalSigns URI properties are used in contexts expecting strings

**Use String Casting When Needed for String Operations**
- Use `str(property)` only when the property value is needed as a string
- Example: `frame_uris = [str(frame.URI) for frame in frames]` for string lists

### 🚨 CRITICAL: VitalSigns Serialization Errors in Client Tests

**ISSUE IDENTIFIED**: KGFrames client tests are experiencing persistent CombinedProperty serialization errors that must be fixed properly.

**Root Cause Analysis**:
- VitalSigns `CombinedProperty` objects cannot be serialized directly by Python's `json` library or HTTP requests
- The issue occurs when `slot.to_jsonld()` or `frame.to_jsonld()` results contain `CombinedProperty` objects
- These objects fail during HTTP request serialization with error: `'CombinedProperty' object is not iterable`

**Current Workaround (Temporary)**:
```python
# Force clean CombinedProperty objects by JSON roundtrip
import json
jsonld_dict = slot.to_jsonld()
clean_jsonld_str = json.dumps(jsonld_dict, default=str)
document = json.loads(clean_jsonld_str)
```

**REQUIRED PROPER FIX**:
1. **VitalSigns Library Fix**: Update VitalSigns `to_jsonld()` methods to return fully serializable dictionaries
2. **Client Framework Fix**: Implement proper CombinedProperty handling in client request serialization
3. **Test Pattern Fix**: Establish consistent pattern for VitalSigns object serialization across all client tests

**POTENTIAL SOLUTION**: 
- **Adjust JSON-LD Serialization Functions**: Modify VitalSigns JSON-LD serialization functions (`to_jsonld()`, `GraphObject.to_jsonld_list()`) to automatically convert `CombinedProperty` objects to their string representations during serialization
- **Implementation Approach**: Add property object detection and conversion within the serialization methods themselves, ensuring all output is fully JSON-serializable
- **Benefit**: This would fix the root cause at the VitalSigns level, eliminating the need for workarounds in client code

**COMPARISON WITH WORKING KGEntities**:
- KGEntities client tests work because they use different VitalSigns object creation patterns
- KGEntities uses `GraphObject.to_jsonld_list()` for multiple objects vs single object `to_jsonld()`
- Both approaches should work without manual JSON cleaning

**ACTION REQUIRED**: 
- The serialization errors must be resolved at the VitalSigns/client framework level
- Current JSON cleaning workaround is not sustainable for production
- All KGFrames client tests currently require this workaround to function

## Validation and Graph Grouping URI Requirements

### Entity and Parent URI Validation

The KGFrames endpoint supports flexible validation for frame operations through entity and parent URI parameters:

**Validation Scope:**
- **Entity URI Validation**: When `entity_uri` parameter is provided, the endpoint validates that the entity exists and the user has access
- **Parent URI Validation**: When `parent_uri` parameter is provided, the endpoint validates the parent object (which may be either an entity or frame)
- **Object Retrieval**: The endpoint may retrieve objects associated with the validated entity URI or parent URI for relationship validation

**Graph Grouping URI Assignment:**
- **Entity-Associated Frames**: When creating frames with a validated `entity_uri`, the endpoint uses the entity URI to assign the graph grouping URI (`kGGraphURI`)
- **Standalone Frames**: When creating frames without an entity URI, frames use their own URI for graph grouping
- **Hierarchical Frames**: Child frames inherit the entity URI from their parent frame for consistent graph grouping

**Validation Process:**
1. **Entity URI Validation**: If `entity_uri` is provided, validate entity exists and user has access
2. **Parent URI Validation**: If `parent_uri` is provided, validate parent object exists and determine if it's an entity or frame
3. **Relationship Validation**: Ensure proper parent-child relationships are maintained
4. **Graph Grouping Assignment**: Set `kGGraphURI` based on validated entity URI or frame hierarchy

**Implementation Requirements:**
- Validate entity existence before frame creation
- Support both entity and frame parent URIs
- Maintain consistent graph grouping across frame hierarchies
- Provide clear error messages for validation failures

## Test Architecture Requirements

**CRITICAL**: KGFrames endpoint tests must follow the correct two-endpoint architecture:

### Correct Test Architecture Pattern

**Entity Graph Creation (KGEntities Endpoint)**:
- Entity graphs are created using the KGEntities endpoint
- This creates entities with associated frames and slots as a complete graph
- The KGEntities endpoint handles entity creation, validation, and graph assembly

**Frame Operations (KGFrames Endpoint)**:
- Once entity graphs exist, the KGFrames endpoint accesses/modifies frames within those graphs
- KGFrames endpoint operates on existing frames, not entity creation
- Frame operations include retrieval, updates, queries, and slot management

### Test Implementation Requirements

**Two-Endpoint Test Pattern**:
1. **Setup Phase**: Use KGEntities endpoint to create entity graphs with frames
2. **Test Phase**: Use KGFrames endpoint to test frame operations on existing graphs
3. **Cleanup Phase**: Use appropriate endpoints to clean up test data

**Test Orchestrator Requirements**:
- Initialize both KGEntities and KGFrames endpoints
- Provide both endpoints to test functions
- Ensure proper entity graph setup before frame testing

### Test Categories Implementation

**Two-Tier Testing Strategy** (as implemented in fuseki_postgresql test):

#### Category 1: Standalone Tests (Independent of Entities)
- Test frame/slot functionality without requiring entity graphs
- Direct KGFrames endpoint operations on standalone frames
- Includes: frame creation, retrieval, updates, deletion, queries
- Includes: slot CRUD operations on standalone frames
- **Pattern**: `test_func(kgframes_endpoint, space_id, graph_id, logger)`

#### Category 2: Integration Tests (Using KGEntities Endpoint)  
- Test frame/slot operations in conjunction with entity graphs
- Use KGEntities endpoint to create entity graphs first
- Then test KGFrames operations on those entity-associated frames
- Includes: entity-frame integration, cross-endpoint consistency
- **Pattern**: `test_func(kgframes_endpoint, kgentities_endpoint, space_id, graph_id, logger)`

### Test Function Signature Requirements

**All KGFrames test functions must use one of these signatures:**

#### Standalone Tests (4 parameters):
```python
async def test_function(kgframes_endpoint, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test standalone frame/slot functionality."""
    pass
```

#### Integration Tests (5 parameters):
```python  
async def test_function(kgframes_endpoint, kgentities_endpoint, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test entity-frame integration functionality."""
    pass
```

### Test Orchestrator Pattern

The test orchestrator must:
1. Initialize both KGEntities and KGFrames endpoints
2. Detect test function signature (4 vs 5 parameters) using `inspect.signature()`
3. Call appropriate test pattern based on parameter count
4. Handle both standalone and integration test categories
5. Provide comprehensive test result reporting

## API Endpoint Test Case Requirements

**MANDATORY**: Test cases must be created for each and every KGFrames API endpoint to ensure comprehensive coverage of all frame and slot operations.

### KG Frames Operations Test Coverage

**GET /api/kgframes** - Kg Frames Operations
- Test case: List frames with pagination (requires existing entity graphs)
- Test case: Filter frames by entity URI (requires existing entity graphs)
- Test case: Filter frames by parent URI (requires existing entity graphs)
- Test case: Search frames by properties (requires existing entity graphs)
- Test case: Empty result handling
- Test case: Invalid parameter validation
- Test case: Authentication and authorization

**POST /api/kgframes** - Create Kg Frames
- Test case: Create standalone frame (no entity)
- Test case: Create entity-associated frame (requires existing entity)
- Test case: Create hierarchical frame (parent frame)
- Test case: Create frame with slots
- Test case: Batch frame creation
- Test case: UPSERT operation mode
- Test case: Invalid JSON-LD validation
- Test case: Duplicate URI handling

**DELETE /api/kgframes** - Delete Kg Frames
- Test case: Delete single frame by URI
- Test case: Delete multiple frames (batch)
- Test case: Delete frame with cascading slots
- Test case: Delete hierarchical frame structure
- Test case: Non-existent frame handling
- Test case: Authorization validation

**POST /api/kgframes/query** - Query Kg Frames
- Test case: Query by frame type
- Test case: Query by entity association
- Test case: Query by hierarchical relationship
- Test case: Complex multi-criteria queries
- Test case: Pagination in query results
- Test case: Invalid query syntax handling

### KG Frame Slots Operations Test Coverage

**GET /api/kgframes/kgslots** - Get Frame Slots
- Test case: List all slots with pagination
- Test case: Filter slots by frame URI
- Test case: Filter slots by slot type
- Test case: Search slots by value
- Test case: Empty slot collection handling
- Test case: Invalid filter parameters

**POST /api/kgframes/kgslots** - Create Frame Slots
- Test case: Create single slot
- Test case: Create multiple slots (batch)
- Test case: Create slots with different types (text, number, date, etc.)
- Test case: Create slots for standalone frames
- Test case: Create slots for entity-associated frames
- Test case: UPSERT slot operation
- Test case: Invalid slot data validation

**PUT /api/kgframes/kgslots** - Update Frame Slots
- Test case: Update single slot value
- Test case: Update multiple slots (batch)
- Test case: Update slot type
- Test case: Update slot metadata
- Test case: Non-existent slot handling
- Test case: Concurrent update handling

**DELETE /api/kgframes/kgslots** - Delete Frame Slots
- Test case: Delete single slot by URI
- Test case: Delete multiple slots (batch)
- Test case: Delete all slots for a frame
- Test case: Non-existent slot handling
- Test case: Cascade delete validation

### Test Implementation Requirements

**Two-Tier Testing Strategy:**
1. **Standalone Tests**: Test frame and slot operations independent of entities
2. **Integration Tests**: Test frame and slot operations in conjunction with KGEntities endpoint

**Test Coverage Metrics:**
- Each endpoint must achieve 100% code path coverage
- All error conditions must be tested
- All parameter combinations must be validated
- Performance benchmarks for batch operations

**Test Data Requirements:**
- Comprehensive test data sets for each operation
- Edge case scenarios (empty data, large datasets, malformed input)
- Cross-endpoint consistency validation

## Missing Test Cases - Next Implementation Steps

**IMPLEMENTATION STATUS**: The following test cases are missing from the current implementation and need to be added to achieve complete API endpoint coverage. Authentication/authorization tests are excluded from this implementation.

### ✅ **GET /api/kgframes** - Missing Tests (6/7 implemented)
- [x] **Filter frames by entity URI** - Test filtering frames associated with specific entities
- [x] **Search frames by properties** - Test property-based search functionality  
- [x] **Invalid parameter validation** - Test error handling for malformed parameters

### ✅ **POST /api/kgframes** - Missing Tests (8/8 implemented)
- [x] **Invalid JSON-LD validation** - Test handling of malformed JSON-LD input
- [x] **Duplicate URI handling** - Test conflict resolution for duplicate frame URIs

### ✅ **DELETE /api/kgframes** - Missing Tests (6/6 implemented)
- [x] **Delete hierarchical frame structure** - Test complete hierarchy deletion with proper cascade

### ✅ **POST /api/kgframes/query** - Missing Tests (6/6 implemented)
- [x] **Query by frame type** - Test querying frames by kGFrameType
- [x] **Query by entity association** - Test querying frames associated with entities
- [x] **Query by hierarchical relationship** - Test querying parent/child frame relationships
- [x] **Complex multi-criteria queries** - Test queries with multiple filter conditions
- [x] **Pagination in query results** - Test query result pagination
- [x] **Invalid query syntax handling** - Test error handling for malformed queries

### ✅ **GET /api/kgframes/kgslots** - Missing Tests (6/6 implemented)
- [x] **Filter slots by slot type** - Test filtering slots by kGSlotType
- [x] **Search slots by value** - Test searching slots by their values
- [x] **Empty slot collection handling** - Test behavior when no slots exist
- [x] **Invalid filter parameters** - Test error handling for invalid filters

### ✅ **POST /api/kgframes/kgslots** (Update Operations) - Missing Tests (6/6 implemented)
- [x] **Update single slot value** - Test updating individual slot values
- [x] **Update multiple slots (batch)** - Test batch slot value updates
- [x] **Update slot type** - Test changing slot type (if supported)
- [x] **Update slot metadata** - Test updating slot properties/metadata
- [x] **Non-existent slot handling** - Test error handling for missing slots
- [x] **Concurrent update handling** - Test handling of simultaneous slot updates

### ✅ **DELETE /api/kgframes/kgslots** - Missing Tests (5/5 implemented)
- [x] **Delete single slot by URI** - Test deleting individual slots
- [x] **Delete multiple slots (batch)** - Test batch slot deletion
- [x] **Delete all slots for a frame** - Test removing all slots from a frame
- [x] **Non-existent slot handling** - Test error handling for missing slots
- [x] **Cascade delete validation** - Test proper cleanup of slot relationships

**TOTAL MISSING TESTS**: 25 test cases across 7 API endpoints

**IMPLEMENTATION PRIORITY**:
1. **HIGH**: Query operations (complete gap - 6 tests)
2. **HIGH**: Slot updates/deletes (complete gaps - 11 tests)  
3. **MEDIUM**: Advanced filtering/validation (scattered gaps - 8 tests)

## Slot Endpoint Functionality

The KGFrames endpoint includes comprehensive slot management through dedicated slot endpoints:

### Slot Endpoints

#### GET /api/graphs/kgframes/kgslots
**Get Frame Slots**
- List slots with optional frame filtering
- Pagination support (page_size, offset)
- Search functionality across slot properties
- Optional frame_uri parameter to filter slots by parent frame
- Returns SlotListResponse with slot data in JSON-LD format
- **Optional Parameters:**
  - `parent_uri` (string | null): Parent entity or frame URI
  - `entity_uri` (string | null): Entity URI for entity graph association

#### POST /api/graphs/kgframes/kgslots
**Create Frame Slots**
- Create new slots associated with frames
- Supports multiple slot types (KGTextSlot, KGDoubleSlot, KGDateTimeSlot, etc.)
- Automatic frame-slot relationship creation (Edge_hasKGSlot)
- Operation modes: CREATE, UPDATE, UPSERT
- Delegates to KGSlotCreateProcessor for backend operations
- **Optional Parameters:**
  - `parent_uri` (string | null): Parent entity or frame URI
  - `entity_uri` (string | null): Entity URI for entity graph association

#### POST /api/graphs/kgframes/kgslots (Update Operation)
**Update Frame Slots**
- Update existing slots with new values (changed from PUT to POST)
- Atomic slot replacement using DELETE + INSERT pattern
- Maintains frame-slot relationships during updates
- Delegates to KGSlotUpdateProcessor for backend operations
- **Optional Parameters:**
  - `parent_uri` (string | null): Parent entity or frame URI
  - `entity_uri` (string | null): Entity URI for entity graph association

#### DELETE /api/graphs/kgframes/kgslots
**Delete Frame Slots**
- Delete individual slots or batch deletion
- Optional slot graph deletion (cascading delete of related objects)
- Maintains referential integrity with parent frames
- Delegates to KGSlotDeleteProcessor for backend operations

### Slot Processor Architecture

The slot endpoints leverage dedicated processors following entity processor patterns:

- **KGSlotCreateProcessor**: Handles slot creation with frame relationship management
- **KGSlotDeleteProcessor**: Manages slot deletion with cascade options
- **KGSlotUpdateProcessor**: Provides atomic slot updates using update_quads
- **Slot Discovery**: Integrated with frame discovery for slot retrieval operations

### Slot Test Coverage

Comprehensive test coverage for slot operations:

- **case_frame_slots.py**: Complete slot CRUD test module
- **Slot Creation Tests**: POST endpoint validation with multiple slot types
- **Slot Retrieval Tests**: GET endpoint validation with filtering and pagination
- **Slot Update Tests**: POST endpoint validation with atomic updates (changed from PUT)
- **Slot Deletion Tests**: DELETE endpoint validation with cascade options

### Client Update Requirements

**⚠️ IMPORTANT: Client updates required for slot endpoint changes:**

1. **Update Method**: Slot update operations changed from `PUT` to `POST`
2. **New Parameters**: All slot endpoints now support optional parameters:
   - `parent_uri` (string | null): Parent entity or frame URI for relationship management
   - `entity_uri` (string | null): Entity URI for entity graph association and enclosing graph context

**Entity Graph URI Usage:**
- The `entity_uri` parameter associates KGFrame slots with an enclosing entity graph
- Enables proper graph-level organization and retrieval of slot collections
- Supports hierarchical slot management within entity contexts

**Parent URI Usage:**
- The `parent_uri` parameter covers cases where the parent is either an entity graph or a frame
- Provides flexible parent-child relationships for slot organization
- Supports both direct entity-slot and frame-slot associations

### Implementation Status
- **Current Status**: ✅ COMPLETE - Server implementation 100% functional
- **Server Implementation**: ✅ All KGFrames endpoints fully implemented and tested
- **Test Coverage**: ✅ Comprehensive test suite with 100% success rate (35/35 tests passing - January 17, 2026)
- **Frame Operations**: ✅ All frame and slot operations working correctly
- **Code Organization**: ✅ Major refactoring completed - SPARQL and JSON-LD utilities moved to dedicated processors
- **Test Architecture**: ✅ Two-endpoint architecture successfully implemented and validated
- **Integration Tests**: ✅ Entity-frame integration tests passing
- **Client Test Updates**: ✅ All client test files updated with convert_to_jsonld_request helper (January 17, 2026)
- **Priority**: High - Ready for client/server integration testing
- **Dependencies**: KGEntities endpoint (completed), Edge_hasEntityKGFrame relationships (completed)
- **Recent Achievement**: ✅ Fixed all KGFrames endpoint tests achieving 100% success rate (35/35)

### Latest Implementation Notes (January 2026)

**🔧 KGFRAMES ENDPOINT IMPLEMENTATION STATUS:**
- **Server Endpoints**: Core CRUD operations implemented and functional
- **Two-Endpoint Architecture**: Successfully implemented correct separation between KGEntities (entity graph creation) and KGFrames (frame operations)
- **Comprehensive Test Coverage**: All API endpoints fully tested with complete functionality validation
- **Import Errors Fixed**: Corrected all function name mismatches in test orchestrator
- **Integration Tests Fixed**: Added missing endpoint attribute for backward compatibility
- **Broken Code Cleanup**: Removed all unreachable code fragments and syntax errors
- **Function Signatures Updated**: All test functions use proper `(kgframes_endpoint, kgentities_endpoint, ...)` pattern

### ✅ January 17, 2026 - Local Test Fixes Complete (100% Pass Rate)

**Local Test Script**: `/test_scripts/fuseki_postgresql/test_kgframes_endpoint_fuseki_postgresql.py`

**All Fixes Applied:**
1. ✅ **JSON-LD Conversion Helper** - Created `test_utils.py` with `convert_to_jsonld_request()` function
   - Automatically selects `JsonLdObject` for single objects
   - Automatically selects `JsonLdDocument` for multiple objects
   - Handles empty lists correctly
   
2. ✅ **Processor Initialization** - Fixed lazy initialization of all processors
   - `slot_create_processor`, `slot_update_processor`, `slot_delete_processor`
   - `frame_processor` for entity frame operations
   
3. ✅ **Operation Mode Handling** - Fixed enum value usage
   - Use lowercase strings: `"create"`, `"update"`, `"upsert"`
   - Not uppercase: `"CREATE"`, `"UPDATE"`, `"UPSERT"`
   
4. ✅ **Edge Property Names** - Corrected all edge property references
   - Use `edgeSource` and `edgeDestination`
   - Not `hasEdgeSource` and `hasEdgeDestination`
   
5. ✅ **Parameter Names** - Fixed all parameter mismatches
   - Use `document=` for frame operations
   - Use `request=` for entity operations
   
6. ✅ **Response Attributes** - Fixed all response attribute access
   - Use `response.frames` for FramesResponse
   - Use `response.success` for operation status
   - Not `response.data`
   
7. ✅ **Backend Adapter Methods** - Implemented missing `get_object()` method
   - Added SPARQL CONSTRUCT query for object retrieval
   - Proper handling of `BackendOperationResult`
   
8. ✅ **UPSERT Mode** - Updated tests to use UPSERT for existing entities
   - Check `response.success` instead of `response.created_count`
   - Handles both create and update scenarios
   
9. ✅ **Search Filter** - Fixed SPARQL search query to use correct property URIs
   - `http://vital.ai/ontology/vital-core#hasName`
   - `http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription`
   - Not made-up property names

**Test Results**: 35/35 tests passing (100% success rate)

### ✅ January 17, 2026 - Client Test Updates Complete

**Client Test Directory**: `/vitalgraph_client_test/kgframes/`

**Files Updated:**
1. ✅ **test_utils.py** - Created with `convert_to_jsonld_request()` helper
2. ✅ **case_frame_create.py** - 4 conversions updated
3. ✅ **case_frame_update.py** - 4 conversions updated
4. ✅ **case_slot_create.py** - 5 conversions updated (replaced JSON roundtrip pattern)
5. ✅ **case_slot_update.py** - 4 conversions updated
6. ✅ **case_child_frames.py** - 3 conversions updated
7. ✅ **case_frames_with_slots.py** - 2 conversions updated
8. ✅ **case_integration_tests.py** - 6 conversions updated

**Pattern Applied:**
- **Before**: Manual JSON-LD conversion with `to_jsonld()` and `JsonLdObject(**jsonld_dict)`
- **After**: Consistent helper usage with `convert_to_jsonld_request(objects)`
- **Benefit**: All client tests now match the successful local test patterns

**Key Changes:**
- Removed JSON roundtrip cleaning pattern (`json.dumps()` → `json.loads()`)
- Consistent Pydantic model selection (JsonLdObject vs JsonLdDocument)
- All tests follow the same pattern as 100% passing local tests

**Status**: All major client test files updated and ready for integration testing

### 🚨 CRITICAL CLIENT TEST REQUIREMENTS

**VitalSigns Graph Objects Mandatory:**
- **NO Manual JSON-LD Creation**: Test cases must NEVER manually create JSON-LD data structures
- **Use ClientTestDataCreator**: All test data must use `/vitalgraph_client_test/client_test_data.py`
- **VitalSigns Objects Only**: Create KGFrame, KGSlot, Edge objects using VitalSigns domain models
- **Conversion via VitalSigns Utils**: Use VitalSigns utilities for JSON-LD conversion, never manual dict creation
- **Graph Object Pattern**: Follow `ClientTestDataCreator` patterns for entity/frame/slot relationships

**Required Imports for Client Tests:**
```python
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from vitalgraph_client_test.client_test_data import ClientTestDataCreator
```

**Test Data Creation Pattern:**
```python
# CORRECT - Use VitalSigns objects
test_data_creator = ClientTestDataCreator()
frame_objects = test_data_creator.create_frame_with_slots("Test Frame")
document = vitalsigns.to_jsonld_list(frame_objects)

# INCORRECT - Manual JSON-LD creation
frame_data = {"@context": {...}, "@graph": [...]}  # ❌ FORBIDDEN
```

**Test Categories Successfully Implemented:**
- ✅ **Standalone Frame Creation** (2 tests)
- ✅ **Frame Retrieval Tests** (3 tests) 
- ✅ **Frame Validation Tests** (3 tests)
- ✅ **Frame Query Tests** (6 tests)
- ✅ **Slot Retrieval Tests** (4 tests)
- ✅ **Slot Update Tests** (6 tests)
- ✅ **Slot Deletion Tests** (5 tests)
- ✅ **Integration Tests** (1 test)
- ✅ **Cleanup** (1 test)

**Architecture Benefits Achieved:**
- **Correct Separation of Concerns**: KGEntities for entity graphs, KGFrames for frame operations
- **Proper Cleanup**: All tests use KGEntities endpoint for cleanup
- **VitalSigns Integration**: Native JSON-LD handling throughout
- **Error Handling**: Comprehensive exception handling and graceful degradation
- **Production Ready**: All tests follow established patterns and best practices

## Next Steps: Client Implementation and Testing

### 🎯 **NEXT PHASE: Client Testing Implementation**

With the server implementation complete and all tests passing, the next critical phase is updating the client implementation and creating comprehensive client tests to match the server functionality.

### Client Update Requirements

#### 1. Update KGFrames Client Endpoint
**File**: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph/client/endpoint/kgframes_endpoint.py`

**Required Updates:**
- **Slot Update Method Change**: Update slot operations from `PUT` to `POST` method
- **New Optional Parameters**: Add support for `parent_uri` and `entity_uri` parameters across all slot endpoints
- **Method Signature Updates**: Ensure all client methods match the updated server API signatures
- **Response Model Updates**: Update response handling to match new server response models
- **Error Handling**: Implement proper error handling for new validation scenarios

**Specific Client Methods to Update:**
```python
# Frame Operations
async def list_frames(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, entity_uri: Optional[str] = None, parent_uri: Optional[str] = None, search: Optional[str] = None) -> FramesResponse
async def create_frames(self, space_id: str, graph_id: str, frames_data: Union[JsonLdObject, JsonLdDocument], entity_uri: Optional[str] = None, parent_uri: Optional[str] = None, operation_mode: str = "CREATE") -> FrameCreateResponse
async def update_frames(self, space_id: str, graph_id: str, frames_data: Union[JsonLdObject, JsonLdDocument], entity_uri: Optional[str] = None, parent_uri: Optional[str] = None) -> FrameUpdateResponse
async def delete_frames(self, space_id: str, graph_id: str, frame_uris: List[str]) -> FrameDeleteResponse
async def query_frames(self, space_id: str, graph_id: str, query_criteria: FrameQueryCriteria) -> FrameQueryResponse

# Slot Operations (Updated from PUT to POST)
async def list_slots(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, frame_uri: Optional[str] = None, entity_uri: Optional[str] = None, parent_uri: Optional[str] = None, search: Optional[str] = None) -> SlotListResponse
async def create_slots(self, space_id: str, graph_id: str, slots_data: Union[JsonLdObject, JsonLdDocument], entity_uri: Optional[str] = None, parent_uri: Optional[str] = None, operation_mode: str = "CREATE") -> SlotCreateResponse
async def update_slots(self, space_id: str, graph_id: str, slots_data: Union[JsonLdObject, JsonLdDocument], entity_uri: Optional[str] = None, parent_uri: Optional[str] = None) -> SlotUpdateResponse  # Changed from PUT to POST
async def delete_slots(self, space_id: str, graph_id: str, slot_uris: List[str]) -> SlotDeleteResponse
```

#### 2. Update Client Test Script
**File**: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph_client_test/test_kgframes_endpoint.py`

**Current Status**: Basic client test script exists but needs comprehensive updates to match server test coverage

**Required Updates:**
- **Test Architecture**: Implement two-endpoint testing pattern (KGEntities + KGFrames)
- **Comprehensive Coverage**: Match all 31 test cases from server implementation
- **Error Handling**: Test all error scenarios and edge cases
- **Authentication**: Use proper client authentication patterns
- **Data Validation**: Validate all response models and data structures

#### 3. Create Client Test Cases Directory
**Directory**: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph_client_test/kgframes/`

**Required Test Case Files** (matching server test structure):
```
vitalgraph_client_test/kgframes/
├── case_frame_create.py           # Frame creation test cases
├── case_frame_get.py              # Frame retrieval test cases  
├── case_frame_update.py           # Frame update test cases
├── case_frame_delete.py           # Frame deletion test cases
├── case_frame_query.py            # Frame query test cases
├── case_slot_create.py            # Slot creation test cases
├── case_slot_get.py               # Slot retrieval test cases
├── case_slot_update.py            # Slot update test cases
├── case_slot_delete.py            # Slot deletion test cases
├── case_frame_hierarchical.py    # Hierarchical frame test cases
├── case_entity_frame_integration.py  # Integration test cases
└── __init__.py                    # Package initialization
```

### Detailed Client Testing Implementation Plan

#### Phase 1: Client Endpoint Updates (Priority: HIGH)

**Step 1.1: Update KGFrames Client Methods**
- [ ] Update all method signatures to include new optional parameters
- [ ] Change slot update operations from PUT to POST
- [ ] Update request/response model handling
- [ ] Add proper error handling for new validation scenarios
- [ ] Test client methods against live server

**Step 1.2: Validate Client-Server Compatibility**
- [ ] Test all client methods against updated server endpoints
- [ ] Verify request/response model compatibility
- [ ] Validate parameter passing and error handling
- [ ] Ensure authentication works correctly

#### Phase 2: Client Test Case Implementation (Priority: HIGH)

**Step 2.1: Create Test Case Structure**
- [ ] Create `/vitalgraph_client_test/kgframes/` directory
- [ ] Implement base test case classes following server patterns
- [ ] Create individual test case files matching server structure
- [ ] Implement proper test data creation and cleanup

**Step 2.2: Frame Operations Test Cases**
- [ ] **case_frame_create.py**: Implement frame creation tests
  - [ ] Standalone frame creation
  - [ ] Entity-associated frame creation
  - [ ] Hierarchical frame creation
  - [ ] Frame creation with slots
  - [ ] Batch frame creation
  - [ ] Invalid JSON-LD validation
  - [ ] Duplicate URI handling
- [ ] **case_frame_get.py**: Implement frame retrieval tests
  - [ ] List frames with pagination
  - [ ] Filter frames by entity URI
  - [ ] Search frames by properties
  - [ ] Invalid parameter validation
- [ ] **case_frame_update.py**: Implement frame update tests
  - [ ] Single frame updates
  - [ ] Batch frame updates
  - [ ] Frame metadata updates
- [ ] **case_frame_delete.py**: Implement frame deletion tests
  - [ ] Single frame deletion
  - [ ] Batch frame deletion
  - [ ] Hierarchical frame deletion
  - [ ] Cascade deletion validation
- [ ] **case_frame_query.py**: Implement frame query tests
  - [ ] Query by frame type
  - [ ] Query by entity association
  - [ ] Query by hierarchical relationship
  - [ ] Complex multi-criteria queries
  - [ ] Pagination in query results
  - [ ] Invalid query syntax handling

**Step 2.3: Slot Operations Test Cases**
- [ ] **case_slot_create.py**: Implement slot creation tests
  - [ ] Single slot creation
  - [ ] Multiple slot creation
  - [ ] Different slot types (text, number, date)
  - [ ] Slots for standalone frames
  - [ ] Slots for entity-associated frames
- [ ] **case_slot_get.py**: Implement slot retrieval tests
  - [ ] List slots with pagination
  - [ ] Filter slots by frame URI
  - [ ] Filter slots by slot type
  - [ ] Search slots by value
  - [ ] Empty slot collection handling
- [ ] **case_slot_update.py**: Implement slot update tests (POST method)
  - [ ] Update single slot value
  - [ ] Update multiple slots batch
  - [ ] Update slot type
  - [ ] Update slot metadata
  - [ ] Non-existent slot handling
  - [ ] Concurrent update handling
- [ ] **case_slot_delete.py**: Implement slot deletion tests
  - [ ] Delete single slot by URI
  - [ ] Delete multiple slots batch
  - [ ] Delete all slots for frame
  - [ ] Non-existent slot handling
  - [ ] Cascade delete validation

**Step 2.4: Integration and Advanced Test Cases**
- [ ] **case_frame_hierarchical.py**: Implement hierarchical frame tests
  - [ ] Parent-child frame relationships
  - [ ] Multi-level hierarchies
  - [ ] Hierarchical deletion cascades
- [ ] **case_entity_frame_integration.py**: Implement integration tests
  - [ ] Entity-frame relationship validation
  - [ ] Cross-endpoint data consistency
  - [ ] Graph grouping URI validation
  - [ ] Two-endpoint workflow testing

#### Phase 3: Test Integration and Validation (Priority: MEDIUM)

**Step 3.1: Update Main Test Script**
- [ ] Update `test_kgframes_endpoint.py` to use new test case modules
- [ ] Implement test orchestration matching server patterns
- [ ] Add comprehensive test result reporting
- [ ] Implement proper test cleanup and error handling

**Step 3.2: Test Coverage Validation**
- [ ] Ensure 100% API endpoint coverage
- [ ] Validate all error scenarios are tested
- [ ] Test all parameter combinations
- [ ] Verify response model validation

**Step 3.3: Performance and Integration Testing**
- [ ] Test client performance against server
- [ ] Validate memory usage and connection handling
- [ ] Test concurrent client operations
- [ ] Validate authentication and authorization

#### Phase 4: Documentation and Finalization (Priority: LOW)

**Step 4.1: Update Documentation**
- [ ] Update client API documentation
- [ ] Create client usage examples
- [ ] Document new parameters and methods
- [ ] Update integration guides

**Step 4.2: Final Validation**
- [ ] Run complete test suite (client + server)
- [ ] Validate end-to-end workflows
- [ ] Performance benchmarking
- [ ] Production readiness assessment

### Success Criteria

**Client Implementation Complete When:**
- [ ] All client methods updated to match server API
- [ ] All 31 test cases implemented in client test suite
- [ ] 100% test success rate for client tests
- [ ] Full compatibility between client and server
- [ ] Comprehensive error handling and validation
- [ ] Documentation updated and complete

**Expected Timeline:**
- **Phase 1**: 2-3 days (Client endpoint updates)
- **Phase 2**: 5-7 days (Test case implementation)
- **Phase 3**: 2-3 days (Integration and validation)
- **Phase 4**: 1-2 days (Documentation and finalization)
- **Total**: 10-15 days for complete client testing implementation

This comprehensive plan ensures the client implementation matches the robust server functionality and provides reliable, well-tested KGFrames operations for production use.

## Quad Logging and Validation Requirements

### Purpose
Enable comprehensive debugging and validation of triple/quad storage and retrieval by logging all quads in a space and comparing SPARQL query results at different stages of data operations.

### Configuration Parameter
Add a configuration parameter to enable quad logging in space info operations:
- **Parameter**: `enable_quad_logging` (boolean, default: false)
- **Location**: VitalGraph configuration file
- **Usage**: Set to `true` in test environments to enable detailed quad logging

### Space Info Endpoint Quad Logging
When `enable_quad_logging` is enabled, the space info endpoint should:
1. Retrieve all quads in the specified space
2. Log each quad with subject, predicate, object, and graph
3. Group quads by graph URI for easier analysis
4. Include quad count statistics in the response

**Implementation Location**: Space service implementation (get space info method)

### Realistic Test Script Validation Points
The `test_realistic_organization_workflow.py` script should include validation at three critical checkpoints:

#### Checkpoint 1: Before Entity Graph Insert
- Query all triples in the test graph using SPARQL endpoint
- Get space info to trigger quad logging
- Baseline: Should be empty or contain only pre-existing data

#### Checkpoint 2: After Entity Graph Insert
- Query all triples in the test graph using SPARQL endpoint
- Get space info to trigger quad logging
- Validation: Verify entity, frames, slots, and edges are present
- Compare SPARQL results with quad logging output

#### Checkpoint 3: After Frame Updates (Before Space Deletion)
- Query all triples in the test graph using SPARQL endpoint
- Get space info to trigger quad logging
- Validation: Verify all slot updates are reflected in stored quads
- Compare SPARQL results with quad logging output
- Identify any discrepancies between expected and actual data

### ✅ Implementation Status (Completed January 18, 2026)

**Quad Logging Implementation Complete:**

1. **Configuration Parameter** ✅
   - Added `enable_quad_logging: true` to `vitalgraphdb-config.yaml`
   - Parameter correctly read from `fuseki_postgresql.database` section
   - Verified in Docker container configuration

2. **PostgreSQL Query Methods** ✅ (in `FusekiPostgreSQLDbImpl`)
   - `get_graph_uris(space_id)` - Returns list of all graph URIs in a space
   - `get_space_stats(space_id)` - Returns comprehensive statistics:
     - Total quad count
     - List of graph URIs
     - Per-graph statistics (quad count, unique subjects, unique predicates)
   - `get_unique_subjects(space_id, graph_uri, limit, offset)` - Paginated sorted unique subjects
   - `get_unique_predicates(space_id, graph_uri, limit, offset)` - Paginated sorted unique predicates
   - `count_quads(space_id, graph_uri=None)` - Count quads with optional graph filter
   - `get_data_quads(space_id, limit, offset, graph_uri=None)` - Paginated quads as tuples:
     ```python
     {
         'start_index': int,
         'end_index': int,
         'status': 'success' | 'error',
         'quads': [(graph, subject, predicate, object), ...]
     }
     ```

3. **Space Info Endpoint Enhancement** ✅ (in `FusekiPostgreSQLSpaceImpl`)
   - `get_space_info()` now **always** calls `get_space_stats()` and logs statistics
   - Space statistics logged on every call:
     ```
     📊 SPACE STATISTICS for {space_id}:
       Total quads: {count}
       Number of graphs: {count}
       Graph: {graph_uri}
         - Quads: {count}
         - Unique subjects: {count}
         - Unique predicates: {count}
     ```
   - When `enable_quad_logging: true`, additionally logs detailed quads:
     ```
     🔍 QUAD LOGGING ENABLED for space {space_id}
     📊 Starting quad logging - Total quads: {count}
     📄 Processing page {num} (offset {offset}, size {size})
     QUAD: G=<graph> S=<subject> P=<predicate> O=<object>
     ```

4. **Quad Logging Implementation** ✅ (in `FusekiPostgreSQLSpaceImpl`)
   - `_log_all_quads(space_id, page_size=100)` - Logs all quads with pagination
   - Uses dual backend coordinator to access PostgreSQL implementation
   - Pagination with configurable page size (default 100 quads per page)
   - Each quad logged on separate line with truncated URIs for readability
   - Summary statistics by graph

5. **Test Validation** ✅
   - Test script `test_realistic_organization_workflow.py` successfully validates:
     - SPARQL query results: 308 triples
     - PostgreSQL quad logging: 308 quads
     - Consistency check: `consistent: True, difference: 0`
     - Space statistics: 308 quads, 45 unique subjects, 14 unique predicates
   - All data sources verified identical
   - Dual backend (Fuseki + PostgreSQL) perfectly synchronized

**Architecture:**
- All methods use dual backend architecture via `self.dual_write_coordinator.postgresql_impl`
- Direct SQL queries on PostgreSQL primary data tables (`{space_id}_rdf_quad`, `{space_id}_term`)
- JOIN queries to resolve UUID-based storage to human-readable data
- Efficient pagination with LIMIT/OFFSET
- Proper error handling and structured return formats

### SPARQL Query Helper Implementation
Add a helper function to the realistic test script:

```python
async def query_graph_triples(client, space_id: str, graph_id: str) -> List[Dict]:
    """
    Query all triples in a specific graph using SPARQL endpoint.
    
    Returns list of triples with subject, predicate, object.
    """
    query = f"""
    SELECT ?s ?p ?o WHERE {{
        GRAPH <{graph_id}> {{
            ?s ?p ?o .
        }}
    }}
    ORDER BY ?s ?p ?o
    """
    # Execute SPARQL query via client endpoint
    # Return results as list of dicts
```

### Validation Logic
At each checkpoint:
1. **Execute SPARQL Query**: Get all triples in the test graph
2. **Trigger Quad Logging**: Call space info endpoint to log all quads
3. **Compare Results**: Analyze differences between SPARQL results and quad logs
4. **Report Discrepancies**: Log any missing or unexpected triples/quads
5. **Assert Consistency**: Fail test if critical discrepancies are found

### Expected Benefits
- **Debug Data Issues**: Identify when data is not being stored correctly
- **Validate Updates**: Confirm slot updates are persisted properly
- **Catch Regressions**: Detect when changes break data storage/retrieval
- **Performance Analysis**: Track quad count growth through operations
- **Integration Validation**: Ensure SPARQL queries match actual stored data

### Implementation Files
1. **Config**: Add `enable_quad_logging` parameter to config schema
2. **Space Service**: Implement quad logging in space info method
3. **Test Script**: Add SPARQL query helper and validation checkpoints to `test_realistic_organization_workflow.py`
4. **Documentation**: Update this planning document with implementation details

This comprehensive plan ensures the client implementation matches the robust server functionality and provides reliable, well-tested KGFrames operations for production use.

## Architecture

### Frame Data Model
```
KGEntity (Root)
├── hasKGGraphURI: entity_uri (grouping URI for fast queries)
├── Connected to KGFrames via Edge_hasEntityKGFrame
│
KGFrame (Child of Entity)
├── hasKGGraphURI: entity_uri (entity-level grouping)
├── hasFrameGraphURI: frame_uri (frame-level grouping)
├── Connected to KGSlots via Edge_hasFrameKGSlot
├── Connected to other KGFrames via Edge_hasKGFrame (hierarchical)
│
KGSlot (Child of Frame)
├── hasKGGraphURI: entity_uri (entity-level grouping)
├── Contains actual data values
│
Connecting Edges:
├── Edge_hasEntityKGFrame (Entity → Frame)
├── Edge_hasFrameKGSlot (Frame → Slot)
├── Edge_hasKGFrame (Frame → Frame, hierarchical)
└── hasKGGraphURI: entity_uri (for all edges)
```

### Frame Types and Relationships
- **KGFrame**: Base frame class for structured data containers
- **KGTextSlot**: Text-based data slots
- **KGIntegerSlot**: Integer-based data slots  
- **KGDateTimeSlot**: DateTime-based data slots
- **Edge_hasEntityKGFrame**: Links entities to their frames
- **Edge_hasKGFrame**: Links frames to other frames (hierarchical)
- **Edge_hasFrameKGSlot**: Links frames to their slots

## JSON-LD Request Model Validation Requirements

### Universal JSON-LD Request Model Design

**APPLIES TO ALL JSON-LD ENDPOINTS**: All endpoints that accept JSON-LD input must follow consistent patterns.

All JSON-LD endpoints must support two distinct JSON-LD input formats with proper validation:

#### 1. Single Object Operations (JsonLdObject)
**Use Case**: Updating or creating a single object (KGFrame, etc.)
**Format**: JSON-LD object with @id, @type, and properties at root level
**Validation**: 
- Must contain exactly one object
- Must have @id and @type properties
- Properties at root level (not in @graph array)

**Example** (KGFrame):
```json
{
  "@context": {...},
  "@id": "http://vital.ai/test/kgframe/PersonFrame_12345678",
  "@type": "http://vital.ai/ontology/haley-ai-kg#KGFrame",
  "name": "Person Frame",
  "kGFrameDescription": "Represents a person frame"
}
```

#### 2. Multiple Object Operations (JsonLdDocument)
**Use Case**: Creating or updating multiple objects in batch (KGFrames, etc.)
**Format**: JSON-LD document with @graph array containing multiple objects
**Validation**:
- Must contain @graph array with one or more objects
- Each object in @graph must have @id and @type
- Should reject if used for single object operations
- Used for: Batch object creation, bulk updates, complex object graphs

**Example** (Multiple KGFrames):
```json
{
  "@context": {...},
  "@graph": [
    {
      "@id": "http://vital.ai/test/kgframe/PersonFrame_12345678",
      "@type": "http://vital.ai/ontology/haley-ai-kg#KGFrame",
      "name": "Person Frame"
    },
    {
      "@id": "http://vital.ai/test/kgframe/OrganizationFrame_87654321",
      "@type": "http://vital.ai/ontology/haley-ai-kg#KGFrame",
      "name": "Organization Frame"
    }
  ]
}
```

**Example** (Frame with Slots):
```json
{
  "@context": {...},
  "@graph": [
    {
      "@id": "http://example.org/frame123",
      "@type": "http://vital.ai/ontology/haley-ai-kg#KGFrame",
      "name": "Person Frame"
    },
    {
      "@id": "http://example.org/person123_profile",
      "@type": "http://vital.ai/ontology/haley-ai-kg#KGFrame",
      "name": "Profile Frame"
    },
    {
      "@id": "http://example.org/person123_profile_age",
      "@type": "http://vital.ai/ontology/haley-ai-kg#KGIntegerSlot",
      "integerValue": 30
    }
  ]
}
```

#### 3. Request Model Validation Logic

**Applicable Endpoint Methods**:
- **KGFrames**: `POST /kgframes`, `PUT /kgframes`, `DELETE /kgframes`
- **KGSlots**: `POST /kgslots`, `PUT /kgslots`, `DELETE /kgslots`
- **KGRelations**: `POST /kgrelations`, `PUT /kgrelations`, `DELETE /kgrelations`
- **All other JSON-LD endpoints**: Accept both JsonLdObject and JsonLdDocument

**Validation Rules**:
1. **Single Object Validation**: If request contains root-level @id/@type, validate as JsonLdObject
2. **Multiple Object Validation**: If request contains @graph array, validate as JsonLdDocument
3. **Error Handling**: Return HTTP 400 with descriptive error if:
   - JsonLdDocument used where single object expected
   - JsonLdObject used where multiple objects expected
   - Missing required fields (@id, @type)
   - Invalid JSON-LD structure

**Implementation Requirements**:
- Use Pydantic Union types to support both models
- Add custom validation logic to enforce single vs multiple object rules
- Provide clear error messages for validation failures
- Support automatic detection of input format based on structure

## Universal Request and Response Models

### Request Models with Union Support (Applied to All Endpoints)

**Pattern to be applied to all JSON-LD endpoints (KGFrames, KGSlots, KGRelations)**

#### 1. KGFrameRequest (Union Model Example)
```python
from typing import Union
from pydantic import BaseModel, Field, validator
from vitalgraph.model.jsonld_model import JsonLdObject, JsonLdDocument

class KGFrameRequest(BaseModel):
    """
    Universal request model supporting both single and multiple KGFrame operations.
    Uses Union to accept either JsonLdObject or JsonLdDocument.
    """
    space_id: str = Field(..., description="Space identifier")
    graph_id: str = Field(..., description="Graph identifier")
    data: Union[JsonLdObject, JsonLdDocument] = Field(
        ..., 
        description="KGFrame data - either single object or document with @graph array"
    )
    
    @validator('data')
    def validate_kgframe_data(cls, v):
        """Validate that data contains only KGFrame objects."""
        if isinstance(v, JsonLdObject):
            # Single object validation
            if not v.type or 'KGFrame' not in str(v.type):
                raise ValueError("Single object must be a KGFrame")
        elif isinstance(v, JsonLdDocument):
            # Multiple objects validation
            if not v.graph or len(v.graph) == 0:
                raise ValueError("Document must contain at least one KGFrame")
            for obj in v.graph:
                if not obj.get('@type') or 'KGFrame' not in str(obj.get('@type')):
                    raise ValueError("All objects in document must be KGFrames")
        return v

# Specific operation request models
class KGFrameCreateRequest(KGFrameRequest):
    """Request model for creating KGFrames (POST /kgframes)."""
    pass

class KGFrameUpdateRequest(KGFrameRequest):
    """Request model for updating KGFrames (PUT /kgframes)."""
    pass

class KGFrameBatchDeleteRequest(BaseModel):
    """Request model for batch deleting KGFrames (DELETE /kgframes with body)."""
    space_id: str = Field(..., description="Space identifier")
    graph_id: str = Field(..., description="Graph identifier")
    data: Union[JsonLdDocument, List[str]] = Field(
        ..., 
        description="KGFrame URIs to delete - either JsonLdDocument or list of URIs"
    )
```

#### 2. Response Models with Union Support
```python
class KGFrameResponse(BaseModel):
    """Base response model for KGFrame operations."""
    success: bool = Field(..., description="Operation success status")
    message: str = Field(..., description="Human-readable status message")
    data: Optional[Union[JsonLdObject, JsonLdDocument]] = Field(
        None, 
        description="Response data - single object or document with @graph array"
    )
    errors: Optional[List[str]] = Field(None, description="Error messages if any")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")

class KGFrameCreateResponse(KGFrameResponse):
    """Response model for KGFrame creation operations."""
    created_count: Optional[int] = Field(None, description="Number of KGFrames created")
    created_uris: Optional[List[str]] = Field(None, description="URIs of created KGFrames")

class KGFrameUpdateResponse(KGFrameResponse):
    """Response model for KGFrame update operations."""
    updated_count: Optional[int] = Field(None, description="Number of KGFrames updated")
    updated_uris: Optional[List[str]] = Field(None, description="URIs of updated KGFrames")

class KGFrameDeleteResponse(KGFrameResponse):
    """Response model for KGFrame deletion operations."""
    deleted_count: Optional[int] = Field(None, description="Number of KGFrames deleted")
    deleted_uris: Optional[List[str]] = Field(None, description="URIs of deleted KGFrames")

class KGFrameListResponse(BaseModel):
    """Response model for KGFrame listing operations."""
    success: bool = Field(..., description="Operation success status")
    data: Optional[JsonLdDocument] = Field(None, description="KGFrames as JSON-LD document")
    pagination: Optional[Dict[str, Any]] = Field(None, description="Pagination metadata")
    total_count: Optional[int] = Field(None, description="Total number of KGFrames")
    page_size: int = Field(..., description="Number of items per page")
    offset: int = Field(..., description="Current page offset")
```

## API Endpoints

### Frame Operations
1. **GET /kgframes** - Get/List Frames
   - Query parameters: `space_id`, `graph_id`, `entity_uri`, `parent_uri`, `frame_type`, `page_size`, `offset`
   - Returns: `FramesResponse` with JSON-LD document/object
   - Supports entity-associated frames and standalone frames

2. **POST /kgframes** - Create Or Update Frames
   - Request body: `JsonLdRequest` (discriminated union of JsonLdObject or JsonLdDocument)
   - Query parameters: `space_id`, `graph_id`, `operation_mode` (CREATE/UPDATE/UPSERT), `parent_uri`, `entity_uri`
   - Returns: `FrameCreateResponse`, `FrameUpdateResponse`, or `FrameUpsertResponse`
   - **Discriminated Union**: Automatically handles single frames (JsonLdObject) or multiple frames (JsonLdDocument)
   - Supports hierarchical frame creation with parent relationships

3. **DELETE /kgframes** - Delete Frames
   - Request body: `FrameDeleteRequest` with list of frame URIs
   - Returns: `FrameDeleteResponse`
   - Supports cascade deletion of frame hierarchies

### JSON-LD Request Handling

**Discriminated Union Pattern**:
```python
JsonLdRequest = Annotated[
    Union[
        Annotated[JsonLdObject, Tag("object")],
        Annotated[JsonLdDocument, Tag("document")]
    ],
    Discriminator(get_jsonld_discriminator)
]
```

**Discriminator Logic**:
- Checks for `@graph` field → JsonLdDocument (multiple frames)
- Checks for `@id` field → JsonLdObject (single frame)
- Explicit `jsonld_type` field can override detection

**Benefits**:
- FastAPI automatically routes to correct model based on content
- Single endpoint handles both single and batch frame operations
- Type-safe validation for both formats
- Consistent with KGEntities, KGRelations, KGTypes, Objects, and Triples endpoints

**Usage Pattern**:
- Single frame creation: Send JsonLdObject with `@id` and frame properties
- Batch frame operations: Send JsonLdDocument with `@graph` array containing multiple frames
- Hierarchical frames: Include parent-child relationships in frame properties
- Entity-associated frames: Provide `entity_uri` parameter for entity graph grouping

## Enhanced Frame Graph Retrieval

### Frame Graph Retrieval Implementation

**Endpoint Enhancement**: `GET /api/graphs/kgentities/{entity_uri}/frames`
**New Parameter**: `frame_uris: List[str]` (optional)

**Response Format**:
```python
class FrameGraphsResponse(BaseModel):
    frame_graphs: Dict[str, Union[JsonLdDocument, Dict]] = Field(
        ..., 
        description="Map of frame URI to complete frame graph (JsonLdDocument) or empty dict"
    )
```

**Example Response**:
```json
{
    "frame_graphs": {
        "frame_uri_1": JsonLdDocument(...),  # Complete frame graph
        "frame_uri_2": JsonLdDocument(...),  # Complete frame graph  
        "frame_uri_3": {},                   # Empty if no graph data
    }
}
```

**Error Handling**:
- Cross-entity frame access → 400 Bad Request
- Non-existent frame URI → Empty JsonLD document in response
- SPARQL query errors → 500 Internal Server Error

### Query Execution Flow

#### Step 1: Input Validation
```python
if frame_uris:
    # Validate frame URI format
    # Check frame_uris is not empty list
```

#### Step 2: Phase 1 Query - Ownership Validation
```python
ownership_query = build_frame_ownership_query(entity_uri, frame_uris)
ownership_results = await backend.execute_sparql_query(space_id, ownership_query)
validated_frame_uris = extract_validated_frames(ownership_results)

if len(validated_frame_uris) != len(frame_uris):
    # Some frames don't belong to entity
    raise HTTPException(400, "One or more frame URIs do not belong to the specified entity")
```

#### Step 3: Phase 2 Queries - Frame Graph Retrieval
```python
frame_graphs = {}
for frame_uri in validated_frame_uris:
    graph_query = build_frame_graph_query(frame_uri)
    graph_results = await backend.execute_sparql_query(space_id, graph_query)
    
    if graph_results:
        graph_objects = convert_sparql_to_vitalsigns(graph_results)
        frame_graphs[frame_uri] = convert_to_jsonld_document(graph_objects)
    else:
        frame_graphs[frame_uri] = {}  # Empty document
```

#### Step 4: Response Construction
```python
return FrameGraphsResponse(frame_graphs=frame_graphs)
```

### Test Integration Plan

#### Phase E1: Frame Graph Retrieval Test
**Method**: `test_frame_graph_retrieval()`
**Test Logic**:
```python
# Get frame URIs from creation result
frame_uris = [frame.URI for frame in creation_result.created_frames]

# Call enhanced endpoint
response = await self.endpoint.get_entity_frames(
    entity_uri=entity_uri,
    frame_uris=frame_uris
)

# Validate response structure
assert len(response.frame_graphs) == len(frame_uris)
for frame_uri in frame_uris:
    assert frame_uri in response.frame_graphs
    frame_graph = response.frame_graphs[frame_uri]
    # Validate frame graph contains expected objects
```

#### Phase E2: Entity Graph Retrieval Test
**Method**: `test_entity_graph_with_frames()`
**Approach**: Use existing entity retrieval with `include_entity_graph=True`

**Implementation**:
```python
# Call entity retrieval with full graph
response = await self.endpoint._get_entity_by_uri(
    space_id=space_id,
    graph_id=graph_id,
    uri=entity_uri,
    include_entity_graph=True,  # Get complete graph
    current_user=current_user
)
```

**Validation**:
- Entity object is present
- Frame objects are included in entity graph
- Edge_hasEntityKGFrame relationships connect entity to frames
- Complete frame structure (frames + slots + edges) is present
- Dual grouping URIs are correctly assigned

#### Enhanced Test Sequence
```
Phase 1.4: Frame Creation Tests  
├── 1. test_frame_creation_with_processor()
├── 2. test_dual_grouping_uri_assignment()
├── 3. test_frame_graph_retrieval()
└── 4. test_entity_graph_with_frames()
```

## Frame UPDATE/UPSERT Implementation Plan

### Overview: PostgreSQL-First Atomic Operations

Based on investigation of existing KGEntity UPDATE patterns, the frame UPDATE/UPSERT implementation will use a **PostgreSQL-first dual-write coordination** approach with a new `update_quads` function that handles atomic delete+insert operations.

### Key Architecture Decision: Simplified Transaction Management

**Critical Insight**: PostgreSQL transaction provides the atomicity guarantee. Once PostgreSQL transaction commits successfully, Fuseki operations can be performed separately without complex transaction coordination.

**Benefits**:
- **Single Transaction Scope**: Only PostgreSQL needs transaction management

### Atomic `update_quads` Function Implementation

#### Core Function Signature
```python
async def update_quads(self, space_id: str, graph_id: str, 
                      delete_quads: List[Tuple], insert_quads: List[Tuple]) -> bool:
    """
    Atomically update quads by deleting old ones and inserting new ones.
    
    Args:
        space_id: Space identifier
        graph_id: Graph identifier
        delete_quads: List of quads to delete
        insert_quads: List of quads to insert
        
    Returns:
        bool: True if operation succeeded, False otherwise
        
    Implementation:
        1. Begin PostgreSQL transaction
        2. Delete specified quads
        3. Insert new quads
        4. Commit transaction (atomic point)
        5. Update Fuseki (separate operation)
    """
```

#### PostgreSQL Transaction Implementation
```python
async def update_quads(self, space_id: str, graph_id: str, 
                      delete_quads: List[Tuple], insert_quads: List[Tuple]) -> bool:
    
    async with self.get_connection() as conn:
        async with conn.transaction():
            try:
                # Step 1: Delete old quads
                if delete_quads:
                    delete_success = await self._delete_quads_batch(
                        conn, space_id, graph_id, delete_quads
                    )
                    if not delete_success:
                        return False
                
                # Step 2: Insert new quads
                if insert_quads:
                    insert_success = await self._insert_quads_batch(
                        conn, space_id, graph_id, insert_quads
                    )
                    if not insert_success:
                        return False
                
                # Transaction commits automatically here
                
            except Exception as e:
                self.logger.error(f"PostgreSQL update_quads failed: {e}")
                # Transaction rolls back automatically
                return False
    
    # Step 3: Update Fuseki (separate from transaction)
    try:
        fuseki_success = await self._update_fuseki_quads(
            space_id, graph_id, delete_quads, insert_quads
        )
        if not fuseki_success:
            self.logger.warning("Fuseki sync failed, but PostgreSQL committed")
            # Could trigger async resync here
        
        return True
        
    except Exception as e:
        self.logger.error(f"Fuseki update failed: {e}")
        return True  # PostgreSQL succeeded, so operation is valid
```

### Frame UPDATE Operation Flow

#### Step 1: Frame Identification and Validation
```python
async def update_kgframes(self, space_id: str, graph_id: str, 
                         frame_data: JsonLdDocument, current_user: Dict) -> FrameUpdateResponse:
    
    # Extract frame URIs from input data
    frame_uris = extract_frame_uris(frame_data)
    
    # Validate frame ownership (prevent cross-entity updates)
    ownership_valid = await self._validate_frame_ownership(space_id, frame_uris, current_user)
    if not ownership_valid:
        raise HTTPException(403, "Unauthorized frame access")
```

#### Step 2: Current State Retrieval
```python
    # Get current quads for all frames being updated
    current_quads = await self._get_frame_quads(space_id, graph_id, frame_uris)
    
    # Convert new frame data to quads
    new_quads = await self._convert_frames_to_quads(frame_data, space_id, graph_id)
```

#### Step 3: Atomic Update Execution
```python
    # Execute atomic update
    update_success = await self.db_impl.update_quads(
        space_id=space_id,
        graph_id=graph_id,
        delete_quads=current_quads,
        insert_quads=new_quads
    )
    
    if update_success:
        return FrameUpdateResponse(
            success=True,
            message="Frames updated successfully",
            updated_count=len(frame_uris),
            updated_uris=frame_uris
        )
    else:
        raise HTTPException(500, "Frame update failed")
```

### UPSERT Operation Implementation

#### UPSERT Logic Flow
```python
async def upsert_kgframes(self, space_id: str, graph_id: str, 
                         frame_data: JsonLdDocument, current_user: Dict) -> FrameUpsertResponse:
    
    # Extract frame URIs
    frame_uris = extract_frame_uris(frame_data)
    
    # Check which frames exist
    existing_frames = await self._get_existing_frame_uris(space_id, frame_uris)
    new_frames = [uri for uri in frame_uris if uri not in existing_frames]
    
    # Split data into update vs create
    update_data = filter_frames_by_uris(frame_data, existing_frames)
    create_data = filter_frames_by_uris(frame_data, new_frames)
    
    results = {
        'updated_count': 0,
        'created_count': 0,
        'updated_uris': [],
        'created_uris': []
    }
    
    # Update existing frames
    if update_data:
        update_result = await self.update_kgframes(space_id, graph_id, update_data, current_user)
        results['updated_count'] = update_result.updated_count
        results['updated_uris'] = update_result.updated_uris
    
    # Create new frames
    if create_data:
        create_result = await self.create_kgframes(space_id, graph_id, create_data, current_user)
        results['created_count'] = create_result.created_count
        results['created_uris'] = create_result.created_uris
    
    return FrameUpsertResponse(**results)
```

### Success Criteria

#### Functional Requirements
- ✅ UPDATE operations atomically replace frame data
- ✅ UPSERT operations handle mixed create/update scenarios
- ✅ PostgreSQL transaction ensures atomicity
- ✅ Fuseki synchronization maintains query performance
- ✅ Proper error handling and rollback behavior
- ✅ Frame ownership validation prevents unauthorized access

#### Performance Requirements
- ✅ Single transaction for multiple frame updates
- ✅ Batch quad operations for efficiency
- ✅ Minimal Fuseki synchronization overhead
- ✅ Graceful handling of large frame datasets

This implementation provides robust, atomic frame UPDATE/UPSERT operations with clear transaction boundaries and proper error handling.

## Frame Deletion Issues Resolution

### Major Milestone: Frame Deletion Issues Completely Resolved

After extensive debugging and systematic problem-solving, all frame deletion issues have been successfully resolved, resulting in **100% test success rate** for the comprehensive KGFrames functionality.

### Key Issues Identified and Fixed

#### Issue: Frame Ownership Validation Failure
**Problem**: Frame deletion processor could not find entity-frame relationships during ownership validation, returning empty results and preventing frame deletion.

**Root Cause**: The ownership validation SPARQL query used incorrect property URIs that didn't match VitalSigns' actual property mappings:
- **Expected**: `edgeSource` and `edgeDestination`  
- **Actual VitalSigns properties**: `hasEdgeSource` and `hasEdgeDestination`

**Debug Process**:
1. Created debug script to examine actual VitalSigns triple generation
2. Discovered VitalSigns uses `http://vital.ai/ontology/vital-core#hasEdgeSource` and `http://vital.ai/ontology/vital-core#hasEdgeDestination`
3. Updated ownership validation query to match actual property URIs

**Solution Applied**:
```python
# Fixed in: /vitalgraph/kg_impl/kgentity_frame_delete_impl.py
# Updated ownership validation query to use correct VitalSigns property URIs
ownership_query = f"""
SELECT DISTINCT ?frame_uri WHERE {{
    GRAPH <{graph_id}> {{
        ?edge_uri <http://vital.ai/ontology/vital-core#hasEdgeSource> <{entity_uri}> .
        ?edge_uri <http://vital.ai/ontology/vital-core#hasEdgeDestination> ?frame_uri .
        ?edge_uri a <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .
        FILTER(?frame_uri IN ({frame_uris_filter}))
    }}
}}
"""
```

### Expected Results

#### Phase E1 - Frame Graph Retrieval
```
KGFrames Response (with frame_uris parameter):
├── KGFrame objects (specified by frame_uris)
├── KGSlot objects (associated with frames)
├── Edge_hasKGSlot objects (frame → slot relationships)
└── Complete frame graph structure
```

#### Phase E2 - Entity Graph Retrieval
```
Entity Graph Response (include_entity_graph=True):
├── KGEntity (main entity)
├── Edge_hasEntityKGFrame (entity → frame relationships)
├── KGFrame objects (all frames linked to entity)
├── KGSlot objects (all slots in frame graphs)
└── Edge_hasKGSlot objects (frame → slot relationships)
```

This enhancement provides secure, efficient, and well-structured frame graph retrieval with proper validation and comprehensive testing coverage, completing the frame creation validation infrastructure.

### Detailed UPDATE/UPSERT Mode Implementation

#### UPDATE Mode Implementation
```python
async def update_frames_atomic(self, space_id: str, graph_id: str, 
                              entity_uri: str, frame_objects: List[GraphObject]) -> FrameCreateResponse:
    """UPDATE frames using PostgreSQL-first atomic update_quads."""
    
    # Step 1: Validate frame ownership (prevent unauthorized updates)
    frame_uris = self._extract_frame_uris(frame_objects)
    delete_processor = KGEntityFrameDeleteProcessor(self.backend, self.logger)
    validated_uris = await delete_processor.validate_frame_ownership(
        space_id, graph_id, entity_uri, frame_uris
    )
    
    if len(validated_uris) != len(frame_uris):
        missing_frames = set(frame_uris) - set(validated_uris)
        raise HTTPException(status_code=404, detail=f"UPDATE failed: Frames not found: {missing_frames}")
    
    # Step 2: Build quad sets for atomic replacement
    delete_quads = await self._build_frame_delete_quads(space_id, graph_id, frame_uris)
    insert_quads = self._build_frame_insert_quads(graph_id, frame_objects)
    
    # Step 3: Execute atomic update (PostgreSQL transaction + Fuseki sync)
    success = await self.backend.update_quads(space_id, graph_id, delete_quads, insert_quads)
    
    if not success:
        raise HTTPException(status_code=500, detail="UPDATE failed: Atomic frame replacement failed")
    
    return FrameCreateResponse(
        success=True,
        created_uris=frame_uris,
        message=f"Successfully updated {len(frame_uris)} frames atomically"
    )
```

#### UPSERT Mode Implementation
```python
async def upsert_frames_atomic(self, space_id: str, graph_id: str,
                              entity_uri: str, frame_objects: List[GraphObject]) -> FrameCreateResponse:
    """UPSERT frames using conditional atomic update_quads function."""
    
    # Step 1: Extract frame URIs
    frame_uris = self._extract_frame_uris(frame_objects)
    
    # Step 2: Identify existing frames (no failure for missing ones)
    delete_processor = KGEntityFrameDeleteProcessor(self.backend, self.logger)
    existing_frame_uris = await delete_processor.validate_frame_ownership(
        space_id, graph_id, entity_uri, frame_uris
    )
    
    # Step 3: Build delete quads (only for existing frames)
    delete_quads = []
    if existing_frame_uris:
        delete_quads = await self._build_frame_delete_quads(space_id, graph_id, existing_frame_uris)
    
    # Step 4: Build insert quads (for all frames - existing and new)
    insert_quads = self._build_frame_insert_quads(graph_id, frame_objects)
    
    # Step 5: Execute atomic update
    success = await self.backend.update_quads(space_id, graph_id, delete_quads, insert_quads)
    
    if not success:
        raise HTTPException(status_code=500, detail="UPSERT failed: Atomic frame operation failed")
    
    return FrameCreateResponse(
        success=True,
        created_uris=frame_uris,
        message=f"Successfully upserted {len(frame_uris)} frames atomically"
    )
```

### Helper Functions for Quad Building

#### Frame Delete Quads Builder
```python
async def _build_frame_delete_quads(self, space_id: str, graph_id: str, 
                                   frame_uris: List[str]) -> List[Tuple]:
    """Build delete quads for complete frame graphs using frameGraphURI grouping."""
    delete_quads = []
    
    for frame_uri in frame_uris:
        # Query to find all subjects belonging to this frame graph
        query = f"""
        SELECT ?s ?p ?o WHERE {{
            GRAPH <{graph_id}> {{
                ?s <http://vital.ai/ontology/haley-ai-kg#frameGraphURI> <{frame_uri}> .
                ?s ?p ?o .
            }}
        }}
        """
        
        results = await self.backend.execute_sparql_query(space_id, query)
        
        for result in results:
            subject = result['s']['value']
            predicate = result['p']['value'] 
            obj = result['o']['value']
            delete_quads.append((subject, predicate, obj, graph_id))
    
    return delete_quads
```

#### Frame Insert Quads Builder
```python
def _build_frame_insert_quads(self, graph_id: str, frame_objects: List[GraphObject]) -> List[Tuple]:
    """Build insert quads from frame GraphObjects."""
    insert_quads = []
    
    for frame_obj in frame_objects:
        # Convert GraphObject to triples
        triples = frame_obj.to_triples()
        
        # Add graph context to create quads
        for subject, predicate, obj in triples:
            insert_quads.append((subject, predicate, obj, graph_id))
    
    return insert_quads
```

## Test Architecture Requirements

### Two-Tier Testing Strategy

The KGFrames endpoint testing must follow a clear separation of concerns with two distinct test categories:

#### 1. Standalone Frame/Slot Tests (Independent of Entities)
**Purpose**: Test frame and slot functionality in isolation
**Scope**: 
- Frame CRUD operations without entity dependencies
- Slot CRUD operations without entity dependencies  
- Frame-slot relationships
- Hierarchical frame structures
- JSON-LD validation and processing
- Backend storage and retrieval

**Test Cases**:
- `case_frame_standalone_create.py` - Create frames without entities
- `case_frame_standalone_update.py` - Update standalone frames
- `case_frame_standalone_delete.py` - Delete standalone frames
- `case_frame_standalone_hierarchical.py` - Hierarchical frame relationships
- `case_slot_standalone_create.py` - Create slots for standalone frames
- `case_slot_standalone_update.py` - Update slots independently
- `case_slot_standalone_delete.py` - Delete slots independently

**Key Requirements**:
- No dependency on KGEntities endpoint
- No entity creation or management
- Focus purely on frame/slot data structures
- Test frame-to-frame relationships (hierarchical)
- Test slot-to-frame relationships
- Validate JSON-LD processing for frames/slots

#### 2. Entity-Associated Frame/Slot Tests (Using KGEntities Endpoint)
**Purpose**: Test frame and slot functionality in the context of entities
**Scope**:
- Entity creation via KGEntities endpoint
- Frame attachment to existing entities
- Slot attachment to entity-associated frames
- Entity-frame-slot graph relationships
- Cross-endpoint integration testing

**Test Cases**:
- `case_entity_frame_integration.py` - Create entity, then attach frames
- `case_entity_frame_lifecycle.py` - Full entity-frame lifecycle management
- `case_entity_slot_integration.py` - Entity-frame-slot integration
- `case_entity_frame_queries.py` - Query frames by entity relationships

**Key Requirements**:
- Use KGEntities endpoint to create entities first
- Test KGFrames endpoint operations on entity-associated frames
- Validate entity-frame relationship integrity
- Test cross-endpoint data consistency
- Ensure proper grouping URI management across endpoints

### Test Data Strategy

#### Standalone Tests Data
```python
def create_standalone_frame_data():
    """Create frame test data without entity dependencies."""
    frames = []
    # Create KGFrame objects with standalone URIs
    # No entity relationships required
    # Focus on frame properties and structure
    return frames

def create_standalone_slot_data(frame_uri: str):
    """Create slot test data for standalone frames."""
    slots = []
    # Create KGSlot objects linked to frame_uri
    # No entity context required
    return slots
```

#### Entity-Associated Tests Data
```python
async def create_entity_via_kgentities_endpoint(endpoint, space_id, graph_id):
    """Create entity using KGEntities endpoint for integration tests."""
    # Use KGEntities endpoint to create entity
    # Return entity URI for frame attachment
    pass

async def create_frames_for_entity(kgframes_endpoint, entity_uri, space_id, graph_id):
    """Create frames associated with existing entity."""
    # Use KGFrames endpoint to create frames
    # Link frames to entity_uri
    pass
```

### Test Orchestrator Updates

The main test orchestrator should run both test categories:

```python
class KGFramesEndpointTester:
    async def run_all_tests(self):
        """Run comprehensive KGFrames testing."""
        
        # Category 1: Standalone Tests
        standalone_results = await self.run_standalone_tests()
        
        # Category 2: Entity-Associated Tests  
        integration_results = await self.run_integration_tests()
        
        return {
            'standalone': standalone_results,
            'integration': integration_results
        }
    
    async def run_standalone_tests(self):
        """Run tests that don't require entities."""
        # Test frame operations independently
        # Test slot operations independently
        # Test frame-slot relationships
        pass
    
    async def run_integration_tests(self):
        """Run tests that integrate with KGEntities."""
        # Create entities via KGEntities endpoint
        # Test frame operations on entities
        # Test cross-endpoint consistency
        pass
```

### Endpoint Responsibilities Clarification

#### KGFrames Endpoint Responsibilities
- Frame CRUD operations (standalone and entity-associated)
- Slot CRUD operations (standalone and frame-associated)
- Frame-slot relationship management
- Hierarchical frame structures
- JSON-LD processing for frames/slots
- **NOT RESPONSIBLE FOR**: Entity creation or management

#### KGEntities Endpoint Responsibilities  
- Entity CRUD operations
- Entity-frame relationship management (via existing functionality)
- Entity graph retrieval including associated frames
- **NOT RESPONSIBLE FOR**: Direct frame/slot manipulation

### Implementation Priority

1. **Phase 1**: Remove inappropriate `_create_entities` method from KGFrames endpoint
2. **Phase 2**: Create standalone frame/slot test cases
3. **Phase 3**: Create entity-associated integration test cases
4. **Phase 4**: Update test orchestrator to run both categories
5. **Phase 5**: Validate complete test coverage

This architecture ensures proper separation of concerns while providing comprehensive test coverage for both standalone and integrated use cases.

## Implementation Phases Following KGEntities Success

### Phase F1: Local Test Script Implementation 🚨 **HIGHEST PRIORITY**
- **Status**: 📋 PLANNED - Starting Point for Implementation
- **Dependencies**: Existing KGEntities local test structure
- **Primary Focus**: `/Users/hadfield/Local/vital-git/vital-graph/test_scripts/fuseki_postgresql/test_kgframes_endpoint_fuseki_postgresql.py`
- **Test Cases Directory**: `/Users/hadfield/Local/vital-git/vital-graph/test_script_kg_impl/kgframes/`
- **Pattern Source**: `/Users/hadfield/Local/vital-git/vital-graph/test_script_kg_impl/kgentities/` (12 existing test cases)
- **Tasks**:
  - **CREATE**: Local KGFrames test cases in `/test_script_kg_impl/kgframes/` directory
  - **IMPLEMENT**: Direct backend testing with fuseki_postgresql integration
  - **FOLLOW**: KGEntities local test pattern from `/test_script_kg_impl/kgentities/`
  - **LEVERAGE**: Existing frame processors through direct backend calls

### Phase F2: Frame Operations via Existing Processors ✅ **HIGH PRIORITY**
- **Status**: ✅ MOSTLY COMPLETE (existing processors already working)
- **Dependencies**: Phase F1 (Client Test Framework)
- **Tasks**:
  - **REUSE**: `KGEntityFrameCreateProcessor` - Already working with 100% test success ✅
  - **REUSE**: `KGEntityFrameDeleteProcessor` - Already working with 100% test success ✅
  - **REUSE**: `KGEntityFrameDiscoveryProcessor` - Already working with 100% test success ✅
  - **REUSE**: `KGEntityFrameUpdateProcessor` - Already working with 100% test success ✅
  - **REUSE**: `KGEntityHierarchicalFrameProcessor` - Already working with 100% test success ✅
  - **VALIDATE**: Through client test framework implementation

### Phase F3: Slot Processors Implementation ✅ **MEDIUM PRIORITY**
- **Status**: 📋 PLANNED
- **Dependencies**: Phase F1, F2
- **Tasks**:
  - **CREATE**: `KGSlotCreateProcessor` following `KGEntityCreateProcessor` pattern
  - **CREATE**: `KGSlotDeleteProcessor` following `KGEntityDeleteProcessor` pattern
  - **CREATE**: `KGSlotGetProcessor` following `KGEntityGetProcessor` pattern
  - **CREATE**: `KGSlotListProcessor` following `KGEntityListProcessor` pattern
  - **CREATE**: `KGSlotUpdateProcessor` following `KGEntityUpdateProcessor` pattern
  - **CREATE**: `KGSlotQueryProcessor` using existing `KGSparqlQueryProcessor`
  - **VALIDATE**: Through expanded client test framework

### Phase F4: Comprehensive Testing ✅ **MEDIUM PRIORITY**
- **Status**: 📋 PLANNED
- **Dependencies**: Phase F3
- **Tasks**:
  - Create comprehensive test suite following KGEntities pattern
  - Implement all frame and slot test cases (10 test modules)
  - Achieve 100% test success rate following KGEntities achievement
  - Validate JSON serialization and VitalSigns integration
  - Create client test orchestrator following KGEntities pattern

### Phase F5: Advanced Features ✅ **LOW PRIORITY**
- **Status**: 📋 PLANNED
- **Dependencies**: Phase F4
- **Tasks**:
  - Implement hierarchical frame operations
  - Add frame-to-frame relationship support
  - Implement complex frame query operations
  - Add performance optimization features
  - Complete integration with entity operations

### Success Criteria Following KGEntities Achievement

**Functional Requirements**:
- ✅ All frame CRUD operations working with 100% test success
- ✅ All slot CRUD operations working with 100% test success
- ✅ Proper Pydantic response models (no HTTPException raises)
- ✅ VitalSigns native JSON-LD handling
- ✅ Comprehensive test suite with modular test cases
- ✅ Backend processor delegation pattern

**Performance Requirements**:
- Efficient SPARQL query generation using shared utilities
- Proper backend adapter integration
- JSON-LD processing optimization
- Scalable processor architecture

**Architecture Requirements**:
- Clean separation of concerns (endpoint vs processors)
- Reusable components across KG implementations
- Consistent error handling and logging
- Maintainable and testable code structure
- Following established KGEntities success patterns

**Testing Requirements**:
- 100% test success rate (following KGEntities achievement)
- Comprehensive test coverage for all operations
- JSON serialization validation
- VitalSigns integration testing
- Client-server compatibility validation
- ✅ JSON serialization validation
- ✅ VitalSigns integration testing
- ✅ Client-server compatibility validation

## Implementation Requirements Following KGEntities Pattern

### Planned KG Implementation Classes (Following KGEntities Success Pattern)

**Core Frame Processors** (leverage existing KGEntities frame implementation):
- **REUSE**: `KGEntityFrameCreateProcessor` - Frame creation operations (already exists and working)
- **REUSE**: `KGEntityFrameDeleteProcessor` - Frame deletion operations (already exists and working)
- **REUSE**: `KGEntityFrameDiscoveryProcessor` - Frame retrieval operations (already exists and working)
- **REUSE**: `KGEntityFrameUpdateProcessor` - Frame update operations (already exists and working)
- **REUSE**: `KGEntityHierarchicalFrameProcessor` - Hierarchical frame operations (already exists and working)
- **NEW**: `KGFrameQueryProcessor` - Frame query operations (new, but can leverage existing SPARQL utilities)

**Slot Processors** (to be created in `/vitalgraph/kg_impl/`):
- `KGSlotCreateProcessor` - Slot creation operations
- `KGSlotUpdateProcessor` - Slot update operations
- `KGSlotDeleteProcessor` - Slot deletion operations
- `KGSlotGetProcessor` - Slot retrieval operations
- `KGSlotListProcessor` - Slot listing operations
- `KGSlotQueryProcessor` - Slot query operations

**Existing Frame Implementation** (already complete in `/vitalgraph/kg_impl/`):
- `kgentity_frame_create_impl.py` - `KGEntityFrameCreateProcessor` - Complete frame creation with VitalSigns integration ✅
- `kgentity_frame_delete_impl.py` - `KGEntityFrameDeleteProcessor` - Complete frame deletion with ownership validation ✅
- `kgentity_frame_discovery_impl.py` - `KGEntityFrameDiscoveryProcessor` - Complete frame retrieval with SPARQL queries ✅
- `kgentity_frame_update_impl.py` - `KGEntityFrameUpdateProcessor` - Complete frame update operations ✅
- `kgentity_hierarchical_frame_impl.py` - `KGEntityHierarchicalFrameProcessor` - Complete hierarchical frame support ✅

**Shared Utilities** (ready for reuse from `/vitalgraph/kg_impl/`):
- `kg_sparql_utils.py` - `KGSparqlUtils` class - SPARQL utilities (already exists) ✅
- `kg_sparql_query.py` - `KGSparqlQueryProcessor` class - SPARQL query processor (already exists) ✅
- `kg_jsonld_utils.py` - `KGJsonLdUtils` class - JSON-LD utilities (already exists) ✅
- `kg_validation_utils.py` - `KGEntityValidator`, `ValidationResult` classes - Validation utilities (already exists) ✅
- `kg_backend_utils.py` - `KGBackendInterface`, `BackendOperationResult` classes - Backend abstraction (already exists) ✅
- `kg_graph_validation.py` - Graph validation utilities (already exists) ✅

**Entity Processor Templates** (patterns for slot processors in `/vitalgraph/kg_impl/`):
- `kgentity_create_impl.py` - `KGEntityCreateProcessor` (template for `KGSlotCreateProcessor`)
- `kgentity_delete_impl.py` - `KGEntityDeleteProcessor` (template for `KGSlotDeleteProcessor`)
- `kgentity_get_impl.py` - `KGEntityGetProcessor` (template for `KGSlotGetProcessor`)
- `kgentity_list_impl.py` - `KGEntityListProcessor` (template for `KGSlotListProcessor`)
- `kgentity_update_impl.py` - `KGEntityUpdateProcessor` (template for `KGSlotUpdateProcessor`)

**KGTypes Processor Patterns** (additional patterns in `/vitalgraph/kg_impl/`):
- `kgtypes_create_impl.py` - Additional creation patterns
- `kgtypes_delete_impl.py` - Additional deletion patterns
- `kgtypes_read_impl.py` - Additional read patterns
- `kgtypes_update_impl.py` - Additional update patterns

### Implementation Architecture Following KGEntities Success Pattern

**KGFrames Endpoint Structure** (direct delegation to existing processors):
```python
# /vitalgraph/endpoint/kgframes_endpoint.py
from ..kg_impl.kgentity_frame_create_impl import KGEntityFrameCreateProcessor
from ..kg_impl.kgentity_frame_delete_impl import KGEntityFrameDeleteProcessor
from ..kg_impl.kgentity_frame_discovery_impl import KGEntityFrameDiscoveryProcessor
from ..kg_impl.kgentity_frame_update_impl import KGEntityFrameUpdateProcessor
from ..kg_impl.kgentity_hierarchical_frame_impl import KGEntityHierarchicalFrameProcessor

class KGFramesEndpoint:
    # Core Frame Operations (direct delegation to existing processors)
    async def _list_frames(self) -> FramesResponse:
        processor = KGEntityFrameDiscoveryProcessor()
        return await processor.get_entity_frames(...)
        
    async def _get_frame_by_uri(self) -> JsonLdDocument:
        processor = KGEntityFrameDiscoveryProcessor()
        return await processor.get_individual_frame(...)
        
    async def _create_frames(self) -> FrameCreateResponse:
        processor = KGEntityFrameCreateProcessor()
        return await processor.create_entity_frame(...)
        
    async def _update_frames(self) -> FrameUpdateResponse:
        processor = KGEntityFrameUpdateProcessor()
        return await processor.update_entity_frames(...)
        
    async def _delete_frames(self) -> FrameDeleteResponse:
        processor = KGEntityFrameDeleteProcessor()
        return await processor.delete_entity_frames(...)
    
    # Slot Operations (new processors following existing patterns)
    async def _list_slots(self) -> SlotsResponse:
        processor = KGSlotListProcessor()  # New - follow KGEntityListProcessor pattern
        return await processor.list_slots(...)
        
    async def _create_slots(self) -> SlotCreateResponse:
        processor = KGSlotCreateProcessor()  # New - follow KGEntityCreateProcessor pattern
        return await processor.create_slots(...)
        
    async def _update_slots(self) -> SlotUpdateResponse:
        processor = KGSlotUpdateProcessor()  # New - follow KGEntityUpdateProcessor pattern
        return await processor.update_slots(...)
        
    async def _delete_slots(self) -> SlotDeleteResponse:
        processor = KGSlotDeleteProcessor()  # New - follow KGEntityDeleteProcessor pattern
        return await processor.delete_slots(...)
    
    # Query Operations (new processors using existing SPARQL utilities)
    async def _query_frames(self) -> FrameQueryResponse:
        processor = KGFrameQueryProcessor()  # New - use existing KGSparqlQueryProcessor
        return await processor.query_frames(...)
        
    async def _query_slots(self) -> SlotQueryResponse:
        processor = KGSlotQueryProcessor()  # New - use existing KGSparqlQueryProcessor
        return await processor.query_slots(...)
```

**Processor Integration Pattern** (following KGEntities success):
- All SPARQL operations delegate to dedicated processors
- All JSON-LD operations use shared utilities
- Consistent error handling and logging
- Backend adapter integration through processors

### Implementation Plan Following KGEntities Success

**Phase 1: Direct Delegation to Existing Processors** 🚨 **HIGH PRIORITY** (Immediate Implementation)
- **DELEGATE**: Import and use `KGEntityFrameCreateProcessor` from `kgentity_frame_create_impl.py` ✅
- **DELEGATE**: Import and use `KGEntityFrameDeleteProcessor` from `kgentity_frame_delete_impl.py` ✅
- **DELEGATE**: Import and use `KGEntityFrameDiscoveryProcessor` from `kgentity_frame_discovery_impl.py` ✅
- **DELEGATE**: Import and use `KGEntityFrameUpdateProcessor` from `kgentity_frame_update_impl.py` ✅
- **DELEGATE**: Import and use `KGEntityHierarchicalFrameProcessor` from `kgentity_hierarchical_frame_impl.py` ✅
- **IMMEDIATE BENEFIT**: Frame operations work instantly through delegation with 100% reliability

**Phase 2: New Slot Processors** 🚨 **HIGH PRIORITY** (Follow Existing Patterns)
- **CREATE**: `KGSlotCreateProcessor` following `KGEntityCreateProcessor` pattern from `kgentity_create_impl.py`
- **CREATE**: `KGSlotDeleteProcessor` following `KGEntityDeleteProcessor` pattern from `kgentity_delete_impl.py`
- **CREATE**: `KGSlotGetProcessor` following `KGEntityGetProcessor` pattern from `kgentity_get_impl.py`
- **CREATE**: `KGSlotListProcessor` following `KGEntityListProcessor` pattern from `kgentity_list_impl.py`
- **CREATE**: `KGSlotUpdateProcessor` following `KGEntityUpdateProcessor` pattern from `kgentity_update_impl.py`
- **CREATE**: `KGSlotQueryProcessor` using existing `KGSparqlQueryProcessor` from `kg_sparql_query.py`
- **REUSE INFRASTRUCTURE**: All processors use existing utilities (`KGSparqlUtils`, `KGJsonLdUtils`, `KGEntityValidator`, etc.)

**Phase 3: Endpoint Integration** 🚨 **MEDIUM PRIORITY** (Minimal Wrapper Implementation)
- **UPDATE**: `kgframes_endpoint.py` to import and delegate to existing frame processors
- **IMPLEMENT**: Simple wrapper methods that instantiate and call existing processors
- **REUSE**: Existing error handling patterns from KGEntities endpoint
- **REUSE**: Existing response models (`FrameCreateResponse`, `FrameDeleteResponse`, etc.)
- **LEVERAGE**: Existing HTTPException elimination patterns from KGEntities refactoring
- **MINIMAL CODE**: Only routing and delegation logic needed

**Phase 4: Comprehensive Testing** 🚨 **MEDIUM PRIORITY**
- Create comprehensive test suite following KGEntities pattern
- Implement all frame and slot test cases
- Achieve 100% test success rate
- Validate JSON serialization and VitalSigns integration

## Test Coverage

### Current Test Implementation Status

**Local Test Script**: 🔄 `/test_scripts/fuseki_postgresql/test_kgframes_endpoint_fuseki_postgresql.py` **IMPLEMENTATION STARTING POINT**
- **Current Status**: Empty file - needs complete implementation
- **Current Scope**: Direct backend testing with fuseki_postgresql integration
- **Uses**: Direct processor calls and backend validation
- **Priority**: Create comprehensive local test suite following KGEntities pattern
- **Target**: 100% test success rate matching KGEntities local tests
- **Implementation Timeline and Dependencies**

**Immediate Next Steps** (local test-driven approach):
1. **Create Local Test Framework** - Start with `/test_scripts/fuseki_postgresql/test_kgframes_endpoint_fuseki_postgresql.py`
2. **Create Local Test Cases** - Implement test cases in `/test_script_kg_impl/kgframes/` directory
3. **Leverage Existing Frame Processors** - Use existing processors through direct backend calls
4. **Implement Slot Processors** - Create new processors following existing patterns
5. **Achieve 100% Success** - Match KGEntities local test success rate through backend testing
6. **Secondary Client Testing** - Expand client test framework after local tests are complete

**Local Test Script**: ✅ `/test_scripts/fuseki_postgresql/test_kgframes_endpoint_fuseki_postgresql.py`
- Direct endpoint testing with backend integration
- SPARQL query validation and result processing

**Client Test Script**: ✅ `/vitalgraph_client_test/test_kgframes_endpoint.py` **SECONDARY PRIORITY**
- **Current Status**: Basic KGFrames endpoint testing with typed client methods
- **Current Scope**: Tests GET and LIST operations with existing test data
- **Uses**: FramesResponse models for type safety
- **Priority**: Secondary to local test implementation


**Mock Test Scripts**: ✅ Multiple mock test files in `/vitalgraph_mock_client_test/`
- `test_mock_client_kgframes.py`
- `test_mock_kgframes_endpoint.py`
- `test_mock_kgframes_integration.py`
- `test_mock_kgframes_vitalsigns.py`
- Status: Comprehensive mock testing complete

### Required Test Enhancements (Following KGEntities Pattern)

**Client Test Framework Implementation** (starting point in `/vitalgraph_client_test/kgframes/`):

**Phase F1 Priority - Local Test Cases to Create in `/test_script_kg_impl/kgframes/`:**
- **CREATE**: `case_frame_create.py` - Adapt existing `case_entity_frame_create.py` (54,608 bytes - comprehensive)
- **CREATE**: `case_frame_delete.py` - Adapt existing `case_entity_frame_delete.py` (28,464 bytes - comprehensive)
- **CREATE**: `case_frame_get.py` - Adapt existing `case_entity_frame_get.py` (13,766 bytes - comprehensive)
- **CREATE**: `case_frame_update.py` - Adapt existing `case_entity_frame_update.py` (19,277 bytes - comprehensive)
- **CREATE**: `case_frame_hierarchical.py` - Adapt existing `case_entity_frame_hierarchical.py` (39,626 bytes - comprehensive)

**Local Test Infrastructure:**
- **REUSE**: `case_utils.py` (6,181 bytes) - Common test utilities
- **INTEGRATE**: `test_orchestrator.py` (8,491 bytes) - Test orchestration framework
- **FOLLOW**: Existing KGEntities local test patterns with direct backend integration

**Phase F3 Priority - Slot Test Cases in `/test_script_kg_impl/kgframes/`:**
- **CREATE**: `case_slot_create.py` - Slot creation operations (new functionality)
- **CREATE**: `case_slot_delete.py` - Slot deletion operations (new functionality)
- **CREATE**: `case_slot_get.py` - Slot retrieval operations (new functionality)
- **CREATE**: `case_slot_update.py` - Slot update operations (new functionality)
- **CREATE**: `case_frame_query.py` - Frame query operations (new functionality)
- **CREATE**: `case_slot_query.py` - Slot query operations (new functionality)

**Client Test Cases** (Secondary Priority in `/vitalgraph_client_test/kgframes/`):
- **CREATE**: `case_kgframe_create.py` - Client-side frame creation testing
- **CREATE**: `case_kgframe_delete.py` - Client-side frame deletion testing
- **CREATE**: `case_kgframe_get.py` - Client-side frame retrieval testing
- **CREATE**: `case_kgframe_update.py` - Client-side frame update testing
- **CREATE**: `case_kgframe_hierarchical.py` - Client-side hierarchical frame testing

**Test Orchestrator Enhancement:**
- **PRIMARY**: `/test_scripts/fuseki_postgresql/test_kgframes_endpoint_fuseki_postgresql.py` - Local backend testing
- **INTEGRATE**: `/test_script_kg_impl/kgframes/` test cases with existing orchestrator
- **FOLLOW**: KGEntities local test pattern from `/test_script_kg_impl/kgentities/`
- **SECONDARY**: `/vitalgraph_client_test/test_kgframes_endpoint.py` - Client-side testing
- Frame-level grouping URI management (`frameGraphURI`)
- True atomicity validation (old slots removed, new slots added)
- Uses `update_quads` function for atomic consistency

**Test Coverage**:
- **Basic Atomic UPDATE**: Complete frame graph replacement
- **UPSERT New Frame**: Create frame when it doesn't exist
- **UPSERT Existing Frame**: Update frame when it exists
- **Atomicity Verification**: SPARQL queries to verify old objects removed and new objects added
- **Backend Integration**: Uses KGEntityFrameCreateProcessor with backend adapter

**Key Features Tested**:
- Frame-level grouping URI management (`frameGraphURI`)
- Slot replacement within frame context
- SPARQL-based validation of atomic operations
- Hybrid backend integration with dual-write consistency
- CREATE/UPDATE/UPSERT operation modes

## Test Data and Validation

### Hierarchical Structure Examples
- **Person Entities**: Enhanced with Contact, Personal, and Employment frames (3 frames, 9 slots each)
- **Organization Entities**: **45 objects, 22 edges, 3 levels** (Address/Company/Management hierarchies)
- **Project Entities**: 23 objects, 11 edges, 2 levels (Timeline/Budget/Team frames)
- **Hierarchical Management**: Management Frame → CEO/CTO/CFO Officer Frames → Name/Role/StartDate slots

### Test Data Validation
- **Total Object Types**: KGEntity, KGFrame, KGTextSlot, KGIntegerSlot, KGDateTimeSlot, Edge_hasEntityKGFrame, Edge_hasKGFrame, Edge_hasKGSlot
- **DAG Validation**: 16/16 tests passing with complex hierarchical structures
- **Frame-to-Frame Relationships**: Implemented `Edge_hasKGFrame` connections between Management and Officer frames
- **3-Level DAG Structures**: Successfully created and validated 3-level deep hierarchies

### Critical Corrections Applied
- **Fixed Slot Classes**: Replaced generic `KGSlot` with specific types (`KGTextSlot`, `KGDateTimeSlot`, `KGIntegerSlot`)
- **Fixed Edge Classes**: Corrected to use `Edge_hasEntityKGFrame` (entity-frame) and `Edge_hasKGFrame` (frame-frame)
- **Enhanced Edge Relationships**: Added frame-to-frame connections for hierarchical structures
- **Fixed Property Names**: Updated to use correct VitalSigns properties (`textSlotValue`, `dateTimeSlotValue`, `edgeSource`, `edgeDestination`)
- **Enhanced DAG Support**: Validated arbitrary depth DAG handling with 3-level hierarchies

## Implementation Phases

### Phase 1: Core Frame Operations (2-3 days)
- Implement basic frame CRUD operations
- Frame creation and deletion with proper edge relationships
- Integration with existing Edge_hasEntityKGFrame functionality

### Phase 2: Hierarchical Frame Support (1-2 days)  
- Implement Edge_hasKGFrame relationships for frame-to-frame connections
- Multi-level frame hierarchy traversal
- Frame chain connection queries

### Phase 3: Advanced Frame Queries (1-2 days)
- Frame graph retrieval using hasFrameGraphURI
- Complex frame filtering and sorting
- Frame-based entity discovery

### Phase 4: Testing and Validation (1 day)
- Comprehensive test suite for all frame operations
- Hierarchical structure validation
- Performance optimization and caching

## Dependencies and Integration

### Completed Dependencies
- ✅ **Edge_hasEntityKGFrame Persistence**: Fixed and working correctly
- ✅ **Frame Creation and Deletion**: Complete functionality in KGEntities endpoint
- ✅ **SPARQL Parser**: CompValue operation detection working correctly
- ✅ **Test Data**: Comprehensive hierarchical frame test data available

### Integration Points
- **KGEntities Endpoint**: Frame management functionality already implemented
- **Backend Storage**: Dual Fuseki-PostgreSQL storage working correctly
- **VitalSigns Integration**: JSON-LD to VitalSigns object conversion complete
- **Graph Validation**: Entity graph structure validation and consistency checking

## Success Criteria
- All 16 missing methods implemented and tested
- Hierarchical frame relationships working correctly
- Frame graph retrieval performance optimized
- Complete integration with KGEntities endpoint
- 100% test coverage for frame operations
- Production-ready frame management capabilities

## Notes
- Frame operations are closely integrated with KGEntities endpoint
- Hierarchical frame structures require careful edge relationship management
- Performance optimization critical for complex frame graph queries

---

# REVISED IMPLEMENTATION PLAN - January 17, 2026
## Code Organization Using kg_impl/ Directory Structure

## Executive Summary

**Current Status:**
- **Client Testing**: 8/12 test suites passing (66.7%)
- **Core Functionality**: Frame and Slot CRUD operations 100% functional
- **Missing Features**: Child frames, frame graphs, query endpoint issues
- **Root Cause**: Missing server-side endpoint implementations and proper code organization

**Implementation Strategy:**
Split KGFrames implementation into dedicated processor files in `/vitalgraph/kg_impl/` following the proven KGEntity pattern found in:
- `/vitalgraph/kg_impl/kgentity_frame_create_impl.py` - Processor pattern
- `/vitalgraph/kg_impl/kg_backend_utils.py` - Backend adapter pattern
- `/vitalgraph/client/endpoint/kgentities_endpoint.py` - Client patterns

---

## Architecture Review - Working Patterns from KGEntities

### ✅ Working KGEntities Implementation Patterns

#### 1. **Processor Pattern** (`kg_impl/kgentity_frame_create_impl.py`)
```python
class KGEntityFrameCreateProcessor:
    """Processor for creating frames and linking them to existing KGEntities."""
    
    async def create_entity_frame(
        self,
        backend_adapter: FusekiPostgreSQLBackendAdapter,
        space_id: str,
        graph_id: str,
        entity_uri: str,
        frame_objects: List[GraphObject],
        operation_mode: str = "CREATE"
    ) -> CreateFrameResult:
        # 1. Validate entity exists
        # 2. Categorize frame objects
        # 3. Set dual grouping URIs
        # 4. Create Edge_hasEntityKGFrame objects
        # 5. Execute atomic UPDATE/UPSERT or CREATE
```

**Key Insights:**
- Uses `FusekiPostgreSQLBackendAdapter` for all backend operations
- Implements atomic operations via `update_quads()` for UPDATE/UPSERT
- Handles dual grouping URIs (entity-level + frame-level)
- Creates proper edge relationships

#### 2. **Backend Adapter Pattern** (`kg_impl/kg_backend_utils.py`)
```python
class FusekiPostgreSQLBackendAdapter(KGBackendInterface):
    async def store_objects(self, space_id: str, graph_id: str, objects: List[GraphObject])
    async def object_exists(self, space_id: str, graph_id: str, uri: str)
    async def delete_object(self, space_id: str, graph_id: str, uri: str)
    async def execute_sparql_query(self, space_id: str, query: str)
    async def update_quads(self, space_id: str, graph_id: str, delete_quads, insert_quads)
```

**Key Insights:**
- Provides unified interface for backend operations
- Wraps `FusekiPostgreSQLSpaceImpl` with consistent API
- Handles VitalSigns object conversion to RDF quads
- Implements atomic update operations

#### 3. **Client Endpoint Pattern** (`client/endpoint/kgentities_endpoint.py`)
```python
class KGEntitiesEndpoint(BaseEndpoint):
    def create_entity_frames(self, space_id, graph_id, entity_uri, document, parent_frame_uri=None):
        url = f"{self._get_server_url()}/api/graphs/kgentities/kgframes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            entity_uri=entity_uri,
            parent_frame_uri=parent_frame_uri
        )
        return self._make_typed_request('POST', url, FrameCreateResponse, params=params, json=document.dict())
```

**Key Insights:**
- Uses `_make_typed_request()` for automatic response model validation
- Supports optional `parent_frame_uri` parameter for hierarchical frames
- Consistent parameter passing via `build_query_params()`

---

## Current KGFrames Issues - Detailed Analysis

### Issue 1: Child Frames Tests Failing (405 Method Not Allowed)

**Problem:**
```
Client calls: POST /api/graphs/kgframes/kgframes?parent_frame_uri=...
Server returns: 405 Method Not Allowed
```

**Root Cause:**
The KGFrames endpoint doesn't have a route handler for `parent_frame_uri` parameter.

**Current Server Route:**
```python
@self.router.post("/kgframes", response_model=Union[FrameCreateResponse, FrameUpdateResponse])
async def create_or_update_frames(
    request: JsonLdRequest,
    space_id: str = Query(...),
    graph_id: str = Query(...),
    entity_uri: Optional[str] = Query(None),
    parent_uri: Optional[str] = Query(None),
    operation_mode: Optional[str] = Query("create")
):
```

**Issue:** The route accepts `parent_uri` but doesn't handle `parent_frame_uri` specifically for child frame creation.

**Solution:** Create dedicated route `POST /kgframes/kgframes` with `parent_frame_uri` parameter.

### Issue 2: Frame Graphs Tests Failing (405 Method Not Allowed)

**Problem:**
```
Client calls: GET /api/graphs/kgframes/graph?frame_uri=...
Server returns: 405 Method Not Allowed
```

**Root Cause:**
No route exists for `/kgframes/graph` endpoint.

**Missing Routes:**
- `GET /api/graphs/kgframes/graph` - Get complete frame graph
- `DELETE /api/graphs/kgframes/graph` - Delete frame graph

**Solution:** Create `kgframe_graph_impl.py` processor and add both GET/DELETE routes.

### Issue 3: Query Frames Tests Failing

**Problem:**
```
Client calls: POST /api/graphs/kgframes/query
Server returns: 405 Method Not Allowed (or other error)
```

**Current Server Route:**
```python
@self.router.post("/kgframes/query", response_model=FrameQueryResponse)
async def query_frames(
    query_request: FrameQueryRequest,
    space_id: str = Query(...),
    graph_id: str = Query(...)
):
    return await self._query_frames(space_id, graph_id, query_request, current_user)
```

**Issue:** Route exists but may have implementation issues in `_query_frames()` method.

**Solution:** Debug existing implementation or create `kgframe_query_impl.py` processor.

### Issue 4: Frame Delete Test Data Issue

**Problem:**
One test case tries to delete a non-existent organization frame.

**Root Cause:**
Test setup doesn't create the organization entity before attempting frame deletion.

**Solution:** Update test case to create organization entity first.

---

## Code Organization Structure

### New KGFrame Processor Files to Create

**Location:** `/vitalgraph/kg_impl/`

1. **`kgframe_create_impl.py`**
   - Standalone frame creation (no entity association)
   - Pattern: Follow `kgentity_create_impl.py`
   - Handles: Frame validation, grouping URI assignment, backend storage

2. **`kgframe_get_impl.py`**
   - Frame retrieval and discovery
   - Pattern: Follow `kgentity_get_impl.py`
   - Handles: Single frame retrieval, frame listing, SPARQL queries

3. **`kgframe_update_impl.py`**
   - Frame update operations
   - Pattern: Follow `kgentity_update_impl.py`
   - Handles: Atomic updates using `update_quads()`, UPSERT logic

4. **`kgframe_delete_impl.py`**
   - Frame deletion operations
   - Pattern: Follow `kgentity_delete_impl.py`
   - Handles: Single/batch deletion, cascade deletion of slots

5. **`kgframe_hierarchical_impl.py`**
   - Child frame creation and management
   - Pattern: Follow `kgentity_hierarchical_frame_impl.py`
   - Handles: Parent-child relationships, Edge_hasKGFrame creation

6. **`kgframe_graph_impl.py`** (NEW)
   - Frame graph operations
   - Handles: Complete graph retrieval, graph deletion with cascade

7. **`kgframe_query_impl.py`** (NEW)
   - Frame query and search operations
   - Handles: Criteria-based search, pagination, filtering

8. **`kgframe_discovery_impl.py`** (NEW)
   - Frame discovery utilities
   - Pattern: Follow `kgentity_frame_discovery_impl.py`
   - Handles: Frame graph traversal, relationship discovery

### Existing KGSlot Processor Files (Review and Update)

**Already Exist:**
- `kgslot_create_impl.py` - Review for standalone frame support
- `kgslot_update_impl.py` - Review for standalone frame support
- `kgslot_delete_impl.py` - Review for standalone frame support

**Updates Needed:**
- Ensure slot processors work with both entity-associated and standalone frames
- Add support for frame-level grouping URIs
- Verify proper Edge_hasKGSlot relationship handling

### Common Utility Files (Use Existing)

**Backend Operations:**
- `kg_backend_utils.py`
  - `FusekiPostgreSQLBackendAdapter` class
  - `BackendOperationResult` dataclass
  - `create_backend_adapter()` function

**Graph Validation:**
- `kg_graph_validation.py`
  - Frame structure validation
  - DAG validation
  - Relationship validation

**JSON-LD Utilities:**
- `kg_jsonld_utils.py`
  - JSON-LD to VitalSigns conversion
  - VitalSigns to JSON-LD conversion
  - Document formatting

**SPARQL Query Building:**
- `kg_sparql_query.py`
  - Frame existence queries
  - Frame retrieval queries
  - Graph traversal queries

**SPARQL Utilities:**
- `kg_sparql_utils.py`
  - Query execution helpers
  - Result parsing
  - Triple/quad construction

**Validation Utilities:**
- `kg_validation_utils.py`
  - URI validation
  - Property validation
  - Structure validation

---

## Detailed Implementation Plan by Processor File

### 1. kgframe_create_impl.py

**Purpose:** Standalone frame creation without entity association

**Class:** `KGFrameCreateProcessor`

**Key Methods:**
```python
async def create_frame(
    backend_adapter: FusekiPostgreSQLBackendAdapter,
    space_id: str,
    graph_id: str,
    frame_objects: List[GraphObject],
    operation_mode: str = "CREATE"
) -> CreateFrameResult
```

**Dependencies:**
- Import from `kg_backend_utils.py`: `FusekiPostgreSQLBackendAdapter`, `BackendOperationResult`
- Import from `kg_validation_utils.py`: Frame validation functions
- Import from `kg_jsonld_utils.py`: JSON-LD conversion utilities

**Implementation Tasks:**
- [ ] Create file structure following `kgentity_create_impl.py` pattern
- [ ] Implement frame validation logic
- [ ] Implement grouping URI assignment (frame-level only, no entity)
- [ ] Implement backend storage integration
- [ ] Add comprehensive logging
- [ ] Add error handling

### 2. kgframe_hierarchical_impl.py

**Purpose:** Child frame creation with parent-child relationships

**Class:** `KGFrameHierarchicalProcessor`

**Key Methods:**
```python
async def create_child_frames(
    backend_adapter: FusekiPostgreSQLBackendAdapter,
    space_id: str,
    graph_id: str,
    parent_frame_uri: str,
    child_frame_objects: List[GraphObject],
    operation_mode: str = "CREATE"
) -> CreateFrameResult
```

**Dependencies:**
- Import from `kg_backend_utils.py`: Backend adapter
- Import from `kg_sparql_query.py`: Parent frame existence queries
- Import from `kg_validation_utils.py`: Relationship validation

**Implementation Tasks:**
- [ ] Create file following `kgentity_hierarchical_frame_impl.py` pattern
- [ ] Implement parent frame existence validation
- [ ] Implement grouping URI inheritance from parent
- [ ] Implement Edge_hasKGFrame relationship creation
- [ ] Add atomic creation logic
- [ ] Add error handling for missing parent

### 3. kgframe_graph_impl.py

**Purpose:** Frame graph operations (get/delete complete graphs)

**Class:** `KGFrameGraphProcessor`

**Key Methods:**
```python
async def get_frame_graph(
    backend_adapter: FusekiPostgreSQLBackendAdapter,
    space_id: str,
    graph_id: str,
    frame_uri: str
) -> Dict[str, Any]

async def delete_frame_graph(
    backend_adapter: FusekiPostgreSQLBackendAdapter,
    space_id: str,
    graph_id: str,
    frame_uri: str
) -> bool
```

**Dependencies:**
- Import from `kg_sparql_query.py`: CONSTRUCT query builders
- Import from `kg_jsonld_utils.py`: Result conversion
- Import from `kg_backend_utils.py`: Backend operations

**Implementation Tasks:**
- [ ] Create new file (no existing pattern to follow)
- [ ] Implement SPARQL CONSTRUCT query for complete frame graph
- [ ] Include frame + all slots + all edges in graph retrieval
- [ ] Implement cascade deletion (frame + slots + edges)
- [ ] Add support for child frame inclusion
- [ ] Convert results to JsonLdDocument format

### 4. kgframe_query_impl.py

**Purpose:** Frame query and search operations

**Class:** `KGFrameQueryProcessor`

**Key Methods:**
```python
async def query_frames(
    backend_adapter: FusekiPostgreSQLBackendAdapter,
    space_id: str,
    graph_id: str,
    query_criteria: FrameQueryCriteria
) -> FrameQueryResult
```

**Dependencies:**
- Import from `kg_sparql_query.py`: Query builders
- Import from `kg_validation_utils.py`: Criteria validation

**Implementation Tasks:**
- [ ] Create new file for query operations
- [ ] Implement criteria-based SPARQL query building
- [ ] Support frame type filtering
- [ ] Support property-based filtering
- [ ] Implement pagination
- [ ] Add result parsing and formatting

### 5. kgframe_get_impl.py

**Purpose:** Frame retrieval and discovery

**Class:** `KGFrameGetProcessor`

**Key Methods:**
```python
async def get_frame_by_uri(
    backend_adapter: FusekiPostgreSQLBackendAdapter,
    space_id: str,
    graph_id: str,
    frame_uri: str
) -> Optional[GraphObject]

async def list_frames(
    backend_adapter: FusekiPostgreSQLBackendAdapter,
    space_id: str,
    graph_id: str,
    page_size: int,
    offset: int
) -> List[GraphObject]
```

**Dependencies:**
- Import from `kg_sparql_query.py`: Retrieval queries
- Import from `kg_jsonld_utils.py`: Object conversion

**Implementation Tasks:**
- [ ] Create file following `kgentity_get_impl.py` pattern
- [ ] Implement single frame retrieval
- [ ] Implement frame listing with pagination
- [ ] Add filtering support
- [ ] Convert SPARQL results to VitalSigns objects

### 6. kgframe_update_impl.py

**Purpose:** Frame update operations

**Class:** `KGFrameUpdateProcessor`

**Key Methods:**
```python
async def update_frame(
    backend_adapter: FusekiPostgreSQLBackendAdapter,
    space_id: str,
    graph_id: str,
    frame_objects: List[GraphObject]
) -> UpdateFrameResult
```

**Dependencies:**
- Import from `kg_backend_utils.py`: `update_quads()` method
- Import from `kg_sparql_query.py`: Current state retrieval

**Implementation Tasks:**
- [ ] Create file following `kgentity_update_impl.py` pattern
- [ ] Implement atomic update using `update_quads()`
- [ ] Get current frame quads
- [ ] Build delete and insert quad lists
- [ ] Execute atomic update
- [ ] Handle UPSERT logic

### 7. kgframe_delete_impl.py

**Purpose:** Frame deletion operations

**Class:** `KGFrameDeleteProcessor`

**Key Methods:**
```python
async def delete_frame(
    backend_adapter: FusekiPostgreSQLBackendAdapter,
    space_id: str,
    graph_id: str,
    frame_uri: str
) -> bool
```

**Dependencies:**
- Import from `kg_sparql_query.py`: Deletion queries
- Import from `kg_backend_utils.py`: Backend operations

**Implementation Tasks:**
- [ ] Create file following `kgentity_delete_impl.py` pattern
- [ ] Implement single frame deletion
- [ ] Implement batch frame deletion
- [ ] Add cascade deletion of connected slots
- [ ] Add cascade deletion of Edge_hasKGSlot relationships
- [ ] Verify parent-child edge cleanup

---

## Server Endpoint Cleanup and Refactoring

### Critical Principle: JSON-LD at Endpoint Boundary Only

**JSON-LD Usage:**
- JSON-LD is **ONLY** for endpoint data exchange (request/response)
- JSON-LD conversion happens **AT THE ENDPOINT BOUNDARY**
- Internal implementation uses **VitalSigns GraphObjects**
- Use `kg_jsonld_utils.py` for all JSON-LD ↔ VitalSigns conversions

**Data Flow:**
```
Client Request (JSON-LD)
    ↓
[Endpoint] → Convert JSON-LD to VitalSigns (kg_jsonld_utils.py)
    ↓
[Processors] → Work with VitalSigns GraphObjects
    ↓
[Backend] → Store/retrieve as RDF quads
    ↓
[Processors] → Return VitalSigns GraphObjects
    ↓
[Endpoint] → Convert VitalSigns to JSON-LD (kg_jsonld_utils.py)
    ↓
Client Response (JSON-LD)
```

### Cleanup Tasks for KGFramesEndpoint

**File:** `/vitalgraph/endpoint/kgframes_endpoint.py`

#### 1. Remove Redundant Code

**Delete inline implementations that duplicate processor logic:**
- [ ] Remove inline frame creation logic (delegate to `KGFrameCreateProcessor`)
- [ ] Remove inline frame update logic (delegate to `KGFrameUpdateProcessor`)
- [ ] Remove inline frame deletion logic (delegate to `KGFrameDeleteProcessor`)
- [ ] Remove inline SPARQL query building (use `kg_sparql_query.py`)
- [ ] Remove inline validation logic (use `kg_validation_utils.py`)
- [ ] Remove inline JSON-LD conversion (use `kg_jsonld_utils.py`)

**Current Problem Example:**
```python
# BEFORE: Inline logic in endpoint (BAD)
async def _create_frames(self, space_id, graph_id, request, ...):
    # 50+ lines of inline frame creation logic
    # Validation logic
    # Grouping URI assignment
    # Backend storage
    # Error handling
```

**After Cleanup:**
```python
# AFTER: Delegate to processor (GOOD)
async def _create_frames(self, space_id, graph_id, request, ...):
    # Convert JSON-LD to VitalSigns at boundary
    frame_objects = jsonld_to_vitalsigns(request)
    
    # Delegate to processor
    result = await self.frame_create_processor.create_frame(
        backend_adapter=await self._get_backend_adapter(space_id),
        space_id=space_id,
        graph_id=graph_id,
        frame_objects=frame_objects
    )
    
    # Convert result to response model
    return FrameCreateResponse(...)
```

#### 2. Consolidate JSON-LD Conversion

**Use `kg_jsonld_utils.py` consistently:**

```python
from ..kg_impl.kg_jsonld_utils import (
    jsonld_to_vitalsigns,
    vitalsigns_to_jsonld,
    jsonld_document_to_vitalsigns_list,
    vitalsigns_list_to_jsonld_document
)

# In route handlers:
async def create_frames(request: JsonLdRequest, ...):
    # Convert at boundary
    frame_objects = jsonld_to_vitalsigns(request)
    
    # Process (no JSON-LD here)
    result = await processor.create_frame(frame_objects)
    
    # Convert back at boundary
    return vitalsigns_to_jsonld(result)
```

#### 3. Import and Initialize Processors

**Add processor imports:**
```python
from ..kg_impl.kgframe_create_impl import KGFrameCreateProcessor
from ..kg_impl.kgframe_get_impl import KGFrameGetProcessor
from ..kg_impl.kgframe_update_impl import KGFrameUpdateProcessor
from ..kg_impl.kgframe_delete_impl import KGFrameDeleteProcessor
from ..kg_impl.kgframe_hierarchical_impl import KGFrameHierarchicalProcessor
from ..kg_impl.kgframe_graph_impl import KGFrameGraphProcessor
from ..kg_impl.kgframe_query_impl import KGFrameQueryProcessor
from ..kg_impl.kgslot_create_impl import KGSlotCreateProcessor
from ..kg_impl.kgslot_update_impl import KGSlotUpdateProcessor
from ..kg_impl.kgslot_delete_impl import KGSlotDeleteProcessor
```

**Initialize in `__init__`:**
```python
def __init__(self, space_manager, auth_dependency):
    # ... existing code ...
    
    # Initialize frame processors
    self.frame_create_processor = KGFrameCreateProcessor()
    self.frame_get_processor = KGFrameGetProcessor()
    self.frame_update_processor = KGFrameUpdateProcessor()
    self.frame_delete_processor = KGFrameDeleteProcessor()
    self.frame_hierarchical_processor = KGFrameHierarchicalProcessor()
    self.frame_graph_processor = KGFrameGraphProcessor()
    self.frame_query_processor = KGFrameQueryProcessor()
    
    # Slot processors already exist, just initialize
    self.slot_create_processor = KGSlotCreateProcessor()
    self.slot_update_processor = KGSlotUpdateProcessor()
    self.slot_delete_processor = KGSlotDeleteProcessor()
```

#### 4. Refactor Route Handlers

**Pattern for all route handlers:**

```python
@self.router.post("/kgframes", response_model=FrameCreateResponse)
async def create_frames(
    request: JsonLdRequest,
    space_id: str = Query(...),
    graph_id: str = Query(...),
    operation_mode: Optional[str] = Query("create"),
    current_user: Dict = Depends(self.auth_dependency)
):
    """
    Create frames.
    
    JSON-LD conversion happens here at endpoint boundary.
    All processing delegated to processor.
    """
    try:
        # 1. Convert JSON-LD to VitalSigns (boundary)
        frame_objects = jsonld_to_vitalsigns(request)
        
        # 2. Get backend adapter
        backend_adapter = await self._get_backend_adapter(space_id)
        
        # 3. Delegate to processor (no JSON-LD)
        result = await self.frame_create_processor.create_frame(
            backend_adapter=backend_adapter,
            space_id=space_id,
            graph_id=graph_id,
            frame_objects=frame_objects,
            operation_mode=operation_mode
        )
        
        # 4. Return response model (processor returns structured data)
        return FrameCreateResponse(
            success=result.success,
            message=result.message,
            created_count=result.frame_count,
            created_uris=result.created_uris,
            frames_created=result.frame_count
        )
        
    except Exception as e:
        self.logger.error(f"Frame creation failed: {e}")
        return FrameCreateResponse(
            success=False,
            message=f"Frame creation failed: {str(e)}",
            created_count=0
        )
```

#### 5. Add Missing Routes

**Child frames route:**
```python
@self.router.post("/kgframes/kgframes", response_model=FrameCreateResponse, tags=["KG Child Frames"])
async def create_child_frames(
    request: JsonLdRequest,
    space_id: str = Query(...),
    graph_id: str = Query(...),
    parent_frame_uri: str = Query(...),
    operation_mode: Optional[str] = Query("create"),
    current_user: Dict = Depends(self.auth_dependency)
):
    """Create child frames for a parent frame."""
    frame_objects = jsonld_to_vitalsigns(request)
    backend_adapter = await self._get_backend_adapter(space_id)
    
    result = await self.frame_hierarchical_processor.create_child_frames(
        backend_adapter=backend_adapter,
        space_id=space_id,
        graph_id=graph_id,
        parent_frame_uri=parent_frame_uri,
        child_frame_objects=frame_objects,
        operation_mode=operation_mode
    )
    
    return FrameCreateResponse(
        success=result.success,
        message=result.message,
        created_count=result.frame_count,
        created_uris=result.created_uris,
        frames_created=result.frame_count
    )
```

**Frame graph routes:**
```python
@self.router.get("/kgframes/graph", response_model=JsonLdDocument, tags=["KG Frame Graphs"])
async def get_frame_graph(
    space_id: str = Query(...),
    graph_id: str = Query(...),
    frame_uri: str = Query(...),
    current_user: Dict = Depends(self.auth_dependency)
):
    """Get complete graph for a specific frame."""
    backend_adapter = await self._get_backend_adapter(space_id)
    
    # Processor returns VitalSigns objects
    graph_objects = await self.frame_graph_processor.get_frame_graph(
        backend_adapter=backend_adapter,
        space_id=space_id,
        graph_id=graph_id,
        frame_uri=frame_uri
    )
    
    # Convert to JSON-LD at boundary
    return vitalsigns_list_to_jsonld_document(graph_objects)

@self.router.delete("/kgframes/graph", response_model=FrameDeleteResponse, tags=["KG Frame Graphs"])
async def delete_frame_graph(
    space_id: str = Query(...),
    graph_id: str = Query(...),
    frame_uri: str = Query(...),
    current_user: Dict = Depends(self.auth_dependency)
):
    """Delete frame and its complete graph."""
    backend_adapter = await self._get_backend_adapter(space_id)
    
    success = await self.frame_graph_processor.delete_frame_graph(
        backend_adapter=backend_adapter,
        space_id=space_id,
        graph_id=graph_id,
        frame_uri=frame_uri
    )
    
    return FrameDeleteResponse(
        success=success,
        message="Frame graph deleted" if success else "Deletion failed",
        deleted_count=1 if success else 0
    )
```

#### 6. Remove Unused Helper Methods

**Delete methods that are now in processors or utils:**
- [ ] Remove `_validate_frame_structure()` → Use `kg_validation_utils.py`
- [ ] Remove `_build_sparql_query()` → Use `kg_sparql_query.py`
- [ ] Remove `_convert_to_vitalsigns()` → Use `kg_jsonld_utils.py`
- [ ] Remove `_assign_grouping_uris()` → In processors
- [ ] Remove `_create_edges()` → In processors
- [ ] Remove inline SPARQL execution → Use backend adapter

### Expected Code Size Reduction

**Before Cleanup:**
- Endpoint file: ~2900 lines
- Inline logic: ~1500 lines
- Redundant code: ~800 lines

**After Cleanup:**
- Endpoint file: ~800-1000 lines
- Route handlers: ~400 lines
- Helper methods: ~200 lines
- Initialization: ~200 lines

**Reduction: ~65-70% code reduction in endpoint file**

### Cleanup Checklist

- [ ] Remove all inline frame creation logic
- [ ] Remove all inline frame update logic
- [ ] Remove all inline frame deletion logic
- [ ] Remove all inline SPARQL query building
- [ ] Remove all inline validation logic
- [ ] Consolidate all JSON-LD conversion to use `kg_jsonld_utils.py`
- [ ] Import all processors
- [ ] Initialize all processors in `__init__`
- [ ] Refactor all route handlers to use processors
- [ ] Add missing routes (child frames, frame graphs)
- [ ] Remove unused helper methods
- [ ] Verify no JSON-LD usage in processors
- [ ] Test all endpoints after cleanup

---

## Implementation Checklist

### Phase 1: Create Core Processor Files
- [x] Create `kgframe_hierarchical_impl.py` ✅ COMPLETED
- [x] Create `kgframe_graph_impl.py` ✅ COMPLETED
- [x] Create `kgframe_query_impl.py` ✅ COMPLETED
- [ ] Create `kgframe_create_impl.py`
- [ ] Create `kgframe_get_impl.py`
- [ ] Create `kgframe_update_impl.py`
- [ ] Create `kgframe_delete_impl.py`
- [ ] Review and update `kgslot_create_impl.py`
- [ ] Review and update `kgslot_update_impl.py`
- [ ] Review and update `kgslot_delete_impl.py`

### Phase 2: Create Advanced Processor Files
- [x] Create `kgframe_hierarchical_impl.py` ✅ COMPLETED
- [x] Create `kgframe_graph_impl.py` ✅ COMPLETED
- [x] Create `kgframe_query_impl.py` ✅ COMPLETED
- [ ] Create `kgframe_discovery_impl.py`

### Phase 3: Update Server Endpoint
- [x] Import all new processors in `kgframes_endpoint.py` ✅ COMPLETED
- [x] Initialize processors in `__init__` ✅ COMPLETED
- [x] Removed duplicate routes - existing routes already handle functionality ✅ COMPLETED
- [ ] Update `_create_or_update_frames` to use hierarchical processor when `parent_uri` provided
- [ ] Update `_get_frame_by_uri` to use graph processor when `include_frame_graph=True`
- [ ] Update `_delete_frame_by_uri` to use graph processor for cascade deletion
- [ ] Update `_query_frames` to use query processor
- [ ] Remove inline logic, delegate to processors

### Phase 4: Local Testing (Pre-Client/Server Testing)

**CRITICAL: Test locally BEFORE running client/server tests**

**Local Test Script:**
- **File:** `/test_scripts/fuseki_postgresql/test_kgframes_endpoint_fuseki_postgresql.py`
- **Test Cases:** `/test_script_kg_impl/kgframes/`

**Why Local Testing First:**
- Tests endpoint logic without client/server overhead
- Validates Pydantic model serialization
- Ensures aliases are triggered correctly
- Faster iteration on fixes
- Isolates backend issues from network issues

**Pydantic Serialization Requirements:**
- [ ] Verify response models serialize correctly with `.model_dump()`
- [ ] Ensure aliases are triggered (e.g., `frames_created` vs `created_count`)
- [ ] Test all response model fields are populated
- [ ] Validate JSON-LD conversion at boundary

**Local Test Tasks:**
- [ ] Update `test_kgframes_endpoint_fuseki_postgresql.py` to include new routes
- [ ] Review test cases in `/test_script_kg_impl/kgframes/`
- [ ] Add test cases for child frames operations
- [ ] Add test cases for frame graph operations
- [ ] Add test cases for query operations
- [ ] Run local tests and verify all pass
- [ ] Fix any Pydantic serialization issues
- [ ] Fix any processor logic issues

### Phase 5: Client/Server Testing
- [ ] Fix frame delete test data issue (create organization entity first)
- [ ] Run all 12 client test suites
- [ ] Verify 12/12 pass rate (100% success)
- [ ] Performance testing

---

## Local Testing Strategy - CRITICAL

### Why Local Testing Before Client/Server Tests

**Local tests bypass client/server communication and test endpoint logic directly:**
- ✅ Faster iteration (no server startup, no HTTP overhead)
- ✅ Better debugging (direct Python stack traces)
- ✅ Validates Pydantic model serialization
- ✅ Ensures response model aliases work correctly
- ✅ Tests processor integration without network issues
- ✅ Catches serialization bugs before client tests

### Local Test Files

**Main Test Orchestrator:**
```
/test_scripts/fuseki_postgresql/test_kgframes_endpoint_fuseki_postgresql.py
```

**Test Case Modules:**
```
/test_script_kg_impl/kgframes/
├── case_frame_create.py
├── case_frame_get.py
├── case_frame_update.py
├── case_frame_delete.py
├── case_child_frames.py          # NEW - needs test cases
├── case_frame_graphs.py           # NEW - needs test cases
├── case_query_frames.py           # NEW - needs test cases
├── case_slot_create.py
├── case_slot_update.py
├── case_slot_delete.py
└── __init__.py
```

### Pydantic Serialization Requirements

**CRITICAL: Response models must serialize correctly with aliases**

**Problem Example:**
```python
class FrameCreateResponse(BaseModel):
    success: bool
    message: str
    created_count: int
    frames_created: int = Field(alias="created_count")  # Alias!
```

**What Must Happen:**
```python
# When serializing response:
response = FrameCreateResponse(
    success=True,
    message="Created",
    created_count=5,
    frames_created=5  # Must set BOTH fields
)

# Serialization triggers aliases:
response.model_dump(by_alias=True)
# Output: {"success": true, "message": "Created", "created_count": 5}
```

**Common Serialization Issues:**
1. ❌ Only setting `created_count`, not `frames_created`
2. ❌ Not calling `.model_dump()` to trigger serialization
3. ❌ Missing `by_alias=True` parameter
4. ❌ Aliases not defined in response model

**How to Fix:**
```python
# In endpoint handler:
return FrameCreateResponse(
    success=result.success,
    message=result.message,
    created_count=result.frame_count,
    created_uris=result.created_uris,
    frames_created=result.frame_count  # Set alias field!
)
```

### Local Test Updates Needed

**1. Update Test Orchestrator**

**File:** `/test_scripts/fuseki_postgresql/test_kgframes_endpoint_fuseki_postgresql.py`

**Add imports for new test cases:**
```python
from test_script_kg_impl.kgframes.case_child_frames import (
    test_create_child_frames,
    test_child_frame_hierarchy
)
from test_script_kg_impl.kgframes.case_frame_graphs import (
    test_get_frame_graph,
    test_delete_frame_graph
)
from test_script_kg_impl.kgframes.case_query_frames import (
    test_query_frames_by_type,
    test_query_frames_by_parent
)
```

**Add to test execution:**
```python
# Child frames tests
print("\n=== Testing Child Frames ===")
test_create_child_frames(endpoint, space_id, graph_id)
test_child_frame_hierarchy(endpoint, space_id, graph_id)

# Frame graph tests
print("\n=== Testing Frame Graphs ===")
test_get_frame_graph(endpoint, space_id, graph_id)
test_delete_frame_graph(endpoint, space_id, graph_id)

# Query tests
print("\n=== Testing Frame Queries ===")
test_query_frames_by_type(endpoint, space_id, graph_id)
test_query_frames_by_parent(endpoint, space_id, graph_id)
```

**2. Create New Test Case Files**

**File:** `/test_script_kg_impl/kgframes/case_child_frames.py`

```python
"""Test cases for child frame operations."""

def test_create_child_frames(endpoint, space_id, graph_id):
    """Test creating child frames with parent_frame_uri parameter."""
    # Create parent frame first
    # Create child frames with parent_frame_uri
    # Verify Edge_hasKGFrame relationships created
    # Verify grouping URIs inherited
    pass

def test_child_frame_hierarchy(endpoint, space_id, graph_id):
    """Test multi-level frame hierarchy."""
    # Create parent -> child -> grandchild hierarchy
    # Verify all relationships
    pass
```

**File:** `/test_script_kg_impl/kgframes/case_frame_graphs.py`

```python
"""Test cases for frame graph operations."""

def test_get_frame_graph(endpoint, space_id, graph_id):
    """Test retrieving complete frame graph."""
    # Create frame with slots
    # Get frame graph
    # Verify frame + slots + edges returned
    pass

def test_delete_frame_graph(endpoint, space_id, graph_id):
    """Test deleting complete frame graph."""
    # Create frame with slots
    # Delete frame graph
    # Verify frame + slots + edges all deleted
    pass
```

**File:** `/test_script_kg_impl/kgframes/case_query_frames.py`

```python
"""Test cases for frame query operations."""

def test_query_frames_by_type(endpoint, space_id, graph_id):
    """Test querying frames by type."""
    # Create frames of different types
    # Query by specific type
    # Verify only matching frames returned
    pass

def test_query_frames_by_parent(endpoint, space_id, graph_id):
    """Test querying child frames by parent URI."""
    # Create parent with children
    # Query by parent_frame_uri
    # Verify only children returned
    pass
```

### Pydantic Serialization Testing

**Test Pattern:**
```python
def test_response_serialization(endpoint, space_id, graph_id):
    """Verify response models serialize correctly with aliases."""
    
    # Call endpoint
    response = endpoint.create_frames(...)
    
    # Verify response is Pydantic model
    assert isinstance(response, FrameCreateResponse)
    
    # Test serialization with aliases
    serialized = response.model_dump(by_alias=True)
    
    # Verify alias fields present
    assert "created_count" in serialized
    assert "frames_created" not in serialized  # Alias replaces original
    
    # Verify values correct
    assert serialized["created_count"] == 5
    assert serialized["success"] == True
```

### Local Test Execution

**Run local tests:**
```bash
/opt/homebrew/anaconda3/envs/vital-graph/bin/python \
  /Users/hadfield/Local/vital-git/vital-graph/test_scripts/fuseki_postgresql/test_kgframes_endpoint_fuseki_postgresql.py
```

**Expected Output:**
```
=== Testing Frame Creation ===
✓ test_create_frame_standalone
✓ test_create_frame_with_slots

=== Testing Child Frames ===
✓ test_create_child_frames
✓ test_child_frame_hierarchy

=== Testing Frame Graphs ===
✓ test_get_frame_graph
✓ test_delete_frame_graph

=== Testing Frame Queries ===
✓ test_query_frames_by_type
✓ test_query_frames_by_parent

All tests passed!
```

### Debugging Pydantic Issues

**Common Issues and Fixes:**

**Issue 1: Alias not triggered**
```python
# BAD:
return FrameCreateResponse(created_count=5)

# GOOD:
return FrameCreateResponse(
    created_count=5,
    frames_created=5  # Set alias field explicitly
)
```

**Issue 2: Missing field in serialization**
```python
# Check model definition:
class FrameCreateResponse(BaseModel):
    frames_created: int = Field(alias="created_count")
    
    class Config:
        populate_by_name = True  # Allow both names
```

**Issue 3: Serialization not called**
```python
# BAD: Returning model directly
return response

# GOOD: FastAPI auto-serializes, but test manually:
serialized = response.model_dump(by_alias=True)
```

---

## Success Criteria

**Code Organization:**
- [ ] All frame logic in dedicated `kgframe_*.py` processor files
- [ ] Common utilities properly imported from `kg_*.py` files
- [ ] No duplicate code between processors
- [ ] Consistent patterns across all processors

**Functionality:**
- [ ] 12/12 client test suites passing (100%)
- [ ] All CRUD operations functional
- [ ] Child frames working
- [ ] Frame graphs working
- [ ] Query endpoint working

**Code Quality:**
- [ ] Comprehensive logging in all processors
- [ ] Proper error handling
- [ ] Type hints throughout
- [ ] Docstrings for all public methods
- [ ] Following established patterns

---

## Timeline Estimate

**Phase 1 (Core Processors):** 6-8 hours
**Phase 2 (Advanced Processors):** 6-8 hours
**Phase 3 (Endpoint Integration):** 2-3 hours
**Phase 4 (Testing):** 2-3 hours

**Total: 16-22 hours**

---

## Next Steps

1. Start with `kgframe_hierarchical_impl.py` (highest priority for failing tests)
2. Create `kgframe_graph_impl.py` (second highest priority)
3. Debug/fix `kgframe_query_impl.py`
4. Create remaining core processors
5. Integrate all processors into endpoint
6. Run comprehensive tests
- VitalSigns integration ensures type safety and validation