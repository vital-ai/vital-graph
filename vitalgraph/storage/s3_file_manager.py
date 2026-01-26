"""
S3-Compatible File Manager for VitalGraph

Unified file manager supporting both AWS S3 and MinIO for file storage operations.
Handles file upload, download, deletion, and presigned URL generation.
"""

import io
import logging
from typing import Optional, Dict, Any, BinaryIO
from pathlib import Path

try:
    from minio import Minio
    from minio.error import S3Error
    MINIO_AVAILABLE = True
except ImportError:
    MINIO_AVAILABLE = False

logger = logging.getLogger(__name__)


class S3FileManager:
    """Unified S3-compatible file manager supporting both AWS S3 and MinIO."""
    
    def __init__(self, endpoint_url: Optional[str] = None, access_key_id: str = "", 
                 secret_access_key: str = "", bucket_name: str = "",
                 use_ssl: bool = True, region: str = "us-east-1"):
        """
        Initialize S3-compatible file manager.
        
        Args:
            endpoint_url: MinIO endpoint URL (e.g., 'localhost:9000') or None for AWS S3
            access_key_id: Access key ID
            secret_access_key: Secret access key
            bucket_name: Default bucket name
            use_ssl: Whether to use SSL (True for S3, False for local MinIO)
            region: AWS region (not used by MinIO but kept for compatibility)
        """
        if not MINIO_AVAILABLE:
            raise ImportError("minio package not installed. Install with: pip install minio")
        
        self.endpoint_url = endpoint_url
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.bucket_name = bucket_name
        self.use_ssl = use_ssl
        self.region = region
        
        # Initialize MinIO client
        if endpoint_url:
            # MinIO or custom S3-compatible endpoint
            self.client = Minio(
                endpoint_url,
                access_key=access_key_id,
                secret_key=secret_access_key,
                secure=use_ssl
            )
            logger.info(f"Initialized MinIO client for endpoint: {endpoint_url}")
        else:
            # AWS S3 (would need boto3 for production)
            # For now, we'll use MinIO client with AWS endpoints
            self.client = Minio(
                f"s3.{region}.amazonaws.com",
                access_key=access_key_id,
                secret_key=secret_access_key,
                secure=use_ssl
            )
            logger.info(f"Initialized S3 client for region: {region}")
        
        # Ensure bucket exists
        self._ensure_bucket_exists()
    
    def _ensure_bucket_exists(self) -> None:
        """Ensure the default bucket exists, create if not."""
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
                logger.info(f"Created bucket: {self.bucket_name}")
            else:
                logger.debug(f"Bucket already exists: {self.bucket_name}")
        except S3Error as e:
            logger.error(f"Error ensuring bucket exists: {e}")
            raise
    
    def upload_file(self, file_data: BinaryIO, object_key: str, 
                   content_type: Optional[str] = None, 
                   metadata: Optional[Dict[str, str]] = None,
                   bucket_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Upload file to S3/MinIO.
        
        Args:
            file_data: Binary file data (file-like object)
            object_key: S3 object key/path
            content_type: MIME content type
            metadata: Optional metadata dictionary
            bucket_name: Optional bucket name (uses default if not provided)
            
        Returns:
            Dictionary containing upload result with etag, size, etc.
        """
        bucket = bucket_name or self.bucket_name
        
        try:
            # Get file size
            file_data.seek(0, 2)  # Seek to end
            file_size = file_data.tell()
            file_data.seek(0)  # Seek back to start
            
            # Upload file
            result = self.client.put_object(
                bucket,
                object_key,
                file_data,
                length=file_size,
                content_type=content_type or 'application/octet-stream',
                metadata=metadata
            )
            
            logger.info(f"Uploaded file: {object_key} ({file_size} bytes) to bucket: {bucket}")
            
            return {
                "success": True,
                "bucket": bucket,
                "object_key": object_key,
                "etag": result.etag,
                "size": file_size,
                "content_type": content_type
            }
            
        except S3Error as e:
            logger.error(f"Error uploading file {object_key}: {e}")
            raise
    
    def download_file(self, object_key: str, bucket_name: Optional[str] = None) -> bytes:
        """
        Download file from S3/MinIO.
        
        Args:
            object_key: S3 object key/path
            bucket_name: Optional bucket name (uses default if not provided)
            
        Returns:
            File content as bytes
        """
        bucket = bucket_name or self.bucket_name
        
        try:
            response = self.client.get_object(bucket, object_key)
            data = response.read()
            response.close()
            response.release_conn()
            
            logger.info(f"Downloaded file: {object_key} ({len(data)} bytes) from bucket: {bucket}")
            return data
            
        except S3Error as e:
            logger.error(f"Error downloading file {object_key}: {e}")
            raise
    
    def download_file_stream(self, object_key: str, bucket_name: Optional[str] = None):
        """
        Download file as stream from S3/MinIO.
        
        Args:
            object_key: S3 object key/path
            bucket_name: Optional bucket name (uses default if not provided)
            
        Returns:
            Response object with streaming data
        """
        bucket = bucket_name or self.bucket_name
        
        try:
            response = self.client.get_object(bucket, object_key)
            logger.info(f"Streaming file: {object_key} from bucket: {bucket}")
            return response
            
        except S3Error as e:
            logger.error(f"Error streaming file {object_key}: {e}")
            raise
    
    def delete_file(self, object_key: str, bucket_name: Optional[str] = None) -> bool:
        """
        Delete file from S3/MinIO.
        
        Args:
            object_key: S3 object key/path
            bucket_name: Optional bucket name (uses default if not provided)
            
        Returns:
            True if successful
        """
        bucket = bucket_name or self.bucket_name
        
        try:
            self.client.remove_object(bucket, object_key)
            logger.info(f"Deleted file: {object_key} from bucket: {bucket}")
            return True
            
        except S3Error as e:
            logger.error(f"Error deleting file {object_key}: {e}")
            raise
    
    def generate_presigned_url(self, object_key: str, expiration: int = 3600,
                               bucket_name: Optional[str] = None) -> str:
        """
        Generate presigned URL for temporary file access.
        
        Args:
            object_key: S3 object key/path
            expiration: URL expiration time in seconds (default: 1 hour)
            bucket_name: Optional bucket name (uses default if not provided)
            
        Returns:
            Presigned URL string
        """
        bucket = bucket_name or self.bucket_name
        
        try:
            from datetime import timedelta
            url = self.client.presigned_get_object(
                bucket,
                object_key,
                expires=timedelta(seconds=expiration)
            )
            
            logger.info(f"Generated presigned URL for: {object_key} (expires in {expiration}s)")
            return url
            
        except S3Error as e:
            logger.error(f"Error generating presigned URL for {object_key}: {e}")
            raise
    
    def list_files(self, prefix: Optional[str] = None, bucket_name: Optional[str] = None) -> list:
        """
        List files in bucket.
        
        Args:
            prefix: Optional prefix to filter objects
            bucket_name: Optional bucket name (uses default if not provided)
            
        Returns:
            List of object information dictionaries
        """
        bucket = bucket_name or self.bucket_name
        
        try:
            objects = self.client.list_objects(bucket, prefix=prefix)
            
            file_list = []
            for obj in objects:
                file_list.append({
                    "object_key": obj.object_name,
                    "size": obj.size,
                    "last_modified": obj.last_modified,
                    "etag": obj.etag
                })
            
            logger.info(f"Listed {len(file_list)} files from bucket: {bucket}")
            return file_list
            
        except S3Error as e:
            logger.error(f"Error listing files: {e}")
            raise
    
    def get_file_metadata(self, object_key: str, bucket_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Get file metadata.
        
        Args:
            object_key: S3 object key/path
            bucket_name: Optional bucket name (uses default if not provided)
            
        Returns:
            Dictionary containing file metadata
        """
        bucket = bucket_name or self.bucket_name
        
        try:
            stat = self.client.stat_object(bucket, object_key)
            
            metadata = {
                "object_key": object_key,
                "size": stat.size,
                "content_type": stat.content_type,
                "etag": stat.etag,
                "last_modified": stat.last_modified,
                "metadata": stat.metadata
            }
            
            logger.info(f"Retrieved metadata for: {object_key}")
            return metadata
            
        except S3Error as e:
            logger.error(f"Error getting metadata for {object_key}: {e}")
            raise
    
    def get_file_url(self, object_key: str, bucket_name: Optional[str] = None) -> str:
        """
        Get the full URL for a file in S3/MinIO.
        
        Args:
            object_key: S3 object key/path
            bucket_name: Optional bucket name (uses default if not provided)
            
        Returns:
            Full URL to the file
        """
        bucket = bucket_name or self.bucket_name
        
        # Construct the URL based on endpoint
        if self.endpoint_url:
            # MinIO or custom S3-compatible endpoint
            protocol = "https" if self.use_ssl else "http"
            url = f"{protocol}://{self.endpoint_url}/{bucket}/{object_key}"
        else:
            # AWS S3
            url = f"https://s3.{self.region}.amazonaws.com/{bucket}/{object_key}"
        
        logger.debug(f"Generated URL for {object_key}: {url}")
        return url


def create_s3_file_manager_from_config(config: Dict[str, Any]) -> S3FileManager:
    """
    Create S3FileManager from configuration dictionary.
    
    Args:
        config: Configuration dictionary from vitalgraphdb-config.yaml
        
    Returns:
        Configured S3FileManager instance
    """
    file_storage_config = config.get('file_storage', {})
    backend = file_storage_config.get('backend', 'minio')
    
    if backend == 'minio':
        minio_config = file_storage_config.get('minio', {})
        return S3FileManager(
            endpoint_url=minio_config.get('endpoint_url', 'localhost:9000'),
            access_key_id=minio_config.get('access_key_id', 'minioadmin'),
            secret_access_key=minio_config.get('secret_access_key', 'minioadmin'),
            bucket_name=minio_config.get('bucket_name', 'vitalgraph-files-local'),
            use_ssl=minio_config.get('use_ssl', False),
            region=minio_config.get('region', 'us-east-1')
        )
    elif backend == 's3':
        s3_config = file_storage_config.get('s3', {})
        return S3FileManager(
            endpoint_url=s3_config.get('endpoint_url'),  # None for AWS S3
            access_key_id=s3_config.get('access_key_id', ''),
            secret_access_key=s3_config.get('secret_access_key', ''),
            bucket_name=s3_config.get('bucket_name', 'vitalgraph-files-prod'),
            use_ssl=s3_config.get('use_ssl', True),
            region=s3_config.get('region', 'us-east-1')
        )
    else:
        raise ValueError(f"Unknown file storage backend: {backend}")
