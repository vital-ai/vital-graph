#!/usr/bin/env python3
"""
Refactored SPARQL Property Path Implementation Test Script
=========================================================

Tests the new refactored SPARQL implementation against the same property path queries
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

async def test_refactored_property_path_queries():
    """Test refactored SPARQL implementation against original with property path queries."""
    print("🧪 REFACTORED SPARQL PROPERTY PATH IMPLEMENTATION TEST")
    print("=" * 60)
    
    # Initialize
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    space_impl = impl.db_impl.get_space_impl()
    
    # Initialize BOTH implementations with the same space_impl
    original_sparql = OriginalSparqlImpl(space_impl)
    refactored_sparql = RefactoredSparqlImpl(space_impl)
    
    print(f"🔌 Connected to database")
    print(f"📊 Testing SPARQL property path queries on space: {SPACE_ID}")
    
    # Test counters
    total_tests = 0
    passed_tests = 0
    
    print("\n1. BASIC PROPERTY PATH TESTS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Basic knows relationships", f"""
        PREFIX ex: <http://example.org/>
        
        SELECT ?person1 ?person2 ?name1 ?name2
        WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person1 ex:knows ?person2 .
                ?person1 ex:hasName ?name1 .
                ?person2 ex:hasName ?name2 .
            }}
        }}
        ORDER BY ?name1 ?name2
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n2. TRANSITIVE PATH TESTS (+, *):")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Transitive plus path (one or more)", f"""
        PREFIX ex: <http://example.org/>
        
        SELECT ?person1 ?person2 ?name1 ?name2
        WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person1 ex:knows+ ?person2 .
                ?person1 ex:hasName ?name1 .
                ?person2 ex:hasName ?name2 .
                FILTER(?person1 != ?person2)
            }}
        }}
        ORDER BY ?name1 ?name2
        LIMIT 10
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Transitive star path (zero or more)", f"""
        PREFIX ex: <http://example.org/>
        
        SELECT ?person1 ?person2 ?name1 ?name2
        WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person1 ex:knows* ?person2 .
                ?person1 ex:hasName ?name1 .
                ?person2 ex:hasName ?name2 .
            }}
        }}
        ORDER BY ?name1 ?name2
        LIMIT 10
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Management hierarchy (manages+)", f"""
        PREFIX ex: <http://example.org/>
        
        SELECT ?manager ?employee ?managerName ?employeeName
        WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?manager ex:manages+ ?employee .
                ?manager ex:hasName ?managerName .
                ?employee ex:hasName ?employeeName .
                FILTER(?manager != ?employee)
            }}
        }}
        ORDER BY ?managerName ?employeeName
        LIMIT 10
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n3. SEQUENCE PATH TESTS (/):")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Sequence path (knows/hasName)", f"""
        PREFIX ex: <http://example.org/>
        
        SELECT ?person ?name
        WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:knows/ex:hasName ?name .
            }}
        }}
        ORDER BY ?name
        LIMIT 10
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Complex sequence path (knows+/hasName)", f"""
        PREFIX ex: <http://example.org/>
        
        SELECT ?person ?name
        WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:knows+/ex:hasName ?name .
            }}
        }}
        ORDER BY ?name
        LIMIT 10
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Location hierarchy sequence", f"""
        PREFIX ex: <http://example.org/>
        
        SELECT ?building ?locationName
        WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?building ex:locatedIn+/ex:hasName ?locationName .
            }}
        }}
        ORDER BY ?locationName
        LIMIT 10
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n4. ALTERNATIVE PATH TESTS (|):")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Alternative transport routes", f"""
        PREFIX ex: <http://example.org/>
        
        SELECT ?station ?destination ?stationName ?destName
        WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?station (ex:busRoute|ex:trainRoute|ex:subwayRoute) ?destination .
                ?station ex:hasName ?stationName .
                ?destination ex:hasName ?destName .
            }}
        }}
        ORDER BY ?stationName ?destName
        LIMIT 10
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Alternative management paths", f"""
        PREFIX ex: <http://example.org/>
        
        SELECT ?manager ?employee ?managerName ?employeeName
        WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?manager (ex:manages|ex:supervises) ?employee .
                ?manager ex:hasName ?managerName .
                ?employee ex:hasName ?employeeName .
            }}
        }}
        ORDER BY ?managerName ?employeeName
        LIMIT 10
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Alternative paths with transitive", f"""
        PREFIX ex: <http://example.org/>
        
        SELECT ?person ?other ?personName ?otherName
        WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person (ex:knows|ex:directlyKnows)+ ?other .
                ?person ex:hasName ?personName .
                ?other ex:hasName ?otherName .
                FILTER(?person != ?other)
            }}
        }}
        ORDER BY ?personName ?otherName
        LIMIT 10
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n5. INVERSE PATH TESTS (~):")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Inverse paths (child ~parentOf parent)", f"""
        PREFIX ex: <http://example.org/>
        
        SELECT ?child ?parent ?childName ?parentName
        WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?child ~ex:parentOf ?parent .
                ?child ex:hasName ?childName .
                ?parent ex:hasName ?parentName .
            }}
        }}
        ORDER BY ?childName ?parentName
        LIMIT 10
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Inverse paths with transitive", f"""
        PREFIX ex: <http://example.org/>
        
        SELECT ?employee ?manager ?employeeName ?managerName
        WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?employee ~ex:manages+ ?manager .
                ?employee ex:hasName ?employeeName .
                ?manager ex:hasName ?managerName .
                FILTER(?employee != ?manager)
            }}
        }}
        ORDER BY ?employeeName ?managerName
        LIMIT 10
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n6. NEGATED PATH TESTS (!):")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Negated paths (people who don't know each other)", f"""
        PREFIX ex: <http://example.org/>
        
        SELECT ?person1 ?person2 ?name1 ?name2
        WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person1 !ex:knows ?person2 .
                ?person1 ex:hasName ?name1 .
                ?person2 ex:hasName ?name2 .
                FILTER(?person1 != ?person2)
            }}
        }}
        ORDER BY ?name1 ?name2
        LIMIT 10
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n7. COMPLEX COMBINATION TESTS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Complex academic relationships", f"""
        PREFIX ex: <http://example.org/>
        
        SELECT ?person ?related ?personName ?relatedName
        WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person (ex:advisedBy|ex:collaboratesWith)+/ex:knows* ?related .
                ?person ex:hasName ?personName .
                ?related ex:hasName ?relatedName .
                FILTER(?person != ?related)
            }}
        }}
        ORDER BY ?personName ?relatedName
        LIMIT 5
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Nested sequence with alternatives", f"""
        PREFIX ex: <http://example.org/>
        
        SELECT ?station ?name
        WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?station (ex:busRoute|ex:trainRoute)+/ex:hasName ?name .
            }}
        }}
        ORDER BY ?name
        LIMIT 10
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n8. ZERO-OR-MORE AND SELF-REFERENTIAL TESTS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Zero-or-more self-referential", f"""
        PREFIX ex: <http://example.org/>
        
        SELECT ?person ?name
        WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:knows* ?person .
                ?person ex:hasName ?name .
            }}
        }}
        ORDER BY ?name
        LIMIT 10
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n9. CYCLE DETECTION TESTS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Cycle detection in transitive paths", f"""
        PREFIX ex: <http://example.org/>
        
        SELECT ?person ?name
        WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ex:Alice ex:knows+ ex:Alice .
                ex:Alice ex:hasName ?name .
                BIND(ex:Alice AS ?person)
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
    print("\n✅ Refactored SPARQL Property Path Implementation Test Complete!")
    
    return passed_tests == total_tests

if __name__ == "__main__":
    success = asyncio.run(test_refactored_property_path_queries())
    sys.exit(0 if success else 1)
