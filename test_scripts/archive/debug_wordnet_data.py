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

def debug_wordnet_data():
    """Debug what data is actually available in the WordNet database"""
    print("=== Debugging WordNet Data Structure ===")
    
    # Create store and graph
    store = VitalGraphSQLStore(identifier="hardcoded")
    graph_iri = URIRef("http://vital.ai/graph/wordnet")
    g = Graph(store=store, identifier=graph_iri)
    
    try:
        # Open the store with database connection
        db_url = "postgresql+psycopg://postgres@127.0.0.1:5432/vitalgraphdb"
        store.open(db_url, create=False)
        print("✅ Database connection established")
        
        # Check total triple count
        print("\n🔍 Step 1: Check total data availability")
        total_count_query = """
        SELECT (COUNT(*) as ?count)
        WHERE {
            ?s ?p ?o
        }
        """
        
        start_time = time.time()
        count_results = list(g.query(total_count_query))
        count_time = time.time() - start_time
        
        if count_results:
            total_count = count_results[0][0]
            print(f"📊 Total triples in graph: {total_count}")
            print(f"⏱️ Query time: {count_time:.3f}s")
        else:
            print("❌ No count results - database may be empty")
            
        # Check what types of entities exist
        print("\n🔍 Step 2: Check available entity types")
        types_query = """
        SELECT DISTINCT ?type (COUNT(?s) as ?count)
        WHERE {
            ?s <http://vital.ai/ontology/vital-core#vitaltype> ?type
        }
        GROUP BY ?type
        ORDER BY DESC(?count)
        LIMIT 10
        """
        
        start_time = time.time()
        types_results = list(g.query(types_query))
        types_time = time.time() - start_time
        
        print(f"📊 Available entity types:")
        print(f"⏱️ Query time: {types_time:.3f}s")
        if types_results:
            for i, (entity_type, count) in enumerate(types_results):
                print(f"  {i+1}. {entity_type}: {count} entities")
        else:
            print("❌ No entity types found")
            
        # Check for KGEntity specifically
        print("\n🔍 Step 3: Check for KGEntity instances")
        kg_entity_query = """
        SELECT (COUNT(*) as ?count)
        WHERE {
            ?s a <http://vital.ai/ontology/haley-ai-kg#KGEntity>
        }
        """
        
        start_time = time.time()
        kg_results = list(g.query(kg_entity_query))
        kg_time = time.time() - start_time
        
        if kg_results:
            kg_count = kg_results[0][0]
            print(f"📊 KGEntity instances: {kg_count}")
            print(f"⏱️ Query time: {kg_time:.3f}s")
        else:
            print("❌ No KGEntity count results")
            
        # Check for entities with names
        print("\n🔍 Step 4: Check for entities with names")
        names_query = """
        SELECT (COUNT(*) as ?count)
        WHERE {
            ?s <http://vital.ai/ontology/vital-core#hasName> ?name
        }
        """
        
        start_time = time.time()
        names_results = list(g.query(names_query))
        names_time = time.time() - start_time
        
        if names_results:
            names_count = names_results[0][0]
            print(f"📊 Entities with names: {names_count}")
            print(f"⏱️ Query time: {names_time:.3f}s")
        else:
            print("❌ No entities with names found")
            
        # Sample some actual data
        print("\n🔍 Step 5: Sample actual data structure")
        sample_query = """
        SELECT ?s ?p ?o
        WHERE {
            ?s ?p ?o
        }
        LIMIT 20
        """
        
        start_time = time.time()
        sample_results = list(g.query(sample_query))
        sample_time = time.time() - start_time
        
        print(f"📊 Sample data (first 20 triples):")
        print(f"⏱️ Query time: {sample_time:.3f}s")
        if sample_results:
            for i, (s, p, o) in enumerate(sample_results):
                print(f"  {i+1}. S: {s}")
                print(f"     P: {p}")
                print(f"     O: {o}")
                print()
        else:
            print("❌ No sample data found")
            
        # Check for edges specifically
        print("\n🔍 Step 6: Check for edge relationships")
        edges_query = """
        SELECT (COUNT(*) as ?count)
        WHERE {
            ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeSource> ?source
        }
        """
        
        start_time = time.time()
        edges_results = list(g.query(edges_query))
        edges_time = time.time() - start_time
        
        if edges_results:
            edges_count = edges_results[0][0]
            print(f"📊 Edges with sources: {edges_count}")
            print(f"⏱️ Query time: {edges_time:.3f}s")
        else:
            print("❌ No edges found")
            
        # Check for any entities with 'happy' in their data
        print("\n🔍 Step 7: Search for 'happy' in any string values")
        happy_query = """
        SELECT ?s ?p ?o
        WHERE {
            ?s ?p ?o .
            FILTER(CONTAINS(LCASE(STR(?o)), "happy"))
        }
        LIMIT 10
        """
        
        start_time = time.time()
        happy_results = list(g.query(happy_query))
        happy_time = time.time() - start_time
        
        print(f"📊 Triples containing 'happy':")
        print(f"⏱️ Query time: {happy_time:.3f}s")
        if happy_results:
            for i, (s, p, o) in enumerate(happy_results):
                print(f"  {i+1}. S: {s}")
                print(f"     P: {p}")
                print(f"     O: {o}")
                print()
        else:
            print("❌ No triples containing 'happy' found")
            
        # Final diagnostic summary
        print(f"\n📋 DIAGNOSTIC SUMMARY:")
        print(f"- Total triples: {total_count if count_results else 'Unknown'}")
        print(f"- Entity types found: {len(types_results) if types_results else 0}")
        print(f"- KGEntity instances: {kg_count if kg_results else 'Unknown'}")
        print(f"- Entities with names: {names_count if names_results else 'Unknown'}")
        print(f"- Edges found: {edges_count if edges_results else 'Unknown'}")
        print(f"- 'Happy' matches: {len(happy_results) if happy_results else 0}")
        
        # Determine likely issues
        print(f"\n🔍 LIKELY ISSUES:")
        if not count_results or (count_results and count_results[0][0] == 0):
            print("❌ CRITICAL: Database appears to be empty")
        elif not kg_results or (kg_results and kg_results[0][0] == 0):
            print("❌ ISSUE: No KGEntity instances found - wrong entity type in query")
        elif not names_results or (names_results and names_results[0][0] == 0):
            print("❌ ISSUE: No entities with names found - wrong property URI in query")
        elif not edges_results or (edges_results and edges_results[0][0] == 0):
            print("❌ ISSUE: No edge relationships found - wrong edge structure in query")
        elif not happy_results:
            print("❌ ISSUE: No 'happy' entities found - test data may not contain expected values")
        else:
            print("✅ Data structure looks correct - query logic may need adjustment")
            
    except Exception as e:
        print(f"❌ Error during debugging: {e}")
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
    debug_wordnet_data()
    print("\n=== WordNet data debugging completed ===")
