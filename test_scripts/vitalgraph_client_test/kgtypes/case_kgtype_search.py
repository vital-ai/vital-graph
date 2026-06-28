#!/usr/bin/env python3
"""
KGType Search Test Case

Client-based test case for KGType search operations using VitalGraph client.
Tests keyword search with optional type filtering.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class KGTypeSearchTester:
    """Test case for KGType search operations."""

    def __init__(self, client):
        self.client = client

    async def run_tests(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """
        Run KGType search tests.

        Args:
            space_id: Space identifier
            graph_id: Graph identifier

        Returns:
            Test results dictionary
        """
        logger.info("🔍 Testing KGType search operations...")

        results = []

        # Test 1: Basic keyword search
        basic_result = await self._test_basic_search(space_id, graph_id)
        results.append(basic_result)

        # Test 2: Search with type filter
        filtered_result = await self._test_search_with_type_filter(space_id, graph_id)
        results.append(filtered_result)

        # Test 3: Search with no matches
        empty_result = await self._test_search_no_matches(space_id, graph_id)
        results.append(empty_result)

        # Test 4: List with type_uri filter (new param)
        type_uri_result = await self._test_list_with_type_uri(space_id, graph_id)
        results.append(type_uri_result)

        passed_tests = sum(1 for r in results if r['passed'])
        logger.info(f"✅ KGType search tests completed: {passed_tests}/{len(results)} passed")

        return {
            'name': 'KGType Search Tests',
            'passed': passed_tests == len(results),
            'total_tests': len(results),
            'passed_tests': passed_tests,
            'results': results,
        }

    async def _test_basic_search(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test basic keyword search for types."""
        logger.info("  Testing basic keyword search...")

        try:
            response = await self.client.kgtypes.search_types(
                space_id, graph_id, query="Entity"
            )

            if response.is_success:
                return {
                    'name': 'Basic Keyword Search',
                    'passed': True,
                    'details': f"Found {response.count} types matching 'Entity'",
                    'count': response.count,
                    'search_mode': response.search_mode,
                }
            else:
                return {
                    'name': 'Basic Keyword Search',
                    'passed': False,
                    'error': response.error_message or 'Search failed',
                }
        except Exception as e:
            return {
                'name': 'Basic Keyword Search',
                'passed': False,
                'error': f'Exception: {e}',
            }

    async def _test_search_with_type_filter(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test keyword search with type filter."""
        logger.info("  Testing search with type filter...")

        try:
            response = await self.client.kgtypes.search_types(
                space_id, graph_id, query="type", type="entity"
            )

            if response.is_success:
                return {
                    'name': 'Search with Type Filter',
                    'passed': True,
                    'details': f"Found {response.count} entity types matching 'type'",
                    'count': response.count,
                }
            else:
                return {
                    'name': 'Search with Type Filter',
                    'passed': False,
                    'error': response.error_message or 'Filtered search failed',
                }
        except Exception as e:
            return {
                'name': 'Search with Type Filter',
                'passed': False,
                'error': f'Exception: {e}',
            }

    async def _test_search_no_matches(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test search that should return no matches."""
        logger.info("  Testing search with no matches...")

        try:
            response = await self.client.kgtypes.search_types(
                space_id, graph_id, query="zzz_nonexistent_xyz_12345"
            )

            if response.is_success and response.count == 0:
                return {
                    'name': 'Search No Matches',
                    'passed': True,
                    'details': 'Correctly returned 0 results for nonsense query',
                }
            elif response.is_success:
                return {
                    'name': 'Search No Matches',
                    'passed': False,
                    'error': f'Expected 0 results but got {response.count}',
                }
            else:
                return {
                    'name': 'Search No Matches',
                    'passed': False,
                    'error': response.error_message or 'Search failed',
                }
        except Exception as e:
            return {
                'name': 'Search No Matches',
                'passed': False,
                'error': f'Exception: {e}',
            }

    async def _test_list_with_type_uri(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test list_kgtypes with type_uri filter parameter."""
        logger.info("  Testing list with type_uri filter...")

        entity_type_uri = "http://vital.ai/ontology/haley-ai-kg#KGEntityType"

        try:
            response = await self.client.kgtypes.list_kgtypes(
                space_id, graph_id, page_size=100, type_uri=entity_type_uri
            )

            if response.is_success:
                return {
                    'name': 'List with type_uri Filter',
                    'passed': True,
                    'details': f"Found {response.count} KGEntityType objects",
                    'count': response.count,
                }
            else:
                return {
                    'name': 'List with type_uri Filter',
                    'passed': False,
                    'error': response.error_message or 'Filtered list failed',
                }
        except Exception as e:
            return {
                'name': 'List with type_uri Filter',
                'passed': False,
                'error': f'Exception: {e}',
            }
