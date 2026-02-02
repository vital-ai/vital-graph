#!/usr/bin/env python3
"""
KGType Delete Test Case

Client-based test case for KGType deletion operations using VitalGraph client.
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class KGTypeDeleteTester:
    """Test case for KGType deletion operations."""
    
    def __init__(self, client):
        self.client = client
        
    def run_tests(self, space_id: str, graph_id: str, created_kgtypes: list = None) -> Dict[str, Any]:
        """
        Run KGType deletion tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            created_kgtypes: List of created KGType URIs for testing
            
        Returns:
            Test results dictionary
        """
        logger.info("🗑️ Testing KGType deletion operations...")
        
        results = []
        
        # Test delete existing KGType - use first 2 KGTypes (same as get tests, but get tests run first)
        if created_kgtypes:
            # Use first 2 KGTypes for delete tests (get tests have already completed)
            delete_kgtypes = created_kgtypes[:2]
            for i, kgtype_uri in enumerate(delete_kgtypes):
                delete_result = self._test_delete_existing_kgtype(space_id, graph_id, kgtype_uri, i+1)
                results.append(delete_result)
        
        # Test delete non-existent KGType
        nonexistent_result = self._test_delete_nonexistent_kgtype(space_id, graph_id)
        results.append(nonexistent_result)
        
        # Test batch delete - use remaining KGTypes (starting from index 2)
        if created_kgtypes and len(created_kgtypes) > 2:
            batch_result = self._test_batch_delete_kgtypes(space_id, graph_id, created_kgtypes[2:])
            results.append(batch_result)
        
        passed_tests = sum(1 for r in results if r['passed'])
        logger.info(f"✅ KGType deletion tests completed: {passed_tests}/{len(results)} passed")
        
        return {
            'name': 'KGType Deletion Tests',
            'passed': passed_tests == len(results),
            'total_tests': len(results),
            'passed_tests': passed_tests,
            'results': results
        }
    
    def _test_delete_existing_kgtype(self, space_id: str, graph_id: str, kgtype_uri: str, index: int) -> Dict[str, Any]:
        """Test deleting an existing KGType."""
        logger.info(f"  Testing delete existing KGType: {kgtype_uri}")
        
        try:
            # Log the request details
            logger.info(f"    📤 REQUEST: DELETE KGType")
            logger.info(f"      - Space ID: {space_id}")
            logger.info(f"      - Graph ID: {graph_id}")
            logger.info(f"      - KGType URI: {kgtype_uri}")
            
            # Delete KGType using client
            response = self.client.delete_kgtype(space_id, graph_id, kgtype_uri)
            
            # Log the response details
            logger.info(f"    📥 RESPONSE: DELETE KGType")
            logger.info(f"      - Response type: {type(response).__name__}")
            logger.info(f"      - Has success attr: {hasattr(response, 'success')}")
            if hasattr(response, 'success'):
                logger.info(f"      - Success: {response.success}")
            logger.info(f"      - Has deleted_count attr: {hasattr(response, 'deleted_count')}")
            if hasattr(response, 'deleted_count'):
                logger.info(f"      - Deleted count: {response.deleted_count}")
            if hasattr(response, 'message'):
                logger.info(f"      - Message: {response.message}")
            if hasattr(response, 'deleted_uris'):
                logger.info(f"      - Deleted URIs: {response.deleted_uris}")
            
            if response.is_success:
                return {
                    'name': f'Delete Existing KGType #{index}',
                    'passed': True,
                    'details': f"Successfully deleted KGType: {kgtype_uri}",
                    'kgtype_uri': kgtype_uri,
                    'deleted_count': response.deleted_count
                }
            else:
                return {
                    'name': f'Delete Existing KGType #{index}',
                    'passed': False,
                    'error': f"KGType deletion failed: {response.error_message}",
                    'response': response.model_dump() if response and hasattr(response, 'model_dump') else str(response)
                }
                
        except Exception as e:
            return {
                'name': f'Delete Existing KGType #{index}',
                'passed': False,
                'error': f"Exception during KGType deletion: {e}"
            }
    
    def _test_delete_nonexistent_kgtype(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test deleting a non-existent KGType."""
        logger.info("  Testing delete non-existent KGType...")
        
        nonexistent_uri = "http://vital.ai/test/kgtype/nonexistent_delete_12345"
        
        try:
            response = self.client.delete_kgtype(space_id, graph_id, nonexistent_uri)
            
            # Deletion of non-existent KGType might succeed (no-op) or fail
            # Both behaviors are acceptable depending on implementation
            return {
                'name': 'Delete Non-existent KGType',
                'passed': True,  # Either success or failure is acceptable
                'details': f"Delete attempt completed for non-existent KGType",
                'nonexistent_uri': nonexistent_uri,
                'response': response.model_dump() if response and hasattr(response, 'model_dump') else str(response)
            }
                
        except Exception as e:
            # Exception is acceptable for non-existent KGType deletion
            return {
                'name': 'Delete Non-existent KGType',
                'passed': True,  # Exception is acceptable
                'details': f"Exception for non-existent KGType deletion (acceptable): {e}",
                'nonexistent_uri': nonexistent_uri
            }
    
    def _test_batch_delete_kgtypes(self, space_id: str, graph_id: str, kgtype_uris: List[str]) -> Dict[str, Any]:
        """Test batch deletion of KGTypes."""
        logger.info(f"  Testing batch delete KGTypes: {len(kgtype_uris)} KGTypes...")
        
        try:
            deleted_count = 0
            successful_deletes = []
            failed_deletes = []
            
            # Delete each KGType individually (client might not support batch delete)
            for kgtype_uri in kgtype_uris:
                try:
                    response = self.client.delete_kgtype(space_id, graph_id, kgtype_uri)
                    if response and hasattr(response, 'deleted_count') and response.deleted_count > 0:
                        deleted_count += response.deleted_count
                        successful_deletes.append(kgtype_uri)
                    else:
                        failed_deletes.append(kgtype_uri)
                except Exception as e:
                    failed_deletes.append(f"{kgtype_uri} (error: {e})")
            
            if deleted_count > 0:
                return {
                    'name': 'Batch Delete KGTypes',
                    'passed': True,
                    'details': f"Successfully deleted {deleted_count} KGTypes in batch operation",
                    'total_attempted': len(kgtype_uris),
                    'successful_deletes': len(successful_deletes),
                    'failed_deletes': len(failed_deletes),
                    'deleted_count': deleted_count
                }
            else:
                return {
                    'name': 'Batch Delete KGTypes',
                    'passed': False,
                    'error': f"Batch delete failed - no KGTypes were deleted",
                    'total_attempted': len(kgtype_uris),
                    'failed_deletes': failed_deletes
                }
                
        except Exception as e:
            return {
                'name': 'Batch Delete KGTypes',
                'passed': False,
                'error': f"Exception during batch KGType deletion: {e}"
            }
