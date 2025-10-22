"""Mock Import Endpoint

Mock implementation of ImportEndpoint for testing.
"""

from typing import Dict, Any, Optional
from .mock_base_endpoint import MockBaseEndpoint
from ....model.import_model import (
    ImportJob, ImportJobsResponse, ImportJobResponse, ImportCreateResponse, ImportUpdateResponse, 
    ImportDeleteResponse, ImportExecuteResponse, ImportStatusResponse, ImportLogResponse, ImportUploadResponse,
    ImportStatus, ImportType
)
from datetime import datetime


class MockImportEndpoint(MockBaseEndpoint):
    """Mock implementation of ImportEndpoint."""
    
    def create_import_job(self, import_job: ImportJob) -> ImportCreateResponse:
        """Create new data import job."""
        self._log_method_call("create_import_job", import_job=import_job)
        
        # Generate mock import job
        mock_job = ImportJob(
            import_id="mock_import_001",
            name=import_job.name,
            description=import_job.description,
            import_type=import_job.import_type,
            space_id=import_job.space_id,
            graph_id=import_job.graph_id,
            status=ImportStatus.CREATED,
            created_date=datetime.utcnow(),
            updated_date=datetime.utcnow(),
            progress_percent=0.0,
            records_processed=0,
            config=import_job.config or {},
            uploaded_files=[]
        )
        
        mock_data = {
            "message": "Successfully created import job",
            "import_id": "mock_import_001",
            "import_job": mock_job
        }
        
        return ImportCreateResponse.model_validate(mock_data)
    
    def list_import_jobs(self, space_id: Optional[str] = None, graph_id: Optional[str] = None,
                        page_size: int = 100, offset: int = 0) -> ImportJobsResponse:
        """List all import jobs with optional filtering."""
        self._log_method_call("list_import_jobs", space_id=space_id, graph_id=graph_id, page_size=page_size, offset=offset)
        
        # Generate mock import jobs
        mock_data = {
            "import_jobs": [],
            "total_count": 0,
            "page_size": page_size,
            "offset": offset
        }
        
        return ImportJobsResponse.model_validate(mock_data)
    
    def get_import_job(self, import_id: str) -> ImportJobResponse:
        """Get import job details by ID."""
        self._log_method_call("get_import_job", import_id=import_id)
        
        # Generate mock import job
        mock_job = ImportJob(
            import_id=import_id,
            name="Mock Import Job",
            description="Mock import job for testing",
            import_type=ImportType.JSON_LD,
            space_id="mock_space_001",
            graph_id="mock_graph_001",
            status=ImportStatus.PENDING,
            created_date=datetime.utcnow(),
            updated_date=datetime.utcnow(),
            progress_percent=0.0,
            records_processed=0,
            config={},
            uploaded_files=[]
        )
        
        mock_data = {
            "import_job": mock_job
        }
        
        return ImportJobResponse.model_validate(mock_data)
    
    def update_import_job(self, import_id: str, import_job: ImportJob) -> ImportUpdateResponse:
        """Update import job."""
        self._log_method_call("update_import_job", import_id=import_id, import_job=import_job)
        
        # Generate mock updated job
        updated_job = ImportJob(
            import_id=import_id,
            name=import_job.name,
            description=import_job.description,
            import_type=import_job.import_type,
            space_id=import_job.space_id,
            graph_id=import_job.graph_id,
            status=import_job.status or ImportStatus.CREATED,
            created_date=datetime.utcnow(),
            updated_date=datetime.utcnow(),
            progress_percent=import_job.progress_percent or 0.0,
            records_processed=import_job.records_processed or 0,
            config=import_job.config or {},
            uploaded_files=import_job.uploaded_files or []
        )
        
        mock_data = {
            "message": "Successfully updated import job",
            "import_job": updated_job
        }
        
        return ImportUpdateResponse.model_validate(mock_data)
    
    def delete_import_job(self, import_id: str) -> ImportDeleteResponse:
        """Delete import job."""
        self._log_method_call("delete_import_job", import_id=import_id)
        
        mock_data = {
            "message": "Successfully deleted import job",
            "import_id": import_id
        }
        
        return ImportDeleteResponse.model_validate(mock_data)
    
    def execute_import_job(self, import_id: str) -> ImportExecuteResponse:
        """Execute import job."""
        self._log_method_call("execute_import_job", import_id=import_id)
        
        mock_data = {
            "message": "Successfully started import job execution",
            "import_id": import_id,
            "execution_started": True
        }
        
        return ImportExecuteResponse.model_validate(mock_data)
    
    def get_import_status(self, import_id: str) -> ImportStatusResponse:
        """Get import execution status."""
        self._log_method_call("get_import_status", import_id=import_id)
        
        mock_data = {
            "import_id": import_id,
            "status": ImportStatus.RUNNING,
            "progress_percent": 75.0,
            "records_processed": 750,
            "records_total": 1000,
            "started_date": datetime.utcnow(),
            "completed_date": None,
            "error_message": None
        }
        
        return ImportStatusResponse.model_validate(mock_data)
    
    def get_import_log(self, import_id: str) -> ImportLogResponse:
        """Get import execution log."""
        self._log_method_call("get_import_log", import_id=import_id)
        
        mock_data = {
            "import_id": import_id,
            "log_entries": [
                {
                    "timestamp": "2024-01-01T10:00:00Z",
                    "level": "INFO",
                    "message": "Mock import job started",
                    "details": {"records_total": 1000}
                }
            ],
            "total_entries": 1
        }
        
        return ImportLogResponse.model_validate(mock_data)
    
    def upload_import_file(self, import_id: str, file_path: str) -> ImportUploadResponse:
        """Upload file to import job."""
        self._log_method_call("upload_import_file", import_id=import_id, file_path=file_path)
        
        from pathlib import Path
        file_path_obj = Path(file_path)
        
        mock_data = {
            "message": "Successfully uploaded file to import job",
            "import_id": import_id,
            "filename": file_path_obj.name if file_path_obj.exists() else "mock_file.txt",
            "file_size": 1024
        }
        
        return ImportUploadResponse.model_validate(mock_data)
    
    def upload_from_generator(self, import_id: str, generator) -> Dict[str, Any]:
        """Upload file to import job from a BinaryGenerator."""
        self._log_method_call("upload_from_generator", import_id=import_id)
        return self._create_stub_response("upload_from_generator", import_id=import_id, uploaded_bytes=1024)
