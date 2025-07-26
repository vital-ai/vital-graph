#!/usr/bin/env python3
"""
VitalGraph Client Test Script

Test script for VitalGraph client functionality.
Instantiates the client using configuration file and tests open/close operations.
"""

import sys
import logging
import json
from pathlib import Path

# Add the parent directory to the path so we can import vitalgraph_client
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph_client.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError


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


def test_client_basic_operations(config_path: str = None):
    """
    Test basic client operations: initialization, open, and close.
    
    Args:
        config_path: Optional path to configuration file
    """
    logger = logging.getLogger(__name__)
    
    print("=" * 60)
    print("VitalGraph Client Test - Basic Operations")
    print("=" * 60)
    
    try:
        # Test 1: Client initialization
        print("\n1. Testing client initialization...")
        if config_path:
            print(f"   Using config file: {config_path}")
            client = VitalGraphClient(config_path)
        else:
            print("   Using default config search")
            client = VitalGraphClient()
        
        print(f"   ✓ Client initialized: {client}")
        print(f"   ✓ Server info: {client.get_server_info()}")
        
        # Test 2: Client open
        print("\n2. Testing client open...")
        print(f"   Connection status before open: {client.is_connected()}")
        
        client.open()
        print(f"   ✓ Client opened successfully")
        print(f"   ✓ Connection status after open: {client.is_connected()}")
        print(f"   ✓ Updated server info: {client.get_server_info()}")
        
        # Test 3: Client close
        print("\n3. Testing client close...")
        client.close()
        print(f"   ✓ Client closed successfully")
        print(f"   ✓ Connection status after close: {client.is_connected()}")
        
        print("\n✓ All basic operations completed successfully!")
        
    except VitalGraphClientError as e:
        print(f"   ✗ VitalGraph client error: {e}")
        logger.error(f"Client error: {e}")
        return False
    except Exception as e:
        print(f"   ✗ Unexpected error: {e}")
        logger.error(f"Unexpected error: {e}")
        return False
    
    return True


def test_space_crud_lifecycle(config_path=None):
    """
    Test complete Space CRUD lifecycle: login, list, add, update, get, delete, list.
    
    Args:
        config_path: Optional path to configuration file
    """
    logger = logging.getLogger(__name__)
    
    print("=" * 60)
    print("VitalGraph Client Test - Space CRUD Lifecycle")
    print("=" * 60)
    
    try:
        # Initialize and connect client
        print("\n1. Initializing and connecting client...")
        if config_path:
            client = VitalGraphClient(config_path)
        else:
            client = VitalGraphClient()
        
        client.open()
        print(f"   ✓ Client connected: {client.is_connected()}")
        
        # Step 1: List initial spaces
        print("\n2. Listing initial spaces...")
        initial_spaces = client.list_spaces()
        print(f"   ✓ Found {len(initial_spaces)} initial spaces:")
        for space in initial_spaces:
            print(f"     - ID: {space.get('id')}, Name: {space.get('space_name')}, Space: {space.get('space')}")
        
        # Step 2: Clean up any existing test space first
        print("\n3. Cleaning up any existing test space...")
        test_space_identifier = "test_space_crud"
        existing_test_space = next((s for s in initial_spaces if s.get('space') == test_space_identifier), None)
        
        if existing_test_space:
            print(f"   🧹 Found existing test space '{test_space_identifier}' (ID: {existing_test_space.get('id')}), deleting...")
            try:
                delete_result = client.delete_space(existing_test_space.get('id'))
                print(f"   ✓ Existing test space deleted successfully")
            except Exception as e:
                print(f"   ⚠️  Could not delete existing test space: {e}")
                raise VitalGraphClientError(f"Cannot proceed with test - existing space cleanup failed: {e}")
        else:
            print(f"   ✓ No existing test space found, ready to proceed")
        
        # Step 3: Add a new test space
        print("\n4. Adding new test space...")
        test_space_data = {
            "tenant": "test_tenant",
            "space": test_space_identifier,
            "space_name": "Test Space CRUD",
            "space_description": "Test space for CRUD lifecycle testing"
        }
        print(f"   Space data to add:")
        print(f"   {json.dumps(test_space_data, indent=4)}")
        
        added_space = client.add_space(test_space_data)
        print(f"   ✓ Space added successfully:")
        print(f"   {json.dumps(added_space, indent=4)}")
        
        space_id = added_space.get('id')
        if not space_id:
            raise VitalGraphClientError("Added space does not have an ID")
        
        # Step 3: List spaces after addition
        print("\n4. Listing spaces after addition...")
        spaces_after_add = client.list_spaces()
        print(f"   ✓ Found {len(spaces_after_add)} spaces after addition:")
        for space in spaces_after_add:
            print(f"     - ID: {space.get('id')}, Name: {space.get('space_name')}, Space: {space.get('space')}")
        
        # Verify the space was added
        found_space = next((s for s in spaces_after_add if s.get('id') == space_id), None)
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
        
        updated_space = client.update_space(space_id, update_data)
        print(f"   ✓ Space updated successfully:")
        print(f"   {json.dumps(updated_space, indent=4)}")
        
        # Step 5: Get space by ID to confirm update
        print("\n6. Getting space by ID to confirm update...")
        retrieved_space = client.get_space(space_id)
        print(f"   ✓ Retrieved space by ID {space_id}:")
        print(f"   {json.dumps(retrieved_space, indent=4)}")
        
        # Verify the update worked
        if retrieved_space.get('space_name') != update_data['space_name']:
            raise VitalGraphClientError(f"Space name was not updated correctly")
        if retrieved_space.get('space_description') != update_data['space_description']:
            raise VitalGraphClientError(f"Space description was not updated correctly")
        print(f"   ✓ Confirmed space was updated correctly")
        
        # Step 6: Delete the space
        print("\n7. Deleting the test space...")
        delete_result = client.delete_space(space_id)
        print(f"   ✓ Space deleted successfully:")
        print(f"   {json.dumps(delete_result, indent=4)}")
        
        # Step 7: List spaces after deletion to confirm cleanup
        print("\n8. Listing spaces after deletion...")
        final_spaces = client.list_spaces()
        print(f"   ✓ Found {len(final_spaces)} spaces after deletion:")
        for space in final_spaces:
            print(f"     - ID: {space.get('id')}, Name: {space.get('space_name')}, Space: {space.get('space')}")
        
        # Verify the space was deleted
        deleted_space = next((s for s in final_spaces if s.get('id') == space_id), None)
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
        
    except VitalGraphClientError as e:
        print(f"   ✗ VitalGraph client error: {e}")
        logger.error(f"Client error: {e}")
        return False
    except Exception as e:
        print(f"   ✗ Unexpected error: {e}")
        logger.error(f"Unexpected error: {e}")
        return False
    
    return True


def main():
    """
    Main function to run VitalGraph client tests.
    """
    setup_logging()
    logger = logging.getLogger(__name__)
    
    print("Starting VitalGraph Client Tests...")
    
    # Determine config file path
    # Look for config file in the vitalgraphclient_config directory
    config_dir = Path(__file__).parent.parent / "vitalgraphclient_config"
    config_file = config_dir / "vitalgraphclient-config.yaml"
    
    config_path = None
    if config_file.exists():
        config_path = str(config_file)
        print(f"Found config file: {config_path}")
    else:
        print("No config file found, will use defaults")
    
    # Run tests
    success = True
    
    # Run basic operations test
    print("\n" + "=" * 80)
    print("RUNNING BASIC OPERATIONS TEST")
    print("=" * 80)
    basic_success = test_client_basic_operations(config_path)
    
    # Run Space CRUD lifecycle test
    print("\n" + "=" * 80)
    print("RUNNING SPACE CRUD LIFECYCLE TEST")
    print("=" * 80)
    crud_success = test_space_crud_lifecycle(config_path)
    
    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print(f"Basic Operations Test: {'✓ PASSED' if basic_success else '✗ FAILED'}")
    print(f"Space CRUD Lifecycle Test: {'✓ PASSED' if crud_success else '✗ FAILED'}")
    
    if basic_success and crud_success:
        print("\n🎉 All tests passed!")
        print("\nReady for additional functionality implementation.")
        return 0
    else:
        print("✗ Some tests failed.")
        print("\nCheck the error messages above for details.")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)