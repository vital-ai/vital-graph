#!/usr/bin/env python3
"""
Test script to report on database info and table existence.
Loads config, connects to database, and reports on install, space, and user tables.
"""

import sys
import os
import asyncio
from sqlalchemy import create_engine, text

# Add the parent directory to Python path to import vitalgraph
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from vitalgraph.config.config_loader import get_config
from vitalgraph.db.postgresql.postgresql_db_impl import PostgreSQLDbImpl


async def test_database_report():
    """Test database reporting functionality"""
    print("=== VITALGRAPH DATABASE REPORT TEST ===")
    
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
        print(f"   Username: {db_config.get('username', 'unknown')}")
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
        
        # Get database info
        print("\n" + "="*60)
        print("DATABASE INFORMATION")
        print("="*60)
        
        db_info = await db_impl.get_database_info()
        for key, value in db_info.items():
            print(f"   {key}: {value}")
        
        # Get current state
        print("\n" + "="*60)
        print("CURRENT STATE")
        print("="*60)
        
        state_info = db_impl.get_current_state()
        print(f"   Connection Status: {state_info['connected']}")
        print(f"   Initialization State: {state_info['state']}")
        print(f"   Table Prefix: {state_info['table_prefix']}")
        
        # Report on install table
        print("\n" + "="*60)
        print("INSTALL TABLE STATUS")
        print("="*60)
        
        if state_info['current_install']:
            install = state_info['current_install']
            print("✅ Install table exists and has active record:")
            print(f"   Install ID: {install['id']}")
            print(f"   Install Date: {install['install_datetime']}")
            print(f"   Update Date: {install['update_datetime']}")
            print(f"   Active: {install['active']}")
            
            # List all installs
            all_installs = await db_impl._list_installs()
            if len(all_installs) > 1:
                print(f"\n   Total install records: {len(all_installs)}")
                print("   All install records:")
                for i, inst in enumerate(all_installs, 1):
                    status = "ACTIVE" if inst['active'] else "INACTIVE"
                    print(f"     {i}. ID {inst['id']} - {inst['install_datetime']} ({status})")
        else:
            print("❌ No install table or no active install record found")
        
        # Report on space table
        print("\n" + "="*60)
        print("SPACE TABLE STATUS")
        print("="*60)
        
        spaces = state_info['current_spaces']
        if spaces:
            print(f"✅ Space table exists with {len(spaces)} records:")
            for i, space in enumerate(spaces, 1):
                print(f"   {i}. ID {space['id']} - Tenant: {space['tenant']}, Space: {space['space']}")
                print(f"      Name: {space.get('space_name', 'N/A')}")
                print(f"      Description: {space.get('space_description', 'N/A')}")
                print(f"      Updated: {space.get('update_time', 'N/A')}")
        else:
            if state_info['state'] == 'initialized':
                print("✅ Space table exists but is empty")
            else:
                print("❌ Space table does not exist")
        
        # Report on user table
        print("\n" + "="*60)
        print("USER TABLE STATUS")
        print("="*60)
        
        users = state_info['current_users']
        if users:
            print(f"✅ User table exists with {len(users)} records:")
            for i, user in enumerate(users, 1):
                print(f"   {i}. ID {user['id']} - Tenant: {user['tenant']}, Username: {user['username']}")
                print(f"      Email: {user.get('email', 'N/A')}")
                print(f"      Updated: {user.get('update_time', 'N/A')}")
        else:
            if state_info['state'] == 'initialized':
                print("✅ User table exists but is empty")
            else:
                print("❌ User table does not exist")
        
        # Check table existence directly in database
        print("\n" + "="*60)
        print("DIRECT TABLE EXISTENCE CHECK")
        print("="*60)
        
        prefix = tables_config.get('prefix', 'vg_')
        expected_tables = [f"{prefix}install", f"{prefix}space", f"{prefix}user"]
        
        # Query information_schema to check table existence
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
                status = "✅ EXISTS" if exists else "❌ MISSING"
                print(f"   {table_name}: {status}")
        
        # Summary
        print(f"\n{'='*60}")
        print("SUMMARY")
        print(f"{'='*60}")
        
        if state_info['state'] == 'initialized':
            print("✅ Database is properly initialized")
            print(f"✅ Active install record found")
            print(f"✅ {len(spaces)} spaces configured")
            print(f"✅ {len(users)} users configured")
        elif state_info['state'] == 'uninitialized':
            print("⚠️  Database is connected but not initialized")
            print("   Run the init test script to initialize tables")
        else:
            print("❌ Database is not connected")
        
        # Disconnect
        await db_impl.disconnect()
        print("\n✅ Disconnected from database")
        
    except Exception as e:
        print(f"❌ Error during database report: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Main test function"""
    asyncio.run(test_database_report())


if __name__ == "__main__":
    main()
