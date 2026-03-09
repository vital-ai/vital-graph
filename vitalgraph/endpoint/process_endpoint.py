"""
Process Tracking REST API Endpoint.

Provides read-only access to process records and the ability to
trigger maintenance operations manually.

Routes:
    GET  /api/processes              — list recent processes
    GET  /api/processes/detail?process_id=... — get process details
    POST /api/processes/trigger      — manually trigger a maintenance job
    GET  /api/processes/scheduler    — get scheduler status
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

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
    process_type: str = Field(..., description="Operation type: analyze, vacuum, stats_rebuild")
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


# ---------------------------------------------------------------------------
# Endpoint class
# ---------------------------------------------------------------------------

class ProcessEndpoint:
    """Process tracking endpoint handler."""

    def __init__(self, app_impl, auth_dependency):
        self.app_impl = app_impl
        self.auth_dependency = auth_dependency
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        auth = self.auth_dependency

        @self.router.get(
            "/processes",
            response_model=ProcessListResponse,
            summary="List processes",
        )
        async def list_processes(
            process_type: Optional[str] = Query(None, description="Filter by type"),
            process_status: Optional[str] = Query(None, alias="status", description="Filter by status"),
            limit: int = Query(50, ge=1, le=200),
            offset: int = Query(0, ge=0),
            current_user: Dict = Depends(auth),
        ):
            tracker = self._get_tracker()
            if tracker is None:
                raise HTTPException(status_code=503, detail="Process tracking not available")

            rows = await tracker.list_processes(
                process_type=process_type,
                status=process_status,
                limit=limit,
                offset=offset,
            )
            processes = [self._row_to_response(r) for r in rows]
            return ProcessListResponse(
                processes=processes,
                total_count=len(processes),
                limit=limit,
                offset=offset,
            )

        @self.router.get(
            "/processes/scheduler",
            response_model=SchedulerStatusResponse,
            summary="Get scheduler status",
        )
        async def scheduler_status(current_user: Dict = Depends(auth)):
            scheduler = getattr(self.app_impl, "process_scheduler", None)
            if scheduler is None:
                raise HTTPException(status_code=503, detail="Process scheduler not available")
            info = scheduler.get_status()
            return SchedulerStatusResponse(**info)

        @self.router.get(
            "/processes/detail",
            response_model=ProcessResponse,
            summary="Get process details",
        )
        async def get_process(
            process_id: str = Query(..., description="Process ID"),
            current_user: Dict = Depends(auth),
        ):
            tracker = self._get_tracker()
            if tracker is None:
                raise HTTPException(status_code=503, detail="Process tracking not available")

            row = await tracker.get_process(process_id)
            if row is None:
                raise HTTPException(status_code=404, detail="Process not found")
            return self._row_to_response(row)

        @self.router.post(
            "/processes/trigger",
            response_model=TriggerResponse,
            summary="Trigger maintenance operation",
        )
        async def trigger_process(body: TriggerRequest, current_user: Dict = Depends(auth)):
            scheduler = getattr(self.app_impl, "process_scheduler", None)
            if scheduler is None:
                raise HTTPException(status_code=503, detail="Process scheduler not available")

            result = await scheduler.trigger_now(body.process_type, body.space_id)
            if result is None:
                return TriggerResponse(
                    triggered=False,
                    message="Lock busy or no handler registered for this process type",
                )
            return TriggerResponse(
                triggered=True,
                message=f"{body.process_type} completed",
                result=result if isinstance(result, dict) else {"raw": str(result)},
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_tracker(self):
        """Retrieve ProcessTracker from the app lifecycle if available."""
        scheduler = getattr(self.app_impl, "process_scheduler", None)
        if scheduler is None:
            return None
        # The tracker lives on the MaintenanceJob which is the handler
        for job in scheduler._jobs.values():
            handler = job.handler
            tracker = getattr(handler, "_tracker", None)
            if tracker is not None:
                return tracker
        return None

    @staticmethod
    def _row_to_response(row: Dict) -> ProcessResponse:
        """Convert a process table row dict to a ProcessResponse."""
        def _ts(val):
            return val.isoformat() if val is not None else None

        return ProcessResponse(
            process_id=str(row.get("process_id", "")),
            process_type=row.get("process_type", ""),
            process_subtype=row.get("process_subtype"),
            status=row.get("status", ""),
            instance_id=row.get("instance_id"),
            progress_percent=row.get("progress_percent"),
            progress_message=row.get("progress_message"),
            error_message=row.get("error_message"),
            result_details=row.get("result_details"),
            created_at=_ts(row.get("created_at")),
            updated_at=_ts(row.get("updated_at")),
            started_at=_ts(row.get("started_at")),
            completed_at=_ts(row.get("completed_at")),
        )


def create_process_router(app_impl, auth_dependency) -> APIRouter:
    """Factory function to create the process tracking router."""
    endpoint = ProcessEndpoint(app_impl, auth_dependency)
    return endpoint.router
