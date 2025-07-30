#!/usr/bin/env python3
"""
Test direct SQL text search vs SPARQL to identify the performance bottleneck.
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

def test_direct_sql_search(engine, interned_id):
    """Test direct SQL text search on literal_statements table."""
    print("="*60)
    print("TESTING DIRECT SQL TEXT SEARCH")
    print("="*60)
    
    literal_table = f"{interned_id}_literal_statements"
    
    with engine.connect() as connection:
        
        # Test 1: Simple text search with ILIKE
        print(f"\n1. Direct ILIKE search on {literal_table}:")
        start_time = time.time()
        
        result = connection.execute(text(f"""
            SELECT subject, predicate, object 
            FROM {literal_table} 
            WHERE object ILIKE '%happy%' 
            LIMIT 10
        """))
        
        rows = result.fetchall()
        elapsed = time.time() - start_time
        
        print(f"   Results: {len(rows)} found in {elapsed:.3f} seconds")
        for i, row in enumerate(rows[:3]):
            obj = str(row[2])[:60] + "..." if len(str(row[2])) > 60 else str(row[2])
            print(f"   Sample {i+1}: {obj}")
        
        # Test 2: Check if index is being used
        print(f"\n2. Query plan for ILIKE search:")
        result = connection.execute(text(f"""
            EXPLAIN (ANALYZE, BUFFERS) 
            SELECT subject, predicate, object 
            FROM {literal_table} 
            WHERE object ILIKE '%happy%' 
            LIMIT 10
        """))
        
        uses_index = False
        for row in result:
            line = row[0]
            print(f"   {line}")
            if 'Index Scan' in line or 'Bitmap' in line:
                uses_index = True
        
        if uses_index:
            print("   ✓ Index is being used!")
        else:
            print("   ✗ No index usage detected")
        
        # Test 3: Join with asserted_statements (similar to SPARQL)
        print(f"\n3. JOIN query (similar to SPARQL pattern):")
        asserted_table = f"{interned_id}_asserted_statements"
        
        start_time = time.time()
        
        result = connection.execute(text(f"""
            SELECT a.subject, l.object 
            FROM {asserted_table} a
            JOIN {literal_table} l ON a.subject = l.subject
            WHERE l.object ILIKE '%happy%'
            AND a.predicate = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
            LIMIT 10
        """))
        
        rows = result.fetchall()
        elapsed = time.time() - start_time
        
        print(f"   Results: {len(rows)} found in {elapsed:.3f} seconds")
        
        if elapsed > 10:
            print("   ✗ SLOW - This might be the SPARQL bottleneck!")
        else:
            print("   ✓ FAST - JOIN performance is good")

def test_sparql_simple(g):
    """Test the simplest possible SPARQL text search."""
    print("\n" + "="*60)
    print("TESTING SIMPLE SPARQL TEXT SEARCH")
    print("="*60)
    
    # Simplest possible text search query
    simple_query = """
SELECT ?s ?p ?o WHERE {
  ?s ?p ?o .
  FILTER(CONTAINS(STR(?o), "happy"))
}
LIMIT 5
"""
    
    print("SPARQL Query:")
    print(simple_query)
    
    start_time = time.time()
    
    try:
        results = g.query(simple_query)
        count = 0
        for row in results:
            count += 1
            if count >= 5:
                break
        
        elapsed = time.time() - start_time
        print(f"\nResults: {count} found in {elapsed:.3f} seconds")
        
        if elapsed > 30:
            print("✗ VERY SLOW - SPARQL has major performance issues")
        elif elapsed > 10:
            print("⚠ SLOW - SPARQL needs optimization")
        else:
            print("✓ FAST - SPARQL performance is good")
            
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"ERROR after {elapsed:.3f} seconds: {e}")

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
    store = VitalGraphSQLStore()
    interned_id = store._interned_id
    
    print("Testing text search performance...")
    print(f"Database: {PG_DATABASE}")
    print(f"Tables: {interned_id}_*")
    
    # Test direct SQL first
    test_direct_sql_search(engine, interned_id)
    
    # Test SPARQL
    graph_iri = URIRef(f"http://vital.ai/graph/{GRAPH_NAME}")
    g = Graph(store=store, identifier=graph_iri)
    g.open(db_url)
    
    test_sparql_simple(g)
    
    print("\n" + "="*60)
    print("ANALYSIS COMPLETE")
    print("="*60)
    print("\nComparison:")
    print("- If direct SQL is fast but SPARQL is slow:")
    print("  → Problem is in SPARQL-to-SQL translation")
    print("- If both are slow:")
    print("  → Problem is with indexes or PostgreSQL settings")
    print("- If JOIN queries are slow:")
    print("  → Problem is with complex query patterns")

if __name__ == "__main__":
    main()
