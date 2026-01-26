"""Mock VitalGraph Client

Mock implementation of VitalGraphClientInterface for testing.
Delegates all method calls to mock endpoints with stub implementations.
"""

import logging
from typing import Dict, Any, List, Optional

from ...client.vitalgraph_client_inf import VitalGraphClientInterface
from .endpoint.mock_spaces_endpoint import MockSpacesEndpoint
from .endpoint.mock_users_endpoint import MockUsersEndpoint
from .endpoint.mock_sparql_endpoint import MockSparqlEndpoint
from .endpoint.mock_kgtypes_endpoint import MockKGTypesEndpoint
from .endpoint.mock_kgframes_endpoint import MockKGFramesEndpoint
from .endpoint.mock_kgentities_endpoint import MockKGEntitiesEndpoint
from .endpoint.mock_kgrelations_endpoint import MockKGRelationsEndpoint
from .endpoint.mock_kgqueries_endpoint import MockKGQueriesEndpoint
from .endpoint.mock_objects_endpoint import MockObjectsEndpoint
from .endpoint.mock_graphs_endpoint import MockGraphsEndpoint
from .endpoint.mock_files_endpoint import MockFilesEndpoint
from .endpoint.mock_triples_endpoint import MockTriplesEndpoint
from .endpoint.mock_import_endpoint import MockImportEndpoint
from .endpoint.mock_export_endpoint import MockExportEndpoint
from .space.mock_space_manager import MockSpaceManager

logger = logging.getLogger(__name__)


class MockVitalGraphClient(VitalGraphClientInterface):
    """
    Mock implementation of VitalGraphClientInterface with in-memory storage.
    """
    
    def __init__(self, config_path: Optional[str] = None, *, config: Optional[Any] = None):
        """
        Initialize the mock VitalGraph client.
        
        Args:
            config_path: Optional config path (ignored in mock implementation)
            config: Optional config object (ignored in mock implementation)
        """
        self.config_path = config_path
        self.config_object = config
        self.is_open = False
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Initialize mock space manager
        self.space_manager = MockSpaceManager()
        
        # Initialize mock endpoints with space manager and config
        self.spaces = MockSpacesEndpoint(self, self.space_manager, config=config)
        self.users = MockUsersEndpoint(self, self.space_manager, config=config)
        self.sparql = MockSparqlEndpoint(self, self.space_manager, config=config)
        self.kgtypes = MockKGTypesEndpoint(self, self.space_manager, config=config)
        self.kgframes = MockKGFramesEndpoint(self, self.space_manager, config=config)
        self.kgentities = MockKGEntitiesEndpoint(self, self.space_manager, config=config)
        self.kgqueries = MockKGQueriesEndpoint(self, self.space_manager, config=config)
        self.objects = MockObjectsEndpoint(self, self.space_manager, config=config)
        self.graphs = MockGraphsEndpoint(self, self.space_manager, config=config)
        self.files = MockFilesEndpoint(self, self.space_manager, config=config)
        self.triples = MockTriplesEndpoint(self, self.space_manager, config=config)
        self.imports = MockImportEndpoint(self, self.space_manager, config=config)
        self.exports = MockExportEndpoint(self, self.space_manager, config=config)
        
        if config is not None:
            self.logger.info("Mock VitalGraph client initialized with provided config object and space manager")
        elif config_path is not None:
            self.logger.info(f"Mock VitalGraph client initialized with config path '{config_path}' and space manager")
        else:
            self.logger.info("Mock VitalGraph client initialized with default config and space manager")
    
    # Connection Management
    
    def open(self) -> None:
        """Open the mock client connection."""
        if self.is_open:
            self.logger.warning("Mock client is already open")
            return
        
        self.is_open = True
        self.logger.info("Mock client connection opened")
    
    def close(self) -> None:
        """Close the mock client connection."""
        if not self.is_open:
            self.logger.warning("Mock client is already closed")
            return
        
        self.is_open = False
        self.logger.info("Mock client connection closed")
    
    def is_connected(self) -> bool:
        """Check if the mock client is connected."""
        return self.is_open
    
    def get_server_info(self) -> Dict[str, Any]:
        """Get mock server information."""
        return {
            "server_url": "mock://localhost:8001",
            "api_base_path": "/api/v1",
            "timeout": 30,
            "max_retries": 3,
            "is_connected": self.is_connected(),
            "authentication": {
                "has_access_token": True,
                "has_refresh_token": True,
                "token_expired": False
            },
            "mock": True
        }
    
    # Space CRUD Methods - Delegate to MockSpacesEndpoint
    
    def list_spaces(self, tenant: Optional[str] = None) -> 'SpacesListResponse':
        """List all spaces."""
        return self.spaces.list_spaces(tenant)
    
    def add_space(self, space: 'Space') -> 'SpaceCreateResponse':
        """Add a new space."""
        return self.spaces.add_space(space)
    
    def get_space(self, space_id: str) -> 'Space':
        """Get a space by ID."""
        return self.spaces.get_space(space_id)
    
    def update_space(self, space_id: str, space: 'Space') -> 'SpaceUpdateResponse':
        """Update a space."""
        return self.spaces.update_space(space_id, space)
    
    def delete_space(self, space_id: str) -> 'SpaceDeleteResponse':
        """Delete a space."""
        return self.spaces.delete_space(space_id)
    
    def filter_spaces(self, name_filter: str, tenant: Optional[str] = None) -> 'SpacesListResponse':
        """Filter spaces by name."""
        return self.spaces.filter_spaces(name_filter, tenant)
    
    # User CRUD Methods - Delegate to MockUsersEndpoint
    
    def list_users(self, tenant: Optional[str] = None) -> 'UsersListResponse':
        """List all users."""
        return self.users.list_users(tenant)
    
    def add_user(self, user: 'User') -> 'UserCreateResponse':
        """Add a new user."""
        return self.users.add_user(user)
    
    def get_user(self, user_id: str) -> 'User':
        """Get a user by ID."""
        return self.users.get_user(user_id)
    
    def update_user(self, user_id: str, user: 'User') -> 'UserUpdateResponse':
        """Update a user."""
        return self.users.update_user(user_id, user)
    
    def delete_user(self, user_id: str) -> 'UserDeleteResponse':
        """Delete a user."""
        return self.users.delete_user(user_id)
    
    def filter_users(self, name_filter: str, tenant: Optional[str] = None) -> 'UsersListResponse':
        """Filter users by name."""
        return self.users.filter_users(name_filter, tenant)
    
    # SPARQL Methods - Delegate to MockSparqlEndpoint
    
    def execute_sparql_query(self, space_id: str, request: 'SPARQLQueryRequest') -> 'SPARQLQueryResponse':
        """Execute a SPARQL query."""
        return self.sparql.execute_sparql_query(space_id, request)
    
    def execute_sparql_insert(self, space_id: str, request: 'SPARQLInsertRequest') -> 'SPARQLInsertResponse':
        """Execute a SPARQL insert operation."""
        return self.sparql.execute_sparql_insert(space_id, request)
    
    def execute_sparql_update(self, space_id: str, request: 'SPARQLUpdateRequest') -> 'SPARQLUpdateResponse':
        """Execute a SPARQL update operation."""
        return self.sparql.execute_sparql_update(space_id, request)
    
    def execute_sparql_delete(self, space_id: str, request: 'SPARQLDeleteRequest') -> 'SPARQLDeleteResponse':
        """Execute a SPARQL delete operation."""
        return self.sparql.execute_sparql_delete(space_id, request)
    
    # KGType CRUD Methods - Delegate to MockKGTypesEndpoint
    
    def list_kgtypes(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> 'KGTypeListResponse':
        """List KGTypes with pagination and optional search."""
        return self.kgtypes.list_kgtypes(space_id, graph_id, page_size, offset, search)
    
    def get_kgtype(self, space_id: str, graph_id: str, uri: str) -> 'KGTypeListResponse':
        """Get a specific KGType by URI."""
        return self.kgtypes.get_kgtype(space_id, graph_id, uri)
    
    def create_kgtypes(self, space_id: str, graph_id: str, document: 'JsonLdDocument') -> 'KGTypeCreateResponse':
        """Create KGTypes from JSON-LD document."""
        return self.kgtypes.create_kgtypes(space_id, graph_id, document)
    
    def update_kgtypes(self, space_id: str, graph_id: str, document: 'JsonLdDocument') -> 'KGTypeUpdateResponse':
        """Update KGTypes from JSON-LD document."""
        return self.kgtypes.update_kgtypes(space_id, graph_id, document)
    
    def delete_kgtype(self, space_id: str, graph_id: str, uri: str) -> 'KGTypeDeleteResponse':
        """Delete a KGType by URI."""
        return self.kgtypes.delete_kgtype(space_id, graph_id, uri)
    
    def delete_kgtypes_batch(self, space_id: str, graph_id: str, uri_list: str) -> 'KGTypeDeleteResponse':
        """Delete multiple KGTypes by URI list."""
        return self.kgtypes.delete_kgtypes_batch(space_id, graph_id, uri_list)
    
    # KGFrame CRUD Methods - Delegate to MockKGFramesEndpoint
    
    def list_kgframes(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> 'FramesResponse':
        """List KGFrames with pagination and optional search."""
        return self.kgframes.list_kgframes(space_id, graph_id, page_size, offset, search)
    
    def get_kgframe(self, space_id: str, graph_id: str, uri: str) -> 'FramesResponse':
        """Get a specific KGFrame by URI."""
        return self.kgframes.get_kgframe(space_id, graph_id, uri)
    
    def create_kgframes(self, space_id: str, graph_id: str, document: 'JsonLdDocument') -> 'FrameCreateResponse':
        """Create KGFrames from JSON-LD document."""
        return self.kgframes.create_kgframes(space_id, graph_id, document)
    
    def update_kgframes(self, space_id: str, graph_id: str, document: 'JsonLdDocument') -> 'FrameUpdateResponse':
        """Update KGFrames from JSON-LD document."""
        return self.kgframes.update_kgframes(space_id, graph_id, document)
    
    def delete_kgframe(self, space_id: str, graph_id: str, uri: str) -> 'FrameDeleteResponse':
        """Delete a KGFrame by URI."""
        return self.kgframes.delete_kgframe(space_id, graph_id, uri)
    
    def delete_kgframes_batch(self, space_id: str, graph_id: str, uri_list: str) -> 'FrameDeleteResponse':
        """Delete multiple KGFrames by URI list."""
        return self.kgframes.delete_kgframes_batch(space_id, graph_id, uri_list)
    
    # Graph Management Methods - Delegate to MockGraphsEndpoint
    
    def list_graphs(self, space_id: str) -> List['GraphInfo']:
        """List graphs in a space."""
        return self.graphs.list_graphs(space_id)
    
    def get_graph_info(self, space_id: str, graph_uri: str) -> 'GraphInfo':
        """Get information about a specific graph."""
        return self.graphs.get_graph_info(space_id, graph_uri)
    
    def create_graph(self, space_id: str, graph_uri: str) -> 'SPARQLGraphResponse':
        """Create a new graph."""
        return self.graphs.create_graph(space_id, graph_uri)
    
    def drop_graph(self, space_id: str, graph_uri: str, silent: bool = False) -> 'SPARQLGraphResponse':
        """Drop (delete) a graph."""
        return self.graphs.drop_graph(space_id, graph_uri, silent)
    
    def clear_graph(self, space_id: str, graph_uri: str) -> 'SPARQLGraphResponse':
        """Clear a graph (remove all triples but keep the graph)."""
        return self.graphs.clear_graph(space_id, graph_uri)
    
    # Objects CRUD Methods - Delegate to MockObjectsEndpoint
    
    def list_objects(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> 'ObjectsResponse':
        """List Objects with pagination and optional search."""
        return self.objects.list_objects(space_id, graph_id, page_size, offset, search)
    
    def get_object(self, space_id: str, graph_id: str, uri: str) -> 'ObjectsResponse':
        """Get a specific Object by URI."""
        return self.objects.get_object(space_id, graph_id, uri)
    
    def create_objects(self, space_id: str, graph_id: str, document: 'JsonLdDocument') -> 'ObjectCreateResponse':
        """Create Objects from JSON-LD document."""
        return self.objects.create_objects(space_id, graph_id, document)
    
    def update_objects(self, space_id: str, graph_id: str, document: 'JsonLdDocument') -> 'ObjectUpdateResponse':
        """Update Objects from JSON-LD document."""
        return self.objects.update_objects(space_id, graph_id, document)
    
    def delete_object(self, space_id: str, graph_id: str, uri: str) -> 'ObjectDeleteResponse':
        """Delete an Object by URI."""
        return self.objects.delete_object(space_id, graph_id, uri)
    
    def delete_objects_batch(self, space_id: str, graph_id: str, uri_list: str) -> 'ObjectDeleteResponse':
        """Delete multiple Objects by URI list."""
        return self.objects.delete_objects_batch(space_id, graph_id, uri_list)
    
    # Triples CRUD Methods - Delegate to MockTriplesEndpoint
    
    def list_triples(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, 
                    subject: Optional[str] = None, predicate: Optional[str] = None, 
                    object: Optional[str] = None, object_filter: Optional[str] = None) -> 'TripleListResponse':
        """List/search triples with pagination and filtering options."""
        return self.triples.list_triples(space_id, graph_id, page_size, offset, subject, predicate, object, object_filter)
    
    def add_triples(self, space_id: str, graph_id: str, document: 'JsonLdDocument') -> 'TripleOperationResponse':
        """Add new triples to the specified graph."""
        return self.triples.add_triples(space_id, graph_id, document)
    
    def delete_triples(self, space_id: str, graph_id: str, 
                      subject: Optional[str] = None, predicate: Optional[str] = None, 
                      object: Optional[str] = None) -> 'TripleOperationResponse':
        """Delete specific triples by pattern."""
        return self.triples.delete_triples(space_id, graph_id, subject, predicate, object)
    
    # KGFrames with Slots Methods - Delegate to MockKGFramesEndpoint
    
    def get_kgframes_with_slots(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> 'FramesResponse':
        """Get KGFrames with their associated slots."""
        return self.kgframes.get_kgframes_with_slots(space_id, graph_id, page_size, offset, search)
    
    def create_kgframes_with_slots(self, space_id: str, graph_id: str, document: 'JsonLdDocument') -> 'FrameCreateResponse':
        """Create KGFrames with their associated slots from JSON-LD document."""
        return self.kgframes.create_kgframes_with_slots(space_id, graph_id, document)
    
    def update_kgframes_with_slots(self, space_id: str, graph_id: str, document: 'JsonLdDocument') -> 'FrameUpdateResponse':
        """Update KGFrames with their associated slots from JSON-LD document."""
        return self.kgframes.update_kgframes_with_slots(space_id, graph_id, document)
    
    def delete_kgframes_with_slots(self, space_id: str, graph_id: str, uri_list: str) -> 'FrameDeleteResponse':
        """Delete KGFrames with their associated slots by URI list."""
        return self.kgframes.delete_kgframes_with_slots(space_id, graph_id, uri_list)
    
    # KGEntity CRUD Methods - Delegate to MockKGEntitiesEndpoint
    
    def list_kgentities(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> 'EntityListResponse':
        """List KGEntities with pagination and optional search."""
        return self.kgentities.list_kgentities(space_id, graph_id, page_size, offset, search)
    
    def get_kgentity(self, space_id: str, graph_id: str, uri: str) -> 'EntityResponse':
        """Get a specific KGEntity by URI."""
        return self.kgentities.get_kgentity(space_id, graph_id, uri)
    
    def create_kgentities(self, space_id: str, graph_id: str, document: 'JsonLdDocument') -> 'EntityCreateResponse':
        """Create KGEntities from JSON-LD document."""
        return self.kgentities.create_kgentities(space_id, graph_id, document)
    
    def update_kgentities(self, space_id: str, graph_id: str, document: 'JsonLdDocument') -> 'EntityUpdateResponse':
        """Update KGEntities from JSON-LD document."""
        return self.kgentities.update_kgentities(space_id, graph_id, document)
    
    def delete_kgentity(self, space_id: str, graph_id: str, uri: str) -> 'EntityDeleteResponse':
        """Delete a KGEntity by URI."""
        return self.kgentities.delete_kgentity(space_id, graph_id, uri)
    
    def delete_kgentities_batch(self, space_id: str, graph_id: str, uri_list: str) -> 'EntityDeleteResponse':
        """Delete multiple KGEntities by URI list."""
        return self.kgentities.delete_kgentities_batch(space_id, graph_id, uri_list)
    
    # File Management Methods - Delegate to MockFilesEndpoint
    
    def list_files(self, space_id: str, graph_id: Optional[str] = None, page_size: int = 100, 
                  offset: int = 0, file_filter: Optional[str] = None) -> 'FilesResponse':
        """List files with pagination and optional filtering."""
        return self.files.list_files(space_id, graph_id, page_size, offset, file_filter)
    
    def get_file(self, space_id: str, uri: str, graph_id: Optional[str] = None) -> 'JsonLdDocument':
        """Get a specific file by URI."""
        return self.files.get_file(space_id, uri, graph_id)
    
    def get_files_by_uris(self, space_id: str, uri_list: str, graph_id: Optional[str] = None) -> 'JsonLdDocument':
        """Get multiple files by URI list."""
        return self.files.get_files_by_uris(space_id, uri_list, graph_id)
    
    def create_file(self, space_id: str, document: 'JsonLdDocument', graph_id: Optional[str] = None) -> 'FileCreateResponse':
        """Create new file node (metadata only)."""
        return self.files.create_file(space_id, document, graph_id)
    
    def update_file(self, space_id: str, document: 'JsonLdDocument', graph_id: Optional[str] = None) -> 'FileUpdateResponse':
        """Update file metadata."""
        return self.files.update_file(space_id, document, graph_id)
    
    def delete_file(self, space_id: str, uri: str, graph_id: Optional[str] = None) -> 'FileDeleteResponse':
        """Delete file node by URI."""
        return self.files.delete_file(space_id, uri, graph_id)
    
    def upload_file_content(self, space_id: str, uri: str, file_path: str, graph_id: Optional[str] = None) -> 'FileUploadResponse':
        """Upload binary file content to existing file node."""
        return self.files.upload_file_content(space_id, uri, file_path, graph_id)
    
    def download_file_content(self, space_id: str, uri: str, output_path: str, graph_id: Optional[str] = None) -> bool:
        """Download binary file content by URI."""
        return self.files.download_file_content(space_id, uri, output_path, graph_id)
    
    # Import Management Methods - Delegate to MockImportEndpoint
    
    def create_import_job(self, import_job: 'ImportJob') -> 'ImportCreateResponse':
        """Create new data import job."""
        return self.imports.create_import_job(import_job)
    
    def list_import_jobs(self, space_id: Optional[str] = None, graph_id: Optional[str] = None, 
                        page_size: int = 100, offset: int = 0) -> 'ImportJobsResponse':
        """List all import jobs with optional filtering."""
        return self.imports.list_import_jobs(space_id, graph_id, page_size, offset)
    
    def get_import_job(self, import_id: str) -> 'ImportJobResponse':
        """Get import job details by ID."""
        return self.imports.get_import_job(import_id)
    
    def update_import_job(self, import_id: str, import_job: 'ImportJob') -> 'ImportUpdateResponse':
        """Update import job."""
        return self.imports.update_import_job(import_id, import_job)
    
    def delete_import_job(self, import_id: str) -> 'ImportDeleteResponse':
        """Delete import job."""
        return self.imports.delete_import_job(import_id)
    
    def execute_import_job(self, import_id: str) -> 'ImportExecuteResponse':
        """Execute import job."""
        return self.imports.execute_import_job(import_id)
    
    def get_import_status(self, import_id: str) -> 'ImportStatusResponse':
        """Get import execution status."""
        return self.imports.get_import_status(import_id)
    
    def get_import_log(self, import_id: str) -> 'ImportLogResponse':
        """Get import execution log."""
        return self.imports.get_import_log(import_id)
    
    def upload_import_file(self, import_id: str, file_path: str) -> 'ImportUploadResponse':
        """Upload file to import job."""
        return self.imports.upload_import_file(import_id, file_path)
    
    # Export Management Methods - Delegate to MockExportEndpoint
    
    def create_export_job(self, export_job: 'ExportJob') -> 'ExportCreateResponse':
        """Create new data export job."""
        return self.exports.create_export_job(export_job)
    
    def list_export_jobs(self, space_id: Optional[str] = None, graph_id: Optional[str] = None, 
                        page_size: int = 100, offset: int = 0) -> 'ExportJobsResponse':
        """List all export jobs with optional filtering."""
        return self.exports.list_export_jobs(space_id, graph_id, page_size, offset)
    
    def get_export_job(self, export_id: str) -> 'ExportJobResponse':
        """Get export job details by ID."""
        return self.exports.get_export_job(export_id)
    
    def update_export_job(self, export_id: str, export_job: 'ExportJob') -> 'ExportUpdateResponse':
        """Update export job."""
        return self.exports.update_export_job(export_id, export_job)
    
    def delete_export_job(self, export_id: str) -> 'ExportDeleteResponse':
        """Delete export job."""
        return self.exports.delete_export_job(export_id)
    
    def execute_export_job(self, export_id: str) -> 'ExportExecuteResponse':
        """Execute export job."""
        return self.exports.execute_export_job(export_id)
    
    def get_export_status(self, export_id: str) -> 'ExportStatusResponse':
        """Get export execution status."""
        return self.exports.get_export_status(export_id)
    
    def download_export_results(self, export_id: str, binary_id: str, output_path: str) -> bool:
        """Download export results."""
        return self.exports.download_export_results(export_id, binary_id, output_path)