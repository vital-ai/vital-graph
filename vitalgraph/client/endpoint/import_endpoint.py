"""
VitalGraph Client Import Endpoint

Client-side implementation for Data Import operations.
"""

import httpx
from typing import Dict, Any, Optional, List
from pathlib import Path

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ...model.import_model import (
    ImportJobCreate, ImportJob, ImportJobsResponse, ImportJobResponse,
    ImportCreateResponse, ImportDeleteResponse, ImportExecuteResponse,
    ImportStatusResponse, ImportLogResponse, ImportUploadResponse,
)


class ImportEndpoint(BaseEndpoint):
    """Client endpoint for Data Import operations."""

    async def create_import_job(self, request: ImportJobCreate) -> ImportCreateResponse:
        """Create a new import job.

        Args:
            request: ImportJobCreate with space_id, graph_uri, mode, etc.

        Returns:
            ImportCreateResponse with the created job.
        """
        self._check_connection()
        url = f"{self._get_server_url().rstrip('/')}/api/data/import"
        return await self._make_typed_request('POST', url, ImportCreateResponse, json=request.model_dump())

    async def list_import_jobs(
        self,
        space_id: Optional[str] = None,
        status: Optional[str] = None,
        page_size: int = 50,
        offset: int = 0,
    ) -> ImportJobsResponse:
        """List import jobs with optional filtering."""
        self._check_connection()
        url = f"{self._get_server_url().rstrip('/')}/api/data/import"
        params = build_query_params(space_id=space_id, status=status, page_size=page_size, offset=offset)
        return await self._make_typed_request('GET', url, ImportJobsResponse, params=params)

    async def get_import_job(self, job_id: str) -> ImportJobResponse:
        """Get import job details by ID."""
        self._check_connection()
        validate_required_params(job_id=job_id)
        url = f"{self._get_server_url().rstrip('/')}/api/data/import/{job_id}"
        return await self._make_typed_request('GET', url, ImportJobResponse)

    async def delete_import_job(self, job_id: str) -> ImportDeleteResponse:
        """Cancel (if running) and delete import job."""
        self._check_connection()
        validate_required_params(job_id=job_id)
        url = f"{self._get_server_url().rstrip('/')}/api/data/import/{job_id}"
        return await self._make_typed_request('DELETE', url, ImportDeleteResponse)

    async def upload_import_file(self, job_id: str, file_path: str) -> ImportUploadResponse:
        """Upload a file for an import job.

        Args:
            job_id: Import job UUID.
            file_path: Local path to file.

        Returns:
            ImportUploadResponse with staged file info.
        """
        self._check_connection()
        validate_required_params(job_id=job_id, file_path=file_path)

        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            raise VitalGraphClientError(f"File not found: {file_path}")

        try:
            url = f"{self._get_server_url().rstrip('/')}/api/data/import/{job_id}/upload"
            with open(file_path_obj, 'rb') as f:
                files = {'file': (file_path_obj.name, f, 'application/octet-stream')}
                response = await self._make_authenticated_request('POST', url, files=files)
                response.raise_for_status()
                return ImportUploadResponse.model_validate(response.json())
        except httpx.HTTPError as e:
            raise VitalGraphClientError(f"Failed to upload import file: {e}")

    async def execute_import_job(self, job_id: str) -> ImportExecuteResponse:
        """Start background import execution."""
        self._check_connection()
        validate_required_params(job_id=job_id)
        url = f"{self._get_server_url().rstrip('/')}/api/data/import/{job_id}/execute"
        return await self._make_typed_request('POST', url, ImportExecuteResponse)

    async def get_import_status(self, job_id: str) -> ImportStatusResponse:
        """Get import progress / status."""
        self._check_connection()
        validate_required_params(job_id=job_id)
        url = f"{self._get_server_url().rstrip('/')}/api/data/import/{job_id}/status"
        return await self._make_typed_request('GET', url, ImportStatusResponse)

    async def get_import_log(self, job_id: str) -> ImportLogResponse:
        """Get import log entries."""
        self._check_connection()
        validate_required_params(job_id=job_id)
        url = f"{self._get_server_url().rstrip('/')}/api/data/import/{job_id}/log"
        return await self._make_typed_request('GET', url, ImportLogResponse)
