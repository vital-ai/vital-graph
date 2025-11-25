#!/usr/bin/env python3

import asyncio
import psycopg
from psycopg.rows import dict_row
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph.config.config_loader import get_config

async def direct_partition_test():
    """Direct SQL test to see what's happening with partition creation."""
    
    print("🔍 Direct partition creation test...")
    
    # Load config with explicit path
    config_path = "/Users/hadfield/Local/vital-git/vital-graph/vitalgraphdb_config/vitalgraphdb-config.yaml"
    from vitalgraph.config.config_loader import VitalGraphConfig
    config = VitalGraphConfig(config_path)
    db_config = config.get_database_config()
    table_config = config.get_table_config()
    global_prefix = table_config.get('table_prefix', 'vitalgraph2')
    
    space_id = "import_001"
    partition_dataset = "csv_import_001"
    
    term_table = f"{global_prefix}__{space_id}__term"
    term_partition = f"{term_table}_{partition_dataset}"
    
    # Connect to database
    conn = await psycopg.AsyncConnection.connect(
        host=db_config['host'],
        port=db_config['port'],
        dbname=db_config['database'],
        user=db_config['username'],
        password=db_config['password'],
        row_factory=dict_row
    )
    
    try:
        print(f"\n1. Checking if term table exists and is partitioned:")
        async with conn.cursor() as cursor:
            check_sql = """
            SELECT 
                c.relname,
                c.relkind,
                pg_get_partkeydef(c.oid) as partition_key,
                c.relispartition
            FROM pg_class c
            WHERE c.relname = %s;
            """
            await cursor.execute(check_sql, (term_table,))
            result = await cursor.fetchone()
            
            if result:
                print(f"   ✅ Table exists: {result['relname']}")
                print(f"   Kind: {result['relkind']} ({'partitioned table' if result['relkind'] == 'p' else 'regular table'})")
                print(f"   Partition key: {result['partition_key']}")
                print(f"   Is partition: {result['relispartition']}")
            else:
                print(f"   ❌ Table {term_table} not found!")
                return
        
        print(f"\n2. Checking existing partitions:")
        async with conn.cursor() as cursor:
            partitions_sql = """
            SELECT 
                c.relname,
                pg_get_expr(c.relpartbound, c.oid) as partition_bound
            FROM pg_class c
            JOIN pg_inherits i ON c.oid = i.inhrelid
            JOIN pg_class parent ON i.inhparent = parent.oid
            WHERE parent.relname = %s
            ORDER BY c.relname;
            """
            await cursor.execute(partitions_sql, (term_table,))
            partitions = await cursor.fetchall()
            
            print(f"   Found {len(partitions)} existing partitions:")
            for p in partitions:
                print(f"   - {p['relname']}: {p['partition_bound']}")
        
        print(f"\n3. Attempting to create partition: {term_partition}")
        create_sql = f"""
        CREATE TABLE {term_partition} PARTITION OF {term_table}
        FOR VALUES IN ('{partition_dataset}');
        """
        print(f"   SQL: {create_sql.strip()}")
        
        async with conn.cursor() as cursor:
            try:
                await cursor.execute(create_sql)
                print(f"   ✅ SQL executed without error")
            except Exception as e:
                print(f"   ❌ SQL failed: {e}")
                print(f"   Error type: {type(e).__name__}")
                return
        
        print(f"\n4. Verifying partition was created:")
        async with conn.cursor() as cursor:
            verify_sql = """
            SELECT 
                c.relname,
                c.relispartition,
                pg_get_expr(c.relpartbound, c.oid) as partition_bound
            FROM pg_class c
            WHERE c.relname = %s;
            """
            await cursor.execute(verify_sql, (term_partition,))
            result = await cursor.fetchone()
            
            if result:
                print(f"   ✅ Partition found: {result['relname']}")
                print(f"   Is partition: {result['relispartition']}")
                print(f"   Bound: {result['partition_bound']}")
            else:
                print(f"   ❌ Partition {term_partition} NOT FOUND after creation!")
        
        print(f"\n5. Checking all partitions again:")
        async with conn.cursor() as cursor:
            await cursor.execute(partitions_sql, (term_table,))
            partitions = await cursor.fetchall()
            
            print(f"   Found {len(partitions)} partitions after creation:")
            for p in partitions:
                print(f"   - {p['relname']}: {p['partition_bound']}")
        
        print(f"\n6. Checking if table exists with different name pattern:")
        async with conn.cursor() as cursor:
            search_sql = """
            SELECT relname, relkind, relispartition
            FROM pg_class 
            WHERE relname LIKE %s
            ORDER BY relname;
            """
            await cursor.execute(search_sql, (f"%{partition_dataset}%",))
            results = await cursor.fetchall()
            
            print(f"   Tables matching '{partition_dataset}' pattern:")
            for r in results:
                print(f"   - {r['relname']} (kind: {r['relkind']}, is_partition: {r['relispartition']})")
    
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(direct_partition_test())
