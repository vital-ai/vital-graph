#!/usr/bin/env python3
"""
Test script to check for existing tables and delete them if found.
Checks for prefix tables and performs delete case to remove them completely.
"""

import sys
import os
import asyncio
from sqlalchemy import create_engine, text

# Add the parent directory to Python path to import vitalgraph
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from vitalgraph.config.config_loader import get_config
from vitalgraph.db.postgresql.postgresql_db_impl import PostgreSQLDbImpl


async def test_database_delete():
    """Test database deletion functionality"""
    print("=== VITALGRAPH DATABASE DELETION TEST ===")
    
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
        print(f"   Host: {db_config.get('host', 'unknown')}")
        print(f"   Port: {db_config.get('port', 'unknown')}")
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
        
        # Check current state before deletion
        print("\n" + "="*60)
        print("PRE-DELETION STATE CHECK")
        print("="*60)
        
        state_info = db_impl.get_current_state()
        print(f"   Connection Status: {state_info['connected']}")
        print(f"   Initialization State: {state_info['state']}")
        print(f"   Table Prefix: {state_info['table_prefix']}")
        
        # Check table existence directly
        prefix = tables_config.get('prefix', 'vg_')
        expected_tables = [f"{prefix}install", f"{prefix}space", f"{prefix}user"]
        
        print(f"\n   Checking for tables with prefix '{prefix}':")
        tables_exist = []
        
        with db_impl.engine.connect() as conn:
            for table_name in expected_tables:
                result = conn.execute(text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = :table_name
                    )
                """), {"table_name": table_name})
                
                exists = result.scalar()
                status = "EXISTS" if exists else "MISSING"
                print(f"      {table_name}: {status}")
                
                if exists:
                    tables_exist.append(table_name)
        
        # Show current data before deletion
        if state_info['state'] == 'initialized':
            print(f"\n   Current data before deletion:")
            if state_info['current_install']:
                install = state_info['current_install']
                print(f"      Install ID: {install['id']} (Active: {install['active']})")
            print(f"      Spaces: {len(state_info['current_spaces'])}")
            print(f"      Users: {len(state_info['current_users'])}")
            
            # Show all install records
            all_installs = await db_impl._list_installs()
            if len(all_installs) > 1:
                print(f"      Total install records: {len(all_installs)}")
        
        # Decide on deletion action
        if not tables_exist:
            print(f"\n⚠️  No tables found with prefix '{prefix}'")
            print("   Nothing to delete. Database is already clean.")
            
        else:
            print(f"\n⚠️  Found {len(tables_exist)} tables to delete")
            print("   Proceeding with table deletion...")
            
            # Perform deletion
            print("\n" + "="*60)
            print("DELETING DATABASE TABLES")
            print("="*60)
            
            delete_success = await db_impl.delete_tables()
            
            if delete_success:
                print("✅ Database table deletion successful!")
                
                # Verify deletion
                print("\n" + "="*60)
                print("POST-DELETION VERIFICATION")
                print("="*60)
                
                # Check state after deletion
                post_delete_state = db_impl.get_current_state()
                print(f"   New State: {post_delete_state['state']}")
                print(f"   Current Install: {post_delete_state['current_install']}")
                print(f"   Current Spaces: {len(post_delete_state['current_spaces'])}")
                print(f"   Current Users: {len(post_delete_state['current_users'])}")
                
                # Verify tables are gone
                print(f"\n   Verifying table deletion:")
                with db_impl.engine.connect() as conn:
                    for table_name in expected_tables:
                        result = conn.execute(text("""
                            SELECT EXISTS (
                                SELECT FROM information_schema.tables 
                                WHERE table_schema = 'public' 
                                AND table_name = :table_name
                            )
                        """), {"table_name": table_name})
                        
                        exists = result.scalar()
                        status = "❌ STILL EXISTS" if exists else "✅ DELETED"
                        print(f"      {table_name}: {status}")
                
                # Summary of deletion
                print(f"\n   ✅ All tables with prefix '{prefix}' have been removed")
                print(f"   ✅ Install records deleted")
                print(f"   ✅ Space records deleted")
                print(f"   ✅ User records deleted")
                print(f"   ✅ Database state reset to 'uninitialized'")
                
            else:
                print("❌ Database table deletion failed!")
        
        # Final state check
        print("\n" + "="*60)
        print("FINAL STATE VERIFICATION")
        print("="*60)
        
        final_state = db_impl.get_current_state()
        
        print(f"   Connection Status: {final_state['connected']}")
        print(f"   Initialization State: {final_state['state']}")
        print(f"   Active Install: {'Yes' if final_state['current_install'] else 'No'}")
        print(f"   Spaces Count: {len(final_state['current_spaces'])}")
        print(f"   Users Count: {len(final_state['current_users'])}")
        
        # Summary
        print(f"\n{'='*60}")
        print("DELETION SUMMARY")
        print(f"{'='*60}")
        
        if not tables_exist:
            print("✅ No tables were found to delete")
            print("✅ Database was already clean")
        elif final_state['state'] == 'uninitialized':
            print("✅ Database tables successfully deleted")
            print("✅ Database state reset to uninitialized")
            print("✅ All install, space, and user data removed")
            print("\nNext steps:")
            print("   - Run test_db_init.py to reinitialize if needed")
            print("   - Database is ready for fresh installation")
        else:
            print("❌ Database deletion may be incomplete")
            print("   Please check error messages above")
        
        # Disconnect
        await db_impl.disconnect()
        print("\n✅ Disconnected from database")
        
    except Exception as e:
        print(f"❌ Error during database deletion: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Main test function"""
    asyncio.run(test_database_delete())


if __name__ == "__main__":
    main()
