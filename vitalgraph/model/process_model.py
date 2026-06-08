"""
Pydantic request/response models for Process Tracking endpoints.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ProcessResponse(BaseModel):
    """Single process record."""
    process_id: str
    process_type: str
    process_subtype: Optional[str] = None
    status: str
    instance_id: Optional[str] = None
    progress_percent: Optional[float] = None
    progress_message: Optional[str] = None
    error_message: Optional[str] = None
    result_details: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class ProcessListResponse(BaseModel):
    """Paginated list of process records."""
    processes: List[ProcessResponse]
    total_count: int
    limit: int
    offset: int


class TriggerRequest(BaseModel):
    """Request body for triggering a maintenance operation."""
    process_type: str = Field(..., description="Operation type: analyze, vacuum, stats_rebuild, vector_reindex")
    space_id: Optional[str] = Field(None, description="Target space (omit for auto-select)")


class TriggerResponse(BaseModel):
    """Response from a manual trigger."""
    triggered: bool
    message: str
    result: Optional[Dict[str, Any]] = None


class SchedulerStatusResponse(BaseModel):
    """Current scheduler status."""
    enabled: bool
    running: bool
    jobs: Dict[str, Any]
    active_locks: int
