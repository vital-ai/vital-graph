#!/usr/bin/env python3
"""
Multiple Organizations CRUD Test - Main Orchestrator

This test orchestrates comprehensive CRUD operations on multiple organization entities
using modular test cases from the multi_kgentity package.

Test Flow:
0. KGTypes operations (create and list entity types, frame types, slot types)
1. Upload files (contracts, reports)
2. Create 10 organization entities (with reference IDs and file references)
2.5. Create relation data (types, products, relations)
3. Create 10 business events (referencing organizations)
4. Download and verify files
5. List and verify graphs
6. List all entities
7. List entity graphs
8. Get individual entities by URI
9. List business events
10. Get business event graphs
11. Get entities by reference ID (single and multiple)
12. Update entities (employee counts)
13. Verify updates
14. Frame-level operations (list, get, update frames)
15. KGQuery entity frame queries (single and multi-frame slot criteria)
16. KGQuery relation queries (relation type and entity criteria)
17. Entity graph operations
18. Delete entities
19. Delete files
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
from vitalgraph.model.spaces_model import Space

# Import test case modules
from vitalgraph_client_test.multi_kgentity.case_create_organizations import CreateOrganizationsTester, ORGANIZATIONS
from vitalgraph_client_test.multi_kgentity.case_create_business_events import CreateBusinessEventsTester
from vitalgraph_client_test.multi_kgentity.case_list_entities import ListEntitiesTester
from vitalgraph_client_test.multi_kgentity.case_list_entity_graphs import ListEntityGraphsTester
from vitalgraph_client_test.multi_kgentity.case_list_business_events import ListBusinessEventsTester
from vitalgraph_client_test.multi_kgentity.case_get_entities import GetEntitiesTester
from vitalgraph_client_test.multi_kgentity.case_get_business_events import GetBusinessEventsTester
from vitalgraph_client_test.multi_kgentity.case_reference_id_operations import ReferenceIdOperationsTester
from vitalgraph_client_test.multi_kgentity.case_update_entities import UpdateEntitiesTester
from vitalgraph_client_test.multi_kgentity.case_verify_updates import VerifyUpdatesTester
from vitalgraph_client_test.multi_kgentity.case_frame_operations import FrameOperationsTester
from vitalgraph_client_test.multi_kgentity.case_entity_graph_operations import EntityGraphOperationsTester
from vitalgraph_client_test.multi_kgentity.case_delete_entities import DeleteEntitiesTester
from vitalgraph_client_test.multi_kgentity.case_list_graphs import ListGraphsTester
from vitalgraph_client_test.multi_kgentity.case_kgtypes_operations import KGTypesOperationsTester
from vitalgraph_client_test.multi_kgentity.case_kgquery_frame_queries import KGQueryFrameQueriesTester
from vitalgraph_client_test.multi_kgentity.case_kgquery_relation_queries import KGQueryRelationQueriesTester
from vitalgraph_client_test.multi_kgentity.case_create_relations import create_all_relation_data
from vitalgraph_client_test.multi_kgentity.case_upload_files import UploadFilesTester
from vitalgraph_client_test.multi_kgentity.case_download_files import DownloadFilesTester
from vitalgraph_client_test.multi_kgentity.case_delete_files import DeleteFilesTester


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
        
        if result["errors"]:
            print(f"   Errors:")
            for error in result["errors"][:3]:  # Show first 3 errors
                print(f"      • {error}")
    
    print(f"\n{'=' * 80}")
    print(f"OVERALL: {total_passed}/{total_tests} tests passed")
    print(f"{'=' * 80}\n")
    
    return total_failed == 0


async def main():
    """Run the multiple organizations CRUD test."""
    
    print_section("🏢 Multiple Organizations CRUD Test")
    
    # Initialize client
    logger.info("🔧 Initializing VitalGraph client...")
    # Configuration loaded from environment variables
    client = VitalGraphClient()
    
    # Connect
    logger.info("🔐 Connecting to VitalGraph server...")
    client.open()
    if not client.is_connected():
        logger.error("❌ Connection failed!")
        return False
    logger.info("✅ Connected successfully\n")
    
    # Create test space
    space_id = "space_multi_org_crud_test"
    graph_id = "urn:multi_org_crud_graph"
    
    # Check if space already exists and delete it
    logger.info(f"📦 Checking for existing test space: {space_id}")
    try:
        spaces_response = client.spaces.list_spaces()
        if spaces_response.is_success:
            existing_space = next((s for s in spaces_response.spaces if s.space == space_id), None)
            
            if existing_space:
                logger.info(f"   Found existing space, deleting...")
                delete_response = client.spaces.delete_space(space_id)
                if delete_response.is_success:
                    logger.info(f"   ✅ Existing space deleted")
    except Exception as e:
        logger.info(f"   Note: Could not check/delete existing space: {e}")
    
    logger.info(f"📦 Creating test space: {space_id}")
    space_data = Space(
        space=space_id,
        space_name="Multiple Organizations CRUD Test",
        space_description="Test space for multiple organization CRUD operations",
        tenant="test_tenant"
    )
    create_response = client.spaces.create_space(space_data)
    if not create_response.is_success:
        logger.error(f"❌ Failed to create space: {create_response.error_message}")
        return False
    logger.info(f"✅ Test space created: {create_response.space.space if create_response.space else space_id}\n")
    
    # Track all test results
    all_results = []
    
    try:
        # ====================================================================
        # STEP 0: KGTypes Operations (Create and List Types)
        # ====================================================================
        kgtypes_tester = KGTypesOperationsTester(client)
        kgtypes_results = kgtypes_tester.run_tests(space_id, graph_id)
        all_results.append(kgtypes_results)
        
        if kgtypes_results["tests_failed"] > 0:
            logger.warning("⚠️  KGTypes operations had failures, but continuing with entity creation")
        
        # ====================================================================
        # STEP 1: Upload Files
        # ====================================================================
        upload_tester = UploadFilesTester(client)
        upload_results = await upload_tester.run_tests(space_id, graph_id)
        all_results.append(upload_results)
        
        file_uris = upload_results.get("file_uris", {})
        if upload_results["tests_failed"] > 0:
            logger.warning("⚠️  File upload had failures, continuing without file references")
            file_uris = None
        
        # ====================================================================
        # STEP 2: Create Organizations (with file references)
        # ====================================================================
        create_tester = CreateOrganizationsTester(client)
        create_results = create_tester.run_tests(space_id, graph_id, file_uris=file_uris)
        all_results.append(create_results)
        
        if create_results["tests_failed"] > 0:
            logger.error("❌ Organization creation failed, stopping tests")
            return False
        
        created_entity_uris = create_results["created_entity_uris"]
        reference_ids = create_results["reference_ids"]
        entity_names = [org["name"] for org in ORGANIZATIONS]
        
        # ====================================================================
        # STEP 2.5: Create Relation Data (Types, Products, Relations)
        # ====================================================================
        logger.info("\n" + "=" * 80)
        logger.info("  Creating Relation Data")
        logger.info("=" * 80)
        
        # Create organization name to URI mapping for relation creation
        org_name_to_uri = {
            "TechCorp Industries": created_entity_uris[0],
            "Global Finance Group": created_entity_uris[1],
            "Healthcare Solutions Inc": created_entity_uris[2],
            "Energy Innovations LLC": created_entity_uris[3],
            "Retail Dynamics Corp": created_entity_uris[4],
            "Manufacturing Excellence": created_entity_uris[5],
            "Education Systems Ltd": created_entity_uris[6],
            "Transportation Networks": created_entity_uris[7],
            "Media & Entertainment Co": created_entity_uris[8],
            "Biotech Research Labs": created_entity_uris[9]
        }
        
        try:
            relation_type_uris, product_uris, relation_uris = create_all_relation_data(
                client, space_id, graph_id, org_name_to_uri
            )
            total_relations = sum(len(uris) for uris in relation_uris.values())
            logger.info(f"\n✅ Created {len(relation_type_uris)} relation types, {len(product_uris)} products, {total_relations} relations")
        except Exception as e:
            logger.warning(f"⚠️  Relation data creation failed: {e}")
            logger.warning("   Continuing without relation data...")
            relation_type_uris = {}
            product_uris = {}
            relation_uris = {}
        
        # ====================================================================
        # STEP 3: Create Business Events
        # ====================================================================
        event_tester = CreateBusinessEventsTester(client)
        event_results = event_tester.run_tests(space_id, graph_id, created_entity_uris)
        all_results.append(event_results)
        
        if event_results["tests_failed"] > 0:
            logger.error("❌ Business event creation failed, stopping tests")
            return False
        
        created_event_uris = event_results["created_event_uris"]
        event_reference_ids = event_results["event_reference_ids"]
        
        # ====================================================================
        # STEP 3.5: Download and Verify Files
        # ====================================================================
        if file_uris:
            download_tester = DownloadFilesTester(client)
            download_results = await download_tester.run_tests(space_id, graph_id, file_uris)
            all_results.append(download_results)
        
        # ====================================================================
        # STEP 4: List and Verify Graphs
        # ====================================================================
        graphs_tester = ListGraphsTester(client)
        graphs_results = graphs_tester.run_tests(space_id, graph_id)
        all_results.append(graphs_results)
        
        # ====================================================================
        # STEP 3: List Entities (Organizations + Events + Relation Types + Products)
        # ====================================================================
        # Expected: 10 orgs + 10 events + 4 relation types + 2 products = 26 entities
        list_tester = ListEntitiesTester(client)
        list_results = list_tester.run_tests(space_id, graph_id, expected_count=26)
        all_results.append(list_results)
        
        # ====================================================================
        # STEP 3: List Entity Graphs (MultiEntityGraphResponse)
        # ====================================================================
        list_graphs_tester = ListEntityGraphsTester(client)
        list_graphs_results = list_graphs_tester.run_tests(space_id, graph_id, created_entity_uris)
        all_results.append(list_graphs_results)
        
        # ====================================================================
        # STEP 4: Get Individual Entities
        # ====================================================================
        get_tester = GetEntitiesTester(client)
        get_results = get_tester.run_tests(space_id, graph_id, created_entity_uris, entity_names)
        all_results.append(get_results)
        
        # ====================================================================
        # STEP 5: List Business Events
        # ====================================================================
        list_events_tester = ListBusinessEventsTester(client)
        list_events_results = list_events_tester.run_tests(space_id, graph_id, expected_event_count=10)
        all_results.append(list_events_results)
        
        # ====================================================================
        # STEP 6: Get Business Event Graphs
        # ====================================================================
        get_events_tester = GetBusinessEventsTester(client)
        get_events_results = get_events_tester.run_tests(space_id, graph_id, created_event_uris)
        all_results.append(get_events_results)
        
        # ====================================================================
        # STEP 7: Reference ID Operations
        # ====================================================================
        ref_id_tester = ReferenceIdOperationsTester(client)
        ref_id_results = ref_id_tester.run_tests(space_id, graph_id, created_entity_uris, 
                                                  entity_names, reference_ids)
        all_results.append(ref_id_results)
        
        # ====================================================================
        # STEP 8: Update Entities
        # ====================================================================
        update_tester = UpdateEntitiesTester(client)
        update_results = update_tester.run_tests(space_id, graph_id, created_entity_uris, entity_names)
        all_results.append(update_results)
        
        # ====================================================================
        # STEP 9: Verify Updates
        # ====================================================================
        if update_results.get("updates"):
            verify_tester = VerifyUpdatesTester(client)
            verify_results = verify_tester.run_tests(space_id, graph_id, created_entity_uris, 
                                                     update_results["updates"])
            all_results.append(verify_results)
        
        # ====================================================================
        # STEP 10: Frame Operations
        # ====================================================================
        frame_tester = FrameOperationsTester(client)
        frame_results = frame_tester.run_tests(space_id, graph_id, 
                                               created_entity_uris[0], entity_names[0])
        all_results.append(frame_results)
        
        # ====================================================================
        # STEP 11: KGQuery Entity Frame Queries
        # ====================================================================
        # Run frame-based entity queries (single and multi-frame)
        kgquery_tester = KGQueryFrameQueriesTester(client)
        kgquery_results = kgquery_tester.run_tests(space_id, graph_id, 
                                                    created_entity_uris, created_event_uris, 
                                                    file_uris=file_uris)
        all_results.append(kgquery_results)
        
        # ====================================================================
        # STEP 12: KGQuery Relation Queries
        # ====================================================================
        if relation_type_uris and product_uris:
            kgquery_relation_tester = KGQueryRelationQueriesTester(client)
            kgquery_relation_results = kgquery_relation_tester.run_tests(
                space_id, graph_id,
                org_name_to_uri, product_uris, relation_type_uris
            )
            all_results.append(kgquery_relation_results)
        else:
            logger.info("\n⚠️  Skipping KGQuery Relation-Based Queries (no relation data)")
        
        # ====================================================================
        # STEP 13: Entity Graph Operations
        # ====================================================================
        entity_graph_tester = EntityGraphOperationsTester(client)
        entity_graph_results = entity_graph_tester.run_tests(space_id, graph_id, 
                                                              created_entity_uris[1])
        all_results.append(entity_graph_results)
        
        # ====================================================================
        # STEP 14: Delete Entities
        # ====================================================================
        # Note: One entity (Global Finance Group) was already deleted in entity graph operations
        # Expected remaining: 6 orgs + 10 events + 4 relation types + 2 products = 22 entities
        delete_tester = DeleteEntitiesTester(client)
        delete_results = delete_tester.run_tests(space_id, graph_id, created_entity_uris, entity_names, 
                                                  expected_remaining=22)
        all_results.append(delete_results)
        
        # ====================================================================
        # STEP 15: Delete Files
        # ====================================================================
        if file_uris:
            delete_files_tester = DeleteFilesTester(client)
            delete_files_results = await delete_files_tester.run_tests(space_id, graph_id, file_uris)
            all_results.append(delete_files_results)
        
        # ====================================================================
        # Print Summary
        # ====================================================================
        success = print_test_summary(all_results)
        
        # ====================================================================
        # Print KGQuery Performance Summary
        # ====================================================================
        print_section("⏱️ KGQuery Performance Summary")
        
        # Collect all KGQuery timing data
        kgquery_timings = []
        for result in all_results:
            if 'KGQuery' in result.get('test_name', ''):
                test_name = result.get('test_name', 'Unknown')
                if 'results' in result:
                    for test_result in result['results']:
                        query_name = test_result.get('name', 'Unknown Query')
                        elapsed_time = test_result.get('elapsed_time', 0)
                        passed = test_result.get('passed', False)
                        kgquery_timings.append({
                            'category': test_name,
                            'name': query_name,
                            'time': elapsed_time,
                            'passed': passed
                        })
        
        if kgquery_timings:
            logger.info("\nKGQuery Execution Times (by query):")
            logger.info("-" * 80)
            
            # Group by category
            current_category = None
            for timing in kgquery_timings:
                if timing['category'] != current_category:
                    current_category = timing['category']
                    logger.info(f"\n{current_category}:")
                
                status = "✅" if timing['passed'] else "❌"
                logger.info(f"  {status} {timing['name']:<50} {timing['time']:>6.3f}s")
            
            # Overall statistics
            total_queries = len(kgquery_timings)
            total_time = sum(t['time'] for t in kgquery_timings)
            avg_time = total_time / total_queries if total_queries > 0 else 0
            min_time = min((t['time'] for t in kgquery_timings), default=0)
            max_time = max((t['time'] for t in kgquery_timings), default=0)
            
            logger.info("\n" + "-" * 80)
            logger.info(f"Total KGQueries:  {total_queries}")
            logger.info(f"Total time:       {total_time:.3f}s")
            logger.info(f"Average time:     {avg_time:.3f}s")
            logger.info(f"Fastest query:    {min_time:.3f}s")
            logger.info(f"Slowest query:    {max_time:.3f}s")
            logger.info("-" * 80)
        
        if success:
            print_section("✅ All Tests Completed Successfully!")
        else:
            print_section("⚠️ Some Tests Failed")
        
        return success
        
    finally:
        # Cleanup
        print_section("🧹 Cleanup")
        # logger.info("Deleting test space...")
        # delete_response = client.spaces.delete_space(space_id)
        # if delete_response.is_success:
        #     logger.info(f"✅ Test space deleted: {delete_response.space_id}")
        # else:
        #     logger.warning(f"⚠️  Could not delete space: {delete_response.error_message}")
        logger.info(f"⚠️  Skipping space deletion - space '{space_id}' preserved for inspection")
        
        client.close()
        logger.info("✅ Client closed")


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
