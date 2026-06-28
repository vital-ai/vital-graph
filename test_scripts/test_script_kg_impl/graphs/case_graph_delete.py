#!/usr/bin/env python3
"""
Graph Delete Test Module

Modular test implementation for SPARQL graph deletion operations.
Used by the main graphs endpoint test orchestrator.

Focuses on:
- Graph deletion with dual-write validation
- Graph cleanup verification
- Error handling for non-existent graphs
- Response validation
"""

import logging
import uuid
from typing import Dict, Any, List, Optional

# Import models
from vitalgraph.model.sparql_model import SPARQLGraphRequest, SPARQLGraphResponse

logger = logging.getLogger(__name__)


class GraphDeleteTester:
    """
    Modular test implementation for SPARQL graph deletion operations.
    
    Handles:
    - Graph deletion with dual-write validation
    - Graph cleanup verification
    - Response validation
    - Error handling
    """
    
    def __init__(self, endpoint):
        """
        Initialize the graph delete tester.
        
        Args:
            endpoint: SPARQLGraphEndpoint instance
        """
        self.endpoint = endpoint
        
    async def test_graph_deletion(self, space_id: str, graphs_to_delete: List[str] = None) -> Dict[str, Any]:
        """
        Test graph deletion operations.
        
        Args:
            space_id: Space ID to delete graphs from
            graphs_to_delete: List of graph URIs to delete
            
        Returns:
            Dictionary with test results
        """
        logger.info("🗑️ Testing graph deletion operations...")
        
        results = {
            'success': True,
            'total_tests': 0,
            'passed_tests': 0,
            'failed_tests': [],
            'test_details': [],
            'deleted_graphs': []
        }
        
        # Test 1: Delete existing graphs
        if graphs_to_delete:
            for graph_uri in graphs_to_delete:
                delete_result = await self._test_delete_existing_graph(space_id, graph_uri)
                results['test_details'].append(delete_result)
                results['total_tests'] += 1
                if delete_result['passed']:
                    results['passed_tests'] += 1
                    results['deleted_graphs'].append(graph_uri)
                else:
                    results['success'] = False
                    results['failed_tests'].append(delete_result['name'])
        
        # Test 2: Delete non-existent graph
        delete_nonexistent_result = await self._test_delete_nonexistent_graph(space_id)
        results['test_details'].append(delete_nonexistent_result)
        results['total_tests'] += 1
        if delete_nonexistent_result['passed']:
            results['passed_tests'] += 1
        else:
            results['success'] = False
            results['failed_tests'].append(delete_nonexistent_result['name'])
        
        # Test 3: Verify deletion (dual-write consistency)
        if results['deleted_graphs']:
            verification_result = await self._test_deletion_verification(space_id, results['deleted_graphs'][0])
            results['test_details'].append(verification_result)
            results['total_tests'] += 1
            if verification_result['passed']:
                results['passed_tests'] += 1
            else:
                results['success'] = False
                results['failed_tests'].append(verification_result['name'])
        
        logger.info(f"✅ Graph deletion tests completed: {results['passed_tests']}/{results['total_tests']} passed")
        return results
    
    async def _test_delete_existing_graph(self, space_id: str, graph_uri: str) -> Dict[str, Any]:
        """Test deleting an existing graph."""
        logger.info(f"  Testing delete existing graph: {graph_uri}")
        
        try:
            # Delete graph using endpoint
            request = SPARQLGraphRequest(
                operation="DROP",
                target_graph_uri=graph_uri
            )
            
            response = await self.endpoint._execute_graph_operation(
                space_id, 
                request,
                {"username": "test_user", "user_id": "test_user_123"}
            )
            
            if response.success:
                return {
                    'name': f'Delete Existing Graph ({graph_uri})',
                    'passed': True,
                    'details': f"Successfully deleted graph: {graph_uri}",
                    'graph_uri': graph_uri,
                    'response': response.model_dump()
                }
            else:
                return {
                    'name': f'Delete Existing Graph ({graph_uri})',
                    'passed': False,
                    'error': f"Failed to delete existing graph: {response.message}",
                    'graph_uri': graph_uri,
                    'response': response.model_dump()
                }
                
        except Exception as e:
            return {
                'name': f'Delete Existing Graph ({graph_uri})',
                'passed': False,
                'error': f"Exception during graph deletion: {e}",
                'graph_uri': graph_uri
            }
    
    async def _test_delete_nonexistent_graph(self, space_id: str) -> Dict[str, Any]:
        """Test deleting a non-existent graph."""
        nonexistent_uri = f"http://vital.ai/graph/nonexistent_delete_{uuid.uuid4().hex[:8]}"
        logger.info(f"  Testing delete non-existent graph: {nonexistent_uri}")
        
        try:
            # Try to delete non-existent graph
            request = SPARQLGraphRequest(
                operation="DROP",
                target_graph_uri=nonexistent_uri
            )
            
            response = await self.endpoint._execute_graph_operation(
                space_id, 
                request,
                {"username": "test_user", "user_id": "test_user_123"}
            )
            
            # Should handle gracefully (either succeed silently or provide meaningful error)
            return {
                'name': 'Delete Non-existent Graph',
                'passed': True,  # Pass if it handles gracefully
                'details': f"Handled non-existent graph deletion: {response.message}",
                'graph_uri': nonexistent_uri,
                'response': response.model_dump()
            }
                
        except Exception as e:
            return {
                'name': 'Delete Non-existent Graph',
                'passed': False,
                'error': f"Exception during non-existent graph deletion: {e}",
                'graph_uri': nonexistent_uri
            }
    
    async def _test_deletion_verification(self, space_id: str, deleted_graph_uri: str) -> Dict[str, Any]:
        """Test verification that graph was actually deleted."""
        logger.info(f"  Testing deletion verification: {deleted_graph_uri}")
        
        try:
            # Try to get the deleted graph to verify it's gone using direct method
            graph_info = await self.endpoint._get_graph_info(
                space_id, 
                deleted_graph_uri,
                {"username": "test_user", "user_id": "test_user_123"}
            )
            
            # Should return None since graph was deleted
            if graph_info is None:
                return {
                    'name': 'Deletion Verification',
                    'passed': True,
                    'details': f"Verified graph deletion - graph not found: {deleted_graph_uri}",
                    'graph_uri': deleted_graph_uri
                }
            else:
                return {
                    'name': 'Deletion Verification',
                    'passed': False,
                    'error': f"Graph still exists after deletion: {deleted_graph_uri}",
                    'graph_uri': deleted_graph_uri,
                    'graph_info': graph_info.model_dump() if hasattr(graph_info, 'model_dump') else str(graph_info)
                }
                
        except Exception as e:
            return {
                'name': 'Deletion Verification',
                'passed': False,
                'error': f"Exception during deletion verification: {e}",
                'graph_uri': deleted_graph_uri
            }
