#!/usr/bin/env python3

"""
Test script to verify LimitOptimizedGraph functionality.
This test confirms that SPARQL LIMIT clauses are properly intercepted
and pushed down to the SQL level using the LimitOptimizedGraph wrapper.
"""

import logging
import sys
import os
import time

# Configure logging BEFORE importing vitalgraph
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

# Configure vitalgraph.store logger specifically
vitalgraph_logger = logging.getLogger('vitalgraph.store')
vitalgraph_logger.setLevel(logging.INFO)

# Add the project root to Python path
sys.path.insert(0, '/Users/hadfield/Local/vital-git/vital-graph')

from rdflib import URIRef
from vitalgraph.store.store import VitalGraphSQLStore
from vitalgraph.limit_optimized_graph import LimitOptimizedGraph

def test_limit_optimized_graph():
    """Test that LimitOptimizedGraph properly intercepts and optimizes SPARQL LIMIT queries"""
    
    print("=== Testing LimitOptimizedGraph SPARQL LIMIT Optimization ===")
    
    try:
        # Database connection parameters
        db_url = "postgresql+psycopg://postgres@127.0.0.1:5432/vitalgraphdb"
        
        # Create store and optimized graph
        store = VitalGraphSQLStore(identifier="hardcoded")
        store.open(db_url)
        
        graph_iri = URIRef("http://vital.ai/graph/wordnet")
        g = LimitOptimizedGraph(store=store, identifier=graph_iri)
        
        print(f"Connected to store with identifier: {store.identifier}")
        print(f"Graph IRI: {graph_iri}")
        print(f"Using LimitOptimizedGraph wrapper")
        
        # Test SPARQL query with LIMIT - should be fast now
        sparql_query = """
        SELECT ?s ?p ?o WHERE {
            ?s ?p ?o .
        }
        LIMIT 100
        """
        
        print(f"\nExecuting SPARQL query with LIMIT 100:")
        print(sparql_query)
        
        # Execute query and measure time
        start_time = time.time()
        results = list(g.query(sparql_query))
        end_time = time.time()
        
        print(f"\nQuery Results:")
        print(f"- Number of results: {len(results)}")
        print(f"- Execution time: {end_time - start_time:.3f} seconds")
        
        # Check if we got exactly 100 results (LIMIT should be applied)
        if len(results) == 100:
            print("✅ LIMIT appears to be working - got exactly 100 results")
        else:
            print(f"❌ LIMIT may not be working - got {len(results)} results instead of 100")
        
        # Check if execution was fast (should be under 10 seconds with LIMIT pushdown)
        if end_time - start_time < 10.0:
            print("✅ Query execution was fast - LIMIT pushdown likely working")
        else:
            print(f"❌ Query execution was slow ({end_time - start_time:.3f}s) - LIMIT pushdown may not be working")
        
        # Test with smaller LIMIT
        sparql_query_small = """
        SELECT ?s ?p ?o WHERE {
            ?s ?p ?o .
        }
        LIMIT 10
        """
        
        print(f"\nExecuting SPARQL query with LIMIT 10:")
        start_time = time.time()
        results_small = list(g.query(sparql_query_small))
        end_time = time.time()
        
        print(f"- Number of results: {len(results_small)}")
        print(f"- Execution time: {end_time - start_time:.3f} seconds")
        
        if len(results_small) == 10:
            print("✅ LIMIT 10 working correctly")
        else:
            print(f"❌ LIMIT 10 not working - got {len(results_small)} results")
        
        # Test OFFSET as well
        sparql_query_offset = """
        SELECT ?s ?p ?o WHERE {
            ?s ?p ?o .
        }
        LIMIT 10 OFFSET 50
        """
        
        print(f"\nExecuting SPARQL query with LIMIT 10 OFFSET 50:")
        start_time = time.time()
        results_offset = list(g.query(sparql_query_offset))
        end_time = time.time()
        
        print(f"- Number of results: {len(results_offset)}")
        print(f"- Execution time: {end_time - start_time:.3f} seconds")
        
        if len(results_offset) == 10:
            print("✅ LIMIT with OFFSET working correctly")
        else:
            print(f"❌ LIMIT with OFFSET not working - got {len(results_offset)} results")
        
        store.close()
        print("\n=== Test completed ===")
        
    except Exception as e:
        print(f"❌ Error during test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_limit_optimized_graph()
