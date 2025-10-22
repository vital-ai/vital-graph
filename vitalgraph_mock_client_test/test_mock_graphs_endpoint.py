#!/usr/bin/env python3
"""
Test script for MockGraphsEndpoint with VitalSigns native functionality.

This script demonstrates:
- VitalSigns native object creation and conversion
- pyoxigraph in-memory SPARQL quad store operations for graphs
- Complete graph lifecycle: create, list, get info, clear, drop
- Real SPARQL operations (CREATE GRAPH, DROP GRAPH, CLEAR GRAPH)
- Comprehensive error handling and edge cases
- Graph triple counting and metadata management
"""

import sys
import json
from pathlib import Path
from typing import Dict, Any, List

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.mock.client.endpoint.mock_graphs_endpoint import MockGraphsEndpoint
from vitalgraph.mock.client.space.mock_space_manager import MockSpaceManager
from vitalgraph.model.sparql_model import GraphInfo, SPARQLGraphResponse
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.VITAL_Node import VITAL_Node


class TestMockGraphsEndpoint:
    """Test suite for MockGraphsEndpoint."""
    
    def __init__(self):
        """Initialize test suite."""
        self.space_manager = MockSpaceManager()
        self.endpoint = MockGraphsEndpoint(client=None, space_manager=self.space_manager)
        self.test_results = []
        self.test_space_id = "test-graphs-space"
        self.created_graphs = []  # Track created graphs for cleanup
        
        # Create test space
        self.space_manager.create_space(self.test_space_id)
    
    def log_test_result(self, test_name: str, success: bool, message: str, data: Dict[str, Any] = None):
        """Log a test result."""
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}")
        print(f"    {message}")
        
        if data:
            print(f"    Data: {json.dumps(data, indent=2)}")
        
        self.test_results.append({
            "test_name": test_name,
            "success": success,
            "message": message,
            "data": data
        })
        print()
    
    def cleanup_all_graphs(self):
        """Clean up all graphs in the test space."""
        try:
            # Get all graphs and drop them
            graphs = self.endpoint.list_graphs(self.test_space_id)
            deleted_count = 0
            for graph in graphs:
                response = self.endpoint.drop_graph(self.test_space_id, graph.graph_uri, silent=True)
                if response.success:
                    deleted_count += 1
            
            print(f"🧹 Cleaned up {deleted_count} graphs")
            self.created_graphs.clear()
            
        except Exception as e:
            print(f"⚠️  Cleanup error: {e}")
    
    def add_test_data_to_graph(self, graph_uri: str) -> int:
        """Add some test triples to a graph and return the count."""
        try:
            space = self.space_manager.get_space(self.test_space_id)
            if not space:
                return 0
            
            # Add some test triples using SPARQL INSERT
            insert_query = f"""
            INSERT DATA {{
                GRAPH <{graph_uri}> {{
                    <http://example.org/person1> <http://example.org/name> "John Doe" .
                    <http://example.org/person1> <http://example.org/age> "30"^^<http://www.w3.org/2001/XMLSchema#integer> .
                    <http://example.org/person2> <http://example.org/name> "Jane Smith" .
                }}
            }}
            """
            
            # Execute the INSERT query
            result = space.update_sparql(insert_query)
            
            # Return the number of triples we attempted to insert
            return 3 if result.get("success", True) else 0
            
        except Exception as e:
            print(f"Error adding test data: {e}")
            return 0
    
    def test_list_graphs_empty(self):
        """Test listing graphs when no graphs exist."""
        try:
            graphs = self.endpoint.list_graphs(self.test_space_id)
            
            success = isinstance(graphs, list) and len(graphs) == 0
            
            self.log_test_result(
                "List Graphs (Empty)",
                success,
                f"Found {len(graphs)} graphs in empty space",
                {"graphs_count": len(graphs)}
            )
            
        except Exception as e:
            self.log_test_result("List Graphs (Empty)", False, f"Exception: {e}")
    
    def test_create_graph(self):
        """Test creating a new graph."""
        try:
            graph_uri = "http://example.org/test-graph-001"
            response = self.endpoint.create_graph(self.test_space_id, graph_uri)
            
            success = (
                isinstance(response, SPARQLGraphResponse) and
                response.success
            )
            
            if success:
                self.created_graphs.append(graph_uri)
            
            self.log_test_result(
                "Create Graph",
                success,
                f"Created graph: {graph_uri}",
                {
                    "success": response.success,
                    "message": response.message,
                    "operation_time": response.operation_time,
                    "graph_uri": graph_uri
                }
            )
            
            return graph_uri if success else None
            
        except Exception as e:
            self.log_test_result("Create Graph", False, f"Exception: {e}")
            return None
    
    def test_get_graph_info_empty(self, graph_uri: str):
        """Test getting info for an empty graph."""
        if not graph_uri:
            self.log_test_result("Get Graph Info (Empty)", False, "No graph URI provided")
            return
        
        try:
            graph_info = self.endpoint.get_graph_info(self.test_space_id, graph_uri)
            
            success = (
                isinstance(graph_info, GraphInfo) and
                graph_info.graph_uri == graph_uri and
                graph_info.triple_count == 0
            )
            
            self.log_test_result(
                "Get Graph Info (Empty)",
                success,
                f"Retrieved info for empty graph: {graph_uri}",
                {
                    "graph_uri": graph_info.graph_uri,
                    "triple_count": graph_info.triple_count,
                    "created_time": graph_info.created_time,
                    "updated_time": graph_info.updated_time
                }
            )
            
        except Exception as e:
            self.log_test_result("Get Graph Info (Empty)", False, f"Exception: {e}")
    
    def test_list_graphs_with_data(self):
        """Test listing graphs when graphs exist."""
        try:
            graphs = self.endpoint.list_graphs(self.test_space_id)
            
            success = isinstance(graphs, list) and len(graphs) > 0
            
            graphs_data = []
            if success:
                for graph in graphs:
                    graphs_data.append({
                        "graph_uri": graph.graph_uri,
                        "triple_count": graph.triple_count
                    })
            
            self.log_test_result(
                "List Graphs (With Data)",
                success,
                f"Found {len(graphs)} graphs in space",
                {"graphs_count": len(graphs), "graphs": graphs_data}
            )
            
        except Exception as e:
            self.log_test_result("List Graphs (With Data)", False, f"Exception: {e}")
    
    def test_add_data_to_graph(self, graph_uri: str):
        """Test adding data to a graph and verifying triple count."""
        if not graph_uri:
            self.log_test_result("Add Data to Graph", False, "No graph URI provided")
            return
        
        try:
            # Add test data to the graph
            added_count = self.add_test_data_to_graph(graph_uri)
            
            # Get updated graph info
            graph_info = self.endpoint.get_graph_info(self.test_space_id, graph_uri)
            
            success = (
                added_count > 0 and
                graph_info.triple_count >= added_count
            )
            
            self.log_test_result(
                "Add Data to Graph",
                success,
                f"Added {added_count} triples to graph, total count: {graph_info.triple_count}",
                {
                    "added_triples": added_count,
                    "total_triples": graph_info.triple_count,
                    "graph_uri": graph_uri
                }
            )
            
        except Exception as e:
            self.log_test_result("Add Data to Graph", False, f"Exception: {e}")
    
    def test_get_graph_info_with_data(self, graph_uri: str):
        """Test getting info for a graph with data."""
        if not graph_uri:
            self.log_test_result("Get Graph Info (With Data)", False, "No graph URI provided")
            return
        
        try:
            graph_info = self.endpoint.get_graph_info(self.test_space_id, graph_uri)
            
            success = (
                isinstance(graph_info, GraphInfo) and
                graph_info.graph_uri == graph_uri and
                graph_info.triple_count > 0
            )
            
            self.log_test_result(
                "Get Graph Info (With Data)",
                success,
                f"Retrieved info for graph with {graph_info.triple_count} triples",
                {
                    "graph_uri": graph_info.graph_uri,
                    "triple_count": graph_info.triple_count,
                    "created_time": graph_info.created_time,
                    "updated_time": graph_info.updated_time
                }
            )
            
        except Exception as e:
            self.log_test_result("Get Graph Info (With Data)", False, f"Exception: {e}")
    
    def test_clear_graph(self, graph_uri: str):
        """Test clearing a graph (removing all triples but keeping the graph)."""
        if not graph_uri:
            self.log_test_result("Clear Graph", False, "No graph URI provided")
            return
        
        try:
            response = self.endpoint.clear_graph(self.test_space_id, graph_uri)
            
            success = (
                isinstance(response, SPARQLGraphResponse) and
                response.success
            )
            
            # Verify graph is cleared by checking triple count
            if success:
                graph_info = self.endpoint.get_graph_info(self.test_space_id, graph_uri)
                success = success and graph_info.triple_count == 0
            
            self.log_test_result(
                "Clear Graph",
                success,
                f"Cleared graph: {graph_uri}",
                {
                    "success": response.success,
                    "message": response.message,
                    "operation_time": response.operation_time,
                    "graph_uri": graph_uri
                }
            )
            
        except Exception as e:
            self.log_test_result("Clear Graph", False, f"Exception: {e}")
    
    def test_drop_graph(self, graph_uri: str):
        """Test dropping (deleting) a graph."""
        if not graph_uri:
            self.log_test_result("Drop Graph", False, "No graph URI provided")
            return
        
        try:
            response = self.endpoint.drop_graph(self.test_space_id, graph_uri)
            
            success = (
                isinstance(response, SPARQLGraphResponse) and
                response.success
            )
            
            if success and graph_uri in self.created_graphs:
                self.created_graphs.remove(graph_uri)
            
            self.log_test_result(
                "Drop Graph",
                success,
                f"Dropped graph: {graph_uri}",
                {
                    "success": response.success,
                    "message": response.message,
                    "operation_time": response.operation_time,
                    "graph_uri": graph_uri
                }
            )
            
        except Exception as e:
            self.log_test_result("Drop Graph", False, f"Exception: {e}")
    
    def test_create_multiple_graphs(self):
        """Test creating multiple graphs."""
        try:
            graph_uris = [
                "http://example.org/batch-graph-001",
                "http://example.org/batch-graph-002",
                "http://example.org/batch-graph-003"
            ]
            
            created_graphs = []
            for graph_uri in graph_uris:
                response = self.endpoint.create_graph(self.test_space_id, graph_uri)
                if response.success:
                    created_graphs.append(graph_uri)
                    self.created_graphs.append(graph_uri)
            
            success = len(created_graphs) == len(graph_uris)
            
            self.log_test_result(
                "Create Multiple Graphs",
                success,
                f"Created {len(created_graphs)} of {len(graph_uris)} graphs",
                {"created_graphs": created_graphs, "total_requested": len(graph_uris)}
            )
            
            return created_graphs
            
        except Exception as e:
            self.log_test_result("Create Multiple Graphs", False, f"Exception: {e}")
            return []
    
    def test_drop_multiple_graphs(self, graph_uris: List[str]):
        """Test dropping multiple graphs."""
        if not graph_uris:
            self.log_test_result("Drop Multiple Graphs", False, "No graph URIs provided")
            return
        
        try:
            dropped_count = 0
            for graph_uri in graph_uris:
                response = self.endpoint.drop_graph(self.test_space_id, graph_uri)
                if response.success:
                    dropped_count += 1
                    if graph_uri in self.created_graphs:
                        self.created_graphs.remove(graph_uri)
            
            success = dropped_count > 0
            
            self.log_test_result(
                "Drop Multiple Graphs",
                success,
                f"Dropped {dropped_count} of {len(graph_uris)} graphs",
                {"dropped_count": dropped_count, "total_requested": len(graph_uris)}
            )
            
        except Exception as e:
            self.log_test_result("Drop Multiple Graphs", False, f"Exception: {e}")
    
    def test_error_handling_nonexistent_space(self):
        """Test error handling with nonexistent space."""
        try:
            # Test with nonexistent space
            graphs = self.endpoint.list_graphs("nonexistent-space-12345")
            
            success = isinstance(graphs, list) and len(graphs) == 0
            
            self.log_test_result(
                "Error Handling (Nonexistent Space)",
                success,
                "Gracefully handled nonexistent space request",
                {"graphs_count": len(graphs)}
            )
            
        except Exception as e:
            self.log_test_result("Error Handling (Nonexistent Space)", False, f"Exception: {e}")
    
    def test_get_info_nonexistent_graph(self):
        """Test getting info for a nonexistent graph."""
        try:
            graph_uri = "http://example.org/nonexistent-graph-12345"
            graph_info = self.endpoint.get_graph_info(self.test_space_id, graph_uri)
            
            success = (
                isinstance(graph_info, GraphInfo) and
                graph_info.graph_uri == graph_uri and
                graph_info.triple_count == 0
            )
            
            self.log_test_result(
                "Get Info Nonexistent Graph",
                success,
                f"Handled nonexistent graph gracefully",
                {
                    "graph_uri": graph_info.graph_uri,
                    "triple_count": graph_info.triple_count
                }
            )
            
        except Exception as e:
            self.log_test_result("Get Info Nonexistent Graph", False, f"Exception: {e}")
    
    def test_create_graph_nonexistent_space(self):
        """Test creating a graph in a nonexistent space."""
        try:
            graph_uri = "http://example.org/test-graph-bad-space"
            response = self.endpoint.create_graph("nonexistent-space-12345", graph_uri)
            
            success = (
                isinstance(response, SPARQLGraphResponse) and
                not response.success and
                "not found" in response.message.lower()
            )
            
            self.log_test_result(
                "Create Graph Nonexistent Space",
                success,
                f"Handled nonexistent space gracefully",
                {
                    "success": response.success,
                    "message": response.message
                }
            )
            
        except Exception as e:
            self.log_test_result("Create Graph Nonexistent Space", False, f"Exception: {e}")
    
    def test_drop_nonexistent_graph(self):
        """Test dropping a nonexistent graph."""
        try:
            graph_uri = "http://example.org/nonexistent-graph-drop"
            response = self.endpoint.drop_graph(self.test_space_id, graph_uri)
            
            # This might succeed or fail depending on implementation
            # Both are valid behaviors for dropping nonexistent graphs
            success = isinstance(response, SPARQLGraphResponse)
            
            self.log_test_result(
                "Drop Nonexistent Graph",
                success,
                f"Handled nonexistent graph drop",
                {
                    "success": response.success,
                    "message": response.message
                }
            )
            
        except Exception as e:
            self.log_test_result("Drop Nonexistent Graph", False, f"Exception: {e}")
    
    def test_drop_graph_silent(self):
        """Test dropping a nonexistent graph with silent flag."""
        try:
            graph_uri = "http://example.org/nonexistent-graph-silent"
            response = self.endpoint.drop_graph(self.test_space_id, graph_uri, silent=True)
            
            # Silent drop should always succeed
            success = (
                isinstance(response, SPARQLGraphResponse) and
                response.success
            )
            
            self.log_test_result(
                "Drop Graph Silent",
                success,
                f"Silent drop handled gracefully",
                {
                    "success": response.success,
                    "message": response.message
                }
            )
            
        except Exception as e:
            self.log_test_result("Drop Graph Silent", False, f"Exception: {e}")
    
    def test_clear_nonexistent_graph(self):
        """Test clearing a nonexistent graph."""
        try:
            graph_uri = "http://example.org/nonexistent-graph-clear"
            response = self.endpoint.clear_graph(self.test_space_id, graph_uri)
            
            # This might succeed or fail depending on implementation
            success = isinstance(response, SPARQLGraphResponse)
            
            self.log_test_result(
                "Clear Nonexistent Graph",
                success,
                f"Handled nonexistent graph clear",
                {
                    "success": response.success,
                    "message": response.message
                }
            )
            
        except Exception as e:
            self.log_test_result("Clear Nonexistent Graph", False, f"Exception: {e}")

    def run_all_tests(self):
        """Run complete test suite."""
        print("MockGraphsEndpoint Test Suite")
        print("=" * 50)
        
        # Test 1: Initial empty state
        self.test_list_graphs_empty()
        
        # Test 2-6: Basic graph lifecycle
        graph_uri = self.test_create_graph()
        self.test_get_graph_info_empty(graph_uri)
        self.test_add_data_to_graph(graph_uri)
        self.test_get_graph_info_with_data(graph_uri)
        self.test_list_graphs_with_data()
        
        # Test 7-8: Graph operations
        self.test_clear_graph(graph_uri)
        
        # Test 9-10: Multiple graph operations
        batch_graph_uris = self.test_create_multiple_graphs()
        self.test_drop_multiple_graphs(batch_graph_uris)
        
        # Test 11: Drop the original graph
        if graph_uri:
            self.test_drop_graph(graph_uri)
        
        # Test 12-18: Error handling and edge cases
        self.test_error_handling_nonexistent_space()
        self.test_get_info_nonexistent_graph()
        self.test_create_graph_nonexistent_space()
        self.test_drop_nonexistent_graph()
        self.test_drop_graph_silent()
        self.test_clear_nonexistent_graph()
        
        # Clean up any remaining graphs before final test
        self.cleanup_all_graphs()
        
        # Test 19: Final verification - should be empty now
        self.test_list_graphs_empty()
        
        # Summary
        print("=" * 50)
        passed = sum(1 for result in self.test_results if result["success"])
        total = len(self.test_results)
        print(f"Test Results: {passed}/{total} tests passed")
        
        if passed == total:
            print("🎉 All tests passed!")
        else:
            print("⚠️  Some tests failed. Check the output above for details.")
        
        return passed == total


def main():
    """Run the test suite."""
    test_suite = TestMockGraphsEndpoint()
    success = test_suite.run_all_tests()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
