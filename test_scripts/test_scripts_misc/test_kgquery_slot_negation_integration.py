#!/usr/bin/env python3
"""
KGQuery Slot Negation — Integration Test

Runs end-to-end tests for frame negate, slot not_exists, and slot is_empty
against a live VitalGraph server via the Python client.

Test data: 5 entities with controlled frame/slot structures.
See vitalgraph_client_test/kgqueries/case_slot_negation.py for details.

Usage:
    python test_kgquery_slot_negation_integration.py
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.spaces_model import Space
from vitalgraph_client_test.kgqueries.case_slot_negation import SlotNegationTester

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

SPACE_ID = "space_slot_negation_test"
GRAPH_ID = "urn:slot_negation_test_graph"


def print_section(title: str):
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


async def main() -> bool:
    print_section("KGQuery Slot Negation Integration Test")

    # ------------------------------------------------------------------
    # Connect
    # ------------------------------------------------------------------
    logger.info("Initializing VitalGraph client...")
    client = VitalGraphClient()
    await client.open()

    if not client.is_connected():
        logger.error("Connection failed!")
        return False
    logger.info("Connected.\n")

    # ------------------------------------------------------------------
    # Create / recreate test space
    # ------------------------------------------------------------------
    logger.info(f"Preparing test space: {SPACE_ID}")
    try:
        spaces_resp = await client.spaces.list_spaces()
        if spaces_resp.is_success:
            existing = next((s for s in spaces_resp.spaces if s.space == SPACE_ID), None)
            if existing:
                logger.info("  Deleting existing test space...")
                await client.spaces.delete_space(SPACE_ID)
    except Exception as e:
        logger.warning(f"  Could not check/delete existing space: {e}")

    space_data = Space(
        id=None,
        space=SPACE_ID,
        space_name="Slot Negation Test Space",
        space_description="Integration tests for frame/slot negation",
        tenant="test_tenant",
        update_time=None,
    )
    create_resp = await client.spaces.create_space(space_data)
    if not create_resp.is_success:
        logger.error(f"Failed to create space: {create_resp.error_message}")
        await client.close()
        return False
    logger.info(f"  Space created: {SPACE_ID}\n")

    # ------------------------------------------------------------------
    # Setup data & run tests
    # ------------------------------------------------------------------
    try:
        tester = SlotNegationTester(client, query_mode="edge")

        # Step 1 — Load test entities
        print_section("Step 1: Create Test Entities")
        ok = await tester.setup_data(SPACE_ID, GRAPH_ID)
        if not ok:
            logger.error("Data setup failed — aborting.")
            return False

        # Step 2 — Run negation tests
        print_section("Step 2: Run Negation Queries")
        results = await tester.run_tests(SPACE_ID, GRAPH_ID)

        # ------------------------------------------------------------------
        # Summary
        # ------------------------------------------------------------------
        print_section("Test Summary")
        passed = results["tests_passed"]
        total = results["tests_run"]
        failed = results["tests_failed"]

        for r in results["results"]:
            status = "PASS" if r["passed"] else "FAIL"
            logger.info(f"  [{status}] {r['name']}")

        logger.info(f"\n  {passed}/{total} passed, {failed} failed")

        if results["errors"]:
            logger.info("\n  Errors:")
            for err in results["errors"]:
                logger.info(f"    - {err}")

        return failed == 0

    finally:
        # ------------------------------------------------------------------
        # Cleanup
        # ------------------------------------------------------------------
        print_section("Cleanup")
        logger.info(f"  Test space preserved for inspection: {SPACE_ID}")
        logger.info(f"  Graph: {GRAPH_ID}")
        logger.info("  (Will be deleted on next run)\n")

        logger.info("  Closing client...")
        await client.close()
        logger.info("  Done.\n")


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
