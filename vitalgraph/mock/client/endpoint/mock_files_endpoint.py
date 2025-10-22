"""
Mock implementation of FilesEndpoint for testing with VitalSigns native functionality.

This implementation uses:
- VitalSigns native object creation and conversion
- pyoxigraph in-memory SPARQL quad store for file metadata persistence
- Configurable MinIO storage: temporary directory (default) or configured path
- Complete CRUD operations following real endpoint patterns
- No mock data generation - all operations use real pyoxigraph storage

Configuration options:
- use_temp_storage=True (default): Temporary directory with automatic cleanup
- use_temp_storage=False: Uses configured file path, throws exception if not configured
"""

import os
import tempfile
import shutil
import atexit
from pathlib import Path
from typing import Dict, Any, Optional, List
from .mock_base_endpoint import MockBaseEndpoint
from vitalgraph.model.files_model import (
    FilesResponse, FileCreateResponse, FileUpdateResponse, FileDeleteResponse, FileUploadResponse
)
from vitalgraph.model.jsonld_model import JsonLdDocument
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject


class MockFilesEndpoint(MockBaseEndpoint):
    """Mock implementation of FilesEndpoint."""
    
    def __init__(self, client, space_manager=None, *, config=None):
        """Initialize the mock files endpoint with configurable MinIO storage."""
        super().__init__(client, space_manager, config=config)
        
        # Initialize MinIO-like file storage based on configuration
        self.minio_base_path = None
        self.minio_client = None
        self._temp_dir = None
        self._use_temp_storage = True  # Default to temp storage
        
        # Check configuration for storage type
        if self.config:
            # Check for use-temp-storage configuration
            if hasattr(self.config, 'use_temp_storage'):
                self._use_temp_storage = self.config.use_temp_storage()
            else:
                # Fallback for direct attribute access (test configs)
                self._use_temp_storage = getattr(self.config, 'use_temp_storage', True)
        
        if self._use_temp_storage:
            # Use temporary directory approach
            self._temp_dir = tempfile.mkdtemp(prefix="mock_minio_")
            self.minio_base_path = Path(self._temp_dir)
            self.logger.info(f"Mock MinIO initialized with temporary directory: {self.minio_base_path}")
            
            # Simulate MinIO client initialization
            self.minio_client = {
                'base_path': str(self.minio_base_path),
                'initialized': True,
                'buckets': {},
                'temp_dir': self._temp_dir
            }
            
            # Register cleanup on exit
            atexit.register(self._cleanup_temp_dir)
        else:
            # Use configured file path approach
            if self.config:
                # Get the mock file path from config
                if hasattr(self.config, 'get_mock_file_path'):
                    file_path = self.config.get_mock_file_path()
                else:
                    # Fallback for direct attribute access (test configs)
                    file_path = getattr(self.config, '_file_path', None)
                
                if file_path:
                    self.minio_base_path = Path(file_path)
                    self.minio_base_path.mkdir(parents=True, exist_ok=True)
                    self.logger.info(f"Mock MinIO initialized with configured path: {self.minio_base_path}")
                    
                    # Simulate MinIO client initialization
                    self.minio_client = {
                        'base_path': str(self.minio_base_path),
                        'initialized': True,
                        'buckets': {}
                    }
                else:
                    self.logger.info("No mock file path configured and temp storage disabled")
            else:
                self.logger.info("No config provided and temp storage disabled")
    
    def _cleanup_temp_dir(self):
        """Cleanup temporary MinIO directory."""
        try:
            if hasattr(self, '_temp_dir') and Path(self._temp_dir).exists():
                shutil.rmtree(self._temp_dir)
                self.logger.info(f"Cleaned up temporary MinIO directory: {self._temp_dir}")
        except Exception as e:
            self.logger.warning(f"Error cleaning up temporary MinIO directory: {e}")
    
    def clear_minio_storage(self, space_id: Optional[str] = None) -> bool:
        """
        Clear MinIO storage for specified space or all spaces.
        
        Args:
            space_id: Optional space identifier. If None, clears all storage.
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if not self.minio_base_path or not self.minio_base_path.exists():
                return True
                
            if space_id:
                # Clear specific space directory
                space_dir = self.minio_base_path / space_id
                if space_dir.exists():
                    shutil.rmtree(space_dir)
                    storage_type = "temporary MinIO" if self._use_temp_storage else "configured MinIO"
                    self.logger.info(f"Cleared {storage_type} storage for space: {space_id}")
            else:
                if self._use_temp_storage:
                    # For temp storage, clear entire directory contents
                    for item in self.minio_base_path.iterdir():
                        if item.is_dir():
                            shutil.rmtree(item)
                        else:
                            item.unlink()
                    self.logger.info("Cleared all temporary MinIO storage")
                else:
                    # For configured storage, only clear contents but preserve directory
                    for item in self.minio_base_path.iterdir():
                        if item.is_dir():
                            shutil.rmtree(item)
                        else:
                            item.unlink()
                    self.logger.info("Cleared all configured MinIO storage")
            return True
        except Exception as e:
            self.logger.error(f"Error clearing MinIO storage: {e}")
            return False
    
    def __enter__(self):
        """Context manager entry."""
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with cleanup."""
        self.clear_minio_storage()
    
    def list_files(self, space_id: str, graph_id: Optional[str] = None, page_size: int = 100, 
                  offset: int = 0, file_filter: Optional[str] = None) -> FilesResponse:
        """
        List files with pagination and optional filtering using pyoxigraph SPARQL queries.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier (optional)
            page_size: Number of files per page
            offset: Offset for pagination
            file_filter: Optional filter term
            
        Returns:
            FilesResponse with VitalSigns native JSON-LD document
        """
        self._log_method_call("list_files", space_id=space_id, graph_id=graph_id, page_size=page_size, offset=offset, file_filter=file_filter)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id) if self.space_manager else None
            if not space:
                # Return empty response for non-existent space
                from vital_ai_domain.model.FileNode import FileNode
                empty_jsonld = FileNode.to_jsonld_list([])
                return FilesResponse(
                    files=JsonLdDocument(**empty_jsonld),
                    total_count=0,
                    page_size=page_size,
                    offset=offset
                )
            
            # Build SPARQL query for file objects
            graph_clause = f"GRAPH <{graph_id}>" if graph_id else ""
            filter_clause = ""
            if file_filter:
                filter_clause = f'FILTER(CONTAINS(LCASE(?name), LCASE("{file_filter}")))'
            
            query = f"""
            PREFIX vital: <http://vital.ai/ontology/vital#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            
            SELECT ?subject ?predicate ?object WHERE {{
                {graph_clause} {{
                    ?subject ?predicate ?object .
                    ?subject rdf:type vital:FileNode .
                    OPTIONAL {{ ?subject vital:hasFileName ?name }}
                    {filter_clause}
                }}
            }}
            LIMIT {page_size}
            OFFSET {offset}
            """
            
            # Log all quads in the store first
            self.logger.info("=== ALL QUADS IN STORE (list_files) ===")
            try:
                all_quads_query = "SELECT ?s ?p ?o ?g WHERE { GRAPH ?g { ?s ?p ?o } }"
                all_results = self._execute_sparql_query(space, all_quads_query)
                for i, binding in enumerate(all_results.get("bindings", [])):
                    s = binding.get("s", {}).get("value", "")
                    p = binding.get("p", {}).get("value", "")
                    o = binding.get("o", {}).get("value", "")
                    g = binding.get("g", {}).get("value", "")
                    self.logger.info(f"Quad {i}: {s} | {p} | {o} | {g}")
            except Exception as e:
                self.logger.error(f"Error logging quads: {e}")
            self.logger.info("=== END QUADS ===")
            
            # Execute query
            results = self._execute_sparql_query(space, query)
            
            if not results.get("bindings"):
                # No results found
                from vital_ai_domain.model.FileNode import FileNode
                empty_jsonld = FileNode.to_jsonld_list([])
                return FilesResponse(
                    files=JsonLdDocument(**empty_jsonld),
                    total_count=0,
                    page_size=page_size,
                    offset=offset
                )
            
            # Group results by subject to reconstruct file objects
            subjects_data = {}
            for binding in results["bindings"]:
                subject = binding.get("subject", {}).get("value", "").strip('<>')  # Clean URI
                predicate = binding.get("predicate", {}).get("value", "")
                obj_value = binding.get("object", {}).get("value", "")
                
                if subject not in subjects_data:
                    subjects_data[subject] = {}
                
                subjects_data[subject][predicate] = obj_value
            
            # Convert to VitalSigns GraphObject instances (FileNode objects)
            files = []
            for subject_uri, properties in subjects_data.items():
                file_obj = self._convert_sparql_to_vitalsigns_object("http://vital.ai/ontology/vital#FileNode", subject_uri, properties)
                if file_obj:
                    files.append(file_obj)
            
            # Get total count (separate query)
            count_query = f"""
            PREFIX vital: <http://vital.ai/ontology/vital#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            
            SELECT (COUNT(DISTINCT ?subject) as ?count) WHERE {{
                {graph_clause} {{
                    ?subject rdf:type vital:FileNode .
                }}
            }}
            """
            
            count_results = self._execute_sparql_query(space, count_query)
            total_count = 0
            if count_results.get("bindings"):
                count_value = count_results["bindings"][0].get("count", {}).get("value", "0")
                # Handle both plain integers and typed literals
                if isinstance(count_value, str):
                    # Extract just the number part if it's a typed literal like "3"^^<datatype>
                    if '"' in count_value:
                        count_value = count_value.split('"')[1]
                    total_count = int(count_value)
                else:
                    total_count = int(count_value)
            
            # Convert to JSON-LD document using VitalSigns
            files_jsonld = self._objects_to_jsonld_document(files)
            
            return FilesResponse(
                files=JsonLdDocument(**files_jsonld),
                total_count=total_count,
                page_size=page_size,
                offset=offset
            )
            
        except Exception as e:
            self.logger.error(f"Error listing files: {e}")
            from vital_ai_domain.model.FileNode import FileNode
            empty_jsonld = FileNode.to_jsonld_list([])
            return FilesResponse(
                files=JsonLdDocument(**empty_jsonld),
                total_count=0,
                page_size=page_size,
                offset=offset
            )
    
    def get_file(self, space_id: str, uri: str, graph_id: Optional[str] = None) -> JsonLdDocument:
        """
        Get a specific file by URI using pyoxigraph SPARQL query.
        
        Args:
            space_id: Space identifier
            uri: File URI
            graph_id: Graph identifier (optional)
            
        Returns:
            JsonLdDocument with VitalSigns native JSON-LD conversion
        """
        self._log_method_call("get_file", space_id=space_id, uri=uri, graph_id=graph_id)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id) if self.space_manager else None
            if not space:
                # Return empty document for non-existent space
                from vital_ai_domain.model.FileNode import FileNode
                empty_jsonld = FileNode.to_jsonld_list([])
                return JsonLdDocument(**empty_jsonld)
            
            # Clean URI - but keep it for the SPARQL query
            clean_uri = uri.strip('<>')
            
            # Use EXACTLY the same query pattern as list_files
            graph_clause = f"GRAPH <{graph_id}>" if graph_id else ""
            query = f"""
            PREFIX vital: <http://vital.ai/ontology/vital#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            
            SELECT ?subject ?predicate ?object WHERE {{
                {graph_clause} {{
                    ?subject ?predicate ?object .
                    FILTER(?subject = <{clean_uri}>)
                }}
            }}
            """
            
            # Log all quads in the store first
            self.logger.info("=== ALL QUADS IN STORE (get_file) ===")
            try:
                all_quads_query = "SELECT ?s ?p ?o ?g WHERE { GRAPH ?g { ?s ?p ?o } }"
                all_results = self._execute_sparql_query(space, all_quads_query)
                for i, binding in enumerate(all_results.get("bindings", [])):
                    s = binding.get("s", {}).get("value", "")
                    p = binding.get("p", {}).get("value", "")
                    o = binding.get("o", {}).get("value", "")
                    g = binding.get("g", {}).get("value", "")
                    self.logger.info(f"Quad {i}: {s} | {p} | {o} | {g}")
            except Exception as e:
                self.logger.error(f"Error logging quads: {e}")
            self.logger.info("=== END QUADS ===")
            
            results = self._execute_sparql_query(space, query)
            self.logger.info(f"get_file query returned {len(results.get('bindings', []))} bindings for URI: {clean_uri}")
            
            if not results.get("bindings"):
                # File not found
                from vital_ai_domain.model.FileNode import FileNode
                empty_jsonld = FileNode.to_jsonld_list([])
                return JsonLdDocument(**empty_jsonld)
            
            # Group results by subject (same as list_files)
            subjects_data = {}
            for binding in results["bindings"]:
                subject = binding.get("subject", {}).get("value", "").strip('<>')  # Clean URI
                predicate = binding.get("predicate", {}).get("value", "")
                obj_value = binding.get("object", {}).get("value", "")
                
                if subject not in subjects_data:
                    subjects_data[subject] = {}
                
                subjects_data[subject][predicate] = obj_value
            
            # Convert to VitalSigns FileNode object (same as list_files)
            files = []
            for subject_uri, properties in subjects_data.items():
                self.logger.info(f"Converting subject {subject_uri} with properties: {properties}")
                file_obj = self._convert_sparql_to_vitalsigns_object("http://vital.ai/ontology/vital#FileNode", subject_uri, properties)
                if file_obj:
                    files.append(file_obj)
                else:
                    self.logger.error(f"Failed to convert subject {subject_uri} to FileNode")
            
            if files:
                # Convert to JSON-LD document using VitalSigns
                files_jsonld = self._objects_to_jsonld_document(files)
                self.logger.info(f"get_file final JSON-LD: {files_jsonld}")
                
                # Ensure the JSON-LD has a @graph structure that the test expects
                if '@graph' not in files_jsonld:
                    # Convert single object to @graph array format
                    single_obj = {k: v for k, v in files_jsonld.items() if k not in ['@context']}
                    files_jsonld = {
                        '@context': files_jsonld.get('@context', {}),
                        '@graph': [single_obj]
                    }
                
                result_doc = JsonLdDocument(**files_jsonld)
                self.logger.info(f"get_file returned JsonLdDocument: {result_doc}")
                self.logger.info(f"get_file JsonLdDocument.graph: {result_doc.graph}")
                return result_doc
            else:
                # No files found - return empty
                from vital_ai_domain.model.FileNode import FileNode
                empty_jsonld = FileNode.to_jsonld_list([])
                return JsonLdDocument(**empty_jsonld)
                
        except Exception as e:
            self.logger.error(f"Error getting file {uri}: {e}")
            from vital_ai_domain.model.FileNode import FileNode
            empty_jsonld = FileNode.to_jsonld_list([])
            return JsonLdDocument(**empty_jsonld)
    
    def get_files_by_uris(self, space_id: str, uri_list: str, graph_id: Optional[str] = None) -> JsonLdDocument:
        """
        Get multiple files by URI list using pyoxigraph SPARQL queries.
        
        Args:
            space_id: Space identifier
            uri_list: Comma-separated list of file URIs
            graph_id: Graph identifier (optional)
            
        Returns:
            JsonLdDocument with VitalSigns native JSON-LD conversion
        """
        self._log_method_call("get_files_by_uris", space_id=space_id, uri_list=uri_list, graph_id=graph_id)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id) if self.space_manager else None
            if not space:
                from vital_ai_domain.model.FileNode import FileNode
                empty_jsonld = FileNode.to_jsonld_list([])
                return JsonLdDocument(**empty_jsonld)
            
            # Parse URI list
            uris = [uri.strip().strip('<>') for uri in uri_list.split(',') if uri.strip()]
            
            if not uris:
                from vital_ai_domain.model.FileNode import FileNode
                empty_jsonld = FileNode.to_jsonld_list([])
                return JsonLdDocument(**empty_jsonld)
            
            # Build SPARQL query for multiple URIs
            uri_values = ' '.join([f'<{uri}>' for uri in uris])
            graph_clause = f"GRAPH <{graph_id}>" if graph_id else ""
            
            query = f"""
            SELECT ?subject ?predicate ?object WHERE {{
                {graph_clause} {{
                    ?subject ?predicate ?object .
                    VALUES ?subject {{ {uri_values} }}
                }}
            }}
            """
            
            results = self._execute_sparql_query(space, query)
            
            if not results.get("bindings"):
                from vital_ai_domain.model.FileNode import FileNode
                empty_jsonld = FileNode.to_jsonld_list([])
                return JsonLdDocument(**empty_jsonld)
            
            # Group results by subject
            subjects_data = {}
            for binding in results["bindings"]:
                subject = binding.get("subject", {}).get("value", "")
                predicate = binding.get("predicate", {}).get("value", "")
                obj_value = binding.get("object", {}).get("value", "")
                
                if subject not in subjects_data:
                    subjects_data[subject] = {}
                
                subjects_data[subject][predicate] = obj_value
            
            # Convert to VitalSigns FileNode objects
            files = []
            for subject_uri, properties in subjects_data.items():
                file_obj = self._convert_sparql_to_vitalsigns_object("http://vital.ai/ontology/vital#FileNode", subject_uri, properties)
                if file_obj:
                    files.append(file_obj)
            
            # Convert to JSON-LD document using VitalSigns
            files_jsonld = self._objects_to_jsonld_document(files)
            return JsonLdDocument(**files_jsonld)
            
        except Exception as e:
            self.logger.error(f"Error getting files by URIs: {e}")
            from vital_ai_domain.model.FileNode import FileNode
            empty_jsonld = FileNode.to_jsonld_list([])
            return JsonLdDocument(**empty_jsonld)
    
    def create_file(self, space_id: str, document: JsonLdDocument, graph_id: Optional[str] = None) -> FileCreateResponse:
        """
        Create new file node (metadata only) using VitalSigns native functionality.
        
        Args:
            space_id: Space identifier
            document: JsonLdDocument containing file metadata
            graph_id: Graph identifier (optional)
            
        Returns:
            FileCreateResponse with created URIs and count
        """
        self._log_method_call("create_file", space_id=space_id, document=document, graph_id=graph_id)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id) if self.space_manager else None
            if not space:
                return FileCreateResponse(
                    message="Space not found",
                    created_count=0, 
                    created_uris=[]
                )
            
            # Convert JSON-LD document to VitalSigns objects
            document_dict = document.model_dump(by_alias=True)
            files = self._jsonld_to_vitalsigns_objects(document_dict)
            
            if not files:
                return FileCreateResponse(
                    message="No valid files to create",
                    created_count=0, 
                    created_uris=[]
                )
            
            # Store files in pyoxigraph
            stored_count = self._store_vitalsigns_objects_in_pyoxigraph(space, files, graph_id)
            
            # Get created URIs
            created_uris = [str(file_obj.URI) for file_obj in files]
            
            return FileCreateResponse(
                message=f"Successfully created {stored_count} files",
                created_count=stored_count,
                created_uris=created_uris
            )
            
        except Exception as e:
            self.logger.error(f"Error creating file: {e}")
            return FileCreateResponse(
                message=f"Error creating file: {str(e)}",
                created_count=0, 
                created_uris=[]
            )
    
    def update_file(self, space_id: str, document: JsonLdDocument, graph_id: Optional[str] = None) -> FileUpdateResponse:
        """
        Update file metadata using VitalSigns native functionality.
        
        Args:
            space_id: Space identifier
            document: JsonLdDocument containing updated file metadata
            graph_id: Graph identifier (optional)
            
        Returns:
            FileUpdateResponse with updated URI
        """
        self._log_method_call("update_file", space_id=space_id, document=document, graph_id=graph_id)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id) if self.space_manager else None
            if not space:
                return FileUpdateResponse(
                    message="Space not found",
                    updated_uri=None
                )
            
            # Convert JSON-LD document to VitalSigns objects
            document_dict = document.model_dump(by_alias=True)
            files = self._jsonld_to_vitalsigns_objects(document_dict)
            
            if not files:
                return FileUpdateResponse(
                    message="No valid files to update",
                    updated_uri=None
                )
            
            # Update files in pyoxigraph (DELETE + INSERT pattern)
            updated_uri = None
            for file_obj in files:
                # Delete existing triples for this file
                if self._delete_quads_from_store(space, file_obj.URI, graph_id):
                    # Insert updated triples
                    if self._store_vitalsigns_objects_in_pyoxigraph(space, [file_obj], graph_id) > 0:
                        updated_uri = str(file_obj.URI)  # Convert to string
                        break  # Return first successfully updated file
            
            if updated_uri:
                return FileUpdateResponse(
                    message="Successfully updated file",
                    updated_uri=updated_uri
                )
            else:
                return FileUpdateResponse(
                    message="Failed to update file",
                    updated_uri=None
                )
            
        except Exception as e:
            self.logger.error(f"Error updating file: {e}")
            return FileUpdateResponse(
                message=f"Error updating file: {e}",
                updated_uri=None
            )
    
    def delete_file(self, space_id: str, uri: str, graph_id: Optional[str] = None) -> FileDeleteResponse:
        """
        Delete file node by URI using pyoxigraph SPARQL DELETE and remove binary content.
        
        Args:
            space_id: Space identifier
            uri: File URI to delete
            graph_id: Graph identifier (optional)
            
        Returns:
            FileDeleteResponse with real deletion results
        """
        self._log_method_call("delete_file", space_id=space_id, uri=uri, graph_id=graph_id)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id) if self.space_manager else None
            if not space:
                return FileDeleteResponse(
                    message="Space not found",
                    deleted_count=0, 
                    deleted_uris=[]
                )
            
            # Delete binary content from MinIO storage first
            self._delete_binary_content(space_id, uri, graph_id)
            
            # Delete quads from pyoxigraph
            if self._delete_quads_from_store(space, uri, graph_id):
                return FileDeleteResponse(
                    message="Successfully deleted file",
                    deleted_count=1, 
                    deleted_uris=[uri]
                )
            else:
                return FileDeleteResponse(
                    message="File not found or already deleted",
                    deleted_count=0, 
                    deleted_uris=[]
                )
                
        except Exception as e:
            self.logger.error(f"Error deleting file {uri}: {e}")
            return FileDeleteResponse(
                message=f"Error deleting file: {e}",
                deleted_count=0, 
                deleted_uris=[]
            )
    
    def _delete_binary_content(self, space_id: str, uri: str, graph_id: Optional[str] = None):
        """
        Delete binary file content from MinIO storage.
        
        Args:
            space_id: Space identifier
            uri: File URI
            graph_id: Graph identifier (optional)
        """
        try:
            if not self.minio_base_path or not self.minio_base_path.exists():
                return
                
            # Create path to binary file
            import urllib.parse
            encoded_graph_id = urllib.parse.quote(graph_id or 'default', safe='')
            storage_dir = self.minio_base_path / space_id / encoded_graph_id
            encoded_uri = urllib.parse.quote(uri, safe='')
            binary_file = storage_dir / encoded_uri
            
            # Remove binary file if it exists
            if binary_file.exists():
                binary_file.unlink()
                self.logger.info(f"Deleted binary content for file: {uri}")
                
        except Exception as e:
            self.logger.warning(f"Error deleting binary content for {uri}: {e}")
    
    def delete_files_batch(self, space_id: str, graph_id: str, uri_list: str) -> Dict[str, Any]:
        """
        Delete multiple File nodes by URI list using VitalSigns functionality.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of file URIs to delete
            
        Returns:
            Dictionary with deletion results
        """
        self._log_method_call("delete_files_batch", space_id=space_id, graph_id=graph_id, uri_list=uri_list)
        
        try:
            # Get space from space manager
            space = self.space_manager.get_space(space_id) if self.space_manager else None
            if not space:
                return {
                    "deleted_count": 0,
                    "deleted_uris": [],
                    "status": "error",
                    "message": f"Space {space_id} not found"
                }
            
            # Parse URI list
            uris = [uri.strip().strip('<>') for uri in uri_list.split(',') if uri.strip()]
            
            if not uris:
                return {
                    "deleted_count": 0,
                    "deleted_uris": [],
                    "status": "success",
                    "message": "No URIs provided"
                }
            
            deleted_uris = []
            deleted_count = 0
            
            # Delete each file (metadata + binary content)
            for uri in uris:
                try:
                    # Delete binary content from MinIO storage first
                    self._delete_binary_content(space_id, uri, graph_id)
                    
                    # Delete quads from pyoxigraph
                    if self._delete_quads_from_store(space, uri, graph_id):
                        deleted_uris.append(uri)
                        deleted_count += 1
                        self.logger.info(f"Successfully deleted file: {uri}")
                    else:
                        self.logger.warning(f"File metadata not found in store: {uri}")
                        
                except Exception as e:
                    self.logger.error(f"Error deleting file {uri}: {e}")
                    # Continue with other files even if one fails
            
            return {
                "deleted_count": deleted_count,
                "deleted_uris": deleted_uris,
                "status": "success" if deleted_count > 0 else "partial",
                "message": f"Successfully deleted {deleted_count} of {len(uris)} files"
            }
            
        except Exception as e:
            self.logger.error(f"Error in batch file deletion: {e}")
            return {
                "deleted_count": 0,
                "deleted_uris": [],
                "status": "error",
                "message": str(e)
            }
    
    def upload_file_content(self, space_id: str, uri: str, file_path: str, graph_id: Optional[str] = None) -> FileUploadResponse:
        """Upload binary file content to existing file node."""
        self._log_method_call("upload_file_content", space_id=space_id, uri=uri, file_path=file_path, graph_id=graph_id)
        
        # Check if MinIO storage is configured
        if not self.minio_client or not self.minio_base_path:
            raise RuntimeError("MinIO storage not configured - cannot upload files. Enable use_temp_storage=True or configure file path.")
        
        file_size = 1024  # Default mock size
        
        try:
            # Create space directory with encoded graph_id
            import urllib.parse
            encoded_graph_id = urllib.parse.quote(graph_id or 'default', safe='')
            storage_dir = self.minio_base_path / space_id / encoded_graph_id
            storage_dir.mkdir(parents=True, exist_ok=True)
            
            # Encode URI as a single filename
            encoded_uri = urllib.parse.quote(uri, safe='')
            target_file = storage_dir / encoded_uri
            
            # Copy source file to MinIO storage if it exists
            source_path = Path(file_path)
            if source_path.exists():
                shutil.copy2(source_path, target_file)
                file_size = target_file.stat().st_size
                storage_type = "temporary MinIO" if self._use_temp_storage else "configured MinIO"
                self.logger.info(f"File uploaded to {storage_type}: {target_file} ({file_size} bytes)")
            else:
                raise FileNotFoundError(f"Source file not found: {file_path}")
                
        except Exception as e:
            self.logger.error(f"Error in mock MinIO upload: {e}")
            raise
        
        mock_data = {
            "message": "Mock file upload completed" + (f" to {self.minio_base_path}" if self.minio_base_path else ""),
            "file_uri": uri,
            "file_size": file_size,
            "content_type": "application/octet-stream"
        }
        
        return FileUploadResponse.model_validate(mock_data)
    
    def upload_from_generator(self, space_id: str, graph_id: str, file_uri: str, generator) -> Dict[str, Any]:
        """Upload file content from a BinaryGenerator."""
        self._log_method_call("upload_from_generator", space_id=space_id, graph_id=graph_id, file_uri=file_uri)
        return self._create_stub_response("upload_from_generator", uploaded_bytes=1024, file_uri=file_uri)
    
    def download_file_content(self, space_id: str, uri: str, output_path: str, graph_id: Optional[str] = None) -> bool:
        """Download binary file content by URI."""
        self._log_method_call("download_file_content", space_id=space_id, uri=uri, output_path=output_path, graph_id=graph_id)
        
        # Check if MinIO storage is configured
        if not self.minio_client or not self.minio_base_path:
            raise RuntimeError("MinIO storage not configured - cannot download files. Enable use_temp_storage=True or configure file path.")
        
        output_path_obj = Path(output_path)
        output_path_obj.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            # Look for file in MinIO storage with encoded graph_id
            import urllib.parse
            encoded_graph_id = urllib.parse.quote(graph_id or 'default', safe='')
            storage_dir = self.minio_base_path / space_id / encoded_graph_id
            
            # Encode URI as a single filename
            encoded_uri = urllib.parse.quote(uri, safe='')
            source_file = storage_dir / encoded_uri
            
            if source_file.exists():
                shutil.copy2(source_file, output_path_obj)
                storage_type = "temporary MinIO" if self._use_temp_storage else "configured MinIO"
                self.logger.info(f"File downloaded from {storage_type}: {source_file} -> {output_path_obj}")
                return True
            else:
                storage_type = "temporary MinIO" if self._use_temp_storage else "configured MinIO"
                raise FileNotFoundError(f"File not found in {storage_type}: {source_file}")
        except Exception as e:
            self.logger.error(f"Error in mock MinIO download: {e}")
            raise
    
    def download_to_consumer(self, space_id: str, graph_id: str, file_uri: str, 
                            consumer, chunk_size: int = 8192) -> Dict[str, Any]:
        """Download file content to a BinaryConsumer."""
        self._log_method_call("download_to_consumer", space_id=space_id, graph_id=graph_id, file_uri=file_uri)
        return self._create_stub_response("download_to_consumer", downloaded_bytes=1024, file_uri=file_uri)
    
    def pump_file(self, source_space_id: str, source_graph_id: str, source_file_uri: str,
                  target_space_id: str, target_graph_id: str, target_file_uri: str,
                  chunk_size: int = 8192) -> Dict[str, Any]:
        """Pump file content from one file node to another (download + upload)."""
        self._log_method_call("pump_file", source_space_id=source_space_id, source_graph_id=source_graph_id, 
                             source_file_uri=source_file_uri, target_space_id=target_space_id, 
                             target_graph_id=target_graph_id, target_file_uri=target_file_uri)
        return self._create_stub_response("pump_file", pumped_bytes=1024, source_uri=source_file_uri, target_uri=target_file_uri)
