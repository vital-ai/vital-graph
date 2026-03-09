#!/usr/bin/env python3
"""
SPARQL-SQL Backend CRUD Test — Spaces, Graphs, Triples

Orchestrator that validates basic CRUD operations against the sparql_sql backend
using modular test cases in vitalgraph_client_test/sparql_sql/.

Test Flow:
  1. Spaces  — list, create, get, get_info, update, verify
  2. Graphs  — list, create, get_info, clear, drop, verify
  3. Triples — add, list, filter, delete, verify deletion
  4. Cleanup — delete test space (unless DELETE_SPACE_AT_END is False)
"""

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import List, Dict, Any

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Path & env setup
# ---------------------------------------------------------------------------
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path)

# ---------------------------------------------------------------------------
# Imports (after path setup)
# ---------------------------------------------------------------------------
from vitalgraph.client.vitalgraph_client import VitalGraphClient

# Modular test cases
from vitalgraph_client_test.sparql_sql.case_spaces_crud import SpacesCrudTester
from vitalgraph_client_test.sparql_sql.case_graphs_crud import GraphsCrudTester
from vitalgraph_client_test.sparql_sql.case_triples_crud import TriplesCrudTester
from vitalgraph_client_test.sparql_sql.case_objects_crud import ObjectsCrudTester
from vitalgraph_client_test.sparql_sql.case_kgtypes_crud import KGTypesCrudTester
from vitalgraph_client_test.sparql_sql.case_files_crud import FilesCrudTester
from vitalgraph_client_test.sparql_sql.case_kgentities_crud import KGEntitiesCrudTester

# ===========================================================================
# Configuration
# ===========================================================================
TEST_SPACE_ID = "sp_sql_crud"
TEST_SPACE_NAME = "SPARQL-SQL CRUD Test Space"
TEST_GRAPH_ID = "urn:sql_triples"
SECONDARY_GRAPH_ID = "urn:sql_graphs"
OBJECTS_GRAPH_ID = "urn:sql_objects"
KGTYPES_GRAPH_ID = "urn:sql_kgtypes"
FILES_GRAPH_ID = "urn:sql_files"
KGENTITIES_GRAPH_ID = "urn:sql_kgentities"

# Set to False to keep the test space intact for post-run inspection
DELETE_SPACE_AT_END = True


# ===========================================================================
# Helpers
# ===========================================================================
def print_section(title: str):
    """Print a formatted section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_test_summary(all_results: List[Dict[str, Any]]) -> bool:
    """Print summary of all test results. Returns True if all passed."""
    print_section("TEST SUMMARY")

    total_run = total_passed = total_failed = 0
    all_success = True

    for result in all_results:
        total_run += result["tests_run"]
        total_passed += result["tests_passed"]
        total_failed += result["tests_failed"]

        if result["tests_failed"] > 0:
            all_success = False
            status = "❌ FAIL"
        else:
            status = "✅ PASS"

        print(f"{status}: {result['test_name']}")
        print(f"   Tests: {result['tests_passed']}/{result['tests_run']} passed")

        if result["errors"]:
            print(f"   Errors:")
            for error in result["errors"]:
                print(f"      • {error}")

    print("\n" + "=" * 80)
    print(f"OVERALL: {total_passed}/{total_run} tests passed")
    print("=" * 80)

    return all_success


# ===========================================================================
# Main
# ===========================================================================
async def main():
    print_section("SPARQL-SQL Backend CRUD Tests")
    print(f"  Space:    {TEST_SPACE_ID}")
    print(f"  Graph:    {TEST_GRAPH_ID}")
    print(f"  Cleanup:  {'delete space at end' if DELETE_SPACE_AT_END else 'KEEP space for inspection'}")

    # Connect client
    client = VitalGraphClient()
    await client.open()
    if not client.is_connected():
        logger.error("❌ Failed to connect to VitalGraph server")
        return False
    logger.info("\n✅ Connected to VitalGraph server\n")

    all_results: List[Dict[str, Any]] = []
    t0 = time.time()

    try:
        # ==================================================================
        # Pre-test cleanup: delete the test space if it already exists
        # ==================================================================
        resp = await client.spaces.list_spaces()
        existing_ids = [s.space for s in resp.spaces] if resp.is_success else []
        logger.info(f"  Existing spaces: {existing_ids}")
        if TEST_SPACE_ID in existing_ids:
            logger.info(f"  Deleting pre-existing space '{TEST_SPACE_ID}'...")
            await client.spaces.delete_space(TEST_SPACE_ID)
            logger.info(f"  ✅ Pre-existing space deleted")

        # ==================================================================
        # STEP 1: Spaces CRUD (creates the test space)
        # ==================================================================
        spaces_tester = SpacesCrudTester(client)
        spaces_results = await spaces_tester.run_tests(TEST_SPACE_ID, TEST_SPACE_NAME)
        all_results.append(spaces_results)

        if spaces_results["tests_failed"] > 0:
            logger.error("❌ Spaces CRUD failed — cannot continue without a space")
            return print_test_summary(all_results)

        # ==================================================================
        # STEP 2: Graphs CRUD (uses a secondary graph inside the test space)
        # ==================================================================
        graphs_tester = GraphsCrudTester(client)
        graphs_results = await graphs_tester.run_tests(TEST_SPACE_ID, SECONDARY_GRAPH_ID)
        all_results.append(graphs_results)

        # ==================================================================
        # STEP 3: Triples CRUD (uses the primary test graph)
        # ==================================================================
        triples_tester = TriplesCrudTester(client)
        triples_results = await triples_tester.run_tests(TEST_SPACE_ID, TEST_GRAPH_ID)
        all_results.append(triples_results)

        # ==================================================================
        # STEP 4: Objects CRUD (uses a dedicated objects graph)
        # ==================================================================
        objects_tester = ObjectsCrudTester(client)
        objects_results = await objects_tester.run_tests(TEST_SPACE_ID, OBJECTS_GRAPH_ID)
        all_results.append(objects_results)

        # ==================================================================
        # STEP 5: KGTypes CRUD (uses a dedicated kgtypes graph)
        # ==================================================================
        kgtypes_tester = KGTypesCrudTester(client)
        kgtypes_results = await kgtypes_tester.run_tests(TEST_SPACE_ID, KGTYPES_GRAPH_ID)
        all_results.append(kgtypes_results)

        # ==================================================================
        # STEP 6: Files CRUD (uses a dedicated files graph)
        # ==================================================================
        files_tester = FilesCrudTester(client)
        files_results = await files_tester.run_tests(TEST_SPACE_ID, FILES_GRAPH_ID)
        all_results.append(files_results)

        # ==================================================================
        # STEP 7: KGEntities CRUD (uses a dedicated kgentities graph)
        # ==================================================================
        kgentities_tester = KGEntitiesCrudTester(client)
        kgentities_results = await kgentities_tester.run_tests(TEST_SPACE_ID, KGENTITIES_GRAPH_ID)
        all_results.append(kgentities_results)

        # ==================================================================
        # Summary
        # ==================================================================
        success = print_test_summary(all_results)

        elapsed = time.time() - t0
        print(f"\n⏱️  Total elapsed: {elapsed:.2f}s")

        if success:
            print_section("✅ All Tests Completed Successfully!")
        else:
            print_section("⚠️ Some Tests Failed")

        return success

    finally:
        # ==================================================================
        # Cleanup
        # ==================================================================
        print_section("Cleanup")
        if DELETE_SPACE_AT_END:
            logger.info(f"   Deleting test space '{TEST_SPACE_ID}'...")
            try:
                dr = await client.spaces.delete_space(TEST_SPACE_ID)
                if dr.is_success:
                    logger.info(f"   ✅ Test space deleted")
                else:
                    logger.warning(f"   ⚠️  Failed to delete: {dr.error_message}")
            except Exception as e:
                logger.warning(f"   ⚠️  Exception during cleanup: {e}")
        else:
            logger.info(f"   ℹ️  Keeping test space '{TEST_SPACE_ID}' for inspection")
            logger.info(f"       Set DELETE_SPACE_AT_END = True to auto-delete")

        await client.close()
        logger.info(f"   ✅ Client closed")


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
