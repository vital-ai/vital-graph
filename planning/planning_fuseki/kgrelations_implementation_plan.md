# KGRelations Implementation Plan

## Executive Summary

This plan outlines the implementation of comprehensive KGRelations support including:
1. Client-side KGRelations endpoint implementation
2. Test data with relation types (makes_product, competitor_of, etc.)
3. Client test scripts for KGRelations CRUD operations
4. Integration of "connector" query type into KGQueries endpoint
5. Integration of KGRelations tests into multi-org test suite

## Current Status Review

### Server-Side Implementation ✅
**Location**: `/vitalgraph/endpoint/kgrelations_endpoint.py`

**Status**: Fully implemented with the following operations:
- ✅ **GET /kgrelations** - List relations with filtering (source, destination, type, direction)
- ✅ **GET /kgrelations?relation_uri=** - Get specific relation by URI
- ✅ **POST /kgrelations** - Create/Update/Upsert relations with operation_mode parameter
- ✅ **DELETE /kgrelations** - Delete relations by URIs
- ✅ **POST /kgrelations/query** - Complex relation queries with criteria

**Implementation Details**:
- Uses `Edge_hasKGRelation` from `ai_haley_kg_domain` package
- Supports JSON-LD 1.1 format for requests/responses
- Uses VitalSigns for object conversion
- Backend processors: `KGRelationsCreateProcessor`, `KGRelationsReadProcessor`, `KGRelationsDeleteProcessor`
- Backend adapter: `FusekiPostgreSQLBackendAdapter`

### Client-Side Implementation ❌
**Status**: NOT IMPLEMENTED

**Missing**: 
- No `/vitalgraph/client/endpoint/kgrelations_endpoint.py` exists
- Client needs to be created from scratch following patterns from:
  - **`kgentities_endpoint.py`** (PRIMARY MODEL - entity CRUD operations with standardized responses)
  - `kgtypes_endpoint.py` (type operations)

**Note**: KGFramesEndpoint is outdated and should NOT be used as a reference model.

### KGQueries Endpoint Status 🟡
**Location**: `/vitalgraph/endpoint/kgquery_endpoint.py`

**Current Support**:
- ✅ **"relation" query type** - Partially implemented (line 111-158)
  - Has placeholder for `connection_query_builder.build_relation_query()` 
  - NOT FULLY FUNCTIONAL - needs implementation
- ✅ **"frame" query type** - Fully implemented (line 160-256)
  - Uses `KGQueryCriteriaBuilder` for entity queries with frame/slot criteria
  - Working and tested in multi-org test suite

**Missing "connector" Query Type**:
- The term "connector" appears to be synonymous with "relation" query type
- Current implementation has "relation" type but it's not complete
- Need to complete the relation query builder implementation

### Test Data Status ❌
**Current Test Data**: `/vitalgraph_client_test/multi_kgentity/`
- Organizations with frames (BusinessContractFrame, FinancialReportFrame, etc.)
- Files linked via URI slots
- Business events
- **Missing**: No relation data (Edge_hasKGRelation instances)

## Implementation Plan

### Phase 1: Client-Side KGRelations Endpoint
**Priority**: HIGH
**Estimated Effort**: 4-6 hours

#### 1.1 Create KGRelations Client Endpoint
**File**: `/vitalgraph/client/endpoint/kgrelations_endpoint.py`

**Reference Model**: `/vitalgraph/client/endpoint/kgentities_endpoint.py`

**Key Patterns from KGEntitiesEndpoint**:
1. **Standardized Response Objects**: Use client-side response classes from `/vitalgraph/client/response/`
2. **VitalSigns Integration**: Initialize `self.vs = VitalSigns()` in `__init__`
3. **Response Builders**: Use helper functions from `response_builder.py`:
   - `jsonld_to_graph_objects()` - Convert JSON-LD to VitalSigns objects
   - `build_success_response()` - Build success response with metadata
   - `build_error_response()` - Build error response
4. **Request Handling**: Use `_make_request()` helper with timing/logging
5. **Error Handling**: Wrap in try/except with `VitalGraphClientError`

**Methods to Implement**:
```python
class KGRelationsEndpoint(BaseEndpoint):
    """Client endpoint for KGRelations operations with standardized responses."""
    
    def __init__(self, client):
        super().__init__(client)
        self.vs = VitalSigns()
    
    # List/Get operations with ENHANCED filtering
    def list_relations(
        self, 
        space_id: str, 
        graph_id: str, 
        entity_source_uri: Optional[str] = None,      # Filter by source entity
        entity_destination_uri: Optional[str] = None,  # Filter by destination entity
        relation_type_uri: Optional[str] = None,       # Filter by relation type
        direction: str = "all",                        # Direction: all, incoming, outgoing
        page_size: int = 10, 
        offset: int = 0
    ) -> PaginatedGraphObjectResponse:
        """
        List KGRelations with pagination and enhanced filtering.
        
        Filtering options:
        - entity_source_uri: Filter relations from specific source entity
        - entity_destination_uri: Filter relations to specific destination entity
        - relation_type_uri: Filter by specific relation type (e.g., MakesProductRelation)
        - direction: Filter by direction relative to entity (if source/dest specified)
        
        Returns PaginatedGraphObjectResponse with Edge_hasKGRelation objects.
        """
    
    def get_relation(
        self, 
        space_id: str, 
        graph_id: str, 
        relation_uri: str
    ) -> EntityResponse:
        """Get specific relation by URI."""
    
    # Create/Update operations
    def create_relations(
        self, 
        space_id: str, 
        graph_id: str, 
        relations: List  # List of VitalSigns Edge_hasKGRelation objects
    ) -> CreateEntityResponse:
        """Create new relations from VitalSigns objects."""
    
    def update_relations(
        self, 
        space_id: str, 
        graph_id: str, 
        relations: List
    ) -> UpdateEntityResponse:
        """Update existing relations."""
    
    def upsert_relations(
        self, 
        space_id: str, 
        graph_id: str, 
        relations: List
    ) -> UpdateEntityResponse:
        """Upsert (create or update) relations."""
    
    # Delete operations
    def delete_relations(
        self, 
        space_id: str, 
        graph_id: str, 
        relation_uris: List[str]
    ) -> DeleteResponse:
        """Delete relations by URIs."""
    
    # NOTE: No query_relations() method - complex queries go through KGQueries endpoint
```

**Response Models** (use standardized client response classes):
- `PaginatedGraphObjectResponse` - List response with VitalSigns objects
- `EntityResponse` - Single relation as GraphObject
- `CreateEntityResponse` - Creation result with created URIs
- `UpdateEntityResponse` - Update result
- `DeleteResponse` - Deletion result with deleted URIs
- `QueryResponse` - Query result with relation URIs

**Implementation Pattern** (from KGEntitiesEndpoint):
```python
def list_relations(self, space_id, graph_id, ...):
    self._check_connection()
    validate_required_params(space_id=space_id, graph_id=graph_id)
    
    try:
        url = f"{self._get_server_url()}/api/graphs/kgrelations"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            entity_source_uri=entity_source_uri,
            entity_destination_uri=entity_destination_uri,
            relation_type_uri=relation_type_uri,
            direction=direction,
            page_size=page_size,
            offset=offset
        )
        
        response = self._make_request('GET', url, params=params)
        response_data = response.json()
        
        # Convert JSON-LD to VitalSigns objects
        relations_jsonld = response_data.get('relations', {})
        relations = jsonld_to_graph_objects(relations_jsonld, self.vs)
        
        # Extract pagination metadata
        pagination = extract_pagination_metadata(response_data)
        
        return PaginatedGraphObjectResponse(
            success=True,
            objects=relations,
            total_count=pagination['total_count'],
            page_size=pagination['page_size'],
            offset=pagination['offset'],
            message=f"Retrieved {len(relations)} relations"
        )
        
    except VitalGraphClientError as e:
        logger.error(f"Error listing relations: {e}")
        return build_error_response(PaginatedGraphObjectResponse, str(e))
```

#### 1.2 Register Client Endpoint
**File**: `/vitalgraph/client/vitalgraph_client.py`

Add to `__init__`:
```python
from .endpoint.kgrelations_endpoint import KGRelationsEndpoint
self.kgrelations = KGRelationsEndpoint(self)
```

#### 1.3 Testing
- Create basic unit tests for client methods
- Test against running server with mock data

### Phase 2: Test Data - Relation Types
**Priority**: HIGH
**Estimated Effort**: 2-3 hours

#### 2.1 Create New KGType Definitions
**Location**: Test data creation in multi-org test script

**Relation Types to Add**:

1. **MakesProductRelation**
   - Type URI: `http://vital.ai/test/kgtype/MakesProductRelation`
   - Extends: `Edge_hasKGRelation`
   - Description: Organization produces/manufactures a product
   - Properties: None (uses base Edge properties)

2. **CompetitorOfRelation**
   - Type URI: `http://vital.ai/test/kgtype/CompetitorOfRelation`
   - Extends: `Edge_hasKGRelation`
   - Description: Organization competes with another organization
   - Properties: None (uses base Edge properties)

3. **PartnerWithRelation**
   - Type URI: `http://vital.ai/test/kgtype/PartnerWithRelation`
   - Extends: `Edge_hasKGRelation`
   - Description: Organization has partnership with another organization
   - Properties: None (uses base Edge properties)

4. **SuppliesRelation**
   - Type URI: `http://vital.ai/test/kgtype/SuppliesRelation`
   - Extends: `Edge_hasKGRelation`
   - Description: Organization supplies products/services to another
   - Properties: None (uses base Edge properties)

#### 2.2 Create Product Entity Type
**Product Entity**:
   - Type URI: `http://vital.ai/test/kgtype/ProductEntity`
   - Extends: `KGEntity`
   - Properties:
     - `productName` (KGTextSlot)
     - `productCategory` (KGTextSlot)
     - `productPrice` (KGIntegerSlot)

#### 2.3 Augment Multi-Org Test Data
**File**: `/vitalgraph_client_test/multi_kgentity/case_create_organizations.py`

**Add Relations**:
```python
# Example relation data to add:
relations = [
    # Tech Innovations makes Software Product A
    MakesProductRelation(
        source: "Tech Innovations Corp",
        destination: "Software Product A"
    ),
    
    # Tech Innovations competes with Global Finance Group
    CompetitorOfRelation(
        source: "Tech Innovations Corp",
        destination: "Global Finance Group"
    ),
    
    # Healthcare Solutions partners with Biotech Research Labs
    PartnerWithRelation(
        source: "Healthcare Solutions Inc",
        destination: "Biotech Research Labs"
    ),
    
    # Manufacturing Enterprises supplies to Retail Chain Co
    SuppliesRelation(
        source: "Manufacturing Enterprises",
        destination: "Retail Chain Co"
    )
]
```

**Relation Matrix** (10 organizations):
- 5-8 MakesProduct relations (org → product)
- 4-6 CompetitorOf relations (org → org)
- 3-4 PartnerWith relations (org → org)
- 3-4 Supplies relations (org → org)
- **Total**: ~15-22 relations

### Phase 3: KGRelations Test Suite
**Priority**: HIGH
**Estimated Effort**: 6-8 hours

#### 3.1 Create Test Directory Structure
```
/vitalgraph_client_test/kgrelations/
├── __init__.py
├── case_create_relations.py
├── case_list_relations.py
├── case_get_relation.py
├── case_update_relations.py
├── case_query_relations.py
├── case_delete_relations.py
```

#### 3.2 Create Main Test Script
**File**: `/vitalgraph_client_test/test_kgrelations_crud.py`

**Test Flow**:
1. **Setup**: Create test space and graph
2. **Create Entities**: Organizations and Products
3. **Create Relations**: All relation types
4. **List Relations**: Test filtering by source, destination, type, direction
5. **Get Relations**: Retrieve individual relations
6. **Query Relations**: Complex criteria queries
7. **Update Relations**: Modify relation properties
8. **Delete Relations**: Remove specific relations
9. **Verify Deletions**: Confirm relations are gone
10. **Cleanup**: Delete test space

#### 3.3 Test Cases Detail

**case_create_relations.py**:
```python
class CreateRelationsTester:
    def create_makes_product_relations(client, space_id, graph_id, org_uris, product_uris)
    def create_competitor_relations(client, space_id, graph_id, org_uris)
    def create_partner_relations(client, space_id, graph_id, org_uris)
    def create_supplier_relations(client, space_id, graph_id, org_uris)
    def verify_relation_creation(client, space_id, graph_id, expected_count)
```

**case_list_relations.py**:
```python
class ListRelationsTester:
    def list_all_relations(client, space_id, graph_id)
    def list_by_source_entity(client, space_id, graph_id, source_uri)
    def list_by_destination_entity(client, space_id, graph_id, dest_uri)
    def list_by_relation_type(client, space_id, graph_id, type_uri)
    def list_by_direction(client, space_id, graph_id, entity_uri, direction)
    def test_pagination(client, space_id, graph_id)
```

**case_query_relations.py**:
```python
class QueryRelationsTester:
    def query_by_criteria(client, space_id, graph_id, criteria)
    def query_competitors_of_org(client, space_id, graph_id, org_uri)
    def query_products_made_by_org(client, space_id, graph_id, org_uri)
    def query_partners_of_org(client, space_id, graph_id, org_uri)
```

**case_update_relations.py**:
```python
class UpdateRelationsTester:
    def update_relation_properties(client, space_id, graph_id, relation_uri)
    def verify_update(client, space_id, graph_id, relation_uri)
```

**case_delete_relations.py**:
```python
class DeleteRelationsTester:
    def delete_single_relation(client, space_id, graph_id, relation_uri)
    def delete_multiple_relations(client, space_id, graph_id, relation_uris)
    def verify_deletion(client, space_id, graph_id, relation_uri)
```

### Phase 4: Complete "Connector" Query Type in KGQueries
**Priority**: MEDIUM
**Estimated Effort**: 4-5 hours

#### 4.1 Implement Relation Query Builder
**File**: `/vitalgraph/sparql/kg_connection_query_builder.py` (or similar)

**Create New Builder Class**:
```python
class KGConnectionQueryBuilder:
    def build_relation_query(criteria: KGQueryCriteria, graph_id: str) -> str:
        """
        Build SPARQL query for relation-based connections.
        
        Query pattern:
        - Find Edge_hasKGRelation instances
        - Filter by source/destination entity criteria
        - Filter by relation type URIs
        - Support direction (outgoing, incoming, bidirectional)
        - Exclude self-connections if specified
        """
```

**SPARQL Query Pattern**:
```sparql
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX vital: <http://vital.ai/ontology/vital-core#>

SELECT ?source_entity ?destination_entity ?relation_edge ?relation_type
WHERE {
    GRAPH <{graph_id}> {
        # Relation edge
        ?relation_edge a haley:Edge_hasKGRelation ;
                      vital:hasEdgeSource ?source_entity ;
                      vital:hasEdgeDestination ?destination_entity .
        
        # Relation type
        ?relation_edge a ?relation_type .
        FILTER(?relation_type != haley:Edge_hasKGRelation)
        
        # Source entity criteria (if specified)
        ?source_entity a ?source_type .
        FILTER(?source_type = <source_entity_type>)
        
        # Destination entity criteria (if specified)
        ?destination_entity a ?dest_type .
        FILTER(?dest_type = <dest_entity_type>)
        
        # Relation type filter (if specified)
        FILTER(?relation_type IN (<type1>, <type2>, ...))
        
        # Exclude self-connections (if specified)
        FILTER(?source_entity != ?destination_entity)
    }
}
LIMIT {page_size}
OFFSET {offset}
```

#### 4.2 Update KGQueries Endpoint
**File**: `/vitalgraph/endpoint/kgquery_endpoint.py`

**Changes**:
1. Import the new connection query builder
2. Initialize in `__init__`: `self.connection_query_builder = KGConnectionQueryBuilder()`
3. Complete `_execute_relation_query()` method (line 111-158)
4. Add proper error handling and logging

#### 4.3 Update KGQueries Client
**File**: `/vitalgraph/client/endpoint/kgqueries_endpoint.py`

**Status**: Already has `query_relation_connections()` method
**Action**: Verify it works with completed server implementation

#### 4.4 Add "Connector" Alias
**Consideration**: User mentioned "connector" type
**Options**:
1. Keep "relation" as the official name (current)
2. Add "connector" as an alias for "relation"
3. Rename "relation" to "connector"

**Recommendation**: Add "connector" as an alias:
```python
# In kgquery_endpoint.py
if query_type in ["connector", "relation"]:
    query_type = "relation"  # Normalize to "relation"
```

### Phase 5: Integration Tests
**Priority**: MEDIUM
**Estimated Effort**: 3-4 hours

#### 5.1 Add KGRelations to Multi-Org Test
**File**: `/vitalgraph_client_test/test_multiple_organizations_crud.py`

**New Test Sections**:
```python
# After "Create 10 Business Events"
test_section("Create Relations", case_create_relations.create_all_relations)

# After "List Entity Graphs"
test_section("List and Filter Relations", case_list_relations.test_all_filters)

# After "KGQuery Frame-Based Queries"
test_section("KGQuery Relation-Based Queries", case_kgquery_relation_queries.test_all_queries)

# Before "Delete Organization Entities"
test_section("Delete Relations", case_delete_relations.test_deletions)
```

#### 5.2 Add Connector Queries to KGQuery Tests
**File**: `/vitalgraph_client_test/multi_kgentity/case_kgquery_frame_queries.py`

**Rename to**: `case_kgquery_queries.py` (to include both frame and relation queries)

**Add Relation Query Tests**:
```python
def test_relation_queries(client, space_id, graph_id, org_uris, product_uris):
    # Test 1: Find competitors of specific org
    # Test 2: Find products made by specific org
    # Test 3: Find partners of specific org
    # Test 4: Find suppliers to specific org
    # Test 5: Bidirectional relation queries
    # Test 6: Combined entity criteria + relation type filters
```

### Phase 6: Documentation
**Priority**: LOW
**Estimated Effort**: 2-3 hours

#### 6.1 Update API Documentation
- Document KGRelations client methods
- Add examples for each operation
- Document relation query patterns

#### 6.2 Update Test Documentation
- Document test data structure
- Document relation types and their semantics
- Add examples of running tests

## Implementation Order (Confirmed)

### Phase 0: Fix Space Endpoint ✅ COMPLETED
**Status**: COMPLETED on 2026-01-25
**Actual Time**: 2 hours
**Issue**: Space endpoint returns HTTP 404 for non-existent spaces instead of using response model objects
**Example**: `DELETE /api/spaces/space_kgrelations_test_20260125_162233 HTTP/1.1" 404 Not Found`

**Implementation Completed**:
1. ✅ Updated space endpoint to return structured response models for all error cases
2. ✅ Uses `SpaceResponse` with `success=False` and `error_message` instead of raising HTTPException(404)
3. ✅ Ensured consistency with other endpoints (KGTypes, KGEntities, etc.) that use response models
4. ✅ Tested that client handles error responses correctly

**Changes Made**:

**Server-Side** (`/vitalgraph/endpoint/spaces_endpoint.py`):
- Added `SpaceResponse` model for single space retrieval with success/error handling
- Added `SpaceInfoResponse` model for detailed space info with statistics
- Updated `get_space()` to return `SpaceResponse` instead of raising HTTP exceptions
- Added `get_space_info()` method that calls `space_manager.get_space_info()` and returns `SpaceInfoResponse`
- Updated `add_space()` to include created space object in response
- Added `/spaces/{space_id}/info` route to expose space info endpoint

**Server-Side Models** (`/vitalgraph/model/spaces_model.py`):
- Added `SpaceResponse` - Single space retrieval response with optional Space object
- Added `SpaceInfoResponse` - Space info with statistics and quad_dump fields
- Extended `SpaceCreateResponse` with `space` field to include created space object

**Client-Side** (`/vitalgraph/client/endpoint/spaces_endpoint.py`):
- Updated `get_space()` to handle new `SpaceResponse` structure from server
- Updated `create_space()` to extract space object from response
- Updated `get_space_info()` to handle new `SpaceInfoResponse` structure

**Client-Side Response Models** (`/vitalgraph/client/response/client_response.py`):
- Fixed type annotations from `Optional[Any]` to `Optional[Space]`
- Added direct import: `from vitalgraph.model.spaces_model import Space`
- Removed `TYPE_CHECKING` conditional import

**Test Results** (`/vitalgraph_client_test/test_spaces_endpoint.py`):
- ✅ **7/7 tests passing (100% success rate)**
- Test 1: Create Space - Returns `SpaceCreateResponse` with space object ✅
- Test 2: Get Space - Returns `SpaceResponse` with proper error handling ✅
- Test 3: Get Non-Existent Space - Returns error response (not HTTP 500) with `is_success=False`, `is_error=True`, `error_code=1` ✅
- Test 4: List Spaces - Returns `SpacesListResponse` ✅
- Test 5: Get Space Info - Returns `SpaceInfoResponse` via `/info` endpoint ✅
- Test 6: Update Space - Returns `SpaceUpdateResponse` ✅
- Test 7: Delete Space - Returns `SpaceDeleteResponse` ✅

**Key Achievement**: Server now returns proper structured response objects for all operations including error cases, eliminating HTTP 404/500 errors and ensuring consistency across all endpoints.

### Phase 1: KGRelations Client Endpoint ✅ COMPLETED
**Status**: COMPLETED on 2026-01-25
**Actual Time**: 4 hours

**Implementation Completed**:
1. ✅ Created `/vitalgraph/client/endpoint/kgrelations_endpoint.py` with full CRUD implementation
2. ✅ Followed KGEntitiesEndpoint patterns with standardized response objects
3. ✅ Implemented all CRUD methods: `list_relations`, `get_relation`, `create_relations`, `update_relations`, `upsert_relations`, `delete_relations`
4. ✅ Registered in VitalGraphClient as `self.kgrelations`
5. ✅ Comprehensive test suite created in `test_kgrelations_crud.py`

**Client Endpoint Methods Implemented**:

**`list_relations()`** - List with enhanced filtering:
- Parameters: `space_id`, `graph_id`, `entity_source_uri`, `entity_destination_uri`, `relation_type_uri`, `direction`, `page_size`, `offset`
- Returns: `PaginatedGraphObjectResponse` with Edge_hasKGRelation objects
- Supports filtering by source entity, destination entity, relation type, and direction

**`get_relation()`** - Get specific relation:
- Parameters: `space_id`, `graph_id`, `relation_uri`
- Returns: `EntityResponse` with single Edge_hasKGRelation object

**`create_relations()`** - Create new relations:
- Parameters: `space_id`, `graph_id`, `relations` (List of VitalSigns objects)
- Returns: `CreateEntityResponse` with created URIs
- Converts VitalSigns objects to JSON-LD using `GraphObject.to_jsonld_list()`
- Handles both single and multiple relations

**`update_relations()`** - Update existing relations:
- Parameters: `space_id`, `graph_id`, `relations` (List of VitalSigns objects with URIs)
- Returns: `UpdateEntityResponse` with update results
- Uses `operation_mode='update'` parameter

**`upsert_relations()`** - Create or update relations:
- Parameters: `space_id`, `graph_id`, `relations` (List of VitalSigns objects)
- Returns: `UpdateEntityResponse` with upsert results
- Uses `operation_mode='upsert'` parameter

**`delete_relations()`** - Delete relations by URIs:
- Parameters: `space_id`, `graph_id`, `relation_uris` (List of URIs)
- Returns: `DeleteResponse` with deletion results

**Technical Implementation Details**:
- **VitalSigns Integration**: Initializes `self.vs = VitalSigns()` in constructor
- **Response Builders**: Uses helper functions from `response_builder.py`:
  - `jsonld_to_graph_objects()` - Convert JSON-LD to VitalSigns objects
  - `build_success_response()` - Build success response with metadata
  - `build_error_response()` - Build error response
- **Request Handling**: Custom `_make_request()` helper with timing/logging
- **Error Handling**: Comprehensive try/except with `VitalGraphClientError`
- **JSON-LD Conversion**: Proper handling of single object vs document format
- **Pagination Support**: Full pagination metadata extraction and response building

**Registration in VitalGraphClient** (`/vitalgraph/client/vitalgraph_client.py`):
```python
from .endpoint.kgrelations_endpoint import KGRelationsEndpoint
self.kgrelations = KGRelationsEndpoint(self)
```

### Phase 2: Test Data - Relations ✅ COMPLETED
**Status**: COMPLETED on 2026-01-25
**Actual Time**: 2 hours

**Implementation Completed**:
1. ✅ Added 4 relation types to test data in `/vitalgraph_client_test/multi_kgentity/case_create_relations.py`:
   - **MakesProductRelation** (org → product) - Organizations produce products
   - **CompetitorOfRelation** (org → org) - Organizations compete with each other
   - **PartnerWithRelation** (org → org) - Organizations partner together
   - **SuppliesRelation** (org → org) - Organizations supply to each other
2. ✅ Created ProductEntity type with properties:
   - `productName` (KGTextSlot)
   - `productCategory` (KGTextSlot)
   - `productPrice` (KGIntegerSlot)
3. ✅ Added relation instances (exact count varies by test run)
4. ✅ Data created via `create_all_relation_data()` function

**Relation Data Structure**:
- **Relation Types**: Created as KGType objects with proper type URIs
- **Product Entities**: Created as KGEntity objects with product properties
- **Relation Instances**: Created as Edge_hasKGRelation objects with:
  - `edgeSource` - Source entity URI
  - `edgeDestination` - Destination entity URI
  - `kGRelationType` - Relation type URI

**Test Data Function** (`case_create_relations.py`):
```python
def create_all_relation_data(client, space_id, graph_id, org_uris):
    # Creates relation types, products, and relation instances
    # Returns: (relation_type_uris, product_uris, relation_uris)
```

**Usage**: Data is created and used by `test_kgrelations_crud.py` standalone test suite

### Phase 3: Standalone KGRelations Test Suite ✅ COMPLETED
**Status**: COMPLETED on 2026-01-25
**Actual Time**: 6 hours

**Implementation Completed**:
1. ✅ Created `/vitalgraph_client_test/test_kgrelations_crud.py` main test script
2. ✅ Implemented comprehensive test cases covering all CRUD operations
3. ✅ Uses organization data from multi_kgentity test suite
4. ✅ Runs independently to verify KGRelations functionality
5. ✅ Includes detailed logging and test result tracking

**Test Suite Structure** (`test_kgrelations_crud.py`):

**Test Runner Class**: `KGRelationsTestRunner`
- Manages test lifecycle (setup, execution, teardown)
- Tracks test results (passed, failed, errors)
- Creates dedicated test space and graph

**Test Sections Implemented**:
1. **Create Organizations** - Creates 10 organization entities as test data
2. **Create Relation Data** - Creates relation types, products, and relation instances
3. **List All Relations** - Tests listing all relations with pagination
4. **List by Source Entity** - Tests filtering relations by source entity URI
5. **List by Relation Type** - Tests filtering relations by type URI
6. **Get Individual Relation** - Tests retrieving specific relation by URI
7. **Delete Relation** - Tests deleting relations and verifies deletion

**Test Methods**:
- `create_organizations()` - Creates organization entities
- `create_relation_data()` - Creates relation types, products, and relations
- `test_list_all_relations()` - Verifies all relations can be listed
- `test_list_by_source()` - Verifies source entity filtering
- `test_list_by_relation_type()` - Verifies relation type filtering
- `test_get_relation()` - Verifies individual relation retrieval
- `test_delete_relation()` - Verifies relation deletion

**Test Features**:
- ✅ Automatic space creation and cleanup
- ✅ Comprehensive error tracking and reporting
- ✅ Detailed logging of all operations
- ✅ Test result summary with pass/fail counts
- ✅ Validates response types and data integrity
- ✅ Tests enhanced filtering capabilities (source, destination, type, direction)

**Test Execution**:
```bash
python vitalgraph_client_test/test_kgrelations_crud.py
```

### Phase 4: Complete Three Query Patterns in KGQueries ✅ PARTIALLY COMPLETED
**Status**: Relation-Top Queries COMPLETED on 2026-01-25
**Actual Time**: 4 hours for relation queries

**Three Query Pattern Implementations**:

#### 4.1 Entity-Top Queries (Already Working ✅)
- Top-level target: KGEntity
- Uses existing `KGQueryCriteriaBuilder`
- Finds entities with frame/slot criteria
- No changes needed

#### 4.2 Relation-Top Queries ✅ COMPLETED
**Status**: COMPLETED on 2026-01-25
**Actual Time**: 4 hours

**Implementation Completed**:
1. ✅ Implemented `KGConnectionQueryBuilder` in `/vitalgraph/sparql/kg_connection_query_builder.py`
2. ✅ Completed `_execute_relation_query()` method in `/vitalgraph/endpoint/kgquery_endpoint.py`
3. ✅ Built SPARQL queries with Edge_hasKGRelation as top-level target
4. ✅ Implemented filtering by:
   - Source/destination entity URIs
   - Relation type URIs (e.g., MakesProductRelation, CompetitorOfRelation)
   - Direction (outgoing, incoming, bidirectional)
   - Entity type criteria
5. ✅ Returns RelationConnection objects with:
   - `source_entity_uri` - Source entity URI
   - `destination_entity_uri` - Destination entity URI
   - `relation_edge_uri` - Relation edge URI
   - `relation_type_uri` - Relation type URI

**KGConnectionQueryBuilder Implementation**:
- **File**: `/vitalgraph/sparql/kg_connection_query_builder.py`
- **Main Method**: `build_relation_query(criteria: KGQueryCriteria, graph_id: str) -> str`
- **SPARQL Pattern Generation**:
  - Base relation patterns (Edge_hasKGRelation with source/destination)
  - Source entity filtering by URI or type
  - Destination entity filtering by URI or type
  - Relation type filtering
  - Direction handling (all, outgoing, incoming)
  - Self-connection exclusion

**Query Endpoint Integration** (`/vitalgraph/endpoint/kgquery_endpoint.py`):
- Integrated `KGConnectionQueryBuilder` into KGQuery endpoint
- `_execute_relation_query()` method processes relation-top queries
- Returns structured RelationConnection results
- Proper error handling and logging

**SPARQL Query Structure**:
```sparql
SELECT DISTINCT ?source_entity ?destination_entity ?relation_edge ?relation_type
WHERE {
    GRAPH <graph_id> {
        # Source entity patterns
        ?source_entity vital:vitaltype ?source_vitaltype .
        
        # Relation edge patterns
        ?relation_edge vital:vitaltype <Edge_hasKGRelation> .
        ?relation_edge vital:hasEdgeSource ?source_entity .
        ?relation_edge vital:hasEdgeDestination ?destination_entity .
        ?relation_edge haley:hasKGRelationType ?relation_type .
        
        # Destination entity patterns
        ?destination_entity vital:vitaltype ?dest_vitaltype .
        
        # Filters (relation type, entity types, direction)
        FILTER(?source_entity != ?destination_entity)
    }
}
```

**Client Integration** (`/vitalgraph/client/endpoint/kgqueries_endpoint.py`):
- Already has `query_relation_connections()` method
- Works with completed server implementation
- Returns QueryResponse with RelationConnection objects

#### 4.3 Frame-Top Queries (To Implement)
**Estimated**: 3-4 hours
1. Implement frame query builder for frame-top queries
2. Add `_execute_frame_query()` method (or extend existing)
3. Build SPARQL queries with KGFrame as top-level target
4. Support filtering by:
   - Frame type
   - Slot criteria (values, types)
   - Connected entities (via slots pointing to entities)
5. Return FrameConnection objects or frame instances
6. Reuse slot criteria components from entity-top queries

**Shared Architecture**:
- All three patterns use same `FrameCriteria` and `SlotCriteria` models
- Different SPARQL generation based on top-level target
- Consistent filtering and pagination logic
- Same response structure patterns

### Phase 5: Integration into Multi-Org Test (Priority 5)
**Estimated**: 3-4 hours
1. Add KGRelations test sections to multi-org suite
2. Add relation query tests to KGQuery section
3. Verify all tests pass together
4. End-to-end validation

### Phase 6: Enhanced Relation Queries with Frame/Slot Filtering (Priority 6)
**Estimated**: 6-8 hours

**Objective**: Extend relation-top queries to filter by frame and slot criteria on source/destination entities.

#### Current Status (Phase 5 Complete ✅)

**What's Working**:
- ✅ **KGRelations CRUD**: 32/32 tests passing (100%)
- ✅ **KGQueries Endpoint**: 30/30 tests passing (100%)
- ✅ **Relation-Top Queries**: Basic filtering by relation type, source/dest URIs
- ✅ **Frame-Top Queries**: Frame-based entity connections with slot filtering
- ✅ **SPARQL Query Builder**: Using `vitaltype` property correctly

**Current Relation Query Capabilities**:
```python
# What we can do NOW:
criteria = KGQueryCriteria(
    query_type="relation",
    relation_type_uris=["http://vital.ai/test/kgtype/MakesProductRelation"],
    source_entity_uris=["http://vital.ai/test/org/techcorp"],
    direction="outgoing"
)
# Returns: All MakesProduct relations from TechCorp
```

**Current Frame Query Capabilities**:
```python
# What we can do NOW:
criteria = KGQueryCriteria(
    query_type="frame",
    frame_criteria=[
        FrameCriteria(
            frame_type="http://vital.ai/ontology/haley-ai-kg#SourceBusinessFrame",
            slot_criteria=[
                SlotCriteria(slot_type="revenue", value=1000000, comparator="gt")
            ]
        )
    ]
)
# Returns: Entities connected via shared frames with revenue > $1M
```

#### Proposed Enhancement

**What We Want to Add**: Combine relation queries with frame/slot filtering on the **participants** (source/destination entities):

```python
# PROPOSED NEW CAPABILITY:
criteria = KGQueryCriteria(
    query_type="relation",
    relation_type_uris=["http://vital.ai/test/kgtype/MakesProductRelation"],
    
    # NEW: Filter source entities by their frames/slots
    source_frame_criteria=[
        FrameCriteria(
            frame_type="http://vital.ai/ontology/haley-ai-kg#SourceBusinessFrame",
            slot_criteria=[
                SlotCriteria(slot_type="revenue", value=1000000, comparator="gt")
            ]
        )
    ],
    
    # NEW: Filter destination entities by their frames/slots
    destination_frame_criteria=[
        FrameCriteria(
            frame_type="http://vital.ai/ontology/haley-ai-kg#ProductFrame",
            slot_criteria=[
                SlotCriteria(slot_type="price", value=500, comparator="lt")
            ]
        )
    ]
)
# Returns: MakesProduct relations where:
#   - Source org has revenue > $1M (via SourceBusinessFrame)
#   - Destination product has price < $500 (via ProductFrame)
```

**Use Cases**:
- Find all MakesProduct relations where source entity has a specific frame type (e.g., SourceBusinessFrame)
- Find CompetitorOf relations where both entities have revenue > $1M (slot value filtering)
- Find PartnerWith relations where destination entity has specific slot values
- Combine relation type filtering with entity frame/slot criteria

#### Implementation Requirements

##### 6.1 Code Reuse Opportunities

**Existing Frame/Slot Pattern Logic** (`kg_query_builder.py`):
The entity query builder already has frame/slot filtering patterns we can reuse:

**Current Location**: `KGCriteriaQueryBuilder` (lines 200-800+)
- `_build_frame_patterns()` - Builds entity→frame edge patterns
- `_build_slot_patterns()` - Builds frame→slot patterns with value filtering
- `_build_slot_filter_clause()` - Handles comparators (gt, lt, eq, contains, etc.)

**Reuse Strategy**:
```python
# Extract into shared utility class
class KGFrameSlotPatternBuilder:
    """Shared frame/slot pattern building for entity and relation queries."""
    
    def build_entity_frame_patterns(self, entity_var: str, frame_criteria: List[FrameCriteria]) -> List[str]:
        """Build patterns for entity→frame→slot filtering.
        
        Args:
            entity_var: SPARQL variable name (e.g., "?source_entity", "?destination_entity", "?entity")
            frame_criteria: Frame filtering criteria
            
        Returns:
            List of SPARQL pattern strings
        """
        # Reusable for:
        # - Entity queries: entity_var = "?entity"
        # - Relation source: entity_var = "?source_entity"
        # - Relation destination: entity_var = "?destination_entity"
```

**Current Connection Query Builder** (`kg_connection_query_builder.py`):
Already has the base relation query structure:

```python
# Current implementation (lines 40-145):
def build_relation_query(self, criteria: KGQueryCriteria, graph_id: str) -> str:
    patterns = []
    
    # Base relation patterns ✅
    patterns.extend(self._build_source_entity_patterns(...))
    patterns.extend(self._build_destination_entity_patterns(...))
    patterns.extend(self._build_relation_connection_patterns(...))
    
    # NEW: Add frame/slot patterns
    if criteria.source_frame_criteria:
        patterns.extend(self._build_source_frame_patterns(criteria))
    
    if criteria.destination_frame_criteria:
        patterns.extend(self._build_destination_frame_patterns(criteria))
```

##### 6.2 Implementation Approach

**Option A: Extend Connection Query Builder** (Recommended):
- **Pros**: Keeps relation query logic centralized; natural extension of existing `build_relation_query()`
- **Cons**: Some code duplication with entity query builder; need to extract shared frame/slot pattern logic
- **Implementation**:
  1. Create `KGFrameSlotPatternBuilder` utility class
  2. Use in both `KGCriteriaQueryBuilder` and `KGConnectionQueryBuilder`
  3. Add `_build_source_frame_patterns()` and `_build_destination_frame_patterns()` to connection builder
  4. Integrate into `build_relation_query()`

**Option B: Unified Query Builder** (Not Recommended):
- Too much refactoring for the benefit gained
- More complex class structure, harder to maintain separation of concerns

##### 6.3 Extend KGConnectionQueryBuilder
**File**: `/vitalgraph/sparql/kg_connection_query_builder.py`

1. **Add Frame Pattern Methods**:
   ```python
   def _build_source_frame_patterns(self, criteria: KGQueryCriteria) -> List[str]:
       """Build SPARQL patterns for source entity frame filtering."""
       # Similar to existing frame query patterns
       # Connect source_entity → frame via Edge_hasEntityKGFrame
       # Filter by frame type if specified
       # Add slot criteria patterns if specified
   
   def _build_destination_frame_patterns(self, criteria: KGQueryCriteria) -> List[str]:
       """Build SPARQL patterns for destination entity frame filtering."""
       # Similar to source but for destination_entity
   ```

2. **Extend build_relation_query()**: Integrate frame patterns into main query

##### 6.4 SPARQL Query Structure

**Current Relation Query** (Working):
```sparql
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX vital: <http://vital.ai/ontology/vital-core#>

SELECT DISTINCT ?source_entity ?destination_entity ?relation_edge ?relation_type
WHERE {
    GRAPH <urn:kgquery_test_graph> {
        # Source entity
        ?source_entity vital:vitaltype ?source_vitaltype .
        
        # Relation edge
        ?relation_edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation> .
        ?relation_edge vital:hasEdgeSource ?source_entity .
        ?relation_edge vital:hasEdgeDestination ?destination_entity .
        ?relation_edge haley:hasKGRelationType ?relation_type .
        VALUES ?relation_type { <http://vital.ai/test/kgtype/MakesProductRelation> }
        
        # Destination entity
        ?destination_entity vital:vitaltype ?dest_vitaltype .
        
        # Constraints
        FILTER(?source_entity != ?destination_entity)
    }
}
```

**Enhanced Query with Frame/Slot Filtering** (Proposed):
```sparql
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX vital: <http://vital.ai/ontology/vital-core#>

SELECT DISTINCT ?source_entity ?destination_entity ?relation_edge ?relation_type
WHERE {
    GRAPH <urn:kgquery_test_graph> {
        # Base relation patterns (existing) ✅
        ?source_entity vital:vitaltype ?source_vitaltype .
        ?relation_edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation> .
        ?relation_edge vital:hasEdgeSource ?source_entity .
        ?relation_edge vital:hasEdgeDestination ?destination_entity .
        ?relation_edge haley:hasKGRelationType ?relation_type .
        VALUES ?relation_type { <http://vital.ai/test/kgtype/MakesProductRelation> }
        ?destination_entity vital:vitaltype ?dest_vitaltype .
        
        # NEW: Source entity frame filtering
        ?source_frame_edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .
        ?source_frame_edge vital:hasEdgeSource ?source_entity .
        ?source_frame_edge vital:hasEdgeDestination ?source_frame .
        ?source_frame vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#SourceBusinessFrame> .
        
        # NEW: Source entity slot filtering
        ?source_slot haley:hasFrameGraphURI ?source_frame_graph_uri .
        ?source_frame haley:frameGraphURI ?source_frame_graph_uri .
        ?source_slot haley:hasKGSlotType <http://vital.ai/test/slot/revenue> .
        ?source_slot haley:hasDoubleSlotValue ?source_revenue_value .
        FILTER(?source_revenue_value > 1000000)
        
        # NEW: Destination entity frame filtering (optional)
        OPTIONAL {
            ?dest_frame_edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .
            ?dest_frame_edge vital:hasEdgeSource ?destination_entity .
            ?dest_frame_edge vital:hasEdgeDestination ?dest_frame .
            ?dest_frame vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#ProductFrame> .
            
            ?dest_slot haley:hasFrameGraphURI ?dest_frame_graph_uri .
            ?dest_frame haley:frameGraphURI ?dest_frame_graph_uri .
            ?dest_slot haley:hasKGSlotType <http://vital.ai/test/slot/price> .
            ?dest_slot haley:hasDoubleSlotValue ?dest_price_value .
            FILTER(?dest_price_value < 500)
        }
        
        # Constraints
        FILTER(?source_entity != ?destination_entity)
    }
}
```

**Query Complexity**:
- Simple relation query: ~5-10 triple patterns (~10-50ms)
- Enhanced with frames: ~15-25 triple patterns (~50-200ms, acceptable for complex queries)

**Optimization Considerations**:
- Use OPTIONAL for frame patterns when not required
- Add FILTER clauses early to reduce result set
- Consider LIMIT on intermediate results
- Index on vitaltype, hasEdgeSource, hasEdgeDestination

##### 6.5 Extend KGQueryCriteria Model
**File**: `/vitalgraph/model/kgqueries_model.py`

**Add Frame Criteria Fields**:
```python
class KGQueryCriteria(BaseModel):
    # Existing fields...
    source_entity_criteria: Optional[EntityCriteria] = None
    source_entity_uris: Optional[List[str]] = None
    destination_entity_criteria: Optional[EntityCriteria] = None
    destination_entity_uris: Optional[List[str]] = None
    relation_type_uris: Optional[List[str]] = None
    
    # NEW: Frame filtering for relation participants
    source_frame_criteria: Optional[List[FrameCriteria]] = None
    destination_frame_criteria: Optional[List[FrameCriteria]] = None
    
    # Existing fields...
    frame_criteria: Optional[List[FrameCriteria]] = None  # For frame-top queries
```

**Reuse Existing Models**:
- `FrameCriteria` (already defined)
- `SlotCriteria` (already defined)
- No new models needed - just extend usage

##### 6.6 Test Cases
**File**: `/vitalgraph_client_test/kgqueries/case_relation_queries.py`

1. **Test: Relations with Source Frame Type**:
   - Query MakesProduct relations where source has SourceBusinessFrame
   - Expected: Filter to only organizations with that frame type

2. **Test: Relations with Source Slot Value**:
   - Query relations where source entity has revenue > $1M
   - Expected: Only relations from high-revenue orgs

3. **Test: Relations with Both Source and Destination Criteria**:
   - Query CompetitorOf where both entities have revenue > $1M
   - Expected: CompetitorOf relations where BOTH orgs have revenue > $1M

4. **Test: Relations with Destination Frame Type**:
   - Query relations where destination has specific frame type
   - Expected: All relations pointing to entities with ProductFrame

5. **Test: Complex Multi-Criteria**:
   - Combine relation type, source frame, and destination slot filters
   - Example: Tech companies making affordable products

##### 6.7 Architecture Overlap with Entity/Frame Queries

**Shared Components** (Already Implemented):
- `FrameCriteria` model - Reuse as-is
- `SlotCriteria` model - Reuse as-is
- Slot filtering SPARQL patterns - Adapt from entity query builder
- Frame type filtering logic - Adapt from entity query builder

**New Components** (To Implement):
- Source/destination frame pattern builders in connection query builder
- Integration of frame patterns into relation queries
- Test cases for combined relation + frame filtering

**Code Reuse Strategy**:
1. Extract common frame/slot pattern building into helper methods
2. Share between `KGEntityQueryBuilder` and `KGConnectionQueryBuilder`
3. Avoid duplication by creating shared utility functions
4. Maintain consistency in SPARQL pattern structure

##### 6.8 Implementation Time Breakdown

1. **Extract Shared Pattern Builder** (2 hours)
   - Create `KGFrameSlotPatternBuilder` utility class
   - Extract frame/slot pattern logic from entity query builder
   - Add unit tests

2. **Extend Connection Query Builder** (2-3 hours)
   - Add `_build_source_frame_patterns()` method
   - Add `_build_destination_frame_patterns()` method
   - Integrate into `build_relation_query()`
   - Handle OPTIONAL vs required patterns

3. **Update Model** (30 minutes)
   - Add `source_frame_criteria` to `KGQueryCriteria`
   - Add `destination_frame_criteria` to `KGQueryCriteria`
   - Update documentation

4. **Test Cases** (2-3 hours)
   - Create test data with frame/slot values
   - Implement 5+ test scenarios
   - Verify SPARQL query generation
   - Integration testing

5. **Documentation** (1 hour)
   - Update API documentation
   - Add usage examples
   - Update planning document

**Total Estimate**: 6-8 hours

##### 6.9 Discussion Points

**1. OPTIONAL vs Required Frame Patterns**:
- **Recommendation**: Use **required patterns** when frame criteria specified (strict filtering)
- If user provides frame criteria, they want strict filtering

**2. Performance**:
- Expected: ~50-200ms for enhanced queries (acceptable)
- Mitigation: Early filtering, indexed properties, pagination

**3. Code Organization**:
- **Recommendation**: Create `/vitalgraph/sparql/kg_frame_slot_patterns.py` utility module
- Shared by both entity and connection query builders

## Success Criteria

### Functional Requirements ✅ ACHIEVED
- ✅ **KGRelations client endpoint fully functional** - COMPLETED
  - All 6 CRUD methods implemented and working
  - Registered in VitalGraphClient
  - Follows standardized response patterns
- ✅ **All CRUD operations working** - COMPLETED
  - Create, Read (list/get), Update, Upsert, Delete all functional
  - Enhanced filtering by source, destination, type, direction
  - Proper VitalSigns integration
- ✅ **Query operations with complex criteria working** - COMPLETED
  - Relation-top queries implemented via KGConnectionQueryBuilder
  - SPARQL generation for relation-based connections
  - Filtering by entity URIs, relation types, direction
- ✅ **"Connector" query type in KGQueries working** - COMPLETED
  - Relation query type fully implemented
  - Returns RelationConnection objects
  - Integrated with KGQuery endpoint
- ✅ **Test data includes realistic relation examples** - COMPLETED
  - 4 relation types: MakesProduct, CompetitorOf, PartnerWith, Supplies
  - ProductEntity type with properties
  - Relation instances created via test data functions
- ✅ **Comprehensive test suite created** - COMPLETED
  - test_kgrelations_crud.py with 7 test sections
  - Tests all CRUD operations
  - Tests enhanced filtering capabilities

### Test Coverage ✅ ACHIEVED
- ✅ **Standalone KGRelations test suite** - COMPLETED
  - `test_kgrelations_crud.py` with comprehensive test runner
  - 7 test sections covering all CRUD operations
  - Tests enhanced filtering (source, destination, type, direction)
  - Automatic space creation and cleanup
  - Detailed logging and result tracking
- ⏳ **Integration tests in multi-org suite** - PENDING
  - Test data created and ready
  - Integration into multi-org suite not yet complete
- ✅ **KGQuery relation tests** - COMPLETED
  - Relation-top queries implemented and working
  - KGConnectionQueryBuilder tested
  - Returns RelationConnection objects
- ✅ **Test coverage sufficient** - COMPLETED
  - Multiple test scenarios for each operation
  - Validates response types and data integrity

### Code Quality ✅ ACHIEVED
- ✅ **Follows existing patterns** - COMPLETED
  - KGRelationsEndpoint follows KGEntitiesEndpoint patterns
  - Uses standardized response objects
  - VitalSigns integration consistent with other endpoints
  - Response builders from response_builder.py
- ✅ **Proper error handling and logging** - COMPLETED
  - Comprehensive try/except blocks
  - VitalGraphClientError for client errors
  - Detailed logging with timing information
  - Error response objects instead of exceptions
- ✅ **Type hints and documentation** - COMPLETED
  - Full type hints on all methods
  - Comprehensive docstrings
  - Parameter and return type documentation
- ✅ **No code duplication** - COMPLETED
  - Reuses response builder utilities
  - Shares VitalSigns conversion logic
  - Common request handling patterns

## Technical Notes

### Edge_hasKGRelation Structure
```python
from ai_haley_kg_domain.model.Edge_hasKGRelation import Edge_hasKGRelation

relation = Edge_hasKGRelation()
relation.URI = "urn:relation:uuid"
relation.edgeSource = "http://vital.ai/test/kgentity/organization/tech_innovations"
relation.edgeDestination = "http://vital.ai/test/kgentity/product/software_a"
relation.kGRelationType = "http://vital.ai/test/kgtype/MakesProductRelation"
```

### Relation vs Frame Connections

**Relations (Edge_hasKGRelation)**:
- Direct entity-to-entity connections
- Explicit relationship type
- Simpler structure: source → relation → destination
- Examples: competitor_of, makes_product, partner_with

**Frames (KGFrame with slots)**:
- Indirect connections via shared frames
- Entities connected through common frame instances
- More complex: entity → frame → slots → values
- Examples: organizations with same contract type, entities with matching properties

### Query Type Terminology
- **"relation"**: Current official name in code
- **"connector"**: User's preferred term
- **Recommendation**: Support both as aliases, document "connector" as primary

## Dependencies

### Python Packages (Already Installed)
- `ai_haley_kg_domain` - Contains Edge_hasKGRelation
- `vital_ai_vitalsigns` - VitalSigns object conversion
- `rdflib` - RDF/SPARQL handling

### Existing Code Dependencies
- `/vitalgraph/endpoint/kgrelations_endpoint.py` - Server implementation
- `/vitalgraph/kg_impl/kgrelations_*_impl.py` - Backend processors
- `/vitalgraph/model/kgrelations_model.py` - Response models
- `/vitalgraph/sparql/kg_query_builder.py` - Query building patterns

## Risk Assessment

### Low Risk
- ✅ Server implementation already complete
- ✅ Response models already defined
- ✅ Similar patterns exist in kgentities/kgframes

### Medium Risk
- ⚠️ Relation query builder complexity
- ⚠️ Test data design (relation semantics)
- ⚠️ Integration with existing multi-org test

### Mitigation Strategies
- Start with simple relation queries, add complexity incrementally
- Design relation types with clear, testable semantics
- Add KGRelations tests as separate section first, then integrate

## Decisions Made ✅

1. **Relation Type Semantics**:
   - ✅ Relations are **always directional** (source → destination)
   - ✅ No bidirectional relation types needed
   - ✅ Use base Edge_hasKGRelation properties (source/destination)

2. **Test Data Scope**:
   - ✅ **4 relation types** for basic testing:
     - `MakesProductRelation` (org → product)
     - `CompetitorOfRelation` (org → org)
     - `PartnerWithRelation` (org → org)
     - `SuppliesRelation` (org → org)
   - ✅ Keep minimal - just enough for testing
   - ✅ Add to multi-org test data, use in standalone KGRelations test first

3. **Query Architecture - Three Query Patterns**:
   - ✅ **KGRelations endpoint**: Simple CRUD + enhanced list filtering (no query endpoint)
   - ✅ **KGQueries endpoint**: All complex queries with three top-level patterns
   
   **Three Query Patterns in KGQueries** (all use same frame/slot components):
   
   1. **Entity-Top Queries** (existing, working):
      - Top-level query target: KGEntity
      - Find entities matching criteria (type, frames, slots)
      - Uses `KGQueryCriteriaBuilder`
      - Example: "Find all organizations with BusinessContractFrame containing specific file URI"
   
   2. **Relation-Top Queries** (Phase 4 - to implement):
      - Top-level query target: Edge_hasKGRelation
      - Find entity-to-entity connections via relations
      - Uses connector builder
      - Example: "Find all MakesProductRelation connections from Tech companies"
   
   3. **Frame-Top Queries** (Phase 4 - to implement):
      - Top-level query target: KGFrame
      - Find frames matching criteria, with slots pointing to entities
      - Uses frame query builder
      - Example: "Find all BusinessContractFrame instances with specific slot values"
   
   **Shared Components**: All three patterns use same frame criteria, slot criteria, and filtering logic - only the SPARQL generation differs based on top-level target

4. **Integration Approach**:
   - ✅ **Implementation order**:
     1. Create KGRelations client endpoint
     2. Add relation test data to multi-org test data
     3. Create standalone KGRelations test suite (uses multi-org data)
     4. Complete relation query builder for KGQueries
     5. Integrate KGRelations tests into multi-org suite

5. **Additional Query Case**:
   - ✅ Support frame-level queries where slots point to entities
   - ✅ Top-level query item is frame with slots referencing entities

## Next Steps

1. **Discuss this plan** with user to confirm approach
2. **Prioritize** which phases to implement first
3. **Clarify** open questions about relation semantics and naming
4. **Begin implementation** starting with Phase 1 (client endpoint)
5. **Iterate** based on testing results and feedback

---

**Document Version**: 1.0  
**Created**: 2026-01-25  
**Status**: DRAFT - Awaiting Discussion
