# KG Services Migration Plan - KGEntity, KGFrame, and Objects

## Overview

This document outlines the migration plan for updating KGEntity, KGFrame, and Object services to use the proven KGTypes implementation patterns. The plan leverages the successful architecture established with KGTypes:

- **Database Objects Layer**: `PostgreSQLSpaceDBObjects` with optimized SQL
- **Service Utilities**: `service_utils.py` with reusable JSON-LD/GraphObject processing
- **Transaction-based Operations**: Using `add_rdf_quads_batch()` and `remove_rdf_quads_batch()`
- **Proper Error Handling**: Consistent HTTP status codes and validation

## VitalSigns Semantic Model

### Core Object Types and Relationships

Based on VitalSigns analysis, the semantic model includes:

#### 1. **KGEntity** - Real-world Entities
- **Purpose**: Represents people, places, things, concepts
- **URI**: `http://vital.ai/ontology/haley-ai-kg#KGEntity`
- **Properties**: `kGEntityType`, `kGEntityTypeDescription`, `kGFormType`
- **Examples**: 
  - Person: "John Doe", "Dr. Sarah Johnson"
  - Organization: "ACME Corporation", "MIT AI Lab"
  - Location: "New York City", "Building A"
  - Concept: "Machine Learning", "Artificial Intelligence"

#### 2. **KGFrame** - Information Groupings/Contexts
- **Purpose**: Groups related information and relationships into coherent contexts
- **URI**: `http://vital.ai/ontology/haley-ai-kg#KGFrame`
- **Properties**: `frameGraphURI`, `kGFrameType`, `kGFrameTypeDescription`, `parentFrameURI`
- **Examples**:
  - Employment Frame: Groups employment-related information
  - Address Frame: Groups address/location information
  - Education Frame: Groups educational background information
  - Project Frame: Groups project-related data

#### 3. **KGSlot** - Individual Values/Facts
- **Purpose**: Represents specific values, facts, or properties within a frame
- **URI**: `http://vital.ai/ontology/haley-ai-kg#KGSlot`
- **Properties**: `kGSlotType`, `kGSlotTypeDescription`, `kGSlotValueType`, `slotSequence`
- **Examples** (within Employment Frame):
  - Employee Slot: Points to the person entity being employed
  - Employer Slot: Points to the organization entity doing the employing
  - Start Date Slot: Contains the employment start date
  - Position Title Slot: Contains the job title

#### 4. **KGType** - Type Definitions (✅ Already Implemented)
- **Purpose**: Defines types and schemas for other KG objects
- **URI**: `http://vital.ai/ontology/haley-ai-kg#KGType`
- **Status**: Production-ready with full CRUD operations

### Relationship Navigation Patterns

#### Core Edge Types for Traversal:
- **Edge_hasKGFrame**: Links entities to frames (Entity → Frame)
- **Edge_hasKGSlot**: Links frames to their slots (Frame → Slot)
- **Edge_hasKGEntity**: Links slots to entities (Slot → Entity)

#### Navigation Flow:
```
KGEntity --[Edge_hasKGFrame]--> KGFrame --[Edge_hasKGSlot]--> KGSlot --[Edge_hasKGEntity]--> KGEntity
```

## Current State Analysis

### ✅ **Already Implemented (KGTypes)**
- **KGTypeService**: Complete CRUD operations using service_utils
- **KGTypesEndpoint**: Full REST API with proper validation
- **Foundation Components**: db_objects, service_utils, transaction management
- **Status**: Production-ready, high-performance (~15,000 quads/sec)

### 📋 **Needs Migration**

#### 1. **KGEntityService** (`/vitalgraph/service/kgentity_service.py`)
- **Current**: Read-only operations, delegates to ObjectService
- **Needs**: CRUD operations using KGTypes pattern
- **Vitaltype Validation**: KGEntity and subclasses only

#### 2. **KGFrameService** (`/vitalgraph/service/kgframe_service.py`)
- **Current**: Read-only operations, delegates to ObjectService
- **Needs**: CRUD operations using KGTypes pattern
- **Vitaltype Validation**: KGFrame and subclasses only

#### 3. **ObjectService** (`/vitalgraph/service/object_service.py`)
- **Current**: Read operations + old SPARQL-based CRUD (broken)
- **Needs**: Clean CRUD operations using KGTypes pattern
- **Vitaltype Validation**: All valid VitalSigns objects (no restrictions)

#### 4. **Endpoints** (`/vitalgraph/endpoint/`)
- **KGEntitiesEndpoint**: Needs CRUD endpoints
- **KGFramesEndpoint**: Needs CRUD endpoints  
- **ObjectsEndpoint**: Needs CRUD endpoints (currently read-only)

## Migration Architecture

### Established Pattern (from KGTypes Success)

```
Endpoint → Service → service_utils → db_objects/db_ops → Database
```

### Service Layer Pattern

Each service follows the same structure:

```python
class KG[Type]Service:
    def __init__(self, space_manager):
        self.space_manager = space_manager
        self.logger = logging.getLogger(f"{__name__}.KG[Type]Service")
        
        # Initialize VitalSigns for vitaltype validation
        self.vitalsigns = VitalSigns()
        self.ontology_manager = self.vitalsigns.get_ontology_manager()
    
    def get_kg[type]_vitaltypes(self) -> List[str]:
        """Get all vitaltype URIs for KG[Type] and its subclasses."""
        
    def validate_kg[type]_vitaltype(self, vitaltype_uri: str) -> bool:
        """Validate that a vitaltype URI is a KG[Type] or subclass."""
        
    async def create_kg[type](self, space_id: str, data: Dict, graph_id: str) -> str:
        """Create using service_utils.jsonld_to_graphobjects() with type validator"""
        
    async def update_kg[type](self, space_id: str, uri: str, data: Dict, graph_id: str) -> bool:
        """Update using atomic delete+insert pattern"""
        
    async def delete_kg[type](self, space_id: str, uri: str, graph_id: str) -> bool:
        """Delete using service_utils.get_existing_quads_for_uris()"""
        
    async def delete_kg[type]s(self, space_id: str, uris: List[str], graph_id: str) -> int:
        """Batch delete using service_utils patterns"""
```

### Endpoint Layer Pattern

Each endpoint follows the same structure:

```python
class KG[Type]sEndpoint:
    def __init__(self, space_manager, auth_dependency):
        self.space_manager = space_manager
        self.kg[type]_service = KG[Type]Service(space_manager)
        self.logger = logging.getLogger(f"{__name__}.KG[Type]sEndpoint")
        
    async def _create_kg[type]s(self, space_id: str, graph_id: str, document: JsonLdDocument, current_user: Dict):
        """Create following triples endpoint validation pattern"""
        
    async def _update_kg[type]s(self, space_id: str, graph_id: str, document: JsonLdDocument, current_user: Dict):
        """Update following KGTypes pattern"""
        
    async def _delete_kg[type]s(self, space_id: str, graph_id: str, uri: str, uri_list: str, document: JsonLdDocument, current_user: Dict):
        """Delete following KGTypes pattern"""
```

## Implementation Plan

### Phase 1: Basic CRUD Operations (3-4 days) - **KGTypes Pattern Replication**

**Goal**: Implement identical CRUD operations to KGTypes for individual objects and lists of objects (including subclasses).

#### 1.1 KGEntityService Migration
**File**: `/vitalgraph/service/kgentity_service.py`

**Tasks**:
- ✅ Keep existing: `get_kgentity_vitaltypes()`, `validate_kgentity_vitaltype()`
- 🔄 **Add Basic CRUD Methods** (exact copy from KGTypeService pattern):
  ```python
  async def create_kgentity(self, space_id: str, kgentity_data: Dict, graph_id: str) -> str:
      """Create single KGEntity - identical to KGTypeService.create_kgtype()"""
      # Use service_utils.jsonld_to_graphobjects() with self.validate_kgentity_vitaltype
      # Use service_utils.check_subject_uri_conflicts()
      # Use service_utils.execute_with_transaction() + db_ops.add_rdf_quads_batch()
  
  async def update_kgentity(self, space_id: str, kgentity_uri: str, kgentity_data: Dict, graph_id: str) -> bool:
      """Update single KGEntity - identical to KGTypeService.update_kgtype()"""
      # Use service_utils.get_existing_quads_for_uris()
      # Use atomic delete+insert in transaction
  
  async def delete_kgentity(self, space_id: str, kgentity_uri: str, graph_id: str) -> bool:
      """Delete single KGEntity - identical to KGTypeService.delete_kgtype()"""
      # Use service_utils.get_existing_quads_for_uris()
      # Use service_utils.execute_with_transaction() + db_ops.remove_rdf_quads_batch()
  
  async def delete_kgentities(self, space_id: str, kgentity_uris: List[str], graph_id: str) -> int:
      """Batch delete KGEntities - identical to KGTypeService.delete_kgtypes()"""
      # Batch delete using service_utils patterns
  ```

**Scope**: Handle KGEntity objects and all subclasses, individual or batch operations.

#### 1.2 KGFrameService Migration
**File**: `/vitalgraph/service/kgframe_service.py`

**Tasks**:
- ✅ Keep existing: `get_kgframe_vitaltypes()`, `validate_kgframe_vitaltype()`
- 🔄 **Add Basic CRUD Methods** (identical pattern to KGEntityService):
  ```python
  async def create_kgframe(self, space_id: str, kgframe_data: Dict, graph_id: str) -> str:
      """Create single KGFrame - identical pattern to KGEntity/KGType"""
  
  async def update_kgframe(self, space_id: str, kgframe_uri: str, kgframe_data: Dict, graph_id: str) -> bool:
      """Update single KGFrame - identical pattern to KGEntity/KGType"""
  
  async def delete_kgframe(self, space_id: str, kgframe_uri: str, graph_id: str) -> bool:
      """Delete single KGFrame - identical pattern to KGEntity/KGType"""
  
  async def delete_kgframes(self, space_id: str, kgframe_uris: List[str], graph_id: str) -> int:
      """Batch delete KGFrames - identical pattern to KGEntity/KGType"""
  ```

**Scope**: Handle KGFrame objects and all subclasses, individual or batch operations.

#### 1.3 ObjectService Migration
**File**: `/vitalgraph/service/object_service.py`

**Tasks**:
- ✅ Keep existing: All read operations (list, get by URI, search)
- ❌ **Remove SPARQL-based CRUD**: Delete old `create_object()`, `update_object()`, `delete_object()` methods
- 🔄 **Add Basic CRUD Methods** (identical pattern, no vitaltype restrictions):
  ```python
  async def create_objects(self, space_id: str, objects_data: List[Dict], graph_id: str) -> List[str]:
      """Create objects - identical pattern but accepts ANY valid VitalSigns object"""
      # Use service_utils.jsonld_to_graphobjects() with NO vitaltype validator (accepts all)
      # Use service_utils.check_subject_uri_conflicts()
      # Use service_utils.execute_with_transaction() + db_ops.add_rdf_quads_batch()
  
  async def update_objects(self, space_id: str, objects_data: List[Dict], graph_id: str) -> int:
      """Update objects - identical pattern to KGTypes"""
      # Use atomic delete+insert pattern for each object
  
  async def delete_objects(self, space_id: str, object_uris: List[str], graph_id: str) -> int:
      """Delete objects - identical pattern to KGTypes"""
      # Use batch delete pattern
  ```

**Scope**: Handle ANY VitalSigns objects (KGEntity, KGFrame, KGType, edges, etc.), individual or batch operations.

### Phase 2: Basic Endpoint CRUD Operations (2-3 days) - **KGTypes Pattern Replication**

**Goal**: Implement identical CRUD endpoints to KGTypes for individual objects and lists of objects.

#### 2.1 KGEntitiesEndpoint Migration
**File**: `/vitalgraph/endpoint/kgentities_endpoint.py`

**Tasks**:
- ✅ Keep existing: All GET operations (list, get by URI, search)
- 🔄 **Add Basic CRUD Endpoints** (exact copy from KGTypesEndpoint pattern):
  ```python
  @router.post("/api/graphs/kgentities")
  async def create_kgentities(space_id: str, graph_id: str, document: JsonLdDocument, current_user: Dict):
      """Create KGEntities - identical to KGTypesEndpoint.create_kgtypes()"""
      # Same validation pattern as KGTypes
      # Use kgentity_service.create_kgentity() for each object
  
  @router.put("/api/graphs/kgentities") 
  async def update_kgentities(space_id: str, graph_id: str, document: JsonLdDocument, current_user: Dict):
      """Update KGEntities - identical to KGTypesEndpoint.update_kgtypes()"""
      # Same validation pattern as KGTypes
      # Use kgentity_service.update_kgentity() for each object
  
  @router.delete("/api/graphs/kgentities")
  async def delete_kgentities(space_id: str, graph_id: str, uri: str = None, uri_list: str = None, document: JsonLdDocument = None, current_user: Dict = None):
      """Delete KGEntities - identical to KGTypesEndpoint.delete_kgtypes()"""
      # Same validation pattern as KGTypes
      # Support uri, uri_list, and document deletion methods
  ```

**Scope**: Basic CRUD for KGEntity objects and subclasses only.

#### 2.2 KGFramesEndpoint Migration
**File**: `/vitalgraph/endpoint/kgframes_endpoint.py`

**Tasks**:
- ✅ Keep existing: All GET operations (list, get by URI, search)
- 🔄 **Add Basic CRUD Endpoints** (identical pattern to KGEntitiesEndpoint):
  ```python
  @router.post("/api/graphs/kgframes")
  async def create_kgframes(...)
      """Create KGFrames - identical pattern to KGEntities/KGTypes"""
  
  @router.put("/api/graphs/kgframes") 
  async def update_kgframes(...)
      """Update KGFrames - identical pattern to KGEntities/KGTypes"""
  
  @router.delete("/api/graphs/kgframes")
  async def delete_kgframes(...)
      """Delete KGFrames - identical pattern to KGEntities/KGTypes"""
  ```

**Scope**: Basic CRUD for KGFrame objects and subclasses only.

#### 2.3 ObjectsEndpoint Migration
**File**: `/vitalgraph/endpoint/objects_endpoint.py`

**Tasks**:
- ✅ Keep existing: All GET operations (list, get by URI, search)
- 🔄 **Add Basic CRUD Endpoints** (identical pattern, no vitaltype restrictions):
  ```python
  @router.post("/api/graphs/objects")
  async def create_objects(...)
      """Create Objects - identical pattern but accepts ANY VitalSigns objects"""
  
  @router.put("/api/graphs/objects")
  async def update_objects(...)
      """Update Objects - identical pattern to KGTypes"""
  
  @router.delete("/api/graphs/objects") 
  async def delete_objects(...)
      """Delete Objects - identical pattern to KGTypes"""
  ```

**Scope**: Basic CRUD for ANY VitalSigns objects (KGEntity, KGFrame, KGType, edges, etc.).

---

## **Phase 3: Relationship Traversal Implementation (2-3 days) - **Enhanced Query Patterns**

**Goal**: Add relationship traversal capabilities to support complex queries like "get KGFrame with all associated KGSlots" or "get KGEntity with all associated KGFrames and their KGSlots".

### Phase 3A: Service Layer Relationship Methods

#### 3A.1 KGEntityService Relationship Methods
**File**: `/vitalgraph/service/kgentity_service.py`

**Add Relationship Navigation**:
```python
async def get_kgentity_with_frames(self, space_id: str, kgentity_uri: str, graph_id: str, 
                                  include_slots: bool = False) -> Dict:
    """Get KGEntity with all associated KGFrames (and optionally their KGSlots)"""
    # 1. Get base KGEntity object
    # 2. Find frames via Edge_hasKGFrame relationships
    # 3. If include_slots=True, get slots for each frame via Edge_hasKGSlot
    # 4. Return nested structure with entity -> frames -> slots

async def get_kgentities_with_frames(self, space_id: str, kgentity_uris: List[str], graph_id: str,
                                    include_slots: bool = False) -> List[Dict]:
    """Batch version - get multiple KGEntities with their frames/slots"""
    
async def get_entity_frames(self, space_id: str, kgentity_uri: str, graph_id: str) -> List[Dict]:
    """Get just the KGFrames linked to a KGEntity via Edge_hasKGFrame"""
    # Use service_utils.find_related_objects_by_edge_type()
```

#### 3A.2 KGFrameService Relationship Methods  
**File**: `/vitalgraph/service/kgframe_service.py`

**Add Relationship Navigation**:
```python
async def get_kgframe_with_slots(self, space_id: str, kgframe_uri: str, graph_id: str) -> Dict:
    """Get KGFrame with all associated KGSlots"""
    # 1. Get base KGFrame object
    # 2. Find slots via Edge_hasKGSlot relationships
    # 3. Return nested structure with frame -> slots

async def get_kgframes_with_slots(self, space_id: str, kgframe_uris: List[str], graph_id: str) -> List[Dict]:
    """Batch version - get multiple KGFrames with their slots"""

async def get_frame_slots(self, space_id: str, kgframe_uri: str, graph_id: str) -> List[Dict]:
    """Get just the KGSlots linked to a KGFrame via Edge_hasKGSlot"""
    # Use service_utils.find_related_objects_by_edge_type()

async def get_frame_entities(self, space_id: str, kgframe_uri: str, graph_id: str) -> List[Dict]:
    """Get KGEntities that reference this frame (reverse lookup)"""
    # Find entities where Edge_hasKGFrame points to this frame

async def get_frame_hierarchy(self, space_id: str, kgframe_uri: str, graph_id: str) -> Dict:
    """Get parent/child frame relationships using parentFrameURI property"""
```

### Phase 3B: Enhanced Endpoint Parameters

#### 3B.1 KGEntitiesEndpoint Enhanced GET Operations
**File**: `/vitalgraph/endpoint/kgentities_endpoint.py`

**Add Query Parameters**:
```python
@router.get("/api/graphs/kgentities")
async def list_kgentities(
    space_id: str, graph_id: str,
    # Existing parameters...
    include_frames: bool = False,     # Include associated KGFrames
    include_slots: bool = False,      # Include KGSlots within frames
    current_user: Dict = Depends(auth_dependency)
):
    """Enhanced list with optional relationship inclusion"""
    # If include_frames=True, use get_kgentities_with_frames()
    # If include_slots=True, include slots within frames

@router.get("/api/graphs/kgentities")  # with uri parameter
async def get_kgentity_by_uri(
    space_id: str, graph_id: str, uri: str,
    include_frames: bool = False,     # Include associated KGFrames  
    include_slots: bool = False,      # Include KGSlots within frames
    current_user: Dict = Depends(auth_dependency)
):
    """Enhanced get by URI with optional relationship inclusion"""
    # If include_frames=True, use get_kgentity_with_frames()

# New dedicated relationship endpoints
@router.get("/api/graphs/kgentities/kgframes")
async def get_entity_frames(
    space_id: str, graph_id: str, 
    entity_uri: str = None, entity_uri_list: str = None,
    current_user: Dict = Depends(auth_dependency)
):
    """Get KGFrames linked to KGEntities via Edge_hasKGFrame"""
```

#### 3B.2 KGFramesEndpoint Enhanced GET Operations
**File**: `/vitalgraph/endpoint/kgframes_endpoint.py`

**Add Query Parameters**:
```python
@router.get("/api/graphs/kgframes")
async def list_kgframes(
    space_id: str, graph_id: str,
    # Existing parameters...
    include_slots: bool = False,      # Include associated KGSlots
    current_user: Dict = Depends(auth_dependency)
):
    """Enhanced list with optional slot inclusion"""

@router.get("/api/graphs/kgframes")  # with uri parameter  
async def get_kgframe_by_uri(
    space_id: str, graph_id: str, uri: str,
    include_slots: bool = False,      # Include associated KGSlots
    current_user: Dict = Depends(auth_dependency)
):
    """Enhanced get by URI with optional slot inclusion"""

# New dedicated relationship endpoints
@router.get("/api/graphs/kgframes/kgslots")
async def get_frame_slots(
    space_id: str, graph_id: str,
    frame_uri: str = None, frame_uri_list: str = None,
    current_user: Dict = Depends(auth_dependency)
):
    """Get KGSlots linked to KGFrames via Edge_hasKGSlot"""

@router.get("/api/graphs/kgframes/kgentities")
async def get_frame_entities(
    space_id: str, graph_id: str,
    frame_uri: str = None, frame_uri_list: str = None,
    current_user: Dict = Depends(auth_dependency)
):
    """Get KGEntities that reference KGFrames (reverse lookup)"""
```

### Phase 3C: Service Utilities Extensions

#### 3C.1 Relationship Navigation Support
**File**: `/vitalgraph/service/service_utils.py`

**Add New Functions**:
```python
async def find_related_objects_by_edge_type(
    space_manager, space_id: str, graph_id: str, 
    source_uris: List[str], edge_type: str
) -> List[Tuple[str, str]]:
    """Find objects related via specific edge types (e.g., Edge_hasKGFrame)"""
    # Use db_objects to query edge relationships
    # Return (source_uri, destination_uri) pairs

async def get_object_relationships(
    space_manager, space_id: str, graph_id: str, 
    object_uri: str, relationship_types: List[str] = None
) -> Dict[str, List[str]]:
    """Get all relationships for an object, grouped by relationship type"""
    # Use db_objects to find all edges where object is source or destination

async def build_nested_object_structure(
    space_manager, space_id: str, graph_id: str,
    base_objects: List[Dict], relationship_config: Dict
) -> List[Dict]:
    """Build nested object structures with relationships"""
    # relationship_config example:
    # {
    #   "frames": {"edge_type": "Edge_hasKGFrame", "include": True},
    #   "slots": {"edge_type": "Edge_hasKGSlot", "include": True, "parent": "frames"}
    # }
```

#### 3C.2 Database Objects Extensions
**File**: `/vitalgraph/db/postgresql/space/postgresql_space_db_objects.py`

**Add New Methods**:
```python
async def get_edge_relationships(self, space_id: str, edge_type: str, 
                                source_uris: List[str] = None, 
                                destination_uris: List[str] = None,
                                graph_id: Optional[str] = None) -> List[Dict]:
    """Get edge relationships with optimized SQL"""
    # Query edges with hasEdgeSource/hasEdgeDestination properties
    # Support filtering by source URIs, destination URIs, or both
    
async def get_objects_by_edge_traversal(self, space_id: str, graph_id: str,
                                       start_uris: List[str], edge_type: str,
                                       direction: str = "outgoing") -> List[str]:
    """Traverse edges to find related objects"""
    # direction: "outgoing" (source->dest) or "incoming" (dest->source)

async def get_multi_level_relationships(self, space_id: str, graph_id: str,
                                       root_uris: List[str], 
                                       relationship_chain: List[str]) -> Dict:
    """Get multi-level relationships (e.g., Entity -> Frame -> Slot)"""
    # relationship_chain example: ["Edge_hasKGFrame", "Edge_hasKGSlot"]
    # Returns nested structure with all levels
```

---

### Phase 4: Testing & Validation (1-2 days)

#### 4.1 Basic CRUD Testing
- **Unit Tests**: Test each service CRUD method with various object types
- **Integration Tests**: End-to-end API testing with JSON-LD documents
- **Performance Tests**: Batch operations with large datasets
- **Error Scenario Tests**: Invalid JSON-LD, conflicts, not-found cases

#### 4.2 Relationship Traversal Testing
- **Single Level**: Test Entity->Frame, Frame->Slot relationships
- **Multi Level**: Test Entity->Frame->Slot nested queries
- **Performance**: Test relationship queries with large datasets
- **Edge Cases**: Missing relationships, circular references

#### 4.3 Migration Validation
- **Backward Compatibility**: Ensure existing read operations still work
- **Data Integrity**: Verify no data corruption during migration
- **Performance Comparison**: Compare with old SPARQL-based operations

---

### Phase 5: KGSlot Implementation (Future - 2-3 days)

#### 5.1 KGSlotService Creation
**File**: `/vitalgraph/service/kgslot_service.py` (new)

**Implementation**:
- Follow same pattern as other KG services (Phases 1-3)
- Add slot-specific validation (slotSequence, kGSlotValueType)
- Support slot ordering within frames
- Relationship methods for slot-entity connections

#### 5.2 KGSlotsEndpoint Creation
**File**: `/vitalgraph/endpoint/kgslots_endpoint.py` (new)

**Implementation**:
- Full CRUD operations for slots (Phase 1-2 pattern)
- Enhanced GET with relationship inclusion (Phase 3 pattern)
- Slot ordering and sequencing support
- Relationship endpoints for slot-entity connections

## Error Handling Strategy

### Consistent Error Responses

All services will use the same error handling pattern:

```python
# Service Layer Exceptions
from .service_utils import ServiceValidationError, ServiceConflictError

# Endpoint Layer HTTP Responses
try:
    result = await self.kg[type]_service.create_kg[type](...)
except ServiceValidationError as e:
    raise HTTPException(status_code=400, detail=f"Validation error: {str(e)}")
except ServiceConflictError as e:
    raise HTTPException(status_code=409, detail=f"Conflict error: {str(e)}")
except Exception as e:
    raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")
```

### Error Types by HTTP Status Code

- **400 Bad Request**: Invalid JSON-LD, missing URIs, invalid vitaltype
- **404 Not Found**: Space not found, object not found
- **409 Conflict**: URI already exists (create), URI not found (update/delete)
- **500 Internal Server Error**: Database errors, unexpected failures

## Testing Strategy

### Phase 1: Unit Tests
- **Service Layer**: Test each CRUD method with various object types
- **Validation**: Test vitaltype validation for each service
- **Error Handling**: Test all error scenarios

### Phase 2: Integration Tests
- **End-to-End**: Test complete API workflows
- **Relationship Navigation**: Test edge traversal functionality
- **Performance**: Test batch operations with large datasets

### Phase 3: Migration Tests
- **Backward Compatibility**: Ensure existing read operations still work
- **Data Integrity**: Verify no data corruption during migration
- **Performance Comparison**: Compare with old SPARQL-based operations

## Deployment Strategy

### Phase 1: Service Layer Deployment
1. **Deploy Service Changes**: Update service files with new CRUD methods
2. **Keep Old Methods**: Temporarily keep old SPARQL methods as fallback
3. **Feature Flags**: Use feature flags to switch between old/new implementations
4. **Monitor Performance**: Track performance metrics and error rates

### Phase 2: Endpoint Layer Deployment
1. **Deploy New Endpoints**: Add CRUD endpoints alongside existing GET endpoints
2. **Gradual Rollout**: Enable new endpoints for specific users/spaces first
3. **Monitor Usage**: Track API usage and error rates
4. **Full Rollout**: Enable for all users once validated

### Phase 3: Cleanup
1. **Remove Old Code**: Delete old SPARQL-based CRUD methods
2. **Remove Feature Flags**: Clean up temporary feature flag code
3. **Documentation**: Update API documentation with new endpoints
4. **Performance Optimization**: Fine-tune based on production usage

## Success Metrics

### Performance Targets
- **Throughput**: Maintain ~15,000 quads/sec for batch operations
- **Latency**: <100ms for single object operations, <500ms for batch operations
- **Error Rate**: <1% error rate for valid requests
- **Availability**: 99.9% uptime during migration

### Functional Targets
- **API Compatibility**: 100% backward compatibility for existing GET operations
- **Data Integrity**: Zero data loss or corruption during migration
- **Feature Parity**: All CRUD operations work identically to KGTypes
- **Relationship Navigation**: All edge traversal operations work correctly

## Timeline Summary

### Total Estimated Time: 10-14 days (Phases 1-4)

#### **Phase 1: Basic CRUD Operations (3-4 days) - KGTypes Pattern Replication**
- **KGEntityService**: 1 day (copy KGTypeService CRUD methods)
- **KGFrameService**: 1 day (copy KGTypeService CRUD methods)  
- **ObjectService**: 1-2 days (copy KGTypeService CRUD methods, remove old SPARQL)

#### **Phase 2: Basic Endpoint CRUD (2-3 days) - KGTypes Pattern Replication**
- **KGEntitiesEndpoint**: 1 day (copy KGTypesEndpoint CRUD endpoints)
- **KGFramesEndpoint**: 1 day (copy KGTypesEndpoint CRUD endpoints)
- **ObjectsEndpoint**: 1 day (copy KGTypesEndpoint CRUD endpoints)

#### **Phase 3: Relationship Traversal (2-3 days) - Enhanced Query Patterns**
- **Service Layer Relationships**: 1 day (add relationship methods to services)
- **Enhanced Endpoints**: 1 day (add include_frames/include_slots parameters)
- **Service Utilities Extensions**: 1 day (add relationship navigation functions)

#### **Phase 4: Testing & Validation (1-2 days)**
- **Basic CRUD Testing**: 0.5 days (unit tests, integration tests)
- **Relationship Testing**: 0.5 days (traversal tests, performance tests)
- **Migration Validation**: 0.5 days (backward compatibility, data integrity)

#### **Phase 5: KGSlot Implementation (Future - 2-3 days)**
- **KGSlotService**: 1-2 days (follow established pattern)
- **KGSlotsEndpoint**: 1 day (follow established pattern)

### **Key Advantages of Phased Approach:**

#### **Phase 1-2 Benefits:**
- **Immediate Value**: Basic CRUD operations available quickly
- **Low Risk**: Exact copy of proven KGTypes implementation
- **Fast Development**: Copy-paste pattern with minimal changes
- **Production Ready**: Can deploy basic CRUD immediately

#### **Phase 3 Benefits:**
- **Enhanced Functionality**: Relationship traversal for complex queries
- **Backward Compatible**: Existing operations continue to work
- **Optional Features**: Relationship inclusion via parameters
- **Performance Optimized**: Direct SQL for relationship queries

#### **Deployment Strategy:**
1. **Phase 1-2**: Deploy basic CRUD operations (production ready)
2. **Phase 3**: Deploy relationship enhancements (additive features)
3. **Phase 4**: Validate and optimize based on usage
4. **Phase 5**: Add KGSlot support when needed

### Dependencies
- ✅ **KGTypes Implementation**: Complete and production-ready
- ✅ **Database Objects Layer**: Complete with optimized SQL
- ✅ **Service Utilities**: Complete with JSON-LD/GraphObject processing
- ✅ **Transaction Management**: Complete with rollback support

## Risk Mitigation

### Technical Risks
1. **Performance Regression**: Mitigated by using proven KGTypes patterns
2. **Data Corruption**: Mitigated by transaction management and testing
3. **API Breaking Changes**: Mitigated by maintaining backward compatibility
4. **Complex Relationships**: Mitigated by extending db_objects with edge queries

### Operational Risks
1. **Deployment Issues**: Mitigated by gradual rollout and feature flags
2. **User Impact**: Mitigated by maintaining existing functionality during migration
3. **Rollback Complexity**: Mitigated by keeping old code until migration complete
4. **Performance Monitoring**: Mitigated by comprehensive metrics and alerting

## Conclusion

This migration plan leverages the successful KGTypes implementation to provide a **phased approach** that delivers immediate value while building toward advanced functionality:

### **Phase 1-2: Immediate Production Value (5-7 days)**
- **Fast Development**: Exact copy of proven KGTypes patterns
- **High Performance**: Direct SQL operations with ~15,000 quads/sec throughput
- **Production Ready**: Transaction safety and proper error handling
- **Low Risk**: Reusing battle-tested code with minimal changes

### **Phase 3: Enhanced Functionality (2-3 days)**
- **Relationship Traversal**: Support complex queries like "KGEntity with all KGFrames and KGSlots"
- **Backward Compatible**: Existing operations continue unchanged
- **Optional Enhancement**: Relationship inclusion via query parameters
- **Performance Optimized**: Direct SQL for relationship navigation

### **Key Strategic Benefits:**

#### **Incremental Delivery**
- **Phase 1-2**: Basic CRUD operations (immediate business value)
- **Phase 3**: Relationship traversal (enhanced query capabilities)
- **Phase 5**: KGSlot support (complete semantic model)

#### **Risk Management**
- **Proven Architecture**: Leverages successful KGTypes implementation
- **Gradual Rollout**: Each phase can be deployed independently
- **Backward Compatibility**: No breaking changes to existing functionality
- **Performance Guarantee**: Maintains KGTypes-level performance

#### **Development Efficiency**
- **Copy-Paste Pattern**: Minimal new code development
- **Consistent Architecture**: Same patterns across all services
- **Fast Time-to-Market**: 5-7 days for basic CRUD, 10-14 days for full functionality
- **Future-Proof**: Extensible to KGSlot and other object types

The plan provides a **clear, low-risk path** to migrate all KG services to the correct VitalGraph architecture while delivering immediate business value and maintaining the high performance standards established with KGTypes.

---

## Implementation Checklist

### **Phase 1: Basic CRUD Operations (3-4 days)**

#### **1.1 KGEntityService Migration**
**File**: `/vitalgraph/service/kgentity_service.py`

- [ ] **Keep existing methods**
  - [ ] `get_kgentity_vitaltypes()` - working correctly
  - [ ] `validate_kgentity_vitaltype()` - working correctly
- [ ] **Add CRUD methods** (copy from KGTypeService)
  - [ ] `create_kgentity()` - identical to `KGTypeService.create_kgtype()`
  - [ ] `update_kgentity()` - identical to `KGTypeService.update_kgtype()`
  - [ ] `delete_kgentity()` - identical to `KGTypeService.delete_kgtype()`
  - [ ] `delete_kgentities()` - identical to `KGTypeService.delete_kgtypes()`
- [ ] **Testing**
  - [ ] Unit tests for all CRUD methods
  - [ ] Integration tests with database
  - [ ] Error handling tests

#### **1.2 KGFrameService Migration**
**File**: `/vitalgraph/service/kgframe_service.py`

- [ ] **Keep existing methods**
  - [ ] `get_kgframe_vitaltypes()` - working correctly
  - [ ] `validate_kgframe_vitaltype()` - working correctly
- [ ] **Add CRUD methods** (copy from KGTypeService)
  - [ ] `create_kgframe()` - identical pattern to KGEntity/KGType
  - [ ] `update_kgframe()` - identical pattern to KGEntity/KGType
  - [ ] `delete_kgframe()` - identical pattern to KGEntity/KGType
  - [ ] `delete_kgframes()` - identical pattern to KGEntity/KGType
- [ ] **Testing**
  - [ ] Unit tests for all CRUD methods
  - [ ] Integration tests with database
  - [ ] Error handling tests

#### **1.3 ObjectService Migration**
**File**: `/vitalgraph/service/object_service.py`

- [ ] **Keep existing methods**
  - [ ] All read operations (list, get by URI, search) - working correctly
- [ ] **Remove old SPARQL-based CRUD**
  - [ ] Delete old `create_object()` method
  - [ ] Delete old `update_object()` method
  - [ ] Delete old `delete_object()` method
  - [ ] Remove any SPARQL dependencies
- [ ] **Add new CRUD methods** (copy from KGTypeService)
  - [ ] `create_objects()` - accepts ANY VitalSigns objects
  - [ ] `update_objects()` - identical pattern to KGTypes
  - [ ] `delete_objects()` - identical pattern to KGTypes
- [ ] **Testing**
  - [ ] Unit tests for all CRUD methods
  - [ ] Integration tests with various object types
  - [ ] Error handling tests

### **Phase 2: Basic Endpoint CRUD Operations (2-3 days)**

#### **2.1 KGEntitiesEndpoint Migration**
**File**: `/vitalgraph/endpoint/kgentities_endpoint.py`

- [ ] **Keep existing GET operations**
  - [ ] List KGEntities - working correctly
  - [ ] Get by URI - working correctly
  - [ ] Search KGEntities - working correctly
- [ ] **Add CRUD endpoints** (copy from KGTypesEndpoint)
  - [ ] `POST /api/graphs/kgentities` - create KGEntities
  - [ ] `PUT /api/graphs/kgentities` - update KGEntities
  - [ ] `DELETE /api/graphs/kgentities` - delete KGEntities (uri/uri_list/document)
- [ ] **Validation and error handling**
  - [ ] Same validation pattern as KGTypes
  - [ ] Proper HTTP status codes (400, 404, 409, 500)
  - [ ] Consistent error messages
- [ ] **Testing**
  - [ ] End-to-end API tests for all CRUD operations
  - [ ] JSON-LD document processing tests
  - [ ] Error scenario tests

#### **2.2 KGFramesEndpoint Migration**
**File**: `/vitalgraph/endpoint/kgframes_endpoint.py`

- [ ] **Keep existing GET operations**
  - [ ] List KGFrames - working correctly
  - [ ] Get by URI - working correctly
  - [ ] Search KGFrames - working correctly
- [ ] **Add CRUD endpoints** (copy from KGTypesEndpoint)
  - [ ] `POST /api/graphs/kgframes` - create KGFrames
  - [ ] `PUT /api/graphs/kgframes` - update KGFrames
  - [ ] `DELETE /api/graphs/kgframes` - delete KGFrames (uri/uri_list/document)
- [ ] **Validation and error handling**
  - [ ] Same validation pattern as KGTypes
  - [ ] Proper HTTP status codes (400, 404, 409, 500)
  - [ ] Consistent error messages
- [ ] **Testing**
  - [ ] End-to-end API tests for all CRUD operations
  - [ ] JSON-LD document processing tests
  - [ ] Error scenario tests

#### **2.3 ObjectsEndpoint Migration**
**File**: `/vitalgraph/endpoint/objects_endpoint.py`

- [ ] **Keep existing GET operations**
  - [ ] List Objects - working correctly
  - [ ] Get by URI - working correctly
  - [ ] Search Objects - working correctly
- [ ] **Add CRUD endpoints** (copy from KGTypesEndpoint)
  - [ ] `POST /api/graphs/objects` - create Objects (any VitalSigns type)
  - [ ] `PUT /api/graphs/objects` - update Objects
  - [ ] `DELETE /api/graphs/objects` - delete Objects (uri/uri_list/document)
- [ ] **Validation and error handling**
  - [ ] Same validation pattern as KGTypes
  - [ ] Proper HTTP status codes (400, 404, 409, 500)
  - [ ] Consistent error messages
- [ ] **Testing**
  - [ ] End-to-end API tests for all CRUD operations
  - [ ] JSON-LD document processing tests
  - [ ] Error scenario tests

### **Phase 3: Relationship Traversal Implementation (2-3 days)**

#### **3A.1 KGEntityService Relationship Methods**
**File**: `/vitalgraph/service/kgentity_service.py`

- [ ] **Add relationship navigation methods**
  - [ ] `get_kgentity_with_frames()` - get entity with associated frames
  - [ ] `get_kgentities_with_frames()` - batch version
  - [ ] `get_entity_frames()` - get just the frames linked to entity
- [ ] **Testing**
  - [ ] Unit tests for relationship methods
  - [ ] Performance tests with large datasets
  - [ ] Edge case tests (missing relationships)

#### **3A.2 KGFrameService Relationship Methods**
**File**: `/vitalgraph/service/kgframe_service.py`

- [ ] **Add relationship navigation methods**
  - [ ] `get_kgframe_with_slots()` - get frame with associated slots
  - [ ] `get_kgframes_with_slots()` - batch version
  - [ ] `get_frame_slots()` - get just the slots linked to frame
  - [ ] `get_frame_entities()` - get entities that reference frame
  - [ ] `get_frame_hierarchy()` - get parent/child relationships
- [ ] **Testing**
  - [ ] Unit tests for relationship methods
  - [ ] Performance tests with large datasets
  - [ ] Edge case tests (missing relationships, circular references)

#### **3B.1 KGEntitiesEndpoint Enhanced GET Operations**
**File**: `/vitalgraph/endpoint/kgentities_endpoint.py`

- [ ] **Add enhanced query parameters**
  - [ ] `include_frames=True` parameter for list and get operations
  - [ ] `include_slots=True` parameter for nested slot inclusion
- [ ] **Add dedicated relationship endpoints**
  - [ ] `GET /api/graphs/kgentities/kgframes` - get frames linked to entities
- [ ] **Testing**
  - [ ] API tests for enhanced parameters
  - [ ] Performance tests for nested queries
  - [ ] Relationship endpoint tests

#### **3B.2 KGFramesEndpoint Enhanced GET Operations**
**File**: `/vitalgraph/endpoint/kgframes_endpoint.py`

- [ ] **Add enhanced query parameters**
  - [ ] `include_slots=True` parameter for list and get operations
- [ ] **Add dedicated relationship endpoints**
  - [ ] `GET /api/graphs/kgframes/kgslots` - get slots linked to frames
  - [ ] `GET /api/graphs/kgframes/kgentities` - get entities that reference frames
- [ ] **Testing**
  - [ ] API tests for enhanced parameters
  - [ ] Performance tests for nested queries
  - [ ] Relationship endpoint tests

#### **3C.1 Service Utilities Extensions**
**File**: `/vitalgraph/service/service_utils.py`

- [ ] **Add relationship navigation functions**
  - [ ] `find_related_objects_by_edge_type()` - find objects via edge types
  - [ ] `get_object_relationships()` - get all relationships for object
  - [ ] `build_nested_object_structure()` - build nested structures
- [ ] **Testing**
  - [ ] Unit tests for all utility functions
  - [ ] Performance tests with large datasets
  - [ ] Integration tests with services

#### **3C.2 Database Objects Extensions**
**File**: `/vitalgraph/db/postgresql/space/postgresql_space_db_objects.py`

- [ ] **Add relationship query methods**
  - [ ] `get_edge_relationships()` - get edge relationships with optimized SQL
  - [ ] `get_objects_by_edge_traversal()` - traverse edges to find related objects
  - [ ] `get_multi_level_relationships()` - get multi-level relationships
- [ ] **Testing**
  - [ ] Unit tests for all database methods
  - [ ] Performance tests with large datasets
  - [ ] SQL optimization validation

### **Phase 4: Testing & Validation (1-2 days)**

#### **4.1 Basic CRUD Testing**
- [ ] **Unit Tests**
  - [ ] All service CRUD methods tested
  - [ ] All endpoint CRUD operations tested
  - [ ] Error handling scenarios tested
- [ ] **Integration Tests**
  - [ ] End-to-end API workflows tested
  - [ ] JSON-LD document processing tested
  - [ ] Database transaction testing
- [ ] **Performance Tests**
  - [ ] Batch operations with large datasets
  - [ ] Performance comparison with KGTypes baseline
  - [ ] Memory usage validation

#### **4.2 Relationship Traversal Testing**
- [ ] **Single Level Relationships**
  - [ ] Entity->Frame relationships tested
  - [ ] Frame->Slot relationships tested
  - [ ] Reverse lookup relationships tested
- [ ] **Multi Level Relationships**
  - [ ] Entity->Frame->Slot nested queries tested
  - [ ] Performance with deep nesting validated
  - [ ] Memory usage with large nested structures
- [ ] **Edge Cases**
  - [ ] Missing relationships handled correctly
  - [ ] Circular references handled correctly
  - [ ] Large relationship sets performance tested

#### **4.3 Migration Validation**
- [ ] **Backward Compatibility**
  - [ ] All existing GET operations still work
  - [ ] No breaking changes to existing APIs
  - [ ] Performance maintained or improved
- [ ] **Data Integrity**
  - [ ] No data corruption during migration
  - [ ] All CRUD operations maintain data consistency
  - [ ] Transaction rollback working correctly
- [ ] **Production Readiness**
  - [ ] Error handling comprehensive
  - [ ] Logging and monitoring in place
  - [ ] Performance metrics validated

### **Phase 5: KGSlot Implementation (Future - 2-3 days)**

#### **5.1 KGSlotService Creation**
**File**: `/vitalgraph/service/kgslot_service.py` (new)

- [ ] **Follow established pattern**
  - [ ] Copy Phase 1 CRUD pattern from other services
  - [ ] Add slot-specific validation (slotSequence, kGSlotValueType)
  - [ ] Add Phase 3 relationship methods
- [ ] **Slot-specific features**
  - [ ] Slot ordering within frames
  - [ ] Slot value type validation
  - [ ] Slot constraint validation
- [ ] **Testing**
  - [ ] Full test suite following established patterns

#### **5.2 KGSlotsEndpoint Creation**
**File**: `/vitalgraph/endpoint/kgslots_endpoint.py` (new)

- [ ] **Follow established pattern**
  - [ ] Copy Phase 2 CRUD endpoints from other endpoints
  - [ ] Add Phase 3 relationship enhancements
  - [ ] Add slot-specific parameters
- [ ] **Slot-specific features**
  - [ ] Slot ordering and sequencing support
  - [ ] Slot value type filtering
  - [ ] Slot constraint validation
- [ ] **Testing**
  - [ ] Full API test suite following established patterns

### **Deployment Checklist**

#### **Phase 1-2 Deployment (Basic CRUD)**
- [ ] **Pre-deployment**
  - [ ] All Phase 1-2 checklist items completed
  - [ ] Performance tests passing
  - [ ] Security review completed
- [ ] **Deployment**
  - [ ] Feature flags configured
  - [ ] Monitoring and alerting in place
  - [ ] Rollback plan prepared
- [ ] **Post-deployment**
  - [ ] Basic CRUD operations validated in production
  - [ ] Performance metrics within expected ranges
  - [ ] Error rates within acceptable limits

#### **Phase 3 Deployment (Relationship Traversal)**
- [ ] **Pre-deployment**
  - [ ] All Phase 3 checklist items completed
  - [ ] Relationship query performance validated
  - [ ] Backward compatibility confirmed
- [ ] **Deployment**
  - [ ] Gradual rollout of relationship features
  - [ ] Performance monitoring for complex queries
  - [ ] User feedback collection
- [ ] **Post-deployment**
  - [ ] Relationship queries working correctly
  - [ ] Performance within expected ranges
  - [ ] No impact on existing operations

### **Success Criteria**
- [ ] **Performance**: Maintain ~15,000 quads/sec for batch operations
- [ ] **Latency**: <100ms for single object operations, <500ms for batch operations
- [ ] **Error Rate**: <1% error rate for valid requests
- [ ] **Compatibility**: 100% backward compatibility for existing GET operations
- [ ] **Data Integrity**: Zero data loss or corruption during migration
- [ ] **Feature Parity**: All CRUD operations work identically to KGTypes
