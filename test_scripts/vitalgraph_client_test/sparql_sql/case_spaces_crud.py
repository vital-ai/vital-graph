"""
Spaces CRUD Test Case — SPARQL-SQL Backend

Tests space lifecycle: list, create, get, get_info, update, verify.
"""

import logging
from typing import Dict, Any

from vitalgraph.model.spaces_model import Space

logger = logging.getLogger(__name__)


class SpacesCrudTester:
    """Client-based test for spaces CRUD against sparql_sql backend."""

    def __init__(self, client):
        self.client = client

    async def run_tests(self, space_id: str, space_name: str) -> Dict[str, Any]:
        """
        Run spaces CRUD tests.  Creates the space used by subsequent test cases.

        Args:
            space_id: Test space identifier to create
            space_name: Human-readable name for the space

        Returns:
            Standard test results dict
        """
        results = {
            "test_name": "Spaces CRUD",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
        }

        logger.info(f"\n{'=' * 80}")
        logger.info(f"  Spaces CRUD")
        logger.info(f"{'=' * 80}")

        # --- 1. List spaces (baseline) ---
        results["tests_run"] += 1
        try:
            resp = await self.client.spaces.list_spaces()
            if resp.is_success:
                logger.info(f"✅ PASS: List spaces — {len(resp.spaces)} existing")
                results["tests_passed"] += 1
            else:
                raise Exception(resp.error_message)
        except Exception as e:
            logger.error(f"❌ FAIL: List spaces — {e}")
            results["errors"].append(f"List spaces: {e}")

        # --- 2. Create space ---
        results["tests_run"] += 1
        try:
            space = Space(space=space_id, space_name=space_name,
                          space_description="Automated CRUD test space for sparql_sql backend")
            cr = await self.client.spaces.create_space(space)
            if cr.is_success:
                logger.info(f"✅ PASS: Create space '{space_id}'")
                results["tests_passed"] += 1
            else:
                raise Exception(cr.error_message)
        except Exception as e:
            logger.error(f"❌ FAIL: Create space — {e}")
            results["errors"].append(f"Create space: {e}")
            return results  # can't continue without a space

        # --- 4. Get space ---
        results["tests_run"] += 1
        try:
            gr = await self.client.spaces.get_space(space_id)
            if gr.is_success and gr.space and gr.space.space == space_id:
                logger.info(f"✅ PASS: Get space — name='{gr.space.space_name}'")
                results["tests_passed"] += 1
            else:
                raise Exception(getattr(gr, "error_message", "unexpected"))
        except Exception as e:
            logger.error(f"❌ FAIL: Get space — {e}")
            results["errors"].append(f"Get space: {e}")

        # --- 5. Get space info ---
        results["tests_run"] += 1
        try:
            ir = await self.client.spaces.get_space_info(space_id)
            if ir.is_success:
                logger.info(f"✅ PASS: Get space info — stats={ir.statistics is not None}")
                results["tests_passed"] += 1
            else:
                raise Exception(getattr(ir, "error_message", "unexpected"))
        except Exception as e:
            logger.error(f"❌ FAIL: Get space info — {e}")
            results["errors"].append(f"Get space info: {e}")

        # --- 6. Update space ---
        results["tests_run"] += 1
        try:
            updated = Space(space=space_id, space_name=f"{space_name} (updated)")
            ur = await self.client.spaces.update_space(space_id, updated)
            if ur.is_success:
                logger.info(f"✅ PASS: Update space name")
                results["tests_passed"] += 1
            else:
                raise Exception(getattr(ur, "error_message", "unexpected"))
        except Exception as e:
            logger.error(f"❌ FAIL: Update space — {e}")
            results["errors"].append(f"Update space: {e}")

        # --- 7. Verify update ---
        results["tests_run"] += 1
        try:
            gr2 = await self.client.spaces.get_space(space_id)
            if gr2.is_success and gr2.space and "updated" in (gr2.space.space_name or ""):
                logger.info(f"✅ PASS: Verify updated name")
                results["tests_passed"] += 1
            else:
                raise Exception(f"got '{getattr(gr2.space, 'space_name', None)}'")
        except Exception as e:
            logger.error(f"❌ FAIL: Verify updated name — {e}")
            results["errors"].append(f"Verify updated name: {e}")

        # --- 8. List spaces includes test space ---
        results["tests_run"] += 1
        try:
            resp2 = await self.client.spaces.list_spaces()
            found = any(s.space == space_id for s in resp2.spaces)
            if found:
                logger.info(f"✅ PASS: List spaces includes '{space_id}'")
                results["tests_passed"] += 1
            else:
                raise Exception("test space not found in list")
        except Exception as e:
            logger.error(f"❌ FAIL: List spaces after create — {e}")
            results["errors"].append(f"List spaces after create: {e}")

        return results
