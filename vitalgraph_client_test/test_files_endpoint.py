#!/usr/bin/env python3
"""
VitalGraph Files Endpoint Test (JWT Client)

Comprehensive test script for Files endpoint operations using VitalGraph client.
Tests file node creation, listing, retrieval, updating, deletion, and binary operations.

Architecture: Direct client testing pattern:
- Files endpoint: Creates file nodes, uploads/downloads content, pumps files

Follows the pattern from KGFrames client test implementation.
"""

import sys
import os
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, List

# Add project root to Python path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph.model.spaces_model import Space, SpacesListResponse

# Import test case modules
from vitalgraph_client_test.files.case_file_create import run_file_creation_tests
from vitalgraph_client_test.files.case_file_list import run_file_list_tests
from vitalgraph_client_test.files.case_file_upload import run_file_upload_tests
from vitalgraph_client_test.files.case_file_download import run_file_download_tests
from vitalgraph_client_test.files.case_file_stream_upload import run_file_stream_upload_tests
from vitalgraph_client_test.files.case_file_stream_download import run_file_stream_download_tests
from vitalgraph_client_test.files.case_file_delete import run_file_delete_tests

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)


async def test_files_endpoint(config_path: str) -> bool:
    """
    Test the Files endpoint operations using VitalGraph client.
    
    Args:
        config_path: Path to client configuration file
        
    Returns:
        bool: True if all tests passed, False otherwise
    """
    logger = logging.getLogger(__name__)
    
    print("=" * 80)
    print("VitalGraph Files Endpoint Testing")
    print("   Using direct client testing with file operations")
    print("=" * 80)
    
    try:
        # Initialize and connect client with JWT
        print("\n1. Initializing and connecting JWT client...")
        client = VitalGraphClient(config_path)
        
        client.open()
        print(f"   ✓ JWT client connected: {client.is_connected()}")
        
        # Display JWT authentication status
        server_info = client.get_server_info()
        auth_info = server_info.get('authentication', {})
        print(f"   ✓ JWT Authentication Active:")
        print(f"     - Access Token: {'✓' if auth_info.get('has_access_token') else '✗'}")
        print(f"     - Refresh Token: {'✓' if auth_info.get('has_refresh_token') else '✗'}")
        
        # Create or use test space
        print("\n2. Setting up test space...")
        test_space_id = "space_client_files_test"  # Dedicated space for Files client tests
        test_graph_id = "urn:test_files"
        
        # Check if space already exists
        spaces_response = client.spaces.list_spaces()
        if spaces_response.is_success:
            existing_space = next((s for s in spaces_response.spaces if s.space == test_space_id), None)
            
            if existing_space:
                print(f"   ⚠️  Found existing test space '{test_space_id}', deleting it first...")
                try:
                    delete_response = client.spaces.delete_space(test_space_id)
                    if delete_response.is_success:
                        print(f"   ✓ Existing space deleted")
                    else:
                        print(f"   ⚠️  Could not delete existing space: {delete_response.error_message}")
                        return False
                except Exception as e:
                    print(f"   ⚠️  Exception deleting existing space: {e}")
                    return False
        
        # Create fresh test space
        print(f"\n2. Creating test space: {test_space_id}")
        try:
            space_data = Space(
                space=test_space_id,
                space_name="Files Endpoint Test Space",
                space_description="Test space for files endpoint operations",
                tenant="test_tenant"
            )
            
            create_response = client.spaces.create_space(space_data)
            if create_response.is_success:
                print(f"   ✓ Test space created successfully: {create_response.space.space if create_response.space else test_space_id}")
            else:
                print(f"   ❌ Failed to create test space: {create_response.error_message}")
                return False
        except Exception as e:
            print(f"   ❌ Exception creating test space: {e}")
            return False
        
        # Initialize test results tracking
        all_results = []
        total_tests = 0
        total_passed = 0
        total_failed = 0
        
        # Track created file URIs for validation
        created_file_uris = []
        
        # Define test file URIs
        test_file_uri = "haley:file_test_document_001"
        test_source_uri = "haley:file_test_document_001"
        test_target_uri = "haley:file_test_pumped_001"
        
        # Run comprehensive test suites
        print("\n3. Running File Creation Tests...")
        try:
            success, created_uris = await run_file_creation_tests(
                client, test_space_id, test_graph_id, logger=logger
            )
            created_file_uris = created_uris
            all_results.append(("File Creation Tests", success))
            total_tests += 1
            if success:
                total_passed += 1
                print(f"   ✅ Created {len(created_file_uris)} file(s) for testing")
            else:
                total_failed += 1
        except Exception as e:
            print(f"   ❌ File Creation Tests failed: {e}")
            all_results.append(("File Creation Tests", False))
            total_tests += 1
            total_failed += 1
        
        print("\n4. Running File List Tests...")
        try:
            # Pass created file URIs to list tests for validation
            success = await run_file_list_tests(
                client, test_space_id, test_graph_id, logger=logger,
                created_file_uris=created_file_uris
            )
            all_results.append(("File List Tests", success))
            total_tests += 1
            if success:
                total_passed += 1
            else:
                total_failed += 1
        except Exception as e:
            print(f"   ❌ File List Tests failed: {e}")
            all_results.append(("File List Tests", False))
            total_tests += 1
            total_failed += 1
        
        print("\n5. Running File Upload Tests...")
        try:
            success = await run_file_upload_tests(
                client, test_space_id, test_graph_id, test_file_uri, logger=logger
            )
            all_results.append(("File Upload Tests", success))
            total_tests += 1
            if success:
                total_passed += 1
            else:
                total_failed += 1
        except Exception as e:
            print(f"   ❌ File Upload Tests failed: {e}")
            all_results.append(("File Upload Tests", False))
            total_tests += 1
            total_failed += 1
        
        print("\n6. Running File Download Tests...")
        try:
            success = await run_file_download_tests(
                client, test_space_id, test_graph_id, test_file_uri, logger=logger
            )
            all_results.append(("File Download Tests", success))
            total_tests += 1
            if success:
                total_passed += 1
            else:
                total_failed += 1
        except Exception as e:
            print(f"   ❌ File Download Tests failed: {e}")
            all_results.append(("File Download Tests", False))
            total_tests += 1
            total_failed += 1
        
        print("\n7. Running File Streaming Upload Tests...")
        try:
            success = await run_file_stream_upload_tests(
                client, test_space_id, test_graph_id, test_file_uri, logger=logger
            )
            all_results.append(("File Streaming Upload Tests", success))
            total_tests += 1
            if success:
                total_passed += 1
            else:
                total_failed += 1
        except Exception as e:
            print(f"   ❌ File Streaming Upload Tests failed: {e}")
            all_results.append(("File Streaming Upload Tests", False))
            total_tests += 1
            total_failed += 1
        
        print("\n8. Running File Streaming Download Tests...")
        try:
            success = await run_file_stream_download_tests(
                client, test_space_id, test_graph_id, test_file_uri, logger=logger
            )
            all_results.append(("File Streaming Download Tests", success))
            total_tests += 1
            if success:
                total_passed += 1
            else:
                total_failed += 1
        except Exception as e:
            print(f"   ❌ File Streaming Download Tests failed: {e}")
            all_results.append(("File Streaming Download Tests", False))
            total_tests += 1
            total_failed += 1
        
        print("\n9. Running File Delete Tests...")
        try:
            success = await run_file_delete_tests(
                client, test_space_id, test_graph_id, logger=logger
            )
            all_results.append(("File Delete Tests", success))
            total_tests += 1
            if success:
                total_passed += 1
            else:
                total_failed += 1
        except Exception as e:
            print(f"   ❌ File Delete Tests failed: {e}")
            all_results.append(("File Delete Tests", False))
            total_tests += 1
            total_failed += 1
        
        # Print summary
        print("\n" + "=" * 80)
        print("TEST SUMMARY")
        print("=" * 80)
        
        for test_name, success in all_results:
            status = "✅ PASS" if success else "❌ FAIL"
            print(f"{status} - {test_name}")
        
        print("\n" + "-" * 80)
        print(f"Total Tests: {total_tests}")
        print(f"Passed: {total_passed}")
        print(f"Failed: {total_failed}")
        print(f"Success Rate: {(total_passed/total_tests*100):.1f}%")
        print("=" * 80)
        
        # Cleanup test space
        print("\n9. Cleaning up test space...")
        try:
            delete_response = client.spaces.delete_space(test_space_id)
            if delete_response.is_success:
                print(f"   ✓ Test space deleted successfully: {delete_response.space_id}")
            else:
                print(f"   ⚠️  Could not delete test space: {delete_response.error_message}")
        except Exception as e:
            print(f"   ⚠️  Could not delete test space: {e}")
        
        # Close client connection
        client.close()
        print("\n   ✓ Client connection closed")
        
        # Return overall success
        return total_failed == 0
        
    except Exception as e:
        logger.error(f"❌ Test execution failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def main():
    """Main entry point for the test script."""
    # Determine config path
    config_path = Path(__file__).parent.parent / "vitalgraphclient_config" / "vitalgraphclient-config.yaml"
    
    if not config_path.exists():
        print(f"❌ Config file not found: {config_path}")
        print("   Please ensure the client configuration file exists.")
        sys.exit(1)
    
    # Run tests
    success = asyncio.run(test_files_endpoint(str(config_path)))
    
    if success:
        print("\n🎉 All Files endpoint tests passed!")
        sys.exit(0)
    else:
        print("\n💥 Some Files endpoint tests failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
