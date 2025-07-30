#!/usr/bin/env python3
"""
Refactored SPARQL Aggregate Implementation Test Script
====================================================

Tests the new refactored SPARQL implementation against the same aggregate queries
as the original test to verify functional parity.

This test directly instantiates the new PostgreSQLSparqlImpl class from:
vitalgraph.db.postgresql.sparql.postgres_sparql_impl

Compares results with the original implementation to ensure identical behavior
for aggregate functions (COUNT, SUM, AVG, MIN, MAX) with GROUP BY and HAVING.
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
logging.getLogger('vitalgraph.db.postgresql.postgresql_cache_term').setLevel(logging.WARNING)

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
    
    # Convert to sets of sorted tuples for comparison
    original_set = {tuple(sorted(dict(result).items())) for result in original}
    refactored_set = {tuple(sorted(dict(result).items())) for result in refactored}
    
    return original_set == refactored_set

async def test_refactored_agg_queries():
    """Test refactored SPARQL implementation against original with aggregate queries."""
    print("🧪 Refactored SPARQL Aggregate Implementation Test")
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
    
    print(f"✅ Connected | Space: {SPACE_ID}")
    print(f"📊 Original cache: {original_sparql.term_uuid_cache.size()} terms")
    print(f"📊 Refactored cache: {refactored_sparql.term_cache.size()} terms")
    
    # Test counters
    total_tests = 0
    passed_tests = 0
    
    print("\n1. BASIC COUNT FUNCTIONS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Count all people", f"""
        PREFIX ex: <http://example.org/>
        SELECT (COUNT(?person) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person a ex:Person .
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Count all products", f"""
        PREFIX ex: <http://example.org/>
        SELECT (COUNT(?product) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?product a ex:Product .
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Count distinct entities", f"""
        PREFIX ex: <http://example.org/>
        SELECT (COUNT(DISTINCT ?entity) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                {{ ?entity a ex:Person }} UNION {{ ?entity a ex:Product }}
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n2. NUMERIC AGGREGATES:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Sum of all ages", f"""
        PREFIX ex: <http://example.org/>
        SELECT (SUM(?age) AS ?totalAge) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Average age", f"""
        PREFIX ex: <http://example.org/>
        SELECT (AVG(?age) AS ?avgAge) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Min and max age", f"""
        PREFIX ex: <http://example.org/>
        SELECT (MIN(?age) AS ?minAge) (MAX(?age) AS ?maxAge) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n3. STRING AGGREGATES:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Alphabetically first and last names", f"""
        PREFIX ex: <http://example.org/>
        SELECT (MIN(?name) AS ?firstName) (MAX(?name) AS ?lastName) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n4. GROUP BY QUERIES:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Count employees by department", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?dept (COUNT(?employee) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?employee ex:hasDepartment ?dept .
            }}
        }}
        GROUP BY ?dept
        ORDER BY ?dept
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Average age by department", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?dept (AVG(?age) AS ?avgAge) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasDepartment ?dept ;
                        ex:hasAge ?age .
            }}
        }}
        GROUP BY ?dept
        ORDER BY ?dept
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Count products by type", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?type (COUNT(?product) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?product ex:hasType ?type .
            }}
        }}
        GROUP BY ?type
        ORDER BY ?type
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n5. HAVING CLAUSES:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Departments with more than 1 employee", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?dept (COUNT(?employee) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?employee ex:hasDepartment ?dept .
            }}
        }}
        GROUP BY ?dept
        HAVING (COUNT(?employee) > 1)
        ORDER BY ?dept
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Departments with average age > 25", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?dept (AVG(?age) AS ?avgAge) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasDepartment ?dept ;
                        ex:hasAge ?age .
            }}
        }}
        GROUP BY ?dept
        HAVING (AVG(?age) > 25)
        ORDER BY ?dept
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n6. COMPLEX AGGREGATES:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Complex aggregate with OPTIONAL", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?dept (COUNT(?person) AS ?personCount) (AVG(?age) AS ?avgAge) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasDepartment ?dept .
                OPTIONAL {{ ?person ex:hasAge ?age }}
            }}
        }}
        GROUP BY ?dept
        ORDER BY ?dept
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Aggregate with BIND", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?ageGroup (COUNT(?person) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
                BIND(IF(?age < 30, "Young", "Older") AS ?ageGroup)
            }}
        }}
        GROUP BY ?ageGroup
        ORDER BY ?ageGroup
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n7. ORDER BY WITH AGGREGATES:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Departments ordered by employee count", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?dept (COUNT(?employee) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?employee ex:hasDepartment ?dept .
            }}
        }}
        GROUP BY ?dept
        ORDER BY DESC(?count)
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Top 3 most expensive products", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?product ?price WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?product ex:hasPrice ?price .
            }}
        }}
        ORDER BY DESC(?price)
        LIMIT 3
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n8. NESTED AGGREGATES:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Count of departments with employees", f"""
        PREFIX ex: <http://example.org/>
        SELECT (COUNT(DISTINCT ?dept) AS ?deptWithEmployees) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?employee ex:hasDepartment ?dept .
            }}
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
    print("\n✅ Refactored SPARQL Aggregate Implementation Test Complete!")
    
    return passed_tests == total_tests

if __name__ == "__main__":
    success = asyncio.run(test_refactored_agg_queries())
    sys.exit(0 if success else 1)
