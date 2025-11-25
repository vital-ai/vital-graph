"""KG Frames Model Classes

Pydantic models for KG frame management operations.
"""

from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field

from .jsonld_model import JsonLdDocument
from .api_model import BaseCreateResponse, BaseUpdateResponse, BaseDeleteResponse, BasePaginatedResponse
from .kgentities_model import SlotCriteria


class FramesResponse(BasePaginatedResponse):
    """Response model for frames listing."""
    frames: JsonLdDocument = Field(..., description="JSON-LD document containing frames")


class FrameCreateResponse(BaseCreateResponse):
    """Response model for frame creation."""
    pass


class FrameUpdateResponse(BaseUpdateResponse):
    """Response model for frame updates."""
    pass


class FrameDeleteResponse(BaseDeleteResponse):
    """Response model for frame deletion."""
    pass


# Enhanced Models for Frame Graph Operations

class FrameQueryCriteria(BaseModel):
    """Criteria for frame queries."""
    search_string: Optional[str] = Field(None, description="Search string for frame name/label")
    frame_type: Optional[str] = Field(None, description="Frame type URI to filter by")
    entity_type: Optional[str] = Field(None, description="Entity type URI - frames must belong to entity of this type")
    slot_criteria: Optional[List[SlotCriteria]] = Field(None, description="Slot-based filtering criteria")


class FrameQueryRequest(BaseModel):
    """Request model for frame queries."""
    criteria: FrameQueryCriteria = Field(..., description="Query criteria")
    page_size: int = Field(10, description="Number of results per page", ge=1, le=100)
    offset: int = Field(0, description="Offset for pagination", ge=0)


class FrameQueryResponse(BasePaginatedResponse):
    """Response model for frame queries."""
    frame_uris: List[str] = Field(..., description="List of matching frame subject URIs")


class FrameGraphResponse(BaseModel):
    """Response model for frame with optional complete graph."""
    frame: JsonLdDocument = Field(..., description="JSON-LD document containing the frame")
    complete_graph: Optional[JsonLdDocument] = Field(None, description="Complete frame graph when include_frame_graph=True")


class FrameGraphDeleteResponse(BaseDeleteResponse):
    """Response model for frame graph deletion."""
    deleted_graph_components: Optional[Dict[str, int]] = Field(None, description="Count of deleted components by type")


class FramesGraphResponse(BasePaginatedResponse):
    """Enhanced response model for frames with optional graph data."""
    frames: JsonLdDocument = Field(..., description="JSON-LD document containing frames")
    complete_graphs: Optional[Dict[str, JsonLdDocument]] = Field(None, description="Complete graphs by frame URI when include_frame_graph=True")


# Slot Response Models

class SlotCreateResponse(BaseCreateResponse):
    """Response model for slot creation."""
    pass


class SlotUpdateResponse(BaseUpdateResponse):
    """Response model for slot updates."""
    pass


class SlotDeleteResponse(BaseDeleteResponse):
    """Response model for slot deletion."""
    pass