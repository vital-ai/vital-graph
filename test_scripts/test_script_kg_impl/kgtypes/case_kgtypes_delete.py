"""
KGTypes Delete Modular Test Case

This module provides modular testing for KGTypes deletion operations.
Extracted from the monolithic test suite for better maintainability and reusability.
"""

import logging
from typing import List, Optional, Dict, Any
from ai_haley_kg_domain.model.KGType import KGType
from vitalgraph.model.kgtypes_model import KGTypeDeleteResponse


class KGTypesDeleteTester:
    """Modular tester for KGTypes deletion operations."""
    
    def __init__(self, endpoint, space_id: str, graph_id: str, logger: Optional[logging.Logger] = None):
        """
        Initialize the KGTypes Delete Tester.
        
        Args:
            endpoint: KGTypes endpoint instance
            space_id: Test space identifier
            graph_id: Test graph identifier
            logger: Optional logger instance
        """
        self.endpoint = endpoint
        self.space_id = space_id
        self.graph_id = graph_id
        self.logger = logger or logging.getLogger(__name__)
        
        # Test tracking
        self.test_results = []
        self.created_kgtype_ids = []
    
    def log_test_result(self, test_name: str, success: bool, message: str, details: Optional[Dict[str, Any]] = None):
        """Log test result with consistent formatting."""
        status = "✅ PASSED" if success else "❌ FAILED"
        self.logger.info(f"{status} - {test_name}: {message}")
        
        if details:
            for key, value in details.items():
                self.logger.info(f"  {key}: {value}")
        
        self.test_results.append({
            "test_name": test_name,
            "success": success,
            "message": message,
            "details": details or {}
        })
    
    def set_created_kgtype_ids(self, kgtype_ids: List[str]):
        """Set the list of created KGType IDs for deletion testing."""
        self.created_kgtype_ids = kgtype_ids.copy()
        self.logger.info(f"Set {len(kgtype_ids)} KGType IDs for deletion testing")
    
    async def test_delete_individual_kgtype(self) -> bool:
        """
        Test deleting an individual KGType by URI.
        
        Returns:
            bool: True if test passed, False otherwise
        """
        test_name = "Delete Individual KGType"
        
        try:
            # Ensure we have KGTypes available for deletion
            if not self.created_kgtype_ids:
                self.log_test_result(
                    test_name, 
                    False, 
                    "No KGTypes available for deletion test",
                    {"available_ids": len(self.created_kgtype_ids)}
                )
                return False
            
            # Delete the last created KGType
            kgtype_id = self.created_kgtype_ids[-1]
            
            self.logger.info(f"Attempting to delete KGType: {kgtype_id}")
            
            response = await self.endpoint._delete_kgtypes(
                self.space_id,
                self.graph_id,
                uri=kgtype_id,
                uri_list=None,
                document=None,
                current_user={"username": "test_user", "user_id": "test_user_123"}
            )
            
            if response and hasattr(response, 'success') and response.success:
                # Remove from our tracking list
                self.created_kgtype_ids.remove(kgtype_id)
                
                self.log_test_result(
                    test_name, 
                    True, 
                    f"Successfully deleted KGType: {kgtype_id}",
                    {
                        "deleted_kgtype_id": kgtype_id,
                        "remaining_ids": len(self.created_kgtype_ids),
                        "response_message": getattr(response, 'message', 'No message')
                    }
                )
                return True
            else:
                self.log_test_result(
                    test_name, 
                    False, 
                    f"Failed to delete KGType: {kgtype_id}",
                    {
                        "kgtype_id": kgtype_id,
                        "response_success": getattr(response, 'success', None),
                        "response_message": getattr(response, 'message', 'No message'),
                        "response_type": type(response).__name__
                    }
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                test_name, 
                False, 
                f"Exception during KGType deletion: {str(e)}",
                {"exception_type": type(e).__name__, "kgtype_id": kgtype_id if 'kgtype_id' in locals() else "unknown"}
            )
            return False
    
    async def test_delete_multiple_kgtypes(self) -> bool:
        """
        Test deleting multiple KGTypes using URI list.
        
        Returns:
            bool: True if test passed, False otherwise
        """
        test_name = "Delete Multiple KGTypes"
        
        try:
            # Ensure we have at least 2 KGTypes available for deletion
            if len(self.created_kgtype_ids) < 2:
                self.log_test_result(
                    test_name, 
                    False, 
                    f"Need at least 2 KGTypes for batch deletion test, have {len(self.created_kgtype_ids)}",
                    {"available_ids": len(self.created_kgtype_ids)}
                )
                return False
            
            # Delete the first 2 KGTypes
            kgtype_ids_to_delete = self.created_kgtype_ids[:2]
            
            self.logger.info(f"Attempting to delete {len(kgtype_ids_to_delete)} KGTypes: {kgtype_ids_to_delete}")
            
            response = await self.endpoint._delete_kgtypes(
                self.space_id,
                self.graph_id,
                uri=None,
                uri_list=kgtype_ids_to_delete,
                document=None,
                current_user={"username": "test_user", "user_id": "test_user_123"}
            )
            
            if response and hasattr(response, 'success') and response.success:
                # Remove from our tracking list
                for kgtype_id in kgtype_ids_to_delete:
                    if kgtype_id in self.created_kgtype_ids:
                        self.created_kgtype_ids.remove(kgtype_id)
                
                self.log_test_result(
                    test_name, 
                    True, 
                    f"Successfully deleted {len(kgtype_ids_to_delete)} KGTypes",
                    {
                        "deleted_kgtype_ids": kgtype_ids_to_delete,
                        "remaining_ids": len(self.created_kgtype_ids),
                        "response_message": getattr(response, 'message', 'No message')
                    }
                )
                return True
            else:
                self.log_test_result(
                    test_name, 
                    False, 
                    f"Failed to delete multiple KGTypes",
                    {
                        "kgtype_ids": kgtype_ids_to_delete,
                        "response_success": getattr(response, 'success', None),
                        "response_message": getattr(response, 'message', 'No message'),
                        "response_type": type(response).__name__
                    }
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                test_name, 
                False, 
                f"Exception during multiple KGTypes deletion: {str(e)}",
                {
                    "exception_type": type(e).__name__, 
                    "kgtype_ids": kgtype_ids_to_delete if 'kgtype_ids_to_delete' in locals() else "unknown"
                }
            )
            return False
    
    async def test_delete_nonexistent_kgtype(self) -> bool:
        """
        Test deleting a non-existent KGType (should handle gracefully).
        
        Returns:
            bool: True if test passed, False otherwise
        """
        test_name = "Delete Non-existent KGType"
        
        try:
            # Use a non-existent KGType ID
            nonexistent_id = "http://vital.ai/haley.ai/haley-ai-kg#KGType_nonexistent_test_delete"
            
            self.logger.info(f"Attempting to delete non-existent KGType: {nonexistent_id}")
            
            response = await self.endpoint._delete_kgtypes(
                self.space_id,
                self.graph_id,
                uri=nonexistent_id,
                uri_list=None,
                document=None,
                current_user={"username": "test_user", "user_id": "test_user_123"}
            )
            
            # The endpoint should handle this gracefully - either succeed (idempotent) or fail with proper error
            if response and hasattr(response, 'success'):
                if response.success:
                    self.log_test_result(
                        test_name, 
                        True, 
                        f"Deletion of non-existent KGType handled gracefully (idempotent behavior)",
                        {
                            "nonexistent_id": nonexistent_id,
                            "response_message": getattr(response, 'message', 'No message')
                        }
                    )
                    return True
                else:
                    # Failure is also acceptable for non-existent resources
                    self.log_test_result(
                        test_name, 
                        True, 
                        f"Deletion of non-existent KGType properly failed",
                        {
                            "nonexistent_id": nonexistent_id,
                            "response_message": getattr(response, 'message', 'No message')
                        }
                    )
                    return True
            else:
                self.log_test_result(
                    test_name, 
                    False, 
                    f"Invalid response format for non-existent KGType deletion",
                    {
                        "nonexistent_id": nonexistent_id,
                        "response_type": type(response).__name__
                    }
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                test_name, 
                False, 
                f"Exception during non-existent KGType deletion: {str(e)}",
                {"exception_type": type(e).__name__, "nonexistent_id": nonexistent_id}
            )
            return False
    
    async def run_all_delete_tests(self) -> Dict[str, Any]:
        """
        Run all KGTypes deletion tests.
        
        Returns:
            Dict containing test results summary
        """
        self.logger.info("🧪 Starting KGTypes Delete Tests")
        
        # Run all delete tests
        tests = [
            ("Individual Delete", self.test_delete_individual_kgtype),
            ("Multiple Delete", self.test_delete_multiple_kgtypes),
            ("Non-existent Delete", self.test_delete_nonexistent_kgtype)
        ]
        
        results = []
        for test_name, test_func in tests:
            self.logger.info(f"🔍 Running: {test_name}")
            try:
                result = await test_func()
                results.append(result)
                status = "✅ PASSED" if result else "❌ FAILED"
                self.logger.info(f"Result: {status}")
            except Exception as e:
                self.logger.error(f"❌ FAILED with exception: {e}")
                results.append(False)
        
        # Calculate summary
        passed = sum(1 for r in results if r)
        total = len(results)
        success_rate = (passed / total) * 100 if total > 0 else 0
        
        summary = {
            "total_tests": total,
            "passed_tests": passed,
            "failed_tests": total - passed,
            "success_rate": success_rate,
            "all_passed": passed == total,
            "test_results": self.test_results,
            "remaining_kgtype_ids": self.created_kgtype_ids.copy()
        }
        
        self.logger.info(f"📊 KGTypes Delete Tests Summary: {passed}/{total} passed ({success_rate:.1f}%)")
        
        return summary


def create_kgtypes_delete_tester(endpoint, space_id: str, graph_id: str, logger: Optional[logging.Logger] = None) -> KGTypesDeleteTester:
    """
    Factory function to create a KGTypes Delete Tester instance.
    
    Args:
        endpoint: KGTypes endpoint instance
        space_id: Test space identifier
        graph_id: Test graph identifier
        logger: Optional logger instance
        
    Returns:
        KGTypesDeleteTester: Configured tester instance
    """
    return KGTypesDeleteTester(endpoint, space_id, graph_id, logger)
