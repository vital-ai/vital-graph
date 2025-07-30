#!/usr/bin/env python3
"""
VALUES Query Test Script - Refactored with Test Utilities
=========================================================

Test SPARQL VALUES clause functionality in VitalGraph's PostgreSQL-backed SPARQL engine.
This file focuses specifically on VALUES clause translation and execution.

VALUES clauses allow inline data binding:
- Single variable VALUES: VALUES ?var { "value1" "value2" }
- Multi-variable VALUES: VALUES (?var1 ?var2) { ("a" "b") ("c" "d") }
- VALUES with FILTER, OPTIONAL, UNION, BIND patterns
- Complex VALUES queries with multiple graph patterns
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

async def run_values_query(sparql_impl, query_name, query):
    """Run a single VALUES query using TestToolUtils for clean, maintainable code."""
    # Use the utility function to run the complete test with all features
    result = await TestToolUtils.run_test_query(
        sparql_impl=sparql_impl,
        space_id=SPACE_ID,
        query_name=query_name,
        query=query,
        enable_algebra_logging=True,
        max_results=10  # Show up to 10 results for VALUES queries
    )
    return result

async def test_values_queries():
    """Test VALUES clause functionality with various scenarios using TestToolUtils."""
    print("📊 VALUES Query Tests - Refactored with Utilities")
    print("=" * 50)
    
    # Initialize
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    space_impl = impl.db_impl.get_space_impl()
    sparql_impl = PostgreSQLSparqlImpl(space_impl)
    
    print(f"✅ Connected | Testing VALUES patterns with utility modules")
    
    # Track test results for summary
    test_results = []
    
    TestToolUtils.print_test_section_header("0. UTILITY QUERIES", "Debug algebra and predicate checking queries")
    
    # Test 1: Debug VALUES algebra (from debug_values_algebra)
    result = await run_values_query(sparql_impl, "Debug VALUES algebra - multi-variable", f"""
        SELECT ?name ?population WHERE {{
            VALUES (?name ?population) {{
                ("New York" 8336817)
                ("Los Angeles" 3979576)
            }}
        }}
    """)
    test_results.append(result)
    
    # Test 2: Debug VALUES algebra - single variable (from debug_values_algebra)
    result = await run_values_query(sparql_impl, "Debug VALUES algebra - single variable", f"""
        SELECT ?color WHERE {{
            VALUES ?color {{ "Red" "Green" "Blue" }}
        }}
    """)
    test_results.append(result)
    
    # Test 3: Check available predicates (from check_available_predicates)
    result = await run_values_query(sparql_impl, "Check available predicates", f"""
        SELECT DISTINCT ?p WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?s ?p ?o .
            }}
        }}
        ORDER BY ?p
        LIMIT 20
    """)
    test_results.append(result)
    
    # Test 4: Check specific predicate existence (from check_available_predicates)
    result = await run_values_query(sparql_impl, "Check specific predicate existence", f"""
        SELECT ?s ?o WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?s <http://example.org/hasPopulation> ?o .
            }}
        }}
        LIMIT 1
    """)
    test_results.append(result)
    
    TestToolUtils.print_test_section_header("1. DEBUG BIND MAPPING TESTS", "Testing BIND variable mapping in simple and complex patterns")
    
    # Test 1: Simple BIND (from debug_bind_mapping)
    result = await run_values_query(sparql_impl, "Simple BIND", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?type WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?entity ex:hasName "New York" ;
                       a ex:City .
                BIND("City" AS ?type)
                BIND(?entity AS ?name)
            }}
        }}
    """)
    test_results.append(result)
    
    # Test 2: VALUES + BIND (from debug_bind_mapping)
    result = await run_values_query(sparql_impl, "VALUES + BIND", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?type WHERE {{
            VALUES ?name {{ "New York" }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?entity ex:hasName ?name ;
                       a ex:City .
                BIND("City" AS ?type)
            }}
        }}
    """)
    test_results.append(result)
    
    # Test 3: UNION + BIND (from debug_bind_mapping)
    result = await run_values_query(sparql_impl, "UNION + BIND", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?type WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                {{
                    ?entity ex:hasName "New York" ;
                           a ex:City .
                    BIND("City" AS ?type)
                    BIND(?entity AS ?name)
                }} UNION {{
                    ?entity ex:hasTitle "The Great Gatsby" ;
                           a ex:Book .
                    BIND("Book" AS ?type)
                    BIND(?entity AS ?name)
                }}
            }}
        }}
    """)
    test_results.append(result)
    
    # Test 4: VALUES + UNION + BIND (from debug_bind_mapping)
    result = await run_values_query(sparql_impl, "VALUES + UNION + BIND", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?type WHERE {{
            VALUES ?name {{ "New York" "The Great Gatsby" }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                {{
                    ?entity ex:hasName ?name ;
                           a ex:City .
                    BIND("City" AS ?type)
                }} UNION {{
                    ?entity ex:hasTitle ?name ;
                           a ex:Book .
                    BIND("Book" AS ?type)
                }}
            }}
        }}
    """)
    test_results.append(result)
    
    TestToolUtils.print_test_section_header("2. SIMPLE VALUES-ONLY DEBUG", "Testing basic VALUES structure and algebra patterns")
    
    # Test 5: Single variable VALUES (from test_simple_values_only)
    result = await run_values_query(sparql_impl, "Single variable VALUES debug", f"""
        SELECT ?color WHERE {{
            VALUES ?color {{ "Red" "Green" "Blue" }}
        }}
    """)
    test_results.append(result)
    
    # Test 6: Multi-variable VALUES (from test_simple_values_only)
    result = await run_values_query(sparql_impl, "Multi-variable VALUES debug", f"""
        SELECT ?name ?code WHERE {{
            VALUES (?name ?code) {{
                ("USA" "US")
                ("Canada" "CA")
                ("Mexico" "MX")
            }}
        }}
    """)
    test_results.append(result)
    
    TestToolUtils.print_test_section_header("3. BASIC SINGLE VARIABLE VALUES", "Testing fundamental single-variable VALUES patterns")
    
    # Test 7: Simple color VALUES
    result = await run_values_query(sparql_impl, "Simple color VALUES", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?color WHERE {{
            VALUES ?color {{ "Red" "Green" "Blue" }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?colorEntity ex:hasName ?color .
            }}
        }}
    """)
    test_results.append(result)
    
    # Test 8: Country code VALUES
    result = await run_values_query(sparql_impl, "Country code VALUES", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?code ?name WHERE {{
            VALUES ?code {{ "USA" "CAN" "MEX" }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?country ex:hasCode ?code ;
                        ex:hasName ?name .
            }}
        }}
    """)
    test_results.append(result)
    
    # Test 9: Book year VALUES
    result = await run_values_query(sparql_impl, "Book year VALUES", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?year ?title WHERE {{
            VALUES ?year {{ 1925 1949 1960 }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?book ex:hasYear ?year ;
                     ex:hasTitle ?title .
            }}
        }}
    """)
    test_results.append(result)
    
    TestToolUtils.print_test_section_header("4. MULTI-VARIABLE VALUES", "Testing VALUES with multiple variables and tuples")
    
    # Test 10: City name and population VALUES
    result = await run_values_query(sparql_impl, "City name and population VALUES", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?population WHERE {{
            VALUES (?name ?population) {{
                ("New York" 8336817)
                ("Los Angeles" 3979576)
                ("Chicago" 2693976)
            }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?city ex:hasName ?name ;
                     ex:hasPopulation ?population .
            }}
        }}
    """)
    test_results.append(result)
    
    # Test 11: Book title and author VALUES
    result = await run_values_query(sparql_impl, "Book title and author VALUES", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?title ?author ?year WHERE {{
            VALUES (?title ?author) {{
                ("The Great Gatsby" "F. Scott Fitzgerald")
                ("1984" "George Orwell")
                ("To Kill a Mockingbird" "Harper Lee")
            }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?book ex:hasTitle ?title ;
                     ex:hasAuthor ?author ;
                     ex:hasYear ?year .
            }}
        }}
    """)
    test_results.append(result)
    
    # Test 12: Country name and code VALUES
    result = await run_values_query(sparql_impl, "Country name and code VALUES", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?code ?continent WHERE {{
            VALUES (?name ?code) {{
                ("United States" "USA")
                ("Canada" "CAN")
                ("Mexico" "MEX")
            }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?country ex:hasName ?name ;
                        ex:hasCode ?code ;
                        ex:hasContinent ?continent .
            }}
        }}
    """)
    test_results.append(result)
    
    TestToolUtils.print_test_section_header("5. VALUES WITH FILTERS", "Testing VALUES combined with FILTER conditions")
    
    # Test 17: VALUES with population filter
    result = await run_values_query(sparql_impl, "VALUES with population filter", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?population WHERE {{
            VALUES ?name {{ "New York" "Los Angeles" "Chicago" "Houston" "Phoenix" }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?city ex:hasName ?name ;
                     ex:hasPopulation ?population .
            }}
            FILTER(?population > 3000000)
        }}
    """)
    test_results.append(result)
    
    # Test 18: VALUES with string filter
    result = await run_values_query(sparql_impl, "VALUES with string filter", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?title ?author ?year WHERE {{
            VALUES ?author {{ "F. Scott Fitzgerald" "George Orwell" "Harper Lee" }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?book ex:hasAuthor ?author ;
                     ex:hasTitle ?title ;
                     ex:hasYear ?year .
            }}
            FILTER(CONTAINS(?title, "a"))
        }}
    """)
    test_results.append(result)
    
    # Test 19: VALUES with numeric range filter
    result = await run_values_query(sparql_impl, "VALUES with numeric range filter", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?title ?year WHERE {{
            VALUES ?year {{ 1925 1949 1960 }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?book ex:hasYear ?year ;
                     ex:hasTitle ?title .
            }}
            FILTER(?year >= 1940 && ?year <= 1970)
        }}
    """)
    test_results.append(result)
    
    TestToolUtils.print_test_section_header("6. VALUES WITH OPTIONAL", "Testing VALUES combined with OPTIONAL patterns")
    
    # Test 20: VALUES with optional ISBN
    result = await run_values_query(sparql_impl, "VALUES with optional ISBN", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?title ?author ?isbn WHERE {{
            VALUES ?title {{ "The Great Gatsby" "1984" "To Kill a Mockingbird" }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?book ex:hasTitle ?title ;
                     ex:hasAuthor ?author .
                OPTIONAL {{
                    ?book ex:hasISBN ?isbn .
                }}
            }}
        }}
    """)
    test_results.append(result)
    
    # Test 21: VALUES with optional color hex
    result = await run_values_query(sparql_impl, "VALUES with optional color hex", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?hex WHERE {{
            VALUES ?name {{ "Red" "Green" "Blue" "Yellow" "Purple" }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?color ex:hasName ?name .
                OPTIONAL {{
                    ?color ex:hasHex ?hex .
                }}
            }}
        }}
    """)
    test_results.append(result)
    
    TestToolUtils.print_test_section_header("7. VALUES WITH UNION", "Testing VALUES combined with UNION patterns")
    
    # Test 22: VALUES with UNION types
    result = await run_values_query(sparql_impl, "VALUES with UNION types", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?type WHERE {{
            VALUES ?name {{ "New York" "The Great Gatsby" "Red" }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                {{
                    ?entity ex:hasName ?name ;
                           a ex:City .
                    BIND("City" AS ?type)
                }} UNION {{
                    ?entity ex:hasTitle ?name ;
                           a ex:Book .
                    BIND("Book" AS ?type)
                }} UNION {{
                    ?entity ex:hasName ?name ;
                           a ex:Color .
                    BIND("Color" AS ?type)
                }}
            }}
        }}
    """)
    test_results.append(result)
    
    # Test 10: Complex VALUES with UNION and BIND
    result = await run_values_query(sparql_impl, "Complex VALUES with UNION and BIND", f"""
        PREFIX ex: <http://example.org/>
        PREFIX test: <http://example.org/test#>
        SELECT ?entity ?label ?sourceType ?category WHERE {{
            VALUES ?label {{ "TestEntity1" "TestEntity2" "John" "Jane" }}
            {{
                GRAPH <{GRAPH_URI}> {{
                    ?entity test:hasName ?label .
                    BIND("test_entity" AS ?sourceType)
                    BIND("test" AS ?category)
                }}
            }}
            UNION
            {{
                GRAPH <{GLOBAL_GRAPH_URI}> {{
                    ?entity ex:hasName ?label .
                    BIND("global_person" AS ?sourceType)
                    BIND("person" AS ?category)
                }}
            }}
        }}
        ORDER BY ?sourceType ?label
    """)
    test_results.append(result)
    
    TestToolUtils.print_test_section_header("8. EMPTY VALUES AND EDGE CASES", "Testing empty VALUES and edge cases")
    
    # Test 23: VALUES with non-existent data
    result = await run_values_query(sparql_impl, "VALUES with non-existent data", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?population WHERE {{
            VALUES (?name ?population) {{
                ("NonExistent City" 999999)
                ("Fake Place" 888888)
            }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?city ex:hasName ?name ;
                     ex:hasPopulation ?population .
            }}
        }}
    """)
    test_results.append(result)
    
    # Test 24: Single value in VALUES
    result = await run_values_query(sparql_impl, "Single value in VALUES", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?population WHERE {{
            VALUES ?name {{ "New York" }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?city ex:hasName ?name ;
                     ex:hasPopulation ?population .
            }}
        }}
    """)
    test_results.append(result)
    
    TestToolUtils.print_test_section_header("9. VALUES WITH BIND", "Testing VALUES combined with BIND expressions")
    
    # Test 25: VALUES with BIND calculations
    result = await run_values_query(sparql_impl, "VALUES with BIND calculations", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?population ?populationMillion WHERE {{
            VALUES (?name ?population) {{
                ("New York" 8336817)
                ("Los Angeles" 3979576)
                ("Chicago" 2693976)
            }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?city ex:hasName ?name ;
                     ex:hasPopulation ?population .
            }}
            BIND(?population / 1000000.0 AS ?populationMillion)
        }}
    """)
    test_results.append(result)
    
    # Test 26: VALUES with BIND string operations
    result = await run_values_query(sparql_impl, "VALUES with BIND string operations", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?code ?fullName WHERE {{
            VALUES (?name ?code) {{
                ("United States" "USA")
                ("Canada" "CAN")
                ("Mexico" "MEX")
            }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?country ex:hasName ?name ;
                        ex:hasCode ?code .
            }}
            BIND(CONCAT(?name, " (", ?code, ")") AS ?fullName)
        }}
    """)
    test_results.append(result)
    
    TestToolUtils.print_test_section_header("10. COMPLEX VALUES QUERIES", "Testing complex queries combining VALUES with multiple patterns")
    
    # Test 27: VALUES with multiple graph patterns
    result = await run_values_query(sparql_impl, "VALUES with multiple graph patterns", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?cityName ?countryName ?population WHERE {{
            VALUES (?cityName ?countryCode) {{
                ("New York" "USA")
                ("Los Angeles" "USA")
                ("Chicago" "USA")
            }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?city ex:hasName ?cityName ;
                     ex:hasPopulation ?population ;
                     ex:hasCountry ?countryCode .
                ?country ex:hasCode ?countryCode ;
                        ex:hasName ?countryName .
            }}
        }}
    """)
    test_results.append(result)
    
    # Test 28: VALUES with aggregation
    result = await run_values_query(sparql_impl, "VALUES with aggregation", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?countryCode (AVG(?population) AS ?avgPopulation) WHERE {{
            VALUES ?countryCode {{ "USA" }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?city ex:hasCountry ?countryCode ;
                     ex:hasPopulation ?population .
            }}
        }}
        GROUP BY ?countryCode
    """)
    test_results.append(result)
    
    TestToolUtils.print_test_section_header("8. VALUES EDGE CASES", "Testing empty VALUES and edge cases")
    
    # Test 15: Single value in VALUES (edge case)
    result = await run_values_query(sparql_impl, "Single value in VALUES", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?population WHERE {{
            VALUES ?name {{ "New York" }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?city ex:hasName ?name ;
                     ex:hasPopulation ?population .
            }}
        }}
    """)
    test_results.append(result)
    
    # Test 16: VALUES with year range filter
    result = await run_values_query(sparql_impl, "VALUES with year range filter", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?title ?year WHERE {{
            VALUES ?year {{ 1925 1960 1949 1813 1951 1953 1962 1937 1884 1950 }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?book ex:hasPublicationYear ?year ;
                     ex:hasTitle ?title .
            }}
            FILTER(?year >= 1940 && ?year <= 1970)
        }}
        ORDER BY ?year
    """)
    test_results.append(result)
    
    # Test results summary using TestToolUtils
    TestToolUtils.print_test_summary(test_results)
    
    # Performance summary
    print(f"\n📊 Cache: {sparql_impl.term_cache.size()} terms")
    
    await impl.db_impl.disconnect()
    print("\n✅ VALUES Query Tests Complete!")
    print("📊 Test data includes cities, countries, books, and colors with comprehensive VALUES clause testing")
    
    # Return test results for aggregation
    return test_results

if __name__ == "__main__":
    asyncio.run(test_values_queries())
