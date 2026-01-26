"""KG Relations Model Classes

Pydantic models for KG relation management operations.
Following established VitalGraph patterns for consistent API design.
"""

from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field

from .jsonld_model import JsonLdDocument, JsonLdObject
from .api_model import BaseCreateResponse, BaseUpdateResponse, BaseDeleteResponse, BasePaginatedResponse


class RelationsResponse(BasePaginatedResponse):
    """Response model for relations listing."""
    relations: Union[JsonLdObject, JsonLdDocument] = Field(..., description="Single JSON-LD object or JSON-LD document containing relations")


class RelationResponse(BaseModel):
    """Response model for single relation."""
    relation: Union[JsonLdObject, JsonLdDocument] = Field(..., description="Single JSON-LD object or JSON-LD document containing the relation")


class RelationCreateResponse(BaseCreateResponse):
    """Response model for relation creation."""
    pass


class RelationUpdateResponse(BaseUpdateResponse):
    """Response model for relation updates."""
    pass


class RelationUpsertResponse(BaseCreateResponse):
    """Response model for relation upsert."""
    pass


class RelationDeleteRequest(BaseModel):
    """Request model for relation deletion."""
    relation_uris: List[str] = Field(..., description="List of relation URIs to delete")


class RelationDeleteResponse(BaseDeleteResponse):
    """Response model for relation deletion."""
    pass


class RelationQueryCriteria(BaseModel):
    """Criteria for relation queries."""
    entity_source_uri: Optional[str] = Field(None, description="Source entity URI filter")
    entity_destination_uri: Optional[str] = Field(None, description="Destination entity URI filter")
    relation_type_uri: Optional[str] = Field(None, description="Relation type URN filter")
    direction: str = Field("all", description="Direction filter: all, incoming, outgoing")
    search_string: Optional[str] = Field(None, description="Search in relation properties")


class RelationQueryRequest(BaseModel):
    """Request model for relation queries."""
    criteria: RelationQueryCriteria = Field(..., description="Query criteria")
    page_size: int = Field(10, description="Number of results per page", ge=1, le=100)
    offset: int = Field(0, description="Offset for pagination", ge=0)


class RelationQueryResponse(BasePaginatedResponse):
    """Response model for relation queries."""
    relation_uris: List[str] = Field(..., description="List of matching relation URIs")
