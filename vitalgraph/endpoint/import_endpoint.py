"""
Data Import REST API endpoint for VitalGraph.

Manages import job lifecycle:
  POST   /import              — create job
  GET    /import              — list jobs
  GET    /import/job          — get job (job_id query param)
  DELETE /import              — cancel & delete job (job_id query param)
  POST   /import/upload       — upload file to S3 staging (job_id query param)
  POST   /import/execute      — start background import (job_id query param)
  GET    /import/status       — poll progress (job_id query param)
  GET    /import/log          — fetch log entries (job_id query param)
"""

import json
import logging
import os
import tempfile
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, Query, Depends, UploadFile, File, HTTPException

from ..model.import_model import (
    JobStatus,
    ImportJobCreate,
    ImportJob,
    ImportJobsResponse,
    ImportJobResponse,
    ImportCreateResponse,
    ImportDeleteResponse,
    ImportExecuteResponse,
    ImportStatusResponse,
    ImportLogResponse,
    ImportUploadResponse,
)
from ..auth.role_dependencies import require_admin

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: DB row dict → ImportJob Pydantic model
# ---------------------------------------------------------------------------

def _row_to_import_job(row: Dict[str, Any]) -> ImportJob:
    """Convert an asyncpg row dict to an ImportJob model."""
    config = row.get("config")
    if isinstance(config, str):
        config = json.loads(config)
    log_entries = row.get("log_entries")
    if isinstance(log_entries, str):
        log_entries = json.loads(log_entries)
    return ImportJob(
        job_id=str(row["job_id"]),
        job_type=row.get("job_type", "import"),
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
        checkpoint_offset=row.get("checkpoint_offset", 0),
        checkpoint_batch=row.get("checkpoint_batch", 0),
        error_message=row.get("error_message"),
        log_entries=log_entries if log_entries else [],
        created_by=row.get("created_by"),
        created_at=row.get("created_at"),
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
        updated_at=row.get("updated_at"),
    )


class ImportEndpoint:
    """Data Import endpoint handler backed by ImportExportJobManager."""

    def __init__(self, app_impl, space_manager, auth_dependency):
        self.app_impl = app_impl
        self.space_manager = space_manager
        self.auth_dependency = auth_dependency
        self.router = APIRouter()
        self._setup_routes()

    @property
    def job_manager(self):
        """Get the ImportExportJobManager from app_impl (set during startup)."""
        mgr = getattr(self.app_impl, 'import_export_manager', None)
        if mgr is None:
            raise HTTPException(
                status_code=503,
                detail="Import/export service is not available (database not connected)",
            )
        return mgr

    def _setup_routes(self):
        """Setup FastAPI routes for data import management."""

        @self.router.post("/import", response_model=ImportCreateResponse)
        async def create_import_job(
            request: ImportJobCreate,
            current_user: Dict = Depends(self.auth_dependency),
        ):
            """Create a new import job (no file yet)."""
            require_admin(current_user)
            return await self._create_import_job(request, current_user)

        @self.router.get("/import", response_model=ImportJobsResponse)
        async def list_import_jobs(
            space_id: Optional[str] = Query(None, description="Filter by space ID"),
            status: Optional[str] = Query(None, description="Filter by status"),
            page_size: int = Query(50, ge=1, le=1000),
            offset: int = Query(0, ge=0),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            """List import jobs with optional filtering."""
            require_admin(current_user)
            return await self._list_import_jobs(space_id, status, page_size, offset)

        @self.router.get("/import/job", response_model=ImportJobResponse)
        async def get_import_job(
            job_id: str = Query(..., description="Import job ID"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            """Get import job details by ID."""
            require_admin(current_user)
            return await self._get_import_job(job_id)

        @self.router.delete("/import", response_model=ImportDeleteResponse)
        async def delete_import_job(
            job_id: str = Query(..., description="Import job ID"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            """Cancel (if running) and delete import job."""
            require_admin(current_user)
            return await self._delete_import_job(job_id)

        @self.router.post("/import/upload", response_model=ImportUploadResponse)
        async def upload_import_file(
            file: UploadFile = File(..., description="File to upload"),
            job_id: str = Query(..., description="Import job ID"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            """Upload a file for an import job (staged to temp dir)."""
            require_admin(current_user)
            return await self._upload_import_file(job_id, file, current_user)

        @self.router.post("/import/execute", response_model=ImportExecuteResponse)
        async def execute_import_job(
            job_id: str = Query(..., description="Import job ID"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            """Start background import execution."""
            require_admin(current_user)
            return await self._execute_import_job(job_id)

        @self.router.get("/import/status", response_model=ImportStatusResponse)
        async def get_import_status(
            job_id: str = Query(..., description="Import job ID"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            """Get import progress / status."""
            require_admin(current_user)
            return await self._get_import_status(job_id)

        @self.router.get("/import/log", response_model=ImportLogResponse)
        async def get_import_log(
            job_id: str = Query(..., description="Import job ID"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            """Get import log entries."""
            require_admin(current_user)
            return await self._get_import_log(job_id)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _create_import_job(
        self, request: ImportJobCreate, current_user: Dict
    ) -> ImportCreateResponse:
        job_id = await self.job_manager.create_job(
            job_type="import",
            space_id=request.space_id,
            graph_uri=request.graph_uri,
            mode=request.mode.value,
            file_format=request.file_format.value if request.file_format else None,
            config=request.config,
            created_by=current_user.get("username"),
        )
        row = await self.job_manager.get_job(job_id)
        return ImportCreateResponse(
            message="Import job created",
            job_id=job_id,
            job=_row_to_import_job(row),
        )

    async def _list_import_jobs(
        self, space_id: Optional[str], status: Optional[str],
        page_size: int, offset: int,
    ) -> ImportJobsResponse:
        rows = await self.job_manager.list_jobs(
            space_id=space_id,
            status=status,
            job_type="import",
            limit=page_size,
            offset=offset,
        )
        jobs = [_row_to_import_job(r) for r in rows]
        return ImportJobsResponse(
            jobs=jobs,
            total_count=len(jobs),
            page_size=page_size,
            offset=offset,
        )

    async def _get_import_job(self, job_id: str) -> ImportJobResponse:
        row = await self.job_manager.get_job(job_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Import job {job_id} not found")
        return ImportJobResponse(job=_row_to_import_job(row))

    async def _delete_import_job(self, job_id: str) -> ImportDeleteResponse:
        deleted = await self.job_manager.delete_job(job_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Import job {job_id} not found")
        return ImportDeleteResponse(
            message="Import job deleted",
            job_id=job_id,
        )

    async def _upload_import_file(
        self, job_id: str, file: UploadFile, current_user: Dict
    ) -> ImportUploadResponse:
        row = await self.job_manager.get_job(job_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Import job {job_id} not found")
        if row["status"] not in ("created", "failed", "cancelled"):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot upload to job in status '{row['status']}'",
            )

        # Stage file to a temp directory
        staging_dir = os.path.join(tempfile.gettempdir(), "vitalgraph_imports")
        os.makedirs(staging_dir, exist_ok=True)
        filename = file.filename or "upload.nt"
        staged_path = os.path.join(staging_dir, f"{job_id}_{filename}")

        content = await file.read()
        file_size = len(content)
        with open(staged_path, "wb") as f:
            f.write(content)

        # Update job row with file info
        async with self.job_manager._pool.acquire() as conn:
            await conn.execute(
                """UPDATE import_export_job
                   SET file_name = $2, file_size = $3, file_s3_key = $4,
                       updated_at = NOW()
                   WHERE job_id = $1""",
                job_id, filename, file_size, staged_path,
            )

        logger.info("Staged import file %s (%d bytes) for job %s",
                     filename, file_size, job_id)

        return ImportUploadResponse(
            message="File uploaded and staged",
            job_id=job_id,
            filename=filename,
            file_size=file_size,
        )

    async def _execute_import_job(self, job_id: str) -> ImportExecuteResponse:
        row = await self.job_manager.get_job(job_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Import job {job_id} not found")

        file_path = row.get("file_s3_key")  # staged local path
        if not file_path or not os.path.exists(file_path):
            raise HTTPException(
                status_code=400,
                detail="No file uploaded. Use POST /import/{id}/upload first.",
            )

        started = await self.job_manager.start_job(job_id, file_path=file_path)
        if not started:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot start job (status={row['status']}, "
                       f"or max concurrency reached)",
            )

        return ImportExecuteResponse(
            message="Import job execution started",
            job_id=job_id,
            execution_started=True,
        )

    async def _get_import_status(self, job_id: str) -> ImportStatusResponse:
        row = await self.job_manager.get_job(job_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Import job {job_id} not found")
        return ImportStatusResponse(
            job_id=str(row["job_id"]),
            status=row["status"],
            progress_pct=row.get("progress_pct", 0.0),
            records_done=row.get("records_done", 0),
            records_total=row.get("records_total"),
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
            error_message=row.get("error_message"),
        )

    async def _get_import_log(self, job_id: str) -> ImportLogResponse:
        row = await self.job_manager.get_job(job_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Import job {job_id} not found")
        log_entries = row.get("log_entries") or []
        if isinstance(log_entries, str):
            log_entries = json.loads(log_entries)
        return ImportLogResponse(
            job_id=str(row["job_id"]),
            log_entries=log_entries,
            total_entries=len(log_entries),
        )


def create_import_router(job_manager, space_manager, auth_dependency) -> APIRouter:
    """Create and return the data import router."""
    endpoint = ImportEndpoint(job_manager, space_manager, auth_dependency)
    return endpoint.router
