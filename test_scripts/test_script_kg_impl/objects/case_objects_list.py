"""
Objects List Test Cases

Tests the Objects endpoint list functionality with pagination, filtering, and search.
"""

import logging
from typing import Dict, Any, List, Optional


class ObjectsListTester:
    """Test cases for Objects endpoint list operations."""
    
    def __init__(self, endpoint, space_id: str, graph_id: str):
        self.endpoint = endpoint
        self.space_id = space_id
        self.graph_id = graph_id
        self.logger = logging.getLogger(f"{__name__}.ObjectsListTester")
    
    def log_test_result(self, test_name: str, success: bool, message: str, details: Dict[str, Any] = None):
        """Log test result with consistent formatting."""
        status = "✅ PASS" if success else "❌ FAIL"
        self.logger.info(f"{status} - {test_name}: {message}")
        if details:
            self.logger.debug(f"Details: {details}")
    
    async def test_list_objects_empty(self) -> bool:
        """Test listing objects from empty graph."""
        try:
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint.list_or_get_objects(
                space_id=self.space_id,
                graph_id=self.graph_id,
                page_size=10,
                offset=0,
                current_user=current_user
            )
            
            if response and hasattr(response, 'objects') and hasattr(response, 'total_count'):
                success = response.total_count == 0
                self.log_test_result(
                    "List Objects (Empty Graph)",
                    success,
                    f"Empty graph returned {response.total_count} objects" if success else "Expected empty graph",
                    {"total_count": response.total_count, "page_size": response.page_size}
                )
                return success
            else:
                self.log_test_result(
                    "List Objects (Empty Graph)",
                    False,
                    "Invalid response structure",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "List Objects (Empty Graph)",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_list_objects_populated(self) -> bool:
        """Test listing objects from populated graph."""
        try:
            response = await self.endpoint.list_or_get_objects(
                space_id=self.space_id,
                graph_id=self.graph_id,
                page_size=10,
                offset=0
            )
            
            if response and hasattr(response, 'objects') and hasattr(response, 'total_count'):
                success = response.total_count > 0
                self.log_test_result(
                    "List Objects (Populated Graph)",
                    success,
                    f"Found {response.total_count} objects in graph",
                    {"total_count": response.total_count, "page_size": response.page_size}
                )
                return success
            else:
                self.log_test_result(
                    "List Objects (Populated Graph)",
                    False,
                    "Invalid response structure",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "List Objects (Populated Graph)",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_list_objects_pagination(self) -> bool:
        """Test objects list pagination."""
        try:
            # Test with small page size
            response = await self.endpoint.list_or_get_objects(
                space_id=self.space_id,
                graph_id=self.graph_id,
                page_size=2,
                offset=0
            )
            
            if response and hasattr(response, 'objects') and hasattr(response, 'total_count'):
                success = response.page_size == 2
                self.log_test_result(
                    "List Objects (Pagination)",
                    success,
                    f"Pagination working: page_size={response.page_size}, total={response.total_count}",
                    {"page_size": response.page_size, "total_count": response.total_count, "offset": response.offset}
                )
                return success
            else:
                self.log_test_result(
                    "List Objects (Pagination)",
                    False,
                    "Invalid response structure",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "List Objects (Pagination)",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_list_objects_with_search(self) -> bool:
        """Test objects list with search functionality."""
        try:
            response = await self.endpoint.list_or_get_objects(
                space_id=self.space_id,
                graph_id=self.graph_id,
                page_size=10,
                offset=0,
                search="test"
            )
            
            if response and hasattr(response, 'objects') and hasattr(response, 'total_count'):
                self.log_test_result(
                    "List Objects (Search)",
                    True,
                    f"Search completed, found {response.total_count} matching objects",
                    {"search_term": "test", "total_count": response.total_count}
                )
                return True
            else:
                self.log_test_result(
                    "List Objects (Search)",
                    False,
                    "Invalid response structure",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "List Objects (Search)",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def run_all_list_tests(self) -> Dict[str, bool]:
        """Run all objects list tests."""
        results = {}
        
        # Test empty graph first
        results["empty"] = await self.test_list_objects_empty()
        
        # Note: populated, pagination, and search tests should be run after objects are created
        
        return results
    
    async def run_populated_list_tests(self) -> Dict[str, bool]:
        """Run list tests that require populated graph."""
        results = {}
        
        results["populated"] = await self.test_list_objects_populated()
        results["pagination"] = await self.test_list_objects_pagination()
        results["search"] = await self.test_list_objects_with_search()
        
        return results
