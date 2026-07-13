"""KG Types Model Classes

Pydantic models for KG type management operations with Union support for 
both single objects and documents.
"""

from typing import Dict, List, Any, Optional, Union
from pydantic import BaseModel, Field, validator

from .quad_model import Quad, QuadRequest, QuadResponse, QuadResultsResponse
from .api_model import BasePaginatedResponse, BaseCreateResponse, BaseUpdateResponse, BaseDeleteResponse


class KGTypeFilter(BaseModel):
    """Filter criteria for KGType queries."""
    search_text: Optional[str] = Field(None, description="Text to search for in KGType properties")
    subject_uri: Optional[str] = Field(None, description="Specific subject URI to filter by")
    vitaltype_filter: Optional[str] = Field(None, description="Filter by vitaltype URI")


class KGTypeRequest(BaseModel):
    """
    Request model for KGType operations.
    """
    space_id: str = Field(..., description="Space identifier")
    graph_id: str = Field(..., description="Graph identifier")
    data: Optional[QuadRequest] = Field(None, description="KGType data as quads")


class KGTypeCreateRequest(KGTypeRequest):
    """Request model for creating KGTypes (POST /kgtypes)."""
    pass


class KGTypeUpdateRequest(KGTypeRequest):
    """Request model for updating KGTypes (PUT /kgtypes)."""
    pass


class KGTypeBatchDeleteRequest(BaseModel):
    """Request model for batch deleting KGTypes (DELETE /kgtypes with body)."""
    space_id: str = Field(..., description="Space identifier")
    graph_id: str = Field(..., description="Graph identifier")
    data: Union[QuadRequest, List[str]] = Field(
        ..., 
        description="KGType URIs to delete - as quads or list of URI strings"
    )


class KGTypeListRequest(BaseModel):
    """Request model for listing KG types with pagination and filtering."""
    space_id: str = Field(..., description="Space identifier")
    graph_id: str = Field(..., description="Graph identifier")
    page_size: int = Field(10, ge=1, le=100, description="Number of items per page")
    offset: int = Field(0, ge=0, description="Number of items to skip")
    filter: Optional[str] = Field(None, description="Filter criteria for KGTypes")


class KGTypeResponse(BaseModel):
    """Base response model for KGType operations."""
    success: bool = Field(..., description="Operation success status")
    message: str = Field(..., description="Human-readable status message")
    data: Optional[QuadResultsResponse] = Field(None, description="Response data as quad results")
    errors: Optional[List[str]] = Field(None, description="Error messages if any")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")


class KGTypeCreateResponse(KGTypeResponse):
    """Response model for KGType creation operations."""
    created_count: Optional[int] = Field(None, description="Number of KGTypes created")
    created_uris: Optional[List[str]] = Field(None, description="URIs of created KGTypes")


class KGTypeUpdateResponse(KGTypeResponse):
    """Response model for KGType update operations."""
    updated_count: Optional[int] = Field(None, description="Number of KGTypes updated")
    updated_uris: Optional[List[str]] = Field(None, description="URIs of updated KGTypes")


class KGTypeDeleteResponse(KGTypeResponse):
    """Response model for KGType deletion operations."""
    deleted_count: Optional[int] = Field(None, description="Number of KGTypes deleted")
    deleted_uris: Optional[List[str]] = Field(None, description="URIs of deleted KGTypes")


class KGTypeRelationshipEdge(BaseModel):
    """A single type-level edge in a relationship response."""
    uri: str = Field(..., description="Edge object URI")
    edgeType: str = Field(..., description="Edge vitaltype URI (e.g. Edge_hasSubKGFrameType)")
    sourceURI: str = Field(..., description="Source type URI")
    destinationURI: str = Field(..., description="Destination type URI")
    direction: str = Field(..., description="'outgoing' or 'incoming' relative to the queried type")


class KGTypeRelationshipType(BaseModel):
    """Summary of a connected type in a relationship response."""
    uri: str = Field(..., description="Type URI")
    name: str = Field(..., description="Type name (hasName)")
    vitaltype: str = Field(..., description="vitaltype URI of the connected type")


class KGTypeRelationshipsResponse(BaseModel):
    """Response model for GET /api/graphs/kgtypes/relationships."""
    success: bool = Field(True, description="Operation success status")
    message: str = Field("", description="Human-readable status message")
    source_type: KGTypeRelationshipType = Field(..., description="The queried type")
    edges: List[KGTypeRelationshipEdge] = Field(default_factory=list, description="Type-level edges")
    connected_types: List[KGTypeRelationshipType] = Field(default_factory=list, description="Connected types")


class KGTypeRelationshipCreateRequest(BaseModel):
    """Request body for POST /api/graphs/kgtypes/relationships."""
    edge_type: str = Field(..., description="Edge vitaltype URI (e.g. Edge_hasSubKGFrameType)")
    target_uri: str = Field(..., description="URI of the target type to link to")


class KGTypeRelationshipCreateResponse(BaseModel):
    """Response model for POST /api/graphs/kgtypes/relationships."""
    success: bool = Field(True, description="Operation success status")
    message: str = Field("", description="Human-readable status message")
    edge_uri: str = Field("", description="URI of the created edge")
    edge_type: str = Field("", description="Edge vitaltype URI")
    source_uri: str = Field("", description="Source type URI")
    destination_uri: str = Field("", description="Destination type URI")


class KGTypeRelationshipDeleteResponse(BaseModel):
    """Response model for DELETE /api/graphs/kgtypes/relationships."""
    success: bool = Field(True, description="Operation success status")
    message: str = Field("", description="Human-readable status message")
    deleted: bool = Field(False, description="Whether the edge was deleted")
    edge_uri: str = Field("", description="URI of the deleted edge")


class KGTypeDocumentationRequest(BaseModel):
    """Request body for PUT /api/graphs/kgtypes/documentation."""
    content: str = Field(..., description="Markdown documentation content")


class KGTypeDocumentationResponse(BaseModel):
    """Response model for GET /api/graphs/kgtypes/documentation."""
    success: bool = Field(True, description="Operation success status")
    message: str = Field("", description="Human-readable status message")
    type_uri: str = Field("", description="Type URI")
    content: Optional[str] = Field(None, description="Markdown documentation content")
    document_uri: Optional[str] = Field(None, description="KGDocument URI")
    has_documentation: bool = Field(False, description="Whether documentation exists")


class KGTypeDocumentationUpdateResponse(BaseModel):
    """Response model for PUT /api/graphs/kgtypes/documentation."""
    success: bool = Field(True, description="Operation success status")
    message: str = Field("", description="Human-readable status message")
    type_uri: str = Field("", description="Type URI")
    document_uri: str = Field("", description="KGDocument URI")
    created: bool = Field(False, description="Whether a new document was created (vs updated)")


class KGTypeDocumentationDeleteResponse(BaseModel):
    """Response model for DELETE /api/graphs/kgtypes/documentation."""
    success: bool = Field(True, description="Operation success status")
    message: str = Field("", description="Human-readable status message")
    type_uri: str = Field("", description="Type URI")
    deleted: bool = Field(False, description="Whether the documentation was deleted")


class KGTypeSearchResponse(BaseModel):
    """Response model for GET /api/graphs/kgtypes/search."""
    success: bool = Field(True, description="Operation success status")
    message: str = Field("", description="Human-readable status message")
    types: List[Dict[str, Any]] = Field(default_factory=list, description="Matching types")
    count: int = Field(0, description="Number of results on this page")
    total_count: int = Field(0, description="Total matching results across all pages")
    page_size: int = Field(25, description="Page size used")
    offset: int = Field(0, description="Offset used")
    search_mode: str = Field("keyword", description="Search mode used (keyword, fts, vector, hybrid)")
    query: str = Field("", description="Original search query")


class KGTypeDescriptionResponse(BaseModel):
    """Response model for GET /api/graphs/kgtypes/description."""
    type_uri: str = Field(..., description="The KGType URI queried")
    mapping_type: str = Field("kgentity", description="Mapping type used")
    description: Optional[str] = Field(None, description="Type description text")

