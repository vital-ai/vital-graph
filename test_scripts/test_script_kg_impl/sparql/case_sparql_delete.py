"""
SPARQL Delete Test Case

Tests SPARQL delete operations via REST API endpoints:
- POST /api/graphs/sparql/delete?space_id=
- POST /api/graphs/sparql/delete-form?space_id=

Tests various SPARQL DELETE operations including DELETE DATA and DELETE WHERE patterns.
"""

import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class SPARQLDeleteTester:
    """Test case for SPARQL delete operations."""
    
    def __init__(self, endpoint, space_id: str, graph_id: str, logger: Optional[logging.Logger] = None):
        """
        Initialize SPARQL delete tester.
        
        Args:
            endpoint: SPARQL endpoint instance
            space_id: Target space ID
            graph_id: Target graph ID
            logger: Optional logger instance
        """
        self.endpoint = endpoint
        self.space_id = space_id
        self.graph_id = graph_id
        self.logger = logger or logging.getLogger(__name__)
        self.test_results = []
        
    def log_test_result(self, test_name: str, success: bool, message: str, details: Optional[Dict[str, Any]] = None):
        """Log test result with standard format."""
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
    
    def set_test_uris(self, uris: List[str]):
        """Set URIs that were created during insert tests for deletion."""
        self.test_uris = uris
        self.logger.info(f"Set {len(uris)} test URIs for deletion testing")
    
    async def test_sparql_delete_data(self) -> bool:
        """Test SPARQL DELETE DATA operation."""
        try:
            if not hasattr(self, 'test_uris') or not self.test_uris:
                self.log_test_result(
                    "SPARQL DELETE DATA",
                    False,
                    "No test URIs available for deletion",
                    {"available_uris": 0}
                )
                return False
            
            # Use first test URI for DELETE DATA
            test_uri = self.test_uris[0]
            
            # DELETE DATA operation
            delete_query = f"""
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            PREFIX ex: <http://example.org/>
            
            DELETE DATA {{
                GRAPH <{self.graph_id}> {{
                    <{test_uri}> a foaf:Person .
                    <{test_uri}> foaf:name "Test Person Insert Data" .
                    <{test_uri}> foaf:age 30 .
                    <{test_uri}> ex:testType "insert_data" .
                }}
            }}
            """
            
            response = await self.endpoint.sparql_delete_post(
                space_id=self.space_id,
                delete=delete_query
            )
            
            if response and hasattr(response, 'success') and response.success:
                self.log_test_result(
                    "SPARQL DELETE DATA",
                    True,
                    "DELETE DATA operation executed successfully",
                    {"operation": "DELETE DATA", "uri": test_uri}
                )
                return True
            else:
                self.log_test_result(
                    "SPARQL DELETE DATA",
                    False,
                    "DELETE DATA operation failed",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "SPARQL DELETE DATA",
                False,
                f"Exception during DELETE DATA operation: {e}",
                {"exception": str(e)}
            )
            return False
    
    async def test_sparql_delete_where(self) -> bool:
        """Test SPARQL DELETE WHERE operation."""
        try:
            # DELETE WHERE operation to remove test entities
            delete_query = f"""
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            PREFIX ex: <http://example.org/>
            
            DELETE {{
                GRAPH <{self.graph_id}> {{
                    ?person ?p ?o .
                }}
            }}
            WHERE {{
                GRAPH <{self.graph_id}> {{
                    ?person a foaf:Person .
                    ?person ex:testType "insert_where" .
                    ?person ?p ?o .
                }}
            }}
            """
            
            response = await self.endpoint.sparql_delete_post(
                space_id=self.space_id,
                delete=delete_query
            )
            
            if response and hasattr(response, 'success') and response.success:
                self.log_test_result(
                    "SPARQL DELETE WHERE",
                    True,
                    "DELETE WHERE operation executed successfully",
                    {"operation": "DELETE WHERE", "pattern": "test entities with testType=insert_where"}
                )
                return True
            else:
                self.log_test_result(
                    "SPARQL DELETE WHERE",
                    False,
                    "DELETE WHERE operation failed",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "SPARQL DELETE WHERE",
                False,
                f"Exception during DELETE WHERE operation: {e}",
                {"exception": str(e)}
            )
            return False
    
    async def test_sparql_delete_form(self) -> bool:
        """Test SPARQL DELETE via form submission."""
        try:
            # DELETE operation via form
            delete_query = f"""
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            PREFIX ex: <http://example.org/>
            
            DELETE {{
                GRAPH <{self.graph_id}> {{
                    ?person ?p ?o .
                }}
            }}
            WHERE {{
                GRAPH <{self.graph_id}> {{
                    ?person a foaf:Person .
                    ?person ex:testType "insert_form" .
                    ?person ?p ?o .
                }}
            }}
            """
            
            response = await self.endpoint.sparql_delete_form(
                space_id=self.space_id,
                delete=delete_query
            )
            
            if response and hasattr(response, 'success') and response.success:
                self.log_test_result(
                    "SPARQL DELETE (Form)",
                    True,
                    "DELETE operation via form executed successfully",
                    {"operation": "DELETE WHERE", "method": "FORM"}
                )
                return True
            else:
                self.log_test_result(
                    "SPARQL DELETE (Form)",
                    False,
                    "DELETE operation via form failed",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "SPARQL DELETE (Form)",
                False,
                f"Exception during form DELETE operation: {e}",
                {"exception": str(e)}
            )
            return False
    
    async def test_complex_delete_operation(self) -> bool:
        """Test complex SPARQL DELETE with multiple patterns."""
        try:
            # Complex DELETE with relationships
            delete_query = f"""
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            PREFIX ex: <http://example.org/>
            PREFIX org: <http://www.w3.org/ns/org#>
            
            DELETE {{
                GRAPH <{self.graph_id}> {{
                    ?person ?pp ?po .
                    ?org ?op ?oo .
                }}
            }}
            WHERE {{
                GRAPH <{self.graph_id}> {{
                    ?person a foaf:Person .
                    ?person org:memberOf ?org .
                    ?org ex:testType "complex_insert" .
                    ?person ?pp ?po .
                    ?org ?op ?oo .
                }}
            }}
            """
            
            response = await self.endpoint.sparql_delete_post(
                space_id=self.space_id,
                delete=delete_query
            )
            
            if response and hasattr(response, 'success') and response.success:
                self.log_test_result(
                    "Complex SPARQL DELETE",
                    True,
                    "Complex DELETE operation executed successfully",
                    {"operation": "Complex DELETE with relationships"}
                )
                return True
            else:
                self.log_test_result(
                    "Complex SPARQL DELETE",
                    False,
                    "Complex DELETE operation failed",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Complex SPARQL DELETE",
                False,
                f"Exception during complex DELETE operation: {e}",
                {"exception": str(e)}
            )
            return False
    
    async def run_all_delete_tests(self) -> Dict[str, Any]:
        """Run all SPARQL delete tests."""
        self.logger.info("🧪 Starting SPARQL Delete Tests")
        
        tests = [
            self.test_sparql_delete_data,
            self.test_sparql_delete_where,
            self.test_sparql_delete_form,
            self.test_complex_delete_operation
        ]
        
        passed = 0
        total = len(tests)
        
        for test in tests:
            try:
                if await test():
                    passed += 1
            except Exception as e:
                self.logger.error(f"Test {test.__name__} failed with exception: {e}")
        
        success_rate = (passed / total) * 100 if total > 0 else 0
        
        self.logger.info(f"🧪 SPARQL Delete Tests Complete: {passed}/{total} passed ({success_rate:.1f}%)")
        
        return {
            "all_passed": passed == total,
            "passed_tests": passed,
            "total_tests": total,
            "success_rate": success_rate,
            "test_results": self.test_results
        }


def create_sparql_delete_tester(endpoint, space_id: str, graph_id: str, logger: Optional[logging.Logger] = None) -> SPARQLDeleteTester:
    """Factory function to create SPARQLDeleteTester instance."""
    return SPARQLDeleteTester(endpoint, space_id, graph_id, logger)
