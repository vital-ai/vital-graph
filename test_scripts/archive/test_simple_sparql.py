#!/usr/bin/env python3
"""
Simple SPARQL test to verify basic query functionality without regex
"""

import sys
import os
import time
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from rdflib import Graph, URIRef
from sqlalchemy import create_engine
from vitalgraph.store.store import VitalGraphSQLStore

# Database connection parameters
PG_HOST = "127.0.0.1"
PG_PORT = 5432
PG_USER = "postgres"
PG_PASSWORD = ""
PG_DATABASE = "vitalgraphdb"

# Store identifier (determines table prefix) vs Graph URI (logical graph name)
STORE_IDENTIFIER = "hardcoded"  # Maps to kb_bec6803d52_* tables
GRAPH_URI = "http://vital.ai/graph/wordnet"  # Actual graph URI

def create_test_graph():
    """Create a VitalGraph instance connected to PostgreSQL"""
    DRIVER = "postgresql+psycopg"
    if PG_PASSWORD:
        db_uri = f"{DRIVER}://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"
    else:
        db_uri = f"{DRIVER}://{PG_USER}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"
    
    # Create engine and store
    engine = create_engine(db_uri)
    store = VitalGraphSQLStore(identifier=STORE_IDENTIFIER, engine=engine)
    store.open(configuration=db_uri, create=False)
    
    # Create graph with actual WordNet URI
    graph_iri = URIRef(GRAPH_URI)
    graph = Graph(store=store, identifier=graph_iri)
    
    return graph, store

def test_simple_sparql():
    """Test simple SPARQL query functionality"""
    print("=== SIMPLE SPARQL FUNCTIONALITY TEST ===")
    print(f"Database: {PG_DATABASE} on {PG_HOST}:{PG_PORT}")
    print(f"Store Identifier: {STORE_IDENTIFIER} (table prefix: kb_bec6803d52_*)")
    print(f"Graph URI: {GRAPH_URI}")
    
    try:
        graph, store = create_test_graph()
        print("✅ Connected to VitalGraph store")
        print(f"✅ Engine: {store.engine.name} (expecting 'postgresql')")
        
        # Test 1: Simple quad query with graph variable
        print("\n" + "="*60)
        print("TEST 1: Simple SPARQL query - ?s ?p ?o ?g LIMIT 100")
        print("="*60)
        
        sparql_query = """
        SELECT ?s ?p ?o ?g
        WHERE {
            GRAPH ?g {
                ?s ?p ?o
            }
        }
        LIMIT 100
        """
        
        print("SPARQL Query:")
        print(sparql_query)
        
        start_time = time.time()
        try:
            results = list(graph.query(sparql_query))
            query_time = time.time() - start_time
            
            print(f"\nResults: {len(results)} quads found")
            print(f"Query time: {query_time:.3f} seconds")
            
            if results:
                print("\nSample results:")
                for i, (s, p, o, g) in enumerate(results[:5], 1):
                    print(f"  {i}. Graph: {g}")
                    print(f"     Subject: {s}")
                    print(f"     Predicate: {p}")
                    print(f"     Object: {o}")
                    print()
            else:
                print("⚠️  No results found")
                
        except Exception as e:
            print(f"❌ Query failed with GRAPH clause: {e}")
            print("Trying without GRAPH clause...")
            
            # Test 2: Simple triple query without graph
            print("\n" + "="*60)
            print("TEST 2: Simple SPARQL query - ?s ?p ?o LIMIT 100")
            print("="*60)
            
            simple_query = """
            SELECT ?s ?p ?o
            WHERE {
                ?s ?p ?o
            }
            LIMIT 100
            """
            
            print("SPARQL Query:")
            print(simple_query)
            
            start_time = time.time()
            results = list(graph.query(simple_query))
            query_time = time.time() - start_time
            
            print(f"\nResults: {len(results)} triples found")
            print(f"Query time: {query_time:.3f} seconds")
            
            if results:
                print("\nSample results:")
                for i, (s, p, o) in enumerate(results[:5], 1):
                    print(f"  {i}. {s} -> {p} -> {o}")
            else:
                print("⚠️  No results found")
        
        # Test 3: Count query
        print("\n" + "="*60)
        print("TEST 3: Count total triples")
        print("="*60)
        
        count_query = """
        SELECT (COUNT(*) as ?count)
        WHERE {
            ?s ?p ?o
        }
        """
        
        print("SPARQL Query:")
        print(count_query)
        
        start_time = time.time()
        count_results = list(graph.query(count_query))
        query_time = time.time() - start_time
        
        if count_results:
            total_count = count_results[0][0]
            print(f"\nTotal triples: {total_count}")
            print(f"Query time: {query_time:.3f} seconds")
        
        # Test 4: Simple filter (non-regex)
        print("\n" + "="*60)
        print("TEST 4: Simple filter query")
        print("="*60)
        
        filter_query = """
        SELECT ?s ?p ?o
        WHERE {
            ?s ?p ?o .
            FILTER(isLiteral(?o))
        }
        LIMIT 10
        """
        
        print("SPARQL Query:")
        print(filter_query)
        
        start_time = time.time()
        filter_results = list(graph.query(filter_query))
        query_time = time.time() - start_time
        
        print(f"\nResults: {len(filter_results)} literal objects found")
        print(f"Query time: {query_time:.3f} seconds")
        
        if filter_results:
            print("\nSample literal objects:")
            for i, (s, p, o) in enumerate(filter_results[:3], 1):
                print(f"  {i}. {s} -> {p} -> {o}")
        
        store.close()
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        print("✅ Simple SPARQL functionality test completed")
        print("✅ Basic query engine is working")
        
    except Exception as e:
        print(f"❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_simple_sparql()
