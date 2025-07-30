#!/usr/bin/env python3
"""
UNION Query Test Script
=======================

Test SPARQL UNION pattern functionality in VitalGraph's PostgreSQL-backed SPARQL engine.
This file focuses specifically on UNION pattern translation and execution.

UNION patterns allow querying alternative patterns:
- { ?s ?p ?o } UNION { ?s ?p2 ?o2 }
- Complex nested UNION patterns
- UNION with different variable bindings
- UNION across different graphs
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.config.config_loader import get_config
from vitalgraph.db.postgresql.postgresql_sparql_impl import PostgreSQLSparqlImpl

# Import test utilities for consistent test execution and reporting
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tool_utils"))
from tool_utils import TestToolUtils

# Configure logging to see SQL generation
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(name)s - %(message)s')

# Suppress verbose logging from other modules but keep SPARQL SQL logging
logging.getLogger('vitalgraph.rdf.rdf_utils').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.db.postgresql.postgresql_cache_term').setLevel(logging.WARNING)
# Keep SPARQL implementation logging at INFO level to see SQL generation
logging.getLogger('vitalgraph.db.postgresql.postgresql_sparql_impl').setLevel(logging.INFO)

# Configuration
SPACE_ID = "space_test"
GRAPH_URI = "http://vital.ai/graph/test"
GLOBAL_GRAPH_URI = "urn:___GLOBAL"

async def run_union_query(sparql_impl, query_name, query):
    """Run a single UNION query using TestToolUtils for clean, maintainable code."""
    # Use the utility function to run the complete test with all features
    result = await TestToolUtils.run_test_query(
        sparql_impl=sparql_impl,
        space_id=SPACE_ID,
        query_name=query_name,
        query=query,
        enable_algebra_logging=True,
        max_results=3  # Show first 3 results like the original
    )
    return result

async def test_union_queries():
    """Test UNION pattern functionality with various scenarios using TestToolUtils."""
    print("🔗 UNION Query Tests - Refactored with Utilities")
    print("=" * 50)
    
    # Initialize
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    space_impl = impl.db_impl.get_space_impl()
    sparql_impl = PostgreSQLSparqlImpl(space_impl)
    
    print(f"✅ Connected | Testing UNION patterns with utility modules")
    
    # Track test results for summary
    test_results = []
    
    TestToolUtils.print_test_section_header("1. BASIC UNION PATTERNS", "Testing fundamental UNION query patterns")
    
    # Test 1: Simple property UNION - entities with either name or description
    result = await run_union_query(sparql_impl, "Properties UNION - name OR description", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?value WHERE {{
            GRAPH <{GRAPH_URI}> {{
                {{ ?entity test:hasName ?value }}
                UNION
                {{ ?entity test:hasDescription ?value }}
            }}
        }}
        ORDER BY ?entity
        LIMIT 10
    """)
    test_results.append(result)
    
    # Test 2: Type UNION - different entity types
    await run_union_query(sparql_impl, "Type UNION - TestEntity OR NumberEntity", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?type WHERE {{
            GRAPH <{GRAPH_URI}> {{
                {{ ?entity rdf:type test:TestEntity . BIND(test:TestEntity AS ?type) }}
                UNION
                {{ ?entity rdf:type test:NumberEntity . BIND(test:NumberEntity AS ?type) }}
            }}
        }}
        ORDER BY ?type ?entity
        LIMIT 10
    """)
    
    # Test 3: Cross-graph UNION - main graph OR global graph
    await run_union_query(sparql_impl, "Cross-graph UNION - test graph OR global graph", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?name ?source WHERE {{
            {{
                GRAPH <{GRAPH_URI}> {{
                    ?entity test:hasName ?name .
                    BIND("test_graph" AS ?source)
                }}
            }}
            UNION
            {{
                GRAPH <{GLOBAL_GRAPH_URI}> {{
                    ?entity ex:hasName ?name .
                    BIND("global_graph" AS ?source)
                }}
            }}
        }}
        ORDER BY ?source ?entity
        LIMIT 10
    """)
    
    print("\n2. UNION WITH DIFFERENT VARIABLE PATTERNS:")
    
    # Test 4: Different variable bindings in UNION branches
    await run_union_query(sparql_impl, "Different variables - names from entities OR labels from numbers", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?item ?text ?category WHERE {{
            GRAPH <{GRAPH_URI}> {{
                {{
                    ?item rdf:type test:TestEntity .
                    ?item test:hasName ?text .
                    BIND("entity_name" AS ?category)
                }}
                UNION
                {{
                    ?item rdf:type test:NumberEntity .
                    ?item test:hasLabel ?text .
                    BIND("number_label" AS ?category)
                }}
            }}
        }}
        ORDER BY ?category ?item
        LIMIT 15
    """)
    
    # Test 5: UNION with optional variables (some branches don't bind all variables)
    await run_union_query(sparql_impl, "Optional variables - entities with/without descriptions", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?name ?description ?hasDesc WHERE {{
            GRAPH <{GRAPH_URI}> {{
                {{
                    ?entity test:hasName ?name .
                    ?entity test:hasDescription ?description .
                    BIND("yes" AS ?hasDesc)
                }}
                UNION
                {{
                    ?entity test:hasName ?name .
                    FILTER NOT EXISTS {{ ?entity test:hasDescription ?desc }}
                    BIND("no" AS ?hasDesc)
                }}
            }}
        }}
        ORDER BY ?hasDesc ?entity
        LIMIT 10
    """)
    
    print("\n3. NESTED AND COMPLEX UNION PATTERNS:")
    
    # Test 6: Nested UNION - (A UNION B) UNION C
    await run_union_query(sparql_impl, "Nested UNION - three-way alternative", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?item ?identifier ?type WHERE {{
            {{
                {{
                    GRAPH <{GRAPH_URI}> {{
                        ?item test:hasName ?identifier .
                        BIND("test_name" AS ?type)
                    }}
                }}
                UNION
                {{
                    GRAPH <{GRAPH_URI}> {{
                        ?item test:hasLabel ?identifier .
                        BIND("test_label" AS ?type)
                    }}
                }}
            }}
            UNION
            {{
                GRAPH <{GLOBAL_GRAPH_URI}> {{
                    ?item ex:hasName ?identifier .
                    BIND("global_name" AS ?type)
                }}
            }}
        }}
        ORDER BY ?type ?item
        LIMIT 15
    """)
    
    # Test 7: UNION with filters in each branch
    await run_union_query(sparql_impl, "UNION with filters - short names OR high values", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?item ?value ?reason WHERE {{
            GRAPH <{GRAPH_URI}> {{
                {{
                    ?item test:hasName ?value .
                    FILTER(STRLEN(?value) < 10)
                    BIND("short_name" AS ?reason)
                }}
                UNION
                {{
                    ?item test:hasValue ?value .
                    FILTER(?value > 25)
                    BIND("high_value" AS ?reason)
                }}
            }}
        }}
        ORDER BY ?reason ?value
        LIMIT 10
    """)
    
    print("\n4. UNION WITH CONSTRUCT QUERIES:")
    
    # Test 8: CONSTRUCT with UNION - create unified triples from different patterns
    await run_union_query(sparql_impl, "CONSTRUCT with UNION - unified entity representation", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity ex:unifiedLabel ?label .
            ?entity ex:sourceType ?sourceType .
        }}
        WHERE {{
            {{
                GRAPH <{GRAPH_URI}> {{
                    ?entity test:hasName ?label .
                    BIND("test_entity" AS ?sourceType)
                }}
            }}
            UNION
            {{
                GRAPH <{GLOBAL_GRAPH_URI}> {{
                    ?entity ex:hasName ?label .
                    BIND("global_person" AS ?sourceType)
                }}
            }}
        }}
        LIMIT 8
    """)
    
    print("\n5. UNION WITH RELATIONSHIPS:")
    
    # Test 9: UNION for different relationship types
    await run_union_query(sparql_impl, "Relationship UNION - relatedTo OR knows", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity1 ?entity2 ?relationship WHERE {{
            {{
                GRAPH <{GRAPH_URI}> {{
                    ?entity1 test:relatedTo ?entity2 .
                    BIND("related" AS ?relationship)
                }}
            }}
            UNION
            {{
                GRAPH <{GLOBAL_GRAPH_URI}> {{
                    ?entity1 ex:knows ?entity2 .
                    BIND("knows" AS ?relationship)
                }}
            }}
        }}
        ORDER BY ?relationship ?entity1
        LIMIT 10
    """)
    
    # Test 10: Complex UNION with multiple patterns per branch
    await run_union_query(sparql_impl, "Complex UNION - multi-pattern branches", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?subject ?predicate ?object ?context WHERE {{
            {{
                GRAPH <{GRAPH_URI}> {{
                    ?subject rdf:type test:TestEntity .
                    ?subject test:hasName ?name .
                    ?subject test:hasCategory ?category .
                    BIND(?subject AS ?subject)
                    BIND(test:hasName AS ?predicate)
                    BIND(?name AS ?object)
                    BIND("test_names" AS ?context)
                }}
            }}
            UNION
            {{
                GRAPH <{GLOBAL_GRAPH_URI}> {{
                    ?person rdf:type ex:Person .
                    ?person ex:hasName ?personName .
                    ?person ex:hasAge ?age .
                    BIND(?person AS ?subject)
                    BIND(ex:hasName AS ?predicate)
                    BIND(?personName AS ?object)
                    BIND("global_persons" AS ?context)
                }}
            }}
        }}
        ORDER BY ?context ?subject
        LIMIT 12
    """)
    
    # Test results summary
    total_tests = len(test_results)
    successful_tests = sum(1 for result in test_results if result.get('success', False))
    failed_tests = total_tests - successful_tests
    success_rate = (successful_tests / total_tests * 100) if total_tests > 0 else 0
    
    print(f"\n📊 Test Results Summary:")
    print(f"   Total Tests: {total_tests}")
    print(f"   ✅ Passed: {successful_tests}")
    print(f"   ❌ Failed: {failed_tests}")
    print(f"   📈 Success Rate: {success_rate:.1f}%")
    
    if failed_tests > 0:
        print(f"\n❌ Failed Tests:")
        for result in test_results:
            if not result.get('success', False):
                print(f"   • {result.get('query_name', 'Unknown')}: {result.get('error_msg', 'Unknown error')}")
    
    # Performance summary
    print(f"\n📊 Cache: {sparql_impl.term_cache.size()} terms")
    
    await impl.db_impl.disconnect()
    print("\n✅ UNION Query Tests Complete!")
    print("💡 These queries will work once UNION implementation is added to postgresql_sparql_impl.py")
    print("🔗 Test data includes entities, numbers, and relationships across multiple graphs")
    
    # Return test results for aggregation
    return test_results

if __name__ == "__main__":
    asyncio.run(test_union_queries())
