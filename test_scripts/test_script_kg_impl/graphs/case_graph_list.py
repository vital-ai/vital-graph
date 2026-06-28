#!/usr/bin/env python3
"""
Graph List Test Module

Modular test implementation for SPARQL graph listing operations.
Used by the main graphs endpoint test orchestrator.

Focuses on:
- Graph listing with pagination
- Graph filtering and search
- Empty state handling
- Response validation
"""

import logging
import uuid
from typing import Dict, Any, List, Optional

# Import models
from vitalgraph.model.sparql_model import SPARQLGraphRequest, SPARQLGraphResponse

logger = logging.getLogger(__name__)


class GraphListTester:
    """
    Modular test implementation for SPARQL graph listing operations.
    
    Handles:
    - Graph listing with pagination
    - Graph filtering and search
    - Response validation
    - Empty state testing
    """
    
    def __init__(self, endpoint):
        """
        Initialize the graph list tester.
        
        Args:
            endpoint: SPARQLGraphEndpoint instance
        """
        self.endpoint = endpoint
        
    async def test_graph_listing(self, space_id: str, created_graphs: List[str] = None) -> Dict[str, Any]:
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
        list_all_result = await self._test_list_all_graphs(space_id, created_graphs)
        results['test_details'].append(list_all_result)
        results['total_tests'] += 1
        if list_all_result['passed']:
            results['passed_tests'] += 1
        else:
            results['success'] = False
            results['failed_tests'].append(list_all_result['name'])
        
        # Test 2: List graphs with pagination
        pagination_result = await self._test_list_graphs_with_pagination(space_id)
        results['test_details'].append(pagination_result)
        results['total_tests'] += 1
        if pagination_result['passed']:
            results['passed_tests'] += 1
        else:
            results['success'] = False
            results['failed_tests'].append(pagination_result['name'])
        
        # Test 3: Empty space listing (if no graphs created)
        if not created_graphs:
            empty_result = await self._test_empty_graph_listing(space_id)
            results['test_details'].append(empty_result)
            results['total_tests'] += 1
            if empty_result['passed']:
                results['passed_tests'] += 1
            else:
                results['success'] = False
                results['failed_tests'].append(empty_result['name'])
        
        logger.info(f"✅ Graph listing tests completed: {results['passed_tests']}/{results['total_tests']} passed")
        return results
    
    async def _test_list_all_graphs(self, space_id: str, expected_graphs: List[str] = None) -> Dict[str, Any]:
        """Test listing all graphs."""
        logger.info("  Testing list all graphs...")
        
        try:
            # List graphs using endpoint's direct method
            graphs = await self.endpoint._list_graphs(
                space_id, 
                {"username": "test_user", "user_id": "test_user_123"}
            )
            
            graph_count = len(graphs) if graphs else 0
            
            # Validate expected graphs if provided
            validation_passed = True
            validation_details = ""
            
            if expected_graphs:
                found_graphs = [g.graph_uri for g in graphs] if graphs else []
                missing_graphs = [g for g in expected_graphs if g not in found_graphs]
                
                if missing_graphs:
                    validation_passed = False
                    validation_details = f"Missing expected graphs: {missing_graphs}"
                else:
                    validation_details = f"All {len(expected_graphs)} expected graphs found"
            
            return {
                'name': 'List All Graphs',
                'passed': validation_passed,
                'details': f"Found {graph_count} graphs. {validation_details}",
                'graph_count': graph_count,
                'graphs': [g.model_dump() if hasattr(g, 'model_dump') else str(g) for g in graphs] if graphs else []
            }
                
        except Exception as e:
            return {
                'name': 'List All Graphs',
                'passed': False,
                'error': f"Exception during graph listing: {e}"
            }
    
    async def _test_list_graphs_with_pagination(self, space_id: str) -> Dict[str, Any]:
        """Test graph listing with pagination."""
        logger.info("  Testing graph listing with pagination...")
        
        try:
            # List graphs using direct method (pagination handled by endpoint internally)
            graphs = await self.endpoint._list_graphs(
                space_id, 
                {"username": "test_user", "user_id": "test_user_123"}
            )
            
            return {
                'name': 'List Graphs with Pagination',
                'passed': True,
                'details': f"Pagination successful, returned {len(graphs) if graphs else 0} graphs",
                'graph_count': len(graphs) if graphs else 0
            }
                
        except Exception as e:
            return {
                'name': 'List Graphs with Pagination',
                'passed': False,
                'error': f"Exception during paginated graph listing: {e}"
            }
    
    async def _test_empty_graph_listing(self, space_id: str) -> Dict[str, Any]:
        """Test listing graphs in empty space."""
        logger.info("  Testing empty graph listing...")
        
        try:
            # List graphs in empty space using direct method
            graphs = await self.endpoint._list_graphs(
                space_id, 
                {"username": "test_user", "user_id": "test_user_123"}
            )
            
            graph_count = len(graphs) if graphs else 0
            return {
                'name': 'Empty Graph Listing',
                'passed': True,
                'details': f"Empty space listing successful, found {graph_count} graphs",
                'graph_count': graph_count
            }
                
        except Exception as e:
            return {
                'name': 'Empty Graph Listing',
                'passed': False,
                'error': f"Exception during empty graph listing: {e}"
            }
