#!/usr/bin/env python3
"""
Fixed WordNet query script that uses the correct tables where data actually exists
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

class FixedVitalGraphSQLStore(VitalGraphSQLStore):
    """Custom store that uses the correct interned ID where WordNet data actually exists"""
    
    def __init__(self, identifier, configuration):
        # Initialize normally first
        super().__init__(identifier, configuration)
        
        # Override the interned ID to point to the correct tables
        self._interned_id = "kb_bec6803d52"
        
        # Recreate table definitions with the correct interned ID
        self.tables = self._create_table_definitions()
        
        print(f"Fixed store using interned ID: {self._interned_id}")
        for table_name, table_obj in self.tables.items():
            print(f"  {table_name}: {table_obj.name}")

def main():
    print("WordNet Query Test - Fixed Version")
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
    
    # Create fixed store and graph
    graph_iri = URIRef("http://vital.ai/graph/wordnet")  # Keep original identifier for compatibility
    store = FixedVitalGraphSQLStore(identifier=graph_iri, configuration=db_url)
    g = OptimizedVitalGraph(store=store, identifier=graph_iri)
    
    print(f"Connected to WordNet graph 'wordnet' in PostgreSQL at {db_url}")
    
    # Check total triples
    total_triples = len(g)
    print(f"Total triples in WordNet graph: {total_triples:,}")
    
    print("\n" + "=" * 50)
    
    # Test 1: Simple text search (should work with optimization)
    print("Test 1: Finding entities with 'happy' in names")
    
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
        for i, row in enumerate(results):
            entity_name = row.get('entityName', 'N/A')
            entity_uri = row.get('entity', 'N/A')
            print(f"  Found: {entity_name}")
            print(f"  URI: {entity_uri}")
            if i == 0:
                first_entity = entity_uri  # Save for edge test
        print(f"Query time: {elapsed:.3f} seconds")
        
    except Exception as e:
        print(f"✗ Error in text search: {e}")
        return
    
    # Test 2: Edge traversal query (the main issue we're fixing)
    print(f"\nTest 2: Finding edges for the first entity")
    
    if 'first_entity' in locals():
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
                print(f"✓ Found {len(edge_results)} edges for entity:")
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
    
    # Test 3: Direct edge verification
    print(f"\nTest 3: Direct edge verification (any edges in database)")
    
    direct_edge_query = """
    SELECT ?edge ?source ?dest WHERE {
      ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeSource> ?source .
      ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeDestination> ?dest .
    }
    LIMIT 5
    """
    
    start_time = time.time()
    try:
        direct_results = list(g.query(direct_edge_query))
        elapsed = time.time() - start_time
        
        if direct_results:
            print(f"✓ Found {len(direct_results)} edges in database:")
            for i, row in enumerate(direct_results):
                print(f"  Edge {i+1}: {row.get('edge', 'N/A')}")
                print(f"    Source: {row.get('source', 'N/A')}")
                print(f"    Dest: {row.get('dest', 'N/A')}")
        else:
            print("✗ No edges found in database at all")
            
        print(f"Query time: {elapsed:.3f} seconds")
        
    except Exception as e:
        print(f"✗ Error in direct edge query: {e}")
    
    print("\n" + "=" * 50)
    print("Fixed WordNet query test completed!")

if __name__ == "__main__":
    main()
