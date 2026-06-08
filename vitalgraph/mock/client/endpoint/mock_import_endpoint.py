"""Mock Import Endpoint

Mock implementation of ImportEndpoint for testing.
"""

from typing import Dict, Any, Optional
from pathlib import Path
from datetime import datetime

from .mock_base_endpoint import MockBaseEndpoint
from ....model.import_model import (
    JobStatus, ImportJobCreate, ImportJob,
    ImportJobsResponse, ImportJobResponse, ImportCreateResponse,
    ImportDeleteResponse, ImportExecuteResponse, ImportStatusResponse,
    ImportLogResponse, ImportUploadResponse,
)

_MOCK_JOB_ID = "00000000-0000-0000-0000-000000000001"


class MockImportEndpoint(MockBaseEndpoint):
    """Mock implementation of ImportEndpoint."""

    def _mock_job(self, job_id: str = _MOCK_JOB_ID,
                  space_id: str = "mock_space",
                  graph_uri: Optional[str] = None) -> ImportJob:
        now = datetime.utcnow()
        return ImportJob(
            job_id=job_id, job_type="import", space_id=space_id,
            graph_uri=graph_uri, status=JobStatus.CREATED, mode="append",
            progress_pct=0.0, records_done=0,
            created_at=now, updated_at=now,
        )

    def create_import_job(self, request: ImportJobCreate) -> ImportCreateResponse:
        self._log_method_call("create_import_job", request=request)
        job = self._mock_job(space_id=request.space_id, graph_uri=request.graph_uri)
        return ImportCreateResponse(message="Import job created", job_id=job.job_id, job=job)

    def list_import_jobs(self, space_id: Optional[str] = None, status: Optional[str] = None,
                         page_size: int = 50, offset: int = 0) -> ImportJobsResponse:
        self._log_method_call("list_import_jobs", space_id=space_id, status=status)
        return ImportJobsResponse(jobs=[], total_count=0, page_size=page_size, offset=offset)

    def get_import_job(self, job_id: str) -> ImportJobResponse:
        self._log_method_call("get_import_job", job_id=job_id)
        return ImportJobResponse(job=self._mock_job(job_id=job_id))

    def delete_import_job(self, job_id: str) -> ImportDeleteResponse:
        self._log_method_call("delete_import_job", job_id=job_id)
        return ImportDeleteResponse(message="Import job deleted", job_id=job_id)

    def execute_import_job(self, job_id: str) -> ImportExecuteResponse:
        self._log_method_call("execute_import_job", job_id=job_id)
        return ImportExecuteResponse(message="Import job execution started", job_id=job_id, execution_started=True)

    def get_import_status(self, job_id: str) -> ImportStatusResponse:
        self._log_method_call("get_import_status", job_id=job_id)
        return ImportStatusResponse(
            job_id=job_id, status=JobStatus.RUNNING,
            progress_pct=75.0, records_done=750, records_total=1000,
            started_at=datetime.utcnow(), completed_at=None, error_message=None,
        )

    def get_import_log(self, job_id: str) -> ImportLogResponse:
        self._log_method_call("get_import_log", job_id=job_id)
        return ImportLogResponse(job_id=job_id, log_entries=[], total_entries=0)

    def upload_import_file(self, job_id: str, file_path: str) -> ImportUploadResponse:
        self._log_method_call("upload_import_file", job_id=job_id, file_path=file_path)
        fp = Path(file_path)
        return ImportUploadResponse(
            message="File uploaded", job_id=job_id,
            filename=fp.name if fp.exists() else "mock_file.nt", file_size=1024,
        )
