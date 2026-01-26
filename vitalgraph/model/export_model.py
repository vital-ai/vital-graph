"""Export Model Classes

Pydantic models for data export operations.
"""

from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime

from .api_model import BasePaginatedResponse


class ExportStatus(str, Enum):
    """Export job status enumeration."""
    CREATED = "created"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExportFormat(str, Enum):
    """Export format enumeration."""
    RDF_TURTLE = "rdf_turtle"
    RDF_XML = "rdf_xml"
    JSON_LD = "json_ld"
    CSV = "csv"
    EXCEL = "excel"
    JSON = "json"
    PARQUET = "parquet"


class ExportJob(BaseModel):
    """Export job data model."""
    export_id: Optional[str] = Field(None, description="Unique export job ID")
    name: str = Field(..., description="Export job name")
    description: Optional[str] = Field(None, description="Export job description")
    export_format: ExportFormat = Field(..., description="Export format")
    space_id: str = Field(..., description="Source space ID")
    graph_id: Optional[str] = Field(None, description="Source graph ID")
    status: ExportStatus = Field(ExportStatus.CREATED, description="Current status")
    created_date: Optional[datetime] = Field(None, description="Creation timestamp")
    updated_date: Optional[datetime] = Field(None, description="Last update timestamp")
    started_date: Optional[datetime] = Field(None, description="Execution start timestamp")
    completed_date: Optional[datetime] = Field(None, description="Completion timestamp")
    progress_percent: Optional[float] = Field(0.0, description="Progress percentage (0-100)")
    records_processed: Optional[int] = Field(0, description="Number of records processed")
    records_total: Optional[int] = Field(None, description="Total records to process")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    config: Optional[Dict[str, Any]] = Field(None, description="Export configuration")
    output_files: Optional[List[Dict[str, Any]]] = Field([], description="List of generated output files")
    query_filter: Optional[str] = Field(None, description="SPARQL query filter for export")


class ExportJobsResponse(BasePaginatedResponse):
    """Response model for export jobs listing."""
    export_jobs: List[ExportJob]


class ExportJobResponse(BaseModel):
    """Response model for single export job."""
    export_job: ExportJob


class ExportCreateResponse(BaseModel):
    """Response model for export job creation."""
    message: str
    export_id: str
    export_job: ExportJob


class ExportUpdateResponse(BaseModel):
    """Response model for export job updates."""
    message: str
    export_job: ExportJob


class ExportDeleteResponse(BaseModel):
    """Response model for export job deletion."""
    message: str
    export_id: str


class ExportExecuteResponse(BaseModel):
    """Response model for export job execution."""
    message: str
    export_id: str
    execution_started: bool


class ExportStatusResponse(BaseModel):
    """Response model for export job status."""
    export_id: str
    status: ExportStatus
    progress_percent: float
    records_processed: int
    records_total: Optional[int]
    started_date: Optional[datetime]
    completed_date: Optional[datetime]
    error_message: Optional[str]
    output_files: List[Dict[str, Any]]