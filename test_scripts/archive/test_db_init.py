#!/usr/bin/env python3
"""
Test script to check for install table and initialize if missing.
Checks for prefix/install table and triggers init case to create tables if not found.
"""

import sys
import os
import asyncio

# Add the parent directory to Python path to import vitalgraph
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from vitalgraph.config.config_loader import get_config
from vitalgraph.db.postgresql.postgresql_db_impl import PostgreSQLDbImpl


async def test_database_init():
    """Test database initialization functionality"""
    print("=== VITALGRAPH DATABASE INITIALIZATION TEST ===")
    
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
        
        # Check current state
        print("\n" + "="*60)
        print("CHECKING CURRENT STATE")
        print("="*60)
        
        state_info = db_impl.get_current_state()
        print(f"   Connection Status: {state_info['connected']}")
        print(f"   Initialization State: {state_info['state']}")
        print(f"   Table Prefix: {state_info['table_prefix']}")
        
        # Check if initialization is needed
        if state_info['state'] == 'initialized':
            print("\n✅ Database is already initialized!")
            
            # Show current install info
            if state_info['current_install']:
                install = state_info['current_install']
                print(f"   Active Install ID: {install['id']}")
                print(f"   Install Date: {install['install_datetime']}")
                print(f"   Spaces Count: {len(state_info['current_spaces'])}")
                print(f"   Users Count: {len(state_info['current_users'])}")
            
            print("\n⚠️  No initialization needed. Database is ready to use.")
            
        elif state_info['state'] == 'uninitialized':
            print("\n⚠️  Database is connected but not initialized")
            print("   Installing tables and creating initial install record...")
            
            # Initialize tables
            print("\n" + "="*60)
            print("INITIALIZING DATABASE TABLES")
            print("="*60)
            
            init_success = await db_impl.init_tables()
            
            if init_success:
                print("✅ Database initialization successful!")
                
                # Reload state to see what was created
                await db_impl.refresh()
                updated_state = db_impl.get_current_state()
                
                print("\n" + "="*60)
                print("POST-INITIALIZATION STATE")
                print("="*60)
                
                print(f"   New State: {updated_state['state']}")
                
                if updated_state['current_install']:
                    install = updated_state['current_install']
                    print(f"   ✅ Install record created:")
                    print(f"      Install ID: {install['id']}")
                    print(f"      Install Date: {install['install_datetime']}")
                    print(f"      Active: {install['active']}")
                
                # Check table creation
                prefix = tables_config.get('prefix', 'vg_')
                expected_tables = [f"{prefix}install", f"{prefix}space", f"{prefix}user"]
                
                print(f"\n   ✅ Tables created with prefix '{prefix}':")
                for table_name in expected_tables:
                    print(f"      - {table_name}")
                
                print(f"\n   ✅ Empty space table ready for space creation")
                print(f"   ✅ Empty user table ready for user creation")
                
            else:
                print("❌ Database initialization failed!")
                
        else:
            print(f"\n❌ Database is in unexpected state: {state_info['state']}")
            print("   Cannot proceed with initialization")
        
        # Final state check
        print("\n" + "="*60)
        print("FINAL STATE VERIFICATION")
        print("="*60)
        
        final_state = db_impl.get_current_state()
        db_info = await db_impl.get_database_info()
        
        print(f"   Connection Status: {final_state['connected']}")
        print(f"   Initialization State: {final_state['state']}")
        print(f"   Active Install: {'Yes' if final_state['current_install'] else 'No'}")
        print(f"   Spaces Count: {len(final_state['current_spaces'])}")
        print(f"   Users Count: {len(final_state['current_users'])}")
        
        # Summary
        print(f"\n{'='*60}")
        print("INITIALIZATION SUMMARY")
        print(f"{'='*60}")
        
        if final_state['state'] == 'initialized':
            print("✅ Database is properly initialized and ready for use")
            print("✅ Install record is active")
            print("✅ Space and User tables are ready")
            print("\nNext steps:")
            print("   - Use VitalGraph API to create spaces")
            print("   - Use VitalGraph API to create users")
            print("   - Begin storing graph data")
        else:
            print("❌ Database initialization incomplete")
            print("   Please check error messages above")
        
        # Disconnect
        await db_impl.disconnect()
        print("\n✅ Disconnected from database")
        
    except Exception as e:
        print(f"❌ Error during database initialization: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Main test function"""
    asyncio.run(test_database_init())


if __name__ == "__main__":
    main()
