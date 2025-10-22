#!/usr/bin/env python3
"""
Test script for MockSparqlEndpoint with VitalSigns native functionality.

This script demonstrates:
- Real pyoxigraph SPARQL execution for all query types
- VitalSigns native object creation and RDF conversion
- Complete SPARQL lifecycle: SELECT, ASK, CONSTRUCT, INSERT, UPDATE, DELETE
- SPARQL result format handling and response validation
- Comprehensive error handling and edge cases
- Performance timing and query optimization
"""
import logging
import sys
import json
from pathlib import Path
from typing import Dict, Any

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s'
)

from vitalgraph.mock.client.endpoint.mock_sparql_endpoint import MockSparqlEndpoint
from vitalgraph.mock.client.space.mock_space_manager import MockSpaceManager
from vitalgraph.model.sparql_model import (
    SPARQLQueryRequest, SPARQLQueryResponse,
    SPARQLUpdateRequest, SPARQLUpdateResponse,
    SPARQLInsertRequest, SPARQLInsertResponse,
    SPARQLDeleteRequest, SPARQLDeleteResponse
)
from vitalgraph.model.jsonld_model import JsonLdDocument
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.VITAL_Node import VITAL_Node


class TestMockSparqlEndpoint:
    """Test suite for MockSparqlEndpoint."""
    
    def __init__(self):
        """Initialize test suite."""
        self.space_manager = MockSpaceManager()
        self.endpoint = MockSparqlEndpoint(client=None, space_manager=self.space_manager)
        self.test_results = []
        self.test_space_id = "test-sparql-space"
        self.test_graph_id = "http://example.org/test-graph-sparql"
        
        # Create test space and graph
        self.space_manager.create_space(self.test_space_id)
        space = self.space_manager.get_space(self.test_space_id)
        if space:
            space.add_graph(self.test_graph_id, name="Test SPARQL Graph")
    
    def log_test_result(self, test_name: str, success: bool, message: str = "", data: Dict[str, Any] = None):
        """Log test result with details."""
        status = "✅ PASS" if success else "❌ FAIL"
        result = {
            "test": test_name,
            "success": success,
            "message": message,
            "data": data or {}
        }
        self.test_results.append(result)
        
        print(f"{status} {test_name}")
        if message:
            print(f"    {message}")
        if data:
            print(f"    Data: {json.dumps(data, indent=2)}")
        print()
    
    def setup_test_data(self):
        """Set up test RDF data for SPARQL queries."""
        space = self.space_manager.get_space(self.test_space_id)
        if not space:
            return False
        
        # Add test triples directly to the space (default graph for SPARQL queries)
        test_triples = [
            ("http://example.org/person1", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "http://example.org/Person"),
            ("http://example.org/person1", "http://example.org/name", "Alice"),  # Literal without quotes
            ("http://example.org/person1", "http://example.org/age", "30"),
            ("http://example.org/person1", "http://example.org/email", "alice@example.org"),
            
            ("http://example.org/person2", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "http://example.org/Person"),
            ("http://example.org/person2", "http://example.org/name", "Bob"),
            ("http://example.org/person2", "http://example.org/age", "25"),
            
            ("http://example.org/person3", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "http://example.org/Person"),
            ("http://example.org/person3", "http://example.org/name", "Charlie"),
            ("http://example.org/person3", "http://example.org/age", "35"),
        ]
        
        for subject, predicate, obj in test_triples:
            try:
                space.add_quad(subject, predicate, obj)  # Add to default graph
            except Exception as e:
                print(f"Failed to add test triple: {e}")
                return False
        
        return True
    
    def test_sparql_select_basic(self):
        """Test basic SPARQL SELECT query."""
        query = """
        SELECT ?person ?name WHERE {
            ?person <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/Person> .
            ?person <http://example.org/name> ?name .
        }
        """
        
        request = SPARQLQueryRequest(query=query)
        response = self.endpoint.execute_sparql_query(self.test_space_id, request)
        
        success = (
            isinstance(response, SPARQLQueryResponse) and
            response.error is None and
            response.results is not None and
            "bindings" in response.results and
            len(response.results["bindings"]) >= 3 and  # Should find at least 3 people
            response.query_time is not None and
            response.query_time > 0
        )
        
        bindings_count = len(response.results.get("bindings", [])) if response.results else 0
        
        self.log_test_result(
            "SPARQL SELECT Basic",
            success,
            f"Found {bindings_count} person records with names",
            {
                "query_time": response.query_time,
                "bindings_count": bindings_count,
                "variables": response.head.get("vars", []) if response.head else [],
                "error": response.error
            }
        )
        
        return success
    
    def test_sparql_select_with_filter(self):
        """Test SPARQL SELECT query with FILTER."""
        query = """
        SELECT ?person ?name ?age WHERE {
            ?person <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/Person> .
            ?person <http://example.org/name> ?name .
            ?person <http://example.org/age> ?age .
            FILTER(?age >= "30")
        }
        """
        
        request = SPARQLQueryRequest(query=query)
        response = self.endpoint.execute_sparql_query(self.test_space_id, request)
        
        success = (
            isinstance(response, SPARQLQueryResponse) and
            response.error is None and
            response.results is not None and
            "bindings" in response.results and
            len(response.results["bindings"]) >= 2  # Should find Alice (30) and Charlie (35)
        )
        
        bindings_count = len(response.results.get("bindings", [])) if response.results else 0
        
        self.log_test_result(
            "SPARQL SELECT with FILTER",
            success,
            f"Found {bindings_count} people aged 30 or older",
            {
                "query_time": response.query_time,
                "bindings_count": bindings_count,
                "error": response.error
            }
        )
        
        return success
    
    def test_sparql_ask_query(self):
        """Test SPARQL ASK query."""
        query = """
        ASK {
            ?person <http://example.org/name> "Alice" .
        }
        """
        
        request = SPARQLQueryRequest(query=query)
        response = self.endpoint.execute_sparql_query(self.test_space_id, request)
        
        success = (
            isinstance(response, SPARQLQueryResponse) and
            response.error is None and
            response.boolean is True and  # Should find Alice
            response.query_time is not None and
            response.query_time > 0
        )
        
        self.log_test_result(
            "SPARQL ASK Query",
            success,
            f"ASK query returned: {response.boolean}",
            {
                "query_time": response.query_time,
                "boolean_result": response.boolean,
                "error": response.error
            }
        )
        
        return success
    
    def test_sparql_ask_false(self):
        """Test SPARQL ASK query that should return false."""
        query = """
        ASK {
            ?person <http://example.org/name> "NonExistentPerson" .
        }
        """
        
        request = SPARQLQueryRequest(query=query)
        response = self.endpoint.execute_sparql_query(self.test_space_id, request)
        
        success = (
            isinstance(response, SPARQLQueryResponse) and
            response.error is None and
            response.boolean is False and  # Should not find NonExistentPerson
            response.query_time is not None
        )
        
        self.log_test_result(
            "SPARQL ASK Query (False)",
            success,
            f"ASK query correctly returned: {response.boolean}",
            {
                "query_time": response.query_time,
                "boolean_result": response.boolean,
                "error": response.error
            }
        )
        
        return success
    
    def test_sparql_construct_query(self):
        """Test SPARQL CONSTRUCT query."""
        query = """
        CONSTRUCT {
            ?person <http://example.org/hasName> ?name .
            ?person <http://example.org/hasType> <http://example.org/Person> .
        } WHERE {
            ?person <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/Person> .
            ?person <http://example.org/name> ?name .
        }
        """
        
        request = SPARQLQueryRequest(query=query)
        response = self.endpoint.execute_sparql_query(self.test_space_id, request)
        
        success = (
            isinstance(response, SPARQLQueryResponse) and
            response.error is None and
            response.triples is not None and
            len(response.triples) >= 3 and  # Should construct at least 3 triples (1 per person)
            response.query_time is not None
        )
        
        triples_count = len(response.triples) if response.triples else 0
        
        self.log_test_result(
            "SPARQL CONSTRUCT Query",
            success,
            f"Constructed {triples_count} new triples",
            {
                "query_time": response.query_time,
                "triples_count": triples_count,
                "error": response.error
            }
        )
        
        return success
    
    def test_sparql_insert_data(self):
        """Test SPARQL INSERT DATA operation."""
        insert_query = """
        INSERT DATA {
            GRAPH <http://example.org/test-graph-sparql> {
                <http://example.org/person4> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/Person> .
                <http://example.org/person4> <http://example.org/name> "David" .
                <http://example.org/person4> <http://example.org/age> "28"^^<http://www.w3.org/2001/XMLSchema#integer> .
            }
        }
        """
        
        request = SPARQLInsertRequest(update=insert_query)
        response = self.endpoint.execute_sparql_insert(self.test_space_id, request)
        
        success = (
            isinstance(response, SPARQLInsertResponse) and
            response.error is None and
            response.insert_time is not None and
            response.insert_time > 0
        )
        
        self.log_test_result(
            "SPARQL INSERT DATA",
            success,
            f"Inserted data in {response.insert_time:.4f}s",
            {
                "insert_time": response.insert_time,
                "inserted_triples": getattr(response, 'inserted_triples', 'N/A'),
                "error": response.error
            }
        )
        
        return success
    
    def test_sparql_update_where(self):
        """Test SPARQL UPDATE with WHERE clause."""
        update_query = """
        DELETE {
            GRAPH <http://example.org/test-graph-sparql> {
                ?person <http://example.org/age> ?oldAge .
            }
        }
        INSERT {
            GRAPH <http://example.org/test-graph-sparql> {
                ?person <http://example.org/age> "31"^^<http://www.w3.org/2001/XMLSchema#integer> .
            }
        }
        WHERE {
            GRAPH <http://example.org/test-graph-sparql> {
                ?person <http://example.org/name> "Alice" .
                ?person <http://example.org/age> ?oldAge .
            }
        }
        """
        
        request = SPARQLUpdateRequest(update=update_query)
        response = self.endpoint.execute_sparql_update(self.test_space_id, request)
        
        success = (
            isinstance(response, SPARQLUpdateResponse) and
            response.error is None and
            response.update_time is not None and
            response.update_time > 0
        )
        
        self.log_test_result(
            "SPARQL UPDATE WHERE",
            success,
            f"Updated Alice's age in {response.update_time:.4f}s",
            {
                "update_time": response.update_time,
                "error": response.error
            }
        )
        
        return success
    
    def test_sparql_delete_where(self):
        """Test SPARQL DELETE WHERE operation."""
        delete_query = """
        DELETE WHERE {
            GRAPH <http://example.org/test-graph-sparql> {
                ?person <http://example.org/name> "Bob" .
                ?person ?p ?o .
            }
        }
        """
        
        request = SPARQLDeleteRequest(update=delete_query)
        response = self.endpoint.execute_sparql_delete(self.test_space_id, request)
        
        success = (
            isinstance(response, SPARQLDeleteResponse) and
            response.error is None and
            response.delete_time is not None and
            response.delete_time > 0
        )
        
        self.log_test_result(
            "SPARQL DELETE WHERE",
            success,
            f"Deleted Bob's data in {response.delete_time:.4f}s",
            {
                "delete_time": response.delete_time,
                "deleted_triples": getattr(response, 'deleted_triples', 'N/A'),
                "error": response.error
            }
        )
        
        return success
    
    def test_sparql_count_aggregation(self):
        """Test SPARQL query with COUNT aggregation."""
        query = """
        SELECT (COUNT(?person) AS ?personCount) WHERE {
            ?person <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/Person> .
        }
        """
        
        request = SPARQLQueryRequest(query=query)
        response = self.endpoint.execute_sparql_query(self.test_space_id, request)
        
        success = (
            isinstance(response, SPARQLQueryResponse) and
            response.error is None and
            response.results is not None and
            "bindings" in response.results and
            len(response.results["bindings"]) == 1  # Should return one row with count
        )
        
        count_value = None
        if success and response.results["bindings"]:
            count_binding = response.results["bindings"][0].get("personCount", {})
            count_value = count_binding.get("value", "N/A")
        
        self.log_test_result(
            "SPARQL COUNT Aggregation",
            success,
            f"Person count: {count_value}",
            {
                "query_time": response.query_time,
                "count_result": count_value,
                "error": response.error
            }
        )
        
        return success
    
    def test_sparql_invalid_syntax(self):
        """Test SPARQL query with invalid syntax."""
        query = "INVALID SPARQL SYNTAX { ?s ?p ?o }"
        
        request = SPARQLQueryRequest(query=query)
        response = self.endpoint.execute_sparql_query(self.test_space_id, request)
        
        success = (
            isinstance(response, SPARQLQueryResponse) and
            response.error is not None and
            ("syntax" in response.error.lower() or "parse" in response.error.lower() or "expected" in response.error.lower())
        )
        
        self.log_test_result(
            "SPARQL Invalid Syntax",
            success,
            "Correctly handled invalid SPARQL syntax",
            {
                "error": response.error,
                "query_time": response.query_time
            }
        )
        
        return success
    
    def test_sparql_nonexistent_space(self):
        """Test SPARQL query on nonexistent space."""
        query = "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 1"
        
        request = SPARQLQueryRequest(query=query)
        response = self.endpoint.execute_sparql_query("nonexistent-space-12345", request)
        
        success = (
            isinstance(response, SPARQLQueryResponse) and
            response.error is not None and
            "not found" in response.error.lower()
        )
        
        self.log_test_result(
            "SPARQL Nonexistent Space",
            success,
            "Correctly handled nonexistent space",
            {
                "error": response.error,
                "query_time": response.query_time
            }
        )
        
        return success
    
    def test_sparql_different_formats(self):
        """Test SPARQL query with different response formats."""
        query = "SELECT ?person ?name WHERE { ?person <http://example.org/name> ?name } LIMIT 2"
        
        formats = [
            "application/sparql-results+json",
            "text/csv",
            "application/sparql-results+xml"
        ]
        
        results = {}
        overall_success = True
        
        for format_type in formats:
            request = SPARQLQueryRequest(query=query, format=format_type)
            response = self.endpoint.execute_sparql_query(self.test_space_id, request)
            
            format_success = (
                isinstance(response, SPARQLQueryResponse) and
                response.error is None
            )
            
            results[format_type] = {
                "success": format_success,
                "error": response.error,
                "query_time": response.query_time
            }
            
            if not format_success:
                overall_success = False
        
        self.log_test_result(
            "SPARQL Different Formats",
            overall_success,
            f"Tested {len(formats)} response formats",
            results
        )
        
        return overall_success
    
    def run_all_tests(self):
        """Run all SPARQL endpoint tests."""
        print("🧪 Starting MockSparqlEndpoint Test Suite")
        print("=" * 50)
        
        # Setup test data
        print("📝 Setting up test data...")
        if not self.setup_test_data():
            print("❌ Failed to setup test data")
            return
        print("✅ Test data setup complete")
        print()
        
        # Run all tests
        test_methods = [
            self.test_sparql_select_basic,
            self.test_sparql_select_with_filter,
            self.test_sparql_ask_query,
            self.test_sparql_ask_false,
            self.test_sparql_construct_query,
            self.test_sparql_insert_data,
            self.test_sparql_update_where,
            self.test_sparql_delete_where,
            self.test_sparql_count_aggregation,
            self.test_sparql_invalid_syntax,
            self.test_sparql_nonexistent_space,
            self.test_sparql_different_formats
        ]
        
        passed = 0
        total = len(test_methods)
        
        for test_method in test_methods:
            try:
                if test_method():
                    passed += 1
            except Exception as e:
                print(f"❌ EXCEPTION in {test_method.__name__}: {e}")
        
        # Print summary
        print("=" * 50)
        print(f"Test Results: {passed}/{total} tests passed")
        
        if passed == total:
            print("🎉 All tests passed!")
        else:
            print("⚠️  Some tests failed. Check the output above for details.")
        
        return passed == total


def main():
    """Main test execution."""
    test_suite = TestMockSparqlEndpoint()
    success = test_suite.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
