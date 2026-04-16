"""KG Entities Model Classes

Pydantic models for KG entity operations including entities, frames, and slots.
"""

from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field

from .quad_model import QuadResponse, QuadResultsResponse
from .api_model import BaseCreateResponse, BaseUpdateResponse, BaseDeleteResponse, BasePaginatedResponse


class EntityCreateResponse(BaseCreateResponse):
    """Response model for entity creation."""
    pass


class EntityUpdateResponse(BaseUpdateResponse):
    """Response model for entity updates."""
    pass


class EntityDeleteResponse(BaseDeleteResponse):
    """Response model for entity deletion."""
    pass


class EntityFramesResponse(QuadResponse):
    """Response model for entity frames with pagination support (paginated quad results)."""
    frame_uris: Optional[List[str]] = Field(None, description="List of frame URIs for simple responses")


class EntityFramesMultiResponse(BaseModel):
    """Response model for entity frames - multi URI case returns map of entity URI -> frame URI list."""
    entity_frame_map: Dict[str, List[str]]


# Enhanced Models for Graph Operations

class QueryFilter(BaseModel):
    """Simple property-based filter for entity queries."""
    property_name: str = Field(..., description="Property name to filter by")
    operator: str = Field(..., description="Filter operator: equals, not_equals, contains, exists, gt, lt, gte, lte")
    value: Optional[Any] = Field(None, description="Value to compare against (not needed for 'exists' operator)")


class SlotCriteria(BaseModel):
    """Criteria for slot filtering in KG queries."""
    slot_type: Optional[str] = Field(None, description="Slot type URI to filter by")
    slot_class_uri: Optional[str] = Field(None, description="Underlying slot class URI (e.g., KGTextSlot, KGDoubleSlot) to determine value property")
    value: Optional[Any] = Field(None, description="Value to compare against")
    comparator: Optional[str] = Field(None, description="Comparison operator: eq, ne, gt, lt, gte, lte, contains, exists, not_exists, is_empty")


class FrameCriteria(BaseModel):
    """Criteria for frame filtering in KG queries.
    
    Supports hierarchical frame structures:
    - frame_type filters the frame at this level
    - slot_criteria filters slots within this frame
    - frame_criteria allows recursive nesting for child frames (e.g., parent→child→grandchild)
    
    Example flat structure: entity→frame→slot
    Example hierarchical: entity→parent_frame→child_frame→slot
    """
    frame_type: Optional[str] = Field(None, description="Frame type URI to filter by")
    negate: bool = Field(False, description="When True, negate this frame criterion — match entities/frames that do NOT have this frame pattern")
    slot_criteria: Optional[List[SlotCriteria]] = Field(None, description="Slot criteria within this frame")
    frame_criteria: Optional[List['FrameCriteria']] = Field(None, description="Nested frame criteria for hierarchical frame structures (parent→child frames)")


class SortCriteria(BaseModel):
    """Criteria for sorting in KG queries."""
    sort_type: str = Field(..., description="Sort type: frame_slot, entity_frame_slot, or property")
    slot_type: Optional[str] = Field(None, description="Slot type URI for sorting (required for frame_slot and entity_frame_slot)")
    frame_type: Optional[str] = Field(None, description="Frame type URI (required for entity_frame_slot sorting)")
    property_uri: Optional[str] = Field(None, description="Property URI for property-based sorting")
    sort_order: str = Field("asc", description="Sort order: asc or desc")
    priority: int = Field(1, description="Sort priority: 1=primary, 2=secondary, 3=tertiary, etc.")


class EntityQueryCriteria(BaseModel):
    """Criteria for entity queries."""
    search_string: Optional[str] = Field(None, description="Search string for entity name/label")
    entity_type: Optional[str] = Field(None, description="Entity type URI to filter by")
    frame_type: Optional[str] = Field(None, description="Frame type URI - entities must have frame of this type")
    slot_criteria: Optional[List[SlotCriteria]] = Field(None, description="Slot-based filtering criteria")
    sort_criteria: Optional[List[SortCriteria]] = Field(None, description="Multi-level sorting criteria")
    filters: Optional[List[QueryFilter]] = Field(None, description="Property-based filters")


class EntityQueryRequest(BaseModel):
    """Request model for entity queries."""
    criteria: EntityQueryCriteria = Field(..., description="Query criteria")
    page_size: int = Field(10, description="Number of results per page", ge=1, le=100)
    offset: int = Field(0, description="Offset for pagination", ge=0)


class EntityQueryResponse(BasePaginatedResponse):
    """Response model for entity queries."""
    entity_uris: List[str] = Field(..., description="List of matching entity subject URIs")


class EntityGraphResponse(QuadResultsResponse):
    """Response model for entity with optional complete graph (non-paginated quad results)."""
    complete_graph: Optional[QuadResultsResponse] = Field(None, description="Complete entity graph when include_entity_graph=True")


class EntityGraphDeleteResponse(BaseDeleteResponse):
    """Response model for entity graph deletion."""
    deleted_graph_components: Optional[Dict[str, int]] = Field(None, description="Count of deleted components by type")


# Enhanced Response Models

class EntitiesGraphResponse(QuadResponse):
    """Enhanced response model for entities with optional graph data (paginated quad results)."""
    complete_graphs: Optional[Dict[str, QuadResultsResponse]] = Field(None, description="Complete graphs by entity URI when include_entity_graph=True")


# Update forward references for recursive models
FrameCriteria.model_rebuild()