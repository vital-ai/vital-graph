#!/usr/bin/env python3
"""
Apply permanent PostgreSQL optimizations for text search performance.
This will make the query planner favor index usage over sequential scans.
"""

import os
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
    
    print("="*60)
    print("APPLYING POSTGRESQL OPTIMIZATIONS FOR TEXT SEARCH")
    print("="*60)
    
    # First check current settings
    with engine.connect() as connection:
        print("\n1. Current cost settings:")
        for setting in ['random_page_cost', 'seq_page_cost']:
            result = connection.execute(text(f"SHOW {setting}"))
            value = result.scalar()
            print(f"  {setting}: {value}")
    
    # Use autocommit for ALTER SYSTEM commands
    print("\n2. Applying optimizations...")
    
    import psycopg
    from urllib.parse import urlparse
    
    # Parse the database URI
    parsed = urlparse(str(db_url))
    
    # Connect with autocommit for ALTER SYSTEM
    conn = psycopg.connect(
        host=parsed.hostname,
        port=parsed.port,
        dbname=parsed.path[1:],  # Remove leading slash
        user=parsed.username,
        password=parsed.password,
        autocommit=True
    )
    
    try:
        with conn.cursor() as cursor:
            # Key optimization: Make random access cheaper to favor index scans
            print("  Setting random_page_cost = 1.0 (was 4.0)")
            cursor.execute("ALTER SYSTEM SET random_page_cost = 1.0")
            
            # Optional: Make sequential scans slightly more expensive
            print("  Setting seq_page_cost = 1.2 (was 1.0)")
            cursor.execute("ALTER SYSTEM SET seq_page_cost = 1.2")
            
            # Reload configuration
            print("\n3. Reloading PostgreSQL configuration...")
            cursor.execute("SELECT pg_reload_conf()")
    
    finally:
        conn.close()
    
    # Check new settings
    with engine.connect() as connection:
        print("\n4. New settings:")
        for setting in ['random_page_cost', 'seq_page_cost']:
            result = connection.execute(text(f"SHOW {setting}"))
            value = result.scalar()
            print(f"  {setting}: {value}")
        
    print("\n" + "="*60)
    print("✓ OPTIMIZATION COMPLETE")
    print("="*60)
    print("\nChanges applied:")
    print("- random_page_cost: 4.0 → 1.0 (favors index scans)")
    print("- seq_page_cost: 1.0 → 1.2 (makes seq scans slightly more expensive)")
    print("\nThese settings are persistent and will survive PostgreSQL restarts.")
    print("\nYour SPARQL text search queries should now be MUCH faster!")
    print("Test with: python test_scripts/wordnet_test_performance.py")

if __name__ == "__main__":
    main()
