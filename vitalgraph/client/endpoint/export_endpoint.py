"""
VitalGraph Client Export Endpoint

Client-side implementation for Data Export operations.
"""

import httpx
from typing import Dict, Any, Optional, Union, BinaryIO, List
from pathlib import Path

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ..binary.streaming import BinaryConsumer
from ...model.export_model import (
    ExportJob, ExportJobsResponse, ExportJobResponse, ExportCreateResponse, ExportUpdateResponse, 
    ExportDeleteResponse, ExportExecuteResponse, ExportStatusResponse
)


class ExportEndpoint(BaseEndpoint):
    """Client endpoint for Data Export operations."""
    
    def create_export_job(self, export_job: ExportJob) -> ExportCreateResponse:
        """
        Create new data export job.
        
        Args:
            export_job: ExportJob object with job details
            
        Returns:
            ExportCreateResponse containing creation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(export_job=export_job)
        
        url = f"{self._get_server_url().rstrip('/')}/api/export"
        
        return self._make_typed_request('POST', url, ExportCreateResponse, json=export_job.model_dump())
    
    def list_export_jobs(self, space_id: Optional[str] = None, graph_id: Optional[str] = None,
                        page_size: int = 100, offset: int = 0) -> ExportJobsResponse:
        """
        List all export jobs with optional filtering.
        
        Args:
            space_id: Optional space ID filter
            graph_id: Optional graph ID filter
            page_size: Number of jobs per page (default: 100, max: 1000)
            offset: Offset for pagination (default: 0)
            
        Returns:
            ExportJobsResponse containing export jobs list and pagination info
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        
        url = f"{self._get_server_url().rstrip('/')}/api/export"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            page_size=page_size,
            offset=offset
        )
        
        return self._make_typed_request('GET', url, ExportJobsResponse, params=params)
    
    def get_export_job(self, export_id: str) -> ExportJobResponse:
        """
        Get export job details by ID.
        
        Args:
            export_id: Export job ID
            
        Returns:
            ExportJobResponse containing export job details
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(export_id=export_id)
        
        url = f"{self._get_server_url().rstrip('/')}/api/export/{export_id}"
        
        return self._make_typed_request('GET', url, ExportJobResponse)
    
    def update_export_job(self, export_id: str, export_job: ExportJob) -> ExportUpdateResponse:
        """
        Update export job.
        
        Args:
            export_id: Export job ID
            export_job: ExportJob object with updated job details
            
        Returns:
            ExportUpdateResponse containing update result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(export_id=export_id, export_job=export_job)
        
        url = f"{self._get_server_url().rstrip('/')}/api/export/{export_id}"
        
        return self._make_typed_request('PUT', url, ExportUpdateResponse, json=export_job.model_dump())
    
    def delete_export_job(self, export_id: str) -> ExportDeleteResponse:
        """
        Delete export job.
        
        Args:
            export_id: Export job ID
            
        Returns:
            ExportDeleteResponse containing deletion result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(export_id=export_id)
        
        url = f"{self._get_server_url().rstrip('/')}/api/export/{export_id}"
        
        return self._make_typed_request('DELETE', url, ExportDeleteResponse)
    
    def execute_export_job(self, export_id: str) -> ExportExecuteResponse:
        """
        Execute export job.
        
        Args:
            export_id: Export job ID
            
        Returns:
            ExportExecuteResponse containing execution result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(export_id=export_id)
        
        url = f"{self._get_server_url().rstrip('/')}/api/export/{export_id}/execute"
        
        return self._make_typed_request('POST', url, ExportExecuteResponse)
    
    def get_export_status(self, export_id: str) -> ExportStatusResponse:
        """
        Get export execution status.
        
        Args:
            export_id: Export job ID
            
        Returns:
            ExportStatusResponse containing export status and progress
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(export_id=export_id)
        
        url = f"{self._get_server_url().rstrip('/')}/api/export/{export_id}/status"
        
        return self._make_typed_request('GET', url, ExportStatusResponse)
    
    def download_export_results(self, export_id: str, binary_id: str, output_path: str) -> bool:
        """
        Download export results by binary ID.
        
        Args:
            export_id: Export job ID
            binary_id: Binary file ID to download
            output_path: Path where to save the downloaded file
            
        Returns:
            True if download successful
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(export_id=export_id, binary_id=binary_id, output_path=output_path)
        
        try:
            url = f"{self._get_server_url().rstrip('/')}/api/export/{export_id}/download"
            params = build_query_params(binary_id=binary_id)
            
            # Use authenticated request with token refresh
            response = self._make_authenticated_request('GET', url, params=params, stream=True)
            response.raise_for_status()
            
            # Save to file
            output_path_obj = Path(output_path)
            output_path_obj.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_path_obj, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            return True
            
        except httpx.HTTPError as e:
            raise VitalGraphClientError(f"Failed to download export results: {e}")
    
    def download_to_consumer(self, export_id: str, binary_id: str, 
                            consumer: BinaryConsumer, chunk_size: int = 8192) -> Dict[str, Any]:
        """
        Download export results to a BinaryConsumer.
        
        Args:
            export_id: Export job ID
            binary_id: Binary file ID to download
            consumer: BinaryConsumer instance
            chunk_size: Size of chunks for streaming
            
        Returns:
            Dictionary containing download result
        """
        return self.download_export_results(export_id, binary_id, consumer, chunk_size)
    
    def get_export_files(self, export_id: str) -> List[Dict[str, Any]]:
        """
        Get list of available export output files.
        
        Args:
            export_id: Export job ID
            
        Returns:
            List of output file dictionaries with binary_id, filename, size, mime_type
            
        Raises:
            VitalGraphClientError: If request fails
        """
        job_details = self.get_export_job(export_id)
        export_job = job_details.get('export_job', {})
        return export_job.get('output_files', [])
    
    def download_all_export_files(self, export_id: str, destination_dir: Union[str, Path],
                                 chunk_size: int = 8192) -> Dict[str, Any]:
        """
        Download all export output files to a directory.
        
        Args:
            export_id: Export job ID
            destination_dir: Directory to save files
            chunk_size: Size of chunks for streaming
            
        Returns:
            Dictionary containing download results for all files
            
        Raises:
            VitalGraphClientError: If request fails
        """
        destination_path = Path(destination_dir)
        destination_path.mkdir(parents=True, exist_ok=True)
        
        output_files = self.get_export_files(export_id)
        results = []
        
        for file_info in output_files:
            binary_id = file_info.get('binary_id')
            filename = file_info.get('filename', f'export_{binary_id}')
            
            if binary_id:
                file_path = destination_path / filename
                result = self.download_export_results(export_id, binary_id, file_path, chunk_size)
                results.append({
                    "binary_id": binary_id,
                    "filename": filename,
                    "file_path": str(file_path),
                    "result": result
                })
        
        return {
            "success": True,
            "export_id": export_id,
            "destination_dir": str(destination_path),
            "files_downloaded": len(results),
            "file_results": results
        }
