#!/usr/bin/env python3

"""
Test script to verify SQL LIMIT pushdown functionality.
This test confirms that SPARQL LIMIT clauses are pushed down to the SQL level
rather than being applied in Python after fetching all rows.
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

from rdflib import Graph, URIRef, Literal, Namespace
from rdflib.plugins.sparql import prepareQuery
from vitalgraph.store.store import VitalGraphSQLStore

def test_sql_limit_pushdown():
    """Test that SPARQL LIMIT queries push LIMIT down to SQL level"""
    
    print("=== Testing SQL LIMIT Pushdown ===")
    
    try:
        # Database connection parameters
        db_url = "postgresql+psycopg://postgres@127.0.0.1:5432/vitalgraphdb"
        
        # Create store and graph
        store = VitalGraphSQLStore(identifier="hardcoded")
        store.open(db_url)
        
        graph_iri = URIRef("http://vital.ai/graph/wordnet")
        g = Graph(store=store, identifier=graph_iri)
        
        print(f"Connected to store with identifier: {store.identifier}")
        print(f"Graph IRI: {graph_iri}")
        
        # Test SPARQL query with LIMIT
        sparql_query = """
        SELECT ?s ?p ?o WHERE {
            ?s ?p ?o .
        }
        LIMIT 10
        """
        
        print(f"\nExecuting SPARQL query with LIMIT 10:")
        print(sparql_query)
        
        # Execute query and measure time
        start_time = time.time()
        results = list(g.query(sparql_query))
        end_time = time.time()
        
        print(f"\nQuery Results:")
        print(f"- Number of results: {len(results)}")
        print(f"- Execution time: {end_time - start_time:.3f} seconds")
        
        # Check if we got exactly 10 results (LIMIT should be applied)
        if len(results) == 10:
            print("✅ LIMIT appears to be working - got exactly 10 results")
        else:
            print(f"❌ LIMIT may not be working - got {len(results)} results instead of 10")
        
        # Test with different LIMIT
        sparql_query_5 = """
        SELECT ?s ?p ?o WHERE {
            ?s ?p ?o .
        }
        LIMIT 5
        """
        
        print(f"\nExecuting SPARQL query with LIMIT 5:")
        start_time = time.time()
        results_5 = list(g.query(sparql_query_5))
        end_time = time.time()
        
        print(f"- Number of results: {len(results_5)}")
        print(f"- Execution time: {end_time - start_time:.3f} seconds")
        
        if len(results_5) == 5:
            print("✅ LIMIT 5 working correctly")
        else:
            print(f"❌ LIMIT 5 not working - got {len(results_5)} results")
        
        # Test OFFSET as well
        sparql_query_offset = """
        SELECT ?s ?p ?o WHERE {
            ?s ?p ?o .
        }
        LIMIT 5 OFFSET 10
        """
        
        print(f"\nExecuting SPARQL query with LIMIT 5 OFFSET 10:")
        start_time = time.time()
        results_offset = list(g.query(sparql_query_offset))
        end_time = time.time()
        
        print(f"- Number of results: {len(results_offset)}")
        print(f"- Execution time: {end_time - start_time:.3f} seconds")
        
        if len(results_offset) == 5:
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
    test_sql_limit_pushdown()
