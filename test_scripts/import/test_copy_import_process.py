#!/usr/bin/env python3
"""
Copy Import Process Test Script
===============================

Test script for processing CSV import data into VitalGraph spaces.
This script handles:
- Space listing and management
- Space deletion and creation
- CSV data import from temporary tables to production spaces

Based on patterns from test_partition_import.py but focused on CSV import processing.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.config.config_loader import get_config
from vitalgraph.db.postgresql.space.postgresql_space_db_import import PostgreSQLSpaceDBImport
import psycopg
from psycopg.rows import dict_row

# Configure logging to see detailed operations
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(name)s - %(message)s')

# Suppress verbose logging from other modules
logging.getLogger('vitalgraph.db.postgresql.postgresql_cache_term').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.db.postgresql.space.postgresql_space_core').setLevel(logging.WARNING)

# Configuration
TARGET_SPACE_ID = "import_001"
TARGET_SPACE_NAME = "CSV Import Test Space"
TARGET_SPACE_DESCRIPTION = "Space created for CSV import processing"
TARGET_PARTITION_DATASET = "csv_import_001"

async def initialize_vitalgraph():
    """Initialize VitalGraphImpl and return configured instance."""
    print("🚀 CSV Import Process Test")
    print("=" * 50)
    
    # Initialize VitalGraph with configuration
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    config = get_config(str(config_path))
    
    print(f"📋 Loading configuration from: {config_path}")
    print(f"📊 Configuration loaded successfully")
    
    # Create VitalGraphImpl instance
    impl = VitalGraphImpl(config=config)
    
    # Force disconnect first to clear any cached settings
    try:
        await impl.db_impl.disconnect()
    except:
        pass
    
    await impl.db_impl.connect()
    
    print(f"✅ Connected to database successfully")
    print(f"📋 VitalGraph Implementation: {type(impl).__name__}")
    print(f"📋 Database Implementation: {type(impl.db_impl).__name__}")
    
    return impl

async def list_spaces(space_manager):
    """List all available spaces."""
    print(f"\n📋 LISTING AVAILABLE SPACES")
    print(f"------------------------------")
    
    # Initialize space manager from database
    await space_manager.initialize_from_database()
    spaces_count = len(space_manager)
    
    print(f"✅ Found {spaces_count} spaces in database:")
    
    if spaces_count > 0:
        for space_id in space_manager.list_spaces():
            space_info = space_manager.get_space_info(space_id)
            print(f"  - {space_id}: {space_info.get('name', 'No name')}")
    else:
        print("  (No spaces found)")
    
    return spaces_count

async def delete_space_if_exists(space_manager, space_id: str):
    """Delete space if it exists."""
    print(f"\n🗑️ CHECKING FOR EXISTING SPACE: {space_id}")
    print(f"------------------------------")
    
    try:
        # Check if space exists
        if space_id in space_manager.list_spaces():
            print(f"🗑️  Found existing space '{space_id}' - deleting...")
            await space_manager.delete_space_with_tables(space_id)
            print(f"✅ Deleted existing space: {space_id}")
            return True
        else:
            print(f"ℹ️  Space '{space_id}' does not exist - no deletion needed")
            return False
    except Exception as e:
        print(f"❌ Error checking/deleting space '{space_id}': {e}")
        return False

async def create_space(space_manager, space_id: str, space_name: str):
    """Create new space."""
    print(f"\n🏗️ CREATING NEW SPACE: {space_id}")
    print(f"------------------------------")
    
    try:
        await space_manager.create_space_with_tables(space_id, space_name)
        print(f"✅ Created space successfully: {space_id}")
        print(f"   Name: {space_name}")
        return True
    except Exception as e:
        print(f"❌ Failed to create space '{space_id}': {e}")
        return False

async def get_db_connection(config):
    """Get direct database connection for partition management."""
    db_config = config.get_database_config()
    conn = await psycopg.AsyncConnection.connect(
        host=db_config.get('host', 'localhost'),
        port=db_config.get('port', 5432),
        dbname=db_config.get('database', 'vitalgraphdb'),
        user=db_config.get('username', 'vitalgraph_user'),
        password=db_config.get('password', 'vitalgraph_password')
    )
    conn.row_factory = psycopg.rows.dict_row
    return conn

async def check_partition_exists(conn, table_name: str, partition_dataset: str) -> bool:
    """Check if a partition exists for the given dataset."""
    partition_name = f"{table_name}_{partition_dataset}"
    query = """
    SELECT EXISTS (
        SELECT 1 FROM pg_class c
        WHERE c.relname = %s 
        AND c.relkind = 'r'
        AND c.relispartition = true
    ) as exists;
    """
    
    async with conn.cursor() as cursor:
        await cursor.execute(query, (partition_name,))
        result = await cursor.fetchone()
        return result['exists']

async def drop_partition_if_exists(conn, table_name: str, partition_dataset: str) -> bool:
    """Drop partition if it exists."""
    partition_name = f"{table_name}_{partition_dataset}"
    
    if await check_partition_exists(conn, table_name, partition_dataset):
        print(f"  🗑️  Dropping existing partition: {partition_name}")
        drop_sql = f"DROP TABLE IF EXISTS {partition_name} CASCADE;"
        
        async with conn.cursor() as cursor:
            await cursor.execute(drop_sql)
        
        print(f"  ✅ Dropped partition: {partition_name}")
        return True
    else:
        print(f"  ℹ️  Partition {partition_name} does not exist")
        return False

async def create_minimal_term_partition(config, table_name: str, partition_dataset: str) -> bool:
    """Create minimal term partition with only essential indexes."""
    partition_name = f"{table_name}_{partition_dataset}"
    
    print(f"  🏗️  Creating minimal term partition: {partition_name}")
    print(f"      Parent table: {table_name}")
    print(f"      Dataset value: {partition_dataset}")
    
    # Get a fresh connection for partition creation
    conn = await get_db_connection(config)
    
    try:
        # First verify the parent table exists and is partitioned
        check_parent_sql = """
        SELECT 
            c.relname,
            c.relkind,
            c.relpartbound IS NOT NULL as has_partition_bound,
            pg_get_partkeydef(c.oid) as partition_key
        FROM pg_class c
        WHERE c.relname = %s;
        """
        
        async with conn.cursor() as cursor:
            await cursor.execute(check_parent_sql, (table_name.split('.')[-1],))
            parent_info = await cursor.fetchone()
            
            if not parent_info:
                print(f"  ❌ Parent table {table_name} not found!")
                return False
            
            print(f"  📋 Parent table info:")
            print(f"      Name: {parent_info['relname']}")
            print(f"      Kind: {parent_info['relkind']}")
            print(f"      Partition key: {parent_info['partition_key']}")
        
        # Create partition
        create_sql = f"""
        CREATE TABLE {partition_name} PARTITION OF {table_name}
        FOR VALUES IN ('{partition_dataset}');
        """
        
        print(f"  🔧 Executing SQL: {create_sql.strip()}")
        
        async with conn.cursor() as cursor:
            try:
                await cursor.execute(create_sql)
                await conn.commit()  # Explicitly commit the transaction
                print(f"  ✅ Created partition: {partition_name}")
            except Exception as e:
                print(f"  ❌ Failed to create partition: {e}")
                await conn.rollback()
                return False
        
        # Verify the partition was created
        verify_sql = """
        SELECT 
            c.relname,
            pg_get_expr(c.relpartbound, c.oid) as partition_bound,
            pg_size_pretty(pg_total_relation_size(c.oid)) as size
        FROM pg_class c
        WHERE c.relname = %s;
        """
        
        async with conn.cursor() as cursor:
            await cursor.execute(verify_sql, (partition_name.split('.')[-1],))
            partition_info = await cursor.fetchone()
            
            if partition_info:
                print(f"  ✅ Verified partition creation:")
                print(f"      Name: {partition_info['relname']}")
                print(f"      Bound: {partition_info['partition_bound']}")
                print(f"      Size: {partition_info['size']}")
            else:
                print(f"  ❌ Partition verification failed - table not found")
                return False
        
    finally:
        await conn.close()
    
    print(f"  📋 Partition {partition_name} created with inherited indexes from parent table")
    
    return True

async def create_minimal_quad_partition(config, table_name: str, partition_dataset: str) -> bool:
    """Create minimal quad partition with only essential indexes."""
    partition_name = f"{table_name}_{partition_dataset}"
    
    print(f"  🏗️  Creating minimal quad partition: {partition_name}")
    print(f"      Parent table: {table_name}")
    print(f"      Dataset value: {partition_dataset}")
    
    # Get a fresh connection for partition creation
    conn = await get_db_connection(config)
    
    try:
        # First verify the parent table exists and is partitioned
        check_parent_sql = """
        SELECT 
            c.relname,
            c.relkind,
            c.relpartbound IS NOT NULL as has_partition_bound,
            pg_get_partkeydef(c.oid) as partition_key
        FROM pg_class c
        WHERE c.relname = %s;
        """
        
        async with conn.cursor() as cursor:
            await cursor.execute(check_parent_sql, (table_name.split('.')[-1],))
            parent_info = await cursor.fetchone()
            
            if not parent_info:
                print(f"  ❌ Parent table {table_name} not found!")
                return False
            
            print(f"  📋 Parent table info:")
            print(f"      Name: {parent_info['relname']}")
            print(f"      Kind: {parent_info['relkind']}")
            print(f"      Partition key: {parent_info['partition_key']}")
        
        # Create partition
        create_sql = f"""
        CREATE TABLE {partition_name} PARTITION OF {table_name}
        FOR VALUES IN ('{partition_dataset}');
        """
        
        print(f"  🔧 Executing SQL: {create_sql.strip()}")
        
        async with conn.cursor() as cursor:
            try:
                await cursor.execute(create_sql)
                await conn.commit()  # Explicitly commit the transaction
                print(f"  ✅ Created partition: {partition_name}")
            except Exception as e:
                print(f"  ❌ Failed to create partition: {e}")
                await conn.rollback()
                return False
        
        # Verify the partition was created
        verify_sql = """
        SELECT 
            c.relname,
            pg_get_expr(c.relpartbound, c.oid) as partition_bound,
            pg_size_pretty(pg_total_relation_size(c.oid)) as size
        FROM pg_class c
        WHERE c.relname = %s;
        """
        
        async with conn.cursor() as cursor:
            await cursor.execute(verify_sql, (partition_name.split('.')[-1],))
            partition_info = await cursor.fetchone()
            
            if partition_info:
                print(f"  ✅ Verified partition creation:")
                print(f"      Name: {partition_info['relname']}")
                print(f"      Bound: {partition_info['partition_bound']}")
                print(f"      Size: {partition_info['size']}")
            else:
                print(f"  ❌ Partition verification failed - table not found")
                return False
        
    finally:
        await conn.close()
    
    print(f"  📋 Partition {partition_name} created with inherited indexes from parent table")
    
    return True

async def manage_partitions(config, space_id: str, partition_dataset: str):
    """Manage partitions for term and quad tables."""
    start_time = time.time()
    print(f"\n📂 MANAGING PARTITIONS FOR SPACE: {space_id}")
    print(f"=" * 60)
    
    # Get table prefix from config
    tables_config = config.get_table_config()
    global_prefix = tables_config.get('prefix', 'vitalgraph1_').rstrip('_')
    
    # Define table names
    term_table = f"{global_prefix}__{space_id}__term"
    quad_table = f"{global_prefix}__{space_id}__rdf_quad"
    
    print(f"Target partition dataset: {partition_dataset}")
    print(f"Term table: {term_table}")
    print(f"Quad table: {quad_table}")
    
    # Get database connection
    conn = await get_db_connection(config)
    
    try:
        # Process term table
        print(f"\n🔍 Processing term table: {term_table}")
        print(f"-" * 40)
        
        # Drop existing partition if present
        await drop_partition_if_exists(conn, term_table, partition_dataset)
        
        # Create minimal partition
        await create_minimal_term_partition(config, term_table, partition_dataset)
        
        # Process quad table
        print(f"\n🔍 Processing quad table: {quad_table}")
        print(f"-" * 40)
        
        # Drop existing partition if present
        await drop_partition_if_exists(conn, quad_table, partition_dataset)
        
        # Create minimal partition
        await create_minimal_quad_partition(config, quad_table, partition_dataset)
        
        elapsed_time = time.time() - start_time
        print(f"\n✅ Partition management completed successfully! ({elapsed_time:.2f}s)")
        
    finally:
        await conn.close()

async def copy_data_to_partitions(config: dict, space_id: str, partition_dataset: str):
    """
    Copy data from temp staging tables to the partitioned tables.
    
    Args:
        config: Database configuration
        space_id: Target space ID
        partition_dataset: Dataset name for partition (e.g., 'csv_import_001')
    """
    start_time = time.time()
    print(f"\n🔄 Copying data from staging tables to partitions...")
    
    # Get database connection
    conn = await get_db_connection(config)
    
    try:
        # Get table names
        global_prefix = config.get_tables_config().get('prefix', 'vg').rstrip('_')
        term_table = f"{global_prefix}__{space_id}__term"
        quad_table = f"{global_prefix}__{space_id}__rdf_quad"
        
        # Source temp table names
        temp_term_table = f"temp_term_{partition_dataset}"
        temp_quad_table = f"temp_quad_{partition_dataset}"
        
        print(f"   Source tables: {temp_term_table}, {temp_quad_table}")
        print(f"   Target tables: {term_table}, {quad_table}")
        
        # Check if temp tables exist
        temp_term_exists = await check_table_exists(conn, temp_term_table)
        temp_quad_exists = await check_table_exists(conn, temp_quad_table)
        
        cursor = conn.cursor()
        
        # Copy term data
        if not temp_term_exists:
            print(f"   ⚠️  Temp table {temp_term_table} does not exist - skipping term data copy")
        else:
            print(f"   📋 Copying data from {temp_term_table} to {term_table} partition...")
            copy_start = time.time()
            
            await cursor.execute(f"""
                INSERT INTO {term_table} (term_uuid, term_text, term_type, lang, datatype_id, created_time, dataset)
                SELECT term_uuid, term_text, term_type, lang, datatype_id, created_time, %s
                FROM {temp_term_table};
            """, (partition_dataset,))
            
            term_rows = cursor.rowcount
            copy_elapsed = time.time() - copy_start
            print(f"   ✅ Copied {term_rows} rows to term partition ({copy_elapsed:.2f}s)")
        
        # Copy quad data if temp table exists
        if temp_quad_exists:
            print(f"   📋 Copying data from {temp_quad_table} to {quad_table} partition...")
            quad_copy_start = time.time()
            
            await cursor.execute(f"""
                INSERT INTO {quad_table} (subject_uuid, predicate_uuid, object_uuid, context_uuid, created_time, dataset)
                SELECT subject_uuid, predicate_uuid, object_uuid, context_uuid, created_time, %s
                FROM {temp_quad_table};
            """, (partition_dataset,))
            
            quad_rows = cursor.rowcount
            quad_copy_elapsed = time.time() - quad_copy_start
            print(f"   ✅ Copied {quad_rows} rows to quad partition ({quad_copy_elapsed:.2f}s)")
        else:
            print(f"   ⚠️  Temp quad table {temp_quad_table} not found - skipping quad data copy")
        
        # Commit the transaction
        await conn.commit()
        
        elapsed_time = time.time() - start_time
        print(f"\n✅ Data copy completed successfully! ({elapsed_time:.2f}s)")
        
    except Exception as e:
        print(f"\n❌ Error copying data to partitions: {e}")
        await conn.rollback()
        raise
    finally:
        await conn.close()

async def check_table_exists(conn, table_name: str) -> bool:
    """Check if a table exists in the database."""
    cursor = conn.cursor()
    await cursor.execute("""
        SELECT COUNT(*) as count
        FROM information_schema.tables 
        WHERE table_name = %s;
    """, (table_name,))
    
    result = await cursor.fetchone()
    return result['count'] > 0 if result else False

async def verify_partition_data(config: dict, space_id: str, partition_dataset: str):
    """
    Verify that data was correctly inserted into the partitions.
    
    Args:
        config: Database configuration
        space_id: Target space ID
        partition_dataset: Dataset name for partition (e.g., 'csv_import_001')
    """
    start_time = time.time()
    print(f"\n🔍 Verifying data in partitions...")
    
    # Get database connection
    conn = await get_db_connection(config)
    
    try:
        # Get table names
        global_prefix = config.get_tables_config().get('prefix', 'vg').rstrip('_')
        term_table = f"{global_prefix}__{space_id}__term"
        quad_table = f"{global_prefix}__{space_id}__rdf_quad"
        
        # Check term partition data
        cursor = conn.cursor()
        await cursor.execute(f"""
            SELECT COUNT(*) as count
            FROM {term_table} 
            WHERE dataset = %s;
        """, (partition_dataset,))
        
        term_result = await cursor.fetchone()
        term_count = term_result['count'] if term_result else 0
        
        # Check quad partition data
        await cursor.execute(f"""
            SELECT COUNT(*) as count
            FROM {quad_table} 
            WHERE dataset = %s;
        """, (partition_dataset,))
        
        quad_result = await cursor.fetchone()
        quad_count = quad_result['count'] if quad_result else 0
        
        print(f"   📊 Term partition ({partition_dataset}): {term_count} rows")
        print(f"   📊 Quad partition ({partition_dataset}): {quad_count} rows")
        
        elapsed_time = time.time() - start_time
        if term_count > 0 or quad_count > 0:
            print(f"\n✅ Data verification successful - partitions contain data! ({elapsed_time:.2f}s)")
        else:
            print(f"\n⚠️  No data found in partitions - may need to load staging tables first ({elapsed_time:.2f}s)")
        
    except Exception as e:
        print(f"\n❌ Error verifying partition data: {e}")
        raise
    finally:
        await conn.close()

async def main():
    """Main function."""
    overall_start = time.time()
    try:
        # Step 1: Initialize VitalGraph
        step_start = time.time()
        impl = await initialize_vitalgraph()
        step_elapsed = time.time() - step_start
        print(f"   ⏱️  VitalGraph initialization: {step_elapsed:.2f}s")
        
        # Step 2: Get space manager
        step_start = time.time()
        space_manager = impl.get_space_manager()
        print(f"\n🔄 Initializing SpaceManager from database...")
        step_elapsed = time.time() - step_start
        print(f"   ⏱️  SpaceManager initialization: {step_elapsed:.2f}s")
        
        # Step 3: List available spaces
        step_start = time.time()
        await list_spaces(space_manager)
        step_elapsed = time.time() - step_start
        print(f"   ⏱️  Space listing: {step_elapsed:.2f}s")
        
        # Step 4: Delete space if it exists
        step_start = time.time()
        deleted = await delete_space_if_exists(space_manager, TARGET_SPACE_ID)
        step_elapsed = time.time() - step_start
        print(f"   ⏱️  Space deletion: {step_elapsed:.2f}s")
        
        # Step 5: Create new space
        step_start = time.time()
        created = await create_space(space_manager, TARGET_SPACE_ID, TARGET_SPACE_NAME)
        step_elapsed = time.time() - step_start
        print(f"   ⏱️  Space creation: {step_elapsed:.2f}s")
        
        if created:
            print(f"\n🎉 Space management completed successfully!")
            print(f"   Target space '{TARGET_SPACE_ID}' is ready for CSV import processing")
        else:
            print(f"\n❌ Space management failed!")
            return False
        
        # Step 6: Manage partitions for CSV import
        config = get_config(str(Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"))
        await manage_partitions(config, TARGET_SPACE_ID, TARGET_PARTITION_DATASET)
        
        # Step 7: Copy data from staging tables to partitions
        await copy_data_to_partitions(config, TARGET_SPACE_ID, TARGET_PARTITION_DATASET)
        
        # Step 8: Verify data was correctly inserted into partitions
        await verify_partition_data(config, TARGET_SPACE_ID, TARGET_PARTITION_DATASET)
        
        # Cleanup
        step_start = time.time()
        await impl.db_impl.disconnect()
        step_elapsed = time.time() - step_start
        print(f"\n✅ Disconnected from database ({step_elapsed:.2f}s)")
        
        # Overall timing summary
        overall_elapsed = time.time() - overall_start
        print(f"\n🎯 **TOTAL EXECUTION TIME: {overall_elapsed:.2f}s**")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error in main process: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    if success:
        print(f"\n✅ SUCCESS: CSV import process setup completed!")
        sys.exit(0)
    else:
        print(f"\n❌ FAILED: CSV import process setup failed!")
        sys.exit(1)