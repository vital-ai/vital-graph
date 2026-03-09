#!/usr/bin/env python3
"""
SPARQL-SQL Backend KGQueries Test

Standalone runner for KGQueries endpoint test against the sparql_sql backend.
Creates organizations, business events, relation data, then runs
frame-based and relation-based query tests. Cleans up at the end.
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
from vitalgraph_client_test.multi_kgentity.case_create_organizations import (
    CreateOrganizationsTester,
    ORGANIZATIONS,
)
from vitalgraph_client_test.multi_kgentity.case_create_business_events import (
    CreateBusinessEventsTester,
)
from vitalgraph_client_test.multi_kgentity.case_create_relations import (
    create_all_relation_data,
)
from vitalgraph_client_test.kgqueries.case_frame_queries import FrameQueriesTester
from vitalgraph_client_test.kgqueries.case_relation_queries import RelationQueriesTester

# ===========================================================================
# Configuration
# ===========================================================================
TEST_SPACE_ID = "sp_sql_kgqueries"
TEST_SPACE_NAME = "SPARQL-SQL KGQueries Test Space"
TEST_GRAPH_ID = "urn:sql_kgqueries"

DELETE_SPACE_AT_END = True

# Organization name list (matches ORGANIZATIONS data order)
ORG_NAMES = [org["name"] for org in ORGANIZATIONS]


# ===========================================================================
# Main
# ===========================================================================
async def main():
    print("\n" + "=" * 80)
    print("  SPARQL-SQL Backend — KGQueries Endpoint Test")
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
    all_results = []

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
                      space_description="Automated KGQueries endpoint test space")
        cr = await client.spaces.create_space(space)
        if not cr.is_success:
            logger.error(f"❌ Failed to create space: {cr.error_message}")
            return False
        logger.info(f"  ✅ Space '{TEST_SPACE_ID}' created")

        # Create graph
        await client.graphs.create_graph(TEST_SPACE_ID, TEST_GRAPH_ID)
        logger.info(f"  ✅ Graph '{TEST_GRAPH_ID}' created")

        # ====================================================================
        # STEP 1: Create Organizations
        # ====================================================================
        print("\n" + "=" * 80)
        print("  Step 1: Create Organizations")
        print("=" * 80)

        org_tester = CreateOrganizationsTester(client)
        org_results = await org_tester.run_tests(TEST_SPACE_ID, TEST_GRAPH_ID)
        all_results.append(org_results)

        if org_results["tests_failed"] > 0:
            logger.error("❌ Organization creation failed, stopping tests")
            return False

        organization_uris = org_results["created_entity_uris"]
        logger.info(f"  Created {len(organization_uris)} organizations")

        # Build org name → URI map
        org_uri_map = {}
        for i, name in enumerate(ORG_NAMES):
            if i < len(organization_uris):
                org_uri_map[name] = organization_uris[i]

        # ====================================================================
        # STEP 2: Create Business Events
        # ====================================================================
        print("\n" + "=" * 80)
        print("  Step 2: Create Business Events")
        print("=" * 80)

        event_tester = CreateBusinessEventsTester(client)
        event_results = await event_tester.run_tests(TEST_SPACE_ID, TEST_GRAPH_ID, organization_uris)
        all_results.append(event_results)

        if event_results["tests_failed"] > 0:
            logger.error("❌ Business event creation failed, stopping tests")
            return False

        event_uris = event_results["created_event_uris"]
        logger.info(f"  Created {len(event_uris)} business events")

        # ====================================================================
        # STEP 3: Create Relation Data (types, products, instances)
        # ====================================================================
        print("\n" + "=" * 80)
        print("  Step 3: Create Relation Data")
        print("=" * 80)

        relation_type_uris, product_uris, relation_uris = await create_all_relation_data(
            client, TEST_SPACE_ID, TEST_GRAPH_ID, org_uri_map
        )
        total_relations = sum(len(uris) for uris in relation_uris.values())
        logger.info(f"  Created {len(relation_type_uris)} types, {len(product_uris)} products, {total_relations} relations")

        # ====================================================================
        # STEP 4: Frame-Based Queries
        # ====================================================================
        print("\n" + "=" * 80)
        print("  Step 4: Frame-Based Entity Queries")
        print("=" * 80)

        frame_tester = FrameQueriesTester(client, query_mode="edge")
        frame_results = await frame_tester.run_tests(TEST_SPACE_ID, TEST_GRAPH_ID, organization_uris, event_uris)
        all_results.append(frame_results)

        # ====================================================================
        # STEP 5: Relation-Based Queries
        # ====================================================================
        print("\n" + "=" * 80)
        print("  Step 5: Relation-Based Connection Queries")
        print("=" * 80)

        relation_tester = RelationQueriesTester(client)
        relation_results = await relation_tester.run_tests(
            TEST_SPACE_ID, TEST_GRAPH_ID, org_uri_map, product_uris, relation_type_uris
        )
        all_results.append(relation_results)

        # ====================================================================
        # Summary
        # ====================================================================
        elapsed = time.time() - t0
        total_passed = sum(r["tests_passed"] for r in all_results)
        total_run = sum(r["tests_run"] for r in all_results)
        total_failed = sum(r["tests_failed"] for r in all_results)

        print("\n" + "=" * 80)
        for r in all_results:
            status = "✅ PASS" if r["tests_failed"] == 0 else "❌ FAIL"
            print(f"  {status}: {r['test_name']} — {r['tests_passed']}/{r['tests_run']}")
        print("=" * 80)
        print(f"  RESULTS: {total_passed}/{total_run} passed")
        print("=" * 80)
        if total_failed > 0:
            for r in all_results:
                for e in r.get("errors", []):
                    print(f"  ❌ {e}")
        print(f"\n⏱️  Total elapsed: {elapsed:.2f}s")

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
