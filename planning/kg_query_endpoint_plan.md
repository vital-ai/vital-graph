# KG Query Endpoint Implementation Plan

## Overview

This plan outlines the implementation of a new `/kgqueries` endpoint in VitalGraph to support one-hop entity-to-entity queries. The endpoint provides **two distinct query types**: relation-based and frame-based connections. Each query type is completely separate and never combined.

**Key Design Principles:**
- **Separate Query Types**: Relation queries and frame queries are distinct endpoints
- **Simple Results**: Focus on connection triples (source → connection → destination)
- **No Full Graphs**: Results contain URIs and connection details, not complete entity/frame graphs
- **Distinct from Existing**: Completely separate from `/kgentities` and `/kgframes` endpoints

## Architecture Context

### Current Query Capabilities
- **KGEntities Endpoint**: Queries entities based on entity properties, frame types, and slot criteria
- **KGFrames Endpoint**: Queries frames based on frame properties, entity types, and slot criteria  
- **KGRelations Endpoint**: Queries direct entity-to-entity relationships via Edge_hasKGRelation

### New KG Query Endpoint Scope
The new endpoint provides two distinct query capabilities:

1. **Relation-Based Queries**: Find entities connected via Edge_hasKGRelation
   - Source entity → Edge_hasKGRelation → Destination entity
   - Results: `{source_uri, destination_uri, relation_edge_uri, relation_type_uri}`

2. **Frame-Based Queries**: Find entities connected via shared KGFrames  
   - Source entity → Shared KGFrame ← Destination entity
   - Results: `{source_uri, destination_uri, shared_frame_uri, frame_type_uri}`

## Endpoint Design

### Base URL Structure
```
/api/spaces/{space_id}/graphs/{graph_id}/kgqueries
```

### Core Operations

#### Single KG Query Endpoint
**POST** `/kgqueries`

**Request Model:**
```python
class KGQueryCriteria(BaseModel):
    """Criteria for KG entity-to-entity queries."""
    
    # Query type specification
    query_type: str = Field(..., description="Query type: 'relation' or 'frame'")
    
    # Source entity specification
    source_entity_criteria: Optional[EntityQueryCriteria] = Field(None, description="Criteria for source entities")
    source_entity_uris: Optional[List[str]] = Field(None, description="Specific source entity URIs")
    
    # Destination entity specification  
    destination_entity_criteria: Optional[EntityQueryCriteria] = Field(None, description="Criteria for destination entities")
    destination_entity_uris: Optional[List[str]] = Field(None, description="Specific destination entity URIs")
    
    # Relation-specific criteria (only used when query_type="relation")
    relation_type_uris: Optional[List[str]] = Field(None, description="Relation type URNs to match")
    direction: str = Field("outgoing", description="Direction: outgoing, incoming, bidirectional")
    
    # Frame-specific criteria (only used when query_type="frame")
    shared_frame_types: Optional[List[str]] = Field(None, description="Frame types that entities must share")
    frame_slot_criteria: Optional[List[SlotCriteria]] = Field(None, description="Slot criteria for shared frames")
    
    # Query constraints
    exclude_self_connections: bool = Field(True, description="Exclude connections from entity to itself")

class KGQueryRequest(BaseModel):
    """Request model for KG queries."""
    criteria: KGQueryCriteria = Field(..., description="Query criteria")
    page_size: int = Field(10, description="Number of results per page", ge=1, le=100)
    offset: int = Field(0, description="Offset for pagination", ge=0)
```

**Response Model:**
```python
class RelationConnection(BaseModel):
    """Represents a relation-based connection between two entities."""
    source_entity_uri: str = Field(..., description="Source entity URI")
    destination_entity_uri: str = Field(..., description="Destination entity URI")
    relation_edge_uri: str = Field(..., description="Relation edge URI")
    relation_type_uri: str = Field(..., description="Relation type URN")

class FrameConnection(BaseModel):
    """Represents a frame-based connection between two entities."""
    source_entity_uri: str = Field(..., description="Source entity URI")
    destination_entity_uri: str = Field(..., description="Destination entity URI")
    shared_frame_uri: str = Field(..., description="Shared frame URI")
    frame_type_uri: str = Field(..., description="Frame type URI")

class KGQueryResponse(BasePaginatedResponse):
    """Response model for KG queries."""
    query_type: str = Field(..., description="Query type that was executed: 'relation' or 'frame'")
    relation_connections: Optional[List[RelationConnection]] = Field(None, description="Relation connections (when query_type='relation')")
    frame_connections: Optional[List[FrameConnection]] = Field(None, description="Frame connections (when query_type='frame')")
```

## Implementation Architecture

### 1. Model Definitions

#### File: `/vitalgraph/model/kgqueries_model.py`
```python
"""KG Queries Model Classes

Pydantic models for comprehensive KG entity-to-entity query operations.
"""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from .jsonld_model import JsonLdDocument
from .kgentities_model import EntityQueryCriteria, SlotCriteria
from .api_model import BasePaginatedResponse

# [Model definitions as shown above]
```

### 2. Mock Endpoint Implementation

#### File: `/vitalgraph/mock/client/endpoint/mock_kgqueries_endpoint.py`
```python
"""Mock implementation of KGQueriesEndpoint for comprehensive entity-to-entity queries."""

from typing import Dict, Any, Optional, List
from .mock_base_endpoint import MockBaseEndpoint
from vitalgraph.model.kgqueries_model import KGQueryRequest, KGQueryResponse
from vitalgraph.sparql.kg_connection_query_builder import KGConnectionQueryBuilder

class MockKGQueriesEndpoint(MockBaseEndpoint):
    """Mock implementation with VitalSigns native functionality."""
    
    def __init__(self, client=None, space_manager=None, *, config=None):
        super().__init__(client, space_manager, config=config)
        self.connection_query_builder = KGConnectionQueryBuilder()
    
    def query_connected_entities(self, space_id: str, graph_id: str, 
                                query_request: KGQueryRequest) -> KGQueryResponse:
        """Query entities connected via relations or shared frames."""
        # Implementation using SPARQL query builder
        pass
```

### 3. SPARQL Query Builder

#### File: `/vitalgraph/sparql/kg_connection_query_builder.py`
```python
"""SPARQL Query Builder for Entity-to-Entity Connection Queries."""

class KGConnectionQueryBuilder:
    """Builds SPARQL queries for entity connection discovery."""
    
    def build_relation_connection_query(self, criteria: KGQueryCriteria) -> str:
        """Build SPARQL for relation-based connections."""
        # Generate SPARQL for Edge_hasKGRelation traversal
        pass
    
    def build_frame_connection_query(self, criteria: KGQueryCriteria) -> str:
        """Build SPARQL for frame-based connections."""
        # Generate SPARQL for shared frame discovery
        pass
    
    def build_hybrid_connection_query(self, criteria: KGQueryCriteria) -> str:
        """Build SPARQL combining relation and frame connections."""
        # Generate UNION query combining both approaches
        pass
```

## Key SPARQL Query Patterns

### 1. Relation-Based Connection Query
```sparql
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX vital: <http://vital.ai/ontology/vital-core#>

SELECT ?source_entity ?destination_entity ?relation_type WHERE {
    GRAPH <graph_id> {
        # Source entity criteria
        ?source_entity a haley:KGEntity .
        ?source_entity vital:vitaltype ?source_type .
        FILTER(?source_type = <source_entity_type>)
        
        # Relation connection
        ?relation a haley:Edge_hasKGRelation .
        ?relation vital:hasEdgeSource ?source_entity .
        ?relation vital:hasEdgeDestination ?destination_entity .
        ?relation haley:hasKGRelationType ?relation_type .
        FILTER(?relation_type IN (<relation_type_1>, <relation_type_2>))
        
        # Destination entity criteria
        ?destination_entity a haley:KGEntity .
        ?destination_entity vital:vitaltype ?dest_type .
        FILTER(?dest_type = <destination_entity_type>)
    }
}
```

### 2. Frame-Based Connection Query
```sparql
SELECT ?source_entity ?destination_entity ?shared_frame WHERE {
    GRAPH <graph_id> {
        # Source entity with frame
        ?source_entity a haley:KGEntity .
        ?source_frame_edge a haley:Edge_hasEntityKGFrame .
        ?source_frame_edge vital:hasEdgeSource ?source_entity .
        ?source_frame_edge vital:hasEdgeDestination ?shared_frame .
        
        # Destination entity with same frame
        ?dest_frame_edge a haley:Edge_hasEntityKGFrame .
        ?dest_frame_edge vital:hasEdgeSource ?destination_entity .
        ?dest_frame_edge vital:hasEdgeDestination ?shared_frame .
        
        # Frame criteria
        ?shared_frame a haley:KGFrame .
        ?shared_frame vital:vitaltype ?frame_type .
        FILTER(?frame_type = <shared_frame_type>)
        
        # Optional slot criteria on shared frame
        OPTIONAL {
            ?slot_edge a haley:Edge_hasKGSlot .
            ?slot_edge vital:hasEdgeSource ?shared_frame .
            ?slot_edge vital:hasEdgeDestination ?slot .
            ?slot haley:hasTextSlotValue ?slot_value .
            FILTER(CONTAINS(?slot_value, "criteria_text"))
        }
    }
}
```

## Implementation Phases

### Phase 1: Core Infrastructure (High Priority)
1. **Create Model Definitions** - Pydantic models for comprehensive queries
2. **Create Mock Endpoint Skeleton** - Basic structure with VitalSigns integration
3. **Add to Mock Client** - Client factory integration and endpoint registration
4. **Basic Query Builder** - SPARQL generation for simple connection queries

### Phase 2: Relation-Based Queries (High Priority)  
1. **Implement Relation Connection Queries** - Direct Edge_hasKGRelation traversal
2. **Add Direction Support** - Outgoing, incoming, bidirectional queries
3. **Relation Type Filtering** - Multiple relation type support
4. **Integration Testing** - End-to-end relation query testing

### Phase 3: Frame-Based Queries (Medium Priority)
1. **Implement Shared Frame Queries** - Entities connected via shared frames
2. **Add Slot Criteria Support** - Frame slot-based filtering
3. **Frame Chain Queries** - Multi-hop frame traversal
4. **Performance Optimization** - Query optimization for complex frame queries

### Phase 4: Advanced Features (Medium Priority)
1. **Hybrid Queries** - Combining relation and frame criteria
2. **Result Enrichment** - Optional entity and connection details
3. **Pagination and Sorting** - Large result set handling
4. **Query Performance** - Caching and optimization

## Test Data Generation

### Test Data Function: `/vitalgraph/utils/test_data.py`

Add a comprehensive test data generation function to create entities connected via both relations and frames:

```python
def create_kg_connection_test_data(set_grouping_uris: bool = True) -> List[GraphObject]:
    """
    Create comprehensive test data for KG connection queries.
    
    Generates entities connected via:
    1. Direct relations (Edge_hasKGRelation)
    2. Shared frames (Edge_hasEntityKGFrame)
    
    Args:
        set_grouping_uris: If True, set hasKGGraphURI for server-side loading. 
                          If False, generate clean data for client-side posting to endpoints.
    
    Returns:
        List of VitalSigns GraphObjects (entities, relations, frames, slots, edges)
    """
    
    objects = []
    
    # Create test entities
    person1 = KGEntity()
    person1.URI = "http://example.com/person1"
    person1.name = "John Doe"
    person1.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#PersonEntity"
    if set_grouping_uris:
        person1.hasKGGraphURI = "http://example.com/graph/person1_graph"
    objects.append(person1)
    
    person2 = KGEntity()
    person2.URI = "http://example.com/person2"
    person2.name = "Jane Smith"
    person2.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#PersonEntity"
    if set_grouping_uris:
        person2.hasKGGraphURI = "http://example.com/graph/person2_graph"
    objects.append(person2)
    
    company1 = KGEntity()
    company1.URI = "http://example.com/company1"
    company1.name = "Tech Corp"
    company1.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#CompanyEntity"
    if set_grouping_uris:
        company1.hasKGGraphURI = "http://example.com/graph/company1_graph"
    objects.append(company1)
    
    # Create relation-based connections
    works_for_relation = Edge_hasKGRelation()
    works_for_relation.URI = "http://example.com/relation/person1_works_for_company1"
    works_for_relation.edgeSource = person1.URI
    works_for_relation.edgeDestination = company1.URI
    works_for_relation.kGRelationType = "urn:WorksFor"
    objects.append(works_for_relation)
    
    knows_relation = Edge_hasKGRelation()
    knows_relation.URI = "http://example.com/relation/person1_knows_person2"
    knows_relation.edgeSource = person1.URI
    knows_relation.edgeDestination = person2.URI
    knows_relation.kGRelationType = "urn:KnowsPerson"
    objects.append(knows_relation)
    
    # Create frame-based connections (shared employment frame)
    employment_frame = KGFrame()
    employment_frame.URI = "http://example.com/frame/employment1"
    employment_frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#EmploymentFrame"
    if set_grouping_uris:
        # Frames should belong to the same grouping URI as their primary entity
        employment_frame.hasKGGraphURI = "http://example.com/graph/person1_graph"
    objects.append(employment_frame)
    
    # Connect person1 to employment frame
    person1_frame_edge = Edge_hasEntityKGFrame()
    person1_frame_edge.URI = "http://example.com/edge/person1_employment"
    person1_frame_edge.edgeSource = person1.URI
    person1_frame_edge.edgeDestination = employment_frame.URI
    objects.append(person1_frame_edge)
    
    # Connect company1 to same employment frame
    company1_frame_edge = Edge_hasEntityKGFrame()
    company1_frame_edge.URI = "http://example.com/edge/company1_employment"
    company1_frame_edge.edgeSource = company1.URI
    company1_frame_edge.edgeDestination = employment_frame.URI
    objects.append(company1_frame_edge)
    
    # Add slots to employment frame
    position_slot = KGTextSlot()
    position_slot.URI = "http://example.com/slot/position"
    position_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#PositionSlot"
    position_slot.textSlotValue = "Software Engineer"
    if set_grouping_uris:
        position_slot.hasKGGraphURI = "http://example.com/graph/person1_graph"
    objects.append(position_slot)
    
    salary_slot = KGDoubleSlot()
    salary_slot.URI = "http://example.com/slot/salary"
    salary_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#SalarySlot"
    salary_slot.doubleSlotValue = 75000.0
    if set_grouping_uris:
        salary_slot.hasKGGraphURI = "http://example.com/graph/person1_graph"
    objects.append(salary_slot)
    
    # Connect slots to frame
    position_edge = Edge_hasKGSlot()
    position_edge.URI = "http://example.com/edge/frame_position"
    position_edge.edgeSource = employment_frame.URI
    position_edge.edgeDestination = position_slot.URI
    objects.append(position_edge)
    
    salary_edge = Edge_hasKGSlot()
    salary_edge.URI = "http://example.com/edge/frame_salary"
    salary_edge.edgeSource = employment_frame.URI
    salary_edge.edgeDestination = salary_slot.URI
    objects.append(salary_edge)
    
    return objects

def create_large_kg_connection_dataset(num_entities: int = 50, set_grouping_uris: bool = True) -> List[GraphObject]:
    """
    Create a larger dataset for performance testing.
    
    Args:
        num_entities: Number of entities to create
        set_grouping_uris: If True, set hasKGGraphURI for server-side loading.
                          If False, generate clean data for client-side posting to endpoints.
        
    Returns:
        List of VitalSigns GraphObjects with various connection types
    """
    
    objects = []
    
    # Create entities with different types
    for i in range(num_entities):
        if i % 3 == 0:  # Person entities
            entity = KGEntity()
            entity.URI = f"http://example.com/person{i}"
            entity.name = f"Person {i}"
            entity.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#PersonEntity"
        elif i % 3 == 1:  # Company entities
            entity = KGEntity()
            entity.URI = f"http://example.com/company{i}"
            entity.name = f"Company {i}"
            entity.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#CompanyEntity"
        else:  # Project entities
            entity = KGEntity()
            entity.URI = f"http://example.com/project{i}"
            entity.name = f"Project {i}"
            entity.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#ProjectEntity"
        
        if set_grouping_uris:
            entity.hasKGGraphURI = f"http://example.com/graph/entity_{i}"
        
        objects.append(entity)
    
    # Create various relation types
    relation_types = [
        "urn:WorksFor", "urn:KnowsPerson", "urn:OwnsCompany", 
        "urn:WorksOnProject", "urn:MemberOf"
    ]
    
    # Create random relations between entities
    import random
    for i in range(num_entities // 2):
        source_idx = random.randint(0, num_entities - 1)
        dest_idx = random.randint(0, num_entities - 1)
        if source_idx != dest_idx:
            relation = Edge_hasKGRelation()
            relation.URI = f"http://example.com/relation/rel_{i}"
            relation.edgeSource = f"http://example.com/entity{source_idx}"
            relation.edgeDestination = f"http://example.com/entity{dest_idx}"
            relation.kGRelationType = random.choice(relation_types)
            objects.append(relation)
    
    # Create shared frames for frame-based connections
    frame_types = [
        "http://vital.ai/ontology/haley-ai-kg#EmploymentFrame",
        "http://vital.ai/ontology/haley-ai-kg#ProjectFrame",
        "http://vital.ai/ontology/haley-ai-kg#CollaborationFrame"
    ]
    
    for i in range(num_entities // 5):
        frame = KGFrame()
        frame.URI = f"http://example.com/frame/frame_{i}"
        frame.kGFrameType = random.choice(frame_types)
        
        # Connect 2-4 random entities to this frame
        num_connections = random.randint(2, 4)
        connected_entities = random.sample(range(num_entities), num_connections)
        
        if set_grouping_uris and connected_entities:
            # Frame belongs to the same grouping URI as the first connected entity
            primary_entity_idx = connected_entities[0]
            frame.hasKGGraphURI = f"http://example.com/graph/entity_{primary_entity_idx}"
        
        objects.append(frame)
        
        for entity_idx in connected_entities:
            edge = Edge_hasEntityKGFrame()
            edge.URI = f"http://example.com/edge/frame_{i}_entity_{entity_idx}"
            edge.edgeSource = f"http://example.com/entity{entity_idx}"
            edge.edgeDestination = frame.URI
            objects.append(edge)
    
    return objects
```

## Testing Strategy

### Reference Test Scripts
Use these existing test scripts as examples for implementation patterns:

- **`/test_vitalsigns_query_real.py`** - VitalSigns query patterns and mock client usage
- **`/test_entity_frame_crud.py`** - Entity and frame CRUD operations testing
- **`/test_entity_graph_client.py`** - Entity graph client testing patterns

### Test Script: `/test_kg_queries_comprehensive.py`
Following established VitalGraph patterns with 5 major test functions:

1. **test_relation_based_connections()** - Direct relation queries using test data
2. **test_frame_based_connections()** - Shared frame queries using test data
3. **test_query_type_validation()** - Test query_type parameter validation
4. **test_complex_criteria_combinations()** - Multi-criteria filtering
5. **test_performance_with_large_datasets()** - Scalability testing with large dataset

### Implementation Pattern Reference
```python
# Follow patterns from existing test scripts:

# Mock client setup (from test_entity_graph_client.py)
def setup_mock_client():
    """Setup mock client following established patterns."""
    pass

# VitalSigns query patterns (from test_vitalsigns_query_real.py)  
def test_kg_query_with_vitalsigns_patterns():
    """Test KG queries using VitalSigns query patterns."""
    pass

# CRUD operation patterns (from test_entity_frame_crud.py)
def test_kg_query_with_crud_setup():
    """Test KG queries after setting up data via CRUD operations."""
    pass
```

### Next Implementation Steps
Reference these existing test scripts for implementation patterns:

**Step 4: Test Data Function** (`/vitalgraph/utils/test_data.py`)
- **Reference**: Follow patterns from existing `create_vitalsigns_entity_graphs()`
- **Status**: ❌ **NEXT TO IMPLEMENT**

**Step 5: Mock Client Integration** (`/vitalgraph/mock/client/mock_vitalgraph_client.py`)
- **Reference**: Follow patterns from existing endpoint properties in the same file
- **Status**: ❌ **NEXT TO IMPLEMENT**

**Step 6: Basic Test Script** (`/test_kg_queries_basic.py`)
- **Reference Test Scripts**:
  - `/test_vitalsigns_query_real.py` - Mock client setup and query patterns
  - `/test_entity_frame_crud.py` - CRUD operations and data setup  
  - `/test_entity_graph_client.py` - Entity graph testing patterns
- **Status**: ❌ **NEXT TO IMPLEMENT**

### Test Data Integration
```python
def setup_test_data_for_server_loading():
    """Setup test data for direct server-side loading (with grouping URIs)."""
    # Create test data with grouping URIs for direct triple store loading
    basic_objects = create_kg_connection_test_data(set_grouping_uris=True)
    large_objects = create_large_kg_connection_dataset(100, set_grouping_uris=True)
    
    client = create_mock_client()
    space_id = "kg-queries-test"
    graph_id = "test-graph"
    
    # Convert to JSON-LD and load directly into triple store
    basic_jsonld = vitalsigns.to_jsonld_list(basic_objects)
    large_jsonld = vitalsigns.to_jsonld_list(large_objects)
    
    return client, space_id, graph_id, basic_jsonld, large_jsonld

def setup_test_data_for_client_posting():
    """Setup test data for client-side posting (without grouping URIs)."""
    # Create clean test data without grouping URIs for posting to endpoints
    basic_objects = create_kg_connection_test_data(set_grouping_uris=False)
    large_objects = create_large_kg_connection_dataset(50, set_grouping_uris=False)
    
    client = create_mock_client()
    space_id = "kg-queries-test"
    graph_id = "test-graph"
    
    # Convert to JSON-LD for posting to create endpoints
    basic_jsonld = vitalsigns.to_jsonld_list(basic_objects)
    large_jsonld = vitalsigns.to_jsonld_list(large_objects)
    
    return client, space_id, graph_id, basic_jsonld, large_jsonld
```

## Integration with Mock Client

### Client Factory Integration
```python
# Add to mock_vitalgraph_client.py
@property
def kgqueries(self) -> MockKGQueriesEndpoint:
    """Get KG Queries endpoint for entity-to-entity queries."""
    if not hasattr(self, '_kgqueries_endpoint'):
        self._kgqueries_endpoint = MockKGQueriesEndpoint(
            client=self, 
            space_manager=self.space_manager,
            config=self.config
        )
    return self._kgqueries_endpoint
```

## Success Criteria

### Functional Requirements
- ✅ Relation-based entity-to-entity queries working
- ✅ Frame-based entity connection discovery working  
- ✅ Hybrid queries combining both approaches working
- ✅ Source and destination entity criteria filtering working
- ✅ Connection type and direction filtering working
- ✅ Result enrichment with entity and connection details working

### Performance Requirements
- Query response time < 2 seconds for moderate datasets (100-500 entities)
- Support for pagination with large result sets (1000+ connections)
- Memory efficient processing of complex multi-criteria queries

### Integration Requirements  
- Seamless integration with existing KGEntities and KGFrames endpoints
- Consistent API patterns and response models
- VitalSigns native JSON-LD handling throughout
- Complete test coverage following established patterns

This plan provides a comprehensive foundation for implementing sophisticated entity-to-entity queries that extend VitalGraph's current capabilities while maintaining consistency with existing patterns and architecture.
