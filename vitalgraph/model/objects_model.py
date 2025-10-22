"""Graph Objects Model Classes

Pydantic models for graph object management operations.
"""

from typing import List
from pydantic import Field

from .jsonld_model import JsonLdDocument
from .api_model import BaseCreateResponse, BaseUpdateResponse, BaseDeleteResponse, BasePaginatedResponse


class ObjectsResponse(BasePaginatedResponse):
    """Response model for objects listing."""
    objects: JsonLdDocument = Field(..., description="JSON-LD document containing objects")


class ObjectCreateResponse(BaseCreateResponse):
    """Response model for object creation."""
    pass


class ObjectUpdateResponse(BaseUpdateResponse):
    """Response model for object updates."""
    pass


class ObjectDeleteResponse(BaseDeleteResponse):
    """Response model for object deletion."""
    pass