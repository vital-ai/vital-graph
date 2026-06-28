#!/usr/bin/env python3
"""
Query Lead Data Test - Main Runner

Queries lead entity data that is already loaded in space_lead_dataset_test.
Does NOT reload data - assumes test_lead_entity_graph_dataset.py has been run.

Tests:
1. Entity queries (query_type="entity") - new query_entities() method
2. Frame queries (query_type="frame") - existing query_connections() method
3. total_count accuracy across paginated results
4. Cross-validation: entity query total vs frame query total for same criteria

Usage:
    /opt/homebrew/anaconda3/envs/vital-graph/bin/python vitalgraph_client_test/test_query_lead_data.py
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import List
from dotenv import load_dotenv

# Add project root to Python path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
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

# Import test case
from vitalgraph_client_test.entity_graph_lead_dataset.case_query_lead_data import QueryLeadDataTester


def print_section(title: str):
    """Print a formatted section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_test_summary(all_results: List[dict]) -> bool:
    """Print summary of all test results."""
    print_section("TEST SUMMARY")

    total_run = 0
    total_passed = 0
    total_failed = 0

    for result in all_results:
        total_run += result["tests_run"]
        total_passed += result["tests_passed"]
        total_failed += result["tests_failed"]

        status = "✅ PASS" if result["tests_failed"] == 0 else "❌ FAIL"
        print(f"{status}: {result['test_name']}")
        print(f"   Tests: {result['tests_passed']}/{result['tests_run']} passed")

        if result.get("errors"):
            print(f"   Errors:")
            for error in result["errors"][:5]:
                print(f"      • {error}")

    print(f"\n{'=' * 80}")
    print(f"OVERALL: {total_passed}/{total_run} tests passed")
    print(f"{'=' * 80}")

    return total_failed == 0


async def main():
    """Main test runner."""
    print_section("Query Lead Data Test Suite")

    # Configuration - must match what test_lead_entity_graph_dataset.py uses
    space_id = "space_lead_dataset_test"
    graph_id = "urn:lead_entity_graph_dataset"

    logger.info(f"Space ID: {space_id}")
    logger.info(f"Graph ID: {graph_id}")
    logger.info(f"Note: Assumes data is already loaded via test_lead_entity_graph_dataset.py")

    # Initialize client
    logger.info("\n🔌 Connecting to VitalGraph...")
    client = VitalGraphClient()

    logger.info("🔐 Connecting to VitalGraph server...")
    await client.open()
    if not client.is_connected():
        logger.error("❌ Connection failed!")
        return False
    logger.info("✅ Connected successfully\n")

    # Verify space exists
    try:
        spaces_response = await client.spaces.list_spaces()
        if spaces_response.is_success:
            existing_space = next((s for s in spaces_response.spaces if s.space == space_id), None)
            if not existing_space:
                logger.error(f"❌ Space '{space_id}' not found. Run test_lead_entity_graph_dataset.py first.")
                await client.close()
                return False
            logger.info(f"✅ Found existing space: {space_id}")
    except Exception as e:
        logger.error(f"❌ Error checking space: {e}")
        await client.close()
        return False

    # Verify entities exist by doing a quick list
    try:
        list_response = await client.kgentities.list_kgentities(
            space_id=space_id,
            graph_id=graph_id,
            page_size=1,
            offset=0,
            include_entity_graph=False
        )
        if list_response.is_success and list_response.objects:
            logger.info(f"✅ Entities found in graph (total_count: {list_response.total_count})\n")
        else:
            logger.error(f"❌ No entities found in {space_id}/{graph_id}. Load data first.")
            await client.close()
            return False
    except Exception as e:
        logger.error(f"❌ Error listing entities: {e}")
        await client.close()
        return False

    # Run tests
    all_results = []

    try:
        # Run query tests with edge mode (default)
        tester = QueryLeadDataTester(client, query_mode="edge")
        results = await tester.run_tests(space_id, graph_id)
        all_results.append(results)

        # Print summary
        success = print_test_summary(all_results)

        if success:
            print_section("✅ All Query Lead Data Tests Passed!")
        else:
            print_section("⚠️ Some Tests Failed")

        return success

    finally:
        await client.close()
        logger.info("✅ Client closed")


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
