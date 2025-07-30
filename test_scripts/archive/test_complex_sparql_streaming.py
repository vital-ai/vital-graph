#!/usr/bin/env python3

import logging
import time
from rdflib import Graph, URIRef, Literal, Namespace
from vitalgraph.store.store import VitalGraphSQLStore
from vitalgraph.optimized_graph import OptimizedVitalGraph

# Configure logging BEFORE importing VitalGraph modules
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def test_complex_sparql_streaming():
    """Test streaming performance across complex SPARQL query patterns"""
    print("=== Complex SPARQL Streaming Performance Test ===")
    
    # Initialize store and graph
    store = VitalGraphSQLStore(identifier="hardcoded")
    store.open("postgresql+psycopg://postgres@127.0.0.1:5432/vitalgraphdb", create=False)
    
    graph_iri = URIRef("http://vital.ai/graph/wordnet")
    # Use OptimizedVitalGraph for ALL queries to fix text search issues
    g = OptimizedVitalGraph(store=store, identifier=graph_iri)
    
    try:
        # Open the store with database connection
        db_url = "postgresql+psycopg://postgres@127.0.0.1:5432/vitalgraphdb"
        store.open(db_url, create=False)
        print("✅ Database connection established")
        
        # Test 1: Complex SPARQL with FILTER and LIMIT
        print("\n🔍 Test 1: Complex SPARQL with FILTER and LIMIT")
        filter_query = """
        SELECT ?s ?p ?o
        WHERE {
            ?s ?p ?o .
            FILTER(CONTAINS(STR(?o), "KG"))
        }
        LIMIT 50
        """
        
        start_time = time.time()
        filter_results = list(g.query(filter_query))
        filter_time = time.time() - start_time
        
        print(f"📈 FILTER Query Results:")
        print(f"- Results: {len(filter_results)}")
        print(f"- Query time: {filter_time:.3f} seconds")
        print(f"- Time per result: {filter_time*1000/max(len(filter_results),1):.1f} ms")
        
        if filter_time < 2.0:
            print("✅ FILTER query streaming performance acceptable")
        else:
            print("❌ FILTER query too slow for streaming")
        
        # Test 2: SPARQL with OPTIONAL patterns
        print("\n🔍 Test 2: SPARQL with OPTIONAL patterns")
        optional_query = """
        SELECT ?s ?type ?name
        WHERE {
            ?s <http://vital.ai/ontology/vital-core#vitaltype> ?type .
            OPTIONAL { ?s <http://vital.ai/ontology/haley-ai-kg#vital__hasName> ?name }
        }
        LIMIT 30
        """
        
        start_time = time.time()
        optional_results = list(g.query(optional_query))
        optional_time = time.time() - start_time
        
        print(f"📈 OPTIONAL Query Results:")
        print(f"- Results: {len(optional_results)}")
        print(f"- Query time: {optional_time:.3f} seconds")
        print(f"- Time per result: {optional_time*1000/max(len(optional_results),1):.1f} ms")
        
        if optional_time < 2.0:
            print("✅ OPTIONAL query streaming performance acceptable")
        else:
            print("❌ OPTIONAL query too slow for streaming")
        
        # Test 3: SPARQL with multiple triple patterns (implicit JOIN)
        print("\n🔍 Test 3: SPARQL with multiple triple patterns (implicit JOIN)")
        join_query = """
        SELECT ?edge ?source ?dest ?relType
        WHERE {
            ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeSource> ?source .
            ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeDestination> ?dest .
            ?edge <http://vital.ai/ontology/haley-ai-kg#vital__hasKGRelationType> ?relType .
        }
        LIMIT 25
        """
        
        start_time = time.time()
        join_results = list(g.query(join_query))
        join_time = time.time() - start_time
        
        print(f"📈 JOIN Query Results:")
        print(f"- Results: {len(join_results)}")
        print(f"- Query time: {join_time:.3f} seconds")
        print(f"- Time per result: {join_time*1000/max(len(join_results),1):.1f} ms")
        
        if join_time < 3.0:
            print("✅ JOIN query streaming performance acceptable")
        else:
            print("❌ JOIN query too slow for streaming")
        
        # Test 4: SPARQL with UNION patterns
        print("\n🔍 Test 4: SPARQL with UNION patterns")
        union_query = """
        SELECT ?s ?p ?o
        WHERE {
            {
                ?s <http://vital.ai/ontology/vital-core#vitaltype> ?o .
                BIND(<http://vital.ai/ontology/vital-core#vitaltype> AS ?p)
            }
            UNION
            {
                ?s <http://vital.ai/ontology/vital-core#vital__hasEdgeSource> ?o .
                BIND(<http://vital.ai/ontology/vital-core#vital__hasEdgeSource> AS ?p)
            }
        }
        LIMIT 40
        """
        
        start_time = time.time()
        union_results = list(g.query(union_query))
        union_time = time.time() - start_time
        
        print(f"📈 UNION Query Results:")
        print(f"- Results: {len(union_results)}")
        print(f"- Query time: {union_time:.3f} seconds")
        print(f"- Time per result: {union_time*1000/max(len(union_results),1):.1f} ms")
        
        if union_time < 3.0:
            print("✅ UNION query streaming performance acceptable")
        else:
            print("❌ UNION query too slow for streaming")
        
        # Test 5: SPARQL ASK query (boolean result)
        print("\n🔍 Test 5: SPARQL ASK query (boolean result)")
        ask_query = """
        ASK {
            ?s <http://vital.ai/ontology/vital-core#vitaltype> <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation> .
        }
        """
        
        start_time = time.time()
        ask_result = g.query(ask_query)
        ask_time = time.time() - start_time
        
        print(f"📈 ASK Query Results:")
        print(f"- Result: {bool(ask_result)}")
        print(f"- Query time: {ask_time:.3f} seconds")
        
        if ask_time < 1.0:
            print("✅ ASK query streaming performance acceptable")
        else:
            print("❌ ASK query too slow for streaming")
        
        # Test 6: SPARQL CONSTRUCT query (graph result)
        print("\n🔍 Test 6: SPARQL CONSTRUCT query (graph result)")
        construct_query = """
        CONSTRUCT {
            ?s <http://example.org/hasType> ?type .
        }
        WHERE {
            ?s <http://vital.ai/ontology/vital-core#vitaltype> ?type .
        }
        LIMIT 20
        """
        
        start_time = time.time()
        construct_result = g.query(construct_query)
        construct_graph = Graph()
        for triple in construct_result:
            construct_graph.add(triple)
        construct_time = time.time() - start_time
        
        print(f"📈 CONSTRUCT Query Results:")
        print(f"- Triples constructed: {len(construct_graph)}")
        print(f"- Query time: {construct_time:.3f} seconds")
        print(f"- Time per triple: {construct_time*1000/max(len(construct_graph),1):.1f} ms")
        
        if construct_time < 2.0:
            print("✅ CONSTRUCT query streaming performance acceptable")
        else:
            print("❌ CONSTRUCT query too slow for streaming")
        
        # Test 7: Text regex queries (SPARQL REGEX function)
        print("\n🔍 Test 7: Text regex queries (SPARQL REGEX function)")
        
        # Test basic regex pattern matching
        regex_query = """
        SELECT ?s ?p ?o
        WHERE {
            ?s ?p ?o .
            FILTER(REGEX(STR(?o), "KG", "i"))
        }
        LIMIT 30
        """
        
        start_time = time.time()
        regex_results = list(g.query(regex_query))
        regex_time = time.time() - start_time
        
        print(f"📈 REGEX Query Results:")
        print(f"- Results: {len(regex_results)}")
        print(f"- Query time: {regex_time:.3f} seconds")
        print(f"- Time per result: {regex_time*1000/max(len(regex_results),1):.1f} ms")
        
        if regex_time < 3.0:
            print("✅ REGEX query streaming performance acceptable")
        else:
            print("❌ REGEX query too slow for streaming")
        
        # Test more complex regex pattern
        complex_regex_query = """
        SELECT ?s ?p ?o
        WHERE {
            ?s ?p ?o .
            FILTER(REGEX(STR(?o), "Edge"))
        }
        LIMIT 25
        """
        
        start_time = time.time()
        complex_regex_results = list(g.query(complex_regex_query))
        complex_regex_time = time.time() - start_time
        
        print(f"📈 Complex REGEX Query Results:")
        print(f"- Results: {len(complex_regex_results)}")
        print(f"- Query time: {complex_regex_time:.3f} seconds")
        print(f"- Time per result: {complex_regex_time*1000/max(len(complex_regex_results),1):.1f} ms")
        
        if complex_regex_time < 3.0:
            print("✅ Complex REGEX query streaming performance acceptable")
        else:
            print("❌ Complex REGEX query too slow for streaming")
        
        # Test CONTAINS function (simpler text search)
        contains_query = """
        SELECT ?s ?p ?o
        WHERE {
            ?s ?p ?o .
            FILTER(CONTAINS(STR(?o), "Relation"))
        }
        LIMIT 35
        """
        
        start_time = time.time()
        contains_results = list(g.query(contains_query))
        contains_time = time.time() - start_time
        
        print(f"📈 CONTAINS Query Results:")
        print(f"- Results: {len(contains_results)}")
        print(f"- Query time: {contains_time:.3f} seconds")
        print(f"- Time per result: {contains_time*1000/max(len(contains_results),1):.1f} ms")
        
        if contains_time < 2.0:
            print("✅ CONTAINS query streaming performance acceptable")
        else:
            print("❌ CONTAINS query too slow for streaming")
        
        # Test STARTS WITH function
        starts_with_query = """
        SELECT ?s ?p ?o
        WHERE {
            ?s ?p ?o .
            FILTER(STRSTARTS(STR(?o), "http://vital.ai/ontology"))
        }
        LIMIT 40
        """
        
        start_time = time.time()
        starts_with_results = list(g.query(starts_with_query))
        starts_with_time = time.time() - start_time
        
        print(f"📈 STRSTARTS Query Results:")
        print(f"- Results: {len(starts_with_results)}")
        print(f"- Query time: {starts_with_time:.3f} seconds")
        print(f"- Time per result: {starts_with_time*1000/max(len(starts_with_results),1):.1f} ms")
        
        if starts_with_time < 2.0:
            print("✅ STRSTARTS query streaming performance acceptable")
        else:
            print("❌ STRSTARTS query too slow for streaming")
        
        # Test 8: Different result formats and processors
        print("\n🔍 Test 8: Different RDFLib result formats and processors")
        
        simple_query = """
        SELECT ?s ?p ?o
        WHERE {
            ?s ?p ?o
        }
        LIMIT 50
        """
        
        # Test different result formats
        formats_to_test = ['sparql', 'json', 'xml']
        
        for result_format in formats_to_test:
            try:
                start_time = time.time()
                results = g.query(simple_query, result=result_format)
                
                # Convert to list to force evaluation
                if hasattr(results, '__iter__'):
                    result_list = list(results)
                    result_count = len(result_list)
                else:
                    result_count = 1
                    
                format_time = time.time() - start_time
                
                print(f"  📊 Format '{result_format}':")
                print(f"    - Results: {result_count}")
                print(f"    - Time: {format_time:.3f} seconds")
                
                if format_time < 2.0:
                    print(f"    ✅ Format '{result_format}' streaming acceptable")
                else:
                    print(f"    ❌ Format '{result_format}' too slow")
                    
            except Exception as e:
                print(f"    ❌ Format '{result_format}' failed: {e}")
        
        # Test 9: WordNet complex query (multiple JOINs + text filtering)
        print("\n🔍 Test 9: WordNet complex query (multiple JOINs + text filtering)")
        
        # WordNet complex query (multi-JOIN + text search)
        # This tests the most complex SPARQL pattern: multiple JOINs + text filtering
        wordnet_query = '''
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        
        SELECT ?entity ?entityName ?edge ?connectedEntity ?connectedName WHERE {
          ?entity a haley-ai-kg:KGEntity .
          ?entity vital-core:hasName ?entityName .
          FILTER(CONTAINS(LCASE(STR(?entityName)), "happy"))
          
          ?edge vital-core:vital__hasEdgeSource ?entity .
          ?edge vital-core:vital__hasEdgeDestination ?connectedEntity .
          
          ?connectedEntity vital-core:hasName ?connectedName .
        }
        ORDER BY ?entityName ?connectedName
        LIMIT 10
        '''
        
        start_time = time.time()
        try:
            wordnet_results = list(g.query(wordnet_query))
            wordnet_time = time.time() - start_time
            
            print(f"📈 WordNet Complex Query Results:")
            print(f"- Results: {len(wordnet_results)}")
            print(f"- Query time: {wordnet_time:.3f} seconds")
            print(f"- Time per result: {wordnet_time*1000/max(len(wordnet_results),1):.1f} ms")
            
            # Show first few results if any
            if wordnet_results:
                print(f"- Sample results:")
                for i, result in enumerate(wordnet_results[:3]):
                    print(f"  {i+1}. Entity: {result[1]}, Connected: {result[4]}")
            
            if wordnet_time < 5.0:
                print("✅ WordNet complex query streaming performance acceptable")
            else:
                print("❌ WordNet complex query too slow for streaming")
                
        except Exception as e:
            print(f"❌ WordNet query failed: {e}")
            wordnet_time = 0.0
            wordnet_results = []
        
        # Test 10: Streaming behavior validation with large LIMIT
        print("\n🔍 Test 10: Streaming behavior validation with large LIMIT")
        
        large_query = """
        SELECT ?s ?p ?o
        WHERE {
            ?s ?p ?o
        }
        LIMIT 500
        """
        
        print("Testing streaming behavior with 500 results...")
        start_time = time.time()
        
        streaming_results = []
        yield_times = []
        
        for i, result in enumerate(g.query(large_query)):
            current_time = time.time()
            yield_times.append(current_time - start_time)
            streaming_results.append(result)
            
            # Log timing for key milestones
            if i + 1 in [1, 10, 50, 100, 250, 500]:
                print(f"  Result {i+1}: yielded at {yield_times[i]*1000:.1f}ms")
                
        end_time = time.time()
        total_streaming_time = end_time - start_time
        
        print(f"\n📈 Large LIMIT Streaming Analysis:")
        print(f"- Total results: {len(streaming_results)}")
        print(f"- Total time: {total_streaming_time:.3f} seconds")
        print(f"- First result at: {yield_times[0]*1000:.1f}ms")
        print(f"- 50th result at: {yield_times[49]*1000:.1f}ms" if len(yield_times) > 49 else "- Less than 50 results")
        print(f"- Last result at: {yield_times[-1]*1000:.1f}ms")
        print(f"- Average per result: {total_streaming_time*1000/len(streaming_results):.1f}ms")
        
        # Validate true streaming behavior
        streaming_checks = []
        
        if yield_times[0] < 0.2:  # First result within 200ms
            streaming_checks.append("✅ First result immediate")
        else:
            streaming_checks.append("❌ First result delayed")
            
        if len(yield_times) > 49 and yield_times[49] < 1.0:  # 50th result within 1s
            streaming_checks.append("✅ Consistent streaming")
        else:
            streaming_checks.append("❌ Inconsistent streaming")
            
        if total_streaming_time < 5.0:  # Total under 5s
            streaming_checks.append("✅ Scalable performance")
        else:
            streaming_checks.append("❌ Poor scalability")
        
        print(f"\n🔍 Streaming Validation:")
        for check in streaming_checks:
            print(f"  {check}")
        
        # Final summary
        print(f"\n📊 COMPREHENSIVE SPARQL STREAMING TEST SUMMARY:")
        print(f"- FILTER query: {filter_time:.3f}s ({len(filter_results)} results)")
        print(f"- OPTIONAL query: {optional_time:.3f}s ({len(optional_results)} results)")
        print(f"- JOIN query: {join_time:.3f}s ({len(join_results)} results)")
        print(f"- UNION query: {union_time:.3f}s ({len(union_results)} results)")
        print(f"- ASK query: {ask_time:.3f}s")
        print(f"- CONSTRUCT query: {construct_time:.3f}s ({len(construct_graph)} triples)")
        print(f"- REGEX query: {regex_time:.3f}s ({len(regex_results)} results)")
        print(f"- Complex REGEX query: {complex_regex_time:.3f}s ({len(complex_regex_results)} results)")
        print(f"- CONTAINS query: {contains_time:.3f}s ({len(contains_results)} results)")
        print(f"- STRSTARTS query: {starts_with_time:.3f}s ({len(starts_with_results)} results)")
        print(f"- WordNet complex query: {wordnet_time:.3f}s ({len(wordnet_results)} results)")
        print(f"- Large LIMIT (500): {total_streaming_time:.3f}s")
        
        # Overall assessment
        all_times = [filter_time, optional_time, join_time, union_time, ask_time, construct_time, 
                    regex_time, complex_regex_time, contains_time, starts_with_time, wordnet_time, total_streaming_time]
        max_time = max(all_times)
        avg_time = sum(all_times) / len(all_times)
        
        print(f"\n🎯 OVERALL ASSESSMENT:")
        print(f"- Maximum query time: {max_time:.3f}s")
        print(f"- Average query time: {avg_time:.3f}s")
        
        if max_time < 5.0 and avg_time < 2.0:
            print("🎉 SUCCESS: Complex SPARQL streaming performance excellent!")
        elif max_time < 10.0 and avg_time < 4.0:
            print("✅ GOOD: Complex SPARQL streaming performance acceptable")
        else:
            print("❌ NEEDS WORK: Complex SPARQL streaming performance issues")
            
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
    test_complex_sparql_streaming()
    print("\n=== Complex SPARQL streaming performance test completed ===")
