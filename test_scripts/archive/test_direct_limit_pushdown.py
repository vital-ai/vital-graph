#!/usr/bin/env python3

import logging
import time
import re
from rdflib import Graph, URIRef
from vitalgraph.store.store import VitalGraphSQLStore

# Configure logging BEFORE importing VitalGraph modules
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def extract_limit_from_sparql(sparql_query):
    """Extract LIMIT value from SPARQL query"""
    # Look for LIMIT followed by a number
    match = re.search(r'\bLIMIT\s+(\d+)', sparql_query, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None

def test_direct_limit_pushdown():
    """Test direct LIMIT pushdown to SQL level"""
    print("=== Testing Direct LIMIT Pushdown ===")
    
    # Database connection parameters
    db_params = {
        'host': '127.0.0.1',
        'port': 5432,
        'user': 'postgres',
        'database': 'vitalgraphdb',
        'driver': 'postgresql+psycopg'
    }
    
    # Create store and graph
    store = VitalGraphSQLStore(**db_params)
    graph_iri = URIRef("http://vital.ai/graph/wordnet")
    g = Graph(store=store, identifier=graph_iri)
    
    try:
        # Open the store
        store.open(create=False)
        print("✅ Database connection established")
        
        # Test SPARQL query with LIMIT
        sparql_query = """
        SELECT ?s ?p ?o WHERE {
            ?s ?p ?o
        } LIMIT 5
        """
        
        print(f"\n🔍 Testing SPARQL query: {sparql_query.strip()}")
        
        # Extract LIMIT from SPARQL
        limit_value = extract_limit_from_sparql(sparql_query)
        print(f"📊 Extracted LIMIT: {limit_value}")
        
        # Manually set query context with LIMIT
        store._query_context = {'limit': limit_value}
        print(f"🎯 Set query context: {store._query_context}")
        
        # Execute query with timing
        start_time = time.time()
        
        # Use the triples method directly to test our optimization
        triple_pattern = (None, None, None)  # ?s ?p ?o
        results = list(store.triples(triple_pattern, context=g))
        
        end_time = time.time()
        execution_time = end_time - start_time
        
        print(f"\n📈 Query Results:")
        print(f"- Number of results: {len(results)}")
        print(f"- Total execution time: {execution_time:.3f} seconds")
        print(f"- Time per result: {execution_time*1000/len(results):.1f} ms")
        
        # Check if we achieved millisecond performance
        if execution_time < 0.1:  # Under 100ms
            print("✅ Query is FAST - achieved millisecond-level performance!")
        else:
            print("❌ Query is still slow - need further optimization")
            
        # Clear query context
        store._query_context = {}
        
        # Test without LIMIT for comparison
        print(f"\n🔍 Testing same query WITHOUT LIMIT for comparison...")
        start_time = time.time()
        
        # Get just first 5 results for fair comparison
        results_no_limit = []
        for i, triple in enumerate(store.triples(triple_pattern, context=g)):
            results_no_limit.append(triple)
            if i >= 4:  # Get 5 results
                break
                
        end_time = time.time()
        execution_time_no_limit = end_time - start_time
        
        print(f"📈 Results without LIMIT:")
        print(f"- Number of results: {len(results_no_limit)}")
        print(f"- Total execution time: {execution_time_no_limit:.3f} seconds")
        print(f"- Time per result: {execution_time_no_limit*1000/len(results_no_limit):.1f} ms")
        
        # Performance comparison
        if execution_time < execution_time_no_limit:
            improvement = execution_time_no_limit / execution_time
            print(f"✅ LIMIT pushdown improved performance by {improvement:.1f}x")
        else:
            print("❌ LIMIT pushdown did not improve performance")
            
    except Exception as e:
        print(f"❌ Error during test: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # Clean up
        try:
            store.close()
            print("🔒 Database connection closed")
        except:
            pass

if __name__ == "__main__":
    test_direct_limit_pushdown()
    print("\n=== Direct LIMIT pushdown test completed ===")
