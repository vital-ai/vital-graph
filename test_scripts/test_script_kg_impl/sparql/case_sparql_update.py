"""
SPARQL Update Test Case

Tests SPARQL update operations via REST API endpoints:
- POST /api/graphs/sparql/update?space_id=
- POST /api/graphs/sparql/update-form?space_id=

Tests various SPARQL UPDATE operations including DELETE/INSERT patterns.
"""

import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class SPARQLUpdateTester:
    """Test case for SPARQL update operations."""
    
    def __init__(self, endpoint, space_id: str, graph_id: str, logger: Optional[logging.Logger] = None):
        """
        Initialize SPARQL update tester.
        
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
    
    async def test_sparql_update_post(self) -> bool:
        """Test SPARQL UPDATE via POST method."""
        try:
            # UPDATE operation using DELETE/INSERT pattern
            update_query = f"""
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            PREFIX ex: <http://example.org/>
            
            DELETE {{
                GRAPH <{self.graph_id}> {{
                    ex:testPerson foaf:age ?oldAge .
                }}
            }}
            INSERT {{
                GRAPH <{self.graph_id}> {{
                    ex:testPerson foaf:age 35 .
                    ex:testPerson ex:lastUpdated "2026-01-11" .
                }}
            }}
            WHERE {{
                GRAPH <{self.graph_id}> {{
                    ex:testPerson foaf:age ?oldAge .
                }}
            }}
            """
            
            # Execute UPDATE
            response = await self.endpoint.sparql_update_post(
                space_id=self.space_id,
                update=update_query
            )
            
            if response and hasattr(response, 'success') and response.success:
                self.log_test_result(
                    "SPARQL UPDATE (POST)",
                    True,
                    "UPDATE operation executed successfully",
                    {"operation": "DELETE/INSERT", "method": "POST"}
                )
                return True
            else:
                self.log_test_result(
                    "SPARQL UPDATE (POST)",
                    False,
                    "UPDATE operation failed",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "SPARQL UPDATE (POST)",
                False,
                f"Exception during UPDATE operation: {e}",
                {"exception": str(e)}
            )
            return False
    
    async def test_sparql_update_form(self) -> bool:
        """Test SPARQL UPDATE via form submission."""
        try:
            # Simple UPDATE using form method
            update_query = f"""
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            PREFIX ex: <http://example.org/>
            
            DELETE {{
                GRAPH <{self.graph_id}> {{
                    ex:testPerson2 foaf:status ?oldStatus .
                }}
            }}
            INSERT {{
                GRAPH <{self.graph_id}> {{
                    ex:testPerson2 foaf:status "updated" .
                }}
            }}
            WHERE {{
                GRAPH <{self.graph_id}> {{
                    ex:testPerson2 foaf:status ?oldStatus .
                }}
            }}
            """
            
            # Execute UPDATE via form
            response = await self.endpoint.sparql_update_form(
                space_id=self.space_id,
                update=update_query
            )
            
            if response and hasattr(response, 'success') and response.success:
                self.log_test_result(
                    "SPARQL UPDATE (Form)",
                    True,
                    "UPDATE operation via form executed successfully",
                    {"operation": "DELETE/INSERT", "method": "FORM"}
                )
                return True
            else:
                self.log_test_result(
                    "SPARQL UPDATE (Form)",
                    False,
                    "UPDATE operation via form failed",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "SPARQL UPDATE (Form)",
                False,
                f"Exception during form UPDATE operation: {e}",
                {"exception": str(e)}
            )
            return False
    
    async def test_complex_update_operation(self) -> bool:
        """Test complex SPARQL UPDATE with multiple patterns."""
        try:
            # Complex UPDATE with multiple DELETE/INSERT blocks
            update_query = f"""
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            PREFIX ex: <http://example.org/>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            
            DELETE {{
                GRAPH <{self.graph_id}> {{
                    ?person foaf:age ?oldAge .
                    ?person ex:status ?oldStatus .
                }}
            }}
            INSERT {{
                GRAPH <{self.graph_id}> {{
                    ?person foaf:age ?newAge .
                    ?person ex:status "verified" .
                    ?person vital:hasModifiedTime "2026-01-11T10:00:00Z" .
                }}
            }}
            WHERE {{
                GRAPH <{self.graph_id}> {{
                    ?person a foaf:Person .
                    ?person foaf:age ?oldAge .
                    ?person ex:status ?oldStatus .
                    BIND(?oldAge + 1 AS ?newAge)
                    FILTER(?oldAge < 100)
                }}
            }}
            """
            
            response = await self.endpoint.sparql_update_post(
                space_id=self.space_id,
                update=update_query
            )
            
            if response and hasattr(response, 'success') and response.success:
                self.log_test_result(
                    "Complex SPARQL UPDATE",
                    True,
                    "Complex UPDATE operation executed successfully",
                    {"operation": "Complex DELETE/INSERT with BIND and FILTER", "method": "POST"}
                )
                return True
            else:
                self.log_test_result(
                    "Complex SPARQL UPDATE",
                    False,
                    "Complex UPDATE operation failed",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Complex SPARQL UPDATE",
                False,
                f"Exception during complex UPDATE operation: {e}",
                {"exception": str(e)}
            )
            return False
    
    async def run_all_update_tests(self) -> Dict[str, Any]:
        """Run all SPARQL update tests."""
        self.logger.info("🧪 Starting SPARQL Update Tests")
        
        tests = [
            self.test_sparql_update_post,
            self.test_sparql_update_form,
            self.test_complex_update_operation
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
        
        self.logger.info(f"🧪 SPARQL Update Tests Complete: {passed}/{total} passed ({success_rate:.1f}%)")
        
        return {
            "all_passed": passed == total,
            "passed_tests": passed,
            "total_tests": total,
            "success_rate": success_rate,
            "test_results": self.test_results
        }


def create_sparql_update_tester(endpoint, space_id: str, graph_id: str, logger: Optional[logging.Logger] = None) -> SPARQLUpdateTester:
    """Factory function to create SPARQLUpdateTester instance."""
    return SPARQLUpdateTester(endpoint, space_id, graph_id, logger)
