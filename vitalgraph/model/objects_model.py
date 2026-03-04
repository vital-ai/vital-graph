"""Graph Objects Model Classes

Pydantic models for graph object management operations.
"""

from typing import List, Optional
from pydantic import BaseModel, Field

from .api_model import BaseCreateResponse, BaseUpdateResponse, BaseDeleteResponse


class ObjectCreateResponse(BaseCreateResponse):
    """Response model for object creation."""
    pass


class ObjectUpdateResponse(BaseUpdateResponse):
    """Response model for object updates."""
    pass


class ObjectDeleteResponse(BaseDeleteResponse):
    """Response model for object deletion."""
    pass