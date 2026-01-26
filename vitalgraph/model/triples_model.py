"""Triples Model Classes

Pydantic models for RDF triple management operations.
"""

from typing import Dict, Any, Optional, Union
from pydantic import BaseModel, Field

from .jsonld_model import JsonLdDocument, JsonLdObject, JsonLdRequest
from .api_model import BaseJsonLdResponse, BaseOperationResponse


class TripleListRequest(BaseModel):
    """Request model for operations on JSON-LD documents."""
    document: JsonLdRequest = Field(..., description="JSON-LD request (discriminated union automatically handles single object or document with multiple triples)")


class TripleListResponse(BaseJsonLdResponse):
    """Response model for triple listing operations using JSON-LD."""
    pass


class TripleOperationResponse(BaseOperationResponse):
    """Response model for triple operations (add/delete)."""
    deleted_count: Optional[int] = Field(None, description="Number of triples deleted")
    added_count: Optional[int] = Field(None, description="Number of triples added")