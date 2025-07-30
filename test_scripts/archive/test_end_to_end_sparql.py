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

def test_end_to_end_sparql():
    """Test end-to-end SPARQL query performance with manual LIMIT context setting"""
    print("=== Testing End-to-End SPARQL Performance ===")
    
    # Create store and graph
    store = VitalGraphSQLStore(identifier="hardcoded")
    graph_iri = URIRef("http://vital.ai/graph/wordnet")
    g = Graph(store=store, identifier=graph_iri)
    
    try:
        # Open the store with database connection
        db_url = "postgresql+psycopg://postgres@127.0.0.1:5432/vitalgraphdb"
        store.open(db_url, create=False)
        print("✅ Database connection established")
        
        # Test SPARQL query with manual LIMIT context setting
        sparql_query = """
        SELECT ?s ?p ?o WHERE {
            ?s ?p ?o .
        } LIMIT 5
        """
        
        print(f"\n🔍 Testing SPARQL query with manual LIMIT context:")
        print(f"Query: {sparql_query.strip()}")
        
        # Extract LIMIT from SPARQL manually
        limit_match = re.search(r'LIMIT\s+(\d+)', sparql_query, re.IGNORECASE)
        limit = int(limit_match.group(1)) if limit_match else None
        
        print(f"📊 Extracted LIMIT: {limit}")
        
        # Set query context manually before executing SPARQL
        store._query_context = {'limit': limit, 'offset': None}
        print(f"🎯 Set store query context: {store._query_context}")
        
        start_time = time.time()
        
        try:
            # Execute SPARQL query using RDFLib's built-in engine
            # This should trigger our optimized triples() method
            results = []
            for result in g.query(sparql_query):
                results.append(result)
                
            end_time = time.time()
            execution_time = end_time - start_time
            
            print(f"\n📈 SPARQL Query Results:")
            print(f"- Number of results: {len(results)}")
            print(f"- Total execution time: {execution_time:.3f} seconds")
            print(f"- Time per result: {execution_time*1000/len(results):.1f} ms")
            
            # Check if we achieved millisecond performance
            if execution_time < 0.1:  # Under 100ms
                print("✅ SPARQL query is FAST - achieved millisecond-level performance!")
            else:
                print("❌ SPARQL query is still slow - need further optimization")
                
            # Show first few results
            print(f"\n📋 First 3 results:")
            for i, result in enumerate(results[:3]):
                print(f"  {i+1}. {result}")
                
        except Exception as e:
            print(f"❌ SPARQL query failed: {e}")
            import traceback
            traceback.print_exc()
            
        finally:
            # Clear query context
            store._query_context = {}
            
        print(f"\n🔍 Test 2: Compare with direct triples() call")
        
        # Set LIMIT context again for direct comparison
        store._query_context = {'limit': 5, 'offset': None}
        
        start_time = time.time()
        
        # Direct triples call for comparison
        triple_pattern = (None, None, None)
        direct_results = list(store.triples(triple_pattern, context=g))
        
        end_time = time.time()
        direct_execution_time = end_time - start_time
        
        print(f"📈 Direct triples() Results:")
        print(f"- Number of results: {len(direct_results)}")
        print(f"- Total execution time: {direct_execution_time:.3f} seconds")
        print(f"- Time per result: {direct_execution_time*1000/len(direct_results):.1f} ms")
        
        # Performance comparison
        if len(results) > 0 and len(direct_results) > 0:
            sparql_per_result = execution_time / len(results)
            direct_per_result = direct_execution_time / len(direct_results)
            
            if sparql_per_result < direct_per_result * 2:  # Within 2x
                print("✅ SPARQL performance is comparable to direct triples()")
            else:
                overhead = sparql_per_result / direct_per_result
                print(f"⚠️ SPARQL has {overhead:.1f}x overhead vs direct triples()")
                
        # Clear query context
        store._query_context = {}
        
        print(f"\n🔍 Test 3: Test without LIMIT context (should be slower)")
        
        start_time = time.time()
        
        # Test without LIMIT context
        no_limit_results = []
        for i, triple in enumerate(store.triples(triple_pattern, context=g)):
            no_limit_results.append(triple)
            if i >= 4:  # Get 5 results manually
                break
                
        end_time = time.time()
        no_limit_execution_time = end_time - start_time
        
        print(f"📈 No LIMIT context Results:")
        print(f"- Number of results: {len(no_limit_results)}")
        print(f"- Total execution time: {no_limit_execution_time:.3f} seconds")
        print(f"- Time per result: {no_limit_execution_time*1000/len(no_limit_results):.1f} ms")
        
        # Final performance summary
        print(f"\n📊 Performance Summary:")
        if len(results) > 0:
            print(f"- SPARQL with LIMIT: {execution_time*1000:.1f} ms total")
        print(f"- Direct triples with LIMIT: {direct_execution_time*1000:.1f} ms total")
        print(f"- Direct triples without LIMIT: {no_limit_execution_time*1000:.1f} ms total")
        
        if direct_execution_time < no_limit_execution_time:
            improvement = no_limit_execution_time / direct_execution_time
            print(f"✅ LIMIT optimization provides {improvement:.1f}x speedup")
        else:
            print("❌ LIMIT optimization not working as expected")
            
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
    test_end_to_end_sparql()
    print("\n=== End-to-end SPARQL performance test completed ===")
