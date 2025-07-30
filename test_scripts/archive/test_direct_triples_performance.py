#!/usr/bin/env python3

import logging
import time
from rdflib import Graph, URIRef
from vitalgraph.store.store import VitalGraphSQLStore

# Configure logging BEFORE importing VitalGraph modules
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def test_direct_triples_performance():
    """Test direct triples() method performance with LIMIT context"""
    print("=== Testing Direct Triples Performance ===")
    
    # Create store and graph
    store = VitalGraphSQLStore(identifier="hardcoded")
    graph_iri = URIRef("http://vital.ai/graph/wordnet")
    g = Graph(store=store, identifier=graph_iri)
    
    try:
        # Open the store with database connection
        db_url = "postgresql+psycopg://postgres@127.0.0.1:5432/vitalgraphdb"
        store.open(db_url, create=False)
        print("✅ Database connection established")
        
        print("\n🔍 Test 1: Direct triples() call WITHOUT LIMIT context")
        start_time = time.time()
        
        # Test direct triples call without LIMIT
        triple_pattern = (None, None, None)  # ?s ?p ?o
        results_no_limit = []
        for i, triple in enumerate(store.triples(triple_pattern, context=g)):
            results_no_limit.append(triple)
            if i >= 4:  # Get 5 results
                break
                
        end_time = time.time()
        execution_time_no_limit = end_time - start_time
        
        print(f"📈 Results WITHOUT LIMIT:")
        print(f"- Number of results: {len(results_no_limit)}")
        print(f"- Total execution time: {execution_time_no_limit:.3f} seconds")
        print(f"- Time per result: {execution_time_no_limit*1000/len(results_no_limit):.1f} ms")
        
        print(f"\n🔍 Test 2: Direct triples() call WITH LIMIT context")
        
        # Set query context with LIMIT for comparison
        store._query_context = {'limit': 5, 'offset': None}
        print(f"🎯 Set query context: {store._query_context}")
        
        start_time = time.time()
        
        # Test direct triples call with LIMIT context
        results_with_limit = list(store.triples(triple_pattern, context=g))
        
        end_time = time.time()
        execution_time_with_limit = end_time - start_time
        
        print(f"📈 Results WITH LIMIT:")
        print(f"- Number of results: {len(results_with_limit)}")
        print(f"- Total execution time: {execution_time_with_limit:.3f} seconds")
        print(f"- Time per result: {execution_time_with_limit*1000/len(results_with_limit):.1f} ms")
        
        # Performance comparison
        if execution_time_with_limit < execution_time_no_limit:
            improvement = execution_time_no_limit / execution_time_with_limit
            print(f"✅ LIMIT context improved performance by {improvement:.1f}x")
        else:
            print("❌ LIMIT context did not improve performance")
            
        # Check if we achieved millisecond performance
        if execution_time_with_limit < 0.1:  # Under 100ms
            print("✅ Query is FAST - achieved millisecond-level performance!")
        else:
            print("❌ Query is still slow - need further optimization")
            
        # Clear query context
        store._query_context = {}
        
        print(f"\n🔍 Test 3: Direct SQL comparison")
        # Test direct SQL for comparison
        sql_query = """
        SELECT subject, predicate, object 
        FROM kb_bec6803d52_asserted_statements 
        WHERE context = %s
        LIMIT 5
        """
        
        start_time = time.time()
        
        with store.engine.connect() as connection:
            from sqlalchemy import text
            result = connection.execute(text(sql_query), (str(graph_iri),))
            sql_results = result.fetchall()
            
        end_time = time.time()
        sql_execution_time = end_time - start_time
        
        print(f"📈 Direct SQL Results:")
        print(f"- Number of results: {len(sql_results)}")
        print(f"- Total execution time: {sql_execution_time:.3f} seconds")
        print(f"- Time per result: {sql_execution_time*1000/len(sql_results):.1f} ms")
        
        # Final comparison
        print(f"\n📊 Performance Summary:")
        print(f"- Direct SQL: {sql_execution_time*1000:.1f} ms")
        print(f"- Triples with LIMIT: {execution_time_with_limit*1000:.1f} ms")
        print(f"- Triples without LIMIT: {execution_time_no_limit*1000:.1f} ms")
        
        gap = execution_time_with_limit / sql_execution_time
        print(f"- Performance gap: {gap:.1f}x slower than direct SQL")
        
        if gap < 10:
            print("✅ Performance gap is acceptable (under 10x)")
        else:
            print("❌ Performance gap is too large - needs optimization")
            
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
    test_direct_triples_performance()
    print("\n=== Direct triples performance test completed ===")
