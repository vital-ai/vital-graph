# Objects Endpoint Implementation Plan
## Fuseki-PostgreSQL Hybrid Backend

### Overview
The Objects endpoint provides generic graph object management capabilities for the VitalGraph knowledge graph system. It handles CRUD operations for general graph objects that don't fall into specialized categories like entities, frames, types, or relations.

### Implementation Status
- **Current Status**: 🔄 Implementation pending (Phase K5)
- **Priority**: Medium
- **Dependencies**: Backend storage (completed), VitalSigns integration (completed)

## Architecture

### Object Data Model
```
GraphObject (Generic)
├── URI: unique object identifier
├── @type: object type classification
├── Properties: dynamic property set based on object type
├── Metadata: creation/modification timestamps
├── Graph Context: named graph assignment
└── Relationships: connections to other objects
```

### Object Categories
- **Generic VitalSigns Objects**: Any VitalSigns-compatible graph object
- **Custom Domain Objects**: Application-specific object types
- **Utility Objects**: System and metadata objects
- **Relationship Objects**: Objects representing connections between other objects

## API Endpoints

### Core Object Operations
1. **GET /objects** - List Objects
   - Query parameters: `space_id`, `graph_id`, `page_size`, `offset`, `object_type`
   - Returns: `ObjectsResponse` with JSON-LD document/object

2. **POST /objects** - Create/Update Objects
   - Request body: `JsonLdRequest` (discriminated union of JsonLdObject or JsonLdDocument)
   - Query parameters: `space_id`, `graph_id`
   - Returns: `ObjectCreateResponse` or `ObjectUpdateResponse`
   - **Discriminated Union**: Automatically handles single objects (JsonLdObject) or multiple objects (JsonLdDocument)

3. **DELETE /objects** - Delete Objects
   - Request body: `ObjectDeleteRequest` with list of object URIs
   - Returns: `ObjectDeleteResponse`

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
- Checks for `@graph` field → JsonLdDocument (multiple objects)
- Checks for `@id` field → JsonLdObject (single object)
- Explicit `jsonld_type` field can override detection

**Benefits**:
- FastAPI automatically routes to correct model based on content
- Single endpoint handles both single and batch object operations
- Type-safe validation for both formats
- Consistent with KGFrames, KGRelations, and KGTypes endpoints

## Implementation Requirements

### Core Object Management
- **Generic CRUD Operations**: Support for any VitalSigns-compatible object type
- **Type Validation**: Validate objects against their declared types
- **Property Management**: Dynamic property handling based on object schemas
- **Batch Operations**: Efficient batch create/update/delete operations

### JSON-LD Format Support
The Objects endpoint must support both single and multiple object operations:

#### Single Object Operations (JsonLdObject)
```json
{
  "@id": "http://example.com/object/123",
  "@type": "http://vital.ai/ontology/vital-core#VitalNode",
  "http://vital.ai/ontology/vital-core#hasName": "Example Object",
  "http://vital.ai/ontology/vital-core#hasDescription": "A sample object"
}
```

#### Multiple Object Operations (JsonLdDocument)
```json
{
  "@context": {...},
  "@graph": [
    {
      "@id": "http://example.com/object/123",
      "@type": "http://vital.ai/ontology/vital-core#VitalNode",
      "http://vital.ai/ontology/vital-core#hasName": "Object 1"
    },
    {
      "@id": "http://example.com/object/124", 
      "@type": "http://vital.ai/ontology/vital-core#VitalNode",
      "http://vital.ai/ontology/vital-core#hasName": "Object 2"
    }
  ]
}
```

### VitalSigns Integration
- **Native JSON-LD Handling**: Use VitalSigns `to_jsonld()` and `jsonld_to_graphobjects()`
- **Object Validation**: Leverage VitalSigns type validation
- **Property Mapping**: Automatic property mapping from VitalSigns schemas
- **Type Safety**: Ensure type safety through VitalSigns object model

## Backend Integration Requirements

### SPARQL Operations
- **INSERT DATA**: Object creation via SPARQL INSERT
- **DELETE DATA**: Object deletion via SPARQL DELETE
- **CONSTRUCT**: Object retrieval via SPARQL CONSTRUCT
- **SELECT**: Object querying and filtering

### Dual-Write Coordination
- **PostgreSQL Primary**: Authoritative object storage in PostgreSQL
- **Fuseki Index**: Query optimization through Fuseki RDF store
- **Consistency Validation**: Real-time consistency checks between backends
- **Transaction Support**: Atomic operations across both systems

### Object Processing Pipeline
```python
async def process_object_operation(operation_type, objects, metadata):
    # 1. Validate objects using VitalSigns
    validation_result = await validate_objects(objects)
    
    # 2. Convert to RDF quads
    quads = await objects_to_quads(objects)
    
    # 3. Execute dual-write operation
    pg_result = await postgresql_backend.execute_operation(operation_type, quads)
    fuseki_result = await fuseki_backend.execute_operation(operation_type, quads)
    
    # 4. Validate consistency
    await validate_dual_write_consistency(pg_result, fuseki_result)
    
    return operation_result
```

## Implementation Phases

### Phase 1: Core Object Operations (2-3 days)
- Implement basic object CRUD operations
- VitalSigns integration for object validation
- Single and batch object operations
- Basic object listing and retrieval

### Phase 2: Advanced Object Features (2-3 days)
- Object search and filtering capabilities
- Object type management and validation
- Object metadata operations
- Complex object querying

### Phase 3: Performance Optimization (1-2 days)
- Query optimization for large object sets
- Batch operation performance tuning
- Caching strategies for frequently accessed objects
- Index optimization for object properties

### Phase 4: Testing and Validation (1 day)
- Comprehensive test suite for all object operations
- VitalSigns integration testing
- Dual-write consistency validation
- Performance testing with large object sets

## Object Type Management

### Supported Object Types
- **VitalNode**: Base class for all graph objects
- **VitalEdge**: Relationship objects connecting other objects
- **Custom Types**: Application-specific object types
- **System Types**: Internal system and metadata objects

### Type Validation
- **Schema Validation**: Validate objects against VitalSigns schemas
- **Property Validation**: Ensure required properties are present
- **Type Hierarchy**: Support for object type inheritance
- **Custom Validation**: Extensible validation rules

### Object Metadata
- **Creation Metadata**: Timestamp, creator, source information
- **Modification Metadata**: Last modified timestamp, modifier
- **Version Information**: Object versioning and change tracking
- **Graph Context**: Named graph assignment and context

## Success Criteria
- All object operations implemented and tested
- VitalSigns integration working correctly
- Dual-write consistency maintained
- Performance optimized for large object sets
- 100% test coverage for object operations
- Production-ready generic object management capabilities

## Dependencies and Integration

### Required Dependencies
- ✅ **Backend Storage**: Dual Fuseki-PostgreSQL storage working correctly
- ✅ **VitalSigns Integration**: Native JSON-LD handling complete
- ✅ **SPARQL Parser**: Query generation and execution working
- ✅ **Transaction Management**: Atomic operations across backends

### Integration Points
- **Type System**: Integration with KGTypes endpoint for type definitions
- **Entity System**: Support for entity-related objects
- **File System**: Integration with Files endpoint for file objects
- **Query Engine**: Advanced SPARQL query generation and execution

## Configuration Requirements

### Object Processing Configuration
```python
OBJECTS_CONFIG = {
    'max_batch_size': 1000,
    'validation_enabled': True,
    'type_checking_strict': True,
    'metadata_tracking': True,
    'versioning_enabled': False,
    'cache_frequently_accessed': True,
    'supported_formats': ['json-ld', 'turtle', 'rdf-xml']
}
```

### Performance Configuration
- **Batch Size Limits**: Configurable limits for batch operations
- **Query Timeouts**: Timeout settings for complex queries
- **Cache Settings**: Object caching configuration
- **Index Settings**: Database index configuration for object properties

## Notes
- Objects endpoint provides the foundation for generic graph object management
- VitalSigns integration ensures type safety and validation
- Dual-write architecture ensures both performance and reliability
- Generic design allows support for any VitalSigns-compatible object type
- Performance optimization critical for large-scale object operations
- Integration with specialized endpoints enables comprehensive graph management
