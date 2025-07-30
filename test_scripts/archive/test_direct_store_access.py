#!/usr/bin/env python3
"""
Test direct store access with hardcoded identifier
"""

import os
import sys
import time
from sqlalchemy import URL
from rdflib import Graph

# Add the parent directory to the path so we can import vitalgraph
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from vitalgraph.store.store import VitalGraphSQLStore

# Database connection parameters
PG_HOST     = "127.0.0.1"
PG_PORT     = 5432
PG_USER     = "postgres"
PG_PASSWORD = ""
PG_DATABASE = "vitalgraphdb"

def main():
    print("Testing direct store access with 'hardcoded' identifier")
    print("=" * 50)
    
    # Database connection
    db_url = URL.create(
        drivername="postgresql+psycopg",
        username=PG_USER,
        password=PG_PASSWORD or None,
        host=PG_HOST,
        port=PG_PORT,
        database=PG_DATABASE,
    )
    
    # Test 1: Direct store access
    print("Test 1: Direct VitalGraphSQLStore")
    store = VitalGraphSQLStore()
    store.open(db_url)
    
    print(f"Store identifier: {store.identifier}")
    print(f"Store interned ID: {store._interned_id}")
    
    # Test 2: Graph with hardcoded identifier
    print(f"\nTest 2: Graph with 'hardcoded' identifier")
    g = Graph(store=store, identifier="hardcoded")
    
    # Check triple count
    total_triples = len(g)
    print(f"Total triples: {total_triples:,}")
    
    if total_triples > 0:
        print("✅ SUCCESS: Found triples in the graph!")
        
        # Test a simple SPARQL query
        print(f"\nTest 3: Simple SPARQL query")
        simple_query = """
        SELECT ?s ?p ?o WHERE {
          ?s ?p ?o .
        }
        LIMIT 5
        """
        
        start_time = time.time()
        results = list(g.query(simple_query))
        elapsed = time.time() - start_time
        
        print(f"Found {len(results)} sample triples:")
        for i, row in enumerate(results):
            print(f"  {i+1}: {row.s} {row.p} {row.o}")
        print(f"Query time: {elapsed:.3f} seconds")
        
        # Test text search
        print(f"\nTest 4: Text search query")
        text_query = """
        SELECT ?s ?p ?o WHERE {
          ?s ?p ?o .
          FILTER(CONTAINS(STR(?o), "happy"))
        }
        LIMIT 5
        """
        
        start_time = time.time()
        text_results = list(g.query(text_query))
        elapsed = time.time() - start_time
        
        print(f"Found {len(text_results)} results with 'happy':")
        for i, row in enumerate(text_results):
            print(f"  {i+1}: {row.s} {row.p} {row.o}")
        print(f"Query time: {elapsed:.3f} seconds")
        
    else:
        print("❌ No triples found - checking table contents directly...")
        
        # Check table contents with direct SQL
        from sqlalchemy import create_engine, text
        
        engine = create_engine(db_url)
        with engine.connect() as conn:
            # Check if tables exist and have data
            tables_to_check = [
                'kb_bec6803d52_asserted_statements',
                'kb_bec6803d52_literal_statements',
                'kb_bec6803d52_type_statements',
                'kb_bec6803d52_quoted_statements'
            ]
            
            for table in tables_to_check:
                try:
                    result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                    count = result.scalar()
                    print(f"  {table}: {count:,} rows")
                except Exception as e:
                    print(f"  {table}: Error - {e}")

if __name__ == "__main__":
    main()
