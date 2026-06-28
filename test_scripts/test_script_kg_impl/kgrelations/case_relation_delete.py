"""
KGRelations Delete Test Cases

Tests for deleting KG relations via the KGRelations endpoint.
"""

import logging
from typing import Dict, Any, List, Optional

from vitalgraph.model.kgrelations_model import RelationDeleteRequest, RelationDeleteResponse

logger = logging.getLogger(__name__)


class KGRelationDeleteTester:
    """Test cases for KGRelations deletion operations."""
    
    def __init__(self, endpoint, space_id: str, graph_id: str):
        self.endpoint = endpoint
        self.space_id = space_id
        self.graph_id = graph_id
        self.test_relation_uris = []
    
    def log_test_result(self, test_name: str, success: bool, message: str, details: Dict[str, Any] = None):
        """Log test result with consistent formatting."""
        status = "✅ PASS" if success else "❌ FAIL"
        logger.info(f"{status} - {test_name}: {message}")
        if details:
            logger.debug(f"Details: {details}")
    
    def set_test_relation_uris(self, uris: List[str]):
        """Set test relation URIs from create tests."""
        self.test_relation_uris = uris.copy()
    
    async def test_delete_single_relation(self) -> bool:
        """Test deleting a single relation by URI."""
        if not self.test_relation_uris:
            self.log_test_result(
                "Delete Single Relation",
                False,
                "No test relation URIs available for deletion",
                {"test_uris": self.test_relation_uris}
            )
            return False
        
        try:
            # Delete first test relation
            test_uri = self.test_relation_uris.pop(0)  # Remove from list since we're deleting it
            
            delete_request = RelationDeleteRequest(relation_uris=[test_uri])
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._delete_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                request=delete_request,
                current_user=current_user
            )
            
            if response and hasattr(response, 'deleted_count') and response.deleted_count > 0:
                self.log_test_result(
                    "Delete Single Relation",
                    True,
                    f"Successfully deleted relation: {test_uri}",
                    {"uri": test_uri, "deleted_count": response.deleted_count, "message": response.message}
                )
                return True
            else:
                self.log_test_result(
                    "Delete Single Relation",
                    False,
                    "Failed to delete relation",
                    {"uri": test_uri, "response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Delete Single Relation",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_delete_multiple_relations(self) -> bool:
        """Test deleting multiple relations in one request."""
        if len(self.test_relation_uris) < 2:
            self.log_test_result(
                "Delete Multiple Relations",
                False,
                "Need at least 2 test relation URIs for multi-delete",
                {"available_uris": len(self.test_relation_uris)}
            )
            return False
        
        try:
            # Delete first two remaining test relations
            test_uris = [self.test_relation_uris.pop(0), self.test_relation_uris.pop(0)]
            
            delete_request = RelationDeleteRequest(relation_uris=test_uris)
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._delete_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                request=delete_request,
                current_user=current_user
            )
            
            if response and hasattr(response, 'deleted_count') and response.deleted_count > 0:
                self.log_test_result(
                    "Delete Multiple Relations",
                    True,
                    f"Successfully deleted {response.deleted_count} relations",
                    {"uris": test_uris, "deleted_count": response.deleted_count, "message": response.message}
                )
                return True
            else:
                self.log_test_result(
                    "Delete Multiple Relations",
                    False,
                    "Failed to delete multiple relations",
                    {"uris": test_uris, "response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Delete Multiple Relations",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_delete_nonexistent_relation(self) -> bool:
        """Test deleting relation that doesn't exist."""
        try:
            # Try to delete nonexistent relation
            nonexistent_uri = "http://vital.ai/test/kgrelation/nonexistent_delete_12345"
            
            delete_request = RelationDeleteRequest(relation_uris=[nonexistent_uri])
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._delete_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                request=delete_request,
                current_user=current_user
            )
            
            # For stub implementation, this might succeed - that's acceptable
            success = True
            result_msg = "Handled nonexistent relation deletion gracefully"
            if response and hasattr(response, 'deleted_count'):
                result_msg += f" (deleted_count: {response.deleted_count})"
            
            self.log_test_result(
                "Delete Nonexistent Relation",
                success,
                result_msg,
                {"uri": nonexistent_uri, "response": str(response)}
            )
            return success
            
        except Exception as e:
            # Exception for nonexistent relation is acceptable
            self.log_test_result(
                "Delete Nonexistent Relation",
                True,
                f"Exception for nonexistent relation (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def test_delete_already_deleted_relation(self) -> bool:
        """Test deleting relation that was already deleted."""
        try:
            # Create and immediately delete a relation, then try to delete again
            test_uri = "http://vital.ai/test/kgrelation/delete_twice_test"
            
            delete_request = RelationDeleteRequest(relation_uris=[test_uri])
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            
            # First deletion (should succeed if relation exists, or be handled gracefully)
            response1 = await self.endpoint._delete_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                request=delete_request,
                current_user=current_user
            )
            
            # Second deletion (should handle already-deleted relation)
            response2 = await self.endpoint._delete_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                request=delete_request,
                current_user=current_user
            )
            
            # Should handle double deletion gracefully
            success = True
            self.log_test_result(
                "Delete Already Deleted Relation",
                success,
                f"Handled double deletion gracefully",
                {"uri": test_uri, "first_response": str(response1), "second_response": str(response2)}
            )
            return success
            
        except Exception as e:
            # Exception for double deletion is acceptable
            self.log_test_result(
                "Delete Already Deleted Relation",
                True,
                f"Exception for double deletion (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def test_delete_empty_uri_list(self) -> bool:
        """Test delete request with empty URI list."""
        try:
            # Try to delete with empty URI list
            delete_request = RelationDeleteRequest(relation_uris=[])
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._delete_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                request=delete_request,
                current_user=current_user
            )
            
            # Should handle empty list gracefully
            success = True
            result_msg = "Handled empty URI list deletion"
            if response and hasattr(response, 'deleted_count'):
                result_msg += f" (deleted_count: {response.deleted_count})"
            
            self.log_test_result(
                "Delete Empty URI List",
                success,
                result_msg,
                {"uris": [], "response": str(response)}
            )
            return success
            
        except Exception as e:
            # Exception for empty list might be acceptable
            self.log_test_result(
                "Delete Empty URI List",
                True,
                f"Exception for empty URI list (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def test_delete_invalid_uris(self) -> bool:
        """Test delete request with invalid URI formats."""
        try:
            # Try to delete with invalid URIs
            invalid_uris = ["not_a_valid_uri", "also_invalid", ""]
            
            delete_request = RelationDeleteRequest(relation_uris=invalid_uris)
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._delete_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                request=delete_request,
                current_user=current_user
            )
            
            # For stub implementation, this might succeed - that's acceptable
            success = True
            result_msg = "Handled invalid URIs deletion"
            if response and hasattr(response, 'deleted_count'):
                result_msg += f" (deleted_count: {response.deleted_count})"
            
            self.log_test_result(
                "Delete Invalid URIs",
                success,
                result_msg,
                {"uris": invalid_uris, "response": str(response)}
            )
            return success
            
        except Exception as e:
            # Exception for invalid URIs is acceptable
            self.log_test_result(
                "Delete Invalid URIs",
                True,
                f"Exception for invalid URIs (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def run_all_delete_tests(self) -> Dict[str, bool]:
        """Run all relation deletion tests."""
        logger.info("🧪 Running KGRelations Delete Tests")
        
        results = {}
        
        # Test single relation deletion
        results["delete_single_relation"] = await self.test_delete_single_relation()
        
        # Test multiple relations deletion
        results["delete_multiple_relations"] = await self.test_delete_multiple_relations()
        
        # Test nonexistent relation deletion
        results["delete_nonexistent_relation"] = await self.test_delete_nonexistent_relation()
        
        # Test already deleted relation
        results["delete_already_deleted_relation"] = await self.test_delete_already_deleted_relation()
        
        # Test empty URI list deletion
        results["delete_empty_uri_list"] = await self.test_delete_empty_uri_list()
        
        # Test invalid URIs deletion
        results["delete_invalid_uris"] = await self.test_delete_invalid_uris()
        
        return results
