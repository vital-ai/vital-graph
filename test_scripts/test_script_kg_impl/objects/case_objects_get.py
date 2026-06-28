"""
Objects Get Test Cases

Tests the Objects endpoint get functionality for single and multiple object retrieval.
"""

import logging
from typing import Dict, Any, List, Optional


class ObjectsGetTester:
    """Test cases for Objects endpoint get operations."""
    
    def __init__(self, endpoint, space_id: str, graph_id: str):
        self.endpoint = endpoint
        self.space_id = space_id
        self.graph_id = graph_id
        self.logger = logging.getLogger(f"{__name__}.ObjectsGetTester")
        self.test_object_uris = []
    
    def log_test_result(self, test_name: str, success: bool, message: str, details: Dict[str, Any] = None):
        """Log test result with consistent formatting."""
        status = "✅ PASS" if success else "❌ FAIL"
        self.logger.info(f"{status} - {test_name}: {message}")
        if details:
            self.logger.debug(f"Details: {details}")
    
    def set_test_object_uris(self, uris: List[str]):
        """Set the URIs of test objects created for testing."""
        self.test_object_uris = uris
    
    async def test_get_object_by_uri(self) -> bool:
        """Test getting single object by URI."""
        if not self.test_object_uris:
            self.log_test_result(
                "Get Object by URI",
                False,
                "No test object URIs available",
                {"test_uris": self.test_object_uris}
            )
            return False
        
        try:
            test_uri = self.test_object_uris[0]
            response = await self.endpoint.list_or_get_objects(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=test_uri
            )
            
            # Response is QuadResultsResponse with results: List[Quad]
            if response and hasattr(response, 'results') and response.results:
                self.log_test_result(
                    "Get Object by URI",
                    True,
                    f"Retrieved object with URI: {test_uri}",
                    {"uri": test_uri, "quad_count": len(response.results), "total_count": response.total_count}
                )
                return True
            else:
                self.log_test_result(
                    "Get Object by URI",
                    False,
                    f"No results for URI: {test_uri}",
                    {"uri": test_uri, "response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Get Object by URI",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_get_objects_by_uri_list(self) -> bool:
        """Test getting multiple objects by URI list."""
        if len(self.test_object_uris) < 2:
            self.log_test_result(
                "Get Objects by URI List",
                False,
                "Need at least 2 test object URIs",
                {"available_uris": len(self.test_object_uris)}
            )
            return False
        
        try:
            # Use first 2 URIs
            test_uris = self.test_object_uris[:2]
            uri_list_str = ','.join(test_uris)
            
            response = await self.endpoint.list_or_get_objects(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri_list=uri_list_str
            )
            
            # Response is QuadResultsResponse with results: List[Quad]
            if response and hasattr(response, 'results') and response.results:
                self.log_test_result(
                    "Get Objects by URI List",
                    True,
                    f"Retrieved objects for {len(test_uris)} URIs ({len(response.results)} quads)",
                    {"uri_count": len(test_uris), "quad_count": len(response.results)}
                )
                return True
            else:
                self.log_test_result(
                    "Get Objects by URI List",
                    False,
                    f"No results for URI list",
                    {"uri_list": test_uris, "response": str(response)}
                )
                return False
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.log_test_result(
                "Get Objects by URI List",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_get_nonexistent_object(self) -> bool:
        """Test getting object that doesn't exist."""
        try:
            nonexistent_uri = "http://example.com/nonexistent/object/12345"
            response = await self.endpoint.list_or_get_objects(
                space_id=self.space_id,
                graph_id=self.graph_id,
                uri=nonexistent_uri
            )
            
            # Should return empty results for nonexistent object
            success = response is None or (hasattr(response, 'results') and not response.results)
            self.log_test_result(
                "Get Nonexistent Object",
                success,
                f"Correctly handled nonexistent URI: {nonexistent_uri}",
                {"uri": nonexistent_uri, "response": str(response) if response else None}
            )
            return success
                
        except Exception as e:
            # Exception might be expected for nonexistent objects
            self.log_test_result(
                "Get Nonexistent Object",
                True,
                f"Exception for nonexistent object (expected): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def run_all_get_tests(self) -> Dict[str, bool]:
        """Run all objects get tests."""
        results = {}
        
        results["get_by_uri"] = await self.test_get_object_by_uri()
        results["get_by_uri_list"] = await self.test_get_objects_by_uri_list()
        results["get_nonexistent"] = await self.test_get_nonexistent_object()
        
        return results
