#!/usr/bin/env python3
"""
Refactored SPARQL Critical Built-in Functions Implementation Test Script
=======================================================================

Tests the new refactored SPARQL implementation against critical built-in functions
that are essential for SPARQL functionality.

Critical functions tested:
- BOUND(?var) - Check if variable is bound (essential for OPTIONAL)
- COALESCE(?var1, ?var2, "default") - Return first non-null value
- URI(string) / IRI(string) - Create URI from string
- ENCODE_FOR_URI(string) - URL encoding
- IF(condition, true_value, false_value) - Conditional expressions
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
                        print(f"      [{i+1}] {dict(item) if hasattr(item, 'keys') else item}")
                
                print("\n    Refactored sample:")
                if hasattr(refactored_results, '__iter__'):
                    for i, item in enumerate(list(refactored_results)[:2]):
                        print(f"      [{i+1}] {dict(item) if hasattr(item, 'keys') else item}")
        else:
            # Show first 2 results from refactored (should match original)
            if hasattr(refactored_results, '__iter__'):
                for i, item in enumerate(list(refactored_results)[:2]):
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

async def test_refactored_builtin_critical():
    """Test refactored SPARQL implementation against original with critical built-in functions."""
    print("🧪 REFACTORED SPARQL CRITICAL BUILT-IN FUNCTIONS TEST")
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
    print(f"📊 Testing critical SPARQL built-in functions on space: {SPACE_ID}")
    
    # Test counters
    total_tests = 0
    passed_tests = 0
    
    print("\n1. BOUND FUNCTION TESTS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Basic BOUND function", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?hasAge WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasAge ?age }}
                BIND(BOUND(?age) AS ?hasAge)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "BOUND with FILTER", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasAge ?age }}
                FILTER(BOUND(?age))
            }}
        }}
        ORDER BY ?name
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "NOT BOUND with FILTER", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasAge ?age }}
                FILTER(!BOUND(?age))
            }}
        }}
        ORDER BY ?name
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n2. COALESCE FUNCTION TESTS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Basic COALESCE function", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?contact WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasEmail ?email }}
                OPTIONAL {{ ?person ex:hasPhone ?phone }}
                BIND(COALESCE(?email, ?phone, "No contact") AS ?contact)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "COALESCE with multiple optionals", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?info WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasEmail ?email }}
                OPTIONAL {{ ?person ex:hasPhone ?phone }}
                OPTIONAL {{ ?person ex:hasAge ?age }}
                BIND(COALESCE(?email, ?phone, STR(?age), "Unknown") AS ?info)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n3. URI/IRI FUNCTION TESTS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Basic URI function", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?profileURI WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(URI(CONCAT("http://example.org/profile/", ?name)) AS ?profileURI)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "IRI function (alias for URI)", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?profileIRI WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(IRI(CONCAT("http://example.org/profile/", ?name)) AS ?profileIRI)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n4. ENCODE_FOR_URI FUNCTION TESTS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Basic ENCODE_FOR_URI function", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?encodedName WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(ENCODE_FOR_URI(?name) AS ?encodedName)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "ENCODE_FOR_URI with special characters", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?encodedURI WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(URI(CONCAT("http://example.org/profile/", ENCODE_FOR_URI(?name))) AS ?encodedURI)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n5. IF FUNCTION TESTS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Basic IF function", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?ageCategory WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasAge ?age }}
                BIND(IF(BOUND(?age), IF(?age >= 18, "Adult", "Minor"), "Unknown") AS ?ageCategory)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "IF with numeric comparison", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?age ?status WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                ?person ex:hasAge ?age .
                BIND(IF(?age > 30, "Senior", "Junior") AS ?status)
            }}
        }}
        ORDER BY ?age
        LIMIT 5
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n6. COMBINED CRITICAL FUNCTIONS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "BOUND + COALESCE + IF combination", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?contactInfo WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasEmail ?email }}
                OPTIONAL {{ ?person ex:hasPhone ?phone }}
                BIND(IF(BOUND(?email) || BOUND(?phone), 
                        COALESCE(?email, ?phone), 
                        "No contact available") AS ?contactInfo)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "URI + ENCODE_FOR_URI + COALESCE combination", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?safeProfileURI WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasEmail ?email }}
                BIND(COALESCE(?name, "anonymous") AS ?safeName)
                BIND(URI(CONCAT("http://example.org/profile/", ENCODE_FOR_URI(?safeName))) AS ?safeProfileURI)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
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
    print("\n✅ Refactored SPARQL Critical Built-in Functions Test Complete!")
    
    return passed_tests == total_tests

if __name__ == "__main__":
    success = asyncio.run(test_refactored_builtin_critical())
    sys.exit(0 if success else 1)
