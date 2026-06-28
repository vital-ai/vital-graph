#!/usr/bin/env python3
"""
KGType Listing Test Case

Client-based test case for KGType listing operations using VitalGraph client.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class KGTypeListTester:
    """Test case for KGType listing operations."""
    
    def __init__(self, client):
        self.client = client
        
    async def run_tests(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """
        Run KGType listing tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            
        Returns:
            Test results dictionary
        """
        logger.info("📋 Testing KGType listing operations...")
        
        results = []
        
        # Test list all KGTypes
        list_result = await self._test_list_all_kgtypes(space_id, graph_id)
        results.append(list_result)
        
        # Test list with pagination
        pagination_result = await self._test_list_with_pagination(space_id, graph_id)
        results.append(pagination_result)
        
        # Test list with search
        search_result = await self._test_list_with_search(space_id, graph_id)
        results.append(search_result)
        
        passed_tests = sum(1 for r in results if r['passed'])
        logger.info(f"✅ KGType listing tests completed: {passed_tests}/{len(results)} passed")
        
        return {
            'name': 'KGType Listing Tests',
            'passed': passed_tests == len(results),
            'total_tests': len(results),
            'passed_tests': passed_tests,
            'results': results
        }
    
    async def _test_list_all_kgtypes(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test listing all KGTypes."""
        logger.info("  Testing list all KGTypes...")
        
        try:
            response = await self.client.list_kgtypes(space_id, graph_id, page_size=100)
            
            if response.is_success:
                return {
                    'name': 'List All KGTypes',
                    'passed': True,
                    'details': f"Successfully listed {response.count} KGTypes",
                    'total_count': response.count,
                    'returned_count': len(response.types),
                    'page_size': response.page_size,
                    'offset': response.offset
                }
            else:
                return {
                    'name': 'List All KGTypes',
                    'passed': False,
                    'error': response.error_message or "Failed to list KGTypes"
                }
                
        except Exception as e:
            return {
                'name': 'List All KGTypes',
                'passed': False,
                'error': f"Exception during KGType listing: {e}"
            }
    
    async def _test_list_with_pagination(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test listing KGTypes with pagination."""
        logger.info("  Testing list KGTypes with pagination...")
        
        try:
            # Test with small page size
            response = await self.client.list_kgtypes(space_id, graph_id, page_size=2, offset=0)
            
            if response.is_success:
                returned_count = len(response.types)
                expected_count = min(2, response.count)
                
                return {
                    'name': 'List KGTypes with Pagination',
                    'passed': returned_count <= 2,  # Should not exceed page size
                    'details': f"Pagination working correctly",
                    'total_count': response.count,
                    'returned_count': returned_count,
                    'expected_count': expected_count,
                    'page_size': response.page_size,
                    'offset': response.offset
                }
            else:
                return {
                    'name': 'List KGTypes with Pagination',
                    'passed': False,
                    'error': response.error_message or "Failed to list KGTypes with pagination"
                }
                
        except Exception as e:
            return {
                'name': 'List KGTypes with Pagination',
                'passed': False,
                'error': f"Exception during paginated KGType listing: {e}"
            }
    
    async def _test_list_with_search(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test listing KGTypes with search."""
        logger.info("  Testing list KGTypes with search...")
        
        try:
            # Search for KGTypes containing "type" in description
            response = await self.client.list_kgtypes(space_id, graph_id, search="type", page_size=10)
            
            if response.is_success:
                return {
                    'name': 'List KGTypes with Search',
                    'passed': True,  # Search executed successfully
                    'details': f"Search completed successfully",
                    'search_term': 'type',
                    'total_count': response.count,
                    'returned_count': len(response.types)
                }
            else:
                return {
                    'name': 'List KGTypes with Search',
                    'passed': False,
                    'error': response.error_message or "Failed to search KGTypes"
                }
                
        except Exception as e:
            return {
                'name': 'List KGTypes with Search',
                'passed': False,
                'error': f"Exception during KGType search: {e}"
            }
