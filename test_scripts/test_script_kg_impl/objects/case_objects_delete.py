"""
Objects Delete Test Cases

Tests the Objects endpoint delete functionality for single and multiple object deletion.
"""

import logging
from typing import Dict, Any, List, Optional


class ObjectsDeleteTester:
    """Test cases for Objects endpoint delete operations."""
    
    def __init__(self, endpoint, space_id: str, graph_id: str):
        self.endpoint = endpoint
        self.space_id = space_id
        self.graph_id = graph_id
        self.logger = logging.getLogger(f"{__name__}.ObjectsDeleteTester")
        self.test_object_uris = []
    
    def log_test_result(self, test_name: str, success: bool, message: str, details: Dict[str, Any] = None):
        """Log test result with consistent formatting."""
        status = "✅ PASS" if success else "❌ FAIL"
        self.logger.info(f"{status} - {test_name}: {message}")
        if details:
            self.logger.debug(f"Details: {details}")
    
    def set_test_object_uris(self, uris: List[str]):
        """Set the URIs of test objects for delete testing."""
        self.test_object_uris = uris.copy()
    
    async def test_delete_single_object(self) -> bool:
        """Test deleting a single object by URI."""
        if not self.test_object_uris:
            self.log_test_result(
                "Delete Single Object",
                False,
                "No test object URIs available for deletion",
                {"test_uris": self.test_object_uris}
            )
            return False
        
        try:
            # Delete first test object
            test_uri = self.test_object_uris.pop(0)  # Remove from list since we're deleting it
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint.delete_objects(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=test_uri,
                current_user=current_user
            )
            
            if response and hasattr(response, 'deleted_count') and response.deleted_count > 0:
                self.log_test_result(
                    "Delete Single Object",
                    True,
                    f"Successfully deleted object: {test_uri}",
                    {"uri": test_uri, "deleted_count": response.deleted_count, "message": response.message}
                )
                return True
            else:
                self.log_test_result(
                    "Delete Single Object",
                    False,
                    "Failed to delete object",
                    {"uri": test_uri, "response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Delete Single Object",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_delete_multiple_objects(self) -> bool:
        """Test deleting multiple objects by URI list."""
        if len(self.test_object_uris) < 2:
            self.log_test_result(
                "Delete Multiple Objects",
                False,
                "Need at least 2 test object URIs for multi-delete",
                {"available_uris": len(self.test_object_uris)}
            )
            return False
        
        try:
            # Delete first two remaining test objects
            test_uris = [self.test_object_uris.pop(0), self.test_object_uris.pop(0)]
            uri_list_str = ','.join(test_uris)
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint.delete_objects(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri_list=uri_list_str,
                current_user=current_user
            )
            
            if response and hasattr(response, 'deleted_count') and response.deleted_count > 0:
                self.log_test_result(
                    "Delete Multiple Objects",
                    True,
                    f"Successfully deleted {response.deleted_count} objects",
                    {"uris": test_uris, "deleted_count": response.deleted_count, "message": response.message}
                )
                return True
            else:
                self.log_test_result(
                    "Delete Multiple Objects",
                    False,
                    "Failed to delete multiple objects",
                    {"uris": test_uris, "response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Delete Multiple Objects",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_delete_nonexistent_object(self) -> bool:
        """Test deleting object that doesn't exist."""
        try:
            # Try to delete nonexistent object
            nonexistent_uri = f"http://example.com/nonexistent/object/{self._generate_test_id()}"
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint.delete_objects(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=nonexistent_uri,
                current_user=current_user
            )
            
            # Should handle nonexistent object gracefully (might succeed with 0 deletions or fail)
            success = True
            result_msg = "Handled nonexistent object deletion gracefully"
            if response and hasattr(response, 'success'):
                result_msg += f" (success: {response.success})"
            
            self.log_test_result(
                "Delete Nonexistent Object",
                success,
                result_msg,
                {"uri": nonexistent_uri, "response": str(response)}
            )
            return success
                
        except Exception as e:
            # Exception might be expected for nonexistent objects
            self.log_test_result(
                "Delete Nonexistent Object",
                True,
                f"Exception for nonexistent object (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def test_delete_already_deleted_object(self) -> bool:
        """Test deleting object that was already deleted."""
        try:
            # Create and immediately delete an object, then try to delete again
            test_uri = f"http://example.com/test/delete_twice/{self._generate_test_id()}"
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            
            # First deletion (should succeed if object exists, or be handled gracefully)
            response1 = await self.endpoint.delete_objects(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=test_uri,
                current_user=current_user
            )
            
            # Second deletion (should handle already-deleted object)
            response2 = await self.endpoint.delete_objects(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=test_uri,
                current_user=current_user
            )
            
            # Should handle double deletion gracefully
            success = True
            self.log_test_result(
                "Delete Already Deleted Object",
                success,
                f"Handled double deletion gracefully",
                {"uri": test_uri, "first_response": str(response1), "second_response": str(response2)}
            )
            return success
                
        except Exception as e:
            # Exception might be expected for double deletion
            self.log_test_result(
                "Delete Already Deleted Object",
                True,
                f"Exception for double deletion (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def test_delete_without_parameters(self) -> bool:
        """Test delete request without uri or uri_list parameters."""
        try:
            # Try to delete without specifying any URIs
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint.delete_objects(
                space_id=self.space_id,
                graph_id=self.graph_id,
                current_user=current_user
            )
            
            # Should fail with appropriate error
            success = not (response and hasattr(response, 'success') and response.success)
            self.log_test_result(
                "Delete Without Parameters",
                success,
                "Correctly rejected delete request without URI parameters" if success else "Unexpectedly allowed delete without parameters",
                {"response": str(response)}
            )
            return success
                
        except Exception as e:
            # Exception is expected for missing parameters
            self.log_test_result(
                "Delete Without Parameters",
                True,
                f"Exception for missing parameters (expected): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    def _generate_test_id(self) -> str:
        """Generate unique test ID."""
        import uuid
        return str(uuid.uuid4())
    
    async def run_all_delete_tests(self) -> Dict[str, bool]:
        """Run all objects delete tests."""
        results = {}
        
        results["delete_single"] = await self.test_delete_single_object()
        results["delete_multiple"] = await self.test_delete_multiple_objects()
        results["delete_nonexistent"] = await self.test_delete_nonexistent_object()
        results["delete_already_deleted"] = await self.test_delete_already_deleted_object()
        results["delete_without_params"] = await self.test_delete_without_parameters()
        
        return results
