#!/usr/bin/env python3
"""
Test the WordNet complex query with standard Graph vs OptimizedVitalGraph
to identify if the issue is with OptimizedVitalGraph's complex query handling.
"""

import sys
import os
import time

# Add the parent directory to sys.path to import vitalgraph
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from vitalgraph.store.store import VitalGraphSQLStore
from vitalgraph.optimized_graph import OptimizedVitalGraph
from rdflib import Graph, URIRef

def test_wordnet_with_both_graphs():
    """Test WordNet query with both standard Graph and OptimizedVitalGraph"""
    
    print("=== Testing WordNet Query with Both Graph Types ===")
    
    store = VitalGraphSQLStore(identifier="hardcoded")
    store.open("postgresql+psycopg://postgres@127.0.0.1:5432/vitalgraphdb", create=False)
    
    graph_iri = URIRef("http://vital.ai/graph/wordnet")
    
    # Test with standard Graph
    print("\n🔍 Test 1: Standard rdflib.Graph")
    standard_g = Graph(store=store, identifier=graph_iri)
    
    # Simple query first
    simple_query = """
    PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
    PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
    
    SELECT ?entity ?entityName WHERE {
      ?entity a haley-ai-kg:KGEntity .
      ?entity vital-core:hasName ?entityName .
      FILTER(CONTAINS(LCASE(STR(?entityName)), "happy"))
    }
    LIMIT 3
    """
    
    print("1a. Simple query with standard Graph:")
    start_time = time.time()
    standard_simple_results = list(standard_g.query(simple_query))
    duration = time.time() - start_time
    
    print(f"✅ Standard Graph simple: {len(standard_simple_results)} results in {duration:.3f}s")
    for result in standard_simple_results:
        print(f"   - {result[0]}: {result[1]}")
    
    # Complex query with standard Graph
    complex_query = """
    PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
    PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
    
    SELECT ?entity ?entityName ?edge ?connectedEntity ?connectedName WHERE {
      ?entity a haley-ai-kg:KGEntity .
      ?entity vital-core:hasName ?entityName .
      FILTER(CONTAINS(LCASE(STR(?entityName)), "happy"))
      
      ?edge vital-core:vital__hasEdgeSource ?entity .
      ?edge vital-core:vital__hasEdgeDestination ?connectedEntity .
      
      ?connectedEntity vital-core:hasName ?connectedName .
    }
    ORDER BY ?entityName ?connectedName
    LIMIT 3
    """
    
    print("\n1b. Complex query with standard Graph:")
    start_time = time.time()
    standard_complex_results = list(standard_g.query(complex_query))
    duration = time.time() - start_time
    
    print(f"✅ Standard Graph complex: {len(standard_complex_results)} results in {duration:.3f}s")
    for result in standard_complex_results:
        print(f"   - Entity: {result[0]}")
        print(f"     Name: {result[1]}")
        print(f"     Connected: {result[4]}")
    
    # Test with OptimizedVitalGraph
    print("\n🔍 Test 2: OptimizedVitalGraph")
    opt_g = OptimizedVitalGraph(store=store, identifier=graph_iri)
    
    print("2a. Simple query with OptimizedVitalGraph:")
    start_time = time.time()
    opt_simple_results = list(opt_g.query(simple_query))
    duration = time.time() - start_time
    
    print(f"✅ OptimizedVitalGraph simple: {len(opt_simple_results)} results in {duration:.3f}s")
    for result in opt_simple_results:
        print(f"   - {result[0]}: {result[1]}")
    
    print("\n2b. Complex query with OptimizedVitalGraph:")
    start_time = time.time()
    opt_complex_results = list(opt_g.query(complex_query))
    duration = time.time() - start_time
    
    print(f"✅ OptimizedVitalGraph complex: {len(opt_complex_results)} results in {duration:.3f}s")
    for result in opt_complex_results:
        print(f"   - Entity: {result[0]}")
        print(f"     Name: {result[1]}")
        print(f"     Connected: {result[4]}")
    
    # Analysis
    print(f"\n📊 COMPARISON:")
    print(f"- Standard Graph simple: {len(standard_simple_results)} results")
    print(f"- OptimizedVitalGraph simple: {len(opt_simple_results)} results")
    print(f"- Standard Graph complex: {len(standard_complex_results)} results")
    print(f"- OptimizedVitalGraph complex: {len(opt_complex_results)} results")
    
    if len(standard_complex_results) > 0 and len(opt_complex_results) == 0:
        print("\n🎯 ROOT CAUSE: OptimizedVitalGraph breaks complex queries with JOINs")
        print("   Solution: Use standard Graph for complex queries, OptimizedVitalGraph for simple text search")
    elif len(standard_complex_results) == 0 and len(opt_complex_results) == 0:
        print("\n❌ Both graphs fail - there's a deeper SPARQL-to-SQL translation issue")
    elif len(opt_complex_results) > 0:
        print("\n✅ OptimizedVitalGraph works correctly for complex queries")
    
    store.close()

if __name__ == "__main__":
    test_wordnet_with_both_graphs()
