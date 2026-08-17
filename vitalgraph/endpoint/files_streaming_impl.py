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


class _CountingReader:
    """Tallies bytes as MinIO pulls them, so a streamed upload can report its size.

    `put_object(length=-1)` never learns the size — that is the point of it — so
    the size has to be observed in passing or fetched back with a second round
    trip to storage. This is the free half of that choice: the bytes go past
    here anyway.

    MinIO reads the body ONLY through `read_part_data(data, ...)`, which calls
    `data.read(n)` and nothing else (minio/api.py `put_object`), so every byte
    that reaches the bucket is counted here exactly once. Its one-byte lookahead
    does not double count: the spare byte is carried forward as a prefix to the
    next part, not re-read from this stream.
    """

    __slots__ = ("_stream", "bytes_read")

    def __init__(self, stream):
        self._stream = stream
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._stream.read(size)
        self.bytes_read += len(chunk)
        return chunk

    def __getattr__(self, name):
        # `seek`/`close`/etc. stay reachable; only `read` is instrumented.
        return getattr(self._stream, name)


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
        Dictionary with upload result, including the "size" actually streamed
    """
    try:
        # Use MinIO's streaming upload with length=-1 for unknown size
        # This allows true streaming without buffering entire file
        counter = _CountingReader(file.file)
        result = file_manager.client.put_object(
            file_manager.bucket_name,
            object_key,
            counter,  # Pass file object directly for streaming
            length=-1,  # Unknown length - enables streaming
            part_size=10485760,  # 10MB parts for multipart upload
            content_type=content_type or 'application/octet-stream',
            metadata=metadata
        )

        logger.info(f"Streamed upload: {object_key} ({counter.bytes_read} bytes) "
                    f"to bucket: {file_manager.bucket_name}")

        return {
            "success": True,
            "bucket": file_manager.bucket_name,
            "object_key": object_key,
            "etag": result.etag,
            "content_type": content_type,
            "size": counter.bytes_read
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
