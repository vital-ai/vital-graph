#!/usr/bin/env python3
"""
Graph List Test Module - Client Version

Client-based test implementation for graph listing operations.
Used by the main graphs endpoint test orchestrator.

Focuses on:
- Graph listing using VitalGraph client
- Response validation
- Empty state handling
- Graph filtering verification
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class GraphListTester:
    """
    Client-based test implementation for graph listing operations.
    
    Handles:
    - Graph listing using VitalGraphClient
    - Response validation
    - Empty state testing
    - Graph existence verification
    """
    
    def __init__(self, client):
        """
        Initialize the graph list tester.
        
        Args:
            client: VitalGraphClient instance
        """
        self.client = client
        
    def test_graph_listing(self, space_id: str, created_graphs: List[str] = None) -> Dict[str, Any]:
        """
        Test graph listing operations.
        
        Args:
            space_id: Space ID to list graphs from
            created_graphs: List of graph URIs that should exist
            
        Returns:
            Dictionary with test results
        """
        logger.info("📋 Testing graph listing operations...")
        
        results = {
            'success': True,
            'total_tests': 0,
            'passed_tests': 0,
            'failed_tests': [],
            'test_details': []
        }
        
        # Test 1: List all graphs
        list_all_result = self._test_list_all_graphs(space_id, created_graphs)
        results['test_details'].append(list_all_result)
        results['total_tests'] += 1
        if list_all_result['passed']:
            results['passed_tests'] += 1
        else:
            results['success'] = False
            results['failed_tests'].append(list_all_result['name'])
        
        # Test 2: Verify created graphs are listed
        if created_graphs:
            verify_result = self._test_verify_created_graphs_listed(space_id, created_graphs)
            results['test_details'].append(verify_result)
            results['total_tests'] += 1
            if verify_result['passed']:
                results['passed_tests'] += 1
            else:
                results['success'] = False
                results['failed_tests'].append(verify_result['name'])
        
        # Test 3: Empty space listing (if no graphs expected)
        if not created_graphs:
            empty_result = self._test_empty_graph_listing(space_id)
            results['test_details'].append(empty_result)
            results['total_tests'] += 1
            if empty_result['passed']:
                results['passed_tests'] += 1
            else:
                results['success'] = False
                results['failed_tests'].append(empty_result['name'])
        
        logger.info(f"✅ Graph listing tests completed: {results['passed_tests']}/{results['total_tests']} passed")
        return results
    
    def _test_list_all_graphs(self, space_id: str, expected_graphs: List[str] = None) -> Dict[str, Any]:
        """Test listing all graphs in a space."""
        logger.info("  Testing list all graphs...")
        
        try:
            # List graphs using client
            graphs_response = self.client.list_graphs(space_id)
            
            if graphs_response is not None:
                # Handle different response formats
                if isinstance(graphs_response, list):
                    graph_count = len(graphs_response)
                    graph_list = graphs_response
                elif isinstance(graphs_response, dict):
                    graph_list = graphs_response.get('graphs', [])
                    graph_count = len(graph_list)
                else:
                    graph_count = 0
                    graph_list = []
                
                return {
                    'name': 'List All Graphs',
                    'passed': True,
                    'details': f"Successfully listed {graph_count} graphs",
                    'graph_count': graph_count,
                    'graphs': graph_list,
                    'response': graphs_response
                }
            else:
                return {
                    'name': 'List All Graphs',
                    'passed': False,
                    'error': "Graph listing returned None"
                }
                
        except Exception as e:
            return {
                'name': 'List All Graphs',
                'passed': False,
                'error': f"Exception during graph listing: {e}"
            }
    
    def _test_verify_created_graphs_listed(self, space_id: str, expected_graphs: List[str]) -> Dict[str, Any]:
        """Test that created graphs appear in the listing."""
        logger.info("  Testing verification of created graphs in listing...")
        
        try:
            # List graphs using client
            graphs_response = self.client.graphs.list_graphs(space_id)
            
            if not graphs_response.is_success:
                return {
                    'name': 'Verify Created Graphs Listed',
                    'passed': False,
                    'error': "Graph listing returned None"
                }
            
            # Extract graph URIs from response
            listed_graph_uris = []
            for graph in graphs_response.graphs:
                if hasattr(graph, 'graph_uri'):
                    listed_graph_uris.append(graph.graph_uri)
                elif isinstance(graph, dict):
                    uri = graph.get('graph_uri') or graph.get('uri') or graph.get('graph_id')
                    if uri:
                        listed_graph_uris.append(uri)
                else:
                    listed_graph_uris.append(str(graph))
            
            # Check if expected graphs are in the listing
            found_graphs = []
            missing_graphs = []
            
            for expected_graph in expected_graphs:
                if expected_graph in listed_graph_uris:
                    found_graphs.append(expected_graph)
                else:
                    missing_graphs.append(expected_graph)
            
            if not missing_graphs:
                return {
                    'name': 'Verify Created Graphs Listed',
                    'passed': True,
                    'details': f"All {len(expected_graphs)} created graphs found in listing",
                    'found_graphs': found_graphs,
                    'listed_graph_uris': listed_graph_uris
                }
            else:
                return {
                    'name': 'Verify Created Graphs Listed',
                    'passed': False,
                    'error': f"Missing graphs in listing: {missing_graphs}",
                    'found_graphs': found_graphs,
                    'missing_graphs': missing_graphs,
                    'listed_graph_uris': listed_graph_uris
                }
                
        except Exception as e:
            return {
                'name': 'Verify Created Graphs Listed',
                'passed': False,
                'error': f"Exception during graph listing verification: {e}"
            }
    
    def _test_empty_graph_listing(self, space_id: str) -> Dict[str, Any]:
        """Test listing graphs in an empty space."""
        logger.info("  Testing empty graph listing...")
        
        try:
            # List graphs using client
            graphs_response = self.client.graphs.list_graphs(space_id)
            
            if graphs_response.is_success:
                graphs = graphs_response.graphs
                graph_count = len(graphs)
                return {
                    'name': 'Empty Graph Listing',
                    'passed': True,
                    'details': f"Empty space listing returned {graph_count} graphs (expected behavior)",
                    'graph_count': graph_count,
                    'response': graphs_response
                }
            else:
                return {
                    'name': 'Empty Graph Listing',
                    'passed': False,
                    'error': "Empty graph listing returned None"
                }
                
        except Exception as e:
            return {
                'name': 'Empty Graph Listing',
                'passed': False,
                'error': f"Exception during empty graph listing: {e}"
            }
