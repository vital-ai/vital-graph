#!/usr/bin/env python3

import asyncio
import psycopg
from psycopg.rows import dict_row
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

async def simple_partition_test():
    """Simple test to create and verify partition persistence."""
    
    print("🔍 Simple partition persistence test...")
    
    # Connect to database with autocommit
    conn = await psycopg.AsyncConnection.connect(
        host="localhost",
        port=5432,
        dbname="vitalgraphdb",
        user="postgres",
        password="postgres",
        autocommit=True,  # Use autocommit to avoid transaction issues
        row_factory=dict_row
    )
    
    try:
        term_table = "vitalgraph2__import_001__term"
        partition_name = f"{term_table}_csv_import_001"
        
        print(f"\n1. Checking existing partitions for {term_table}:")
        async with conn.cursor() as cursor:
            check_sql = """
            SELECT c.relname, pg_get_expr(c.relpartbound, c.oid) as bound
            FROM pg_class c
            JOIN pg_inherits i ON c.oid = i.inhrelid
            JOIN pg_class parent ON i.inhparent = parent.oid
            WHERE parent.relname = %s
            ORDER BY c.relname;
            """
            await cursor.execute(check_sql, (term_table,))
            partitions = await cursor.fetchall()
            
            for p in partitions:
                print(f"   - {p['relname']}: {p['bound']}")
        
        print(f"\n2. Dropping partition if it exists:")
        async with conn.cursor() as cursor:
            drop_sql = f"DROP TABLE IF EXISTS {partition_name}"
            await cursor.execute(drop_sql)
            print(f"   Executed: {drop_sql}")
        
        print(f"\n3. Creating partition {partition_name}:")
        create_sql = f"""
        CREATE TABLE {partition_name} PARTITION OF {term_table}
        FOR VALUES IN ('csv_import_001');
        """
        
        async with conn.cursor() as cursor:
            await cursor.execute(create_sql)
            print(f"   ✅ SQL executed successfully")
        
        print(f"\n4. Verifying partition exists immediately:")
        async with conn.cursor() as cursor:
            await cursor.execute(check_sql, (term_table,))
            partitions = await cursor.fetchall()
            
            csv_partition_found = False
            for p in partitions:
                print(f"   - {p['relname']}: {p['bound']}")
                if 'csv_import_001' in p['relname']:
                    csv_partition_found = True
            
            if csv_partition_found:
                print(f"   ✅ csv_import_001 partition found!")
            else:
                print(f"   ❌ csv_import_001 partition NOT found!")
        
        print(f"\n5. Closing connection and reconnecting to test persistence:")
        await conn.close()
        
        # Reconnect to test persistence
        conn2 = await psycopg.AsyncConnection.connect(
            host="localhost",
            port=5432,
            dbname="vitalgraphdb",
            user="postgres",
            password="postgres",
            row_factory=dict_row
        )
        
        print(f"\n6. Checking partitions after reconnect:")
        async with conn2.cursor() as cursor:
            await cursor.execute(check_sql, (term_table,))
            partitions = await cursor.fetchall()
            
            csv_partition_found = False
            for p in partitions:
                print(f"   - {p['relname']}: {p['bound']}")
                if 'csv_import_001' in p['relname']:
                    csv_partition_found = True
            
            if csv_partition_found:
                print(f"   ✅ csv_import_001 partition persisted!")
            else:
                print(f"   ❌ csv_import_001 partition did NOT persist!")
        
        await conn2.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        if not conn.closed:
            await conn.close()

if __name__ == "__main__":
    asyncio.run(simple_partition_test())
