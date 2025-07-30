import sys
import logging
import time

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ],
    force=True  # Force reconfiguration
)

print ("running...")

# Specifically enable logging for ALL VitalGraph SQL modules
logging.getLogger('vitalgraph.store').setLevel(logging.INFO)
logging.getLogger('vitalgraph.store.store').setLevel(logging.INFO)
logging.getLogger('vitalgraph.store.base').setLevel(logging.INFO)
logging.getLogger('vitalgraph.store.sql').setLevel(logging.INFO)
logging.getLogger('vitalgraph.store.termutils').setLevel(logging.INFO)
logging.getLogger('vitalgraph.store.tables').setLevel(logging.INFO)
logging.getLogger('vitalgraph.store.statistics').setLevel(logging.INFO)
logging.getLogger('vitalgraph.store.types').setLevel(logging.INFO)

# Also set the root logger to ensure we catch everything
logging.getLogger().setLevel(logging.INFO)

# NOW import vitalgraph modules (logging should show function calls)
from rdflib import Graph, URIRef
from sqlalchemy import create_engine
from vitalgraph.store.store import VitalGraphSQLStore

print("🔍 Logging configured for vitalgraph.store modules")

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

def test_performance():
    """Test SPARQL performance with detailed logging"""
    print("=== SPARQL PERFORMANCE TEST WITH LOGGING ===")
    print(f"Database: {PG_DATABASE} on {PG_HOST}:{PG_PORT}")
    print(f"Store Identifier: {STORE_IDENTIFIER}")
    print(f"Graph URI: {GRAPH_URI}")
    print("Logging level: INFO (will show detailed SQL execution)")
    print()
    
    # First test: Show logging from basic VitalGraph operations (no database needed)
    print("🔍 Step 1: Testing basic VitalGraph logging (no database connection needed)...")
    try:
        from vitalgraph.store.store import generate_interned_id, VitalGraphSQLStore
        
        print("   Calling generate_interned_id...")
        result = generate_interned_id(STORE_IDENTIFIER)
        print(f"   ✅ generate_interned_id result: {result}")
        
        print("   Creating VitalGraphSQLStore instance...")
        store = VitalGraphSQLStore(identifier=STORE_IDENTIFIER)
        print(f"   ✅ Store created with identifier: {store.identifier}")
        
        print("   ✅ Basic logging test successful!")
        print()
        
    except Exception as e:
        print(f"   ❌ Error in basic logging test: {e}")
        return False
    
    # Second test: Try database connection and show more logging
    print("🔍 Step 2: Testing database connection and advanced logging...")
    try:
        graph, store = create_test_graph()
        print("✅ Connected to VitalGraph store")
        
        # Test 1: Simple LIMIT 100 query (should be fast now)
        print("\n" + "="*60)
        print("TEST 1: Simple SPARQL query - LIMIT 100 (should be milliseconds)")
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
        print("\nExecuting query with detailed logging...")
        
        start_time = time.time()
        results = list(graph.query(simple_query))
        query_time = time.time() - start_time
        
        print(f"\n🎯 PERFORMANCE RESULT:")
        print(f"   Results: {len(results)} triples")
        print(f"   Query time: {query_time:.3f} seconds")
        
        if query_time < 1.0:
            print(f"   ✅ EXCELLENT: Query completed in under 1 second!")
        elif query_time < 5.0:
            print(f"   ✅ GOOD: Query completed in under 5 seconds")
        else:
            print(f"   ⚠️  SLOW: Query took {query_time:.1f} seconds (still needs optimization)")
        
        # Test 2: Count query (should also be faster)
        print("\n" + "="*60)
        print("TEST 2: Count query (should be fast)")
        print("="*60)
        
        count_query = """
        SELECT (COUNT(*) as ?count)
        WHERE {
            ?s ?p ?o
        }
        """
        
        print("SPARQL Query:")
        print(count_query)
        print("\nExecuting count query...")
        
        start_time = time.time()
        count_results = list(graph.query(count_query))
        query_time = time.time() - start_time
        
        if count_results:
            total_count = count_results[0][0]
            print(f"\n🎯 COUNT RESULT:")
            print(f"   Total triples: {total_count}")
            print(f"   Query time: {query_time:.3f} seconds")
            
            if query_time < 5.0:
                print(f"   ✅ Count query performance acceptable")
            else:
                print(f"   ⚠️  Count query still slow: {query_time:.1f} seconds")
        
        store.close()
        print("\n" + "="*60)
        print("PERFORMANCE TEST SUMMARY")
        print("="*60)
        print("✅ Performance test completed")
        print("📊 Check the logs above for detailed SQL execution information")
        
    except Exception as e:
        print(f"❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_performance()
