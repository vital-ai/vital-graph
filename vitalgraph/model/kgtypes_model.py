"""KG Types Model Classes

Pydantic models for KG type management operations.
"""

from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field

from .jsonld_model import JsonLdDocument
from .api_model import BasePaginatedResponse, BaseCreateResponse, BaseUpdateResponse, BaseDeleteResponse


class KGTypeFilter(BaseModel):
    """Filter criteria for KGType queries."""
    search_text: Optional[str] = Field(None, description="Text to search for in KGType properties")
    subject_uri: Optional[str] = Field(None, description="Specific subject URI to filter by")
    vitaltype_filter: Optional[str] = Field(None, description="Filter by vitaltype URI")


class KGTypeListRequest(BaseModel):
    """Request model for operations on JSON-LD documents containing KG types."""
    document: JsonLdDocument = Field(..., description="JSON-LD document containing KG types")


class KGTypeListResponse(BasePaginatedResponse):
    """Response model for KG type listing operations using JSON-LD."""
    types: JsonLdDocument = Field(..., description="JSON-LD document containing KG types")


class KGTypeCreateResponse(BaseCreateResponse):
    """Response model for KG type creation operations."""
    pass


class KGTypeUpdateResponse(BaseUpdateResponse):
    """Response model for KG type update operations."""
    pass


class KGTypeDeleteResponse(BaseDeleteResponse):
    """Response model for KG type deletion operations."""
    pass