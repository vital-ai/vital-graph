#!/usr/bin/env python3
"""
Segmentation Config Delete Test Case

Client-based test case for deleting segmentation configs using VitalGraph client.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class ConfigDeleteTester:
    """Test case for segmentation config deletion."""

    def __init__(self, client):
        self.client = client

    async def run_tests(self, space_id: str, config_id: int) -> Dict[str, Any]:
        """
        Run segmentation config delete tests.

        Args:
            space_id: Space identifier
            config_id: ID of config to delete

        Returns:
            Test results dictionary
        """
        results = []

        delete_result = await self._test_delete_config(space_id, config_id)
        results.append(delete_result)

        verify_result = await self._test_verify_deleted(space_id, config_id)
        results.append(verify_result)

        passed_tests = sum(1 for r in results if r['passed'])

        return {
            'name': 'Config Delete Tests',
            'passed': passed_tests == len(results),
            'total_tests': len(results),
            'passed_tests': passed_tests,
            'results': results,
        }

    async def _test_delete_config(self, space_id: str, config_id: int) -> Dict[str, Any]:
        """Test deleting a config."""
        try:
            response = await self.client.delete_segmentation_config(
                space_id=space_id,
                config_id=config_id,
            )

            if response and response.get("success"):
                return {
                    'name': 'Delete Config',
                    'passed': True,
                    'details': f"Deleted config {config_id}",
                }
            else:
                return {
                    'name': 'Delete Config',
                    'passed': False,
                    'error': f"Unexpected response: {response}",
                }

        except Exception as e:
            return {
                'name': 'Delete Config',
                'passed': False,
                'error': f"Exception: {e}",
            }

    async def _test_verify_deleted(self, space_id: str, config_id: int) -> Dict[str, Any]:
        """Verify config no longer appears in list after deletion."""
        try:
            response = await self.client.list_segmentation_configs(
                space_id=space_id,
                enabled_only=False,
            )

            configs = response.get("configs", [])
            found = any(c.get("config_id") == config_id for c in configs)

            if not found:
                return {
                    'name': 'Verify Config Deleted',
                    'passed': True,
                    'details': f"Config {config_id} no longer in list",
                }
            else:
                return {
                    'name': 'Verify Config Deleted',
                    'passed': False,
                    'error': f"Config {config_id} still found after deletion",
                }

        except Exception as e:
            return {
                'name': 'Verify Config Deleted',
                'passed': False,
                'error': f"Exception: {e}",
            }
