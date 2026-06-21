#!/usr/bin/env python3
"""
Segmentation Config Creation Test Case

Client-based test case for segmentation config creation using VitalGraph client.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class ConfigCreateTester:
    """Test case for segmentation config creation."""

    def __init__(self, client):
        self.client = client

    async def run_tests(self, space_id: str) -> Dict[str, Any]:
        """
        Run segmentation config creation tests.

        Returns:
            Test results dictionary
        """
        results = []

        basic_result = await self._test_basic_create(space_id)
        results.append(basic_result)

        passed_tests = sum(1 for r in results if r['passed'])

        return {
            'name': 'Config Create Tests',
            'passed': passed_tests == len(results),
            'total_tests': len(results),
            'passed_tests': passed_tests,
            'results': results,
        }

    async def _test_basic_create(self, space_id: str) -> Dict[str, Any]:
        """Test basic segmentation config creation."""
        try:
            response = await self.client.create_segmentation_config(
                space_id=space_id,
                document_type_uri="urn:test:doctype:article",
                segment_method_uri="urn:segmethod:sentence_window",
                max_segment_tokens=256,
                min_segment_tokens=32,
                overlap_tokens=16,
                enabled=True,
                auto_vectorize=False,
            )

            if response and response.get("config_id"):
                return {
                    'name': 'Basic Config Creation',
                    'passed': True,
                    'details': f"Created config id={response['config_id']}",
                    'config_id': response['config_id'],
                }
            else:
                return {
                    'name': 'Basic Config Creation',
                    'passed': False,
                    'error': f"Unexpected response: {response}",
                }

        except Exception as e:
            return {
                'name': 'Basic Config Creation',
                'passed': False,
                'error': f"Exception: {e}",
            }
