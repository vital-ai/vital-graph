#!/usr/bin/env python3
"""
Test SPARQL queries directly without triggering len(g) or other expensive operations.
"""

import os
import time
from rdflib import Graph, URIRef
from sqlalchemy import URL
from vitalgraph.store.store import VitalGraphSQLStore

# Database configuration
PG_HOST = os.getenv("PG_HOST", "127.0.0.1")
PG_PORT = os.getenv("PG_PORT", "5432")
PG_DATABASE = os.getenv("PG_DATABASE", "vitalgraphdb")
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "")
GRAPH_NAME = "wordnet"

def test_sparql_query(g, query_name, sparql_query):
    """Test a SPARQL query without any expensive setup operations."""
    print(f"\n{'='*60}")
    print(f"TESTING: {query_name}")
    print(f"{'='*60}")
    
    print("SPARQL Query:")
    print(sparql_query)
    
    print(f"\nExecuting SPARQL query (no len() call)...")
    start_time = time.time()
    
    try:
        results = g.query(sparql_query)
        count = 0
        sample_results = []
        
        for row in results:
            count += 1
            if count <= 3:  # Collect first 3 results
                row_dict = {str(var): str(row[var]) for var in row.labels}
                sample_results.append(row_dict)
            if count >= 10:  # Stop after 10 results
                break
        
        elapsed = time.time() - start_time
        
        print(f"\nResults: {count} found")
        print(f"Execution time: {elapsed:.3f} seconds")
        
        for i, result in enumerate(sample_results, 1):
            print(f"Sample {i}: {result}")
        
        if elapsed < 1.0:
            print("✓ EXCELLENT: Very fast!")
        elif elapsed < 5.0:
            print("✓ GOOD: Reasonable performance")
        elif elapsed < 15.0:
            print("⚠ MODERATE: Could be better")
        else:
            print("✗ SLOW: Needs optimization")
            
        return elapsed, count
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"✗ ERROR after {elapsed:.3f} seconds: {e}")
        return elapsed, 0

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
    
    print("Connected to WordNet graph")
    print("Skipping len(g) call to avoid expensive counting operation...")
    
    # Test queries without calling len(g)
    test_queries = [
        {
            "name": "Simple entity query (no text search)",
            "query": """
PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?entity ?entityName WHERE {
  ?entity a haley-ai-kg:KGEntity .
  ?entity vital-core:hasName ?entityName .
}
LIMIT 5
"""
        },
        {
            "name": "Text search: CONTAINS 'happy'",
            "query": """
PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?entity ?entityName WHERE {
  ?entity a haley-ai-kg:KGEntity .
  ?entity vital-core:hasName ?entityName .
  FILTER(CONTAINS(LCASE(STR(?entityName)), "happy"))
}
LIMIT 5
"""
        },
        {
            "name": "Text search: CONTAINS 'good'",
            "query": """
PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?entity ?entityName WHERE {
  ?entity a haley-ai-kg:KGEntity .
  ?entity vital-core:hasName ?entityName .
  FILTER(CONTAINS(LCASE(STR(?entityName)), "good"))
}
LIMIT 5
"""
        }
    ]
    
    results = []
    total_time = 0
    
    for test in test_queries:
        elapsed, count = test_sparql_query(g, test["name"], test["query"])
        results.append((test["name"], elapsed, count))
        total_time += elapsed
    
    print(f"\n{'='*60}")
    print("PERFORMANCE SUMMARY")
    print(f"{'='*60}")
    
    for name, elapsed, count in results:
        print(f"{name:<40} {elapsed:>8.3f}s ({count} results)")
    
    print(f"{'Total execution time':<40} {total_time:>8.3f}s")
    print(f"{'Average per query':<40} {total_time/len(results):>8.3f}s")
    
    if total_time < 10:
        print("\n✓ EXCELLENT: Text search is now optimized!")
    elif total_time < 30:
        print("\n✓ GOOD: Significant improvement achieved")
    else:
        print("\n✗ POOR: Still needs optimization")

if __name__ == "__main__":
    main()
