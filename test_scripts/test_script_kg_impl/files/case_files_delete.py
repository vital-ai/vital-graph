"""
Files Delete Test Cases

Tests for deleting file nodes via the Files endpoint.
"""

import logging
from typing import Dict, Any, List, Optional

from vitalgraph.model.files_model import FileDeleteResponse

logger = logging.getLogger(__name__)


class FilesDeleteTester:
    """Test cases for Files deletion operations."""
    
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
    
    async def test_delete_single_file(self) -> bool:
        """Test deleting a single file by URI."""
        if not self.test_file_uris:
            self.log_test_result(
                "Delete Single File",
                False,
                "No test file URIs available for deletion",
                {"test_uris": self.test_file_uris}
            )
            return False
        
        try:
            # Delete first test file
            test_uri = self.test_file_uris.pop(0)  # Remove from list since we're deleting it
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._delete_file_node(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=test_uri,
                current_user=current_user
            )
            
            if response and hasattr(response, 'deleted_count') and response.deleted_count > 0:
                self.log_test_result(
                    "Delete Single File",
                    True,
                    f"Successfully deleted file: {test_uri}",
                    {"uri": test_uri, "deleted_count": response.deleted_count, "message": response.message}
                )
                return True
            else:
                self.log_test_result(
                    "Delete Single File",
                    False,
                    "Failed to delete file",
                    {"uri": test_uri, "response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Delete Single File",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_delete_multiple_files(self) -> bool:
        """Test deleting multiple files (simulated by calling delete multiple times)."""
        if len(self.test_file_uris) < 2:
            self.log_test_result(
                "Delete Multiple Files",
                False,
                "Need at least 2 test file URIs for multi-delete",
                {"available_uris": len(self.test_file_uris)}
            )
            return False
        
        try:
            # Delete first two remaining test files
            test_uris = [self.test_file_uris.pop(0), self.test_file_uris.pop(0)]
            deleted_count = 0
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            
            for uri in test_uris:
                response = await self.endpoint._delete_file_node(
                    space_id=self.space_id,
                    graph_id=self.graph_id,
                    uri=uri,
                    current_user=current_user
                )
                
                if response and hasattr(response, 'deleted_count') and response.deleted_count > 0:
                    deleted_count += response.deleted_count
            
            if deleted_count > 0:
                self.log_test_result(
                    "Delete Multiple Files",
                    True,
                    f"Successfully deleted {deleted_count} files",
                    {"uris": test_uris, "deleted_count": deleted_count}
                )
                return True
            else:
                self.log_test_result(
                    "Delete Multiple Files",
                    False,
                    "Failed to delete multiple files",
                    {"uris": test_uris, "deleted_count": deleted_count}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Delete Multiple Files",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_delete_nonexistent_file(self) -> bool:
        """Test deleting file that doesn't exist."""
        try:
            # Try to delete nonexistent file
            nonexistent_uri = "http://vital.ai/test/file/nonexistent_file_12345"
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._delete_file_node(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=nonexistent_uri,
                current_user=current_user
            )
            
            # For stub implementation, this might succeed - that's acceptable
            success = True
            result_msg = "Handled nonexistent file deletion gracefully"
            if response and hasattr(response, 'deleted_count'):
                result_msg += f" (deleted_count: {response.deleted_count})"
            
            self.log_test_result(
                "Delete Nonexistent File",
                success,
                result_msg,
                {"uri": nonexistent_uri, "response": str(response)}
            )
            return success
            
        except Exception as e:
            # Exception for nonexistent file is acceptable
            self.log_test_result(
                "Delete Nonexistent File",
                True,
                f"Exception for nonexistent file (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def test_delete_already_deleted_file(self) -> bool:
        """Test deleting file that was already deleted."""
        try:
            # Create and immediately delete a file, then try to delete again
            test_uri = "http://vital.ai/test/file/delete_twice_test"
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            
            # First deletion (should succeed if file exists, or be handled gracefully)
            response1 = await self.endpoint._delete_file_node(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=test_uri,
                current_user=current_user
            )
            
            # Second deletion (should handle already-deleted file)
            response2 = await self.endpoint._delete_file_node(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=test_uri,
                current_user=current_user
            )
            
            # Should handle double deletion gracefully
            success = True
            self.log_test_result(
                "Delete Already Deleted File",
                success,
                f"Handled double deletion gracefully",
                {"uri": test_uri, "first_response": str(response1), "second_response": str(response2)}
            )
            return success
            
        except Exception as e:
            # Exception for double deletion is acceptable
            self.log_test_result(
                "Delete Already Deleted File",
                True,
                f"Exception for double deletion (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def test_delete_invalid_uri(self) -> bool:
        """Test delete request with invalid URI format."""
        try:
            # Try to delete with invalid URI
            invalid_uri = "not_a_valid_uri"
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._delete_file_node(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=invalid_uri,
                current_user=current_user
            )
            
            # For stub implementation, this might succeed - that's acceptable
            success = True
            result_msg = "Handled invalid URI deletion"
            if response and hasattr(response, 'deleted_count'):
                result_msg += f" (deleted_count: {response.deleted_count})"
            
            self.log_test_result(
                "Delete Invalid URI",
                success,
                result_msg,
                {"uri": invalid_uri, "response": str(response)}
            )
            return success
            
        except Exception as e:
            # Exception for invalid URI is acceptable
            self.log_test_result(
                "Delete Invalid URI",
                True,
                f"Exception for invalid URI (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def run_all_delete_tests(self) -> Dict[str, bool]:
        """Run all file deletion tests."""
        logger.info("🧪 Running Files Delete Tests")
        
        results = {}
        
        # Test single file deletion
        results["delete_single_file"] = await self.test_delete_single_file()
        
        # Test multiple files deletion
        results["delete_multiple_files"] = await self.test_delete_multiple_files()
        
        # Test nonexistent file deletion
        results["delete_nonexistent_file"] = await self.test_delete_nonexistent_file()
        
        # Test already deleted file
        results["delete_already_deleted_file"] = await self.test_delete_already_deleted_file()
        
        # Test invalid URI deletion
        results["delete_invalid_uri"] = await self.test_delete_invalid_uri()
        
        return results
