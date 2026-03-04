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

