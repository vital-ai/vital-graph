"""KG Queries Model Classes

Pydantic models for KG entity-to-entity query operations.
Single endpoint with query criteria that specifies relation or frame query type.
"""

from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field

from .kgentities_model import EntityQueryCriteria, FrameCriteria, SlotCriteria
from .api_model import BasePaginatedResponse


class KGQueryCriteria(BaseModel):
    """Criteria for KG entity-to-entity queries."""
    
    # Query type specification
    query_type: str = Field(..., description="Query type: 'relation' or 'frame'")
    
    # Source entity specification
    source_entity_criteria: Optional[EntityQueryCriteria] = Field(None, description="Criteria for source entities")
    source_entity_uris: Optional[List[str]] = Field(None, description="Specific source entity URIs")
    
    # Destination entity specification  
    destination_entity_criteria: Optional[EntityQueryCriteria] = Field(None, description="Criteria for destination entities")
    destination_entity_uris: Optional[List[str]] = Field(None, description="Specific destination entity URIs")
    
    # Relation-specific criteria (only used when query_type="relation")
    relation_type_uris: Optional[List[str]] = Field(None, description="Relation type URNs to match")
    direction: str = Field("outgoing", description="Direction: outgoing, incoming, bidirectional")
    
    # Frame/slot filtering for relation participants (only used when query_type="relation")
    source_frame_criteria: Optional[List[FrameCriteria]] = Field(None, description="Frame/slot criteria for source entities in relation queries")
    destination_frame_criteria: Optional[List[FrameCriteria]] = Field(None, description="Frame/slot criteria for destination entities in relation queries")
    
    # Frame-specific criteria (only used when query_type="frame")
    frame_criteria: Optional[List[FrameCriteria]] = Field(None, description="Frame criteria with nested slot criteria (entity->frame->slot paths)")
    
    # Query constraints
    exclude_self_connections: bool = Field(True, description="Exclude connections from entity to itself")


class KGQueryRequest(BaseModel):
    """Request model for KG queries."""
    criteria: KGQueryCriteria = Field(..., description="Query criteria")
    page_size: int = Field(10, description="Number of results per page", ge=1, le=100)
    offset: int = Field(0, description="Offset for pagination", ge=0)


class RelationConnection(BaseModel):
    """Represents a relation-based connection between two entities."""
    source_entity_uri: str = Field(..., description="Source entity URI")
    destination_entity_uri: str = Field(..., description="Destination entity URI")
    relation_edge_uri: str = Field(..., description="Relation edge URI")
    relation_type_uri: str = Field(..., description="Relation type URN")


class FrameConnection(BaseModel):
    """Represents a frame-based connection between two entities."""
    source_entity_uri: str = Field(..., description="Source entity URI")
    destination_entity_uri: str = Field(..., description="Destination entity URI")
    shared_frame_uri: str = Field(..., description="Shared frame URI")
    frame_type_uri: str = Field(..., description="Frame type URI")


class KGQueryResponse(BasePaginatedResponse):
    """Response model for KG queries."""
    query_type: str = Field(..., description="Query type that was executed: 'relation' or 'frame'")
    relation_connections: Optional[List[RelationConnection]] = Field(None, description="Relation connections (when query_type='relation')")
    frame_connections: Optional[List[FrameConnection]] = Field(None, description="Frame connections (when query_type='frame')")


# Optional: Statistics and utility models

class KGQueryStatsResponse(BaseModel):
    """Response model for KG query statistics."""
    total_entities: int = Field(..., description="Total entities in graph")
    total_relations: int = Field(..., description="Total relations in graph")
    total_frames: int = Field(..., description="Total frames in graph")
    relation_connections_count: int = Field(..., description="Count of relation-based connections")
    frame_connections_count: int = Field(..., description="Count of frame-based connections")
