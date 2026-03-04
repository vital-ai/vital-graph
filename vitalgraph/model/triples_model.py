"""Triples Model Classes

Pydantic models for RDF triple management operations.
"""

from typing import Dict, Any, Optional, Union
from pydantic import BaseModel, Field

from .quad_model import Quad, QuadRequest
from .api_model import BaseQuadListResponse, BaseOperationResponse


class TripleListRequest(QuadRequest):
    """Request model for triple/quad operations."""
    pass


class TripleListResponse(BaseQuadListResponse):
    """Response model for triple listing operations."""
    pass


class TripleOperationResponse(BaseOperationResponse):
    """Response model for triple operations (add/delete)."""
    deleted_count: Optional[int] = Field(None, description="Number of triples deleted")
    added_count: Optional[int] = Field(None, description="Number of triples added")