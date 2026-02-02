# JSON-LD Processing Plan
## VitalGraph Fuseki-PostgreSQL Hybrid Backend

### Overview
This document defines the JSON-LD processing architecture for VitalGraph, establishing clear separation between JSON-LD objects and documents, with strict conversion requirements at endpoint boundaries.

### Core Principles

1. **Complete Separation**: JsonLdObject and JsonLdDocument are distinct types with separate processing paths
2. **Endpoint Boundary Conversion**: JSON-LD must be converted to GraphObjects or RDFLib triples immediately at endpoints
3. **No Internal JSON-LD**: Internal processing uses only GraphObjects and RDFLib triples
4. **Union Types**: Inputs/outputs use Union[JsonLdObject, JsonLdDocument] with separate codepaths

## Pydantic Models

### JsonLdObject Model

```python
from pydantic import BaseModel, Field, validator
from typing import Any, Dict, Optional, Union, List

class JsonLdObject(BaseModel):
    """
    Pydantic model for single JSON-LD object.
    
    Special handling for @-properties which must be aliased in Pydantic.
    Represents a single RDF resource with its properties.
    """
    
    # @-properties must be aliased due to Pydantic restrictions
    id: Optional[str] = Field(None, alias="@id")
    type: Optional[Union[str, List[str]]] = Field(None, alias="@type")
    context: Optional[Union[str, Dict[str, Any], List[Union[str, Dict[str, Any]]]]] = Field(None, alias="@context")
    
    # Additional properties (dynamic)
    # All other properties are stored in __root__ or as additional fields
    
    class Config:
        allow_population_by_field_name = True
        extra = "allow"  # Allow additional properties beyond defined fields
    
    @validator('type', pre=True)
    def normalize_type(cls, v):
        """Ensure @type is always a list for consistent processing."""
        if v is None:
            return None
        if isinstance(v, str):
            return [v]
        return v
    
    def get_subject_uri(self) -> Optional[str]:
        """Extract subject URI from @id field."""
        return self.id
    
    def get_rdf_types(self) -> List[str]:
        """Get RDF types from @type field."""
        return self.type or []
    
    def to_rdf_triples(self) -> List[tuple]:
        """Convert to RDFLib triples for internal processing."""
        # Implementation converts JSON-LD object to triples
        pass
```

### JsonLdDocument Model

```python
class JsonLdDocument(BaseModel):
    """
    Pydantic model for JSON-LD document containing multiple objects.
    
    Represents a complete JSON-LD document with @context and @graph array.
    Used for batch operations and multi-object responses.
    """
    
    # @-properties with aliases
    context: Optional[Union[str, Dict[str, Any], List[Union[str, Dict[str, Any]]]]] = Field(None, alias="@context")
    graph: List[Dict[str, Any]] = Field(..., alias="@graph")
    id: Optional[str] = Field(None, alias="@id")  # Document-level ID (optional)
    
    class Config:
        allow_population_by_field_name = True
        extra = "forbid"  # Documents have strict structure
    
    @validator('graph', pre=True)
    def validate_graph_array(cls, v):
        """Ensure @graph is always a list."""
        if not isinstance(v, list):
            raise ValueError("@graph must be an array")
        return v
    
    def get_objects(self) -> List[JsonLdObject]:
        """Extract individual JSON-LD objects from @graph array."""
        objects = []
        for obj_data in self.graph:
            # Add document context to each object if not present
            if self.context and "@context" not in obj_data:
                obj_data["@context"] = self.context
            objects.append(JsonLdObject(**obj_data))
        return objects
    
    def to_rdf_triples(self) -> List[tuple]:
        """Convert entire document to RDFLib triples for internal processing."""
        # Implementation converts all objects in document to triples
        pass
    
    def get_object_count(self) -> int:
        """Get number of objects in the document."""
        return len(self.graph)
```

### Union Types for Endpoint Processing

```python
from typing import Union

# Input/Output union types
JsonLdInput = Union[JsonLdObject, JsonLdDocument]
JsonLdOutput = Union[JsonLdObject, JsonLdDocument]

# Type guards for runtime type checking
def is_jsonld_object(data: JsonLdInput) -> bool:
    """Type guard to check if input is JsonLdObject."""
    return isinstance(data, JsonLdObject)

def is_jsonld_document(data: JsonLdInput) -> bool:
    """Type guard to check if input is JsonLdDocument."""
    return isinstance(data, JsonLdDocument)

def detect_jsonld_type(raw_data: Dict[str, Any]) -> str:
    """Detect whether raw JSON-LD data represents object or document."""
    if "@graph" in raw_data:
        return "document"
    else:
        return "object"
```

## Endpoint Processing Architecture

### Input Processing Pattern

```python
from vitalgraph.model.graph_object import GraphObject
from rdflib import Graph
from typing import List

async def process_jsonld_input(jsonld_input: JsonLdInput) -> List[GraphObject]:
    """
    Convert JSON-LD input to GraphObjects at endpoint boundary.
    
    This is the ONLY place where JSON-LD is processed internally.
    All subsequent processing uses GraphObjects.
    """
    
    if is_jsonld_object(jsonld_input):
        # Single object processing path
        triples = jsonld_input.to_rdf_triples()
        graph_object = GraphObject.from_triples(triples)
        return [graph_object]
    
    elif is_jsonld_document(jsonld_input):
        # Document processing path
        graph_objects = []
        for jsonld_obj in jsonld_input.get_objects():
            triples = jsonld_obj.to_rdf_triples()
            graph_object = GraphObject.from_triples(triples)
            graph_objects.append(graph_object)
        return graph_objects
    
    else:
        raise ValueError("Invalid JSON-LD input type")

async def process_raw_jsonld_input(raw_data: Dict[str, Any]) -> List[GraphObject]:
    """
    Process raw JSON-LD data by first determining type, then converting.
    """
    
    jsonld_type = detect_jsonld_type(raw_data)
    
    if jsonld_type == "object":
        jsonld_obj = JsonLdObject(**raw_data)
        return await process_jsonld_input(jsonld_obj)
    
    elif jsonld_type == "document":
        jsonld_doc = JsonLdDocument(**raw_data)
        return await process_jsonld_input(jsonld_doc)
    
    else:
        raise ValueError(f"Unknown JSON-LD type: {jsonld_type}")
```

### Output Processing Pattern

```python
async def format_jsonld_output(graph_objects: List[GraphObject], 
                              output_format: str = "auto") -> JsonLdOutput:
    """
    Convert GraphObjects back to JSON-LD for endpoint responses.
    
    Args:
        graph_objects: List of GraphObjects from internal processing
        output_format: "object", "document", or "auto"
    
    Returns:
        JsonLdObject for single objects, JsonLdDocument for multiple
    """
    
    if output_format == "auto":
        output_format = "object" if len(graph_objects) == 1 else "document"
    
    if output_format == "object":
        if len(graph_objects) != 1:
            raise ValueError("Cannot format multiple objects as JsonLdObject")
        
        # Convert single GraphObject to JsonLdObject
        triples = graph_objects[0].to_triples()
        jsonld_data = convert_triples_to_jsonld_object(triples)
        return JsonLdObject(**jsonld_data)
    
    elif output_format == "document":
        # Convert multiple GraphObjects to JsonLdDocument
        graph_array = []
        for graph_obj in graph_objects:
            triples = graph_obj.to_triples()
            jsonld_obj_data = convert_triples_to_jsonld_object(triples)
            graph_array.append(jsonld_obj_data)
        
        return JsonLdDocument(
            context=get_default_context(),
            graph=graph_array
        )
    
    else:
        raise ValueError(f"Invalid output format: {output_format}")
```

## Endpoint Implementation Pattern

### Request Handler Template

```python
from fastapi import HTTPException
from typing import Union

async def endpoint_handler(jsonld_input: Union[Dict[str, Any], JsonLdInput]) -> JsonLdOutput:
    """
    Template for endpoint handlers with proper JSON-LD processing.
    
    1. Convert JSON-LD input to GraphObjects immediately
    2. Process using internal GraphObject operations
    3. Convert back to JSON-LD for response
    """
    
    try:
        # Step 1: Convert JSON-LD to GraphObjects at boundary
        if isinstance(jsonld_input, dict):
            graph_objects = await process_raw_jsonld_input(jsonld_input)
        else:
            graph_objects = await process_jsonld_input(jsonld_input)
        
        # Step 2: Internal processing (NO JSON-LD allowed here)
        processed_objects = await internal_business_logic(graph_objects)
        
        # Step 3: Convert back to JSON-LD for response
        response = await format_jsonld_output(processed_objects)
        
        return response
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"JSON-LD processing error: {str(e)}")

async def internal_business_logic(graph_objects: List[GraphObject]) -> List[GraphObject]:
    """
    Internal business logic that operates ONLY on GraphObjects.
    
    NO JSON-LD processing allowed in internal functions.
    """
    # All internal processing uses GraphObjects and RDFLib triples
    # JSON-LD is forbidden beyond the endpoint boundary
    pass
```

## Validation and Error Handling

### JSON-LD Validation

```python
from pydantic import ValidationError

def validate_jsonld_input(raw_data: Dict[str, Any]) -> JsonLdInput:
    """
    Validate raw JSON-LD data and return appropriate Pydantic model.
    """
    
    try:
        jsonld_type = detect_jsonld_type(raw_data)
        
        if jsonld_type == "object":
            return JsonLdObject(**raw_data)
        elif jsonld_type == "document":
            return JsonLdDocument(**raw_data)
        else:
            raise ValueError(f"Invalid JSON-LD structure")
            
    except ValidationError as e:
        raise ValueError(f"JSON-LD validation failed: {e}")
    except Exception as e:
        raise ValueError(f"JSON-LD processing error: {e}")
```

### Error Response Format

```python
class JsonLdErrorResponse(BaseModel):
    """Standard error response for JSON-LD processing failures."""
    
    error: str
    message: str
    details: Optional[Dict[str, Any]] = None
    invalid_fields: Optional[List[str]] = None
```

## Implementation Requirements

### Critical Rules

1. **Endpoint Boundary Only**: JSON-LD processing ONLY at endpoint boundaries
2. **Immediate Conversion**: Convert JSON-LD to GraphObjects/triples immediately upon receipt
3. **No Internal JSON-LD**: Internal functions must never process JSON-LD directly
4. **Separate Codepaths**: Distinct processing for JsonLdObject vs JsonLdDocument
5. **Union Types**: Use Union[JsonLdObject, JsonLdDocument] for inputs/outputs
6. **Type Guards**: Always use type guards to determine processing path

### Conversion Functions Required

```python
def convert_triples_to_jsonld_object(triples: List[tuple]) -> Dict[str, Any]:
    """Convert RDFLib triples to JSON-LD object format."""
    pass

def convert_triples_to_jsonld_document(triples: List[tuple]) -> Dict[str, Any]:
    """Convert RDFLib triples to JSON-LD document format."""
    pass

def get_default_context() -> Dict[str, str]:
    """Get default JSON-LD context for VitalGraph objects."""
    return {
        "vital": "http://vital.ai/ontology/vital-core#",
        "haley": "http://vital.ai/ontology/haley-ai-kg#",
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "rdfs": "http://www.w3.org/2000/01/rdf-schema#"
    }
```

## Testing Strategy

### Unit Tests Required

1. **Pydantic Model Tests**: Validate @-property aliasing and model validation
2. **Type Detection Tests**: Ensure correct object vs document detection
3. **Conversion Tests**: Verify GraphObject ↔ JSON-LD conversion accuracy
4. **Union Type Tests**: Test separate codepaths for object vs document processing
5. **Error Handling Tests**: Validate error responses for invalid JSON-LD

### Integration Tests Required

1. **Endpoint Boundary Tests**: Verify JSON-LD stops at endpoint boundaries
2. **Internal Processing Tests**: Ensure no JSON-LD in internal functions
3. **Round-trip Tests**: JSON-LD → GraphObject → JSON-LD consistency
4. **Performance Tests**: Validate conversion performance for large datasets

This architecture ensures clean separation between JSON-LD interface requirements and internal RDF processing, with strict boundaries and clear conversion patterns.