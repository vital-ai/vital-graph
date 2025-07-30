#!/usr/bin/env python3
"""
SPARQL Critical Built-in Functions Test Script
==============================================

Tests critical SPARQL built-in functions that are essential for SPARQL functionality.
Uses shared utility modules for maintainable, consistent testing.

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
from pathlib import Path

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.db.postgresql.postgresql_sparql_impl import PostgreSQLSparqlImpl
from vitalgraph.config.config_loader import get_config

# Import shared utility modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tool_utils"))
from tool_utils import TestToolUtils

# Configuration
SPACE_ID = "space_test"
GRAPH_URI = "http://vital.ai/graph/test"
GLOBAL_GRAPH_URI = "urn:___GLOBAL"

# Configure logging to reduce noise
logging.getLogger('vitalgraph.rdf.rdf_utils').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.db.postgresql.postgresql_cache_term').setLevel(logging.WARNING)

async def test_critical_builtins():
    """Test critical SPARQL built-in functions using TestToolUtils for clean, maintainable code."""
    print("🧪 SPARQL Critical Built-in Functions Tests")
    print("=" * 60)
    
    # Initialize VitalGraph implementation
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    config = get_config(str(config_path))
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    space_impl = impl.db_impl.get_space_impl()
    sparql_impl = PostgreSQLSparqlImpl(space_impl)
    
    print(f"✅ Connected | Testing critical SPARQL built-in functions")
    print(f"🎯 Target Graph: {GLOBAL_GRAPH_URI}")
    
    # Track test results for summary
    test_results = []
    
    # Run the critical builtins comprehensive test from the original file
    await test_critical_builtins_comprehensive(sparql_impl, test_results)
    
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
    print("\n✅ Critical Built-in Functions Tests Complete!")
    
    # Return test results for aggregation
    return test_results

async def test_critical_builtins_comprehensive(sparql_impl, test_results):
    """Test critical built-in functions with comprehensive coverage using TestToolUtils."""
    TestToolUtils.print_test_section_header("1. CRITICAL BUILT-INS", "Essential for OPTIONAL patterns")
    
    # Test 1: BOUND function - Essential for OPTIONAL patterns
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "BOUND - Check if variable is bound", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?hasEmail WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasEmail ?email }}
                BIND(BOUND(?email) AS ?hasEmail)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)
    
    # Test 2: COALESCE function - Return first non-null value
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "COALESCE - First non-null value", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?contact WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasEmail ?email }}
                OPTIONAL {{ ?person ex:hasPhone ?phone }}
                BIND(COALESCE(?email, ?phone, "no-contact") AS ?contact)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)
    
    # Test 3: URI/IRI function - Create URI from string
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "URI - Create URI from string", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?profileUri WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(URI(CONCAT("http://example.org/profile/", ?name)) AS ?profileUri)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """)
    test_results.append(result)
    
    # Test 4: STRUUID function - Generate UUID string
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "STRUUID - Generate UUID string", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?uuid WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(STRUUID() AS ?uuid)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """)
    test_results.append(result)
    
    # Test 5: ENCODE_FOR_URI function - URL encoding
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "ENCODE_FOR_URI - URL encoding", f"""
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
    test_results.append(result)
    
    # Test 6: UUID function - Generate UUID as URI
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "UUID - Generate UUID as URI", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?uuidUri WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(UUID() AS ?uuidUri)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """)
    test_results.append(result)

if __name__ == "__main__":
    asyncio.run(test_critical_builtins())
