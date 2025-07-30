#!/usr/bin/env python3

"""
Test script to diagnose millisecond-level performance bottlenecks.
This test identifies what's causing the 5-second delay for simple LIMIT queries.
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

def test_millisecond_performance():
    """Diagnose what's causing slow performance even with LIMIT pushdown"""
    
    print("=== Diagnosing Millisecond-Level Performance Issues ===")
    
    try:
        # Database connection parameters
        db_url = "postgresql+psycopg://postgres@127.0.0.1:5432/vitalgraphdb"
        
        # Create store and optimized graph
        store = VitalGraphSQLStore(identifier="hardcoded")
        store.open(db_url)
        
        graph_iri = URIRef("http://vital.ai/graph/wordnet")
        g = LimitOptimizedGraph(store=store, identifier=graph_iri)
        
        print(f"Connected to store with identifier: {store.identifier}")
        
        # Test very small LIMIT to see baseline performance
        sparql_query = """
        SELECT ?s ?p ?o WHERE {
            ?s ?p ?o .
        }
        LIMIT 5
        """
        
        print(f"\nExecuting SPARQL query with LIMIT 5 to diagnose bottlenecks:")
        print("Looking for timing breakdown in logs...")
        
        # Execute query with detailed timing
        start_time = time.time()
        results = list(g.query(sparql_query))
        end_time = time.time()
        
        print(f"\nQuery Results:")
        print(f"- Number of results: {len(results)}")
        print(f"- Total execution time: {end_time - start_time:.3f} seconds")
        print(f"- Time per result: {(end_time - start_time) / len(results) * 1000:.1f} ms")
        
        if end_time - start_time > 0.1:  # More than 100ms is too slow
            print("❌ Query is too slow - should be under 100ms for 5 results")
            print("Analyzing logs to identify bottlenecks...")
        else:
            print("✅ Query performance is acceptable")
        
        # Test direct SQL to compare
        print(f"\nTesting direct SQL for comparison:")
        
        # Get the table name
        interned_id = store._interned_id
        table_name = f"{interned_id}_asserted_statements"
        
        direct_sql = f"""
        SELECT subject, predicate, object 
        FROM {table_name} 
        LIMIT 5
        """
        
        print(f"Direct SQL: {direct_sql}")
        
        from sqlalchemy import text
        start_time = time.time()
        with store.engine.connect() as conn:
            result = conn.execute(text(direct_sql))
            rows = result.fetchall()
        end_time = time.time()
        
        print(f"Direct SQL Results:")
        print(f"- Number of results: {len(rows)}")
        print(f"- Execution time: {end_time - start_time:.3f} seconds")
        print(f"- Time per result: {(end_time - start_time) / len(rows) * 1000:.1f} ms")
        
        # Compare performance
        sparql_time = end_time - start_time
        if sparql_time < 0.01:  # Less than 10ms
            print("✅ Direct SQL is fast - bottleneck is in SPARQL processing")
        else:
            print("❌ Even direct SQL is slow - may be database/connection issue")
        
        store.close()
        print("\n=== Performance diagnosis completed ===")
        
    except Exception as e:
        print(f"❌ Error during test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_millisecond_performance()
