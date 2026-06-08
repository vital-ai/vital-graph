"""Mock Export Endpoint

Mock implementation of ExportEndpoint for testing.
"""

from typing import Dict, Any, Optional, List
from pathlib import Path
from datetime import datetime

from .mock_base_endpoint import MockBaseEndpoint
from ....model.export_model import (
    ExportJobCreate, ExportJob, ExportJobsResponse, ExportJobResponse,
    ExportCreateResponse, ExportDeleteResponse, ExportExecuteResponse,
    ExportStatusResponse,
)
from ....model.import_model import JobStatus

_MOCK_JOB_ID = "00000000-0000-0000-0000-000000000002"


class MockExportEndpoint(MockBaseEndpoint):
    """Mock implementation of ExportEndpoint."""

    def _mock_job(self, job_id: str = _MOCK_JOB_ID,
                  space_id: str = "mock_space",
                  graph_uri: Optional[str] = None,
                  file_format: str = "nq") -> ExportJob:
        now = datetime.utcnow()
        return ExportJob(
            job_id=job_id, job_type="export", space_id=space_id,
            graph_uri=graph_uri, status=JobStatus.CREATED,
            progress_pct=0.0, records_done=0, file_format=file_format,
            created_at=now, updated_at=now,
        )

    def create_export_job(self, request: ExportJobCreate) -> ExportCreateResponse:
        self._log_method_call("create_export_job", request=request)
        job = self._mock_job(space_id=request.space_id, graph_uri=request.graph_uri,
                             file_format=request.file_format.value)
        return ExportCreateResponse(message="Export job created", job_id=job.job_id, job=job)

    def list_export_jobs(self, space_id: Optional[str] = None, status: Optional[str] = None,
                         page_size: int = 50, offset: int = 0) -> ExportJobsResponse:
        self._log_method_call("list_export_jobs", space_id=space_id, status=status)
        return ExportJobsResponse(jobs=[], total_count=0, page_size=page_size, offset=offset)

    def get_export_job(self, job_id: str) -> ExportJobResponse:
        self._log_method_call("get_export_job", job_id=job_id)
        return ExportJobResponse(job=self._mock_job(job_id=job_id))

    def delete_export_job(self, job_id: str) -> ExportDeleteResponse:
        self._log_method_call("delete_export_job", job_id=job_id)
        return ExportDeleteResponse(message="Export job deleted", job_id=job_id)

    def execute_export_job(self, job_id: str) -> ExportExecuteResponse:
        self._log_method_call("execute_export_job", job_id=job_id)
        return ExportExecuteResponse(message="Export job execution started", job_id=job_id, execution_started=True)

    def get_export_status(self, job_id: str) -> ExportStatusResponse:
        self._log_method_call("get_export_status", job_id=job_id)
        return ExportStatusResponse(
            job_id=job_id, status=JobStatus.RUNNING,
            progress_pct=75.0, records_done=750, records_total=1000,
            started_at=datetime.utcnow(), completed_at=None, error_message=None,
        )

    def download_export_file(self, job_id: str, output_path: str) -> bool:
        self._log_method_call("download_export_file", job_id=job_id, output_path=output_path)
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# mock export data\n")
        return True
