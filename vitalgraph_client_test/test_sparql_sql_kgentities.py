#!/usr/bin/env python3
"""
SPARQL-SQL Backend KGEntities Test

Standalone runner for KGEntities CRUD test case against the sparql_sql backend.
Creates a dedicated space, runs entity CRUD tests, then cleans up.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

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
from vitalgraph_client_test.sparql_sql.case_kgentities_crud import KGEntitiesCrudTester
from vitalgraph_client_test.sparql_sql.case_entity_frames_crud import EntityFramesCrudTester

# ===========================================================================
# Configuration
# ===========================================================================
TEST_SPACE_ID = "sp_sql_kgentities"
TEST_SPACE_NAME = "SPARQL-SQL KGEntities Test Space"
TEST_GRAPH_ID = "urn:sql_kgentities"

DELETE_SPACE_AT_END = True


# ===========================================================================
# Main
# ===========================================================================
async def main():
    print("\n" + "=" * 80)
    print("  SPARQL-SQL Backend — KGEntities CRUD Test")
    print("=" * 80)
    print(f"  Space:  {TEST_SPACE_ID}")
    print(f"  Graph:  {TEST_GRAPH_ID}")

    client = VitalGraphClient()
    await client.open()
    if not client.is_connected():
        logger.error("❌ Failed to connect to VitalGraph server")
        return False
    logger.info("\n✅ Connected to VitalGraph server\n")

    t0 = time.time()

    try:
        # Pre-test cleanup
        resp = await client.spaces.list_spaces()
        existing_ids = [s.space for s in resp.spaces] if resp.is_success else []
        logger.info(f"  Existing spaces: {existing_ids}")
        if TEST_SPACE_ID in existing_ids:
            logger.info(f"  Deleting pre-existing space '{TEST_SPACE_ID}'...")
            await client.spaces.delete_space(TEST_SPACE_ID)
            logger.info(f"  ✅ Pre-existing space deleted")

        # Create space
        space = Space(space=TEST_SPACE_ID, space_name=TEST_SPACE_NAME,
                      space_description="Automated KGEntities CRUD test space")
        cr = await client.spaces.create_space(space)
        if not cr.is_success:
            logger.error(f"❌ Failed to create space: {cr.error_message}")
            return False
        logger.info(f"  ✅ Space '{TEST_SPACE_ID}' created")

        # Create graph
        await client.graphs.create_graph(TEST_SPACE_ID, TEST_GRAPH_ID)
        logger.info(f"  ✅ Graph '{TEST_GRAPH_ID}' created")

        # Run KGEntities CRUD tests
        tester = KGEntitiesCrudTester(client)
        results = await tester.run_tests(TEST_SPACE_ID, TEST_GRAPH_ID)

        # Run Entity Frames CRUD tests
        frames_tester = EntityFramesCrudTester(client)
        frames_results = await frames_tester.run_tests(TEST_SPACE_ID, TEST_GRAPH_ID)

        # Merge results
        results["tests_run"] += frames_results["tests_run"]
        results["tests_passed"] += frames_results["tests_passed"]
        results["tests_failed"] += frames_results["tests_failed"]
        results["errors"].extend(frames_results["errors"])

        elapsed = time.time() - t0
        passed = results["tests_passed"]
        total = results["tests_run"]

        print("\n" + "=" * 80)
        print(f"  RESULTS: {passed}/{total} passed")
        print("=" * 80)
        if results["errors"]:
            for e in results["errors"]:
                print(f"  ❌ {e}")
        print(f"\n⏱️  Total elapsed: {elapsed:.2f}s")

        return results["tests_failed"] == 0

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
