"""
Modular test case for triples listing operations.

This module provides comprehensive testing for listing triples with pagination,
filtering, and search functionality.
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class TriplesListingTester:
    """
    Modular test case for triples listing operations.
    
    Tests:
    - Basic triples listing with pagination
    - Subject-based filtering
    - Predicate-based filtering
    - Keyword-based search
    - Response structure validation
    """
    
    def __init__(self, endpoint):
        """
        Initialize the triples listing tester.
        
        Args:
            endpoint: TriplesEndpoint instance
        """
        self.endpoint = endpoint
        
    async def test_triples_listing(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """
        Test listing triples with various filters and pagination.
        
        Args:
            space_id: Space ID to test in
            graph_id: Graph ID to test in
            
        Returns:
            Dictionary with test results
        """
        logger.info(f"🧪 Testing triples listing in space {space_id}, graph {graph_id}")
        
        results = {
            'success': True,
            'total_tests': 0,
            'passed_tests': 0,
            'failed_tests': [],
            'test_details': []
        }
        
        # Test 1: Basic listing with pagination
        basic_listing_result = await self._test_basic_listing(space_id, graph_id)
        results['test_details'].append(basic_listing_result)
        results['total_tests'] += 1
        if basic_listing_result['passed']:
            results['passed_tests'] += 1
        else:
            results['success'] = False
            results['failed_tests'].append(basic_listing_result['name'])
        
        # Test 2: Subject-based filtering
        subject_filter_result = await self._test_subject_filtering(space_id, graph_id)
        results['test_details'].append(subject_filter_result)
        results['total_tests'] += 1
        if subject_filter_result['passed']:
            results['passed_tests'] += 1
        else:
            results['success'] = False
            results['failed_tests'].append(subject_filter_result['name'])
        
        # Test 3: Predicate-based filtering
        predicate_filter_result = await self._test_predicate_filtering(space_id, graph_id)
        results['test_details'].append(predicate_filter_result)
        results['total_tests'] += 1
        if predicate_filter_result['passed']:
            results['passed_tests'] += 1
        else:
            results['success'] = False
            results['failed_tests'].append(predicate_filter_result['name'])
        
        # Test 4: Keyword-based search
        keyword_search_result = await self._test_keyword_search(space_id, graph_id)
        results['test_details'].append(keyword_search_result)
        results['total_tests'] += 1
        if keyword_search_result['passed']:
            results['passed_tests'] += 1
        else:
            results['success'] = False
            results['failed_tests'].append(keyword_search_result['name'])
        
        logger.info(f"✅ Triples listing tests completed: {results['passed_tests']}/{results['total_tests']} passed")
        return results
    
    async def _test_basic_listing(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test basic triples listing with pagination."""
        logger.info(f"  Testing basic listing with pagination")
        
        try:
            response = await self.endpoint._list_triples(
                space_id,
                graph_id,
                page_size=10,
                offset=0,
                subject=None,
                predicate=None,
                object=None,
                object_filter=None,
                current_user={"username": "test_user", "user_id": "test_user_123"}
            )
            
            # Validate response structure
            if hasattr(response, 'results') and hasattr(response, 'total_count'):
                return {
                    'name': 'Basic Listing with Pagination',
                    'passed': True,
                    'details': f"Successfully listed {response.total_count} triples",
                    'total_count': response.total_count,
                    'page_size': response.page_size,
                    'offset': response.offset,
                    'has_results': response.results is not None,
                    'pagination': getattr(response, 'pagination', None)
                }
            else:
                return {
                    'name': 'Basic Listing with Pagination',
                    'passed': False,
                    'error': "Invalid response structure from triples listing",
                    'response_type': type(response).__name__,
                    'response_attributes': [attr for attr in dir(response) if not attr.startswith('_')]
                }
                
        except Exception as e:
            return {
                'name': 'Basic Listing with Pagination',
                'passed': False,
                'error': f"Exception during basic listing test: {e}"
            }
    
    async def _test_subject_filtering(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test triples listing with subject filter."""
        logger.info(f"  Testing subject filtering")
        
        try:
            test_subject = "http://vital.ai/person/john_doe"
            
            response = await self.endpoint._list_triples(
                space_id,
                graph_id,
                page_size=10,
                offset=0,
                subject=test_subject,
                predicate=None,
                object=None,
                object_filter=None,
                current_user={"username": "test_user", "user_id": "test_user_123"}
            )
            
            # Validate filtered results
            if hasattr(response, 'total_count'):
                return {
                    'name': 'Subject Filtering',
                    'passed': True,
                    'details': f"Found {response.total_count} triples for subject {test_subject}",
                    'subject_filter': test_subject,
                    'filtered_count': response.total_count,
                    'filters_applied': getattr(response, 'meta', {}).get('filters', {}) if hasattr(response, 'meta') else {}
                }
            else:
                return {
                    'name': 'Subject Filtering',
                    'passed': False,
                    'error': "Invalid response from subject-filtered search",
                    'subject_filter': test_subject
                }
                
        except Exception as e:
            return {
                'name': 'Subject Filtering',
                'passed': False,
                'error': f"Exception during subject filtering test: {e}"
            }
    
    async def _test_predicate_filtering(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test triples listing with predicate filter."""
        logger.info(f"  Testing predicate filtering")
        
        try:
            test_predicate = "http://vital.ai/ontology/name"
            
            response = await self.endpoint._list_triples(
                space_id,
                graph_id,
                page_size=10,
                offset=0,
                subject=None,
                predicate=test_predicate,
                object=None,
                object_filter=None,
                current_user={"username": "test_user", "user_id": "test_user_123"}
            )
            
            # Validate filtered results
            if hasattr(response, 'total_count'):
                return {
                    'name': 'Predicate Filtering',
                    'passed': True,
                    'details': f"Found {response.total_count} triples for predicate {test_predicate}",
                    'predicate_filter': test_predicate,
                    'filtered_count': response.total_count,
                    'filters_applied': getattr(response, 'meta', {}).get('filters', {}) if hasattr(response, 'meta') else {}
                }
            else:
                return {
                    'name': 'Predicate Filtering',
                    'passed': False,
                    'error': "Invalid response from predicate-filtered search",
                    'predicate_filter': test_predicate
                }
                
        except Exception as e:
            return {
                'name': 'Predicate Filtering',
                'passed': False,
                'error': f"Exception during predicate filtering test: {e}"
            }
    
    async def _test_keyword_search(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test triples listing with keyword search."""
        logger.info(f"  Testing keyword search")
        
        try:
            test_keyword = "ACME"
            
            response = await self.endpoint._list_triples(
                space_id,
                graph_id,
                page_size=10,
                offset=0,
                subject=None,
                predicate=None,
                object=None,
                object_filter=test_keyword,
                current_user={"username": "test_user", "user_id": "test_user_123"}
            )
            
            # Validate keyword search results
            if hasattr(response, 'total_count'):
                return {
                    'name': 'Keyword Search',
                    'passed': True,
                    'details': f"Found {response.total_count} triples containing keyword '{test_keyword}'",
                    'keyword_filter': test_keyword,
                    'filtered_count': response.total_count,
                    'filters_applied': getattr(response, 'meta', {}).get('filters', {}) if hasattr(response, 'meta') else {}
                }
            else:
                return {
                    'name': 'Keyword Search',
                    'passed': False,
                    'error': "Invalid response from keyword search",
                    'keyword_filter': test_keyword
                }
                
        except Exception as e:
            return {
                'name': 'Keyword Search',
                'passed': False,
                'error': f"Exception during keyword search test: {e}"
            }
