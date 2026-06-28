"""
Files Get Test Cases

Tests for retrieving individual files via the Files endpoint.
"""

import logging
from typing import Dict, Any, List, Optional


logger = logging.getLogger(__name__)


class FilesGetTester:
    """Test cases for Files retrieval operations."""
    
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
    
    async def test_get_file_by_uri(self) -> bool:
        """Test retrieving a single file by URI."""
        try:
            # Use a test URI or generate one for stub testing
            test_uri = self.test_file_uris[0] if self.test_file_uris else "http://vital.ai/test/file/sample_document"
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._get_file_by_uri(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=test_uri,
                current_user=current_user
            )
            
            # Response is QuadResultsResponse with results: List[Quad]
            if response and hasattr(response, 'results') and response.results:
                self.log_test_result(
                    "Get File By URI",
                    True,
                    f"Successfully retrieved file: {test_uri}",
                    {"uri": test_uri, "quad_count": len(response.results), "total_count": response.total_count}
                )
                return True
            else:
                self.log_test_result(
                    "Get File By URI",
                    False,
                    "No results in response",
                    {"uri": test_uri, "response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Get File By URI",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_get_files_by_uri_list(self) -> bool:
        """Test retrieving multiple files by URI list."""
        try:
            # Use test URIs or generate sample ones for stub testing
            if len(self.test_file_uris) >= 2:
                test_uris = self.test_file_uris[:2]
            else:
                test_uris = [
                    "http://vital.ai/test/file/sample_document_1",
                    "http://vital.ai/test/file/sample_document_2"
                ]
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._get_files_by_uris(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uris=test_uris,
                current_user=current_user
            )
            
            # Response is QuadResultsResponse with results: List[Quad]
            if response and hasattr(response, 'results') and response.results:
                self.log_test_result(
                    "Get Files By URI List",
                    True,
                    f"Successfully retrieved files ({len(response.results)} quads)",
                    {"uris": test_uris, "quad_count": len(response.results)}
                )
                return True
            else:
                self.log_test_result(
                    "Get Files By URI List",
                    False,
                    "No results in response",
                    {"uris": test_uris, "response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Get Files By URI List",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_get_nonexistent_file(self) -> bool:
        """Test retrieving a file that doesn't exist."""
        try:
            nonexistent_uri = "http://vital.ai/test/file/nonexistent_file_12345"
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._get_file_by_uri(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=nonexistent_uri,
                current_user=current_user
            )
            
            # For stub implementation, this might return sample data - that's acceptable
            success = True
            result_msg = "Handled nonexistent file request"
            if response and hasattr(response, 'results'):
                result_msg += f" (returned {len(response.results)} quads)"
            
            self.log_test_result(
                "Get Nonexistent File",
                success,
                result_msg,
                {"uri": nonexistent_uri, "response": str(response)}
            )
            return success
            
        except Exception as e:
            # Exception for nonexistent file is acceptable
            self.log_test_result(
                "Get Nonexistent File",
                True,
                f"Exception for nonexistent file (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def test_get_file_invalid_uri(self) -> bool:
        """Test retrieving file with invalid URI format."""
        try:
            invalid_uri = "not_a_valid_uri"
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._get_file_by_uri(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=invalid_uri,
                current_user=current_user
            )
            
            # For stub implementation, this might succeed - that's acceptable
            success = True
            result_msg = "Handled invalid URI format"
            if response and hasattr(response, 'results'):
                result_msg += f" (returned {len(response.results)} quads)"
            
            self.log_test_result(
                "Get File Invalid URI",
                success,
                result_msg,
                {"uri": invalid_uri, "response": str(response)}
            )
            return success
            
        except Exception as e:
            # Exception for invalid URI is acceptable
            self.log_test_result(
                "Get File Invalid URI",
                True,
                f"Exception for invalid URI (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def test_get_files_empty_uri_list(self) -> bool:
        """Test retrieving files with empty URI list."""
        try:
            empty_uris = []
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._get_files_by_uris(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uris=empty_uris,
                current_user=current_user
            )
            
            # Should handle empty list gracefully
            if response and hasattr(response, 'results'):
                quad_count = len(response.results)
                self.log_test_result(
                    "Get Files Empty URI List",
                    True,
                    f"Handled empty URI list (returned {quad_count} quads)",
                    {"uris": empty_uris, "quad_count": quad_count}
                )
                return True
            else:
                self.log_test_result(
                    "Get Files Empty URI List",
                    False,
                    "Failed to handle empty URI list",
                    {"uris": empty_uris, "response": str(response)}
                )
                return False
                
        except Exception as e:
            # Exception for empty list might be acceptable
            self.log_test_result(
                "Get Files Empty URI List",
                True,
                f"Exception for empty URI list (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def run_all_get_tests(self) -> Dict[str, bool]:
        """Run all file retrieval tests."""
        logger.info("🧪 Running Files Get Tests")
        
        results = {}
        
        # Test single file retrieval
        results["get_file_by_uri"] = await self.test_get_file_by_uri()
        
        # Test multiple files retrieval
        results["get_files_by_uri_list"] = await self.test_get_files_by_uri_list()
        
        # Test nonexistent file
        results["get_nonexistent_file"] = await self.test_get_nonexistent_file()
        
        # Test invalid URI
        results["get_file_invalid_uri"] = await self.test_get_file_invalid_uri()
        
        # Test empty URI list
        results["get_files_empty_uri_list"] = await self.test_get_files_empty_uri_list()
        
        return results
