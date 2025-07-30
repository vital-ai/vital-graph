#!/usr/bin/env python3
"""
VALUES Clause Test Script
=========================

Focused testing of SPARQL VALUES clauses with inline data binding
using test data specifically designed for VALUES clause testing.
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

async def run_query(sparql_impl, name, sparql, debug=False):
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
            import logging
            logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(levelname)s - %(message)s')
            console_handler.setFormatter(formatter)
            sparql_logger.addHandler(console_handler)
    
    try:
        start_time = time.time()
        results = await sparql_impl.execute_sparql_query(SPACE_ID, sparql)
        query_time = time.time() - start_time
        
        print(f"    ⏱️  {query_time:.3f}s | {len(results)} results")
        
        # Show all results for VALUES queries (usually small result sets)
        for i, result in enumerate(results):
            print(f"    [{i+1}] {dict(result)}")
            
        if debug:
            print("\n" + "=" * 60)
            
            # Add algebra debugging for VALUES queries
            if "VALUES" in sparql:
                try:
                    from rdflib.plugins.sparql import prepareQuery
                    prepared = prepareQuery(sparql)
                    print(f"    🔍 Algebra: {prepared.algebra}")
                    
                    # Look for ToMultiSet patterns
                    def find_tomultiset(pattern, path=""):
                        if hasattr(pattern, 'name'):
                            if pattern.name == 'ToMultiSet':
                                print(f"    🎯 ToMultiSet found at {path}")
                                if hasattr(pattern, 'multiset'):
                                    print(f"       multiset: {pattern.multiset}")
                                if hasattr(pattern, 'var'):
                                    print(f"       var: {pattern.var}")
                            
                            # Recurse
                            for attr in ['p', 'p1', 'p2', 'left', 'right']:
                                if hasattr(pattern, attr):
                                    nested = getattr(pattern, attr)
                                    if nested and hasattr(nested, 'name'):
                                        find_tomultiset(nested, f"{path}.{attr}")
                    
                    find_tomultiset(prepared.algebra)
                except Exception as debug_e:
                    print(f"    🔍 Algebra debug failed: {debug_e}")
    
    except Exception as e:
        print(f"    ❌ Error: {e}")
        if debug:
            import traceback
            traceback.print_exc()
    
    finally:
        if debug:
            # Restore original logging level
            sparql_logger.setLevel(original_level)

async def debug_values_algebra():
    """Debug VALUES query algebra structure."""
    print("🔍 Debug VALUES Algebra")
    print("=" * 50)
    
    from rdflib.plugins.sparql import prepareQuery
    
    # Simple VALUES query
    sparql = f'''
        PREFIX ex: <http://example.org/>
        SELECT ?name ?population WHERE {{
            VALUES (?name ?population) {{
                ("New York" 8336817)
                ("Los Angeles" 3979576)
                ("Chicago" 2693976)
            }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?city ex:hasName ?name .
                ?city ex:hasPopulation ?population .
            }}
        }}
    '''
    
    print("SPARQL Query:")
    print(sparql)
    print()
    
    prepared_query = prepareQuery(sparql)
    print("Algebra structure:")
    print(prepared_query.algebra)
    print()
    print("Projection variables:")
    print(prepared_query.algebra.get('PV', []))
    print()
    
    # Detailed pattern analysis
    def analyze_pattern(pattern, depth=0):
        indent = '  ' * depth
        print(f'{indent}Pattern: {pattern.name if hasattr(pattern, "name") else type(pattern)}')
        
        if hasattr(pattern, 'name') and pattern.name == 'ToMultiSet':
            print(f'{indent}  ToMultiSet found!')
            print(f'{indent}  Attributes: {[attr for attr in dir(pattern) if not attr.startswith("_")]}')
            if hasattr(pattern, 'p'):
                print(f'{indent}  p (nested pattern): {pattern.p}')
            if hasattr(pattern, 'var'):
                print(f'{indent}  var: {pattern.var}')
            if hasattr(pattern, 'res'):
                print(f'{indent}  res: {pattern.res}')
            if hasattr(pattern, 'multiset'):
                print(f'{indent}  multiset: {pattern.multiset}')
        
        # Recurse into nested patterns
        for attr in ['p', 'p1', 'p2', 'left', 'right']:
            if hasattr(pattern, attr):
                nested = getattr(pattern, attr)
                if nested and hasattr(nested, 'name'):
                    analyze_pattern(nested, depth + 1)
    
    print("Detailed Pattern Analysis:")
    analyze_pattern(prepared_query.algebra)
    print()
    
    # Single variable VALUES
    sparql_single = f'''
        PREFIX ex: <http://example.org/>
        SELECT ?color WHERE {{
            VALUES ?color {{ "Red" "Green" "Blue" }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?colorEntity ex:hasName ?color .
            }}
        }}
    '''
    
    print("Single Variable VALUES Query:")
    print(sparql_single)
    print()
    
    prepared_single = prepareQuery(sparql_single)
    print("Single VALUES Algebra structure:")
    print(prepared_single.algebra)
    print()
    
    print("Single VALUES Pattern Analysis:")
    analyze_pattern(prepared_single.algebra)
    print()

# Global variables for database connection
impl = None
sparql_impl = None

async def setup_connection():
    """Initialize database connection for tests."""
    global impl, sparql_impl
    
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
        await impl.db_impl.disconnect()
        print("🔌 Disconnected")

async def check_available_predicates():
    """Check what predicates are available in the database."""
    print("\n🔍 CHECKING AVAILABLE PREDICATES:")
    
    try:
        # Check predicates in global graph
        results = await sparql_impl.execute_sparql_query(
            SPACE_ID,
            f'''
                SELECT DISTINCT ?p WHERE {{
                    GRAPH <{GLOBAL_GRAPH_URI}> {{
                        ?s ?p ?o .
                    }}
                }}
                ORDER BY ?p
                LIMIT 20
            '''
        )
        print(f"\n  Predicates in global graph ({len(results)} found):")
        for i, result in enumerate(results):
            print(f"    [{i+1}] {result['p']}")
            
        # Check for specific VALUES test predicates
        test_predicates = [
            "http://example.org/hasPopulation",
            "http://example.org/hasCode", 
            "http://example.org/hasYear",
            "http://example.org/hasISBN",
            "http://example.org/hasAuthor",
            "http://example.org/hasHex",
            "http://example.org/hasContinent"
        ]
        
        print("\n  Checking specific VALUES test predicates:")
        for predicate in test_predicates:
            try:
                check_results = await sparql_impl.execute_sparql_query(
                    SPACE_ID,
                    f'''
                        SELECT ?s ?o WHERE {{
                            GRAPH <{GLOBAL_GRAPH_URI}> {{
                                ?s <{predicate}> ?o .
                            }}
                        }}
                        LIMIT 1
                    '''
                )
                exists = len(check_results) > 0
                status = "✅" if exists else "❌"
                count = len(check_results) if exists else 0
                print(f"    {status} {predicate} ({count} triples)")
            except Exception as e:
                print(f"    ❌ {predicate} - Error: {e}")
                
    except Exception as e:
        print(f"    ❌ Error checking predicates: {e}")

async def debug_bind_mapping():
    """Debug BIND variable mapping in simple and complex patterns."""
    print("\n🔧 BIND VARIABLE MAPPING DEBUG:")
    
    # Enable debug logging for this test
    import logging
    logger = logging.getLogger('vitalgraph.db.postgresql.postgresql_sparql_impl')
    logger.setLevel(logging.DEBUG)
    
    # Test 1: Simple BIND without VALUES
    print("\n  Simple BIND test (no VALUES):")
    await run_query(sparql_impl, "Simple BIND", f"""
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
    
    # Test 2: Simple VALUES + BIND (no UNION)
    print("\n  VALUES + BIND test (no UNION):")
    await run_query(sparql_impl, "VALUES + BIND", f"""
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
    
    # Test 3: Simple UNION + BIND (no VALUES)
    print("\n  UNION + BIND test (no VALUES):")
    await run_query(sparql_impl, "UNION + BIND", f"""
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
    
    # Test 4: Full VALUES + UNION + BIND (the problematic case)
    print("\n  VALUES + UNION + BIND test (problematic case):")
    await run_query(sparql_impl, "VALUES + UNION + BIND", f"""
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

async def test_simple_values_only():
    """Debug VALUES structure and algebra patterns."""
    print("\n🔍 SIMPLE VALUES-ONLY DEBUG:")
    
    # Test 1: Single variable VALUES
    print("\n  Single variable VALUES:")
    try:
        results = await sparql_impl.execute_sparql_query(
            SPACE_ID,
            '''
                SELECT ?color WHERE {
                    VALUES ?color { "Red" "Green" "Blue" }
                }
            '''
        )
        print(f"    ⏱️  {len(results)} results")
        for i, result in enumerate(results):
            print(f"    [{i+1}] {dict(result)}")
    except Exception as e:
        print(f"    ❌ Error: {e}")
    
    # Test 2: Multi-variable VALUES
    print("\n  Multi-variable VALUES:")
    try:
        results = await sparql_impl.execute_sparql_query(
            SPACE_ID,
            '''
                SELECT ?name ?code WHERE {
                    VALUES (?name ?code) {
                        ("USA" "US")
                        ("Canada" "CA")
                        ("Mexico" "MX")
                    }
                }
            '''
        )
        print(f"    ⏱️  {len(results)} results")
        for i, result in enumerate(results):
            print(f"    [{i+1}] {dict(result)}")
    except Exception as e:
        print(f"    ❌ Error: {e}")

async def test_basic_single_variable_values():
    """Test basic single-variable VALUES queries."""
    print("\n🎯 BASIC SINGLE VARIABLE VALUES:")
    
    # Simple color VALUES
    await run_query(
        sparql_impl,
        "Simple color VALUES",
        f'''
            PREFIX ex: <http://example.org/>
            SELECT ?color WHERE {{
                VALUES ?color {{ "Red" "Green" "Blue" }}
                GRAPH <{GLOBAL_GRAPH_URI}> {{
                    ?colorEntity ex:hasName ?color .
                }}
            }}
        '''
    )
    
    await run_query(
        sparql_impl,
        "Country code VALUES",
        f'''
            PREFIX ex: <http://example.org/>
            SELECT ?code ?name WHERE {{
                VALUES ?code {{ "USA" "CAN" "MEX" }}
                GRAPH <{GLOBAL_GRAPH_URI}> {{
                    ?country ex:hasCode ?code ;
                            ex:hasName ?name .
                }}
            }}
        '''
    )
    
    await run_query(
        sparql_impl,
        "Book year VALUES",
        f'''
            PREFIX ex: <http://example.org/>
            SELECT ?year ?title WHERE {{
                VALUES ?year {{ 1925 1949 1960 }}
                GRAPH <{GLOBAL_GRAPH_URI}> {{
                    ?book ex:hasYear ?year ;
                         ex:hasTitle ?title .
                }}
            }}
        '''
    )

async def test_multi_variable_values():
    """Test multi-variable VALUES clauses with tuples."""
    print("\n🎯 MULTI-VARIABLE VALUES:")
    
    await run_query(sparql_impl, "City name and population VALUES", f"""
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
    
    await run_query(sparql_impl, "Book title and author VALUES", f"""
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
    
    await run_query(sparql_impl, "Country name and code VALUES", f"""
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

async def test_values_with_filters():
    """Test VALUES clauses combined with FILTER conditions."""
    print("\n🎯 VALUES WITH FILTERS:")
    
    await run_query(sparql_impl, "VALUES with population filter", f"""
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
    
    await run_query(sparql_impl, "VALUES with string filter", f"""
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
    
    await run_query(sparql_impl, "VALUES with numeric range filter", f"""
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

async def test_values_with_optional():
    """Test VALUES clauses combined with OPTIONAL patterns."""
    print("\n🎯 VALUES WITH OPTIONAL:")
    
    await run_query(sparql_impl, "VALUES with optional ISBN", f"""
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
    
    await run_query(sparql_impl, "VALUES with optional color hex", f"""
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

async def test_values_with_union():
    """Test VALUES clauses combined with UNION patterns."""
    print("\n🎯 VALUES WITH UNION:")
    
    await run_query(sparql_impl, "VALUES with UNION types", f"""
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

async def test_empty_and_edge_cases():
    """Test empty VALUES and edge cases."""
    print("\n🎯 EMPTY VALUES AND EDGE CASES:")
    
    await run_query(sparql_impl, "VALUES with non-existent data", f"""
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
    
    await run_query(sparql_impl, "Single value in VALUES", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?population WHERE {{
            VALUES ?name {{ "New York" }}
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?city ex:hasName ?name ;
                     ex:hasPopulation ?population .
            }}
        }}
    """)

async def test_values_with_bind():
    """Test VALUES clauses combined with BIND expressions."""
    print("\n🎯 VALUES WITH BIND:")
    
    await run_query(sparql_impl, "VALUES with BIND calculations", f"""
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
    
    await run_query(sparql_impl, "VALUES with BIND string operations", f"""
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

async def test_complex_values_queries():
    """Test complex queries combining VALUES with multiple patterns."""
    print("\n🎯 COMPLEX VALUES QUERIES:")
    
    await run_query(sparql_impl, "VALUES with multiple graph patterns", f"""
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
    
    await run_query(sparql_impl, "VALUES with aggregation", f"""
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

async def main():
    """Main test execution function."""
    print("🎯 SPARQL VALUES Clause Tests")
    print("=" * 50)
    
    # Debug algebra structure first
    await debug_values_algebra()
    
    # Setup database connection
    await setup_connection()
    
    try:
        # Check what predicates are available first
        await check_available_predicates()
        
        # Run all VALUES test categories for comprehensive verification
        await test_simple_values_only()  # Basic VALUES structure
        await test_basic_single_variable_values()  # Single variable VALUES
        await test_multi_variable_values()  # Multi-variable VALUES
        print("\n🔧 VALUES+UNION working perfectly, now testing more complex cases")
        await test_values_with_union()  # VALUES+UNION (already working)
        print("\n🔧 Now testing VALUES with BIND expressions")
        await test_values_with_bind()  # VALUES+BIND combinations
        print("\n🔧 Now testing VALUES with FILTER conditions")
        await test_values_with_filters()  # VALUES+FILTER combinations
        print("\n🔧 Now testing VALUES with OPTIONAL patterns")
        await test_values_with_optional()  # VALUES+OPTIONAL combinations
        print("\n🔧 Now testing VALUES edge cases")
        await test_empty_and_edge_cases()  # Edge cases and error handling
        print("\n🔧 Now testing complex VALUES queries")
        await test_complex_values_queries()  # Complex multi-pattern VALUES
        
        print("\n" + "=" * 50)
        print("🎯 VALUES Clause Tests Complete!")
        
    except Exception as e:
        print(f"\n❌ Test execution failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Clean up connection
        await cleanup_connection()

if __name__ == "__main__":
    asyncio.run(main())
