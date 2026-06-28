# KG Update Plan: Entity and Frame Graph Operations

## Overview

This plan outlines the enhancement of VitalGraph's KG functions to support entity and frame graph operations using the properties `hasKGGraphURI` and `hasFrameGraphURI` for efficient graph-based queries and operations.

**Important Note**: This is a **new application** without existing users or legacy constraints. We can implement optimal designs without backward compatibility concerns, allowing for clean architecture and best practices throughout.

## ✅ **TASK #1 COMPLETED: MockKGFramesEndpoint Integration**

**Status: 100% COMPLETE - All 5/5 Integration Tests Passing**

### **Achievements:**

1. **✅ VitalSigns Integration Patterns** - Complete alignment with MockKGEntitiesEndpoint
   - Native JSON-LD conversion using `vitalsigns.from_jsonld_list()`
   - Proper `document.model_dump(by_alias=True)` usage
   - VitalSigns object creation and Property object handling

2. **✅ Property Object Handling** - Complete VitalSigns Property system integration
   - Correct property casting: `str(obj.URI)`, `str(obj.name)`
   - Property access patterns: `obj.textSlotValue`, `obj.integerSlotValue`
   - Pydantic validation compatibility

3. **✅ Grouping URI Enforcement** - Frame-level grouping implemented
   - **Key Discovery**: `hasFrameGraphURI` → `frameGraphURI` (VitalSigns naming convention)
   - Distinct from entity grouping (`kGGraphURI`)
   - Proper RDF triple storage and retrieval

4. **✅ isinstance() Type Checking** - Complete type validation system
   - `isinstance(obj, KGFrame)`, `isinstance(obj, KGTextSlot)`, etc.
   - Reliable type detection for all KG object types
   - GraphObject inheritance validation

5. **✅ VitalSigns Native JSON-LD Conversion** - Perfect integration
   - `GraphObject.to_jsonld_list()` for object-to-JSON-LD conversion
   - Proper `@context` and `@graph` structure handling
   - 7-object test case (1 KGFrame, 3 KGSlots, 3 Edges) working perfectly

### **Implementation Details:**

```python
# Key Methods Implemented:
- create_kgframes() - Full VitalSigns integration with grouping URI enforcement
- create_frame_slots() - Slot creation with Edge_hasKGSlot relationship handling
- _set_frame_grouping_uris() - Frame-specific grouping using frameGraphURI property
- _create_vitalsigns_objects_from_jsonld() - Native VitalSigns JSON-LD processing
- _store_vitalsigns_objects_in_pyoxigraph() - RDF triple storage integration

# Property Naming Conventions Established:
- hasFrameGraphURI → frameGraphURI (VitalSigns convention)
- hasName → name (direct property access)
- hasKGFrameType → kGFrameType (short name)
- hasTextSlotValue → textSlotValue (slot-specific properties)
```

### **Test Results:**
```
🎉 All MockKGFramesEndpoint integration tests passed!
✅ PASS VitalSigns Integration Patterns (7 objects created)
✅ PASS Property Object Handling (3/3 property tests passed)
✅ PASS Grouping URI Enforcement (frameGraphURI working)
✅ PASS isinstance() Type Checking (5/5 tests passed)
✅ PASS VitalSigns Native JSON-LD Conversion (5/5 tests passed)
```

### **Files Modified:**
- `/vitalgraph/mock/client/endpoint/mock_kgframes_endpoint.py` - Complete VitalSigns integration
- `/vitalgraph_mock_client_test/test_mock_kgframes_integration.py` - Comprehensive integration tests
- `/vitalgraph_mock_client_test/run_integration_tests.py` - Test runner for validation

**MockKGFramesEndpoint now has complete parity with MockKGEntitiesEndpoint and is production-ready!**

## ✅ **TASK #2 COMPLETED: Data Lifecycle Management & Stale Triple Prevention**

**Status: 100% COMPLETE - All 4/4 Data Lifecycle Tests Passing**

### **Achievements:**

1. **✅ Atomic Update Operations** - Complete success or rollback capability implemented
   - Enhanced `update_kgframes()` with atomic transaction patterns
   - Backup and restore functionality for rollback operations
   - Operation mode support: create/update/upsert

2. **✅ Stale Triple Detection & Cleanup** - Comprehensive orphaned data prevention
   - `detect_stale_triples()` method with SPARQL-based detection
   - `cleanup_stale_triples()` method for automated cleanup
   - Detection of orphaned slots, edges, and broken references

3. **✅ Edge Relationship Management** - Referential integrity maintained
   - Frame graph-level operations (frame + slots + edges)
   - Proper deletion of connected objects to prevent stale data
   - Edge validation and consistency checking

4. **✅ Server-Authoritative Grouping URI Enforcement** - Consistent grouping
   - Client-provided grouping URIs stripped and replaced by server
   - Proper `frameGraphURI` setting on all frame graph components
   - Grouping URI consistency validation

### **Implementation Details:**

```python
# Key Methods Implemented:
- update_kgframes(operation_mode="create|update|upsert") - Enhanced with atomic operations
- _frame_exists_in_store() - Check frame existence for operation mode validation
- _backup_frame_graph() - Backup complete frame graphs for rollback
- _delete_frame_graph_from_store() - Atomic deletion of frame + slots + edges
- _restore_frame_graph_from_backup() - Rollback capability
- detect_stale_triples() - SPARQL-based stale data detection
- cleanup_stale_triples() - Automated cleanup of orphaned objects

# Operation Modes Supported:
- "create": Only create new frames (skip existing)
- "update": Only update existing frames (skip non-existent)  
- "upsert": Create or update regardless of existence
```

### **Test Results:**
```
🎉 All Data Lifecycle Management tests passed!
✅ PASS Atomic Update Operations (rollback capability working)
✅ PASS Operation Modes (create/update/upsert all working)
✅ PASS Stale Triple Detection & Cleanup (SPARQL queries working)
✅ PASS Grouping URI Enforcement (server authority working)
```

### **Files Modified:**
- `/vitalgraph/mock/client/endpoint/mock_kgframes_endpoint.py` - Enhanced update operations with atomic patterns
- `/vitalgraph_mock_client_test/test_data_lifecycle_management.py` - Comprehensive test suite for data lifecycle

**Data lifecycle management is now production-ready with atomic operations and stale triple prevention!**

## 🏗️ **ENDPOINT ARCHITECTURE CLARIFICATION**

### **Main vs Sub-Endpoint Distinction**

**CRITICAL ARCHITECTURAL INSIGHT**: There are two distinct types of endpoints with different operational scopes:

#### **Main Endpoints** (Whole Graph Operations)
- **`/kgentities`** - Operates on complete entity graphs (entity + all frames + slots + edges)
- **`/kgframes`** - Operates on complete frame graphs (frame + all slots + edges)

#### **Sub-Endpoints** (Contextual Operations Within Existing Graphs)
- **`/kgentities/kgframes?entity_uri={uri}`** - Frame operations within an existing entity context
- **`/kgframes/kgframes?parent_frame_uri={uri}`** - Child frame operations within an existing parent frame context  
- **`/kgframes/kgslots?frame_uri={uri}`** - Slot operations within an existing frame context

### **Operation Mode Requirements by Endpoint Type**

#### **Main Endpoints: Complete Graph Validation**

**KGEntities Endpoint (`/kgentities`):**
- **CREATE**: Verify complete entity graph structure (entity→frame via Edge_hasEntityKGFrame, frame→frame via Edge_hasKGFrame, frame→slot via Edge_hasKGSlot)
- **CREATE**: Verify NO object URIs exist as subjects in the graph
- **UPDATE**: Validate new graph structure, get existing objects via grouping URI, compare URI sets (must match exactly), delete old, insert new
- **UPSERT**: Validate structure, get existing objects, verify same KGEntity URI, delete old graph via grouping URIs, insert new

**KGFrames Endpoint (`/kgframes`):**
- **CREATE**: Verify complete frame graph structure (frame→slot via Edge_hasKGSlot, frame→frame via Edge_hasKGFrame if applicable)
- **CREATE**: Verify complete frame graph structure (frame→slot, frame→frame if applicable)
- **CREATE**: Verify NO object URIs exist as subjects in the graph
- **UPDATE**: Validate new graph structure, get existing objects via grouping URI, compare URI sets (must match exactly), delete old, insert new
- **UPSERT**: Validate structure, get existing objects, verify same KGFrame URI, delete old graph via grouping URIs, insert new

#### **Sub-Endpoints: Contextual Operations**
- Operate within existing parent graphs
- Validate relationships to parent objects
- Maintain referential integrity with existing graph structure

## ✅ **TASK #7 COMPLETED: Sub-Endpoint Operations Implementation**

**Status: 100% COMPLETE - All 13/13 Tests Passing (100% Success Rate)**

### **Achievements:**

1. **✅ `/kgentities/kgframes` Sub-Endpoint** - Complete implementation
   - `create_entity_frames()` - Creates frames within entity context with Edge_hasEntityKGFrame relationships
   - `get_entity_frames()` - Retrieves frames connected to entity via SPARQL edge queries
   - `delete_entity_frames()` - Deletes frames and associated components from entity
   - Operation modes: create/update/upsert with proper validation and atomic operations

2. **✅ `/kgframes/kgslots` Sub-Endpoint** - Complete implementation
   - `create_frame_slots()` - Creates slots within frame context with Edge_hasKGSlot relationships
   - `get_frame_slots()` - Retrieves slots connected to frame with optional kGSlotType filtering
   - `delete_frame_slots()` - Deletes specific slots from frame with referential integrity
   - Batch operations with atomic success/rollback capability

3. **✅ Entity-Frame Edge Relationships** - Perfect implementation
   - Edge_hasEntityKGFrame objects created and stored correctly
   - SPARQL queries find entity→frame relationships via edges
   - Proper edge validation for update/delete operations
   - Grouping URI management for efficient graph operations

4. **✅ VitalSigns Integration** - Complete success
   - RDF triple generation with proper N-Triples format
   - Clean bracket handling (no double angle brackets)
   - Type URI resolution working (rdf:type and vitaltype triples)
   - Single object JSON-LD wrapping in graph arrays for consistency

5. **✅ Comprehensive Test Coverage** - All scenarios working
   - Create operations with validation and edge creation
   - Get operations with SPARQL edge traversal
   - Delete operations with referential integrity
   - VitalSigns property object handling (12/12 tests passing)
   - Concrete slot value preservation
   - Enhanced graph operations with complete data retrieval

### **Implementation Details:**

```python
# Key Sub-Endpoint Methods Implemented:

# /kgentities/kgframes operations
- create_entity_frames(space_id, graph_id, entity_uri, document, operation_mode)
- get_entity_frames(space_id, graph_id, entity_uri) -> JsonLdDocument
- delete_entity_frames(space_id, graph_id, entity_uri, frame_uris)

# /kgframes/kgslots operations  
- create_frame_slots(space_id, graph_id, frame_uri, document, operation_mode)
- get_frame_slots(space_id, graph_id, frame_uri, kGSlotType=None) -> JsonLdDocument
- delete_frame_slots(space_id, graph_id, frame_uri, slot_uris)

# Edge Relationship Management:
- _create_entity_frame_edges() - Creates Edge_hasEntityKGFrame relationships
- _get_entity_frame_edge() - Validates specific entity-frame connections
- SPARQL queries using proper edge traversal patterns
- Atomic operations with rollback capability
```

### **Technical Breakthroughs:**

1. **SPARQL Edge Queries** - Proper entity→frame relationship traversal:
   ```sparql
   SELECT ?frame ?prop ?value WHERE {
       GRAPH <graph_id> {
           ?edge a haley:Edge_hasEntityKGFrame ;
                 vital:hasEdgeSource <entity_uri> ;
                 vital:hasEdgeDestination ?frame .
           ?frame ?prop ?value .
       }
   }
   ```

2. **RDF Triple Formatting** - Clean N-Triples generation:
   ```
   <subject> <predicate> <object> .
   <subject> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <type> .
   ```

3. **JSON-LD Single Object Handling** - Consistent graph array format:
   ```python
   # Single objects wrapped in graph array for JsonLdDocument consistency
   if 'graph' not in jsonld_data and 'id' in jsonld_data:
       jsonld_data = {'@context': context, 'graph': [object_data]}
   ```

### **Test Results:**
```
🎉 All 13/13 sub-endpoint tests passed!
✅ PASS Create Entity Frames (1 frame created with edge relationships)
✅ PASS Get Entity Frames (1 frame retrieved via SPARQL edge query)
✅ PASS Create Frame Slots (1 slot created with edge relationships)
✅ PASS Get Frame Slots (4 slots retrieved, filtering working)
✅ PASS Delete Operations (frames and slots deleted with referential integrity)
✅ PASS VitalSigns Integration (6/6 integration tests passed)
✅ PASS Property Object Handling (12/12 property tests passed)
✅ PASS Enhanced Graph Operations (complete data retrieval working)
✅ PASS Concrete Slot Values (value preservation verified)
```

### **Files Modified:**
- `/vitalgraph/mock/client/endpoint/mock_kgentities_endpoint.py` - Added complete sub-endpoint operations
- `/vitalgraph/mock/client/endpoint/mock_kgframes_endpoint.py` - Added complete sub-endpoint operations  
- `/vitalgraph_mock_client_test/test_kg_endpoint_enhancements.py` - Comprehensive test suite
- `/vitalgraph/model/kgframes_model.py` - Response models for sub-endpoint operations

**Sub-endpoint operations are now fully functional and production-ready with 100% test coverage!**

## ✅ **TASK #8 COMPLETED: Mock Query Implementation for KGEntities and KGFrames**

**Status: 100% COMPLETE - All Query Functionality Implemented with Sorting Support**

### **Achievements:**

1. **✅ Enhanced SPARQL Query Builder** - Complete sorting support added
   - Added `SortCriteria` dataclass with support for multi-level sorting
   - Enhanced `EntityQueryCriteria` and `FrameQueryCriteria` with `sort_criteria` field
   - New methods: `build_entity_query_sparql_with_sorting()`, `build_frame_query_sparql_with_sorting()`
   - Support for `frame_slot`, `entity_frame_slot`, and `property` sorting types
   - Priority-based multi-level sorting (primary, secondary, tertiary)

2. **✅ Mock Endpoint Integration** - Complete query method implementation
   - `MockKGEntitiesEndpoint.query_entities()` - Enhanced with sorting support
   - `MockKGFramesEndpoint.query_frames()` - Complete new implementation with sorting
   - Pydantic ↔ Dataclass conversion functions for seamless integration
   - Backward compatibility maintained with existing query patterns

3. **✅ Enhanced Request/Response Models** - Type-safe query interfaces
   - `EntityQueryRequest/Response` models enhanced with `SortCriteria`
   - `FrameQueryRequest/Response` models enhanced with `SortCriteria`
   - Complete model validation and serialization support

4. **✅ Comprehensive Testing** - All functionality verified
   - 5 integration tests passed: Models, conversion, builder, scenarios
   - SPARQL query generation working correctly for all criteria types
   - Multi-level sorting with proper ORDER BY clause generation

### **CRITICAL ISSUE IDENTIFIED: VitalSigns Object Integration Required**

**Problem:** Current implementation uses mock JSON-LD data instead of proper VitalSigns graph objects with correct relationships and edge structures.

**Impact:** Test data doesn't reflect real-world usage patterns with instantiated VitalSigns objects like KGEntity, KGFrame, slot subclasses, and proper Edge relationships.

## 🔄 **TASK #9: VitalSigns Query Implementation Restart**

**Status: PENDING - Complete Query Implementation with Real VitalSigns Objects**

### **Objective:**
Restart the query implementation to ensure proper integration with real VitalSigns graph objects, including instantiated KGEntity, KGFrame, slot subclasses, and proper Edge relationships. The current implementation works with SPARQL generation but needs to be tested and validated with actual VitalSigns object data.

### **Critical Requirements:**

#### **1. VitalSigns Object Data Creation**
- **Real Object Instantiation**:
  ```python
  # Create proper VitalSigns objects
  customer = KGEntity()
  customer.URI = "http://example.com/customer1"
  customer.name = "Premium Customer Alpha"
  customer.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#CustomerEntity"
  
  transaction_frame = KGFrame()
  transaction_frame.URI = "http://example.com/transaction1"
  transaction_frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#FinancialTransactionFrame"
  
  amount_slot = KGDoubleSlot()
  amount_slot.URI = "http://example.com/amount1"
  amount_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#AmountSlot"
  amount_slot.doubleSlotValue = 1500.00  # Python property name
  
  date_slot = KGDateTimeSlot()
  date_slot.URI = "http://example.com/date1"
  date_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#DateSlot"
  date_slot.dateTimeSlotValue = "2023-06-15T10:30:00Z"  # Python property name
  
  status_slot = KGTextSlot()
  status_slot.URI = "http://example.com/status1"
  status_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#StatusSlot"
  status_slot.textSlotValue = "completed"  # Python property name
  ```

- **Proper Edge Relationships**:
  ```python
  # Create Edge_hasKGFrame to connect entity to frame
  entity_frame_edge = Edge_hasKGFrame()
  entity_frame_edge.URI = "http://example.com/edge/entity_frame1"
  entity_frame_edge.edgeSource = customer.URI
  entity_frame_edge.edgeDestination = transaction_frame.URI
  
  # Create Edge_hasKGSlot to connect frame to slots
  frame_amount_edge = Edge_hasKGSlot()
  frame_amount_edge.URI = "http://example.com/edge/frame_amount1"
  frame_amount_edge.edgeSource = transaction_frame.URI
  frame_amount_edge.edgeDestination = amount_slot.URI
  ```

#### **2. VitalSigns Slot Subclass Integration**
- **Slot Type Mapping**:
  ```python
  SLOT_TYPE_MAPPING = {
      "http://vital.ai/ontology/haley-ai-kg#AmountSlot": KGDoubleSlot,
      "http://vital.ai/ontology/haley-ai-kg#DateSlot": KGDateTimeSlot,
      "http://vital.ai/ontology/haley-ai-kg#StatusSlot": KGTextSlot,
      "http://vital.ai/ontology/haley-ai-kg#TypeSlot": KGTextSlot,
      "http://vital.ai/ontology/haley-ai-kg#CountSlot": KGIntegerSlot,
      "http://vital.ai/ontology/haley-ai-kg#ActiveSlot": KGBooleanSlot
  }
  ```

- **Value Property Access**:
  ```python
  # Proper value access based on slot type (Python VitalSigns object properties)
  if isinstance(slot, KGDoubleSlot):
      value = slot.doubleSlotValue  # Python property name
  elif isinstance(slot, KGDateTimeSlot):
      value = slot.dateTimeSlotValue  # Python property name
  elif isinstance(slot, KGTextSlot):
      value = slot.textSlotValue  # Python property name
  elif isinstance(slot, KGIntegerSlot):
      value = slot.integerSlotValue  # Python property name
  elif isinstance(slot, KGBooleanSlot):
      value = slot.booleanSlotValue  # Python property name
  ```

- **CRITICAL: Python vs RDF Property Name Mapping**:
  ```python
  # Python VitalSigns Objects use short property names:
  slot.textSlotValue = "purchase"
  slot.doubleSlotValue = 1500.00
  slot.dateTimeSlotValue = "2023-06-15T10:30:00Z"
  
  # But in RDF/SPARQL, these become full URI properties:
  # haley:hasTextSlotValue "purchase"
  # haley:hasDoubleSlotValue 1500.00
  # haley:hasDateTimeSlotValue "2023-06-15T10:30:00Z"
  ```

- **SPARQL Query Property Mapping**:
  ```sparql
  # Use full RDF property URIs in SPARQL queries:
  ?slot haley:hasTextSlotValue ?textValue .
  ?slot haley:hasDoubleSlotValue ?doubleValue .
  ?slot haley:hasDateTimeSlotValue ?dateTimeValue .
  ?slot haley:hasIntegerSlotValue ?integerValue .
  ?slot haley:hasBooleanSlotValue ?booleanValue .
  ```

#### **3. Test Data Creation with VitalSigns Objects**
- **Comprehensive Test Dataset**:
  ```python
  def create_vitalsigns_test_data():
      """Create proper VitalSigns graph objects for testing."""
      
      # Create 5 customer entities
      customers = []
      for i in range(5):
          customer = KGEntity()
          customer.URI = f"http://example.com/customer{i+1}"
          customer.name = f"Customer {i+1}"
          customer.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#CustomerEntity"
          customers.append(customer)
      
      # Create 4 transaction frames per customer (20 total)
      frames = []
      slots = []
      edges = []
      
      for customer in customers:
          for j in range(4):
              # Create transaction frame
              frame = KGFrame()
              frame.URI = f"{customer.URI}/transaction{j+1}"
              frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#FinancialTransactionFrame"
              frames.append(frame)
              
              # Create entity-frame edge
              edge = Edge_hasKGFrame()
              edge.URI = f"{customer.URI}/edge/frame{j+1}"
              edge.edgeSource = customer.URI
              edge.edgeDestination = frame.URI
              edges.append(edge)
              
              # Create slots for frame
              amount_slot = KGDoubleSlot()
              amount_slot.URI = f"{frame.URI}/amount"
              amount_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#AmountSlot"
              amount_slot.doubleSlotValue = random.uniform(100.0, 5000.0)  # Python property name
              slots.append(amount_slot)
              
              # Create frame-slot edge
              slot_edge = Edge_hasKGSlot()
              slot_edge.URI = f"{frame.URI}/edge/amount"
              slot_edge.edgeSource = frame.URI
              slot_edge.edgeDestination = amount_slot.URI
              edges.append(slot_edge)
      
      return customers + frames + slots + edges
  ```

#### **4. Query Criteria Testing with Real Data**
- **Text Contains Queries**:
  ```python
  def test_entity_query_contains_text():
      """Test entity query with contains text criteria using real VitalSigns objects."""
      
      # Create test data with VitalSigns objects
      test_objects = create_vitalsigns_test_data()
      
      # Load into triple store
      store = setup_triple_store_with_vitalsigns_objects(test_objects)
      
      # Create query criteria
      criteria = EntityQueryCriteria(
          search_string="Premium",
          entity_type="http://vital.ai/ontology/haley-ai-kg#CustomerEntity",
          sort_criteria=[
              SortCriteria(
                  sort_type="property",
                  property_uri="http://vital.ai/ontology/vital-core#name",
                  sort_order="asc",
                  priority=1
              )
          ]
      )
      
      # Execute query
      response = entity_endpoint.query_entities(space_id, graph_id, EntityQueryRequest(criteria=criteria))
      
      # Verify results
      assert len(response.entity_uris) > 0
      assert all("Premium" in get_entity_name(uri) for uri in response.entity_uris)
  ```

- **Numeric Comparison Queries**:
  ```python
  def test_entity_query_amount_greater_than():
      """Test entity query with amount > threshold using real slot values."""
      
      criteria = EntityQueryCriteria(
          entity_type="http://vital.ai/ontology/haley-ai-kg#CustomerEntity",
          frame_type="http://vital.ai/ontology/haley-ai-kg#FinancialTransactionFrame",
          slot_criteria=[
              SlotCriteria(
                  slot_type="http://vital.ai/ontology/haley-ai-kg#AmountSlot",
                  value=1000.0,
                  comparator="gt"
              )
          ],
          sort_criteria=[
              SortCriteria(
                  sort_type="entity_frame_slot",
                  frame_type="http://vital.ai/ontology/haley-ai-kg#FinancialTransactionFrame",
                  slot_type="http://vital.ai/ontology/haley-ai-kg#AmountSlot",
                  sort_order="desc",
                  priority=1
              )
          ]
      )
      
      response = entity_endpoint.query_entities(space_id, graph_id, EntityQueryRequest(criteria=criteria))
      
      # Verify all returned entities have transactions > $1000
      for entity_uri in response.entity_uris:
          max_amount = get_max_transaction_amount(entity_uri)
          assert max_amount > 1000.0
  ```

- **Date Range Queries**:
  ```python
  def test_entity_query_date_range():
      """Test entity query with date range (between) using real datetime values."""
      
      criteria = EntityQueryCriteria(
          entity_type="http://vital.ai/ontology/haley-ai-kg#CustomerEntity",
          frame_type="http://vital.ai/ontology/haley-ai-kg#FinancialTransactionFrame",
          slot_criteria=[
              SlotCriteria(
                  slot_type="http://vital.ai/ontology/haley-ai-kg#DateSlot",
                  value="2023-07-01T00:00:00Z",
                  comparator="gte"
              ),
              SlotCriteria(
                  slot_type="http://vital.ai/ontology/haley-ai-kg#DateSlot",
                  value="2023-08-31T23:59:59Z",
                  comparator="lte"
              )
          ]
      )
      
      response = entity_endpoint.query_entities(space_id, graph_id, EntityQueryRequest(criteria=criteria))
      
      # Verify all returned entities have transactions in July-August 2023
      for entity_uri in response.entity_uris:
          transaction_dates = get_entity_transaction_dates(entity_uri)
          assert any(is_date_in_range(date, "2023-07-01", "2023-08-31") for date in transaction_dates)
  ```

#### **5. SPARQL Query Validation with VitalSigns Data**
- **Edge Relationship Queries**:
  ```sparql
  # Entity query with frame slot filtering
  SELECT DISTINCT ?entity WHERE {
      GRAPH <graph_id> {
          ?entity a haley:KGEntity .
          ?entity vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#CustomerEntity> .
          
          # Find frames connected to entity via Edge_hasKGFrame
          ?entity_frame_edge a haley:Edge_hasKGFrame .
          ?entity_frame_edge vital:hasEdgeSource ?entity .
          ?entity_frame_edge vital:hasEdgeDestination ?frame .
          
          # Filter frames by type
          ?frame vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#FinancialTransactionFrame> .
          
          # Find slots connected to frame via Edge_hasKGSlot
          ?frame_slot_edge a haley:Edge_hasKGSlot .
          ?frame_slot_edge vital:hasEdgeSource ?frame .
          ?frame_slot_edge vital:hasEdgeDestination ?slot .
          
          # Filter slots by type and value
          ?slot vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#AmountSlot> .
          ?slot haley:doubleValue ?amount .
          FILTER(?amount > 1000.0)
      }
  }
  ORDER BY DESC(?amount)
  ```

#### **6. Mock Endpoint Integration with VitalSigns**
- **Enhanced Data Loading**:
  ```python
  def setup_mock_endpoints_with_vitalsigns_data():
      """Set up mock endpoints with real VitalSigns test data."""
      
      # Create VitalSigns test objects
      test_objects = create_vitalsigns_test_data()
      
      # Convert to JSON-LD using VitalSigns native methods
      jsonld_objects = []
      for obj in test_objects:
          obj_dict = obj.to_json()  # VitalSigns native conversion
          jsonld_objects.append(obj_dict)
      
      # Create JSON-LD document
      jsonld_doc = JsonLdDocument(
          context=get_vitalsigns_context(),
          graph=jsonld_objects
      )
      
      # Load into triple store
      space.triple_store.load_jsonld_document(jsonld_doc.model_dump())
      
      return entity_endpoint, frame_endpoint, space_id, graph_id
  ```

#### **7. Comprehensive Test Suite with VitalSigns Objects**
- **Test Categories**:
  1. **VitalSigns Object Creation Tests** - Verify proper object instantiation
  2. **Edge Relationship Tests** - Verify proper Edge_hasKGFrame and Edge_hasKGSlot creation
  3. **Slot Value Tests** - Verify proper slot value setting and retrieval
  4. **Query Execution Tests** - Verify queries work with real VitalSigns data
  5. **Sorting Tests** - Verify sorting works with real slot values
  6. **Filtering Tests** - Verify filtering works with real slot values
  7. **Complex Criteria Tests** - Verify complex queries with multiple criteria
  8. **Performance Tests** - Verify performance with moderate datasets (50-100 objects)

#### **8. Expected Test Results**
- **Entity Queries**: Find customers with specific criteria using real VitalSigns objects
- **Frame Queries**: Find transaction frames with specific criteria using real slot values
- **Sorting**: Verify proper ordering by slot values (dates, amounts, text)
- **Filtering**: Verify proper filtering by slot values (contains, gt, eq, between)
- **Complex Queries**: Verify multi-criteria queries work with real data relationships

### **Implementation Priority:**
1. **Phase 1**: Create VitalSigns test data creation functions
2. **Phase 2**: Enhance mock endpoint data loading with VitalSigns objects
3. **Phase 3**: Create comprehensive test suite with real object queries
4. **Phase 4**: Validate SPARQL generation and execution with VitalSigns data
5. **Phase 5**: Performance testing with moderate datasets

### **Success Criteria:**
- All query types work with real VitalSigns objects
- Proper Edge relationship traversal in SPARQL queries
- Correct slot value filtering and sorting
- Performance acceptable for development-scale datasets (50-100 entities/frames)
- Complete test coverage for all query scenarios

### **Implementation Requirements:**

#### **1. Mock Query Method Implementation**
- **MockKGEntitiesEndpoint**:
  - `query_entities(space_id, graph_id, query_request: EntityQueryRequest) -> EntityQueryResponse`
  - Integration with `KGQueryCriteriaBuilder.build_entity_query_sparql()`
  - Support for entity type, search string, frame type, and slot criteria filtering
  - Proper pagination and result formatting

- **MockKGFramesEndpoint**:
  - `query_frames(space_id, graph_id, query_request: FrameQueryRequest) -> FrameQueryResponse`
  - Integration with `KGQueryCriteriaBuilder.build_frame_query_sparql()`
  - Support for frame type, search string, entity type, and slot criteria filtering
  - Proper pagination and result formatting

#### **2. SPARQL Query Builder Integration**
- **Enhanced SPARQL Execution**:
  - Integrate existing `KGQueryCriteriaBuilder` with mock endpoint SPARQL execution
  - Handle complex criteria combinations (entity type + slot criteria + search string + sorting)
  - Support all comparison operators: `eq`, `ne`, `gt`, `lt`, `gte`, `lte`, `contains`, `exists`
  - Generate ORDER BY clauses for multi-level sorting
  - Proper URI handling and result parsing

- **SPARQL Sorting Implementation**:
  - **Frame Sorting SPARQL Pattern**:
    ```sparql
    SELECT DISTINCT ?frame WHERE {
        GRAPH <graph_id> {
            ?frame a <frame_type> .
            ?frame haley:hasKGSlot ?slot .
            ?slot a <slot_type> .
            ?slot haley:hasTextSlotValue ?sort_value .
            # Additional filtering criteria...
        }
    }
    ORDER BY DESC(?sort_value) ASC(?secondary_sort)
    ```
  
  - **Entity Sorting SPARQL Pattern**:
    ```sparql
    SELECT DISTINCT ?entity WHERE {
        GRAPH <graph_id> {
            ?entity a <entity_type> .
            ?entity haley:hasKGFrame ?frame .
            ?frame a <frame_type> .
            ?frame haley:hasKGSlot ?slot .
            ?slot a <slot_type> .
            ?slot haley:hasTextSlotValue ?sort_value .
            # Additional filtering criteria...
        }
    }
    ORDER BY ASC(?sort_value) DESC(?secondary_sort)
    ```

- **Data Type Handling for Sorting**:
  - **Date/DateTime**: Convert to sortable format, handle timezone considerations
  - **Numeric**: Direct numeric sorting (integers, floats, decimals)
  - **Text**: Lexicographic sorting with case sensitivity options
  - **Boolean**: Standard boolean ordering (false < true)
  - **URI**: Lexicographic sorting by URI string

#### **3. Query Criteria Support**
- **Entity Query Criteria**:
  - `search_string` - Search in entity name/label properties
  - `entity_type` - Filter by specific entity type URI
  - `frame_type` - Find entities that have frames of specific type
  - `slot_criteria` - Complex slot-based filtering with value comparisons
  - `sort_criteria` - Multi-level sorting by frame/slot combinations

- **Frame Query Criteria**:
  - `search_string` - Search in frame name/label properties
  - `frame_type` - Filter by specific frame type URI
  - `entity_type` - Find frames that belong to entities of specific type
  - `slot_criteria` - Complex slot-based filtering with value comparisons
  - `sort_criteria` - Multi-level sorting by slot values

#### **3a. Sorting Criteria Definitions**
- **SortCriteria Model**:
  ```python
  class SortCriteria:
      sort_type: str  # "frame_slot" | "entity_frame_slot" | "property"
      frame_type: Optional[str]  # Required for entity_frame_slot sorting
      slot_type: str  # Slot type URI for sorting
      sort_order: str = "asc"  # "asc" | "desc"
      priority: int = 1  # 1=primary, 2=secondary, 3=tertiary, etc.
  ```

- **Frame Sorting Examples**:
  - Sort financial transaction frames by transaction date (descending)
  - Sort document frames by creation timestamp (ascending)
  - Sort contact frames by last interaction date (descending)

- **Entity Sorting Examples**:
  - Sort entities by "marketing info" frame → "initial contact date" slot → date value
  - Sort entities by "financial data" frame → "account balance" slot → numeric value
  - Sort entities by "profile info" frame → "last name" slot → alphabetical value

#### **4. Advanced Query Features**
- **Slot-Based Filtering**:
  - Support for multiple slot criteria with AND logic
  - Value comparison operators for different data types
  - Existence checks for slot presence
  - Type-specific slot filtering (text, integer, boolean slots)

- **Query Result Sorting**:
  - **Frame Sorting**: Sort frames by specific slot values within the frame
    - Sort by slot type + slot value (e.g., transaction date, creation timestamp)
    - Support for multiple data types: date, numeric, text, boolean
    - Ascending/descending sort order specification
  - **Entity Sorting**: Sort entities by slot values within their associated frames
    - Sort by frame type + slot type + slot value combination
    - Example: Sort entities by "marketing info" frame type → "initial contact date" slot type → date value
    - Cross-frame sorting capabilities for entities with multiple frames
  - **Multi-Level Sorting**: Support for primary and secondary sort criteria
    - Primary sort: Main sorting criterion (e.g., transaction date)
    - Secondary sort: Tie-breaker criterion (e.g., transaction amount)
    - Tertiary sort: Additional tie-breaker (e.g., entity name)

- **Performance Optimization**:
  - Efficient SPARQL query generation with ORDER BY clauses
  - Proper indexing considerations for pyoxigraph
  - Result caching for repeated queries
  - Pagination optimization with sorted results

#### **5. Test Implementation**
- **Comprehensive Test Coverage**:

##### **5a. Basic Query Functionality Tests**
```python
# Test file: test_query_basic_functionality.py

class TestBasicQueryFunctionality:
    def test_query_entities_no_criteria(self):
        """Test entity query with no filtering criteria - returns all entities"""
        
    def test_query_frames_no_criteria(self):
        """Test frame query with no filtering criteria - returns all frames"""
        
    def test_query_entities_by_type(self):
        """Test entity filtering by entity type"""
        
    def test_query_frames_by_type(self):
        """Test frame filtering by frame type"""
        
    def test_query_entities_by_search_string(self):
        """Test entity search by name/label text search"""
        
    def test_query_frames_by_search_string(self):
        """Test frame search by name/label text search"""
        
    def test_query_pagination_basic(self):
        """Test basic pagination without sorting"""
        
    def test_query_empty_results(self):
        """Test queries that return no results"""
        
    def test_query_invalid_space_or_graph(self):
        """Test error handling for invalid space/graph IDs"""
```

##### **5b. Slot-Based Filtering Tests**
```python
# Test file: test_query_slot_filtering.py

class TestSlotBasedFiltering:
    def test_entity_query_by_frame_slot_text_equals(self):
        """Test entity filtering by text slot value (exact match)"""
        
    def test_entity_query_by_frame_slot_text_contains(self):
        """Test entity filtering by text slot value (contains)"""
        
    def test_entity_query_by_frame_slot_integer_comparison(self):
        """Test entity filtering by integer slot (gt, lt, gte, lte, eq, ne)"""
        
    def test_entity_query_by_frame_slot_boolean(self):
        """Test entity filtering by boolean slot value"""
        
    def test_frame_query_by_slot_text_equals(self):
        """Test frame filtering by text slot value (exact match)"""
        
    def test_frame_query_by_slot_integer_range(self):
        """Test frame filtering by integer slot range (gte + lte)"""
        
    def test_multiple_slot_criteria_and_logic(self):
        """Test filtering with multiple slot criteria (AND logic)"""
        
    def test_slot_existence_filtering(self):
        """Test filtering by slot existence (exists comparator)"""
        
    def test_slot_filtering_missing_slots(self):
        """Test behavior when queried slots don't exist"""
```

##### **5c. Complex Criteria Combination Tests**
```python
# Test file: test_query_complex_criteria.py

class TestComplexCriteriaCombinations:
    def test_entity_type_plus_frame_type_filtering(self):
        """Test entity filtering by both entity type and frame type"""
        
    def test_search_string_plus_slot_criteria(self):
        """Test combining text search with slot-based filtering"""
        
    def test_entity_type_plus_multiple_slot_criteria(self):
        """Test entity type filtering with multiple slot conditions"""
        
    def test_frame_type_plus_entity_type_plus_slots(self):
        """Test frame queries with entity type, frame type, and slot criteria"""
        
    def test_complex_financial_transaction_query(self):
        """Real-world test: Find high-value transactions for premium customers"""
        # Entity type: Customer, Frame type: Transaction, Amount > 10000, Status = "completed"
        
    def test_complex_employee_search_query(self):
        """Real-world test: Find senior employees in specific departments"""
        # Entity type: Employee, Frame type: Employment, Department = "Engineering", Years > 5
```

##### **5d. Sorting Functionality Tests**
```python
# Test file: test_query_sorting.py

class TestQuerySorting:
    def test_frame_sorting_by_date_slot_desc(self):
        """Test sorting frames by date slot (newest first)"""
        
    def test_frame_sorting_by_numeric_slot_asc(self):
        """Test sorting frames by numeric slot (lowest first)"""
        
    def test_frame_sorting_by_text_slot_alphabetical(self):
        """Test sorting frames by text slot (alphabetical)"""
        
    def test_entity_sorting_by_frame_slot_date(self):
        """Test sorting entities by date slot in associated frame"""
        
    def test_entity_sorting_by_frame_slot_numeric(self):
        """Test sorting entities by numeric slot in associated frame"""
        
    def test_multi_level_sorting_primary_secondary(self):
        """Test two-level sorting (primary + secondary criteria)"""
        
    def test_multi_level_sorting_three_levels(self):
        """Test three-level sorting (primary + secondary + tertiary)"""
        
    def test_sorting_mixed_data_types(self):
        """Test sorting hierarchy with different data types"""
        
    def test_sorting_with_null_values(self):
        """Test sorting behavior when some entities/frames have missing sort slots"""
        
    def test_sorting_ascending_vs_descending(self):
        """Test explicit ascending and descending sort orders"""
        
    def test_financial_transaction_sorting(self):
        """Real-world test: Sort transactions by date desc, then amount desc"""
        
    def test_customer_contact_sorting(self):
        """Real-world test: Sort customers by initial contact date, then last name"""
        
    def test_employee_department_sorting(self):
        """Real-world test: Sort employees by department, hire date, last name"""
```

##### **5e. Pagination with Sorting Tests**
```python
# Test file: test_query_pagination_sorting.py

class TestPaginationWithSorting:
    def test_sorted_pagination_consistency(self):
        """Test that sort order is maintained across paginated results"""
        
    def test_sorted_pagination_page_boundaries(self):
        """Test correct handling of page boundaries with sorting"""
        
    def test_moderate_dataset_sorted_pagination(self):
        """Test pagination performance with moderate sorted datasets (50-100 items)"""
        
    def test_multi_level_sort_pagination(self):
        """Test pagination with complex multi-level sorting"""
        
    def test_sorted_pagination_edge_cases(self):
        """Test pagination with equal sort values (tie-breaking)"""
```

##### **5f. Performance and Edge Case Tests**
```python
# Test file: test_query_performance_edge_cases.py

class TestQueryPerformanceAndEdgeCases:
    def test_moderate_dataset_query_performance(self):
        """Test query performance with 100-200 entities/frames (development scale)"""
        
    def test_complex_query_performance(self):
        """Test performance with multiple criteria + sorting + pagination"""
        
    def test_query_with_no_matching_results(self):
        """Test queries that match no entities/frames"""
        
    def test_query_with_invalid_sort_criteria(self):
        """Test error handling for invalid sort slot types"""
        
    def test_query_with_invalid_filter_criteria(self):
        """Test error handling for invalid filter slot types"""
        
    def test_query_with_malformed_criteria(self):
        """Test error handling for malformed query requests"""
        
    def test_query_timeout_handling(self):
        """Test behavior with very complex queries that might timeout"""
        
    def test_concurrent_query_execution(self):
        """Test multiple simultaneous queries for thread safety"""
```

##### **5g. Real-World Scenario Tests**
```python
# Test file: test_query_real_world_scenarios.py

class TestRealWorldQueryScenarios:
    def test_financial_dashboard_queries(self):
        """Test queries for financial dashboard: transactions, accounts, balances"""
        
    def test_customer_relationship_queries(self):
        """Test CRM-style queries: customer search, contact history, preferences"""
        
    def test_inventory_management_queries(self):
        """Test inventory queries: product search, stock levels, categories"""
        
    def test_employee_directory_queries(self):
        """Test HR queries: employee search, department listings, skill matching"""
        
    def test_document_management_queries(self):
        """Test document queries: content search, metadata filtering, date ranges"""
        
    def test_analytics_aggregation_queries(self):
        """Test analytical queries: grouping, counting, statistical operations"""
```

##### **5h. SPARQL Generation and Execution Tests**
```python
# Test file: test_query_sparql_generation.py

class TestSPARQLGenerationAndExecution:
    def test_sparql_generation_basic_entity_query(self):
        """Test SPARQL generation for basic entity queries"""
        
    def test_sparql_generation_basic_frame_query(self):
        """Test SPARQL generation for basic frame queries"""
        
    def test_sparql_generation_with_sorting(self):
        """Test SPARQL ORDER BY clause generation"""
        
    def test_sparql_generation_with_pagination(self):
        """Test SPARQL LIMIT/OFFSET generation"""
        
    def test_sparql_generation_complex_criteria(self):
        """Test SPARQL generation for complex filter combinations"""
        
    def test_sparql_execution_result_parsing(self):
        """Test parsing of SPARQL query results into response objects"""
        
    def test_sparql_error_handling(self):
        """Test handling of SPARQL syntax errors and execution failures"""
```

### **Implementation Details:**

```python
# Key Methods to Implement:

# MockKGEntitiesEndpoint
def query_entities(self, space_id: str, graph_id: str, query_request: EntityQueryRequest) -> EntityQueryResponse:
    """Execute criteria-based entity search using SPARQL query builder."""
    # 1. Get space from space manager
    # 2. Build SPARQL query using KGQueryCriteriaBuilder
    # 3. Execute query against pyoxigraph
    # 4. Parse results and return entity URIs with pagination
    pass

# MockKGFramesEndpoint  
def query_frames(self, space_id: str, graph_id: str, query_request: FrameQueryRequest) -> FrameQueryResponse:
    """Execute criteria-based frame search using SPARQL query builder."""
    # 1. Get space from space manager
    # 2. Build SPARQL query using KGQueryCriteriaBuilder
    # 3. Execute query against pyoxigraph
    # 4. Parse results and return frame URIs with pagination
    pass

# Enhanced SPARQL Integration
def _execute_criteria_query(self, space, criteria, graph_id: str, page_size: int, offset: int) -> List[str]:
    """Execute criteria-based SPARQL query and return matching URIs."""
    # 1. Initialize KGQueryCriteriaBuilder
    # 2. Build appropriate SPARQL query (entity or frame)
    # 3. Execute query using space.query_sparql()
    # 4. Extract URIs from results
    # 5. Apply pagination
    pass
```

### **Expected Query Examples:**

```python
# Entity Query Examples with Sorting:
entity_query = EntityQueryRequest(
    criteria=EntityQueryCriteria(
        search_string="customer",
        entity_type="http://vital.ai/ontology/haley-ai-kg#CustomerEntityType",
        frame_type="http://vital.ai/ontology/haley-ai-kg#MarketingInfoFrameType",
        slot_criteria=[
            SlotCriteria(
                slot_type="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                value="premium",
                comparator="contains"
            )
        ],
        sort_criteria=[
            SortCriteria(
                sort_type="entity_frame_slot",
                frame_type="http://vital.ai/ontology/haley-ai-kg#MarketingInfoFrameType",
                slot_type="http://vital.ai/ontology/haley-ai-kg#InitialContactDateSlot",
                sort_order="desc",
                priority=1  # Primary sort by initial contact date (newest first)
            ),
            SortCriteria(
                sort_type="entity_frame_slot", 
                frame_type="http://vital.ai/ontology/haley-ai-kg#ProfileInfoFrameType",
                slot_type="http://vital.ai/ontology/haley-ai-kg#LastNameSlot",
                sort_order="asc",
                priority=2  # Secondary sort by last name (alphabetical)
            )
        ]
    ),
    page_size=20,
    offset=0
)

# Frame Query Examples with Sorting:
frame_query = FrameQueryRequest(
    criteria=FrameQueryCriteria(
        search_string="transaction",
        frame_type="http://vital.ai/ontology/haley-ai-kg#FinancialTransactionFrameType",
        entity_type="http://vital.ai/ontology/haley-ai-kg#AccountEntityType",
        slot_criteria=[
            SlotCriteria(
                slot_type="http://vital.ai/ontology/haley-ai-kg#TransactionAmountSlot",
                value=1000,
                comparator="gte"
            )
        ],
        sort_criteria=[
            SortCriteria(
                sort_type="frame_slot",
                slot_type="http://vital.ai/ontology/haley-ai-kg#TransactionDateSlot",
                sort_order="desc",
                priority=1  # Primary sort by transaction date (newest first)
            ),
            SortCriteria(
                sort_type="frame_slot",
                slot_type="http://vital.ai/ontology/haley-ai-kg#TransactionAmountSlot", 
                sort_order="desc",
                priority=2  # Secondary sort by amount (highest first)
            )
        ]
    ),
    page_size=10,
    offset=0
)

# Complex Multi-Level Entity Sorting Example:
complex_entity_query = EntityQueryRequest(
    criteria=EntityQueryCriteria(
        entity_type="http://vital.ai/ontology/haley-ai-kg#EmployeeEntityType",
        sort_criteria=[
            SortCriteria(
                sort_type="entity_frame_slot",
                frame_type="http://vital.ai/ontology/haley-ai-kg#EmploymentInfoFrameType",
                slot_type="http://vital.ai/ontology/haley-ai-kg#DepartmentSlot",
                sort_order="asc",
                priority=1  # Primary: Group by department
            ),
            SortCriteria(
                sort_type="entity_frame_slot",
                frame_type="http://vital.ai/ontology/haley-ai-kg#EmploymentInfoFrameType", 
                slot_type="http://vital.ai/ontology/haley-ai-kg#HireDateSlot",
                sort_order="asc",
                priority=2  # Secondary: Order by hire date within department
            ),
            SortCriteria(
                sort_type="entity_frame_slot",
                frame_type="http://vital.ai/ontology/haley-ai-kg#PersonalInfoFrameType",
                slot_type="http://vital.ai/ontology/haley-ai-kg#LastNameSlot",
                sort_order="asc", 
                priority=3  # Tertiary: Alphabetical by last name
            )
        ]
    ),
    page_size=50,
    offset=0
)
```

### **Implementation Plan:**

#### **Phase 0: Existing SPARQL Query Functionality Review**
1. **Analyze Existing SPARQL Infrastructure**:
   ```bash
   # Review existing query functionality in:
   /Users/hadfield/Local/vital-git/vital-graph/vitalgraph/sparql/
   
   # Key files to analyze:
   - Query builder implementations
   - SPARQL generation utilities  
   - Existing query criteria handling
   - Current sorting/filtering capabilities
   - Integration patterns with mock endpoints
   ```

2. **Assessment Tasks**:
   ```python
   # Evaluate existing functionality:
   - Document current query capabilities and limitations
   - Identify reusable components vs. components needing replacement
   - Map existing SPARQL patterns to new query requirements
   - Assess compatibility with sorting and complex criteria
   - Determine integration approach (enhance vs. replace)
   ```

3. **Integration Decision Matrix**:
   ```python
   # For each existing component, determine:
   - ENHANCE: Can be extended to support new requirements
   - REPLACE: Needs complete rewrite for new functionality  
   - INTEGRATE: Can be used as-is with new components
   - DEPRECATE: No longer needed with new implementation
   ```

#### **Phase 1: Test-Driven Development Setup**
1. **Create Test Infrastructure**:
   ```bash
   # Create test files with comprehensive test cases
   vitalgraph_mock_client_test/test_query_basic_functionality.py
   vitalgraph_mock_client_test/test_query_slot_filtering.py
   vitalgraph_mock_client_test/test_query_complex_criteria.py
   vitalgraph_mock_client_test/test_query_sorting.py
   vitalgraph_mock_client_test/test_query_pagination_sorting.py
   vitalgraph_mock_client_test/test_query_performance_edge_cases.py
   vitalgraph_mock_client_test/test_query_real_world_scenarios.py
   vitalgraph_mock_client_test/test_query_sparql_generation.py
   ```

2. **Create Test Data Setup**:
   ```python
   # Small generated test data for development
   vitalgraph_mock_client_test/query_test_data_setup.py
   - create_small_test_entities() # 5-10 entities with varied data
   - create_test_financial_transactions() # 10-15 transactions with different amounts/dates
   - create_test_employees() # 8-12 employees across 3-4 departments
   - create_test_customers() # 6-10 customers with contact history
   - generate_test_data_for_sorting() # Specific data for sorting edge cases
   - generate_test_data_for_filtering() # Specific data for filter combinations
   
   # Example small test data approach:
   # - 8 entities (2 customers, 3 employees, 2 accounts, 1 product)
   # - 12 frames (contact info, employment, transactions, etc.)
   # - 25 slots (names, dates, amounts, statuses, etc.)
   # - Designed to test all query patterns with minimal data
   ```

#### **Phase 2: Query Model Enhancement**
1. **Update Query Models** (if needed):
   ```python
   # Enhance existing models in vitalgraph/model/
   - EntityQueryRequest/EntityQueryCriteria - Add sort_criteria field
   - FrameQueryRequest/FrameQueryCriteria - Add sort_criteria field  
   - SortCriteria - New model for sorting specifications
   - EntityQueryResponse/FrameQueryResponse - Ensure proper response format
   ```

#### **Phase 3: SPARQL Query Builder Enhancement**
1. **Enhance KGQueryCriteriaBuilder**:
   ```python
   # Add sorting support to existing query builder
   vitalgraph/query/kg_query_criteria_builder.py
   - build_entity_query_sparql_with_sorting()
   - build_frame_query_sparql_with_sorting()
   - _generate_order_by_clause()
   - _handle_multi_level_sorting()
   ```

#### **Phase 4: Mock Endpoint Implementation**
1. **MockKGEntitiesEndpoint**:
   ```python
   # Add query method to existing endpoint
   vitalgraph/mock/client/endpoint/mock_kgentities_endpoint.py
   - query_entities() - Main query method
   - _execute_entity_criteria_query() - SPARQL execution helper
   - _parse_entity_query_results() - Result parsing helper
   ```

2. **MockKGFramesEndpoint**:
   ```python
   # Add query method to existing endpoint  
   vitalgraph/mock/client/endpoint/mock_kgframes_endpoint.py
   - query_frames() - Main query method
   - _execute_frame_criteria_query() - SPARQL execution helper
   - _parse_frame_query_results() - Result parsing helper
   ```

#### **Phase 5: Integration and Testing**
1. **Run Test Suite**: Execute all test categories progressively
2. **Performance Optimization**: Based on test results
3. **Documentation**: Update API documentation with query examples

### **Files to Modify:**

#### **New Test Files** (8 files):
1. **`test_query_basic_functionality.py`** - Basic query functionality tests
2. **`test_query_slot_filtering.py`** - Slot-based filtering tests
3. **`test_query_complex_criteria.py`** - Complex criteria combination tests
4. **`test_query_sorting.py`** - Sorting functionality tests
5. **`test_query_pagination_sorting.py`** - Pagination with sorting tests
6. **`test_query_performance_edge_cases.py`** - Performance and edge case tests
7. **`test_query_real_world_scenarios.py`** - Real-world scenario tests
8. **`test_query_sparql_generation.py`** - SPARQL generation and execution tests

#### **Enhanced Existing Files**:
1. **`MockKGEntitiesEndpoint`** - Add `query_entities()` method with SPARQL integration
2. **`MockKGFramesEndpoint`** - Add `query_frames()` method with SPARQL integration  
3. **`KGQueryCriteriaBuilder`** - Enhance with sorting support for mock endpoint integration
4. **Query Models** - Add sorting criteria models (if not already present)

#### **New Utility Files**:
1. **`query_test_data_setup.py`** - Shared test data creation utilities

### **Success Criteria:**
- ✅ `query_entities()` method working with all criteria types and sorting
- ✅ `query_frames()` method working with all criteria types and sorting
- ✅ Complex slot-based filtering functional
- ✅ **Multi-level sorting functionality working correctly**:
  - Single and multi-level sorting by slot values
  - Frame-level and entity-level sorting patterns
  - Support for all data types (date, numeric, text, boolean, URI)
  - Proper handling of ascending/descending sort orders
  - Correct priority-based sorting (primary, secondary, tertiary)
- ✅ Pagination with sorted results (maintaining sort order across pages)
- ✅ Performance acceptable for typical query loads with sorting
- ✅ Comprehensive test coverage for all query and sorting scenarios
- ✅ Integration with existing VitalSigns and pyoxigraph infrastructure
- ✅ **SPARQL ORDER BY generation working correctly for complex sort criteria**

### **Implementation Timeline:**

#### **Week 1: Existing Code Review and Test Infrastructure Setup**
- **Day 1**: Comprehensive review of existing SPARQL query functionality in `/vitalgraph/sparql/`
- **Day 2**: Create integration decision matrix and determine enhance vs. replace strategy
- **Day 3**: Create all 8 test files with comprehensive test cases
- **Day 4**: Implement `query_test_data_setup.py` with small generated test data (5-15 items per category)
- **Day 5**: Set up test runner and create specific test data generators for edge cases

#### **Week 2: Core Implementation**  
- **Day 1-2**: Enhance query models and SPARQL query builder with sorting support
- **Day 3-4**: Implement `query_entities()` method in MockKGEntitiesEndpoint
- **Day 5**: Implement `query_frames()` method in MockKGFramesEndpoint

#### **Week 3: Testing and Optimization**
- **Day 1-2**: Run basic functionality and slot filtering tests
- **Day 3**: Run complex criteria and sorting tests
- **Day 4**: Run pagination and performance tests  
- **Day 5**: Run real-world scenario tests and optimization

#### **Week 4: Integration and Documentation**
- **Day 1-2**: SPARQL generation testing and debugging
- **Day 3-4**: Performance optimization and edge case handling
- **Day 5**: Documentation and final integration testing

### **Priority: HIGH** - Completes the query functionality gap in the KG endpoint implementation

### **Existing Code Analysis Requirements:**

#### **Files to Review in `/vitalgraph/sparql/`:**
```bash
# Directory structure analysis needed:
vitalgraph/sparql/
├── query_builders/          # Existing query construction logic
├── criteria_handlers/       # Current filtering implementations  
├── sparql_generators/       # SPARQL string generation utilities
├── result_parsers/         # Query result processing
└── integration_helpers/    # Mock endpoint integration utilities

# Key questions to answer:
1. What query patterns are already supported?
2. How is SPARQL generation currently handled?
3. What filtering/sorting capabilities exist?
4. How do mock endpoints currently integrate with SPARQL?
5. What components can be reused vs. need replacement?
```

#### **Integration Assessment Criteria:**
```python
# For each existing component, evaluate:
class ComponentAssessment:
    supports_sorting: bool           # Can handle ORDER BY clauses
    supports_complex_filtering: bool # Can handle multiple slot criteria
    supports_pagination: bool        # Can handle LIMIT/OFFSET
    mock_endpoint_compatible: bool   # Works with current mock endpoints
    extensible_architecture: bool    # Can be enhanced vs. needs rewrite
    performance_adequate: bool       # Meets performance requirements
    
    decision: str  # "ENHANCE" | "REPLACE" | "INTEGRATE" | "DEPRECATE"
    rationale: str # Explanation for decision
```

### **Expected Deliverables:**
- ✅ **Existing code analysis report** with integration decision matrix
- ✅ **8 comprehensive test files** covering all query scenarios
- ✅ **Enhanced query models** with sorting criteria support
- ✅ **Enhanced/Replaced SPARQL query builder** with ORDER BY generation
- ✅ **Complete query_entities() implementation** with filtering and sorting
- ✅ **Complete query_frames() implementation** with filtering and sorting
- ✅ **Performance benchmarks** for query operations
- ✅ **Real-world query examples** demonstrating practical usage
- ✅ **Comprehensive documentation** with query API reference

---

## 🚀 **TASK #9: Mock Endpoint Code Refactoring and Commonality Analysis**

**Status: PENDING - Code Quality and Maintainability Enhancement**

### **Objective:**
Analyze MockKGEntitiesEndpoint and MockKGFramesEndpoint implementations to identify common functionality and helper functions that can be refactored into shared utility modules. This will improve code maintainability, reduce duplication, and create reusable components for future endpoint implementations.

### **Problem Identified:**
Both MockKGEntitiesEndpoint and MockKGFramesEndpoint have grown significantly in functionality and likely contain:
- Duplicated helper methods for SPARQL operations
- Common VitalSigns object handling patterns
- Shared JSON-LD conversion logic
- Similar error handling and validation patterns
- Repeated pyoxigraph interaction code
- Common grouping URI management functionality

### **Implementation Approach:**

#### **Phase 1: Code Analysis and Commonality Identification**
- **Comprehensive Code Review**:
  - Analyze all methods in MockKGEntitiesEndpoint (~2600+ lines)
  - Analyze all methods in MockKGFramesEndpoint 
  - Identify duplicate or near-duplicate functionality
  - Map common patterns and helper method opportunities

- **Function Categorization**:
  - **SPARQL Operations**: Query building, execution, result parsing
  - **VitalSigns Integration**: Object creation, conversion, property handling
  - **Graph Operations**: Grouping URI management, graph traversal
  - **Validation Logic**: Structure validation, edge relationship validation
  - **Data Transformation**: RDF triple handling, JSON-LD conversion
  - **Error Handling**: Exception management, logging patterns

#### **Phase 2: Refactoring Proposal and Approval**
- **Incremental Refactoring Plan**:
  - Propose specific functions for refactoring on a function-by-function basis
  - Identify target utility modules in `/vitalgraph/utils/` or new modules
  - Present refactoring proposals for approval before implementation
  - Ensure backward compatibility and test coverage

- **Proposed Utility Modules**:
  - `vitalgraph/utils/sparql_helpers.py` - Common SPARQL operations
  - `vitalgraph/utils/vitalsigns_helpers.py` - VitalSigns object utilities
  - `vitalgraph/utils/graph_operations.py` - Graph traversal and grouping URI utilities
  - `vitalgraph/utils/rdf_conversion.py` - RDF/JSON-LD transformation utilities
  - `vitalgraph/utils/endpoint_validation.py` - Common validation patterns

#### **Phase 3: Function-by-Function Refactoring**
- **Systematic Refactoring Process**:
  1. **Identify candidate function** for refactoring
  2. **Propose refactoring** with target location and interface
  3. **Get approval** before proceeding with changes
  4. **Extract function** to utility module with proper interface
  5. **Update both endpoints** to use shared utility
  6. **Verify tests pass** and functionality unchanged
  7. **Repeat** for next function

### **Candidate Functions for Refactoring Analysis:**

#### **SPARQL Operations (High Priority)**
```python
# Likely candidates from both endpoints:
- _execute_sparql_query()
- _build_sparql_query_with_pagination()
- _parse_sparql_results()
- _handle_sparql_errors()
- _execute_update_sparql()
```

#### **VitalSigns Integration (High Priority)**
```python
# Likely candidates from both endpoints:
- _convert_triples_to_vitalsigns_objects()
- _create_vitalsigns_objects_from_jsonld()
- _objects_to_jsonld_document()
- _handle_vitalsigns_property_casting()
- _validate_vitalsigns_object_types()
```

#### **Graph Operations (Medium Priority)**
```python
# Likely candidates from both endpoints:
- _set_grouping_uris()
- _get_objects_by_grouping_uri()
- _validate_graph_structure()
- _collect_graph_components()
- _handle_edge_relationships()
```

#### **Data Transformation (Medium Priority)**
```python
# Likely candidates from both endpoints:
- _format_rdf_triples()
- _handle_pyoxigraph_results()
- _convert_jsonld_to_triples()
- _format_object_values()
- _handle_uri_formatting()
```

#### **Validation and Error Handling (Low Priority)**
```python
# Likely candidates from both endpoints:
- _validate_operation_mode()
- _handle_validation_errors()
- _log_method_calls()
- _format_error_responses()
- _validate_required_parameters()
```

### **Refactoring Benefits:**

#### **Code Quality Improvements**
- **Reduced Duplication**: Eliminate duplicate code between endpoints
- **Improved Maintainability**: Single source of truth for common operations
- **Enhanced Testability**: Isolated utility functions easier to unit test
- **Better Documentation**: Centralized documentation for common patterns

#### **Development Efficiency**
- **Faster Development**: Reusable utilities speed up new endpoint development
- **Consistent Patterns**: Standardized approaches across all endpoints
- **Easier Debugging**: Centralized logic easier to troubleshoot
- **Simplified Testing**: Shared utilities reduce test complexity

#### **Architecture Benefits**
- **Modular Design**: Clear separation of concerns
- **Reusability**: Utilities available for future endpoint implementations
- **Scalability**: Easier to extend and modify common functionality
- **Standards Compliance**: Consistent implementation patterns

### **Implementation Process:**

#### **Step 1: Analysis Phase (1-2 days)**
```bash
# Analyze both endpoint files for commonality
1. Review MockKGEntitiesEndpoint methods and patterns
2. Review MockKGFramesEndpoint methods and patterns  
3. Create commonality matrix and refactoring candidates list
4. Prioritize functions by impact and complexity
5. Document findings in kg_refactor_mock_endpoint_plan.md
```

#### **Step 2: Proposal Phase (Per Function)**
```bash
# For each candidate function:
1. Propose specific refactoring approach
2. Define target utility module and interface
3. Identify any breaking changes or dependencies
4. Document proposal in kg_refactor_mock_endpoint_plan.md
5. Get approval before proceeding
```

#### **Step 3: Refactoring Phase (Per Function)**
```bash
# For each approved function:
1. Create/enhance target utility module
2. Extract function with proper interface design
3. Update both endpoints to use shared utility
4. Run comprehensive tests to verify functionality
5. Update documentation and type hints
6. Mark as completed in kg_refactor_mock_endpoint_plan.md
```

### **Dedicated Planning Document:**
**`/Users/hadfield/Local/vital-git/vital-graph/planning/kg_refactor_mock_endpoint_plan.md`**

This dedicated planning file will be used to:
- **Track Analysis Results**: Document all identified common functionality
- **Manage Refactoring Queue**: Prioritized list of functions to refactor
- **Proposal Documentation**: Detailed refactoring proposals for each function
- **Progress Tracking**: Status of each refactoring effort (Proposed → Approved → In Progress → Completed)
- **Target File Mapping**: Clear mapping of functions to target utility files
- **Dependencies**: Track interdependencies between refactoring efforts
- **Testing Notes**: Document test requirements and validation steps

#### **Planning File Structure:**
```markdown
# Mock Endpoint Refactoring Plan

## Analysis Results
- [Function commonality matrix]
- [Duplication assessment]
- [Priority rankings]

## Refactoring Queue
- [Prioritized list of candidate functions]

## Active Proposals
- [Functions currently proposed for refactoring]

## Approved for Refactoring
- [Functions approved and ready for implementation]

## In Progress
- [Functions currently being refactored]

## Completed Refactoring
- [Successfully refactored functions]

## Target Utility Files
- [Mapping of functions to target utility modules]
```

### **Success Criteria:**
- ✅ Comprehensive analysis of both endpoint implementations completed
- ✅ Refactoring candidates identified and prioritized
- ✅ Incremental refactoring process established
- ✅ First batch of high-priority functions successfully refactored
- ✅ Code duplication significantly reduced
- ✅ All existing tests continue to pass
- ✅ New utility modules properly documented and tested
- ✅ Development velocity improved for future endpoint work

### **Files to Analyze:**
1. **MockKGEntitiesEndpoint** (~2600+ lines) - Complete method analysis
2. **MockKGFramesEndpoint** - Complete method analysis
3. **MockBaseEndpoint** - Existing shared functionality review
4. **Existing utils modules** - Current utility landscape assessment

### **Planning and Tracking Files:**
1. **`kg_refactor_mock_endpoint_plan.md`** - Dedicated refactoring planning and progress tracking
2. **`kg_update_plan.md`** - High-level task status and coordination

### **Target Utility Locations:**
- `/vitalgraph/utils/sparql_helpers.py`
- `/vitalgraph/utils/vitalsigns_helpers.py`
- `/vitalgraph/utils/graph_operations.py`
- `/vitalgraph/utils/rdf_conversion.py`
- `/vitalgraph/utils/endpoint_validation.py`

### **Priority: MEDIUM** - Code quality improvement that will benefit long-term maintainability and development velocity

---

## 🚀 **NEXT TASKS: Implementation Roadmap**

## ✅ **TASK #3 COMPLETED: KGEntities Endpoint Enhancement**

**Status: 100% COMPLETE - Entity Lifecycle Management Test Passing**

### **Achievements:**

1. **✅ Operation Mode Support** - Complete CREATE/UPDATE/UPSERT implementation
   - CREATE mode: Verifies no objects exist, validates structure, creates entity graph
   - UPDATE mode: Verifies entity exists, validates structure, replaces atomically with rollback
   - UPSERT mode: Creates or updates with structure validation and URI consistency

2. **✅ Entity Graph Structure Validation** - Complete validation system
   - Validates exactly 1 entity with associated frames, slots, and edges
   - Validates entity→frame and frame→slot connection integrity
   - Collects all URIs for atomic operations
   - Proper error reporting for structure violations

3. **✅ Parent URI Support** - Optional parent object validation
   - Validates parent existence (entity or frame)
   - Validates proper connection edges between parent and entity
   - Supports both entity-to-entity and frame-to-entity relationships

4. **✅ Atomic Operations with Rollback** - Enterprise-level data integrity
   - Backup existing entity graphs before modifications
   - Atomic delete and insert operations
   - Rollback capability on any failure
   - Proper grouping URI management (`hasKGGraphURI`)

5. **✅ Architectural Consistency** - Perfect alignment with KGFrames patterns
   - Same operation mode semantics as MockKGFramesEndpoint
   - Consistent error handling and validation patterns
   - Same helper method structure and naming conventions

### **Implementation Details:**

```python
# Enhanced update_kgentities method signature:
def update_kgentities(self, space_id: str, graph_id: str, document: JsonLdDocument, 
                     operation_mode: str = "update", parent_uri: str = None) -> EntityUpdateResponse

# Key Helper Methods Implemented:
- _validate_parent_object() - Parent existence validation
- _validate_entity_graph_structure() - Complete structure validation
- _handle_entity_create_mode() - CREATE mode with existence checks
- _handle_entity_update_mode() - UPDATE mode with atomic replacement
- _handle_entity_upsert_mode() - UPSERT mode with URI consistency
- _object_exists_in_store() - Individual object existence checking
- _entity_exists_in_store() - Entity-specific existence checking
- _get_current_entity_objects() - Current entity graph retrieval
- _validate_parent_connection() - Parent-entity connection validation
- _backup_entity_graph() / _restore_entity_graph_from_backup() - Rollback support
```

### **Test Results:**
```
✅ PASS Entity Operation Modes (CREATE/UPDATE/UPSERT validation working)
✅ PASS Entity Graph Structure Validation (entity→frame→slot integrity)
✅ PASS Atomic Operations (proper grouping URI management)
✅ PASS Error Handling (proper validation and error reporting)
```

### **Files Modified:**
- `/vitalgraph/mock/client/endpoint/mock_kgentities_endpoint.py` - Enhanced with complete lifecycle management
- `/vitalgraph_mock_client_test/test_entity_lifecycle_management.py` - Comprehensive test suite for entity operations

**KGEntities endpoint now has complete architectural parity with KGFrames endpoint!**

## ✅ **TASK #4 COMPLETED: Graph-Level Operations Enhancement**

**Status: 100% COMPLETE - Graph-Level Retrieval Tests Passing**

### **Achievements:**

1. **✅ Entity Graph Retrieval Enhancement** - Complete implementation
   - `get_kgentity()` with `include_entity_graph: bool = False` parameter working
   - Uses existing `hasKGGraphURI` grouping for efficient complete graph retrieval
   - Delegates to `_get_single_entity()` and `_get_entity_with_complete_graph()` helper methods
   - Returns complete entity + frames + slots + edges in single operation

2. **✅ Frame Graph Retrieval Enhancement** - Complete implementation  
   - `get_kgframe()` with `include_frame_graph: bool = False` parameter implemented
   - Added `_get_single_frame()` and `_get_frame_with_complete_graph()` helper methods
   - Uses `hasFrameGraphURI` grouping for efficient frame graph retrieval
   - Returns complete frame + child frames + slots + edges in single operation

3. **✅ Efficient SPARQL Queries** - Optimized graph traversal
   - Leverages existing grouping URI infrastructure (`hasKGGraphURI`, `hasFrameGraphURI`)
   - Single SPARQL query retrieves complete graph structures
   - Clean implementation - no backward compatibility constraints (new application)

4. **✅ Response Model Support** - Complete graph structures in JSON-LD
   - EntityGraphResponse supports both single entity and complete graph
   - JsonLdDocument handles complete graph structures with proper @graph format
   - VitalSigns native JSON-LD conversion maintains object integrity

### **Implementation Details:**

```python
# Enhanced method signatures:
def get_kgentity(self, space_id: str, graph_id: str, uri: str, 
                include_entity_graph: bool = False) -> EntityGraphResponse

def get_kgframe(self, space_id: str, graph_id: str, uri: str, 
               include_frame_graph: bool = False) -> JsonLdDocument

# Key Helper Methods Added:
- _get_single_frame() - Standard frame retrieval
- _get_frame_with_complete_graph() - Complete frame graph using hasFrameGraphURI
- Efficient SPARQL queries using grouping URI patterns
```

### **Test Results:**
```
✅ PASS Entity Graph Retrieval (single vs complete graph working)
✅ PASS Frame Graph Retrieval (single vs complete graph working)  
✅ PASS Efficient SPARQL Queries (grouping URI optimization working)
✅ PASS Clean Implementation (no legacy constraints - new application)
```

### **Benefits Delivered:**
- **Reduced API Calls** - Complete graphs retrieved in single operation
- **Efficient Queries** - Leverages existing grouping URI infrastructure  
- **Clean Architecture** - No legacy constraints, optimal design for new application
- **Consistent Patterns** - Same enhancement approach for both entities and frames

### **Files Modified:**
- `/vitalgraph/mock/client/endpoint/mock_kgframes_endpoint.py` - Enhanced with complete frame graph retrieval
- `/vitalgraph_mock_client_test/test_graph_level_retrieval.py` - Comprehensive test suite for graph-level operations

**Both KGEntities and KGFrames endpoints now support efficient complete graph retrieval!**

## ✅ **Task #5: Frame-Level Grouping URI Implementation - COMPLETE**

### **Status: 100% COMPLETE - All Tests Passing**

### **Objective:**
Implement frame-level grouping URIs (`frameGraphURI`) to enable proper frame graph retrieval with `include_frame_graph=True` parameter. This addresses the identified issue where frame graphs cannot be efficiently retrieved due to missing frame-level grouping.

### **Problem Identified:**
During Task #4 implementation, it was discovered that frame graphs need dual grouping URI assignment:
1. **Entity-level grouping** (`kGGraphURI`) - for entity graph retrieval
2. **Frame-level grouping** (`frameGraphURI`) - for frame graph retrieval

Without frame-level grouping URIs, the `include_frame_graph=True` parameter cannot efficiently retrieve complete frame structures.

### **Implementation Requirements:**

#### **1. Dual Grouping URI Assignment**
- **Entity operations**: Set both `kGGraphURI` (entity URI) and `frameGraphURI` (frame URI) on frame components
- **Frame operations**: Set `frameGraphURI` (frame URI) on frame components
- **Maintain backward compatibility** with existing `kGGraphURI` usage

#### **2. Frame Structure Analysis**
- **Analyze entity graphs** to identify frame membership for each object
- **Group frame components** (frame + slots + edges) by frame URI
- **Enable targeted frame retrieval** using frame-specific grouping URIs

#### **3. Enhanced Retrieval Operations**
- **Update `get_kgentity()`** to support frame-level retrieval within entity graphs
- **Update `get_kgframe()`** to use frame-level grouping for efficient retrieval
- **Maintain entity-level retrieval** for complete entity graphs

#### **4. SPARQL Query Updates**
- **Frame graph queries** use `?obj haley:hasFrameGraphURI <frame_uri>`
- **Entity graph queries** continue using `?obj haley:hasKGGraphURI <entity_uri>`
- **Dual queries** for complete entity graphs with frame-level detail

### **Files to Modify:**
1. **MockKGEntitiesEndpoint**: Add dual grouping URI assignment logic
2. **MockKGFramesEndpoint**: Ensure frame-level grouping is properly set
3. **Validation utilities**: Add frame structure analysis functions
4. **SPARQL queries**: Update to support frame-level grouping URI patterns
5. **Test cases**: Verify dual grouping URI functionality

### **✅ Achievements Completed:**
- ✅ **Dual Grouping URI Assignment** - Both `kGGraphURI` and `frameGraphURI` properly assigned
- ✅ **Frame Structure Analysis** - `analyze_frame_structure_for_grouping()` function implemented
- ✅ **Enhanced Retrieval Operations** - Frame-level retrieval working correctly
- ✅ **SPARQL Query Updates** - Frame-level grouping URI patterns implemented
- ✅ **Test Verification** - `test_dual_grouping_uris.py` passing with 2/2 tests
- ✅ **Efficient frame graph retrieval** using frame-level grouping URIs
- ✅ **Backward compatibility** maintained with existing entity-level grouping
- ✅ **Proper frame isolation** for targeted frame operations
- ✅ **Enhanced query performance** for frame-specific operations

### **Files Modified:**
1. **MockKGEntitiesEndpoint**: Updated to use `_set_dual_grouping_uris()` instead of `_set_entity_grouping_uris()`
2. **Validation utilities**: Added frame structure analysis functions in `validation_utils.py`
3. **SPARQL queries**: Updated to support frame-level grouping URI patterns
4. **Test cases**: Created `test_dual_grouping_uris.py` to verify dual grouping functionality

### **Priority: COMPLETE** ✅

---

## ✅ **Task #6: Test Data Edge Model Updates - COMPLETE**

### **Status: 100% COMPLETE - All Tests Passing**

### **Objective:**
Update all existing test data and test cases to use the corrected edge model with proper `Edge_hasEntityKGFrame`, `Edge_hasKGFrame`, and `Edge_hasKGSlot` relationships.

### **Problem Identified:**
Following the edge model corrections, all existing test data uses incorrect edge types:
- Tests currently use `Edge_hasKGFrame` for entity→frame connections
- Should use `Edge_hasEntityKGFrame` for entity→frame connections
- Should use `Edge_hasKGFrame` only for frame→frame (parent-child) connections

### **Implementation Requirements:**

#### **1. Test Data Updates**
- **Entity test data**: Replace `Edge_hasKGFrame` (entity→frame) with `Edge_hasEntityKGFrame`
- **Frame test data**: Update frame→frame relationships to use `Edge_hasKGFrame` correctly
- **Slot test data**: Ensure `Edge_hasKGSlot` usage is correct for frame→slot relationships
- **JSON-LD documents**: Update `@type` fields to use correct edge class names

#### **2. Test Case Validation**
- **Edge type validation**: Verify tests check for correct edge types in validation
- **Graph structure tests**: Update expected edge types in assertions
- **Mock data generation**: Fix edge instantiation in test utilities
- **Import statements**: Update edge class imports in all test files

#### **3. Test Files to Update**
- **`test_entity_lifecycle_management.py`**: Update entity→frame edge types
- **`test_data_lifecycle_management.py`**: Update edge type validations
- **`test_graph_level_retrieval.py`**: Update graph structure expectations
- **Mock endpoint tests**: Update edge type handling in endpoint tests
- **Integration tests**: Verify correct edge relationships in full workflows

#### **4. Validation Updates**
- **Structure validation tests**: Update to expect correct edge types
- **Error message tests**: Update expected validation error messages
- **Graph traversal tests**: Update edge type filtering logic
- **SPARQL query tests**: Update expected edge types in query results

### **Files to Modify:**
1. **All test files** in `vitalgraph_mock_client_test/`
2. **Mock data utilities** for test data generation
3. **Test validation functions** that check edge types
4. **JSON-LD test documents** with edge type specifications
5. **Test assertions** that verify graph structure

### **✅ Achievements Completed:**
- ✅ **All test files updated** with correct edge model (`Edge_hasEntityKGFrame` for entity→frame)
- ✅ **All tests pass** with corrected edge model
- ✅ **Accurate validation** of graph structures in tests
- ✅ **Consistent edge usage** across all test scenarios
- ✅ **Proper test coverage** for all three edge types
- ✅ **RDF conversion fixes** - Fixed VitalSigns `from_rdf_list` usage and literal formatting
- ✅ **Missing method fixes** - Added `_convert_triples_to_vitalsigns_objects` to MockKGFramesEndpoint

### **Files Modified:**
1. **test_entity_lifecycle_management.py** - Updated to use `Edge_hasEntityKGFrame`
2. **test_graph_level_retrieval.py** - Updated to use `Edge_hasEntityKGFrame`
3. **test_mock_kgentities_enhanced.py** - Updated to use `Edge_hasEntityKGFrame`
4. **test_kg_endpoint_enhancements.py** - Updated imports and comments
5. **test_mock_kgframes_integration.py** - Updated imports
6. **MockKGFramesEndpoint** - Added missing `_convert_triples_to_vitalsigns_objects` method
7. **MockKGEntitiesEndpoint** - Fixed RDF conversion with proper literal formatting

### **Priority: COMPLETE** ✅

### **Implementation Details:**

```python
# Enhanced grouping URI assignment logic needed:
def _set_dual_grouping_uris(self, objects: List[Any], entity_uri: str) -> None:
    """Set both entity-level and frame-level grouping URIs."""
    
    # Step 1: Analyze graph structure to identify frame memberships
    frame_structure = self._analyze_frame_structure(objects)
    
    # Step 2: Set entity-level grouping for all objects
    for obj in objects:
        obj.kGGraphURI = entity_uri
    
    # Step 3: Set frame-level grouping for frame components
    for frame_uri, frame_components in frame_structure.items():
        for component in frame_components:
            component.frameGraphURI = frame_uri

def _analyze_frame_structure(self, objects: List[Any]) -> Dict[str, List[Any]]:
    """Analyze objects to determine frame membership."""
    # Use existing validation logic to identify:
    # - Which objects belong to which frames
    # - Frame → Slot relationships via edges
    # - Frame → Frame relationships (child frames)
    pass
```

**Required Changes:**

1. **MockKGEntitiesEndpoint Enhancement**:
   - Update `_set_entity_grouping_uris()` to also set frame-level grouping
   - Enhance entity graph structure validation to identify frame components
   - Ensure all frame components get proper `hasFrameGraphURI` values

2. **MockKGFramesEndpoint Enhancement**:
   - Update `_set_frame_grouping_uris()` to properly set frame-level grouping
   - Ensure frame graph retrieval uses correct grouping URI queries
   - Handle both standalone frames and frames within entities

3. **Utility Functions**:
   - Enhance existing graph structure validation utilities
   - Create frame membership analysis functions
   - Implement dual grouping URI assignment logic

4. **Testing**:
   - Test frame graph retrieval with proper `hasFrameGraphURI` grouping
   - Verify both entity-level and frame-level grouping work correctly
   - Test mixed scenarios (entities with multiple frames, nested frames)

**Expected Outcome**: Complete graph retrieval working for both entity-level (`include_entity_graph=True`) and frame-level (`include_frame_graph=True`) operations with proper grouping URI implementation.

### **Task #6: Sub-Endpoint Implementation**
**Priority: LOW - New functionality expansion**

**Objective**: Implement contextual sub-endpoints for nested operations using URI parameters.

**Key Components:**
1. **`/kgentities/kgframes?entity_uri={uri}`** - Frame operations within entity context
2. **`/kgframes/kgslots?frame_uri={uri}`** - Slot operations within frame context
3. **`/kgframes/kgframes?parent_frame_uri={uri}`** - Child frame operations within parent frame context
4. **Query Interfaces** - Simple criteria-based filtering with URI parameters

**Implementation Details:**
```python
# Entity Context Operations
class KGEntitiesKGFramesEndpoint:
    def list_entity_frames(self, entity_uri: str, page_size: int = 10, offset: int = 0):
        """List frames within an entity context"""
        
    def create_entity_frame(self, entity_uri: str, document: JsonLdDocument, operation_mode: str = "create"):
        """Create frame within entity context"""
        
    def update_entity_frame(self, entity_uri: str, document: JsonLdDocument, operation_mode: str = "update"):
        """Update frame within entity context"""

# Frame Context Operations  
class KGFramesKGFramesEndpoint:
    def list_child_frames(self, parent_frame_uri: str, page_size: int = 10, offset: int = 0):
        """List child frames within parent frame context"""
        
    def create_child_frame(self, parent_frame_uri: str, document: JsonLdDocument, operation_mode: str = "create"):
        """Create child frame within parent frame context"""

class KGFramesKGSlotsEndpoint:
    def list_frame_slots(self, frame_uri: str, page_size: int = 10, offset: int = 0):
        """List slots within frame context"""
        
    def create_frame_slot(self, frame_uri: str, document: JsonLdDocument, operation_mode: str = "create"):
        """Create slot within frame context"""
```

**API Examples:**
```bash
# List frames within an entity
GET /kgentities/kgframes?entity_uri=http://vital.ai/app/entity123

# Create a new frame within an entity context
POST /kgentities/kgframes?entity_uri=http://vital.ai/app/entity123
Content-Type: application/json
{
  "@context": {...},
  "@graph": [frame_data...]
}

# List slots within a frame
GET /kgframes/kgslots?frame_uri=http://vital.ai/app/frame456

# Create child frame within parent frame
POST /kgframes/kgframes?parent_frame_uri=http://vital.ai/app/parent_frame789
Content-Type: application/json
{
  "@context": {...}, 
  "@graph": [child_frame_data...]
}
```

**Benefits:**
- **URI Safety** - No need to URL-encode complex URIs in paths
- **REST Compliance** - Follows proper REST conventions for resource identification
- **Query Flexibility** - Easy to add additional filtering parameters
- **Backward Compatibility** - Doesn't conflict with existing endpoint structures

## Requirements Summary

### Core Properties for Graph Operations
- **hasKGGraphURI**: Identifies complete entity graphs (entities + frames + slots + all the connecting edges) - *Property exists in ontology, implemented in MockKGEntitiesEndpoint*
- **hasFrameGraphURI**: Identifies complete frame graphs (frames + slots + frame-to-frame edges) - *Property exists in ontology, ✅ **IMPLEMENTED** in MockKGFramesEndpoint*

### Enhanced Operations

#### KGEntities Endpoint Extensions
1. **GET kgentities**: Add `include_entity_graph` parameter to retrieve entire entity graph
2. **POST/PUT kgentities**: Support creating/updating entire entity graphs (frames and slots)
3. **DELETE kgentities**: Add `delete_entity_graph` parameter to delete entire entity graph vs just entity

#### KGFrames Endpoint Extensions
1. **GET kgframes**: Add `include_frame_graph` parameter to retrieve entire frame graph
2. **POST/PUT/DELETE kgframes**: Handle frame graphs including edges and slots

#### New Sub-Endpoints
1. **kgentities/kgframes**: CRUD operations on frames within entity context
2. **kgframes/kgslots**: CRUD operations on slots within frame context
3. **kgframes/kgframes**: CRUD operations on child frames within parent frame context
4. **kgentities/query**: Simple query interface for entities with criteria-based filtering
5. **kgframes/query**: Simple query interface for frames with criteria-based filtering

## Current Architecture Analysis

Based on the codebase analysis, the current structure includes:

### Client Layer
- `KGEntitiesEndpoint` - Basic CRUD operations for entities
- `KGFramesEndpoint` - Basic CRUD operations for frames
- Both support single URI and batch operations

### Mock Implementation
- `MockKGEntitiesEndpoint` - VitalSigns + pyoxigraph implementation
- `MockKGFramesEndpoint` - VitalSigns + pyoxigraph implementation
- `MockBaseEndpoint` - Common functionality with VitalSigns integration

### Server Layer
- Server endpoints with FastAPI routes
- Support for JSON-LD document processing
- Authentication and validation

## 🚧 CRITICAL CONSIDERATIONS

Based on comprehensive implementation experience and ontology analysis, the following requirements are **MANDATORY** for all new development:

### **Edge-based Relationships (CRITICAL)**
- **NEVER use direct properties** for entity-frame-slot relationships
- **ALWAYS use Edge classes**: `Edge_hasEntityKGFrame` (entity→frame), `Edge_hasKGFrame` (frame→frame), `Edge_hasKGSlot` (frame→slot)
- **Property names**: Use `edgeSource`/`edgeDestination` (NOT `hasEdgeSource`/`hasEdgeDestination`)
- **String casting required**: `edge.edgeSource = str(entity.URI)`, `edge.edgeDestination = str(frame.URI)`

### **VitalSigns Native Integration (CRITICAL)**
- **JSON-LD conversion**: Use `GraphObject.to_jsonld_list(objects)` (NOT `vitalsigns.to_jsonld_list()`)
- **Object creation**: Use `vitalsigns.from_jsonld_list(document)` for JSON-LD to VitalSigns objects
- **Property access**: Cast Property objects: `str(obj.textSlotValue)`, `int(obj.integerSlotValue)`
- **Type detection**: Use `isinstance(obj, KGEntity)` (NOT string matching)
- **NO manual JSON-LD context creation** - always use VitalSigns native methods

### **Property Name Corrections (CRITICAL)**
- **Slot value properties are type-specific**: `textSlotValue`, `integerSlotValue`, `booleanSlotValue` (NOT generic `hasSlotValue`)
- **Entity properties**: `hasKGEntityType`, `hasKGraphDescription` (NOT `hasKGEntityTypeURI`)
- **Frame properties**: `hasKGFrameTypeDescription`, `hasFrameSequence`, `hasKGraphDescription`
- **All URI assignments**: Must use `str()` casting for Pydantic validation

### **SPARQL Query Patterns (CRITICAL)**
- **Entity-to-Frame relationships**:
  ```sparql
  ?edge a haley:Edge_hasEntityKGFrame .
  ?edge vital:hasEdgeSource ?entity .
  ?edge vital:hasEdgeDestination ?frame .
  ```
- **Frame-to-Frame relationships** (parent-child):
  ```sparql
  ?edge a haley:Edge_hasKGFrame .
  ?edge vital:hasEdgeSource ?parent_frame .
  ?edge vital:hasEdgeDestination ?child_frame .
  ```
- **Frame-to-Slot relationships**:
  ```sparql
  ?edge a haley:Edge_hasKGSlot .
  ?edge vital:hasEdgeSource ?frame .
  ?edge vital:hasEdgeDestination ?slot .
  ```
- **NEVER use non-existent direct properties** like `?entity haley:hasFrame ?frame`

### **Response Model Requirements (CRITICAL)**
- **All response models** must include `message: str` field for Pydantic validation

### **Test Data and Edge Model Updates (CRITICAL)**
- **All existing test data** must be updated to use correct edge types:
  - Replace `Edge_hasKGFrame` (entity→frame) with `Edge_hasEntityKGFrame`
  - Keep `Edge_hasKGFrame` only for frame→frame (parent-child) relationships
  - Ensure `Edge_hasKGSlot` is used correctly for frame→slot relationships
- **Test endpoint validation** must verify correct edge type usage in JSON-LD documents
- **Mock data generation** must instantiate proper edge objects with correct source/destination relationships
- **Validation test cases** must cover all three edge types and their proper usage patterns
- **Graph structure tests** must validate the complete entity→frame→slot hierarchy using correct edges
- **URI handling**: Convert VitalSigns CombinedProperty objects to strings: `str(obj.URI)`
- **Integer parsing**: Handle typed literals properly: `"3"^^<http://www.w3.org/2001/XMLSchema#integer>`
- **JSON-LD structure**: Use proper `@graph` array format in `_objects_to_jsonld_document`

### **Test Implementation Standards (CRITICAL)**
- **Remove pytest dependencies** from all mock client tests
- **Direct test runner pattern**: Use custom test classes with `run_all_tests()` method
- **String casting in tests**: All edge assignments must use `str()` casting
- **Consistent property naming**: All test files must use `edgeSource`/`edgeDestination`
- **VitalSigns integration**: All tests must use `GraphObject.to_jsonld_list()` for conversion

## Implementation Plan

### Phase 1: Client API Extensions

#### 1.1 KGEntitiesEndpoint Enhancements

**New Parameters:**
```python
# GET operations
def get_kgentity(self, space_id: str, graph_id: str, uri: str, 
                include_entity_graph: bool = False) -> Union[EntitiesResponse, JsonLdDocument]

def list_kgentities(self, space_id: str, graph_id: str, 
                   include_entity_graph: bool = False, **kwargs) -> EntitiesResponse

# DELETE operations  
def delete_kgentity(self, space_id: str, graph_id: str, uri: str,
                   delete_entity_graph: bool = False) -> EntityDeleteResponse
```

**New Methods:**
```python
# Frame operations within entity context
def create_entity_frames(self, space_id: str, graph_id: str, entity_uri: str,
                        document: JsonLdDocument) -> FrameCreateResponse

def update_entity_frames(self, space_id: str, graph_id: str, entity_uri: str,
                        document: JsonLdDocument) -> FrameUpdateResponse

def delete_entity_frames(self, space_id: str, graph_id: str, entity_uri: str,
                        frame_uris: List[str]) -> FrameDeleteResponse

def get_entity_frames(self, space_id: str, graph_id: str, entity_uri: str) -> JsonLdDocument
```

#### 1.2 KGFramesEndpoint Enhancements

**New Parameters:**
```python
# GET operations
def get_kgframe(self, space_id: str, graph_id: str, uri: str,
               include_frame_graph: bool = False) -> Union[FramesResponse, JsonLdDocument]

def list_kgframes(self, space_id: str, graph_id: str,
                 include_frame_graph: bool = False, **kwargs) -> FramesResponse
```

**New Methods:**
```python
# Slot operations within frame context
def create_frame_slots(self, space_id: str, graph_id: str, frame_uri: str,
                      document: JsonLdDocument) -> SlotCreateResponse

def update_frame_slots(self, space_id: str, graph_id: str, frame_uri: str,
                      document: JsonLdDocument) -> SlotUpdateResponse

def delete_frame_slots(self, space_id: str, graph_id: str, frame_uri: str,
                      slot_uris: List[str]) -> SlotDeleteResponse

def get_frame_slots(self, space_id: str, graph_id: str, frame_uri: str,
                   slot_type: Optional[Union[str, List[str]]] = None) -> JsonLdDocument
    """
    Get slots for a frame, optionally filtered by slot type(s).
    
    Args:
        slot_type: Single slot type URI or list of slot type URIs
                  Examples:
                  - "http://vital.ai/ontology/haley-ai-kg#KGTextSlot"
                  - ["http://vital.ai/ontology/haley-ai-kg#KGTextSlot", 
                     "http://vital.ai/ontology/haley-ai-kg#KGIntegerSlot"]
    """

# Frame-to-frame operations within frame context
def create_child_frames(self, space_id: str, graph_id: str, parent_frame_uri: str,
                       document: JsonLdDocument) -> FrameCreateResponse

def update_child_frames(self, space_id: str, graph_id: str, parent_frame_uri: str,
                       document: JsonLdDocument) -> FrameUpdateResponse

def delete_child_frames(self, space_id: str, graph_id: str, parent_frame_uri: str,
                       frame_uris: List[str]) -> FrameDeleteResponse

def get_child_frames(self, space_id: str, graph_id: str, parent_frame_uri: str,
                    frame_type: Optional[str] = None) -> JsonLdDocument

def list_child_frames(self, space_id: str, graph_id: str, parent_frame_uri: str,
                     frame_type: Optional[str] = None, page_size: int = 10, 
                     offset: int = 0) -> FramesResponse

# Simple query operations
def query_entities(self, space_id: str, graph_id: str, 
                  query_criteria: Dict[str, Any]) -> EntitiesResponse

def query_frames(self, space_id: str, graph_id: str,
                query_criteria: Dict[str, Any]) -> FramesResponse
```

### Phase 2: Mock Implementation Updates

#### 2.1 MockKGEntitiesEndpoint Enhancements

**Graph Query Implementation:**
```python
def _get_entity_graph_by_kg_graph_uri(self, space, kg_graph_uri: str, graph_id: str) -> List[GraphObject]:
    """Retrieve entire entity graph using hasKGGraphURI property."""
    query = f"""
    PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
    PREFIX vital: <http://vital.ai/ontology/vital-core#>
    
    SELECT ?subject ?predicate ?object WHERE {{
        GRAPH <{graph_id}> {{
            ?subject haley:hasKGGraphURI <{kg_graph_uri}> .
            ?subject ?predicate ?object .
        }}
        UNION
        {{
            # Find frames via Edge_hasKGFrame relationships
            ?entity haley:hasKGGraphURI <{kg_graph_uri}> .
            ?edge a haley:Edge_hasKGFrame .
            ?edge vital:hasEdgeSource ?entity .
            ?edge vital:hasEdgeDestination ?frame .
            ?frame ?predicate ?object .
            BIND(?frame as ?subject)
        }}
        UNION
        {{
            # Find slots via Edge_hasKGSlot relationships
            ?frame haley:hasKGGraphURI <{kg_graph_uri}> .
            ?edge a haley:Edge_hasKGSlot .
            ?edge vital:hasEdgeSource ?frame .
            ?edge vital:hasEdgeDestination ?slot .
            ?slot ?predicate ?object .
            BIND(?slot as ?subject)
        }}
        UNION
        {{
            # Include Edge objects themselves
            ?edge_obj haley:hasKGGraphURI <{kg_graph_uri}> .
            ?edge_obj a ?edge_type .
            FILTER(?edge_type IN (haley:Edge_hasKGFrame, haley:Edge_hasKGSlot, haley:Edge_hasKGEdge))
            ?edge_obj ?predicate ?object .
            BIND(?edge_obj as ?subject)
        }}
    }}
    """
    # Execute query and convert to VitalSigns objects
```

**Entity Graph Validation and Separation:**

*Note: This functionality will be implemented in the new `vitalgraph.sparql` package for SPARQL-related validation and in-memory graph queries.*

```python
# vitalgraph/sparql/graph_validation.py
from typing import Dict, List, Set, Any
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGSlot import KGSlot
from vital_ai_vitalsigns.model.VITAL_Edge import VITAL_Edge

class EntityGraphValidator:
    """Validates and separates entity graphs using Edge-based relationships."""
    
    def __init__(self):
        self.vitalsigns = VitalSigns()
    
    def validate_and_separate_entity_graph(self, jsonld_document: dict) -> Dict[str, Dict]:
        """
        Validate and separate entity graphs from JSON-LD document.
        Uses Edge-based relationship discovery instead of direct properties.
        """
        # Step 1: Convert JSON-LD to VitalSigns objects
        objects = self.vitalsigns.from_jsonld_list(jsonld_document)
        
        # Step 2: Categorize objects using isinstance
        entities = []
        frames = []
        slots = []
        edges = []
        
        for obj in objects:
            if isinstance(obj, KGEntity):
                entities.append(obj)
            elif isinstance(obj, KGFrame):
                frames.append(obj)
            elif isinstance(obj, KGSlot):  # Catches all slot subclasses
                slots.append(obj)
            elif isinstance(obj, VITAL_Edge):
                edges.append(obj)
        
        # Step 3: Build entity graphs using Edge relationships
        entity_graphs = {}
        for entity in entities:
            entity_uri = str(entity.URI)
            entity_graph = self._build_entity_graph_from_edges(
                entity, frames, slots, edges
            )
            entity_graphs[entity_uri] = entity_graph
        
        # Step 4: Validate completeness and detect orphaned objects
        self._validate_graph_completeness(entity_graphs, objects)
        
        return entity_graphs
    
    def _build_entity_graph_from_edges(self, entity: KGEntity, frames: List[KGFrame], 
                                     slots: List[KGSlot], edges: List[VITAL_Edge]) -> Dict:
        """Build entity graph using Edge-based relationship discovery."""
        entity_uri = str(entity.URI)
        entity_graph = {
            'entities': [entity],
            'frames': [],
            'slots': [],
            'edges': []
        }
        
        # Find frames connected to this entity via Edge_hasKGFrame
        entity_frames = self._find_entity_frames(entity_uri, frames, edges)
        entity_graph['frames'].extend(entity_frames)
        
        # Find slots connected to entity frames via Edge_hasKGSlot
        for frame in entity_frames:
            frame_uri = str(frame.URI)
            frame_slots = self._find_frame_slots(frame_uri, slots, edges)
            entity_graph['slots'].extend(frame_slots)
        
        # Find all edges related to this entity graph
        related_edges = self._find_related_edges(entity_uri, entity_frames, edges)
        entity_graph['edges'].extend(related_edges)
        
        return entity_graph
    
    def _find_entity_frames(self, entity_uri: str, frames: List[KGFrame], 
                           edges: List[VITAL_Edge]) -> List[KGFrame]:
        """Find frames connected to entity via Edge_hasKGFrame relationships."""
        connected_frames = []
        
        for edge in edges:
            # Check if this is an Edge_hasKGFrame connecting to our entity
            if (hasattr(edge, 'hasEdgeSource') and hasattr(edge, 'hasEdgeDestination') and
                str(edge.hasEdgeSource) == entity_uri and 
                type(edge).__name__ == 'Edge_hasKGFrame'):
                
                # Find the destination frame
                destination_uri = str(edge.hasEdgeDestination)
                for frame in frames:
                    if str(frame.URI) == destination_uri:
                        connected_frames.append(frame)
                        break
        
        return connected_frames
    
    def _find_frame_slots(self, frame_uri: str, slots: List[KGSlot], 
                         edges: List[VITAL_Edge]) -> List[KGSlot]:
        """Find slots connected to frame via Edge_hasKGSlot relationships."""
        connected_slots = []
        
        for edge in edges:
            # Check if this is an Edge_hasKGSlot connecting to our frame
            if (hasattr(edge, 'hasEdgeSource') and hasattr(edge, 'hasEdgeDestination') and
                str(edge.hasEdgeSource) == frame_uri and 
                type(edge).__name__ == 'Edge_hasKGSlot'):
                
                # Find the destination slot
                destination_uri = str(edge.hasEdgeDestination)
                for slot in slots:
                    if str(slot.URI) == destination_uri:
                        connected_slots.append(slot)
                        break
        
        return connected_slots
    
    def _find_related_edges(self, entity_uri: str, entity_frames: List[KGFrame], 
                           edges: List[VITAL_Edge]) -> List[VITAL_Edge]:
        """Find all edges related to this entity graph."""
        related_edges = []
        frame_uris = {str(frame.URI) for frame in entity_frames}
        
        for edge in edges:
            if hasattr(edge, 'hasEdgeSource') and hasattr(edge, 'hasEdgeDestination'):
                source_uri = str(edge.hasEdgeSource)
                destination_uri = str(edge.hasEdgeDestination)
                
                # Include edges where source or destination is part of this entity graph
                if (source_uri == entity_uri or source_uri in frame_uris or
                    destination_uri == entity_uri or destination_uri in frame_uris):
                    related_edges.append(edge)
        
        return related_edges
    
    def _validate_graph_completeness(self, entity_graphs: Dict[str, Dict], 
                                   all_objects: List) -> None:
        """Validate that all objects are accounted for in entity graphs."""
        accounted_objects = set()
        
        # Collect all objects that are part of entity graphs
        for entity_uri, graph in entity_graphs.items():
            for obj_list in graph.values():
                for obj in obj_list:
                    accounted_objects.add(str(obj.URI))
        
        # Check for orphaned objects
        orphaned_objects = []
        for obj in all_objects:
            if str(obj.URI) not in accounted_objects:
                orphaned_objects.append(obj)
        
        if orphaned_objects:
            orphaned_uris = [str(obj.URI) for obj in orphaned_objects]
            raise ValueError(f"Found {len(orphaned_objects)} orphaned objects not "
                           f"belonging to any entity graph: {orphaned_uris}")

class FrameGraphValidator:
    """Validates and separates frame graphs using Edge-based relationships."""
    
    def __init__(self):
        self.vitalsigns = VitalSigns()
    
    def validate_and_separate_frame_graph(self, jsonld_document: dict) -> Dict[str, Dict]:
        """
        Validate and separate frame graphs from JSON-LD document.
        Uses Edge-based relationship discovery for frame-to-frame and frame-to-slot relationships.
        """
        # Step 1: Convert JSON-LD to VitalSigns objects
        objects = self.vitalsigns.from_jsonld_list(jsonld_document)
        
        # Step 2: Categorize objects using isinstance
        frames = []
        slots = []
        edges = []
        
        for obj in objects:
            if isinstance(obj, KGFrame):
                frames.append(obj)
            elif isinstance(obj, KGSlot):  # Catches all slot subclasses
                slots.append(obj)
            elif isinstance(obj, VITAL_Edge):
                edges.append(obj)
        
        # Step 3: Build frame graphs using Edge relationships
        frame_graphs = {}
        processed_frames = set()
        
        for frame in frames:
            frame_uri = str(frame.URI)
            if frame_uri not in processed_frames:
                frame_graph = self._build_frame_graph_from_edges(
                    frame, frames, slots, edges, processed_frames
                )
                frame_graphs[frame_uri] = frame_graph
        
        # Step 4: Validate completeness
        self._validate_frame_graph_completeness(frame_graphs, objects)
        
        return frame_graphs
    
    def _build_frame_graph_from_edges(self, root_frame: KGFrame, all_frames: List[KGFrame],
                                    slots: List[KGSlot], edges: List[VITAL_Edge],
                                    processed_frames: Set[str]) -> Dict:
        """Build frame graph using Edge-based relationship discovery."""
        frame_uri = str(root_frame.URI)
        processed_frames.add(frame_uri)
        
        frame_graph = {
            'frames': [root_frame],
            'slots': [],
            'edges': []
        }
        
        # Find slots connected to this frame via Edge_hasKGSlot
        frame_slots = self._find_frame_slots(frame_uri, slots, edges)
        frame_graph['slots'].extend(frame_slots)
        
        # Find child frames connected via Edge_hasKGFrame (frame-to-frame)
        child_frames = self._find_child_frames(frame_uri, all_frames, edges)
        for child_frame in child_frames:
            child_uri = str(child_frame.URI)
            if child_uri not in processed_frames:
                # Recursively build child frame graphs
                child_graph = self._build_frame_graph_from_edges(
                    child_frame, all_frames, slots, edges, processed_frames
                )
                frame_graph['frames'].extend(child_graph['frames'])
                frame_graph['slots'].extend(child_graph['slots'])
                frame_graph['edges'].extend(child_graph['edges'])
        
        # Find all edges related to this frame graph
        related_edges = self._find_frame_related_edges(frame_uri, frame_slots, edges)
        frame_graph['edges'].extend(related_edges)
        
        return frame_graph
    
    def _find_child_frames(self, parent_frame_uri: str, frames: List[KGFrame],
                          edges: List[VITAL_Edge]) -> List[KGFrame]:
        """Find child frames connected via Edge_hasKGFrame relationships."""
        child_frames = []
        
        for edge in edges:
            # Check if this is an Edge_hasKGFrame with parent frame as source
            if (hasattr(edge, 'hasEdgeSource') and hasattr(edge, 'hasEdgeDestination') and
                str(edge.hasEdgeSource) == parent_frame_uri and 
                type(edge).__name__ == 'Edge_hasKGFrame'):
                
                # Find the destination frame
                destination_uri = str(edge.hasEdgeDestination)
                for frame in frames:
                    if str(frame.URI) == destination_uri:
                        child_frames.append(frame)
                        break
        
        return child_frames
    
    def _find_frame_related_edges(self, frame_uri: str, frame_slots: List[KGSlot],
                                 edges: List[VITAL_Edge]) -> List[VITAL_Edge]:
        """Find all edges related to this frame and its slots."""
        related_edges = []
        slot_uris = {str(slot.URI) for slot in frame_slots}
        
        for edge in edges:
            if hasattr(edge, 'hasEdgeSource') and hasattr(edge, 'hasEdgeDestination'):
                source_uri = str(edge.hasEdgeSource)
                destination_uri = str(edge.hasEdgeDestination)
                
                # Include edges where source or destination is part of this frame graph
                if (source_uri == frame_uri or source_uri in slot_uris or
                    destination_uri == frame_uri or destination_uri in slot_uris):
                    related_edges.append(edge)
        
        return related_edges
    
    def _validate_frame_graph_completeness(self, frame_graphs: Dict[str, Dict],
                                         all_objects: List) -> None:
        """Validate that all frame-related objects are accounted for."""
        accounted_objects = set()
        
        # Collect all objects that are part of frame graphs
        for frame_uri, graph in frame_graphs.items():
            for obj_list in graph.values():
                for obj in obj_list:
                    accounted_objects.add(str(obj.URI))
        
        # Check for orphaned frame-related objects
        orphaned_objects = []
        for obj in all_objects:
            # Only check frames, slots, and edges (entities are handled separately)
            if (isinstance(obj, (KGFrame, KGSlot, VITAL_Edge)) and 
                str(obj.URI) not in accounted_objects):
                orphaned_objects.append(obj)
        
        if orphaned_objects:
            orphaned_uris = [str(obj.URI) for obj in orphaned_objects]
            raise ValueError(f"Found {len(orphaned_objects)} orphaned frame-related objects: {orphaned_uris}")

# Test suite for graph validators
class TestEntityGraphValidator:
    """Test suite for EntityGraphValidator with Edge-based relationships."""
    
    def test_single_entity_with_frames_and_slots(self):
        """Test entity graph validation with complete entity-frame-slot structure."""
        test_document = {
            "@context": {
                "haley": "http://vital.ai/ontology/haley-ai-kg#",
                "vital": "http://vital.ai/ontology/vital-core#"
            },
            "@graph": [
                {
                    "@id": "http://example.org/entity1",
                    "@type": "haley:KGEntity",
                    "vital:hasName": "Test Entity",
                    "vital:vitaltype": "http://vital.ai/ontology/haley-ai-kg#KGEntity"
                },
                {
                    "@id": "http://example.org/frame1",
                    "@type": "haley:KGFrame", 
                    "vital:hasName": "Test Frame",
                    "vital:vitaltype": "http://vital.ai/ontology/haley-ai-kg#KGFrame"
                },
                {
                    "@id": "http://example.org/slot1",
                    "@type": "haley:KGTextSlot",
                    "vital:hasName": "Test Slot",
                    "haley:hasTextSlotValue": "Test Value",
                    "vital:vitaltype": "http://vital.ai/ontology/haley-ai-kg#KGTextSlot"
                },
                {
                    "@id": "http://example.org/edge1",
                    "@type": "haley:Edge_hasKGFrame",
                    "vital:hasEdgeSource": "http://example.org/entity1",
                    "vital:hasEdgeDestination": "http://example.org/frame1",
                    "vital:vitaltype": "http://vital.ai/ontology/haley-ai-kg#Edge_hasKGFrame"
                },
                {
                    "@id": "http://example.org/edge2", 
                    "@type": "haley:Edge_hasKGSlot",
                    "vital:hasEdgeSource": "http://example.org/frame1",
                    "vital:hasEdgeDestination": "http://example.org/slot1",
                    "vital:vitaltype": "http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot"
                }
            ]
        }
        
        # Step 2: Use EntityGraphValidator to separate entity graphs with Edge-based relationships
        separated_graphs = self.entity_validator.validate_and_separate_entity_graph(test_document)
        
        # Assertions
        assert len(separated_graphs) == 1
        entity_uri = "http://example.org/entity1"
        assert entity_uri in separated_graphs
        
        graph = entity_graphs[entity_uri]
        assert len(graph['entities']) == 1
        assert len(graph['frames']) == 1
        assert len(graph['slots']) == 1
        assert len(graph['edges']) == 2
    
    def test_multiple_entities_separate_graphs(self):
        """Test separation of multiple independent entity graphs."""
        # Test with multiple entities, each with their own frames and slots
        # Verify proper separation and no cross-contamination
        pass
    
    def test_orphaned_object_detection(self):
        """Test detection of orphaned objects not connected via edges."""
        # Test with objects that have no Edge relationships
        # Should raise ValueError with orphaned object details
        pass

class TestFrameGraphValidator:
    """Test suite for FrameGraphValidator with Edge-based relationships."""
    
    def test_frame_with_slots_and_child_frames(self):
        """Test frame graph validation with frame-to-frame and frame-to-slot relationships."""
        # Test hierarchical frame structure with slots
        pass
    
    def test_recursive_frame_hierarchy(self):
        """Test recursive frame-to-frame relationships."""
        # Test deep frame hierarchies with proper Edge navigation
        pass
```

```python
# Import from new SPARQL package
from vitalgraph.sparql.graph_validation import EntityGraphValidator
from vitalgraph.sparql.query_builder import GraphSeparationQueryBuilder

def _validate_and_separate_entity_graph(self, document: JsonLdDocument) -> Dict[str, Dict[str, List]]:
    """
    Validate entity graph structure and separate into individual entity graphs using SPARQL.
    Uses triple-based analysis to identify entity boundaries and relationships.
    
    Returns:
        Dict mapping entity URIs to their complete graphs:
        {
            "entity_uri_1": {
                "entities": [entity_triples],
                "frames": [frame_triples], 
                "slots": [slot_triples],
                "edges": [relationship_triples]
            },
            ...
        }
    """
    # Step 1: Load triples into temporary pyoxigraph store
    temp_store = pyoxigraph.Store()
    self._load_jsonld_triples_to_store(temp_store, document)
    
    # Step 2: Find all top-level entities using SPARQL
    entity_query = """
    PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
    SELECT DISTINCT ?entity WHERE {
        ?entity a haley:KGEntity .
    }
    """
    entity_results = temp_store.query(entity_query)
    entity_uris = [str(result['entity']) for result in entity_results]
    
    separated_graphs = {}
    
    # Step 3: For each entity, recursively collect its complete graph
    for entity_uri in entity_uris:
        entity_graph = self._collect_entity_graph_triples(temp_store, entity_uri)
        separated_graphs[entity_uri] = entity_graph
    
    # Step 4: Identify orphaned triples (not part of any entity graph)
    all_collected_subjects = set()
    for graph in separated_graphs.values():
        for triple_list in graph.values():
            all_collected_subjects.update([t['subject'] for t in triple_list])
    
    orphaned_triples = self._find_orphaned_triples(temp_store, all_collected_subjects)
    if orphaned_triples:
        raise ValueError(f"Found {len(orphaned_triples)} orphaned triples not belonging to any entity graph")
    
    return separated_graphs

def _collect_entity_graph_triples(self, store, entity_uri: str) -> Dict[str, List]:
    """
    Recursively collect all triples belonging to an entity's complete graph.
    """
    collected_subjects = set()
    entity_graph = {
        "entities": [],
        "frames": [],
        "slots": [],
        "edges": []
    }
    
    # Step 1: Collect entity triples
    entity_triples = self._get_subject_triples(store, entity_uri)
    entity_graph["entities"].extend(entity_triples)
    collected_subjects.add(entity_uri)
    
    # Step 2: Find direct frames using Edge_hasKGFrame relationship
    frame_query = f"""
    PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
    PREFIX vital: <http://vital.ai/ontology/vital-core#>
    SELECT DISTINCT ?frame WHERE {{
        ?edge a haley:Edge_hasKGFrame .
        ?edge vital:hasEdgeSource <{entity_uri}> .
        ?edge vital:hasEdgeDestination ?frame .
    }}
    """
    frame_results = store.query(frame_query)
    frame_uris = [str(result['frame']) for result in frame_results]
    
    # Step 3: Recursively collect frame graphs (including child frames)
    for frame_uri in frame_uris:
        frame_graph = self._collect_frame_graph_triples(store, frame_uri, collected_subjects)
        entity_graph["frames"].extend(frame_graph["frames"])
        entity_graph["slots"].extend(frame_graph["slots"])
        entity_graph["edges"].extend(frame_graph["edges"])
    
    # Step 4: Collect Edge_hasKGFrame relationship triples
    hasframe_query = f"""
    PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
    PREFIX vital: <http://vital.ai/ontology/vital-core#>
    SELECT ?edge ?predicate ?object WHERE {{
        ?edge a haley:Edge_hasKGFrame .
        ?edge vital:hasEdgeSource <{entity_uri}> .
        ?edge ?predicate ?object .
    }}
    """
    hasframe_results = store.query(hasframe_query)
    for result in hasframe_results:
        entity_graph["edges"].append({
            "subject": entity_uri,
            "predicate": str(result['predicate']),
            "object": str(result['object'])
        })
    
    return entity_graph

def _collect_frame_graph_triples(self, store, frame_uri: str, collected_subjects: set) -> Dict[str, List]:
    """
    Recursively collect all triples for a frame and its children/slots.
    """
    if frame_uri in collected_subjects:
        return {"frames": [], "slots": [], "edges": []}  # Already processed
    
    frame_graph = {"frames": [], "slots": [], "edges": []}
    collected_subjects.add(frame_uri)
    
    # Step 1: Collect frame triples
    frame_triples = self._get_subject_triples(store, frame_uri)
    frame_graph["frames"].extend(frame_triples)
    
    # Step 2: Find child frames using Edge_hasKGFrame relationship (frame-to-frame)
    child_frame_query = f"""
    PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
    PREFIX vital: <http://vital.ai/ontology/vital-core#>
    SELECT DISTINCT ?child_frame WHERE {{
        ?edge a haley:Edge_hasKGFrame .
        ?edge vital:hasEdgeSource <{frame_uri}> .
        ?edge vital:hasEdgeDestination ?child_frame .
    }}
    """
    child_frame_results = store.query(child_frame_query)
    child_frame_uris = [str(result['child_frame']) for result in child_frame_results]
    
    # Step 3: Recursively collect child frame graphs
    for child_frame_uri in child_frame_uris:
        child_graph = self._collect_frame_graph_triples(store, child_frame_uri, collected_subjects)
        frame_graph["frames"].extend(child_graph["frames"])
        frame_graph["slots"].extend(child_graph["slots"])
        frame_graph["edges"].extend(child_graph["edges"])
    
    # Step 4: Find slots using Edge_hasKGSlot relationship
    slot_query = f"""
    PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
    PREFIX vital: <http://vital.ai/ontology/vital-core#>
    SELECT DISTINCT ?slot WHERE {{
        ?edge a haley:Edge_hasKGSlot .
        ?edge vital:hasEdgeSource <{frame_uri}> .
        ?edge vital:hasEdgeDestination ?slot .
    }}
    """
    slot_results = store.query(slot_query)
    slot_uris = [str(result['slot']) for result in slot_results]
    
    # Step 5: Collect slot triples
    for slot_uri in slot_uris:
        if slot_uri not in collected_subjects:
            slot_triples = self._get_subject_triples(store, slot_uri)
            frame_graph["slots"].extend(slot_triples)
            collected_subjects.add(slot_uri)
    
    # Step 6: Collect Edge relationship triples (Edge_hasKGFrame, Edge_hasKGSlot)
    relationship_queries = [
        f'?edge a haley:Edge_hasKGFrame . ?edge vital:hasEdgeSource <{frame_uri}> . ?edge vital:hasEdgeDestination ?child_frame',
        f'?edge a haley:Edge_hasKGSlot . ?edge vital:hasEdgeSource <{frame_uri}> . ?edge vital:hasEdgeDestination ?slot'
    ]
    
    for query_pattern in relationship_queries:
        rel_query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT ?subject ?predicate ?object WHERE {{
            {query_pattern} .
            BIND(?subject as ?s)
            BIND(?predicate as ?p) 
            BIND(?object as ?o)
        }}
        """
        rel_results = store.query(rel_query)
        for result in rel_results:
            frame_graph["edges"].append({
                "subject": str(result['subject']),
                "predicate": str(result['predicate']),
                "object": str(result['object'])
            })
    
    return frame_graph

def _get_subject_triples(self, store, subject_uri: str) -> List[Dict]:
    """Get all triples with the given subject."""
    query = f"""
    SELECT ?predicate ?object WHERE {{
        <{subject_uri}> ?predicate ?object .
    }}
    """
    results = store.query(query)
    return [
        {
            "subject": subject_uri,
            "predicate": str(result['predicate']),
            "object": str(result['object'])
        }
        for result in results
    ]

def _find_orphaned_triples(self, store, collected_subjects: set) -> List[Dict]:
    """Find triples whose subjects are not part of any collected entity graph."""
    all_subjects_query = """
    SELECT DISTINCT ?subject WHERE {
        ?subject ?predicate ?object .
    }
    """
    all_results = store.query(all_subjects_query)
    all_subjects = {str(result['subject']) for result in all_results}
    
    orphaned_subjects = all_subjects - collected_subjects
    orphaned_triples = []
    
    for subject in orphaned_subjects:
        subject_triples = self._get_subject_triples(store, subject)
        orphaned_triples.extend(subject_triples)
    
    return orphaned_triples
```

#### 2.2 MockKGFramesEndpoint Enhancements

**Frame Graph Query Implementation:**
```python
def _get_frame_graph_by_frame_graph_uri(self, space, frame_graph_uri: str, graph_id: str) -> List[GraphObject]:
    """Retrieve entire frame graph using hasFrameGraphURI property."""
    query = f"""
    PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
    PREFIX vital: <http://vital.ai/ontology/vital-core#>
    
    SELECT ?subject ?predicate ?object WHERE {{
        GRAPH <{graph_id}> {{
            ?subject haley:hasFrameGraphURI <{frame_graph_uri}> .
            ?subject ?predicate ?object .
        }}
        UNION
        {{
            # Find slots via Edge_hasKGSlot relationships
            ?frame haley:hasFrameGraphURI <{frame_graph_uri}> .
            ?edge a haley:Edge_hasKGSlot .
            ?edge vital:hasEdgeSource ?frame .
            ?edge vital:hasEdgeDestination ?slot .
            ?slot ?predicate ?object .
            BIND(?slot as ?subject)
        }}
        UNION
        {{
            # Find child frames via Edge_hasKGFrame relationships
            ?parent_frame haley:hasFrameGraphURI <{frame_graph_uri}> .
            ?edge a haley:Edge_hasKGFrame .
            ?edge vital:hasEdgeSource ?parent_frame .
            ?edge vital:hasEdgeDestination ?child_frame .
            ?child_frame ?predicate ?object .
            BIND(?child_frame as ?subject)
        }}
        UNION
        {{
            # Include Edge objects themselves
            ?edge_obj haley:hasFrameGraphURI <{frame_graph_uri}> .
            ?edge_obj a ?edge_type .
            FILTER(?edge_type IN (haley:Edge_hasKGFrame, haley:Edge_hasKGSlot))
            ?edge_obj ?predicate ?object .
            BIND(?edge_obj as ?subject)
        }}
    }}
    """
    # Execute query and convert to VitalSigns objects

**Frame Graph Validation and Separation:**

*Note: This functionality will also be implemented in the `vitalgraph.sparql` package.*

```python
# Import from SPARQL package
from vitalgraph.sparql.graph_validation import FrameGraphValidator

def _validate_and_separate_frame_graph(self, document: JsonLdDocument) -> Dict[str, Dict[str, List]]:
    """
    Validate frame graph structure and separate into individual frame graphs using SPARQL.
    Uses triple-based analysis to identify frame boundaries and relationships.
    
    Returns:
        Dict mapping frame URIs to their complete graphs:
        {
            "frame_uri_1": {
                "frames": [frame_triples],
                "slots": [slot_triples],
                "edges": [relationship_triples]
            },
            ...
        }
    """
    # Step 1: Load triples into temporary pyoxigraph store
    temp_store = pyoxigraph.Store()
    self._load_jsonld_triples_to_store(temp_store, document)
    
    # Step 2: Find all top-level frames using SPARQL
    frame_query = """
    PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
    SELECT DISTINCT ?frame WHERE {
        ?frame a haley:KGFrame .
    }
    """
    frame_results = temp_store.query(frame_query)
    frame_uris = [str(result['frame']) for result in frame_results]
    
    separated_graphs = {}
    
    # Step 3: For each frame, recursively collect its complete graph
    for frame_uri in frame_uris:
        frame_graph = self._collect_frame_only_graph_triples(temp_store, frame_uri)
        separated_graphs[frame_uri] = frame_graph
    
    # Step 4: Identify orphaned triples (not part of any frame graph)
    all_collected_subjects = set()
    for graph in separated_graphs.values():
        for triple_list in graph.values():
            all_collected_subjects.update([t['subject'] for t in triple_list])
    
    orphaned_triples = self._find_orphaned_triples(temp_store, all_collected_subjects)
    if orphaned_triples:
        raise ValueError(f"Found {len(orphaned_triples)} orphaned triples not belonging to any frame graph")
    
    return separated_graphs

def _collect_frame_only_graph_triples(self, store, frame_uri: str) -> Dict[str, List]:
    """
    Recursively collect all triples belonging to a frame's complete graph.
    Similar to entity graph collection but starting from KGFrame as top-level type.
    """
    collected_subjects = set()
    frame_graph = {
        "frames": [],
        "slots": [],
        "edges": []
    }
    
    # Step 1: Collect frame triples
    frame_triples = self._get_subject_triples(store, frame_uri)
    frame_graph["frames"].extend(frame_triples)
    collected_subjects.add(frame_uri)
    
    # Step 2: Recursively collect complete frame graph (child frames and slots)
    child_frame_graph = self._collect_frame_graph_triples(store, frame_uri, collected_subjects)
    frame_graph["frames"].extend(child_frame_graph["frames"])
    frame_graph["slots"].extend(child_frame_graph["slots"])
    frame_graph["edges"].extend(child_frame_graph["edges"])
    
    return frame_graph
```

### Phase 3: Server Endpoint Extensions

#### 3.1 Route Parameter Updates

**KGEntities Endpoint:**
```python
@router.get("/kgentities")
async def list_or_get_entities(
    # ... existing parameters ...
    include_entity_graph: bool = Query(False, description="Include entire entity graph"),
    current_user: Dict = Depends(auth_dependency)
):

@router.delete("/kgentities") 
async def delete_entities(
    # ... existing parameters ...
    delete_entity_graph: bool = Query(False, description="Delete entire entity graph"),
    current_user: Dict = Depends(auth_dependency)
):
```

**New Sub-Routes:**
```python
@router.post("/kgentities/kgframes")
async def create_entity_frames(
    entity_uri: str = Query(..., description="Entity URI"),
    request: JsonLdDocument,
    # ... other parameters ...
):

@router.get("/kgframes/kgslots")
async def get_frame_slots(
    frame_uri: str = Query(..., description="Frame URI"),
    slot_type: Optional[str] = Query(None, description="Filter by specific slot type URI (e.g., 'http://vital.ai/ontology/haley-ai-kg#KGTextSlot')"),
    # Note: For multiple slot types, use POST endpoint with SlotCriteria in request body
    # ... other parameters ...
):

@router.get("/kgframes/kgframes")
async def list_child_frames(
    parent_frame_uri: str = Query(..., description="Parent frame URI"),
    frame_type: Optional[str] = Query(None, description="Filter by frame type"),
    page_size: int = Query(10, ge=1, le=100, description="Number of frames per page"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    # ... other parameters ...
):

@router.post("/kgframes/kgframes")
async def create_child_frames(
    parent_frame_uri: str = Query(..., description="Parent frame URI"),
    request: JsonLdDocument,
    # ... other parameters ...
):

@router.put("/kgframes/kgframes")
async def update_child_frames(
    parent_frame_uri: str = Query(..., description="Parent frame URI"),
    request: JsonLdDocument,
    # ... other parameters ...
):

@router.delete("/kgframes/kgframes")
async def delete_child_frames(
    parent_frame_uri: str = Query(..., description="Parent frame URI"),
    frame_uris: Optional[str] = Query(None, description="Comma-separated list of child frame URIs"),
    # ... other parameters ...
):

@router.post("/kgentities/query")
async def query_entities(
    request: Dict[str, Any],
    space_id: str = Query(..., description="Space ID"),
    graph_id: Optional[str] = Query(None, description="Graph ID"),
    page_size: int = Query(100, ge=1, le=1000, description="Number of entities per page"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    current_user: Dict = Depends(auth_dependency)
):

@router.post("/kgframes/query")
async def query_frames(
    request: Dict[str, Any],
    space_id: str = Query(..., description="Space ID"),
    graph_id: Optional[str] = Query(None, description="Graph ID"),
    page_size: int = Query(100, ge=1, le=1000, description="Number of frames per page"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    current_user: Dict = Depends(auth_dependency)
):
```

### Phase 4: Query Criteria Implementation

#### 4.1 Query Criteria Models

**Entity Query Criteria:**
```python
from typing import Union, List, Optional, Any

class SlotCriteria(BaseModel):
    """Criteria for slot filtering."""
    slot_type: Optional[Union[str, List[str]]] = None  # Single slot type or list of slot types
    value: Optional[Any] = None
    comparator: Optional[str] = None  # "eq", "gt", "lt", "gte", "lte", "contains", "ne", "exists"
    
    # Examples of slot_type values:
    # Single: "http://vital.ai/ontology/haley-ai-kg#KGTextSlot"
    # Multiple: ["http://vital.ai/ontology/haley-ai-kg#KGTextSlot", "http://vital.ai/ontology/haley-ai-kg#KGIntegerSlot"]
    
    # Example usage:
    # Find entities with text slots containing "John":
    # SlotCriteria(slot_type="http://vital.ai/ontology/haley-ai-kg#KGTextSlot", value="John", comparator="contains")
    # 
    # Find entities with numeric slots (integer or double) greater than 100:
    # SlotCriteria(slot_type=["http://vital.ai/ontology/haley-ai-kg#KGIntegerSlot", 
    #                         "http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot"], 
    #              value=100, comparator="gt")

class EntityQueryCriteria(BaseModel):
    """Criteria for entity queries."""
    search_string: Optional[str] = None  # Search in entity name
    entity_type: Optional[str] = None    # Filter by entity type URI
    frame_type: Optional[str] = None     # Entities must have frame of this type
    slot_criteria: Optional[List[SlotCriteria]] = None  # Slot-based filtering
    
    class Config:
        extra = "forbid"

class FrameQueryCriteria(BaseModel):
    """Criteria for frame queries."""
    search_string: Optional[str] = None  # Search in frame name
    frame_type: Optional[str] = None     # Filter by frame type URI
    entity_type: Optional[str] = None    # Frames must belong to entity of this type
    slot_criteria: Optional[List[SlotCriteria]] = None  # Slot-based filtering
    
    class Config:
        extra = "forbid"
```

#### 4.2 Query Implementation

**Entity Query SPARQL Generation:**
```python
def _build_entity_query_sparql(self, criteria: EntityQueryCriteria, graph_id: str, 
                              page_size: int, offset: int) -> str:
    """Build SPARQL query from entity criteria."""
    
    base_query = f"""
    PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
    PREFIX vital: <http://vital.ai/ontology/vital-core#>
    
    SELECT DISTINCT ?entity ?predicate ?object WHERE {{
        GRAPH <{graph_id}> {{
            ?entity a haley:KGEntity .
            ?entity ?predicate ?object .
    """
    
    filters = []
    
    # Entity type filter
    if criteria.entity_type:
        filters.append(f"?entity a <{criteria.entity_type}> .")
    
    # Name search filter
    if criteria.search_string:
        filters.append(f"""
            ?entity vital:hasName ?name .
            FILTER(CONTAINS(LCASE(?name), LCASE("{criteria.search_string}")))
        """)
    
    # Frame type filter
    if criteria.frame_type:
        filters.append(f"""
            # Find frames via Edge_hasKGFrame relationships
            ?edge_frame a haley:Edge_hasKGFrame .
            ?edge_frame vital:hasEdgeSource ?entity .
            ?edge_frame vital:hasEdgeDestination ?frame .
            ?frame a <{criteria.frame_type}> .
        """)
    
    # Slot criteria filters
    if criteria.slot_criteria:
        for i, slot_crit in enumerate(criteria.slot_criteria):
            slot_filter = f"""
                # Find frames and slots via Edge relationships
                ?edge_frame{i} a haley:Edge_hasKGFrame .
                ?edge_frame{i} vital:hasEdgeSource ?entity .
                ?edge_frame{i} vital:hasEdgeDestination ?frame{i} .
                ?edge_slot{i} a haley:Edge_hasKGSlot .
                ?edge_slot{i} vital:hasEdgeSource ?frame{i} .
                ?edge_slot{i} vital:hasEdgeDestination ?slot{i} .
            """
            
            if slot_crit.slot_type:
                # Handle specific slot subclasses, not generic KGSlot
                if isinstance(slot_crit.slot_type, list):
                    # Multiple slot types - use VALUES clause
                    slot_types_str = " ".join([f"<{st}>" for st in slot_crit.slot_type])
                    slot_filter += f"""
                        VALUES ?slotType{i} {{ {slot_types_str} }}
                        ?slot{i} a ?slotType{i} .
                    """
                else:
                    # Single slot type
                    slot_filter += f"?slot{i} a <{slot_crit.slot_type}> ."
            
            if slot_crit.value is not None and slot_crit.comparator:
                # Use slot-type-specific value properties
                if slot_crit.slot_type:
                    # Map slot types to their specific value properties
                    slot_value_properties = self._get_slot_value_properties(slot_crit.slot_type)
                    if slot_value_properties:
                        props_str = " ".join([f"haley:{prop}" for prop in slot_value_properties])
                        slot_filter += f"""
                            VALUES ?valueProperty{i} {{ {props_str} }}
                            ?slot{i} ?valueProperty{i} ?value{i} .
                        """
                    else:
                        # Fallback to all known slot value properties
                        slot_filter += f"""
                            ?slot{i} ?valueProperty{i} ?value{i} .
                            FILTER(?valueProperty{i} IN (
                                haley:hasTextSlotValue, haley:hasIntegerSlotValue, 
                                haley:hasBooleanSlotValue, haley:hasChoiceSlotValue,
                                haley:hasDoubleSlotValue, haley:hasDateTimeSlotValue,
                                haley:hasCurrencySlotValue, haley:hasEntitySlotValue,
                                haley:hasAudioSlotValue, haley:hasVideoSlotValue,
                                haley:hasImageSlotValue, haley:hasJsonSlotValue,
                                haley:hasLongTextSlotValue, haley:hasLongSlotValue
                            ))
                        """
                else:
                    # No slot type specified - search all value properties
                    slot_filter += f"""
                        ?slot{i} ?valueProperty{i} ?value{i} .
                        FILTER(?valueProperty{i} IN (
                            haley:hasTextSlotValue, haley:hasIntegerSlotValue, 
                            haley:hasBooleanSlotValue, haley:hasChoiceSlotValue,
                            haley:hasDoubleSlotValue, haley:hasDateTimeSlotValue,
                            haley:hasCurrencySlotValue, haley:hasEntitySlotValue,
                            haley:hasAudioSlotValue, haley:hasVideoSlotValue,
                            haley:hasImageSlotValue, haley:hasJsonSlotValue,
                            haley:hasLongTextSlotValue, haley:hasLongSlotValue
                        ))
                    """
                
                if slot_crit.comparator == "eq":
                    slot_filter += f'FILTER(?value{i} = "{slot_crit.value}")'
                elif slot_crit.comparator == "contains":
                    slot_filter += f'FILTER(CONTAINS(LCASE(STR(?value{i})), LCASE("{slot_crit.value}")))'
                elif slot_crit.comparator == "gt":
                    slot_filter += f'FILTER(?value{i} > "{slot_crit.value}")'
                elif slot_crit.comparator == "lt":
                    slot_filter += f'FILTER(?value{i} < "{slot_crit.value}")'
                elif slot_crit.comparator == "gte":
                    slot_filter += f'FILTER(?value{i} >= "{slot_crit.value}")'
                elif slot_crit.comparator == "lte":
                    slot_filter += f'FILTER(?value{i} <= "{slot_crit.value}")'
                elif slot_crit.comparator == "ne":
                    slot_filter += f'FILTER(?value{i} != "{slot_crit.value}")'
            elif slot_crit.comparator == "exists":
                slot_filter += f"""
                    # Check for existence of any slot value property
                    ?slot{i} ?valueProperty{i} ?value{i} .
                    FILTER(?valueProperty{i} IN (
                        haley:hasTextSlotValue, haley:hasIntegerSlotValue, 
                        haley:hasBooleanSlotValue, haley:hasChoiceSlotValue,
                        haley:hasDoubleSlotValue, haley:hasDateTimeSlotValue
                    ))
                """
            
            filters.append(slot_filter)
    
    # Combine all filters
    if filters:
        base_query += "\n".join(filters)
    
    base_query += f"""
        }}
    }}
    ORDER BY ?entity
    LIMIT {page_size}
    OFFSET {offset}
    """
    
    return base_query

def _build_frame_query_sparql(self, criteria: FrameQueryCriteria, graph_id: str,
                             page_size: int, offset: int) -> str:
    """Build SPARQL query from frame criteria."""
    # Similar implementation for frames
```

#### 4.3 Mock Implementation

**MockKGEntitiesEndpoint Query Method:**
```python
def query_entities(self, space_id: str, graph_id: str, 
                  query_criteria: Dict[str, Any]) -> EntitiesResponse:
    """
    Query entities using simple criteria-based filtering.
    
    Args:
        space_id: Space identifier
        graph_id: Graph identifier
        query_criteria: Dictionary containing query criteria
        
    Returns:
        EntitiesResponse with matching entities
    """
    self._log_method_call("query_entities", space_id=space_id, graph_id=graph_id, 
                         query_criteria=query_criteria)
    
    try:
        # Validate and parse criteria
        criteria = EntityQueryCriteria.model_validate(query_criteria)
        
        # Get space from space manager
        space = self.space_manager.get_space(space_id)
        if not space:
            return self._empty_entities_response()
        
        # Build and execute SPARQL query
        sparql_query = self._build_entity_query_sparql(criteria, graph_id, 
                                                      query_criteria.get('page_size', 10),
                                                      query_criteria.get('offset', 0))
        
        results = self._execute_sparql_query(space, sparql_query)
        
        # Process results and convert to entities
        entities = self._process_entity_query_results(results)
        
        # Get total count with separate query
        total_count = self._get_entity_query_count(space, criteria, graph_id)
        
        # Convert VitalSigns objects to JSON-LD document using native methods
        entities_jsonld = self._vitalsigns_objects_to_jsonld(entities)
        
        return EntitiesResponse(
            entities=JsonLdDocument(**entities_jsonld),
            total_count=total_count,
            page_size=query_criteria.get('page_size', 10),
            offset=query_criteria.get('offset', 0)
        )
        
    except Exception as e:
        self.logger.error(f"Error querying entities: {e}")
        return self._empty_entities_response()
```

### Phase 1: SPARQL Package Implementation

#### 1.1 New Package Structure

**vitalgraph.sparql Package:**
```
vitalgraph/sparql/
├── __init__.py
├── graph_validation.py      # EntityGraphValidator, FrameGraphValidator
├── kg_query_builder.py      # KG-specific GraphSeparationQueryBuilder, QueryCriteriaBuilder
├── triple_store.py          # TemporaryTripleStore wrapper
└── utils.py                 # SPARQL utility functions
```

**Core Classes:**
```python
# vitalgraph.sparql.graph_validation
class EntityGraphValidator:
    """Validates and separates entity graphs using SPARQL queries."""
    
    def validate_and_separate_entity_graph(self, document: JsonLdDocument) -> Dict[str, Dict[str, List]]
    def _collect_entity_graph_triples(self, store, entity_uri: str) -> Dict[str, List]
    def _find_orphaned_triples(self, store, collected_subjects: set) -> List[Dict]

class FrameGraphValidator:
    """Validates and separates frame graphs using SPARQL queries."""
    
    def validate_and_separate_frame_graph(self, document: JsonLdDocument) -> Dict[str, Dict[str, List]]
    def _collect_frame_only_graph_triples(self, store, frame_uri: str) -> Dict[str, List]

# vitalgraph.sparql.kg_query_builder
class KGGraphSeparationQueryBuilder:
    """Builds SPARQL queries for KG entity/frame graph separation and validation."""
    
    def build_entity_discovery_query(self) -> str
    def build_frame_discovery_query(self) -> str
    def build_frame_relationship_query(self, frame_uri: str) -> str
    def build_slot_relationship_query(self, frame_uri: str) -> str

class KGQueryCriteriaBuilder:
    """Builds SPARQL queries for KG entity/frame criteria-based searches."""
    
    def build_entity_query_sparql(self, criteria: EntityQueryCriteria, graph_id: str, page_size: int, offset: int) -> str
    def build_frame_query_sparql(self, criteria: FrameQueryCriteria, graph_id: str, page_size: int, offset: int) -> str

# vitalgraph.sparql.triple_store
class TemporaryTripleStore:
    """Wrapper for pyoxigraph temporary stores with utility methods."""
    
    def load_jsonld_document(self, document: JsonLdDocument) -> None
    def execute_query(self, sparql_query: str) -> List[Dict]
    def get_subject_triples(self, subject_uri: str) -> List[Dict]
```

#### 1.2 SPARQL Package Test Suite

**test_sparql/ Test Structure:**
```
test_sparql/
├── __init__.py
├── test_graph_validation.py        # EntityGraphValidator, FrameGraphValidator tests
├── test_kg_query_builder.py        # KG query builder tests
├── test_triple_store.py             # TemporaryTripleStore tests
├── test_integration.py              # End-to-end SPARQL package tests
├── fixtures/
│   ├── sample_entity_graphs.py     # Test data for entity graph validation
│   ├── sample_frame_graphs.py      # Test data for frame graph validation
│   └── sample_query_criteria.py    # Test data for query criteria
└── utils/
    └── test_helpers.py              # Helper functions for SPARQL tests
```

**Core Test Classes:**
```python
# test_sparql/test_graph_validation.py
class TestEntityGraphValidator:
    """Test entity graph validation and separation."""
    
    def test_validate_single_entity_graph(self):
        """Test validation of single entity with frames and slots."""
        # Load sample entity graph JSON-LD
        # Validate separation into single entity graph
        # Verify all triples are collected
        # Verify no orphaned triples
    
    def test_validate_multiple_entity_graphs(self):
        """Test separation of multiple entity graphs."""
        # Load JSON-LD with multiple entities
        # Validate separation into N entity graphs
        # Verify each entity has complete graph
        # Verify no cross-contamination
    
    def test_validate_complex_frame_hierarchy(self):
        """Test entity with complex frame-to-frame relationships."""
        # Load entity with parent/child frames
        # Validate recursive frame collection
        # Verify all child frames included
        # Verify slot relationships preserved
    
    def test_orphaned_triple_detection(self):
        """Test detection of orphaned triples not belonging to any entity."""
        # Load JSON-LD with orphaned triples
        # Expect ValueError with orphaned triple count
        # Verify error message details
    
    def test_invalid_entity_graph_structure(self):
        """Test handling of invalid graph structures."""
        # Test missing entity type
        # Test broken relationships
        # Test circular references

class TestFrameGraphValidator:
    """Test frame graph validation and separation."""
    
    def test_validate_single_frame_graph(self):
        """Test validation of single frame with slots and child frames."""
        # Similar to entity tests but starting from KGFrame
    
    def test_validate_multiple_frame_graphs(self):
        """Test separation of multiple frame graphs."""
        # Load JSON-LD with multiple top-level frames
        # Validate separation into N frame graphs

# test_sparql/test_kg_query_builder.py
class TestKGGraphSeparationQueryBuilder:
    """Test SPARQL query generation for KG entity/frame graph separation."""
    
    def test_entity_discovery_query(self):
        """Test query to find all KGEntity subjects."""
        # Verify correct SPARQL syntax
        # Test with sample data
        # Verify returns expected entity URIs
    
    def test_frame_relationship_queries(self):
        """Test queries for KG frame relationships."""
        # Test hasFrame relationship query
        # Test kGFrameSlotFrame relationship query
        # Test frame-to-frame relationship query
    
    def test_query_validation(self):
        """Test SPARQL query syntax validation for KG operations."""
        # Verify all generated queries are valid SPARQL
        # Test with pyoxigraph query parser

class TestKGQueryCriteriaBuilder:
    """Test KG-specific criteria-based query generation."""
    
    def test_entity_query_generation(self):
        """Test KG entity query with various criteria."""
        # Test search string criteria
        # Test entity type filtering
        # Test frame type filtering
        # Test slot criteria with different comparators
    
    def test_complex_query_combinations(self):
        """Test complex multi-criteria KG queries."""
        # Test multiple slot criteria
        # Test combination of all filter types
        # Verify query performance and correctness

# test_sparql/test_triple_store.py
class TestTemporaryTripleStore:
    """Test temporary triple store wrapper."""
    
    def test_jsonld_loading(self):
        """Test loading JSON-LD documents into store."""
        # Test valid JSON-LD loading
        # Test invalid JSON-LD handling
        # Verify triple count matches expectations
    
    def test_query_execution(self):
        """Test SPARQL query execution."""
        # Test valid queries
        # Test invalid queries
        # Test result format consistency
    
    def test_subject_triple_retrieval(self):
        """Test getting all triples for a subject."""
        # Load test data
        # Retrieve triples for known subjects
        # Verify completeness and format

# test_sparql/test_integration.py
class TestSPARQLPackageIntegration:
    """End-to-end tests for SPARQL package functionality."""
    
    def test_complete_entity_graph_workflow(self):
        """Test complete workflow from JSON-LD to separated graphs."""
        # Load complex JSON-LD document
        # Use EntityGraphValidator to separate
        # Verify each separated graph is complete
        # Test with various graph complexities
    
    def test_query_criteria_workflow(self):
        """Test complete KG query criteria workflow."""
        # Load test data into store
        # Build queries with KGQueryCriteriaBuilder
        # Execute queries and verify results
        # Test pagination and filtering
```

### Phase 2: Client API Extensions

#### 2.1 KGEntitiesEndpoint Enhancements

**New Parameters:**
```python
# Enhanced get_kgentity method
def get_kgentity(self, space_id: str, graph_id: str, uri: str, 
                include_entity_graph: bool = False) -> JsonLdDocument:
    """
    Get KGEntity with optional complete entity graph.
    
    Args:
        include_entity_graph: If True, includes all frames, slots, and connecting edges
    """

# Enhanced delete_kgentity method  
def delete_kgentity(self, space_id: str, graph_id: str, uri: str,
                   delete_entity_graph: bool = False) -> EntityDeleteResponse:
    """
    Delete KGEntity with optional complete entity graph deletion.
    
    Args:
        delete_entity_graph: If True, deletes entire entity graph (frames, slots, edges)
    """

# New query method
def query_entities(self, space_id: str, graph_id: str, 
                  query_criteria: Dict[str, Any]) -> EntitiesResponse:
    """Query entities using simple criteria-based filtering."""
```

#### 2.2 KGFramesEndpoint Enhancements

**New Parameters:**
```python
# Enhanced get_kgframe method
def get_kgframe(self, space_id: str, graph_id: str, uri: str,
               include_frame_graph: bool = False) -> JsonLdDocument:
    """
    Get KGFrame with optional complete frame graph.
    
    Args:
        include_frame_graph: If True, includes all slots, child frames, and edges
    """

# New frame-to-frame operations
def create_child_frames(self, space_id: str, graph_id: str, parent_frame_uri: str,
                       document: JsonLdDocument) -> FrameCreateResponse

def get_child_frames(self, space_id: str, graph_id: str, parent_frame_uri: str,
                    frame_type: Optional[str] = None) -> JsonLdDocument

# New query method
def query_frames(self, space_id: str, graph_id: str,
                query_criteria: Dict[str, Any]) -> FramesResponse:
    """Query frames using simple criteria-based filtering."""
```

### Phase 3: Mock Implementation Updates

#### 3.1 Grouping URI-Based Graph Retrieval

**Entity Graph Retrieval using hasKGGraphURI:**
```python
def get_kgentity_with_graph(self, space_id: str, graph_id: str, uri: str, 
                           include_entity_graph: bool = False) -> EntityGraphResponse:
    """Get entity with optional complete graph using grouping URIs."""
    
    if not include_entity_graph:
        # Standard entity retrieval
        return self._get_single_entity(space_id, graph_id, uri)
    
    # Step 1: Find all subjects with hasKGGraphURI = entity_uri
    subjects_query = f"""
    PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
    SELECT DISTINCT ?subject WHERE {{
        GRAPH <{graph_id}> {{
            ?subject haley:hasKGGraphURI <{uri}> .
        }}
    }}
    """
    
    # Step 2: Get all triples for those subjects
    graph_triples = []
    for subject_result in self._execute_sparql_query(subjects_query):
        subject_uri = subject_result['subject']
        triples_query = f"""
        SELECT ?predicate ?object WHERE {{
            GRAPH <{graph_id}> {{
                <{subject_uri}> ?predicate ?object .
            }}
        }}
        """
        subject_triples = self._execute_sparql_query(triples_query)
        graph_triples.extend([(subject_uri, t['predicate'], t['object']) for t in subject_triples])
    
    # Step 3: Convert triples to JSON-LD and separate by type
    return self._build_entity_graph_response(graph_triples, uri)
```

**Frame Graph Retrieval using hasFrameGraphURI:**
```python
def get_kgframe_with_graph(self, space_id: str, graph_id: str, uri: str,
                          include_frame_graph: bool = False) -> FrameGraphResponse:
    """Get frame with optional complete graph using grouping URIs."""
    
    if not include_frame_graph:
        # Standard frame retrieval
        return self._get_single_frame(space_id, graph_id, uri)
    
    # Step 1: Find all subjects with hasFrameGraphURI = frame_uri
    subjects_query = f"""
    PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
    SELECT DISTINCT ?subject WHERE {{
        GRAPH <{graph_id}> {{
            ?subject haley:hasFrameGraphURI <{uri}> .
        }}
    }}
    """
    
    # Step 2: Get all triples for those subjects
    graph_triples = []
    for subject_result in self._execute_sparql_query(subjects_query):
        subject_uri = subject_result['subject']
        triples_query = f"""
        SELECT ?predicate ?object WHERE {{
            GRAPH <{graph_id}> {{
                <{subject_uri}> ?predicate ?object .
            }}
        }}
        """
        subject_triples = self._execute_sparql_query(triples_query)
        graph_triples.extend([(subject_uri, t['predicate'], t['object']) for t in subject_triples])
    
    # Step 3: Convert triples to JSON-LD and separate by type
    return self._build_frame_graph_response(graph_triples, uri)
```

#### 3.2 MockKGEntitiesEndpoint Integration

**Using SPARQL Package with Grouping URIs and VitalSigns Integration:**
```python
from vitalgraph.sparql.graph_validation import EntityGraphValidator
from vitalgraph.sparql.kg_query_builder import KGQueryCriteriaBuilder
from vital_ai_vitalsigns.vitalsigns import VitalSigns

# Import KG classes for isinstance checks
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGSlot import KGSlot  # Base class for isinstance checks
from vital_ai_vitalsigns.model.VITAL_Edge import VITAL_Edge

# Import specific slot subclasses for precise type checking when needed
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
from ai_haley_kg_domain.model.KGBooleanSlot import KGBooleanSlot
from ai_haley_kg_domain.model.KGChoiceSlot import KGChoiceSlot
from ai_haley_kg_domain.model.KGDoubleSlot import KGDoubleSlot
from ai_haley_kg_domain.model.KGDateTimeSlot import KGDateTimeSlot
from ai_haley_kg_domain.model.KGCurrencySlot import KGCurrencySlot
from ai_haley_kg_domain.model.KGEntitySlot import KGEntitySlot
# ... import other slot subclasses as needed

# Note: isinstance(obj, KGSlot) returns True for ALL KGSlot subclasses
# Use KGSlot for general slot detection, specific subclasses for value access

class MockKGEntitiesEndpoint:
    def __init__(self):
        self.entity_validator = EntityGraphValidator()
        self.query_builder = KGQueryCriteriaBuilder()
        self.vitalsigns = VitalSigns()
    
    def create_kgentities(self, space_id: str, graph_id: str, document: JsonLdDocument) -> EntityCreateResponse:
        """Create entities using Edge-based graph validation and VitalSigns integration."""
        # Step 1: Validate and separate entity graphs using Edge-based relationships
        entity_graphs = self.entity_validator.validate_and_separate_entity_graph(document.dict())
        
        # Step 2: Process each entity graph separately
        created_entities = []
        for entity_uri, entity_graph in entity_graphs.items():
            # Step 3: Set grouping URIs on all objects in this entity graph
            self._set_entity_grouping_uris(entity_graph, entity_uri)
            
            # Step 4: Store entity graph objects in database
            all_objects = (entity_graph['entities'] + entity_graph['frames'] + 
                          entity_graph['slots'] + entity_graph['edges'])
            self._store_vitalsigns_objects(space_id, graph_id, all_objects)
            
            created_entities.extend([str(entity.URI) for entity in entity_graph['entities']])
        
        return EntityCreateResponse(
            message=f"Created {len(created_entities)} entities with complete graphs",
            created_count=len(created_entities),
            created_uris=created_entities
        )
    
    def _set_entity_grouping_uris(self, entity_graph: Dict, entity_uri: str) -> None:
        """Set hasKGGraphURI on all objects in the entity graph."""
        for obj_list in entity_graph.values():
            for obj in obj_list:
                try:
                    obj.kGGraphURI = entity_uri  # Use VitalSigns short property name
                except Exception as e:
                    print(f"Warning: Could not set kGGraphURI on {obj.URI}: {e}")
    
    def get_kgentity(self, space_id: str, graph_id: str, uri: str, 
                    include_entity_graph: bool = False) -> EntityGraphResponse:
        """Get entity using grouping URI-based graph retrieval."""
        return self.get_kgentity_with_graph(space_id, graph_id, uri, include_entity_graph)
    
    def query_entities(self, space_id: str, graph_id: str, 
                      query_criteria: Dict[str, Any]) -> EntitiesResponse:
        """Query entities using KG SPARQL criteria builder."""
        # Use KGQueryCriteriaBuilder to generate SPARQL
        sparql_query = self.query_builder.build_entity_query_sparql(
            criteria, graph_id, page_size, offset
        )
        # Execute query and return results

def _get_slot_value_properties(self, slot_types: Union[str, List[str]]) -> List[str]:
    """Map slot types to their specific value properties."""
    slot_type_to_property = {
        "http://vital.ai/ontology/haley-ai-kg#KGTextSlot": "hasTextSlotValue",
        "http://vital.ai/ontology/haley-ai-kg#KGIntegerSlot": "hasIntegerSlotValue", 
        "http://vital.ai/ontology/haley-ai-kg#KGBooleanSlot": "hasBooleanSlotValue",
        "http://vital.ai/ontology/haley-ai-kg#KGChoiceSlot": "hasChoiceSlotValue",
        "http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot": "hasDoubleSlotValue",
        "http://vital.ai/ontology/haley-ai-kg#KGDateTimeSlot": "hasDateTimeSlotValue",
        "http://vital.ai/ontology/haley-ai-kg#KGCurrencySlot": "hasCurrencySlotValue",
        "http://vital.ai/ontology/haley-ai-kg#KGEntitySlot": "hasEntitySlotValue",
        "http://vital.ai/ontology/haley-ai-kg#KGAudioSlot": "hasAudioSlotValue",
        "http://vital.ai/ontology/haley-ai-kg#KGVideoSlot": "hasVideoSlotValue",
        "http://vital.ai/ontology/haley-ai-kg#KGImageSlot": "hasImageSlotValue",
        "http://vital.ai/ontology/haley-ai-kg#KGJSONSlot": "hasJsonSlotValue",
        "http://vital.ai/ontology/haley-ai-kg#KGLongTextSlot": "hasLongTextSlotValue",
        "http://vital.ai/ontology/haley-ai-kg#KGLongSlot": "hasLongSlotValue",
        "http://vital.ai/ontology/haley-ai-kg#KGMultiChoiceSlot": "hasMultiChoiceSlotValues",
        "http://vital.ai/ontology/haley-ai-kg#KGMultiTaxonomySlot": "hasMultiTaxonomySlotValues",
        "http://vital.ai/ontology/haley-ai-kg#KGTaxonomySlot": "hasTaxonomySlotValue",
        "http://vital.ai/ontology/haley-ai-kg#KGRunSlot": "hasRunSlotValue",
        "http://vital.ai/ontology/haley-ai-kg#KGFileUploadSlot": "hasFileUploadSlotValue",
        "http://vital.ai/ontology/haley-ai-kg#KGGeoLocationSlot": "hasGeoLocationSlotValue",
        "http://vital.ai/ontology/haley-ai-kg#KGCodeSlot": "hasCodeSlotValue"
    }
    
    if isinstance(slot_types, str):
        slot_types = [slot_types]
    
    properties = []
    for slot_type in slot_types:
        if slot_type in slot_type_to_property:
            properties.append(slot_type_to_property[slot_type])
    
    return properties

def _get_slot_value(self, slot_obj) -> Any:
    """
    Generic helper to get slot value with proper casting.
    Uses isinstance() with KGSlot subclasses for type dispatch.
    """
    # Use isinstance() with specific subclasses for value access
    if isinstance(slot_obj, KGTextSlot):
        return str(slot_obj.textSlotValue) if slot_obj.textSlotValue else None
    elif isinstance(slot_obj, KGIntegerSlot):
        return int(slot_obj.integerSlotValue) if slot_obj.integerSlotValue else None
    elif isinstance(slot_obj, KGBooleanSlot):
        return bool(slot_obj.booleanSlotValue) if slot_obj.booleanSlotValue else None
    elif isinstance(slot_obj, KGChoiceSlot):
        return str(slot_obj.choiceSlotValue) if slot_obj.choiceSlotValue else None
    elif isinstance(slot_obj, KGDoubleSlot):
        return float(slot_obj.doubleSlotValue) if slot_obj.doubleSlotValue else None
    elif isinstance(slot_obj, KGDateTimeSlot):
        return slot_obj.dateTimeSlotValue  # DateTime objects may not need casting
    elif isinstance(slot_obj, KGCurrencySlot):
        return float(slot_obj.currencySlotValue) if slot_obj.currencySlotValue else None
    elif isinstance(slot_obj, KGEntitySlot):
        return str(slot_obj.entitySlotValue) if slot_obj.entitySlotValue else None
    # Add more slot types as needed
    else:
        # Generic fallback for unknown slot types
        slot_type = type(slot_obj).__name__
        print(f"Warning: Unknown slot type {slot_type}, cannot extract value")
        return None

def _categorize_objects_efficiently(self, objects: List) -> Dict[str, List]:
    """
    Efficient object categorization using isinstance() with parent classes.
    Demonstrates best practice for KGSlot handling.
    """
    categorized = {
        'entities': [],
        'frames': [],
        'slots': [],
        'edges': []
    }
    
    for obj in objects:
        # Use parent classes for efficient categorization
        if isinstance(obj, KGEntity):
            categorized['entities'].append(obj)
        elif isinstance(obj, KGFrame):
            categorized['frames'].append(obj)
        elif isinstance(obj, KGSlot):  # Catches ALL slot subclasses
            categorized['slots'].append(obj)
        elif isinstance(obj, VITAL_Edge):
            categorized['edges'].append(obj)
    
    return categorized
```

### Phase 4: Property Management and Consistency

**Automatic Property Setting:**
```python
def _ensure_graph_uri_consistency(self, objects: List[GraphObject], operation: str) -> None:
    """
    Ensure hasKGGraphURI and hasFrameGraphURI properties are set consistently.
    
    Rules:
    - All entity graph components have hasKGGraphURI = entity_uri
    - All frame graph components have hasFrameGraphURI = frame_uri
    - Server strips client values and sets authoritatively
    - Includes entities, frames, slots, hasSlot edges, other edges
    """
    # Strip any existing grouping URIs from client
    # Extract entity/frame URIs from objects
    # Set hasKGGraphURI = entity_uri for all entity components
    # Set hasFrameGraphURI = frame_uri for all frame components
    # Validate relationships and consistency
```

**Grouping URI Assignment (Corrected):**
```python
def _set_entity_grouping_uris(self, entity_graph: Dict, entity_uri: str) -> None:
    """Set hasKGGraphURI to entity URI for all entity graph components."""
    # hasKGGraphURI = entity_uri (the entity subject itself)
    for component in entity_graph['entities'] + entity_graph['frames'] + entity_graph['slots'] + entity_graph['edges']:
        component['hasKGGraphURI'] = entity_uri

def _set_frame_grouping_uris(self, frame_graph: Dict, frame_uri: str, entity_uri: str) -> None:
    """Set both grouping URIs for frame graph components."""
    # hasKGGraphURI = entity_uri (links to entity)
    # hasFrameGraphURI = frame_uri (the frame subject itself)
    for component in frame_graph['frames'] + frame_graph['slots'] + frame_graph['hasSlot_edges']:
        component['hasKGGraphURI'] = entity_uri
        component['hasFrameGraphURI'] = frame_uri
```

**Grouping URI-Based Queries:**
```python
def _build_entity_graph_query(self, entity_uri: str, graph_id: str) -> str:
    """Build SPARQL query to get complete entity graph using hasKGGraphURI."""
    return f"""
    PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
    SELECT DISTINCT ?subject ?predicate ?object WHERE {{
        GRAPH <{graph_id}> {{
            ?subject haley:hasKGGraphURI <{entity_uri}> .
            ?subject ?predicate ?object .
        }}
    }}
    """

def _build_frame_graph_query(self, frame_uri: str, graph_id: str) -> str:
    """Build SPARQL query to get complete frame graph using hasFrameGraphURI."""
    return f"""
    PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
    SELECT DISTINCT ?subject ?predicate ?object WHERE {{
        GRAPH <{graph_id}> {{
            ?subject haley:hasFrameGraphURI <{frame_uri}> .
            ?subject ?predicate ?object .
        }}
    }}
    """
```

#### 6.2 Transactional Operations

**Multi-Object Transactions:**
```python
def _create_entity_graph_transactional(self, space, entities: List[KGEntity], 
                                     frames: List[KGFrame], slots: List[KGSlot],
                                     graph_id: str) -> bool:
    """
    Create entire entity graph in transaction.
    Rollback all changes if any operation fails.
    """
    # Begin transaction
    # Create entities
    # Create frames with entity relationships
    # Create slots with frame relationships
    # Commit or rollback
```

### Phase 7: Response Model Extensions

#### 7.1 New Response Models

```python
class EntityGraphResponse(BaseModel):
    """Response for entity graph operations."""
    entities: List[JsonLdDocument]
    frames: List[JsonLdDocument] 
    slots: List[JsonLdDocument]
    total_count: int
    kg_graph_uri: str

class FrameGraphResponse(BaseModel):
    """Response for frame graph operations."""
    frames: List[JsonLdDocument]
    slots: List[JsonLdDocument]
    edges: List[JsonLdDocument]
    total_count: int
    frame_graph_uri: str

class SlotCreateResponse(BaseModel):
    """Response for slot creation operations."""
    message: str
    created_count: int
    created_uris: List[str]
    frame_uri: str
```

## Implementation Priority

### High Priority (Phase 1)
1. **SPARQL package implementation** - Foundation for all graph operations
2. **SPARQL package tests** - Comprehensive test suite for validation logic

### Medium Priority (Phase 2-4)  
1. Client API parameter extensions (`include_entity_graph`, `delete_entity_graph`)
2. Mock implementation graph query methods using SPARQL package
3. Server endpoint parameter handling
4. Query criteria implementation

### Low Priority (Phase 5-8)
1. New sub-endpoint routes
2. Property consistency management
3. Enhanced response models
4. **Mock test suite enhancements**

## Testing Strategy

### Unit Tests
- Graph query validation
- Property consistency checks
- Transactional rollback scenarios

### Integration Tests
- End-to-end entity graph operations
- Cross-endpoint relationship validation
- Performance with large graphs

### Mock Client Tests
- In-memory graph separation and validation
- SPARQL query correctness
- VitalSigns object conversion accuracy

## Mock Test Updates

### Phase 8: Mock Test Suite Enhancements

#### 8.1 Test File Updates

**test_mock_kgentities_vitalsigns.py Extensions:**
```python
class TestKGEntitiesGraphOperations:
    """Test entity graph operations with hasKGGraphURI."""
    
    def test_get_entity_with_graph(self):
        """Test retrieving entity with entire graph (include_entity_graph=True)."""
        # Create entity with frames and slots
        # Set hasKGGraphURI on all objects
        # Test get_kgentity with include_entity_graph=True
        # Verify all related objects returned
    
    def test_create_entity_graph(self):
        """Test creating complete entity graph in single operation."""
        # Create JSON-LD with entity, frames, and slots
        # Ensure hasKGGraphURI consistency
        # Test create_kgentities with graph data
        # Verify all objects created with relationships
    
    def test_update_entity_graph(self):
        """Test updating entity graph with new frames/slots."""
        # Create initial entity graph
        # Update with additional frames/slots
        # Verify hasKGGraphURI consistency maintained
        # Test partial updates vs full graph replacement
    
    def test_delete_entity_graph(self):
        """Test deleting entire entity graph vs just entity."""
        # Create entity graph with frames and slots
        # Test delete with delete_entity_graph=False (entity only)
        # Test delete with delete_entity_graph=True (full graph)
        # Verify appropriate objects deleted
    
    def test_entity_frames_operations(self):
        """Test CRUD operations on frames within entity context."""
        # Test create_entity_frames()
        # Test update_entity_frames()
        # Test delete_entity_frames()
        # Test get_entity_frames()
    
    def test_kg_graph_uri_consistency(self):
        """Test hasKGGraphURI property management."""
        # Test auto-generation of hasKGGraphURI
        # Test consistency enforcement across objects
        # Test overwriting existing values
        # Test validation of relationships
    
    def test_entity_graph_validation(self):
        """Test validation of entity graph structure."""
        # Test invalid relationships (orphaned frames/slots)
        # Test missing hasKGGraphURI properties
        # Test inconsistent hasKGGraphURI values
        # Test proper error handling
    
    def test_entity_query_operations(self):
        """Test simple query operations for entities."""
        # Test query_entities with search_string
        # Test query_entities with entity_type filter
        # Test query_entities with frame_type filter
        # Test query_entities with slot_criteria (various comparators)
        # Test complex queries with multiple criteria
        # Test pagination and result ordering
```

**test_mock_kgframes_vitalsigns.py Extensions:**
```python
class TestKGFramesGraphOperations:
    """Test frame graph operations with hasFrameGraphURI."""
    
    def test_get_frame_with_graph(self):
        """Test retrieving frame with entire graph (include_frame_graph=True)."""
        # Create frame with slots and edges
        # Set hasFrameGraphURI on all objects
        # Test get_kgframe with include_frame_graph=True
        # Verify all related objects returned
    
    def test_create_frame_graph(self):
        """Test creating complete frame graph in single operation."""
        # Create JSON-LD with frame, slots, and edges
        # Ensure hasFrameGraphURI consistency
        # Test create_kgframes with graph data
        # Verify all objects created with relationships
    
    def test_update_frame_graph(self):
        """Test updating frame graph with new slots/edges."""
        # Create initial frame graph
        # Update with additional slots/edges
        # Verify hasFrameGraphURI consistency maintained
    
    def test_delete_frame_graph(self):
        """Test deleting entire frame graph."""
        # Create frame graph with slots and edges
        # Test delete operations
        # Verify all related objects deleted
    
    def test_frame_slots_operations(self):
        """Test CRUD operations on slots within frame context."""
        # Test create_frame_slots()
        # Test update_frame_slots()
        # Test delete_frame_slots()
        # Test get_frame_slots() with type filtering
    
    def test_frame_to_frame_operations(self):
        """Test CRUD operations on child frames within parent frame context."""
        # Test create_child_frames()
        # Test update_child_frames()
        # Test delete_child_frames()
        # Test get_child_frames() with frame type filtering
        # Test list_child_frames() with pagination
    
    def test_frame_graph_uri_consistency(self):
        """Test hasFrameGraphURI property management."""
        # Test auto-generation of hasFrameGraphURI
        # Test consistency enforcement across objects
        # Test validation of frame-slot relationships
    
    def test_frame_query_operations(self):
        """Test simple query operations for frames."""
        # Test query_frames with search_string
        # Test query_frames with frame_type filter
        # Test query_frames with entity_type filter
        # Test query_frames with slot_criteria (various comparators)
        # Test complex queries with multiple criteria
        # Test pagination and result ordering
```

#### 8.2 New Test Files

**test_mock_kg_graph_operations.py:**
```python
"""
Comprehensive tests for KG graph operations across entities and frames.
Tests cross-endpoint functionality and complex graph scenarios.
"""

class TestKGGraphIntegration:
    """Test integration between entity and frame graph operations."""
    
    def test_entity_with_multiple_frames(self):
        """Test entity with multiple frames, each with their own slots."""
        # Create entity with multiple frames
        # Each frame has different hasFrameGraphURI
        # Entity has single hasKGGraphURI covering all
        # Test retrieval and manipulation
    
    def test_shared_frame_across_entities(self):
        """Test frame shared across multiple entities."""
        # Create multiple entities referencing same frame
        # Test hasKGGraphURI vs hasFrameGraphURI handling
        # Test deletion scenarios (frame vs entity deletion)
    
    def test_complex_graph_operations(self):
        """Test complex multi-level graph operations."""
        # Create hierarchical entity-frame-slot structures
        # Test bulk operations across multiple graphs
        # Test transactional consistency
    
    def test_graph_uri_conflicts(self):
        """Test handling of graph URI conflicts and resolution."""
        # Test objects with conflicting hasKGGraphURI values
        # Test automatic resolution strategies
        # Test error handling for unresolvable conflicts
    
    def test_performance_large_graphs(self):
        """Test performance with large entity/frame graphs."""
        # Create large graphs (100+ entities, 1000+ frames/slots)
        # Test retrieval performance
        # Test SPARQL query efficiency
        # Test memory usage patterns

class TestKGGraphSPARQL:
    """Test SPARQL query generation for graph operations."""
    
    def test_entity_graph_queries(self):
        """Test SPARQL queries for entity graph retrieval."""
        # Verify correct UNION patterns for entity graphs
        # Test query optimization for large graphs
        # Test filtering and pagination with graphs
    
    def test_frame_graph_queries(self):
        """Test SPARQL queries for frame graph retrieval."""
        # Verify correct patterns for frame-slot relationships
        # Verify correct patterns for frame-to-frame relationships
        # Test edge case handling (orphaned slots, orphaned child frames, etc.)
    
    def test_graph_deletion_queries(self):
        """Test SPARQL DELETE patterns for graph operations."""
        # Test cascading deletes for entity graphs
        # Test selective deletion (entity vs full graph)
        # Test cleanup of orphaned objects
```

**test_mock_kg_property_management.py:**
```python
"""
Tests for hasKGGraphURI and hasFrameGraphURI property management.
"""

class TestGraphURIManagement:
    """Test automatic graph URI property management."""
    
    def test_auto_generation(self):
        """Test automatic generation of graph URI properties."""
        # Test hasKGGraphURI generation from entity URI
        # Test hasFrameGraphURI generation from frame URI
        # Test URI format consistency
    
    def test_property_consistency(self):
        """Test consistency enforcement across related objects."""
        # Test setting hasKGGraphURI on all entity graph objects
        # Test setting hasFrameGraphURI on all frame graph objects
        # Test overwriting existing inconsistent values
    
    def test_validation_rules(self):
        """Test validation of graph URI properties."""
        # Test required properties on graph operations
        # Test relationship validation (entity->frame->slot)
        # Test proper error messages for violations
    
    def test_property_updates(self):
        """Test updating graph URI properties during operations."""
        # Test property updates during create operations
        # Test property updates during update operations
        # Test property cleanup during delete operations
```

#### 8.3 Test Data and Fixtures

**test_data/kg_graph_samples.py:**
```python
"""Sample data for KG graph operation testing."""

def create_sample_entity_graph():
    """Create sample entity with frames and slots for testing."""
    return {
        "@context": {...},
        "@graph": [
            {
                "@id": "urn:entity:person:john",
                "@type": "http://vital.ai/ontology/haley-ai-kg#KGEntity",
                "hasKGGraphURI": "urn:entity:person:john/kg-graph",
                "hasName": "John Doe",
                "hasFrame": ["urn:frame:person:demographics", "urn:frame:person:skills"]
            },
            {
                "@id": "urn:frame:person:demographics", 
                "@type": "http://vital.ai/ontology/haley-ai-kg#KGFrame",
                "hasFrameGraphURI": "urn:frame:person:demographics/frame-graph",
                "hasName": "Demographics Frame"
            },
            # ... slots and additional objects
        ]
    }

def create_sample_frame_graph():
    """Create sample frame with slots for testing."""
    # Similar structure for frame graph testing

def create_complex_multi_entity_graph():
    """Create complex graph with multiple entities and shared frames."""
    # Complex test data for integration testing
```

#### 8.4 Test Utilities

**test_utils/kg_graph_helpers.py:**
```python
"""Helper utilities for KG graph testing."""

class KGGraphTestHelper:
    """Helper class for KG graph testing operations."""
    
    def validate_entity_graph_structure(self, graph_data):
        """Validate entity graph has proper structure and relationships."""
        # Check hasKGGraphURI consistency
        # Validate entity->frame relationships
        # Validate frame->slot relationships
        # Return validation results
    
    def validate_frame_graph_structure(self, graph_data):
        """Validate frame graph has proper structure and relationships."""
        # Check hasFrameGraphURI consistency
        # Validate frame->slot relationships
        # Return validation results
    
    def extract_graph_uris(self, objects):
        """Extract all graph URIs from a collection of objects."""
        # Extract hasKGGraphURI values
        # Extract hasFrameGraphURI values
        # Return unique URI sets
    
    def create_test_graph_data(self, entity_count, frame_count, slot_count):
        """Generate test data with specified object counts."""
        # Generate entities with hasKGGraphURI
        # Generate frames with hasFrameGraphURI
        # Generate slots with proper relationships
        # Return structured test data
```

#### 8.5 Performance and Load Tests

**test_performance/test_kg_graph_performance.py:**
```python
"""Performance tests for KG graph operations."""

class TestKGGraphPerformance:
    """Test performance characteristics of graph operations."""
    
    def test_large_entity_graph_retrieval(self):
        """Test performance of retrieving large entity graphs."""
        # Create entity with 100+ frames and 1000+ slots
        # Measure retrieval time with include_entity_graph=True
        # Verify performance meets requirements
    
    def test_bulk_graph_operations(self):
        """Test performance of bulk graph operations."""
        # Test creating multiple entity graphs simultaneously
        # Test updating multiple graphs
        # Test deleting multiple graphs
    
    def test_sparql_query_optimization(self):
        """Test SPARQL query performance for graph operations."""
        # Measure query execution time for complex graphs
        # Test query plan optimization
        # Verify index usage in pyoxigraph
```

## Discussion Points

1. **Graph URI Generation**: Should we auto-generate or require explicit URIs?
2. **Performance**: Caching strategies for large entity/frame graphs?
3. **Validation**: How strict should relationship validation be?
4. **Transactions**: Mock implementation transaction simulation approach?

## Recent Completed Work (November 2024)

### ✅ VitalSigns Integration and Property Access Patterns

#### VitalSigns JSON-LD Conversion Implementation
- **Direct VitalSigns Integration**: Implemented `vitalsigns.from_jsonld_list()` for JSON-LD to VitalSigns object conversion
- **Property Object Handling**: Documented that VitalSigns property access returns Property objects requiring casting
- **Grouping URI Management**: Implemented `obj.kGGraphURI = entity_uri` for hasKGGraphURI property assignment
- **Type Safety**: Replaced string matching with `isinstance(obj, KGEntity)` for reliable type detection

#### Comprehensive KG Classes Documentation
- **Property Discovery**: Created script to discover all KG class properties using VitalSigns introspection
- **Complete Documentation**: Generated comprehensive documentation for 33 KG classes (entities, frames, 28 slot subclasses, 3 edge classes)
- **Property Reference**: Documented 2,800+ individual properties with URIs, short names, and types
- **Working Code Examples**: Provided tested code examples for JSON-LD conversion and property access

#### Property Access Patterns Established
```python
# Property Objects (returns Property instances)
text_property = obj.textSlotValue          # Returns StringProperty object
text_value = str(obj.textSlotValue)        # Cast to get actual string value

# Direct Property Access (recommended)
obj.textSlotValue = "New Text"             # Setting values
value = str(obj.textSlotValue)             # Getting values with casting

# Alternative Methods
value = str(obj.get_property('http://vital.ai/ontology/haley-ai-kg#hasTextSlotValue'))
obj.set_property('http://vital.ai/ontology/haley-ai-kg#hasTextSlotValue', "new value")
```

#### MockKGEntitiesEndpoint Enhancements
- **VitalSigns Integration**: Updated to use `vitalsigns.from_jsonld_list()` directly
- **Grouping URI Enforcement**: Implemented automatic `kGGraphURI` setting on all objects
- **Type Detection**: Using `isinstance()` checks for reliable object categorization
- **Property Validation**: Added VitalSigns object validation and conversion

#### Test Suite Updates
- **Comprehensive Testing**: Updated test scripts to demonstrate Property object handling
- **Multiple Slot Types**: Testing KGTextSlot, KGIntegerSlot, KGBooleanSlot, KGChoiceSlot, KGDoubleSlot
- **Property Casting**: Verified proper casting from Property objects to actual values
- **Working Examples**: All tests passing with real VitalSigns integration

#### Documentation Files Created
1. **`/planning/kg_classes_properties.md`** (8,228 lines) - Complete KG classes documentation
2. **`/planning/kg_classes_properties.json`** - Raw property data for programmatic access  
3. **`/planning/kg_slot_value_properties_summary.md`** - Quick reference with working code examples

### 🔧 Key Technical Findings

#### Property Access Requirements
- **Property Objects**: VitalSigns returns Property objects, not raw values
- **Casting Required**: Use `str()`, `int()`, `float()`, `bool()` to extract actual values
- **Short Names**: VitalSigns converts `hasXxxSlotValue` to `xxxSlotValue` for direct access
- **Type Safety**: Use `isinstance(obj, KGTextSlot)` instead of string matching

#### VitalSigns Integration Patterns
- **JSON-LD to Objects**: `vitalsigns.from_jsonld_list(document)` for @graph arrays
- **Grouping URIs**: `obj.kGGraphURI = entity_uri` for hasKGGraphURI assignment
- **Edge Detection**: All edges inherit from `VITAL_Edge` - use `isinstance(obj, VITAL_Edge)`
- **Property Mapping**: Full URIs in JSON-LD, short names in Python code

#### Slot Value Properties Discovered
| Slot Class | Short Property Name | Property Type | Casting |
|------------|---------------------|---------------|---------|
| KGTextSlot | `textSlotValue` | StringProperty | `str(obj.textSlotValue)` |
| KGIntegerSlot | `integerSlotValue` | IntegerProperty | `int(obj.integerSlotValue)` |
| KGBooleanSlot | `booleanSlotValue` | BooleanProperty | `bool(obj.booleanSlotValue)` |
| KGChoiceSlot | `choiceSlotValue` | StringProperty | `str(obj.choiceSlotValue)` |
| KGDoubleSlot | `doubleSlotValue` | DoubleProperty | `float(obj.doubleSlotValue)` |
| + 16 more slot types... | | | |

### 📋 Updated Implementation Status

#### ✅ Completed (High Priority)
1. **VitalSigns JSON-LD Integration** - Direct conversion methods implemented and tested
2. **Property Access Patterns** - Comprehensive documentation and working examples
3. **MockKGEntitiesEndpoint Integration** - VitalSigns integration with grouping URI enforcement
4. **KG Classes Documentation** - Complete property discovery and documentation
5. **Test Suite Updates** - Working tests with Property object handling

#### 🔄 In Progress (Medium Priority)
1. **MockKGFramesEndpoint Integration** - Apply same VitalSigns patterns to frames endpoint
2. **SPARQL Package Implementation** - Graph validation and query building utilities

#### ⏳ Pending (Updated Priorities)
1. **Client API Extensions** - Add `include_entity_graph`, `delete_entity_graph` parameters
2. **Server Endpoint Extensions** - Route parameter updates and new sub-endpoints
3. **Query Criteria Implementation** - Entity and frame query with criteria-based filtering

## Critical Updates Required Based on VitalSigns Data Model

### 🚨 **IMMEDIATE PRIORITY - Data Model Corrections**

The following critical updates are required based on our improved understanding of the VitalSigns ontology and Property object model. These must be addressed before proceeding with further implementation.

#### **1. SPARQL Query Pattern Updates (Critical)**
- **Replace Direct Property Relationships**: Update all SPARQL queries to use Edge classes instead of non-existent direct properties
- **Fix Entity-Frame Relationships**: Replace `?entity haley:hasFrame ?frame` with Edge_hasKGFrame relationship queries
- **Fix Frame-Slot Relationships**: Replace `?slot haley:kGFrameSlotFrame ?frame` with Edge_hasKGSlot relationship queries
- **Update Graph Traversal Logic**: Revise all graph discovery queries to use proper Edge-based navigation

**Example Correction Needed:**
```sparql
# WRONG (Current):
?entity haley:hasFrame ?frame .

# CORRECT (Should be):
?edge a haley:Edge_hasKGFrame .
?edge vital:hasEdgeSource ?entity .
?edge vital:hasEdgeDestination ?frame .
```

#### **2. Property Name Corrections (Critical)**
- **Remove Non-Existent Properties**: Eliminate references to `hasKGEntityType`, `hasKGFrameType`, `hasKGSlotType`
- **Replace Generic Slot Values**: Remove `hasSlotValue` and use specific slot properties (`hasTextSlotValue`, `hasIntegerSlotValue`, etc.)
- **Update Type Detection**: Replace string matching with `isinstance()` checks for all object categorization
- **Fix Property Access**: Update all property access to use VitalSigns Property object patterns with proper casting

**Properties That Don't Exist (Remove):**
- `haley:hasFrame` (use Edge_hasKGFrame instead)
- `haley:kGFrameSlotFrame` (use Edge_hasKGSlot instead)  
- `haley:hasChildFrame` (use Edge_hasKGFrame for frame-to-frame)
- `haley:hasKGEntityType` (use actual entity type properties)
- `haley:hasSlotValue` (use specific slot value properties)

#### **3. Graph Validation Logic Updates (High Priority)**
- **Revise EntityGraphValidator**: Update to use Edge-based relationship discovery
- **Update FrameGraphValidator**: Implement proper Edge_hasKGSlot relationship handling
- **Fix Relationship Traversal**: Replace direct property queries with Edge class navigation
- **Update Orphaned Triple Detection**: Account for Edge objects in graph completeness validation

#### **4. VitalSigns Integration Standardization (High Priority)**
- **Replace Manual JSON-LD Handling**: Eliminate all manual context creation in favor of VitalSigns native methods
- **Implement Property Object Handling**: Update all property access to handle Property objects with proper casting
- **Standardize Type Detection**: Replace all string-based type checking with `isinstance()` patterns
- **Update Response Models**: Ensure all response generation uses VitalSigns-aware serialization

**VitalSigns Integration Patterns to Implement:**
```python
# WRONG (Manual JSON-LD handling):
def _objects_to_jsonld_document(self, objects):
    # Manual context creation - REMOVE THIS
    context = {
        "haley": "http://vital.ai/ontology/haley-ai-kg#",
        "vital": "http://vital.ai/ontology/vital-core#"
    }
    # Manual object serialization - REMOVE THIS

# CORRECT (VitalSigns native methods):
def _vitalsigns_objects_to_jsonld(self, objects):
    """Convert VitalSigns objects to JSON-LD using native methods."""
    if not objects:
        return {"@graph": []}
    
    # Use VitalSigns native to_jsonld_list method
    vitalsigns = VitalSigns()
    jsonld_doc = vitalsigns.to_jsonld_list(objects)
    return jsonld_doc

# WRONG (String-based type detection):
if 'KGEntity' in str(obj.vitaltype):
    entities.append(obj)

# CORRECT (isinstance() type detection):
if isinstance(obj, KGEntity):
    entities.append(obj)

# CORRECT (KGSlot isinstance catches ALL slot subclasses):
if isinstance(obj, KGSlot):  # True for KGTextSlot, KGIntegerSlot, etc.
    slots.append(obj)

# CORRECT (Specific subclass for value access):
if isinstance(obj, KGTextSlot):
    text_value = str(obj.textSlotValue)
elif isinstance(obj, KGIntegerSlot):
    int_value = int(obj.integerSlotValue)

# WRONG (Manual property access):
value = obj.get_property('http://vital.ai/ontology/haley-ai-kg#hasTextSlotValue')

# CORRECT (Direct property access with casting):
property_obj = obj.textSlotValue          # Returns Property object
value = str(obj.textSlotValue)            # Cast to get actual value
```

**isinstance() Usage Patterns:**
```python
# Pattern 1: General categorization (RECOMMENDED)
if isinstance(obj, KGSlot):
    # This catches ALL slot subclasses efficiently
    slots.append(obj)

# Pattern 2: Specific value access (when needed)
if isinstance(obj, KGTextSlot):
    value = str(obj.textSlotValue)
elif isinstance(obj, KGIntegerSlot):
    value = int(obj.integerSlotValue)
# ... handle other specific slot types

# Pattern 3: Combined approach (BEST PRACTICE)
if isinstance(obj, KGSlot):
    slots.append(obj)
    # Access slot value using generic approach or type dispatch
    slot_value = self._get_slot_value(obj)  # Helper method handles casting
```

**Key isinstance() Best Practices:**
- ✅ **Use `isinstance(obj, KGSlot)` for general slot detection** - catches all 21+ slot subclasses
- ✅ **Use specific subclasses only for value access** - when you need type-specific property access
- ✅ **Leverage Python's inheritance** - parent class isinstance checks are efficient and maintainable
- ❌ **Don't check each subclass individually** for categorization - inefficient and error-prone
- ❌ **Don't use string matching on vitaltype** - unreliable and slow

**Performance Benefits:**
- Single `isinstance(obj, KGSlot)` check vs. 21+ individual subclass checks
- Automatic support for new slot subclasses without code changes
- Cleaner, more maintainable code structure

#### **5. Slot Value Handling Revision (High Priority)**
- **Remove Generic Slot Queries**: Replace `hasSlotValue` with slot-type-specific properties
- **Implement Slot Type Dispatch**: Use `isinstance()` to determine slot type and access appropriate value property
- **Update Query Criteria**: Revise slot-based filtering to use correct property names per slot type
- **Fix Value Casting**: Ensure proper casting from Property objects to actual values

#### **6. Test Data and Fixture Updates (Medium Priority)**
- **Update Sample Data**: Revise all test JSON-LD to use Edge classes for relationships
- **Fix Property Names**: Update test data to use correct property names from ontology discovery
- **Add Property Object Tests**: Include tests for Property object casting and value access
- **Update Validation Tests**: Ensure tests reflect actual Edge-based relationship model

### **📋 Implementation Priority Order:**

#### **Phase 1A: Critical SPARQL Fixes (IMMEDIATE)**
1. Update all entity graph retrieval queries to use Edge_hasKGFrame relationships
2. Update all frame-slot queries to use Edge_hasKGSlot relationships  
3. Remove references to non-existent direct properties (`hasFrame`, `kGFrameSlotFrame`)
4. Fix graph traversal logic in EntityGraphValidator and FrameGraphValidator

#### **Phase 1B: Property Access Standardization (IMMEDIATE)**
1. Replace all manual JSON-LD handling with VitalSigns native methods
2. Update all property access to use Property object casting patterns
3. Replace string-based type detection with `isinstance()` checks
4. Standardize slot value access using slot-type-specific properties

#### **Phase 1C: Query and Response Updates (HIGH)**
1. Update query criteria builders to use correct property names
2. Fix slot-based filtering to use specific slot value properties
3. Update response model serialization for VitalSigns compatibility
4. Revise test data to match actual ontology structure

## Next Steps (Updated)

### Immediate Priority (Phase 1)
1. **Complete MockKGFramesEndpoint Integration**
   - Apply VitalSigns integration patterns from MockKGEntitiesEndpoint
   - Implement grouping URI enforcement for frame operations
   - Add `isinstance()` type checking and Property object handling

2. **Data Lifecycle Management & Stale Triple Prevention** ⭐ **NEW PRIORITY**
   - **Review CRUD Operations for Data Integrity**
     - Analyze create, update, delete operations for proper triple management
     - Ensure existing triples are properly deleted before new ones are added
     - Verify grouping URI assignment and cleanup behavior
   - **Stale Triple Prevention Strategy**
     - Document when existing data should be deleted vs. merged
     - Define cleanup patterns for entity/frame/slot updates
     - Establish rules for orphaned edge relationship cleanup
   - **Comprehensive Update Testing**
     - Create tests that verify no stale triples remain after updates
     - Test edge cases: partial updates, failed operations, concurrent modifications
     - Validate grouping URI consistency after complex operations
   - **Implementation Guidelines**
     - Document proper sequence: delete existing → validate → add new → set grouping URIs
     - Create helper methods for atomic update operations
     - Establish rollback patterns for failed operations

3. **Create Integration Tests**
   - Test complete entity document processing with multiple slot types
   - Verify Property object casting and value access
   - Test grouping URI consistency across operations

### Medium Priority (Phase 2)
1. **SPARQL Package Implementation** 
   - Create `vitalgraph.sparql` package structure
   - Implement `EntityGraphValidator` and `FrameGraphValidator` using established VitalSigns patterns
   - Implement `KGQueryCriteriaBuilder` with Property object awareness

2. **Client API Extensions**
   - Add `include_entity_graph` and `delete_entity_graph` parameters
   - Add `include_frame_graph` parameter  
   - Add `query_entities` and `query_frames` methods

### Long-term Priority (Phase 3)
1. **Server Endpoint Extensions**
   - Route parameter updates for graph operations
   - New sub-endpoint routes for nested operations
   - Query criteria endpoint implementation

2. **Performance Optimization**
   - Caching strategies for large entity/frame graphs
   - SPARQL query optimization
   - Property access performance improvements

---

## Data Lifecycle Management & Stale Triple Prevention (Detailed Plan)

### Problem Statement
Current KG operations may leave stale triples in the database during update operations, potentially causing:
- Inconsistent data states
- Orphaned relationships
- Incorrect query results
- Data integrity violations

### CRUD Operation Analysis Required

#### **CREATE Operations**
- ✅ **Current State**: Generally safe - no existing data to conflict
- 🔍 **Required Implementation**: 
  - **Pre-existence Check**: For each unique subject URI in the graph objects being inserted, check if it already exists in the database
  - **Conflict Prevention**: If any subject already exists, reject the CREATE operation (fail-fast)
  - **Atomic Creation**: Only proceed if ALL subjects are new
  - **Grouping URI Assignment**: Assign grouping URIs atomically after successful insertion
  - **Edge Relationship Validation**: Ensure all edge sources and destinations exist or are being created in the same operation

#### **UPDATE Operations** ⚠️ **HIGH RISK**
- ❌ **Current Issue**: May add new triples without removing old ones
- 🔍 **Required Implementation**:
  - **Pre-existence Validation**: For each unique subject URI in the graph objects being updated, verify it already exists in the database
  - **Complete Subject Deletion**: Delete ALL existing triples for each subject URI before inserting new triples
  - **Atomic Replacement**: DELETE all subject triples → VALIDATE new data → INSERT new triples → UPDATE grouping URIs
- 🔍 **Critical Review Areas**:
  - **Entity Updates**: When entity properties change, old property triples must be deleted
  - **Frame Updates**: Frame property changes, slot additions/removals
  - **Slot Updates**: Value changes, type changes, relationship updates
  - **Edge Updates**: Source/destination changes, relationship type changes

#### **UPSERT Operations** ⭐ **NEW FUNCTIONALITY**
- 🆕 **Implementation Required**: Combine CREATE and UPDATE logic
- 📋 **Logic Flow**:
  - For each unique subject URI in the graph objects:
    - If subject exists: Apply UPDATE logic (delete existing + insert new)
    - If subject doesn't exist: Apply CREATE logic (insert new)
- 🔧 **Benefits**: 
  - Simplifies client code (no need to check existence first)
  - Atomic operation for mixed scenarios
  - Reduces round-trip API calls

#### **REST API Pattern** ✅ **QUERY PARAMETER APPROACH**
- 🎯 **Endpoint Structure**:
  ```http
  POST /spaces/{space_id}/graphs/{graph_id}/entities?operation_mode=create
  POST /spaces/{space_id}/graphs/{graph_id}/entities?operation_mode=update  
  POST /spaces/{space_id}/graphs/{graph_id}/entities?operation_mode=upsert
  
  POST /spaces/{space_id}/graphs/{graph_id}/frames?operation_mode=create
  POST /spaces/{space_id}/graphs/{graph_id}/frames?operation_mode=update
  POST /spaces/{space_id}/graphs/{graph_id}/frames?operation_mode=upsert
  ```
- 📋 **Parameter Definition**:
  ```python
  class OperationMode(str, Enum):
      CREATE = "create"    # Insert only - fail if any subject exists
      UPDATE = "update"    # Update only - fail if any subject missing  
      UPSERT = "upsert"    # Insert or update - handle mixed scenarios
  
  operation_mode: OperationMode = OperationMode.CREATE  # Default for backward compatibility
  ```
- 🚨 **Response Model with Application Error Codes**:
  ```http
  # All requests return 200 OK with application-level status
  
  # SUCCESS Response
  200 OK
  {
    "status": "success",
    "operation_mode": "create|update|upsert",
    "created_count": 5,
    "updated_count": 0,
    "failed_count": 0,
    "results": [...]
  }
  
  # CREATE mode - subject exists
  200 OK
  {
    "status": "error",
    "error_code": "SUBJECT_EXISTS",
    "message": "One or more subjects already exist",
    "operation_mode": "create",
    "created_count": 0,
    "failed_count": 3,
    "existing_subjects": ["http://vital.ai/app/Entity/123", "..."],
    "details": "CREATE operation requires all subjects to be new"
  }
  
  # UPDATE mode - subject missing  
  200 OK
  {
    "status": "error", 
    "error_code": "SUBJECT_NOT_FOUND",
    "message": "One or more subjects do not exist",
    "operation_mode": "update",
    "updated_count": 0,
    "failed_count": 2,
    "missing_subjects": ["http://vital.ai/app/Entity/456", "..."],
    "details": "UPDATE operation requires all subjects to exist"
  }
  ```

#### **Response Model Definition**
```python
class OperationStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    PARTIAL = "partial"  # Some succeeded, some failed

class ErrorCode(str, Enum):
    SUBJECT_EXISTS = "SUBJECT_EXISTS"
    SUBJECT_NOT_FOUND = "SUBJECT_NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    STORAGE_ERROR = "STORAGE_ERROR"
    GROUPING_URI_ERROR = "GROUPING_URI_ERROR"

class OperationResponse(BaseModel):
    status: OperationStatus
    operation_mode: OperationMode
    created_count: int = 0
    updated_count: int = 0
    failed_count: int = 0
    
    # Success fields
    results: Optional[List[Dict]] = None
    
    # Error fields (only present when status != "success")
    error_code: Optional[ErrorCode] = None
    message: Optional[str] = None
    details: Optional[str] = None
    existing_subjects: Optional[List[str]] = None
    missing_subjects: Optional[List[str]] = None
    failed_subjects: Optional[List[Dict]] = None  # Subject + reason
```

#### **DELETE Operations**
- 🔍 **Review Needed**:
  - **Cascade Deletion**: When entity deleted, ensure all frames/slots/edges are removed
  - **Partial Deletion**: When frame deleted, ensure slots and edges are cleaned up
  - **Orphan Prevention**: Ensure no dangling references remain
  - **Grouping URI Cleanup**: Remove grouping URI references

#### **Grouping URI Block Operations** ⭐ **LEVERAGE EXISTING FUNCTIONALITY**
- 🎯 **Entity Graph Replacement**: 
  - Use grouping URIs to get entire entity graph as a block
  - Delete entire entity graph by grouping URI
  - Replace with new entity graph atomically
  - **Use Case**: Complete entity replacement without manual triple management
- 🎯 **Frame Graph Replacement**:
  - Use grouping URIs to get entire frame graph as a block  
  - Delete entire frame graph by grouping URI
  - Replace with new frame graph atomically
  - **Use Case**: Complete frame replacement including all slots and edges
- 🔧 **Implementation Strategy**:
  - Leverage existing `include_entity_graph` and `include_frame_graph` parameters
  - Add `replace_entity_graph` and `replace_frame_graph` operations
  - Use grouping URI queries for efficient block operations
  - Ensure atomic replacement (delete old block + insert new block)

### Stale Triple Prevention Strategy

#### **Atomic Operation Patterns**

```python
def atomic_create_operation(graph_objects, operation_mode="create"):
    # 1. Extract unique subject URIs from graph objects
    subject_uris = extract_unique_subjects(graph_objects)
    
    # 2. Check pre-existence based on operation mode
    if operation_mode == "create":
        existing_subjects = check_subjects_exist(subject_uris)
        if existing_subjects:
            raise ConflictError(f"Subjects already exist: {existing_subjects}")
    elif operation_mode == "update":
        missing_subjects = check_subjects_missing(subject_uris)
        if missing_subjects:
            raise NotFoundError(f"Subjects don't exist: {missing_subjects}")
    # upsert mode: no pre-checks needed
    
    # 3. For UPDATE/UPSERT: Delete existing triples for each subject
    if operation_mode in ["update", "upsert"]:
        for subject_uri in subject_uris:
            if subject_exists(subject_uri):
                delete_all_subject_triples(subject_uri)
    
    # 4. Validate new data
    validate_graph_objects(graph_objects)
    
    # 5. Insert new triples
    new_triples = convert_objects_to_triples(graph_objects)
    insert_triples(new_triples)
    
    # 6. Set grouping URIs atomically
    set_grouping_uris(new_triples, get_primary_subject(graph_objects))

def atomic_graph_replacement(grouping_uri, new_graph_objects):
    # 1. Get existing graph by grouping URI
    existing_graph = get_graph_by_grouping_uri(grouping_uri)
    
    # 2. Delete entire existing graph block
    delete_graph_by_grouping_uri(grouping_uri)
    
    # 3. Insert new graph block
    new_triples = convert_objects_to_triples(new_graph_objects)
    insert_triples(new_triples)
    
    # 4. Set grouping URIs for new graph
    set_grouping_uris(new_triples, grouping_uri)
```

#### **Edge Relationship Management**
- **Before Entity/Frame Update**: Query and store existing edge relationships
- **After Update**: Reconcile edges - delete orphaned, update changed, preserve valid
- **Validation**: Ensure all edge sources and destinations exist

#### **Grouping URI Consistency**
- **Server Authority**: Server must strip client-provided grouping URIs and set authoritatively
- **Update Sequence**: Set grouping URIs AFTER all triples are successfully inserted
- **Validation**: Verify all components have correct grouping URIs

### Comprehensive Testing Requirements

#### **Update Integrity Tests**
```python
def test_entity_update_no_stale_triples():
    # 1. Create entity with initial data
    # 2. Query all triples for entity
    # 3. Update entity with new data
    # 4. Query all triples again
    # 5. Verify no old triples remain
    # 6. Verify all new triples present
    # 7. Verify grouping URIs correct
```

#### **Edge Case Testing**
- **Partial Update Failures**: Ensure rollback leaves no partial state
- **Concurrent Modifications**: Test race conditions in update operations
- **Large Graph Updates**: Test performance and consistency with complex entity graphs
- **Property Type Changes**: Test slot value type changes (text → integer, etc.)
- **Relationship Changes**: Test edge source/destination updates

#### **Stale Triple Detection**
```python
def detect_stale_triples(entity_uri):
    # Query for triples that reference entity but aren't properly linked
    # Check for orphaned edges
    # Verify grouping URI consistency
    # Report any inconsistencies
```

### Implementation Guidelines

#### **Helper Methods Needed**

##### **Subject Existence & Management**
- `extract_unique_subjects(graph_objects)` - Extract all unique subject URIs from graph objects
- `check_subjects_exist(subject_uris)` - Return list of subjects that already exist in database
- `check_subjects_missing(subject_uris)` - Return list of subjects that don't exist in database
- `subject_exists(subject_uri)` - Check if single subject exists
- `delete_all_subject_triples(subject_uri)` - Remove ALL triples for a specific subject

##### **Graph Block Operations**
- `get_graph_by_grouping_uri(grouping_uri)` - Retrieve entire graph using grouping URI
- `delete_graph_by_grouping_uri(grouping_uri)` - Delete entire graph block by grouping URI
- `get_entity_graph_by_grouping_uri(entity_uri)` - Get complete entity graph including frames/slots
- `get_frame_graph_by_grouping_uri(frame_uri)` - Get complete frame graph including slots

##### **Operation Mode Support**
- `atomic_create_operation(graph_objects, operation_mode)` - Handle create/update/upsert logic
- `atomic_graph_replacement(grouping_uri, new_graph_objects)` - Replace entire graph blocks

##### **Client API Updates Needed**
- Add `operation_mode` parameter to `create_kgentity()`, `create_entity_frames()`, `create_frame_slots()`
- Add `operation_mode` parameter to `create_kgframe()` and related frame operations
- Update method signatures: `create_kgentity(space_id, graph_id, document, operation_mode="create")`
- Add validation for `operation_mode` enum values

##### **Server Endpoint Updates Needed**  
- Add `operation_mode` query parameter parsing to all POST endpoints
- Update route handlers to pass `operation_mode` to business logic

---

## 📊 **OVERALL PROGRESS SUMMARY**

### **Completed Tasks:**
- ✅ **Task #1: MockKGFramesEndpoint Integration** - 100% Complete
  - VitalSigns integration patterns implemented
  - Property object handling working
  - Grouping URI enforcement (`frameGraphURI`) implemented
  - isinstance() type checking complete
  - Native JSON-LD conversion working
  - All 5/5 integration tests passing

- ✅ **Task #2: Data Lifecycle Management & Stale Triple Prevention** - 100% Complete
  - Atomic update operations with rollback capability
  - Stale triple detection and cleanup utilities
  - Edge relationship management with referential integrity
  - Server-authoritative grouping URI enforcement
  - Operation mode support (create/update/upsert)
  - All 4/4 data lifecycle tests passing

- ✅ **Task #3: KGEntities Endpoint Enhancement** - 100% Complete
  - Complete architectural parity with MockKGFramesEndpoint
  - Operation mode support (CREATE/UPDATE/UPSERT) with proper validation
  - Entity graph structure validation (entity→frame→frame→slot)
  - Parent URI support with connection validation
  - Atomic operations with backup/rollback capability
  - Entity lifecycle management test passing

- ✅ **Task #4: Graph-Level Operations Enhancement** - 100% Complete
  - Enhanced GET operations with graph-level retrieval parameters
  - `get_kgentity()` with `include_entity_graph` parameter working
  - `get_kgframe()` with `include_frame_graph` parameter implemented
  - Efficient SPARQL queries using grouping URIs
  - Complete graph structures in single operations
  - Graph-level retrieval tests passing

### **Current Status:**
- **MockKGFramesEndpoint**: ✅ Production-ready with complete VitalSigns integration, proper graph-level operations (CREATE/UPDATE/UPSERT), AND efficient graph retrieval
- **MockKGEntitiesEndpoint**: ✅ **ENHANCED** with complete architectural parity - proper graph-level operations, structure validation, atomic operations, AND efficient graph retrieval
- **Architecture**: ✅ Clear distinction established between main endpoints (whole graph operations) vs sub-endpoints (contextual operations)
- **Graph Operations**: ✅ Both endpoints support efficient complete graph retrieval in single operations

### **✅ Completed Tasks:**
1. **✅ COMPLETE**: Task #5 - Frame-Level Grouping URI Implementation (dual grouping URIs working perfectly)
2. **✅ COMPLETE**: Task #6 - Test Data Edge Model Updates (all tests passing with correct edge model)

### **🚨 HIGH PRIORITY - Next Required Task:**
**Task #7: Contextual Sub-Endpoint Operations - REQUIRED**

**Status**: 🔄 **IN PROGRESS** - Core functionality missing

**Missing Required Sub-Endpoints:**
- **`/kgentities/kgframes`** - Batch operations on N frames within entity context
  - POST with operation_mode=create/update/upsert, DELETE with frame_uris query parameter, GET operations
- **`/kgframes/kgframes`** - Batch operations on N child frames within parent frame context  
  - POST with operation_mode=create/update/upsert, DELETE with frame_uris query parameter, GET operations
- **`/kgframes/kgslots`** - Batch operations on N slots within frame context
  - POST with operation_mode=create/update/upsert, DELETE with slot_uris query parameter, GET operations

**Priority**: **HIGH** - These are core CRUD operations, not optional features

---

## 🚨 **Task #7: Contextual Sub-Endpoint Operations - DETAILED SPECIFICATION**

### **Status: 🔄 IN PROGRESS - REQUIRED FUNCTIONALITY**

### **Objective:**
Implement contextual CRUD operations that allow manipulation of frames within entities and slots within frames, without requiring full graph replacement operations.

### **Problem Identified:**
Current implementation only supports whole-graph operations:
- `create_kgentities()` - Creates entire entity graph
- `create_kgframes()` - Creates entire frame graph

**Missing contextual operations:**
- Creating/updating/deleting frames within an existing entity
- Creating/updating/deleting slots within an existing frame
- Maintaining referential integrity during partial operations

### **Implementation Requirements:**

#### **1. Sub-Endpoint: `/kgentities/kgframes` - Entity-Frame Operations**
**Batch operations on N frames within parent entity context:**
- `POST /kgentities/kgframes?entity_uri={uri}&operation_mode=create` - **CREATE** N frames in entity (fail if any exist)
- `POST /kgentities/kgframes?entity_uri={uri}&operation_mode=update` - **UPDATE** N frames in entity (fail if any don't exist)  
- `POST /kgentities/kgframes?entity_uri={uri}&operation_mode=upsert` - **UPSERT** N frames in entity (mixed create/update)
- `DELETE /kgentities/kgframes?entity_uri={uri}&frame_uris={uri1,uri2,uri3}` - **DELETE** N frames from entity (comma-separated URIs)
- `GET /kgentities/kgframes?entity_uri={uri}` - **RETRIEVE** all frames for entity

#### **2. Sub-Endpoint: `/kgframes/kgframes` - Parent-Child Frame Operations**
**Batch operations on N child frames within parent frame context:**
- `POST /kgframes/kgframes?parent_frame_uri={uri}&operation_mode=create[&entity_uri={entity_uri}]` - **CREATE** N child frames in parent frame
- `POST /kgframes/kgframes?parent_frame_uri={uri}&operation_mode=update[&entity_uri={entity_uri}]` - **UPDATE** N child frames in parent frame
- `POST /kgframes/kgframes?parent_frame_uri={uri}&operation_mode=upsert[&entity_uri={entity_uri}]` - **UPSERT** N child frames in parent frame
- `DELETE /kgframes/kgframes?parent_frame_uri={uri}&frame_uris={uri1,uri2,uri3}[&entity_uri={entity_uri}]` - **DELETE** N child frames (comma-separated URIs)
- `GET /kgframes/kgframes?parent_frame_uri={uri}[&entity_uri={entity_uri}]` - **RETRIEVE** all child frames for parent frame

#### **3. Sub-Endpoint: `/kgframes/kgslots` - Frame-Slot Operations**
**Batch operations on N slots within parent frame context:**
- `POST /kgframes/kgslots?frame_uri={uri}&operation_mode=create[&entity_uri={entity_uri}]` - **CREATE** N slots in frame (fail if any exist)
- `POST /kgframes/kgslots?frame_uri={uri}&operation_mode=update[&entity_uri={entity_uri}]` - **UPDATE** N slots in frame (fail if any don't exist)
- `POST /kgframes/kgslots?frame_uri={uri}&operation_mode=upsert[&entity_uri={entity_uri}]` - **UPSERT** N slots in frame (mixed create/update)
- `DELETE /kgframes/kgslots?frame_uri={uri}&slot_uris={uri1,uri2,uri3}[&entity_uri={entity_uri}]` - **DELETE** N slots from frame (comma-separated URIs)
- `GET /kgframes/kgslots?frame_uri={uri}[&entity_uri={entity_uri}]` - **RETRIEVE** all slots for frame

#### **4. Operation Mode Semantics**
- **CREATE (operation_mode=create)**: All N objects must not exist, fail if any exist
- **UPDATE (operation_mode=update)**: All N objects must exist, fail if any don't exist  
- **UPSERT (operation_mode=upsert)**: Mixed operations - create new, update existing
- **DELETE**: Remove specified objects by comma-separated URI query parameters and their relationships
- **Atomic operations**: All succeed or all fail with rollback

#### **5. Edge Relationship Management & Validation**
- **Entity→Frame**: Use `Edge_hasEntityKGFrame` for `/kgentities/kgframes` operations
- **Frame→Frame**: Use `Edge_hasKGFrame` for `/kgframes/kgframes` operations (parent-child)
- **Frame→Slot**: Use `Edge_hasKGSlot` for `/kgframes/kgslots` operations
- **Validate parent existence** before contextual operations
- **Maintain edge relationships** between parent and child objects
- **Preserve grouping URIs** for both entity-level and frame-level grouping
- **Handle orphaned edges** when deleting child objects

#### **6. Sub-Endpoint Validation Requirements**

##### **Connection Validation (Pre-Operation):**
- **DELETE**: Validate that slot/frame is connected to parent entity/frame before deletion
- **UPDATE**: Validate that slot/frame is connected to parent entity/frame (edge must be present)
- **UPSERT**: Identify if slot/frame is already attached to parent or not
  - If attached → UPDATE operation
  - If not attached → CREATE operation with new edge

##### **Grouping URI Selection & Validation:**
- **Use grouping URIs** to select the whole frame being modified for:
  - DELETE operations (identify connected objects)
  - UPDATE operations (identify existing objects)
  - UPSERT operations (determine which are update vs create)

##### **Entity URI Assertion (Critical Validation):**
- **Optional entity_uri parameter** for all sub-endpoints:
  - `/kgframes` (top level)
  - `/kgframes/kgframes` (sub-endpoint)
  - `/kgframes/kgslots` (sub-endpoint)
- **Purpose**: Assert that frame/slot belongs to specified parent entity
- **Validation Logic**:
  - If `entity_uri` provided → Assert all objects have matching `kGGraphURI`
  - If `entity_uri` NOT provided but objects have `kGGraphURI` set → **ERROR**
  - Return validation error **BEFORE** any database modifications
- **Grouping URI Assertion**: On UPDATE/UPSERT operations, assert correct grouping URIs on all objects

#### **7. Response Models & Operation Modes**
- **Consistent response structure** with existing endpoints
- **Operation counters**: `created_count`, `updated_count`, `deleted_count`, `failed_count`
- **Error handling**: Proper validation and rollback on failures
- **Batch results**: Success/failure status for each object in batch

### **Files to Modify:**
1. **MockKGEntitiesEndpoint**: Add entity-frame contextual methods
2. **MockKGFramesEndpoint**: Add frame-slot contextual methods  
3. **Test files**: Update `test_kg_endpoint_enhancements.py` to pass
4. **Response models**: Ensure proper response structure

### **Expected Outcome:**
- ✅ **Contextual frame operations** within entity graphs
- ✅ **Contextual slot operations** within frame graphs
- ✅ **Referential integrity** maintained during partial operations
- ✅ **All enhancement tests passing** in `test_kg_endpoint_enhancements.py`

### **Priority: HIGH** - Required for complete CRUD functionality

### **🎯 CORE FUNCTIONALITY STATUS:**
- ✅ **Basic Entity and Frame CRUD operations** (whole graph operations)
- ✅ **Dual grouping URI system** (entity-level + frame-level)
- ✅ **Complete graph retrieval functionality** 
- ✅ **Correct edge model implementation**
- ✅ **All tests passing with proper validation**
- ❌ **Contextual sub-operations** (frames within entities, slots within frames) - **MISSING**

### **Key Achievements:**
- **VitalSigns Integration**: Complete alignment between MockKGEntitiesEndpoint and MockKGFramesEndpoint
- **Property Naming Standards**: Established consistent VitalSigns property conventions
- **Grouping URI System**: Implemented both entity-level (`kGGraphURI`) and frame-level (`frameGraphURI`) grouping
- **Data Lifecycle Management**: Atomic operations, stale triple prevention, and rollback capability
- **Operation Modes**: Full create/update/upsert support with proper validation
- **Test Infrastructure**: Comprehensive integration and lifecycle test suites with 100% pass rates
- **Production Readiness**: MockKGFramesEndpoint ready for enterprise-level usage with data integrity guarantees

**The foundation for advanced KG operations is now complete and ready for the next phase of development!** 🚀
- Implement subject existence checking before operations
- **Response Model Updates**:
  - Always return 200 OK with application-level status
  - Include `status`, `error_code`, `message` fields
  - Add operation counters: `created_count`, `updated_count`, `failed_count`
  - Include specific error details: `existing_subjects`, `missing_subjects`
  - Maintain backward compatibility with existing response structure

##### **Legacy Methods (Still Needed)**
- `delete_entity_triples(entity_uri)` - Remove all triples for entity
- `delete_frame_triples(frame_uri)` - Remove all triples for frame  
- `cleanup_orphaned_edges(subject_uri)` - Remove dangling edge references
- `validate_graph_consistency(graph_id)` - Check for stale triples

#### **Error Handling**
- **Validation Failures**: Rollback any partial changes
- **Storage Failures**: Ensure atomic operations or proper cleanup
- **Concurrent Access**: Handle race conditions gracefully

#### **Monitoring & Logging**
- Log all triple deletions and insertions
- Track grouping URI assignments
- Monitor for stale triple detection
- Alert on data consistency violations

### Success Criteria
1. ✅ **Zero Stale Triples**: Update operations leave no orphaned data
2. ✅ **Atomic Operations**: Updates are all-or-nothing
3. ✅ **Operation Mode Support**: CREATE/UPDATE/UPSERT modes work correctly
   - CREATE: Fails if any subject already exists
   - UPDATE: Fails if any subject doesn't exist, deletes all existing triples first
   - UPSERT: Handles mixed scenarios (some exist, some don't)
4. ✅ **Subject-Level Triple Management**: Complete deletion of all triples per subject before replacement
5. ✅ **Grouping URI Block Operations**: Efficient graph replacement using grouping URIs
6. ✅ **Consistent Grouping URIs**: All components have correct grouping URIs
7. ✅ **Edge Integrity**: No orphaned or invalid edge relationships
8. ✅ **Performance**: Update operations complete efficiently
9. ✅ **Test Coverage**: Comprehensive tests validate all scenarios including new operation modes

---

6. **Continue with remaining phases** (Property management, Server endpoints, etc.)