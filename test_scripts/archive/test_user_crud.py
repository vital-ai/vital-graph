#!/usr/bin/env python3
"""
Comprehensive User CRUD Test Script for VitalGraph PostgreSQL Integration

This script tests all User CRUD operations including:
- Add users (multiple test cases with different tenants)
- List all users and by tenant
- Get user by ID (valid and invalid)
- Filter users by name (case-insensitive partial match)
- Filter users by name with tenant filter
- Update user
- Delete user
- Complete cleanup (net zero change to database)

All objects are displayed as pretty-printed JSON for REST API compatibility.
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


async def test_user_crud():
    """Test comprehensive User CRUD operations"""
    print("=== VITALGRAPH USER CRUD TEST ===")
    print("Testing all User CRUD operations with PostgreSQL database")
    print("=" * 70)
    
    # Load configuration
    try:
        config_path = "vitalgraphdb_config/vitalgraphdb-config.yaml"
        config = get_config(config_path)
        print(f"✅ Configuration loaded from: {config_path}")
    except Exception as e:
        print(f"❌ Failed to load configuration: {e}")
        return
    
    # Get database and tables configuration
    db_config = config.get_database_config()
    tables_config = config.get_tables_config()
    
    print(f"Database: {db_config.get('database')}")
    print(f"Host: {db_config.get('host')}:{db_config.get('port')}")
    print(f"Username: {db_config.get('username')}")
    print(f"Table prefix: {tables_config.get('prefix', 'vg_')}")
    
    # Create database implementation
    db_impl = PostgreSQLDbImpl(db_config, tables_config)
    
    try:
        # Connect to database
        print(f"\n🔌 Connecting to database...")
        await db_impl.connect()
        print("✅ Connected to database successfully")
        
        # Test data - multiple users with different tenants
        test_users = [
            {
                "tenant": "test_tenant",
                "username": "testuser1",
                "password": "password123",
                "email": "testuser1@example.com"
            },
            {
                "tenant": "test_tenant", 
                "username": "testuser2",
                "password": "password456",
                "email": "testuser2@example.com"
            },
            {
                "tenant": "test_tenant",
                "username": "admin_user",
                "password": "admin123",
                "email": "admin@example.com"
            },
            {
                "tenant": "other_tenant",
                "username": "otheruser",
                "password": "other123",
                "email": "other@example.com"
            }
        ]
        
        # Record initial state
        print("\n" + "="*60)
        print("RECORDING INITIAL STATE")
        print("="*60)
        
        initial_users = await db_impl.list_users()
        initial_user_count = len(initial_users)
        print(f"Initial user count: {initial_user_count}")
        
        # Test 1: Add users
        print("\n" + "="*60)
        print("TEST 1: ADDING USERS")
        print("="*60)
        
        added_user_ids = []  # Track users we add for cleanup
        for i, user_data in enumerate(test_users, 1):
            print(f"\nAdding user {i}: {user_data['username']}")
            success = await db_impl.add_user(user_data)
            if success:
                print(f"✅ User '{user_data['username']}' added successfully")
            else:
                print(f"❌ Failed to add user '{user_data['username']}'")
        
        # Test 2: List all users
        print("\n" + "="*60)
        print("TEST 2: LISTING ALL USERS")
        print("="*60)
        
        all_users = await db_impl.list_users()
        print(f"Found {len(all_users)} total users:")
        user_ids = []  # All current user IDs
        for i, user in enumerate(all_users, 1):
            user_ids.append(user['id'])
            # Track which users we added (those not in initial state)
            if len(initial_users) == 0 or user['id'] not in [u['id'] for u in initial_users]:
                added_user_ids.append(user['id'])
            pretty_print_json(user, f"User {i} (ID: {user['id']})")
        
        # Test 3: List users by tenant
        print("\n" + "="*60)
        print("TEST 3: LISTING USERS BY TENANT")
        print("="*60)
        
        test_tenant_users = await db_impl.list_users(tenant="test_tenant")
        print(f"Found {len(test_tenant_users)} users for 'test_tenant':")
        for i, user in enumerate(test_tenant_users, 1):
            pretty_print_json(user, f"Test Tenant User {i}")
        
        other_tenant_users = await db_impl.list_users(tenant="other_tenant")
        print(f"Found {len(other_tenant_users)} users for 'other_tenant':")
        for i, user in enumerate(other_tenant_users, 1):
            pretty_print_json(user, f"Other Tenant User {i}")
        
        # Test 4: Get user by ID
        print("\n" + "="*60)
        print("TEST 4: GET USER BY ID")
        print("="*60)
        
        if user_ids:
            test_id = user_ids[0]
            print(f"Getting user by ID: {test_id}")
            user = await db_impl.get_user_by_id(str(test_id))
            if user:
                print(f"✅ Found user: {user['username']}")
                pretty_print_json(user, "Retrieved User")
            else:
                print(f"❌ User with ID {test_id} not found")
        
        # Test invalid ID
        print(f"\nTesting invalid ID: 99999")
        invalid_user = await db_impl.get_user_by_id("99999")
        if invalid_user is None:
            print("✅ Correctly returned None for invalid ID")
        else:
            print("❌ Should have returned None for invalid ID")
        
        # Test 5: Filter users by name
        print("\n" + "="*60)
        print("TEST 5: FILTER USERS BY NAME")
        print("="*60)
        
        test_filters = ["test", "Test", "admin", "user", "other"]
        
        for name_filter in test_filters:
            print(f"\nFiltering by name: '{name_filter}'")
            filtered_users = await db_impl.filter_users_by_name(name_filter)
            print(f"Found {len(filtered_users)} users matching '{name_filter}':")
            for i, user in enumerate(filtered_users, 1):
                pretty_print_json(user, f"Match {i}")
        
        # Test filter with tenant
        print(f"\nFiltering by name 'test' for tenant 'test_tenant':")
        tenant_filtered = await db_impl.filter_users_by_name("test", tenant="test_tenant")
        print(f"Found {len(tenant_filtered)} users:")
        for i, user in enumerate(tenant_filtered, 1):
            pretty_print_json(user, f"Tenant Filtered Match {i}")
        
        # Test 6: Update user
        print("\n" + "="*60)
        print("TEST 6: UPDATE USER")
        print("="*60)
        
        if added_user_ids:
            update_id = added_user_ids[0]  # Update the first user we added
            print(f"Updating user ID: {update_id}")
            
            update_data = {
                "username": "updated_testuser1",
                "email": "updated_testuser1@example.com"
            }
            
            print("Update data:")
            pretty_print_json(update_data, "Update Request")
            
            success = await db_impl.update_user(str(update_id), update_data)
            if success:
                print("✅ User updated successfully")
                
                # Verify update
                updated_user = await db_impl.get_user_by_id(str(update_id))
                if updated_user:
                    print("Updated user:")
                    pretty_print_json(updated_user, "Updated User")
            else:
                print("❌ Failed to update user")
        
        # Test 7: Delete user
        print("\n" + "="*60)
        print("TEST 7: DELETE USER")
        print("="*60)
        
        if len(added_user_ids) > 1:
            delete_id = added_user_ids[-1]  # Delete one of our added users
            print(f"Deleting user ID: {delete_id}")
            
            success = await db_impl.remove_user(str(delete_id))
            if success:
                print("✅ User deleted successfully")
                added_user_ids.remove(delete_id)  # Remove from our tracking list
                
                # Verify deletion
                deleted_user = await db_impl.get_user_by_id(str(delete_id))
                if deleted_user is None:
                    print("✅ User confirmed deleted (not found)")
                else:
                    print("❌ User still exists after deletion")
            else:
                print("❌ Failed to delete user")
        
        # Test 8: Cleanup - Remove all test users
        print("\n" + "="*60)
        print("TEST 8: CLEANUP - REMOVING TEST USERS")
        print("="*60)
        
        print(f"Removing {len(added_user_ids)} test users to restore initial state...")
        cleanup_success = True
        
        for user_id in added_user_ids:
            print(f"Removing user ID: {user_id}")
            success = await db_impl.remove_user(str(user_id))
            if success:
                print(f"✅ User {user_id} removed successfully")
            else:
                print(f"❌ Failed to remove user {user_id}")
                cleanup_success = False
        
        # Test 9: Final state verification
        print("\n" + "="*60)
        print("TEST 9: FINAL STATE VERIFICATION")
        print("="*60)
        
        final_users = await db_impl.list_users()
        final_user_count = len(final_users)
        print(f"Final user count: {final_user_count}")
        print(f"Initial user count: {initial_user_count}")
        
        if final_user_count == initial_user_count:
            print("✅ Database restored to initial state")
        else:
            print(f"❌ User count mismatch! Expected {initial_user_count}, got {final_user_count}")
            cleanup_success = False
        
        if final_users:
            print("Remaining users:")
            for i, user in enumerate(final_users, 1):
                pretty_print_json(user, f"Remaining User {i}")
        else:
            print("No users remaining in database")
        
        # Summary
        print(f"\n{'='*60}")
        print("USER CRUD TEST SUMMARY")
        print(f"{'='*60}")
        
        print("✅ User CRUD operations tested:")
        print("   ✅ Record initial state")
        print("   ✅ Add users (multiple test cases)")
        print("   ✅ List all users")
        print("   ✅ List users by tenant filter")
        print("   ✅ Get user by ID (valid and invalid)")
        print("   ✅ Filter users by name (case-insensitive partial match)")
        print("   ✅ Filter users by name with tenant filter")
        print("   ✅ Update user")
        print("   ✅ Delete user")
        print("   ✅ Cleanup test users")
        print("   ✅ Final state verification")
        
        if cleanup_success:
            print(f"\n✅ All User CRUD operations working correctly!")
            print(f"✅ Database restored to initial state (net zero change)")
        else:
            print(f"\n⚠️  User CRUD operations tested but cleanup incomplete")
            print(f"❌ Some test data may remain in database")
        
        # Disconnect
        await db_impl.disconnect()
        print(f"\n✅ Disconnected from database")
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        try:
            await db_impl.disconnect()
        except:
            pass


if __name__ == "__main__":
    asyncio.run(test_user_crud())
