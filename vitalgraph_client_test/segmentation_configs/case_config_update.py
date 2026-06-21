#!/usr/bin/env python3
"""
Segmentation Config Update Test Case

Client-based test case for updating segmentation configs using VitalGraph client.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class ConfigUpdateTester:
    """Test case for segmentation config updating."""

    def __init__(self, client):
        self.client = client

    async def run_tests(self, space_id: str, config_id: int) -> Dict[str, Any]:
        """
        Run segmentation config update tests.

        Args:
            space_id: Space identifier
            config_id: ID of config to update

        Returns:
            Test results dictionary
        """
        results = []

        update_result = await self._test_update_tokens(space_id, config_id)
        results.append(update_result)

        disable_result = await self._test_disable_config(space_id, config_id)
        results.append(disable_result)

        passed_tests = sum(1 for r in results if r['passed'])

        return {
            'name': 'Config Update Tests',
            'passed': passed_tests == len(results),
            'total_tests': len(results),
            'passed_tests': passed_tests,
            'results': results,
        }

    async def _test_update_tokens(self, space_id: str, config_id: int) -> Dict[str, Any]:
        """Test updating token parameters on a config."""
        try:
            response = await self.client.update_segmentation_config(
                space_id=space_id,
                config_id=config_id,
                document_type_uri="urn:test:doctype:article",
                segment_method_uri="urn:segmethod:sentence_window",
                max_segment_tokens=512,
                min_segment_tokens=64,
                overlap_tokens=32,
                enabled=True,
                auto_vectorize=True,
            )

            if response and response.get("config_id") == config_id:
                updated_max = response.get("max_segment_tokens")
                if updated_max == 512:
                    return {
                        'name': 'Update Token Parameters',
                        'passed': True,
                        'details': f"Updated config {config_id}: max_segment_tokens=512",
                    }
                else:
                    return {
                        'name': 'Update Token Parameters',
                        'passed': False,
                        'error': f"max_segment_tokens expected 512, got {updated_max}",
                    }
            else:
                return {
                    'name': 'Update Token Parameters',
                    'passed': False,
                    'error': f"Unexpected response: {response}",
                }

        except Exception as e:
            return {
                'name': 'Update Token Parameters',
                'passed': False,
                'error': f"Exception: {e}",
            }

    async def _test_disable_config(self, space_id: str, config_id: int) -> Dict[str, Any]:
        """Test disabling a config."""
        try:
            response = await self.client.update_segmentation_config(
                space_id=space_id,
                config_id=config_id,
                document_type_uri="urn:test:doctype:article",
                segment_method_uri="urn:segmethod:sentence_window",
                max_segment_tokens=512,
                min_segment_tokens=64,
                overlap_tokens=32,
                enabled=False,
                auto_vectorize=True,
            )

            if response and response.get("enabled") is False:
                return {
                    'name': 'Disable Config',
                    'passed': True,
                    'details': f"Config {config_id} disabled successfully",
                }
            else:
                return {
                    'name': 'Disable Config',
                    'passed': False,
                    'error': f"Expected enabled=False, got: {response}",
                }

        except Exception as e:
            return {
                'name': 'Disable Config',
                'passed': False,
                'error': f"Exception: {e}",
            }
