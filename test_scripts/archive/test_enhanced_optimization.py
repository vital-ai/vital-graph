#!/usr/bin/env python3
"""
Test script for Phase 2: Enhanced Query Generation
Tests various SPARQL patterns to verify general optimization improvements
"""

import os
import sys
import time
from sqlalchemy import URL
from rdflib import URIRef

# Add the parent directory to the path so we can import vitalgraph
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from vitalgraph.store.store import VitalGraphSQLStore
from vitalgraph.optimized_graph import OptimizedVitalGraph

# Database connection parameters
PG_HOST     = "127.0.0.1"
PG_PORT     = 5432
PG_USER     = "postgres"
PG_PASSWORD = ""
PG_DATABASE = "vitalgraphdb"

# Graph name
GRAPH_NAME = "wordnet"

def test_query_performance(g, query_name, query, expected_min_results=1):
    """Test a query and report performance"""
    print(f"\n{query_name}:")
    print("-" * 50)
    
    start_time = time.time()
    try:
        results = list(g.query(query))
        end_time = time.time()
        elapsed = end_time - start_time
        
        result_count = len(results)
        print(f"✓ Results: {result_count}")
        print(f"✓ Time: {elapsed:.3f} seconds")
        
        if result_count >= expected_min_results:
            print(f"✓ Performance: {'FAST' if elapsed < 1.0 else 'SLOW'}")
        else:
            print(f"⚠ Warning: Expected at least {expected_min_results} results, got {result_count}")
            
        return elapsed, result_count
        
    except Exception as e:
        end_time = time.time()
        elapsed = end_time - start_time
        print(f"✗ Error: {e}")
        print(f"✗ Time: {elapsed:.3f} seconds")
        return elapsed, 0

def main():
    # Build database connection
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
    g = OptimizedVitalGraph(store=store, identifier=graph_iri)
    g.open(db_url)

    print(f"Testing Enhanced Query Generation (Phase 2)")
    print(f"Connected to WordNet graph '{GRAPH_NAME}' in PostgreSQL")
    print(f"Total triples: {len(g):,}")

    # Test 1: Simple type query (should use single table optimization)
    type_query = """
    SELECT ?entity WHERE {
        ?entity a <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
    } LIMIT 10
    """
    test_query_performance(g, "Test 1: Type Query (Single Table)", type_query, 10)

    # Test 2: Simple predicate query (should use predicate optimization)
    name_query = """
    SELECT ?entity ?name WHERE {
        ?entity <http://vital.ai/ontology/vital-core#hasName> ?name .
    } LIMIT 10
    """
    test_query_performance(g, "Test 2: Name Query (Predicate Optimization)", name_query, 10)

    # Test 3: Description query (should use predicate optimization)
    desc_query = """
    SELECT ?entity ?desc WHERE {
        ?entity <http://vital.ai/ontology/haley-ai-kg#vital__hasKGraphDescription> ?desc .
    } LIMIT 10
    """
    test_query_performance(g, "Test 3: Description Query (Predicate Optimization)", desc_query, 10)

    # Test 4: Text search (should use Phase 1 optimization)
    text_query = """
    SELECT ?entity ?name WHERE {
        ?entity <http://vital.ai/ontology/vital-core#hasName> ?name .
        FILTER(CONTAINS(?name, "happy"))
    } LIMIT 10
    """
    test_query_performance(g, "Test 4: Text Search (Phase 1 Optimization)", text_query, 1)

    # Test 5: Complex query (should fall back to original)
    complex_query = """
    SELECT DISTINCT ?class WHERE {
        ?entity a ?class .
    } LIMIT 10
    """
    test_query_performance(g, "Test 5: Complex Query (Original Fallback)", complex_query, 1)

    print(f"\n" + "="*60)
    print("ENHANCED OPTIMIZATION TEST COMPLETE")
    print("="*60)
    
    g.close()

if __name__ == "__main__":
    main()
