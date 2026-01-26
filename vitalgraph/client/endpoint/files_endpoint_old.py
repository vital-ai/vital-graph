"""
VitalGraph Client Files Endpoint

Client-side implementation for Files operations.
"""

import requests
from typing import Dict, Any, Optional, BinaryIO, Union
from pathlib import Path

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ..binary.streaming import (
    BinaryGenerator, BinaryConsumer, BytesConsumer,
    create_generator, create_consumer
)
from ...model.files_model import (
    FilesResponse, FileCreateResponse, FileUpdateResponse, FileDeleteResponse, FileUploadResponse
)
from ...model.jsonld_model import JsonLdDocument, JsonLdObject, Union


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
    
    def get_file(self, space_id: str, uri: str, graph_id: Optional[str] = None) -> JsonLdObject:
        """
        Get a single file by URI.
        
        Args:
            space_id: Space identifier
            uri: File URI to retrieve
            graph_id: Graph identifier (optional)
            
        Returns:
            JsonLdObject containing file metadata
            
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
        
        return self._make_typed_request('GET', url, JsonLdObject, params=params)
    
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
    
    def create_file(self, space_id: str, data: Union[JsonLdObject, JsonLdDocument], graph_id: Optional[str] = None) -> FileCreateResponse:
        """
        Create new file node (metadata only).
        
        Args:
            space_id: Space identifier
            data: JSON-LD data - either single object or document with @graph array
            graph_id: Graph identifier (optional)
            
        Returns:
            FileCreateResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, data=data)
        
        url = f"{self._get_server_url().rstrip('/')}/api/files"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id
        )
        
        # Set discriminator automatically based on type
        payload = data.model_dump(by_alias=True)
        if isinstance(data, JsonLdObject):
            payload['jsonld_type'] = 'object'
        else:
            payload['jsonld_type'] = 'document'
        
        return self._make_typed_request('POST', url, FileCreateResponse, params=params, json=payload)
    
    def update_file(self, space_id: str, data: Union[JsonLdObject, JsonLdDocument], graph_id: Optional[str] = None) -> FileUpdateResponse:
        """
        Update file metadata.
        
        Args:
            space_id: Space identifier
            data: JSON-LD data - either single object or document with @graph array
            graph_id: Graph identifier (optional)
            
        Returns:
            FileUpdateResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, data=data)
        
        url = f"{self._get_server_url().rstrip('/')}/api/files"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id
        )
        
        # Set discriminator automatically based on type
        payload = data.model_dump(by_alias=True)
        if isinstance(data, JsonLdObject):
            payload['jsonld_type'] = 'object'
        else:
            payload['jsonld_type'] = 'document'
        
        return self._make_typed_request('PUT', url, FileUpdateResponse, params=params, json=payload)
    
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
    
    # Advanced streaming methods with full support for bytes, streams, paths, and generators
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
            url = f"{self._get_server_url()}/api/files"
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
            url = f"{self._get_server_url()}/api/files/upload"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                uri=file_uri
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
            
            # Collect all chunks into bytes for upload
            # (requests doesn't handle generators well in multipart/form-data)
            file_content = b""
            for chunk in generator.generate():
                file_content += chunk
            
            files = {
                'file': (final_filename, file_content, final_content_type)
            }
            
            # Remove Content-Type header to let requests set multipart/form-data with boundary
            headers = {'Content-Type': None}
            
            response = self._make_authenticated_request('POST', url, params=params, files=files, headers=headers)
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
            url = f"{self._get_server_url()}/api/files/download"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                uri=file_uri
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
            download_url = f"{self._get_server_url()}/api/files/download"
            download_params = build_query_params(
                space_id=source_space_id,
                graph_id=source_graph_id,
                uri=source_file_uri
            )
            
            download_response = self._make_authenticated_request('GET', download_url, params=download_params, stream=True)
            
            # Upload to target
            upload_url = f"{self._get_server_url()}/api/files/upload"
            upload_params = build_query_params(
                space_id=target_space_id,
                graph_id=target_graph_id,
                uri=target_file_uri
            )
            
            # Collect downloaded content into bytes for upload
            # (requests doesn't handle generators well in multipart/form-data)
            file_content = b""
            for chunk in download_response.iter_content(chunk_size=chunk_size):
                if chunk:
                    file_content += chunk
            
            files = {
                'file': ('pumped_file', file_content, download_response.headers.get('content-type'))
            }
            
            # Remove Content-Type header to let requests set multipart/form-data with boundary
            headers = {'Content-Type': None}
            
            upload_response = self._make_authenticated_request('POST', upload_url, params=upload_params, files=files, headers=headers)
            
            return {
                "success": True,
                "source": f"{source_space_id}/{source_graph_id}/{source_file_uri}",
                "target": f"{target_space_id}/{target_graph_id}/{target_file_uri}",
                "content_type": download_response.headers.get('content-type'),
                "upload_result": upload_response.json()
            }
            
        except requests.exceptions.RequestException as e:
            raise VitalGraphClientError(f"Failed to pump file content: {e}")
