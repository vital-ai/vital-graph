#!/usr/bin/env python3
"""
VitalGraph KGTypes Endpoint Test (JWT Client)

Comprehensive test script for KGTypes endpoint operations using VitalGraph client.
Tests KGType creation, listing, retrieval, updating, and deletion using modular test cases.

Architecture: Uses client-based testing with modular test cases and proper space management.
"""

import sys
import os
import logging
from pathlib import Path
from typing import Dict, Any, List

# Add project root to Python path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph.model.spaces_model import Space, SpacesListResponse
from vitalgraph.model.kgtypes_model import KGTypeListResponse, KGTypeGetResponse

# Import test data creator
from vitalgraph_client_test.client_test_data import ClientTestDataCreator

# Import modular test cases
from vitalgraph_client_test.kgtypes.case_kgtype_create import KGTypeCreateTester
from vitalgraph_client_test.kgtypes.case_kgtype_list import KGTypeListTester
from vitalgraph_client_test.kgtypes.case_kgtype_get import KGTypeGetTester
from vitalgraph_client_test.kgtypes.case_kgtype_update import KGTypeUpdateTester
from vitalgraph_client_test.kgtypes.case_kgtype_delete import KGTypeDeleteTester


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)


def test_kgtypes_endpoint(config_path: str) -> bool:
    """
    Test the KGTypes endpoint operations using VitalGraph client.
    
    Args:
        config_path: Path to configuration file (required)
        
    Returns:
        bool: True if all tests passed, False otherwise
    """
    logger = logging.getLogger(__name__)
    
    print("=" * 80)
    print("VitalGraph KGTypes Endpoint Test (JWT Client)")
    print("=" * 80)
    
    test_results = {
        'total_tests': 0,
        'passed_tests': 0,
        'failed_tests': [],
        'test_details': []
    }
    
    test_space_id = None
    test_graph_id = "urn:test_kgtypes"
    created_kgtypes = []
    client = None
    
    try:
        # Initialize and connect client with JWT
        # Use short token expiry (15 seconds) to test token refresh functionality
        print("\n1. Initializing and connecting JWT client...")
        print("   ⚠️  Using 15-second token expiry to test automatic token refresh")
        print("   ⚠️  Proactive refresh ENABLED - will refresh token before expiry")
        client = VitalGraphClient(config_path, token_expiry_seconds=15)
        
        client.open()
        print(f"   ✓ JWT client connected: {client.is_connected()}")
        
        # Display JWT authentication status
        server_info: Dict[str, Any] = client.get_server_info()
        auth_info = server_info.get('authentication', {})
        print(f"   ✓ JWT Authentication Active:")
        print(f"     - Access Token: {'✓' if auth_info.get('has_access_token') else '✗'}")
        print(f"     - Refresh Token: {'✓' if auth_info.get('has_refresh_token') else '✗'}")
        print(f"     - Token Expiry: 15 seconds (testing mode)")
        
        # Create or use test space
        print("\n2. Setting up test space...")
        test_space_id = "space_client_test"  # Dedicated space for client tests
        
        # Check if space already exists
        spaces_response: SpacesListResponse = client.list_spaces()
        existing_spaces = spaces_response.spaces
        existing_space = next((s for s in existing_spaces if s.space == test_space_id), None)
        
        if existing_space:
            print(f"   ⚠️  Found existing test space '{test_space_id}', deleting it first...")
            try:
                delete_response = client.delete_space(test_space_id)
                if delete_response and hasattr(delete_response, 'success') and delete_response.success:
                    print(f"   ✓ Existing space deleted successfully")
                else:
                    error_msg = delete_response.message if delete_response and hasattr(delete_response, 'message') else 'Unknown error'
                    print(f"   ❌ Failed to delete existing space: {error_msg}")
                    return False
            except Exception as e:
                print(f"   ❌ Exception deleting existing space: {e}")
                return False
        
        # Create fresh test space
        print(f"   📝 Creating fresh test space: {test_space_id}")
        try:
            from vitalgraph.model.spaces_model import Space
            space_data = Space(
                space=test_space_id,
                space_name="KGTypes Client Test Space",
                space_description="Dedicated space for VitalGraph client KGTypes endpoint testing",
                tenant="test_tenant"
            )
            
            create_response = client.add_space(space_data)
            if create_response and create_response.created_count == 1:
                print(f"   ✓ Test space created successfully: {test_space_id}")
            else:
                print(f"   ❌ Failed to create test space: {create_response.get('message', 'Unknown error') if create_response else 'No response'}")
                return False
        except Exception as e:
            print(f"   ❌ Exception creating test space: {e}")
            return False
        
        # Create test data using ClientTestDataCreator
        print("\n   📝 Creating test KGType objects...")
        data_creator = ClientTestDataCreator()
        test_kgtypes = data_creator.create_test_kgtype_objects()
        print(f"   ✓ Created {len(test_kgtypes)} test KGType objects")
        
        # Extract URIs for tracking
        created_kgtypes = [str(kgtype.URI) for kgtype in test_kgtypes]
        
        # Test 1: KGType creation using client KGTypes endpoint
        print("\n3. Testing KGType creation using client KGTypes endpoint...")
        create_tester = KGTypeCreateTester(client)
        create_results = create_tester.run_tests(test_space_id, test_graph_id, test_kgtypes)
        test_results['test_details'].append(create_results)
        test_results['total_tests'] += create_results['total_tests']
        test_results['passed_tests'] += create_results['passed_tests']
        
        if create_results['passed']:
            print(f"   ✓ KGType creation tests PASSED: {create_results['passed_tests']}/{create_results['total_tests']}")
        else:
            print(f"   ❌ KGType creation tests FAILED: {create_results['total_tests'] - create_results['passed_tests']} failures")
            test_results['failed_tests'].extend([r['name'] for r in create_results['results'] if not r['passed']])
        
        # Test 2: KGType listing using client KGTypes endpoint
        print("\n4. Testing KGType listing using client KGTypes endpoint...")
        list_tester = KGTypeListTester(client)
        list_results = list_tester.run_tests(test_space_id, test_graph_id)
        test_results['test_details'].append(list_results)
        test_results['total_tests'] += list_results['total_tests']
        test_results['passed_tests'] += list_results['passed_tests']
        
        if list_results['passed']:
            print(f"   ✓ KGType listing tests PASSED: {list_results['passed_tests']}/{list_results['total_tests']}")
        else:
            print(f"   ❌ KGType listing tests FAILED: {list_results['total_tests'] - list_results['passed_tests']} failures")
            test_results['failed_tests'].extend([r['name'] for r in list_results['results'] if not r['passed']])
        
        # Force token expiry to test automatic refresh
        print("\n   ⏳ Waiting 20 seconds to force token expiry (testing automatic refresh)...")
        import time
        time.sleep(20)
        print("   ✓ Token should now be expired - next request will test 401 retry logic")
        
        # Test 3: KGType retrieval using client KGTypes endpoint (BEFORE deletion tests)
        print("\n5. Testing KGType retrieval using client KGTypes endpoint...")
        get_tester = KGTypeGetTester(client)
        get_results = get_tester.run_tests(test_space_id, test_graph_id, created_kgtypes)
        test_results['test_details'].append(get_results)
        test_results['total_tests'] += get_results['total_tests']
        test_results['passed_tests'] += get_results['passed_tests']
        
        if get_results['passed']:
            print(f"   ✓ KGType retrieval tests PASSED: {get_results['passed_tests']}/{get_results['total_tests']}")
        else:
            print(f"   ❌ KGType retrieval tests FAILED: {get_results['total_tests'] - get_results['passed_tests']} failures")
            test_results['failed_tests'].extend([r['name'] for r in get_results['results'] if not r['passed']])
        
        # Test 4: KGType updating using client KGTypes endpoint
        print("\n6. Testing KGType updating using client KGTypes endpoint...")
        update_tester = KGTypeUpdateTester(client)
        update_results = update_tester.run_tests(test_space_id, test_graph_id, test_kgtypes, created_kgtypes)
        test_results['test_details'].append(update_results)
        test_results['total_tests'] += update_results['total_tests']
        test_results['passed_tests'] += update_results['passed_tests']
        
        if update_results['passed']:
            print(f"   ✓ KGType updating tests PASSED: {update_results['passed_tests']}/{update_results['total_tests']}")
        else:
            print(f"   ❌ KGType updating tests FAILED: {update_results['total_tests'] - update_results['passed_tests']} failures")
            test_results['failed_tests'].extend([r['name'] for r in update_results['results'] if not r['passed']])
        
        # Test 5: KGType deletion using client KGTypes endpoint (AFTER get tests)
        print("\n7. Testing KGType deletion using client KGTypes endpoint...")
        delete_tester = KGTypeDeleteTester(client)
        delete_results = delete_tester.run_tests(test_space_id, test_graph_id, created_kgtypes)
        test_results['test_details'].append(delete_results)
        test_results['total_tests'] += delete_results['total_tests']
        test_results['passed_tests'] += delete_results['passed_tests']
        
        if delete_results['passed']:
            print(f"   ✓ KGType deletion tests PASSED: {delete_results['passed_tests']}/{delete_results['total_tests']}")
        else:
            print(f"   ❌ KGType deletion tests FAILED: {delete_results['total_tests'] - delete_results['passed_tests']} failures")
            test_results['failed_tests'].extend([r['name'] for r in delete_results['results'] if not r['passed']])
        
        # Cleanup remaining test KGTypes
        print(f"\n8. Cleaning up remaining test KGTypes...")
        try:
            # List remaining KGTypes
            list_response = client.list_kgtypes(test_space_id, test_graph_id, page_size=100)
            
            # KGTypesListResponse has 'types' attribute, not 'data'
            remaining_kgtypes = list_response.types if hasattr(list_response, 'types') else []
            
            cleanup_count = 0
            for kgtype in remaining_kgtypes:
                try:
                    kgtype_uri = kgtype.get('@id') or kgtype.get('URI')
                    if kgtype_uri:
                        client.delete_kgtype(test_space_id, test_graph_id, kgtype_uri)
                        cleanup_count += 1
                except Exception:
                    pass  # Continue cleanup even if individual deletions fail
            
            if cleanup_count > 0:
                print(f"   ✓ Cleaned up {cleanup_count} remaining KGTypes")
            else:
                print(f"   ✓ No remaining KGTypes to clean up")
        except Exception as e:
            print(f"   ⚠️  Cleanup warning: {e}")
        
        # Cleanup test space
        print(f"\n9. Cleaning up test space...")
        try:
            delete_response = client.delete_space(test_space_id)
            if delete_response and hasattr(delete_response, 'success') and delete_response.success:
                print(f"   ✓ Test space deleted successfully: {test_space_id}")
            elif delete_response and hasattr(delete_response, 'message') and "deleted successfully" in str(delete_response.message):
                # Handle case where success message is present but success flag might be missing/false
                print(f"   ✓ Test space deleted successfully: {test_space_id}")
            else:
                error_msg = delete_response.message if delete_response and hasattr(delete_response, 'message') else 'Unknown error'
                print(f"   ⚠️  Failed to delete test space: {error_msg}")
        except Exception as e:
            print(f"   ⚠️  Exception deleting test space: {e}")
        
        # Close client
        client.close()
        print(f"\n10. Client closed successfully")
        
        # Print comprehensive test summary
        print(f"\n✅ KGTypes endpoint testing completed!")
        print(f"\n📊 Test Summary:")
        print(f"   • Total tests: {test_results['total_tests']}")
        print(f"   • Passed tests: {test_results['passed_tests']}")
        print(f"   • Failed tests: {len(test_results['failed_tests'])}")
        
        if test_results['failed_tests']:
            print(f"   • Failed test names: {', '.join(test_results['failed_tests'])}")
        
        print(f"\n📋 Detailed Test Results:")
        for detail in test_results['test_details']:
            for result in detail['results']:
                status = "✓" if result['passed'] else "❌"
                print(f"   {status} {result['name']}")
                if not result['passed'] and 'error' in result:
                    print(f"     Error: {result['error']}")
        
        # Final result
        all_passed = len(test_results['failed_tests']) == 0
        if all_passed:
            print(f"\n🎉 All KGTypes endpoint tests PASSED!")
            print(f"   KGType operations validated using VitalGraph client KGTypes endpoint methods:")
            print(f"   - client.create_kgtypes()")
            print(f"   - client.list_kgtypes()")
            print(f"   - client.update_kgtypes()")
            print(f"   - client.delete_kgtypes()")
            print(f"\n🎉 KGTypes endpoint testing completed successfully!")
            print(f"✅ KGType operations validated with VitalGraph client KGTypes endpoint!")
            print(f"   All KGType CRUD operations are working correctly through the client interface.")
            print(f"   Used modular test cases with proper client method calls.")
        else:
            print(f"\n❌ Some KGTypes endpoint tests FAILED!")
            print(f"   {len(test_results['failed_tests'])} out of {test_results['total_tests']} tests failed")
            print(f"\n❌ KGTypes endpoint testing failed.")
            print(f"   Check the error messages above for details.")
        
        return all_passed
        
    except VitalGraphClientError as e:
        print(f"\n✗ VitalGraph client error: {e}")
        return False
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if client:
            try:
                client.close()
                print(f"   ✓ Client connection closed")
            except Exception:
                pass


def main():
    """Main entry point for the test script."""
    logger = logging.getLogger(__name__)
    
    print("Starting VitalGraph KGTypes Endpoint Test...")
    
    # Determine config file path (required for JWT client)
    config_dir = Path(__file__).parent.parent / "vitalgraphclient_config"
    config_file = config_dir / "vitalgraphclient-config.yaml"
    
    if config_file.exists():
        config_path = str(config_file)
        print(f"✓ Found config file: {config_path}")
    else:
        print(f"❌ Config file not found: {config_file}")
        print("   JWT client requires a configuration file.")
        print("   Please ensure vitalgraphclient-config.yaml exists in the vitalgraphclient_config directory.")
        return 1
    
    # Run KGTypes endpoint tests
    success = test_kgtypes_endpoint(config_path)
    
    if success:
        print("\n🎉 KGTypes endpoint testing completed successfully!")
        print("\n✅ KGType operations validated with VitalGraph client KGTypes endpoint!")
        print("   All KGType CRUD operations are working correctly through the client interface.")
        print("   Used modular test cases with proper client method calls.")
        return 0
    else:
        print("\n❌ KGTypes endpoint testing failed.")
        print("   Check the error messages above for details.")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
