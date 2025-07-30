#!/usr/bin/env python3
"""
Diagnose edge data access issues
"""

import os
import sys
from sqlalchemy import URL, create_engine, text
from rdflib import Graph, URIRef

# Add the parent directory to the path so we can import vitalgraph
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from vitalgraph.store.store import VitalGraphSQLStore

# Database connection parameters
PG_HOST     = "127.0.0.1"
PG_PORT     = 5432
PG_USER     = "postgres"
PG_PASSWORD = ""
PG_DATABASE = "vitalgraphdb"

def main():
    print("Diagnosing edge data access issues")
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
    
    # Step 1: Direct SQL check for edge data
    print("Step 1: Direct SQL check for edge data in kb_bec6803d52_* tables")
    engine = create_engine(db_url)
    
    with engine.connect() as conn:
        # Check for edge-related predicates
        edge_predicates = [
            'http://vital.ai/ontology/vital-core#vital__hasEdgeSource',
            'http://vital.ai/ontology/vital-core#vital__hasEdgeDestination'
        ]
        
        for pred in edge_predicates:
            for table in ['asserted_statements', 'literal_statements', 'type_statements']:
                table_name = f'kb_bec6803d52_{table}'
                try:
                    result = conn.execute(text(f"""
                        SELECT COUNT(*) FROM {table_name} 
                        WHERE predicate = :pred
                    """), {"pred": pred})
                    count = result.scalar()
                    if count > 0:
                        print(f"  ✓ {table_name}: {count:,} triples with {pred}")
                        
                        # Get sample data
                        sample = conn.execute(text(f"""
                            SELECT subject, object FROM {table_name} 
                            WHERE predicate = :pred LIMIT 3
                        """), {"pred": pred})
                        for row in sample:
                            print(f"    Sample: {row.subject} -> {row.object}")
                    else:
                        print(f"    {table_name}: 0 triples with {pred}")
                except Exception as e:
                    print(f"    {table_name}: Error - {e}")
    
    # Step 2: Check what contexts these edge triples are in
    print(f"\nStep 2: Check contexts for edge triples")
    with engine.connect() as conn:
        for pred in edge_predicates:
            try:
                result = conn.execute(text(f"""
                    SELECT DISTINCT context, COUNT(*) as count
                    FROM kb_bec6803d52_asserted_statements 
                    WHERE predicate = :pred
                    GROUP BY context
                """), {"pred": pred})
                
                print(f"  Contexts for {pred}:")
                for row in result:
                    print(f"    {row.context}: {row.count:,} triples")
            except Exception as e:
                print(f"  Error checking contexts for {pred}: {e}")
    
    # Step 3: Test SPARQL queries with different contexts
    print(f"\nStep 3: Test SPARQL edge queries with different contexts")
    
    store = VitalGraphSQLStore()  # "hardcoded" identifier
    store.open(db_url)
    
    # Test different graph contexts
    contexts_to_test = [
        "http://vital.ai/graph/wordnet",
        "http://example.org/test_graph1",
        "hardcoded"
    ]
    
    for context in contexts_to_test:
        print(f"\n  Testing context: {context}")
        
        if context == "hardcoded":
            g = Graph(store=store, identifier=context)
        else:
            g = Graph(store=store, identifier=URIRef(context))
        
        # Simple edge query
        edge_query = """
        SELECT ?edge ?source ?dest WHERE {
          ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeSource> ?source .
          ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeDestination> ?dest .
        }
        LIMIT 3
        """
        
        try:
            results = list(g.query(edge_query))
            print(f"    SPARQL edge results: {len(results)}")
            for i, row in enumerate(results):
                print(f"      {i+1}: {row.edge} connects {row.source} -> {row.dest}")
        except Exception as e:
            print(f"    SPARQL error: {e}")
    
    # Step 4: Test direct store triples() call for edge predicates
    print(f"\nStep 4: Test direct store.triples() for edge predicates")
    
    for pred in edge_predicates:
        pred_uri = URIRef(pred)
        try:
            edge_triples = list(store.triples((None, pred_uri, None)))
            print(f"  store.triples() for {pred}: {len(edge_triples)} results")
            
            for i, triple in enumerate(edge_triples[:3]):
                print(f"    {i+1}: {triple[0]} {triple[1]} {triple[2]}")
                
        except Exception as e:
            print(f"  store.triples() error for {pred}: {e}")

if __name__ == "__main__":
    main()
