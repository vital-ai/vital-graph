#!/usr/bin/env python3
"""
Refactored SPARQL Filter Implementation Test Script
==================================================

Tests the new refactored SPARQL implementation against the same filter queries
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

async def test_refactored_filter_queries():
    """Test refactored SPARQL implementation against original with filter queries."""
    print("🧪 REFACTORED SPARQL FILTER IMPLEMENTATION TEST")
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
    print(f"📊 Testing SPARQL filter queries on space: {SPACE_ID}")
    
    # Test counters
    total_tests = 0
    passed_tests = 0
    
    print("\n1. REGEX FILTER TESTS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Basic REGEX filter", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(REGEX(?name, "John"))
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "REGEX with flags", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(REGEX(?name, "john", "i"))
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Complex REGEX pattern", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(REGEX(?name, "^[A-Z][a-z]+"))
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n2. STRING FUNCTION FILTER TESTS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "CONTAINS function", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(CONTAINS(?name, "John"))
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "STRSTARTS function", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(STRSTARTS(?name, "J"))
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "STRENDS function", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(STRENDS(?name, "son"))
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n3. TYPE CHECKING FILTER TESTS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "isURI function", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(isURI(?person))
            }}
        }}
        LIMIT 5
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "isLITERAL function", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(isLITERAL(?name))
            }}
        }}
        LIMIT 5
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "isNUMERIC function", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
                FILTER(isNUMERIC(?age))
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n4. LANG AND DATATYPE FILTER TESTS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "LANG function", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(LANG(?name) = "en")
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "DATATYPE function", f"""
        PREFIX ex: <http://example.org/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?person ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
                FILTER(DATATYPE(?age) = xsd:integer)
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n5. URI/IRI FILTER TESTS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "URI function", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(?person = URI("http://example.org/person1"))
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "IRI function", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(?person = IRI("http://example.org/person1"))
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n6. COMPLEX FILTER COMBINATIONS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Multiple filter conditions", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name ;
                       ex:hasAge ?age .
                FILTER(REGEX(?name, "^J") && ?age > 25)
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "OR filter conditions", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(CONTAINS(?name, "John") || CONTAINS(?name, "Jane"))
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Nested filter expressions", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name ;
                       ex:hasAge ?age .
                FILTER((STRSTARTS(?name, "J") && ?age > 20) || (STRENDS(?name, "e") && ?age < 40))
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n7. FILTER EDGE CASES:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "BOUND function", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasAge ?age }}
                FILTER(BOUND(?age))
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "NOT BOUND function", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasAge ?age }}
                FILTER(!BOUND(?age))
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Complex REGEX with escaping", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?entity ?value WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?entity ex:hasProperty ?value .
                FILTER(REGEX(?value, "test\\\\d+"))
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
    print("\n✅ Refactored SPARQL Filter Implementation Test Complete!")
    
    return passed_tests == total_tests

if __name__ == "__main__":
    success = asyncio.run(test_refactored_filter_queries())
    sys.exit(0 if success else 1)
