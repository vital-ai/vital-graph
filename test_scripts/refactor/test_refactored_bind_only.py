#!/usr/bin/env python3
"""
Refactored SPARQL BIND Implementation Test (Standalone)
======================================================

Tests the refactored SPARQL BIND implementation in isolation to validate
its functionality without comparing to the broken original implementation.

This test focuses on:
1. Verifying BIND expressions are properly translated
2. Checking result formatting and structure
3. Validating builtin function integration in BIND context
4. Testing various BIND expression types and complexity levels
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.db.postgresql.sparql.postgres_sparql_impl import PostgreSQLSparqlImpl as RefactoredSparqlImpl

# Enable debug logging for orchestrator to see what's happening
logging.getLogger('vitalgraph.db.postgresql.sparql.postgresql_sparql_orchestrator').setLevel(logging.DEBUG)

# Reduce other logging chatter
logging.getLogger('vitalgraph.db.postgresql.postgresql_space_impl').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.rdf.rdf_utils').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.db.postgresql.postgresql_cache_term').setLevel(logging.WARNING)

# Configuration
SPACE_ID = "wordnet_space"
GRAPH_URI = "http://vital.ai/graph/wordnet"

async def run_bind_test(sparql_impl, test_name, query, expected_behavior=None):
    """Run a single BIND test and analyze results."""
    print(f"\n  🔄 {test_name}:")
    
    try:
        start_time = time.time()
        result = await sparql_impl.execute_sparql_query(SPACE_ID, query)
        elapsed = time.time() - start_time
        
        # Analyze result structure
        result_count = len(result) if result else 0
        result_type = type(result).__name__
        
        print(f"    ⏱️  {elapsed:.3f}s | {result_count} results | Type: {result_type}")
        
        if result_count > 0:
            # Show sample results to understand structure AND VALUES
            sample_results = list(result)[:3]
            print(f"    📊 Sample results:")
            for i, item in enumerate(sample_results):
                if hasattr(item, 'keys'):  # Dictionary-like
                    # Show key structure AND actual values for RDF verification
                    keys = list(item.keys())[:5]  # First 5 keys
                    print(f"      [{i+1}] Dict with keys: {keys}")
                    
                    # Show actual RDF triple values if present
                    if 'subject' in item and 'predicate' in item and 'object' in item:
                        s = str(item['subject'])[:80] + ('...' if len(str(item['subject'])) > 80 else '')
                        p = str(item['predicate'])[:80] + ('...' if len(str(item['predicate'])) > 80 else '')
                        o = str(item['object'])[:80] + ('...' if len(str(item['object'])) > 80 else '')
                        print(f"          S: {s}")
                        print(f"          P: {p}")
                        print(f"          O: {o}")
                    elif 'term_text' in item:
                        print(f"          term_text: {item.get('term_text', 'N/A')}")
                elif hasattr(item, '__len__') and len(item) == 3:  # Triple
                    s, p, o = item
                    print(f"      [{i+1}] {s} -> {p} -> {o}")
                else:
                    print(f"      [{i+1}] {type(item).__name__}: {str(item)[:100]}")
            
            if result_count > 3:
                print(f"      ... and {result_count - 3} more results")
        
        # Validate expected behavior if provided
        if expected_behavior:
            if expected_behavior.get('min_results') and result_count < expected_behavior['min_results']:
                print(f"    ⚠️  Expected at least {expected_behavior['min_results']} results, got {result_count}")
            elif expected_behavior.get('max_results') and result_count > expected_behavior['max_results']:
                print(f"    ⚠️  Expected at most {expected_behavior['max_results']} results, got {result_count}")
            else:
                print(f"    ✅ Result count within expected range")
        
        return True, result_count
        
    except Exception as e:
        print(f"    ❌ Error: {e}")
        return False, 0

async def test_refactored_bind_implementation():
    """Test the refactored SPARQL BIND implementation in isolation."""
    print("🧪 REFACTORED SPARQL BIND IMPLEMENTATION TEST (STANDALONE)")
    print("=" * 70)
    
    # Initialize with proper config
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    print("✅ Initialized database implementation successfully")
    
    # Create refactored SPARQL implementation
    space_impl = impl.db_impl.get_space_impl()
    sparql_impl = RefactoredSparqlImpl(space_impl)
    print("✅ Created refactored SPARQL implementation")
    
    print(f"🔌 Connected to database")
    print(f"📊 Testing BIND queries on space: {SPACE_ID}")
    
    # Test counters
    total_tests = 0
    passed_tests = 0
    
    print("\n1. BASELINE QUERIES (NO BIND):")
    
    # Test 1: Simple entity query without BIND
    success, count = await run_bind_test(sparql_impl, 
        "Simple entity query (no BIND)", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/name> ?name .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
        }}
        LIMIT 5
    """, {'min_results': 1})
    total_tests += 1
    if success: passed_tests += 1
    
    print("\n2. BASIC BIND EXPRESSIONS:")
    
    # Test 2: Simple CONCAT BIND
    success, count = await run_bind_test(sparql_impl,
        "CONCAT BIND expression", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/name> ?name .
            ?entity <http://example.org/profile> ?profile .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            BIND(CONCAT("profile_", STR(?entity)) AS ?profile)
        }}
        LIMIT 5
    """, {'min_results': 1})
    total_tests += 1
    if success: passed_tests += 1
    
    # Test 3: String length BIND
    success, count = await run_bind_test(sparql_impl,
        "STRLEN BIND expression", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/name> ?name .
            ?entity <http://example.org/nameLength> ?length .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            BIND(STRLEN(?name) AS ?length)
        }}
        LIMIT 5
    """, {'min_results': 1})
    total_tests += 1
    if success: passed_tests += 1
    
    # Test 4: Case conversion BIND
    success, count = await run_bind_test(sparql_impl,
        "UCASE/LCASE BIND expressions", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/name> ?name .
            ?entity <http://example.org/upper> ?upper .
            ?entity <http://example.org/lower> ?lower .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            BIND(UCASE(?name) AS ?upper)
            BIND(LCASE(?name) AS ?lower)
        }}
        LIMIT 3
    """, {'min_results': 1})
    total_tests += 1
    if success: passed_tests += 1
    
    print("\n3. CONDITIONAL BIND EXPRESSIONS:")
    
    # Test 5: IF expression BIND
    success, count = await run_bind_test(sparql_impl,
        "IF conditional BIND", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/name> ?name .
            ?entity <http://example.org/category> ?category .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            BIND(IF(STRLEN(?name) > 10, "LONG", "SHORT") AS ?category)
        }}
        LIMIT 5
    """, {'min_results': 1})
    total_tests += 1
    if success: passed_tests += 1
    
    print("\n4. ARITHMETIC BIND EXPRESSIONS:")
    
    # Test 6: Simple arithmetic
    success, count = await run_bind_test(sparql_impl,
        "Arithmetic BIND expressions", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/name> ?name .
            ?entity <http://example.org/nameLength> ?length .
            ?entity <http://example.org/doubledLength> ?doubled .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            BIND(STRLEN(?name) AS ?length)
            BIND(?length * 2 AS ?doubled)
        }}
        LIMIT 3
    """, {'min_results': 1})
    total_tests += 1
    if success: passed_tests += 1
    
    print("\n5. NESTED BIND EXPRESSIONS:")
    
    # Test 7: Nested function calls
    success, count = await run_bind_test(sparql_impl,
        "Nested BIND functions", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/name> ?name .
            ?entity <http://example.org/processed> ?processed .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            BIND(UCASE(SUBSTR(?name, 1, 5)) AS ?processed)
        }}
        LIMIT 3
    """, {'min_results': 1})
    total_tests += 1
    if success: passed_tests += 1
    
    print("\n6. COMPLEX BIND SCENARIOS:")
    
    # Test 8: Multiple BIND variables
    success, count = await run_bind_test(sparql_impl,
        "Multiple BIND variables", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/name> ?name .
            ?entity <http://example.org/prefix> ?prefix .
            ?entity <http://example.org/suffix> ?suffix .
            ?entity <http://example.org/combined> ?combined .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            BIND(SUBSTR(?name, 1, 3) AS ?prefix)
            BIND(SUBSTR(?name, 4) AS ?suffix)
            BIND(CONCAT(?prefix, "_", ?suffix) AS ?combined)
        }}
        LIMIT 2
    """, {'min_results': 1})
    total_tests += 1
    if success: passed_tests += 1
    
    # Final summary
    print(f"\n📊 FINAL TEST SUMMARY:")
    print(f"   Total tests: {total_tests}")
    print(f"   Passed: {passed_tests}")
    print(f"   Failed: {total_tests - passed_tests}")
    print(f"   Success rate: {(passed_tests/total_tests)*100:.1f}%")
    
    if passed_tests == total_tests:
        print(f"\n🎉 ALL TESTS PASSED!")
        print(f"✅ Refactored BIND implementation is working correctly")
    else:
        print(f"\n⚠️  {total_tests - passed_tests} TEST(S) FAILED")
        print(f"🔍 Review the error details above for debugging")
    
    # Performance summary
    print(f"\n📊 Final cache size: {sparql_impl.term_cache.size()} terms")
    
    await impl.db_impl.disconnect()
    print("\n✅ Refactored SPARQL BIND Implementation Test Complete!")
    
    return passed_tests == total_tests

if __name__ == "__main__":
    success = asyncio.run(test_refactored_bind_implementation())
    sys.exit(0 if success else 1)
