"""Triples Model Classes

Pydantic models for RDF triple management operations.
"""

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

from .jsonld_model import JsonLdDocument
from .api_model import BaseJsonLdResponse, BaseOperationResponse


class TripleListRequest(BaseModel):
    """Request model for operations on JSON-LD documents."""
    document: JsonLdDocument = Field(..., description="JSON-LD document containing RDF triples")


class TripleListResponse(BaseJsonLdResponse):
    """Response model for triple listing operations using JSON-LD."""
    pass


class TripleOperationResponse(BaseOperationResponse):
    """Response model for triple operations (add/delete)."""
    deleted_count: Optional[int] = Field(None, description="Number of triples deleted")
    added_count: Optional[int] = Field(None, description="Number of triples added")