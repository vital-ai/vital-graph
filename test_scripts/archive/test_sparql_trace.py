#!/usr/bin/env python3
"""
Trace exactly which functions are called during SPARQL query execution
"""

import sys
import os
import logging
import time
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from rdflib import Graph, URIRef
from sqlalchemy import create_engine
from vitalgraph.store.store import VitalGraphSQLStore

# Configure logging with maximum verbosity
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Enable ALL vitalgraph logging
logging.getLogger('vitalgraph').setLevel(logging.DEBUG)
logging.getLogger('rdflib').setLevel(logging.INFO)  # RDFLib can be very verbose

# Database connection parameters
PG_HOST = "127.0.0.1"
PG_PORT = 5432
PG_USER = "postgres"
PG_PASSWORD = ""
PG_DATABASE = "vitalgraphdb"

STORE_IDENTIFIER = "hardcoded"
GRAPH_URI = "http://vital.ai/graph/wordnet"

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

def test_sparql_execution_trace():
    """Trace SPARQL query execution to see which functions are called"""
    print("=== SPARQL EXECUTION TRACE TEST ===")
    print("This will show exactly which functions are called during SPARQL execution")
    print("Look for log messages from vitalgraph.store.* modules")
    
    try:
        print("\n🔧 Creating graph connection...")
        graph, store = create_test_graph()
        print("✅ Connected to VitalGraph store")
        
        # Add some manual logging to see if store methods are called
        original_triples = store.triples
        def traced_triples(*args, **kwargs):
            print(f"🎯 TRACE: store.triples() called with args={args}, kwargs={kwargs}")
            return original_triples(*args, **kwargs)
        store.triples = traced_triples
        
        print("\n🔍 Executing simple SPARQL query with tracing...")
        print("Query: SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 5")
        
        simple_query = """
        SELECT ?s ?p ?o
        WHERE {
            ?s ?p ?o
        }
        LIMIT 5
        """
        
        start_time = time.time()
        
        # Execute the query and see what gets called
        print("\n📊 Starting query execution...")
        print(f"🎯 IMMEDIATE: About to call graph.query() at {time.time()}")
        
        # Add logging right before the query
        logging.getLogger('vitalgraph.store.store').info("🚀 SPARQL QUERY STARTING NOW")
        
        results = list(graph.query(simple_query))
        
        print(f"🎯 IMMEDIATE: graph.query() completed at {time.time()}")
        
        query_time = time.time() - start_time
        
        print(f"\n🎯 QUERY COMPLETED:")
        print(f"   Results: {len(results)} triples")
        print(f"   Query time: {query_time:.3f} seconds")
        
        if results:
            print(f"   Sample result: {results[0]}")
        
        store.close()
        
        print(f"\n📋 ANALYSIS:")
        if query_time > 5.0:
            print(f"   ⚠️  Query is still slow ({query_time:.1f}s)")
            print(f"   🔍 Check the logs above to see which functions were called")
            print(f"   🔍 If no vitalgraph.store.* logs appear, the issue is in RDFLib's query processing")
        else:
            print(f"   ✅ Query performance is acceptable")
        
    except Exception as e:
        print(f"❌ Error during tracing: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_sparql_execution_trace()
