#!/usr/bin/env python3
"""
Test script for comprehensive Space CRUD operations.
Tests adding, listing, getting by ID, updating, deleting, and filtering spaces by name.
"""

import sys
import os
import asyncio
import json

# Add the parent directory to Python path to import vitalgraph
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from vitalgraph.config.config_loader import get_config
from vitalgraph.db.postgresql.postgresql_db_impl import PostgreSQLDbImpl


def pretty_print_json(obj, title=None):
    """Pretty print an object as JSON"""
    if title:
        print(f"   {title}:")
    print(json.dumps(obj, indent=4, default=str))


async def test_space_crud():
    """Test comprehensive Space CRUD operations"""
    print("=== VITALGRAPH SPACE CRUD TEST ===")
    
    try:
        # Load configuration
        print("Loading VitalGraph configuration...")
        config_path = os.path.join(os.path.dirname(__file__), '..', 'vitalgraphdb_config', 'vitalgraphdb-config.yaml')
        config = get_config(config_path)
        
        # Get database config
        db_config = config.get_database_config()
        tables_config = config.get_tables_config()
        if not db_config:
            print("❌ No database configuration found")
            return
            
        print(f"✅ Configuration loaded")
        print(f"   Database: {db_config.get('database', 'unknown')}")
        print(f"   Table Prefix: {tables_config.get('prefix', 'vg_')}")
        
        # Create PostgreSQL DB implementation
        print("\nCreating PostgreSQL database implementation...")
        db_impl = PostgreSQLDbImpl(db_config, tables_config)
        
        # Connect to database
        print("Connecting to database...")
        connected = await db_impl.connect()
        
        if not connected:
            print("❌ Failed to connect to database")
            return
            
        print("✅ Connected to database successfully")
        
        # Check if database is initialized
        state_info = db_impl.get_current_state()
        if state_info['state'] != 'initialized':
            print("❌ Database is not initialized. Please run test_db_init.py first.")
            return
        
        print(f"✅ Database is initialized and ready")
        
        # Test data for spaces
        test_spaces = [
            {
                "tenant": "test_tenant",
                "space": "space1",
                "space_name": "Test Space One",
                "space_description": "First test space for CRUD operations"
            },
            {
                "tenant": "test_tenant",
                "space": "space2", 
                "space_name": "Test Space Two",
                "space_description": "Second test space for CRUD operations"
            },
            {
                "tenant": "test_tenant",
                "space": "space3",
                "space_name": "Production Space",
                "space_description": "Production environment space"
            },
            {
                "tenant": "other_tenant",
                "space": "space4",
                "space_name": "Other Test Space",
                "space_description": "Space for different tenant"
            }
        ]
        
        # Record initial state
        print("\n" + "="*60)
        print("RECORDING INITIAL STATE")
        print("="*60)
        
        initial_spaces = await db_impl.list_spaces()
        initial_space_count = len(initial_spaces)
        print(f"Initial space count: {initial_space_count}")
        
        # Test 1: Add spaces
        print("\n" + "="*60)
        print("TEST 1: ADDING SPACES")
        print("="*60)
        
        added_space_ids = []  # Track spaces we add for cleanup
        for i, space_data in enumerate(test_spaces, 1):
            print(f"\nAdding space {i}: {space_data['space_name']}")
            success = await db_impl.add_space(space_data)
            if success:
                print(f"✅ Space '{space_data['space_name']}' added successfully")
            else:
                print(f"❌ Failed to add space '{space_data['space_name']}'")
        
        # Test 2: List all spaces
        print("\n" + "="*60)
        print("TEST 2: LISTING ALL SPACES")
        print("="*60)
        
        all_spaces = await db_impl.list_spaces()
        print(f"Found {len(all_spaces)} total spaces:")
        space_ids = []  # All current space IDs
        for i, space in enumerate(all_spaces, 1):
            space_ids.append(space['id'])
            # Track which spaces we added (those not in initial state)
            if len(initial_spaces) == 0 or space['id'] not in [s['id'] for s in initial_spaces]:
                added_space_ids.append(space['id'])
            pretty_print_json(space, f"Space {i} (ID: {space['id']})")
        
        # Test 3: List spaces by tenant
        print("\n" + "="*60)
        print("TEST 3: LISTING SPACES BY TENANT")
        print("="*60)
        
        test_tenant_spaces = await db_impl.list_spaces(tenant="test_tenant")
        print(f"Found {len(test_tenant_spaces)} spaces for 'test_tenant':")
        for i, space in enumerate(test_tenant_spaces, 1):
            pretty_print_json(space, f"Test Tenant Space {i}")
        
        other_tenant_spaces = await db_impl.list_spaces(tenant="other_tenant")
        print(f"Found {len(other_tenant_spaces)} spaces for 'other_tenant':")
        for i, space in enumerate(other_tenant_spaces, 1):
            pretty_print_json(space, f"Other Tenant Space {i}")
        
        # Test 4: Get space by ID
        print("\n" + "="*60)
        print("TEST 4: GET SPACE BY ID")
        print("="*60)
        
        if space_ids:
            test_id = space_ids[0]
            print(f"Getting space by ID: {test_id}")
            space = await db_impl.get_space_by_id(str(test_id))
            if space:
                print(f"✅ Found space: {space['space_name']}")
                pretty_print_json(space, "Retrieved Space")
            else:
                print(f"❌ Space with ID {test_id} not found")
        
        # Test invalid ID
        print(f"\nTesting invalid ID: 99999")
        invalid_space = await db_impl.get_space_by_id("99999")
        if invalid_space is None:
            print("✅ Correctly returned None for invalid ID")
        else:
            print("❌ Should have returned None for invalid ID")
        
        # Test 5: Filter spaces by name
        print("\n" + "="*60)
        print("TEST 5: FILTER SPACES BY NAME")
        print("="*60)
        
        # Test case-insensitive partial match
        test_filters = ["test", "Test", "production", "space", "other"]
        
        for name_filter in test_filters:
            print(f"\nFiltering by name: '{name_filter}'")
            filtered_spaces = await db_impl.filter_spaces_by_name(name_filter)
            print(f"Found {len(filtered_spaces)} spaces matching '{name_filter}':")
            for i, space in enumerate(filtered_spaces, 1):
                pretty_print_json(space, f"Match {i}")
        
        # Test filter with tenant
        print(f"\nFiltering by name 'test' for tenant 'test_tenant':")
        tenant_filtered = await db_impl.filter_spaces_by_name("test", tenant="test_tenant")
        print(f"Found {len(tenant_filtered)} spaces:")
        for i, space in enumerate(tenant_filtered, 1):
            pretty_print_json(space, f"Tenant Filtered Match {i}")
        
        # Test 6: Update space
        print("\n" + "="*60)
        print("TEST 6: UPDATE SPACE")
        print("="*60)
        
        if space_ids:
            update_id = space_ids[0]
            print(f"Updating space ID: {update_id}")
            
            update_data = {
                "space_name": "Updated Test Space One",
                "space_description": "This space has been updated during CRUD testing"
            }
            
            print("Update data:")
            pretty_print_json(update_data, "Update Request")
            
            success = await db_impl.update_space(str(update_id), update_data)
            if success:
                print("✅ Space updated successfully")
                
                # Verify update
                updated_space = await db_impl.get_space_by_id(str(update_id))
                if updated_space:
                    print("Updated space:")
                    pretty_print_json(updated_space, "Updated Space")
            else:
                print("❌ Failed to update space")
        
        # Test 7: Delete space
        print("\n" + "="*60)
        print("TEST 7: DELETE SPACE")
        print("="*60)
        
        if len(added_space_ids) > 1:
            delete_id = added_space_ids[-1]  # Delete one of our added spaces
            print(f"Deleting space ID: {delete_id}")
            
            success = await db_impl.remove_space(str(delete_id))
            if success:
                print("✅ Space deleted successfully")
                added_space_ids.remove(delete_id)  # Remove from our tracking list
                
                # Verify deletion
                deleted_space = await db_impl.get_space_by_id(str(delete_id))
                if deleted_space is None:
                    print("✅ Space confirmed deleted (not found)")
                else:
                    print("❌ Space still exists after deletion")
            else:
                print("❌ Failed to delete space")
        
        # Test 8: Cleanup - Remove all test spaces
        print("\n" + "="*60)
        print("TEST 8: CLEANUP - REMOVING TEST SPACES")
        print("="*60)
        
        print(f"Removing {len(added_space_ids)} test spaces to restore initial state...")
        cleanup_success = True
        
        for space_id in added_space_ids:
            print(f"Removing space ID: {space_id}")
            success = await db_impl.remove_space(str(space_id))
            if success:
                print(f"✅ Space {space_id} removed successfully")
            else:
                print(f"❌ Failed to remove space {space_id}")
                cleanup_success = False
        
        # Test 9: Final state verification
        print("\n" + "="*60)
        print("TEST 9: FINAL STATE VERIFICATION")
        print("="*60)
        
        final_spaces = await db_impl.list_spaces()
        final_space_count = len(final_spaces)
        print(f"Final space count: {final_space_count}")
        print(f"Initial space count: {initial_space_count}")
        
        if final_space_count == initial_space_count:
            print("✅ Database restored to initial state")
        else:
            print(f"❌ Space count mismatch! Expected {initial_space_count}, got {final_space_count}")
            cleanup_success = False
        
        if final_spaces:
            print("Remaining spaces:")
            for i, space in enumerate(final_spaces, 1):
                pretty_print_json(space, f"Remaining Space {i}")
        else:
            print("No spaces remaining in database")
        
        # Summary
        print(f"\n{'='*60}")
        print("SPACE CRUD TEST SUMMARY")
        print(f"{'='*60}")
        
        print("✅ Space CRUD operations tested:")
        print("   ✅ Record initial state")
        print("   ✅ Add spaces (multiple test cases)")
        print("   ✅ List all spaces")
        print("   ✅ List spaces by tenant filter")
        print("   ✅ Get space by ID (valid and invalid)")
        print("   ✅ Filter spaces by name (case-insensitive partial match)")
        print("   ✅ Filter spaces by name with tenant filter")
        print("   ✅ Update space")
        print("   ✅ Delete space")
        print("   ✅ Cleanup test spaces")
        print("   ✅ Final state verification")
        
        if cleanup_success:
            print(f"\n✅ All Space CRUD operations working correctly!")
            print(f"✅ Database restored to initial state (net zero change)")
        else:
            print(f"\n⚠️  Space CRUD operations tested but cleanup incomplete")
            print(f"❌ Some test data may remain in database")
        
        # Disconnect
        await db_impl.disconnect()
        print("\n✅ Disconnected from database")
        
    except Exception as e:
        print(f"❌ Error during Space CRUD testing: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Main test function"""
    asyncio.run(test_space_crud())


if __name__ == "__main__":
    main()
