#!/usr/bin/env python3
"""
SPARQL-SQL Backend — Lead Entity CRUD Test

Loads real lead entity graphs from N-Triples files (first 3 leads),
runs full CRUD lifecycle per lead using the existing entity_graph_lead
test case modules.

Mirrors test_lead_entity_graph.py flow against the sparql_sql backend.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import List

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
from vitalgraph.model.spaces_model import Space

from vitalgraph_client_test.entity_graph_lead.case_load_lead_graph import LoadLeadGraphTester
from vitalgraph_client_test.entity_graph_lead.case_verify_lead_graph import VerifyLeadGraphTester
from vitalgraph_client_test.entity_graph_lead.case_query_lead_graph import QueryLeadGraphTester
from vitalgraph_client_test.entity_graph_lead.case_frame_operations import LeadFrameOperationsTester
from vitalgraph_client_test.entity_graph_lead.case_delete_lead_graph import DeleteLeadGraphTester

# ===========================================================================
# Configuration
# ===========================================================================
TEST_SPACE_ID = "sp_sql_lead_crud"
TEST_SPACE_NAME = "SPARQL-SQL Lead Entity CRUD Test Space"
TEST_GRAPH_ID = "urn:sql_lead_crud"
LEAD_DATA_DIR = project_root / "lead_test_data"
LEAD_FILE_LIMIT = 3

DELETE_SPACE_AT_END = True


def get_lead_files(lead_data_dir: Path, limit: int = None) -> List[Path]:
    """Get sorted list of lead .nt files, optionally limited."""
    nt_files = sorted(lead_data_dir.glob("lead_*.nt"))
    if limit:
        nt_files = nt_files[:limit]
    return nt_files


# ===========================================================================
# Main
# ===========================================================================
async def main():
    print("\n" + "=" * 80)
    print("  SPARQL-SQL Backend — Lead Entity CRUD Test")
    print("=" * 80)
    print(f"  Space:  {TEST_SPACE_ID}")
    print(f"  Graph:  {TEST_GRAPH_ID}")
    print(f"  Data:   {LEAD_DATA_DIR}")
    print(f"  Limit:  {LEAD_FILE_LIMIT} files")

    # Check data directory
    if not LEAD_DATA_DIR.exists():
        logger.error(f"❌ Lead data directory not found: {LEAD_DATA_DIR}")
        return False

    lead_files = get_lead_files(LEAD_DATA_DIR, limit=LEAD_FILE_LIMIT)
    if not lead_files:
        logger.error(f"❌ No lead .nt files found in {LEAD_DATA_DIR}")
        return False
    logger.info(f"  Found {len(lead_files)} lead file(s)\n")

    client = VitalGraphClient()
    await client.open()
    if not client.is_connected():
        logger.error("❌ Failed to connect to VitalGraph server")
        return False
    logger.info("✅ Connected to VitalGraph server\n")

    t0 = time.time()
    all_results: List[dict] = []

    try:
        # Pre-test cleanup
        resp = await client.spaces.list_spaces()
        existing_ids = [s.space for s in resp.spaces] if resp.is_success else []
        if TEST_SPACE_ID in existing_ids:
            logger.info(f"  Deleting pre-existing space '{TEST_SPACE_ID}'...")
            await client.spaces.delete_space(TEST_SPACE_ID)

        # Create space + graph
        space = Space(space=TEST_SPACE_ID, space_name=TEST_SPACE_NAME,
                      space_description="Lead entity CRUD test (sparql_sql)")
        cr = await client.spaces.create_space(space)
        if not cr.is_success:
            logger.error(f"❌ Failed to create space: {cr.error_message}")
            return False
        logger.info(f"  ✅ Space '{TEST_SPACE_ID}' created")

        await client.graphs.create_graph(TEST_SPACE_ID, TEST_GRAPH_ID)
        logger.info(f"  ✅ Graph '{TEST_GRAPH_ID}' created\n")

        # Process each lead file
        for idx, lead_file in enumerate(lead_files, 1):
            print(f"\n{'#' * 80}")
            print(f"  Lead {idx}/{len(lead_files)}: {lead_file.name}")
            print(f"{'#' * 80}")

            # Step 1: Load
            load_tester = LoadLeadGraphTester(client)
            load_results = await load_tester.run_tests(TEST_SPACE_ID, TEST_GRAPH_ID, str(lead_file))
            all_results.append(load_results)

            if load_results["tests_failed"] > 0:
                logger.error(f"❌ Load failed for {lead_file.name} — skipping remaining steps")
                continue

            entity_uri = load_results.get("entity_uri")
            if not entity_uri:
                logger.error(f"❌ No entity URI from {lead_file.name}")
                continue

            # Step 2: Verify
            verify_tester = VerifyLeadGraphTester(client)
            verify_results = await verify_tester.run_tests(
                TEST_SPACE_ID, TEST_GRAPH_ID, entity_uri,
                expected_triple_count=load_results.get("triple_count"))
            all_results.append(verify_results)

            # Step 3: Query
            query_tester = QueryLeadGraphTester(client)
            query_results = await query_tester.run_tests(TEST_SPACE_ID, TEST_GRAPH_ID, entity_uri)
            all_results.append(query_results)

            # Step 4: Frame operations
            frame_tester = LeadFrameOperationsTester(client)
            frame_results = await frame_tester.run_tests(
                TEST_SPACE_ID, TEST_GRAPH_ID, entity_uri,
                lead_id=load_results.get("lead_id", "unknown"))
            all_results.append(frame_results)

            # Step 5: Delete
            delete_tester = DeleteLeadGraphTester(client)
            delete_results = await delete_tester.run_tests(TEST_SPACE_ID, TEST_GRAPH_ID, entity_uri)
            all_results.append(delete_results)

        # Summary
        elapsed = time.time() - t0
        total_run = sum(r["tests_run"] for r in all_results)
        total_passed = sum(r["tests_passed"] for r in all_results)
        total_failed = sum(r["tests_failed"] for r in all_results)
        all_errors = [e for r in all_results for e in r["errors"]]

        print("\n" + "=" * 80)
        for r in all_results:
            status = "✅ PASS" if r["tests_failed"] == 0 else "❌ FAIL"
            print(f"  {status}: {r['test_name']} — {r['tests_passed']}/{r['tests_run']}")
        print("=" * 80)
        print(f"  RESULTS: {total_passed}/{total_run} passed")
        if all_errors:
            for e in all_errors:
                print(f"  ❌ {e}")
        print(f"\n⏱️  Total elapsed: {elapsed:.2f}s")
        print("=" * 80)

        return total_failed == 0

    finally:
        if DELETE_SPACE_AT_END:
            logger.info(f"\n  Deleting test space '{TEST_SPACE_ID}'...")
            try:
                await client.spaces.delete_space(TEST_SPACE_ID)
                logger.info(f"  ✅ Test space deleted")
            except Exception as e:
                logger.warning(f"  ⚠️  Cleanup error: {e}")
        await client.close()
        logger.info(f"  ✅ Client closed")


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
