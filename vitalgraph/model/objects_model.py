"""Graph Objects Model Classes

Pydantic models for graph object management operations.
"""

from typing import List, Union
from pydantic import BaseModel, Field

from .jsonld_model import JsonLdDocument, JsonLdObject
from .api_model import BaseCreateResponse, BaseUpdateResponse, BaseDeleteResponse, BasePaginatedResponse


class ObjectsResponse(BasePaginatedResponse):
    """Response model for objects listing (single or multiple objects)."""
    objects: Union[JsonLdObject, JsonLdDocument] = Field(..., description="JSON-LD object or document (single or multiple objects)")


class SingleObjectResponse(BaseModel):
    """Response model for single object retrieval."""
    object: JsonLdObject = Field(..., description="Single JSON-LD object")


class ObjectCreateResponse(BaseCreateResponse):
    """Response model for object creation."""
    pass


class ObjectUpdateResponse(BaseUpdateResponse):
    """Response model for object updates."""
    pass


class ObjectDeleteResponse(BaseDeleteResponse):
    """Response model for object deletion."""
    pass