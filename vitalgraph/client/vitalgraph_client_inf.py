"""VitalGraph Client Interface

Abstract base class defining the interface for VitalGraph clients.
This interface can be implemented by different client implementations
(REST client, mock client, etc.) to ensure consistent API.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Union
from ..model.sparql_model import (
    SPARQLQueryRequest, SPARQLQueryResponse, SPARQLUpdateRequest, SPARQLUpdateResponse,
    SPARQLInsertRequest, SPARQLInsertResponse, SPARQLDeleteRequest, SPARQLDeleteResponse,
    GraphInfo, SPARQLGraphRequest, SPARQLGraphResponse
)
from .response.client_response import (
    GraphResponse, GraphsListResponse, GraphCreateResponse, GraphDeleteResponse, GraphClearResponse,
    SpaceResponse, SpacesListResponse, SpaceCreateResponse, SpaceUpdateResponse, SpaceDeleteResponse,
    KGTypesListResponse, KGTypeResponse, KGTypeCreateResponse, KGTypeUpdateResponse, KGTypeDeleteResponse,
    ObjectsListResponse, ObjectResponse, ObjectCreateResponse, ObjectUpdateResponse, ObjectDeleteResponse,
    PaginatedGraphObjectResponse, FrameGraphResponse, CreateEntityResponse, UpdateEntityResponse, DeleteResponse,
    EntityResponse,
    FilesListResponse, FileResponse, FileCreateResponse, FileUpdateResponse, FileDeleteResponse, FileUploadResponse,
)
from ..model.triples_model import (
    TripleListResponse, TripleOperationResponse
)
from ..model.users_model import (
    User, UsersListResponse, UserCreateResponse, UserUpdateResponse, UserDeleteResponse
)
from ..model.spaces_model import Space
from ..model.import_model import (
    ImportJobCreate, ImportJob, ImportJobsResponse, ImportJobResponse, ImportCreateResponse,
    ImportDeleteResponse, ImportExecuteResponse, ImportStatusResponse, ImportLogResponse, ImportUploadResponse
)
from ..model.export_model import (
    ExportJobCreate, ExportJob, ExportJobsResponse, ExportJobResponse, ExportCreateResponse,
    ExportDeleteResponse, ExportExecuteResponse, ExportStatusResponse
)
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ..model.quad_model import QuadRequest


class VitalGraphClientInterface(ABC):
    """
    Abstract interface for VitalGraph clients.
    
    Defines the contract that all VitalGraph client implementations must follow.
    This enables dependency injection, testing with mock clients, and multiple
    client implementations (REST, GraphQL, etc.).
    """
    
    # Connection Management
    
    @abstractmethod
    async def open(self) -> None:
        """Open the client connection to the VitalGraph server."""
        pass
    
    @abstractmethod
    async def close(self) -> None:
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
    
    # Context Manager Support (async)
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.open()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    # Space CRUD Methods
    
    @abstractmethod
    async def list_spaces(self, tenant: Optional[str] = None) -> SpacesListResponse:
        """List all spaces."""
        pass
    
    @abstractmethod
    async def add_space(self, space: Space) -> SpaceCreateResponse:
        """Add a new space."""
        pass
    
    @abstractmethod
    async def get_space(self, space_id: str) -> SpaceResponse:
        """Get a space by ID."""
        pass
    
    @abstractmethod
    async def update_space(self, space_id: str, space: Space) -> SpaceUpdateResponse:
        """Update a space."""
        pass
    
    @abstractmethod
    async def delete_space(self, space_id: str) -> SpaceDeleteResponse:
        """Delete a space."""
        pass
    
    @abstractmethod
    async def filter_spaces(self, name_filter: str, tenant: Optional[str] = None) -> SpacesListResponse:
        """Filter spaces by name."""
        pass
    
    # User CRUD Methods
    
    @abstractmethod
    async def list_users(self, tenant: Optional[str] = None) -> UsersListResponse:
        """List all users."""
        pass
    
    @abstractmethod
    async def add_user(self, user: User) -> UserCreateResponse:
        """Add a new user."""
        pass
    
    @abstractmethod
    async def get_user(self, user_id: str) -> User:
        """Get a user by ID."""
        pass
    
    @abstractmethod
    async def update_user(self, user_id: str, user: User) -> UserUpdateResponse:
        """Update a user."""
        pass
    
    @abstractmethod
    async def delete_user(self, user_id: str) -> UserDeleteResponse:
        """Delete a user."""
        pass
    
    @abstractmethod
    async def filter_users(self, name_filter: str, tenant: Optional[str] = None) -> UsersListResponse:
        """Filter users by name."""
        pass
    
    # SPARQL Methods
    
    @abstractmethod
    async def execute_sparql_query(self, space_id: str, request: SPARQLQueryRequest) -> SPARQLQueryResponse:
        """Execute a SPARQL query."""
        pass
    
    @abstractmethod
    async def execute_sparql_insert(self, space_id: str, request: SPARQLInsertRequest) -> SPARQLInsertResponse:
        """Execute a SPARQL insert operation."""
        pass
    
    @abstractmethod
    async def execute_sparql_update(self, space_id: str, request: SPARQLUpdateRequest) -> SPARQLUpdateResponse:
        """Execute a SPARQL update operation."""
        pass
    
    @abstractmethod
    async def execute_sparql_delete(self, space_id: str, request: SPARQLDeleteRequest) -> SPARQLDeleteResponse:
        """Execute a SPARQL delete operation."""
        pass
    
    # KGType CRUD Methods
    
    @abstractmethod
    async def list_kgtypes(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> KGTypesListResponse:
        """List KGTypes with pagination and optional search."""
        pass
    
    @abstractmethod
    async def get_kgtype(self, space_id: str, graph_id: str, uri: str) -> KGTypeResponse:
        """Get a specific KGType by URI."""
        pass
    
    @abstractmethod
    async def create_kgtypes(self, space_id: str, graph_id: str, objects: List[GraphObject]) -> KGTypeCreateResponse:

        """Create KGTypes from GraphObjects."""
        pass
    
    @abstractmethod
    async def update_kgtypes(self, space_id: str, graph_id: str, objects: List[GraphObject]) -> KGTypeUpdateResponse:
        """Update KGTypes from GraphObjects."""
        pass
    
    @abstractmethod
    async def delete_kgtype(self, space_id: str, graph_id: str, uri: str) -> KGTypeDeleteResponse:
        """Delete a KGType by URI."""
        pass
    
    @abstractmethod
    async def delete_kgtypes_batch(self, space_id: str, graph_id: str, uri_list: str) -> KGTypeDeleteResponse:
        """Delete multiple KGTypes by URI list."""
        pass
    
    # KGDocument CRUD Methods
    
    @abstractmethod
    async def list_kgdocuments(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0,
                               search: Optional[str] = None, include_segments: bool = False,
                               document_type_uri: Optional[str] = None):
        """List KGDocuments with pagination and optional filtering."""
        pass
    
    @abstractmethod
    async def get_kgdocument(self, space_id: str, graph_id: str, uri: str):
        """Get a single KGDocument by URI."""
        pass
    
    @abstractmethod
    async def list_kgdocument_segments(self, space_id: str, graph_id: str, parent_uri: str):
        """List segments for a parent KGDocument."""
        pass
    
    @abstractmethod
    async def create_kgdocuments(self, space_id: str, graph_id: str, objects: List[GraphObject]):
        """Create KGDocuments from GraphObjects."""
        pass
    
    @abstractmethod
    async def update_kgdocuments(self, space_id: str, graph_id: str, objects: List[GraphObject]):
        """Update KGDocuments from GraphObjects."""
        pass
    
    @abstractmethod
    async def delete_kgdocument(self, space_id: str, graph_id: str, uri: str):
        """Delete a KGDocument by URI (cascades to segments)."""
        pass
    
    @abstractmethod
    async def delete_kgdocuments_batch(self, space_id: str, graph_id: str, uri_list: str):
        """Delete multiple KGDocuments by URI list (cascades to segments)."""
        pass
    
    @abstractmethod
    async def segment_document(self, space_id: str, graph_id: str, document_uri: str,
                               segment_method_uri: Optional[str] = None,
                               max_segment_tokens: Optional[int] = None):
        """Trigger segmentation for a KGDocument."""
        pass
    
    @abstractmethod
    async def get_segmentation_status(self, space_id: str, document_uri: Optional[str] = None,
                                      status: Optional[str] = None, limit: int = 50, offset: int = 0):
        """Get segmentation job status for a space or specific document."""
        pass
    
    @abstractmethod
    async def list_segmentation_configs(self, space_id: str, enabled_only: bool = False):
        """List segmentation configs for a space."""
        pass

    @abstractmethod
    async def create_segmentation_config(self, space_id: str, document_type_uri: str,
                                         segment_method_uri: str, max_segment_tokens: int = 512,
                                         min_segment_tokens: int = 50, overlap_tokens: int = 0,
                                         enabled: bool = True, auto_vectorize: bool = True):
        """Create a segmentation config."""
        pass

    @abstractmethod
    async def update_segmentation_config(self, space_id: str, config_id: int,
                                         document_type_uri: str, segment_method_uri: str,
                                         max_segment_tokens: int = 512, min_segment_tokens: int = 50,
                                         overlap_tokens: int = 0, enabled: bool = True,
                                         auto_vectorize: bool = True):
        """Update an existing segmentation config."""
        pass

    @abstractmethod
    async def delete_segmentation_config(self, space_id: str, config_id: int):
        """Delete a segmentation config."""
        pass

    # KGFrame CRUD Methods
    
    @abstractmethod
    async def list_kgframes(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0,
                            search: Optional[str] = None, **kwargs) -> PaginatedGraphObjectResponse:
        """List KGFrames with pagination, filtering, and sorting."""
        pass
    
    @abstractmethod
    async def get_kgframe(self, space_id: str, graph_id: str, uri: str) -> FrameGraphResponse:
        """Get a specific KGFrame by URI."""
        pass
    
    @abstractmethod
    async def create_kgframes(self, space_id: str, graph_id: str, objects: List[GraphObject]) -> CreateEntityResponse:
        """Create KGFrames from GraphObjects."""
        pass
    
    @abstractmethod
    async def update_kgframes(self, space_id: str, graph_id: str, objects: List[GraphObject]) -> UpdateEntityResponse:
        """Update KGFrames from GraphObjects."""
        pass
    
    @abstractmethod
    async def delete_kgframe(self, space_id: str, graph_id: str, uri: str) -> DeleteResponse:
        """Delete a KGFrame by URI."""
        pass
    
    @abstractmethod
    async def delete_kgframes_batch(self, space_id: str, graph_id: str, uri_list: str) -> DeleteResponse:
        """Delete multiple KGFrames by URI list."""
        pass
    
    # KGFrames with Slots Methods

    @abstractmethod
    async def get_kgframes_with_slots(self, space_id: str, graph_id: str, page_size: int = 10,
                                      offset: int = 0, search: Optional[str] = None) -> PaginatedGraphObjectResponse:
        """Get KGFrames with their associated slots using pagination."""
        pass

    @abstractmethod
    async def create_kgframes_with_slots(self, space_id: str, graph_id: str, objects: List[GraphObject]):
        """Create KGFrames with their associated slots from GraphObjects."""
        pass

    @abstractmethod
    async def update_kgframes_with_slots(self, space_id: str, graph_id: str, objects: List[GraphObject]):
        """Update KGFrames with their associated slots from GraphObjects."""
        pass

    @abstractmethod
    async def delete_kgframes_with_slots(self, space_id: str, graph_id: str, uri_list: str):
        """Delete KGFrames with their associated slots by URI list."""
        pass

    # KGEntity CRUD Methods

    @abstractmethod
    async def list_kgentities(self, space_id: str, graph_id: str, page_size: int = 10,
                              offset: int = 0, search: Optional[str] = None):
        """List KGEntities with pagination and optional search."""
        pass

    @abstractmethod
    async def get_kgentity(self, space_id: str, graph_id: str, uri: str):
        """Get a specific KGEntity by URI."""
        pass

    @abstractmethod
    async def create_kgentities(self, space_id: str, graph_id: str, objects: List[GraphObject]):
        """Create KGEntities from GraphObjects."""
        pass

    @abstractmethod
    async def update_kgentities(self, space_id: str, graph_id: str, objects: List[GraphObject]):
        """Update KGEntities from GraphObjects."""
        pass

    @abstractmethod
    async def delete_kgentity(self, space_id: str, graph_id: str, uri: str):
        """Delete a KGEntity by URI."""
        pass

    @abstractmethod
    async def delete_kgentities_batch(self, space_id: str, graph_id: str, uri_list: str):
        """Delete multiple KGEntities by URI list."""
        pass

    @abstractmethod
    async def get_kgentity_frames(self, space_id: str, graph_id: str,
                                  entity_uri: Optional[str] = None, page_size: int = 10,
                                  offset: int = 0, search: Optional[str] = None) -> Dict[str, Any]:
        """Get frames associated with KGEntities."""
        pass

    # Health / Diagnostics

    @abstractmethod
    async def health(self) -> Dict[str, Any]:
        """Check service health (no auth required)."""
        pass

    @abstractmethod
    async def cache_stats(self) -> Dict[str, Any]:
        """Fetch entity graph cache statistics (no auth required)."""
        pass

    # Objects CRUD Methods
    
    @abstractmethod
    async def list_objects(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> ObjectsListResponse:
        """List Objects with pagination and optional search."""
        pass
    
    @abstractmethod
    async def get_object(self, space_id: str, graph_id: str, uri: str) -> ObjectResponse:
        """Get a specific Object by URI."""
        pass
    
    @abstractmethod
    async def create_objects(self, space_id: str, graph_id: str, objects: List[GraphObject]) -> ObjectCreateResponse:

        """Create Objects from GraphObjects."""
        pass
    
    @abstractmethod
    async def update_objects(self, space_id: str, graph_id: str, objects: List[GraphObject]) -> ObjectUpdateResponse:
        """Update Objects from GraphObjects."""
        pass
    
    @abstractmethod
    async def delete_object(self, space_id: str, graph_id: str, uri: str) -> ObjectDeleteResponse:
        """Delete an Object by URI."""
        pass
    
    @abstractmethod
    async def delete_objects_batch(self, space_id: str, graph_id: str, uri_list: str) -> ObjectDeleteResponse:
        """Delete multiple Objects by URI list."""
        pass
    
    # Triples CRUD Methods
    
    @abstractmethod
    async def list_triples(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, 
                    subject: Optional[str] = None, predicate: Optional[str] = None, 
                    object: Optional[str] = None, object_filter: Optional[str] = None) -> TripleListResponse:
        """List/search triples with pagination and filtering options."""
        pass
    
    @abstractmethod
    async def add_triples(self, space_id: str, graph_id: str, quad_request: QuadRequest) -> TripleOperationResponse:
        """Add new triples/quads to the specified graph."""
        pass
    
    @abstractmethod
    async def delete_triples(self, space_id: str, graph_id: str, 
                      subject: Optional[str] = None, predicate: Optional[str] = None, 
                      object: Optional[str] = None) -> TripleOperationResponse:
        """Delete specific triples by pattern."""
        pass
    
    # Graph Management Methods
    
    @abstractmethod
    async def list_graphs(self, space_id: str) -> GraphsListResponse:
        """List graphs in a space."""
        pass
    
    @abstractmethod
    async def get_graph_info(self, space_id: str, graph_uri: str) -> GraphResponse:
        """Get information about a specific graph."""
        pass
    
    @abstractmethod
    async def create_graph(self, space_id: str, graph_uri: str) -> GraphCreateResponse:
        """Create a new graph."""
        pass
    
    @abstractmethod
    async def drop_graph(self, space_id: str, graph_uri: str, silent: bool = False) -> GraphDeleteResponse:
        """Drop (delete) a graph."""
        pass
    
    @abstractmethod
    async def clear_graph(self, space_id: str, graph_uri: str) -> GraphClearResponse:
        """Clear a graph (remove all triples but keep the graph)."""
        pass
    
    # File Management Methods
    
    @abstractmethod
    async def list_files(self, space_id: str, graph_id: Optional[str] = None, page_size: int = 100, 
                  offset: int = 0, file_filter: Optional[str] = None) -> FilesListResponse:
        """List files with pagination and optional filtering."""
        pass
    
    @abstractmethod
    async def get_file(self, space_id: str, uri: str, graph_id: Optional[str] = None) -> FileResponse:
        """Get a specific file by URI."""
        pass
    
    @abstractmethod
    async def get_files_by_uris(self, space_id: str, uri_list: str, graph_id: Optional[str] = None) -> FilesListResponse:
        """Get multiple files by URI list."""
        pass
    
    @abstractmethod
    async def create_file(self, space_id: str, objects: List[GraphObject], graph_id: Optional[str] = None) -> FileCreateResponse:
        """Create new file node (metadata only)."""
        pass
    
    @abstractmethod
    async def update_file(self, space_id: str, objects: List[GraphObject], graph_id: Optional[str] = None) -> FileUpdateResponse:
        """Update file metadata."""
        pass
    
    @abstractmethod
    async def delete_file(self, space_id: str, uri: str, graph_id: Optional[str] = None) -> FileDeleteResponse:
        """Delete file node by URI."""
        pass
    
    @abstractmethod
    async def upload_file_content(self, space_id: str, uri: str, file_path: str, graph_id: Optional[str] = None) -> FileUploadResponse:
        """Upload binary file content to existing file node."""
        pass
    
    @abstractmethod
    async def download_file_content(self, space_id: str, uri: str, output_path: str, graph_id: Optional[str] = None) -> bool:
        """Download binary file content by URI."""
        pass
    
    # Import Management Methods

    @abstractmethod
    async def create_import_job(self, request: ImportJobCreate) -> ImportCreateResponse:
        """Create a new import job."""
        pass

    @abstractmethod
    async def list_import_jobs(self, space_id: Optional[str] = None, status: Optional[str] = None,
                               page_size: int = 50, offset: int = 0) -> ImportJobsResponse:
        """List import jobs with optional filtering."""
        pass

    @abstractmethod
    async def get_import_job(self, job_id: str) -> ImportJobResponse:
        """Get import job details by ID."""
        pass

    @abstractmethod
    async def delete_import_job(self, job_id: str) -> ImportDeleteResponse:
        """Cancel (if running) and delete import job."""
        pass

    @abstractmethod
    async def upload_import_file(self, job_id: str, file_path: str) -> ImportUploadResponse:
        """Upload a file for an import job."""
        pass

    @abstractmethod
    async def execute_import_job(self, job_id: str) -> ImportExecuteResponse:
        """Start background import execution."""
        pass

    @abstractmethod
    async def get_import_status(self, job_id: str) -> ImportStatusResponse:
        """Get import progress / status."""
        pass

    @abstractmethod
    async def get_import_log(self, job_id: str) -> ImportLogResponse:
        """Get import log entries."""
        pass

    # Export Management Methods

    @abstractmethod
    async def create_export_job(self, request: ExportJobCreate) -> ExportCreateResponse:
        """Create a new export job."""
        pass

    @abstractmethod
    async def list_export_jobs(self, space_id: Optional[str] = None, status: Optional[str] = None,
                               page_size: int = 50, offset: int = 0) -> ExportJobsResponse:
        """List export jobs with optional filtering."""
        pass

    @abstractmethod
    async def get_export_job(self, job_id: str) -> ExportJobResponse:
        """Get export job details by ID."""
        pass

    @abstractmethod
    async def delete_export_job(self, job_id: str) -> ExportDeleteResponse:
        """Cancel (if running) and delete export job."""
        pass

    @abstractmethod
    async def execute_export_job(self, job_id: str) -> ExportExecuteResponse:
        """Start background export execution."""
        pass

    @abstractmethod
    async def get_export_status(self, job_id: str) -> ExportStatusResponse:
        """Get export progress / status."""
        pass

    @abstractmethod
    async def download_export_file(self, job_id: str, output_path: str) -> bool:
        """Download completed export file."""
        pass