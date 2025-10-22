"""Mock Export Endpoint

Mock implementation of ExportEndpoint for testing.
"""

from typing import Dict, Any, Optional, List
from .mock_base_endpoint import MockBaseEndpoint
from ....model.export_model import (
    ExportJob, ExportJobsResponse, ExportJobResponse, ExportCreateResponse, ExportUpdateResponse, 
    ExportDeleteResponse, ExportExecuteResponse, ExportStatusResponse,
    ExportStatus, ExportFormat
)
from datetime import datetime


class MockExportEndpoint(MockBaseEndpoint):
    """Mock implementation of ExportEndpoint."""
    
    def create_export_job(self, export_job: ExportJob) -> ExportCreateResponse:
        """Create new data export job."""
        self._log_method_call("create_export_job", export_job=export_job)
        
        # Generate mock export job
        mock_job = ExportJob(
            export_id="mock_export_001",
            name=export_job.name,
            description=export_job.description,
            export_format=export_job.export_format,
            space_id=export_job.space_id,
            graph_id=export_job.graph_id,
            status=ExportStatus.CREATED,
            created_date=datetime.utcnow(),
            updated_date=datetime.utcnow(),
            progress_percent=0.0,
            records_processed=0,
            config=export_job.config or {},
            output_files=[],
            query_filter=export_job.query_filter
        )
        
        mock_data = {
            "message": "Successfully created export job",
            "export_id": "mock_export_001",
            "export_job": mock_job
        }
        
        return ExportCreateResponse.model_validate(mock_data)
    
    def list_export_jobs(self, space_id: Optional[str] = None, graph_id: Optional[str] = None,
                        page_size: int = 100, offset: int = 0) -> ExportJobsResponse:
        """List all export jobs with optional filtering."""
        self._log_method_call("list_export_jobs", space_id=space_id, graph_id=graph_id, page_size=page_size, offset=offset)
        
        # Generate mock export jobs
        mock_data = {
            "export_jobs": [],
            "total_count": 0,
            "page_size": page_size,
            "offset": offset
        }
        
        return ExportJobsResponse.model_validate(mock_data)
    
    def get_export_job(self, export_id: str) -> ExportJobResponse:
        """Get export job details by ID."""
        self._log_method_call("get_export_job", export_id=export_id)
        
        # Generate mock export job
        mock_job = ExportJob(
            export_id=export_id,
            name="Mock Export Job",
            description="Mock export job for testing",
            export_format=ExportFormat.JSON_LD,
            space_id="mock_space_001",
            graph_id="mock_graph_001",
            status=ExportStatus.PENDING,
            created_date=datetime.utcnow(),
            updated_date=datetime.utcnow(),
            progress_percent=0.0,
            records_processed=0,
            config={},
            output_files=[],
            query_filter=None
        )
        
        mock_data = {
            "export_job": mock_job
        }
        
        return ExportJobResponse.model_validate(mock_data)
    
    def update_export_job(self, export_id: str, export_job: ExportJob) -> ExportUpdateResponse:
        """Update export job."""
        self._log_method_call("update_export_job", export_id=export_id, export_job=export_job)
        
        # Generate mock updated job
        updated_job = ExportJob(
            export_id=export_id,
            name=export_job.name,
            description=export_job.description,
            export_format=export_job.export_format,
            space_id=export_job.space_id,
            graph_id=export_job.graph_id,
            status=export_job.status or ExportStatus.CREATED,
            created_date=datetime.utcnow(),
            updated_date=datetime.utcnow(),
            progress_percent=export_job.progress_percent or 0.0,
            records_processed=export_job.records_processed or 0,
            config=export_job.config or {},
            output_files=export_job.output_files or [],
            query_filter=export_job.query_filter
        )
        
        mock_data = {
            "message": "Successfully updated export job",
            "export_job": updated_job
        }
        
        return ExportUpdateResponse.model_validate(mock_data)
    
    def delete_export_job(self, export_id: str) -> ExportDeleteResponse:
        """Delete export job."""
        self._log_method_call("delete_export_job", export_id=export_id)
        
        mock_data = {
            "message": "Successfully deleted export job",
            "export_id": export_id
        }
        
        return ExportDeleteResponse.model_validate(mock_data)
    
    def execute_export_job(self, export_id: str) -> ExportExecuteResponse:
        """Execute export job."""
        self._log_method_call("execute_export_job", export_id=export_id)
        
        mock_data = {
            "message": "Successfully started export job execution",
            "export_id": export_id,
            "execution_started": True
        }
        
        return ExportExecuteResponse.model_validate(mock_data)
    
    def get_export_status(self, export_id: str) -> ExportStatusResponse:
        """Get export execution status."""
        self._log_method_call("get_export_status", export_id=export_id)
        
        mock_data = {
            "export_id": export_id,
            "status": ExportStatus.RUNNING,
            "progress_percent": 75.0,
            "records_processed": 750,
            "records_total": 1000,
            "started_date": datetime.utcnow(),
            "completed_date": None,
            "error_message": None,
            "output_files": [
                {"binary_id": "mock_binary_1", "filename": "export.ttl", "size": 1024, "mime_type": "text/turtle"}
            ]
        }
        
        return ExportStatusResponse.model_validate(mock_data)
    
    def download_export_results(self, export_id: str, binary_id: str, output_path: str) -> bool:
        """Download export results by binary ID."""
        self._log_method_call("download_export_results", export_id=export_id, binary_id=binary_id, output_path=output_path)
        
        # Simulate writing mock content to file
        from pathlib import Path
        output_path_obj = Path(output_path)
        output_path_obj.parent.mkdir(parents=True, exist_ok=True)
        
        # Generate mock export content based on binary_id
        if "ttl" in binary_id or "turtle" in binary_id:
            mock_content = "@prefix ex: <http://example.org/> .\nex:entity1 ex:hasProperty \"Mock Export Data\" ."
        elif "csv" in binary_id:
            mock_content = "id,name,value\n1,Mock Entity,Mock Value"
        else:
            mock_content = '{"export_data": "Mock JSON export content"}'
        
        output_path_obj.write_text(mock_content)
        
        return True
    
    def download_to_consumer(self, export_id: str, binary_id: str, 
                            consumer, chunk_size: int = 8192) -> Dict[str, Any]:
        """Download export results to a BinaryConsumer."""
        self._log_method_call("download_to_consumer", export_id=export_id, binary_id=binary_id)
        return self._create_stub_response("download_to_consumer", export_id=export_id, downloaded_bytes=1024)
    
    def get_export_files(self, export_id: str) -> List[Dict[str, Any]]:
        """Get list of available export output files."""
        self._log_method_call("get_export_files", export_id=export_id)
        return [{"binary_id": "mock_binary_1", "filename": "export.ttl", "size": 1024, "mime_type": "text/turtle"}]
    
    def download_all_export_files(self, export_id: str, destination_dir, 
                                 chunk_size: int = 8192) -> Dict[str, Any]:
        """Download all export output files to a directory."""
        self._log_method_call("download_all_export_files", export_id=export_id, destination_dir=destination_dir)
        return self._create_stub_response("download_all_export_files", export_id=export_id, files_downloaded=1, total_bytes=1024)
