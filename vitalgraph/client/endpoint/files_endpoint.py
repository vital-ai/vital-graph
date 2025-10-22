"""
VitalGraph Client Files Endpoint

Client-side implementation for Files operations.
"""

import requests
from typing import Dict, Any, Optional, BinaryIO, Union
from pathlib import Path

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ..binary.streaming import BinaryGenerator, BinaryConsumer
from ...model.files_model import (
    FilesResponse, FileCreateResponse, FileUpdateResponse, FileDeleteResponse, FileUploadResponse
)
from ...model.jsonld_model import JsonLdDocument


class FilesEndpoint(BaseEndpoint):
    """Client endpoint for Files operations."""
    
    def list_files(self, space_id: str, graph_id: Optional[str] = None, page_size: int = 100, 
                  offset: int = 0, file_filter: Optional[str] = None) -> FilesResponse:
        """
        List files with pagination and optional filtering.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier (optional)
            page_size: Number of items per page
            offset: Offset for pagination
            file_filter: Optional file filter
            
        Returns:
            FilesResponse containing files data and pagination info
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        
        url = f"{self._get_server_url().rstrip('/')}/api/files"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            page_size=page_size,
            offset=offset,
            file_filter=file_filter
        )
        
        return self._make_typed_request('GET', url, FilesResponse, params=params)
    
    def get_file(self, space_id: str, uri: str, graph_id: Optional[str] = None) -> JsonLdDocument:
        """
        Get a specific file by URI.
        
        Args:
            space_id: Space identifier
            uri: File URI
            graph_id: Graph identifier (optional)
            
        Returns:
            JsonLdDocument containing file metadata
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, uri=uri)
        
        url = f"{self._get_server_url().rstrip('/')}/api/files"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            uri=uri
        )
        
        return self._make_typed_request('GET', url, JsonLdDocument, params=params)
    
    def get_files_by_uris(self, space_id: str, uri_list: str, graph_id: Optional[str] = None) -> JsonLdDocument:
        """
        Get multiple files by URI list.
        
        Args:
            space_id: Space identifier
            uri_list: Comma-separated list of file URIs
            graph_id: Graph identifier (optional)
            
        Returns:
            JsonLdDocument containing multiple file metadata
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, uri_list=uri_list)
        
        url = f"{self._get_server_url().rstrip('/')}/api/files"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            uri_list=uri_list
        )
        
        return self._make_typed_request('GET', url, JsonLdDocument, params=params)
    
    def create_file(self, space_id: str, document: JsonLdDocument, graph_id: Optional[str] = None) -> FileCreateResponse:
        """
        Create new file node (metadata only).
        
        Args:
            space_id: Space identifier
            document: JSON-LD document containing file metadata
            graph_id: Graph identifier (optional)
            
        Returns:
            FileCreateResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, document=document)
        
        url = f"{self._get_server_url().rstrip('/')}/api/files"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id
        )
        
        return self._make_typed_request('POST', url, FileCreateResponse, params=params, json=document.model_dump())
    
    def update_file(self, space_id: str, document: JsonLdDocument, graph_id: Optional[str] = None) -> FileUpdateResponse:
        """
        Update file metadata.
        
        Args:
            space_id: Space identifier
            document: JSON-LD document containing file metadata
            graph_id: Graph identifier (optional)
            
        Returns:
            FileUpdateResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, document=document)
        
        url = f"{self._get_server_url().rstrip('/')}/api/files"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id
        )
        
        return self._make_typed_request('PUT', url, FileUpdateResponse, params=params, json=document.model_dump())
    
    def delete_file(self, space_id: str, uri: str, graph_id: Optional[str] = None) -> FileDeleteResponse:
        """
        Delete file node by URI.
        
        Args:
            space_id: Space identifier
            uri: File URI to delete
            graph_id: Graph identifier (optional)
            
        Returns:
            FileDeleteResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, uri=uri)
        
        url = f"{self._get_server_url().rstrip('/')}/api/files"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            uri=uri
        )
        
        return self._make_typed_request('DELETE', url, FileDeleteResponse, params=params)
    
    def upload_file_content(self, space_id: str, uri: str, file_path: str, graph_id: Optional[str] = None) -> FileUploadResponse:
        """
        Upload binary file content to existing file node.
        
        Args:
            space_id: Space identifier
            uri: File node URI
            file_path: Path to file to upload
            graph_id: Graph identifier (optional)
            
        Returns:
            FileUploadResponse containing upload result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, uri=uri, file_path=file_path)
        
        try:
            url = f"{self._get_server_url().rstrip('/')}/api/files/upload"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                uri=uri
            )
            
            # Read file and prepare for upload
            file_path_obj = Path(file_path)
            if not file_path_obj.exists():
                raise VitalGraphClientError(f"File not found: {file_path}")
            
            with open(file_path_obj, 'rb') as f:
                files = {'file': (file_path_obj.name, f, 'application/octet-stream')}
                response = self.client.session.post(url, params=params, files=files)
                response.raise_for_status()
                return FileUploadResponse.model_validate(response.json())
                
        except requests.exceptions.RequestException as e:
            raise VitalGraphClientError(f"Failed to upload file content: {e}")
    
    def download_file_content(self, space_id: str, uri: str, output_path: str, graph_id: Optional[str] = None) -> bool:
        """
        Download binary file content by URI.
        
        Args:
            space_id: Space identifier
            uri: File URI to download
            output_path: Path where to save the downloaded file
            graph_id: Graph identifier (optional)
            
        Returns:
            True if download successful
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, uri=uri, output_path=output_path)
        
        try:
            url = f"{self._get_server_url().rstrip('/')}/api/files/download"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                uri=uri
            )
            
            response = self.client.session.get(url, params=params, stream=True)
            response.raise_for_status()
            
            # Save to file
            output_path_obj = Path(output_path)
            output_path_obj.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_path_obj, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            return True
            
        except requests.exceptions.RequestException as e:
            raise VitalGraphClientError(f"Failed to download file content: {e}")

    # Legacy methods for backward compatibility (keeping some of the complex streaming functionality)
    def delete_files_batch(self, space_id: str, graph_id: str, uri_list: str) -> Dict[str, Any]:
        """
        Delete multiple File nodes by URI list.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of File URIs
            
        Returns:
            Dictionary containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri_list=uri_list)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/files"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                uri_list=uri_list
            )
            
            response = self._make_authenticated_request('DELETE', url, params=params)
            return response.json()
        except requests.exceptions.RequestException as e:
            raise VitalGraphClientError(f"Failed to delete File nodes: {e}")
    
    def upload_file_content(self, space_id: str, graph_id: str, file_uri: str, 
                           source: Union[bytes, BinaryIO, str, Path, BinaryGenerator], 
                           filename: Optional[str] = None, 
                           content_type: Optional[str] = None,
                           chunk_size: int = 8192) -> Dict[str, Any]:
        """
        Upload file content to a File node using streaming generators.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            file_uri: File node URI
            source: Data source (bytes, file object, path, or BinaryGenerator)
            filename: Original filename (optional, inferred from source if not provided)
            content_type: MIME content type (optional, inferred if not provided)
            chunk_size: Size of chunks for streaming (default: 8192)
            
        Returns:
            Dictionary containing upload result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, file_uri=file_uri, source=source)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/files/upload"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                file_uri=file_uri
            )
            
            # Create generator from source
            generator = create_generator(
                source, 
                chunk_size=chunk_size, 
                filename=filename, 
                content_type=content_type
            )
            
            # Use generator properties for metadata
            final_filename = filename or generator.filename or 'uploaded_file'
            final_content_type = content_type or generator.content_type
            
            # Create a streaming iterator for requests
            def stream_generator():
                for chunk in generator.generate():
                    yield chunk
            
            files = {
                'file': (final_filename, stream_generator(), final_content_type)
            }
            
            response = self._make_authenticated_request('POST', url, params=params, files=files)
            return response.json()
            
        except requests.exceptions.RequestException as e:
            raise VitalGraphClientError(f"Failed to upload file content: {e}")
    
    def upload_from_generator(self, space_id: str, graph_id: str, file_uri: str, 
                             generator: BinaryGenerator) -> Dict[str, Any]:
        """
        Upload file content from a BinaryGenerator.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            file_uri: File node URI
            generator: BinaryGenerator instance
            
        Returns:
            Dictionary containing upload result
        """
        return self.upload_file_content(space_id, graph_id, file_uri, generator)
    
    def download_file_content(self, space_id: str, graph_id: str, file_uri: str, 
                             destination: Optional[Union[str, Path, BinaryIO, BinaryConsumer]] = None,
                             chunk_size: int = 8192) -> Union[bytes, Dict[str, Any]]:
        """
        Download file content from a File node using streaming consumers.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            file_uri: File node URI
            destination: Optional destination (path, stream, or BinaryConsumer)
            chunk_size: Size of chunks for streaming (default: 8192)
            
        Returns:
            File content as bytes if destination is None, otherwise operation result dict
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, file_uri=file_uri)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/files/download"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                file_uri=file_uri
            )
            
            response = self._make_authenticated_request('GET', url, params=params, stream=True)
            
            if destination is None:
                # Return raw bytes - use BytesConsumer for consistency
                consumer = BytesConsumer()
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        consumer.consume(chunk)
                consumer.finalize()
                return consumer.get_bytes()
            else:
                # Use consumer for streaming
                consumer = create_consumer(destination)
                total_size = 0
                
                try:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            consumer.consume(chunk)
                            total_size += len(chunk)
                finally:
                    consumer.finalize()
                
                return {
                    "success": True,
                    "size": total_size,
                    "content_type": response.headers.get('content-type'),
                    "destination": str(destination) if isinstance(destination, (str, Path)) else "stream"
                }
                
        except requests.exceptions.RequestException as e:
            raise VitalGraphClientError(f"Failed to download file content: {e}")
    
    def download_to_consumer(self, space_id: str, graph_id: str, file_uri: str, 
                            consumer: BinaryConsumer, chunk_size: int = 8192) -> Dict[str, Any]:
        """
        Download file content to a BinaryConsumer.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            file_uri: File node URI
            consumer: BinaryConsumer instance
            chunk_size: Size of chunks for streaming
            
        Returns:
            Dictionary containing download result
        """
        return self.download_file_content(space_id, graph_id, file_uri, consumer, chunk_size)
    
    def pump_file(self, source_space_id: str, source_graph_id: str, source_file_uri: str,
                  target_space_id: str, target_graph_id: str, target_file_uri: str,
                  chunk_size: int = 8192) -> Dict[str, Any]:
        """
        Pump file content from one file node to another (download + upload).
        
        Args:
            source_space_id: Source space identifier
            source_graph_id: Source graph identifier
            source_file_uri: Source file URI
            target_space_id: Target space identifier
            target_graph_id: Target graph identifier
            target_file_uri: Target file URI
            chunk_size: Size of chunks for streaming
            
        Returns:
            Dictionary containing pump result
        """
        self._check_connection()
        
        try:
            # Download from source
            download_url = f"{self._get_server_url()}/api/graphs/files/download"
            download_params = build_query_params(
                space_id=source_space_id,
                graph_id=source_graph_id,
                file_uri=source_file_uri
            )
            
            download_response = self._make_authenticated_request('GET', download_url, params=download_params, stream=True)
            
            # Upload to target
            upload_url = f"{self._get_server_url()}/api/graphs/files/upload"
            upload_params = build_query_params(
                space_id=target_space_id,
                graph_id=target_graph_id,
                file_uri=target_file_uri
            )
            
            # Create streaming generator from download response
            def stream_generator():
                for chunk in download_response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        yield chunk
            
            files = {
                'file': ('pumped_file', stream_generator(), download_response.headers.get('content-type'))
            }
            
            upload_response = self._make_authenticated_request('POST', upload_url, params=upload_params, files=files)
            
            return {
                "success": True,
                "source": f"{source_space_id}/{source_graph_id}/{source_file_uri}",
                "target": f"{target_space_id}/{target_graph_id}/{target_file_uri}",
                "content_type": download_response.headers.get('content-type'),
                "upload_result": upload_response.json()
            }
            
        except requests.exceptions.RequestException as e:
            raise VitalGraphClientError(f"Failed to pump file content: {e}")
