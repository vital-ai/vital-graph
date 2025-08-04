#!/usr/bin/env python3
"""
SPARQL Numeric Built-in Functions Test Script
=============================================

Tests numeric SPARQL built-in functions for mathematical operations.
Uses shared utility modules for maintainable, consistent testing.

Numeric functions tested:
- ABS(numeric) - Absolute value
- CEIL(numeric) - Ceiling function
- FLOOR(numeric) - Floor function
- ROUND(numeric) - Rounding function
- RAND() - Random number generation
- Mathematical operations (+, -, *, /)
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

async def test_numeric_builtins():
    """Test numeric SPARQL built-in functions using TestToolUtils for clean, maintainable code."""
    print("🧪 SPARQL Numeric Built-in Functions Tests")
    print("=" * 60)
    
    # Initialize VitalGraph implementation
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    config = get_config(str(config_path))
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    space_impl = impl.db_impl.get_space_impl()
    sparql_impl = PostgreSQLSparqlImpl(space_impl)
    
    print(f"✅ Connected | Testing numeric SPARQL built-in functions")
    print(f"🎯 Target Graph: {GLOBAL_GRAPH_URI}")
    
    # Track test results for summary
    test_results = []
    
    # Run the numeric builtins comprehensive test from the original file
    await test_numeric_builtins_comprehensive(sparql_impl, test_results)
    
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
    print(f"\n📊 Cache: {sparql_impl.space_impl._term_cache.size()} terms")
    
    await impl.db_impl.disconnect()
    print("\n✅ Numeric Built-in Functions Tests Complete!")
    
    # Return test results for aggregation
    return test_results

async def test_numeric_builtins_comprehensive(sparql_impl, test_results):
    """Test numeric built-in functions comprehensively using TestToolUtils."""
    TestToolUtils.print_test_section_header("2. NUMERIC BUILT-INS", "Mathematical operations")
    
    # Test 1: ABS function - Absolute value
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "ABS - Absolute value", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?age ?absAge WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                ?person ex:hasAge ?age .
                BIND(ABS(?age - 50) AS ?absAge)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)
    
    # Test 2: CEIL function - Ceiling function
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "CEIL - Ceiling function", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?age ?ceilAge WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                ?person ex:hasAge ?age .
                BIND(CEIL(?age / 10.0) AS ?ceilAge)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)
    
    # Test 3: FLOOR function - Floor function
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "FLOOR - Floor function", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?age ?floorAge WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                ?person ex:hasAge ?age .
                BIND(FLOOR(?age / 10.0) AS ?floorAge)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)
    
    # Test 4: ROUND function - Rounding function
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "ROUND - Rounding function", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?age ?roundAge WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                ?person ex:hasAge ?age .
                BIND(ROUND(?age / 10.0) AS ?roundAge)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)
    
    # Test 5: RAND function - Random number
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "RAND - Random number", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?randomValue WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(RAND() AS ?randomValue)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """)
    test_results.append(result)
    
    # Test 6: Mathematical operations
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "Math operations - Addition, subtraction, multiplication, division", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?age ?mathResults WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                ?person ex:hasAge ?age .
                BIND(CONCAT(
                    "Add: ", STR(?age + 10), 
                    " Sub: ", STR(?age - 5), 
                    " Mul: ", STR(?age * 2), 
                    " Div: ", STR(?age / 2)
                ) AS ?mathResults)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """)
    test_results.append(result)

if __name__ == "__main__":
    asyncio.run(test_numeric_builtins())
