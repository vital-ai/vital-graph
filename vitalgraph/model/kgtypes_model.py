"""KG Types Model Classes

Pydantic models for KG type management operations with Union support for 
both single JSON-LD objects and JSON-LD documents.
"""

from typing import Dict, List, Any, Optional, Union
from pydantic import BaseModel, Field, validator

from .jsonld_model import JsonLdDocument, JsonLdObject, JsonLdRequest
from .api_model import BasePaginatedResponse, BaseCreateResponse, BaseUpdateResponse, BaseDeleteResponse


class KGTypeFilter(BaseModel):
    """Filter criteria for KGType queries."""
    search_text: Optional[str] = Field(None, description="Text to search for in KGType properties")
    subject_uri: Optional[str] = Field(None, description="Specific subject URI to filter by")
    vitaltype_filter: Optional[str] = Field(None, description="Filter by vitaltype URI")


class KGTypeRequest(BaseModel):
    """
    Universal request model supporting both single and multiple KGType operations.
    Uses JsonLdRequest discriminated union to automatically handle JsonLdObject or JsonLdDocument.
    """
    space_id: str = Field(..., description="Space identifier")
    graph_id: str = Field(..., description="Graph identifier")
    data: JsonLdRequest = Field(
        ..., 
        description="KGType data - discriminated union automatically handles single object (JsonLdObject) or multiple objects (JsonLdDocument)"
    )
    
    @validator('data')
    def validate_jsonld_format(cls, v):
        """Custom validation to ensure proper JSON-LD format usage."""
        if isinstance(v, JsonLdObject):
            # Single object validation
            if not v.id or not v.type:
                raise ValueError("JsonLdObject must have @id and @type fields")
        elif isinstance(v, JsonLdDocument):
            # Multiple object validation
            if not v.graph or len(v.graph) == 0:
                raise ValueError("JsonLdDocument must have non-empty @graph array")
            for obj in v.graph:
                if not obj.get('@id') or not obj.get('@type'):
                    raise ValueError("Each object in @graph must have @id and @type")
        return v


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
    data: Union[JsonLdDocument, List[str]] = Field(
        ..., 
        description="KGType URIs to delete - either JsonLdDocument or list of URIs"
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
    data: Optional[Union[JsonLdObject, JsonLdDocument]] = Field(
        None, 
        description="Response data - format matches request format"
    )
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


class KGTypeGetResponse(BaseModel):
    """Response model for individual KGType retrieval operations."""
    success: bool = Field(..., description="Operation success status")
    message: str = Field(..., description="Human-readable status message")
    data: Optional[JsonLdObject] = Field(None, description="Individual KGType as JSON-LD object")

class KGTypeListResponse(BasePaginatedResponse):
    """Response model for KGType listing operations."""
    success: bool = Field(..., description="Operation success status")
    data: Optional[Union[JsonLdObject, JsonLdDocument]] = Field(None, description="KGTypes as JSON-LD - single object or document with multiple")
    pagination: Optional[Dict[str, Any]] = Field(None, description="Pagination metadata")