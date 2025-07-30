#!/usr/bin/env python3
"""
Verify WordNet data content to understand what patterns exist for regex testing
"""

import sys
import os
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

def verify_data():
    """Verify what data exists in the WordNet dataset"""
    print("=== WORDNET DATA VERIFICATION ===")
    print(f"Store Identifier: {STORE_IDENTIFIER}")
    print(f"Graph URI: {GRAPH_URI}")
    
    try:
        graph, store = create_test_graph()
        print("✅ Connected to VitalGraph store")
        
        # Test 1: Count total triples
        print("\n--- Total Triple Count ---")
        count_query = "SELECT (COUNT(*) as ?count) WHERE { ?s ?p ?o }"
        results = list(graph.query(count_query))
        if results:
            total_count = results[0][0]
            print(f"Total triples: {total_count}")
        
        # Test 2: Sample some subjects
        print("\n--- Sample Subjects ---")
        subject_query = "SELECT DISTINCT ?s WHERE { ?s ?p ?o } LIMIT 5"
        results = list(graph.query(subject_query))
        for i, result in enumerate(results, 1):
            print(f"Subject {i}: {result[0]}")
        
        # Test 3: Sample some predicates
        print("\n--- Sample Predicates ---")
        predicate_query = "SELECT DISTINCT ?p WHERE { ?s ?p ?o } LIMIT 5"
        results = list(graph.query(predicate_query))
        for i, result in enumerate(results, 1):
            print(f"Predicate {i}: {result[0]}")
        
        # Test 4: Sample some objects (literals)
        print("\n--- Sample Literal Objects ---")
        literal_query = """
        SELECT ?o WHERE { 
            ?s ?p ?o . 
            FILTER(isLiteral(?o))
        } LIMIT 5
        """
        results = list(graph.query(literal_query))
        for i, result in enumerate(results, 1):
            print(f"Literal {i}: {result[0]}")
        
        # Test 5: Look for specific WordNet patterns
        print("\n--- WordNet-specific Patterns ---")
        
        # Check for synset URIs
        synset_query = """
        SELECT ?s WHERE { 
            ?s ?p ?o . 
            FILTER(CONTAINS(STR(?s), "synset"))
        } LIMIT 3
        """
        results = list(graph.query(synset_query))
        print(f"Synset subjects found: {len(results)}")
        for result in results:
            print(f"  {result[0]}")
        
        # Check for name-related predicates
        name_query = """
        SELECT ?p WHERE { 
            ?s ?p ?o . 
            FILTER(CONTAINS(STR(?p), "name") || CONTAINS(STR(?p), "label"))
        } LIMIT 3
        """
        results = list(graph.query(name_query))
        print(f"Name/label predicates found: {len(results)}")
        for result in results:
            print(f"  {result[0]}")
        
        # Check for text containing common words
        text_query = """
        SELECT ?o WHERE { 
            ?s ?p ?o . 
            FILTER(isLiteral(?o) && (CONTAINS(LCASE(STR(?o)), "dog") || CONTAINS(LCASE(STR(?o)), "happy") || CONTAINS(LCASE(STR(?o)), "good")))
        } LIMIT 3
        """
        results = list(graph.query(text_query))
        print(f"Common word literals found: {len(results)}")
        for result in results:
            print(f"  {result[0]}")
        
        store.close()
        print("\n✅ Data verification completed")
        
    except Exception as e:
        print(f"❌ Error during verification: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    verify_data()
