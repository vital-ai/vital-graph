"""KG Entities Model Classes

Pydantic models for KG entity management operations.
"""

from typing import Dict, List
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