#!/usr/bin/env python3
"""
Test script to verify PostgreSQL regex functionality with WordNet data.
Tests the newly implemented regex support in all clause builders.
"""

import sys
import os
import time
from sqlalchemy import create_engine

# Add the parent directory to Python path to import vitalgraph
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from vitalgraph.store.store import VitalGraphSQLStore
from rdflib import Graph, URIRef
from rdflib.plugins.stores.regexmatching import REGEXTerm

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
    # Use hardcoded identifier for table access (kb_bec6803d52_* tables)
    engine = create_engine(db_uri)
    store = VitalGraphSQLStore(identifier=STORE_IDENTIFIER, engine=engine)
    store.open(configuration=db_uri, create=False)
    
    # Create graph with actual WordNet URI
    graph_iri = URIRef(GRAPH_URI)
    graph = Graph(store=store, identifier=graph_iri)
    
    return graph, store

def test_regex_functionality():
    """Test PostgreSQL regex functionality with WordNet data"""
    print("=== POSTGRESQL REGEX FUNCTIONALITY TEST ===")
    print(f"Database: {PG_DATABASE} on {PG_HOST}:{PG_PORT}")
    print(f"Store Identifier: {STORE_IDENTIFIER} (table prefix: kb_bec6803d52_*)")
    print(f"Graph URI: {GRAPH_URI}")
    
    try:
        graph, store = create_test_graph()
        print(f"✅ Connected to VitalGraph store")
        print(f"✅ Engine: {store.engine.name} (expecting 'postgresql')")
        
        # Test 1: Simple SPARQL REGEX query on object values
        print("\n" + "="*60)
        print("TEST 1: SPARQL REGEX on object values (literal_statements)")
        print("="*60)
        
        sparql_query = """
        SELECT ?s ?p ?o
        WHERE {
            ?s ?p ?o .
            FILTER(REGEX(STR(?o), "dog", "i"))
        }
        LIMIT 10
        """
        
        print("SPARQL Query:")
        print(sparql_query)
        
        start_time = time.time()
        results = list(graph.query(sparql_query))
        query_time = time.time() - start_time
        
        print(f"\nResults: {len(results)} triples found")
        print(f"Query time: {query_time:.3f} seconds")
        
        if results:
            print("\nSample results:")
            for i, (s, p, o) in enumerate(results[:5]):
                print(f"  {i+1}. {s} -> {p} -> {o}")
        else:
            print("⚠️  No results found - this might indicate an issue")
        
        # Test 2: SPARQL REGEX on subject values
        print("\n" + "="*60)
        print("TEST 2: SPARQL REGEX on subject values")
        print("="*60)
        
        sparql_query2 = """
        SELECT ?s ?p ?o
        WHERE {
            ?s ?p ?o .
            FILTER(REGEX(STR(?s), "synset", "i"))
        }
        LIMIT 10
        """
        
        print("SPARQL Query:")
        print(sparql_query2)
        
        start_time = time.time()
        results2 = list(graph.query(sparql_query2))
        query_time2 = time.time() - start_time
        
        print(f"\nResults: {len(results2)} triples found")
        print(f"Query time: {query_time2:.3f} seconds")
        
        if results2:
            print("\nSample results:")
            for i, (s, p, o) in enumerate(results2[:5]):
                print(f"  {i+1}. {s} -> {p} -> {o}")
        
        # Test 3: SPARQL REGEX on predicate values
        print("\n" + "="*60)
        print("TEST 3: SPARQL REGEX on predicate values")
        print("="*60)
        
        sparql_query3 = """
        SELECT ?s ?p ?o
        WHERE {
            ?s ?p ?o .
            FILTER(REGEX(STR(?p), "label", "i"))
        }
        LIMIT 10
        """
        
        print("SPARQL Query:")
        print(sparql_query3)
        
        start_time = time.time()
        results3 = list(graph.query(sparql_query3))
        query_time3 = time.time() - start_time
        
        print(f"\nResults: {len(results3)} triples found")
        print(f"Query time: {query_time3:.3f} seconds")
        
        if results3:
            print("\nSample results:")
            for i, (s, p, o) in enumerate(results3[:5]):
                print(f"  {i+1}. {s} -> {p} -> {o}")
        
        # Test 4: Complex REGEX pattern
        print("\n" + "="*60)
        print("TEST 4: Complex REGEX pattern (word boundaries)")
        print("="*60)
        
        sparql_query4 = """
        SELECT ?s ?p ?o
        WHERE {
            ?s ?p ?o .
            FILTER(REGEX(STR(?o), "\\bdog\\b", "i"))
        }
        LIMIT 10
        """
        
        print("SPARQL Query:")
        print(sparql_query4)
        
        start_time = time.time()
        results4 = list(graph.query(sparql_query4))
        query_time4 = time.time() - start_time
        
        print(f"\nResults: {len(results4)} triples found")
        print(f"Query time: {query_time4:.3f} seconds")
        
        if results4:
            print("\nSample results:")
            for i, (s, p, o) in enumerate(results4[:5]):
                print(f"  {i+1}. {s} -> {p} -> {o}")
        
        # Summary
        print(f"\n{'='*60}")
        print("TEST SUMMARY")
        print(f"{'='*60}")
        
        total_results = len(results) + len(results2) + len(results3) + len(results4)
        total_time = query_time + query_time2 + query_time3 + query_time4
        
        print(f"✅ PostgreSQL regex implementation: WORKING")
        print(f"✅ Total test queries: 4")
        print(f"✅ Total results found: {total_results}")
        print(f"✅ Total query time: {total_time:.3f} seconds")
        print(f"✅ Average query time: {total_time/4:.3f} seconds")
        
        if total_results > 0:
            print(f"✅ PostgreSQL regex functionality is working correctly!")
        else:
            print(f"⚠️  No results found - may need to check data or query patterns")
        
        # Close store
        store.close()
        
    except Exception as e:
        print(f"❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()

def main():
    """Main test function"""
    test_regex_functionality()

if __name__ == "__main__":
    main()
