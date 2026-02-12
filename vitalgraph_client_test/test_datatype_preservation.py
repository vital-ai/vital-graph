#!/usr/bin/env python3
"""
Datatype Preservation Test — Main Orchestrator

Tests that all DB write paths correctly preserve RDFLib datatype and language
metadata through to both Fuseki and PostgreSQL.  Verifies the fixes applied to:

  - Entity create/update/delete (kgentity_delete_impl, kgentity_update_impl)
  - Frame/slot create/update (kgframes_endpoint, kgentity_frame_create_impl)
  - KGType update (kgtypes_update_impl)
  - Relations update/upsert (kgrelations_endpoint)
  - Triples delete (triples_endpoint)

Uses space: dt_test, graph: urn:dt_test
"""

import asyncio
import logging
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add project root to Python path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Configure logging BEFORE imports to capture all module logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)
    logger.info(f"Loaded environment variables from {env_path}")
else:
    logger.warning(f".env file not found at {env_path}")

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.spaces_model import Space

# Import test case
from vitalgraph_client_test.datatypes.case_datatype_preservation import DatatypePreservationTester


def print_section(title: str):
    """Print a formatted section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def print_test_summary(all_results: list):
    """Print summary of all test results."""
    print_section("TEST SUMMARY")

    total_tests = 0
    total_passed = 0
    total_failed = 0

    for result in all_results:
        total_tests += result["tests_run"]
        total_passed += result["tests_passed"]
        total_failed += result["tests_failed"]

        status = "PASS" if result["tests_failed"] == 0 else "FAIL"
        print(f"{status}: {result['test_name']}")
        print(f"   Tests: {result['tests_passed']}/{result['tests_run']} passed")

        if result["errors"]:
            print(f"   Errors:")
            for error in result["errors"][:10]:
                print(f"      {error}")

    print(f"\n{'=' * 80}")
    print(f"OVERALL: {total_passed}/{total_tests} tests passed")
    print(f"{'=' * 80}\n")

    return total_failed == 0


async def main():
    """Run the datatype preservation tests."""

    print_section("Datatype Preservation Test Suite")

    # Initialize client
    logger.info("Initializing VitalGraph client...")
    client = VitalGraphClient()

    # Connect
    logger.info("Connecting to VitalGraph server...")
    await client.open()
    if not client.is_connected():
        logger.error("Connection failed!")
        return False
    logger.info("Connected successfully\n")

    # Test space config
    space_id = "dt_test"
    graph_id = "urn:dt_test"

    # Check if space already exists and delete it
    logger.info(f"Checking for existing test space: {space_id}")
    try:
        spaces_response = await client.spaces.list_spaces()
        if spaces_response.is_success:
            existing_space = next(
                (s for s in spaces_response.spaces if s.space == space_id), None
            )
            if existing_space:
                logger.info(f"   Found existing space, deleting...")
                delete_response = await client.spaces.delete_space(space_id)
                if delete_response.is_success:
                    logger.info(f"   Existing space deleted")
    except Exception as e:
        logger.info(f"   Note: Could not check/delete existing space: {e}")

    logger.info(f"Creating test space: {space_id}")
    space_data = Space(
        space=space_id,
        space_name="Datatype Preservation Test",
        space_description="Test space for verifying datatype preservation across all write paths",
        tenant="test_tenant",
    )
    create_response = await client.spaces.create_space(space_data)
    if not create_response.is_success:
        logger.error(f"Failed to create space: {create_response.error_message}")
        return False
    logger.info(
        f"Test space created: "
        f"{create_response.space.space if create_response.space else space_id}\n"
    )

    # Track all test results
    all_results = []

    try:
        # ==================================================================
        # Run datatype preservation tests
        # ==================================================================
        tester = DatatypePreservationTester(client)
        test_results = await tester.run_tests(space_id, graph_id)
        all_results.append(test_results)

        # ==================================================================
        # Print summary
        # ==================================================================
        success = print_test_summary(all_results)

        if success:
            print_section("All Tests Completed Successfully!")
        else:
            print_section("Some Tests Failed")

        return success

    finally:
        # Cleanup
        print_section("Cleanup")
        logger.info(
            f"Skipping space deletion -- space '{space_id}' preserved for inspection"
        )

        await client.close()
        logger.info("Client closed")


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
