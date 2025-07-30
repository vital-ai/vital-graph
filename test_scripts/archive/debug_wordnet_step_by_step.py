#!/usr/bin/env python3
"""
Debug the WordNet complex query step by step to identify exactly where it fails.
We know the SQL JOIN works and returns 10 results, so the issue is in SPARQL translation.
"""

import sys
import os
import time
import logging

# Add the parent directory to sys.path to import vitalgraph
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from vitalgraph.store.store import VitalGraphSQLStore
from rdflib import Graph, URIRef

# Enable detailed logging
logging.basicConfig(level=logging.INFO)

def debug_wordnet_step_by_step():
    """Debug WordNet query by testing each component individually"""
    
    print("=== Debugging WordNet Query Step by Step ===")
    
    store = VitalGraphSQLStore(identifier="hardcoded")
    store.open("postgresql+psycopg://postgres@127.0.0.1:5432/vitalgraphdb", create=False)
    
    graph_iri = URIRef("http://vital.ai/graph/wordnet")
    g = Graph(store=store, identifier=graph_iri)
    
    # Step 1: Test the text search component
    print("\n🔍 Step 1: Test CONTAINS text search")
    step1_query = """
    PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
    PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
    
    SELECT ?entity ?entityName WHERE {
      ?entity a haley-ai-kg:KGEntity .
      ?entity vital-core:hasName ?entityName .
      FILTER(CONTAINS(LCASE(STR(?entityName)), "happy"))
    }
    LIMIT 5
    """
    
    start_time = time.time()
    step1_results = list(g.query(step1_query))
    duration = time.time() - start_time
    
    print(f"✅ Step 1: {len(step1_results)} results in {duration:.3f}s")
    if len(step1_results) > 0:
        print("   Sample results:")
        for result in step1_results[:3]:
            print(f"     - {result[0]}: {result[1]}")
        
        # Use first entity for next steps
        test_entity = step1_results[0][0]
        test_entity_name = step1_results[0][1]
        print(f"   Using test entity: {test_entity}")
    else:
        print("❌ Step 1 failed - no entities with 'happy' found")
        store.close()
        return
    
    # Step 2: Test edge source relationships
    print(f"\n🔍 Step 2: Find edges where {test_entity} is the source")
    step2_query = f"""
    PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
    
    SELECT ?edge WHERE {{
      ?edge vital-core:vital__hasEdgeSource <{test_entity}> .
    }}
    LIMIT 5
    """
    
    start_time = time.time()
    step2_results = list(g.query(step2_query))
    duration = time.time() - start_time
    
    print(f"✅ Step 2: {len(step2_results)} edges in {duration:.3f}s")
    if len(step2_results) > 0:
        print("   Sample edges:")
        for result in step2_results[:3]:
            print(f"     - Edge: {result[0]}")
        
        test_edge = step2_results[0][0]
        print(f"   Using test edge: {test_edge}")
    else:
        print("❌ Step 2 failed - no edges found from test entity")
        store.close()
        return
    
    # Step 3: Test edge destination relationships
    print(f"\n🔍 Step 3: Find destination of edge {test_edge}")
    step3_query = f"""
    PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
    
    SELECT ?connectedEntity WHERE {{
      <{test_edge}> vital-core:vital__hasEdgeDestination ?connectedEntity .
    }}
    """
    
    start_time = time.time()
    step3_results = list(g.query(step3_query))
    duration = time.time() - start_time
    
    print(f"✅ Step 3: {len(step3_results)} destinations in {duration:.3f}s")
    if len(step3_results) > 0:
        print("   Sample destinations:")
        for result in step3_results:
            print(f"     - Connected Entity: {result[0]}")
        
        test_connected_entity = step3_results[0][0]
        print(f"   Using test connected entity: {test_connected_entity}")
    else:
        print("❌ Step 3 failed - no destinations found for test edge")
        store.close()
        return
    
    # Step 4: Test connected entity name
    print(f"\n🔍 Step 4: Find name of connected entity {test_connected_entity}")
    step4_query = f"""
    PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
    
    SELECT ?connectedName WHERE {{
      <{test_connected_entity}> vital-core:hasName ?connectedName .
    }}
    """
    
    start_time = time.time()
    step4_results = list(g.query(step4_query))
    duration = time.time() - start_time
    
    print(f"✅ Step 4: {len(step4_results)} names in {duration:.3f}s")
    if len(step4_results) > 0:
        print("   Connected entity names:")
        for result in step4_results:
            print(f"     - Name: {result[0]}")
        
        test_connected_name = step4_results[0][0]
    else:
        print("❌ Step 4 failed - no name found for connected entity")
        store.close()
        return
    
    # Step 5: Test partial JOIN (entity + edge source)
    print(f"\n🔍 Step 5: Test partial JOIN (entity + edge source)")
    step5_query = """
    PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
    PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
    
    SELECT ?entity ?entityName ?edge WHERE {
      ?entity a haley-ai-kg:KGEntity .
      ?entity vital-core:hasName ?entityName .
      FILTER(CONTAINS(LCASE(STR(?entityName)), "happy"))
      
      ?edge vital-core:vital__hasEdgeSource ?entity .
    }
    LIMIT 5
    """
    
    start_time = time.time()
    step5_results = list(g.query(step5_query))
    duration = time.time() - start_time
    
    print(f"✅ Step 5: {len(step5_results)} partial JOIN results in {duration:.3f}s")
    if len(step5_results) > 0:
        print("   Sample partial JOIN results:")
        for result in step5_results[:3]:
            print(f"     - Entity: {result[0]}")
            print(f"       Name: {result[1]}")
            print(f"       Edge: {result[2]}")
    else:
        print("❌ Step 5 failed - partial JOIN returns no results")
        print("   This indicates the issue is in the JOIN logic")
    
    # Step 6: Test full JOIN
    print(f"\n🔍 Step 6: Test full WordNet JOIN")
    full_query = """
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
    LIMIT 5
    """
    
    start_time = time.time()
    full_results = list(g.query(full_query))
    duration = time.time() - start_time
    
    print(f"✅ Step 6: {len(full_results)} full JOIN results in {duration:.3f}s")
    if len(full_results) > 0:
        print("🎉 SUCCESS: Full WordNet query is working!")
        for result in full_results[:3]:
            print(f"   - Entity: {result[0]}")
            print(f"     Name: {result[1]}")
            print(f"     Connected: {result[4]}")
    else:
        print("❌ Step 6 failed - full JOIN returns no results")
        print("   The issue is in the complex multi-table JOIN logic")
    
    # Analysis
    print(f"\n📊 ANALYSIS:")
    print(f"- Step 1 (text search): {len(step1_results)} results")
    print(f"- Step 2 (edge source): {len(step2_results)} results")
    print(f"- Step 3 (edge destination): {len(step3_results)} results")
    print(f"- Step 4 (connected name): {len(step4_results)} results")
    print(f"- Step 5 (partial JOIN): {len(step5_results)} results")
    print(f"- Step 6 (full JOIN): {len(full_results)} results")
    
    if len(step5_results) == 0:
        print("\n🎯 ROOT CAUSE: The issue is in the entity + edge source JOIN")
        print("   The SPARQL engine is not correctly joining entities with their outgoing edges")
    elif len(full_results) == 0:
        print("\n🎯 ROOT CAUSE: The issue is in the full multi-table JOIN")
        print("   Individual components work, but the complex JOIN fails")
    else:
        print("\n✅ All components work - WordNet query should be fixed!")
    
    store.close()

if __name__ == "__main__":
    debug_wordnet_step_by_step()
