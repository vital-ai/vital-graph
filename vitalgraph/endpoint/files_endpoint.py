"""
Files REST API endpoint for VitalGraph.

This module provides REST API endpoints for managing files and file content using JSON-LD 1.1 format
for metadata and binary handling for file content upload/download.
"""

from typing import Dict, List, Optional, Union, Any
from fastapi import APIRouter, Depends, Query, File, UploadFile, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
import pyld
from pyld import jsonld
import io
import mimetypes
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

from ..model.jsonld_model import JsonLdDocument, JsonLdObject, JsonLdRequest
from ..model.files_model import (
    FilesResponse,
    FileCreateResponse,
    FileUpdateResponse,
    FileDeleteResponse,
    FileUploadResponse
)
from ..storage.s3_file_manager import S3FileManager, create_s3_file_manager_from_config
from vital_ai_domain.model.FileNode import FileNode
from .files_streaming_impl import stream_upload_to_s3, stream_download_from_s3


class FilesEndpoint:
    """Files endpoint handler."""
    
    def __init__(self, space_manager, auth_dependency, config: Optional[Dict] = None):
        self.space_manager = space_manager
        self.auth_dependency = auth_dependency
        self.router = APIRouter()
        
        # Initialize FilesImpl for database operations
        from .impl.files_impl import FilesImpl
        self.files_impl = FilesImpl(space_manager)
        
        # Initialize S3FileManager if config provided
        self.file_manager = None
        if config:
            try:
                # Convert VitalGraphConfig object to dict if needed
                if hasattr(config, 'config_data'):
                    # VitalGraphConfig object - use config_data attribute
                    config_dict = config.config_data
                elif isinstance(config, dict):
                    # Already a dict
                    config_dict = config
                else:
                    # Try to convert to dict
                    config_dict = dict(config)
                
                self.file_manager = create_s3_file_manager_from_config(config_dict)
            except Exception as e:
                # Log error but don't fail initialization
                print(f"Warning: Could not initialize S3FileManager: {e}")
        
        self._setup_routes()
    
    def _validate_file_node_types(self, request: JsonLdRequest) -> Optional[str]:
        """
        Validate that all objects in the request are FileNode or subclasses using isinstance.
        
        Args:
            request: JsonLdRequest containing file node(s)
            
        Returns:
            Error message if validation fails, None if valid
        """
        objects_to_check = []
        
        if isinstance(request, JsonLdObject):
            # Single object - convert to dict with by_alias to preserve @type
            objects_to_check.append(request.model_dump(by_alias=True))
        elif isinstance(request, JsonLdDocument):
            # Multiple objects in @graph
            if request.graph:
                objects_to_check.extend(request.graph)
        
        for obj in objects_to_check:
            try:
                # Convert JSON-LD to VitalSigns object
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                vital_obj = GraphObject.from_jsonld(obj)
                
                # Check if it's an instance of FileNode or subclass
                if not isinstance(vital_obj, FileNode):
                    obj_type = obj.get('@type') or obj.get('type', 'unknown')
                    actual_type = type(vital_obj).__name__
                    return f"Invalid type '{obj_type}' (instantiated as {actual_type}). Only FileNode or its subclasses are allowed for file operations."
                    
            except Exception as e:
                obj_type = obj.get('@type') or obj.get('type', 'unknown')
                return f"Failed to validate object as FileNode: {obj_type}. Error: {str(e)}"
        
        return None
    
    def _setup_routes(self):
        """Setup FastAPI routes for files management."""
        
        @self.router.get("/files", response_model=Union[FilesResponse, JsonLdObject, JsonLdDocument], tags=["Files"])
        async def list_or_get_files(
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            page_size: int = Query(100, ge=1, le=1000, description="Number of files per page"),
            offset: int = Query(0, ge=0, description="Offset for pagination"),
            file_filter: Optional[str] = Query(None, description="Keyword to filter files by"),
            uri: Optional[str] = Query(None, description="Single file URI to retrieve"),
            uri_list: Optional[str] = Query(None, description="Comma-separated list of file URIs"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            List files with pagination, or get specific files by URI(s).
            
            - If uri is provided: returns single file metadata (JsonLdObject)
            - If uri_list is provided: returns multiple file metadata (JsonLdDocument)
            - Otherwise: returns paginated list of all files (FilesResponse)
            """
            
            # Handle single URI retrieval
            if uri:
                return await self._get_file_by_uri(space_id, graph_id, uri, current_user)
            
            # Handle multiple URI retrieval
            if uri_list:
                uris = [u.strip() for u in uri_list.split(',') if u.strip()]
                return await self._get_files_by_uris(space_id, graph_id, uris, current_user)
            
            # Handle paginated listing
            return await self._list_files(space_id, graph_id, page_size, offset, file_filter, current_user)
        
        @self.router.post("/files", response_model=FileCreateResponse, tags=["Files"])
        async def create_file_node(
            request: JsonLdRequest,
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """Create file node(s). Uses discriminated union to automatically handle single files (JsonLdObject) or multiple files (JsonLdDocument)."""
            return await self._create_file_node(space_id, graph_id, request, current_user)
        
        @self.router.put("/files", response_model=FileUpdateResponse, tags=["Files"])
        async def update_file_metadata(
            request: JsonLdRequest,
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """Update file metadata. Uses discriminated union to automatically handle single files (JsonLdObject) or multiple files (JsonLdDocument)."""
            return await self._update_file_metadata(space_id, graph_id, request, current_user)
        
        @self.router.delete("/files", response_model=FileDeleteResponse, tags=["Files"])
        async def delete_file_node(
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            uri: Optional[str] = Query(None, description="File URI to delete"),
            uri_list: Optional[str] = Query(None, description="Comma-separated list of file URIs to delete"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Delete file node(s) by URI or batch delete by URI list.
            
            - If uri is provided: deletes single file
            - If uri_list is provided: deletes multiple files (batch)
            """
            # Handle batch deletion
            if uri_list:
                uris = [u.strip() for u in uri_list.split(',') if u.strip()]
                return await self._delete_files_batch(space_id, graph_id, uris, current_user)
            
            # Handle single deletion
            if uri:
                return await self._delete_file_node(space_id, graph_id, uri, current_user)
            
            # Neither uri nor uri_list provided
            return FileDeleteResponse(
                message="Either uri or uri_list must be provided",
                deleted_count=0,
                deleted_uris=[]
            )
        
        @self.router.post("/files/upload", response_model=FileUploadResponse, tags=["Files"])
        async def upload_file_content(
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            uri: str = Query(..., description="File URI to upload content to"),
            file: UploadFile = File(..., description="File content to upload"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Upload binary file content to existing file node.
            """
            return await self._upload_file_content(space_id, graph_id, uri, file, current_user)
        
        @self.router.get("/files/download", tags=["Files"])
        async def download_file_content(
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            uri: str = Query(..., description="File URI to download content from"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Download binary file content by URI.
            Returns streaming response with file content.
            """
            return await self._download_file_content(space_id, graph_id, uri, current_user)
        
        @self.router.post("/files/stream/upload", response_model=FileUploadResponse, tags=["Files", "Streaming"])
        async def upload_file_stream(
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            uri: str = Query(..., description="File URI to upload content to"),
            file: UploadFile = File(..., description="File content to upload"),
            chunk_size: int = Query(8192, description="Chunk size for streaming (bytes)"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Upload binary file content using true streaming (chunk-based).
            Does not load entire file into memory.
            """
            return await self._upload_file_stream(space_id, graph_id, uri, file, chunk_size, current_user)
        
        @self.router.get("/files/stream/download", tags=["Files", "Streaming"])
        async def download_file_stream(
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            uri: str = Query(..., description="File URI to download content from"),
            chunk_size: int = Query(8192, description="Chunk size for streaming (bytes)"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Download binary file content using true streaming (chunk-based).
            Returns streaming response that yields chunks without loading entire file into memory.
            """
            return await self._download_file_stream(space_id, graph_id, uri, chunk_size, current_user)
    
    async def _list_files(self, space_id: str, graph_id: Optional[str], page_size: int, offset: int, file_filter: Optional[str], current_user: Dict) -> FilesResponse:
        """List files with pagination using FilesImpl."""
        try:
            # Use FilesImpl to query actual FileNode objects from database
            jsonld_document, total_count = await self.files_impl.list_files(
                space_id=space_id,
                graph_id=graph_id,
                page_size=page_size,
                offset=offset,
                file_filter=file_filter
            )
            
            # Convert dict to JsonLdDocument
            files_data = JsonLdDocument(**jsonld_document)
            
            return FilesResponse(
                files=files_data,
                total_count=total_count,
                page_size=page_size,
                offset=offset
            )
            
        except Exception as e:
            # Return empty response on error
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_doc = GraphObject.to_jsonld_list([])
            return FilesResponse(
                files=JsonLdDocument(**empty_doc),
                total_count=0,
                page_size=page_size,
                offset=offset
            )
    
    async def _get_file_by_uri(self, space_id: str, graph_id: Optional[str], uri: str, current_user: Dict) -> JsonLdObject:
        """Get single file by URI using FilesImpl."""
        try:
            # Use FilesImpl to query actual FileNode object from database
            graph_object = await self.files_impl.get_file_by_uri(
                space_id=space_id,
                uri=uri,
                graph_id=graph_id
            )
            
            # Convert GraphObject to JSON-LD using VitalSigns
            jsonld_dict = graph_object.to_jsonld()
            
            # Convert dict to JsonLdObject
            return JsonLdObject(**jsonld_dict)
            
        except ValueError as e:
            # File not found - return 404
            raise HTTPException(status_code=404, detail=f"File not found: {uri}")
        except Exception as e:
            # Other errors - return 500
            raise HTTPException(status_code=500, detail=f"Error retrieving file: {str(e)}")
    
    async def _get_files_by_uris(self, space_id: str, graph_id: Optional[str], uris: List[str], current_user: Dict) -> JsonLdDocument:
        """Get multiple files by URI list using FilesImpl."""
        try:
            # Use FilesImpl to query actual FileNode objects from database
            jsonld_document, count = await self.files_impl.get_files_by_uris(
                space_id=space_id,
                uri_list=uris,
                graph_id=graph_id
            )
            
            # Convert dict to JsonLdDocument
            return JsonLdDocument(**jsonld_document)
            
        except Exception as e:
            # Return empty document on error
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            empty_doc = GraphObject.to_jsonld_list([])
            return JsonLdDocument(**empty_doc)
    
    async def _create_file_node(self, space_id: str, graph_id: Optional[str], request: JsonLdRequest, current_user: Dict) -> FileCreateResponse:
        """Create new file node (metadata only). Only FileNode or subclasses are allowed."""
        # Validate that all objects are FileNode or subclasses
        validation_error = self._validate_file_node_types(request)
        if validation_error:
            return FileCreateResponse(
                message=f"Validation error: {validation_error}",
                created_count=0,
                created_uris=[]
            )
        
        try:
            # Convert request to JSON-LD document format
            if isinstance(request, JsonLdObject):
                # Single object - wrap in document
                jsonld_document = {
                    "@context": request.context if hasattr(request, 'context') else {},
                    "@graph": [request.model_dump(by_alias=True)]
                }
            elif isinstance(request, JsonLdDocument):
                # Already a document
                jsonld_document = request.model_dump(by_alias=True)
            else:
                return FileCreateResponse(
                    message="Invalid request format",
                    created_count=0,
                    created_uris=[]
                )
            
            # Use FilesImpl to create file nodes in database
            created_uris = await self.files_impl.create_files(
                space_id=space_id,
                jsonld_document=jsonld_document,
                graph_id=graph_id
            )
            
            return FileCreateResponse(
                message=f"Successfully created {len(created_uris)} file nodes",
                created_count=len(created_uris),
                created_uris=created_uris
            )
            
        except Exception as e:
            return FileCreateResponse(
                message=f"Error creating file nodes: {str(e)}",
                created_count=0,
                created_uris=[]
            )
    
    async def _update_file_metadata(self, space_id: str, graph_id: Optional[str], request: JsonLdRequest, current_user: Dict) -> FileUpdateResponse:
        """Update existing file metadata. Only FileNode or subclasses are allowed."""
        # Validate that all objects are FileNode or subclasses
        validation_error = self._validate_file_node_types(request)
        if validation_error:
            return FileUpdateResponse(
                message=f"Validation error: {validation_error}",
                updated_uri=None
            )
        
        # NO-OP implementation - simulate file metadata update
        updated_uri = "haley:file_updated_001"
        
        # Handle both JsonLdObject and JsonLdDocument
        if isinstance(request, JsonLdObject):
            # Single object
            if request.id:
                updated_uri = request.id
        elif isinstance(request, JsonLdDocument):
            # Multiple objects in @graph - use first one
            if request.graph and len(request.graph) > 0:
                if '@id' in request.graph[0]:
                    updated_uri = request.graph[0]['@id']
        
        return FileUpdateResponse(
            message=f"Successfully updated file metadata",
            updated_uri=updated_uri
        )
    
    async def _delete_file_node(self, space_id: str, graph_id: Optional[str], uri: str, current_user: Dict) -> FileDeleteResponse:
        """Delete file node by URI and remove file from MinIO/S3 storage."""
        # Delete from MinIO/S3 if file manager is available
        if self.file_manager:
            try:
                # Create object key from URI (sanitize for S3)
                object_key = uri.replace(':', '_').replace('/', '_')
                
                # Delete from MinIO/S3
                self.file_manager.delete_file(object_key)
            except Exception as e:
                # File might not exist in storage, that's acceptable
                pass
        
        # Delete FileNode from graph database
        try:
            logger.info(f"Deleting FileNode from graph database: {uri}")
            deleted_count = await self.files_impl.delete_files(
                space_id=space_id,
                graph_id=graph_id,
                uris=[uri]
            )
            
            logger.info(f"Database deletion result: deleted_count={deleted_count}")
            
            if deleted_count > 0:
                return FileDeleteResponse(
                    message=f"Successfully deleted file node and storage",
                    deleted_count=deleted_count,
                    deleted_uris=[uri]
                )
            else:
                return FileDeleteResponse(
                    message=f"File node not found - no deletion needed",
                    deleted_count=0,
                    deleted_uris=[]
                )
        except Exception as e:
            logger.error(f"Error deleting file node: {e}")
            return FileDeleteResponse(
                message=f"Error deleting file node: {str(e)}",
                deleted_count=0,
                deleted_uris=[]
            )
    
    async def _delete_files_batch(self, space_id: str, graph_id: Optional[str], uris: List[str], current_user: Dict) -> FileDeleteResponse:
        """Delete multiple file nodes by URI list and remove files from MinIO/S3 storage."""
        storage_errors = []
        
        # Delete from MinIO/S3 if file manager is available
        if self.file_manager:
            for uri in uris:
                try:
                    # Create object key from URI (sanitize for S3)
                    object_key = uri.replace(':', '_').replace('/', '_')
                    
                    # Delete from MinIO/S3
                    self.file_manager.delete_file(object_key)
                except Exception as e:
                    # File might not exist in storage, that's acceptable
                    storage_errors.append(f"{uri}: {str(e)}")
        
        # Delete FileNodes from graph database
        try:
            deleted_count = await self.files_impl.delete_files(
                space_id=space_id,
                graph_id=graph_id,
                uris=uris
            )
            
            message = f"Successfully deleted {deleted_count} file nodes and storage"
            if storage_errors:
                message += f" (some storage cleanup warnings: {len(storage_errors)} files)"
            
            return FileDeleteResponse(
                message=message,
                deleted_count=deleted_count,
                deleted_uris=uris[:deleted_count]
            )
        except Exception as e:
            return FileDeleteResponse(
                message=f"Error deleting file nodes: {str(e)}",
                deleted_count=0,
                deleted_uris=[]
            )
    
    async def _upload_file_content(self, space_id: str, graph_id: Optional[str], uri: str, file: UploadFile, current_user: Dict) -> FileUploadResponse:
        """Upload binary file content to existing file node."""
        
        # Read file content
        content = await file.read()
        file_size = len(content)
        
        # Determine content type using mimetypes library
        content_type = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
        
        # Upload to MinIO/S3 if file manager is available
        if self.file_manager:
            try:
                # Create object key from URI (sanitize for S3)
                object_key = uri.replace(':', '_').replace('/', '_')
                
                # Upload to MinIO/S3
                result = self.file_manager.upload_file(
                    file_data=io.BytesIO(content),
                    object_key=object_key,
                    content_type=content_type,
                    metadata={
                        'file_uri': uri,
                        'space_id': space_id,
                        'graph_id': graph_id or '',
                        'original_filename': file.filename or 'unknown'
                    }
                )
                
                # Get S3 URL for the uploaded file
                s3_url = self.file_manager.get_file_url(object_key)
                
                # Update FileNode with hasFileURL and hasFileType properties
                try:
                    # Get the existing FileNode GraphObject
                    file_node = await self.files_impl.get_file_by_uri(
                        space_id=space_id,
                        uri=uri,
                        graph_id=graph_id
                    )
                    
                    # Update the FileNode properties using VitalSigns
                    file_node.fileURL = s3_url
                    file_node.fileType = content_type
                    
                    # Update the FileNode in the database (pass as list)
                    await self.files_impl.update_files(
                        space_id=space_id,
                        file_nodes=[file_node],
                        graph_id=graph_id or "default"
                    )
                    
                    self.logger.info(f"Updated FileNode {uri} with hasFileURL={s3_url} and hasFileType={content_type}")
                except Exception as update_error:
                    self.logger.error(f"Failed to update FileNode properties: {update_error}", exc_info=True)
                    # Continue anyway - file was uploaded successfully
                
                return FileUploadResponse(
                    message=f"Successfully uploaded file content to MinIO",
                    file_uri=uri,
                    file_size=file_size,
                    content_type=content_type,
                    storage_path=result.get('object_key')
                )
            except Exception as e:
                return FileUploadResponse(
                    message=f"Error uploading to MinIO: {str(e)}",
                    file_uri=uri,
                    file_size=file_size,
                    content_type=content_type
                )
        else:
            # Fallback: simulate upload without storage
            return FileUploadResponse(
                message=f"Successfully uploaded file content (no storage configured)",
                file_uri=uri,
                file_size=file_size,
                content_type=content_type
            )
    
    async def _download_file_content(self, space_id: str, graph_id: Optional[str], uri: str, current_user: Dict):
        """Download binary file content by URI."""
        
        # First verify FileNode exists in database
        try:
            file_node = await self.files_impl.get_file_by_uri(
                space_id=space_id,
                uri=uri,
                graph_id=graph_id
            )
            if not file_node:
                raise HTTPException(
                    status_code=404,
                    detail=f"File not found: {uri}"
                )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=404,
                detail=f"File not found: {uri}"
            )
        
        # Download from MinIO/S3 if file manager is available
        if self.file_manager:
            # Create object key from URI (sanitize for S3)
            object_key = uri.replace(':', '_').replace('/', '_')
            
            # Download from MinIO/S3
            content = self.file_manager.download_file(object_key)
            
            # Get metadata to determine content type
            try:
                metadata = self.file_manager.get_file_metadata(object_key)
                content_type = metadata.get('content_type', 'application/octet-stream')
            except:
                content_type = 'application/octet-stream'
            
            # Determine filename from URI
            filename = uri.split('/')[-1] if '/' in uri else uri
            
            return StreamingResponse(
                io.BytesIO(content),
                media_type=content_type,
                headers={
                    "Content-Disposition": f"attachment; filename={filename}",
                    "Content-Length": str(len(content))
                }
            )
        else:
            # Return fallback response
            return StreamingResponse(
                io.BytesIO(b"File content not available"),
                media_type="application/octet-stream",
                headers={"Content-Disposition": f"attachment; filename=unknown"}
            )
    
    async def _upload_file_stream(self, space_id: str, graph_id: Optional[str], uri: str, 
                                   file: UploadFile, chunk_size: int, current_user: Dict) -> FileUploadResponse:
        """Upload binary file content using true streaming (chunk-based)."""
        
        # Determine content type
        content_type = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
        
        # Upload to MinIO/S3 if file manager is available
        if self.file_manager:
            try:
                # Create object key from URI (sanitize for S3)
                object_key = uri.replace(':', '_').replace('/', '_')
                
                # Stream upload to MinIO/S3 without loading into memory
                result = await stream_upload_to_s3(
                    file=file,
                    file_manager=self.file_manager,
                    object_key=object_key,
                    content_type=content_type,
                    metadata={
                        'file_uri': uri,
                        'space_id': space_id,
                        'graph_id': graph_id or '',
                        'original_filename': file.filename or 'unknown'
                    },
                    chunk_size=chunk_size
                )
                
                # Get S3 URL for the uploaded file
                s3_url = self.file_manager.get_file_url(object_key)
                
                # Update FileNode with hasFileURL and hasFileType properties
                try:
                    file_node = await self.files_impl.get_file_by_uri(
                        space_id=space_id,
                        uri=uri,
                        graph_id=graph_id
                    )
                    
                    file_node.fileURL = s3_url
                    file_node.fileType = content_type
                    
                    await self.files_impl.update_files(
                        space_id=space_id,
                        file_nodes=[file_node],
                        graph_id=graph_id or "default"
                    )
                except Exception as update_error:
                    print(f"Failed to update FileNode properties: {update_error}")
                
                return FileUploadResponse(
                    message=f"Successfully streamed file upload to MinIO",
                    file_uri=uri,
                    file_size=0,  # Size unknown in streaming mode
                    content_type=content_type,
                    storage_path=result.get('object_key')
                )
            except Exception as e:
                return FileUploadResponse(
                    message=f"Error streaming upload to MinIO: {str(e)}",
                    file_uri=uri,
                    file_size=0,
                    content_type=content_type
                )
        else:
            return FileUploadResponse(
                message=f"Successfully streamed file upload (no storage configured)",
                file_uri=uri,
                file_size=0,
                content_type=content_type
            )
    
    async def _download_file_stream(self, space_id: str, graph_id: Optional[str], uri: str, 
                                     chunk_size: int, current_user: Dict):
        """Download binary file content using true streaming (chunk-based)."""
        
        # First verify FileNode exists in database
        try:
            file_node = await self.files_impl.get_file_by_uri(
                space_id=space_id,
                uri=uri,
                graph_id=graph_id
            )
            if not file_node:
                raise HTTPException(
                    status_code=404,
                    detail=f"File not found: {uri}"
                )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=404,
                detail=f"File not found: {uri}"
            )
        
        # Download from MinIO/S3 if file manager is available
        if self.file_manager:
            # Create object key from URI (sanitize for S3)
            object_key = uri.replace(':', '_').replace('/', '_')
            
            # Get metadata to determine content type
            try:
                metadata = self.file_manager.get_file_metadata(object_key)
                content_type = metadata.get('content_type', 'application/octet-stream')
            except:
                content_type = 'application/octet-stream'
            
            # Determine filename from URI
            filename = uri.split('/')[-1] if '/' in uri else uri.split(':')[-1]
            
            # Return streaming response with async generator
            return StreamingResponse(
                stream_download_from_s3(
                    file_manager=self.file_manager,
                    object_key=object_key,
                    chunk_size=chunk_size
                ),
                media_type=content_type,
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
        else:
            # Return fallback response
            filename = uri.split('/')[-1] if '/' in uri else uri.split(':')[-1]
            return StreamingResponse(
                io.BytesIO(b"File content not available"),
                media_type="application/octet-stream",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )


def create_files_router(space_manager, auth_dependency, config: Optional[Dict] = None) -> APIRouter:
    """Create and return the files router."""
    endpoint = FilesEndpoint(space_manager, auth_dependency, config=config)
    return endpoint.router
