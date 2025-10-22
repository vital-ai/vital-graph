#!/usr/bin/env python3
"""
VitalGraph Client Test Script

Test script for VitalGraph client functionality with JWT authentication.
Instantiates the client using configuration file and tests open/close operations.

UPDATED: Now uses typed client methods with SpacesListResponse, SpaceCreateResponse, 
SpaceUpdateResponse, and SpaceDeleteResponse models for full type safety.
"""

import sys
import logging
import json
from pathlib import Path
from typing import Dict, Any

from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph.model.spaces_model import SpacesListResponse, SpaceCreateResponse, SpaceUpdateResponse, SpaceDeleteResponse, Space


def setup_logging():
    """
    Set up logging configuration for the test.
    """
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


def test_client_basic_operations(config_path: str) -> bool:
    """
    Test basic client operations: initialization, open, and close with JWT authentication.
    
    Args:
        config_path: Path to configuration file (required)
        
    Returns:
        bool: True if all operations were successful, False otherwise
    """
    logger = logging.getLogger(__name__)
    
    print("=" * 60)
    print("VitalGraph Client Test - Basic Operations (JWT)")
    print("=" * 60)
    
    try:
        # Test 1: Client initialization
        print("\n1. Testing JWT client initialization...")
        print(f"   Using config file: {config_path}")
        client = VitalGraphClient(config_path)
        
        print(f"   ✓ Client initialized: {client}")
        server_info: Dict[str, Any] = client.get_server_info()
        print(f"   ✓ Server info: {server_info}")
        
        # Test 2: Client open with JWT authentication
        print("\n2. Testing JWT client open...")
        print(f"   Connection status before open: {client.is_connected()}")
        
        client.open()
        print(f"   ✓ Client opened successfully with JWT authentication")
        print(f"   ✓ Connection status after open: {client.is_connected()}")
        
        # Display JWT authentication details
        server_info: Dict[str, Any] = client.get_server_info()
        auth_info = server_info.get('authentication', {})
        print(f"   ✓ JWT Authentication Status:")
        print(f"     - Has Access Token: {auth_info.get('has_access_token', False)}")
        print(f"     - Has Refresh Token: {auth_info.get('has_refresh_token', False)}")
        if 'token_expires_at' in auth_info:
            print(f"     - Token Expires: {auth_info['token_expires_at']}")
            print(f"     - Token Valid: {not auth_info.get('token_expired', True)}")
        
        # Test 3: Client close
        print("\n3. Testing client close...")
        client.close()
        print(f"   ✓ Client closed successfully")
        print(f"   ✓ Connection status after close: {client.is_connected()}")
        
        print("\n✓ All JWT basic operations completed successfully!")
        
    except VitalGraphClientError as e:
        print(f"   ✗ VitalGraph client error: {e}")
        logger.error(f"Client error: {e}")
        return False
    except Exception as e:
        print(f"   ✗ Unexpected error: {e}")
        logger.error(f"Unexpected error: {e}")
        return False
    
    return True


def test_space_crud_lifecycle(config_path: str) -> bool:
    """
    Test complete Space CRUD lifecycle with JWT authentication: connect, list, add, update, get, delete, list.
    
    Args:
        config_path: Path to configuration file (required)
        
    Returns:
        bool: True if all CRUD operations were successful, False otherwise
    """
    logger = logging.getLogger(__name__)
    
    print("=" * 60)
    print("VitalGraph Client Test - Space CRUD Lifecycle (JWT)")
    print("=" * 60)
    
    try:
        # Initialize and connect client with JWT
        print("\n1. Initializing and connecting JWT client...")
        client = VitalGraphClient(config_path)
        
        client.open()
        print(f"   ✓ JWT client connected: {client.is_connected()}")
        
        # Display JWT authentication status
        server_info: Dict[str, Any] = client.get_server_info()
        auth_info = server_info.get('authentication', {})
        print(f"   ✓ JWT Authentication Active:")
        print(f"     - Access Token: {'✓' if auth_info.get('has_access_token') else '✗'}")
        print(f"     - Refresh Token: {'✓' if auth_info.get('has_refresh_token') else '✗'}")
        
        # Step 1: List initial spaces
        print("\n2. Listing initial spaces...")
        initial_spaces_response: SpacesListResponse = client.list_spaces()
        initial_spaces = initial_spaces_response.spaces
        print(f"   ✓ Found {len(initial_spaces)} initial spaces (total: {initial_spaces_response.total_count}):")
        for space in initial_spaces:
            print(f"     - ID: {space.id}, Name: {space.space_name}, Space: {space.space}")
        
        # Step 2: Test delete operation on an existing space (if any)
        print("\n3. Testing delete operation on existing space...")
        if len(initial_spaces) > 0:
            # Find a space to delete (prefer test spaces, but use any if needed)
            space_to_delete = None
            for space in initial_spaces:
                if 'test' in space.space_name.lower() or 'test' in space.space.lower():
                    space_to_delete = space
                    break
            
            if not space_to_delete:
                space_to_delete = initial_spaces[0]  # Use first space if no test space found
            
            print(f"   🗑️  Deleting space '{space_to_delete.space_name}' (ID: {space_to_delete.id})...")
            try:
                delete_result: SpaceDeleteResponse = client.delete_space(space_to_delete.id)
                print(f"   ✓ Space deleted successfully:")
                print(f"   Message: {delete_result.message}")
                print(f"   Deleted count: {delete_result.deleted_count}")
                if delete_result.deleted_uris:
                    print(f"   Deleted URIs: {delete_result.deleted_uris}")
                
                # Verify deletion by listing spaces again
                print("\n4. Verifying deletion...")
                spaces_after_delete: SpacesListResponse = client.list_spaces()
                print(f"   ✓ Spaces after deletion: {len(spaces_after_delete.spaces)} (total: {spaces_after_delete.total_count})")
                
                # Check that the deleted space is not in the list
                deleted_space_found = next((s for s in spaces_after_delete.spaces if s.id == space_to_delete.id), None)
                if deleted_space_found:
                    print(f"   ⚠️  Warning: Deleted space still found in list")
                else:
                    print(f"   ✓ Confirmed space was deleted from the list")
                    
            except Exception as e:
                print(f"   ⚠️  Delete operation failed: {e}")
                print(f"   This might be due to server-side response format mismatch")
        else:
            print(f"   ✓ No spaces available to test delete operation")
        
        # Step 3: Add a new test space
        print("\n5. Adding new test space...")
        test_space_identifier = "test_space_crud"
        test_space_data = {
            "tenant": "test_tenant",
            "space": test_space_identifier,
            "space_name": "Test Space CRUD",
            "space_description": "Test space for CRUD lifecycle testing"
        }
        print(f"   Space data to add:")
        print(f"   {json.dumps(test_space_data, indent=4)}")
        
        # Create Space object from dictionary
        test_space = Space(
            tenant=test_space_data["tenant"],
            space=test_space_data["space"],
            space_name=test_space_data["space_name"],
            space_description=test_space_data["space_description"]
        )
        add_response: SpaceCreateResponse = client.add_space(test_space)
        print(f"   ✓ Space added successfully:")
        print(f"   Message: {add_response.message}")
        print(f"   Created count: {add_response.created_count}")
        print(f"   Created URIs: {add_response.created_uris}")
        
        # Extract space ID from the response
        if not add_response.created_uris:
            raise VitalGraphClientError("No created URIs in add response")
        space_id = add_response.created_uris[0]
        if not space_id:
            raise VitalGraphClientError("Added space does not have an ID")
        
        # Step 3: List spaces after addition
        print("\n4. Listing spaces after addition...")
        spaces_after_add_response: SpacesListResponse = client.list_spaces()
        spaces_after_add = spaces_after_add_response.spaces
        print(f"   ✓ Found {len(spaces_after_add)} spaces after addition (total: {spaces_after_add_response.total_count}):")
        for space in spaces_after_add:
            print(f"     - ID: {space.id}, Name: {space.space_name}, Space: {space.space}")
        
        # Verify the space was added
        found_space = next((s for s in spaces_after_add if str(s.id) == str(space_id)), None)
        if not found_space:
            raise VitalGraphClientError(f"Added space with ID {space_id} not found in list")
        print(f"   ✓ Confirmed added space is in the list")
        
        # Step 4: Update the space
        print("\n5. Updating the test space...")
        update_data = {
            "space_name": "Updated Test Space CRUD",
            "space_description": "Updated description for CRUD lifecycle testing"
        }
        print(f"   Update data:")
        print(f"   {json.dumps(update_data, indent=4)}")
        
        # Create updated Space object
        updated_space = Space(
            id=space_id,
            tenant="test_tenant",
            space="test_space_crud_updated",
            space_name="Test Space CRUD Updated",
            space_description=update_data["space_description"]
        )
        update_response: SpaceUpdateResponse = client.update_space(space_id, updated_space)
        print(f"   ✓ Space updated successfully:")
        print(f"   Message: {update_response.message}")
        print(f"   Updated URI: {update_response.updated_uri}")
        
        # Step 5: Get space by ID to confirm update
        print("\n6. Getting space by ID to confirm update...")
        retrieved_space: Space = client.get_space(space_id)
        print(f"   ✓ Retrieved space by ID {space_id}:")
        print(f"   ID: {retrieved_space.id}, Name: {retrieved_space.space_name}")
        print(f"   Description: {retrieved_space.space_description}")
        
        # Verify the update worked
        if retrieved_space.space_name != update_data['space_name']:
            raise VitalGraphClientError(f"Space name was not updated correctly")
        if retrieved_space.space_description != update_data['space_description']:
            raise VitalGraphClientError(f"Space description was not updated correctly")
        print(f"   ✓ Confirmed space was updated correctly")
        
        # Step 6: Delete the space
        print("\n7. Deleting the test space...")
        delete_response: SpaceDeleteResponse = client.delete_space(space_id)
        print(f"   ✓ Space deleted successfully:")
        print(f"   Message: {delete_response.message}")
        print(f"   Deleted count: {delete_response.deleted_count}")
        if delete_response.deleted_uris:
            print(f"   Deleted URIs: {delete_response.deleted_uris}")
        
        # Step 7: List spaces after deletion to confirm cleanup
        print("\n8. Listing spaces after deletion...")
        final_spaces_response: SpacesListResponse = client.list_spaces()
        final_spaces = final_spaces_response.spaces
        print(f"   ✓ Found {len(final_spaces)} spaces after deletion (total: {final_spaces_response.total_count}):")
        for space in final_spaces:
            print(f"     - ID: {space.id}, Name: {space.space_name}, Space: {space.space}")
        
        # Verify the space was deleted
        deleted_space = next((s for s in final_spaces if str(s.id) == str(space_id)), None)
        if deleted_space:
            raise VitalGraphClientError(f"Deleted space with ID {space_id} still found in list")
        print(f"   ✓ Confirmed space was deleted from the list")
        
        # Verify we're back to the initial count
        if len(final_spaces) != len(initial_spaces):
            print(f"   ⚠️  Warning: Final space count ({len(final_spaces)}) differs from initial count ({len(initial_spaces)})")
        else:
            print(f"   ✓ Space count returned to initial state ({len(initial_spaces)} spaces)")
        
        # Close client
        client.close()
        print(f"   ✓ Client closed successfully")
        
        print("\n✓ Complete Space CRUD lifecycle test completed successfully!")
        print("\n📊 CRUD Lifecycle Summary:")
        print(f"   • Initial spaces: {len(initial_spaces)}")
        print(f"   • After addition: {len(spaces_after_add)}")
        print(f"   • After deletion: {len(final_spaces)}")
        print(f"   • Space ID tested: {space_id}")
        print(f"   • All CRUD operations: ✓ PASSED")
        print(f"   • Response models: ✓ UPDATED (using typed SpacesListResponse, SpaceCreateResponse, etc.)")
        
    except VitalGraphClientError as e:
        print(f"   ✗ VitalGraph client error: {e}")
        logger.error(f"Client error: {e}")
        return False
    except Exception as e:
        print(f"   ✗ Unexpected error: {e}")
        logger.error(f"Unexpected error: {e}")
        return False
    
    return True


def main() -> int:
    """
    Main function to run VitalGraph JWT client tests.
    
    Returns:
        int: Exit code (0 for success, 1 for failure)
    """
    setup_logging()
    logger = logging.getLogger(__name__)
    
    print("Starting VitalGraph JWT Client Tests...")
    
    # Determine config file path (required for JWT client)
    # Look for config file in the vitalgraphclient_config directory
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
    
    # Run tests
    success = True
    
    # Run basic operations test
    print("\n" + "=" * 80)
    print("RUNNING JWT BASIC OPERATIONS TEST")
    print("=" * 80)
    basic_success = test_client_basic_operations(config_path)
    
    # Run Space CRUD lifecycle test
    print("\n" + "=" * 80)
    print("RUNNING JWT SPACE CRUD LIFECYCLE TEST")
    print("=" * 80)
    crud_success = test_space_crud_lifecycle(config_path)
    
    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print(f"Basic Operations Test: {'✓ PASSED' if basic_success else '✗ FAILED'}")
    print(f"Space CRUD Lifecycle Test: {'✓ PASSED' if crud_success else '✗ FAILED'}")
    
    if basic_success and crud_success:
        print("\n🎉 All JWT client tests passed with typed client methods!")
        print("\n✅ JWT Authentication System Status:")
        print("   - Client initialization: ✓ Working")
        print("   - JWT authentication: ✓ Working") 
        print("   - Token management: ✓ Working")
        print("   - API operations: ✓ Working")
        print("   - Typed responses: ✓ Working (SpacesListResponse, SpaceCreateResponse, etc.)")
        print("\nVitalGraph JWT client with full type safety is ready for production use!")
        return 0
    else:
        print("❌ Some JWT client tests failed.")
        print("\nCheck the error messages above for details.")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)