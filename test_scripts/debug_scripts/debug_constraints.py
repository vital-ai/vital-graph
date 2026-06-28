#!/usr/bin/env python3

import asyncio
import psycopg

async def debug_constraints():
    """Debug CHECK constraints on partition tables"""
    
    # Connect directly to PostgreSQL using correct credentials
    conn = await psycopg.AsyncConnection.connect(
        "postgresql://postgres:@host.docker.internal:5432/vitalgraphdb"
    )
    
    try:
        cursor = conn.cursor()
        
        # Find recent temp tables
        await cursor.execute("""
            SELECT tablename 
            FROM pg_tables 
            WHERE tablename LIKE 'temp_%_import_%' 
            AND schemaname = 'public'
            ORDER BY tablename DESC 
            LIMIT 2
        """)
        tables = await cursor.fetchall()
        
        # Check PostgreSQL version first
        await cursor.execute("SELECT version()")
        version = await cursor.fetchone()
        print(f"PostgreSQL Version: {version[0]}")
        
        # Check if we have any temp tables
        if not tables:
            print("No temp tables found - they may have been cleaned up after attachment")
            
            # Look for recent partitions instead
            await cursor.execute("""
                SELECT schemaname, tablename 
                FROM pg_tables 
                WHERE tablename LIKE '%part_%term' 
                AND schemaname = 'public'
                ORDER BY tablename DESC 
                LIMIT 3
            """)
            partitions = await cursor.fetchall()
            
            # Also check what partition constraints look like
            await cursor.execute("""
                SELECT 
                    schemaname,
                    tablename,
                    partitionname,
                    partitionboundary
                FROM pg_partitions 
                WHERE tablename LIKE '%part_%term'
                ORDER BY partitionname DESC 
                LIMIT 3
            """)
            partition_info = await cursor.fetchall()
            
            if partition_info:
                print("\nPartition boundary info:")
                for schema, table, partition, boundary in partition_info:
                    print(f"  {partition}: {boundary}")
            
            if partitions:
                print("\nRecent partitions:")
                for schema, table_name in partitions:
                    print(f"\n=== {table_name} ===")
                    
                    # Check constraints on actual partitions
                    await cursor.execute(f"""
                        SELECT conname, pg_get_constraintdef(oid) as definition
                        FROM pg_constraint 
                        WHERE conrelid = '{table_name}'::regclass 
                        AND contype = 'c'
                        ORDER BY conname
                    """)
                    constraints = await cursor.fetchall()
                    
                    if constraints:
                        print("CHECK constraints:")
                        for name, definition in constraints:
                            print(f"  {name}: {definition}")
                    else:
                        print("No CHECK constraints found")
                        
                    # Check partition constraint (what PostgreSQL automatically adds)
                    await cursor.execute(f"""
                        SELECT conname, pg_get_constraintdef(oid) as definition
                        FROM pg_constraint 
                        WHERE conrelid = '{table_name}'::regclass 
                        AND contype = 'c'
                        AND conname LIKE '%_partition_constraint'
                        ORDER BY conname
                    """)
                    partition_constraints = await cursor.fetchall()
                    
                    if partition_constraints:
                        print("Partition constraints:")
                        for name, definition in partition_constraints:
                            print(f"  {name}: {definition}")
            return
        
        print("Recent temp tables:")
        for table in tables:
            table_name = table[0]
            print(f"\n=== {table_name} ===")
            
            # Check constraints
            await cursor.execute(f"""
                SELECT conname, pg_get_constraintdef(oid) as definition
                FROM pg_constraint 
                WHERE conrelid = '{table_name}'::regclass 
                AND contype = 'c'
                ORDER BY conname
            """)
            constraints = await cursor.fetchall()
            
            if constraints:
                print("CHECK constraints:")
                for name, definition in constraints:
                    print(f"  {name}: {definition}")
            else:
                print("No CHECK constraints found")
                
            # Check if table exists
            await cursor.execute(f"""
                SELECT EXISTS (
                    SELECT 1 FROM pg_tables 
                    WHERE tablename = '{table_name}' 
                    AND schemaname = 'public'
                )
            """)
            exists = await cursor.fetchone()
            print(f"Table exists: {exists[0]}")
            
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(debug_constraints())
