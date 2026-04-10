#!/usr/bin/env python3
"""
SPARQL-SQL Backend — Lead Entity Dataset Test

Bulk loads 100 lead entity graphs from N-Triples files, then runs
read-only query and retrieval operations on the loaded data.

Reuses the existing entity_graph_lead_dataset test case modules:
  - BulkLoadDatasetTester: bulk load all .nt files
  - ListAndQueryEntitiesTester: pagination, filtering
  - RetrieveEntityGraphsTester: entity graph + frame retrieval (sample 5)
  - KGQueryLeadQueriesTester: frame-based KGQuery queries

Mirrors test_lead_entity_graph_dataset.py flow against the sparql_sql backend.
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

from vitalgraph_client_test.entity_graph_lead_dataset.case_bulk_load_dataset import BulkLoadDatasetTester
from vitalgraph_client_test.entity_graph_lead_dataset.case_list_and_query_entities import ListAndQueryEntitiesTester
from vitalgraph_client_test.entity_graph_lead_dataset.case_retrieve_entity_graphs import RetrieveEntityGraphsTester
from vitalgraph_client_test.entity_graph_lead_dataset.case_kgquery_lead_queries import KGQueryLeadQueriesTester

# ===========================================================================
# Configuration
# ===========================================================================
TEST_SPACE_ID = "sp_sql_lead_dataset"
TEST_SPACE_NAME = "SPARQL-SQL Lead Dataset Test Space"
TEST_GRAPH_ID = "urn:sql_lead_dataset"
LEAD_DATA_DIR = project_root / "lead_test_data"
MAX_FILES = 100
SAMPLE_SIZE = 5

# Set to True to skip bulk load and use previously loaded data
SKIP_LOAD = False
# Set to True to delete the space at the end (False to preserve for inspection)
DELETE_SPACE_AT_END = False


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
    print("  SPARQL-SQL Backend — Lead Entity Dataset Test")
    print("=" * 80)
    print(f"  Space:      {TEST_SPACE_ID}")
    print(f"  Graph:      {TEST_GRAPH_ID}")
    print(f"  Data:       {LEAD_DATA_DIR}")
    print(f"  Max files:  {MAX_FILES}")
    print(f"  Sample:     {SAMPLE_SIZE}")
    print(f"  Skip load:  {SKIP_LOAD}")

    # Check data directory
    if not LEAD_DATA_DIR.exists():
        logger.error(f"❌ Lead data directory not found: {LEAD_DATA_DIR}")
        return False

    lead_files = get_lead_files(LEAD_DATA_DIR, limit=MAX_FILES)
    if not lead_files:
        logger.error(f"❌ No lead .nt files found in {LEAD_DATA_DIR}")
        return False
    logger.info(f"  Files:      {len(lead_files)}\n")

    client = VitalGraphClient()
    await client.open()
    if not client.is_connected():
        logger.error("❌ Failed to connect to VitalGraph server")
        return False
    logger.info("✅ Connected to VitalGraph server\n")

    t0 = time.time()
    all_results: List[dict] = []

    try:
        if not SKIP_LOAD:
            # Pre-test cleanup
            resp = await client.spaces.list_spaces()
            existing_ids = [s.space for s in resp.spaces] if resp.is_success else []
            if TEST_SPACE_ID in existing_ids:
                logger.info(f"  Deleting pre-existing space '{TEST_SPACE_ID}'...")
                await client.spaces.delete_space(TEST_SPACE_ID)

            # Create space + graph
            space = Space(space=TEST_SPACE_ID, space_name=TEST_SPACE_NAME,
                          space_description="Lead dataset test (sparql_sql)")
            cr = await client.spaces.create_space(space)
            if not cr.is_success:
                logger.error(f"❌ Failed to create space: {cr.error_message}")
                return False
            logger.info(f"  ✅ Space '{TEST_SPACE_ID}' created")

            await client.graphs.create_graph(TEST_SPACE_ID, TEST_GRAPH_ID)
            logger.info(f"  ✅ Graph '{TEST_GRAPH_ID}' created\n")

        # ==================================================================
        # Step 1: Bulk load
        # ==================================================================
        if SKIP_LOAD:
            logger.info("⏭️  Skipping bulk load (SKIP_LOAD=True)\n")
            entity_count = len(lead_files)
            loaded_entities = []
            bulk_results = {
                "test_name": "Bulk Load Lead Dataset (Skipped)",
                "tests_run": 0, "tests_passed": 0, "tests_failed": 0,
                "errors": [], "loaded_entities": [], "load_time": 0,
                "total_triples": 0
            }
            all_results.append(bulk_results)
        else:
            bulk_tester = BulkLoadDatasetTester(client)
            bulk_results = await bulk_tester.run_tests(TEST_SPACE_ID, TEST_GRAPH_ID, lead_files)
            all_results.append(bulk_results)

            if bulk_results["tests_failed"] > 0:
                logger.error("❌ Bulk load had failures")
            
            loaded_entities = bulk_results.get("loaded_entities", [])
            entity_count = len(loaded_entities)
            if entity_count == 0:
                logger.error("❌ No entities loaded — aborting")
                return False
            logger.info(f"\n✅ Loaded {entity_count} entities\n")

        # ==================================================================
        # Step 2: List & paginate
        # ==================================================================
        list_tester = ListAndQueryEntitiesTester(client)
        list_results = await list_tester.run_tests(TEST_SPACE_ID, TEST_GRAPH_ID, entity_count)
        all_results.append(list_results)

        entity_uris = list_results.get("entity_uris", [])

        # ==================================================================
        # Step 3: Retrieve entity graphs + frames (sample)
        # ==================================================================
        retrieve_tester = RetrieveEntityGraphsTester(client)
        retrieve_results = await retrieve_tester.run_tests(
            TEST_SPACE_ID, TEST_GRAPH_ID,
            entity_uris if entity_uris else [e["uri"] for e in loaded_entities],
            sample_size=SAMPLE_SIZE)
        all_results.append(retrieve_results)

        # ==================================================================
        # Step 4: KGQuery frame-based queries
        # ==================================================================
        kgquery_tester = KGQueryLeadQueriesTester(client, query_mode="edge")
        kgquery_results = await kgquery_tester.run_tests(TEST_SPACE_ID, TEST_GRAPH_ID, entity_count)
        all_results.append(kgquery_results)

        # ==================================================================
        # Summary
        # ==================================================================
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
        print(f"\n  Dataset: {entity_count} entities, {bulk_results.get('total_triples', 0):,} triples")
        print(f"  Load:    {bulk_results.get('load_time', 0):.1f}s")
        print(f"⏱️  Total elapsed: {elapsed:.1f}s")
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
        else:
            logger.info(f"\n  Space '{TEST_SPACE_ID}' preserved for inspection")
        await client.close()
        logger.info(f"  ✅ Client closed")


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
