# VitalGraph Client-Server Model Unification Plan

## Overview

This document outlines a plan to unify the Pydantic model classes between the VitalGraph server-side implementation and client-side implementation. Currently, the server uses structured Pydantic models with inheritance and validation, while the client returns raw dictionaries from JSON responses.

## Current State Analysis

### Server-Side Models (`/vitalgraph/model/`)

The server has well-structured Pydantic models organized as follows:

#### Base Models (`api_model.py`)
- `BasePaginatedResponse` - Common pagination fields
- `BaseJsonLdResponse` - JSON-LD responses with pagination
- `BaseCreateResponse` - Creation operation responses
- `BaseUpdateResponse` - Update operation responses
- `BaseDeleteResponse` - Deletion operation responses
- `BaseOperationResponse` - General operation responses
- `BaseJobResponse` - Job-related responses
- `BaseListResponse` - Simple list responses

#### Domain-Specific Models
- `kgentities_model.py` - KGEntity operations (inherits from base models)
- `kgframes_model.py` - KGFrame operations (inherits from base models)
- `kgtypes_model.py` - KGType operations (inherits from base models)
- `objects_model.py` - Generic object operations (inherits from base models)
- `sparql_model.py` - SPARQL operations (inherits from base models)
- `import_model.py` - Import job models
- `export_model.py` - Export job models
- `files_model.py` - File operations
- `spaces_model.py` - Space management
- `users_model.py` - User management
- `triples_model.py` - Triple operations
- `jsonld_model.py` - JSON-LD document structure

### Client-Side Endpoints (`/vitalgraph/client/endpoint/`)

The client endpoints currently return raw dictionaries:

#### Current Client Structure
- `base_endpoint.py` - Base class for all client endpoints
- `kgentities_endpoint.py` - KGEntity client operations
- `kgframes_endpoint.py` - KGFrame client operations
- `kgtypes_endpoint.py` - KGType client operations
- `objects_endpoint.py` - Generic object client operations
- `sparql_endpoint.py` - SPARQL client operations
- `import_endpoint.py` - Import job client operations
- `export_endpoint.py` - Export job client operations
- `files_endpoint.py` - File client operations
- `spaces_endpoint.py` - Space management client operations
- `users_endpoint.py` - User management client operations
- `triples_endpoint.py` - Triple client operations
- `graphs_endpoint.py` - Graph management client operations

#### Current Client Return Types
All client methods currently return `Dict[str, Any]` from `response.json()` calls.

## Unification Strategy

### Direct Model Integration Approach

Since the models are already shared within the server and client codebase, we'll directly integrate the existing server-side Pydantic models (`/vitalgraph/model/`) into the client endpoints without creating new package structures or maintaining backward compatibility.

#### Current Model Structure (Already Available)
```
vitalgraph/model/
├── api_model.py           # Base response models (already consolidated)
├── jsonld_model.py        # JSON-LD document structure
├── kgentities_model.py    # KGEntity response models
├── kgframes_model.py      # KGFrame response models  
├── kgtypes_model.py       # KGType response models
├── objects_model.py       # Object response models
├── sparql_model.py        # SPARQL response models
├── import_model.py        # Import job models
├── export_model.py        # Export job models
├── files_model.py         # File operation models
├── spaces_model.py        # Space management models
├── users_model.py         # User management models
└── triples_model.py       # Triple operation models
```

#### Integration Requirements

**Client-Side Changes:**
- Import existing Pydantic models from `/vitalgraph/model/`
- Replace `Dict[str, Any]` return types with specific model types
- Add model parsing in client endpoint methods
- Provide type hints for IDE support

**No Server-Side Changes Required:**
- Server already uses these models
- No migration needed for server endpoints
- Existing validation and inheritance preserved

### Phase 1: Client Integration Strategy

#### 1.1 Update Client Base Endpoint

Modify the base endpoint to support Pydantic model parsing:

```python
# client/endpoint/base_endpoint.py
from typing import TypeVar, Type, Dict, Any
from pydantic import BaseModel

T = TypeVar('T', bound=BaseModel)

class BaseEndpoint:
    def _parse_response(self, response_data: Dict[str, Any], 
                       model_class: Type[T]) -> T:
        """Parse response data into a Pydantic model."""
        return model_class.model_validate(response_data)
    
    def _make_typed_request(self, method: str, url: str, 
                           response_model: Type[T], **kwargs) -> T:
        """Make a request and return a typed response."""
        response = self._make_authenticated_request(method, url, **kwargs)
        return self._parse_response(response.json(), response_model)
```

#### 1.2 Update Client Endpoints

Modify client endpoints to use existing server models:

```python
# client/endpoint/kgentities_endpoint.py
from vitalgraph.model.kgentities_model import (
    EntitiesResponse, EntityCreateResponse, EntityUpdateResponse, EntityDeleteResponse
)

class KGEntitiesEndpoint(BaseEndpoint):
    def list_kgentities(self, space_id: str, graph_id: str, 
                       page_size: int = 10, offset: int = 0, 
                       search: Optional[str] = None) -> EntitiesResponse:
        """List KGEntities with typed response."""
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        url = f"{self._get_server_url()}/api/graphs/kgentities"
        params = build_query_params(
            space_id=space_id, graph_id=graph_id,
            page_size=page_size, offset=offset, search=search
        )
        
        return self._make_typed_request('GET', url, EntitiesResponse, params=params)
    
    def create_kgentities(self, space_id: str, graph_id: str, 
                         document: Dict[str, Any]) -> EntityCreateResponse:
        """Create KGEntities with typed response."""
        # ... validation code ...
        
        url = f"{self._get_server_url()}/api/graphs/kgentities"
        params = build_query_params(space_id=space_id, graph_id=graph_id)
        
        return self._make_typed_request(
            'POST', url, EntityCreateResponse, params=params, json=document
        )
```

### Phase 2: Complete Client Endpoint Updates

Apply the same pattern to all client endpoints:

#### 2.1 KGFrames Endpoint
```python
# client/endpoint/kgframes_endpoint.py
from vitalgraph.model.kgframes_model import (
    FramesResponse, FrameCreateResponse, FrameUpdateResponse, FrameDeleteResponse
)

class KGFramesEndpoint(BaseEndpoint):
    def list_kgframes(self, ...) -> FramesResponse:
        return self._make_typed_request('GET', url, FramesResponse, params=params)
    
    def create_kgframes(self, ...) -> FrameCreateResponse:
        return self._make_typed_request('POST', url, FrameCreateResponse, ...)
```

#### 2.2 Objects Endpoint
```python
# client/endpoint/objects_endpoint.py
from vitalgraph.model.objects_model import (
    ObjectsResponse, ObjectCreateResponse, ObjectUpdateResponse, ObjectDeleteResponse
)

class ObjectsEndpoint(BaseEndpoint):
    def list_objects(self, ...) -> ObjectsResponse:
        return self._make_typed_request('GET', url, ObjectsResponse, params=params)
```

#### 2.3 SPARQL Endpoint
```python
# client/endpoint/sparql_endpoint.py
from vitalgraph.model.sparql_model import (
    SPARQLQueryResponse, SPARQLUpdateResponse, SPARQLInsertResponse
)

class SparqlEndpoint(BaseEndpoint):
    def execute_sparql_query(self, ...) -> SPARQLQueryResponse:
        return self._make_typed_request('POST', url, SPARQLQueryResponse, json=query_data)
```

## Implementation Plan

### Phase 1: Client Base Infrastructure (Week 1)
1. **Update BaseEndpoint class** with typed response support
2. **Add model parsing methods** (`_parse_response`, `_make_typed_request`)
3. **Test basic model parsing** with one endpoint
4. **Verify no breaking changes** to existing functionality

### Phase 2: Core Client Endpoints (Week 2-3)
1. **Update KGEntities endpoint** with typed responses
2. **Update KGFrames endpoint** with typed responses
3. **Update KGTypes endpoint** with typed responses
4. **Update Objects endpoint** with typed responses
5. **Test all CRUD operations** with typed responses

### Phase 3: Specialized Client Endpoints (Week 4)
1. **Update SPARQL endpoint** with typed responses
2. **Update Import/Export endpoints** with typed responses
3. **Update Files endpoint** with typed responses
4. **Update Spaces/Users endpoints** with typed responses
5. **Update Triples/Graphs endpoints** with typed responses

### Phase 4: Testing & Validation (Week 5)
1. **Comprehensive integration testing** of all client endpoints
2. **Validate type safety** and IDE support
3. **Performance testing** (ensure no regression)
4. **Update client tests** to use typed responses
5. **Update documentation** and examples

## Benefits

### Type Safety
- **Client-side**: Full type hints and IDE support
- **Server-side**: Maintained validation and type safety
- **Shared**: Consistent data structures across client/server boundary

### Maintainability
- **Single source of truth** for API models
- **Reduced duplication** between client and server
- **Easier API evolution** with shared models

### Developer Experience
- **Better IDE support** with type hints
- **Compile-time error detection** for model mismatches
- **Consistent API** across client and server

### Reliability
- **Automatic validation** on both client and server
- **Schema consistency** prevents client-server mismatches
- **Graceful degradation** with fallback to raw dictionaries

## Migration Considerations

### No Backward Compatibility Required
- **Direct replacement** of `Dict[str, Any]` with typed models
- **Clean break** from untyped responses
- **Immediate type safety** benefits

### Performance
- **Minimal overhead** from Pydantic model creation
- **Validation already exists** on server side
- **No additional network overhead**

### Error Handling
- **Standard Pydantic validation errors** for malformed responses
- **Clear error messages** for debugging
- **Consistent error handling** across all endpoints

## Risk Mitigation

### Breaking Changes
- **No breaking changes** - only return type improvements
- **Existing functionality preserved** - same data, better types
- **IDE support improved** immediately

### Dependencies
- **No new dependencies** - Pydantic already used by server
- **Existing model structure** leveraged directly
- **No version conflicts** - same models used by server

### Implementation Risk
- **Simple changes** - only client endpoint modifications
- **Server unchanged** - no risk to existing server functionality
- **Incremental rollout** - can update endpoints one by one

## Success Metrics

1. **Type Coverage**: 100% of client API responses use typed Pydantic models
2. **No Breaking Changes**: Existing client functionality preserved
3. **Performance**: <2% overhead from model parsing (minimal impact)
4. **Developer Experience**: Full IDE support with type hints and validation
5. **Code Quality**: Single source of truth for API response structures

## Conclusion

This simplified plan leverages the existing server-side Pydantic models directly in the client without creating new package structures or maintaining backward compatibility. The approach is:

- **Simple**: Only client-side changes required
- **Fast**: Can be implemented in 4-5 weeks
- **Low Risk**: No server changes, incremental client updates
- **High Value**: Immediate type safety and IDE support benefits

By directly using the existing `/vitalgraph/model/` Pydantic models in the client endpoints, we achieve full type unification between client and server with minimal effort and maximum benefit.
