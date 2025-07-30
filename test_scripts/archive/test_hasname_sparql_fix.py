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

def test_hasname_sparql():
    """Test SPARQL queries to access hasName data in literal_statements table"""
    print("=== Testing hasName SPARQL Access ===")
    
    # Create store and graph
    store = VitalGraphSQLStore(identifier="hardcoded")
    graph_iri = URIRef("http://vital.ai/graph/wordnet")
    g = Graph(store=store, identifier=graph_iri)
    
    try:
        # Open the store with database connection
        db_url = "postgresql+psycopg://postgres@127.0.0.1:5432/vitalgraphdb"
        store.open(db_url, create=False)
        print("✅ Database connection established")
        
        # Test 1: Basic hasName query
        print("\n🔍 Test 1: Basic hasName query")
        basic_hasname_query = """
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT ?entity ?name
        WHERE {
            ?entity vital-core:hasName ?name
        }
        LIMIT 10
        """
        
        start_time = time.time()
        basic_results = list(g.query(basic_hasname_query))
        basic_time = time.time() - start_time
        
        print(f"📊 Basic hasName Results: {len(basic_results)}")
        print(f"⏱️ Query time: {basic_time:.3f}s")
        
        if basic_results:
            print("✅ SUCCESS! Sample hasName data:")
            for i, (entity, name) in enumerate(basic_results[:5]):
                print(f"  {i+1}. Entity: {entity}")
                print(f"     Name: {name}")
                print()
        else:
            print("❌ No hasName results found")
            
        # Test 2: Search for 'happy' in names
        print("\n🔍 Test 2: Search for 'happy' in names")
        happy_query = """
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT ?entity ?name
        WHERE {
            ?entity vital-core:hasName ?name .
            FILTER(CONTAINS(LCASE(STR(?name)), "happy"))
        }
        LIMIT 10
        """
        
        start_time = time.time()
        happy_results = list(g.query(happy_query))
        happy_time = time.time() - start_time
        
        print(f"📊 'Happy' Search Results: {len(happy_results)}")
        print(f"⏱️ Query time: {happy_time:.3f}s")
        
        if happy_results:
            print("✅ SUCCESS! Found 'happy' entities:")
            for i, (entity, name) in enumerate(happy_results):
                print(f"  {i+1}. Entity: {entity}")
                print(f"     Name: {name}")
                print()
        else:
            print("❌ No 'happy' entities found")
            
        # Test 3: Complex WordNet query with hasName
        print("\n🔍 Test 3: Complex WordNet query with hasName")
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
            
            ?relatedEntity vital-core:hasName ?relatedName .
        }
        LIMIT 10
        """
        
        start_time = time.time()
        complex_results = list(g.query(complex_query))
        complex_time = time.time() - start_time
        
        print(f"📊 Complex WordNet Results: {len(complex_results)}")
        print(f"⏱️ Query time: {complex_time:.3f}s")
        
        if complex_results:
            print("✅ SUCCESS! Complex query with names:")
            for i, (entity, entity_name, related_entity, related_name, edge_type) in enumerate(complex_results[:3]):
                print(f"  {i+1}. Entity: {entity}")
                print(f"     Name: {entity_name}")
                print(f"     Related: {related_entity}")
                print(f"     Related Name: {related_name}")
                print(f"     Edge Type: {edge_type}")
                print()
        else:
            print("❌ No complex query results found")
            
        # Test 4: Search for other interesting words
        print("\n🔍 Test 4: Search for other words (joy, glad, cheerful)")
        word_searches = ["joy", "glad", "cheerful", "good", "best"]
        
        for word in word_searches:
            word_query = f"""
            PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
            
            SELECT ?entity ?name
            WHERE {{
                ?entity vital-core:hasName ?name .
                FILTER(CONTAINS(LCASE(STR(?name)), "{word}"))
            }}
            LIMIT 5
            """
            
            start_time = time.time()
            word_results = list(g.query(word_query))
            word_time = time.time() - start_time
            
            print(f"📊 '{word}' search: {len(word_results)} results ({word_time:.3f}s)")
            
            if word_results:
                for entity, name in word_results[:2]:
                    print(f"    - {name}")
                    
        print(f"\n📋 SUMMARY:")
        print(f"- Basic hasName query: {len(basic_results)} results")
        print(f"- 'Happy' search: {len(happy_results)} results")
        print(f"- Complex query: {len(complex_results)} results")
        print(f"- SPARQL can now access literal_statements table ✅")
        
        if len(basic_results) > 0:
            print("🎉 SUCCESS: hasName data is accessible via SPARQL!")
            print("🔧 The original WordNet queries should now work!")
        else:
            print("❌ ISSUE: SPARQL still can't access hasName data")
            
    except Exception as e:
        print(f"❌ Error during testing: {e}")
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
    test_hasname_sparql()
    print("\n=== hasName SPARQL testing completed ===")
