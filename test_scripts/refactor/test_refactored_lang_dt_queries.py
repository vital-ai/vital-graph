#!/usr/bin/env python3
"""
Refactored SPARQL LANG/DT Implementation Test Script
===================================================

Tests the new refactored SPARQL implementation against the same LANG() and DATATYPE()
queries as the original test to verify functional parity.

This test directly instantiates the new PostgreSQLSparqlImpl class from:
vitalgraph.db.postgresql.sparql.postgres_sparql_impl

Compares results with the original implementation to ensure identical behavior.

The LANG() function extracts the language tag from language-tagged literals.
The DATATYPE() function returns the datatype URI of typed literals.
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
        
        # Handle both RDFLib Graph results and list results
        original_count = len(original_results) if original_results else 0
        refactored_count = len(refactored_results) if refactored_results else 0
        
        print(f"    {status} Original: {original_time:.3f}s | {original_count} results")
        print(f"    {status} Refactored: {refactored_time:.3f}s | {refactored_count} results")
        
        if not results_match:
            print(f"    ⚠️  RESULTS MISMATCH!")
            print(f"       Original count: {original_count}")
            print(f"       Refactored count: {refactored_count}")
            
            # Show sample differences for debugging
            if debug:
                print("\n    Original sample:")
                if hasattr(original_results, '__iter__'):
                    for i, item in enumerate(list(original_results)[:2]):
                        if hasattr(item, '__iter__') and len(item) == 3:  # Triple
                            s, p, o = item
                            print(f"      [{i+1}] {s} -> {p} -> {o}")
                        else:
                            print(f"      [{i+1}] {dict(item) if hasattr(item, 'keys') else item}")
                
                print("\n    Refactored sample:")
                if hasattr(refactored_results, '__iter__'):
                    for i, item in enumerate(list(refactored_results)[:2]):
                        if hasattr(item, '__iter__') and len(item) == 3:  # Triple
                            s, p, o = item
                            print(f"      [{i+1}] {s} -> {p} -> {o}")
                        else:
                            print(f"      [{i+1}] {dict(item) if hasattr(item, 'keys') else item}")
        else:
            # Show first 2 results from refactored (should match original)
            if hasattr(refactored_results, '__iter__'):
                for i, item in enumerate(list(refactored_results)[:2]):
                    if hasattr(item, '__iter__') and len(item) == 3:  # Triple
                        s, p, o = item
                        print(f"    [{i+1}] {s} -> {p} -> {o}")
                    else:
                        print(f"    [{i+1}] {dict(item) if hasattr(item, 'keys') else item}")
                if refactored_count > 2:
                    print(f"    ... +{refactored_count - 2} more")
        
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
    
    # Handle RDFLib Graph objects
    if hasattr(original, '__iter__') and hasattr(refactored, '__iter__'):
        # Convert to sets of tuples for comparison
        try:
            original_set = set()
            for item in original:
                if hasattr(item, '__iter__') and len(item) == 3:  # Triple
                    s, p, o = item
                    original_set.add((str(s), str(p), str(o)))
                elif hasattr(item, 'keys'):  # Dict-like result
                    original_set.add(tuple(sorted(dict(item).items())))
                else:
                    original_set.add(str(item))
            
            refactored_set = set()
            for item in refactored:
                if hasattr(item, '__iter__') and len(item) == 3:  # Triple
                    s, p, o = item
                    refactored_set.add((str(s), str(p), str(o)))
                elif hasattr(item, 'keys'):  # Dict-like result
                    refactored_set.add(tuple(sorted(dict(item).items())))
                else:
                    refactored_set.add(str(item))
            
            return original_set == refactored_set
        except:
            # Fallback to simple comparison
            return list(original) == list(refactored)
    
    return False

async def test_refactored_lang_dt_queries():
    """Test refactored SPARQL implementation against original with LANG/DT queries."""
    print("🧪 REFACTORED SPARQL LANG/DT IMPLEMENTATION TEST")
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
    print(f"📊 Testing SPARQL LANG/DT queries on space: {SPACE_ID}")
    
    # Test counters
    total_tests = 0
    passed_tests = 0
    
    print("\n1. BASIC LANG() FUNCTION TESTS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "LANG() function with language-tagged literals", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name ?lang WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                BIND(LANG(?name) AS ?lang)
            }}
        }}
        ORDER BY ?person
        LIMIT 10
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Filter by language tag", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(LANG(?name) = "en")
            }}
        }}
        ORDER BY ?name
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Filter by multiple language tags", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name ?lang WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                BIND(LANG(?name) AS ?lang)
                FILTER(LANG(?name) IN ("en", "fr", "es"))
            }}
        }}
        ORDER BY ?lang ?name
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "LANG() with empty language tag", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name ?lang WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                BIND(LANG(?name) AS ?lang)
                FILTER(LANG(?name) = "")
            }}
        }}
        ORDER BY ?name
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n2. BASIC DATATYPE() FUNCTION TESTS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "DATATYPE() function with typed literals", f"""
        PREFIX ex: <http://example.org/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?person ?age ?datatype WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
                BIND(DATATYPE(?age) AS ?datatype)
            }}
        }}
        ORDER BY ?person
        LIMIT 10
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Filter by datatype", f"""
        PREFIX ex: <http://example.org/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?person ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
                FILTER(DATATYPE(?age) = xsd:integer)
            }}
        }}
        ORDER BY ?age
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "DATATYPE() with string literals", f"""
        PREFIX ex: <http://example.org/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?person ?name ?datatype WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                BIND(DATATYPE(?name) AS ?datatype)
                FILTER(DATATYPE(?name) = xsd:string)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "DATATYPE() with boolean literals", f"""
        PREFIX ex: <http://example.org/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?person ?active ?datatype WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:isActive ?active .
                BIND(DATATYPE(?active) AS ?datatype)
            }}
        }}
        ORDER BY ?person
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n3. COMBINED LANG() AND DATATYPE() TESTS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Combined LANG() and DATATYPE() in same query", f"""
        PREFIX ex: <http://example.org/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?person ?name ?nameType ?age ?ageType WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                ?person ex:hasAge ?age .
                BIND(LANG(?name) AS ?nameType)
                BIND(DATATYPE(?age) AS ?ageType)
            }}
        }}
        ORDER BY ?person
        LIMIT 5
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Filter with both LANG() and DATATYPE()", f"""
        PREFIX ex: <http://example.org/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?person ?name ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                ?person ex:hasAge ?age .
                FILTER(LANG(?name) = "en" && DATATYPE(?age) = xsd:integer)
            }}
        }}
        ORDER BY ?name
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "OPTIONAL with LANG() and DATATYPE()", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?person ?name ?nameType ?age ?ageType WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                OPTIONAL {{ 
                    ?person ex:hasName ?name .
                    BIND(LANG(?name) AS ?nameType)
                }}
                OPTIONAL {{ 
                    ?person ex:hasAge ?age .
                    BIND(DATATYPE(?age) AS ?ageType)
                }}
            }}
        }}
        ORDER BY ?person
        LIMIT 10
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n4. EDGE CASES AND ERROR CONDITIONS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "LANG() on non-literal values", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT ?person ?type ?lang WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ?type .
                BIND(LANG(?type) AS ?lang)
            }}
        }}
        LIMIT 5
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "DATATYPE() on URI values", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT ?person ?type ?datatype WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ?type .
                BIND(DATATYPE(?type) AS ?datatype)
            }}
        }}
        LIMIT 5
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Complex filter with LANG() and string operations", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(LANG(?name) = "en" && CONTAINS(?name, "John"))
            }}
        }}
        ORDER BY ?name
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "LANG() with REGEX filter", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name ?lang WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                BIND(LANG(?name) AS ?lang)
                FILTER(REGEX(?lang, "^(en|fr)$"))
            }}
        }}
        ORDER BY ?lang ?name
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "DATATYPE() with numeric operations", f"""
        PREFIX ex: <http://example.org/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?person ?age ?datatype WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
                BIND(DATATYPE(?age) AS ?datatype)
                FILTER(DATATYPE(?age) = xsd:integer && ?age > 25)
            }}
        }}
        ORDER BY ?age
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n5. ADVANCED LANG/DT SCENARIOS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "CONSTRUCT with LANG() and DATATYPE()", f"""
        PREFIX ex: <http://example.org/>
        PREFIX meta: <http://example.org/meta#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        CONSTRUCT {{
            ?person meta:hasNameInfo ?nameInfo .
            ?nameInfo meta:value ?name .
            ?nameInfo meta:language ?lang .
            ?nameInfo meta:datatype ?datatype .
        }}
        WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                BIND(LANG(?name) AS ?lang)
                BIND(DATATYPE(?name) AS ?datatype)
                BIND(URI(CONCAT("http://example.org/nameinfo/", ENCODE_FOR_URI(?name))) AS ?nameInfo)
            }}
        }}
        LIMIT 5
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "GROUP BY with LANG() and DATATYPE()", f"""
        PREFIX ex: <http://example.org/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?lang ?datatype (COUNT(*) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                BIND(LANG(?name) AS ?lang)
                BIND(DATATYPE(?name) AS ?datatype)
            }}
        }}
        GROUP BY ?lang ?datatype
        ORDER BY ?lang ?datatype
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
    print("\n✅ Refactored SPARQL LANG/DT Implementation Test Complete!")
    
    return passed_tests == total_tests

if __name__ == "__main__":
    success = asyncio.run(test_refactored_lang_dt_queries())
    sys.exit(0 if success else 1)
