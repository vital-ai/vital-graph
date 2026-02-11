"""
VitalGraph Client Import Endpoint

Client-side implementation for Data Import operations.
"""

import httpx
from typing import Dict, Any, Optional, Union, BinaryIO, List
from pathlib import Path

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ..binary.streaming import BinaryGenerator
from ...model.import_model import (
    ImportJob, ImportJobsResponse, ImportJobResponse, ImportCreateResponse, ImportUpdateResponse, 
    ImportDeleteResponse, ImportExecuteResponse, ImportStatusResponse, ImportLogResponse, ImportUploadResponse
)


class ImportEndpoint(BaseEndpoint):
    """Client endpoint for Data Import operations."""
    
    async def create_import_job(self, import_job: ImportJob) -> ImportCreateResponse:
        """
        Create new data import job.
        
        Args:
            import_job: ImportJob object with job details
            
        Returns:
            ImportCreateResponse containing creation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(import_job=import_job)
        
        url = f"{self._get_server_url().rstrip('/')}/api/import"
        
        return await self._make_typed_request('POST', url, ImportCreateResponse, json=import_job.model_dump())
    
    async def list_import_jobs(self, space_id: Optional[str] = None, graph_id: Optional[str] = None,
                        page_size: int = 100, offset: int = 0) -> ImportJobsResponse:
        """
        List all import jobs with optional filtering.
        
        Args:
            space_id: Optional space ID filter
            graph_id: Optional graph ID filter
            page_size: Number of jobs per page (default: 100, max: 1000)
            offset: Offset for pagination (default: 0)
            
        Returns:
            ImportJobsResponse containing import jobs list and pagination info
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        
        url = f"{self._get_server_url().rstrip('/')}/api/import"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            page_size=page_size,
            offset=offset
        )
        
        return await self._make_typed_request('GET', url, ImportJobsResponse, params=params)
    
    async def get_import_job(self, import_id: str) -> ImportJobResponse:
        """
        Get import job details by ID.
        
        Args:
            import_id: Import job ID
            
        Returns:
            ImportJobResponse containing import job details
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(import_id=import_id)
        
        url = f"{self._get_server_url().rstrip('/')}/api/import/{import_id}"
        
        return await self._make_typed_request('GET', url, ImportJobResponse)
    
    async def update_import_job(self, import_id: str, import_job: ImportJob) -> ImportUpdateResponse:
        """
        Update import job.
        
        Args:
            import_id: Import job ID
            import_job: ImportJob object with updated job details
            
        Returns:
            ImportUpdateResponse containing update result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(import_id=import_id, import_job=import_job)
        
        url = f"{self._get_server_url().rstrip('/')}/api/import/{import_id}"
        
        return await self._make_typed_request('PUT', url, ImportUpdateResponse, json=import_job.model_dump())
    
    async def delete_import_job(self, import_id: str) -> ImportDeleteResponse:
        """
        Delete import job.
        
        Args:
            import_id: Import job ID
            
        Returns:
            ImportDeleteResponse containing deletion result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(import_id=import_id)
        
        url = f"{self._get_server_url().rstrip('/')}/api/import/{import_id}"
        
        return await self._make_typed_request('DELETE', url, ImportDeleteResponse)
    
    async def execute_import_job(self, import_id: str) -> ImportExecuteResponse:
        """
        Execute import job.
        
        Args:
            import_id: Import job ID
            
        Returns:
            ImportExecuteResponse containing execution result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(import_id=import_id)
        
        url = f"{self._get_server_url().rstrip('/')}/api/import/{import_id}/execute"
        
        return await self._make_typed_request('POST', url, ImportExecuteResponse)
    
    async def get_import_status(self, import_id: str) -> ImportStatusResponse:
        """
        Get import execution status.
        
        Args:
            import_id: Import job ID
            
        Returns:
            ImportStatusResponse containing import status and progress
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(import_id=import_id)
        
        url = f"{self._get_server_url().rstrip('/')}/api/import/{import_id}/status"
        
        return await self._make_typed_request('GET', url, ImportStatusResponse)
    
    async def get_import_log(self, import_id: str) -> ImportLogResponse:
        """
        Get import execution log.
        
        Args:
            import_id: Import job ID
            
        Returns:
            ImportLogResponse containing import log entries
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(import_id=import_id)
        
        url = f"{self._get_server_url().rstrip('/')}/api/import/{import_id}/log"
        
        return await self._make_typed_request('GET', url, ImportLogResponse)
    
    async def upload_import_file(self, import_id: str, file_path: str) -> ImportUploadResponse:
        """
        Upload file to import job.
        
        Args:
            import_id: Import job ID
            file_path: Path to file to upload
            
        Returns:
            ImportUploadResponse containing upload result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(import_id=import_id, file_path=file_path)
        
        try:
            url = f"{self._get_server_url().rstrip('/')}/api/import/{import_id}/upload"
            
            # Read file and prepare for upload
            file_path_obj = Path(file_path)
            if not file_path_obj.exists():
                raise VitalGraphClientError(f"File not found: {file_path}")
            
            with open(file_path_obj, 'rb') as f:
                files = {'file': (file_path_obj.name, f, 'application/octet-stream')}
                # Use authenticated request with token refresh
                response = await self._make_authenticated_request('POST', url, files=files)
                response.raise_for_status()
                return ImportUploadResponse.model_validate(response.json())
                
        except httpx.HTTPError as e:
            raise VitalGraphClientError(f"Failed to upload import file: {e}")
    
    async def upload_from_generator(self, import_id: str, generator: BinaryGenerator) -> Dict[str, Any]:
        """
        Upload file to import job from a BinaryGenerator.
        
        Args:
            import_id: Import job ID
            generator: BinaryGenerator instance
            
        Returns:
            Dictionary containing upload result
        """
        return await self.upload_import_file(import_id, generator)
