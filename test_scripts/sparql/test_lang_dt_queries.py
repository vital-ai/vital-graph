#!/usr/bin/env python3
"""
LANG() and DATATYPE() Filter Functions Test Script
==================================================

Comprehensive testing of SPARQL LANG() and DATATYPE() filter functions
using test data with language-tagged literals and typed literals.

The LANG() function extracts the language tag from language-tagged literals.
The DATATYPE() function returns the datatype URI of typed literals.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.db.postgresql.postgresql_sparql_impl import PostgreSQLSparqlImpl

# Reduce logging chatter
logging.getLogger('vitalgraph.db.postgresql.postgresql_space_impl').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.rdf.rdf_utils').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.db.postgresql.postgresql_cache_term').setLevel(logging.WARNING)

# Configuration
SPACE_ID = "space_test"
GRAPH_URI = "http://vital.ai/graph/test"
GLOBAL_GRAPH_URI = "urn:___GLOBAL"

async def run_single_test(sparql_impl, name, sparql, expected_count=None, debug=False):
    """Execute a single SPARQL query and display results."""
    print(f"\n  {name}:")
    
    if debug:
        print(f"\n🔍 DEBUG QUERY: {name}")
        print("=" * 60)
        print("SPARQL:")
        print(sparql)
        print("\n" + "-" * 60)
        
        # Enable debug logging temporarily
        sparql_logger = logging.getLogger('vitalgraph.db.postgresql.postgresql_sparql_impl')
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
        
        result_count = len(results)
        status_icon = "✅" if expected_count is None or result_count == expected_count else "⚠️"
        expected_str = f" (expected {expected_count})" if expected_count is not None else ""
        
        print(f"    {status_icon} {query_time:.3f}s | {result_count} results{expected_str}")
        
        # Show results (limit to first 10 for readability)
        for i, result in enumerate(results[:10]):
            print(f"    [{i+1}] {dict(result)}")
        
        if len(results) > 10:
            print(f"    ... and {len(results) - 10} more results")
            
        if debug:
            print("\n" + "=" * 60)
            
        return result_count
            
    except Exception as e:
        print(f"    ❌ Error: {e}")
        if debug:
            import traceback
            traceback.print_exc()
        return 0
    
    finally:
        if debug:
            # Restore original logging level
            sparql_logger.setLevel(original_level)

# Global variables for database connection
impl = None
sparql_impl = None

async def setup_connection():
    """Initialize database connection for tests."""
    global impl, sparql_impl
    
    print("🔌 Setting up database connection...")
    
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    space_impl = impl.db_impl.get_space_impl()
    sparql_impl = PostgreSQLSparqlImpl(space_impl)
    
    print(f"✅ Connected | Graph: {GRAPH_URI}")

async def cleanup_connection():
    """Clean up database connection."""
    global impl
    if impl:
        if impl.db_impl:
            await impl.db_impl.disconnect()
    print("🔌 Database connection closed")

async def test_lang_function_basic():
    """Test basic LANG() function with language-tagged literals."""
    print("🔍 DIAGNOSTIC QUERIES - Checking Language Tag Storage:\n")
    
    # Direct database query to check what's stored for multilingual_person1
    diagnostic_query = """
    PREFIX ex: <http://example.org/>
    SELECT ?person ?name WHERE {
        ?person ex:hasName ?name .
        FILTER(?person = ex:multilingual_person1)
    } ORDER BY ?name
    """
    
    print("  Raw names for multilingual_person1:")
    diagnostic_results = await sparql_impl.execute_sparql_query(SPACE_ID, diagnostic_query)
    if diagnostic_results:
        for i, result in enumerate(diagnostic_results, 1):
            print(f"    [{i}] {dict(result)}")
    else:
        print("    No results found")
    
    # Check LANG() function output directly
    lang_diagnostic_query = """
    PREFIX ex: <http://example.org/>
    SELECT ?person ?name ?lang WHERE {
        ?person ex:hasName ?name .
        BIND(LANG(?name) AS ?lang)
        FILTER(?person = ex:multilingual_person1)
    } ORDER BY ?name
    """
    
    print("\n  LANG() function output for multilingual_person1:")
    lang_diagnostic_results = await sparql_impl.execute_sparql_query(SPACE_ID, lang_diagnostic_query)
    if lang_diagnostic_results:
        for i, result in enumerate(lang_diagnostic_results, 1):
            print(f"    [{i}] {dict(result)}")
    else:
        print("    No results found")
    
    print("\n🌍 LANG() FUNCTION - BASIC TESTS:\n")
    
    # Test 1: Get language tags from multilingual names
    await run_single_test(sparql_impl, "Extract language tags from multilingual names", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name ?lang WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                BIND(LANG(?name) AS ?lang)
                FILTER(?person = ex:multilingual_person1 || ?person = ex:multilingual_person2 || ?person = ex:multilingual_person3)
            }}
        }}
        ORDER BY ?person ?lang
    """, expected_count=None)
    
    # Test 2: Filter by specific language tag
    await run_single_test(sparql_impl, "Filter names with English language tag", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(LANG(?name) = "en")
            }}
        }}
        ORDER BY ?person
    """, expected_count=None)
    
    # Test 3: Filter by French language tag
    await run_single_test(sparql_impl, "Filter names with French language tag", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(LANG(?name) = "fr")
            }}
        }}
    """, expected_count=None)
    
    # Test 4: Find literals without language tags (empty string)
    await run_single_test(sparql_impl, "Find literals without language tags", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(LANG(?name) = "")
            }}
        }}
    """, expected_count=None)

async def test_datatype_function_basic():
    """Test basic DATATYPE() function with typed literals."""
    print("\n🔢 DATATYPE() FUNCTION - BASIC TESTS:")
    
    # Test 1: Get datatypes from numeric values
    await run_single_test(sparql_impl, "Extract datatypes from ages", f"""
        PREFIX ex: <http://example.org/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?person ?age ?datatype WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
                BIND(DATATYPE(?age) AS ?datatype)
            }}
        }}
        ORDER BY ?person
    """, expected_count=None)
    
    # Test 2: Filter by integer datatype
    await run_single_test(sparql_impl, "Filter values with integer datatype", f"""
        PREFIX ex: <http://example.org/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?person ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
                FILTER(DATATYPE(?age) = xsd:integer)
            }}
        }}
    """, expected_count=None)
    
    # Test 3: Filter by decimal datatype
    await run_single_test(sparql_impl, "Filter values with decimal datatype", f"""
        PREFIX ex: <http://example.org/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?product ?price WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?product ex:hasPrice ?price .
                FILTER(DATATYPE(?price) = xsd:decimal)
            }}
        }}
    """, expected_count=None)
    
    # Test 4: Filter by string datatype
    await run_single_test(sparql_impl, "Filter values with string datatype", f"""
        PREFIX ex: <http://example.org/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(DATATYPE(?name) = xsd:string)
            }}
        }}
    """, expected_count=None)

async def test_lang_datatype_combined():
    """Test combined LANG() and DATATYPE() usage in complex queries."""
    print("\n🔗 COMBINED LANG() AND DATATYPE() TESTS:")
    
    # Test 1: Mixed language and datatype filters
    await run_single_test(sparql_impl, "People with English names and integer ages", f"""
        PREFIX ex: <http://example.org/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?person ?name ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name ;
                        ex:hasAge ?age .
                FILTER(LANG(?name) = "en" && DATATYPE(?age) = xsd:integer)
            }}
        }}
    """, expected_count=None)
    
    # Test 2: Count by language and datatype
    await run_single_test(sparql_impl, "Count names by language", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?lang (COUNT(?name) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                BIND(LANG(?name) AS ?lang)
            }}
        }}
        GROUP BY ?lang
        ORDER BY ?lang
    """, expected_count=None)
    
    # Test 3: Count values by datatype
    await run_single_test(sparql_impl, "Count values by datatype", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?datatype (COUNT(?value) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                {{
                    ?person ex:hasAge ?value .
                    BIND(DATATYPE(?value) AS ?datatype)
                }} UNION {{
                    ?product ex:hasPrice ?value .
                    BIND(DATATYPE(?value) AS ?datatype)
                }}
            }}
        }}
        GROUP BY ?datatype
        ORDER BY ?datatype
    """, expected_count=None)

async def test_lang_datatype_edge_cases():
    """Test edge cases and error conditions for LANG() and DATATYPE()."""
    print("\n🎯 EDGE CASES AND ERROR CONDITIONS:")
    
    # Test 1: LANG() on non-literal values (should return empty string)
    await run_single_test(sparql_impl, "LANG() on URI values", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT ?person ?type ?lang WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ?type .
                BIND(LANG(?type) AS ?lang)
            }}
        }}
        LIMIT 5
    """, expected_count=5)
    
    # Test 2: DATATYPE() on URI values (should return appropriate datatype)
    await run_single_test(sparql_impl, "DATATYPE() on URI values", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT ?person ?type ?datatype WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ?type .
                BIND(DATATYPE(?type) AS ?datatype)
            }}
        }}
        LIMIT 5
    """, expected_count=5)
    
    # Test 3: Complex filter with LANG() and string operations
    await run_single_test(sparql_impl, "Complex LANG() filter with CONTAINS", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(LANG(?name) = "en" && CONTAINS(?name, "John"))
            }}
        }}
    """, expected_count=None)
    
    # Test 4: OPTIONAL with LANG() and DATATYPE()
    await run_single_test(sparql_impl, "OPTIONAL with LANG() and DATATYPE()", f"""
        PREFIX ex: <http://example.org/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?person ?name ?nameType ?age ?ageType WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                OPTIONAL {{ 
                    ?person ex:hasName ?name .
                    BIND(LANG(?name) AS ?nameType)
                }}
                OPTIONAL {{ 
                    ?person ex:hasAge ?age .
                    BIND(DATATYPE(?age) AS ?ageType)
                }}
            }}
        }}
        LIMIT 10
    """, expected_count=10)

async def test_lang_datatype_debug():
    """Debug LANG() and DATATYPE() implementation with detailed logging."""
    print("\n🔍 DEBUG LANG() AND DATATYPE() IMPLEMENTATION:")
    
    # Test 1: Extract datatypes from ages (should be xsd:integer)
    await run_single_test(sparql_impl, "Extract datatypes from ages", f"""
        PREFIX ex: <http://example.org/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?person ?age ?datatype WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
                BIND(DATATYPE(?age) AS ?datatype)
                FILTER(?person IN (ex:person1, ex:person2, ex:person3, ex:person4, ex:person5))
            }}
        }}
        ORDER BY ?person
    """, expected_count=3, debug=True)
    
    # Debug DATATYPE() function
    await run_single_test(sparql_impl, "DEBUG: DATATYPE() function", f"""
        PREFIX ex: <http://example.org/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?person ?age ?datatype WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
                BIND(DATATYPE(?age) AS ?datatype)
            }}
        }}
        LIMIT 3
    """, expected_count=3, debug=True)

async def main():
    """Main test controller - enable/disable tests as needed."""
    print("🧪 SPARQL LANG() and DATATYPE() Filter Functions Test Suite")
    print("=" * 65)
    
    # Setup connection
    await setup_connection()
    
    try:
        # Comprehensive test suite
        await test_lang_function_basic()
        await test_datatype_function_basic()
        await test_lang_datatype_combined()
        await test_lang_datatype_edge_cases()
        
        # Debug tests (enable for detailed investigation)
        # await test_lang_datatype_debug()
        
    finally:
        # Performance summary
        print(f"\n📊 Cache: {sparql_impl.term_cache.size()} terms")
        
        # Cleanup
        await cleanup_connection()
        print("\n✅ LANG() and DATATYPE() Filter Functions Test Complete!")

if __name__ == "__main__":
    asyncio.run(main())
