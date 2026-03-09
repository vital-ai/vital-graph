#!/usr/bin/env python3
"""
SPARQL-SQL Backend KGRelations Test

Standalone runner for KGRelations CRUD test against the sparql_sql backend.
Creates organizations, relation types, products, and relation instances,
then tests list/filter/get/delete operations. Cleans up at the end.
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
from vitalgraph_client_test.multi_kgentity.case_create_relations import (
    create_all_relation_data,
)

# ===========================================================================
# Configuration
# ===========================================================================
TEST_SPACE_ID = "sp_sql_kgrelations"
TEST_SPACE_NAME = "SPARQL-SQL KGRelations Test Space"
TEST_GRAPH_ID = "urn:sql_kgrelations"

DELETE_SPACE_AT_END = True


# ===========================================================================
# Inline CRUD tests (self-contained, no separate case module needed)
# ===========================================================================

async def test_list_all_relations(client, space_id, graph_id, relation_uris):
    """Test listing all relations."""
    logger.info("\n--- List All Relations ---")
    passed = failed = 0
    errors = []

    try:
        response = await client.kgrelations.list_relations(space_id, graph_id, page_size=50)
        total_expected = sum(len(uris) for uris in relation_uris.values())
        actual = len(response.objects) if response.objects else 0

        if response.is_success and actual == total_expected:
            logger.info(f"  ✅ Listed {actual} relations (expected {total_expected})")
            passed += 1
        else:
            logger.error(f"  ❌ Count mismatch: got {actual}, expected {total_expected}")
            failed += 1
            errors.append(f"List all: expected {total_expected}, got {actual}")
    except Exception as e:
        logger.error(f"  ❌ Exception: {e}")
        failed += 1
        errors.append(f"List all: {e}")

    return passed, failed, errors


async def test_list_by_source(client, space_id, graph_id, org_uris):
    """Test listing relations filtered by source entity."""
    logger.info("\n--- List Relations by Source Entity ---")
    passed = failed = 0
    errors = []

    techcorp_uri = org_uris.get("TechCorp Industries")
    if not techcorp_uri:
        logger.warning("  ⚠️  TechCorp URI not found, skipping")
        return 0, 0, []

    try:
        response = await client.kgrelations.list_relations(
            space_id, graph_id, entity_source_uri=techcorp_uri
        )
        actual = len(response.objects) if response.objects else 0
        # TechCorp has 2 MakesProduct + 1 PartnerWith = 3 outgoing
        if response.is_success and actual >= 3:
            logger.info(f"  ✅ Found {actual} relations from TechCorp (expected ≥3)")
            passed += 1
        else:
            logger.error(f"  ❌ Found {actual} relations from TechCorp (expected ≥3)")
            failed += 1
            errors.append(f"List by source: expected ≥3, got {actual}")
    except Exception as e:
        logger.error(f"  ❌ Exception: {e}")
        failed += 1
        errors.append(f"List by source: {e}")

    return passed, failed, errors


async def test_list_by_type(client, space_id, graph_id, relation_type_uris, relation_uris):
    """Test listing relations filtered by type."""
    logger.info("\n--- List Relations by Type ---")
    passed = failed = 0
    errors = []

    makes_product_type = relation_type_uris.get("makes_product")
    if not makes_product_type:
        logger.warning("  ⚠️  MakesProduct type URI not found, skipping")
        return 0, 0, []

    try:
        response = await client.kgrelations.list_relations(
            space_id, graph_id, relation_type_uri=makes_product_type
        )
        expected = len(relation_uris["makes_product"])
        actual = len(response.objects) if response.objects else 0

        if response.is_success and actual == expected:
            logger.info(f"  ✅ Found {actual} MakesProduct relations (expected {expected})")
            passed += 1
        else:
            logger.error(f"  ❌ Found {actual} MakesProduct relations (expected {expected})")
            failed += 1
            errors.append(f"List by type: expected {expected}, got {actual}")
    except Exception as e:
        logger.error(f"  ❌ Exception: {e}")
        failed += 1
        errors.append(f"List by type: {e}")

    return passed, failed, errors


async def test_get_relation(client, space_id, graph_id, relation_uris):
    """Test getting individual relation by URI."""
    logger.info("\n--- Get Individual Relation ---")
    passed = failed = 0
    errors = []

    if not relation_uris["makes_product"]:
        logger.warning("  ⚠️  No MakesProduct relation URIs, skipping")
        return 0, 0, []

    relation_uri = relation_uris["makes_product"][0]
    try:
        response = await client.kgrelations.get_relation(space_id, graph_id, relation_uri)
        if response.is_success and response.objects:
            logger.info(f"  ✅ Retrieved relation: {relation_uri}")
            passed += 1
        else:
            logger.error(f"  ❌ Failed to get relation: {relation_uri}")
            failed += 1
            errors.append("Get relation failed")
    except Exception as e:
        logger.error(f"  ❌ Exception: {e}")
        failed += 1
        errors.append(f"Get relation: {e}")

    return passed, failed, errors


async def test_delete_relation(client, space_id, graph_id, relation_uris):
    """Test deleting a relation and verifying count decreases."""
    logger.info("\n--- Delete Relation ---")
    passed = failed = 0
    errors = []

    if not relation_uris["competitor_of"]:
        logger.warning("  ⚠️  No CompetitorOf relation URIs, skipping")
        return 0, 0, []

    relation_uri = relation_uris["competitor_of"][0]
    try:
        response = await client.kgrelations.delete_relations(space_id, graph_id, [relation_uri])
        if response.is_success:
            logger.info(f"  ✅ Deleted relation: {relation_uri}")
            passed += 1

            # Verify deletion
            list_resp = await client.kgrelations.list_relations(space_id, graph_id, page_size=50)
            expected_count = sum(len(uris) for uris in relation_uris.values()) - 1
            actual_count = len(list_resp.objects) if list_resp.objects else 0
            if actual_count == expected_count:
                logger.info(f"  ✅ Verified deletion (count: {actual_count})")
                passed += 1
            else:
                logger.error(f"  ❌ Count after delete: expected {expected_count}, got {actual_count}")
                failed += 1
                errors.append(f"Delete verify: expected {expected_count}, got {actual_count}")
        else:
            logger.error(f"  ❌ Delete failed: {response.message}")
            failed += 1
            errors.append(f"Delete failed: {response.message}")
    except Exception as e:
        logger.error(f"  ❌ Exception: {e}")
        failed += 1
        errors.append(f"Delete relation: {e}")

    return passed, failed, errors


# ===========================================================================
# Main
# ===========================================================================
async def main():
    print("\n" + "=" * 80)
    print("  SPARQL-SQL Backend — KGRelations CRUD Test")
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
    total_passed = total_failed = 0
    all_errors = []

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
                      space_description="Automated KGRelations CRUD test space")
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
        total_passed += org_results["tests_passed"]
        total_failed += org_results["tests_failed"]
        all_errors.extend(org_results["errors"])

        if org_results["tests_failed"] > 0:
            logger.error("❌ Organization creation failed, stopping tests")
            return False

        # Build org name → URI map
        org_uris = {}
        for i, org_data in enumerate(ORGANIZATIONS):
            if i < len(org_results["created_entity_uris"]):
                org_uris[org_data["name"]] = org_results["created_entity_uris"][i]
        logger.info(f"  Created {len(org_uris)} organizations")

        # ====================================================================
        # STEP 2: Create Relation Data (types, products, instances)
        # ====================================================================
        print("\n" + "=" * 80)
        print("  Step 2: Create Relation Data")
        print("=" * 80)

        relation_type_uris, product_uris, relation_uris = await create_all_relation_data(
            client, TEST_SPACE_ID, TEST_GRAPH_ID, org_uris
        )
        total_relations = sum(len(uris) for uris in relation_uris.values())
        logger.info(f"  Created {len(relation_type_uris)} types, {len(product_uris)} products, {total_relations} relations")
        total_passed += total_relations  # Each relation creation counts as a test

        # ====================================================================
        # STEP 3: CRUD Tests
        # ====================================================================
        print("\n" + "=" * 80)
        print("  Step 3: KGRelations CRUD Tests")
        print("=" * 80)

        for test_fn, args in [
            (test_list_all_relations, (client, TEST_SPACE_ID, TEST_GRAPH_ID, relation_uris)),
            (test_list_by_source, (client, TEST_SPACE_ID, TEST_GRAPH_ID, org_uris)),
            (test_list_by_type, (client, TEST_SPACE_ID, TEST_GRAPH_ID, relation_type_uris, relation_uris)),
            (test_get_relation, (client, TEST_SPACE_ID, TEST_GRAPH_ID, relation_uris)),
            (test_delete_relation, (client, TEST_SPACE_ID, TEST_GRAPH_ID, relation_uris)),
        ]:
            p, f, e = await test_fn(*args)
            total_passed += p
            total_failed += f
            all_errors.extend(e)

        # ====================================================================
        # Summary
        # ====================================================================
        elapsed = time.time() - t0
        total = total_passed + total_failed

        print("\n" + "=" * 80)
        print(f"  RESULTS: {total_passed}/{total} passed")
        print("=" * 80)
        if all_errors:
            for e in all_errors:
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
