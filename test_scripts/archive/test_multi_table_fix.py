#!/usr/bin/env python3

import logging
import time
from rdflib import Graph, URIRef
from vitalgraph.store.store import VitalGraphSQLStore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def test_multi_table_fix():
    """Test if disabling aggressive single-table optimization fixes complex queries"""
    print("=== Testing Multi-Table Fix ===")
    
    # Create store and graph
    store = VitalGraphSQLStore(identifier="hardcoded")
    graph_iri = URIRef("http://vital.ai/graph/wordnet")
    g = Graph(store=store, identifier=graph_iri)
    
    try:
        # Open the store with database connection
        db_url = "postgresql+psycopg://postgres@127.0.0.1:5432/vitalgraphdb"
        store.open(db_url, create=False)
        print("✅ Database connection established")
        
        # Test the complex query that was failing before
        print("\n🔍 Testing complex WordNet query")
        complex_query = """
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        
        SELECT ?entity ?entityName ?relatedEntity ?relatedName ?edgeType
        WHERE {
            ?entity a haley-ai-kg:KGEntity .
            ?entity vital-core:hasName ?entityName .
            
            ?edge vital-core:vital__hasEdgeSource ?entity .
            ?edge vital-core:vital__hasEdgeDestination ?relatedEntity .
            ?edge haley-ai-kg:vital__hasKGRelationType ?edgeType .
            
            ?relatedEntity a haley-ai-kg:KGEntity .
            ?relatedEntity vital-core:hasName ?relatedName
        }
        LIMIT 5
        """
        
        start_time = time.time()
        results = list(g.query(complex_query))
        query_time = time.time() - start_time
        
        print(f"📊 Complex query results: {len(results)} results ({query_time:.3f}s)")
        
        if results:
            print("✅ SUCCESS! Complex query now works!")
            for i, (entity, entity_name, related_entity, related_name, edge_type) in enumerate(results[:3]):
                print(f"  {i+1}. Entity: {entity}")
                print(f"     Name: {entity_name}")
                print(f"     Related: {related_entity}")
                print(f"     Related Name: {related_name}")
                print(f"     Edge Type: {edge_type}")
                print()
        else:
            print("❌ Complex query still returns 0 results")
            
        # Test a simple query to make sure we didn't break anything
        print("\n🔍 Testing simple query (should still work)")
        simple_query = """
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        
        SELECT ?entity ?name
        WHERE {
            ?entity a haley-ai-kg:KGEntity .
            ?entity vital-core:hasName ?name
        }
        LIMIT 3
        """
        
        start_time = time.time()
        simple_results = list(g.query(simple_query))
        simple_time = time.time() - start_time
        
        print(f"📊 Simple query results: {len(simple_results)} results ({simple_time:.3f}s)")
        
        if simple_results:
            print("✅ Simple query still works")
        else:
            print("❌ Simple query broken")
            
        print(f"\n📋 SUMMARY:")
        if len(results) > 0:
            print("✅ FIX SUCCESSFUL: Complex multi-table joins now work!")
            print("🎯 Root cause was aggressive single-table optimization bypassing multi-table join logic")
        else:
            print("❌ Fix not sufficient - need further investigation")
            
    except Exception as e:
        print(f"❌ Error during test: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # Clean up
        try:
            store.close()
            print("🔒 Database connection closed")
        except:
            pass

if __name__ == "__main__":
    test_multi_table_fix()
    print("\n=== Multi-table fix test completed ===")
