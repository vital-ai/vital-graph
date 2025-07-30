#!/usr/bin/env python3
"""
Refactored SPARQL OPTIONAL Implementation Test Script
====================================================

Tests the new refactored SPARQL implementation against the same OPTIONAL queries
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

async def test_refactored_optional_queries():
    """Test refactored SPARQL implementation against original with OPTIONAL queries."""
    print("🧪 REFACTORED SPARQL OPTIONAL IMPLEMENTATION TEST")
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
    print(f"📊 Testing SPARQL OPTIONAL queries on space: {SPACE_ID}")
    
    # Test counters
    total_tests = 0
    passed_tests = 0
    
    print("\n1. BASIC OPTIONAL PATTERNS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Simple OPTIONAL pattern", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?name ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?entity rdf:type ex:Person .
                ?entity ex:hasName ?name .
                OPTIONAL {{ ?entity ex:hasAge ?age }}
            }}
        }}
        ORDER BY ?name
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Multiple OPTIONAL patterns", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?name ?age ?email WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?entity rdf:type ex:Person .
                ?entity ex:hasName ?name .
                OPTIONAL {{ ?entity ex:hasAge ?age }}
                OPTIONAL {{ ?entity ex:hasEmail ?email }}
            }}
        }}
        ORDER BY ?name
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "OPTIONAL with FILTER", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?name ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?entity rdf:type ex:Person .
                ?entity ex:hasName ?name .
                OPTIONAL {{ 
                    ?entity ex:hasAge ?age 
                    FILTER(?age > 25)
                }}
            }}
        }}
        ORDER BY ?name
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n2. BOUND FUNCTION QUERIES:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "BOUND function with OPTIONAL", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?name ?hasAge WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?entity rdf:type ex:Person .
                ?entity ex:hasName ?name .
                OPTIONAL {{ ?entity ex:hasAge ?age }}
                BIND(BOUND(?age) AS ?hasAge)
            }}
        }}
        ORDER BY ?name
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "FILTER with BOUND", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?entity rdf:type ex:Person .
                ?entity ex:hasName ?name .
                OPTIONAL {{ ?entity ex:hasAge ?age }}
                FILTER(BOUND(?age))
            }}
        }}
        ORDER BY ?name
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "FILTER with NOT BOUND", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?entity rdf:type ex:Person .
                ?entity ex:hasName ?name .
                OPTIONAL {{ ?entity ex:hasAge ?age }}
                FILTER(!BOUND(?age))
            }}
        }}
        ORDER BY ?name
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n3. NESTED OPTIONAL PATTERNS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Nested OPTIONAL patterns", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?name ?age ?email ?phone WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?entity rdf:type ex:Person .
                ?entity ex:hasName ?name .
                OPTIONAL {{ 
                    ?entity ex:hasAge ?age 
                    OPTIONAL {{ ?entity ex:hasEmail ?email }}
                }}
                OPTIONAL {{ ?entity ex:hasPhone ?phone }}
            }}
        }}
        ORDER BY ?name
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Complex nested OPTIONAL with FILTER", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?name ?contact WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?entity rdf:type ex:Person .
                ?entity ex:hasName ?name .
                OPTIONAL {{ 
                    ?entity ex:hasAge ?age 
                    FILTER(?age > 30)
                    OPTIONAL {{ 
                        ?entity ex:hasEmail ?contact 
                        FILTER(CONTAINS(?contact, "@"))
                    }}
                }}
            }}
        }}
        ORDER BY ?name
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n4. OPTIONAL WITH BIND:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "OPTIONAL with BIND expressions", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?name ?ageCategory WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?entity rdf:type ex:Person .
                ?entity ex:hasName ?name .
                OPTIONAL {{ 
                    ?entity ex:hasAge ?age 
                    BIND(IF(?age < 30, "Young", "Mature") AS ?ageCategory)
                }}
            }}
        }}
        ORDER BY ?name
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "BIND with COALESCE and OPTIONAL", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?name ?contact WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?entity rdf:type ex:Person .
                ?entity ex:hasName ?name .
                OPTIONAL {{ ?entity ex:hasEmail ?email }}
                OPTIONAL {{ ?entity ex:hasPhone ?phone }}
                BIND(COALESCE(?email, ?phone, "No contact") AS ?contact)
            }}
        }}
        ORDER BY ?name
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n5. CROSS-GRAPH OPTIONAL:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Cross-graph OPTIONAL patterns", f"""
        PREFIX ex: <http://example.org/>
        PREFIX test: <http://example.org/test#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?name ?testInfo WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?entity rdf:type ex:Person .
                ?entity ex:hasName ?name .
            }}
            OPTIONAL {{
                GRAPH <{GRAPH_URI}> {{
                    ?entity test:hasInfo ?testInfo
                }}
            }}
        }}
        ORDER BY ?name
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n6. OPTIONAL WITH UNION:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "OPTIONAL with UNION - flexible contact lookup", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?name ?contact ?contactType WHERE {{
            {{
                GRAPH <{GLOBAL_GRAPH_URI}> {{
                    ?entity rdf:type ex:Person .
                    ?entity ex:hasName ?name .
                    OPTIONAL {{ 
                        ?entity ex:hasEmail ?contact 
                        BIND("email" AS ?contactType)
                    }}
                }}
            }}
            UNION
            {{
                GRAPH <{GLOBAL_GRAPH_URI}> {{
                    ?entity rdf:type ex:Organization .
                    ?entity ex:hasName ?name .
                    OPTIONAL {{ 
                        ?entity ex:hasWebsite ?contact 
                        BIND("website" AS ?contactType)
                    }}
                }}
            }}
        }}
        ORDER BY ?contactType ?name
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n7. COMPLEX OPTIONAL SCENARIOS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Organizations with optional project relationships", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?org ?orgName ?orgType ?project ?projectName WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?org rdf:type ex:Organization .
                ?org ex:hasName ?orgName .
                OPTIONAL {{ ?org ex:hasType ?orgType }}
                OPTIONAL {{
                    ?person ex:worksFor ?org .
                    ?person ex:memberOf ?project .
                    ?project ex:hasName ?projectName
                }}
            }}
        }}
        ORDER BY ?orgName ?projectName
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "CONSTRUCT with OPTIONAL - unified profiles", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?person ex:hasProfile ?profile .
            ?profile ex:displayName ?name .
            ?profile ex:contactMethod ?contact .
            ?profile ex:hasCompleteInfo ?complete .
        }}
        WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasEmail ?email }}
                OPTIONAL {{ ?person ex:hasPhone ?phone }}
            }}
            BIND(URI(CONCAT("http://example.org/profile/", ENCODE_FOR_URI(?name))) AS ?profile)
            BIND(COALESCE(?email, ?phone, "none") AS ?contact)
            BIND(IF(BOUND(?email) || BOUND(?phone), "yes", "no") AS ?complete)
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
    print("\n✅ Refactored SPARQL OPTIONAL Implementation Test Complete!")
    
    return passed_tests == total_tests

if __name__ == "__main__":
    success = asyncio.run(test_refactored_optional_queries())
    sys.exit(0 if success else 1)
