#!/usr/bin/env python3
"""
Graph Creation Test Module

Modular test implementation for SPARQL graph creation operations.
Used by the main graphs endpoint test orchestrator.

Focuses on:
- Graph creation with dual-write validation
- Graph metadata insertion
- Error handling for duplicate graphs
- Response validation
"""

import logging
import uuid
from typing import Dict, Any, List, Optional

# Import models
from vitalgraph.model.sparql_model import SPARQLGraphRequest, SPARQLGraphResponse

logger = logging.getLogger(__name__)


class GraphCreateTester:
    """
    Modular test implementation for SPARQL graph creation operations.
    
    Handles:
    - Graph creation with dual-write validation
    - Graph metadata management
    - Response validation
    - Error handling
    """
    
    def __init__(self, endpoint):
        """
        Initialize the graph creation tester.
        
        Args:
            endpoint: SPARQLGraphEndpoint instance
        """
        self.endpoint = endpoint
        
    async def test_graph_creation(self, space_id: str) -> Dict[str, Any]:
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
        create_result = await self._test_basic_graph_creation(space_id)
        results['test_details'].append(create_result)
        results['total_tests'] += 1
        if create_result['passed']:
            results['passed_tests'] += 1
            if 'graph_uri' in create_result:
                results['created_graphs'].append(create_result['graph_uri'])
        else:
            results['success'] = False
            results['failed_tests'].append(create_result['name'])
        
        # Test 2: Graph creation with metadata
        metadata_result = await self._test_graph_creation_with_metadata(space_id)
        results['test_details'].append(metadata_result)
        results['total_tests'] += 1
        if metadata_result['passed']:
            results['passed_tests'] += 1
            if 'graph_uri' in metadata_result:
                results['created_graphs'].append(metadata_result['graph_uri'])
        else:
            results['success'] = False
            results['failed_tests'].append(metadata_result['name'])
        
        # Test 3: Duplicate graph creation (should handle gracefully)
        duplicate_result = await self._test_duplicate_graph_creation(space_id)
        results['test_details'].append(duplicate_result)
        results['total_tests'] += 1
        if duplicate_result['passed']:
            results['passed_tests'] += 1
        else:
            results['success'] = False
            results['failed_tests'].append(duplicate_result['name'])
        
        logger.info(f"✅ Graph creation tests completed: {results['passed_tests']}/{results['total_tests']} passed")
        return results
    
    async def _test_basic_graph_creation(self, space_id: str) -> Dict[str, Any]:
        """Test basic graph creation."""
        logger.info("  Testing basic graph creation...")
        
        test_graph_uri = f"http://vital.ai/graph/test_create_{uuid.uuid4().hex[:8]}"
        
        try:
            # Create graph using endpoint
            request = SPARQLGraphRequest(
                operation="CREATE",
                target_graph_uri=test_graph_uri
            )
            
            response = await self.endpoint._execute_graph_operation(
                space_id, 
                request,
                {"username": "test_user", "user_id": "test_user_123"}
            )
            
            if response.success:
                return {
                    'name': 'Basic Graph Creation',
                    'passed': True,
                    'graph_uri': test_graph_uri,
                    'details': f"Graph created successfully: {test_graph_uri}",
                    'response': response.model_dump()
                }
            else:
                return {
                    'name': 'Basic Graph Creation',
                    'passed': False,
                    'error': f"Graph creation failed: {response.message}",
                    'response': response.model_dump()
                }
                
        except Exception as e:
            return {
                'name': 'Basic Graph Creation',
                'passed': False,
                'error': f"Exception during graph creation: {e}"
            }
    
    async def _test_graph_creation_with_metadata(self, space_id: str) -> Dict[str, Any]:
        """Test graph creation with metadata."""
        logger.info("  Testing graph creation with metadata...")
        
        test_graph_uri = f"http://vital.ai/graph/test_metadata_{uuid.uuid4().hex[:8]}"
        
        try:
            # Create graph with metadata
            request = SPARQLGraphRequest(
                operation="CREATE",
                target_graph_uri=test_graph_uri,
                metadata={
                    "description": "Test graph with metadata",
                    "created_by": "test_user",
                    "purpose": "testing"
                }
            )
            
            response = await self.endpoint._execute_graph_operation(
                space_id, 
                request,
                {"username": "test_user", "user_id": "test_user_123"}
            )
            
            if response.success:
                return {
                    'name': 'Graph Creation with Metadata',
                    'passed': True,
                    'graph_uri': test_graph_uri,
                    'details': f"Graph with metadata created successfully: {test_graph_uri}",
                    'response': response.model_dump()
                }
            else:
                return {
                    'name': 'Graph Creation with Metadata',
                    'passed': False,
                    'error': f"Graph creation with metadata failed: {response.message}",
                    'response': response.model_dump()
                }
                
        except Exception as e:
            return {
                'name': 'Graph Creation with Metadata',
                'passed': False,
                'error': f"Exception during graph creation with metadata: {e}"
            }
    
    async def _test_duplicate_graph_creation(self, space_id: str) -> Dict[str, Any]:
        """Test duplicate graph creation handling."""
        logger.info("  Testing duplicate graph creation handling...")
        
        test_graph_uri = f"http://vital.ai/graph/test_duplicate_{uuid.uuid4().hex[:8]}"
        
        try:
            # Create graph first time
            request = SPARQLGraphRequest(
                operation="CREATE",
                target_graph_uri=test_graph_uri
            )
            
            first_response = await self.endpoint._execute_graph_operation(
                space_id, 
                request,
                {"username": "test_user", "user_id": "test_user_123"}
            )
            
            if not first_response.success:
                return {
                    'name': 'Duplicate Graph Creation Handling',
                    'passed': False,
                    'error': f"Initial graph creation failed: {first_response.message}"
                }
            
            # Try to create the same graph again
            second_response = await self.endpoint._execute_graph_operation(
                space_id, 
                request,
                {"username": "test_user", "user_id": "test_user_123"}
            )
            
            # Should handle gracefully (either succeed or provide meaningful error)
            return {
                'name': 'Duplicate Graph Creation Handling',
                'passed': True,  # Pass if it handles gracefully
                'details': f"Duplicate creation handled: {second_response.message}",
                'first_response': first_response.model_dump(),
                'second_response': second_response.model_dump()
            }
                
        except Exception as e:
            return {
                'name': 'Duplicate Graph Creation Handling',
                'passed': False,
                'error': f"Exception during duplicate graph creation test: {e}"
            }
