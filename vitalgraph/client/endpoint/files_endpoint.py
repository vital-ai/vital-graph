"""
VitalGraph Client Files Endpoint

Client-side implementation for Files operations.
Hides JSON-LD complexity and returns VitalSigns GraphObjects directly.
"""

import httpx
import aiohttp
from typing import Dict, Any, Optional, BinaryIO, Union, List
from pathlib import Path
import asyncio

from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.vitalsigns import VitalSigns

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ..binary.streaming import (
    BinaryGenerator, BinaryConsumer, BytesConsumer,
    create_generator, create_consumer
)
from ..binary.async_streaming import (
    AsyncBinaryGenerator, AsyncBinaryConsumer,
    create_async_generator, create_async_consumer,
    pump_data_async
)
from ..response.client_response import (
    FileResponse,
    FilesListResponse,
    FileCreateResponse,
    FileUpdateResponse,
    FileDeleteResponse,
    FileUploadResponse,
)
from ..response.response_builder import (
    jsonld_to_graph_objects,
    build_success_response,
    build_error_response,
)


class FilesEndpoint(BaseEndpoint):
    """Client endpoint for Files operations with clean GraphObject API."""
    
    def __init__(self, client):
        super().__init__(client)
        # Initialize VitalSigns for JSON-LD conversion
        self.vs = VitalSigns()
    
    async def list_files(self, space_id: str, graph_id: Optional[str] = None, page_size: int = 100, 
                  offset: int = 0, file_filter: Optional[str] = None) -> FilesListResponse:
        """
        List files with pagination and optional filtering.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier (optional)
            page_size: Number of items per page
            offset: Offset for pagination
            file_filter: Optional file filter
            
        Returns:
            FilesListResponse with direct GraphObject access via response.objects
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        
        try:
            url = f"{self._get_server_url().rstrip('/')}/api/files"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                page_size=page_size,
                offset=offset,
                file_filter=file_filter
            )
            
            response = await self._make_authenticated_request('GET', url, params=params)
            response_data = response.json()
            
            # Convert JSON-LD to GraphObjects internally
            files_jsonld = response_data.get('files', {})
            objects = jsonld_to_graph_objects(files_jsonld, self.vs) if files_jsonld else []
            
            return build_success_response(
                FilesListResponse,
                objects=objects,
                count=len(objects),
                total_count=response_data.get('total_count', len(objects)),
                offset=offset,
                page_size=page_size,
                has_more=response_data.get('has_more', False),
                status_code=response.status_code,
                message=f"Retrieved {len(objects)} files",
                space_id=space_id,
                graph_id=graph_id,
                file_filter=file_filter
            )
        except Exception as e:
            return build_error_response(
                FilesListResponse,
                error_code=1,
                error_message=str(e),
                status_code=500,
                space_id=space_id,
                graph_id=graph_id
            )
    
    async def get_file(self, space_id: str, uri: str, graph_id: Optional[str] = None) -> FileResponse:
        """
        Get a single file by URI.
        
        Args:
            space_id: Space identifier
            uri: File URI to retrieve
            graph_id: Graph identifier (optional)
            
        Returns:
            FileResponse with direct GraphObject access via response.file
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, uri=uri)
        
        try:
            url = f"{self._get_server_url().rstrip('/')}/api/files"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                uri=uri
            )
            
            response = await self._make_authenticated_request('GET', url, params=params)
            response_data = response.json()
            
            # Convert JSON-LD to GraphObjects internally
            objects = jsonld_to_graph_objects(response_data, self.vs)
            
            # Find primary FileNode
            file_node = None
            for obj in objects:
                if hasattr(obj, 'URI') and str(obj.URI) == uri:
                    file_node = obj
                    break
            
            return build_success_response(
                FileResponse,
                objects=objects,
                file_uri=uri,
                file_node=file_node,
                status_code=response.status_code,
                message=f"Retrieved file {uri}",
                space_id=space_id,
                graph_id=graph_id,
                requested_uri=uri
            )
        except Exception as e:
            return build_error_response(
                FileResponse,
                error_code=2,
                error_message=str(e),
                status_code=500,
                space_id=space_id,
                graph_id=graph_id,
                requested_uri=uri
            )
    
    async def get_files_by_uris(self, space_id: str, uri_list: str, graph_id: Optional[str] = None) -> FilesListResponse:
        """
        Get multiple files by URI list.
        
        Args:
            space_id: Space identifier
            uri_list: Comma-separated list of file URIs
            graph_id: Graph identifier (optional)
            
        Returns:
            FilesListResponse with direct GraphObject access via response.objects
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, uri_list=uri_list)
        
        try:
            url = f"{self._get_server_url().rstrip('/')}/api/files"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                uri_list=uri_list
            )
            
            response = await self._make_authenticated_request('GET', url, params=params)
            response_data = response.json()
            
            # Convert JSON-LD to GraphObjects internally
            objects = jsonld_to_graph_objects(response_data, self.vs)
            
            return build_success_response(
                FilesListResponse,
                objects=objects,
                count=len(objects),
                total_count=len(objects),
                offset=0,
                page_size=len(objects),
                has_more=False,
                status_code=response.status_code,
                message=f"Retrieved {len(objects)} files",
                space_id=space_id,
                graph_id=graph_id
            )
        except Exception as e:
            return build_error_response(
                FilesListResponse,
                error_code=3,
                error_message=str(e),
                status_code=500,
                space_id=space_id,
                graph_id=graph_id
            )
    
    async def create_file(self, space_id: str, objects: List[GraphObject], graph_id: Optional[str] = None) -> FileCreateResponse:
        """
        Create new file node (metadata only).
        
        Args:
            space_id: Space identifier
            objects: List of GraphObjects (FileNode and related objects)
            graph_id: Graph identifier (optional)
            
        Returns:
            FileCreateResponse with created file information
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, objects=objects)
        
        try:
            # Convert GraphObjects to JSON-LD internally
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            from ...model.jsonld_model import JsonLdDocument, JsonLdObject
            
            jsonld_dict = GraphObject.to_jsonld_list(objects)
            
            # Determine if single object or document
            if len(objects) == 1:
                data = JsonLdObject(**jsonld_dict['@graph'][0] if '@graph' in jsonld_dict else jsonld_dict)
            else:
                data = JsonLdDocument(**jsonld_dict)
            
            url = f"{self._get_server_url().rstrip('/')}/api/files"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id
            )
            
            # Set discriminator automatically based on type (match original behavior)
            payload = data.model_dump(by_alias=True)
            if isinstance(data, JsonLdObject):
                payload['jsonld_type'] = 'object'
            else:
                payload['jsonld_type'] = 'document'
            
            response = await self._make_authenticated_request('POST', url, params=params, json=payload)
            response_data = response.json()
            
            return build_success_response(
                FileCreateResponse,
                created_uris=response_data.get('created_uris', []),
                created_count=response_data.get('created_count', 0),
                objects=objects,
                status_code=response.status_code,
                message=f"Created {response_data.get('created_count', 0)} file(s)",
                space_id=space_id,
                graph_id=graph_id
            )
        except Exception as e:
            return build_error_response(
                FileCreateResponse,
                error_code=4,
                error_message=str(e),
                status_code=500,
                space_id=space_id,
                graph_id=graph_id
            )
    
    async def update_file(self, space_id: str, objects: List[GraphObject], graph_id: Optional[str] = None) -> FileUpdateResponse:
        """
        Update file metadata.
        
        Args:
            space_id: Space identifier
            objects: List of GraphObjects with updated file metadata
            graph_id: Graph identifier (optional)
            
        Returns:
            FileUpdateResponse with update information
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, objects=objects)
        
        try:
            # Convert GraphObjects to JSON-LD internally
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            from ...model.jsonld_model import JsonLdDocument, JsonLdObject
            
            jsonld_dict = GraphObject.to_jsonld_list(objects)
            
            # Determine if single object or document
            if len(objects) == 1:
                data = JsonLdObject(**jsonld_dict['@graph'][0] if '@graph' in jsonld_dict else jsonld_dict)
            else:
                data = JsonLdDocument(**jsonld_dict)
            
            url = f"{self._get_server_url().rstrip('/')}/api/files"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id
            )
            
            # Set discriminator automatically based on type (match original behavior)
            payload = data.model_dump(by_alias=True)
            if isinstance(data, JsonLdObject):
                payload['jsonld_type'] = 'object'
            else:
                payload['jsonld_type'] = 'document'
            
            response = await self._make_authenticated_request('PUT', url, params=params, json=payload)
            response_data = response.json()
            
            return build_success_response(
                FileUpdateResponse,
                updated_uris=response_data.get('updated_uris', []),
                updated_count=response_data.get('updated_count', 0),
                objects=objects,
                status_code=response.status_code,
                message=f"Updated {response_data.get('updated_count', 0)} file(s)",
                space_id=space_id,
                graph_id=graph_id
            )
        except Exception as e:
            return build_error_response(
                FileUpdateResponse,
                error_code=5,
                error_message=str(e),
                status_code=500,
                space_id=space_id,
                graph_id=graph_id
            )
    
    async def delete_file(self, space_id: str, uri: str, graph_id: Optional[str] = None) -> FileDeleteResponse:
        """
        Delete file node by URI.
        
        Args:
            space_id: Space identifier
            uri: File URI to delete
            graph_id: Graph identifier (optional)
            
        Returns:
            FileDeleteResponse with deletion information
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, uri=uri)
        
        try:
            url = f"{self._get_server_url().rstrip('/')}/api/files"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                uri=uri
            )
            
            response = await self._make_authenticated_request('DELETE', url, params=params)
            response_data = response.json()
            
            return build_success_response(
                FileDeleteResponse,
                deleted_uris=[uri],
                deleted_count=1,
                status_code=response.status_code,
                message=f"Deleted file {uri}",
                space_id=space_id,
                graph_id=graph_id,
                requested_uris=[uri]
            )
        except Exception as e:
            return build_error_response(
                FileDeleteResponse,
                error_code=6,
                error_message=str(e),
                status_code=500,
                space_id=space_id,
                graph_id=graph_id,
                requested_uris=[uri]
            )
    
    # Advanced streaming methods with full support for bytes, streams, paths, and generators
    async def delete_files_batch(self, space_id: str, graph_id: str, uri_list: str) -> Dict[str, Any]:
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
            
            response = await self._make_authenticated_request('DELETE', url, params=params)
            return response.json()
        except httpx.HTTPError as e:
            raise VitalGraphClientError(f"Failed to delete File nodes: {e}")
    
    async def upload_file_content(self, space_id: str, graph_id: str, file_uri: str, 
                           source: Union[bytes, BinaryIO, str, Path, BinaryGenerator], 
                           filename: Optional[str] = None, 
                           content_type: Optional[str] = None,
                           chunk_size: int = 8192) -> FileUploadResponse:
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
            FileUploadResponse with upload information
            
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
            
            total_size = len(file_content)
            
            files = {
                'file': (final_filename, file_content, final_content_type)
            }
            
            # httpx will automatically set multipart/form-data with boundary
            response = await self._make_authenticated_request('POST', url, params=params, files=files)
            
            return build_success_response(
                FileUploadResponse,
                file_uri=file_uri,
                size=total_size,
                content_type=final_content_type,
                filename=final_filename,
                status_code=response.status_code,
                message=f"Uploaded {total_size} bytes to {file_uri}",
                space_id=space_id,
                graph_id=graph_id
            )
            
        except Exception as e:
            return build_error_response(
                FileUploadResponse,
                error_code=7,
                error_message=str(e),
                status_code=500,
                file_uri=file_uri,
                space_id=space_id,
                graph_id=graph_id
            )
    
    async def upload_from_generator(self, space_id: str, graph_id: str, file_uri: str, 
                             generator: BinaryGenerator) -> FileUploadResponse:
        """
        Upload file content from a BinaryGenerator.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            file_uri: File node URI
            generator: BinaryGenerator instance
            
        Returns:
            FileUploadResponse with upload information
        """
        return await self.upload_file_content(space_id, graph_id, file_uri, generator)
    
    async def download_file_content(self, space_id: str, graph_id: str, file_uri: str, 
                             destination: Optional[Union[str, Path, BinaryIO, BinaryConsumer]] = None,
                             chunk_size: int = 8192) -> Union[bytes, FileUploadResponse]:
        """
        Download file content from a File node using streaming consumers.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            file_uri: File node URI
            destination: Optional destination (path, stream, or BinaryConsumer)
            chunk_size: Size of chunks for streaming (default: 8192)
            
        Returns:
            bytes if destination is None, otherwise FileDownloadResponse
            
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
            
            response = await self._make_authenticated_request('GET', url, params=params)
            
            # Check HTTP status code - raise exception for errors
            if response.status_code >= 400:
                error_detail = f"File download failed with status {response.status_code}"
                try:
                    error_data = response.json()
                    error_detail = error_data.get('detail', error_detail)
                except:
                    pass
                raise VitalGraphClientError(error_detail)
            
            content_type = response.headers.get('content-type', 'application/octet-stream')
            
            if destination is None:
                # Return raw bytes - use BytesConsumer for consistency
                consumer = BytesConsumer()
                consumer.consume(response.content)
                consumer.finalize()
                return consumer.get_bytes()
            else:
                # Use consumer for streaming
                consumer = create_consumer(destination)
                total_size = 0
                
                try:
                    consumer.consume(response.content)
                    total_size += len(response.content)
                finally:
                    consumer.finalize()
                
                return FileUploadResponse(
                    file_uri=file_uri,
                    size=total_size,
                    content_type=content_type,
                    filename=file_uri.split('/')[-1] if '/' in file_uri else file_uri.split(':')[-1],
                    message=f"Downloaded {total_size} bytes from {file_uri}",
                    error_code=0,
                    status_code=200,
                    space_id=space_id,
                    graph_id=graph_id
                )
                
        except VitalGraphClientError:
            raise
        except Exception as e:
            raise VitalGraphClientError(f"Failed to download file content: {e}")
    
    async def download_to_consumer(self, space_id: str, graph_id: str, file_uri: str, 
                            consumer: BinaryConsumer, chunk_size: int = 8192) -> FileUploadResponse:
        """
        Download file content to a BinaryConsumer.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            file_uri: File node URI
            consumer: BinaryConsumer instance
            chunk_size: Size of chunks for streaming
            
        Returns:
            FileUploadResponse with download information
        """
        return await self.download_file_content(space_id, graph_id, file_uri, consumer, chunk_size)
    
    async def pump_file(self, source_space_id: str, source_graph_id: str, source_file_uri: str,
                  target_space_id: str, target_graph_id: str, target_file_uri: str,
                  chunk_size: int = 8192, use_streaming: bool = True) -> Dict[str, Any]:
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
            use_streaming: If True, uses true streaming (memory-efficient for large files).
                          If False, loads entire file into memory (compatible with all servers).
            
        Returns:
            Dictionary containing pump result
            
        Note:
            Streaming mode (use_streaming=True) is more memory-efficient for large files
            but requires the upload endpoint to support chunked transfer encoding.
            Non-streaming mode loads the entire file into memory but is more compatible.
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
            
            download_response = await self._make_authenticated_request('GET', download_url, params=download_params)
            
            # Check for download errors
            if download_response.status_code >= 400:
                raise VitalGraphClientError(f"Download failed with status {download_response.status_code}")
            
            content_type = download_response.headers.get('content-type', 'application/octet-stream')
            
            # Upload to target
            upload_url = f"{self._get_server_url()}/api/files/upload"
            upload_params = build_query_params(
                space_id=target_space_id,
                graph_id=target_graph_id,
                uri=target_file_uri
            )
            
            if use_streaming:
                # True streaming: use generator to avoid loading entire file into memory
                def file_generator():
                    """Generator that yields chunks from download response."""
                    yield download_response.content
                
                # Use generator for streaming upload
                files = {
                    'file': ('pumped_file', file_generator(), content_type)
                }
                
                response = await self._make_authenticated_request('POST', upload_url, params=upload_params, files=files)
            else:
                # Non-streaming: collect all content into memory first
                # (More compatible but uses more memory)
                file_content = download_response.content
                
                files = {
                    'file': ('pumped_file', file_content, content_type)
                }
                
                response = await self._make_authenticated_request('POST', upload_url, params=upload_params, files=files)
            
            return {
                "success": True,
                "source": f"{source_space_id}/{source_graph_id}/{source_file_uri}",
                "target": f"{target_space_id}/{target_graph_id}/{target_file_uri}",
                "content_type": content_type,
                "streaming_mode": use_streaming,
                "upload_result": response.json()
            }
            
        except VitalGraphClientError:
            raise
        except httpx.HTTPError as e:
            raise VitalGraphClientError(f"Failed to pump file content: {e}")
    
    async def upload_file_stream_async(self, space_id: str, graph_id: str, file_uri: str,
                                       source: Union[str, Path, bytes, AsyncBinaryGenerator],
                                       filename: Optional[str] = None,
                                       content_type: Optional[str] = None,
                                       chunk_size: int = 8192) -> FileUploadResponse:
        """
        Upload file content using true streaming (chunk-based) - ASYNC version for FastAPI.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            file_uri: File node URI
            source: Data source (path, bytes, or AsyncBinaryGenerator)
            filename: Original filename (optional)
            content_type: MIME content type (optional)
            chunk_size: Size of chunks for streaming (default: 8192)
            
        Returns:
            FileUploadResponse with upload information
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, file_uri=file_uri, source=source)
        
        try:
            url = f"{self._get_server_url()}/api/files/stream/upload"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                uri=file_uri,
                chunk_size=chunk_size
            )
            
            # Create async generator from source
            async_gen = create_async_generator(
                source,
                chunk_size=chunk_size,
                filename=filename,
                content_type=content_type
            )
            
            # Use async generator properties for metadata
            final_filename = filename or async_gen.filename or 'uploaded_file'
            final_content_type = content_type or async_gen.content_type or 'application/octet-stream'
            
            # Use aiohttp for true async streaming with async generator
            # aiohttp supports async generators in multipart uploads - only one chunk in memory!
            async with aiohttp.ClientSession() as session:
                # Get auth headers
                headers = await self._get_auth_headers()
                
                # Create multipart form data with async generator
                data = aiohttp.FormData()
                data.add_field(
                    'file',
                    async_gen.generate(),  # aiohttp supports async generators!
                    filename=final_filename,
                    content_type=final_content_type
                )
                
                # Make request with true async streaming - only one chunk in memory at a time
                async with session.post(
                    url,
                    params=params,
                    data=data,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=300.0)
                ) as response:
                    response.raise_for_status()
                    response_data = await response.json()
                    
                    return FileUploadResponse(
                        file_uri=file_uri,
                        size=response_data.get('file_size', 0),
                        content_type=final_content_type,
                        filename=final_filename,
                        message=response_data.get('message', 'File uploaded successfully'),
                        error_code=0,
                        status_code=response.status,  # aiohttp uses 'status' not 'status_code'
                        space_id=space_id,
                        graph_id=graph_id
                    )
                
        except Exception as e:
            raise VitalGraphClientError(f"Failed to stream upload file: {e}")
    
    async def upload_file_stream(self, space_id: str, graph_id: str, file_uri: str,
                          source: Union[str, Path, bytes, AsyncBinaryGenerator],
                          filename: Optional[str] = None,
                          content_type: Optional[str] = None,
                          chunk_size: int = 8192) -> FileUploadResponse:
        """
        Upload file content using true streaming (chunk-based) to avoid loading entire file into memory.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            file_uri: File node URI
            source: Data source (path, bytes, or AsyncBinaryGenerator)
            filename: Original filename (optional)
            content_type: MIME content type (optional)
            chunk_size: Size of chunks for streaming (default: 8192)
            
        Returns:
            FileUploadResponse with upload information
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, file_uri=file_uri, source=source)
        
        try:
            url = f"{self._get_server_url()}/api/files/stream/upload"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                uri=file_uri,
                chunk_size=chunk_size
            )
            
            # Create async generator from source
            async_gen = create_async_generator(
                source,
                chunk_size=chunk_size,
                filename=filename,
                content_type=content_type
            )
            
            # Use async generator properties for metadata
            final_filename = filename or async_gen.filename or 'uploaded_file'
            final_content_type = content_type or async_gen.content_type or 'application/octet-stream'
            
            # Create a sync generator wrapper for requests library
            def sync_generator():
                """Sync wrapper around async generator for requests library."""
                # Run in a separate thread to avoid event loop conflicts
                import queue
                chunk_queue = queue.Queue()
                exception_holder = [None]
                
                def run_async_gen():
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            async def generate_chunks():
                                async for chunk in async_gen.generate():
                                    chunk_queue.put(chunk)
                                chunk_queue.put(None)  # Signal end
                            
                            loop.run_until_complete(generate_chunks())
                        finally:
                            loop.close()
                    except Exception as e:
                        exception_holder[0] = e
                        chunk_queue.put(None)
                
                thread = threading.Thread(target=run_async_gen, daemon=True)
                thread.start()
                
                while True:
                    chunk = chunk_queue.get()
                    if chunk is None:
                        if exception_holder[0]:
                            raise exception_holder[0]
                        break
                    yield chunk
            
            files = {
                'file': (final_filename, sync_generator(), final_content_type)
            }
            
            response = await self._make_authenticated_request('POST', url, params=params, files=files)
            response_data = response.json()
            
            return FileUploadResponse(
                file_uri=file_uri,
                file_size=response_data.get('file_size', 0),
                content_type=final_content_type,
                filename=final_filename,
                message=response_data.get('message', 'File uploaded successfully'),
                storage_path=response_data.get('storage_path')
            )
            
        except Exception as e:
            raise VitalGraphClientError(f"Failed to stream upload file: {e}")
    
    async def download_file_stream_async(self, space_id: str, graph_id: str, file_uri: str,
                                        destination: Union[str, Path, AsyncBinaryConsumer],
                                        chunk_size: int = 8192) -> FileUploadResponse:
        """
        Download file content using true streaming (chunk-based) - ASYNC version for FastAPI.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            file_uri: File node URI
            destination: Destination (path or AsyncBinaryConsumer)
            chunk_size: Size of chunks for streaming (default: 8192)
            
        Returns:
            FileUploadResponse with download information
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, file_uri=file_uri, destination=destination)
        
        try:
            url = f"{self._get_server_url()}/api/files/stream/download"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                uri=file_uri,
                chunk_size=chunk_size
            )
            
            # Use httpx for async HTTP requests
            async with httpx.AsyncClient() as client:
                # Get auth headers
                headers = await self._get_auth_headers()
                
                async with client.stream('GET', url, params=params, headers=headers, timeout=300.0) as response:
                    response.raise_for_status()
                    
                    content_type = response.headers.get('content-type', 'application/octet-stream')
                    
                    # Create async consumer from destination
                    consumer = create_async_consumer(destination)
                    total_size = 0
                    
                    # Stream chunks directly
                    async for chunk in response.aiter_bytes(chunk_size=chunk_size):
                        if chunk:
                            await consumer.consume(chunk)
                            total_size += len(chunk)
                    
                    await consumer.finalize()
                    
                    return FileUploadResponse(
                        file_uri=file_uri,
                        size=total_size,
                        content_type=content_type,
                        filename=file_uri.split('/')[-1] if '/' in file_uri else file_uri.split(':')[-1],
                        message=f"Downloaded {total_size} bytes from {file_uri}",
                        error_code=0,
                        status_code=200,
                        space_id=space_id,
                        graph_id=graph_id
                    )
                    
        except VitalGraphClientError:
            raise
        except Exception as e:
            raise VitalGraphClientError(f"Failed to stream download file: {e}")
    
    async def download_file_stream(self, space_id: str, graph_id: str, file_uri: str,
                            destination: Union[str, Path, AsyncBinaryConsumer],
                            chunk_size: int = 8192) -> FileUploadResponse:
        """
        Download file content using true streaming (chunk-based) - SYNC wrapper.
        For async contexts (FastAPI), use download_file_stream_async() instead.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            file_uri: File node URI
            destination: Destination (path or AsyncBinaryConsumer)
            chunk_size: Size of chunks for streaming
            
        Returns:
            FileUploadResponse with download information
            
        Raises:
            VitalGraphClientError: If request fails
        """
        return await self.download_file_stream_async(space_id, graph_id, file_uri, destination, chunk_size)
    
    async def _download_file_stream_sync_fallback(self, space_id: str, graph_id: str, file_uri: str,
                            destination: Union[str, Path, AsyncBinaryConsumer],
                            chunk_size: int = 8192) -> FileUploadResponse:
        """
        Download file content using true streaming (chunk-based) to avoid loading entire file into memory.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            file_uri: File node URI
            destination: Destination (path or AsyncBinaryConsumer)
            chunk_size: Size of chunks for streaming
            
        Returns:
            FileUploadResponse with download information
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, file_uri=file_uri, destination=destination)
        
        try:
            url = f"{self._get_server_url()}/api/files/stream/download"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                uri=file_uri,
                chunk_size=chunk_size
            )
            
            response = await self._make_authenticated_request('GET', url, params=params)
            
            # Check HTTP status code
            if response.status_code >= 400:
                error_detail = f"File download failed with status {response.status_code}"
                try:
                    error_data = response.json()
                    error_detail = error_data.get('detail', error_detail)
                except:
                    pass
                raise VitalGraphClientError(error_detail)
            
            content_type = response.headers.get('content-type', 'application/octet-stream')
            
            # Create async consumer from destination
            consumer = create_async_consumer(destination)
            total_size = 0
            
            # Run async consumption in a separate thread to avoid event loop conflicts
            exception_holder = [None]
            
            def run_async_consumer():
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        async def consume_chunks():
                            nonlocal total_size
                            for chunk in response.iter_content(chunk_size=chunk_size):
                                if chunk:
                                    await consumer.consume(chunk)
                                    total_size += len(chunk)
                            await consumer.finalize()
                        
                        loop.run_until_complete(consume_chunks())
                    finally:
                        loop.close()
                except Exception as e:
                    exception_holder[0] = e
            
            thread = threading.Thread(target=run_async_consumer, daemon=False)
            thread.start()
            thread.join()  # Wait for completion
            
            if exception_holder[0]:
                raise exception_holder[0]
            
            return FileUploadResponse(
                file_uri=file_uri,
                size=total_size,
                content_type=content_type,
                filename=file_uri.split('/')[-1] if '/' in file_uri else file_uri.split(':')[-1],
                message=f"Downloaded {total_size} bytes from {file_uri}",
                error_code=0,
                status_code=200,
                space_id=space_id,
                graph_id=graph_id
            )
            
        except VitalGraphClientError:
            raise
        except Exception as e:
            raise VitalGraphClientError(f"Failed to stream download file: {e}")
    
    async def _get_auth_headers(self) -> Dict[str, str]:
        """
        Get authentication headers with automatic token refresh.
        Ensures token is valid before returning headers.
        """
        headers = {}
        
        # Ensure token is valid (will refresh if expired)
        # This uses the client's proactive token refresh logic
        if hasattr(self.client, '_ensure_valid_token'):
            try:
                await self.client._ensure_valid_token()
            except Exception as e:
                # If token refresh fails, log but continue with current token
                # The request will fail with 401 if token is invalid
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Token refresh failed in _get_auth_headers: {e}")
        
        # Extract auth headers from the client's session
        if hasattr(self.client, 'session') and self.client.session:
            # Get Authorization header from session headers
            session_headers = self.client.session.headers
            if 'Authorization' in session_headers:
                headers['Authorization'] = session_headers['Authorization']
        
        # Fallback: try to get token directly from JWT manager
        if 'Authorization' not in headers:
            if hasattr(self.client, 'access_token') and self.client.access_token:
                headers['Authorization'] = f'Bearer {self.client.access_token}'
        
        return headers
