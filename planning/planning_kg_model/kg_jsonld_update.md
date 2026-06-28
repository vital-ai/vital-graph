# JSON-LD Function Updates Plan

## Current Issues Identified

After analyzing the codebase, I've identified several key issues with JSON-LD handling:

### 1. **Identifier Inconsistency (@id vs URI vs id)**
- **Problem**: Mixed usage of `@id`, `URI`, and `id` fields across the codebase
- **Current Pattern**: Code checks `obj.get('@id') or obj.get('URI')` everywhere
- **Impact**: Inconsistent object identification, conversion failures

### 2. **Single Object vs Graph List Confusion**
- **Problem**: Inconsistent handling of single objects vs `@graph` arrays
- **Current Pattern**: Some functions expect single objects, others expect `@graph` structure
- **Impact**: Type errors, failed conversions, complex conditional logic

### 3. **Context Management Issues**
- **Problem**: Context handling is inconsistent between single and list operations
- **Current Pattern**: Context sometimes duplicated, sometimes missing
- **Impact**: Invalid JSON-LD documents, namespace resolution failures

### 4. **VitalSigns Integration Problems**
- **Problem**: Mismatch between VitalSigns expectations and JSON-LD structure
- **Current Pattern**: Manual field conversion in multiple places
- **Impact**: Conversion failures, data loss

## Proposed Function Updates

### Core Principles
1. **Consistent Identifier Handling**: Always use `@id` in JSON-LD, `URI` in VitalSigns
2. **Clear Single vs List Semantics**: Explicit function contracts
3. **Unified Context Management**: Single source of truth for contexts
4. **VitalSigns Compatibility**: Seamless integration with VitalSigns library

### Function Specifications

#### 1. `to_jsonld(graph_object) -> dict`
**Purpose**: Convert single GraphObject to complete JSON-LD object

```python
def to_jsonld(graph_object) -> dict:
    """
    Convert a single GraphObject to a complete JSON-LD object.
    
    Returns:
        dict: Complete JSON-LD object with @context, @id, @type, and properties
    
    Example Output:
    {
        "@context": {
            "vital": "http://vital.ai/ontology/vital-core#",
            "haley": "http://vital.ai/ontology/haley-ai-kg#",
            "type": "@type",
            "id": "@id"
        },
        "@id": "http://example.com/entity1",
        "@type": "haley:KGEntity", 
        "vital:hasName": "Test Entity",
        "vital:vitaltype": "http://vital.ai/ontology/haley-ai-kg#KGEntity"
    }
    """
```

**Key Changes**:
- Returns complete, valid JSON-LD object with context
- **Dynamic context**: Only includes namespaces actually used in the data
- Always uses `@id` for identifier
- Uses prefixed properties for readability
- Minimal, optimized context (no unused namespaces)

#### 2. `to_jsonld_list(graph_object_list) -> dict`
**Purpose**: Convert list of GraphObjects to complete JSON-LD document

```python
def to_jsonld_list(graph_object_list) -> dict:
    """
    Convert list of GraphObjects to complete JSON-LD document.
    
    Returns:
        dict: Complete JSON-LD document with @context and @graph
    
    Example Output:
    {
        "@context": {
            "vital": "http://vital.ai/ontology/vital-core#",
            "haley": "http://vital.ai/ontology/haley-ai-kg#",
            "type": "@type",
            "id": "@id"
        },
        "@graph": [
            {
                "@id": "http://example.com/entity1",
                "@type": "haley:KGEntity",
                "vital:hasName": "Test Entity"
            },
            {
                "@id": "http://example.com/slot1", 
                "@type": "haley:KGTextSlot",
                "vital:hasName": "Test Slot"
            }
        ]
    }
    """
```

**Key Changes**:
- Always returns complete document with `@context` and `@graph`
- **Dynamic context**: Analyzes all objects to determine required namespaces
- Handles empty list gracefully
- Unified context management
- Consistent object structure
- Optimized context (only namespaces used across all objects)

**Key Difference from `to_jsonld()`**:
- **Single object**: `{"@context": {...}, "@id": "...", "@type": "...", ...}`
- **Document**: `{"@context": {...}, "@graph": [...]}`

#### 3. `from_jsonld(jsonld_object, cls=None) -> GraphObject`
**Purpose**: Convert single JSON-LD object to GraphObject

```python
def from_jsonld(jsonld_object: dict, cls=None) -> GraphObject:
    """
    Convert single JSON-LD object to GraphObject.
    
    Args:
        jsonld_object: JSON-LD object (NOT document with @graph)
        cls: Optional class hint for object creation
        
    Returns:
        GraphObject: Single VitalSigns object
        
    Raises:
        ValueError: If input is @graph document or list
    """
```

**Key Changes**:
- Strict single object input validation
- Clear error messages for wrong input types
- Automatic `@id` → `URI` conversion
- Optional class hint support

#### 4. `from_jsonld_list(jsonld_document, cls=None) -> List[GraphObject]`
**Purpose**: Convert JSON-LD document or list to GraphObjects

```python
def from_jsonld_list(jsonld_document: Union[dict, list], cls=None) -> List[GraphObject]:
    """
    Convert JSON-LD document or list to list of GraphObjects.
    
    Args:
        jsonld_document: JSON-LD document with @graph, or list of objects
        cls: Optional class hint for object creation
        
    Returns:
        List[GraphObject]: List of VitalSigns objects
        
    Handles:
        - {"@context": {...}, "@graph": [...]} documents
        - [...] lists of objects  
        - {...} single objects (returns list with one item)
    """
```

**Key Changes**:
- Flexible input handling (document, list, or single object)
- Consistent output (always list)
- Proper context inheritance
- Robust error handling

## Implementation Strategy

### Phase 1: Update Core Functions
1. **Update `GraphObjectJsonldUtils` class** with new implementations
2. **Add comprehensive input validation**
3. **Implement consistent identifier normalization**
4. **Add proper error handling and logging**

### Phase 2: Update VitalSigns Integration
1. **Create wrapper functions** for VitalSigns compatibility
2. **Update `vitalsigns_helpers.py`** to use new functions
3. **Add automatic field conversion** (`@id` ↔ `URI`, `@type` ↔ `vitaltype`)

### Phase 3: Update Endpoint Usage
1. **Update all endpoints** to use new function signatures
2. **Remove manual field conversion code**
3. **Standardize error handling**

### Phase 4: Testing and Validation
1. **Update existing tests** to match new behavior
2. **Add comprehensive test coverage** for edge cases
3. **Validate VitalSigns compatibility**

## Detailed Implementation Notes

### Identifier Normalization Rules
```python
# JSON-LD → VitalSigns
if '@id' in jsonld_obj:
    vitalsigns_obj.URI = jsonld_obj['@id']

# VitalSigns → JSON-LD  
if hasattr(vitalsigns_obj, 'URI'):
    jsonld_obj['@id'] = vitalsigns_obj.URI
```

### Context Management Strategy
```python
def build_dynamic_context(graph_objects):
    """
    Build context dynamically based on URIs found in the data.
    
    Args:
        graph_objects: Single GraphObject or list of GraphObjects
        
    Returns:
        dict: Context with namespaces needed for the data
    """
    # Start with base JSON-LD context
    context = {
        "type": "@type",
        "id": "@id"
    }
    
    # Extract all URIs from the objects
    uris_found = set()
    objects_to_scan = [graph_objects] if not isinstance(graph_objects, list) else graph_objects
    
    for obj in objects_to_scan:
        # Scan object properties for URIs
        uris_found.update(extract_uris_from_object(obj))
    
    # Map URIs to known ontology prefixes using VitalSigns OntologyManager
    # NOTE: We depend on VitalSigns OntologyManager to provide meaningful prefixes
    # (e.g., "vital", "haley") rather than generic ones (e.g., "namespace1", "namespace2")
    ontology_manager = VitalSigns().get_ontology_manager()
    for uri in uris_found:
        namespace = get_namespace_from_uri(uri)  # Extract namespace from full URI
        prefix = ontology_manager.get_prefix_for_namespace(namespace)
        if prefix:
            context[prefix] = namespace
    
    return context

def extract_uris_from_object(graph_object):
    """Extract all URIs from a GraphObject (types, properties, values)."""
    uris = set()
    
    # Add object URI
    if hasattr(graph_object, 'URI'):
        uris.add(graph_object.URI)
    
    # Add type URIs
    if hasattr(graph_object, 'vitaltype'):
        uris.add(graph_object.vitaltype)
    
    # Add property URIs by scanning RDF representation
    rdf_string = GraphObjectRdfUtils.to_rdf_impl(graph_object, format='turtle')
    # Parse RDF and extract predicate URIs
    # ... implementation details
    
    return uris
```

### Input Validation Patterns
```python
def validate_single_object(data):
    if isinstance(data, list):
        raise ValueError("Expected single object, got list. Use from_jsonld_list() instead.")
    if isinstance(data, dict) and "@graph" in data:
        raise ValueError("Expected single object, got @graph document. Use from_jsonld_list() instead.")

def validate_document_or_list(data):
    if not isinstance(data, (dict, list)):
        raise ValueError("Expected dict or list, got {type(data)}")
```

## Migration Path

### Backward Compatibility
- **Keep old function signatures** during transition period
- **Add deprecation warnings** for old usage patterns
- **Provide migration utilities** for existing code

### Breaking Changes
- **`to_jsonld()` output format** changes from document to object
- **Stricter input validation** may reject previously accepted inputs
- **Consistent identifier fields** may require code updates

### Migration Timeline
1. **Week 1-2**: Implement new functions with backward compatibility
2. **Week 3-4**: Update endpoints and tests
3. **Week 5-6**: Remove deprecated functions and clean up

## Expected Benefits

### Code Quality
- **Reduced complexity**: Clear function contracts eliminate conditional logic
- **Better error handling**: Explicit validation and clear error messages
- **Consistent patterns**: Unified approach across all endpoints

### Reliability
- **Fewer conversion errors**: Proper input validation and type checking
- **VitalSigns compatibility**: Seamless integration with VitalSigns library
- **Predictable behavior**: Clear semantics for single vs list operations

### Maintainability
- **Single source of truth**: Centralized JSON-LD handling logic
- **Easier testing**: Clear function boundaries and expected behaviors
- **Better documentation**: Explicit contracts and examples

## Risk Mitigation

### Testing Strategy
- **Comprehensive unit tests** for all new functions
- **Integration tests** with VitalSigns library
- **Backward compatibility tests** during transition

### Rollback Plan
- **Feature flags** to enable/disable new functions
- **Parallel implementations** during transition period
- **Monitoring and alerting** for conversion failures

This plan addresses the core issues while providing a clear migration path and maintaining system reliability.