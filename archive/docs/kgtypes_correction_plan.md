# KGTypes Implementation Correction Plan

## Problem Analysis

The current KGTypes endpoint and service implementations are incorrectly designed and do not follow the established VitalGraph patterns. The main issues are:

### Current Issues

1. **Incorrect Data Flow**: The current implementation uses SPARQL INSERT/UPDATE operations instead of the proper `add_rdf_quads_batch()` pattern
2. **Missing GraphObject Validation**: No proper VitalSigns GraphObject conversion and validation
3. **No Transaction Management**: Missing proper transaction handling for atomic operations
4. **Inconsistent Architecture**: Does not follow the triples endpoint pattern which is the correct implementation
5. **Missing Subject URI Conflict Detection**: No checking for existing objects during create operations
6. **Poor Error Handling**: Incomplete error handling and rollback mechanisms

### Correct Pattern (from triples_endpoint.py)

The triples endpoint follows the correct pattern:
1. **JSON-LD to RDF**: Convert JSON-LD document to RDF triples using RDFLib
2. **Triples to Quads**: Add graph context to create quads
3. **Batch Insert**: Use `add_rdf_quads_batch()` with proper transaction management
4. **Validation**: Proper space/graph validation and error handling

## Correction Strategy

### Phase 0: Cleanup - Remove Incorrect SPARQL Implementations

#### 0.1 KGTypeService Cleanup

**File**: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph/service/kgtype_service.py`

**Functions to Remove (SPARQL-based implementations):**
- `create_kgtype()` - Currently uses SPARQL INSERT DATA
- `update_kgtype()` - Currently uses SPARQL DELETE/INSERT
- `delete_kgtype()` - Currently uses SPARQL DELETE
- `delete_kgtypes()` - Currently uses SPARQL DELETE

**Functions to Keep/Update:**
- `__init__()` - Keep VitalSigns initialization
- `_init_vitalsigns()` - Keep ontology manager setup
- `get_kgtype_vitaltypes()` - Keep vitaltype enumeration
- `validate_kgtype_vitaltype()` - Keep validation logic
- `list_kgtypes()` - Keep (delegates to object_service)
- `get_kgtype_by_uri()` - Keep (delegates to object_service)
- `get_kgtypes_by_uris()` - Keep (delegates to object_service)

#### 0.2 KGTypesEndpoint Cleanup

**File**: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph/endpoint/kgtypes_endpoint.py`

**Functions to Remove (incorrect implementations):**
- `_create_kgtypes()` - Currently uses service.create_kgtype()
- `_update_kgtypes()` - Currently uses service.update_kgtype()
- `_delete_kgtypes()` - Currently uses service.delete_kgtype(s)()

**Functions to Keep:**
- `__init__()` - Keep router setup
- `_setup_routes()` - Keep route definitions
- `_list_kgtypes()` - Keep (works correctly via object_service)
- `_get_kgtype_by_uri()` - Keep (works correctly via object_service)
- `_get_kgtypes_by_uris()` - Keep (works correctly via object_service)
- All response models and helper classes

#### 0.3 ObjectService Cleanup

**File**: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph/service/object_service.py`

**Functions to Remove (SPARQL-based implementations):**
- `create_object()` - Currently uses SPARQL INSERT DATA
- `update_object()` - Currently uses SPARQL DELETE/INSERT  
- `delete_object()` - Currently uses SPARQL DELETE
- `delete_objects()` - Currently uses SPARQL DELETE

**Functions to Keep:**
- `__init__()` - Keep VitalSigns registry setup
- `list_objects()` - Keep (uses direct SQL, works correctly)
- `get_object_by_uri()` - Keep (uses direct SQL, works correctly)
- `get_objects_by_uris()` - Keep (uses direct SQL, works correctly)
- `validate_vitaltype()` - Keep validation logic
- All helper methods for SQL query building

#### 0.4 Cleanup Steps

1. **Comment out broken methods** with clear markers:
   ```python
   # TODO: Implement using add_rdf_quads_batch() pattern - see kgtypes_correction_plan.md
   # async def create_kgtype(self, ...):
   #     pass
   ```

2. **Update method signatures** to raise NotImplementedError:
   ```python
   async def create_kgtype(self, space_id: str, kgtype_data: Dict[str, Any], graph_id: Optional[str] = None) -> str:
       raise NotImplementedError("KGType create operations temporarily disabled during refactoring")
   ```

3. **Update endpoint error handling** to return proper HTTP responses:
   ```python
   try:
       result = await self.kgtype_service.create_kgtype(...)
   except NotImplementedError as e:
       raise HTTPException(status_code=501, detail=str(e))
   ```

4. **Keep working read operations** so the API remains partially functional during refactoring

#### 0.5 Create Database Objects Layer

**File**: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph/db/postgresql/space/postgresql_space_db_objects.py`

**Purpose**: Implement optimized database operations for object retrieval and management that complement the existing `db_ops` layer.

**Architecture Pattern**: Follow the same pattern as other space components:
```python
# In PostgreSQLSpaceImpl.__init__()
# Initialize database objects class  
self.db_objects = PostgreSQLSpaceDBObjects(self)
```

**Database Operations to Implement:**

1. **Bulk Object Retrieval:**
   ```python
   async def get_objects_by_uris_batch(self, space_id: str, subject_uris: List[str], graph_id: Optional[str] = None) -> List[Tuple]:
       """Get all quads for multiple objects by their URIs using optimized SQL."""
   
   async def get_object_quads_by_uri(self, space_id: str, subject_uri: str, graph_id: Optional[str] = None) -> List[Tuple]:
       """Get all quads for a single object by URI."""
   ```

2. **Object Existence Checks:**
   ```python
   async def check_objects_exist(self, space_id: str, subject_uris: List[str]) -> Dict[str, bool]:
       """Check which objects exist in the database (for conflict detection)."""
   
   async def get_existing_object_uris(self, space_id: str, subject_uris: List[str]) -> List[str]:
       """Return list of URIs that already exist in the database."""
   ```

3. **Object Metadata Operations:**
   ```python
   async def get_object_vitaltypes(self, space_id: str, subject_uris: List[str]) -> Dict[str, str]:
       """Get vitaltype for each object URI."""
   
   async def count_objects_by_vitaltype(self, space_id: str, vitaltype_uri: str, graph_id: Optional[str] = None) -> int:
       """Count objects of a specific vitaltype."""
   ```

**SQL Optimization Guidelines:**
- Use JOIN operations for efficient multi-table queries
- Leverage existing indexes on subject_uuid, predicate_uuid, graph_uuid
- Use batch operations with `WHERE subject_uuid IN (...)` patterns
- Follow patterns from SPARQL package for complex queries
- Use prepared statements for repeated operations

**Integration with Service Layer:**
- Service utilities call `db_objects` methods instead of writing SQL
- All database access goes through `db_ops` (write operations) or `db_objects` (read operations)
- No SQL code in service_utils.py or any service classes

**Example Usage in Service Utilities:**
```python
# In service_utils.py
async def check_subject_uri_conflicts(space_manager, space_id: str, subject_uris: List[str]) -> List[str]:
    """Check for existing objects with same subject URIs using db_objects layer."""
    
    # Get space implementation
    space_record = space_manager.get_space(space_id)
    space_impl = space_record.space_impl
    db_space_impl = space_impl.get_db_space_impl()
    
    # Use db_objects layer for optimized conflict detection
    existing_uris = await db_space_impl.db_objects.get_existing_object_uris(space_id, subject_uris)
    return existing_uris

async def get_existing_quads_for_uris(space_manager, space_id: str, graph_id: str, subject_uris: List[str]) -> List[Tuple]:
    """Get existing quads for update/delete operations using db_objects layer."""
    
    # Get space implementation
    space_record = space_manager.get_space(space_id)
    space_impl = space_record.space_impl
    db_space_impl = space_impl.get_db_space_impl()
    
    # Use db_objects layer for optimized quad retrieval
    quads = await db_space_impl.db_objects.get_objects_by_uris_batch(space_id, subject_uris, graph_id)
    return quads
```

#### 0.6 Create Reusable Service Utilities

**File**: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph/service/service_utils.py`

**Purpose**: Create reusable utility functions that can be shared across KGType, KGEntity, KGFrame, and general object services.

**Utility Functions to Create:**

1. **JSON-LD Processing Utilities:**
   ```python
   async def jsonld_to_graphobjects(jsonld_document: Dict, vitaltype_validator: Callable = None) -> List[Any]:
       """Convert JSON-LD document to VitalSigns GraphObjects with optional vitaltype validation."""
   
   async def graphobjects_to_quads(graph_objects: List[Any], graph_id: str) -> List[Tuple]:
       """Convert VitalSigns GraphObjects back to RDF quads for database insertion."""
   
   def validate_jsonld_document(document: Dict) -> None:
       """Validate JSON-LD document structure and required fields."""
   ```

2. **Transaction Management Utilities:**
   ```python
   async def execute_with_transaction(space_manager, space_id: str, operation_func, *args, **kwargs):
       """Execute operations within a transaction with proper error handling."""
   
   async def get_db_space_impl(space_manager, space_id: str):
       """Get database space implementation for transaction operations."""
   ```

3. **Conflict Detection Utilities:**
   ```python
   async def check_subject_uri_conflicts(space_manager, space_id: str, subject_uris: List[str]) -> List[str]:
       """Check for existing objects with same subject URIs using db_objects layer."""
   
   async def get_existing_quads_for_uris(space_manager, space_id: str, graph_id: str, subject_uris: List[str]) -> List[Tuple]:
       """Get existing quads for update/delete operations using db_objects layer."""
   ```

4. **Validation Utilities:**
   ```python
   def validate_uri_format(uri: str) -> None:
       """Validate URI format (http:// or urn: prefix)."""
   
   def validate_required_fields(obj_data: Dict, required_fields: List[str]) -> None:
       """Validate that required fields are present in object data."""
   
   def extract_subject_uris(jsonld_objects: List[Dict]) -> List[str]:
       """Extract subject URIs from JSON-LD objects."""
   ```

5. **Error Handling Utilities:**
   ```python
   class ServiceValidationError(Exception):
       """Base class for service validation errors."""
       pass
   
   class ServiceConflictError(Exception):
       """Raised when resource conflicts occur."""
       pass
   
   def handle_service_exceptions(func):
       """Decorator for consistent service exception handling."""
   ```

**Benefits for Multiple Services:**
- **KGType Service**: Uses vitaltype validation for KGType and subclasses
- **KGEntity Service**: Uses vitaltype validation for KGEntity and subclasses  
- **KGFrame Service**: Uses vitaltype validation for KGFrame and subclasses
- **General Object Service**: Uses generic validation without vitaltype restrictions
- **Consistent Patterns**: All services follow the same JSON-LD → GraphObjects → Quads pipeline
- **Shared Error Handling**: Consistent error types and HTTP status codes across all services

### Phase 1: Fix KGTypeService Architecture

#### 1.1 Update KGTypeService Methods

**File**: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph/service/kgtype_service.py`

**Changes Required**:

1. **Remove SPARQL-based operations** - Replace all SPARQL INSERT/UPDATE calls
2. **Add GraphObject conversion pipeline**:
   ```python
   async def _jsonld_to_graphobjects(self, jsonld_objects: List[Dict]) -> List[Any]:
       """Convert JSON-LD objects to VitalSigns GraphObjects with validation."""
   
   async def _graphobjects_to_quads(self, graph_objects: List[Any], graph_id: str) -> List[Tuple]:
       """Convert GraphObjects to RDF quads for database insertion."""
   
   async def _check_subject_conflicts(self, space_id: str, subject_uris: List[str]) -> List[str]:
       """Check for existing objects with same subject URIs."""
   ```

3. **Update create_kgtype() method**:
   ```python
   async def create_kgtype(self, space_id: str, kgtype_data: Dict[str, Any], graph_id: Optional[str] = None) -> str:
       # 1. Convert to GraphObject for validation
       # 2. Check for subject URI conflicts
       # 3. Convert to quads
       # 4. Use transaction + add_rdf_quads_batch()
   ```

4. **Update update_kgtype() method**:
   ```python
   async def update_kgtype(self, space_id: str, kgtype_uri: str, kgtype_data: Dict[str, Any], graph_id: Optional[str] = None) -> bool:
       # 1. Check object exists
       # 2. Convert to GraphObject for validation  
       # 3. Delete existing quads in transaction
       # 4. Insert new quads in same transaction
   ```

5. **Update delete operations** to use `remove_rdf_quads_batch()`

#### 1.2 Add Transaction Management

**New Methods**:
```python
async def _execute_with_transaction(self, space_id: str, operation_func, *args, **kwargs):
    """Execute operations within a transaction with proper error handling."""
    
async def _get_db_space_impl(self, space_id: str):
    """Get database space implementation for transaction operations."""
```

### Phase 2: Fix KGTypesEndpoint Architecture

#### 2.1 Update KGTypesEndpoint Methods

**File**: `/Users/hadfield/Local/vital-git/vital-graph/vitalgraph/endpoint/kgtypes_endpoint.py`

**Changes Required**:

1. **Follow triples_endpoint pattern** for all CRUD operations
2. **Add proper JSON-LD to quads conversion**:
   ```python
   async def _jsonld_to_quads(self, document: JsonLdDocument, graph_id: str) -> List[Tuple]:
       """Convert JSON-LD document to RDF quads (same as triples endpoint)."""
   ```

3. **Update _create_kgtypes() method**:
   ```python
   async def _create_kgtypes(self, space_id: str, graph_id: str, document: JsonLdDocument, current_user: Dict) -> KGTypeOperationResponse:
       try:
           # 1. Validate space exists (same as triples endpoint)
           # 2. Get db_space_impl (same as triples endpoint)
           # 3. Convert JSON-LD to GraphObjects for validation
           graph_objects = await self.kgtype_service._jsonld_to_graphobjects(document.dict())
           # 4. Check for subject URI conflicts
           # 5. Convert to quads
           # 6. Use add_rdf_quads_batch() with transaction
       except KGTypeValidationError as e:
           raise HTTPException(status_code=400, detail=f"Validation error: {str(e)}")
       except KGTypeConflictError as e:
           raise HTTPException(status_code=409, detail=f"Conflict error: {str(e)}")
   ```

4. **Update _update_kgtypes() method**:
   ```python
   async def _update_kgtypes(self, space_id: str, graph_id: str, document: JsonLdDocument, current_user: Dict) -> KGTypeOperationResponse:
       # 1. Validate space exists
       # 2. Get db_space_impl  
       # 3. Convert JSON-LD to GraphObjects
       # 4. For each object:
       #    a. Get existing quads
       #    b. Delete existing + insert new in transaction
   ```

5. **Update _delete_kgtypes() method**:
   ```python
   async def _delete_kgtypes(self, space_id: str, graph_id: str, uri: Optional[str], uri_list: Optional[str], document: Optional[JsonLdDocument], current_user: Dict) -> KGTypeOperationResponse:
       # 1. Validate space exists
       # 2. Get db_space_impl
       # 3. Get quads for deletion
       # 4. Use remove_rdf_quads_batch() with transaction
   ```

#### 2.2 Add GraphObject Integration

**New Methods**:
```python
async def _validate_kgtypes_as_graphobjects(self, jsonld_objects: List[Dict]) -> List[Any]:
    """Convert JSON-LD to GraphObjects and validate vitaltype."""

async def _check_create_conflicts(self, space_id: str, graph_objects: List[Any]) -> None:
    """Check for subject URI conflicts during create operations."""

async def _get_existing_quads_for_objects(self, space_id: str, graph_id: str, subject_uris: List[str]) -> List[Tuple]:
    """Get existing quads for update/delete operations."""
```

### Phase 3: Implementation Details

#### 3.1 GraphObject Conversion Pipeline

```python
# In KGTypeService
async def _jsonld_to_graphobjects(self, jsonld_document: Dict) -> List[Any]:
    """Convert JSON-LD document to VitalSigns GraphObjects using proper JSON-LD processing."""
    from pyld import jsonld
    from rdflib import Graph
    import json
    
    try:
        # Step 1: Use JSON-LD library to convert to RDF triples
        # This handles all JSON-LD complexities (context expansion, etc.)
        expanded = jsonld.expand(jsonld_document)
        ntriples = jsonld.to_rdf(jsonld_document, {'format': 'application/n-triples'})
        
        # Step 2: Parse triples using RDFLib
        g = Graph()
        g.parse(data=ntriples, format='nt')
        
        # Step 3: Extract triples as list for VitalSigns
        triples_list = [(s, p, o) for s, p, o in g]
        
        # Step 4: Convert triples to VitalSigns GraphObjects
        try:
            graph_objects = VitalSigns.from_triples_list(triples_list)
        except Exception as e:
            raise KGTypeValidationError(f"Failed to parse triples into valid GraphObjects: {e}")
        
        # Step 5: Validate that all objects are KGTypes or subclasses
        validated_objects = []
        for obj in graph_objects:
            try:
                if not hasattr(obj, 'vitaltype'):
                    raise KGTypeValidationError(f"Object {obj.URI} missing vitaltype property")
                
                if not self.validate_kgtype_vitaltype(obj.vitaltype):
                    raise KGTypeValidationError(f"Invalid KGType vitaltype '{obj.vitaltype}' for object {obj.URI}")
                
                validated_objects.append(obj)
                
            except AttributeError as e:
                raise KGTypeValidationError(f"Invalid GraphObject structure: {e}")
        
        return validated_objects
        
    except KGTypeValidationError:
        # Re-raise validation errors as-is
        raise
    except Exception as e:
        raise KGTypeValidationError(f"Failed to process JSON-LD document: {e}")

async def _graphobjects_to_quads(self, graph_objects: List[Any], graph_id: str) -> List[Tuple]:
    """Convert VitalSigns GraphObjects back to RDF quads for database insertion."""
    from rdflib import Graph, URIRef
    
    try:
        # Step 1: Convert GraphObjects back to triples using VitalSigns
        all_triples = []
        for obj in graph_objects:
            # Use VitalSigns to_rdf() method to get proper RDF representation
            obj_triples = obj.to_rdf()
            all_triples.extend(obj_triples)
        
        # Step 2: Create RDFLib graph and add triples
        g = Graph()
        for s, p, o in all_triples:
            g.add((s, p, o))
        
        # Step 3: Convert triples to quads with graph context
        graph_uri = URIRef(graph_id)
        quads = []
        for s, p, o in g:
            quads.append((s, p, o, graph_uri))
        
        return quads
        
    except Exception as e:
        raise ValueError(f"Failed to convert GraphObjects to quads: {e}")
```

#### 3.2 Transaction-based Operations

```python
# In KGTypeService (using shared service_utils)
from .service_utils import (
    jsonld_to_graphobjects, graphobjects_to_quads, execute_with_transaction,
    check_subject_uri_conflicts, ServiceValidationError, ServiceConflictError
)

async def create_kgtype(self, space_id: str, kgtype_data: Dict[str, Any], graph_id: Optional[str] = None) -> str:
    """Create a new KGType with proper validation and transaction management."""
    
    try:
        # Step 1: Convert JSON-LD to GraphObjects using shared utility
        # Wrap single object in JSON-LD document format
        jsonld_doc = {
            "@context": {
                "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
                "vital": "http://vital.ai/ontology/vital-core#",
                "haley": "http://vital.ai/ontology/haley-ai-kg#"
            },
            "@graph": [kgtype_data]
        }
        
        # Use shared utility with KGType-specific validator
        graph_objects = await jsonld_to_graphobjects(
            jsonld_doc, 
            vitaltype_validator=self.validate_kgtype_vitaltype
        )
        graph_object = graph_objects[0]
        
        # Step 2: Check for conflicts using shared utility
        subject_uri = str(graph_object.URI)
        conflicts = await check_subject_uri_conflicts(
            self.space_manager, space_id, [subject_uri]
        )
        if conflicts:
            raise ServiceConflictError(f"Object with URI {subject_uri} already exists")
        
        # Step 3: Convert GraphObjects back to quads using shared utility
        quads = await graphobjects_to_quads(graph_objects, graph_id)
        
        # Step 4: Execute with transaction using shared utility
        async def create_operation(transaction):
            db_space_impl = await get_db_space_impl(self.space_manager, space_id)
            added_count = await db_space_impl.add_rdf_quads_batch(space_id, quads, transaction=transaction)
            if added_count != len(quads):
                raise RuntimeError(f"Expected to add {len(quads)} quads, but added {added_count}")
            return subject_uri
        
        return await execute_with_transaction(
            self.space_manager, space_id, create_operation
        )
        
    except ServiceValidationError:
        raise  # Re-raise validation errors
    except ServiceConflictError:
        raise  # Re-raise conflict errors
    except Exception as e:
        raise ServiceValidationError(f"Failed to create KGType: {e}")
```

#### 3.3 Conflict Detection

```python
# In KGTypeService
async def _check_subject_conflicts(self, space_id: str, subject_uris: List[str]) -> List[str]:
    """Check for existing objects with same subject URIs."""
    
    db_space_impl = await self._get_db_space_impl(space_id)
    conflicts = []
    
    for subject_uri in subject_uris:
        # Check if object exists by querying for any triples with this subject
        existing_obj = await self.object_service.get_object_by_uri(space_id, subject_uri)
        if existing_obj:
            conflicts.append(subject_uri)
    
    return conflicts
```

### Phase 4: Error Handling and Validation

#### 4.1 Enhanced Error Handling

```python
# In both KGTypeService and KGTypesEndpoint
class KGTypeValidationError(Exception):
    """Raised when KGType validation fails."""
    pass

class KGTypeConflictError(Exception):
    """Raised when KGType URI conflicts with existing object."""
    pass

# Add proper exception handling in all methods with:
# - Transaction rollback on errors
# - Detailed error messages
# - Proper HTTP status codes in endpoint
```

#### 4.2 Validation Pipeline

```python
# In KGTypeService
async def _validate_kgtype_data(self, kgtype_data: Dict[str, Any]) -> None:
    """Comprehensive validation of KGType data."""
    
    # Check required fields
    if 'vitaltype' not in kgtype_data and '@type' not in kgtype_data:
        raise KGTypeValidationError("KGType must have vitaltype")
    
    # Validate vitaltype
    vitaltype = kgtype_data.get('vitaltype') or kgtype_data.get('@type')
    if not self.validate_kgtype_vitaltype(vitaltype):
        raise KGTypeValidationError(f"Invalid vitaltype: {vitaltype}")
    
    # Validate URI is provided and has correct format
    uri = kgtype_data.get('@id') or kgtype_data.get('URI')
    if not uri:
        raise KGTypeValidationError("KGType must have a URI (@id or URI field)")
    if not (uri.startswith('http://') or uri.startswith('urn:')):
        raise KGTypeValidationError(f"Invalid URI format: {uri}")
```

## Implementation Timeline

### Day 1-2: Phase 0 Cleanup
- [ ] Remove/disable SPARQL-based create/update/delete methods in KGTypeService
- [ ] Remove/disable SPARQL-based create/update/delete methods in ObjectService  
- [ ] Update endpoint methods to return 501 Not Implemented for write operations
- [ ] Keep all read operations (list, get) working
- [ ] Add clear TODO comments with references to this plan
- [ ] Create postgresql_space_db_objects.py following established architecture patterns
- [ ] Add db_objects initialization to PostgreSQLSpaceImpl.__init__()
- [ ] Create service_utils.py with reusable utility functions (no SQL code)
- [ ] Test that read operations still work correctly

### Week 1: KGTypeService Refactoring
- [ ] Import and use service_utils functions in KGTypeService
- [ ] Create KGType-specific vitaltype validator function
- [ ] Implement new create_kgtype() using service_utils.jsonld_to_graphobjects()
- [ ] Implement new update_kgtype() using service_utils.execute_with_transaction()
- [ ] Implement new delete operations using service_utils.get_existing_quads_for_uris()
- [ ] Add KGType-specific validation using service_utils.validate_uri_format()
- [ ] Update all methods to use shared ServiceValidationError and ServiceConflictError

### Week 2: KGTypesEndpoint Refactoring  
- [ ] Follow triples endpoint pattern for space/graph validation
- [ ] Update _create_kgtypes() to use new service methods
- [ ] Update _update_kgtypes() to use new service methods  
- [ ] Update _delete_kgtypes() to use new service methods
- [ ] Add proper JSON-LD validation and error handling
- [ ] Enhanced HTTP error responses (400, 409, 501)

### Week 3: Testing and Validation
- [ ] Unit tests for GraphObject conversion pipeline
- [ ] Integration tests for transaction handling
- [ ] End-to-end tests for all CRUD operations
- [ ] Performance testing with large datasets
- [ ] Error scenario testing (invalid JSON-LD, conflicts, etc.)
- [ ] Backward compatibility testing

### Week 4: Documentation and Deployment
- [ ] Update API documentation with new error responses
- [ ] Create migration guide for any breaking changes
- [ ] Performance optimization and monitoring
- [ ] Production deployment with rollback plan

## Success Criteria

1. **Architectural Consistency**: KGTypes follows same pattern as triples endpoint
2. **GraphObject Integration**: Proper VitalSigns GraphObject validation and conversion
3. **Transaction Safety**: All operations use proper transaction management
4. **Conflict Detection**: Create operations detect and prevent URI conflicts
5. **Performance**: Batch operations maintain high performance
6. **Error Handling**: Comprehensive error handling with proper rollback
7. **Test Coverage**: 100% test coverage for all new functionality

## Risk Mitigation

1. **Backward Compatibility**: Maintain existing API contracts during transition
2. **Data Integrity**: Use transactions to ensure no partial updates
3. **Performance Impact**: Batch operations to minimize database round trips
4. **Error Recovery**: Proper rollback mechanisms for all failure scenarios
5. **Testing**: Comprehensive test suite before production deployment

This plan ensures the KGTypes implementation follows the correct VitalGraph patterns while maintaining data integrity and performance.
