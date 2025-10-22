"""KG Frames Model Classes

Pydantic models for KG frame management operations.
"""

from typing import List
from pydantic import Field

from .jsonld_model import JsonLdDocument
from .api_model import BaseCreateResponse, BaseUpdateResponse, BaseDeleteResponse, BasePaginatedResponse


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