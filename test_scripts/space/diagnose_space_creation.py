#!/usr/bin/env python3
"""
Diagnostic script to investigate space table creation issues.
"""

import asyncio
import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl

TEST_SPACE_ID = "test_space_manager_001"

async def diagnose_space_creation():
    """Diagnose space table creation issues."""
    print(f"🔍 Diagnosing space creation for: {TEST_SPACE_ID}")
    
    impl = None
    try:
        # Initialize VitalGraph with explicit config path
        from vitalgraph.config.config_loader import get_config
        config_path = project_root / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
        
        # Set the config path in environment if needed
        import os
        os.environ['VITALGRAPH_CONFIG_PATH'] = str(config_path)
        
        impl = VitalGraphImpl()
        await impl.connect()
        
        global_prefix = impl.db_impl.global_prefix
        table_prefix = f"{global_prefix}__{TEST_SPACE_ID}__"
        
        print(f"📋 Global prefix: {global_prefix}")
        print(f"📋 Expected table prefix: {table_prefix}")
        
        # Check what's actually in the database
        with impl.db_impl.shared_pool.connection() as conn:
            cursor = conn.cursor()
            
            print(f"\n🔍 Checking for existing tables...")
            cursor.execute("""
                SELECT schemaname, tablename 
                FROM pg_tables 
                WHERE tablename LIKE %s
                ORDER BY tablename
            """, (f"%{TEST_SPACE_ID}%",))
            
            tables = cursor.fetchall()
            if tables:
                print(f"📋 Found {len(tables)} tables:")
                for schema, table in tables:
                    print(f"  - {schema}.{table}")
            else:
                print("📋 No tables found matching the pattern")
            
            print(f"\n🔍 Checking for existing indexes...")
            cursor.execute("""
                SELECT schemaname, indexname, tablename
                FROM pg_indexes 
                WHERE indexname LIKE %s
                ORDER BY indexname
            """, (f"%{TEST_SPACE_ID}%",))
            
            indexes = cursor.fetchall()
            if indexes:
                print(f"📋 Found {len(indexes)} indexes:")
                for schema, index, table in indexes:
                    print(f"  - {schema}.{index} (on {table})")
            else:
                print("📋 No indexes found matching the pattern")
            
            print(f"\n🔍 Checking for any objects with the space ID...")
            cursor.execute("""
                SELECT 'table' as type, schemaname, tablename as name, '' as extra
                FROM pg_tables 
                WHERE tablename LIKE %s
                UNION ALL
                SELECT 'index' as type, schemaname, indexname as name, tablename as extra
                FROM pg_indexes 
                WHERE indexname LIKE %s
                UNION ALL
                SELECT 'sequence' as type, schemaname, sequencename as name, '' as extra
                FROM pg_sequences 
                WHERE sequencename LIKE %s
                ORDER BY type, name
            """, (f"%{TEST_SPACE_ID}%", f"%{TEST_SPACE_ID}%", f"%{TEST_SPACE_ID}%"))
            
            objects = cursor.fetchall()
            if objects:
                print(f"📋 Found {len(objects)} database objects:")
                for obj_type, schema, name, extra in objects:
                    extra_info = f" (on {extra})" if extra else ""
                    print(f"  - {obj_type}: {schema}.{name}{extra_info}")
            else:
                print("📋 No database objects found matching the pattern")
        
        # Try to create the space and see what happens
        print(f"\n🧪 Attempting to create space tables...")
        space_impl_pg = impl.db_impl.space_impl
        
        try:
            # Check if space exists first
            exists = space_impl_pg.space_exists(TEST_SPACE_ID)
            print(f"📋 Space exists check: {exists}")
            
            if not exists:
                print(f"🔨 Creating space tables...")
                success = space_impl_pg.create_space_tables(TEST_SPACE_ID)
                print(f"📋 Creation result: {success}")
            else:
                print(f"⚠️ Space already exists, skipping creation")
                
        except Exception as e:
            print(f"❌ Space creation failed: {e}")
            print(f"📋 Error type: {type(e).__name__}")
            
            # Try to get more details about the error
            if "already exists" in str(e):
                print(f"🔍 'Already exists' error detected")
                # Extract the object name from the error
                import re
                match = re.search(r'"([^"]+)" already exists', str(e))
                if match:
                    object_name = match.group(1)
                    print(f"📋 Problematic object: {object_name}")
                    
                    # Check if this object actually exists
                    with impl.db_impl.shared_pool.connection() as conn:
                        cursor = conn.cursor()
                        
                        # Check tables
                        cursor.execute("""
                            SELECT 1 FROM pg_tables 
                            WHERE tablename = %s
                        """, (object_name,))
                        table_exists = cursor.fetchone() is not None
                        
                        # Check indexes
                        cursor.execute("""
                            SELECT 1 FROM pg_indexes 
                            WHERE indexname = %s
                        """, (object_name,))
                        index_exists = cursor.fetchone() is not None
                        
                        print(f"📋 Object '{object_name}' exists as table: {table_exists}")
                        print(f"📋 Object '{object_name}' exists as index: {index_exists}")
        
        print(f"\n🎯 Diagnosis complete")
        
    except Exception as e:
        print(f"❌ Diagnosis failed: {e}")
        return False
        
    finally:
        if impl:
            await impl.disconnect()
            
    return True

if __name__ == "__main__":
    success = asyncio.run(diagnose_space_creation())
    sys.exit(0 if success else 1)
