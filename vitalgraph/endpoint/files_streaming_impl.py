"""
Streaming implementation methods for Files endpoint.

Provides chunk-based streaming for file upload/download operations
to avoid loading entire files into memory.
"""

import logging
from typing import AsyncIterator, Optional
from fastapi import UploadFile
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)


async def stream_upload_to_s3(
    file: UploadFile,
    file_manager,
    object_key: str,
    content_type: Optional[str] = None,
    metadata: Optional[dict] = None,
    chunk_size: int = 8192
) -> dict:
    """
    Stream upload file content to S3/MinIO using chunk-based iteration.
    
    Args:
        file: FastAPI UploadFile object
        file_manager: S3FileManager instance
        object_key: S3 object key
        content_type: MIME content type
        metadata: Optional metadata dict
        chunk_size: Chunk size for reading (bytes)
        
    Returns:
        Dictionary with upload result
    """
    try:
        # Use MinIO's streaming upload with length=-1 for unknown size
        # This allows true streaming without buffering entire file
        result = file_manager.client.put_object(
            file_manager.bucket_name,
            object_key,
            file.file,  # Pass file object directly for streaming
            length=-1,  # Unknown length - enables streaming
            part_size=10485760,  # 10MB parts for multipart upload
            content_type=content_type or 'application/octet-stream',
            metadata=metadata
        )
        
        logger.info(f"Streamed upload: {object_key} to bucket: {file_manager.bucket_name}")
        
        return {
            "success": True,
            "bucket": file_manager.bucket_name,
            "object_key": object_key,
            "etag": result.etag,
            "content_type": content_type
        }
        
    except Exception as e:
        logger.error(f"Error streaming upload {object_key}: {e}")
        raise


async def stream_download_from_s3(
    file_manager,
    object_key: str,
    chunk_size: int = 8192
) -> AsyncIterator[bytes]:
    """
    Stream download file content from S3/MinIO using chunk-based iteration.
    
    Args:
        file_manager: S3FileManager instance
        object_key: S3 object key
        chunk_size: Chunk size for streaming (bytes)
        
    Yields:
        Chunks of file content as bytes
    """
    try:
        # Get streaming response from MinIO
        response = file_manager.client.get_object(
            file_manager.bucket_name,
            object_key
        )
        
        logger.info(f"Streaming download: {object_key} from bucket: {file_manager.bucket_name}")
        
        try:
            # Stream chunks from response
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            # Ensure response is properly closed
            response.close()
            response.release_conn()
            
    except Exception as e:
        logger.error(f"Error streaming download {object_key}: {e}")
        raise
