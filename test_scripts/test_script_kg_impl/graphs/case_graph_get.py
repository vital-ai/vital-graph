#!/usr/bin/env python3
"""
Graph Get Test Module

Modular test implementation for SPARQL graph retrieval operations.
Used by the main graphs endpoint test orchestrator.

Focuses on:
- Individual graph retrieval by URI
- Graph metadata validation
- Error handling for non-existent graphs
- Response validation
"""

import logging
import uuid
from typing import Dict, Any, List, Optional

# Import models
from vitalgraph.model.sparql_model import SPARQLGraphRequest, SPARQLGraphResponse

logger = logging.getLogger(__name__)


class GraphGetTester:
    """
    Modular test implementation for SPARQL graph retrieval operations.
    
    Handles:
    - Individual graph retrieval by URI
    - Graph metadata validation
    - Response validation
    - Error handling
    """
    
    def __init__(self, endpoint):
        """
        Initialize the graph get tester.
        
        Args:
            endpoint: SPARQLGraphEndpoint instance
        """
        self.endpoint = endpoint
        
    async def test_graph_retrieval(self, space_id: str, existing_graphs: List[str] = None) -> Dict[str, Any]:
        """
        Test graph retrieval operations.
        
        Args:
            space_id: Space ID to retrieve graphs from
            existing_graphs: List of graph URIs that should exist
            
        Returns:
            Dictionary with test results
        """
        logger.info("🔍 Testing graph retrieval operations...")
        
        results = {
            'success': True,
            'total_tests': 0,
            'passed_tests': 0,
            'failed_tests': [],
            'test_details': []
        }
        
        # Test 1: Get existing graph (if any exist)
        if existing_graphs:
            get_existing_result = await self._test_get_existing_graph(space_id, existing_graphs[0])
            results['test_details'].append(get_existing_result)
            results['total_tests'] += 1
            if get_existing_result['passed']:
                results['passed_tests'] += 1
            else:
                results['success'] = False
                results['failed_tests'].append(get_existing_result['name'])
        
        # Test 2: Get non-existent graph
        get_nonexistent_result = await self._test_get_nonexistent_graph(space_id)
        results['test_details'].append(get_nonexistent_result)
        results['total_tests'] += 1
        if get_nonexistent_result['passed']:
            results['passed_tests'] += 1
        else:
            results['success'] = False
            results['failed_tests'].append(get_nonexistent_result['name'])
        
        # Test 3: Get graph info/metadata
        if existing_graphs:
            get_info_result = await self._test_get_graph_info(space_id, existing_graphs[0])
            results['test_details'].append(get_info_result)
            results['total_tests'] += 1
            if get_info_result['passed']:
                results['passed_tests'] += 1
            else:
                results['success'] = False
                results['failed_tests'].append(get_info_result['name'])
        
        logger.info(f"✅ Graph retrieval tests completed: {results['passed_tests']}/{results['total_tests']} passed")
        return results
    
    async def _test_get_existing_graph(self, space_id: str, graph_uri: str) -> Dict[str, Any]:
        """Test retrieving an existing graph."""
        logger.info(f"  Testing get existing graph: {graph_uri}")
        
        try:
            # Get graph using endpoint's direct method
            graph_info = await self.endpoint._get_graph_info(
                space_id, 
                graph_uri,
                {"username": "test_user", "user_id": "test_user_123"}
            )
            
            if graph_info and graph_info.graph_uri == graph_uri:
                return {
                    'name': 'Get Existing Graph',
                    'passed': True,
                    'details': f"Successfully retrieved graph: {graph_uri}",
                    'graph_uri': graph_uri,
                    'graph_info': graph_info.model_dump() if hasattr(graph_info, 'model_dump') else str(graph_info)
                }
            else:
                return {
                    'name': 'Get Existing Graph',
                    'passed': False,
                    'error': f"Failed to retrieve existing graph or incorrect info",
                    'graph_uri': graph_uri,
                    'graph_info': graph_info.model_dump() if graph_info and hasattr(graph_info, 'model_dump') else str(graph_info)
                }
                
        except Exception as e:
            return {
                'name': 'Get Existing Graph',
                'passed': False,
                'error': f"Exception during graph retrieval: {e}",
                'graph_uri': graph_uri
            }
    
    async def _test_get_nonexistent_graph(self, space_id: str) -> Dict[str, Any]:
        """Test retrieving a non-existent graph."""
        nonexistent_uri = f"http://vital.ai/graph/nonexistent_{uuid.uuid4().hex[:8]}"
        logger.info(f"  Testing get non-existent graph: {nonexistent_uri}")
        
        try:
            # Try to get non-existent graph using direct method
            graph_info = await self.endpoint._get_graph_info(
                space_id, 
                nonexistent_uri,
                {"username": "test_user", "user_id": "test_user_123"}
            )
            
            # Should return None for non-existent graphs
            if graph_info is None:
                return {
                    'name': 'Get Non-existent Graph',
                    'passed': True,  # Pass if it correctly returns None
                    'details': f"Correctly handled non-existent graph: returned None",
                    'graph_uri': nonexistent_uri
                }
            else:
                return {
                    'name': 'Get Non-existent Graph',
                    'passed': False,  # Fail if it returns data for non-existent graph
                    'error': f"Expected None for non-existent graph but got data",
                    'graph_uri': nonexistent_uri,
                    'graph_info': graph_info.model_dump() if hasattr(graph_info, 'model_dump') else str(graph_info)
                }
                
        except Exception as e:
            return {
                'name': 'Get Non-existent Graph',
                'passed': False,
                'error': f"Unexpected exception during non-existent graph retrieval: {e}",
                'graph_uri': nonexistent_uri
            }
    
    async def _test_get_graph_info(self, space_id: str, graph_uri: str) -> Dict[str, Any]:
        """Test retrieving graph information/metadata."""
        logger.info(f"  Testing get graph info: {graph_uri}")
        
        try:
            # Get graph info using endpoint's direct method
            graph_info = await self.endpoint._get_graph_info(
                space_id, 
                graph_uri,
                {"username": "test_user", "user_id": "test_user_123"}
            )
            
            if graph_info and graph_info.graph_uri == graph_uri:
                return {
                    'name': 'Get Graph Info',
                    'passed': True,
                    'details': f"Successfully retrieved graph info: {graph_uri}",
                    'graph_uri': graph_uri,
                    'graph_info': graph_info.model_dump() if hasattr(graph_info, 'model_dump') else str(graph_info)
                }
            else:
                return {
                    'name': 'Get Graph Info',
                    'passed': False,
                    'error': f"Failed to retrieve graph info or incorrect info",
                    'graph_uri': graph_uri,
                    'graph_info': graph_info.model_dump() if graph_info and hasattr(graph_info, 'model_dump') else str(graph_info)
                }
                
        except Exception as e:
            return {
                'name': 'Get Graph Info',
                'passed': False,
                'error': f"Exception during graph info retrieval: {e}",
                'graph_uri': graph_uri
            }
