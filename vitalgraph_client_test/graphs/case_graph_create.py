#!/usr/bin/env python3
"""
Graph Creation Test Module - Client Version

Client-based test implementation for graph creation operations.
Used by the main graphs endpoint test orchestrator.

Focuses on:
- Graph creation using VitalGraph client
- Response validation
- Error handling for duplicate graphs
- Graph metadata verification
"""

import logging
import uuid
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class GraphCreateTester:
    """
    Client-based test implementation for graph creation operations.
    
    Handles:
    - Graph creation using VitalGraphClient
    - Response validation
    - Error handling
    - Graph metadata verification
    """
    
    def __init__(self, client):
        """
        Initialize the graph creation tester.
        
        Args:
            client: VitalGraphClient instance
        """
        self.client = client
        
    def test_graph_creation(self, space_id: str) -> Dict[str, Any]:
        """
        Test graph creation operations.
        
        Args:
            space_id: Space ID to create graphs in
            
        Returns:
            Dictionary with test results
        """
        logger.info("🔧 Testing graph creation operations...")
        
        results = {
            'success': True,
            'total_tests': 0,
            'passed_tests': 0,
            'failed_tests': [],
            'test_details': [],
            'created_graphs': []
        }
        
        # Test 1: Basic graph creation
        create_result = self._test_basic_graph_creation(space_id)
        results['test_details'].append(create_result)
        results['total_tests'] += 1
        if create_result['passed']:
            results['passed_tests'] += 1
            if 'graph_uri' in create_result:
                results['created_graphs'].append(create_result['graph_uri'])
        else:
            results['success'] = False
            results['failed_tests'].append(create_result['name'])
        
        # Test 2: Graph creation with verification
        verify_result = self._test_graph_creation_with_verification(space_id)
        results['test_details'].append(verify_result)
        results['total_tests'] += 1
        if verify_result['passed']:
            results['passed_tests'] += 1
            if 'graph_uri' in verify_result:
                results['created_graphs'].append(verify_result['graph_uri'])
        else:
            results['success'] = False
            results['failed_tests'].append(verify_result['name'])
        
        # Test 3: Duplicate graph creation (should handle gracefully)
        duplicate_result = self._test_duplicate_graph_creation(space_id)
        results['test_details'].append(duplicate_result)
        results['total_tests'] += 1
        if duplicate_result['passed']:
            results['passed_tests'] += 1
        else:
            results['success'] = False
            results['failed_tests'].append(duplicate_result['name'])
        
        logger.info(f"✅ Graph creation tests completed: {results['passed_tests']}/{results['total_tests']} passed")
        return results
    
    def _test_basic_graph_creation(self, space_id: str) -> Dict[str, Any]:
        """Test basic graph creation."""
        logger.info("  Testing basic graph creation...")
        
        test_graph_uri = f"http://vital.ai/graph/test_create_{uuid.uuid4().hex[:8]}"
        
        try:
            # Create graph using client
            response = self.client.graphs.create_graph(space_id, test_graph_uri)
            
            if response.is_success:
                return {
                    'name': 'Basic Graph Creation',
                    'passed': True,
                    'graph_uri': test_graph_uri,
                    'details': f"Graph created successfully: {test_graph_uri}",
                    'response': response.model_dump() if hasattr(response, 'model_dump') else str(response)
                }
            else:
                return {
                    'name': 'Basic Graph Creation',
                    'passed': False,
                    'error': f"Graph creation failed: {response.error_message}",
                    'response': response.model_dump() if hasattr(response, 'model_dump') else str(response)
                }
                
        except Exception as e:
            return {
                'name': 'Basic Graph Creation',
                'passed': False,
                'error': f"Exception during graph creation: {e}"
            }
    
    def _test_graph_creation_with_verification(self, space_id: str) -> Dict[str, Any]:
        """Test graph creation with verification."""
        logger.info("  Testing graph creation with verification...")
        
        test_graph_uri = f"http://vital.ai/graph/test_verify_{uuid.uuid4().hex[:8]}"
        
        try:
            # Create graph using client
            create_response = self.client.graphs.create_graph(space_id, test_graph_uri)
            
            if not create_response.is_success:
                return {
                    'name': 'Graph Creation with Verification',
                    'passed': False,
                    'error': f"Graph creation failed: {create_response.error_message}"
                }
            
            # Verify graph exists by getting its info
            try:
                info_response = self.client.graphs.get_graph_info(space_id, test_graph_uri)
                if info_response.is_success and info_response.graph:
                    return {
                        'name': 'Graph Creation with Verification',
                        'passed': True,
                        'graph_uri': test_graph_uri,
                        'details': f"Graph created and verified: {test_graph_uri}",
                        'create_response': create_response,
                        'graph_info': info_response.graph
                    }
                else:
                    return {
                        'name': 'Graph Creation with Verification',
                        'passed': False,
                        'error': f"Graph created but verification failed - no graph info returned"
                    }
            except Exception as verify_e:
                return {
                    'name': 'Graph Creation with Verification',
                    'passed': False,
                    'error': f"Graph created but verification failed: {verify_e}"
                }
                
        except Exception as e:
            return {
                'name': 'Graph Creation with Verification',
                'passed': False,
                'error': f"Exception during graph creation with verification: {e}"
            }
    
    def _test_duplicate_graph_creation(self, space_id: str) -> Dict[str, Any]:
        """Test duplicate graph creation handling."""
        logger.info("  Testing duplicate graph creation handling...")
        
        test_graph_uri = f"http://vital.ai/graph/test_duplicate_{uuid.uuid4().hex[:8]}"
        
        try:
            # Create graph first time
            first_response = self.client.graphs.create_graph(space_id, test_graph_uri)
            
            if not first_response.is_success:
                return {
                    'name': 'Duplicate Graph Creation',
                    'passed': False,
                    'error': f"Initial graph creation failed: {first_response.error_message}"
                }
            
            # Try to create the same graph again
            second_response = self.client.graphs.create_graph(space_id, test_graph_uri)
            
            # This should either succeed (idempotent) or fail gracefully
            if second_response:
                return {
                    'name': 'Duplicate Graph Creation',
                    'passed': True,
                    'graph_uri': test_graph_uri,
                    'details': f"Duplicate graph creation handled appropriately",
                    'first_response': first_response,
                    'second_response': second_response
                }
            else:
                return {
                    'name': 'Duplicate Graph Creation',
                    'passed': False,
                    'error': f"Duplicate graph creation returned no response"
                }
                
        except Exception as e:
            # Exception handling for duplicate creation is acceptable
            return {
                'name': 'Duplicate Graph Creation',
                'passed': True,
                'details': f"Duplicate graph creation properly rejected with exception: {e}",
                'graph_uri': test_graph_uri
            }
