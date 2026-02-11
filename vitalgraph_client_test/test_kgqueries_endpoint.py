#!/usr/bin/env python3
"""
Test script for KGQueries endpoint.

Tests frame-based entity queries using multi-frame slot criteria.
Uses existing multi-org test data (organizations + business events).
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to Python path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.spaces_model import Space

# Import existing multi-org test data loaders
from vitalgraph_client_test.multi_kgentity.case_create_organizations import CreateOrganizationsTester
from vitalgraph_client_test.multi_kgentity.case_create_business_events import CreateBusinessEventsTester
from vitalgraph_client_test.multi_kgentity.case_create_relations import create_all_relation_data

# Import KGQueries test cases
from vitalgraph_client_test.kgqueries.case_frame_queries import FrameQueriesTester
from vitalgraph_client_test.kgqueries.case_relation_queries import RelationQueriesTester

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


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
        
        status = "✅ PASS" if result["tests_failed"] == 0 else "❌ FAIL"
        print(f"{status}: {result['test_name']}")
        print(f"   Tests: {result['tests_passed']}/{result['tests_run']} passed")
        
        if result.get("errors"):
            print(f"   Errors:")
            for error in result["errors"][:3]:  # Show first 3 errors
                print(f"      • {error}")
    
    print(f"\n{'=' * 80}")
    print(f"OVERALL: {total_passed}/{total_tests} tests passed")
    print(f"{'=' * 80}\n")
    
    return total_failed == 0


async def main():
    """Run the KGQueries endpoint tests."""
    
    print_section("🔍 KGQueries Endpoint Test")
    
    # Initialize client
    logger.info("🔧 Initializing VitalGraph client...")
    # Configuration loaded from environment variables
    client = VitalGraphClient()
    
    # Connect
    logger.info("🔐 Connecting to VitalGraph server...")
    await client.open()
    if not client.is_connected():
        logger.error("❌ Connection failed!")
        return False
    logger.info("✅ Connected successfully\n")
    
    # Create test space
    space_id = "space_kgquery_test"
    graph_id = "urn:kgquery_test_graph"
    
    # List all spaces and delete test space if it exists
    logger.info(f"📦 Listing all spaces...")
    try:
        spaces_response = await client.spaces.list_spaces()
        if spaces_response.is_success:
            logger.info(f"   Found {len(spaces_response.spaces)} spaces")
            existing_space = next((s for s in spaces_response.spaces if s.space == space_id), None)
            
            if existing_space:
                logger.info(f"   Found existing test space '{space_id}', deleting...")
                delete_response = await client.spaces.delete_space(space_id)
                if delete_response.is_success:
                    logger.info(f"   ✅ Existing test space deleted")
                else:
                    logger.warning(f"   ⚠️  Failed to delete existing space: {delete_response.error_message}")
            else:
                logger.info(f"   No existing test space found")
    except Exception as e:
        logger.warning(f"   ⚠️  Could not check/delete existing space: {e}")
    
    logger.info(f"📦 Creating fresh test space: {space_id}")
    space_data = Space(
        space=space_id,
        space_name="KGQueries Test Space",
        space_description="Test space for KG frame-based entity queries",
        tenant="test_tenant"
    )
    create_response = await client.spaces.create_space(space_data)
    if not create_response.is_success:
        logger.error(f"❌ Failed to create space: {create_response.error_message}")
        return False
    logger.info(f"✅ Test space created: {create_response.space.space if create_response.space else space_id}\n")
    
    # Track all test results
    all_results = []
    
    try:
        # ====================================================================
        # STEP 1: Load Organizations (using existing multi-org test function)
        # ====================================================================
        logger.info("=" * 80)
        logger.info("  STEP 1: Loading Organizations")
        logger.info("=" * 80)
        
        org_tester = CreateOrganizationsTester(client)
        org_results = await org_tester.run_tests(space_id, graph_id)
        all_results.append(org_results)
        
        if org_results["tests_failed"] > 0:
            logger.error("❌ Organization creation failed, stopping tests")
            return False
        
        organization_uris = org_results["created_entity_uris"]
        logger.info(f"\n Created {len(organization_uris)} organizations")
        
        # ====================================================================
        # STEP 2: Load Business Events (using existing multi-org test function)
        # ====================================================================
        logger.info("\n" + "=" * 80)
        logger.info("  STEP 2: Loading Business Events")
        logger.info("=" * 80)
        
        event_tester = CreateBusinessEventsTester(client)
        event_results = await event_tester.run_tests(space_id, graph_id, organization_uris)
        all_results.append(event_results)
        
        if event_results["tests_failed"] > 0:
            logger.error(" Business event creation failed, stopping tests")
            return False
        
        event_uris = event_results["created_event_uris"]
        logger.info(f"\n Created {len(event_uris)} business events")
        
        # ====================================================================
        # STEP 3: Load Relation Data (types, products, relations)
        # ====================================================================
        logger.info("\n" + "=" * 80)
        logger.info("  STEP 3: Loading Relation Data")
        logger.info("=" * 80)
        
        relation_type_uris, product_uris, relation_uris = create_all_relation_data(
            client, space_id, graph_id, 
            {name: uri for name, uri in zip(
                ["TechCorp Industries", "Global Finance Group", "Healthcare Solutions Inc", 
                 "Energy Innovations LLC", "Retail Dynamics Corp", "Manufacturing Excellence",
                 "Education Systems Ltd", "Transportation Networks", "Media & Entertainment Co",
                 "Biotech Research Labs"],
                organization_uris[:10]
            )}
        )
        
        total_relations = sum(len(uris) for uris in relation_uris.values())
        logger.info(f"\n Created {len(relation_type_uris)} relation types, {len(product_uris)} products, {total_relations} relations")
        
        # ====================================================================
        # STEP 4: Run Frame Query Tests
        # ====================================================================
        logger.info("\n" + "=" * 80)
        logger.info("  STEP 4: Frame-Based Entity Queries")
        logger.info("=" * 80)
        
        frame_tester = FrameQueriesTester(client)
        frame_results = await frame_tester.run_tests(space_id, graph_id, organization_uris, event_uris)
        all_results.append(frame_results)
        
        # ====================================================================
        # STEP 5: Run Relation Query Tests
        # ====================================================================
        logger.info("\n" + "=" * 80)
        logger.info("  STEP 5: Relation-Based Connection Queries")
        logger.info("=" * 80)
        
        org_uri_map = {name: uri for name, uri in zip(
            ["TechCorp Industries", "Global Finance Group", "Healthcare Solutions Inc", 
             "Energy Innovations LLC", "Retail Dynamics Corp", "Manufacturing Excellence",
             "Education Systems Ltd", "Transportation Networks", "Media & Entertainment Co",
             "Biotech Research Labs"],
            organization_uris[:10]
        )}
        
        relation_tester = RelationQueriesTester(client)
        relation_results = await relation_tester.run_tests(space_id, graph_id, org_uri_map, product_uris, relation_type_uris)
        all_results.append(relation_results)
        
        # ====================================================================
        # Print Test Summary
        # ====================================================================
        success = print_test_summary(all_results)
        
        if success:
            logger.info("🎉 All KGQueries endpoint tests PASSED!")
        else:
            logger.error("❌ Some KGQueries endpoint tests FAILED!")
        
        return success
        
    finally:
        # ====================================================================
        # Cleanup
        # ====================================================================
        print_section("🧹 Cleanup")
        
        logger.info("✅ Test space preserved for inspection:")
        logger.info(f"   Space ID: {space_id}")
        logger.info(f"   Graph ID: {graph_id}")
        logger.info(f"   Note: Space will be deleted on next test run\n")
        
        logger.info("Closing client connection...")
        await client.close()
        logger.info("✅ Client closed\n")


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
