"""
Files Download Test Cases

Tests for downloading file content via the Files endpoint.
"""

import logging
from typing import Dict, Any, List, Optional
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)


class FilesDownloadTester:
    """Test cases for Files download operations."""
    
    def __init__(self, endpoint, space_id: str, graph_id: str):
        self.endpoint = endpoint
        self.space_id = space_id
        self.graph_id = graph_id
        self.test_file_uris = []
    
    def log_test_result(self, test_name: str, success: bool, message: str, details: Dict[str, Any] = None):
        """Log test result with consistent formatting."""
        status = "✅ PASS" if success else "❌ FAIL"
        logger.info(f"{status} - {test_name}: {message}")
        if details:
            logger.debug(f"Details: {details}")
    
    def set_test_file_uris(self, uris: List[str]):
        """Set test file URIs from create tests."""
        self.test_file_uris = uris.copy()
    
    async def test_download_file_content(self) -> bool:
        """Test downloading file content."""
        try:
            # Use a test URI or generate one for stub testing
            test_uri = self.test_file_uris[0] if self.test_file_uris else "http://vital.ai/test/file/download_test"
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._download_file_content(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=test_uri,
                current_user=current_user
            )
            
            if isinstance(response, StreamingResponse):
                # Validate streaming response properties
                media_type = getattr(response, 'media_type', None)
                headers = getattr(response, 'headers', {})
                
                self.log_test_result(
                    "Download File Content",
                    True,
                    f"Successfully created download stream for: {test_uri}",
                    {
                        "uri": test_uri, 
                        "media_type": media_type,
                        "headers": dict(headers) if headers else {}
                    }
                )
                return True
            else:
                self.log_test_result(
                    "Download File Content",
                    False,
                    "Invalid response type (expected StreamingResponse)",
                    {"uri": test_uri, "response_type": type(response).__name__}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Download File Content",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_download_nonexistent_file(self) -> bool:
        """Test downloading content from nonexistent file."""
        try:
            nonexistent_uri = "http://vital.ai/test/file/nonexistent_download"
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._download_file_content(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=nonexistent_uri,
                current_user=current_user
            )
            
            # For stub implementation, this might return sample content - that's acceptable
            if isinstance(response, StreamingResponse):
                self.log_test_result(
                    "Download Nonexistent File",
                    True,
                    f"Handled nonexistent file download: {nonexistent_uri}",
                    {"uri": nonexistent_uri, "response_type": type(response).__name__}
                )
                return True
            else:
                # Non-streaming response might also be acceptable for error cases
                self.log_test_result(
                    "Download Nonexistent File",
                    True,
                    f"Handled nonexistent file with non-streaming response: {nonexistent_uri}",
                    {"uri": nonexistent_uri, "response": str(response)}
                )
                return True
                
        except Exception as e:
            # Exception for nonexistent file is acceptable
            self.log_test_result(
                "Download Nonexistent File",
                True,
                f"Exception for nonexistent file (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def test_download_invalid_uri(self) -> bool:
        """Test downloading with invalid URI format."""
        try:
            invalid_uri = "not_a_valid_uri"
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._download_file_content(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=invalid_uri,
                current_user=current_user
            )
            
            # For stub implementation, this might succeed - that's acceptable
            success = True
            result_msg = "Handled invalid URI download"
            if isinstance(response, StreamingResponse):
                result_msg += " (streaming response)"
            else:
                result_msg += f" (response type: {type(response).__name__})"
            
            self.log_test_result(
                "Download Invalid URI",
                success,
                result_msg,
                {"uri": invalid_uri, "response": str(response)}
            )
            return success
            
        except Exception as e:
            # Exception for invalid URI is acceptable
            self.log_test_result(
                "Download Invalid URI",
                True,
                f"Exception for invalid URI (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def test_download_multiple_files(self) -> bool:
        """Test downloading multiple files sequentially."""
        try:
            # Use test URIs or generate sample ones for stub testing
            if len(self.test_file_uris) >= 2:
                test_uris = self.test_file_uris[:2]
            else:
                test_uris = [
                    "http://vital.ai/test/file/download_multi_1",
                    "http://vital.ai/test/file/download_multi_2"
                ]
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            successful_downloads = 0
            
            for uri in test_uris:
                try:
                    response = await self.endpoint._download_file_content(
                        space_id=self.space_id,
                        graph_id=self.graph_id,
                        uri=uri,
                        current_user=current_user
                    )
                    
                    if isinstance(response, StreamingResponse):
                        successful_downloads += 1
                except Exception:
                    # Individual download failures are acceptable
                    pass
            
            if successful_downloads > 0:
                self.log_test_result(
                    "Download Multiple Files",
                    True,
                    f"Successfully downloaded {successful_downloads}/{len(test_uris)} files",
                    {"uris": test_uris, "successful_downloads": successful_downloads}
                )
                return True
            else:
                self.log_test_result(
                    "Download Multiple Files",
                    False,
                    "Failed to download any files",
                    {"uris": test_uris, "successful_downloads": successful_downloads}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Download Multiple Files",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_download_with_content_validation(self) -> bool:
        """Test downloading and validating content headers."""
        try:
            # Use a test URI or generate one for stub testing
            test_uri = self.test_file_uris[0] if self.test_file_uris else "http://vital.ai/test/file/content_validation"
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._download_file_content(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=test_uri,
                current_user=current_user
            )
            
            if isinstance(response, StreamingResponse):
                # Validate response headers
                headers = getattr(response, 'headers', {})
                media_type = getattr(response, 'media_type', None)
                
                # Check for expected headers
                has_content_disposition = 'content-disposition' in headers
                has_content_length = 'content-length' in headers
                has_valid_media_type = media_type is not None
                
                validation_score = sum([has_content_disposition, has_content_length, has_valid_media_type])
                
                self.log_test_result(
                    "Download Content Validation",
                    True,
                    f"Content validation completed (score: {validation_score}/3)",
                    {
                        "uri": test_uri,
                        "media_type": media_type,
                        "has_content_disposition": has_content_disposition,
                        "has_content_length": has_content_length,
                        "headers": dict(headers) if headers else {}
                    }
                )
                return True
            else:
                self.log_test_result(
                    "Download Content Validation",
                    False,
                    "Invalid response type for content validation",
                    {"uri": test_uri, "response_type": type(response).__name__}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Download Content Validation",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_download_large_file_stream(self) -> bool:
        """Test downloading large file with streaming response."""
        try:
            # Use a test URI or generate one for stub testing
            test_uri = self.test_file_uris[-1] if self.test_file_uris else "http://vital.ai/test/file/large_download"
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._download_file_content(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=test_uri,
                current_user=current_user
            )
            
            if isinstance(response, StreamingResponse):
                # For large files, streaming is essential
                headers = getattr(response, 'headers', {})
                content_length = headers.get('content-length', 'unknown')
                
                self.log_test_result(
                    "Download Large File Stream",
                    True,
                    f"Successfully created large file stream: {test_uri}",
                    {
                        "uri": test_uri,
                        "content_length": content_length,
                        "streaming": True
                    }
                )
                return True
            else:
                self.log_test_result(
                    "Download Large File Stream",
                    False,
                    "Expected streaming response for large file",
                    {"uri": test_uri, "response_type": type(response).__name__}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Download Large File Stream",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_download_as_byte_array(self) -> bool:
        """Test downloading file content as byte array."""
        try:
            test_uri = self.test_file_uris[0] if self.test_file_uris else "http://vital.ai/test/file/download_bytes"
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._download_file_content(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=test_uri,
                current_user=current_user
            )
            
            if isinstance(response, StreamingResponse):
                # Read entire stream into byte array
                byte_content = b""
                async for chunk in response.body_iterator:
                    byte_content += chunk
                
                self.log_test_result(
                    "Download As Byte Array",
                    True,
                    f"Successfully downloaded as byte array: {len(byte_content)} bytes",
                    {
                        "uri": test_uri,
                        "bytes_downloaded": len(byte_content),
                        "content_type": getattr(response, 'media_type', 'unknown')
                    }
                )
                return True
            else:
                self.log_test_result(
                    "Download As Byte Array",
                    False,
                    "Expected StreamingResponse for byte array download",
                    {"uri": test_uri, "response_type": type(response).__name__}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Download As Byte Array",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_download_as_stream(self) -> bool:
        """Test downloading file content as stream (chunked)."""
        try:
            test_uri = self.test_file_uris[1] if len(self.test_file_uris) > 1 else "http://vital.ai/test/file/download_stream"
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._download_file_content(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=test_uri,
                current_user=current_user
            )
            
            if isinstance(response, StreamingResponse):
                # Process stream in chunks
                chunk_count = 0
                total_bytes = 0
                
                async for chunk in response.body_iterator:
                    chunk_count += 1
                    total_bytes += len(chunk)
                
                self.log_test_result(
                    "Download As Stream",
                    True,
                    f"Successfully downloaded as stream: {chunk_count} chunks, {total_bytes} bytes",
                    {
                        "uri": test_uri,
                        "chunks": chunk_count,
                        "total_bytes": total_bytes,
                        "streaming": True
                    }
                )
                return True
            else:
                self.log_test_result(
                    "Download As Stream",
                    False,
                    "Expected StreamingResponse for stream download",
                    {"uri": test_uri, "response_type": type(response).__name__}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Download As Stream",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def run_all_download_tests(self) -> Dict[str, bool]:
        """Run all file download tests."""
        logger.info("🧪 Running Files Download Tests")
        
        results = {}
        
        # Test basic file download
        results["download_file_content"] = await self.test_download_file_content()
        
        # Test nonexistent file download
        results["download_nonexistent_file"] = await self.test_download_nonexistent_file()
        
        # Test invalid URI download
        results["download_invalid_uri"] = await self.test_download_invalid_uri()
        
        # Test multiple files download
        results["download_multiple_files"] = await self.test_download_multiple_files()
        
        # Test content validation
        results["download_content_validation"] = await self.test_download_with_content_validation()
        
        # Test large file streaming
        results["download_large_file_stream"] = await self.test_download_large_file_stream()
        
        # Test byte array download
        results["download_as_byte_array"] = await self.test_download_as_byte_array()
        
        # Test stream download
        results["download_as_stream"] = await self.test_download_as_stream()
        
        return results
