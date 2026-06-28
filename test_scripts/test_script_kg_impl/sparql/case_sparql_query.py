"""
SPARQL Query Test Case

Tests SPARQL query operations via REST API endpoints:
- GET /api/graphs/sparql/query?space_id=
- POST /api/graphs/sparql/query?space_id=

Tests various SPARQL SELECT, ASK, CONSTRUCT, and DESCRIBE queries.
"""

import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class SPARQLQueryTester:
    """Test case for SPARQL query operations."""
    
    def __init__(self, endpoint, space_id: str, graph_id: str, logger: Optional[logging.Logger] = None):
        """
        Initialize SPARQL query tester.
        
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
    
    async def test_sparql_select_query_get(self) -> bool:
        """Test SPARQL SELECT query via GET method."""
        try:
            # Simple SELECT query
            query = f"""
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            
            SELECT ?person ?name WHERE {{
                GRAPH <{self.graph_id}> {{
                    ?person a foaf:Person .
                    ?person foaf:name ?name .
                }}
            }} LIMIT 10
            """
            
            # Execute via GET method
            response = await self.endpoint.sparql_query_get(
                space_id=self.space_id,
                query=query
            )
            
            if response and response.results and response.results.get('bindings'):
                bindings = response.results['bindings']
                self.log_test_result(
                    "SPARQL SELECT Query (GET)",
                    True,
                    f"Query executed successfully, returned {len(bindings)} results",
                    {"query_type": "SELECT", "method": "GET", "result_count": len(bindings)}
                )
                return True
            else:
                self.log_test_result(
                    "SPARQL SELECT Query (GET)",
                    False,
                    "Query failed or returned invalid response",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "SPARQL SELECT Query (GET)",
                False,
                f"Exception during query execution: {e}",
                {"exception": str(e)}
            )
            return False
    
    async def test_sparql_select_query_post(self) -> bool:
        """Test SPARQL SELECT query via POST method."""
        try:
            # Complex SELECT query with FILTER
            query = f"""
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            
            SELECT ?person ?name ?type WHERE {{
                GRAPH <{self.graph_id}> {{
                    ?person a ?type .
                    ?person foaf:name ?name .
                    FILTER(CONTAINS(LCASE(?name), "test"))
                }}
            }} ORDER BY ?name LIMIT 5
            """
            
            # Execute via POST method
            response = await self.endpoint.sparql_query_post(
                space_id=self.space_id,
                query=query
            )
            
            if response and response.results and response.results.get('bindings'):
                bindings = response.results['bindings']
                self.log_test_result(
                    "SPARQL SELECT Query (POST)",
                    True,
                    f"Complex query executed successfully, returned {len(bindings)} results",
                    {"query_type": "SELECT", "method": "POST", "result_count": len(bindings)}
                )
                return True
            else:
                self.log_test_result(
                    "SPARQL SELECT Query (POST)",
                    False,
                    "Query failed or returned invalid response",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "SPARQL SELECT Query (POST)",
                False,
                f"Exception during query execution: {e}",
                {"exception": str(e)}
            )
            return False
    
    async def test_sparql_ask_query(self) -> bool:
        """Test SPARQL ASK query."""
        try:
            # ASK query to check if any data exists
            query = f"""
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            
            ASK {{
                GRAPH <{self.graph_id}> {{
                    ?person a foaf:Person .
                }}
            }}
            """
            
            response = await self.endpoint.sparql_query_post(
                space_id=self.space_id,
                query=query
            )
            
            if response and hasattr(response, 'boolean'):
                self.log_test_result(
                    "SPARQL ASK Query",
                    True,
                    f"ASK query executed successfully, result: {response.boolean}",
                    {"query_type": "ASK", "result": response.boolean}
                )
                return True
            else:
                self.log_test_result(
                    "SPARQL ASK Query",
                    False,
                    "ASK query failed or returned invalid response",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "SPARQL ASK Query",
                False,
                f"Exception during ASK query: {e}",
                {"exception": str(e)}
            )
            return False
    
    async def test_sparql_construct_query(self) -> bool:
        """Test SPARQL CONSTRUCT query."""
        try:
            # CONSTRUCT query to build new triples
            query = f"""
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            PREFIX ex: <http://example.org/>
            
            CONSTRUCT {{
                ?person ex:hasName ?name .
                ?person ex:isTestPerson true .
            }}
            WHERE {{
                GRAPH <{self.graph_id}> {{
                    ?person a foaf:Person .
                    ?person foaf:name ?name .
                }}
            }} LIMIT 5
            """
            
            response = await self.endpoint.sparql_query_post(
                space_id=self.space_id,
                query=query
            )
            
            if response:
                self.log_test_result(
                    "SPARQL CONSTRUCT Query",
                    True,
                    "CONSTRUCT query executed successfully",
                    {"query_type": "CONSTRUCT", "response_type": type(response).__name__}
                )
                return True
            else:
                self.log_test_result(
                    "SPARQL CONSTRUCT Query",
                    False,
                    "CONSTRUCT query failed or returned no response",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "SPARQL CONSTRUCT Query",
                False,
                f"Exception during CONSTRUCT query: {e}",
                {"exception": str(e)}
            )
            return False
    
    async def run_all_query_tests(self) -> Dict[str, Any]:
        """Run all SPARQL query tests."""
        self.logger.info("🧪 Starting SPARQL Query Tests")
        
        tests = [
            self.test_sparql_select_query_get,
            self.test_sparql_select_query_post,
            self.test_sparql_ask_query,
            self.test_sparql_construct_query
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
        
        self.logger.info(f"🧪 SPARQL Query Tests Complete: {passed}/{total} passed ({success_rate:.1f}%)")
        
        return {
            "all_passed": passed == total,
            "passed_tests": passed,
            "total_tests": total,
            "success_rate": success_rate,
            "test_results": self.test_results
        }


def create_sparql_query_tester(endpoint, space_id: str, graph_id: str, logger: Optional[logging.Logger] = None) -> SPARQLQueryTester:
    """Factory function to create SPARQLQueryTester instance."""
    return SPARQLQueryTester(endpoint, space_id, graph_id, logger)
