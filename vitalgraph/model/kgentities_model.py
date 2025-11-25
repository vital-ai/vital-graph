"""KG Entities Model Classes

Pydantic models for KG entity management operations.
"""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from .jsonld_model import JsonLdDocument
from .api_model import BaseCreateResponse, BaseUpdateResponse, BaseDeleteResponse, BasePaginatedResponse


class EntitiesResponse(BasePaginatedResponse):
    """Response model for entities listing."""
    entities: JsonLdDocument = Field(..., description="JSON-LD document containing entities")


class EntityCreateResponse(BaseCreateResponse):
    """Response model for entity creation."""
    pass


class EntityUpdateResponse(BaseUpdateResponse):
    """Response model for entity updates."""
    pass


class EntityDeleteResponse(BaseDeleteResponse):
    """Response model for entity deletion."""
    pass


class EntityFramesResponse(BaseModel):
    """Response model for entity frames - single URI case returns list of frame URIs."""
    frame_uris: List[str]


class EntityFramesMultiResponse(BaseModel):
    """Response model for entity frames - multi URI case returns map of entity URI -> frame URI list."""
    entity_frame_map: Dict[str, List[str]]


# Enhanced Models for Graph Operations

class SlotCriteria(BaseModel):
    """Criteria for slot filtering in KG queries."""
    slot_type: Optional[str] = Field(None, description="Slot type URI to filter by")
    value: Optional[Any] = Field(None, description="Value to compare against")
    comparator: Optional[str] = Field(None, description="Comparison operator: eq, ne, gt, lt, gte, lte, contains, exists")


class EntityQueryCriteria(BaseModel):
    """Criteria for entity queries."""
    search_string: Optional[str] = Field(None, description="Search string for entity name/label")
    entity_type: Optional[str] = Field(None, description="Entity type URI to filter by")
    frame_type: Optional[str] = Field(None, description="Frame type URI - entities must have frame of this type")
    slot_criteria: Optional[List[SlotCriteria]] = Field(None, description="Slot-based filtering criteria")


class EntityQueryRequest(BaseModel):
    """Request model for entity queries."""
    criteria: EntityQueryCriteria = Field(..., description="Query criteria")
    page_size: int = Field(10, description="Number of results per page", ge=1, le=100)
    offset: int = Field(0, description="Offset for pagination", ge=0)


class EntityQueryResponse(BasePaginatedResponse):
    """Response model for entity queries."""
    entity_uris: List[str] = Field(..., description="List of matching entity subject URIs")


class EntityGraphResponse(BaseModel):
    """Response model for entity with optional complete graph."""
    entity: JsonLdDocument = Field(..., description="JSON-LD document containing the entity")
    complete_graph: Optional[JsonLdDocument] = Field(None, description="Complete entity graph when include_entity_graph=True")


class EntityGraphDeleteResponse(BaseDeleteResponse):
    """Response model for entity graph deletion."""
    deleted_graph_components: Optional[Dict[str, int]] = Field(None, description="Count of deleted components by type")


# Enhanced Response Models

class EntitiesGraphResponse(BasePaginatedResponse):
    """Enhanced response model for entities with optional graph data."""
    entities: JsonLdDocument = Field(..., description="JSON-LD document containing entities")
    complete_graphs: Optional[Dict[str, JsonLdDocument]] = Field(None, description="Complete graphs by entity URI when include_entity_graph=True")