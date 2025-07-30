#!/usr/bin/env python3
"""
Refactored SPARQL ASK & DESCRIBE Queries Implementation Test Script
===================================================================

Tests the new refactored SPARQL implementation for ASK and DESCRIBE queries.

ASK queries return boolean results indicating whether a pattern exists.
DESCRIBE queries return all properties (triples) of specified resources.

This test validates the refactored implementation independently.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl

# Import refactored SPARQL implementation
from vitalgraph.db.postgresql.sparql.postgres_sparql_impl import PostgreSQLSparqlImpl as RefactoredSparqlImpl

# Reduce logging chatter
logging.getLogger('vitalgraph.db.postgresql.postgresql_space_impl').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.rdf.rdf_utils').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.db.postgresql.postgresql_cache_term').setLevel(logging.WARNING)

# Configuration
SPACE_ID = "space_test"
GRAPH_URI = "http://vital.ai/graph/test"
GLOBAL_GRAPH_URI = "urn:___GLOBAL"

async def run_query(sparql_impl, name, sparql, debug=False):
    """Execute a single SPARQL query and display results."""
    print(f"\n  🔄 {name}:")
    
    if debug:
        print(f"\n🔍 DEBUG QUERY: {name}")
        print("=" * 60)
        print("SPARQL:")
        print(sparql)
        print("\n" + "-" * 60)
        
        # Enable debug logging temporarily
        sparql_logger = logging.getLogger('vitalgraph.db.postgresql.sparql.postgresql_sparql_orchestrator')
        original_level = sparql_logger.level
        sparql_logger.setLevel(logging.DEBUG)
        
        # Add console handler if not present
        if not sparql_logger.handlers:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(levelname)s - %(message)s')
            console_handler.setFormatter(formatter)
            sparql_logger.addHandler(console_handler)
    
    try:
        start_time = time.time()
        results = await sparql_impl.execute_sparql_query(SPACE_ID, sparql)
        query_time = time.time() - start_time
        
        result_count = len(results) if results else 0
        print(f"    ⏱️  {query_time:.3f}s | {result_count} results")
        
        # Show results with appropriate formatting
        if results:
            for i, result in enumerate(results):
                if isinstance(result, dict):
                    # For ASK queries, show boolean result clearly
                    if 'ask' in result:
                        print(f"    [{i+1}] ASK result: {result['ask']}")
                    else:
                        print(f"    [{i+1}] {dict(result)}")
                else:
                    print(f"    [{i+1}] {result}")
                    
                # Limit output for readability
                if i >= 4:  # Show first 5 results
                    remaining = result_count - 5
                    if remaining > 0:
                        print(f"    ... +{remaining} more results")
                    break
        
        if debug:
            print("\n" + "=" * 60)
            
        return True
        
    except Exception as e:
        print(f"    ❌ Error: {e}")
        if debug:
            import traceback
            traceback.print_exc()
        return False
    
    finally:
        if debug:
            # Restore original logging level
            sparql_logger.setLevel(original_level)

async def test_refactored_ask_describe():
    """Test refactored SPARQL implementation for ASK and DESCRIBE queries."""
    print("🧪 REFACTORED SPARQL ASK & DESCRIBE QUERIES TEST SUITE")
    print("=" * 60)
    
    # Load config and initialize
    project_root = Path(__file__).parent.parent.parent
    config_path = project_root / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    db_impl = impl.get_db_impl()
    await db_impl.connect()
    
    space_impl = db_impl.get_space_impl()
    refactored_sparql = RefactoredSparqlImpl(space_impl)
    
    # Test counters
    total_tests = 0
    passed_tests = 0
    
    print("\n❓ BASIC ASK QUERIES:")
    
    # Test 1: Simple existence check
    result = await run_query(refactored_sparql, "ASK if persons exist", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        ASK {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    # Test 2: Check for specific property
    result = await run_query(refactored_sparql, "ASK if any person has age", f"""
        PREFIX ex: <http://example.org/>
        ASK {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    # Test 3: Check for specific value
    result = await run_query(refactored_sparql, "ASK if person1 exists", f"""
        PREFIX ex: <http://example.org/>
        ASK {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ex:person1 ?p ?o .
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    # Test 4: ASK with filter
    result = await run_query(refactored_sparql, "ASK if any person over 30", f"""
        PREFIX ex: <http://example.org/>
        ASK {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
                FILTER(?age > 30)
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n❓ COMPLEX ASK QUERIES:")
    
    # Test 5: ASK with multiple patterns
    result = await run_query(refactored_sparql, "ASK for person with name and age", f"""
        PREFIX ex: <http://example.org/>
        ASK {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name ;
                        ex:hasAge ?age .
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    # Test 6: ASK with UNION
    result = await run_query(refactored_sparql, "ASK with UNION pattern", f"""
        PREFIX ex: <http://example.org/>
        ASK {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
                {{
                    FILTER(?age > 20)
                }} UNION {{
                    ?person ex:hasName ?name .
                    FILTER(STRLEN(?name) > 3)
                }}
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    # Test 7: ASK with OPTIONAL
    result = await run_query(refactored_sparql, "ASK with OPTIONAL pattern", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        ASK {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                OPTIONAL {{ ?person ex:hasEmail ?email }}
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n📋 BASIC DESCRIBE QUERIES:")
    
    # Test 8: DESCRIBE specific resource
    result = await run_query(refactored_sparql, "DESCRIBE person1", f"""
        PREFIX ex: <http://example.org/>
        DESCRIBE ex:person1
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    # Test 9: DESCRIBE with WHERE clause
    result = await run_query(refactored_sparql, "DESCRIBE persons with email", f"""
        PREFIX ex: <http://example.org/>
        DESCRIBE ?person WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasEmail ?email .
            }}
        }}
        LIMIT 3
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    # Test 10: DESCRIBE multiple resources
    result = await run_query(refactored_sparql, "DESCRIBE multiple persons", f"""
        PREFIX ex: <http://example.org/>
        DESCRIBE ex:person1 ex:person2 ex:person3
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n📋 COMPLEX DESCRIBE QUERIES:")
    
    # Test 11: DESCRIBE with filter
    result = await run_query(refactored_sparql, "DESCRIBE persons over 25", f"""
        PREFIX ex: <http://example.org/>
        DESCRIBE ?person WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
                FILTER(?age > 25)
            }}
        }}
        LIMIT 3
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    # Test 12: DESCRIBE with string filter
    result = await run_query(refactored_sparql, "DESCRIBE persons with 'A' in name", f"""
        PREFIX ex: <http://example.org/>
        DESCRIBE ?person WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(CONTAINS(?name, "A"))
            }}
        }}
        LIMIT 2
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    # Test 13: DESCRIBE with ORDER BY
    result = await run_query(refactored_sparql, "DESCRIBE persons ordered by age", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        DESCRIBE ?person WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person ;
                        ex:hasAge ?age .
            }}
        }}
        ORDER BY ?age
        LIMIT 2
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n⚠️  EDGE CASES:")
    
    # Test 14: ASK if any triples exist
    result = await run_query(refactored_sparql, "ASK if any triples exist", f"""
        ASK {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?s ?p ?o .
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    # Test 15: DESCRIBE non-existent resource
    result = await run_query(refactored_sparql, "DESCRIBE non-existent resource", f"""
        PREFIX ex: <http://example.org/>
        DESCRIBE ex:nonexistent
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    # Test 16: ASK with complex nested pattern
    result = await run_query(refactored_sparql, "ASK with nested UNION pattern", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        ASK {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                {{
                    ?person ex:hasAge ?age .
                    FILTER(?age > 20)
                }} UNION {{
                    ?person ex:hasName ?name .
                    FILTER(STRLEN(?name) > 3)
                }}
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    # Test 17: DESCRIBE with BIND expression
    result = await run_query(refactored_sparql, "DESCRIBE with BIND expression", f"""
        PREFIX ex: <http://example.org/>
        DESCRIBE ?person WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
                BIND(?age * 2 AS ?doubleAge)
                FILTER(?doubleAge > 50)
            }}
        }}
        LIMIT 2
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    # Test 18: ASK with BIND expression
    result = await run_query(refactored_sparql, "ASK with BIND expression", f"""
        PREFIX ex: <http://example.org/>
        ASK {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
                BIND(ROUND(?age / 10.0) AS ?decade)
                FILTER(?decade >= 3)
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    # Final summary
    print(f"\n📊 FINAL SUMMARY:")
    print(f"   Total tests: {total_tests}")
    print(f"   Passed: {passed_tests}")
    print(f"   Failed: {total_tests - passed_tests}")
    print(f"   Success rate: {(passed_tests/total_tests)*100:.1f}%")
    
    if passed_tests == total_tests:
        print(f"\n🎉 ALL TESTS PASSED!")
        print(f"✅ Refactored ASK & DESCRIBE implementation working correctly")
    else:
        print(f"\n⚠️  {total_tests - passed_tests} TEST(S) FAILED")
        print(f"❌ Some ASK/DESCRIBE queries need investigation")
    
    # Performance summary
    print(f"\n📊 Final cache size: {refactored_sparql.term_cache.size()} terms")
    
    await impl.db_impl.disconnect()
    print("\n✅ Refactored SPARQL ASK & DESCRIBE Queries Test Complete!")
    
    return passed_tests == total_tests

if __name__ == "__main__":
    success = asyncio.run(test_refactored_ask_describe())
    sys.exit(0 if success else 1)
