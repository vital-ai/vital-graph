"""VitalGraph Client Interface

Abstract base class defining the interface for VitalGraph clients.
This interface can be implemented by different client implementations
(REST client, mock client, etc.) to ensure consistent API.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from ..model.kgframes_model import (
    FramesResponse, FrameCreateResponse, FrameUpdateResponse, FrameDeleteResponse
)
from ..model.kgtypes_model import (
    KGTypeListResponse, KGTypeCreateResponse, KGTypeUpdateResponse, KGTypeDeleteResponse
)
from ..model.objects_model import (
    ObjectsResponse, ObjectCreateResponse, ObjectUpdateResponse, ObjectDeleteResponse
)
from ..model.sparql_model import (
    SPARQLQueryRequest, SPARQLQueryResponse, SPARQLUpdateRequest, SPARQLUpdateResponse,
    SPARQLInsertRequest, SPARQLInsertResponse, SPARQLDeleteRequest, SPARQLDeleteResponse,
    GraphInfo, SPARQLGraphRequest, SPARQLGraphResponse
)
from ..model.triples_model import (
    TripleListResponse, TripleOperationResponse
)
from ..model.users_model import (
    User, UsersListResponse, UserCreateResponse, UserUpdateResponse, UserDeleteResponse
)
from ..model.spaces_model import (
    Space, SpacesListResponse, SpaceCreateResponse, SpaceUpdateResponse, SpaceDeleteResponse
)
from ..model.files_model import (
    FilesResponse, FileCreateResponse, FileUpdateResponse, FileDeleteResponse, FileUploadResponse
)
from ..model.import_model import (
    ImportJob, ImportJobsResponse, ImportJobResponse, ImportCreateResponse, ImportUpdateResponse, 
    ImportDeleteResponse, ImportExecuteResponse, ImportStatusResponse, ImportLogResponse, ImportUploadResponse
)
from ..model.export_model import (
    ExportJob, ExportJobsResponse, ExportJobResponse, ExportCreateResponse, ExportUpdateResponse, 
    ExportDeleteResponse, ExportExecuteResponse, ExportStatusResponse
)
from ..model.jsonld_model import JsonLdDocument


class VitalGraphClientInterface(ABC):
    """
    Abstract interface for VitalGraph clients.
    
    Defines the contract that all VitalGraph client implementations must follow.
    This enables dependency injection, testing with mock clients, and multiple
    client implementations (REST, GraphQL, etc.).
    """
    
    # Connection Management
    
    @abstractmethod
    def open(self) -> None:
        """Open the client connection to the VitalGraph server."""
        pass
    
    @abstractmethod
    def close(self) -> None:
        """Close the client connection."""
        pass
    
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if the client is currently connected."""
        pass
    
    @abstractmethod
    def get_server_info(self) -> Dict[str, Any]:
        """Get information about the configured server."""
        pass
    
    # Context Manager Support
    
    def __enter__(self):
        """Context manager entry."""
        self.open()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
    
    # Space CRUD Methods
    
    @abstractmethod
    def list_spaces(self, tenant: Optional[str] = None) -> SpacesListResponse:
        """List all spaces."""
        pass
    
    @abstractmethod
    def add_space(self, space: Space) -> SpaceCreateResponse:
        """Add a new space."""
        pass
    
    @abstractmethod
    def get_space(self, space_id: str) -> Space:
        """Get a space by ID."""
        pass
    
    @abstractmethod
    def update_space(self, space_id: str, space: Space) -> SpaceUpdateResponse:
        """Update a space."""
        pass
    
    @abstractmethod
    def delete_space(self, space_id: str) -> SpaceDeleteResponse:
        """Delete a space."""
        pass
    
    @abstractmethod
    def filter_spaces(self, name_filter: str, tenant: Optional[str] = None) -> SpacesListResponse:
        """Filter spaces by name."""
        pass
    
    # User CRUD Methods
    
    @abstractmethod
    def list_users(self, tenant: Optional[str] = None) -> UsersListResponse:
        """List all users."""
        pass
    
    @abstractmethod
    def add_user(self, user: User) -> UserCreateResponse:
        """Add a new user."""
        pass
    
    @abstractmethod
    def get_user(self, user_id: str) -> User:
        """Get a user by ID."""
        pass
    
    @abstractmethod
    def update_user(self, user_id: str, user: User) -> UserUpdateResponse:
        """Update a user."""
        pass
    
    @abstractmethod
    def delete_user(self, user_id: str) -> UserDeleteResponse:
        """Delete a user."""
        pass
    
    @abstractmethod
    def filter_users(self, name_filter: str, tenant: Optional[str] = None) -> UsersListResponse:
        """Filter users by name."""
        pass
    
    # SPARQL Methods
    
    @abstractmethod
    def execute_sparql_query(self, space_id: str, request: SPARQLQueryRequest) -> SPARQLQueryResponse:
        """Execute a SPARQL query."""
        pass
    
    @abstractmethod
    def execute_sparql_insert(self, space_id: str, request: SPARQLInsertRequest) -> SPARQLInsertResponse:
        """Execute a SPARQL insert operation."""
        pass
    
    @abstractmethod
    def execute_sparql_update(self, space_id: str, request: SPARQLUpdateRequest) -> SPARQLUpdateResponse:
        """Execute a SPARQL update operation."""
        pass
    
    @abstractmethod
    def execute_sparql_delete(self, space_id: str, request: SPARQLDeleteRequest) -> SPARQLDeleteResponse:
        """Execute a SPARQL delete operation."""
        pass
    
    # KGType CRUD Methods
    
    @abstractmethod
    def list_kgtypes(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> KGTypeListResponse:
        """List KGTypes with pagination and optional search."""
        pass
    
    @abstractmethod
    def get_kgtype(self, space_id: str, graph_id: str, uri: str) -> KGTypeListResponse:
        """Get a specific KGType by URI."""
        pass
    
    @abstractmethod
    def create_kgtypes(self, space_id: str, graph_id: str, document: JsonLdDocument) -> KGTypeCreateResponse:
        """Create KGTypes from JSON-LD document."""
        pass
    
    @abstractmethod
    def update_kgtypes(self, space_id: str, graph_id: str, document: JsonLdDocument) -> KGTypeUpdateResponse:
        """Update KGTypes from JSON-LD document."""
        pass
    
    @abstractmethod
    def delete_kgtype(self, space_id: str, graph_id: str, uri: str) -> KGTypeDeleteResponse:
        """Delete a KGType by URI."""
        pass
    
    @abstractmethod
    def delete_kgtypes_batch(self, space_id: str, graph_id: str, uri_list: str) -> KGTypeDeleteResponse:
        """Delete multiple KGTypes by URI list."""
        pass
    
    # KGFrame CRUD Methods
    
    @abstractmethod
    def list_kgframes(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> FramesResponse:
        """List KGFrames with pagination and optional search."""
        pass
    
    @abstractmethod
    def get_kgframe(self, space_id: str, graph_id: str, uri: str) -> FramesResponse:
        """Get a specific KGFrame by URI."""
        pass
    
    @abstractmethod
    def create_kgframes(self, space_id: str, graph_id: str, document: JsonLdDocument) -> FrameCreateResponse:
        """Create KGFrames from JSON-LD document."""
        pass
    
    @abstractmethod
    def update_kgframes(self, space_id: str, graph_id: str, document: JsonLdDocument) -> FrameUpdateResponse:
        """Update KGFrames from JSON-LD document."""
        pass
    
    @abstractmethod
    def delete_kgframe(self, space_id: str, graph_id: str, uri: str) -> FrameDeleteResponse:
        """Delete a KGFrame by URI."""
        pass
    
    @abstractmethod
    def delete_kgframes_batch(self, space_id: str, graph_id: str, uri_list: str) -> FrameDeleteResponse:
        """Delete multiple KGFrames by URI list."""
        pass
    
    # Objects CRUD Methods
    
    @abstractmethod
    def list_objects(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> ObjectsResponse:
        """List Objects with pagination and optional search."""
        pass
    
    @abstractmethod
    def get_object(self, space_id: str, graph_id: str, uri: str) -> ObjectsResponse:
        """Get a specific Object by URI."""
        pass
    
    @abstractmethod
    def create_objects(self, space_id: str, graph_id: str, document: JsonLdDocument) -> ObjectCreateResponse:
        """Create Objects from JSON-LD document."""
        pass
    
    @abstractmethod
    def update_objects(self, space_id: str, graph_id: str, document: JsonLdDocument) -> ObjectUpdateResponse:
        """Update Objects from JSON-LD document."""
        pass
    
    @abstractmethod
    def delete_object(self, space_id: str, graph_id: str, uri: str) -> ObjectDeleteResponse:
        """Delete an Object by URI."""
        pass
    
    @abstractmethod
    def delete_objects_batch(self, space_id: str, graph_id: str, uri_list: str) -> ObjectDeleteResponse:
        """Delete multiple Objects by URI list."""
        pass
    
    # Triples CRUD Methods
    
    @abstractmethod
    def list_triples(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, 
                    subject: Optional[str] = None, predicate: Optional[str] = None, 
                    object: Optional[str] = None, object_filter: Optional[str] = None) -> TripleListResponse:
        """List/search triples with pagination and filtering options."""
        pass
    
    @abstractmethod
    def add_triples(self, space_id: str, graph_id: str, document: JsonLdDocument) -> TripleOperationResponse:
        """Add new triples to the specified graph."""
        pass
    
    @abstractmethod
    def delete_triples(self, space_id: str, graph_id: str, 
                      subject: Optional[str] = None, predicate: Optional[str] = None, 
                      object: Optional[str] = None) -> TripleOperationResponse:
        """Delete specific triples by pattern."""
        pass
    
    # Graph Management Methods
    
    @abstractmethod
    def list_graphs(self, space_id: str) -> List[GraphInfo]:
        """List graphs in a space."""
        pass
    
    @abstractmethod
    def get_graph_info(self, space_id: str, graph_uri: str) -> GraphInfo:
        """Get information about a specific graph."""
        pass
    
    @abstractmethod
    def create_graph(self, space_id: str, graph_uri: str) -> SPARQLGraphResponse:
        """Create a new graph."""
        pass
    
    @abstractmethod
    def drop_graph(self, space_id: str, graph_uri: str, silent: bool = False) -> SPARQLGraphResponse:
        """Drop (delete) a graph."""
        pass
    
    @abstractmethod
    def clear_graph(self, space_id: str, graph_uri: str) -> SPARQLGraphResponse:
        """Clear a graph (remove all triples but keep the graph)."""
        pass
    
    # File Management Methods
    
    @abstractmethod
    def list_files(self, space_id: str, graph_id: Optional[str] = None, page_size: int = 100, 
                  offset: int = 0, file_filter: Optional[str] = None) -> FilesResponse:
        """List files with pagination and optional filtering."""
        pass
    
    @abstractmethod
    def get_file(self, space_id: str, uri: str, graph_id: Optional[str] = None) -> JsonLdDocument:
        """Get a specific file by URI."""
        pass
    
    @abstractmethod
    def get_files_by_uris(self, space_id: str, uri_list: str, graph_id: Optional[str] = None) -> JsonLdDocument:
        """Get multiple files by URI list."""
        pass
    
    @abstractmethod
    def create_file(self, space_id: str, document: JsonLdDocument, graph_id: Optional[str] = None) -> FileCreateResponse:
        """Create new file node (metadata only)."""
        pass
    
    @abstractmethod
    def update_file(self, space_id: str, document: JsonLdDocument, graph_id: Optional[str] = None) -> FileUpdateResponse:
        """Update file metadata."""
        pass
    
    @abstractmethod
    def delete_file(self, space_id: str, uri: str, graph_id: Optional[str] = None) -> FileDeleteResponse:
        """Delete file node by URI."""
        pass
    
    @abstractmethod
    def upload_file_content(self, space_id: str, uri: str, file_path: str, graph_id: Optional[str] = None) -> FileUploadResponse:
        """Upload binary file content to existing file node."""
        pass
    
    @abstractmethod
    def download_file_content(self, space_id: str, uri: str, output_path: str, graph_id: Optional[str] = None) -> bool:
        """Download binary file content by URI."""
        pass
    
    # Import Management Methods
    
    @abstractmethod
    def create_import_job(self, import_job: ImportJob) -> ImportCreateResponse:
        """Create new data import job."""
        pass
    
    @abstractmethod
    def list_import_jobs(self, space_id: Optional[str] = None, graph_id: Optional[str] = None, 
                        page_size: int = 100, offset: int = 0) -> ImportJobsResponse:
        """List all import jobs with optional filtering."""
        pass
    
    @abstractmethod
    def get_import_job(self, import_id: str) -> ImportJobResponse:
        """Get import job details by ID."""
        pass
    
    @abstractmethod
    def update_import_job(self, import_id: str, import_job: ImportJob) -> ImportUpdateResponse:
        """Update import job."""
        pass
    
    @abstractmethod
    def delete_import_job(self, import_id: str) -> ImportDeleteResponse:
        """Delete import job."""
        pass
    
    @abstractmethod
    def execute_import_job(self, import_id: str) -> ImportExecuteResponse:
        """Execute import job."""
        pass
    
    @abstractmethod
    def get_import_status(self, import_id: str) -> ImportStatusResponse:
        """Get import execution status."""
        pass
    
    @abstractmethod
    def get_import_log(self, import_id: str) -> ImportLogResponse:
        """Get import execution log."""
        pass
    
    @abstractmethod
    def upload_import_file(self, import_id: str, file_path: str) -> ImportUploadResponse:
        """Upload file to import job."""
        pass
    
    # Export Management Methods
    
    @abstractmethod
    def create_export_job(self, export_job: ExportJob) -> ExportCreateResponse:
        """Create new data export job."""
        pass
    
    @abstractmethod
    def list_export_jobs(self, space_id: Optional[str] = None, graph_id: Optional[str] = None, 
                        page_size: int = 100, offset: int = 0) -> ExportJobsResponse:
        """List all export jobs with optional filtering."""
        pass
    
    @abstractmethod
    def get_export_job(self, export_id: str) -> ExportJobResponse:
        """Get export job details by ID."""
        pass
    
    @abstractmethod
    def update_export_job(self, export_id: str, export_job: ExportJob) -> ExportUpdateResponse:
        """Update export job."""
        pass
    
    @abstractmethod
    def delete_export_job(self, export_id: str) -> ExportDeleteResponse:
        """Delete export job."""
        pass
    
    @abstractmethod
    def execute_export_job(self, export_id: str) -> ExportExecuteResponse:
        """Execute export job."""
        pass
    
    @abstractmethod
    def get_export_status(self, export_id: str) -> ExportStatusResponse:
        """Get export execution status."""
        pass
    
    @abstractmethod
    def download_export_results(self, export_id: str, binary_id: str, output_path: str) -> bool:
        """Download export results by binary ID."""
        pass