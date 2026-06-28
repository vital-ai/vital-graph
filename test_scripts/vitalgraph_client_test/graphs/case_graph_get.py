#!/usr/bin/env python3
"""
Graph Get Test Module - Client Version

Client-based test implementation for graph information retrieval operations.
Used by the main graphs endpoint test orchestrator.

Focuses on:
- Graph information retrieval using VitalGraph client
- Response validation
- Error handling for non-existent graphs
- Graph metadata verification
"""

import logging
import uuid
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class GraphGetTester:
    """
    Client-based test implementation for graph information retrieval operations.
    
    Handles:
    - Graph info retrieval using VitalGraphClient
    - Response validation
    - Error handling
    - Non-existent graph testing
    """
    
    def __init__(self, client):
        """
        Initialize the graph get tester.
        
        Args:
            client: VitalGraphClient instance
        """
        self.client = client
        
    async def test_graph_retrieval(self, space_id: str, created_graphs: List[str] = None) -> Dict[str, Any]:
        """
        Test graph information retrieval operations.
        
        Args:
            space_id: Space ID to retrieve graphs from
            created_graphs: List of graph URIs that should exist
            
        Returns:
            Dictionary with test results
        """
        logger.info("🔍 Testing graph information retrieval operations...")
        
        results = {
            'success': True,
            'total_tests': 0,
            'passed_tests': 0,
            'failed_tests': [],
            'test_details': []
        }
        
        # Test 1: Get info for existing graphs
        if created_graphs:
            for graph_uri in created_graphs:
                get_result = await self._test_get_existing_graph_info(space_id, graph_uri)
                results['test_details'].append(get_result)
                results['total_tests'] += 1
                if get_result['passed']:
                    results['passed_tests'] += 1
                else:
                    results['success'] = False
                    results['failed_tests'].append(get_result['name'])
        
        # Test 2: Get info for non-existent graph
        nonexistent_result = await self._test_get_nonexistent_graph_info(space_id)
        results['test_details'].append(nonexistent_result)
        results['total_tests'] += 1
        if nonexistent_result['passed']:
            results['passed_tests'] += 1
        else:
            results['success'] = False
            results['failed_tests'].append(nonexistent_result['name'])
        
        # Test 3: Get info with invalid graph URI
        invalid_result = await self._test_get_invalid_graph_info(space_id)
        results['test_details'].append(invalid_result)
        results['total_tests'] += 1
        if invalid_result['passed']:
            results['passed_tests'] += 1
        else:
            results['success'] = False
            results['failed_tests'].append(invalid_result['name'])
        
        logger.info(f"✅ Graph retrieval tests completed: {results['passed_tests']}/{results['total_tests']} passed")
        return results
    
    async def _test_get_existing_graph_info(self, space_id: str, graph_uri: str) -> Dict[str, Any]:
        """Test getting info for an existing graph."""
        logger.info(f"  Testing get info for existing graph: {graph_uri}")
        
        try:
            # Get graph info using client
            info_response = await self.client.graphs.get_graph_info(space_id, graph_uri)
            
            if info_response.is_success and info_response.graph:
                return {
                    'name': f'Get Existing Graph Info ({graph_uri})',
                    'passed': True,
                    'details': f"Successfully retrieved info for graph: {graph_uri}",
                    'graph_uri': graph_uri,
                    'graph_info': info_response.graph
                }
            else:
                return {
                    'name': f'Get Existing Graph Info ({graph_uri})',
                    'passed': False,
                    'error': f"Graph info retrieval returned None for existing graph: {graph_uri}"
                }
                
        except Exception as e:
            return {
                'name': f'Get Existing Graph Info ({graph_uri})',
                'passed': False,
                'error': f"Exception during graph info retrieval: {e}"
            }
    
    async def _test_get_nonexistent_graph_info(self, space_id: str) -> Dict[str, Any]:
        """Test getting info for a non-existent graph."""
        logger.info("  Testing get info for non-existent graph...")
        
        nonexistent_graph_uri = f"http://vital.ai/graph/nonexistent_{uuid.uuid4().hex[:8]}"
        
        try:
            # Get graph info using client
            info_response = await self.client.graphs.get_graph_info(space_id, nonexistent_graph_uri)
            
            # This should either return None or raise an exception
            if not info_response.is_success or info_response.graph is None:
                return {
                    'name': 'Get Non-existent Graph Info',
                    'passed': True,
                    'details': f"Correctly returned None for non-existent graph: {nonexistent_graph_uri}",
                    'graph_uri': nonexistent_graph_uri
                }
            else:
                return {
                    'name': 'Get Non-existent Graph Info',
                    'passed': False,
                    'error': f"Unexpectedly returned info for non-existent graph: {nonexistent_graph_uri}",
                    'graph_info': info_response.graph
                }
                
        except Exception as e:
            # Exception for non-existent graph is acceptable behavior
            return {
                'name': 'Get Non-existent Graph Info',
                'passed': True,
                'details': f"Correctly raised exception for non-existent graph: {e}",
                'graph_uri': nonexistent_graph_uri
            }
    
    async def _test_get_invalid_graph_info(self, space_id: str) -> Dict[str, Any]:
        """Test getting info with invalid graph URI."""
        logger.info("  Testing get info with invalid graph URI...")
        
        invalid_graph_uri = "invalid-uri-not-a-proper-uri"
        
        try:
            # Get graph info using client
            info_response = await self.client.graphs.get_graph_info(space_id, invalid_graph_uri)
            
            # This should either return None or raise an exception
            if not info_response.is_success or info_response.graph is None:
                return {
                    'name': 'Get Invalid Graph Info',
                    'passed': True,
                    'details': f"Correctly returned None for invalid graph URI: {invalid_graph_uri}",
                    'graph_uri': invalid_graph_uri
                }
            else:
                return {
                    'name': 'Get Invalid Graph Info',
                    'passed': False,
                    'error': f"Unexpectedly returned info for invalid graph URI: {invalid_graph_uri}",
                    'graph_info': info_response.graph
                }
                
        except Exception as e:
            # Exception for invalid graph URI is acceptable behavior
            return {
                'name': 'Get Invalid Graph Info',
                'passed': True,
                'details': f"Correctly raised exception for invalid graph URI: {e}",
                'graph_uri': invalid_graph_uri
            }
