#!/usr/bin/env python3
"""
Test suite for MockVitalGraphClient graph operations.

This test suite validates the mock client's graph management functionality using:
- Direct client method calls (not endpoint calls)
- Proper request/response model validation
- Complete graph lifecycle operations (create, list, get info, clear, drop)
- Space creation as prerequisite for graph operations
- Error handling and edge cases
- Direct test runner format (no pytest dependency)
"""

import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any, List

# Add the parent directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.client.client_factory import create_vitalgraph_client
from vitalgraph.client.config.client_config_loader import VitalGraphClientConfig
from vitalgraph.model.spaces_model import Space, SpaceCreateResponse
from vitalgraph.model.sparql_model import GraphInfo, SPARQLGraphResponse
from vitalgraph.model.jsonld_model import JsonLdDocument


class TestMockClientGraphs:
    """Test suite for MockVitalGraphClient graph operations."""
    
    def __init__(self):
        """Initialize test suite."""
        # Configure logging to see debug output
        logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
        
        self.test_results = []
        self.client = None
        self.test_space_id = "test_graphs_space"
        self.created_graphs = []  # Track created graphs for cleanup
        
        # Create mock client config
        self.config = self._create_mock_config()
    
    def _create_mock_config(self) -> VitalGraphClientConfig:
        """Create a config object with mock client enabled."""
        config = VitalGraphClientConfig()
        
        # Override the config data to enable mock client
        config.config_data = {
            'server': {
                'url': 'http://localhost:8001',
                'api_base_path': '/api/v1'
            },
            'auth': {
                'username': 'admin',
                'password': 'admin'
            },
            'client': {
                'timeout': 30,
                'max_retries': 3,
                'retry_delay': 1,
                'use_mock_client': True,  # This enables the mock client
                'mock': {
                    'filePath': '/Users/hadfield/Local/vital-git/vital-graph/minioFiles'
                }
            }
        }
        config.config_path = "<programmatically created>"
        
        return config
    
    def log_test_result(self, test_name: str, success: bool, message: str, data: Dict[str, Any] = None):
        """Log test result in a consistent format."""
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}")
        if not success or data:
            print(f"    {message}")
            if data:
                print(f"    Data: {json.dumps(data, indent=2)}")
        print()
        
        self.test_results.append({
            "test_name": test_name,
            "success": success,
            "message": message,
            "data": data or {}
        })
    
    def test_client_initialization(self):
        """Test mock client initialization and connection."""
        try:
            # Create client using factory with config object
            self.client = create_vitalgraph_client(config=self.config)
            
            success = (
                self.client is not None and
                hasattr(self.client, 'list_graphs') and
                hasattr(self.client, 'create_graph') and
                hasattr(self.client, 'drop_graph') and
                hasattr(self.client, 'clear_graph') and
                hasattr(self.client, 'get_graph_info')
            )
            
            client_type = type(self.client).__name__
            
            self.log_test_result(
                "Client Initialization",
                success,
                f"Created client: {client_type}",
                {"client_type": client_type, "has_graph_methods": success}
            )
            
        except Exception as e:
            self.log_test_result("Client Initialization", False, f"Exception: {e}")
    
    def test_client_connection(self):
        """Test client connection management."""
        try:
            # Open connection
            self.client.open()
            is_connected_after_open = self.client.is_connected()
            
            # Get server info
            server_info = self.client.get_server_info()
            
            success = (
                is_connected_after_open and
                isinstance(server_info, dict) and
                ('name' in server_info or 'mock' in server_info)
            )
            
            server_name = server_info.get('name', 'Mock Server' if server_info.get('mock') else 'Unknown')
            
            self.log_test_result(
                "Client Connection",
                success,
                f"Connected: {is_connected_after_open}, Server: {server_name}",
                {
                    "connected": is_connected_after_open,
                    "server_name": server_name,
                    "is_mock": server_info.get('mock', False)
                }
            )
            
        except Exception as e:
            self.log_test_result("Client Connection", False, f"Exception: {e}")
    
    def test_create_test_space(self):
        """Test creating a test space for graph operations."""
        try:
            # Create test space (required for graph operations)
            test_space = Space(
                space=self.test_space_id,
                space_name="Test Graphs Space",
                space_description="A test space for graph operations testing"
            )
            
            response = self.client.add_space(test_space)
            
            success = (
                isinstance(response, SpaceCreateResponse) and
                response.created_count > 0
            )
            
            self.log_test_result(
                "Create Test Space",
                success,
                f"Created space: {self.test_space_id}",
                {
                    "space_id": self.test_space_id,
                    "created_count": response.created_count,
                    "message": response.message,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Create Test Space", False, f"Exception: {e}")
    
    def test_list_graphs_empty(self):
        """Test listing graphs when no graphs exist in the space."""
        try:
            graphs = self.client.list_graphs(self.test_space_id)
            
            success = isinstance(graphs, list) and len(graphs) == 0
            
            self.log_test_result(
                "List Graphs (Empty)",
                success,
                f"Found {len(graphs)} graphs in empty space",
                {
                    "graphs_count": len(graphs),
                    "response_type": type(graphs).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("List Graphs (Empty)", False, f"Exception: {e}")
    
    def test_create_graph(self):
        """Test creating a new graph."""
        try:
            graph_uri = "http://example.org/test-graph-001"
            response = self.client.create_graph(self.test_space_id, graph_uri)
            
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
                    "graph_uri": graph_uri,
                    "success": response.success,
                    "message": response.message,
                    "operation_time": response.operation_time,
                    "response_type": type(response).__name__
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
            graph_info = self.client.get_graph_info(self.test_space_id, graph_uri)
            
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
                    "updated_time": graph_info.updated_time,
                    "response_type": type(graph_info).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Get Graph Info (Empty)", False, f"Exception: {e}")
    
    def test_list_graphs_with_data(self):
        """Test listing graphs when graphs exist."""
        try:
            graphs = self.client.list_graphs(self.test_space_id)
            
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
                {
                    "graphs_count": len(graphs),
                    "graphs": graphs_data,
                    "response_type": type(graphs).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("List Graphs (With Data)", False, f"Exception: {e}")
    
    def test_add_data_to_graph(self, graph_uri: str):
        """Test adding data to a graph using triples."""
        if not graph_uri:
            self.log_test_result("Add Data to Graph", False, "No graph URI provided")
            return
        
        try:
            # Create test data as JSON-LD using VitalSigns compatible types
            test_data = JsonLdDocument(
                context={
                    "@vocab": "http://vital.ai/ontology/vital-core#",
                    "vital-core": "http://vital.ai/ontology/vital-core#"
                },
                graph=[
                    {
                        "@id": "http://example.org/node1",
                        "@type": "http://vital.ai/ontology/vital-core#VITAL_Node",
                        "vital-core:hasName": "Test Node 1"
                    },
                    {
                        "@id": "http://example.org/node2",
                        "@type": "http://vital.ai/ontology/vital-core#VITAL_Node",
                        "vital-core:hasName": "Test Node 2"
                    }
                ]
            )
            
            # Add triples to the graph
            response = self.client.add_triples(self.test_space_id, graph_uri, test_data)
            
            # Get updated graph info to verify triple count
            graph_info = self.client.get_graph_info(self.test_space_id, graph_uri)
            
            success = (
                hasattr(response, 'success') and
                graph_info.triple_count > 0
            )
            
            self.log_test_result(
                "Add Data to Graph",
                success,
                f"Added data to graph, total triples: {graph_info.triple_count}",
                {
                    "graph_uri": graph_uri,
                    "total_triples": graph_info.triple_count,
                    "add_response_type": type(response).__name__,
                    "graph_info_type": type(graph_info).__name__
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
            graph_info = self.client.get_graph_info(self.test_space_id, graph_uri)
            
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
            response = self.client.clear_graph(self.test_space_id, graph_uri)
            
            success = (
                isinstance(response, SPARQLGraphResponse) and
                response.success
            )
            
            # Verify graph is cleared by checking triple count
            if success:
                graph_info = self.client.get_graph_info(self.test_space_id, graph_uri)
                success = success and graph_info.triple_count == 0
            
            self.log_test_result(
                "Clear Graph",
                success,
                f"Cleared graph: {graph_uri}",
                {
                    "graph_uri": graph_uri,
                    "success": response.success,
                    "message": response.message,
                    "operation_time": response.operation_time,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Clear Graph", False, f"Exception: {e}")
    
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
                response = self.client.create_graph(self.test_space_id, graph_uri)
                if response.success:
                    created_graphs.append(graph_uri)
                    self.created_graphs.append(graph_uri)
            
            success = len(created_graphs) == len(graph_uris)
            
            self.log_test_result(
                "Create Multiple Graphs",
                success,
                f"Created {len(created_graphs)} of {len(graph_uris)} graphs",
                {
                    "created_graphs": created_graphs,
                    "total_requested": len(graph_uris),
                    "success_count": len(created_graphs)
                }
            )
            
            return created_graphs
            
        except Exception as e:
            self.log_test_result("Create Multiple Graphs", False, f"Exception: {e}")
            return []
    
    def test_drop_graph(self, graph_uri: str):
        """Test dropping (deleting) a graph."""
        if not graph_uri:
            self.log_test_result("Drop Graph", False, "No graph URI provided")
            return
        
        try:
            response = self.client.drop_graph(self.test_space_id, graph_uri)
            
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
                    "graph_uri": graph_uri,
                    "success": response.success,
                    "message": response.message,
                    "operation_time": response.operation_time,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Drop Graph", False, f"Exception: {e}")
    
    def test_drop_multiple_graphs(self, graph_uris: List[str]):
        """Test dropping multiple graphs."""
        if not graph_uris:
            self.log_test_result("Drop Multiple Graphs", False, "No graph URIs provided")
            return
        
        try:
            dropped_count = 0
            dropped_graphs = []
            
            for graph_uri in graph_uris:
                response = self.client.drop_graph(self.test_space_id, graph_uri)
                if response.success:
                    dropped_count += 1
                    dropped_graphs.append(graph_uri)
                    if graph_uri in self.created_graphs:
                        self.created_graphs.remove(graph_uri)
            
            success = dropped_count > 0
            
            self.log_test_result(
                "Drop Multiple Graphs",
                success,
                f"Dropped {dropped_count} of {len(graph_uris)} graphs",
                {
                    "dropped_graphs": dropped_graphs,
                    "dropped_count": dropped_count,
                    "total_requested": len(graph_uris)
                }
            )
            
        except Exception as e:
            self.log_test_result("Drop Multiple Graphs", False, f"Exception: {e}")
    
    def test_error_handling_nonexistent_space(self):
        """Test error handling with nonexistent space."""
        try:
            # Test with nonexistent space
            graphs = self.client.list_graphs("nonexistent_space_12345")
            
            success = isinstance(graphs, list) and len(graphs) == 0
            
            self.log_test_result(
                "Error Handling (Nonexistent Space)",
                success,
                "Gracefully handled nonexistent space request",
                {
                    "requested_space": "nonexistent_space_12345",
                    "graphs_count": len(graphs)
                }
            )
            
        except Exception as e:
            self.log_test_result("Error Handling (Nonexistent Space)", False, f"Exception: {e}")
    
    def test_get_info_nonexistent_graph(self):
        """Test getting info for a nonexistent graph."""
        try:
            graph_uri = "http://example.org/nonexistent-graph-12345"
            graph_info = self.client.get_graph_info(self.test_space_id, graph_uri)
            
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
            response = self.client.create_graph("nonexistent_space_12345", graph_uri)
            
            success = (
                isinstance(response, SPARQLGraphResponse) and
                not response.success and
                ("not found" in response.message.lower() or "error" in response.message.lower())
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
            response = self.client.drop_graph(self.test_space_id, graph_uri)
            
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
            response = self.client.drop_graph(self.test_space_id, graph_uri, silent=True)
            
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
            response = self.client.clear_graph(self.test_space_id, graph_uri)
            
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
    
    def test_list_graphs_after_operations(self):
        """Test listing graphs after all operations (should be empty or reduced)."""
        try:
            graphs = self.client.list_graphs(self.test_space_id)
            
            success = isinstance(graphs, list)
            
            self.log_test_result(
                "List Graphs (After Operations)",
                success,
                f"Found {len(graphs)} graphs after operations",
                {
                    "graphs_count": len(graphs),
                    "remaining_graphs": [g.graph_uri for g in graphs] if graphs else []
                }
            )
            
        except Exception as e:
            self.log_test_result("List Graphs (After Operations)", False, f"Exception: {e}")
    
    def test_client_disconnection(self):
        """Test client disconnection."""
        try:
            # Close connection
            self.client.close()
            is_connected_after_close = self.client.is_connected()
            
            success = not is_connected_after_close
            
            self.log_test_result(
                "Client Disconnection",
                success,
                f"Disconnected: {not is_connected_after_close}",
                {"connected": is_connected_after_close}
            )
            
        except Exception as e:
            self.log_test_result("Client Disconnection", False, f"Exception: {e}")
    
    def cleanup_remaining_graphs(self):
        """Clean up any remaining graphs."""
        try:
            cleanup_count = 0
            for graph_uri in self.created_graphs[:]:  # Copy list to avoid modification during iteration
                try:
                    response = self.client.drop_graph(self.test_space_id, graph_uri, silent=True)
                    if response.success:
                        cleanup_count += 1
                        self.created_graphs.remove(graph_uri)
                except:
                    pass  # Ignore cleanup errors
            
            if cleanup_count > 0:
                print(f"🧹 Cleaned up {cleanup_count} remaining graphs")
                
        except Exception as e:
            print(f"⚠️  Cleanup error: {e}")
    
    def run_all_tests(self):
        """Run all tests in sequence."""
        print("🧪 Testing MockVitalGraphClient Graph Operations")
        print("=" * 60)
        
        # Run tests in logical order
        self.test_client_initialization()
        self.test_client_connection()
        self.test_create_test_space()
        self.test_list_graphs_empty()
        
        # Basic graph lifecycle
        graph_uri = self.test_create_graph()
        self.test_get_graph_info_empty(graph_uri)
        self.test_list_graphs_with_data()
        self.test_add_data_to_graph(graph_uri)
        self.test_get_graph_info_with_data(graph_uri)
        self.test_clear_graph(graph_uri)
        
        # Multiple graph operations
        batch_graph_uris = self.test_create_multiple_graphs()
        self.test_drop_multiple_graphs(batch_graph_uris)
        
        # Drop the original graph
        if graph_uri:
            self.test_drop_graph(graph_uri)
        
        # Error handling and edge cases
        self.test_error_handling_nonexistent_space()
        self.test_get_info_nonexistent_graph()
        self.test_create_graph_nonexistent_space()
        self.test_drop_nonexistent_graph()
        self.test_drop_graph_silent()
        self.test_clear_nonexistent_graph()
        
        # Final verification
        self.test_list_graphs_after_operations()
        
        # Cleanup any remaining graphs
        self.cleanup_remaining_graphs()
        
        # Disconnect client
        self.test_client_disconnection()
        
        # Print summary
        print("=" * 60)
        passed = sum(1 for result in self.test_results if result["success"])
        total = len(self.test_results)
        
        if passed == total:
            print(f"Test Results: {passed}/{total} tests passed")
            print("🎉 All tests passed! MockVitalGraphClient graph operations are working correctly.")
        else:
            print(f"Test Results: {passed}/{total} tests passed")
            print("⚠️  Some tests failed. Check the output above for details.")
        
        return passed == total


def main():
    """Main test runner."""
    test_suite = TestMockClientGraphs()
    success = test_suite.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
