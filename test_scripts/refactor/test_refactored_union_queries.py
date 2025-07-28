#!/usr/bin/env python3
"""
Refactored SPARQL UNION Implementation Test Script
=================================================

Tests the new refactored SPARQL implementation against the same UNION queries
as the original test to verify functional parity.

This test directly instantiates the new PostgreSQLSparqlImpl class from:
vitalgraph.db.postgresql.sparql.postgres_sparql_impl

Compares results with the original implementation to ensure identical behavior
for UNION pattern queries.
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
SPACE_ID = "space_test"
GRAPH_URI = "http://vital.ai/graph/test"
GLOBAL_GRAPH_URI = "urn:___GLOBAL"

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
    
    # Convert to sorted lists of dictionaries for comparison
    original_sorted = sorted([dict(result) for result in original], key=str)
    refactored_sorted = sorted([dict(result) for result in refactored], key=str)
    
    return original_sorted == refactored_sorted

async def test_refactored_union_queries():
    """Test refactored SPARQL implementation against original with UNION pattern queries."""
    print("🔄 Testing Refactored SPARQL Implementation - UNION Queries")
    print("=" * 70)
    
    # Initialize VitalGraph implementation
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    # Get space implementation
    space_impl = impl.db_impl.get_space_impl()
    if not space_impl:
        print("❌ Could not get space implementation")
        return False
    
    # Create both SPARQL implementations
    original_sparql = OriginalSparqlImpl(space_impl)
    refactored_sparql = RefactoredSparqlImpl(space_impl)
    
    print(f"✅ Connected to database")
    print(f"📊 Testing space: {SPACE_ID}")
    print(f"🔗 Graph URI: {GRAPH_URI}")
    print(f"🌐 Global Graph URI: {GLOBAL_GRAPH_URI}")
    
    # Test counters
    total_tests = 0
    passed_tests = 0
    
    print("\n1. BASIC UNION QUERIES:")
    
    # Test 1: Simple UNION - two different predicates
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Simple UNION - names OR titles", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?value WHERE {{
            GRAPH <{GRAPH_URI}> {{
                {{
                    ?entity test:hasName ?value .
                }} UNION {{
                    ?entity test:hasTitle ?value .
                }}
            }}
        }}
        ORDER BY ?entity ?value
        LIMIT 10
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    # Test 2: UNION with different variable names
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "UNION with different variables", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?name ?age WHERE {{
            GRAPH <{GRAPH_URI}> {{
                {{
                    ?entity test:hasName ?name .
                    ?entity test:hasAge ?age .
                }} UNION {{
                    ?entity test:hasTitle ?name .
                    ?entity test:hasYear ?age .
                }}
            }}
        }}
        ORDER BY ?entity
        LIMIT 8
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    # Test 3: Cross-graph UNION
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Cross-graph UNION", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?name WHERE {{
            {{
                GRAPH <{GRAPH_URI}> {{
                    ?entity test:hasName ?name .
                }}
            }} UNION {{
                GRAPH <{GLOBAL_GRAPH_URI}> {{
                    ?entity ex:hasName ?name .
                }}
            }}
        }}
        ORDER BY ?name
        LIMIT 12
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n2. UNION WITH FILTERS:")
    
    # Test 4: UNION with FILTER in one branch
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "UNION with FILTER", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?value WHERE {{
            GRAPH <{GRAPH_URI}> {{
                {{
                    ?entity test:hasName ?value .
                    FILTER(CONTAINS(?value, "test"))
                }} UNION {{
                    ?entity test:hasCategory ?value .
                }}
            }}
        }}
        ORDER BY ?value
        LIMIT 8
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    # Test 5: UNION with numeric filters
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "UNION with numeric filters", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?value WHERE {{
            GRAPH <{GRAPH_URI}> {{
                {{
                    ?entity test:hasAge ?value .
                    FILTER(?value > 25)
                }} UNION {{
                    ?entity test:hasYear ?value .
                    FILTER(?value < 2000)
                }}
            }}
        }}
        ORDER BY ?value
        LIMIT 10
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n3. UNION WITH BIND:")
    
    # Test 6: UNION with BIND expressions
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "UNION with BIND expressions", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?value ?type WHERE {{
            GRAPH <{GRAPH_URI}> {{
                {{
                    ?entity test:hasName ?value .
                    BIND("name" AS ?type)
                }} UNION {{
                    ?entity test:hasCategory ?value .
                    BIND("category" AS ?type)
                }}
            }}
        }}
        ORDER BY ?type ?value
        LIMIT 10
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    # Test 7: Complex UNION with BIND and FILTER
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Complex UNION with BIND and FILTER", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?item ?value ?reason WHERE {{
            GRAPH <{GRAPH_URI}> {{
                {{
                    ?item test:hasName ?value .
                    FILTER(STRLEN(?value) < 10)
                    BIND("short_name" AS ?reason)
                }} UNION {{
                    ?item test:hasValue ?value .
                    FILTER(?value > 25)
                    BIND("high_value" AS ?reason)
                }}
            }}
        }}
        ORDER BY ?reason ?value
        LIMIT 10
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n4. UNION WITH CONSTRUCT:")
    
    # Test 8: CONSTRUCT with UNION
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "CONSTRUCT with UNION", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity ex:unifiedLabel ?label .
            ?entity ex:sourceType ?sourceType .
        }}
        WHERE {{
            {{
                GRAPH <{GRAPH_URI}> {{
                    ?entity test:hasName ?label .
                    BIND("test_entity" AS ?sourceType)
                }}
            }} UNION {{
                GRAPH <{GLOBAL_GRAPH_URI}> {{
                    ?entity ex:hasName ?label .
                    BIND("global_person" AS ?sourceType)
                }}
            }}
        }}
        LIMIT 8
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n5. UNION WITH RELATIONSHIPS:")
    
    # Test 9: UNION for different relationship types
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Relationship UNION", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity1 ?entity2 ?relationship WHERE {{
            {{
                GRAPH <{GRAPH_URI}> {{
                    ?entity1 test:relatedTo ?entity2 .
                    BIND("related" AS ?relationship)
                }}
            }} UNION {{
                GRAPH <{GLOBAL_GRAPH_URI}> {{
                    ?entity1 ex:knows ?entity2 .
                    BIND("knows" AS ?relationship)
                }}
            }}
        }}
        ORDER BY ?relationship ?entity1
        LIMIT 10
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    # Test 10: Complex multi-pattern UNION branches
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Complex multi-pattern UNION", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?subject ?predicate ?object ?context WHERE {{
            {{
                GRAPH <{GRAPH_URI}> {{
                    ?subject rdf:type test:TestEntity .
                    ?subject test:hasName ?name .
                    ?subject test:hasCategory ?category .
                    BIND(?subject AS ?subject)
                    BIND(test:hasName AS ?predicate)
                    BIND(?name AS ?object)
                    BIND("test_names" AS ?context)
                }}
            }} UNION {{
                GRAPH <{GLOBAL_GRAPH_URI}> {{
                    ?person rdf:type ex:Person .
                    ?person ex:hasName ?personName .
                    ?person ex:hasAge ?age .
                    BIND(?person AS ?subject)
                    BIND(ex:hasName AS ?predicate)
                    BIND(?personName AS ?object)
                    BIND("global_persons" AS ?context)
                }}
            }}
        }}
        ORDER BY ?context ?subject
        LIMIT 12
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n6. NESTED AND COMPLEX UNION:")
    
    # Test 11: Triple nested UNION
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Triple nested UNION", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?value ?type WHERE {{
            GRAPH <{GRAPH_URI}> {{
                {{
                    ?entity test:hasName ?value .
                    BIND("name" AS ?type)
                }} UNION {{
                    ?entity test:hasCategory ?value .
                    BIND("category" AS ?type)
                }} UNION {{
                    ?entity test:hasDescription ?value .
                    BIND("description" AS ?type)
                }}
            }}
        }}
        ORDER BY ?type ?entity
        LIMIT 15
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    # Test 12: UNION with OPTIONAL
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "UNION with OPTIONAL", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?name ?optional_value WHERE {{
            GRAPH <{GRAPH_URI}> {{
                {{
                    ?entity test:hasName ?name .
                    OPTIONAL {{ ?entity test:hasAge ?optional_value }}
                }} UNION {{
                    ?entity test:hasTitle ?name .
                    OPTIONAL {{ ?entity test:hasYear ?optional_value }}
                }}
            }}
        }}
        ORDER BY ?name
        LIMIT 10
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
    print("\n✅ Refactored SPARQL UNION Implementation Test Complete!")
    
    return passed_tests == total_tests

if __name__ == "__main__":
    success = asyncio.run(test_refactored_union_queries())
    sys.exit(0 if success else 1)
