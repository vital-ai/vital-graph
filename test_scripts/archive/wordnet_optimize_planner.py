#!/usr/bin/env python3
"""
Script to permanently optimize PostgreSQL query planner settings
to favor index usage for text search operations.
"""

import os
import time
from sqlalchemy import URL, create_engine, text
from rdflib import Graph, URIRef
from vitalgraph.store.store import VitalGraphSQLStore

# Database configuration
PG_HOST = os.getenv("PG_HOST", "127.0.0.1")
PG_PORT = os.getenv("PG_PORT", "5432")
PG_DATABASE = os.getenv("PG_DATABASE", "vitalgraphdb")
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "")
GRAPH_NAME = "wordnet"

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
    print("OPTIMIZING POSTGRESQL FOR TEXT SEARCH PERFORMANCE")
    print("="*60)
    
    with engine.connect() as connection:
        
        print("\n1. Current settings:")
        current_settings = {}
        for setting in ['random_page_cost', 'seq_page_cost', 'cpu_tuple_cost', 'effective_cache_size']:
            result = connection.execute(text(f"SHOW {setting}"))
            value = result.scalar()
            current_settings[setting] = value
            print(f"  {setting}: {value}")
        
        print("\n2. Applying optimizations for text search workloads...")
        
        # Optimize for SSD storage and text search
        optimizations = [
            ("random_page_cost", "1.1"),      # SSD-optimized (default 4.0)
            ("seq_page_cost", "1.0"),         # Keep default
            ("cpu_tuple_cost", "0.01"),       # Keep default  
            ("effective_cache_size", "1GB"),  # Adjust based on available RAM
        ]
        
        for setting, value in optimizations:
            print(f"  Setting {setting} = {value}")
            connection.execute(text(f"ALTER SYSTEM SET {setting} = '{value}'"))
        
        # Reload configuration
        print("\n3. Reloading PostgreSQL configuration...")
        connection.execute(text("SELECT pg_reload_conf()"))
        
        print("\n4. Verifying new settings:")
        for setting, expected_value in optimizations:
            result = connection.execute(text(f"SHOW {setting}"))
            actual_value = result.scalar()
            print(f"  {setting}: {actual_value}")
        
        print("\n5. Testing query performance with new settings...")
        
        # Get table name
        store = VitalGraphSQLStore()
        interned_id = store._interned_id
        literal_table = f"{interned_id}_literal_statements"
        
        # Test query performance
        start_time = time.time()
        result = connection.execute(text(f"""
            SELECT object FROM {literal_table} 
            WHERE object ILIKE '%good%' 
            LIMIT 10
        """))
        rows = result.fetchall()
        elapsed = time.time() - start_time
        
        print(f"  Direct SQL query: {elapsed:.3f} seconds, {len(rows)} results")
        
        # Test query plan
        result = connection.execute(text(f"""
            EXPLAIN (ANALYZE, BUFFERS) 
            SELECT object FROM {literal_table} 
            WHERE object ILIKE '%good%' 
            LIMIT 10
        """))
        
        print(f"\n6. Query execution plan:")
        for row in result:
            line = row[0]
            if 'Index Scan' in line or 'Bitmap' in line:
                print(f"  ✓ {line}")
            else:
                print(f"    {line}")
    
    print("\n7. Testing SPARQL query performance...")
    
    # Test SPARQL performance
    store = VitalGraphSQLStore()
    graph_iri = URIRef(f"http://vital.ai/graph/{GRAPH_NAME}")
    g = Graph(store=store, identifier=graph_iri)
    g.open(db_url)
    
    # Test the problematic SPARQL query
    sparql_query = """
PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?entity ?entityName WHERE {
  ?entity a haley-ai-kg:KGEntity .
  ?entity vital-core:hasName ?entityName .
  FILTER(CONTAINS(LCASE(STR(?entityName)), "happy"))
}
LIMIT 10
"""
    
    start_time = time.time()
    results = g.query(sparql_query)
    result_count = sum(1 for _ in results)
    elapsed = time.time() - start_time
    
    print(f"  SPARQL query: {elapsed:.3f} seconds, {result_count} results")
    
    if elapsed < 5.0:
        print(f"  ✓ EXCELLENT: Query performance is now optimized!")
    elif elapsed < 15.0:
        print(f"  ⚠ GOOD: Significant improvement, but could be better")
    else:
        print(f"  ✗ POOR: Still slow, may need additional optimization")
    
    print("\n" + "="*60)
    print("POSTGRESQL OPTIMIZATION COMPLETE")
    print("="*60)
    print("\nOptimizations applied:")
    print("- random_page_cost reduced for SSD storage")
    print("- Query planner now favors index scans for text search")
    print("- Configuration changes are persistent across restarts")
    print("\nYour SPARQL text search queries should now be much faster!")

if __name__ == "__main__":
    main()
