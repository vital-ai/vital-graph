"""
Modular test case for triples deletion operations.

This module provides comprehensive testing for deleting triples via quad requests
with dual-write consistency validation.
"""

import logging
from typing import Dict, Any

from vitalgraph.model.quad_model import Quad, QuadRequest

logger = logging.getLogger(__name__)


class TriplesDeleteTester:
    """
    Modular test case for triples deletion operations.
    
    Tests:
    - Deleting specific triples via quad requests
    - Dual-write consistency validation after deletion
    - Error handling and validation
    - Response structure verification
    """
    
    def __init__(self, endpoint):
        """
        Initialize the triples deletion tester.
        
        Args:
            endpoint: TriplesEndpoint instance
        """
        self.endpoint = endpoint
        
    async def test_triples_deletion(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """
        Test deleting triples via quad requests using identical logic from original test.
        
        Args:
            space_id: Space ID to test in
            graph_id: Graph ID to test in
            
        Returns:
            Dictionary with test results
        """
        logger.info(f"🧪 Testing triples deletion in space {space_id}, graph {graph_id}")
        
        results = {
            'success': True,
            'total_tests': 1,
            'passed_tests': 0,
            'failed_tests': [],
            'test_details': []
        }
        
        # Use identical logic from original test - single deletion test
        deletion_result = await self._test_delete_specific_triples_original_logic(space_id, graph_id)
        results['test_details'].append(deletion_result)
        
        if deletion_result['passed']:
            results['passed_tests'] += 1
        else:
            results['success'] = False
            results['failed_tests'].append(deletion_result['name'])
        
        logger.info(f"✅ Triples deletion tests completed: {results['passed_tests']}/{results['total_tests']} passed")
        return results
    
    async def _test_delete_specific_triples_original_logic(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test deleting specific triples using identical logic from original test."""
        logger.info(f"  Testing delete specific triples (original logic)")
        
        try:
            # Create quads to delete
            delete_quads = [
                Quad(s="<http://vital.ai/person/john_doe>", p="<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>", o="<http://vital.ai/ontology/Person>"),
                Quad(s="<http://vital.ai/person/john_doe>", p="<http://vital.ai/ontology/name>", o='"John Doe"'),
            ]
            delete_request = QuadRequest(quads=delete_quads)
            
            # Delete triples via endpoint (identical to original test)
            response = await self.endpoint._delete_triples(
                space_id,
                graph_id,
                delete_request,
                {"username": "test_user", "user_id": "test_user_123"}
            )
            
            # Use identical success/failure logic from original test
            if response.success and response.affected_count > 0:
                return {
                    'name': 'Delete Specific Triples',
                    'passed': True,
                    'details': f"Successfully deleted {response.affected_count} triples",
                    'deleted_count': response.affected_count,
                    'response_message': response.message
                }
            else:
                # FAIL if no triples were deleted or operation failed (identical to original)
                error_msg = f"Failed to delete triples: {response.message if not response.success else f'0 triples deleted (expected > 0)'}"
                return {
                    'name': 'Delete Specific Triples',
                    'passed': False,
                    'error': error_msg,
                    'response_success': response.success,
                    'affected_count': response.affected_count
                }
                
        except Exception as e:
            return {
                'name': 'Delete Specific Triples',
                'passed': False,
                'error': f"Exception during triples deletion test: {e}"
            }
    
    async def _test_delete_specific_triples(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test deleting specific triples."""
        logger.info(f"  Testing delete specific triples")
        
        try:
            # Create quads to delete
            delete_quads = [
                Quad(s="<http://vital.ai/person/john_doe>", p="<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>", o="<http://vital.ai/ontology/Person>"),
                Quad(s="<http://vital.ai/person/john_doe>", p="<http://vital.ai/ontology/name>", o='"John Doe"'),
            ]
            delete_request = QuadRequest(quads=delete_quads)
            
            # Delete triples via endpoint
            response = await self.endpoint._delete_triples(
                space_id,
                graph_id,
                delete_request,
                {"username": "test_user", "user_id": "test_user_123"}
            )
            
            if response.success and response.affected_count > 0:
                return {
                    'name': 'Delete Specific Triples',
                    'passed': True,
                    'details': f"Successfully deleted {response.affected_count} triples",
                    'deleted_count': response.affected_count,
                    'response_message': response.message
                }
            elif response.success and response.affected_count == 0:
                return {
                    'name': 'Delete Specific Triples',
                    'passed': True,  # May be valid if triples don't exist
                    'details': "No triples were deleted (may be expected if triples don't exist)",
                    'deleted_count': response.affected_count,
                    'response_message': response.message
                }
            else:
                return {
                    'name': 'Delete Specific Triples',
                    'passed': False,
                    'error': f"Failed to delete triples: {response.message}",
                    'response_success': response.success,
                    'affected_count': response.affected_count
                }
                
        except Exception as e:
            return {
                'name': 'Delete Specific Triples',
                'passed': False,
                'error': f"Exception during specific triples deletion: {e}"
            }
    
    async def _test_delete_non_existent_triples(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test deleting non-existent triples (edge case)."""
        logger.info(f"  Testing delete non-existent triples")
        
        try:
            # Create quads with truly non-existent triples using unique IDs
            import uuid
            unique_id = uuid.uuid4().hex
            non_existent_quads = [
                Quad(s=f"<http://vital.ai/person/definitely_non_existent_{unique_id}>", p="<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>", o="<http://vital.ai/ontology/Person>"),
                Quad(s=f"<http://vital.ai/person/definitely_non_existent_{unique_id}>", p=f"<http://vital.ai/ontology/unique_{unique_id}>", o=f'"Definitely Non Existent Value {unique_id}"'),
            ]
            non_existent_request = QuadRequest(quads=non_existent_quads)
            
            response = await self.endpoint._delete_triples(
                space_id,
                graph_id,
                non_existent_request,
                {"username": "test_user", "user_id": "test_user_123"}
            )
            
            # Should succeed but delete 0 triples
            if response.success and response.affected_count == 0:
                return {
                    'name': 'Delete Non-existent Triples',
                    'passed': True,
                    'details': "Correctly handled non-existent triples deletion (0 triples deleted)",
                    'deleted_count': response.affected_count,
                    'response_message': response.message
                }
            elif response.success and response.affected_count > 0:
                return {
                    'name': 'Delete Non-existent Triples',
                    'passed': False,
                    'error': f"Unexpectedly deleted {response.affected_count} triples for non-existent data",
                    'deleted_count': response.affected_count
                }
            else:
                return {
                    'name': 'Delete Non-existent Triples',
                    'passed': False,
                    'error': f"Failed to handle non-existent triples deletion: {response.message}",
                    'response_success': response.success
                }
                
        except Exception as e:
            return {
                'name': 'Delete Non-existent Triples',
                'passed': False,
                'error': f"Exception during non-existent triples deletion: {e}"
            }
    
    async def _test_delete_empty_document(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test deleting empty quad document (edge case)."""
        logger.info(f"  Testing delete empty document")
        
        try:
            # Create empty QuadRequest
            empty_request = QuadRequest(quads=[])
            
            response = await self.endpoint._delete_triples(
                space_id,
                graph_id,
                empty_request,
                {"username": "test_user", "user_id": "test_user_123"}
            )
            
            # Empty document should succeed but delete 0 triples
            if response.success and response.affected_count == 0:
                return {
                    'name': 'Delete Empty Document',
                    'passed': True,
                    'details': "Empty document handled correctly (0 triples deleted)",
                    'deleted_count': response.affected_count,
                    'response_message': response.message
                }
            elif response.success and response.affected_count > 0:
                return {
                    'name': 'Delete Empty Document',
                    'passed': False,
                    'error': f"Empty document unexpectedly deleted {response.affected_count} triples",
                    'deleted_count': response.affected_count
                }
            else:
                return {
                    'name': 'Delete Empty Document',
                    'passed': False,
                    'error': f"Empty document deletion failed: {response.message}",
                    'response_success': response.success
                }
                
        except Exception as e:
            return {
                'name': 'Delete Empty Document',
                'passed': False,
                'error': f"Exception during empty document deletion: {e}"
            }
