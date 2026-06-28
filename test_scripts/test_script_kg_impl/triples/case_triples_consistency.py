"""
Modular test case for triples dual-write consistency validation.

This module provides comprehensive testing for validating dual-write consistency
between Fuseki and PostgreSQL storage layers.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class TriplesConsistencyTester:
    """
    Modular test case for triples dual-write consistency validation.
    
    Tests:
    - Dual-write consistency validation between Fuseki and PostgreSQL
    - Storage layer synchronization verification
    - Error handling and validation
    """
    
    def __init__(self, endpoint, validation_method):
        """
        Initialize the triples consistency tester.
        
        Args:
            endpoint: TriplesEndpoint instance
            validation_method: Method to validate dual-write consistency
        """
        self.endpoint = endpoint
        self.validation_method = validation_method
        
    async def test_dual_write_consistency(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """
        Test dual-write consistency validation using identical logic from original test.
        
        Args:
            space_id: Space ID to test in
            graph_id: Graph ID to test in
            
        Returns:
            Dictionary with test results
        """
        logger.info(f"🧪 Testing dual-write consistency in space {space_id}, graph {graph_id}")
        
        results = {
            'success': True,
            'total_tests': 1,
            'passed_tests': 0,
            'failed_tests': [],
            'test_details': []
        }
        
        # Use identical logic from original test
        consistency_result = await self._test_consistency_validation_original_logic(space_id, graph_id)
        results['test_details'].append(consistency_result)
        
        if consistency_result['passed']:
            results['passed_tests'] += 1
        else:
            results['success'] = False
            results['failed_tests'].append(consistency_result['name'])
        
        logger.info(f"✅ Dual-write consistency tests completed: {results['passed_tests']}/{results['total_tests']} passed")
        return results
    
    async def _test_consistency_validation_original_logic(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test dual-write consistency using identical logic from original test."""
        logger.info(f"  Testing dual-write consistency validation (original logic)")
        
        try:
            # Perform comprehensive dual-write validation (identical to original test)
            validation_result = await self.validation_method()
            
            # Use identical success/failure logic from original test
            if validation_result["consistent"]:
                return {
                    'name': 'Dual-Write Consistency Validation',
                    'passed': True,
                    'details': "All triples show perfect dual-write consistency",
                    'validation_result': validation_result,
                    'space_id': space_id,
                    'graph_id': graph_id
                }
            else:
                return {
                    'name': 'Dual-Write Consistency Validation',
                    'passed': False,
                    'error': "Dual-write consistency issues detected",
                    'validation_result': validation_result,
                    'space_id': space_id,
                    'graph_id': graph_id
                }
                
        except Exception as e:
            return {
                'name': 'Dual-Write Consistency Validation',
                'passed': False,
                'error': f"Exception during dual-write consistency test: {e}",
                'space_id': space_id,
                'graph_id': graph_id
            }
