#!/usr/bin/env python3
"""
Graph Delete Test Module - Client Version

Client-based test implementation for graph deletion operations.
Used by the main graphs endpoint test orchestrator.

Focuses on:
- Graph deletion using VitalGraph client
- Response validation
- Error handling for non-existent graphs
- Cleanup verification
"""

import logging
import uuid
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class GraphDeleteTester:
    """
    Client-based test implementation for graph deletion operations.
    
    Handles:
    - Graph deletion using VitalGraphClient
    - Response validation
    - Error handling
    - Cleanup verification
    """
    
    def __init__(self, client):
        """
        Initialize the graph delete tester.
        
        Args:
            client: VitalGraphClient instance
        """
        self.client = client
        
    async def test_graph_deletion(self, space_id: str, created_graphs: List[str] = None) -> Dict[str, Any]:
        """
        Test graph deletion operations.
        
        Args:
            space_id: Space ID to delete graphs from
            created_graphs: List of graph URIs that should exist for deletion
            
        Returns:
            Dictionary with test results
        """
        logger.info("🗑️ Testing graph deletion operations...")
        
        results = {
            'success': True,
            'total_tests': 0,
            'passed_tests': 0,
            'failed_tests': [],
            'test_details': []
        }
        
        # Test 1: Delete existing graphs
        if created_graphs:
            # Test deletion of each created graph
            for graph_uri in created_graphs[:]:  # Use slice copy to avoid modification during iteration
                delete_result = await self._test_delete_existing_graph(space_id, graph_uri)
                results['test_details'].append(delete_result)
                results['total_tests'] += 1
                if delete_result['passed']:
                    results['passed_tests'] += 1
                    # Remove from created_graphs list since it's been deleted
                    if graph_uri in created_graphs:
                        created_graphs.remove(graph_uri)
                else:
                    results['success'] = False
                    results['failed_tests'].append(delete_result['name'])
        
        # Test 2: Delete non-existent graph
        nonexistent_result = await self._test_delete_nonexistent_graph(space_id)
        results['test_details'].append(nonexistent_result)
        results['total_tests'] += 1
        if nonexistent_result['passed']:
            results['passed_tests'] += 1
        else:
            results['success'] = False
            results['failed_tests'].append(nonexistent_result['name'])
        
        # Test 3: Delete with silent flag
        silent_result = await self._test_delete_with_silent_flag(space_id)
        results['test_details'].append(silent_result)
        results['total_tests'] += 1
        if silent_result['passed']:
            results['passed_tests'] += 1
        else:
            results['success'] = False
            results['failed_tests'].append(silent_result['name'])
        
        logger.info(f"✅ Graph deletion tests completed: {results['passed_tests']}/{results['total_tests']} passed")
        return results
    
    async def _test_delete_existing_graph(self, space_id: str, graph_uri: str) -> Dict[str, Any]:
        """Test deleting an existing graph."""
        logger.info(f"  Testing delete existing graph: {graph_uri}")
        
        try:
            # Delete graph using client
            delete_response = await self.client.graphs.drop_graph(space_id, graph_uri)
            
            if delete_response.is_success:
                # Verify graph is deleted by trying to get its info
                try:
                    info_response = await self.client.graphs.get_graph_info(space_id, graph_uri)
                    if not info_response.is_success or info_response.graph is None:
                        return {
                            'name': f'Delete Existing Graph ({graph_uri})',
                            'passed': True,
                            'details': f"Successfully deleted graph and verified removal: {graph_uri}",
                            'graph_uri': graph_uri,
                            'delete_response': delete_response
                        }
                    else:
                        return {
                            'name': f'Delete Existing Graph ({graph_uri})',
                            'passed': False,
                            'error': f"Graph deletion succeeded but graph still exists: {graph_uri}",
                            'graph_info': graph_info
                        }
                except Exception:
                    # Exception when getting info for deleted graph is expected
                    return {
                        'name': f'Delete Existing Graph ({graph_uri})',
                        'passed': True,
                        'details': f"Successfully deleted graph (verified by exception on info retrieval): {graph_uri}",
                        'graph_uri': graph_uri,
                        'delete_response': delete_response
                    }
            else:
                error_msg = delete_response.message if delete_response and hasattr(delete_response, 'message') else 'Unknown error'
                return {
                    'name': f'Delete Existing Graph ({graph_uri})',
                    'passed': False,
                    'error': f"Graph deletion failed: {error_msg}",
                    'delete_response': delete_response.model_dump() if delete_response and hasattr(delete_response, 'model_dump') else str(delete_response)
                }
                
        except Exception as e:
            return {
                'name': f'Delete Existing Graph ({graph_uri})',
                'passed': False,
                'error': f"Exception during graph deletion: {e}"
            }
    
    async def _test_delete_nonexistent_graph(self, space_id: str) -> Dict[str, Any]:
        """Test deleting a non-existent graph."""
        logger.info("  Testing delete non-existent graph...")
        
        nonexistent_graph_uri = f"http://vital.ai/graph/nonexistent_delete_{uuid.uuid4().hex[:8]}"
        
        try:
            # Delete non-existent graph using client
            delete_response = await self.client.graphs.drop_graph(space_id, nonexistent_graph_uri)
            
            # This should either succeed (idempotent) or fail gracefully
            if delete_response:
                return {
                    'name': 'Delete Non-existent Graph',
                    'passed': True,
                    'details': f"Delete non-existent graph handled appropriately: {nonexistent_graph_uri}",
                    'graph_uri': nonexistent_graph_uri,
                    'delete_response': delete_response
                }
            else:
                return {
                    'name': 'Delete Non-existent Graph',
                    'passed': False,
                    'error': f"Delete non-existent graph returned no response"
                }
                
        except Exception as e:
            # Exception for non-existent graph deletion is acceptable
            return {
                'name': 'Delete Non-existent Graph',
                'passed': True,
                'details': f"Delete non-existent graph properly handled with exception: {e}",
                'graph_uri': nonexistent_graph_uri
            }
    
    async def _test_delete_with_silent_flag(self, space_id: str) -> Dict[str, Any]:
        """Test deleting with silent flag."""
        logger.info("  Testing delete with silent flag...")
        
        # Create a graph first for deletion
        test_graph_uri = f"http://vital.ai/graph/test_silent_delete_{uuid.uuid4().hex[:8]}"
        
        try:
            # Create graph first
            create_response = await self.client.graphs.create_graph(space_id, test_graph_uri)
            
            if not create_response.is_success:
                return {
                    'name': 'Delete with Silent Flag',
                    'passed': False,
                    'error': f"Failed to create graph for silent delete test: {create_response.error_message}"
                }
            
            # Delete with silent flag using client
            delete_response = await self.client.graphs.drop_graph(space_id, test_graph_uri, silent=True)
            
            if delete_response:
                return {
                    'name': 'Delete with Silent Flag',
                    'passed': True,
                    'details': f"Successfully deleted graph with silent flag: {test_graph_uri}",
                    'graph_uri': test_graph_uri,
                    'delete_response': delete_response
                }
            else:
                return {
                    'name': 'Delete with Silent Flag',
                    'passed': False,
                    'error': f"Delete with silent flag returned no response"
                }
                
        except Exception as e:
            return {
                'name': 'Delete with Silent Flag',
                'passed': False,
                'error': f"Exception during silent delete test: {e}"
            }
