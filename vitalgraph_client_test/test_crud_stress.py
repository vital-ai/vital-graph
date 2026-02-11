#!/usr/bin/env python3
"""
CRUD Stress Test - Frame Update Focus

This test focuses on CRUD operations with stress testing for frame updates.
It loads data, performs update/delete operations, and verifies results.
Includes N iterations of frame updates with randomized values to reproduce
intermittent failures.

Test Flow:
1. Create organizations with frames
2. Update entities (employee counts) and verify
3. Frame update stress test (N iterations with random values)
4. Delete frames and verify
5. Delete entities and verify
"""

import asyncio
import logging
import sys
import random
import string
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
from vitalgraph_client_test.multi_kgentity.case_frame_operations_reset import FrameOperationsResetTester
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
    """Run the CRUD stress test with frame update iterations."""
    
    # Configuration
    NUM_FRAME_UPDATE_ITERATIONS = 100  # Number of times to repeat frame update test
    
    print_section("🏢 CRUD Stress Test - Frame Update Focus")
    logger.info(f"Configuration: {NUM_FRAME_UPDATE_ITERATIONS} frame update iterations with randomized values\n")
    
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
    space_id = "space_multi_org_crud_test"
    graph_id = "urn:multi_org_crud_graph"
    
    # Check if space already exists and delete it
    logger.info(f"📦 Checking for existing test space: {space_id}")
    try:
        spaces_response = await client.spaces.list_spaces()
        if spaces_response.is_success:
            existing_space = next((s for s in spaces_response.spaces if s.space == space_id), None)
            
            if existing_space:
                logger.info(f"   Found existing space, deleting...")
                delete_response = await client.spaces.delete_space(space_id)
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
    create_response = await client.spaces.create_space(space_data)
    if not create_response.is_success:
        logger.error(f"❌ Failed to create space: {create_response.error_message}")
        return False
    logger.info(f"✅ Test space created: {create_response.space.space if create_response.space else space_id}\n")
    
    # Track all test results
    all_results = []
    
    try:
        # Skip file uploads for stress test - not needed
        file_uris = None
        
        # ====================================================================
        # STEP 2: Create Organizations (with file references)
        # ====================================================================
        create_tester = CreateOrganizationsTester(client)
        create_results = await create_tester.run_tests(space_id, graph_id, file_uris=file_uris)
        all_results.append(create_results)
        
        if create_results["tests_failed"] > 0:
            logger.error("❌ Organization creation failed, stopping tests")
            return False
        
        created_entity_uris = create_results["created_entity_uris"]
        reference_ids = create_results["reference_ids"]
        entity_names = [org["name"] for org in ORGANIZATIONS]
        
        # Skip relation data, events, and other non-essential tests for stress testing
        
        # ====================================================================
        # STEP 8: Update Entities
        # ====================================================================
        update_tester = UpdateEntitiesTester(client)
        update_results = await update_tester.run_tests(space_id, graph_id, created_entity_uris, entity_names)
        all_results.append(update_results)
        
        # ====================================================================
        # STEP 9: Verify Updates
        # ====================================================================
        if update_results.get("updates"):
            verify_tester = VerifyUpdatesTester(client)
            verify_results = await verify_tester.run_tests(space_id, graph_id, created_entity_uris, 
                                                     update_results["updates"])
            all_results.append(verify_results)
        
        # ====================================================================
        # STEP 10: Frame Operations with Stress Testing
        # ====================================================================
        logger.info(f"\n{'='*80}")
        logger.info(f"  Frame Update Stress Test - {NUM_FRAME_UPDATE_ITERATIONS} Iterations")
        logger.info(f"{'='*80}\n")
        logger.info(f"Testing on entity: {entity_names[0]}")
        logger.info(f"Each iteration uses a randomized update value\n")
        
        # Run frame operations stress test with multiple iterations on same entity
        frame_reset_tester = FrameOperationsResetTester(client)
        
        # Track stress test results
        stress_test_passed = 0
        stress_test_failed = 0
        stress_test_fuseki_failures = 0
        stress_test_failures = []
        stress_test_timings = []  # Collect timing data from each iteration
        stress_test_recreate_timings = []  # Collect delete/recreate timing
        
        prev_fuseki_failure = False
        
        for iteration in range(1, NUM_FRAME_UPDATE_ITERATIONS + 1):
            # Generate random value for this iteration
            random_suffix = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
            update_value = f"Industry_{random_suffix}"
            
            logger.info(f"\n--- Iteration {iteration}/{NUM_FRAME_UPDATE_ITERATIONS} (value: '{update_value}') ---")
            
            # Recovery: if the previous iteration had fuseki failures, the frame may
            # be out of sync (deleted from PG but still in Fuseki, or vice versa).
            # Attempt to delete and recreate the frame to resync both stores.
            if prev_fuseki_failure:
                logger.info(f"🔄 RECOVERY: Previous iteration had fuseki failures, resyncing frame data...")
                try:
                    company_frame_uri = f"{created_entity_uris[0].replace('/organization/', '/frame/')}_company"
                    # Step 1: Fetch stale frame objects from Fuseki (they may still exist there)
                    fetch_resp = await client.kgentities.get_kgentity_frames(
                        space_id=space_id, graph_id=graph_id,
                        entity_uri=created_entity_uris[0],
                        frame_uris=[company_frame_uri]
                    )
                    saved_objects = list(fetch_resp.frame_graph.objects) if fetch_resp.frame_graph else []
                    logger.info(f"🔄 RECOVERY: Fetched {len(saved_objects)} stale frame objects")
                    
                    # Step 2: Delete to clean up stale Fuseki data
                    del_resp = await client.kgentities.delete_entity_frames(
                        space_id=space_id, graph_id=graph_id,
                        entity_uri=created_entity_uris[0],
                        frame_uris=[company_frame_uri]
                    )
                    _del_ok = getattr(del_resp, 'fuseki_success', None)
                    logger.info(f"🔄 RECOVERY: Delete retry fuseki_success={_del_ok}")
                    
                    # Step 3: Recreate the frame in both PG and Fuseki
                    if saved_objects:
                        create_resp = await client.kgentities.create_entity_frames(
                            space_id=space_id, graph_id=graph_id,
                            entity_uri=created_entity_uris[0],
                            objects=saved_objects
                        )
                        _create_ok = getattr(create_resp, 'fuseki_success', None)
                        logger.info(f"🔄 RECOVERY: Recreate fuseki_success={_create_ok}, success={create_resp.is_success}")
                    else:
                        logger.warning(f"🔄 RECOVERY: No frame objects to recreate — frame may have been fully deleted")
                    
                    prev_fuseki_failure = False
                except Exception as e:
                    logger.error(f"🔄 RECOVERY: Failed to resync: {e}")
            
            # Run frame operations without deletion, with randomized value
            frame_results = await frame_reset_tester.run_tests(
                space_id, graph_id, 
                created_entity_uris[0], entity_names[0],
                update_value=update_value
            )
            
            # Collect timing data if available
            if "timing" in frame_results:
                stress_test_timings.append(frame_results["timing"])
            if "recreate_timing" in frame_results:
                stress_test_recreate_timings.append(frame_results["recreate_timing"])
            
            # Track fuseki failures
            iter_fuseki_failures = frame_results.get('fuseki_failures', 0)
            if iter_fuseki_failures > 0:
                stress_test_fuseki_failures += iter_fuseki_failures
                logger.error(f"⚠️ Iteration {iteration}: {iter_fuseki_failures} FUSEKI_SYNC_FAILURE(s)")
            
            # Track failure state for recovery on next iteration
            # Trigger on ANY failure (fuseki sync failures OR client timeouts) since both
            # can leave frame state inconsistent between PG and Fuseki
            prev_fuseki_failure = frame_results["tests_failed"] > 0
            
            if frame_results["tests_failed"] == 0:
                stress_test_passed += 1
                logger.info(f"✅ Iteration {iteration} PASSED")
            else:
                stress_test_failed += 1
                stress_test_failures.append({
                    'iteration': iteration,
                    'value': update_value,
                    'errors': frame_results.get('errors', [])
                })
                logger.error(f"❌ Iteration {iteration} FAILED: {frame_results.get('errors', [])}")
        
        # Add stress test summary to results
        stress_summary = {
            "test_name": "Frame Update Stress Test",
            "tests_run": NUM_FRAME_UPDATE_ITERATIONS,
            "tests_passed": stress_test_passed,
            "tests_failed": stress_test_failed,
            "errors": [f"Iteration {f['iteration']}: {f['errors']}" for f in stress_test_failures],
            "results": []
        }
        all_results.append(stress_summary)
        
        logger.info(f"\n{'='*80}")
        logger.info(f"  Stress Test Summary")
        logger.info(f"{'='*80}")
        logger.info(f"Total iterations: {NUM_FRAME_UPDATE_ITERATIONS}")
        logger.info(f"Passed: {stress_test_passed}/{NUM_FRAME_UPDATE_ITERATIONS} ({stress_test_passed/NUM_FRAME_UPDATE_ITERATIONS*100:.1f}%)")
        logger.info(f"Failed: {stress_test_failed}/{NUM_FRAME_UPDATE_ITERATIONS} ({stress_test_failed/NUM_FRAME_UPDATE_ITERATIONS*100:.1f}%)")
        logger.info(f"Fuseki sync failures: {stress_test_fuseki_failures}")
        if stress_test_failures:
            for f in stress_test_failures:
                logger.info(f"  Iteration {f['iteration']} (value: '{f['value']}'): {f['errors']}")
        
        # Timing summary
        if stress_test_timings:
            get_times = [t["get"] for t in stress_test_timings]
            update_times = [t["update"] for t in stress_test_timings]
            verify_times = [t["verify"] for t in stress_test_timings]
            total_times = [t["total"] for t in stress_test_timings]
            
            logger.info(f"\n{'='*80}")
            logger.info(f"  Timing Summary ({len(stress_test_timings)} iterations)")
            logger.info(f"{'='*80}")
            logger.info(f"{'Operation':<12} {'Min':>8} {'Max':>8} {'Avg':>8}")
            logger.info(f"{'-'*40}")
            logger.info(f"{'Get':<12} {min(get_times):>7.3f}s {max(get_times):>7.3f}s {sum(get_times)/len(get_times):>7.3f}s")
            logger.info(f"{'Update':<12} {min(update_times):>7.3f}s {max(update_times):>7.3f}s {sum(update_times)/len(update_times):>7.3f}s")
            logger.info(f"{'Verify':<12} {min(verify_times):>7.3f}s {max(verify_times):>7.3f}s {sum(verify_times)/len(verify_times):>7.3f}s")
            logger.info(f"{'-'*40}")
            logger.info(f"{'Total':<12} {min(total_times):>7.3f}s {max(total_times):>7.3f}s {sum(total_times)/len(total_times):>7.3f}s")
        
        # Delete/recreate timing summary
        if stress_test_recreate_timings:
            del_times = [t["delete"] for t in stress_test_recreate_timings]
            del_ver_times = [t["delete_verify"] for t in stress_test_recreate_timings]
            rec_times = [t["recreate"] for t in stress_test_recreate_timings]
            rev_times = [t["verify"] for t in stress_test_recreate_timings]
            rec_total_times = [t["total"] for t in stress_test_recreate_timings]
            
            logger.info(f"\n{'='*80}")
            logger.info(f"  Delete/Recreate Timing ({len(stress_test_recreate_timings)} iterations)")
            logger.info(f"{'='*80}")
            logger.info(f"{'Operation':<14} {'Min':>8} {'Max':>8} {'Avg':>8}")
            logger.info(f"{'-'*42}")
            logger.info(f"{'Delete':<14} {min(del_times):>7.3f}s {max(del_times):>7.3f}s {sum(del_times)/len(del_times):>7.3f}s")
            logger.info(f"{'Del Verify':<14} {min(del_ver_times):>7.3f}s {max(del_ver_times):>7.3f}s {sum(del_ver_times)/len(del_ver_times):>7.3f}s")
            logger.info(f"{'Recreate':<14} {min(rec_times):>7.3f}s {max(rec_times):>7.3f}s {sum(rec_times)/len(rec_times):>7.3f}s")
            logger.info(f"{'Verify':<14} {min(rev_times):>7.3f}s {max(rev_times):>7.3f}s {sum(rev_times)/len(rev_times):>7.3f}s")
            logger.info(f"{'-'*42}")
            logger.info(f"{'Total':<14} {min(rec_total_times):>7.3f}s {max(rec_total_times):>7.3f}s {sum(rec_total_times)/len(rec_total_times):>7.3f}s")
        
        # Skip KGQuery tests for stress testing - not needed
        
        # ====================================================================
        # List entities before deletion
        # ====================================================================
        logger.info(f"\n{'='*80}")
        logger.info(f"  Listing Entities Before Deletion")
        logger.info(f"{'='*80}\n")
        
        list_before_response = await client.kgentities.list_kgentities(
            space_id=space_id,
            graph_id=graph_id,
            page_size=20,
            offset=0
        )
        
        entities_before_delete = []
        if list_before_response.is_success and list_before_response.objects:
            logger.info(f"Found {len(list_before_response.objects)} entities before deletion:")
            for i, entity in enumerate(list_before_response.objects, 1):
                entity_type = type(entity).__name__
                entity_uri = str(entity.URI) if hasattr(entity, 'URI') else 'NO_URI'
                entity_name = str(entity.name) if hasattr(entity, 'name') else 'NO_NAME'
                logger.info(f"  {i}. {entity_type}: {entity_name} ({entity_uri})")
                entities_before_delete.append(entity_uri)
        else:
            logger.info("No entities found")
        
        # ====================================================================
        # STEP 11: Delete Entities
        # ====================================================================
        # DeleteEntitiesTester only deletes last 3 entities, so expect 7 remaining
        delete_tester = DeleteEntitiesTester(client)
        delete_results = await delete_tester.run_tests(space_id, graph_id, created_entity_uris, entity_names, 
                                                  expected_remaining=7)
        all_results.append(delete_results)
        
        # ====================================================================
        # Diagnose: List remaining entities
        # ====================================================================
        logger.info(f"\n{'='*80}")
        logger.info(f"  Diagnosing Remaining Entities")
        logger.info(f"{'='*80}\n")
        
        list_response = await client.kgentities.list_kgentities(
            space_id=space_id,
            graph_id=graph_id,
            page_size=20,
            offset=0
        )
        
        if list_response.is_success and list_response.objects:
            logger.info(f"Found {len(list_response.objects)} remaining entities:")
            for i, entity in enumerate(list_response.objects, 1):
                entity_type = type(entity).__name__
                entity_uri = str(entity.URI) if hasattr(entity, 'URI') else 'NO_URI'
                entity_name = str(entity.name) if hasattr(entity, 'name') else 'NO_NAME'
                logger.info(f"  {i}. {entity_type}: {entity_name} ({entity_uri})")
        else:
            logger.info("No entities found (as expected)")
        
        # ====================================================================
        # Print Summary
        # ====================================================================
        success = print_test_summary(all_results)
        
        # Skip KGQuery performance summary for stress test
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
        
        await client.close()
        logger.info("✅ Client closed")


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
