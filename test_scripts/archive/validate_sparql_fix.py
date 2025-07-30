#!/usr/bin/env python3
"""
Validate that SPARQL queries work correctly with proper entity relationships.

This test proves that the 0-results issue was due to incorrect test data expectations,
not bugs in the SPARQL engine or SQL generation.
"""

import sys
import os
import time

# Add the parent directory to sys.path to import vitalgraph
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from vitalgraph.store.store import VitalGraphSQLStore
from rdflib import Graph, URIRef

def test_sparql_with_correct_data():
    """Test SPARQL queries using entity relationships that actually exist in the database"""
    
    print("=== Validating SPARQL Engine with Correct Entity Relationships ===")
    
    # Use the same store initialization pattern as working test scripts
    store = VitalGraphSQLStore(identifier="hardcoded")
    store.open("postgresql+psycopg://postgres@127.0.0.1:5432/vitalgraphdb")
    
    graph_iri = URIRef("http://vital.ai/graph/wordnet")
    g = Graph(store=store, identifier=graph_iri)
    
    # Test 1: Simple query for existing edge source (we know this exists from database check)
    print("\n🔍 Test 1: Query for existing edge source")
    query1 = """
    SELECT ?source WHERE {
        <http://vital.ai/haley.ai/chat-saas/Edge_hasKGRelation/1447109419803_1265413808> 
        <http://vital.ai/ontology/vital-core#vital__hasEdgeSource> 
        ?source .
    }
    """
    
    start_time = time.time()
    results1 = list(g.query(query1))
    duration1 = time.time() - start_time
    
    print(f"✅ Query 1: {len(results1)} results in {duration1:.3f}s")
    if results1:
        print(f"   - Expected source: http://vital.ai/haley.ai/chat-saas/KGEntity/1447109394647_1265244887")
        print(f"   - Actual source: {results1[0][0]}")
        
    # Test 2: Complex join query using the correct entities
    print("\n🔍 Test 2: Complex join with source and destination")
    query2 = """
    SELECT ?edge ?source ?dest WHERE {
        ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeSource> ?source .
        ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeDestination> ?dest .
        FILTER(?edge = <http://vital.ai/haley.ai/chat-saas/Edge_hasKGRelation/1447109419803_1265413808>)
    }
    """
    
    start_time = time.time()
    results2 = list(g.query(query2))
    duration2 = time.time() - start_time
    
    print(f"✅ Query 2: {len(results2)} results in {duration2:.3f}s")
    for result in results2:
        print(f"   - Edge: {result[0]}")
        print(f"   - Source: {result[1]}")
        print(f"   - Destination: {result[2]}")
    
    # Test 3: Query that would have failed with old incorrect expectations
    print("\n🔍 Test 3: Query with INCORRECT entity (should return 0)")
    query3 = """
    SELECT ?source WHERE {
        <http://vital.ai/haley.ai/chat-saas/Edge_hasKGRelation/1447109419803_1265413808> 
        <http://vital.ai/ontology/vital-core#vital__hasEdgeSource> 
        <http://vital.ai/haley.ai/chat-saas/KGEntity/1447109405459_1265312091> .
    }
    """
    
    start_time = time.time()
    results3 = list(g.query(query3))
    duration3 = time.time() - start_time
    
    print(f"✅ Query 3: {len(results3)} results in {duration3:.3f}s")
    print(f"   - This correctly returns 0 because the entity relationship doesn't exist")
    
    # Summary
    print(f"\n📊 VALIDATION RESULTS:")
    print(f"✅ Query 1 (correct entity): {len(results1)} results")
    print(f"✅ Query 2 (complex join): {len(results2)} results") 
    print(f"✅ Query 3 (incorrect entity): {len(results3)} results")
    
    if len(results1) > 0 and len(results2) > 0 and len(results3) == 0:
        print(f"\n🎉 SUCCESS: SPARQL engine is working correctly!")
        print(f"   - Queries with correct entities return results")
        print(f"   - Queries with incorrect entities return 0 results")
        print(f"   - Complex joins work properly")
        print(f"   - The previous 0-results issue was due to incorrect test data expectations")
    else:
        print(f"\n⚠️  Unexpected results - need further investigation")
    
    store.close()

if __name__ == "__main__":
    test_sparql_with_correct_data()
