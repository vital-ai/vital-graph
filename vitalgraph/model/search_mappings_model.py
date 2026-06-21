"""
Pydantic request/response models for Search Mappings endpoints.

Search mappings define which entity types and predicates feed into a named
search index.  They are shared by both FTS and vector indexes.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Output / response models
# ---------------------------------------------------------------------------

class SearchMappingPropertyOut(BaseModel):
    """A child property within a search mapping."""
    property_id: int
    mapping_id: int
    property_uri: str
    property_role: str = "include"
    ordinal: int = 0


class SearchMappingIndexOut(BaseModel):
    """An index association (junction row) within a search mapping."""
    id: int
    mapping_id: int
    index_type: str  # 'vector' or 'fts'
    index_name: str
    created_time: Optional[str] = None


class SearchMappingOut(BaseModel):
    """A search mapping with its child properties and index associations."""
    mapping_id: int
    mapping_type: str
    type_uri: Optional[str] = None
    index_name: str
    enabled: bool = True
    source_type: str = "default"
    separator: str = ". "
    include_pred_name: bool = False
    created_time: Optional[str] = None
    properties: List[SearchMappingPropertyOut] = []
    indexes: List[SearchMappingIndexOut] = []


class SearchMappingListResponse(BaseModel):
    mappings: List[SearchMappingOut]
    total_count: int


# ---------------------------------------------------------------------------
# Create / update request models
# ---------------------------------------------------------------------------

class CreateSearchMappingRequest(BaseModel):
    index_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Target index name (shared by FTS + vector)",
    )
    mapping_type: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Mapping type, e.g. 'kgentity', 'kgdocument'",
    )
    type_uri: Optional[str] = Field(
        None,
        description="Optional RDF type URI filter",
    )
    enabled: bool = Field(True, description="Whether this mapping is active")
    source_type: str = Field("default", description="Source type: type_description, properties, properties_type, or default")
    separator: str = Field(". ", description="Separator between property values")
    include_pred_name: bool = Field(False, description="Include predicate names in search text")


class UpdateSearchMappingRequest(BaseModel):
    enabled: Optional[bool] = None
    source_type: Optional[str] = None
    separator: Optional[str] = None
    include_pred_name: Optional[bool] = None


class AddIndexRequest(BaseModel):
    index_type: str = Field(..., description="Index type: 'vector' or 'fts'")
    index_name: str = Field(..., min_length=1, max_length=255, description="Name of the vector or FTS index to associate")


class AddPropertyRequest(BaseModel):
    property_uri: str = Field(..., description="Property URI to add")
    property_role: str = Field("include", description="Role: 'include' or 'exclude'")
    ordinal: int = Field(0, description="Sort order")


class DeleteResponse(BaseModel):
    message: str
    deleted: bool = False
