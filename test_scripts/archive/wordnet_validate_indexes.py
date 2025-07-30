#!/usr/bin/env python3
"""
Simple script to validate that the pg_trgm indexes are working
and to understand the actual data structure in WordNet.
"""

import os
import time
from rdflib import Graph, URIRef
from sqlalchemy import URL, create_engine, text
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

    store = VitalGraphSQLStore()
    graph_iri = URIRef(f"http://vital.ai/graph/{GRAPH_NAME}")
    g = Graph(store=store, identifier=graph_iri)

    g.open(db_url)
    print(f"Connected to WordNet graph '{GRAPH_NAME}' in PostgreSQL")
    
    total_triples = len(g)
    print(f"Total triples: {total_triples:,}")

    print("\n" + "="*60)
    print("TESTING INDEX EFFECTIVENESS")
    print("="*60)

    # Test 1: Simple query to see what predicates exist
    print("\n1. Finding available predicates...")
    start_time = time.time()
    
    query1 = """
    SELECT DISTINCT ?predicate WHERE {
      ?s ?predicate ?o .
    }
    LIMIT 20
    """
    
    results = g.query(query1)
    elapsed = time.time() - start_time
    
    predicates = []
    for row in results:
        predicate = str(row[0])
        predicates.append(predicate)
        print(f"  {predicate}")
    
    print(f"Found {len(predicates)} predicates in {elapsed:.3f} seconds")

    # Test 2: Find some sample entities
    print("\n2. Finding sample entities...")
    start_time = time.time()
    
    query2 = """
    SELECT ?entity ?predicate ?value WHERE {
      ?entity ?predicate ?value .
      FILTER(isLiteral(?value))
    }
    LIMIT 10
    """
    
    results = g.query(query2)
    elapsed = time.time() - start_time
    
    count = 0
    for row in results:
        count += 1
        entity = str(row[0])
        predicate = str(row[1])
        value = str(row[2])
        print(f"  {entity} -> {predicate} -> {value[:50]}...")
    
    print(f"Found {count} sample triples in {elapsed:.3f} seconds")

    # Test 3: Simple text search on any literal
    print("\n3. Testing simple text search...")
    start_time = time.time()
    
    query3 = """
    SELECT ?s ?p ?o WHERE {
      ?s ?p ?o .
      FILTER(isLiteral(?o) && CONTAINS(LCASE(STR(?o)), "good"))
    }
    LIMIT 5
    """
    
    results = g.query(query3)
    elapsed = time.time() - start_time
    
    count = 0
    for row in results:
        count += 1
        s = str(row[0])
        p = str(row[1])
        o = str(row[2])
        print(f"  {s} -> {p} -> {o[:50]}...")
    
    print(f"Found {count} results with 'good' in {elapsed:.3f} seconds")

    # Test 4: Check index usage with EXPLAIN
    print("\n4. Checking if indexes are being used...")
    
    # Connect directly to check query plans
    engine = create_engine(db_url)
    interned_id = store._interned_id
    
    with engine.connect() as connection:
        # Check a simple text search query plan
        explain_query = f"""
        EXPLAIN (ANALYZE, BUFFERS) 
        SELECT * FROM {interned_id}_literal_statements 
        WHERE object ILIKE '%good%' 
        LIMIT 5
        """
        
        result = connection.execute(text(explain_query))
        print("\nQuery execution plan:")
        for row in result:
            print(f"  {row[0]}")

    print("\n" + "="*60)
    print("INDEX VALIDATION COMPLETE")
    print("="*60)
    print("\nIf you see 'Bitmap Index Scan' or 'Index Scan' in the query plan,")
    print("the pg_trgm indexes are working correctly!")

if __name__ == "__main__":
    main()
