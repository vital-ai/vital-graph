#!/usr/bin/env python3
"""
Lead Entity Graph Test - Main Orchestrator

This test loads lead entity graphs from N-Triples files and tests
CRUD operations on them.

Test Flow:
1. Load entity graph from N-Triples file
2. Verify entity graph structure
3. Query entity frames
4. Frame operations (list, get, update, delete)
5. Delete entity graph
6. Verify deletion
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
from vitalgraph_client_test.entity_graph_lead.case_load_lead_graph import LoadLeadGraphTester
from vitalgraph_client_test.entity_graph_lead.case_verify_lead_graph import VerifyLeadGraphTester
from vitalgraph_client_test.entity_graph_lead.case_query_lead_graph import QueryLeadGraphTester
from vitalgraph_client_test.entity_graph_lead.case_frame_operations import LeadFrameOperationsTester
from vitalgraph_client_test.entity_graph_lead.case_delete_lead_graph import DeleteLeadGraphTester


def print_section(title: str):
    """Print a formatted section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_test_summary(all_results: List[dict]) -> bool:
    """
    Print summary of all test results.
    
    Args:
        all_results: List of result dictionaries from test cases
        
    Returns:
        True if all tests passed, False otherwise
    """
    print_section("TEST SUMMARY")
    
    total_run = 0
    total_passed = 0
    total_failed = 0
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


def get_lead_files(lead_data_dir: Path, limit: int = None) -> List[Path]:
    """
    Get list of lead N-Triples files.
    
    Args:
        lead_data_dir: Directory containing lead .nt files
        limit: Maximum number of files to return (optional)
        
    Returns:
        List of Path objects for .nt files
    """
    nt_files = sorted(lead_data_dir.glob("lead_*.nt"))
    
    if limit:
        nt_files = nt_files[:limit]
    
    return nt_files


async def main():
    """Main test orchestrator."""
    print_section("Lead Entity Graph Test Suite")
    
    # Configuration
    space_id = "space_lead_entity_graph_test"
    graph_id = "urn:lead_entity_graph"
    lead_data_dir = Path(__file__).parent.parent / "lead_test_data"
    
    # Test with first N lead files (set to None to test all)
    test_file_limit = 3
    
    logger.info(f"Space ID: {space_id}")
    logger.info(f"Graph ID: {graph_id}")
    logger.info(f"Lead Data Directory: {lead_data_dir}")
    
    # Check if lead data directory exists
    if not lead_data_dir.exists():
        logger.error(f"❌ Lead data directory not found: {lead_data_dir}")
        return False
    
    # Get lead files
    lead_files = get_lead_files(lead_data_dir, limit=test_file_limit)
    
    if not lead_files:
        logger.error(f"❌ No lead files found in {lead_data_dir}")
        return False
    
    logger.info(f"Found {len(lead_files)} lead file(s) to test")
    if test_file_limit:
        logger.info(f"Testing first {test_file_limit} file(s)")
    
    # Initialize client
    logger.info("\n🔌 Connecting to VitalGraph...")
    # Configuration loaded from environment variables
    client = VitalGraphClient()
    
    # Connect
    logger.info("🔐 Connecting to VitalGraph server...")
    client.open()
    if not client.is_connected():
        logger.error("❌ Connection failed!")
        return False
    logger.info(f"✅ Connected successfully\n")
    
    # Create test space
    logger.info(f"\n� Creating test space '{space_id}'...")
    try:
        # Delete space if it exists
        try:
            delete_response = client.spaces.delete_space(space_id)
            if delete_response.is_success:
                logger.info(f"   Deleted existing space")
        except:
            pass
        
        # Create new space
        space = Space(space=space_id, space_name="Lead Entity Graph Test Space")
        create_response = client.spaces.create_space(space)
        
        if not create_response.is_success:
            logger.error(f"Failed to create space: {create_response.error_message}")
            return False
        logger.info(f"✅ Test space created\n")
    except Exception as e:
        logger.error(f"❌ Error creating space: {e}")
        return False
    
    # Track all test results
    all_results = []
    
    try:
        # Process each lead file
        for idx, lead_file in enumerate(lead_files, 1):
            logger.info(f"\n{'#' * 80}")
            logger.info(f"  Processing Lead File {idx}/{len(lead_files)}: {lead_file.name}")
            logger.info(f"{'#' * 80}")
            
            # ====================================================================
            # STEP 1: Load Lead Entity Graph
            # ====================================================================
            load_tester = LoadLeadGraphTester(client)
            load_results = load_tester.run_tests(space_id, graph_id, str(lead_file))
            all_results.append(load_results)
            
            if load_results["tests_failed"] > 0:
                logger.error(f"❌ Failed to load lead entity graph from {lead_file.name}")
                continue
            
            entity_uri = load_results.get("entity_uri")
            if not entity_uri:
                logger.error(f"❌ No entity URI found for {lead_file.name}")
                continue
            
            # ====================================================================
            # STEP 2: Verify Lead Entity Graph
            # ====================================================================
            verify_tester = VerifyLeadGraphTester(client)
            verify_results = verify_tester.run_tests(
                space_id, 
                graph_id, 
                entity_uri,
                expected_triple_count=load_results.get("triple_count")
            )
            all_results.append(verify_results)
            
            # ====================================================================
            # STEP 3: Query Lead Entity Graph
            # ====================================================================
            query_tester = QueryLeadGraphTester(client)
            query_results = query_tester.run_tests(space_id, graph_id, entity_uri)
            all_results.append(query_results)
            
            # ====================================================================
            # STEP 4: Frame Operations
            # ====================================================================
            frame_tester = LeadFrameOperationsTester(client)
            frame_results = frame_tester.run_tests(
                space_id, 
                graph_id, 
                entity_uri,
                lead_id=load_results.get("lead_id", "unknown")
            )
            all_results.append(frame_results)
            
            # ====================================================================
            # STEP 5: Delete Lead Entity Graph
            # ====================================================================
            delete_tester = DeleteLeadGraphTester(client)
            delete_results = delete_tester.run_tests(space_id, graph_id, entity_uri)
            all_results.append(delete_results)
        
        # ====================================================================
        # Print Summary
        # ====================================================================
        success = print_test_summary(all_results)
        
        if success:
            print_section("✅ All Tests Completed Successfully!")
        else:
            print_section("⚠️ Some Tests Failed")
        
        return success
        
    finally:
        # Cleanup
        logger.info("\n🧹 Cleaning up test space...")
        # Commented out to preserve space for inspection
        # try:
        #     client.spaces.delete_space(space_id)
        #     logger.info(f"✅ Test space '{space_id}' deleted")
        # except Exception as e:
        #     logger.warning(f"⚠️  Could not delete test space: {e}")
        logger.info(f"⚠️  Space '{space_id}' preserved for inspection")
        
        client.close()
        logger.info("✅ Client closed")


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
