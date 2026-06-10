"""
VitalGraph Client Export Endpoint

Client-side implementation for Data Export operations.
"""

import httpx
from typing import Dict, Any, Optional, List
from pathlib import Path

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ...model.export_model import (
    ExportJobCreate, ExportJob, ExportJobsResponse, ExportJobResponse,
    ExportCreateResponse, ExportDeleteResponse, ExportExecuteResponse,
    ExportStatusResponse,
)


class ExportEndpoint(BaseEndpoint):
    """Client endpoint for Data Export operations."""

    async def create_export_job(self, request: ExportJobCreate) -> ExportCreateResponse:
        """Create a new export job.

        Args:
            request: ExportJobCreate with space_id, graph_uri, file_format, etc.

        Returns:
            ExportCreateResponse with the created job.
        """
        self._check_connection()
        url = f"{self._get_server_url().rstrip('/')}/api/data/export"
        return await self._make_typed_request('POST', url, ExportCreateResponse, json=request.model_dump())

    async def list_export_jobs(
        self,
        space_id: Optional[str] = None,
        status: Optional[str] = None,
        page_size: int = 50,
        offset: int = 0,
    ) -> ExportJobsResponse:
        """List export jobs with optional filtering."""
        self._check_connection()
        url = f"{self._get_server_url().rstrip('/')}/api/data/export"
        params = build_query_params(space_id=space_id, status=status, page_size=page_size, offset=offset)
        return await self._make_typed_request('GET', url, ExportJobsResponse, params=params)

    async def get_export_job(self, job_id: str) -> ExportJobResponse:
        """Get export job details by ID."""
        self._check_connection()
        validate_required_params(job_id=job_id)
        url = f"{self._get_server_url().rstrip('/')}/api/data/export/job"
        params = build_query_params(job_id=job_id)
        return await self._make_typed_request('GET', url, ExportJobResponse, params=params)

    async def delete_export_job(self, job_id: str) -> ExportDeleteResponse:
        """Cancel (if running) and delete export job."""
        self._check_connection()
        validate_required_params(job_id=job_id)
        url = f"{self._get_server_url().rstrip('/')}/api/data/export"
        params = build_query_params(job_id=job_id)
        return await self._make_typed_request('DELETE', url, ExportDeleteResponse, params=params)

    async def execute_export_job(self, job_id: str) -> ExportExecuteResponse:
        """Start background export execution."""
        self._check_connection()
        validate_required_params(job_id=job_id)
        url = f"{self._get_server_url().rstrip('/')}/api/data/export/execute"
        params = build_query_params(job_id=job_id)
        return await self._make_typed_request('POST', url, ExportExecuteResponse, params=params)

    async def get_export_status(self, job_id: str) -> ExportStatusResponse:
        """Get export progress / status."""
        self._check_connection()
        validate_required_params(job_id=job_id)
        url = f"{self._get_server_url().rstrip('/')}/api/data/export/status"
        params = build_query_params(job_id=job_id)
        return await self._make_typed_request('GET', url, ExportStatusResponse, params=params)

    async def download_export_file(self, job_id: str, output_path: str) -> bool:
        """Download completed export file.

        Args:
            job_id: Export job UUID.
            output_path: Local path to save the file.

        Returns:
            True if download successful.
        """
        self._check_connection()
        validate_required_params(job_id=job_id, output_path=output_path)

        try:
            url = f"{self._get_server_url().rstrip('/')}/api/data/export/download?job_id={job_id}"
            response = await self._make_authenticated_request('GET', url)
            response.raise_for_status()

            output_path_obj = Path(output_path)
            output_path_obj.parent.mkdir(parents=True, exist_ok=True)

            with open(output_path_obj, 'wb') as f:
                for chunk in response.iter_bytes(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            return True
        except httpx.HTTPError as e:
            raise VitalGraphClientError(f"Failed to download export file: {e}")
