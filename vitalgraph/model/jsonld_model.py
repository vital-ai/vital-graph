"""JSON-LD Model Classes

Shared Pydantic models for JSON-LD document handling across VitalGraph endpoints.
"""

from typing import Dict, List, Any, Optional, Union
from pydantic import BaseModel, Field


class JsonLdDocument(BaseModel):
    """
    Pydantic model for JSON-LD documents with flexible structure.
    
    This model supports the standard JSON-LD structure with @context and @graph fields,
    while allowing additional fields for flexible JSON-LD document handling.
    """
    context: Optional[Union[str, Dict[str, Any], List[Union[str, Dict[str, Any]]]]] = Field(
        None, 
        alias="@context", 
        description="JSON-LD context defining term mappings and namespaces"
    )
    graph: Optional[List[Dict[str, Any]]] = Field(
        None,
        alias="@graph", 
        description="Array of JSON-LD objects representing the graph data"
    )
    
    class Config:
        populate_by_name = True  # Pydantic V2 equivalent of allow_population_by_field_name
        extra = "allow"  # Allow additional fields for flexible JSON-LD structure