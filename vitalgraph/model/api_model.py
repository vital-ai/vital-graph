"""Base API Model Classes

Shared Pydantic base models for common response patterns across VitalGraph endpoints.
These models provide consistent structure and reduce code duplication.
"""

from typing import Dict, List, Any, Optional, Union
from pydantic import BaseModel, Field

from .jsonld_model import JsonLdDocument, JsonLdObject


class BasePaginatedResponse(BaseModel):
    """Base model for paginated responses."""
    total_count: int = Field(..., description="Total number of items available")
    page_size: int = Field(..., description="Number of items per page")
    offset: int = Field(..., description="Offset for pagination")


class BaseJsonLdResponse(BasePaginatedResponse):
    """Base model for JSON-LD paginated responses."""
    data: Union[JsonLdObject, JsonLdDocument] = Field(..., description="Single JSON-LD object or JSON-LD document containing the response data")
    pagination: Optional[Dict[str, Any]] = Field(None, description="Additional pagination information")
    meta: Optional[Dict[str, Any]] = Field(None, description="Response metadata")


class BaseCreateResponse(BaseModel):
    """Base model for creation responses."""
    success: bool = Field(True, description="Whether the operation was successful")
    message: str = Field(..., description="Success message describing the creation operation")
    created_count: int = Field(..., description="Number of items created")
    created_uris: List[str] = Field(..., description="URIs of the created items")


class BaseUpdateResponse(BaseModel):
    """Base model for update responses."""
    success: bool = Field(True, description="Whether the operation was successful")
    message: str = Field(..., description="Success message describing the update operation")
    updated_uri: Optional[str] = Field(None, description="URI of the updated item (None on error)")


class BaseDeleteResponse(BaseModel):
    """Base model for deletion responses."""
    success: bool = Field(True, description="Whether the operation was successful")
    message: str = Field(..., description="Success message describing the deletion operation")
    deleted_count: int = Field(..., description="Number of items deleted")
    deleted_uris: Optional[List[str]] = Field(None, description="URIs of the deleted items (when available)")


class BaseOperationResponse(BaseModel):
    """Base model for general operation responses."""
    success: bool = Field(..., description="Whether the operation was successful")
    message: str = Field(..., description="Operation result message")
    affected_count: Optional[int] = Field(None, description="Number of items affected by the operation")


class BaseJobResponse(BaseModel):
    """Base model for job-related responses."""
    job_id: str = Field(..., description="Unique job identifier")
    status: str = Field(..., description="Current job status")
    message: str = Field(..., description="Job status message")
    progress_percent: Optional[float] = Field(None, description="Job completion percentage (0-100)")
    started_time: Optional[str] = Field(None, description="Job start timestamp")
    completed_time: Optional[str] = Field(None, description="Job completion timestamp")
    error_message: Optional[str] = Field(None, description="Error message if job failed")


class BaseListResponse(BaseModel):
    """Base model for simple list responses without JSON-LD."""
    items: List[Dict[str, Any]] = Field(..., description="List of items")
    total_count: int = Field(..., description="Total number of items available")
    page_size: int = Field(..., description="Number of items per page")
    offset: int = Field(..., description="Offset for pagination")