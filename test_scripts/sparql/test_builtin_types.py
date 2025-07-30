#!/usr/bin/env python3
"""
SPARQL Type Checking Built-in Functions Test Script
===================================================

Tests type checking SPARQL built-in functions for data type validation.
Uses shared utility modules for maintainable, consistent testing.

Type checking functions tested:
- ISURI(term) / ISIRI(term) - Check if term is a URI/IRI
- ISBLANK(term) - Check if term is a blank node
- ISLITERAL(term) - Check if term is a literal
- ISNUMERIC(literal) - Check if literal is numeric
- DATATYPE(literal) - Get datatype of literal
- LANG(literal) - Get language tag
- LANGMATCHES(lang, pattern) - Language matching
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

async def test_type_builtins():
    """Test type checking SPARQL built-in functions using TestToolUtils for clean, maintainable code."""
    print("🧪 SPARQL Type Checking Built-in Functions Tests")
    print("=" * 60)
    
    # Initialize VitalGraph implementation
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    config = get_config(str(config_path))
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    space_impl = impl.db_impl.get_space_impl()
    sparql_impl = PostgreSQLSparqlImpl(space_impl)
    
    print(f"✅ Connected | Testing type checking SPARQL built-in functions")
    print(f"🎯 Target Graph: {GLOBAL_GRAPH_URI}")
    
    # Track test results for summary
    test_results = []
    
    # Run the type checking builtins comprehensive test from the original file
    await test_type_checking_builtins_comprehensive(sparql_impl, test_results)
    await test_type_checking_builtins(sparql_impl, test_results)
    
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
    print("\n✅ Type Checking Built-in Functions Tests Complete!")
    
    # Return test results for aggregation
    return test_results

async def test_type_checking_builtins_comprehensive(sparql_impl, test_results):
    """Test type checking built-in functions comprehensively using TestToolUtils."""
    TestToolUtils.print_test_section_header("5. TYPE CHECKING BUILT-INS", "Data type validation functions")
    
    # Test 1: DATATYPE function - Get datatype of literal
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "DATATYPE - Get datatype of literal", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        
        SELECT ?person ?name ?age ?ageDatatype WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                ?person ex:hasAge ?age .
                BIND(DATATYPE(?age) AS ?ageDatatype)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)
    
    # Test 2: LANG function - Get language tag
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "LANG - Get language tag", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?nameLang WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(LANG(?name) AS ?nameLang)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)
    
    # Test 3: ISURI/ISIRI function - Check if URI
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "ISURI - Check if term is URI", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?isPersonURI ?isNameURI WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(ISURI(?person) AS ?isPersonURI)
                BIND(ISURI(?name) AS ?isNameURI)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)
    
    # Test 4: ISLITERAL function - Check if literal
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "ISLITERAL - Check if term is literal", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?isPersonLiteral ?isNameLiteral WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(ISLITERAL(?person) AS ?isPersonLiteral)
                BIND(ISLITERAL(?name) AS ?isNameLiteral)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)
    
    # Test 5: ISNUMERIC function - Check if numeric
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "ISNUMERIC - Check if literal is numeric", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?age ?isNameNumeric ?isAgeNumeric WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                ?person ex:hasAge ?age .
                BIND(ISNUMERIC(?name) AS ?isNameNumeric)
                BIND(ISNUMERIC(?age) AS ?isAgeNumeric)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)
    
    # Test 6: ISBLANK function - Check if blank node
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "ISBLANK - Check if term is blank node", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?isPersonBlank ?isNameBlank WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(ISBLANK(?person) AS ?isPersonBlank)
                BIND(ISBLANK(?name) AS ?isNameBlank)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)

async def test_type_checking_builtins(sparql_impl, test_results):
    """Test additional type checking built-in functions using TestToolUtils."""
    TestToolUtils.print_test_section_header("6. LANGUAGE MATCHING", "Language tag operations")
    
    # Test 1: LANGMATCHES function - Language matching
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "LANGMATCHES - Language matching", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?matchesEN WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(LANGMATCHES(LANG(?name), "en") AS ?matchesEN)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)
    
    # Test 2: Combined type checking
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "Combined type checking", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?age ?typeInfo WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                ?person ex:hasAge ?age .
                BIND(CONCAT(
                    "Person URI: ", STR(ISURI(?person)),
                    " Name Literal: ", STR(ISLITERAL(?name)),
                    " Age Numeric: ", STR(ISNUMERIC(?age))
                ) AS ?typeInfo)
            }}
        }}
        ORDER BY ?name
        LIMIT 3
    """)
    test_results.append(result)

if __name__ == "__main__":
    asyncio.run(test_type_builtins())
