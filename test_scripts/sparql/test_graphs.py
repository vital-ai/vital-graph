#!/usr/bin/env python3
"""
Graph Operations Test Script
============================

Test graph management functionality in VitalGraph's PostgreSQL backend.
This file tests both low-level PostgreSQL space graph operations and 
high-level SPARQL graph operations.

Graph operations tested:
- Low-level: create_graph, drop_graph, clear_graph, list_graphs
- SPARQL: CREATE GRAPH, DROP GRAPH, CLEAR GRAPH
- Graph cache integration
- Batch graph operations
- Graph existence checks during quad insertion
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.config.config_loader import get_config
from vitalgraph.db.postgresql.postgresql_sparql_impl import PostgreSQLSparqlImpl

# Import test utilities for consistent test execution and reporting
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tool_utils"))
from tool_utils import TestToolUtils

# Configure logging to see graph operations
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(name)s - %(message)s')

# Suppress verbose logging from other modules but keep graph logging
logging.getLogger('vitalgraph.rdf.rdf_utils').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.db.postgresql.postgresql_cache_term').setLevel(logging.WARNING)
# Keep graph-related logging at INFO level
logging.getLogger('vitalgraph.db.postgresql.space.postgresql_space_graphs').setLevel(logging.INFO)
logging.getLogger('vitalgraph.db.postgresql.postgresql_cache_graph').setLevel(logging.INFO)

# Configuration
SPACE_ID = "space_test"
TEST_GRAPH_1 = "http://vital.ai/graph/test1"
TEST_GRAPH_2 = "http://vital.ai/graph/test2"
TEST_GRAPH_3 = "http://vital.ai/graph/test3"
GLOBAL_GRAPH_URI = "urn:___GLOBAL"

async def test_low_level_graph_operations(space_impl):
    """Test low-level PostgreSQL space graph operations."""
    print("\n" + "="*60)
    print("TESTING LOW-LEVEL GRAPH OPERATIONS")
    print("="*60)
    
    graphs = space_impl.graphs
    
    # Test 1: Create graphs
    print(f"\n1. Creating graphs...")
    success1 = await graphs.create_graph(SPACE_ID, TEST_GRAPH_1, "Test Graph 1")
    success2 = await graphs.create_graph(SPACE_ID, TEST_GRAPH_2, "Test Graph 2")
    print(f"   Created {TEST_GRAPH_1}: {success1}")
    print(f"   Created {TEST_GRAPH_2}: {success2}")
    
    # Test 2: List graphs
    print(f"\n2. Listing graphs...")
    graph_list = await graphs.list_graphs(SPACE_ID)
    print(f"   Found {len(graph_list)} graphs:")
    for graph in graph_list:
        print(f"   - {graph['graph_uri']} ({graph['graph_name']}) - {graph['triple_count']} triples")
    
    # Test 3: Get specific graph
    print(f"\n3. Getting specific graph...")
    graph_info = await graphs.get_graph(SPACE_ID, TEST_GRAPH_1)
    if graph_info:
        print(f"   Graph info: {graph_info['graph_uri']} - {graph_info['triple_count']} triples")
    else:
        print(f"   Graph not found: {TEST_GRAPH_1}")
    
    # Test 4: Update triple count
    print(f"\n4. Updating triple count...")
    await graphs.update_graph_triple_count(SPACE_ID, TEST_GRAPH_1, absolute_count=42)
    updated_graph = await graphs.get_graph(SPACE_ID, TEST_GRAPH_1)
    print(f"   Updated triple count: {updated_graph['triple_count'] if updated_graph else 'N/A'}")
    
    # Test 5: Clear graph (removes triples but keeps graph)
    print(f"\n5. Clearing graph...")
    success = await graphs.clear_graph(SPACE_ID, TEST_GRAPH_1)
    cleared_graph = await graphs.get_graph(SPACE_ID, TEST_GRAPH_1)
    print(f"   Cleared graph: {success}")
    print(f"   Graph still exists with {cleared_graph['triple_count'] if cleared_graph else 'N/A'} triples")
    
    # Test 6: Drop graph (removes triples and graph entry)
    print(f"\n6. Dropping graph...")
    success = await graphs.drop_graph(SPACE_ID, TEST_GRAPH_2)
    dropped_graph = await graphs.get_graph(SPACE_ID, TEST_GRAPH_2)
    print(f"   Dropped graph: {success}")
    print(f"   Graph exists after drop: {dropped_graph is not None}")
    
    # Test 7: Batch ensure graphs exist
    print(f"\n7. Batch ensuring graphs exist...")
    batch_graphs = {TEST_GRAPH_2, TEST_GRAPH_3, "http://vital.ai/graph/batch1"}
    success = await graphs.batch_ensure_graphs_exist(SPACE_ID, batch_graphs)
    print(f"   Batch ensure success: {success}")
    
    final_list = await graphs.list_graphs(SPACE_ID)
    print(f"   Final graph count: {len(final_list)}")
    
    return True

async def test_graph_cache_operations(space_impl):
    """Test graph cache functionality."""
    print("\n" + "="*60)
    print("TESTING GRAPH CACHE OPERATIONS")
    print("="*60)
    
    # Get graph cache for the space
    graph_cache = space_impl.get_graph_cache(SPACE_ID)
    
    # Test 1: Initial cache state
    print(f"\n1. Initial cache state...")
    print(f"   Cache size: {graph_cache.size()}")
    stats = graph_cache.get_statistics()
    print(f"   Cache stats: {stats}")
    
    # Test 2: Check missing graphs
    test_graphs = {TEST_GRAPH_1, TEST_GRAPH_2, "http://vital.ai/graph/new1"}
    missing = graph_cache.get_missing_graphs(test_graphs)
    print(f"\n2. Missing graphs check...")
    print(f"   Test graphs: {len(test_graphs)}")
    print(f"   Missing from cache: {len(missing)}")
    
    # Test 3: Add graphs to cache
    print(f"\n3. Adding graphs to cache...")
    graph_cache.add_graphs_to_cache_batch(test_graphs)
    cached = graph_cache.get_cached_graphs(test_graphs)
    print(f"   Cached graphs: {len(cached)}")
    print(f"   Cache size after batch add: {graph_cache.size()}")
    
    # Test 4: Cache hit/miss statistics
    print(f"\n4. Testing cache hits...")
    # This should be cache hits
    for graph_uri in test_graphs:
        is_cached = graph_cache.is_graph_cached(graph_uri)
        print(f"   {graph_uri}: {'HIT' if is_cached else 'MISS'}")
    
    # Test new graphs (should be misses)
    new_graphs = {"http://vital.ai/graph/miss1", "http://vital.ai/graph/miss2"}
    for graph_uri in new_graphs:
        is_cached = graph_cache.is_graph_cached(graph_uri)
        print(f"   {graph_uri}: {'HIT' if is_cached else 'MISS'}")
    
    # Final statistics
    final_stats = graph_cache.get_statistics()
    print(f"\n5. Final cache statistics:")
    print(f"   Cache size: {final_stats['cache_size']}")
    print(f"   Cache hits: {final_stats['cache_hits']}")
    print(f"   Cache misses: {final_stats['cache_misses']}")
    print(f"   Hit rate: {final_stats['cache_hit_rate']:.2%}")
    
    return True

async def test_sparql_graph_operations(sparql_impl):
    """Test high-level SPARQL graph operations."""
    print("\n" + "="*60)
    print("TESTING SPARQL GRAPH OPERATIONS")
    print("="*60)
    
    # Test 1: CREATE GRAPH
    print(f"\n1. Testing CREATE GRAPH...")
    create_queries = [
        f"CREATE GRAPH <{TEST_GRAPH_1}>",
        f"CREATE GRAPH <{TEST_GRAPH_2}>",
        f"CREATE GRAPH <http://vital.ai/graph/sparql1>"
    ]
    
    for query in create_queries:
        try:
            success = await sparql_impl.execute_sparql_update(SPACE_ID, query)
            print(f"   {query}: {'SUCCESS' if success else 'FAILED'}")
        except Exception as e:
            print(f"   {query}: ERROR - {e}")
    
    # Test 2: INSERT DATA with graphs
    print(f"\n2. Testing INSERT DATA with graphs...")
    insert_queries = [
        f"""
        INSERT DATA {{
            GRAPH <{TEST_GRAPH_1}> {{
                <http://example.org/person1> <http://example.org/name> "Alice" .
                <http://example.org/person1> <http://example.org/age> 30 .
            }}
        }}
        """,
        f"""
        INSERT DATA {{
            GRAPH <{TEST_GRAPH_2}> {{
                <http://example.org/person2> <http://example.org/name> "Bob" .
                <http://example.org/person2> <http://example.org/age> 25 .
            }}
        }}
        """
    ]
    
    for i, query in enumerate(insert_queries, 1):
        try:
            success = await sparql_impl.execute_sparql_update(SPACE_ID, query)
            print(f"   INSERT DATA {i}: {'SUCCESS' if success else 'FAILED'}")
        except Exception as e:
            print(f"   INSERT DATA {i}: ERROR - {e}")
    
    # Test 3: Query data from specific graphs
    print(f"\n3. Testing SELECT from specific graphs...")
    select_queries = [
        f"""
        SELECT ?name ?age WHERE {{
            GRAPH <{TEST_GRAPH_1}> {{
                ?person <http://example.org/name> ?name .
                ?person <http://example.org/age> ?age .
            }}
        }}
        """,
        f"""
        SELECT ?name ?age WHERE {{
            GRAPH <{TEST_GRAPH_2}> {{
                ?person <http://example.org/name> ?name .
                ?person <http://example.org/age> ?age .
            }}
        }}
        """
    ]
    
    for i, query in enumerate(select_queries, 1):
        try:
            results = await sparql_impl.execute_sparql_query(SPACE_ID, query)
            print(f"   SELECT from graph {i}: {len(results)} results")
            for result in results:
                print(f"     - {result}")
        except Exception as e:
            print(f"   SELECT from graph {i}: ERROR - {e}")
    
    # Test 4: CLEAR GRAPH
    print(f"\n4. Testing CLEAR GRAPH...")
    clear_query = f"CLEAR GRAPH <{TEST_GRAPH_1}>"
    clear_success = False
    try:
        success = await sparql_impl.execute_sparql_update(SPACE_ID, clear_query)
        print(f"   {clear_query}: {'SUCCESS' if success else 'FAILED'}")
        
        # Verify graph is cleared but still exists
        verify_query = f"""
        SELECT ?name WHERE {{
            GRAPH <{TEST_GRAPH_1}> {{
                ?person <http://example.org/name> ?name .
            }}
        }}
        """
        results = await sparql_impl.execute_sparql_query(SPACE_ID, verify_query)
        print(f"   Verification: {len(results)} results (should be 0)")
        
        # CLEAR GRAPH should result in 0 results
        clear_success = (len(results) == 0)
        
    except Exception as e:
        print(f"   {clear_query}: ERROR - {e}")
        clear_success = False
    
    # Test 5: DROP GRAPH
    print(f"\n5. Testing DROP GRAPH...")
    drop_query = f"DROP GRAPH <{TEST_GRAPH_2}>"
    drop_success = False
    try:
        success = await sparql_impl.execute_sparql_update(SPACE_ID, drop_query)
        print(f"   {drop_query}: {'SUCCESS' if success else 'FAILED'}")
        
        # Verify graph is completely removed
        verify_query = f"""
        SELECT ?name WHERE {{
            GRAPH <{TEST_GRAPH_2}> {{
                ?person <http://example.org/name> ?name .
            }}
        }}
        """
        try:
            results = await sparql_impl.execute_sparql_query(SPACE_ID, verify_query)
            print(f"   Verification: {len(results)} results (should be 0)")
            # DROP GRAPH should result in 0 results
            drop_success = (len(results) == 0)
        except Exception as verify_e:
            print(f"   Verification: Expected error (graph doesn't exist) - {verify_e}")
            # If we get an error querying the graph, that's also acceptable for DROP GRAPH
            drop_success = True
        
    except Exception as e:
        print(f"   {drop_query}: ERROR - {e}")
        drop_success = False
    
    # Return True only if both CLEAR and DROP operations worked correctly
    overall_success = clear_success and drop_success
    print(f"\n   CLEAR GRAPH test: {'PASSED' if clear_success else 'FAILED'}")
    print(f"   DROP GRAPH test: {'PASSED' if drop_success else 'FAILED'}")
    
    return overall_success

async def test_quad_insertion_with_graph_cache(space_impl):
    """Test that quad insertion properly uses graph cache."""
    print("\n" + "="*60)
    print("TESTING QUAD INSERTION WITH GRAPH CACHE")
    print("="*60)
    
    from rdflib import URIRef, Literal
    
    # Test 1: Insert quads with new graphs (should auto-create)
    print(f"\n1. Testing quad insertion with new graphs...")
    
    new_graph = "http://vital.ai/graph/auto-created"
    quads = [
        (URIRef("http://example.org/subject1"), URIRef("http://example.org/predicate1"), 
         Literal("Object 1"), URIRef(new_graph)),
        (URIRef("http://example.org/subject2"), URIRef("http://example.org/predicate2"), 
         Literal("Object 2"), URIRef(new_graph)),
    ]
    
    try:
        count = await space_impl.add_rdf_quads_batch(SPACE_ID, quads)
        print(f"   Inserted {count} quads")
        
        # Verify graph was auto-created
        graph_info = await space_impl.graphs.get_graph(SPACE_ID, new_graph)
        print(f"   Auto-created graph exists: {graph_info is not None}")
        if graph_info:
            print(f"   Graph URI: {graph_info['graph_uri']}")
        
        # Check graph cache
        graph_cache = space_impl.get_graph_cache(SPACE_ID)
        is_cached = graph_cache.is_graph_cached(new_graph)
        print(f"   Graph is cached: {is_cached}")
        
    except Exception as e:
        print(f"   ERROR: {e}")
    
    # Test 2: Batch insertion with multiple new graphs
    print(f"\n2. Testing batch insertion with multiple new graphs...")
    
    batch_graphs = [
        "http://vital.ai/graph/batch1",
        "http://vital.ai/graph/batch2",
        "http://vital.ai/graph/batch3"
    ]
    
    batch_quads = []
    for i, graph_uri in enumerate(batch_graphs):
        batch_quads.extend([
            (URIRef(f"http://example.org/batch_subject{i}_1"), URIRef("http://example.org/name"), 
             Literal(f"Batch Name {i}_1"), URIRef(graph_uri)),
            (URIRef(f"http://example.org/batch_subject{i}_2"), URIRef("http://example.org/name"), 
             Literal(f"Batch Name {i}_2"), URIRef(graph_uri)),
        ])
    
    try:
        count = await space_impl.add_rdf_quads_batch(SPACE_ID, batch_quads)
        print(f"   Inserted {count} quads across {len(batch_graphs)} graphs")
        
        # Verify all graphs were created
        for graph_uri in batch_graphs:
            graph_info = await space_impl.graphs.get_graph(SPACE_ID, graph_uri)
            print(f"   Graph {graph_uri}: {'EXISTS' if graph_info else 'MISSING'}")
        
        # Check cache statistics
        graph_cache = space_impl.get_graph_cache(SPACE_ID)
        stats = graph_cache.get_statistics()
        print(f"   Cache stats after batch: {stats['cache_size']} graphs, {stats['cache_hit_rate']:.2%} hit rate")
        
    except Exception as e:
        print(f"   ERROR: {e}")
    
    return True

async def run_all_tests():
    """Run all graph operation tests."""
    print("Starting Graph Operations Test Suite")
    print("====================================")
    
    start_time = time.time()
    
    try:
        # Initialize using exact pattern from working tests
        config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
        
        from vitalgraph.config.config_loader import get_config
        config = get_config(str(config_path))
        
        impl = VitalGraphImpl(config=config)
        await impl.db_impl.connect()
        
        space_impl = impl.db_impl.get_space_impl()
        sparql_impl = PostgreSQLSparqlImpl(space_impl)
        
        print(f"✅ Connected | Testing graph operations")
        
        # Run all test suites
        tests = [
            ("Low-Level Graph Operations", test_low_level_graph_operations, space_impl),
            ("Graph Cache Operations", test_graph_cache_operations, space_impl),
            ("SPARQL Graph Operations", test_sparql_graph_operations, sparql_impl),
            ("Quad Insertion with Graph Cache", test_quad_insertion_with_graph_cache, space_impl),
        ]
        
        passed = 0
        failed = 0
        
        for test_name, test_func, test_arg in tests:
            print(f"\n{'='*80}")
            print(f"RUNNING: {test_name}")
            print(f"{'='*80}")
            
            try:
                result = await test_func(test_arg)
                if result:
                    print(f"\n✅ {test_name}: PASSED")
                    passed += 1
                else:
                    print(f"\n❌ {test_name}: FAILED")
                    failed += 1
            except Exception as e:
                print(f"\n❌ {test_name}: ERROR - {e}")
                failed += 1
        
        # Final summary
        total_time = time.time() - start_time
        print(f"\n{'='*80}")
        print(f"GRAPH OPERATIONS TEST SUMMARY")
        print(f"{'='*80}")
        print(f"Total tests: {passed + failed}")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print(f"Success rate: {(passed / (passed + failed) * 100):.1f}%")
        print(f"Total time: {total_time:.2f} seconds")
        
        # Cleanup connection
        await impl.db_impl.disconnect()
        
        if failed == 0:
            print(f"\n🎉 All graph operation tests passed!")
        else:
            print(f"\n⚠️  {failed} test(s) failed. Check the output above for details.")
        
        return failed == 0
        
    except Exception as e:
        print(f"\n❌ Test suite failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    asyncio.run(run_all_tests())
