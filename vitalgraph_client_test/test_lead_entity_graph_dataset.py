#!/usr/bin/env python3
"""
Lead Entity Graph Dataset Test - Main Orchestrator

This test loads a complete dataset of lead entity graphs from N-Triples files
and performs read-only query and retrieval operations on the loaded data.

Test Flow:
1. Bulk load all lead entity graph files (up to 100 files)
2. List and query entities (pagination, filtering, SPARQL queries)
3. Retrieve entity graphs and frames (sample entities)
4. KGQuery frame-based queries (find leads by criteria)

This test is designed to validate performance and functionality with a larger
dataset and focuses on read-only operations after the initial bulk load.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import List

# Add project root to Python path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.spaces_model import Space

# Import test case modules
from vitalgraph_client_test.entity_graph_lead_dataset.case_bulk_load_dataset import BulkLoadDatasetTester
from vitalgraph_client_test.entity_graph_lead_dataset.case_list_and_query_entities import ListAndQueryEntitiesTester
from vitalgraph_client_test.entity_graph_lead_dataset.case_retrieve_entity_graphs import RetrieveEntityGraphsTester
from vitalgraph_client_test.entity_graph_lead_dataset.case_kgquery_lead_queries import KGQueryLeadQueriesTester

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
    print_section("Lead Entity Graph Dataset Test Suite")
    
    # Configuration
    base_url = "http://localhost:8000"
    space_id = "space_lead_dataset_test"
    graph_id = "urn:lead_entity_graph_dataset"
    lead_data_dir = Path(__file__).parent.parent / "lead_test_data"
    
    # Load up to 100 lead files (set to None to load all available)
    max_files = 100 # None
    
    # Skip data loading if data is already loaded (set to True to skip)
    skip_load = True
    
    # Number of entities to sample for detailed retrieval testing
    sample_size = 5
    
    logger.info(f"Base URL: {base_url}")
    logger.info(f"Space ID: {space_id}")
    logger.info(f"Graph ID: {graph_id}")
    logger.info(f"Lead Data Directory: {lead_data_dir}")
    logger.info(f"Skip Data Load: {skip_load}")
    logger.info(f"Max Files to Load: {max_files if max_files else 'all'}")
    logger.info(f"Sample Size for Retrieval: {sample_size}")
    
    # Check if lead data directory exists
    if not lead_data_dir.exists():
        logger.error(f"❌ Lead data directory not found: {lead_data_dir}")
        return False
    
    # Get lead files
    lead_files = get_lead_files(lead_data_dir, limit=max_files)
    
    if not lead_files:
        logger.error(f"❌ No lead files found in {lead_data_dir}")
        return False
    
    logger.info(f"Found {len(lead_files)} lead file(s) to load")
    
    # Initialize client
    logger.info("\n🔌 Connecting to VitalGraph...")
    config_path = project_root / "vitalgraphclient_config" / "vitalgraphclient-config.yaml"
    client = VitalGraphClient(str(config_path))
    
    # Connect
    logger.info("🔐 Connecting to VitalGraph server...")
    client.open()
    if not client.is_connected():
        logger.error("❌ Connection failed!")
        return False
    logger.info("✅ Connected successfully\n")
    
    # Only delete and recreate space if we're loading data
    if not skip_load:
        # List all spaces and delete test space if it exists
        logger.info(f"📦 Listing all spaces...")
        try:
            spaces_response = client.spaces.list_spaces()
            if spaces_response.is_success:
                logger.info(f"   Found {len(spaces_response.spaces)} spaces")
                existing_space = next((s for s in spaces_response.spaces if s.space == space_id), None)
                
                if existing_space:
                    logger.info(f"   Found existing test space '{space_id}', deleting...")
                    delete_response = client.spaces.delete_space(space_id)
                    if delete_response.is_success:
                        logger.info(f"   ✅ Existing test space deleted")
                    else:
                        logger.warning(f"   ⚠️  Failed to delete existing space: {delete_response.error_message}")
        except Exception as e:
            logger.warning(f"⚠️  Error listing/deleting spaces: {e}")
        
        # Create fresh test space
        logger.info(f"\n📦 Creating test space '{space_id}'...")
        try:
            space = Space(space=space_id, space_name="Lead Entity Graph Dataset Test Space")
            create_response = client.spaces.create_space(space)
            
            if not create_response.is_success:
                logger.error(f"Failed to create space: {create_response.error_message}")
                return False
            logger.info(f"✅ Test space created\n")
        except Exception as e:
            logger.error(f"❌ Error creating space: {e}")
            return False
    else:
        logger.info(f"\n📦 Using existing test space '{space_id}' (skip_load=True)\n")
    
    # Track all test results
    all_results = []
    
    try:
        # ====================================================================
        # STEP 1: Bulk Load Lead Dataset (Optional)
        # ====================================================================
        if skip_load:
            logger.info("\n⏭️  Skipping data load (skip_load=True)")
            logger.info("   Assuming data is already loaded in the space\n")
            loaded_entities = []
            entity_count = 100  # Expected entity count from previous load
            
            # Create a placeholder result for skipped load
            bulk_load_results = {
                "test_name": "Bulk Load Lead Dataset (Skipped)",
                "tests_run": 0,
                "tests_passed": 0,
                "tests_failed": 0,
                "errors": [],
                "loaded_entities": [],
                "load_time": 0,
                "total_triples": 192810  # Expected from 100 entities
            }
            all_results.append(bulk_load_results)
        else:
            bulk_load_tester = BulkLoadDatasetTester(client)
            bulk_load_results = bulk_load_tester.run_tests(space_id, graph_id, lead_files)
            all_results.append(bulk_load_results)
            
            if bulk_load_results["tests_failed"] > 0:
                logger.error(f"❌ Bulk load failed")
                return False
            
            loaded_entities = bulk_load_results.get("loaded_entities", [])
            entity_count = len(loaded_entities)
            
            if entity_count == 0:
                logger.error(f"❌ No entities loaded")
                return False
            
            logger.info(f"\n✅ Successfully loaded {entity_count} entities")
        
        # ====================================================================
        # STEP 2: List and Query Entities
        # ====================================================================
        list_query_tester = ListAndQueryEntitiesTester(client)
        list_query_results = list_query_tester.run_tests(space_id, graph_id, entity_count)
        all_results.append(list_query_results)
        
        entity_uris = list_query_results.get("entity_uris", [])
        
        # ====================================================================
        # STEP 3: Retrieve Entity Graphs and Frames
        # ====================================================================
        retrieve_tester = RetrieveEntityGraphsTester(client)
        retrieve_results = retrieve_tester.run_tests(
            space_id, 
            graph_id, 
            entity_uris if entity_uris else [e['uri'] for e in loaded_entities],
            sample_size=sample_size
        )
        all_results.append(retrieve_results)
        
        # ====================================================================
        # STEP 4: KGQuery Frame-Based Queries
        # ====================================================================
        kgquery_tester = KGQueryLeadQueriesTester(client)
        kgquery_results = kgquery_tester.run_tests(space_id, graph_id, entity_count)
        all_results.append(kgquery_results)
        
        # ====================================================================
        # Print Summary
        # ====================================================================
        success = print_test_summary(all_results)
        
        # Print dataset statistics
        print_section("Dataset Statistics")
        print(f"Total Files Loaded: {len(lead_files)}")
        print(f"Total Entities: {entity_count}")
        print(f"Total Triples: {bulk_load_results.get('total_triples', 0):,}")
        print(f"Load Time: {bulk_load_results.get('load_time', 0):.2f}s")
        print(f"Average per File: {bulk_load_results.get('load_time', 0)/len(lead_files):.2f}s")
        if retrieve_results.get('total_frames', 0) > 0:
            print(f"Total Frames (sampled): {retrieve_results.get('total_frames', 0)}")
            print(f"Avg Frames per Entity: {retrieve_results.get('total_frames', 0)/sample_size:.1f}")
        
        if success:
            print_section("✅ All Tests Completed Successfully!")
        else:
            print_section("⚠️ Some Tests Failed")
        
        return success
        
    finally:
        # Close client (space is preserved for inspection)
        logger.info(f"\n✅ Test space preserved for inspection:")
        logger.info(f"   Space ID: {space_id}")
        logger.info(f"   Graph ID: {graph_id}")
        logger.info(f"   Note: Space will be deleted on next test run\n")
        
        client.close()
        logger.info("✅ Client closed")


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
