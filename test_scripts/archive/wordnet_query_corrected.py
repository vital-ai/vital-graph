#!/usr/bin/env python3
"""
Corrected WordNet query script that uses the actual data location
"""

import os
import sys
import time
from sqlalchemy import URL

# Add the parent directory to the path so we can import vitalgraph
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from vitalgraph.store.store import VitalGraphSQLStore
from vitalgraph.optimized_graph import OptimizedVitalGraph
from rdflib import URIRef

# Database connection parameters
PG_HOST     = "127.0.0.1"
PG_PORT     = 5432
PG_USER     = "postgres"
PG_PASSWORD = ""
PG_DATABASE = "vitalgraphdb"
GRAPH_NAME = "wordnet"

class CorrectedVitalGraphSQLStore(VitalGraphSQLStore):
    """Store that uses the correct interned ID where WordNet data actually exists"""
    
    def __init__(self, identifier, configuration):
        # Initialize normally first
        super().__init__(identifier, configuration)
        
        # Override the interned ID to point to the correct tables
        self._interned_id = "kb_bec6803d52"
        
        # Recreate table definitions with the correct interned ID
        try:
            self.tables = self._create_table_definitions()
            print(f"Successfully created table definitions for {self._interned_id}")
        except Exception as e:
            print(f"Error creating table definitions: {e}")
            # Fallback to original tables if there's an issue
            self._interned_id = "kb_5e9e5feadf"
            self.tables = self._create_table_definitions()

def main():
    print("WordNet Query Test - Corrected Version")
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
    
    # Create corrected store and graph
    graph_iri = URIRef(f"http://vital.ai/graph/{GRAPH_NAME}")
    store = CorrectedVitalGraphSQLStore(identifier=graph_iri, configuration=db_url)
    g = OptimizedVitalGraph(store=store, identifier=graph_iri)
    
    print(f"Connected to WordNet graph in PostgreSQL at {db_url}")
    print(f"Using corrected interned ID: {store._interned_id}")
    
    # Check total triples
    total_triples = len(g)
    print(f"Total triples in WordNet graph: {total_triples:,}")
    
    print("\n" + "=" * 50)
    
    # Test 1: Text search for entities with 'happy' in names
    print("Test 1A: Finding entities with 'happy' in names")
    
    simple_happy_query = """
    SELECT ?entity ?entityName WHERE {
      ?entity <http://vital.ai/ontology/vital-core#hasName> ?entityName .
      FILTER(CONTAINS(LCASE(STR(?entityName)), "happy"))
    }
    LIMIT 5
    """
    
    start_time = time.time()
    try:
        results = list(g.query(simple_happy_query))
        elapsed = time.time() - start_time
        
        print(f"✓ Found {len(results)} entities with 'happy' in names")
        entities_found = []
        for i, row in enumerate(results):
            entity_name = row.get('entityName', 'N/A')
            entity_uri = row.get('entity', 'N/A')
            print(f"  Found: {entity_name}")
            print(f"  URI: {entity_uri}")
            entities_found.append(entity_uri)
        print(f"Query time: {elapsed:.3f} seconds")
        
    except Exception as e:
        print(f"✗ Error in text search: {e}")
        return
    
    # Test 1B: Edge traversal for the first entity found
    if entities_found:
        first_entity = entities_found[0]
        print(f"\nTest 1B: Checking for edges from the first entity")
        print(f"Checking edges for: {first_entity}")
        
        edge_query = f"""
        SELECT ?edge ?destination ?destName WHERE {{
          ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeSource> <{first_entity}> .
          ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeDestination> ?destination .
          OPTIONAL {{ ?destination <http://vital.ai/ontology/vital-core#hasName> ?destName . }}
        }}
        LIMIT 10
        """
        
        start_time = time.time()
        try:
            edge_results = list(g.query(edge_query))
            elapsed = time.time() - start_time
            
            if edge_results:
                print(f"✓ Found {len(edge_results)} edges for this entity:")
                for i, row in enumerate(edge_results):
                    edge = row.get('edge', 'N/A')
                    dest = row.get('destination', 'N/A')
                    dest_name = row.get('destName', 'No name')
                    print(f"  Edge {i+1}: {edge}")
                    print(f"    -> {dest}")
                    print(f"    Name: {dest_name}")
            else:
                print("✗ No edges found for this entity")
                
            print(f"Query time: {elapsed:.3f} seconds")
            
        except Exception as e:
            print(f"✗ Error in edge query: {e}")
    
    # Test 2: General edge verification
    print(f"\nTest 2: General edge verification (any edges in database)")
    
    general_edge_query = """
    SELECT ?edge ?source ?dest WHERE {
      ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeSource> ?source .
      ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeDestination> ?dest .
    }
    LIMIT 5
    """
    
    start_time = time.time()
    try:
        edge_results = list(g.query(general_edge_query))
        elapsed = time.time() - start_time
        
        if edge_results:
            print(f"✓ Found {len(edge_results)} edges in database:")
            for i, row in enumerate(edge_results):
                print(f"  Edge {i+1}: {row.get('edge', 'N/A')}")
                print(f"    Source: {row.get('source', 'N/A')}")
                print(f"    Dest: {row.get('dest', 'N/A')}")
        else:
            print("✗ No edges found in database")
            
        print(f"Query time: {elapsed:.3f} seconds")
        
    except Exception as e:
        print(f"✗ Error in general edge query: {e}")
    
    # Test 3: Original complex query (edge traversal with text search)
    print(f"\nTest 3: Original complex query (edge traversal + text search)")
    
    complex_query = """
    SELECT ?entity ?entityName ?edge ?connectedEntity ?connectedName WHERE {
      ?entity <http://vital.ai/ontology/vital-core#hasName> ?entityName .
      FILTER(CONTAINS(LCASE(STR(?entityName)), "happy"))
      
      ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeSource> ?entity .
      ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeDestination> ?connectedEntity .
      
      OPTIONAL { ?connectedEntity <http://vital.ai/ontology/vital-core#hasName> ?connectedName . }
    }
    LIMIT 10
    """
    
    start_time = time.time()
    try:
        complex_results = list(g.query(complex_query))
        elapsed = time.time() - start_time
        
        if complex_results:
            print(f"✓ Found {len(complex_results)} connections for entities with 'happy' in their names:")
            for i, row in enumerate(complex_results):
                entity_name = row.get('entityName', 'N/A')
                connected_name = row.get('connectedName', 'No name')
                edge = row.get('edge', 'N/A')
                print(f"  Connection {i+1}: '{entity_name}' -> '{connected_name}'")
                print(f"    Via edge: {edge}")
        else:
            print("✗ No connections found for entities with 'happy' in their names")
            
        print(f"Query time: {elapsed:.3f} seconds")
        
    except Exception as e:
        print(f"✗ Error in complex query: {e}")
    
    print("\n" + "=" * 50)
    print("Corrected WordNet query test completed!")
    
    if 'edge_results' in locals() and edge_results:
        print("✅ SUCCESS: Edge traversal queries are now working!")
        print("   The issue was using the wrong graph identifier/table set.")
    else:
        print("❌ Edge queries still not working - further investigation needed.")

if __name__ == "__main__":
    main()
