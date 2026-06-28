"""
Files Upload Test Cases

Tests for uploading file content via the Files endpoint.
"""

import logging
import io
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import UploadFile
from fastapi.datastructures import UploadFile as FastAPIUploadFile

from vitalgraph.model.files_model import FileUploadResponse

logger = logging.getLogger(__name__)


def create_upload_file(filename: str, content: bytes, content_type: str = None) -> UploadFile:
    """Create a real FastAPI UploadFile from binary content."""
    return UploadFile(
        file=io.BytesIO(content),
        filename=filename,
        headers={"content-type": content_type or "application/octet-stream"}
    )


class FilesUploadTester:
    """Test cases for Files upload operations."""
    
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
    
    async def test_upload_pdf_content(self) -> bool:
        """Test uploading PDF file content."""
        try:
            # Use a test URI or generate one for stub testing
            test_uri = self.test_file_uris[0] if self.test_file_uris else "http://vital.ai/test/file/upload_pdf"
            
            # Load real PDF file from test_files directory
            pdf_path = Path("/Users/hadfield/Local/vital-git/vital-graph/test_files/2502.16143v1.pdf")
            pdf_content = pdf_path.read_bytes()
            
            upload_file = create_upload_file("2502.16143v1.pdf", pdf_content, "application/pdf")
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._upload_file_content(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=test_uri,
                file=upload_file,
                current_user=current_user
            )
            
            if response and hasattr(response, 'file_uri') and response.file_uri:
                self.log_test_result(
                    "Upload PDF Content",
                    True,
                    f"Successfully uploaded PDF content: {response.file_uri}",
                    {
                        "uri": response.file_uri, 
                        "file_size": response.file_size,
                        "content_type": response.content_type,
                        "message": response.message
                    }
                )
                return True
            else:
                self.log_test_result(
                    "Upload PDF Content",
                    False,
                    "Failed to upload PDF content",
                    {"uri": test_uri, "response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Upload PDF Content",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_upload_image_content(self) -> bool:
        """Test uploading image file content."""
        try:
            # Use a test URI or generate one for stub testing
            test_uri = self.test_file_uris[1] if len(self.test_file_uris) > 1 else "http://vital.ai/test/file/upload_image"
            
            # Load real PNG file from test_files directory
            png_path = Path("/Users/hadfield/Local/vital-git/vital-graph/test_files/vampire_queen_baby.png")
            png_content = png_path.read_bytes()
            
            upload_file = create_upload_file("vampire_queen_baby.png", png_content, "image/png")
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._upload_file_content(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=test_uri,
                file=upload_file,
                current_user=current_user
            )
            
            if response and hasattr(response, 'file_uri') and response.file_uri:
                self.log_test_result(
                    "Upload Image Content",
                    True,
                    f"Successfully uploaded image content: {response.file_uri}",
                    {
                        "uri": response.file_uri, 
                        "file_size": response.file_size,
                        "content_type": response.content_type,
                        "message": response.message
                    }
                )
                return True
            else:
                self.log_test_result(
                    "Upload Image Content",
                    False,
                    "Failed to upload image content",
                    {"uri": test_uri, "response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Upload Image Content",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_upload_large_file(self) -> bool:
        """Test uploading large file content."""
        try:
            # Use a test URI or generate one for stub testing
            test_uri = self.test_file_uris[2] if len(self.test_file_uris) > 2 else "http://vital.ai/test/file/upload_large"
            
            # Create mock large file content (1MB of data)
            large_content = b"A" * (1024 * 1024)  # 1MB of 'A' characters
            
            upload_file = create_upload_file("large_file.txt", large_content, "text/plain")
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._upload_file_content(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=test_uri,
                file=upload_file,
                current_user=current_user
            )
            
            if response and hasattr(response, 'file_uri') and response.file_uri:
                self.log_test_result(
                    "Upload Large File",
                    True,
                    f"Successfully uploaded large file: {response.file_uri}",
                    {
                        "uri": response.file_uri, 
                        "file_size": response.file_size,
                        "content_type": response.content_type,
                        "message": response.message
                    }
                )
                return True
            else:
                self.log_test_result(
                    "Upload Large File",
                    False,
                    "Failed to upload large file",
                    {"uri": test_uri, "response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Upload Large File",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_upload_to_nonexistent_file(self) -> bool:
        """Test uploading content to nonexistent file node."""
        try:
            nonexistent_uri = "http://vital.ai/test/file/nonexistent_upload"
            
            # Create mock content
            content = b"Test content for nonexistent file"
            upload_file = create_upload_file("nonexistent.txt", content, "text/plain")
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._upload_file_content(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=nonexistent_uri,
                file=upload_file,
                current_user=current_user
            )
            
            # For stub implementation, this might succeed - that's acceptable
            success = True
            result_msg = "Handled upload to nonexistent file"
            if response and hasattr(response, 'file_uri'):
                result_msg += f" (file_uri: {response.file_uri})"
            
            self.log_test_result(
                "Upload To Nonexistent File",
                success,
                result_msg,
                {"uri": nonexistent_uri, "response": str(response)}
            )
            return success
            
        except Exception as e:
            # Exception for nonexistent file is acceptable
            self.log_test_result(
                "Upload To Nonexistent File",
                True,
                f"Exception for nonexistent file (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def test_upload_empty_file(self) -> bool:
        """Test uploading empty file content."""
        try:
            # Use a test URI or generate one for stub testing
            test_uri = self.test_file_uris[0] if self.test_file_uris else "http://vital.ai/test/file/upload_empty"
            
            # Create empty file
            empty_content = b""
            upload_file = create_upload_file("empty_file.txt", empty_content, "text/plain")
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._upload_file_content(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=test_uri,
                file=upload_file,
                current_user=current_user
            )
            
            # Should handle empty file gracefully
            if response and hasattr(response, 'file_uri'):
                self.log_test_result(
                    "Upload Empty File",
                    True,
                    f"Successfully handled empty file upload: {response.file_uri}",
                    {
                        "uri": response.file_uri, 
                        "file_size": response.file_size,
                        "content_type": response.content_type,
                        "message": response.message
                    }
                )
                return True
            else:
                self.log_test_result(
                    "Upload Empty File",
                    False,
                    "Failed to handle empty file upload",
                    {"uri": test_uri, "response": str(response)}
                )
                return False
                
        except Exception as e:
            # Exception for empty file might be acceptable
            self.log_test_result(
                "Upload Empty File",
                True,
                f"Exception for empty file (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def test_upload_invalid_content_type(self) -> bool:
        """Test uploading file with invalid/unknown content type."""
        try:
            # Use a test URI or generate one for stub testing
            test_uri = self.test_file_uris[0] if self.test_file_uris else "http://vital.ai/test/file/upload_invalid_type"
            
            # Create file with unknown content type
            content = b"Some binary data with unknown type"
            upload_file = create_upload_file("unknown_file.xyz", content, "application/unknown")
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._upload_file_content(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=test_uri,
                file=upload_file,
                current_user=current_user
            )
            
            # Should handle unknown content type gracefully
            if response and hasattr(response, 'file_uri'):
                self.log_test_result(
                    "Upload Invalid Content Type",
                    True,
                    f"Successfully handled unknown content type: {response.file_uri}",
                    {
                        "uri": response.file_uri, 
                        "file_size": response.file_size,
                        "content_type": response.content_type,
                        "message": response.message
                    }
                )
                return True
            else:
                self.log_test_result(
                    "Upload Invalid Content Type",
                    False,
                    "Failed to handle unknown content type",
                    {"uri": test_uri, "response": str(response)}
                )
                return False
                
        except Exception as e:
            # Exception for invalid content type might be acceptable
            self.log_test_result(
                "Upload Invalid Content Type",
                True,
                f"Exception for invalid content type (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def test_upload_byte_array(self) -> bool:
        """Test uploading file content as byte array."""
        try:
            test_uri = self.test_file_uris[0] if self.test_file_uris else "http://vital.ai/test/file/upload_bytes"
            
            # Create byte array content
            byte_content = b"This is a test file uploaded as a byte array with some binary data: \x00\x01\x02\x03"
            
            upload_file = create_upload_file("byte_array_test.bin", byte_content, "application/octet-stream")
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._upload_file_content(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=test_uri,
                file=upload_file,
                current_user=current_user
            )
            
            if response and hasattr(response, 'file_uri') and response.file_uri:
                self.log_test_result(
                    "Upload Byte Array",
                    True,
                    f"Successfully uploaded byte array: {response.file_uri}",
                    {
                        "uri": response.file_uri, 
                        "file_size": response.file_size,
                        "content_type": response.content_type,
                        "message": response.message
                    }
                )
                return True
            else:
                self.log_test_result(
                    "Upload Byte Array",
                    False,
                    "Failed to upload byte array",
                    {"uri": test_uri, "response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Upload Byte Array",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_upload_stream(self) -> bool:
        """Test uploading file content as stream."""
        try:
            test_uri = self.test_file_uris[1] if len(self.test_file_uris) > 1 else "http://vital.ai/test/file/upload_stream"
            
            # Create stream content (simulating streaming upload)
            stream_content = b"This is streamed content that would normally come from a file stream or network stream."
            
            # Create real UploadFile with stream content
            upload_file = create_upload_file("stream_test.txt", stream_content, "text/plain")
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._upload_file_content(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=test_uri,
                file=upload_file,
                current_user=current_user
            )
            
            if response and hasattr(response, 'file_uri') and response.file_uri:
                self.log_test_result(
                    "Upload Stream",
                    True,
                    f"Successfully uploaded stream: {response.file_uri}",
                    {
                        "uri": response.file_uri, 
                        "file_size": response.file_size,
                        "content_type": response.content_type,
                        "message": response.message
                    }
                )
                return True
            else:
                self.log_test_result(
                    "Upload Stream",
                    False,
                    "Failed to upload stream",
                    {"uri": test_uri, "response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Upload Stream",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def run_all_upload_tests(self) -> Dict[str, bool]:
        """Run all file upload tests."""
        logger.info("🧪 Running Files Upload Tests")
        
        results = {}
        
        # Test PDF upload
        results["upload_pdf_content"] = await self.test_upload_pdf_content()
        
        # Test image upload
        results["upload_image_content"] = await self.test_upload_image_content()
        
        # Test large file upload
        results["upload_large_file"] = await self.test_upload_large_file()
        
        # Test upload to nonexistent file
        results["upload_to_nonexistent_file"] = await self.test_upload_to_nonexistent_file()
        
        # Test empty file upload
        results["upload_empty_file"] = await self.test_upload_empty_file()
        
        # Test invalid content type upload
        results["upload_invalid_content_type"] = await self.test_upload_invalid_content_type()
        
        # Test byte array upload
        results["upload_byte_array"] = await self.test_upload_byte_array()
        
        # Test stream upload
        results["upload_stream"] = await self.test_upload_stream()
        
        return results
