"""JSON-LD Model Classes

Pydantic models for JSON-LD document handling across VitalGraph endpoints.
"""

from typing import Dict, List, Any, Optional, Union, Literal, Annotated
from pydantic import BaseModel, Field, Discriminator, Tag, field_validator


class JsonLdObject(BaseModel):
    """
    Pydantic model for single JSON-LD objects.
    
    This model represents a single JSON-LD object with @id, @type, and properties
    at the root level (not wrapped in a @graph array).
    """
    model_config = {"extra": "allow", "populate_by_name": True, "ser_json_by_alias": True}
    
    # Discriminator field for union handling
    jsonld_type: Literal["object"] = Field(default="object", description="Discriminator for JSON-LD type")
    
    context: Optional[Union[str, Dict[str, Any], List[Union[str, Dict[str, Any]]]]] = Field(
        None, 
        alias="@context",
        serialization_alias="@context",
        description="JSON-LD context defining term mappings and namespaces"
    )
    id: str = Field(
        alias="@id",
        serialization_alias="@id",
        description="The unique identifier (URI) of the JSON-LD object"
    )
    type: Union[str, List[str]] = Field(
        alias="@type",
        serialization_alias="@type",
        description="The type(s) of the JSON-LD object"
    )


class JsonLdDocument(BaseModel):
    """
    Pydantic model for JSON-LD documents with @graph arrays.
    
    This model supports JSON-LD documents that contain multiple objects
    in a @graph array structure, with optional pagination fields.
    """
    model_config = {"extra": "allow", "populate_by_name": True, "ser_json_by_alias": True}
    
    # Discriminator field for union handling
    jsonld_type: Literal["document"] = Field(default="document", description="Discriminator for JSON-LD type")
    
    context: Optional[Union[str, Dict[str, Any], List[Union[str, Dict[str, Any]]]]] = Field(
        None, 
        alias="@context",
        serialization_alias="@context",
        description="JSON-LD context defining term mappings and namespaces"
    )
    graph: List[Dict[str, Any]] = Field(
        alias="@graph",
        serialization_alias="@graph", 
        description="Array of JSON-LD objects representing the graph data"
    )
    
    @field_validator('graph')
    @classmethod
    def validate_graph_not_single_object(cls, v: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Validate that JsonLdDocument is not used for single objects."""
        if len(v) == 1:
            raise ValueError(
                "JsonLdDocument should not be used for single objects. "
                "Use JsonLdObject instead for single JSON-LD objects."
            )
        # Allow empty graph arrays (representing no results)
        return v
    
    def __len__(self) -> int:
        """Return the number of objects in the graph array."""
        return len(self.graph) if self.graph else 0


# Discriminated union for handling both JsonLdObject and JsonLdDocument
def get_jsonld_discriminator(v: Any) -> str:
    """Discriminator function to determine JsonLD type based on content."""
    if isinstance(v, dict):
        # Check for explicit discriminator field first
        if v.get("jsonld_type") == "object":
            return "object"
        elif v.get("jsonld_type") == "document":
            return "document"
        # Fallback to content-based detection
        elif "@graph" in v or "graph" in v:
            return "document"
        elif "@id" in v or "id" in v:
            return "object"
    return "document"  # Default to document


JsonLdRequest = Annotated[
    Union[
        Annotated[JsonLdObject, Tag("object")],
        Annotated[JsonLdDocument, Tag("document")]
    ],
    Discriminator(get_jsonld_discriminator)
]