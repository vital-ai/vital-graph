#!/usr/bin/env python3
"""
Delete Test Space Script

Deletes the specified space and all its data using the VitalGraph JWT client.
This is a cleanup script to remove test data after testing is complete.

UPDATED: Now uses typed client methods with SpacesListResponse and 
SpaceDeleteResponse models for full type safety.
"""

import sys
import logging
from pathlib import Path
from typing import Optional

# Add the project root to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph.model.spaces_model import SpacesListResponse, SpaceDeleteResponse


def setup_logging():
    """Set up logging configuration for the test."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


def delete_test_space(config_path: str, space_name: str) -> bool:
    """
    Delete the specified space and all its data.
    
    Args:
        config_path: Path to configuration file (required)
        space_name: Name of the space to delete (required)
        
    Returns:
        bool: True if deletion was successful, False otherwise
    """
    logger = logging.getLogger(__name__)
    
    print("=" * 80)
    print("VitalGraph Test Space Deletion (JWT)")
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
        
        # Find the specified space
        print(f"\n2. Looking for space '{space_name}' to delete...")
        spaces_response = client.spaces.list_spaces()
        if not spaces_response.is_success:
            print(f"   ❌ Failed to list spaces: {spaces_response.error_message}")
            return False
        
        existing_spaces = spaces_response.spaces
        print(f"   📊 Found {spaces_response.count} total spaces")
        test_space = next((s for s in existing_spaces if s.space == space_name), None)
        
        if test_space:
            # Use space identifier as fallback if ID is None (like in main test)
            space_id = test_space.id or space_name
            space_display_name = test_space.space_name
            print(f"   ✓ Found space:")
            print(f"     - ID: {space_id}")
            print(f"     - Name: {space_display_name}")
            print(f"     - Space: {space_name}")
            
            # Confirm deletion
            print(f"\n3. Deleting space '{space_name}' (ID: {space_id})...")
            
            try:
                delete_result = client.spaces.delete_space(space_id)
                if delete_result.is_success:
                    print(f"   ✓ Test space deleted successfully!")
                    print(f"   📋 Deletion result:")
                    print(f"     - Space ID: {delete_result.space_id}")
                    print(f"     - Deleted count: {delete_result.deleted_count}")
                    print(f"     - Message: {delete_result.message}")
                else:
                    print(f"   ❌ Failed to delete space: {delete_result.error_message}")
                    return False
                
            except VitalGraphClientError as e:
                print(f"   ❌ VitalGraph client error deleting test space: {e}")
                raise
            except Exception as e:
                print(f"   ❌ Unexpected error deleting test space: {e}")
                raise VitalGraphClientError(f"Failed to delete test space: {e}")
        else:
            print(f"   ℹ️  Space '{space_name}' not found")
            print(f"   📋 Available spaces:")
            for space in existing_spaces:
                print(f"     - ID: {space.id}, Name: {space.space_name}, Space: {space.space}")
            print(f"   ✓ Nothing to delete - space does not exist")
        
        # Verify deletion
        print("\n4. Verifying deletion...")
        updated_spaces_response = client.spaces.list_spaces()
        if not updated_spaces_response.is_success:
            print(f"   ⚠️  Could not verify deletion: {updated_spaces_response.error_message}")
            return False
        
        updated_spaces = updated_spaces_response.spaces
        remaining_test_space = next((s for s in updated_spaces if s.space == space_name), None)
        
        if remaining_test_space:
            print(f"   ❌ Test space still exists after deletion attempt!")
            return False
        else:
            print(f"   ✓ Test space successfully removed")
            print(f"   📊 Remaining spaces: {updated_spaces_response.count}")
        
        # Close client
        client.close()
        print(f"\n5. Client closed successfully")
        
        print(f"\n✅ Test space deletion completed successfully!")
        print(f"\n📊 Summary:")
        if test_space:
            print(f"   • Deleted space: {space_name} (ID: {space_id})")
            print(f"   • All test data and tables removed")
        else:
            print(f"   • No test space found to delete")
        print(f"   • Cleanup operation complete")
        
    except VitalGraphClientError as e:
        print(f"   ❌ VitalGraph client error: {e}")
        logger.error(f"Client error: {e}")
        return False
    except Exception as e:
        print(f"   ❌ Unexpected error: {e}")
        logger.error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


def main() -> int:
    """Main function to delete test space.
    
    Returns:
        int: Exit code (0 for success, 1 for failure)
    """
    import argparse
    
    setup_logging()
    logger = logging.getLogger(__name__)
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Delete a VitalGraph space and all its data")
    parser.add_argument("space_name", help="Name of the space to delete")
    parser.add_argument("--config", default="vitalgraphclient_config/vitalgraphclient-config.yaml",
                       help="Path to VitalGraph client config file")
    
    args = parser.parse_args()
    
    print("Starting VitalGraph Test Space Deletion...")
    print(f"Target space: {args.space_name}")
    
    # Determine config file path (required for JWT client)
    config_path = Path(args.config)
    
    if config_path.exists():
        print(f"✓ Found config file: {config_path}")
    else:
        print(f"❌ Config file not found: {config_path}")
        print("   JWT client requires a configuration file.")
        print("   Please ensure vitalgraphclient-config.yaml exists in the vitalgraphclient_config directory.")
        return 1
    
    # Delete specified space
    success = delete_test_space(str(config_path), args.space_name)
    
    if success:
        print("\n🎉 Space deletion completed successfully!")
        print("\n🧹 Cleanup complete with typed client methods!")
        print(f"   The '{args.space_name}' space and all its data have been removed.")
        print("   Used typed SpacesListResponse and SpaceDeleteResponse models for full type safety.")
        return 0
    else:
        print("\n❌ Space deletion failed.")
        print("   Check the error messages above for details.")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
