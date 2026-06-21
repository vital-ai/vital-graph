#!/usr/bin/env python3
"""
Segmentation Config List Test Case

Client-based test case for listing segmentation configs using VitalGraph client.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class ConfigListTester:
    """Test case for segmentation config listing."""

    def __init__(self, client):
        self.client = client

    async def run_tests(self, space_id: str, expected_min: int = 1) -> Dict[str, Any]:
        """
        Run segmentation config list tests.

        Args:
            space_id: Space identifier
            expected_min: Minimum expected config count

        Returns:
            Test results dictionary
        """
        results = []

        list_result = await self._test_list_all(space_id, expected_min)
        results.append(list_result)

        enabled_result = await self._test_list_enabled_only(space_id)
        results.append(enabled_result)

        passed_tests = sum(1 for r in results if r['passed'])

        return {
            'name': 'Config List Tests',
            'passed': passed_tests == len(results),
            'total_tests': len(results),
            'passed_tests': passed_tests,
            'results': results,
        }

    async def _test_list_all(self, space_id: str, expected_min: int) -> Dict[str, Any]:
        """Test listing all configs."""
        try:
            response = await self.client.list_segmentation_configs(
                space_id=space_id,
                enabled_only=False,
            )

            configs = response.get("configs", [])
            total = response.get("total_count", len(configs))

            if total >= expected_min:
                return {
                    'name': 'List All Configs',
                    'passed': True,
                    'details': f"Found {total} config(s) (expected >= {expected_min})",
                }
            else:
                return {
                    'name': 'List All Configs',
                    'passed': False,
                    'error': f"Expected >= {expected_min} configs, got {total}",
                }

        except Exception as e:
            return {
                'name': 'List All Configs',
                'passed': False,
                'error': f"Exception: {e}",
            }

    async def _test_list_enabled_only(self, space_id: str) -> Dict[str, Any]:
        """Test listing only enabled configs."""
        try:
            response = await self.client.list_segmentation_configs(
                space_id=space_id,
                enabled_only=True,
            )

            configs = response.get("configs", [])
            # All returned configs should have enabled=True
            all_enabled = all(c.get("enabled", False) for c in configs)

            if all_enabled:
                return {
                    'name': 'List Enabled-Only Configs',
                    'passed': True,
                    'details': f"Found {len(configs)} enabled config(s), all have enabled=True",
                }
            else:
                return {
                    'name': 'List Enabled-Only Configs',
                    'passed': False,
                    'error': f"Some returned configs have enabled=False",
                }

        except Exception as e:
            return {
                'name': 'List Enabled-Only Configs',
                'passed': False,
                'error': f"Exception: {e}",
            }
