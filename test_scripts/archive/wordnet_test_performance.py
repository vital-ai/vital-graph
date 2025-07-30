import logging
import time
from sqlalchemy import URL
from rdflib import Graph, URIRef
from vitalgraph.store.store import VitalGraphSQLStore
from vitalgraph.optimized_graph import OptimizedVitalGraph

PG_HOST     = "127.0.0.1"
PG_PORT     = 5432
PG_USER     = "postgres"
PG_PASSWORD = ""
PG_DATABASE = "vitalgraphdb"

GRAPH_NAME = "wordnet"


def test_query_performance(g, query_name, query, expected_min_results=0):
    """Test a SPARQL query and measure performance."""
    print(f"\n{'='*60}")
    print(f"Testing: {query_name}")
    print(f"{'='*60}")
    
    start_time = time.time()
    
    try:
        results = g.query(query)
        result_count = 0
        
        # Count results without printing them all
        for row in results:
            result_count += 1
            if result_count <= 3:  # Show first 3 results
                # Convert row to a readable format
                row_dict = {str(var): str(row[var]) for var in row.labels}
                print(f"Sample result {result_count}: {row_dict}")
        
        end_time = time.time()
        elapsed = end_time - start_time
        
        print(f"\nResults: {result_count} found")
        print(f"Execution time: {elapsed:.3f} seconds")
        
        if result_count >= expected_min_results:
            print(f"✓ SUCCESS: Found {result_count} results")
        else:
            print(f"⚠ WARNING: Expected at least {expected_min_results} results, got {result_count}")
        
        return elapsed, result_count
        
    except Exception as e:
        end_time = time.time()
        elapsed = end_time - start_time
        print(f"✗ ERROR: {e}")
        print(f"Failed after: {elapsed:.3f} seconds")
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
    g = OptimizedVitalGraph(store=store, identifier=graph_iri)

    g.open(db_url)
    print(f"Connected to WordNet graph '{GRAPH_NAME}' in PostgreSQL")
    
    total_triples = len(g)
    print(f"Total triples: {total_triples:,}")

    # Test queries with different text search patterns
    test_queries = [
        {
            "name": "CONTAINS 'happy' in names",
            "query": """
PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?entity ?entityName WHERE {
  ?entity a haley-ai-kg:KGEntity .
  ?entity vital-core:hasName ?entityName .
  FILTER(CONTAINS(LCASE(STR(?entityName)), "happy"))
}
LIMIT 10
""",
            "expected": 0
        },
        {
            "name": "CONTAINS 'joy' in descriptions",
            "query": """
PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?entity ?entityName ?description WHERE {
  ?entity a haley-ai-kg:KGEntity .
  ?entity vital-core:hasName ?entityName .
  ?entity haley-ai-kg:vital__hasKGraphDescription ?description .
  FILTER(CONTAINS(LCASE(STR(?description)), "joy"))
}
LIMIT 10
""",
            "expected": 0
        },
        {
            "name": "STRSTARTS with 'able' in names",
            "query": """
PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?entity ?entityName WHERE {
  ?entity a haley-ai-kg:KGEntity .
  ?entity vital-core:hasName ?entityName .
  FILTER(STRSTARTS(LCASE(STR(?entityName)), "able"))
}
LIMIT 10
""",
            "expected": 1
        },
        {
            "name": "REGEX pattern for words ending in 'ing'",
            "query": """
PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?entity ?entityName WHERE {
  ?entity a haley-ai-kg:KGEntity .
  ?entity vital-core:hasName ?entityName .
  FILTER(REGEX(STR(?entityName), "ing$", "i"))
}
LIMIT 10
""",
            "expected": 1
        },
        {
            "name": "CONTAINS 'good' in descriptions",
            "query": """
PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?entity ?entityName ?description WHERE {
  ?entity a haley-ai-kg:KGEntity .
  ?entity vital-core:hasName ?entityName .
  ?entity haley-ai-kg:vital__hasKGraphDescription ?description .
  FILTER(CONTAINS(LCASE(STR(?description)), "good"))
}
LIMIT 10
""",
            "expected": 1
        }
    ]

    # Run performance tests
    results = []
    total_time = 0
    
    for test in test_queries:
        elapsed, count = test_query_performance(
            g, test["name"], test["query"], test["expected"]
        )
        results.append({
            "name": test["name"],
            "time": elapsed,
            "count": count
        })
        total_time += elapsed

    # Summary
    print(f"\n{'='*60}")
    print("PERFORMANCE SUMMARY")
    print(f"{'='*60}")
    
    for result in results:
        print(f"{result['name']:<40} {result['time']:>8.3f}s ({result['count']} results)")
    
    print(f"{'Total execution time':<40} {total_time:>8.3f}s")
    print(f"{'Average per query':<40} {total_time/len(results):>8.3f}s")
    
    if total_time > 30:
        print(f"\n⚠ SLOW PERFORMANCE DETECTED!")
        print(f"Consider running: python test_scripts/wordnet_add_indexes.py")
        print(f"to add pg_trgm indexes for dramatic performance improvement.")
    elif total_time < 5:
        print(f"\n✓ EXCELLENT PERFORMANCE!")
        print(f"pg_trgm indexes appear to be working effectively.")
    else:
        print(f"\n✓ GOOD PERFORMANCE")
        print(f"Text search queries are running reasonably fast.")

    g.close()


if __name__ == "__main__":
    main()
