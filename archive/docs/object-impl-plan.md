# VitalGraph Objects Implementation Plan - UPDATED

## Overview

This document outlines the **correct implementation approach** for VitalGraph Objects based on the successful KGTypes implementation. The plan follows the proven VitalGraph patterns:

- **JSON-LD to GraphObjects conversion** with VitalSigns validation
- **Transaction-based database operations** using `add_rdf_quads_batch()`
- **Proper conflict detection** and error handling
- **No SPARQL operations** - direct database access through optimized layers

## Architecture Foundation

### Established Pattern (from KGTypes Success)

The correct VitalGraph architecture flow:

```
Endpoint → Service → service_utils → db_objects/db_ops → Database
```

**Key Components:**
1. **Database Objects Layer**: `PostgreSQLSpaceDBObjects` - optimized SQL queries
2. **Service Utilities**: `service_utils.py` - reusable JSON-LD/GraphObject processing
3. **Service Layer**: Type-specific services (KGTypeService, ObjectService, etc.)
4. **Endpoint Layer**: REST API with proper validation and error handling

### VitalSigns Object Model

**Core Concepts:**
1. **GraphObject**: Abstract base class for all VitalSigns objects
   - Contains `vitaltype` property: `http://vital.ai/ontology/vital-core#vitaltype`
   - Has URI property: `http://vital.ai/ontology/vital-core#URIProp`
   - Automatically registers with VitalSigns registry on creation

2. **Object Hierarchy**:
   - `GraphObject` (abstract base)
     - `VITAL_Node` (nodes)
       - `KGNode` (knowledge graph nodes)
         - `KGEntity` (entities)
         - `KGFrame` (frames)
         - `KGType` (types)
     - `VITAL_Edge` (edges with source/destination)

3. **Object Identification**:
   - Has a `vitaltype` property with a URI value
   - The `vitaltype` URI is registered in the VitalSigns class registry
   - All triples with that subject URI form a coherent object

## API Endpoints Design - Correct Implementation

### 1. POST /api/graphs/objects - Create Objects

**Purpose**: Create new objects using proper VitalGraph patterns

**Request Body**: JSON-LD document containing object(s)

**Implementation Pattern** (following KGTypes success):
```python
async def create_objects(self, space_id: str, graph_id: str, document: JsonLdDocument) -> ObjectOperationResponse:
    # 1. Validate space exists (same as triples endpoint)
    # 2. Convert JSON-LD to GraphObjects using service_utils.jsonld_to_graphobjects()
    # 3. Check for URI conflicts using service_utils.check_subject_uri_conflicts()
    # 4. Convert to quads using service_utils.graphobjects_to_quads()
    # 5. Execute with transaction using db_ops.add_rdf_quads_batch()
```

**Validation**:
- JSON-LD structure validation
- VitalSigns GraphObject conversion (validates vitaltype automatically)
- URI conflict detection for create operations
- Transaction rollback on any failure

### 2. PUT /api/graphs/objects - Update Objects

**Purpose**: Update existing objects with atomic delete+insert

**Request Body**: JSON-LD document containing object(s) with URIs

**Implementation Pattern**:
```python
async def update_objects(self, space_id: str, graph_id: str, document: JsonLdDocument) -> ObjectOperationResponse:
    # 1. Validate space exists
    # 2. Convert JSON-LD to GraphObjects (validates data)
    # 3. Get existing quads using service_utils.get_existing_quads_for_uris()
    # 4. Execute atomic delete+insert in transaction
```

**Key Features**:
- Requires URIs in all objects (no auto-generation)
- Atomic delete+insert pattern
- Transaction management with rollback
- Validates objects exist before update

### 3. DELETE /api/graphs/objects - Delete Objects

**Purpose**: Delete objects by URI, URI list, or JSON-LD document

**Parameters**:
- `uri` (optional): Single object URI to delete
- `uri_list` (optional): Comma-separated list of object URIs
- `document` (optional): JSON-LD document with objects to delete

**Implementation Pattern**:
```python
async def delete_objects(self, space_id: str, graph_id: str, **params) -> ObjectOperationResponse:
    # 1. Validate space exists
    # 2. Extract URIs from uri/uri_list/document
    # 3. Get existing quads using service_utils.get_existing_quads_for_uris()
    # 4. Execute batch delete using db_ops.remove_rdf_quads_batch()
```

**Key Features**:
- Three deletion methods supported
- Batch deletion for efficiency
- Transaction management
- Proper error handling for not-found cases

### 4. GET /api/graphs/objects - List/Get Objects

**Purpose**: List objects with pagination or retrieve specific objects

**Parameters**:
- `space_id` (required): Space identifier
- `graph_id` (required): Graph identifier
- `page_size` (optional): Number of objects per page
- `offset` (optional): Pagination offset
- `uri` (optional): Single object URI to retrieve
- `uri_list` (optional): Comma-separated list of object URIs
- `vitaltype_filter` (optional): Filter by vitaltype URI
- `search` (optional): Search within object properties

**Implementation**: Uses existing ObjectService (already implemented and working)

## Implementation Architecture - Correct Approach

### 1. Reuse Existing Foundation

**✅ Already Implemented:**
- **Database Objects Layer**: `PostgreSQLSpaceDBObjects` - optimized SQL queries
- **Service Utilities**: `service_utils.py` - reusable JSON-LD/GraphObject processing  
- **ObjectService**: Already exists with read operations (list, get by URI, search)

### 2. General Object Service (Enhanced)

**File**: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph/service/object_service.py`

**Add Missing CRUD Methods** (following KGTypes pattern):

```python
class ObjectService:
    def __init__(self, space_manager):
        self.space_manager = space_manager
        # Initialize VitalSigns for general validation
        self.vitalsigns = VitalSigns()
        self.registry = self.vitalsigns.get_registry()
    
    # ✅ Already implemented: list_objects, get_object_by_uri, get_objects_by_uris
    
    async def create_objects(self, space_id: str, graph_id: str, objects_data: List[Dict]) -> List[str]:
        """Create new objects using service_utils pattern"""
        # Use service_utils.jsonld_to_graphobjects() with no vitaltype validator (accepts all)
        # Use service_utils.check_subject_uri_conflicts()
        # Use service_utils.execute_with_transaction() + db_ops.add_rdf_quads_batch()
        
    async def update_objects(self, space_id: str, graph_id: str, objects_data: List[Dict]) -> int:
        """Update existing objects using atomic delete+insert"""
        # Use service_utils.get_existing_quads_for_uris()
        # Use service_utils.execute_with_transaction() with delete+insert
        
    async def delete_objects(self, space_id: str, graph_id: str, object_uris: List[str]) -> int:
        """Delete objects using batch operations"""
        # Use service_utils.get_existing_quads_for_uris()
        # Use service_utils.execute_with_transaction() + db_ops.remove_rdf_quads_batch()
```

### 3. Objects Endpoint (Enhanced)

**File**: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph/endpoint/objects_endpoint.py`

**Add Missing CRUD Endpoints** (following KGTypes pattern):

```python
class ObjectsEndpoint:
    def __init__(self, space_manager, auth_dependency):
        self.space_manager = space_manager
        self.object_service = ObjectService(space_manager)
        # Setup routes for POST, PUT, DELETE
    
    # ✅ Already implemented: GET operations
    
    async def _create_objects(self, space_id: str, graph_id: str, document: JsonLdDocument, current_user: Dict):
        """Create objects following triples endpoint validation pattern"""
        # Same validation as KGTypes endpoint
        # Use object_service.create_objects()
        
    async def _update_objects(self, space_id: str, graph_id: str, document: JsonLdDocument, current_user: Dict):
        """Update objects following KGTypes pattern"""
        # Same validation as KGTypes endpoint
        # Use object_service.update_objects()
        
    async def _delete_objects(self, space_id: str, graph_id: str, uri: str, uri_list: str, document: JsonLdDocument, current_user: Dict):
        """Delete objects following KGTypes pattern"""
        # Same validation as KGTypes endpoint
        # Use object_service.delete_objects()
```

### 4. No Additional Components Needed

**❌ Not Needed:**
- **VitalSignsValidator**: VitalSigns validation happens automatically in `jsonld_to_graphobjects()`
- **ObjectQueryBuilder**: Direct SQL through `db_objects` layer is faster
- **SPARQL Operations**: Eliminated in favor of `add_rdf_quads_batch()` pattern

### 5. Implementation Benefits

**Reuses Proven Architecture:**
- Same patterns as successful KGTypes implementation
- Leverages existing high-performance database operations (~15,000 quads/sec)
- Uses established service utilities for consistency
- Follows triples endpoint validation patterns

**Key Advantages:**
- **No SPARQL**: Direct database operations for maximum performance
- **Transaction Safety**: Atomic operations with rollback
- **Conflict Detection**: Proper URI conflict checking
- **Error Handling**: Consistent HTTP status codes and error messages
- **Batch Operations**: Efficient bulk create/update/delete

## Test Data Creation

### 1. Sample KGEntity Objects

```python
# Create test KGEntity objects
def create_test_kg_entities():
    entities = []
    
    # Person entity
    person = KGEntity()
    person.URI = "http://example.org/person/john_doe"
    person.hasName = "John Doe"
    person.hasKGEntityType = "http://example.org/types/Person"
    entities.append(person)
    
    # Organization entity
    org = KGEntity() 
    org.URI = "http://example.org/org/acme_corp"
    org.hasName = "ACME Corporation"
    org.hasKGEntityType = "http://example.org/types/Organization"
    entities.append(org)
    
    return entities
```

### 2. Sample KGFrame Objects

```python
# Create test KGFrame objects (like WordNet frames)
def create_test_kg_frames():
    frames = []
    
    # Semantic frame
    frame = KGFrame()
    frame.URI = "http://example.org/frame/communication_frame_001"
    frame.hasName = "Communication Frame"
    frame.hasKGFrameType = "http://example.org/frame_types/Communication"
    frame.hasFrameSequence = 1
    frames.append(frame)
    
    return frames
```

### 3. Sample Edge Objects

```python
# Create test edge objects
def create_test_edges():
    edges = []
    
    # Employment edge
    edge = VITAL_Edge()
    edge.URI = "http://example.org/edge/employment_001"
    edge.hasEdgeSource = "http://example.org/person/john_doe"
    edge.hasEdgeDestination = "http://example.org/org/acme_corp"
    edge.hasName = "Employment Relationship"
    edges.append(edge)
    
    return edges
```

## Implementation Steps - Updated Plan

### Phase 1: Enhance ObjectService (1-2 days)
1. ✅ **Foundation Complete**: Database objects layer, service utilities, existing read operations
2. **Add CRUD Methods**: Implement `create_objects()`, `update_objects()`, `delete_objects()` using service_utils
3. **Remove Old SPARQL Methods**: Clean out any remaining SPARQL-based create/update/delete methods
4. **VitalSigns Integration**: Use existing VitalSigns initialization for general validation

### Phase 2: Enhance Objects Endpoint (1-2 days)
1. ✅ **GET Operations Complete**: List, get by URI, search all working
2. **Add POST Endpoint**: Create objects following KGTypes validation pattern
3. **Add PUT Endpoint**: Update objects with atomic delete+insert
4. **Add DELETE Endpoint**: Delete objects with URI/URI list/document support
5. **Error Handling**: Consistent HTTP status codes (400, 404, 409, 500)

### Phase 3: Testing & Validation (1 day)
1. **Unit Tests**: Test service methods with various object types
2. **Integration Tests**: End-to-end API testing with JSON-LD documents
3. **Performance Tests**: Batch operations with large datasets
4. **Error Scenario Tests**: Invalid JSON-LD, conflicts, not-found cases

### Phase 4: Documentation & Deployment (1 day)
1. **API Documentation**: Update with new CRUD endpoints
2. **Usage Examples**: JSON-LD examples for different object types
3. **Migration Guide**: Any breaking changes from old implementation
4. **Production Deployment**: Deploy with monitoring and rollback plan

## Key Advantages of This Approach

### ✅ Proven Architecture
- **Reuses KGTypes Success**: Same patterns that are already working in production
- **High Performance**: Leverages ~15,000 quads/sec batch operations
- **Transaction Safety**: Atomic operations with proper rollback
- **Clean Error Handling**: Consistent HTTP status codes and error messages

### ✅ Minimal Development Time
- **Foundation Exists**: Database layer, service utilities, read operations all done
- **Copy-Paste Pattern**: CRUD methods follow exact KGTypes implementation
- **No New Components**: No need for additional validators or query builders
- **Fast Implementation**: Estimated 4-5 days total vs weeks for SPARQL approach

### ✅ Future-Proof Design
- **Extensible**: KGEntity, KGFrame can use same pattern
- **Maintainable**: Clean separation of concerns
- **Testable**: Each layer can be tested independently
- **Scalable**: Direct SQL operations for maximum performance

## Database Queries

### Object Listing Query
```sql
-- Get objects with pagination
WITH object_subjects AS (
  SELECT DISTINCT s_term.term_text as subject_uri,
         vt_obj.term_text as vitaltype
  FROM vitalgraph1__space__rdf_quad q
  JOIN vitalgraph1__space__term s_term ON q.subject_uuid = s_term.term_uuid
  JOIN vitalgraph1__space__term p_term ON q.predicate_uuid = p_term.term_uuid
  JOIN vitalgraph1__space__term vt_obj ON q.object_uuid = vt_obj.term_uuid
  WHERE p_term.term_text = 'http://vital.ai/ontology/vital-core#vitaltype'
    AND q.context_uuid = ?
  ORDER BY s_term.term_text
  LIMIT ? OFFSET ?
)
-- Get all triples for these objects
SELECT s_term.term_text as subject,
       p_term.term_text as predicate, 
       o_term.term_text as object,
       o_term.term_type as object_type,
       o_term.term_language as object_language,
       o_term.term_datatype as object_datatype
FROM vitalgraph1__space__rdf_quad q
JOIN vitalgraph1__space__term s_term ON q.subject_uuid = s_term.term_uuid
JOIN vitalgraph1__space__term p_term ON q.predicate_uuid = p_term.term_uuid  
JOIN vitalgraph1__space__term o_term ON q.object_uuid = o_term.term_uuid
JOIN object_subjects os ON s_term.term_text = os.subject_uri
WHERE q.context_uuid = ?
ORDER BY s_term.term_text, p_term.term_text
```

### Single Object Query
```sql
-- Get all triples for specific object URI
SELECT s_term.term_text as subject,
       p_term.term_text as predicate,
       o_term.term_text as object,
       o_term.term_type as object_type,
       o_term.term_language as object_language,
       o_term.term_datatype as object_datatype
FROM vitalgraph1__space__rdf_quad q
JOIN vitalgraph1__space__term s_term ON q.subject_uuid = s_term.term_uuid
JOIN vitalgraph1__space__term p_term ON q.predicate_uuid = p_term.term_uuid
JOIN vitalgraph1__space__term o_term ON q.object_uuid = o_term.term_uuid
WHERE s_term.term_text = ?
  AND q.context_uuid = ?
ORDER BY p_term.term_text
```

### Optimized Object Operations (Direct SQL)

#### Object Deletion (Batch)
```sql
-- Delete all triples for multiple object URIs (optimized batch delete)
DELETE FROM vitalgraph1__space__rdf_quad 
WHERE subject_uuid IN (
  SELECT term_uuid FROM vitalgraph1__space__term 
  WHERE term_text = ANY(?)  -- Array of URIs
) AND context_uuid = ?;
```

#### Object Creation (Conflict Check + Insert)
```sql
-- Check for existing objects (conflict detection)
SELECT term_text FROM vitalgraph1__space__term 
WHERE term_text = ANY(?) AND term_type = 'U';

-- Bulk insert triples for new objects (after conflict check passes)
INSERT INTO vitalgraph1__space__rdf_quad (quad_uuid, subject_uuid, predicate_uuid, object_uuid, context_uuid)
SELECT gen_random_uuid(), s.term_uuid, p.term_uuid, o.term_uuid, ?
FROM (VALUES 
  ('http://example.org/person1', 'http://vital.ai/ontology/vital-core#vitaltype', 'http://vital.ai/ontology/haley-ai-kg#KGEntity'),
  ('http://example.org/person1', 'http://vital.ai/ontology/vital-core#hasName', 'John Doe')
  -- ... more triples
) AS triples(subj, pred, obj)
JOIN vitalgraph1__space__term s ON s.term_text = triples.subj
JOIN vitalgraph1__space__term p ON p.term_text = triples.pred  
JOIN vitalgraph1__space__term o ON o.term_text = triples.obj;
```

#### Object Update (Atomic Delete + Insert)
```sql
-- Transaction: Delete existing + Insert new
BEGIN;

-- Delete existing triples for object
DELETE FROM vitalgraph1__space__rdf_quad 
WHERE subject_uuid = (
  SELECT term_uuid FROM vitalgraph1__space__term 
  WHERE term_text = ? AND term_type = 'U'
) AND context_uuid = ?;

-- Insert new triples for object
INSERT INTO vitalgraph1__space__rdf_quad (quad_uuid, subject_uuid, predicate_uuid, object_uuid, context_uuid)
SELECT gen_random_uuid(), s.term_uuid, p.term_uuid, o.term_uuid, ?
FROM (VALUES 
  -- ... new triples for updated object
) AS triples(subj, pred, obj)
JOIN vitalgraph1__space__term s ON s.term_text = triples.subj
JOIN vitalgraph1__space__term p ON p.term_text = triples.pred
JOIN vitalgraph1__space__term o ON o.term_text = triples.obj;

COMMIT;
```

#### Object Count (Fast)
```sql
-- Count objects by vitaltype (optimized with minimal JOINs)
SELECT COUNT(DISTINCT q.subject_uuid) as object_count
FROM vitalgraph1__space__rdf_quad q
JOIN vitalgraph1__space__term p_term ON q.predicate_uuid = p_term.term_uuid
WHERE p_term.term_text = 'http://vital.ai/ontology/vital-core#vitaltype'
  AND q.context_uuid = ?;
```

## JSON-LD Response Format

### Single Object Response
```json
{
  "@context": {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "vital": "http://vital.ai/ontology/vital-core#",
    "haley": "http://vital.ai/ontology/haley-ai-kg#",
    "vitaltype": "vital:vitaltype",
    "name": "vital:hasName",
    "type": "@type"
  },
  "@id": "http://example.org/person/john_doe",
  "type": "haley:KGEntity", 
  "vitaltype": "haley:KGEntity",
  "name": "John Doe",
  "haley:hasKGEntityType": "http://example.org/types/Person"
}
```

### Multiple Objects Response
```json
{
  "@context": {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "vital": "http://vital.ai/ontology/vital-core#",
    "haley": "http://vital.ai/ontology/haley-ai-kg#",
    "vitaltype": "vital:vitaltype",
    "name": "vital:hasName",
    "type": "@type"
  },
  "@graph": [
    {
      "@id": "http://example.org/person/john_doe",
      "type": "haley:KGEntity",
      "vitaltype": "haley:KGEntity", 
      "name": "John Doe"
    },
    {
      "@id": "http://example.org/org/acme_corp",
      "type": "haley:KGEntity",
      "vitaltype": "haley:KGEntity",
      "name": "ACME Corporation"
    }
  ]
}
```

## Error Handling

### Validation Errors
- Invalid vitaltype URI (not in registry)
- Missing required properties for object type
- Invalid edge without source/destination
- Malformed JSON-LD structure

### Conflict Errors  
- Object URI already exists (on create)
- Object URI not found (on update/delete)
- Graph/space not found

### System Errors
- Database connection failures
- SPARQL query errors
- VitalSigns registry unavailable

## Performance Considerations

### Direct SQL vs SPARQL Approach

Following the ultra-fast triples endpoint pattern, we should implement object operations using **optimized direct SQL** while maintaining SPARQL semantics:

**Benefits of Direct SQL**:
- 5-25x faster than SPARQL for data operations (~5-20ms vs 124ms)
- Direct control over query optimization
- Efficient JOIN strategies and index usage
- Bypasses SPARQL-to-SQL translation overhead

**Implementation Strategy**:
1. **Object Identification**: Direct SQL to find subjects with vitaltype
2. **Object Retrieval**: Efficient JOINs for triple resolution
3. **Object Creation**: Direct INSERT with conflict detection
4. **Object Updates**: Atomic DELETE + INSERT in transaction
5. **Object Deletion**: Optimized DELETE with batch support

### Performance Optimizations

1. **Indexing**: Ensure indexes on vitaltype predicate for fast object identification
2. **Pagination**: Use LIMIT/OFFSET for large object lists
3. **Caching**: Cache VitalSigns registry lookups
4. **Batch Operations**: Support bulk create/delete operations
5. **Connection Pooling**: Reuse database connections efficiently
6. **Direct SQL**: Bypass SPARQL translation for maximum performance

## Security & Authorization

1. **Authentication**: Use existing auth_dependency for all endpoints
2. **Space Access**: Verify user has access to specified space
3. **Graph Access**: Verify user has access to specified graph
4. **Input Validation**: Sanitize all user inputs
5. **Rate Limiting**: Implement rate limiting for object operations

## Summary - Correct Implementation Path

This updated implementation plan provides the **correct approach** for building Objects endpoints based on the successful KGTypes implementation:

### ✅ **Proven Foundation**
- **Database Objects Layer**: `PostgreSQLSpaceDBObjects` with optimized SQL
- **Service Utilities**: `service_utils.py` with JSON-LD/GraphObject processing
- **High Performance**: ~15,000 quads/sec batch operations
- **Transaction Safety**: Atomic operations with rollback

### ✅ **Correct Architecture**
```
ObjectsEndpoint → ObjectService → service_utils → db_objects/db_ops → Database
```

### ✅ **Implementation Benefits**
- **Fast Development**: 4-5 days vs weeks for SPARQL approach
- **Production Ready**: Leverages proven patterns from KGTypes success
- **High Performance**: Direct SQL operations, no SPARQL translation overhead
- **Consistent**: Same patterns across all VitalGraph object services
- **Future-Proof**: Extensible to KGEntity, KGFrame, and other object types

### ✅ **Key Technical Features**
- **JSON-LD Processing**: Proper conversion to VitalSigns GraphObjects
- **Conflict Detection**: URI conflict checking for create operations
- **Atomic Updates**: Delete+insert pattern for consistency
- **Batch Operations**: Efficient bulk create/update/delete
- **Error Handling**: Proper HTTP status codes and error messages
- **VitalSigns Integration**: Automatic vitaltype validation

This approach eliminates the incorrect SPARQL-based patterns and follows the established VitalGraph architecture for maximum performance, reliability, and maintainability.

## VitalSigns Type System Analysis (Updated)

### Core Type Hierarchy from .pyi Files
Based on analysis of .pyi files in the VitalSigns packages:

#### Base Classes
- **VITAL_Node**: Root class for all nodes
- **KGNode**: Base class for knowledge graph nodes, extends VITAL_Node

#### Key KG Types and Their Semantic Roles

1. **KGEntity** (extends KGNode) - **Represents: People, Places, Things**
   - **Purpose**: Represents real-world entities like persons, organizations, locations, concepts
   - **Properties**: `kGEntityType`, `kGEntityTypeDescription`, `kGFormType`, `kGProvenanceType`
   - **URI**: `http://vital.ai/ontology/haley-ai-kg#KGEntity`
   - **Examples**: 
     - Person: "John Doe", "Dr. Sarah Johnson"
     - Organization: "ACME Corporation", "MIT AI Lab"
     - Location: "New York City", "Building A"
     - Concept: "Machine Learning", "Artificial Intelligence"

2. **KGFrame** (extends KGNode) - **Represents: Information Groupings/Contexts**
   - **Purpose**: Groups related information and relationships into coherent contexts
   - **Properties**: `frameGraphURI`, `kGFrameType`, `kGFrameTypeDescription`, `parentFrameURI`
   - **URI**: `http://vital.ai/ontology/haley-ai-kg#KGFrame`
   - **Examples**:
     - Employment Frame: Groups employment-related information
     - Address Frame: Groups address/location information  
     - Education Frame: Groups educational background information
     - Project Frame: Groups project-related data

3. **KGSlot** (extends KGNode) - **Represents: Individual Values/Facts**
   - **Purpose**: Represents specific values, facts, or properties within a frame
   - **Properties**: `kGSlotType`, `kGSlotTypeDescription`, `kGSlotValueType`, `slotSequence`
   - **URI**: `http://vital.ai/ontology/haley-ai-kg#KGSlot`
   - **Examples** (within Employment Frame):
     - Employee Slot: Points to the person entity being employed
     - Employer Slot: Points to the organization entity doing the employing
     - Start Date Slot: Contains the employment start date
     - End Date Slot: Contains the employment end date
     - Position Title Slot: Contains the job title
     - Salary Slot: Contains compensation information

#### Semantic Relationships and Data Model

**Conceptual Example - Employment Information:**

```
Employment Frame (KGFrame)
├── Employee Slot (KGSlot) → Points to "John Doe" (KGEntity)
├── Employer Slot (KGSlot) → Points to "ACME Corp" (KGEntity)  
├── Position Slot (KGSlot) → Contains "Software Engineer"
├── Start Date Slot (KGSlot) → Contains "2023-01-15"
├── End Date Slot (KGSlot) → Contains "2024-06-30"
├── Location Slot (KGSlot) → Points to "New York Office" (KGEntity)
└── Salary Slot (KGSlot) → Contains "$95,000"
```

#### Edge Relationships and Navigation

**Core Edge Types for Relationship Traversal:**
- **Edge_hasKGFrame**: Links entities to frames (Entity → Frame)
  - `hasEdgeSource`: Points to KGEntity
  - `hasEdgeDestination`: Points to KGFrame
- **Edge_hasKGSlot**: Links frames to their slots (Frame → Slot)
  - `hasEdgeSource`: Points to KGFrame  
  - `hasEdgeDestination`: Points to KGSlot
- **Edge_hasKGEntity**: Links slots to entities (Slot → Entity)
  - `hasEdgeSource`: Points to KGSlot
  - `hasEdgeDestination`: Points to KGEntity

**Navigation Patterns:**

**Forward Navigation (via edges):**
```
KGEntity --[Edge_hasKGFrame]--> KGFrame --[Edge_hasKGSlot]--> KGSlot --[Edge_hasKGEntity]--> KGEntity
```

**Reverse Lookup (direct references):**
```
KGEntity <--[property/edge]-- KGSlot
```

**Complete Navigation Flow:**
1. **Entity → Frames**: Find frames that reference this entity (via Edge_hasKGFrame)
2. **Frame → Slots**: Find slots within this frame (via Edge_hasKGSlot)  
3. **Slot → Entity**: Find entity referenced by this slot (via Edge_hasKGEntity)
4. **Entity ← Slots**: Find slots that directly reference this entity (reverse lookup)

### KGNode Common Properties
All KG types inherit from KGNode with properties:
- `kGIdentifier`: Unique identifier
- `kGRefURI`: Reference URI
- `kGTenantIdentifier`: Multi-tenancy support
- `kGIndexDateTime`: Indexing timestamp
- `kGJSON`: JSON representation
- `kGModelVersion`: Version tracking

## Implementation Progress

### ✅ Objects Endpoint - COMPLETED
**Status: Production Ready**

The Objects API has been successfully implemented with all core functionality working:

#### Core Features Completed:
1. **✅ List Objects**: Paginated listing of all objects (1,536,485 objects available)
2. **✅ Individual Object GET**: Retrieve specific objects by URI with full properties
3. **✅ VitalType Filtering**: Filter objects by vitaltype (285,348 KGFrame objects)
4. **✅ Search Functionality**: Full-text search across object properties (1,110 results for "test")
5. **✅ JSON-LD 1.1 Format**: Standards-compliant output with clean URIs
6. **✅ Ultra-Fast Performance**: Direct SQL queries on 8M+ triples
7. **✅ Graph-Aware Operations**: Proper graph isolation and UUID handling

#### Technical Implementation:
- **Service Layer**: `ObjectService` class handles all database operations
- **Endpoint Layer**: `GraphObjectsEndpoint` provides REST API
- **Database Integration**: Direct SQL with psycopg for optimal performance
- **Search Implementation**: Complex CTE-based search across literal properties
- **URI Handling**: Proper angle bracket management for database compatibility

#### API Endpoints:
- `GET /api/graphs/objects` - List/search objects with pagination
- `GET /api/graphs/objects?uri={uri}` - Get specific object
- `GET /api/graphs/objects?uri_list={uris}` - Get multiple objects

### ✅ KGEntities Endpoint - COMPLETED  
**Status: Implemented and Ready for Testing**

Built on top of the Objects infrastructure with KGEntity-specific filtering:

#### Core Features Completed:
1. **✅ KGEntityService**: Service layer with VitalSigns ontology integration
2. **✅ Subclass Resolution**: Uses VitalSigns registry to find KGEntity subclasses
3. **✅ List KGEntities**: Filtered listing of KGEntity objects and subclasses
4. **✅ Individual KGEntity GET**: Retrieve specific entities by URI
5. **✅ Multiple KGEntities GET**: Batch retrieval by URI list
6. **✅ Search Integration**: Text search across KGEntity properties
7. **✅ Type Validation**: Ensures returned objects are valid KGEntities

#### Technical Implementation:
- **Service Layer**: `KGEntityService` extends `ObjectService`
- **Ontology Integration**: Uses VitalSigns `get_subclass_uri_list()` method
- **Type Filtering**: Filters objects by KGEntity vitaltype and subclasses
- **Endpoint Layer**: Updated `KGEntitiesEndpoint` with real service calls

#### API Endpoints:
- `GET /api/graphs/kgentities` - List/search KGEntities with pagination
- `GET /api/graphs/kgentities?uri={uri}` - Get specific KGEntity
- `GET /api/graphs/kgentities?uri_list={uris}` - Get multiple KGEntities
- `GET /api/graphs/kgentities/kgframes` - Get frames linked to entities via Edge_hasKGFrame

### ✅ KGFrames Endpoint - COMPLETED
**Status: Implemented and Ready for Testing**

Built on the same pattern as KGEntities with KGFrame-specific filtering:

#### Core Features Completed:
1. **✅ KGFrameService**: Service layer with VitalSigns ontology integration
2. **✅ Subclass Resolution**: Uses VitalSigns registry to find KGFrame subclasses  
3. **✅ List KGFrames**: Filtered listing of KGFrame objects and subclasses
4. **✅ Individual KGFrame GET**: Retrieve specific frames by URI
5. **✅ Multiple KGFrames GET**: Batch retrieval by URI list
6. **✅ Search Integration**: Text search across KGFrame properties
7. **✅ Type Validation**: Ensures returned objects are valid KGFrames

#### Technical Implementation:
- **Service Layer**: `KGFrameService` extends `ObjectService`
- **Ontology Integration**: Uses VitalSigns `get_subclass_uri_list()` method
- **Type Filtering**: Filters objects by KGFrame vitaltype and subclasses
- **Endpoint Layer**: Updated `KGFramesEndpoint` with real service calls

#### API Endpoints:
- `GET /api/graphs/kgframes` - List/search KGFrames with pagination
- `GET /api/graphs/kgframes?uri={uri}` - Get specific KGFrame
- `GET /api/graphs/kgframes?uri_list={uris}` - Get multiple KGFrames
- `GET /api/graphs/kgframes/kgslots` - Get slots linked to frames via Edge_hasKGSlot

### Test Scripts Created
1. **`test_objects_endpoint.py`**: Comprehensive Objects API testing
2. **`test_kgentities_endpoint.py`**: KGEntities API testing
3. **`test_kgframes_endpoint.py`**: KGFrames API testing

## Next Steps

### Semantic Model Implications for API Design

#### Usage Patterns

1. **Entity-Centric Queries**:
   - Find all frames that reference a specific entity
   - Get all employment history for a person
   - Find all projects associated with an organization

2. **Frame-Centric Queries**:
   - Get all slots within an employment frame
   - Find frames of a specific type (e.g., all address frames)
   - Navigate frame hierarchies using `parentFrameURI`

3. **Slot-Centric Queries**:
   - Find slots that point to specific entities
   - Get all salary information across employment frames
   - Find slots with specific value types

#### API Design Considerations

**Relationship Traversal Requirements**:

#### 1. Entity → Frame Navigation (Edge_hasKGFrame)
- **Endpoint**: `GET /api/graphs/kgentities/kgframes`
- **Parameters**: `entity_uri` or `entity_uri_list`
- **Query**: Find frames where `hasEdgeSource = entity_uri` and edge type is `Edge_hasKGFrame`
- **Use Case**: "Show all frames that reference this person/organization"

#### 2. Frame → Slot Navigation (Edge_hasKGSlot)  
- **Endpoint**: `GET /api/graphs/kgframes/kgslots`
- **Parameters**: `frame_uri` or `frame_uri_list`
- **Query**: Find slots where `hasEdgeSource = frame_uri` and edge type is `Edge_hasKGSlot`
- **Use Case**: "Show all slots within this employment/address frame"

#### 3. Slot → Entity Navigation (Edge_hasKGEntity)
- **Endpoint**: `GET /api/graphs/kgslots/kgentities` 
- **Parameters**: `slot_uri` or `slot_uri_list`
- **Query**: Find entities where `hasEdgeSource = slot_uri` and edge type is `Edge_hasKGEntity`
- **Use Case**: "Show which entity this slot points to"

#### Edge Traversal SQL Pattern:
```sql
-- Generic edge traversal query
SELECT 
    edge.subject_uuid as edge_uri,
    source_term.term_text as source_uri,
    dest_term.term_text as destination_uri,
    edge_type_term.term_text as edge_type
FROM {space}_rdf_quad edge
JOIN {space}_term edge_type_term ON edge.predicate_uuid = edge_type_term.term_uuid
JOIN {space}_rdf_quad source_triple ON edge.subject_uuid = source_triple.subject_uuid
JOIN {space}_term source_pred ON source_triple.predicate_uuid = source_pred.term_uuid
JOIN {space}_term source_term ON source_triple.object_uuid = source_term.term_uuid
JOIN {space}_rdf_quad dest_triple ON edge.subject_uuid = dest_triple.subject_uuid  
JOIN {space}_term dest_pred ON dest_triple.predicate_uuid = dest_pred.term_uuid
JOIN {space}_term dest_term ON dest_triple.object_uuid = dest_term.term_uuid
WHERE edge_type_term.term_text = %s  -- Edge type (e.g., 'Edge_hasKGFrame')
  AND source_pred.term_text = 'http://vital.ai/ontology/vital-core#hasEdgeSource'
  AND dest_pred.term_text = 'http://vital.ai/ontology/vital-core#hasEdgeDestination'
  AND source_term.term_text = %s  -- Source URI filter
  AND edge.context_uuid = %s
```

**Contextual Queries**:
- Search for entities within specific frame contexts
- Filter slots by value type and frame type  
- Navigate frame hierarchies for complex information structures
- Multi-hop traversal: Entity → Frame → Slot → Entity chains

### KGSlot Integration (Planned)
Based on VitalSigns analysis and semantic model, implement:

#### Core KGSlot Functionality:
- **KGSlot Endpoints**: `/api/graphs/kgslots`
- **Slot Value Types**: Handle different `kGSlotValueType` (entity refs, literals, dates)
- **Slot Constraints**: Implement `kGSlotConstraintType` validation
- **Slot Sequencing**: Support `slotSequence` for ordered slots within frames

#### Relationship Navigation:
- **Frame-Slot Relationships**: Use Edge_hasKGSlot to link frames to slots
- **Entity-Slot Relationships**: Use Edge_hasKGEntity for slot-entity connections
- **Slot Value Resolution**: Resolve slot values to entities or literals

#### Advanced Slot Operations:
- **Slot Validation**: Ensure slot values match declared types
- **Slot Ordering**: Maintain slot sequence within frames
- **Slot Constraints**: Validate against slot constraint types
- **Value Type Handling**: Support entity references, literals, dates, numbers

## Relationship Traversal Implementation Requirements

### 1. KGEntities/KGFrames Endpoint (REQUIRED)
**Endpoint**: `GET /api/graphs/kgentities/kgframes`

**Implementation Requirements**:
- Query edges where `vitaltype = "Edge_hasKGFrame"`
- Filter by `hasEdgeSource` pointing to specified entity URI(s)
- Return `hasEdgeDestination` frame URIs
- Support pagination and filtering
- Include edge metadata (edge URI, creation date, etc.)

**Parameters**:
- `entity_uri`: Single entity URI
- `entity_uri_list`: Comma-separated entity URIs  
- `frame_type_uri`: Filter frames by type
- `page_size`, `offset`: Pagination

### 2. KGFrames/KGSlots Endpoint (REQUIRED)
**Endpoint**: `GET /api/graphs/kgframes/kgslots`

**Implementation Requirements**:
- Query edges where `vitaltype = "Edge_hasKGSlot"`
- Filter by `hasEdgeSource` pointing to specified frame URI(s)
- Return `hasEdgeDestination` slot URIs
- Support slot ordering by `slotSequence`
- Include slot metadata and value types

**Parameters**:
- `frame_uri`: Single frame URI
- `frame_uri_list`: Comma-separated frame URIs
- `slot_type_uri`: Filter slots by type
- `slot_value_type`: Filter by slot value type
- `page_size`, `offset`: Pagination

### 3. KGSlots/KGEntities Endpoint (REQUIRED)
**Endpoint**: `GET /api/graphs/kgslots/kgentities`

**Implementation Requirements**:
- Query edges where `vitaltype = "Edge_hasKGEntity"`
- Filter by `hasEdgeSource` pointing to specified slot URI(s)
- Return `hasEdgeDestination` entity URIs
- Handle slots that point to literals vs entities
- Include entity metadata and types

**Parameters**:
- `slot_uri`: Single slot URI
- `slot_uri_list`: Comma-separated slot URIs
- `entity_type_uri`: Filter entities by type
- `page_size`, `offset`: Pagination

### 4. KGEntities/KGSlots Endpoint (REQUIRED) - **REVERSE LOOKUP**
**Endpoint**: `GET /api/graphs/kgentities/kgslots`

**Purpose**: Find all slots that have a `hasEntity` property pointing to a particular entity

**Specific Pattern**: `Slot --[hasEntity]--> Entity`

**Implementation Requirements**:
Find slots where the `hasEntity` property value equals the specified entity URI.

```sql
-- Find slots with hasEntity property pointing to entity
SELECT DISTINCT 
    s_term.term_text as slot_uri,
    slot_vt.term_text as slot_vitaltype,
    p_term.term_text as property_uri
FROM {space}_rdf_quad q
JOIN {space}_term s_term ON q.subject_uuid = s_term.term_uuid
JOIN {space}_term p_term ON q.predicate_uuid = p_term.term_uuid  
JOIN {space}_term o_term ON q.object_uuid = o_term.term_uuid
JOIN {space}_rdf_quad slot_type_q ON s_term.term_uuid = slot_type_q.subject_uuid
JOIN {space}_term slot_vt_pred ON slot_type_q.predicate_uuid = slot_vt_pred.term_uuid
JOIN {space}_term slot_vt ON slot_type_q.object_uuid = slot_vt.term_uuid
WHERE o_term.term_text = %s  -- Entity URI
  AND p_term.term_text = 'http://vital.ai/ontology/haley-ai-kg#hasEntity'  -- hasEntity property
  AND slot_vt_pred.term_text = 'http://vital.ai/ontology/vital-core#vitaltype'
  AND slot_vt.term_text LIKE '%KGSlot%'  -- Ensure it's a slot
  AND q.context_uuid = %s
ORDER BY s_term.term_text
```

**Parameters**:
- `entity_uri`: Single entity URI to find slots for
- `entity_uri_list`: Comma-separated entity URIs
- `slot_type_uri`: Filter slots by specific slot type
- `page_size`, `offset`: Pagination

### 5. Edge Traversal Service Layer
**Required Implementation**: `EdgeTraversalService`

```python
class EdgeTraversalService:
    async def get_frames_for_entities(
        self, 
        space_id: str, 
        entity_uris: List[str], 
        graph_id: Optional[str] = None,
        filters: Optional[FrameFilter] = None
    ) -> List[Dict]:
        """Get frames linked to entities via Edge_hasKGFrame"""
        
    async def get_slots_for_frames(
        self,
        space_id: str,
        frame_uris: List[str], 
        graph_id: Optional[str] = None,
        filters: Optional[SlotFilter] = None
    ) -> List[Dict]:
        """Get slots linked to frames via Edge_hasKGSlot"""
        
    async def get_entities_for_slots(
        self,
        space_id: str,
        slot_uris: List[str],
        graph_id: Optional[str] = None,
        filters: Optional[EntityFilter] = None  
    ) -> List[Dict]:
        """Get entities linked to slots via Edge_hasKGEntity"""
        
    async def get_slots_for_entities_reverse(
        self,
        space_id: str,
        entity_uris: List[str],
        graph_id: Optional[str] = None,
        filters: Optional[SlotFilter] = None
    ) -> List[Dict]:
        """Get slots that have hasEntity property pointing to specified entities
        
        Pattern: Slot --[hasEntity]--> Entity
        
        This finds slots where:
        - Subject: KGSlot URI
        - Predicate: http://vital.ai/ontology/haley-ai-kg#hasEntity
        - Object: Entity URI
        """
```

### 5. Multi-Hop Traversal (FUTURE)
**Advanced Endpoints**:
- `GET /api/graphs/kgentities/{uri}/traverse` - Multi-hop entity traversal
- `GET /api/graphs/kgframes/{uri}/traverse` - Multi-hop frame traversal  
- Support traversal depth limits and path filtering

### CRUD Operations (Planned)
1. **CREATE Operations**: Add new objects to the graph
2. **UPDATE Operations**: Modify existing object properties  
3. **DELETE Operations**: Remove objects and their triples
4. **Edge Management**: Create/update/delete relationship edges

---

**Status**: ✅ **Objects, KGEntities, and KGFrames endpoints PRODUCTION READY**
**Next Phase**: 🔧 **CRITICAL - Relationship Traversal Endpoints Required**

### Immediate Implementation Requirements:
1. **🔧 KGEntities/KGFrames Endpoint** - Entity → Frame navigation via Edge_hasKGFrame
2. **🔧 KGFrames/KGSlots Endpoint** - Frame → Slot navigation via Edge_hasKGSlot  
3. **🔧 KGSlots/KGEntities Endpoint** - Slot → Entity navigation via Edge_hasKGEntity
4. **🔧 KGEntities/KGSlots Endpoint** - **REVERSE LOOKUP** - Find slots with `hasEntity` property
   - **Pattern**: `Slot --[hasEntity]--> Entity`
   - **Query**: Find slots where `hasEntity` property value equals the entity URI
5. **🔧 EdgeTraversalService** - Service layer for dual-mode traversal (property + edge)
6. **🔧 KGSlot Endpoints** - Complete the KGSlot CRUD operations

**Last Updated**: 2024-09-29
**Priority**: High - Relationship traversal is essential for knowledge graph navigation

## KGTypes Endpoint Implementation

### ✅ KGTypes Endpoint - FULLY IMPLEMENTED
**Status: Complete CRUD operations working**

KGType represents type definitions that can be assigned to KG objects like KGEntity instances.

#### KGType Data Model:
Based on analysis of `ai_haley_kg_domain.model.KGType.pyi`:

**Core Properties**:
- **Class URI**: `http://vital.ai/ontology/haley-ai-kg#KGType`
- **Base Class**: `VITAL_Node`
- **Key Properties**:
  - `kGModelVersion`: Version of the model
  - `kGTypeVersion`: Version of the type definition  
  - `kGraphDescription`: Description of the type

**Property Naming Convention**:
- .pyi files show contracted forms (e.g., `kGModelVersion`)
- Full property URIs follow pattern: `http://vital.ai/ontology/haley-ai-kg#kGModelVersion`
- "has" and "is" prefixes removed, capital letters lowercased (hasName → name)

#### Use Case:
KGTypes define semantic types that can be assigned to KGEntity instances:
```
KGType: "Person" → assigned to → KGEntity: "John Doe"
KGType: "Organization" → assigned to → KGEntity: "ACME Corp"
```

#### Current Implementation Status:
- **✅ Endpoint Structure**: `/api/graphs/kgtypes` endpoints exist
- **✅ Service Layer**: `KGTypeService` implemented with VitalSigns integration
- **✅ Subclass Support**: Includes all ~30 KGType subclasses (KGEntityType, KGFrameType, etc.)
- **✅ List/Get Operations**: Working with real database queries for all KGType subclasses
- **✅ Search/Filter**: Text search and pagination implemented
- **✅ URI Lookup**: Single and multiple URI retrieval working
- **✅ CRUD Operations**: Create/Update/Delete fully implemented using ObjectService
- **✅ Type Validation**: Validates vitaltypes belong to KGType hierarchy
- **✅ JSON-LD Processing**: Full JSON-LD document processing for all operations
- **❌ Type Assignment**: No mechanism to assign types to entities yet

#### Completed Implementation:
1. **✅ KGTypeService**: Service layer extending ObjectService pattern
2. **✅ ObjectService CRUD**: Complete CRUD operations implemented
3. **✅ Subclass Resolution**: VitalSigns ontology manager integration for ~30 subclasses
4. **✅ Type Validation**: Validates vitaltypes for create/update/delete operations
5. **✅ List/Get Operations**: Read operations with VitalSigns subclass resolution
6. **✅ Create Operations**: JSON-LD document processing and object creation with validation
7. **✅ Update Operations**: JSON-LD document processing and object updates with validation
8. **✅ Delete Operations**: URI-based and document-based deletion with type verification
9. **✅ Search/Filter**: Text search, pagination, URI-based lookup
10. **✅ JSON-LD Format**: Proper JSON-LD response formatting
11. **✅ Test Script**: Comprehensive test coverage with KGType subclasses
12. **✅ Property Extraction**: Extract and handle KGType-specific properties

#### Remaining Implementation:
1. **❌ Type Assignment**: Link KGTypes to KGEntity instances  
2. **❌ Advanced Validation**: Ensure type definitions are valid and consistent
3. **❌ Type Hierarchy**: Support for type inheritance and subtype relationships
4. **❌ Batch Operations**: High-performance batch operations for multiple objects

## Batch Operations Implementation Plan

### ✅ **Batch Operations - IMPLEMENTATION REQUIRED**
**Status: Critical for performance and transactional integrity**

Batch operations are essential for handling multiple objects efficiently while maintaining database consistency through transactions.

#### **Core Batch Operations**

##### **1. Batch Get Operations**
```python
async def get_objects_batch(
    space_id: str,
    object_uris: List[str],
    graph_id: Optional[str] = None
) -> Dict[str, ObjectInfo]:
    """Get multiple objects by URIs in a single database operation."""
```

**Features**:
- Single SQL query with `WHERE uri IN (...)` clause
- Returns dictionary mapping URI → ObjectInfo
- Missing objects return None in result dict
- Efficient for existence checking and bulk retrieval

##### **2. Batch Verify Operations**
```python
async def verify_objects_batch(
    space_id: str,
    object_uris: List[str],
    graph_id: Optional[str] = None
) -> Dict[str, bool]:
    """Verify which objects exist without retrieving full data."""
```

**Use Cases**:
- Pre-update existence checking
- Upsert operation planning (insert vs update)
- Bulk validation before complex operations
- Returns URI → exists mapping

##### **3. Batch Insert Operations**
```python
async def insert_objects_batch(
    space_id: str,
    objects_data: List[Dict[str, Any]],
    graph_id: Optional[str] = None
) -> List[str]:
    """Insert multiple objects as RDF triples in single transaction."""
```

**Implementation**:
- Converts objects to RDF triples
- Batch inserts all triples in single transaction
- Validates all vitaltypes before insertion
- Returns list of created URIs
- Atomic operation (all succeed or all fail)

##### **4. Batch Update Operations**
```python
async def update_objects_batch(
    space_id: str,
    objects_data: List[Dict[str, Any]],
    graph_id: Optional[str] = None
) -> List[str]:
    """Update multiple objects using delete+insert pattern."""
```

**Implementation**:
- Phase 1: Verify all objects exist
- Phase 2: Delete all existing triples for objects
- Phase 3: Insert new triples for all objects
- Wrapped in database transaction
- Validates vitaltypes for all objects

##### **5. Batch Delete Operations**
```python
async def delete_objects_batch(
    space_id: str,
    object_uris: List[str],
    graph_id: Optional[str] = None
) -> int:
    """Delete multiple objects in single transaction."""
```

**Implementation**:
- Verify objects exist and have correct vitaltypes
- Delete all triples for specified objects
- Single transaction for atomicity
- Returns count of successfully deleted objects

##### **6. Batch Upsert Operations**
```python
async def upsert_objects_batch(
    space_id: str,
    objects_data: List[Dict[str, Any]],
    graph_id: Optional[str] = None
) -> Dict[str, str]:
    """Insert or update objects based on existence."""
```

**Implementation**:
- Phase 1: Verify which objects exist
- Phase 2: Delete existing objects
- Phase 3: Insert all objects (new + updated)
- Returns mapping of URI → operation ("created" or "updated")

#### **Transaction Management**

##### **Database Transaction Wrapper**
```python
async def execute_batch_transaction(
    space_id: str,
    operations: List[Callable],
    graph_id: Optional[str] = None
) -> Any:
    """Execute multiple operations in single database transaction."""
```

**Features**:
- Automatic rollback on any operation failure
- Consistent state across all operations
- Proper error handling and logging
- Support for nested operations

#### **Performance Optimizations**

##### **1. SQL Query Optimization**
- **Batch Term Resolution**: Resolve all URIs to UUIDs in single query
- **Bulk Inserts**: Use PostgreSQL `COPY` or bulk `INSERT` statements
- **Prepared Statements**: Cache prepared statements for repeated operations
- **Connection Pooling**: Reuse connections across batch operations

##### **2. Memory Management**
- **Streaming Processing**: Process large batches in chunks
- **Lazy Loading**: Load object data only when needed
- **Result Pagination**: Support pagination for large result sets
- **Memory Limits**: Configurable batch size limits

##### **3. Parallel Processing**
- **Concurrent Validation**: Validate vitaltypes in parallel
- **Async Operations**: Non-blocking database operations
- **Worker Pools**: Dedicated workers for batch processing

#### **Error Handling and Recovery**

##### **Partial Failure Handling**
```python
class BatchOperationResult:
    successful: List[str]
    failed: List[Tuple[str, Exception]]
    total_count: int
    success_count: int
    failure_count: int
```

**Features**:
- Detailed success/failure reporting
- Individual object error tracking
- Configurable failure tolerance
- Retry mechanisms for transient failures

##### **Validation Pipeline**
1. **Schema Validation**: Validate object structure
2. **VitalType Validation**: Ensure correct vitaltypes
3. **URI Validation**: Check URI format and uniqueness
4. **Property Validation**: Validate property values
5. **Relationship Validation**: Check referential integrity

#### **Service Layer Integration**

**Implementation Location**: 
- Batch operations will be implemented in the service layer (ObjectService, KGTypeService, etc.)
- Existing REST endpoints will be enhanced to handle multiple objects when arrays are provided
- No additional endpoints needed - existing endpoints support both single and batch operations

**Enhanced Request Handling**:
- Existing endpoints detect array vs single object in request body
- Automatically route to batch operations for arrays
- Maintain backward compatibility with single object operations

#### **Monitoring and Metrics**

##### **Performance Metrics**
- Batch operation duration
- Objects processed per second
- Transaction success/failure rates
- Memory usage during batch operations
- Database connection utilization

##### **Logging and Debugging**
- Detailed operation logs
- Performance timing logs
- Error tracking and reporting
- Transaction state logging

#### **Use Cases**

##### **1. Bulk Data Import**
- Import large datasets efficiently
- Maintain referential integrity
- Handle import failures gracefully

##### **2. Synchronization Operations**
- Sync data between systems
- Identify differences efficiently
- Apply changes atomically

##### **3. Batch Updates**
- Update multiple related objects
- Ensure consistency across updates
- Rollback on any failure

##### **4. Data Migration**
- Migrate data between graphs
- Transform object structures
- Validate migration success

#### API Endpoints (Existing Structure):
- `GET /api/graphs/kgtypes` - List/search KGTypes with pagination
- `POST /api/graphs/kgtypes` - Create new KGTypes
- `PUT /api/graphs/kgtypes` - Update existing KGTypes  
- `DELETE /api/graphs/kgtypes` - Delete KGTypes

#### Integration with KGEntities:
KGEntity objects should have a property to reference their assigned KGType:
- Property: `kGEntityType` or similar
- Value: URI of the assigned KGType
- Enables type-based filtering and semantic queries