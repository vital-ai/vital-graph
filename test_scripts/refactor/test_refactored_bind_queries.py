#!/usr/bin/env python3
"""
Refactored SPARQL BIND Implementation Test Script
================================================

Tests the new refactored SPARQL implementation against the same BIND queries
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
                            print(f"      [{i+1}] {item}")
                
                print("\n    Refactored sample:")
                if hasattr(refactored_results, '__iter__'):
                    for i, item in enumerate(list(refactored_results)[:2]):
                        if hasattr(item, '__iter__') and len(item) == 3:  # Triple
                            s, p, o = item
                            print(f"      [{i+1}] {s} -> {p} -> {o}")
                        else:
                            print(f"      [{i+1}] {item}")
        else:
            # Show first 2 results from refactored (should match original)
            if hasattr(refactored_results, '__iter__'):
                for i, item in enumerate(list(refactored_results)[:2]):
                    if hasattr(item, '__iter__') and len(item) == 3:  # Triple
                        s, p, o = item
                        print(f"    [{i+1}] {s} -> {p} -> {o}")
                    else:
                        print(f"    [{i+1}] {item}")
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
                else:
                    original_set.add(str(item))
            
            refactored_set = set()
            for item in refactored:
                if hasattr(item, '__iter__') and len(item) == 3:  # Triple
                    s, p, o = item
                    refactored_set.add((str(s), str(p), str(o)))
                else:
                    refactored_set.add(str(item))
            
            return original_set == refactored_set
        except:
            # Fallback to simple comparison
            return list(original) == list(refactored)
    
    return False

async def test_refactored_bind_queries():
    """Test refactored SPARQL implementation against original with BIND queries."""
    print("🧪 REFACTORED SPARQL BIND IMPLEMENTATION TEST")
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
    print(f"📊 Testing SPARQL BIND queries on space: {SPACE_ID}")
    
    # Test counters
    total_tests = 0
    passed_tests = 0
    
    print("\n1. BASIC BIND EXPRESSIONS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "CONCAT with STR function", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/profile> ?profile .
            ?entity <http://example.org/originalName> ?name .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            BIND(CONCAT("profile_", STR(?entity)) AS ?profile)
        }}
        LIMIT 3
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "STRLEN function", f"""
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
        LIMIT 3
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "UCASE/LCASE functions", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/name> ?name .
            ?entity <http://example.org/upperName> ?upper .
            ?entity <http://example.org/lowerName> ?lower .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            BIND(UCASE(?name) AS ?upper)
            BIND(LCASE(?name) AS ?lower)
        }}
        LIMIT 2
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n2. ARITHMETIC BIND EXPRESSIONS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Simple arithmetic", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/name> ?name .
            ?entity <http://example.org/calculation> ?calc .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            BIND((STRLEN(?name) * 2 + 5) AS ?calc)
        }}
        LIMIT 3
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Division and modulo", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/name> ?name .
            ?entity <http://example.org/divided> ?div .
            ?entity <http://example.org/remainder> ?mod .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            BIND((STRLEN(?name) / 2) AS ?div)
            BIND((STRLEN(?name) % 3) AS ?mod)
        }}
        LIMIT 3
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n3. CONDITIONAL BIND EXPRESSIONS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "IF expression", f"""
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
        LIMIT 3
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Nested IF expression", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/name> ?name .
            ?entity <http://example.org/size> ?size .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            BIND(IF(STRLEN(?name) > 15, "VERY_LONG", IF(STRLEN(?name) > 8, "MEDIUM", "SHORT")) AS ?size)
        }}
        LIMIT 3
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n4. STRING MANIPULATION BIND EXPRESSIONS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "SUBSTR function", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/name> ?name .
            ?entity <http://example.org/prefix> ?prefix .
            ?entity <http://example.org/suffix> ?suffix .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            BIND(SUBSTR(?name, 1, 3) AS ?prefix)
            BIND(SUBSTR(?name, 4) AS ?suffix)
        }}
        LIMIT 3
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "REPLACE function", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/name> ?name .
            ?entity <http://example.org/modified> ?modified .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            BIND(REPLACE(?name, "a", "X") AS ?modified)
        }}
        LIMIT 3
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n5. COMPLEX NESTED BIND EXPRESSIONS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Complex nested expression", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/name> ?name .
            ?entity <http://example.org/complex> ?complex .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            BIND(CONCAT("Result: ", IF(STRLEN(?name) < 5, "SHORT", SUBSTR(?name, 1, 3))) AS ?complex)
        }}
        LIMIT 2
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Function composition", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/name> ?name .
            ?entity <http://example.org/composed> ?composed .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            BIND(UCASE(SUBSTR(CONCAT("PREFIX_", ?name), 1, 8)) AS ?composed)
        }}
        LIMIT 2
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
    print("\n✅ Refactored SPARQL BIND Implementation Test Complete!")
    
    return passed_tests == total_tests

if __name__ == "__main__":
    success = asyncio.run(test_refactored_bind_queries())
    sys.exit(0 if success else 1)
