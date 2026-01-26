"""KG Frames Model Classes

Pydantic models for KG frame management operations.
"""

from typing import List, Optional, Any, Dict, Union
from pydantic import BaseModel, Field

from .jsonld_model import JsonLdDocument, JsonLdObject
from .api_model import BaseCreateResponse, BaseUpdateResponse, BaseDeleteResponse, BasePaginatedResponse, BaseOperationResponse
from .kgentities_model import SlotCriteria, SortCriteria


class FramesResponse(BasePaginatedResponse):
    """Response model for frames listing."""
    frames: Union[JsonLdObject, JsonLdDocument] = Field(..., description="Single JSON-LD object or JSON-LD document containing frames")
    
    @property
    def success(self) -> bool:
        """Always return True for successful GET responses."""
        return True


class FrameCreateResponse(BaseCreateResponse):
    """Response model for frame creation."""
    slots_created: Optional[int] = Field(None, description="Number of slots created along with frames")
    
    @property
    def frames_created(self) -> int:
        """Alias for created_count to match client test expectations."""
        return self.created_count


class FrameUpdateResponse(BaseUpdateResponse):
    """Response model for frame updates."""
    updated_count: int = Field(0, description="Number of frames updated")
    frames_updated: int = Field(0, description="Number of frames updated (alias for updated_count)")
    slots_updated: Optional[int] = Field(None, description="Number of associated slots updated")
    
    def __init__(self, **data):
        # Set frames_updated to match updated_count if not provided
        if 'frames_updated' not in data and 'updated_count' in data:
            data['frames_updated'] = data['updated_count']
        super().__init__(**data)


class FrameDeleteResponse(BaseDeleteResponse):
    """Response model for frame deletion."""
    frames_deleted: int = Field(..., description="Number of frames deleted (alias for deleted_count)")
    slots_deleted: Optional[int] = Field(None, description="Number of associated slots deleted")
    
    def __init__(self, **data):
        # Set frames_deleted to match deleted_count if not provided
        if 'frames_deleted' not in data and 'deleted_count' in data:
            data['frames_deleted'] = data['deleted_count']
        super().__init__(**data)


# Enhanced Models for Frame Graph Operations

class FrameQueryCriteria(BaseModel):
    """Criteria for frame queries."""
    search_string: Optional[str] = Field(None, description="Search string for frame name/label")
    frame_type: Optional[str] = Field(None, description="Frame type URI to filter by")
    entity_type: Optional[str] = Field(None, description="Entity type URI - frames must belong to entity of this type")
    slot_criteria: Optional[List[SlotCriteria]] = Field(None, description="Slot-based filtering criteria")
    sort_criteria: Optional[List[SortCriteria]] = Field(None, description="Multi-level sorting criteria")


class FrameQueryRequest(BaseModel):
    """Request model for frame queries."""
    criteria: FrameQueryCriteria = Field(..., description="Query criteria")
    page_size: int = Field(10, description="Number of results per page", ge=1, le=100)
    offset: int = Field(0, description="Offset for pagination", ge=0)


class FrameQueryResponse(BasePaginatedResponse):
    """Response model for frame queries."""
    frame_uris: List[str] = Field(..., description="List of matching frame subject URIs")


class FrameGraphResponse(BaseOperationResponse):
    """Response model for frame with optional complete graph."""
    frame: Union[JsonLdObject, JsonLdDocument] = Field(..., description="Single JSON-LD object or JSON-LD document containing the frame")
    complete_graph: Optional[Union[JsonLdObject, JsonLdDocument]] = Field(None, description="Complete frame graph when include_frame_graph=True")


class FrameGraphDeleteResponse(BaseDeleteResponse):
    """Response model for frame graph deletion."""
    deleted_graph_components: Optional[Dict[str, int]] = Field(None, description="Count of deleted components by type")


class FramesGraphResponse(BasePaginatedResponse):
    """Enhanced response model for frames with optional graph data."""
    frames: Union[JsonLdObject, JsonLdDocument] = Field(..., description="Single JSON-LD object or JSON-LD document containing frames")
    complete_graphs: Optional[Dict[str, Union[JsonLdObject, JsonLdDocument]]] = Field(None, description="Complete graphs by frame URI when include_frame_graph=True")


# Slot Response Models

class SlotCreateResponse(BaseCreateResponse):
    """Response model for slot creation."""
    slots_created: int = Field(..., description="Number of slots created (alias for created_count)")
    
    def __init__(self, **data):
        # Set slots_created to match created_count if not provided
        if 'slots_created' not in data and 'created_count' in data:
            data['slots_created'] = data['created_count']
        super().__init__(**data)


class SlotUpdateResponse(BaseUpdateResponse):
    """Response model for slot updates."""
    pass


class SlotDeleteResponse(BaseDeleteResponse):
    """Response model for slot deletion."""
    pass


# Enhanced Frame Graph Retrieval Models

class FrameValidationResults(BaseModel):
    """Validation results for frame ownership checks."""
    valid_frames: int = Field(..., description="Number of frames that belong to the entity")
    invalid_frames: int = Field(..., description="Number of frames that do not belong to the entity")
    invalid_frame_uris: List[str] = Field(..., description="List of frame URIs that do not belong to the entity")


class FrameErrorInfo(BaseModel):
    """Error information for invalid frame access."""
    error: str = Field(..., description="Error type identifier")
    message: str = Field(..., description="Human-readable error message")
    frame_uri: str = Field(..., description="The frame URI that caused the error")
    entity_uri: str = Field(..., description="The entity URI that was being accessed")


class FrameGraphsResponse(BaseModel):
    """Enhanced response model for specific frame graph retrieval with frame_uris parameter."""
    frame_graphs: Dict[str, Union[JsonLdDocument, FrameErrorInfo, Dict[str, Any]]] = Field(
        ..., 
        description="Dictionary mapping frame URIs to their complete graphs (JsonLD documents) or error information"
    )
    entity_uri: str = Field(..., description="The entity URI that owns the frames")
    requested_frames: int = Field(..., description="Total number of frame URIs requested")
    retrieved_frames: int = Field(..., description="Number of frames successfully retrieved (excluding errors)")
    validation_results: FrameValidationResults = Field(..., description="Frame ownership validation results")