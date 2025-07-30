#!/usr/bin/env python3
"""
Script to force PostgreSQL to use pg_trgm indexes by adjusting query planner settings
and testing different query patterns.
"""

import os
import time
from sqlalchemy import URL, create_engine, text

# Database configuration
PG_HOST = os.getenv("PG_HOST", "127.0.0.1")
PG_PORT = os.getenv("PG_PORT", "5432")
PG_DATABASE = os.getenv("PG_DATABASE", "vitalgraphdb")
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "")

def main():
    # Build database URL
    db_url = URL.create(
        drivername="postgresql+psycopg",
        username=PG_USER,
        password=PG_PASSWORD or None,
        host=PG_HOST,
        port=PG_PORT,
        database=PG_DATABASE,
    )

    engine = create_engine(db_url)
    
    # Get the interned_id for table names
    from vitalgraph.store.store import VitalGraphSQLStore
    store = VitalGraphSQLStore()
    interned_id = store._interned_id
    
    literal_table = f"{interned_id}_literal_statements"
    
    print("="*60)
    print("FORCING INDEX USAGE FOR TEXT SEARCH")
    print("="*60)
    
    with engine.connect() as connection:
        
        # 1. Check current PostgreSQL settings
        print("\n1. Current PostgreSQL settings:")
        settings_to_check = [
            'enable_seqscan',
            'enable_indexscan', 
            'enable_bitmapscan',
            'random_page_cost',
            'seq_page_cost',
            'cpu_tuple_cost'
        ]
        
        for setting in settings_to_check:
            result = connection.execute(text(f"SHOW {setting}"))
            value = result.scalar()
            print(f"  {setting}: {value}")
        
        # 2. Temporarily disable sequential scans to force index usage
        print("\n2. Disabling sequential scans to force index usage...")
        connection.execute(text("SET enable_seqscan = off"))
        
        # 3. Test the same query with seq scan disabled
        print("\n3. Testing query with seq scan disabled:")
        
        start_time = time.time()
        result = connection.execute(text(f"""
            EXPLAIN (ANALYZE, BUFFERS) 
            SELECT * FROM {literal_table} 
            WHERE object ILIKE '%good%' 
            LIMIT 5
        """))
        elapsed = time.time() - start_time
        
        print(f"\nQuery plan with seq scan disabled:")
        for row in result:
            print(f"  {row[0]}")
        print(f"Planning time: {elapsed:.3f} seconds")
        
        # 4. Test with pg_trgm similarity operator
        print("\n4. Testing with pg_trgm similarity operator:")
        
        start_time = time.time()
        result = connection.execute(text(f"""
            EXPLAIN (ANALYZE, BUFFERS) 
            SELECT * FROM {literal_table} 
            WHERE object % 'good'
            LIMIT 5
        """))
        elapsed = time.time() - start_time
        
        print(f"\nQuery plan with similarity operator:")
        for row in result:
            print(f"  {row[0]}")
        print(f"Planning time: {elapsed:.3f} seconds")
        
        # 5. Test actual query performance
        print("\n5. Testing actual query performance:")
        
        # Test with ILIKE (current approach)
        start_time = time.time()
        result = connection.execute(text(f"""
            SELECT object FROM {literal_table} 
            WHERE object ILIKE '%good%' 
            LIMIT 10
        """))
        rows = result.fetchall()
        elapsed_ilike = time.time() - start_time
        print(f"  ILIKE query: {elapsed_ilike:.3f} seconds, {len(rows)} results")
        
        # Test with similarity operator
        start_time = time.time()
        result = connection.execute(text(f"""
            SELECT object FROM {literal_table} 
            WHERE object % 'good'
            LIMIT 10
        """))
        rows = result.fetchall()
        elapsed_similarity = time.time() - start_time
        print(f"  Similarity query: {elapsed_similarity:.3f} seconds, {len(rows)} results")
        
        # 6. Adjust cost parameters to favor index scans
        print("\n6. Adjusting cost parameters to favor indexes...")
        connection.execute(text("SET random_page_cost = 1.0"))  # Default is 4.0
        connection.execute(text("SET seq_page_cost = 10.0"))    # Default is 1.0
        connection.execute(text("SET enable_seqscan = on"))     # Re-enable but make expensive
        
        start_time = time.time()
        result = connection.execute(text(f"""
            EXPLAIN (ANALYZE, BUFFERS) 
            SELECT * FROM {literal_table} 
            WHERE object ILIKE '%good%' 
            LIMIT 5
        """))
        elapsed = time.time() - start_time
        
        print(f"\nQuery plan with adjusted costs:")
        for row in result:
            print(f"  {row[0]}")
        print(f"Planning time: {elapsed:.3f} seconds")
        
        # 7. Check index statistics
        print("\n7. Index usage statistics:")
        result = connection.execute(text(f"""
            SELECT 
                schemaname,
                relname as tablename,
                indexrelname as indexname,
                idx_scan,
                idx_tup_read,
                idx_tup_fetch
            FROM pg_stat_user_indexes 
            WHERE relname = '{literal_table}'
            AND indexrelname LIKE '%trgm%'
        """))
        
        for row in result:
            print(f"  Index: {row[2]}")
            print(f"    Scans: {row[3]}")
            print(f"    Tuples read: {row[4]}")
            print(f"    Tuples fetched: {row[5]}")
        
        # Reset settings
        connection.execute(text("RESET enable_seqscan"))
        connection.execute(text("RESET random_page_cost"))
        connection.execute(text("RESET seq_page_cost"))
        
    print("\n" + "="*60)
    print("INDEX OPTIMIZATION ANALYSIS COMPLETE")
    print("="*60)

if __name__ == "__main__":
    main()
