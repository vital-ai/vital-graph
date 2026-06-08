"""Import Model Classes

Pydantic models for data import operations.
Aligned with the ``import_export_job`` PostgreSQL table schema.
"""

from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime

from .api_model import BasePaginatedResponse


class JobStatus(str, Enum):
    """Job status — matches DB CHECK constraint."""
    CREATED = "created"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FileFormat(str, Enum):
    """Supported import file formats."""
    NT = "nt"
    NQ = "nq"
    TTL = "ttl"
    JSONL = "jsonl"
    VITAL = "vital"


class ImportMode(str, Enum):
    """Import mode — matches DB CHECK constraint."""
    APPEND = "append"
    REPLACE = "replace"


# Keep old names as aliases for backward compatibility
ImportStatus = JobStatus


class ImportJobCreate(BaseModel):
    """Request body for creating an import job."""
    space_id: str = Field(..., description="Target space ID")
    graph_uri: Optional[str] = Field(None, description="Target graph URI (default: urn:<space_id>)")
    file_format: Optional[FileFormat] = Field(None, description="File format (auto-detected from extension if omitted)")
    mode: ImportMode = Field(ImportMode.APPEND, description="Import mode: append or replace")
    config: Optional[Dict[str, Any]] = Field(None, description="Extra options (batch_size, etc.)")


class ImportJob(BaseModel):
    """Import job — mirrors the import_export_job DB row."""
    job_id: str = Field(..., description="Unique job UUID")
    job_type: str = Field("import", description="Always 'import'")
    space_id: str = Field(..., description="Target space ID")
    graph_uri: Optional[str] = Field(None, description="Target graph URI")
    status: JobStatus = Field(JobStatus.CREATED, description="Current status")
    mode: ImportMode = Field(ImportMode.APPEND, description="Import mode")
    progress_pct: float = Field(0.0, description="Progress percentage (0-100)")
    records_done: int = Field(0, description="Records processed so far")
    records_total: Optional[int] = Field(None, description="Total records (if known)")
    file_s3_key: Optional[str] = Field(None, description="S3 object key for staged file")
    file_name: Optional[str] = Field(None, description="Original filename")
    file_size: Optional[int] = Field(None, description="File size in bytes")
    file_format: Optional[str] = Field(None, description="File format: nt, nq, ttl, jsonl")
    config: Optional[Dict[str, Any]] = Field(None, description="Extra options")
    checkpoint_offset: int = Field(0, description="Byte offset for resume")
    checkpoint_batch: int = Field(0, description="Last committed batch number")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    log_entries: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Log entries")
    created_by: Optional[str] = Field(None, description="User who created the job")
    created_at: Optional[datetime] = Field(None, description="Creation timestamp")
    started_at: Optional[datetime] = Field(None, description="Execution start timestamp")
    completed_at: Optional[datetime] = Field(None, description="Completion timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")


class ImportJobsResponse(BasePaginatedResponse):
    """Response model for import jobs listing."""
    jobs: List[ImportJob]


class ImportJobResponse(BaseModel):
    """Response model for single import job."""
    job: ImportJob


class ImportCreateResponse(BaseModel):
    """Response model for import job creation."""
    message: str
    job_id: str
    job: ImportJob


class ImportDeleteResponse(BaseModel):
    """Response model for import job deletion."""
    message: str
    job_id: str


class ImportExecuteResponse(BaseModel):
    """Response model for import job execution."""
    message: str
    job_id: str
    execution_started: bool


class ImportStatusResponse(BaseModel):
    """Response model for import job status."""
    job_id: str
    status: JobStatus
    progress_pct: float
    records_done: int
    records_total: Optional[int]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_message: Optional[str]


class ImportLogResponse(BaseModel):
    """Response model for import job log."""
    job_id: str
    log_entries: List[Dict[str, Any]]
    total_entries: int


class ImportUploadResponse(BaseModel):
    """Response model for import file upload."""
    message: str
    job_id: str
    filename: str
    file_size: int