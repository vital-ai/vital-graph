"""
Data Export REST API endpoint for VitalGraph.

Manages export job lifecycle:
  POST   /export              — create job (auto-generates output filename)
  GET    /export              — list jobs
  GET    /export/{id}         — get job
  DELETE /export/{id}         — cancel & delete job
  POST   /export/{id}/execute — start background export
  GET    /export/{id}/status  — poll progress
  GET    /export/{id}/download — download completed export file
"""

import json
import logging
import os
import tempfile
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, Query, Depends, Path, HTTPException
from fastapi.responses import FileResponse

from ..model.export_model import (
    ExportStatus,
    ExportJobCreate,
    ExportJob,
    ExportJobsResponse,
    ExportJobResponse,
    ExportCreateResponse,
    ExportDeleteResponse,
    ExportExecuteResponse,
    ExportStatusResponse,
)
from ..auth.role_dependencies import require_admin

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: DB row dict → ExportJob Pydantic model
# ---------------------------------------------------------------------------

def _row_to_export_job(row: Dict[str, Any]) -> ExportJob:
    """Convert an asyncpg row dict to an ExportJob model."""
    config = row.get("config")
    if isinstance(config, str):
        config = json.loads(config)
    log_entries = row.get("log_entries")
    if isinstance(log_entries, str):
        log_entries = json.loads(log_entries)
    return ExportJob(
        job_id=str(row["job_id"]),
        job_type=row.get("job_type", "export"),
        space_id=row["space_id"],
        graph_uri=row.get("graph_uri"),
        status=row.get("status", "created"),
        mode=row.get("mode", "append"),
        progress_pct=row.get("progress_pct", 0.0),
        records_done=row.get("records_done", 0),
        records_total=row.get("records_total"),
        file_s3_key=row.get("file_s3_key"),
        file_name=row.get("file_name"),
        file_size=row.get("file_size"),
        file_format=row.get("file_format"),
        config=config,
        error_message=row.get("error_message"),
        log_entries=log_entries if log_entries else [],
        created_by=row.get("created_by"),
        created_at=row.get("created_at"),
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
        updated_at=row.get("updated_at"),
    )


# ---------------------------------------------------------------------------
# Media-type mapping for download responses
# ---------------------------------------------------------------------------

_FORMAT_MEDIA_TYPES = {
    "nt": "application/n-triples",
    "nq": "application/n-quads",
    "ttl": "text/turtle",
    "jsonl": "application/x-ndjson",
}


class ExportEndpoint:
    """Data Export endpoint handler backed by ImportExportJobManager."""

    def __init__(self, job_manager, space_manager, auth_dependency):
        self.job_manager = job_manager
        self.space_manager = space_manager
        self.auth_dependency = auth_dependency
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        """Setup FastAPI routes for data export management."""

        @self.router.post("/export", response_model=ExportCreateResponse)
        async def create_export_job(
            request: ExportJobCreate,
            current_user: Dict = Depends(self.auth_dependency),
        ):
            """Create a new export job."""
            require_admin(current_user)
            return await self._create_export_job(request, current_user)

        @self.router.get("/export", response_model=ExportJobsResponse)
        async def list_export_jobs(
            space_id: Optional[str] = Query(None, description="Filter by space ID"),
            status: Optional[str] = Query(None, description="Filter by status"),
            page_size: int = Query(50, ge=1, le=1000),
            offset: int = Query(0, ge=0),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            """List export jobs with optional filtering."""
            require_admin(current_user)
            return await self._list_export_jobs(space_id, status, page_size, offset)

        @self.router.get("/export/{job_id}", response_model=ExportJobResponse)
        async def get_export_job(
            job_id: str = Path(..., description="Export job ID"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            """Get export job details by ID."""
            require_admin(current_user)
            return await self._get_export_job(job_id)

        @self.router.delete("/export/{job_id}", response_model=ExportDeleteResponse)
        async def delete_export_job(
            job_id: str = Path(..., description="Export job ID"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            """Cancel (if running) and delete export job."""
            require_admin(current_user)
            return await self._delete_export_job(job_id)

        @self.router.post("/export/{job_id}/execute", response_model=ExportExecuteResponse)
        async def execute_export_job(
            job_id: str = Path(..., description="Export job ID"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            """Start background export execution."""
            require_admin(current_user)
            return await self._execute_export_job(job_id)

        @self.router.get("/export/{job_id}/status", response_model=ExportStatusResponse)
        async def get_export_status(
            job_id: str = Path(..., description="Export job ID"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            """Get export progress / status."""
            require_admin(current_user)
            return await self._get_export_status(job_id)

        @self.router.get("/export/{job_id}/download")
        async def download_export_file(
            job_id: str = Path(..., description="Export job ID"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            """Download the completed export file."""
            require_admin(current_user)
            return await self._download_export_file(job_id)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _create_export_job(
        self, request: ExportJobCreate, current_user: Dict
    ) -> ExportCreateResponse:
        fmt = request.file_format.value
        file_name = f"export_{request.space_id}.{fmt}"

        # Pre-create output path so the manager knows where to write
        staging_dir = os.path.join(tempfile.gettempdir(), "vitalgraph_exports")
        os.makedirs(staging_dir, exist_ok=True)

        job_id = await self.job_manager.create_job(
            job_type="export",
            space_id=request.space_id,
            graph_uri=request.graph_uri,
            file_format=fmt,
            file_name=file_name,
            config=request.config,
            created_by=current_user.get("username"),
        )

        # Store the output path in file_s3_key
        output_path = os.path.join(staging_dir, f"{job_id}_{file_name}")
        async with self.job_manager._pool.acquire() as conn:
            await conn.execute(
                """UPDATE import_export_job
                   SET file_s3_key = $2, updated_at = NOW()
                   WHERE job_id = $1""",
                job_id, output_path,
            )

        row = await self.job_manager.get_job(job_id)
        return ExportCreateResponse(
            message="Export job created",
            job_id=job_id,
            job=_row_to_export_job(row),
        )

    async def _list_export_jobs(
        self, space_id: Optional[str], status: Optional[str],
        page_size: int, offset: int,
    ) -> ExportJobsResponse:
        rows = await self.job_manager.list_jobs(
            space_id=space_id,
            status=status,
            job_type="export",
            limit=page_size,
            offset=offset,
        )
        jobs = [_row_to_export_job(r) for r in rows]
        return ExportJobsResponse(
            jobs=jobs,
            total_count=len(jobs),
            page_size=page_size,
            offset=offset,
        )

    async def _get_export_job(self, job_id: str) -> ExportJobResponse:
        row = await self.job_manager.get_job(job_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Export job {job_id} not found")
        return ExportJobResponse(job=_row_to_export_job(row))

    async def _delete_export_job(self, job_id: str) -> ExportDeleteResponse:
        # Clean up staged output file if it exists
        row = await self.job_manager.get_job(job_id)
        if row and row.get("file_s3_key"):
            try:
                os.unlink(row["file_s3_key"])
            except OSError:
                pass

        deleted = await self.job_manager.delete_job(job_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Export job {job_id} not found")
        return ExportDeleteResponse(
            message="Export job deleted",
            job_id=job_id,
        )

    async def _execute_export_job(self, job_id: str) -> ExportExecuteResponse:
        row = await self.job_manager.get_job(job_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Export job {job_id} not found")

        file_path = row.get("file_s3_key")
        if not file_path:
            raise HTTPException(
                status_code=400,
                detail="Export job has no output path configured.",
            )

        started = await self.job_manager.start_job(job_id, file_path=file_path)
        if not started:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot start job (status={row['status']}, "
                       f"or max concurrency reached)",
            )

        return ExportExecuteResponse(
            message="Export job execution started",
            job_id=job_id,
            execution_started=True,
        )

    async def _get_export_status(self, job_id: str) -> ExportStatusResponse:
        row = await self.job_manager.get_job(job_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Export job {job_id} not found")
        return ExportStatusResponse(
            job_id=str(row["job_id"]),
            status=row["status"],
            progress_pct=row.get("progress_pct", 0.0),
            records_done=row.get("records_done", 0),
            records_total=row.get("records_total"),
            file_s3_key=row.get("file_s3_key"),
            file_name=row.get("file_name"),
            file_size=row.get("file_size"),
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
            error_message=row.get("error_message"),
        )

    async def _download_export_file(self, job_id: str) -> FileResponse:
        row = await self.job_manager.get_job(job_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Export job {job_id} not found")
        if row["status"] != "completed":
            raise HTTPException(
                status_code=409,
                detail=f"Export job is not completed (status={row['status']})",
            )

        file_path = row.get("file_s3_key")
        if not file_path or not os.path.exists(file_path):
            raise HTTPException(
                status_code=404,
                detail="Export file not found on disk.",
            )

        fmt = row.get("file_format", "nq")
        media_type = _FORMAT_MEDIA_TYPES.get(fmt, "application/octet-stream")
        filename = row.get("file_name") or os.path.basename(file_path)

        return FileResponse(
            path=file_path,
            media_type=media_type,
            filename=filename,
        )


def create_export_router(job_manager, space_manager, auth_dependency) -> APIRouter:
    """Create and return the data export router."""
    endpoint = ExportEndpoint(job_manager, space_manager, auth_dependency)
    return endpoint.router
