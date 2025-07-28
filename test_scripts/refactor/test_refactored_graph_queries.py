#!/usr/bin/env python3
"""
Refactored SPARQL Implementation Test Script
===========================================

Tests the new refactored SPARQL implementation against the same queries
as the original test to verify functional parity.

This test directly instantiates the new PostgreSQLSparqlImpl class from:
vitalgraph.db.postgresql.sparql.postgres_sparql_impl

Compares results with the original implementation to ensure identical behavior.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl

# Import BOTH implementations for comparison
from vitalgraph.db.postgresql.postgresql_sparql_impl import PostgreSQLSparqlImpl as OriginalSparqlImpl
from vitalgraph.db.postgresql.sparql.postgres_sparql_impl import PostgreSQLSparqlImpl as RefactoredSparqlImpl

# Reduce logging chatter
logging.getLogger('vitalgraph.db.postgresql.postgresql_space_impl').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.rdf.rdf_utils').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.db.postgresql.postgresql_term_cache').setLevel(logging.WARNING)

# Configuration
SPACE_ID = "wordnet_space"
GRAPH_URI = "http://vital.ai/graph/wordnet"

async def run_comparison_query(original_impl, refactored_impl, name, sparql, debug=False):
    """Execute a SPARQL query on both implementations and compare results."""
    print(f"\n  🔄 {name}:")
    
    if debug:
        print(f"\n🔍 DEBUG QUERY: {name}")
        print("=" * 60)
        print("SPARQL:")
        print(sparql)
        print("\n" + "-" * 60)
    
    original_results = None
    refactored_results = None
    original_time = 0
    refactored_time = 0
    
    try:
        # Run on original implementation
        start_time = time.time()
        original_results = await original_impl.execute_sparql_query(SPACE_ID, sparql)
        original_time = time.time() - start_time
        
        # Run on refactored implementation
        start_time = time.time()
        refactored_results = await refactored_impl.execute_sparql_query(SPACE_ID, sparql)
        refactored_time = time.time() - start_time
        
        # Compare results
        results_match = compare_results(original_results, refactored_results)
        
        # Display results
        status = "✅" if results_match else "❌"
        print(f"    {status} Original: {original_time:.3f}s | {len(original_results) if original_results else 0} results")
        print(f"    {status} Refactored: {refactored_time:.3f}s | {len(refactored_results) if refactored_results else 0} results")
        
        if not results_match:
            print(f"    ⚠️  RESULTS MISMATCH!")
            print(f"       Original count: {len(original_results) if original_results else 0}")
            print(f"       Refactored count: {len(refactored_results) if refactored_results else 0}")
            
            # Show sample differences
            if debug:
                print("\n    Original sample:")
                for i, result in enumerate((original_results or [])[:2]):
                    print(f"      [{i+1}] {dict(result)}")
                print("\n    Refactored sample:")
                for i, result in enumerate((refactored_results or [])[:2]):
                    print(f"      [{i+1}] {dict(result)}")
        else:
            # Show first 2 results from refactored (should match original)
            for i, result in enumerate((refactored_results or [])[:2]):
                print(f"    [{i+1}] {dict(result)}")
            if refactored_results and len(refactored_results) > 2:
                print(f"    ... +{len(refactored_results) - 2} more")
        
        return results_match
        
    except Exception as e:
        print(f"    ❌ Error: {e}")
        if debug:
            import traceback
            traceback.print_exc()
        return False

def compare_results(original, refactored):
    """Compare two result sets for functional equivalence."""
    if original is None and refactored is None:
        return True
    if original is None or refactored is None:
        return False
    if len(original) != len(refactored):
        return False
    
    # Convert to comparable format (sort by string representation for consistency)
    original_sorted = sorted([dict(r) for r in original], key=str)
    refactored_sorted = sorted([dict(r) for r in refactored], key=str)
    
    return original_sorted == refactored_sorted

async def test_refactored_graph_queries():
    """Test refactored SPARQL implementation against original with GRAPH pattern queries."""
    print("🧪 Refactored SPARQL Implementation Test")
    print("=" * 60)
    print("Comparing Original vs Refactored SPARQL implementations")
    print("=" * 60)
    
    # Initialize
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    space_impl = impl.db_impl.get_space_impl()
    
    # Create both implementations
    original_sparql = OriginalSparqlImpl(space_impl)
    refactored_sparql = RefactoredSparqlImpl(space_impl)
    
    print(f"✅ Connected | Graph: {GRAPH_URI}")
    print(f"📊 Original cache: {original_sparql.term_uuid_cache.size()} terms")
    print(f"📊 Refactored cache: {refactored_sparql.term_cache.size()} terms")
    
    # Track test results
    total_tests = 0
    passed_tests = 0
    
    # Test queries focused on GRAPH patterns
    print("\n1. NAMED GRAPH QUERIES:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql, 
        "Count entities in WordNet graph", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT (COUNT(?entity) AS ?count) WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Entities with names in WordNet graph", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT ?entity ?name WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity <http://vital.ai/ontology/vital-core#hasName> ?name .
            }}
            FILTER(CONTAINS(?name, "happy"))
        }}
        LIMIT 5
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n2. VARIABLE GRAPH QUERIES:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Count entities by graph", """
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT ?g (COUNT(?entity) AS ?count) WHERE {
            GRAPH ?g {
                ?entity rdf:type haley:KGEntity .
            }
        }
        GROUP BY ?g
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Variable graph with filtered entities", """
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT ?g ?entity ?name WHERE {
            GRAPH ?g {
                ?entity rdf:type haley:KGEntity .
                ?entity <http://vital.ai/ontology/vital-core#hasName> ?name .
            }
            FILTER(CONTAINS(?name, "happy"))
        }
        LIMIT 3
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n3. GLOBAL GRAPH QUERIES:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Query global graph directly", """
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT ?person ?name ?age WHERE {
            GRAPH <urn:___GLOBAL> {
                ?person rdf:type <http://example.org/Person> .
                ?person <http://example.org/hasName> ?name .
                ?person <http://example.org/hasAge> ?age .
            }
        }
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Global graph relationships", """
        SELECT ?person1 ?name1 ?person2 ?name2 WHERE {
            GRAPH <urn:___GLOBAL> {
                ?person1 <http://example.org/knows> ?person2 .
                ?person1 <http://example.org/hasName> ?name1 .
                ?person2 <http://example.org/hasName> ?name2 .
            }
        }
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Global test entities", """
        SELECT ?entity ?value WHERE {
            GRAPH <urn:___GLOBAL> {
                ?entity <http://example.org/hasProperty> ?value .
            }
        }
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n4. DEFAULT GRAPH UNION QUERIES:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Default graph union - should include both named and global data", """
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT ?s ?p ?o WHERE {
            ?s ?p ?o .
            FILTER(
                ?s = <http://example.org/person/alice> ||
                ?s = <http://vital.ai/haley.ai/chat-saas/KGEntity/1447109393012_1265235442>
            )
        }
        LIMIT 10
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Count all entities across all graphs (union)", """
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT (COUNT(?entity) AS ?count) WHERE {
            {
                ?entity rdf:type haley:KGEntity .
            } UNION {
                ?entity rdf:type <http://example.org/Person> .
            }
        }
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n5. COMPLEX GRAPH PATTERNS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Graph with connected entities", f"""
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT ?entity ?name ?edge ?connected WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity <http://vital.ai/ontology/vital-core#hasName> ?name .
                ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeSource> ?entity .
                ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeDestination> ?connected .
            }}
            FILTER(CONTAINS(?name, "happy"))
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    # Final comparison summary
    print(f"\n📊 FINAL COMPARISON SUMMARY:")
    print(f"   Total tests: {total_tests}")
    print(f"   Passed: {passed_tests}")
    print(f"   Failed: {total_tests - passed_tests}")
    print(f"   Success rate: {(passed_tests/total_tests)*100:.1f}%")
    
    if passed_tests == total_tests:
        print(f"\n🎉 ALL TESTS PASSED - FUNCTIONAL PARITY VERIFIED!")
        print(f"✅ Refactored implementation produces identical results to original")
    else:
        print(f"\n⚠️  {total_tests - passed_tests} TEST(S) FAILED - INVESTIGATE DIFFERENCES")
    
    # Performance summary
    print(f"\n📊 Final cache sizes:")
    print(f"   Original: {original_sparql.term_uuid_cache.size()} terms")
    print(f"   Refactored: {refactored_sparql.term_cache.size()} terms")
    
    await impl.db_impl.disconnect()
    print("\n✅ Refactored SPARQL Implementation Test Complete!")
    
    return passed_tests == total_tests

if __name__ == "__main__":
    success = asyncio.run(test_refactored_graph_queries())
    sys.exit(0 if success else 1)
