#!/usr/bin/env python3
"""
SPARQL String Built-in Functions Test Script
============================================

Tests string SPARQL built-in functions for text manipulation.
Uses shared utility modules for maintainable, consistent testing.

String functions tested:
- CONCAT(str1, str2, ...) - String concatenation
- STR(value) - Convert to string
- SUBSTR(string, start, length) - Substring extraction
- STRLEN(string) - String length
- UCASE(string) - Uppercase conversion
- LCASE(string) - Lowercase conversion
- REPLACE(string, pattern, replacement) - String replacement
- STRBEFORE(string, substring) - String before substring
- STRAFTER(string, substring) - String after substring
- CONTAINS(string, substring) - String contains check
- STRSTARTS(string, prefix) - String starts with check
- STRENDS(string, suffix) - String ends with check
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

async def test_string_builtins():
    """Test string SPARQL built-in functions using TestToolUtils for clean, maintainable code."""
    print("🧪 SPARQL String Built-in Functions Tests")
    print("=" * 60)
    
    # Initialize VitalGraph implementation
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    config = get_config(str(config_path))
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    space_impl = impl.db_impl.get_space_impl()
    sparql_impl = PostgreSQLSparqlImpl(space_impl)
    
    print(f"✅ Connected | Testing string SPARQL built-in functions")
    print(f"🎯 Target Graph: {GLOBAL_GRAPH_URI}")
    
    # Track test results for summary
    test_results = []
    
    # Run the string builtins comprehensive test from the original file
    await test_string_builtins_comprehensive(sparql_impl, test_results)
    await test_advanced_string_builtins(sparql_impl, test_results)
    
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
    print("\n✅ String Built-in Functions Tests Complete!")
    
    # Return test results for aggregation
    return test_results

async def test_string_builtins_comprehensive(sparql_impl, test_results):
    """Test string built-in functions comprehensively using TestToolUtils."""
    TestToolUtils.print_test_section_header("3. STRING BUILT-INS", "Text manipulation functions")
    
    # Test 1: CONCAT function - String concatenation
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "CONCAT - String concatenation", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?greeting WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(CONCAT("Hello, ", ?name, "!") AS ?greeting)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)
    
    # Test 2: STR function - Convert to string
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "STR - Convert to string", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?age ?ageStr WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                ?person ex:hasAge ?age .
                BIND(STR(?age) AS ?ageStr)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)
    
    # Test 3: SUBSTR function - Substring extraction
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "SUBSTR - Substring extraction", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?firstThree WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(SUBSTR(?name, 1, 3) AS ?firstThree)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)
    
    # Test 4: STRLEN function - String length
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "STRLEN - String length", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?nameLength WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(STRLEN(?name) AS ?nameLength)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)
    
    # Test 5: UCASE function - Uppercase conversion
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "UCASE - Uppercase conversion", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?upperName WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(UCASE(?name) AS ?upperName)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)
    
    # Test 6: LCASE function - Lowercase conversion
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "LCASE - Lowercase conversion", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?lowerName WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(LCASE(?name) AS ?lowerName)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)

async def test_advanced_string_builtins(sparql_impl, test_results):
    """Test advanced string built-in functions using TestToolUtils."""
    TestToolUtils.print_test_section_header("4. ADVANCED STRING BUILT-INS", "Complex string operations")
    
    # Test 1: REPLACE function - String replacement
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "REPLACE - String replacement", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?modifiedName WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(REPLACE(?name, " ", "_") AS ?modifiedName)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)
    
    # Test 2: STRBEFORE function - String before substring
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "STRBEFORE - String before substring", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?firstName WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(STRBEFORE(?name, " ") AS ?firstName)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)
    
    # Test 3: STRAFTER function - String after substring
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "STRAFTER - String after substring", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?lastName WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(STRAFTER(?name, " ") AS ?lastName)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)
    
    # Test 4: CONTAINS function - String contains check
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "CONTAINS - String contains check", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?containsA WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(CONTAINS(?name, "a") AS ?containsA)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)
    
    # Test 5: STRSTARTS function - String starts with check
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "STRSTARTS - String starts with check", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?startsWithA WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(STRSTARTS(?name, "A") AS ?startsWithA)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)
    
    # Test 6: STRENDS function - String ends with check
    result = await TestToolUtils.run_test_query(sparql_impl, SPACE_ID, "STRENDS - String ends with check", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?endsWithE WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                BIND(STRENDS(?name, "e") AS ?endsWithE)
            }}
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)

if __name__ == "__main__":
    asyncio.run(test_string_builtins())
