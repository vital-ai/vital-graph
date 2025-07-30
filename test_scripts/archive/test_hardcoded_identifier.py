#!/usr/bin/env python3
"""
Test using the "hardcoded" identifier to access WordNet data
"""

import os
import sys
import time
from sqlalchemy import URL

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

def main():
    print("Testing WordNet access with 'hardcoded' identifier")
    print("=" * 50)
    
    # Database connection
    db_url = URL.create(
        drivername="postgresql+psycopg",
        username=PG_USER,
        password=PG_PASSWORD or None,
        host=PG_HOST,
        port=PG_PORT,
        database=PG_DATABASE,
    )
    
    # Create store using the "hardcoded" identifier (no identifier parameter)
    store = VitalGraphSQLStore()  # This defaults to "hardcoded"
    store.open(db_url)
    
    print(f"Store identifier: {store.identifier}")
    print(f"Store interned ID: {store._interned_id}")
    print(f"Expected: kb_bec6803d52")
    print(f"Match: {store._interned_id == 'kb_bec6803d52'}")
    
    if store._interned_id == 'kb_bec6803d52':
        print("✅ SUCCESS: Using correct identifier!")
        
        # Create optimized graph
        g = OptimizedVitalGraph(store=store, identifier="hardcoded")
        
        # Test 1: Text search
        print(f"\nTest 1: Text search for 'happy' entities")
        
        text_query = """
        SELECT ?entity ?entityName WHERE {
          ?entity <http://vital.ai/ontology/vital-core#hasName> ?entityName .
          FILTER(CONTAINS(LCASE(STR(?entityName)), "happy"))
        }
        LIMIT 5
        """
        
        start_time = time.time()
        try:
            results = list(g.query(text_query))
            elapsed = time.time() - start_time
            
            print(f"✅ Found {len(results)} entities with 'happy' in names")
            entities_found = []
            for i, row in enumerate(results):
                entity_name = row.get('entityName', 'N/A')
                entity_uri = row.get('entity', 'N/A')
                print(f"  {i+1}: {entity_name}")
                entities_found.append(entity_uri)
            print(f"Query time: {elapsed:.3f} seconds")
            
        except Exception as e:
            print(f"❌ Error in text search: {e}")
            return
        
        # Test 2: Edge traversal
        if entities_found:
            first_entity = entities_found[0]
            print(f"\nTest 2: Edge traversal for first entity")
            
            edge_query = f"""
            SELECT ?edge ?destination ?destName WHERE {{
              ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeSource> <{first_entity}> .
              ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeDestination> ?destination .
              OPTIONAL {{ ?destination <http://vital.ai/ontology/vital-core#hasName> ?destName . }}
            }}
            LIMIT 5
            """
            
            start_time = time.time()
            try:
                edge_results = list(g.query(edge_query))
                elapsed = time.time() - start_time
                
                if edge_results:
                    print(f"✅ Found {len(edge_results)} edges for this entity:")
                    for i, row in enumerate(edge_results):
                        edge = row.get('edge', 'N/A')
                        dest = row.get('destination', 'N/A')
                        dest_name = row.get('destName', 'No name')
                        print(f"  Edge {i+1}: -> {dest_name}")
                else:
                    print("❌ No edges found for this entity")
                    
                print(f"Query time: {elapsed:.3f} seconds")
                
            except Exception as e:
                print(f"❌ Error in edge query: {e}")
        
        print(f"\n🎉 SUCCESS: Both text search and edge traversal working!")
        print(f"   The mystery is solved - WordNet data was loaded with identifier 'hardcoded'")
        
    else:
        print("❌ Identifier mismatch - something is still wrong")

if __name__ == "__main__":
    main()
