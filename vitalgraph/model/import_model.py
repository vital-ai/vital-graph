"""Import Model Classes

Pydantic models for data import operations.
"""

from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime

from .api_model import BasePaginatedResponse


class ImportStatus(str, Enum):
    """Import job status enumeration."""
    CREATED = "created"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ImportType(str, Enum):
    """Import type enumeration."""
    RDF_TURTLE = "rdf_turtle"
    RDF_XML = "rdf_xml"
    JSON_LD = "json_ld"
    CSV = "csv"
    EXCEL = "excel"
    JSON = "json"


class ImportJob(BaseModel):
    """Import job data model."""
    import_id: Optional[str] = Field(None, description="Unique import job ID")
    name: str = Field(..., description="Import job name")
    description: Optional[str] = Field(None, description="Import job description")
    import_type: ImportType = Field(..., description="Type of import")
    space_id: str = Field(..., description="Target space ID")
    graph_id: Optional[str] = Field(None, description="Target graph ID")
    status: ImportStatus = Field(ImportStatus.CREATED, description="Current status")
    created_date: Optional[datetime] = Field(None, description="Creation timestamp")
    updated_date: Optional[datetime] = Field(None, description="Last update timestamp")
    started_date: Optional[datetime] = Field(None, description="Execution start timestamp")
    completed_date: Optional[datetime] = Field(None, description="Completion timestamp")
    progress_percent: Optional[float] = Field(0.0, description="Progress percentage (0-100)")
    records_processed: Optional[int] = Field(0, description="Number of records processed")
    records_total: Optional[int] = Field(None, description="Total records to process")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    config: Optional[Dict[str, Any]] = Field(None, description="Import configuration")
    uploaded_files: Optional[List[str]] = Field([], description="List of uploaded file names")


class ImportJobsResponse(BasePaginatedResponse):
    """Response model for import jobs listing."""
    import_jobs: List[ImportJob]


class ImportJobResponse(BaseModel):
    """Response model for single import job."""
    import_job: ImportJob


class ImportCreateResponse(BaseModel):
    """Response model for import job creation."""
    message: str
    import_id: str
    import_job: ImportJob


class ImportUpdateResponse(BaseModel):
    """Response model for import job updates."""
    message: str
    import_job: ImportJob


class ImportDeleteResponse(BaseModel):
    """Response model for import job deletion."""
    message: str
    import_id: str


class ImportExecuteResponse(BaseModel):
    """Response model for import job execution."""
    message: str
    import_id: str
    execution_started: bool


class ImportStatusResponse(BaseModel):
    """Response model for import job status."""
    import_id: str
    status: ImportStatus
    progress_percent: float
    records_processed: int
    records_total: Optional[int]
    started_date: Optional[datetime]
    completed_date: Optional[datetime]
    error_message: Optional[str]


class ImportLogResponse(BaseModel):
    """Response model for import job log."""
    import_id: str
    log_entries: List[Dict[str, Any]]
    total_entries: int


class ImportUploadResponse(BaseModel):
    """Response model for import file upload."""
    message: str
    import_id: str
    filename: str
    file_size: int