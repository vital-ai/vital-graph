#!/usr/bin/env python3
"""
Refactored SPARQL VALUES Implementation Test Script
==================================================

Tests the new refactored SPARQL implementation against the same VALUES queries
as the original test to verify functional parity.

This test directly instantiates the new PostgreSQLSparqlImpl class from:
vitalgraph.db.postgresql.sparql.postgres_sparql_impl

Compares results with the original implementation to ensure identical behavior
for SPARQL VALUES clause functionality.
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
    
    # Convert to sets of sorted tuples for comparison
    original_set = {tuple(sorted(dict(result).items())) for result in original}
    refactored_set = {tuple(sorted(dict(result).items())) for result in refactored}
    
    return original_set == refactored_set

async def test_refactored_values_queries():
    """Test refactored SPARQL implementation against original with VALUES clause queries."""
    print("🎯 Refactored SPARQL VALUES Implementation Test")
    print("=" * 60)
    
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
    
    # Create both SPARQL implementations for comparison
    original_sparql = OriginalSparqlImpl(space_impl)
    refactored_sparql = RefactoredSparqlImpl(space_impl)
    
    print(f"📊 Testing with space: {SPACE_ID}")
    print(f"📊 Original cache: {original_sparql.term_uuid_cache.size()} terms")
    print(f"📊 Refactored cache: {refactored_sparql.term_cache.size()} terms")
    
    # Track test results
    total_tests = 0
    passed_tests = 0
    
    print("\n1. BASIC VALUES QUERIES:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Simple single variable VALUES", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name WHERE {{
            VALUES ?name {{ "New York" "Los Angeles" "Chicago" }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?city ex:hasName ?name .
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Multi-variable VALUES with tuples", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?population WHERE {{
            VALUES (?name ?population) {{
                ("New York" 8336817)
                ("Los Angeles" 3979576)
                ("Chicago" 2693976)
            }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?city ex:hasName ?name ;
                     ex:hasPopulation ?population .
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "VALUES with string literals", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?country ?code WHERE {{
            VALUES (?country ?code) {{
                ("United States" "USA")
                ("Canada" "CAN")
                ("Mexico" "MEX")
            }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?nation ex:hasName ?country ;
                       ex:hasCode ?code .
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n2. VALUES WITH FILTER CONDITIONS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "VALUES with numeric filter", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?year WHERE {{
            VALUES (?name ?year) {{
                ("The Great Gatsby" 1925)
                ("To Kill a Mockingbird" 1960)
                ("1984" 1949)
                ("Pride and Prejudice" 1813)
            }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?book ex:hasName ?name ;
                     ex:hasYear ?year .
            }}
            FILTER(?year >= 1940 && ?year <= 1970)
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "VALUES with string filter", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?hex WHERE {{
            VALUES (?name ?hex) {{
                ("Red" "#FF0000")
                ("Green" "#00FF00")
                ("Blue" "#0000FF")
                ("Yellow" "#FFFF00")
            }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?color ex:hasName ?name ;
                      ex:hasHex ?hex .
            }}
            FILTER(CONTAINS(?name, "e"))
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n3. VALUES WITH OPTIONAL PATTERNS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "VALUES with optional ISBN", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?year ?isbn WHERE {{
            VALUES (?name ?year) {{
                ("The Great Gatsby" 1925)
                ("To Kill a Mockingbird" 1960)
                ("1984" 1949)
            }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?book ex:hasName ?name ;
                     ex:hasYear ?year .
                OPTIONAL {{
                    ?book ex:hasISBN ?isbn .
                }}
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "VALUES with optional color hex", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?hex WHERE {{
            VALUES ?name {{
                "Red" "Green" "Blue" "Yellow" "Orange" "Purple" "Pink" "Brown" "Gray" "Black"
                "White" "Cyan" "Magenta" "Lime" "Maroon" "Navy" "Olive" "Teal" "Silver" "Gold"
                "Indigo" "Violet" "Turquoise" "Coral" "Salmon"
            }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?color ex:hasName ?name .
                OPTIONAL {{
                    ?color ex:hasHex ?hex .
                }}
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n4. VALUES WITH UNION PATTERNS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "VALUES with UNION types", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?type WHERE {{
            VALUES ?name {{ "New York" "The Great Gatsby" "Red" }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                {{
                    ?entity ex:hasName ?name ;
                           a ex:City .
                    BIND("City" AS ?type)
                }} UNION {{
                    ?entity ex:hasName ?name ;
                           a ex:Book .
                    BIND("Book" AS ?type)
                }} UNION {{
                    ?entity ex:hasName ?name ;
                           a ex:Color .
                    BIND("Color" AS ?type)
                }}
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n5. VALUES WITH BIND EXPRESSIONS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "VALUES with BIND calculations", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?population ?populationMillion WHERE {{
            VALUES (?name ?population) {{
                ("New York" 8336817)
                ("Los Angeles" 3979576)
                ("Chicago" 2693976)
            }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?city ex:hasName ?name ;
                     ex:hasPopulation ?population .
            }}
            BIND(?population / 1000000.0 AS ?populationMillion)
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "VALUES with BIND string operations", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?code ?fullName WHERE {{
            VALUES (?name ?code) {{
                ("United States" "USA")
                ("Canada" "CAN")
                ("Mexico" "MEX")
            }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?country ex:hasName ?name ;
                        ex:hasCode ?code .
            }}
            BIND(CONCAT(?name, " (", ?code, ")") AS ?fullName)
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n6. COMPLEX VALUES QUERIES:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "VALUES with multiple graph patterns", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?cityName ?countryName ?population WHERE {{
            VALUES (?cityName ?countryCode) {{
                ("New York" "USA")
                ("Los Angeles" "USA")
                ("Chicago" "USA")
            }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?city ex:hasName ?cityName ;
                     ex:hasPopulation ?population ;
                     ex:hasCountry ?countryCode .
                ?country ex:hasCode ?countryCode ;
                        ex:hasName ?countryName .
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "VALUES with aggregation", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?countryCode (AVG(?population) AS ?avgPopulation) WHERE {{
            VALUES ?countryCode {{ "USA" }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?city ex:hasCountry ?countryCode ;
                     ex:hasPopulation ?population .
            }}
        }}
        GROUP BY ?countryCode
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n7. EDGE CASES AND ERROR HANDLING:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Single value in VALUES", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name WHERE {{
            VALUES ?name {{ "Red" "Green" "Blue" "Yellow" "Orange" }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?color ex:hasName ?name .
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Empty VALUES result", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name WHERE {{
            VALUES ?name {{ "NonExistentCity" "AnotherNonExistentCity" }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?city ex:hasName ?name .
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
    print("\n✅ Refactored SPARQL VALUES Implementation Test Complete!")
    
    return passed_tests == total_tests

if __name__ == "__main__":
    success = asyncio.run(test_refactored_values_queries())
    sys.exit(0 if success else 1)
