"""Base API Model Classes

Shared Pydantic base models for common response patterns across VitalGraph endpoints.
These models provide consistent structure and reduce code duplication.
"""

from typing import Dict, List, Any, Optional, Union
from pydantic import BaseModel, Field

from .quad_model import Quad, QuadRequest, QuadResponse, QuadResultsResponse
from .result_status import ResultStatus, OperationStatus


class BasePaginatedResponse(ResultStatus):
    """Base model for paginated responses.

    Carries the unified success/status/message contract so query/list responses can
    report outcome in-body. ``status`` defaults to FOUND; set EMPTY when nothing
    matches. ``success`` is derived from ``status``.
    """
    status: OperationStatus = Field(
        OperationStatus.FOUND, description="Outcome discriminator (FOUND/EMPTY/...)"
    )
    total_count: int = Field(..., description="Total number of items available")
    page_size: int = Field(..., description="Number of items per page")
    offset: int = Field(..., description="Offset for pagination")


class BaseQuadListResponse(QuadResponse):
    """Base model for paginated quad list responses with optional extra metadata."""
    pagination: Optional[Dict[str, Any]] = Field(None, description="Additional pagination information")
    meta: Optional[Dict[str, Any]] = Field(None, description="Response metadata")


class BaseCreateResponse(ResultStatus):
    """Base model for creation responses.

    success/status/message come from ResultStatus (``success`` derived). ``status``
    defaults to CREATED; set explicitly (CREATED / ALREADY_EXISTS / STORE_FAILED /
    PARTIAL / INVALID_REQUEST) at each real outcome branch. ``message`` is now
    optional (defaults "") — it was previously required.
    """
    status: OperationStatus = Field(
        OperationStatus.CREATED, description="Outcome discriminator (CREATED/ALREADY_EXISTS/...)"
    )
    created_count: int = Field(..., description="Number of items created")
    created_uris: List[str] = Field(..., description="URIs of the created items")


class BaseUpdateResponse(ResultStatus):
    """Base model for update responses.

    ``status`` defaults to UPDATED; set NOT_FOUND when the target URI does not exist,
    STORE_FAILED on a describable write failure. Update is potentially a batch
    operation, so the canonical identity fields are ``updated_count`` +
    ``updated_uris`` (§6.1); ``updated_uri`` (singular) is retained for
    backward-compatibility with existing single-item callers.
    """
    status: OperationStatus = Field(
        OperationStatus.UPDATED, description="Outcome discriminator (UPDATED/NOT_FOUND/...)"
    )
    updated_count: int = Field(0, description="Number of items updated")
    updated_uris: Optional[List[str]] = Field(None, description="URIs of the updated items")
    updated_uri: Optional[str] = Field(None, description="URI of the updated item (singular, back-compat; None on error)")


class BaseDeleteResponse(ResultStatus):
    """Base model for deletion responses.

    ``status`` defaults to DELETED; use NO_OP when the URI was already absent,
    STORE_FAILED on a describable write failure.
    """
    status: OperationStatus = Field(
        OperationStatus.DELETED, description="Outcome discriminator (DELETED/NO_OP/...)"
    )
    deleted_count: int = Field(..., description="Number of items deleted")
    deleted_uris: Optional[List[str]] = Field(None, description="URIs of the deleted items (when available)")


class BaseOperationResponse(ResultStatus):
    """Base model for general operation responses."""
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
    """Base model for simple list responses."""
    items: List[Dict[str, Any]] = Field(..., description="List of items")
    total_count: int = Field(..., description="Total number of items available")
    page_size: int = Field(..., description="Number of items per page")
    offset: int = Field(..., description="Offset for pagination")