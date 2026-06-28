# KGEntities Reference ID Implementation Plan

## Overview
Add support for retrieving KG entities by reference ID(s) using the `hasReferenceIdentifier` property, parallel to the existing URI-based retrieval.

**Property**: `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier`  
**Parameters**: `id` (single), `id_list` (comma-separated)  
**Mutual Exclusivity**: Cannot use both `uri`/`uri_list` AND `id`/`id_list` in same request

---

## Implementation Strategy

### Phase 0: Test Data Preparation ✅

#### 0.1 Add Reference ID Support to Test Data Creator
**File**: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph_client_test/client_test_data.py`

**Update `create_person_with_contact()` method** to include reference ID:

**Location**: Lines 52-150 (approximately)

**Changes**:
```python
def create_person_with_contact(self, name: str = "Alice Johnson", 
                               reference_id: Optional[str] = None) -> List[GraphObject]:
    """
    Create person entity with multiple frames and slots.
    
    Args:
        name: Person name
        reference_id: Optional reference identifier for the entity
        
    Returns:
        List of GraphObject instances (entity, frames, slots, edges)
    """
    objects = []
    
    # Create the person entity
    person = KGEntity()
    person.URI = self.generate_test_uri("person", name.lower().replace(" ", "_"))
    person.name = name
    person.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#PersonEntity"
    
    # Add reference ID if provided
    if reference_id:
        person.hasReferenceIdentifier = reference_id
    
    objects.append(person)
    
    # ... rest of method remains unchanged ...
```

#### 0.2 Create New Test Data Method for Reference ID Testing
**File**: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph_client_test/client_test_data.py`

**Add new method** (after existing entity creation methods):

```python
def create_entities_with_reference_ids(self, count: int = 5, 
                                       entity_type: str = "person") -> List[GraphObject]:
    """
    Create multiple entities with reference IDs for testing reference ID retrieval.
    
    Args:
        count: Number of entities to create
        entity_type: Type of entity ("person", "organization", "project")
        
    Returns:
        List of all GraphObject instances for all entities
    """
    all_objects = []
    
    if entity_type == "person":
        names = [
            "Alice Johnson",
            "Bob Smith", 
            "Carol Williams",
            "David Brown",
            "Eve Davis"
        ]
        
        for i in range(min(count, len(names))):
            # Generate reference ID in format: REF-XXXX
            reference_id = f"REF-{i+1:04d}"
            
            # Create person with reference ID
            person_objects = self.create_person_with_contact(
                name=names[i],
                reference_id=reference_id
            )
            all_objects.extend(person_objects)
    
    elif entity_type == "organization":
        org_names = [
            "Acme Corporation",
            "TechStart Inc",
            "Global Solutions Ltd",
            "Innovation Labs",
            "Future Systems"
        ]
        
        for i in range(min(count, len(org_names))):
            reference_id = f"ORG-{i+1:04d}"
            
            # Create organization with reference ID
            org_objects = self.create_organization_with_details(
                name=org_names[i],
                reference_id=reference_id
            )
            all_objects.extend(org_objects)
    
    elif entity_type == "project":
        project_names = [
            "Alpha Project",
            "Beta Initiative",
            "Gamma Research",
            "Delta Development",
            "Epsilon Launch"
        ]
        
        for i in range(min(count, len(project_names))):
            reference_id = f"PROJ-{i+1:04d}"
            
            # Create project with reference ID
            project_objects = self.create_project_with_milestones(
                name=project_names[i],
                reference_id=reference_id
            )
            all_objects.extend(project_objects)
    
    return all_objects


def create_organization_with_details(self, name: str = "Acme Corp",
                                     reference_id: Optional[str] = None) -> List[GraphObject]:
    """
    Create organization entity with frames and slots.
    
    Args:
        name: Organization name
        reference_id: Optional reference identifier
        
    Returns:
        List of GraphObject instances
    """
    objects = []
    
    # Create organization entity
    org = KGEntity()
    org.URI = self.generate_test_uri("organization", name.lower().replace(" ", "_"))
    org.name = name
    org.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#OrganizationEntity"
    
    # Add reference ID if provided
    if reference_id:
        org.hasReferenceIdentifier = reference_id
    
    objects.append(org)
    
    # Create company info frame
    info_frame = KGFrame()
    info_frame.URI = self.generate_test_uri("frame", f"{name.lower().replace(' ', '_')}_info")
    info_frame.name = f"{name} Company Info"
    info_frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#CompanyInfoFrame"
    objects.append(info_frame)
    
    # Industry slot
    industry_slot = KGTextSlot()
    industry_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_industry")
    industry_slot.name = f"{name} Industry"
    industry_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#IndustrySlot"
    industry_slot.textSlotValue = "Technology"
    objects.append(industry_slot)
    
    # Employee count slot
    employee_slot = KGIntegerSlot()
    employee_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_employees")
    employee_slot.name = f"{name} Employee Count"
    employee_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#EmployeeCountSlot"
    employee_slot.integerSlotValue = 100
    objects.append(employee_slot)
    
    # Edges
    entity_frame_edge = Edge_hasEntityKGFrame()
    entity_frame_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_entity_info")
    entity_frame_edge.edgeSource = org.URI
    entity_frame_edge.edgeDestination = info_frame.URI
    objects.append(entity_frame_edge)
    
    frame_industry_edge = Edge_hasKGSlot()
    frame_industry_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_info_industry")
    frame_industry_edge.edgeSource = info_frame.URI
    frame_industry_edge.edgeDestination = industry_slot.URI
    objects.append(frame_industry_edge)
    
    frame_employee_edge = Edge_hasKGSlot()
    frame_employee_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_info_employees")
    frame_employee_edge.edgeSource = info_frame.URI
    frame_employee_edge.edgeDestination = employee_slot.URI
    objects.append(frame_employee_edge)
    
    return objects


def create_project_with_milestones(self, name: str = "Alpha Project",
                                   reference_id: Optional[str] = None) -> List[GraphObject]:
    """
    Create project entity with frames and slots.
    
    Args:
        name: Project name
        reference_id: Optional reference identifier
        
    Returns:
        List of GraphObject instances
    """
    objects = []
    
    # Create project entity
    project = KGEntity()
    project.URI = self.generate_test_uri("project", name.lower().replace(" ", "_"))
    project.name = name
    project.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#ProjectEntity"
    
    # Add reference ID if provided
    if reference_id:
        project.hasReferenceIdentifier = reference_id
    
    objects.append(project)
    
    # Create project details frame
    details_frame = KGFrame()
    details_frame.URI = self.generate_test_uri("frame", f"{name.lower().replace(' ', '_')}_details")
    details_frame.name = f"{name} Details"
    details_frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#ProjectDetailsFrame"
    objects.append(details_frame)
    
    # Status slot
    status_slot = KGTextSlot()
    status_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_status")
    status_slot.name = f"{name} Status"
    status_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#StatusSlot"
    status_slot.textSlotValue = "In Progress"
    objects.append(status_slot)
    
    # Start date slot
    start_date_slot = KGDateTimeSlot()
    start_date_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_start_date")
    start_date_slot.name = f"{name} Start Date"
    start_date_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#StartDateSlot"
    start_date_slot.dateTimeSlotValue = datetime.now()
    objects.append(start_date_slot)
    
    # Edges
    entity_frame_edge = Edge_hasEntityKGFrame()
    entity_frame_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_entity_details")
    entity_frame_edge.edgeSource = project.URI
    entity_frame_edge.edgeDestination = details_frame.URI
    objects.append(entity_frame_edge)
    
    frame_status_edge = Edge_hasKGSlot()
    frame_status_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_details_status")
    frame_status_edge.edgeSource = details_frame.URI
    frame_status_edge.edgeDestination = status_slot.URI
    objects.append(frame_status_edge)
    
    frame_date_edge = Edge_hasKGSlot()
    frame_date_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_details_date")
    frame_date_edge.edgeSource = details_frame.URI
    frame_date_edge.edgeDestination = start_date_slot.URI
    objects.append(frame_date_edge)
    
    return objects
```

#### 0.3 Test Data Usage Examples
**Usage in test scripts**:

```python
from vitalgraph_client_test.client_test_data import ClientTestDataCreator

# Create test data creator
data_creator = ClientTestDataCreator()

# Create 5 people with reference IDs REF-0001 through REF-0005
person_objects = data_creator.create_entities_with_reference_ids(
    count=5,
    entity_type="person"
)

# Create 3 organizations with reference IDs ORG-0001 through ORG-0003
org_objects = data_creator.create_entities_with_reference_ids(
    count=3,
    entity_type="organization"
)

# Create single person with custom reference ID
custom_person = data_creator.create_person_with_contact(
    name="John Doe",
    reference_id="CUSTOM-REF-001"
)
```

---

### Phase 1: Endpoint Parameter Updates ✅

#### 1.1 Add New Query Parameters to GET /kgentities
**File**: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph/endpoint/kgentities_endpoint.py`

**Location**: `list_or_get_entities()` function (lines 88-119)

**Changes**:
```python
@self.router.get("/kgentities", response_model=Union[EntitiesResponse, JsonLdDocument, JsonLdObject], tags=["KG Entities"])
async def list_or_get_entities(
    space_id: str = Query(..., description="Space ID"),
    graph_id: Optional[str] = Query(None, description="Graph ID"),
    page_size: int = Query(10, ge=1, le=1000, description="Number of entities per page"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    entity_type_uri: Optional[str] = Query(None, description="Entity type URI to filter by"),
    search: Optional[str] = Query(None, description="Search text to find in entity properties"),
    
    # URI-based retrieval (existing)
    uri: Optional[str] = Query(None, description="Single entity URI to retrieve"),
    uri_list: Optional[str] = Query(None, description="Comma-separated list of entity URIs"),
    
    # Reference ID-based retrieval (NEW)
    id: Optional[str] = Query(None, description="Single reference ID to retrieve"),
    id_list: Optional[str] = Query(None, description="Comma-separated list of reference IDs"),
    
    include_entity_graph: bool = Query(False, description="If True, include complete entity graphs with frames and slots"),
    current_user: Dict = Depends(self.auth_dependency)
):
```

#### 1.2 Add Parameter Validation Logic
**Location**: Beginning of `list_or_get_entities()` function

**Validation Rules**:
```python
# Validate mutually exclusive parameters
uri_params_used = bool(uri or uri_list)
id_params_used = bool(id or id_list)

if uri_params_used and id_params_used:
    raise ValueError("Cannot use both URI-based (uri/uri_list) and ID-based (id/id_list) parameters in the same request")

# Handle single reference ID retrieval
if id:
    return await self._get_entity_by_reference_id(space_id, graph_id, id, include_entity_graph, current_user)

# Handle multiple reference ID retrieval
if id_list:
    ids = [ref_id.strip() for ref_id in id_list.split(',') if ref_id.strip()]
    return await self._get_entities_by_reference_ids(space_id, graph_id, ids, include_entity_graph, current_user)

# Existing URI and list logic remains unchanged
if uri:
    return await self._get_entity_by_uri(space_id, graph_id, uri, include_entity_graph, current_user)

if uri_list:
    uris = [u.strip() for u in uri_list.split(',') if u.strip()]
    return await self._get_entities_by_uris(space_id, graph_id, uris, include_entity_graph, current_user)

# Handle paginated listing
return await self._list_entities(space_id, graph_id, page_size, offset, entity_type_uri, search, include_entity_graph, current_user)
```

---

### Phase 2: Backend Query Implementation ✅

#### 2.1 Create Reference ID Query Methods
**File**: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph/endpoint/kgentities_endpoint.py`

**New Methods** (add after existing `_get_entities_by_uris`):

```python
async def _get_entity_by_reference_id(self, space_id: str, graph_id: Optional[str], 
                                      reference_id: str, include_entity_graph: bool, 
                                      current_user: Dict) -> Union[JsonLdObject, EntityGraphResponse]:
    """
    Get a single entity by reference ID.
    
    Args:
        space_id: Space identifier
        graph_id: Graph identifier (optional)
        reference_id: Reference ID value to search for
        include_entity_graph: Whether to include complete entity graph
        current_user: Current authenticated user
        
    Returns:
        JsonLdObject or EntityGraphResponse with entity data
    """
    try:
        # First, find the entity URI by querying hasReferenceIdentifier property
        entity_uri = await self._find_entity_uri_by_reference_id(space_id, graph_id, reference_id)
        
        if not entity_uri:
            raise ValueError(f"Entity not found with reference ID: {reference_id}")
        
        # Use existing URI-based retrieval
        return await self._get_entity_by_uri(space_id, graph_id, entity_uri, include_entity_graph, current_user)
        
    except Exception as e:
        self.logger.error(f"Error getting entity by reference ID {reference_id}: {e}")
        raise


async def _get_entities_by_reference_ids(self, space_id: str, graph_id: Optional[str], 
                                         reference_ids: List[str], include_entity_graph: bool, 
                                         current_user: Dict) -> Union[JsonLdDocument, EntitiesGraphResponse]:
    """
    Get multiple entities by reference ID list.
    
    Args:
        space_id: Space identifier
        graph_id: Graph identifier (optional)
        reference_ids: List of reference ID values to search for
        include_entity_graph: Whether to include complete entity graphs
        current_user: Current authenticated user
        
    Returns:
        JsonLdDocument or EntitiesGraphResponse with entity data
    """
    try:
        # Find all entity URIs by querying hasReferenceIdentifier property
        entity_uris = await self._find_entity_uris_by_reference_ids(space_id, graph_id, reference_ids)
        
        if not entity_uris:
            # Return empty response
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_doc = GraphObject.to_jsonld_list([])
            
            if include_entity_graph:
                return EntitiesGraphResponse(
                    entity_graphs=JsonLdDocument(**empty_doc),
                    total_count=0
                )
            else:
                return JsonLdDocument(**empty_doc)
        
        # Use existing URI-based retrieval
        return await self._get_entities_by_uris(space_id, graph_id, entity_uris, include_entity_graph, current_user)
        
    except Exception as e:
        self.logger.error(f"Error getting entities by reference IDs: {e}")
        raise
```

#### 2.2 Create SPARQL Query Helper Methods
**File**: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph/endpoint/kgentities_endpoint.py`

**New Helper Methods**:

```python
async def _find_entity_uri_by_reference_id(self, space_id: str, graph_id: Optional[str], 
                                           reference_id: str) -> Optional[str]:
    """
    Find entity URI by querying hasReferenceIdentifier property.
    
    Args:
        space_id: Space identifier
        graph_id: Graph identifier (optional)
        reference_id: Reference ID value to search for
        
    Returns:
        Entity URI if found, None otherwise
    """
    try:
        # Get database space implementation
        space = self.space_manager.get_space(space_id)
        db_space_impl = space.get_db_space_impl()
        
        # Build SPARQL query to find entity by reference ID
        sparql_query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX aimp: <http://vital.ai/ontology/vital-aimp#>
        
        SELECT DISTINCT ?entity WHERE {{
            {'GRAPH <' + graph_id + '> {' if graph_id else ''}
                ?entity a haley:KGEntity .
                ?entity aimp:hasReferenceIdentifier "{reference_id}" .
            {'}' if graph_id else ''}
        }}
        LIMIT 1
        """
        
        # Execute SPARQL query
        results = await db_space_impl.execute_sparql_query(
            space_id=space_id,
            sparql_query=sparql_query
        )
        
        # Extract entity URI from results
        if results and len(results) > 0:
            entity_uri = str(results[0].get('entity', ''))
            return entity_uri if entity_uri else None
        
        return None
        
    except Exception as e:
        self.logger.error(f"Error finding entity URI by reference ID {reference_id}: {e}")
        return None


async def _find_entity_uris_by_reference_ids(self, space_id: str, graph_id: Optional[str], 
                                             reference_ids: List[str]) -> List[str]:
    """
    Find entity URIs by querying hasReferenceIdentifier property for multiple IDs.
    
    Args:
        space_id: Space identifier
        graph_id: Graph identifier (optional)
        reference_ids: List of reference ID values to search for
        
    Returns:
        List of entity URIs found
    """
    try:
        # Get database space implementation
        space = self.space_manager.get_space(space_id)
        db_space_impl = space.get_db_space_impl()
        
        # Build VALUES clause for multiple reference IDs
        values_clause = " ".join([f'"{ref_id}"' for ref_id in reference_ids])
        
        # Build SPARQL query to find entities by reference IDs
        sparql_query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX aimp: <http://vital.ai/ontology/vital-aimp#>
        
        SELECT DISTINCT ?entity WHERE {{
            {'GRAPH <' + graph_id + '> {' if graph_id else ''}
                ?entity a haley:KGEntity .
                ?entity aimp:hasReferenceIdentifier ?refId .
                FILTER(?refId IN ({values_clause}))
            {'}' if graph_id else ''}
        }}
        """
        
        # Execute SPARQL query
        results = await db_space_impl.execute_sparql_query(
            space_id=space_id,
            sparql_query=sparql_query
        )
        
        # Extract entity URIs from results
        entity_uris = []
        for result in results:
            entity_uri = str(result.get('entity', ''))
            if entity_uri:
                entity_uris.append(entity_uri)
        
        return entity_uris
        
    except Exception as e:
        self.logger.error(f"Error finding entity URIs by reference IDs: {e}")
        return []
```

---

### Phase 3: Client-Side Support ✅

#### 3.1 Update VitalGraph Client Methods
**File**: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph/client/endpoint/kgentities_endpoint.py`

**Update `get_kgentity()` method**:
```python
def get_kgentity(
    self,
    space_id: str,
    graph_id: str,
    uri: Optional[str] = None,
    reference_id: Optional[str] = None,
    include_entity_graph: bool = False
) -> Union[JsonLdObject, EntityGraphResponse]:
    """
    Get a single KG entity by URI or reference ID.
    
    Args:
        space_id: Space identifier
        graph_id: Graph identifier
        uri: Entity URI (mutually exclusive with reference_id)
        reference_id: Reference ID (mutually exclusive with uri)
        include_entity_graph: Whether to include complete entity graph
        
    Returns:
        JsonLdObject or EntityGraphResponse
        
    Raises:
        ValueError: If both uri and reference_id are provided, or neither
    """
    # Validate parameters
    if uri and reference_id:
        raise ValueError("Cannot specify both uri and reference_id")
    if not uri and not reference_id:
        raise ValueError("Must specify either uri or reference_id")
    
    # Build query parameters
    params = {
        "space_id": space_id,
        "graph_id": graph_id,
        "include_entity_graph": include_entity_graph
    }
    
    if uri:
        params["uri"] = uri
    else:
        params["id"] = reference_id
    
    # Make request
    return self._make_typed_request(
        method="GET",
        endpoint="kgentities",
        params=params,
        response_model=EntityGraphResponse if include_entity_graph else JsonLdObject
    )
```

**Add new `get_kgentities_by_reference_ids()` method**:
```python
def get_kgentities_by_reference_ids(
    self,
    space_id: str,
    graph_id: str,
    reference_ids: List[str],
    include_entity_graph: bool = False
) -> Union[JsonLdDocument, EntitiesGraphResponse]:
    """
    Get multiple KG entities by reference ID list.
    
    Args:
        space_id: Space identifier
        graph_id: Graph identifier
        reference_ids: List of reference IDs
        include_entity_graph: Whether to include complete entity graphs
        
    Returns:
        JsonLdDocument or EntitiesGraphResponse
    """
    # Build query parameters
    params = {
        "space_id": space_id,
        "graph_id": graph_id,
        "id_list": ",".join(reference_ids),
        "include_entity_graph": include_entity_graph
    }
    
    # Make request
    return self._make_typed_request(
        method="GET",
        endpoint="kgentities",
        params=params,
        response_model=EntitiesGraphResponse if include_entity_graph else JsonLdDocument
    )
```

---

### Phase 4: Testing ✅

#### 4.1 Create Test Script
**File**: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph_client_test/test_kgentities_reference_id.py`

**Test Coverage**:
1. **Setup**: Create test space and graph
2. **Create Entities**: Create 5 entities with reference IDs
3. **Single Reference ID Retrieval**: Test `id` parameter
4. **Multiple Reference ID Retrieval**: Test `id_list` parameter
5. **Entity Graph Retrieval**: Test with `include_entity_graph=True`
6. **Error Cases**:
   - Non-existent reference ID
   - Both `uri` and `id` provided (should fail)
   - Empty reference ID
7. **Cleanup**: Delete test space

#### 4.2 Test Case Structure
```python
import logging
from vitalgraph.client.vitalgraph_client import VitalGraphClient

logger = logging.getLogger(__name__)

async def test_reference_id_retrieval():
    """Test KGEntity retrieval by reference ID."""
    
    # 1. Setup
    client = VitalGraphClient(...)
    await client.connect()
    
    space_id = "test_reference_id_space"
    graph_id = "urn:test_reference_id"
    
    # Create space and graph
    await client.spaces.create_space(space_id)
    await client.graphs.create_graph(space_id, graph_id)
    
    # 2. Create entities with reference IDs
    entities_data = []
    for i in range(1, 6):
        entity = KGEntity()
        entity.URI = f"haley:entity_ref_{i:03d}"
        entity.hasName = f"Entity {i}"
        entity.hasReferenceIdentifier = f"REF-{i:04d}"
        entities_data.append(entity)
    
    # Create entities
    response = await client.kgentities.create_kgentities(
        space_id=space_id,
        graph_id=graph_id,
        entities=entities_data
    )
    
    # 3. Test single reference ID retrieval
    entity = await client.kgentities.get_kgentity(
        space_id=space_id,
        graph_id=graph_id,
        reference_id="REF-0001"
    )
    assert entity['@id'] == "haley:entity_ref_001"
    
    # 4. Test multiple reference ID retrieval
    entities = await client.kgentities.get_kgentities_by_reference_ids(
        space_id=space_id,
        graph_id=graph_id,
        reference_ids=["REF-0001", "REF-0003", "REF-0005"]
    )
    assert len(entities['@graph']) == 3
    
    # 5. Test with entity graph
    entity_graph = await client.kgentities.get_kgentity(
        space_id=space_id,
        graph_id=graph_id,
        reference_id="REF-0002",
        include_entity_graph=True
    )
    assert entity_graph.entity_graphs is not None
    
    # 6. Test error cases
    try:
        # Should fail - both uri and reference_id
        await client.kgentities.get_kgentity(
            space_id=space_id,
            graph_id=graph_id,
            uri="haley:entity_ref_001",
            reference_id="REF-0001"
        )
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
    
    # 7. Cleanup
    await client.spaces.delete_space(space_id)
    await client.close()
```

---

### Phase 5: Documentation Updates ✅

#### 5.1 Update API Documentation
**Files to Update**:
- `/Users/hadfield/Local/vital-git/vital-graph/docs/API_ENDPOINTS.md`
- `/Users/hadfield/Local/vital-git/vital-graph/README.md`

**Documentation Additions**:
```markdown
### GET /api/kgentities - Reference ID Retrieval

Retrieve entities by reference ID instead of URI.

**Query Parameters**:
- `id` (optional): Single reference ID to retrieve
- `id_list` (optional): Comma-separated list of reference IDs
- `uri` (optional): Single entity URI (mutually exclusive with id/id_list)
- `uri_list` (optional): Comma-separated URIs (mutually exclusive with id/id_list)

**Examples**:
```bash
# Get single entity by reference ID
GET /api/kgentities?space_id=my_space&graph_id=urn:my_graph&id=REF-0001

# Get multiple entities by reference IDs
GET /api/kgentities?space_id=my_space&graph_id=urn:my_graph&id_list=REF-0001,REF-0002,REF-0003

# Get entity with complete graph by reference ID
GET /api/kgentities?space_id=my_space&graph_id=urn:my_graph&id=REF-0001&include_entity_graph=true
```

**Error Cases**:
- 400 Bad Request: Both URI and reference ID parameters provided
- 404 Not Found: Reference ID does not exist
```

---

## Implementation Checklist

### Phase 0: Test Data Preparation ✅
- [ ] Update `create_person_with_contact()` to accept optional `reference_id` parameter
- [ ] Update `create_organization_with_details()` to accept optional `reference_id` parameter (new method)
- [ ] Update `create_project_with_milestones()` to accept optional `reference_id` parameter (new method)
- [ ] Create `create_entities_with_reference_ids()` method for batch test data creation
- [ ] Add `hasReferenceIdentifier` property assignment in entity creation methods
- [ ] Test data creator methods generate proper reference ID formats (REF-XXXX, ORG-XXXX, PROJ-XXXX)

### Phase 1: Endpoint Parameters ✅
- [ ] Add `id` and `id_list` query parameters to GET /kgentities
- [ ] Add parameter validation (mutual exclusivity check)
- [ ] Add routing logic for reference ID retrieval

### Phase 2: Backend Queries ✅
- [ ] Implement `_get_entity_by_reference_id()` method
- [ ] Implement `_get_entities_by_reference_ids()` method
- [ ] Implement `_find_entity_uri_by_reference_id()` helper
- [ ] Implement `_find_entity_uris_by_reference_ids()` helper
- [ ] Test SPARQL queries against Fuseki backend

### Phase 3: Client Support ✅
- [ ] Update `get_kgentity()` to accept `reference_id` parameter
- [ ] Add `get_kgentities_by_reference_ids()` method
- [ ] Add parameter validation in client methods

### Phase 4: Testing ✅
- [ ] Create test script with comprehensive coverage
- [ ] Test single reference ID retrieval
- [ ] Test multiple reference ID retrieval
- [ ] Test entity graph retrieval with reference IDs
- [ ] Test error cases (mutual exclusivity, not found, etc.)
- [ ] Verify against live Fuseki/PostgreSQL backend

### Phase 5: Documentation ✅
- [ ] Update API endpoint documentation
- [ ] Add usage examples
- [ ] Document error cases
- [ ] Update client library documentation

---

## SPARQL Query Examples

### Single Reference ID Query
```sparql
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX aimp: <http://vital.ai/ontology/vital-aimp#>

SELECT DISTINCT ?entity WHERE {
    GRAPH <urn:my_graph> {
        ?entity a haley:KGEntity .
        ?entity aimp:hasReferenceIdentifier "REF-0001" .
    }
}
LIMIT 1
```

### Multiple Reference IDs Query
```sparql
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX aimp: <http://vital.ai/ontology/vital-aimp#>

SELECT DISTINCT ?entity WHERE {
    GRAPH <urn:my_graph> {
        ?entity a haley:KGEntity .
        ?entity aimp:hasReferenceIdentifier ?refId .
        FILTER(?refId IN ("REF-0001", "REF-0002", "REF-0003"))
    }
}
```

---

## Notes

1. **Property URI**: Using `http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier` as specified
2. **Mutual Exclusivity**: URI-based and ID-based retrieval are separate - cannot mix in same request
3. **Performance**: Reference ID lookup requires additional SPARQL query before URI-based retrieval
4. **Indexing**: Consider adding database index on `hasReferenceIdentifier` property for performance
5. **Validation**: Reference IDs should be validated for format/uniqueness at entity creation time
6. **Error Handling**: Clear error messages when reference ID not found or parameters conflict

---

## Success Criteria

- ✅ Can retrieve single entity by reference ID
- ✅ Can retrieve multiple entities by reference ID list
- ✅ Entity graph retrieval works with reference IDs
- ✅ Parameter validation prevents URI/ID mixing
- ✅ Clear error messages for not found cases
- ✅ Client methods provide clean API
- ✅ All tests pass (100% success rate)
- ✅ Documentation complete and accurate
