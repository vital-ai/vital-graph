#!/usr/bin/env python3
"""
Refactored SPARQL SELECT Queries Test Script
===========================================

Tests the new refactored SPARQL implementation against the original implementation
using SELECT query patterns to verify functional parity.

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
    
    # Special SQL debugging for failing test cases
    capture_sql = any(keyword in name for keyword in [
        "VALUES with multiple variables",
        "UNION with different graphs", 
        "Complex query with OPTIONAL, FILTER, and ORDER BY",
        "Complex query with UNION, BIND, and aggregation",
        "BIND with complex expressions"
    ])
    original_sql = None
    refactored_sql = None
    
    original_results = None
    refactored_results = None
    original_time = 0
    refactored_time = 0
    
    try:
        if capture_sql:
            # Parse query to get algebra for SQL generation
            from rdflib.plugins.sparql import prepareQuery
            parsed_query = prepareQuery(sparql)
            algebra = parsed_query.algebra
            
            # Generate SQL from both implementations
            print("\n🔍 CAPTURING SQL GENERATION:")
            print("-" * 50)
            
            try:
                # Original implementation: create table_config like it does internally
                from vitalgraph.db.postgresql.table_config import TableConfig
                original_table_config = TableConfig.from_space_impl(original_impl.space_impl, SPACE_ID)
                original_sql = await original_impl._translate_select_query(algebra, original_table_config)
                print("📊 ORIGINAL SQL:")
                print(original_sql)
                print()
            except Exception as e:
                print(f"❌ Original SQL generation failed: {e}")
                # Try alternative import path
                try:
                    from vitalgraph.db.postgresql.postgresql_sparql_impl import TableConfig
                    original_table_config = TableConfig.from_space_impl(original_impl.space_impl, SPACE_ID)
                    original_sql = await original_impl._translate_select_query(algebra, original_table_config)
                    print("📊 ORIGINAL SQL (alt):")
                    print(original_sql)
                    print()
                except Exception as e2:
                    print(f"❌ Original SQL alt failed: {e2}")
            
            try:
                # Refactored implementation: access the orchestrator function
                from vitalgraph.db.postgresql.sparql.postgresql_sparql_orchestrator import translate_algebra_pattern
                # Use the same approach as the refactored implementation
                refactored_sql = await refactored_impl._translate_select_query(algebra, refactored_impl.table_config)
                print("📊 REFACTORED SQL:")
                print(refactored_sql)
                print()
            except Exception as e:
                print(f"❌ Refactored SQL generation failed: {e}")
                # Try accessing the method directly
                try:
                    # Check if the method exists with different name
                    if hasattr(refactored_impl, 'translate_select_query'):
                        refactored_sql = await refactored_impl.translate_select_query(algebra, refactored_impl.table_config)
                    else:
                        # Use the orchestrator directly
                        from vitalgraph.db.postgresql.sparql.postgresql_sparql_orchestrator import translate_algebra_pattern
                        pattern_sql = await translate_algebra_pattern(algebra.p, refactored_impl.table_config, refactored_impl.space_impl)
                        refactored_sql = f"SELECT {', '.join([f'{pattern_sql.variable_mappings[var]} AS {var.n3()[1:]}' for var in algebra.PV])} {pattern_sql.from_clause}"
                        if pattern_sql.where_conditions:
                            refactored_sql += f" WHERE {' AND '.join(pattern_sql.where_conditions)}"
                        if pattern_sql.joins:
                            refactored_sql = refactored_sql.replace(pattern_sql.from_clause, pattern_sql.from_clause + ' ' + ' '.join(pattern_sql.joins))
                    print("📊 REFACTORED SQL (alt):")
                    print(refactored_sql)
                    print()
                except Exception as e2:
                    print(f"❌ Refactored SQL alt failed: {e2}")
            
            # Compare SQL
            if original_sql and refactored_sql:
                if original_sql.strip() == refactored_sql.strip():
                    print("✅ SQL IDENTICAL")
                else:
                    print("❌ SQL DIFFERENT - This explains the result mismatch!")
                    print("\n🔍 SQL DIFFERENCES:")
                    orig_lines = original_sql.strip().split('\n')
                    refact_lines = refactored_sql.strip().split('\n')
                    
                    for i, (orig, refact) in enumerate(zip(orig_lines, refact_lines)):
                        if orig.strip() != refact.strip():
                            print(f"  Line {i+1}:")
                            print(f"    Original:   {orig}")
                            print(f"    Refactored: {refact}")
            print("-" * 50)
        
        # Run on original implementation
        start_time = time.time()
        original_results = await original_impl.execute_sparql_query(SPACE_ID, sparql)
        original_time = time.time() - start_time
        
        # Run on refactored implementation
        start_time = time.time()
        refactored_results = await refactored_impl.execute_sparql_query(SPACE_ID, sparql)
        refactored_time = time.time() - start_time
        
        # Compare results
        if original_results is not None and refactored_results is not None:
            if len(original_results) == len(refactored_results):
                # Check if results are identical
                results_match = True
                for orig, ref in zip(original_results, refactored_results):
                    if orig != ref:
                        results_match = False
                        break
                
                if results_match:
                    print(f"    ✅ Original: {original_time:.3f}s | {len(original_results)} results")
                    print(f"    ✅ Refactored: {refactored_time:.3f}s | {len(refactored_results)} results")
                    
                    # Show sample results
                    for i, result in enumerate(original_results[:3]):
                        print(f"    [{i+1}] {result}")
                    if len(original_results) > 3:
                        print(f"    ... +{len(original_results) - 3} more")
                    
                    return True
                else:
                    print(f"    ❌ Original: {original_time:.3f}s | {len(original_results)} results")
                    print(f"    ❌ Refactored: {refactored_time:.3f}s | {len(refactored_results)} results")
                    print(f"    ⚠️  RESULTS MISMATCH!")
                    print(f"       Original count: {len(original_results)}")
                    print(f"       Refactored count: {len(refactored_results)}")
                    
                    # Show detailed comparison for failing queries
                    if "UNION" in name or "Complex query" in name:
                        print(f"\n    🔍 DETAILED COMPARISON FOR: {name}")
                        print(f"    === ORIGINAL RESULTS ===")
                        for i, result in enumerate(original_results[:5]):
                            print(f"    [{i+1}] {result}")
                        if len(original_results) > 5:
                            print(f"    ... +{len(original_results) - 5} more")
                        
                        print(f"    === REFACTORED RESULTS ===")
                        for i, result in enumerate(refactored_results[:5]):
                            print(f"    [{i+1}] {result}")
                        if len(refactored_results) > 5:
                            print(f"    ... +{len(refactored_results) - 5} more")
                
                    return False
            else:
                print(f"    ❌ Original: {original_time:.3f}s | {len(original_results)} results")
                print(f"    ❌ Refactored: {refactored_time:.3f}s | {len(refactored_results)} results")
                print(f"    ⚠️  RESULTS MISMATCH!")
                print(f"       Original count: {len(original_results)}")
                print(f"       Refactored count: {len(refactored_results)}")
                
                # Show detailed comparison for failing queries
                if "UNION" in name or "Complex query" in name:
                    print(f"\n    🔍 DETAILED COMPARISON FOR: {name}")
                    print(f"    === ORIGINAL RESULTS ===")
                    for i, result in enumerate(original_results[:5]):
                        print(f"    [{i+1}] {result}")
                    if len(original_results) > 5:
                        print(f"    ... +{len(original_results) - 5} more")
                    
                    print(f"    === REFACTORED RESULTS ===")
                    for i, result in enumerate(refactored_results[:5]):
                        print(f"    [{i+1}] {result}")
                    if len(refactored_results) > 5:
                        print(f"    ... +{len(refactored_results) - 5} more")
                
                return False
        
        return False
        
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
    
    # Convert to sets of tuples for comparison (order independent)
    original_set = {tuple(sorted(result.items())) for result in original}
    refactored_set = {tuple(sorted(result.items())) for result in refactored}
    
    return original_set == refactored_set

async def test_refactored_select_queries():
    """Test refactored SPARQL implementation against original with SELECT query patterns."""
    print("🧪 Testing Refactored SPARQL Implementation - SELECT Queries")
    print("=" * 65)
    print("Comparing Original vs Refactored SPARQL implementations")
    print("=" * 65)
    
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
    
    print(f"✅ Connected to database")
    print(f"🔧 Testing space: {SPACE_ID}")
    print(f"📊 Original cache: {original_sparql.term_uuid_cache.size()} terms")
    print(f"📊 Refactored cache: {refactored_sparql.term_cache.size()} terms")
    
    # Test counters
    total_tests = 0
    passed_tests = 0
    
    print("\n1. BASIC SELECT QUERIES:")
    
    # Test basic triple patterns
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Basic triple pattern", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
            }}
        }}
        LIMIT 5
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Multiple triple patterns", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                ?person ex:hasAge ?age .
            }}
        }}
        LIMIT 5
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "SELECT with specific subject", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?property ?value WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ex:person1 ?property ?value .
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n2. SELECT WITH FILTERS:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Numeric filter", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                ?person ex:hasAge ?age .
                FILTER(?age > 25)
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "String filter with CONTAINS", f"""
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
        "Complex filter with AND/OR", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                ?person ex:hasAge ?age .
                FILTER(?age > 20 && (?age < 40 || CONTAINS(?name, "Smith")))
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n3. SELECT WITH OPTIONAL:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Basic OPTIONAL pattern", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name ?email WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                OPTIONAL {{
                    ?person ex:hasEmail ?email .
                }}
            }}
        }}
        LIMIT 5
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Multiple OPTIONAL patterns", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name ?email ?phone WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                OPTIONAL {{
                    ?person ex:hasEmail ?email .
                }}
                OPTIONAL {{
                    ?person ex:hasPhone ?phone .
                }}
            }}
        }}
        LIMIT 5
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n4. SELECT WITH UNION:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Basic UNION pattern", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?entity ?identifier WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                {{
                    ?entity ex:hasName ?identifier .
                }} UNION {{
                    ?entity ex:hasEmail ?identifier .
                }}
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "UNION with different graphs", f"""
        PREFIX ex: <http://example.org/>
        PREFIX test: <http://example.org/test#>
        SELECT ?entity ?name WHERE {{
            {{
                GRAPH <{GLOBAL_GRAPH_URI}> {{
                    ?entity ex:hasName ?name .
                }}
            }} UNION {{
                GRAPH <{GRAPH_URI}> {{
                    ?entity test:hasName ?name .
                }}
            }}
        }}
        LIMIT 10
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n5. SELECT WITH BIND:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Basic BIND expression", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name ?greeting WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                BIND(CONCAT("Hello, ", ?name) AS ?greeting)
            }}
        }}
        LIMIT 5
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "BIND with arithmetic", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name ?age ?age_in_months WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                ?person ex:hasAge ?age .
                BIND(?age * 12 AS ?age_in_months)
            }}
        }}
        LIMIT 5
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n6. SELECT WITH AGGREGATION:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "COUNT aggregation", f"""
        PREFIX ex: <http://example.org/>
        SELECT (COUNT(?person) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "GROUP BY with COUNT", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?department (COUNT(?person) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                ?person ex:hasDepartment ?department .
            }}
        }}
        GROUP BY ?department
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Multiple aggregations", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?department (COUNT(?person) AS ?count) (AVG(?age) AS ?avg_age) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                ?person ex:hasDepartment ?department .
                ?person ex:hasAge ?age .
            }}
        }}
        GROUP BY ?department
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n7. SELECT WITH ORDER BY AND LIMIT:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "ORDER BY name", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "ORDER BY with DESC", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                ?person ex:hasAge ?age .
            }}
        }}
        ORDER BY DESC(?age) ?name
        LIMIT 5
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n8. SELECT WITH VALUES:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "VALUES with single variable", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            VALUES ?name {{ "John Doe" "Jane Smith" "Bob Johnson" }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "VALUES with multiple variables", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name ?age WHERE {{
            VALUES (?name ?age) {{ ("John Doe" 30) ("Jane Smith" 25) }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                ?person ex:hasAge ?age .
            }}
        }}
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    print("\n9. COMPLEX SELECT QUERIES:")
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Complex query with OPTIONAL, FILTER, and ORDER BY", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name ?age ?email WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                ?person ex:hasAge ?age .
                OPTIONAL {{
                    ?person ex:hasEmail ?email .
                }}
                FILTER(?age > 20)
            }}
        }}
        ORDER BY DESC(?age) ?name
        LIMIT 10
    """)
    total_tests += 1
    if result: passed_tests += 1
    
    result = await run_comparison_query(original_sparql, refactored_sparql,
        "Complex query with UNION, BIND, and aggregation", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?type (COUNT(?entity) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                {{
                    ?entity ex:hasName ?name .
                    BIND("Person" AS ?type)
                }} UNION {{
                    ?entity ex:hasTitle ?title .
                    BIND("Book" AS ?type)
                }}
            }}
        }}
        GROUP BY ?type
        ORDER BY DESC(?count)
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
    print("\n✅ Refactored SPARQL SELECT Queries Test Complete!")
    
    return passed_tests == total_tests

if __name__ == "__main__":
    success = asyncio.run(test_refactored_select_queries())
    sys.exit(0 if success else 1)
