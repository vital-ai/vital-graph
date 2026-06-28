#!/usr/bin/env python3
"""
KGType Documentation Test Case

Client-based test case for KGType documentation operations using VitalGraph client.
Tests get, update (create/update), and delete of type documentation.
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class KGTypeDocumentationTester:
    """Test case for KGType documentation operations."""

    def __init__(self, client):
        self.client = client

    async def run_tests(self, space_id: str, graph_id: str, type_uri: str) -> Dict[str, Any]:
        """
        Run KGType documentation tests against a single type.

        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            type_uri: URI of a type to test documentation on

        Returns:
            Test results dictionary
        """
        logger.info("📄 Testing KGType documentation operations...")

        results = []

        # Test 1: Get documentation (initially none)
        get_empty = await self._test_get_documentation_empty(space_id, graph_id, type_uri)
        results.append(get_empty)

        # Test 2: Create documentation
        create_result = await self._test_create_documentation(space_id, graph_id, type_uri)
        results.append(create_result)

        # Test 3: Get documentation (should exist now)
        get_exists = await self._test_get_documentation_exists(space_id, graph_id, type_uri)
        results.append(get_exists)

        # Test 4: Update documentation
        update_result = await self._test_update_documentation(space_id, graph_id, type_uri)
        results.append(update_result)

        # Test 5: Verify updated content
        verify_result = await self._test_verify_updated_content(space_id, graph_id, type_uri)
        results.append(verify_result)

        # Test 6: Delete documentation
        delete_result = await self._test_delete_documentation(space_id, graph_id, type_uri)
        results.append(delete_result)

        # Test 7: Verify documentation is gone
        get_gone = await self._test_get_documentation_empty(space_id, graph_id, type_uri)
        get_gone['name'] = 'Get Documentation After Delete (empty)'
        results.append(get_gone)

        passed_tests = sum(1 for r in results if r['passed'])
        logger.info(f"✅ KGType documentation tests completed: {passed_tests}/{len(results)} passed")

        return {
            'name': 'KGType Documentation Tests',
            'passed': passed_tests == len(results),
            'total_tests': len(results),
            'passed_tests': passed_tests,
            'results': results,
        }

    async def _test_get_documentation_empty(self, space_id: str, graph_id: str, type_uri: str) -> Dict[str, Any]:
        """Test getting documentation when none exists."""
        logger.info(f"  Testing get documentation (empty) for {type_uri}...")

        try:
            response = await self.client.kgtypes.get_type_documentation(space_id, graph_id, type_uri)

            if response.is_success and not response.has_documentation:
                return {
                    'name': 'Get Documentation (empty)',
                    'passed': True,
                    'details': 'No documentation found as expected',
                }
            elif response.is_success and response.has_documentation:
                return {
                    'name': 'Get Documentation (empty)',
                    'passed': False,
                    'error': 'Expected no documentation but found some',
                }
            else:
                return {
                    'name': 'Get Documentation (empty)',
                    'passed': False,
                    'error': response.error_message or 'Failed to get documentation',
                }
        except Exception as e:
            return {
                'name': 'Get Documentation (empty)',
                'passed': False,
                'error': f'Exception: {e}',
            }

    async def _test_create_documentation(self, space_id: str, graph_id: str, type_uri: str) -> Dict[str, Any]:
        """Test creating documentation for a type."""
        logger.info(f"  Testing create documentation for {type_uri}...")

        content = "# Test Type Documentation\n\nThis is **test documentation** for a KGType.\n\n## Properties\n\n- Property A\n- Property B"

        try:
            response = await self.client.kgtypes.update_type_documentation(
                space_id, graph_id, type_uri, content
            )

            if response.is_success and response.created:
                return {
                    'name': 'Create Documentation',
                    'passed': True,
                    'details': f'Created documentation with document_uri={response.document_uri}',
                    'document_uri': response.document_uri,
                }
            elif response.is_success:
                return {
                    'name': 'Create Documentation',
                    'passed': False,
                    'error': 'Expected created=True but got False',
                }
            else:
                return {
                    'name': 'Create Documentation',
                    'passed': False,
                    'error': response.error_message or 'Failed to create documentation',
                }
        except Exception as e:
            return {
                'name': 'Create Documentation',
                'passed': False,
                'error': f'Exception: {e}',
            }

    async def _test_get_documentation_exists(self, space_id: str, graph_id: str, type_uri: str) -> Dict[str, Any]:
        """Test getting documentation that exists."""
        logger.info(f"  Testing get documentation (exists) for {type_uri}...")

        try:
            response = await self.client.kgtypes.get_type_documentation(space_id, graph_id, type_uri)

            if response.is_success and response.has_documentation and response.content:
                return {
                    'name': 'Get Documentation (exists)',
                    'passed': True,
                    'details': f'Found documentation ({len(response.content)} chars)',
                    'content_length': len(response.content),
                    'document_uri': response.document_uri,
                }
            elif response.is_success:
                return {
                    'name': 'Get Documentation (exists)',
                    'passed': False,
                    'error': f'Expected documentation but has_documentation={response.has_documentation}',
                }
            else:
                return {
                    'name': 'Get Documentation (exists)',
                    'passed': False,
                    'error': response.error_message or 'Failed to get documentation',
                }
        except Exception as e:
            return {
                'name': 'Get Documentation (exists)',
                'passed': False,
                'error': f'Exception: {e}',
            }

    async def _test_update_documentation(self, space_id: str, graph_id: str, type_uri: str) -> Dict[str, Any]:
        """Test updating existing documentation."""
        logger.info(f"  Testing update documentation for {type_uri}...")

        updated_content = "# Updated Documentation\n\nThis documentation has been **updated**.\n\n## New Section\n\nNew content here."

        try:
            response = await self.client.kgtypes.update_type_documentation(
                space_id, graph_id, type_uri, updated_content
            )

            if response.is_success and not response.created:
                return {
                    'name': 'Update Documentation',
                    'passed': True,
                    'details': f'Updated documentation (created={response.created})',
                }
            elif response.is_success:
                # created=True means the doc was recreated; still acceptable
                return {
                    'name': 'Update Documentation',
                    'passed': True,
                    'details': f'Documentation upserted (created={response.created})',
                }
            else:
                return {
                    'name': 'Update Documentation',
                    'passed': False,
                    'error': response.error_message or 'Failed to update documentation',
                }
        except Exception as e:
            return {
                'name': 'Update Documentation',
                'passed': False,
                'error': f'Exception: {e}',
            }

    async def _test_verify_updated_content(self, space_id: str, graph_id: str, type_uri: str) -> Dict[str, Any]:
        """Verify the documentation content was actually updated."""
        logger.info(f"  Testing verify updated content for {type_uri}...")

        try:
            response = await self.client.kgtypes.get_type_documentation(space_id, graph_id, type_uri)

            if response.is_success and response.has_documentation and response.content:
                has_updated = 'Updated Documentation' in response.content
                return {
                    'name': 'Verify Updated Content',
                    'passed': has_updated,
                    'details': f'Content check: updated marker {"found" if has_updated else "NOT found"}',
                }
            else:
                return {
                    'name': 'Verify Updated Content',
                    'passed': False,
                    'error': 'No documentation found to verify',
                }
        except Exception as e:
            return {
                'name': 'Verify Updated Content',
                'passed': False,
                'error': f'Exception: {e}',
            }

    async def _test_delete_documentation(self, space_id: str, graph_id: str, type_uri: str) -> Dict[str, Any]:
        """Test deleting documentation."""
        logger.info(f"  Testing delete documentation for {type_uri}...")

        try:
            response = await self.client.kgtypes.delete_type_documentation(space_id, graph_id, type_uri)

            if response.is_success and response.deleted:
                return {
                    'name': 'Delete Documentation',
                    'passed': True,
                    'details': 'Documentation deleted successfully',
                }
            elif response.is_success:
                return {
                    'name': 'Delete Documentation',
                    'passed': False,
                    'error': 'Expected deleted=True but got False',
                }
            else:
                return {
                    'name': 'Delete Documentation',
                    'passed': False,
                    'error': response.error_message or 'Failed to delete documentation',
                }
        except Exception as e:
            return {
                'name': 'Delete Documentation',
                'passed': False,
                'error': f'Exception: {e}',
            }
