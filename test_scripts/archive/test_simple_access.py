#!/usr/bin/env python3
"""
Simple test to verify VitalGraph can access WordNet data
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from rdflib import Graph, ConjunctiveGraph, URIRef
from sqlalchemy import create_engine
from vitalgraph.store.store import VitalGraphSQLStore

# Database connection parameters
PG_HOST = "127.0.0.1"
PG_PORT = 5432
PG_USER = "postgres"
PG_PASSWORD = ""
PG_DATABASE = "vitalgraphdb"

STORE_IDENTIFIER = "hardcoded"
GRAPH_URI = "http://vital.ai/graph/wordnet"

def test_simple_access():
    """Test simple data access approaches"""
    print("=== SIMPLE DATA ACCESS TEST ===")
    
    DRIVER = "postgresql+psycopg"
    if PG_PASSWORD:
        db_uri = f"{DRIVER}://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"
    else:
        db_uri = f"{DRIVER}://{PG_USER}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"
    
    try:
        # Create engine and store
        engine = create_engine(db_uri)
        store = VitalGraphSQLStore(identifier=STORE_IDENTIFIER, engine=engine)
        store.open(configuration=db_uri, create=False)
        
        print("✅ Connected to VitalGraph store")
        
        # Test 1: ConjunctiveGraph (all contexts)
        print("\n--- Test 1: ConjunctiveGraph (all contexts) ---")
        conjunctive_graph = ConjunctiveGraph(store=store)
        
        # Simple count query
        count_query = "SELECT (COUNT(*) as ?count) WHERE { ?s ?p ?o }"
        results = list(conjunctive_graph.query(count_query))
        if results:
            total_count = results[0][0]
            print(f"Total triples via ConjunctiveGraph: {total_count}")
        
        # Sample triples
        sample_query = "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 3"
        results = list(conjunctive_graph.query(sample_query))
        print(f"Sample triples: {len(results)}")
        for i, (s, p, o) in enumerate(results, 1):
            print(f"  {i}. {s} -> {p} -> {o}")
        
        # Test 2: Specific Graph context
        print("\n--- Test 2: Specific Graph context ---")
        graph_iri = URIRef(GRAPH_URI)
        specific_graph = Graph(store=store, identifier=graph_iri)
        
        # Count in specific graph
        results = list(specific_graph.query(count_query))
        if results:
            specific_count = results[0][0]
            print(f"Total triples in {GRAPH_URI}: {specific_count}")
        
        # Sample from specific graph
        results = list(specific_graph.query(sample_query))
        print(f"Sample triples from specific graph: {len(results)}")
        for i, (s, p, o) in enumerate(results, 1):
            print(f"  {i}. {s} -> {p} -> {o}")
        
        # Test 3: Direct store query
        print("\n--- Test 3: Direct store triples() method ---")
        direct_triples = list(store.triples((None, None, None), context=graph_iri))
        print(f"Direct triples from store: {len(direct_triples)}")
        for i, (s, p, o) in enumerate(direct_triples[:3], 1):
            print(f"  {i}. {s} -> {p} -> {o}")
        
        store.close()
        print("\n✅ Simple access test completed")
        
    except Exception as e:
        print(f"❌ Error during test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_simple_access()
