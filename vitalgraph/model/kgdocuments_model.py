"""
Pydantic models for KGDocument segmentation endpoints.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Segmentation request/response
# ---------------------------------------------------------------------------

class SegmentDocumentRequest(BaseModel):
    """Request to segment a KGDocument."""

    document_uri: str = Field(..., description="URI of the KGDocument to segment")
    segment_method_uri: Optional[str] = Field(
        None,
        description="Segmentation method URI. If None, auto-detects based on content."
    )
    max_segment_tokens: int = Field(1024, description="Maximum tokens per segment")
    min_segment_tokens: int = Field(50, description="Minimum tokens per segment")
    overlap_tokens: int = Field(0, description="Token overlap between segments")


class SegmentDocumentResponse(BaseModel):
    """Response from segmenting a KGDocument."""

    success: bool = True
    message: str = ""
    document_uri: str = ""
    parent_copy_uri: str = ""
    method_uri: str = ""
    segment_count: int = 0
    segment_uris: List[str] = Field(default_factory=list)
    job_id: Optional[int] = Field(None, description="Background job ID (when async)")
    async_mode: bool = Field(False, description="True if enqueued for background processing")


# ---------------------------------------------------------------------------
# Segmentation config CRUD
# ---------------------------------------------------------------------------

class SegmentationConfigRequest(BaseModel):
    """Request to create/update a segmentation config."""

    document_type_uri: str = Field(..., description="KGDocumentType URI to match")
    segment_method_uri: str = Field(..., description="Segmentation method URI to apply")
    max_segment_tokens: int = Field(1024)
    min_segment_tokens: int = Field(50)
    overlap_tokens: int = Field(0)
    enabled: bool = Field(True)
    auto_vectorize: bool = Field(True)


class SegmentationConfigResponse(BaseModel):
    """Single segmentation config entry."""

    config_id: int
    document_type_uri: str
    segment_method_uri: str
    max_segment_tokens: int = 1024
    min_segment_tokens: int = 50
    overlap_tokens: int = 0
    enabled: bool = True
    auto_vectorize: bool = True
    created_time: Optional[str] = None


class SegmentationConfigListResponse(BaseModel):
    """List of segmentation configs."""

    configs: List[SegmentationConfigResponse] = Field(default_factory=list)
    total_count: int = 0


# ---------------------------------------------------------------------------
# KGDocument list/detail (for future document CRUD endpoint)
# ---------------------------------------------------------------------------

class KGDocumentResponse(BaseModel):
    """Response for a single KGDocument."""

    uri: str
    name: Optional[str] = None
    headline: Optional[str] = None
    document_type: Optional[str] = None
    content_type: Optional[str] = None
    segment_index: Optional[int] = None
    segment_method_uri: Optional[str] = None
    segment_type_uri: Optional[str] = None
    token_length: Optional[int] = None
    publication_date: Optional[str] = None
    url: Optional[str] = None


class KGDocumentListResponse(BaseModel):
    """Response for listing KGDocuments."""

    documents: List[KGDocumentResponse] = Field(default_factory=list)
    total_count: int = 0
    page_size: int = 10
    offset: int = 0


# ---------------------------------------------------------------------------
# Segmentation job status
# ---------------------------------------------------------------------------

class SegmentationJobStatusResponse(BaseModel):
    """Status of a single segmentation job for a document."""

    job_id: int
    document_uri: str
    status: str  # pending | in_progress | completed | failed | cancelled
    attempt_count: int = 0
    segment_count: Optional[int] = None
    segment_method_uri: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SegmentationWorkerStatus(BaseModel):
    """Health status of the background segmentation worker."""

    running: bool = False
    started_at: Optional[str] = None
    last_poll_at: Optional[str] = None
    last_wake_reason: Optional[str] = None
    jobs_processed: int = 0
    jobs_failed: int = 0
    listen_status: Dict[str, str] = Field(default_factory=dict)
    listen_channels_active: int = 0


class SegmentationStatusSummaryResponse(BaseModel):
    """Aggregate segmentation status summary for a space."""

    pending: int = 0
    in_progress: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    jobs: List[SegmentationJobStatusResponse] = Field(default_factory=list)
    worker_status: Optional[SegmentationWorkerStatus] = None
