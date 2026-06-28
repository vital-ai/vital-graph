"""
SPARQL Insert Test Case

Tests SPARQL insert operations via REST API endpoints:
- POST /api/graphs/sparql/insert?space_id=
- POST /api/graphs/sparql/insert-form?space_id=
- POST /api/graphs/sparql/insert-data?space_id=

Tests various SPARQL INSERT operations including INSERT DATA and INSERT WHERE patterns.
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class SPARQLInsertTester:
    """Test case for SPARQL insert operations."""
    
    def __init__(self, endpoint, space_id: str, graph_id: str, logger: Optional[logging.Logger] = None):
        """
        Initialize SPARQL insert tester.
        
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
        self.inserted_uris = []
        
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
    
    async def test_sparql_insert_data(self) -> bool:
        """Test SPARQL INSERT DATA operation."""
        try:
            timestamp = datetime.now().isoformat()
            person_uri = f"http://example.org/person/test_{timestamp.replace(':', '_').replace('.', '_')}"
            self.inserted_uris.append(person_uri)
            
            # INSERT DATA operation
            insert_query = f"""
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            PREFIX ex: <http://example.org/>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            
            INSERT DATA {{
                GRAPH <{self.graph_id}> {{
                    <{person_uri}> a foaf:Person .
                    <{person_uri}> foaf:name "Test Person Insert Data" .
                    <{person_uri}> foaf:age 30 .
                    <{person_uri}> ex:testType "insert_data" .
                    <{person_uri}> vital:hasCreatedTime "{timestamp}" .
                }}
            }}
            """
            
            response = await self.endpoint.sparql_insert_data(
                space_id=self.space_id,
                data=insert_query
            )
            
            if response and hasattr(response, 'success') and response.success:
                self.log_test_result(
                    "SPARQL INSERT DATA",
                    True,
                    "INSERT DATA operation executed successfully",
                    {"operation": "INSERT DATA", "uri": person_uri}
                )
                return True
            else:
                self.log_test_result(
                    "SPARQL INSERT DATA",
                    False,
                    "INSERT DATA operation failed",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "SPARQL INSERT DATA",
                False,
                f"Exception during INSERT DATA operation: {e}",
                {"exception": str(e)}
            )
            return False
    
    async def test_sparql_insert_post(self) -> bool:
        """Test SPARQL INSERT via POST method."""
        try:
            timestamp = datetime.now().isoformat()
            person_uri = f"http://example.org/person/insert_{timestamp.replace(':', '_').replace('.', '_')}"
            self.inserted_uris.append(person_uri)
            
            # INSERT WHERE operation
            insert_query = f"""
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            PREFIX ex: <http://example.org/>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            
            INSERT {{
                GRAPH <{self.graph_id}> {{
                    <{person_uri}> a foaf:Person .
                    <{person_uri}> foaf:name ?derivedName .
                    <{person_uri}> ex:testType "insert_where" .
                    <{person_uri}> vital:hasCreatedTime "{timestamp}" .
                }}
            }}
            WHERE {{
                BIND("Test Person Insert Where" AS ?derivedName)
            }}
            """
            
            response = await self.endpoint.sparql_insert_post(
                space_id=self.space_id,
                insert=insert_query
            )
            
            if response and hasattr(response, 'success') and response.success:
                self.log_test_result(
                    "SPARQL INSERT (POST)",
                    True,
                    "INSERT WHERE operation executed successfully",
                    {"operation": "INSERT WHERE", "uri": person_uri}
                )
                return True
            else:
                self.log_test_result(
                    "SPARQL INSERT (POST)",
                    False,
                    "INSERT WHERE operation failed",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "SPARQL INSERT (POST)",
                False,
                f"Exception during INSERT WHERE operation: {e}",
                {"exception": str(e)}
            )
            return False
    
    async def test_sparql_insert_form(self) -> bool:
        """Test SPARQL INSERT via form submission."""
        try:
            timestamp = datetime.now().isoformat()
            person_uri = f"http://example.org/person/form_{timestamp.replace(':', '_').replace('.', '_')}"
            self.inserted_uris.append(person_uri)
            
            # INSERT operation via form
            insert_query = f"""
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            PREFIX ex: <http://example.org/>
            
            INSERT DATA {{
                GRAPH <{self.graph_id}> {{
                    <{person_uri}> a foaf:Person .
                    <{person_uri}> foaf:name "Test Person Form Insert" .
                    <{person_uri}> foaf:age 25 .
                    <{person_uri}> ex:testType "insert_form" .
                }}
            }}
            """
            
            response = await self.endpoint.sparql_insert_form(
                space_id=self.space_id,
                insert=insert_query
            )
            
            if response and hasattr(response, 'success') and response.success:
                self.log_test_result(
                    "SPARQL INSERT (Form)",
                    True,
                    "INSERT operation via form executed successfully",
                    {"operation": "INSERT DATA", "method": "FORM", "uri": person_uri}
                )
                return True
            else:
                self.log_test_result(
                    "SPARQL INSERT (Form)",
                    False,
                    "INSERT operation via form failed",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "SPARQL INSERT (Form)",
                False,
                f"Exception during form INSERT operation: {e}",
                {"exception": str(e)}
            )
            return False
    
    async def test_complex_insert_operation(self) -> bool:
        """Test complex SPARQL INSERT with multiple patterns."""
        try:
            timestamp = datetime.now().isoformat()
            person_uri = f"http://example.org/person/complex_{timestamp.replace(':', '_').replace('.', '_')}"
            org_uri = f"http://example.org/org/test_{timestamp.replace(':', '_').replace('.', '_')}"
            self.inserted_uris.extend([person_uri, org_uri])
            
            # Complex INSERT with relationships
            insert_query = f"""
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            PREFIX ex: <http://example.org/>
            PREFIX org: <http://www.w3.org/ns/org#>
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            
            INSERT {{
                GRAPH <{self.graph_id}> {{
                    <{person_uri}> a foaf:Person .
                    <{person_uri}> foaf:name ?personName .
                    <{person_uri}> foaf:age ?age .
                    <{person_uri}> org:memberOf <{org_uri}> .
                    <{person_uri}> vital:hasCreatedTime "{timestamp}" .
                    
                    <{org_uri}> a org:Organization .
                    <{org_uri}> foaf:name ?orgName .
                    <{org_uri}> ex:testType "complex_insert" .
                    <{org_uri}> vital:hasCreatedTime "{timestamp}" .
                }}
            }}
            WHERE {{
                BIND("Complex Test Person" AS ?personName)
                BIND("Test Organization" AS ?orgName)
                BIND(40 AS ?age)
            }}
            """
            
            response = await self.endpoint.sparql_insert_post(
                space_id=self.space_id,
                insert=insert_query
            )
            
            if response and hasattr(response, 'success') and response.success:
                self.log_test_result(
                    "Complex SPARQL INSERT",
                    True,
                    "Complex INSERT operation executed successfully",
                    {"operation": "Complex INSERT with relationships", "person_uri": person_uri, "org_uri": org_uri}
                )
                return True
            else:
                self.log_test_result(
                    "Complex SPARQL INSERT",
                    False,
                    "Complex INSERT operation failed",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Complex SPARQL INSERT",
                False,
                f"Exception during complex INSERT operation: {e}",
                {"exception": str(e)}
            )
            return False
    
    async def run_all_insert_tests(self) -> Dict[str, Any]:
        """Run all SPARQL insert tests."""
        self.logger.info("🧪 Starting SPARQL Insert Tests")
        
        tests = [
            self.test_sparql_insert_data,
            self.test_sparql_insert_post,
            self.test_sparql_insert_form,
            self.test_complex_insert_operation
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
        
        self.logger.info(f"🧪 SPARQL Insert Tests Complete: {passed}/{total} passed ({success_rate:.1f}%)")
        
        return {
            "all_passed": passed == total,
            "passed_tests": passed,
            "total_tests": total,
            "success_rate": success_rate,
            "test_results": self.test_results,
            "inserted_uris": self.inserted_uris
        }


def create_sparql_insert_tester(endpoint, space_id: str, graph_id: str, logger: Optional[logging.Logger] = None) -> SPARQLInsertTester:
    """Factory function to create SPARQLInsertTester instance."""
    return SPARQLInsertTester(endpoint, space_id, graph_id, logger)
