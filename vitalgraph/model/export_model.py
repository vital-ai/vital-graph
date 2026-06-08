"""Export Model Classes

Pydantic models for data export operations.
Aligned with the ``import_export_job`` PostgreSQL table schema.
"""

from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime

from .api_model import BasePaginatedResponse
from .import_model import JobStatus, FileFormat


# Re-export for backward compatibility
ExportStatus = JobStatus


class ExportJobCreate(BaseModel):
    """Request body for creating an export job."""
    space_id: str = Field(..., description="Source space ID")
    graph_uri: Optional[str] = Field(None, description="Source graph URI (export all graphs if omitted)")
    file_format: FileFormat = Field(FileFormat.NQ, description="Export format: nt, nq, ttl, jsonl")
    config: Optional[Dict[str, Any]] = Field(None, description="Extra options (batch_size, compress, etc.)")


class ExportJob(BaseModel):
    """Export job — mirrors the import_export_job DB row."""
    job_id: str = Field(..., description="Unique job UUID")
    job_type: str = Field("export", description="Always 'export'")
    space_id: str = Field(..., description="Source space ID")
    graph_uri: Optional[str] = Field(None, description="Source graph URI")
    status: JobStatus = Field(JobStatus.CREATED, description="Current status")
    mode: str = Field("append", description="Mode (not used for export)")
    progress_pct: float = Field(0.0, description="Progress percentage (0-100)")
    records_done: int = Field(0, description="Records exported so far")
    records_total: Optional[int] = Field(None, description="Total records (if known)")
    file_s3_key: Optional[str] = Field(None, description="S3 object key for export file")
    file_name: Optional[str] = Field(None, description="Output filename")
    file_size: Optional[int] = Field(None, description="File size in bytes")
    file_format: Optional[str] = Field(None, description="File format: nt, nq, ttl, jsonl")
    config: Optional[Dict[str, Any]] = Field(None, description="Extra options")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    log_entries: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Log entries")
    created_by: Optional[str] = Field(None, description="User who created the job")
    created_at: Optional[datetime] = Field(None, description="Creation timestamp")
    started_at: Optional[datetime] = Field(None, description="Execution start timestamp")
    completed_at: Optional[datetime] = Field(None, description="Completion timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")


class ExportJobsResponse(BasePaginatedResponse):
    """Response model for export jobs listing."""
    jobs: List[ExportJob]


class ExportJobResponse(BaseModel):
    """Response model for single export job."""
    job: ExportJob


class ExportCreateResponse(BaseModel):
    """Response model for export job creation."""
    message: str
    job_id: str
    job: ExportJob


class ExportDeleteResponse(BaseModel):
    """Response model for export job deletion."""
    message: str
    job_id: str


class ExportExecuteResponse(BaseModel):
    """Response model for export job execution."""
    message: str
    job_id: str
    execution_started: bool


class ExportStatusResponse(BaseModel):
    """Response model for export job status."""
    job_id: str
    status: JobStatus
    progress_pct: float
    records_done: int
    records_total: Optional[int]
    file_s3_key: Optional[str]
    file_name: Optional[str]
    file_size: Optional[int]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_message: Optional[str]