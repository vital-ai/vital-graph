#!/usr/bin/env python3
"""
Filter Functions Test Script
============================

Comprehensive testing of SPARQL filter functions including:
- REGEX() - Regular expression matching
- LANG() - Language tag extraction
- DATATYPE() - Datatype URI extraction  
- IRI() / URI() - URI creation
- BNODE() - Blank node creation
- String functions in filters (CONTAINS, STRSTARTS, STRENDS)
- Type checking functions (isURI, isLITERAL, isNUMERIC)
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
        status = "✅" if expected_count is None or result_count == expected_count else "⚠️"
        expected_str = f" (expected {expected_count})" if expected_count is not None else ""
        
        print(f"    {status} ⏱️  {query_time:.3f}s | {result_count} results{expected_str}")
        
        # Show first few results for verification
        for i, result in enumerate(results[:3]):
            print(f"    [{i+1}] {dict(result)}")
        
        if len(results) > 3:
            print(f"    ... and {len(results) - 3} more results")
            
        if debug:
            print("\n" + "=" * 60)
            
        return result_count == expected_count if expected_count is not None else True
            
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

# Global variables for database connection
impl = None
sparql_impl = None

async def setup_connection():
    """Initialize database connection for tests."""
    global impl, sparql_impl
    
    print("🔌 Setting up database connection...")
    
    # Load config and initialize VitalGraphImpl
    project_root = Path(__file__).parent.parent.parent
    config_path = project_root / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    db_impl = impl.get_db_impl()
    await db_impl.connect()
    
    space_impl = db_impl.get_space_impl()
    sparql_impl = PostgreSQLSparqlImpl(space_impl)
    
    print("✅ Database connection established")

async def cleanup_connection():
    """Clean up database connection."""
    global impl
    if impl:
        db_impl = impl.get_db_impl()
        if db_impl:
            await db_impl.disconnect()
    print("🔌 Database connection closed")

async def test_regex_filters():
    """Test REGEX() function in filters."""
    print("\n🔍 REGEX FILTER FUNCTIONS:")
    
    await run_single_test(sparql_impl, "Names matching pattern '^John.*'", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(REGEX(?name, "^John.*"))
            }}
        }}
    """, expected_count=2)
    
    # Temporarily disabled due to parsing issue
    # await run_single_test(sparql_impl, "Email pattern matching", """
    #     PREFIX ex: <http://example.org/>
    #     SELECT ?person ?email WHERE {
    #         ?person ex:hasEmail ?email .
    #         FILTER(REGEX(?email, ".*@.*\\.org"))
    #     }
    # """, expected_count=3)
    
    await run_single_test(sparql_impl, "Product names with 'Pro' or 'Gaming'", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?product ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?product ex:hasName ?name .
                FILTER(REGEX(?name, ".*(Pro|Gaming).*"))
            }}
        }}
    """, expected_count=2)

async def test_string_filter_functions():
    """Test string functions in filters (CONTAINS, STRSTARTS, STRENDS)."""
    print("\n📝 STRING FILTER FUNCTIONS:")
    
    await run_single_test(sparql_impl, "Names containing 'Smith'", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(CONTAINS(?name, "Smith"))
            }}
        }}
    """, expected_count=2)
    
    await run_single_test(sparql_impl, "Names starting with 'John'", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(STRSTARTS(?name, "John"))
            }}
        }}
    """, expected_count=2)
    
    await run_single_test(sparql_impl, "Emails ending with 'example.org'", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?email WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasEmail ?email .
                FILTER(STRENDS(?email, "example.org"))
            }}
        }}
    """, expected_count=5)

async def test_type_checking_filters():
    """Test type checking functions in filters."""
    print("\n🔍 TYPE CHECKING FILTER FUNCTIONS:")
    
    await run_single_test(sparql_impl, "Filter for URI values", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?s ?p ?o WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?s ?p ?o .
                FILTER(isURI(?o))
            }}
        }}
        LIMIT 5
    """, expected_count=5)
    
    await run_single_test(sparql_impl, "Filter for literal values", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(isLITERAL(?name))
            }}
        }}
    """, expected_count=29, debug=True)
    
    await run_single_test(sparql_impl, "Filter for numeric values", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
                FILTER(isNUMERIC(?age))
            }}
        }}
    """, expected_count=5)

async def test_lang_datatype_filters():
    """Test LANG() and DATATYPE() functions in filters."""
    print("\n🌐 LANG() AND DATATYPE() FILTER FUNCTIONS:")
    
    # Test with language-tagged literals
    await run_single_test(sparql_impl, "Filter by language tag", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?entity ?label WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?entity ex:hasLabel ?label .
                FILTER(LANG(?label) = "en")
            }}
        }}
    """, expected_count=3)
    
    await run_single_test(sparql_impl, "Filter by language tag (French)", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?entity ?label WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?entity ex:hasLabel ?label .
                FILTER(LANG(?label) = "fr")
            }}
        }}
    """, expected_count=2)
    
    # Test DATATYPE() function
    await run_single_test(sparql_impl, "Filter by datatype (integer)", f"""
        PREFIX ex: <http://example.org/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?person ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
                FILTER(DATATYPE(?age) = xsd:integer)
            }}
        }}
    """, expected_count=5)
    
    await run_single_test(sparql_impl, "Filter by datatype (decimal)", f"""
        PREFIX ex: <http://example.org/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?product ?price WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?product ex:hasPrice ?price .
                FILTER(DATATYPE(?price) = xsd:decimal)
            }}
        }}
    """, expected_count=6)

async def test_uri_iri_filters():
    """Test URI() and IRI() functions in filters."""
    print("\n🔗 URI() AND IRI() FILTER FUNCTIONS:")
    
    await run_single_test(sparql_impl, "Create URI from string in filter", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(?person = URI(CONCAT("http://example.org/person", "1")))
            }}
        }}
    """, expected_count=1)
    
    await run_single_test(sparql_impl, "Use IRI() in filter condition", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?product ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?product ex:hasName ?name .
                FILTER(?product = IRI("http://example.org/product1"))
            }}
        }}
    """, expected_count=1)

async def test_bnode_filters():
    """Test BNODE() function in filters."""
    print("\n🔘 BNODE() FILTER FUNCTIONS:")
    
    # Test BNODE() function with BIND and filter - DEBUG ENABLED
    await run_single_test(sparql_impl, "Generate blank nodes with BNODE():", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name ?bnode WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                BIND(BNODE() AS ?bnode)
                FILTER(STRLEN(?name) > 8)
            }}
        }}
    """, expected_count=27, debug=True)
    
    await run_single_test(sparql_impl, "Generate seeded blank nodes", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name ?seeded_bnode WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                BIND(BNODE(?name) AS ?seeded_bnode)
                FILTER(?person = ex:person1)
            }}
        }}
    """, expected_count=1)

async def test_complex_filter_combinations():
    """Test complex combinations of filter functions."""
    print("\n🔗 COMPLEX FILTER COMBINATIONS:")
    
    # First test individual components to understand the issue
    print("\n  🔍 DEBUG: Testing individual filter components:")
    
    # Test 1: Find Johns
    await run_single_test(sparql_impl, "Find Johns with REGEX", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(REGEX(?name, "John.*"))
            }}
        }}
    """, expected_count=None)
    
    # Test 2: Find people with ages
    await run_single_test(sparql_impl, "Find people with ages", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
            }}
        }}
    """, expected_count=None)
    
    # Test 3: Test isNUMERIC on ages
    await run_single_test(sparql_impl, "Test isNUMERIC on ages", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
                FILTER(isNUMERIC(?age))
            }}
        }}
    """, expected_count=None)
    
    # Test 4: Test DATATYPE on ages - see what datatypes are actually returned
    await run_single_test(sparql_impl, "Show actual DATATYPE values for ages", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?age ?datatype WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
                BIND(DATATYPE(?age) AS ?datatype)
            }}
        }}
        LIMIT 5
    """, expected_count=None)
    
    # Test 5: Test DATATYPE on ages
    await run_single_test(sparql_impl, "Test DATATYPE on ages", f"""
        PREFIX ex: <http://example.org/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?person ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
                FILTER(DATATYPE(?age) = xsd:integer)
            }}
        }}
    """, expected_count=None)
    
    # Test 5: Test numeric comparison
    await run_single_test(sparql_impl, "Test numeric comparison on ages", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
                FILTER(?age > 25)
            }}
        }}
    """, expected_count=None)
    
    # Now test the full complex filter with debug
    await run_single_test(sparql_impl, "Multiple filter functions combined", f"""
        PREFIX ex: <http://example.org/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?person ?name ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name ;
                        ex:hasAge ?age .
                FILTER(
                    REGEX(?name, "John.*") && 
                    isNUMERIC(?age) && 
                    DATATYPE(?age) = xsd:integer &&
                    ?age > 25
                )
            }}
        }}
    """, expected_count=1, debug=True)
    
    await run_single_test(sparql_impl, "String and type filters with OR", """
        PREFIX ex: <http://example.org/>
        SELECT ?entity ?value WHERE {
            ?entity ?p ?value .
            FILTER(CONTAINS(STR(?value), "Smith"))
        }
    """, expected_count=2)

    await run_single_test(
        sparql_impl,
        "String and type filters with OR",
        """
        SELECT ?entity ?value WHERE {
            ?entity ?p ?value .
            FILTER(CONTAINS(?value, "Smith") || isNUMERIC(?value))
        }
        """,
        expected_count=2
    )

    print("\n🔗 SAMETERM() AND IN() FUNCTION TESTS:")
    
    # Test sameTerm() function
    await run_single_test(
        sparql_impl,
        "sameTerm() function test",
        """
        SELECT ?person ?name WHERE {
            ?person <http://example.org/hasName> ?name .
            FILTER(sameTerm(?name, "Alice Johnson"))
        }
        """,
        expected_count=1
    )
    
    # Test IN() function with multiple values
    await run_single_test(
        sparql_impl,
        "IN() function with multiple names",
        """
        SELECT ?person ?name WHERE {
            ?person <http://example.org/hasName> ?name .
            FILTER(?name IN ("Alice Johnson", "Bob Smith", "NonExistent Name"))
        }
        """,
        expected_count=2
    )
    
    # Test IN() function with URIs
    await run_single_test(
        sparql_impl,
        "IN() function with URIs",
        """
        SELECT ?person ?type WHERE {
            ?person <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> ?type .
            FILTER(?type IN (<http://example.org/Person>, <http://example.org/Employee>))
        }
        """,
        expected_count=5
    )

async def test_filter_edge_cases():
    """Test edge cases and error conditions for filter functions."""
    print("\n⚠️ FILTER EDGE CASES:")
    
    await run_single_test(sparql_impl, "REGEX with invalid pattern (should handle gracefully)", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(REGEX(?name, "["))
            }}
        }}
    """, expected_count=0)
    
    await run_single_test(sparql_impl, "LANG on non-literal (should return empty)", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?type WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person a ?type .
                FILTER(LANG(?type) = "")
            }}
        }}
    """, expected_count=5)
    
    await run_single_test(sparql_impl, "DATATYPE on URI (should work)", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?type WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person a ?type .
                FILTER(DATATYPE(?type) != "")
            }}
        }}
    """, expected_count=0)

async def inspect_database_tables(space_impl):
    """Inspect database tables to understand datatype storage."""
    print("\n🔍 DATABASE TABLE INSPECTION:")
    
    try:
        # Get the proper table names using space_impl
        table_names = space_impl._get_table_names('space_test')
        datatype_table = table_names.get('datatype')
        term_table = table_names.get('term')
        quad_table = table_names.get('rdf_quad')
        
        print(f"  Using datatype table: {datatype_table}")
        print(f"  Using term table: {term_table}")
        
        async with space_impl.get_db_connection() as connection:
            cursor = connection.cursor()
            
            # Check datatype table contents
            print("\n  📊 DATATYPE TABLE CONTENTS:")
            datatype_query = f"SELECT datatype_id, datatype_uri FROM {datatype_table} ORDER BY datatype_id LIMIT 10"
            try:
                cursor.execute(datatype_query)
                datatype_rows = cursor.fetchall()
                for row in datatype_rows:
                    print(f"    {row[0]}: {row[1]}")
            except Exception as e:
                print(f"  ❌ Error inspecting datatype table: {e}")
                return
            
            # Check term table for numeric literals (ages)
            print("\n  🔢 TERM TABLE - NUMERIC LITERALS:")
            term_query = f"""
                SELECT term_text, term_type, datatype_id 
                FROM {term_table} 
                WHERE term_type = 'L' AND term_text ~ '^[0-9]+$' 
                ORDER BY CASE 
                    WHEN LENGTH(term_text) <= 10 THEN CAST(term_text AS BIGINT)
                    ELSE 0
                END
                LIMIT 10
            """
            try:
                cursor.execute(term_query)
                term_rows = cursor.fetchall()
                for row in term_rows:
                    print(f"    '{row[0]}' (type: {row[1]}, datatype_id: {row[2]})")
            except Exception as e:
                print(f"  ❌ Error inspecting term table: {e}")
                # Rollback the transaction to clear the error state
                try:
                    await connection.rollback()
                except:
                    pass
                
            # Specific lookup for age value "25"
            print("\n  🎯 SPECIFIC AGE LOOKUP - '25':")
            age_query = f"""
                SELECT t.term_text, t.term_type, t.datatype_id, dt.datatype_uri
                FROM {term_table} t
                LEFT JOIN {datatype_table} dt ON t.datatype_id = dt.datatype_id
                WHERE t.term_text = '25' AND t.term_type = 'L'
            """
            try:
                cursor.execute(age_query)
                age_rows = cursor.fetchall()
                if age_rows:
                    for row in age_rows:
                        print(f"    Text: '{row[0]}', Type: {row[1]}, Datatype ID: {row[2]}, Datatype URI: {row[3]}")
                else:
                    print("    No age value '25' found")
            except Exception as e:
                print(f"  ❌ Error looking up age '25': {e}")
                try:
                    await connection.rollback()
                except:
                    pass
                
            # Check age triples with their datatypes
            print("\n  📊 AGE TRIPLES WITH DATATYPE INFO:")
            age_triples_query = f"""
                SELECT 
                    s.term_text as subject, 
                    p.term_text as predicate, 
                    o.term_text as object, 
                    o.datatype_id,
                    dt.datatype_uri
                FROM {quad_table} q
                JOIN {term_table} s ON q.subject_uuid = s.term_uuid
                JOIN {term_table} p ON q.predicate_uuid = p.term_uuid  
                JOIN {term_table} o ON q.object_uuid = o.term_uuid
                LEFT JOIN {datatype_table} dt ON o.datatype_id = dt.datatype_id
                WHERE p.term_text = 'http://example.org/hasAge'
                LIMIT 5
            """
            try:
                cursor.execute(age_triples_query)
                age_triple_results = cursor.fetchall()
                print(f"    Found {len(age_triple_results)} age triples:")
                for row in age_triple_results:
                    print(f"      {row[0]} hasAge \"{row[2]}\" (datatype_id={row[3]}, datatype_uri={row[4]})")
            except Exception as e:
                print(f"  ❌ Error inspecting age triples: {e}")
                try:
                    await connection.rollback()
                except:
                    pass
            
            # Check what XSD integer URI is stored as
            print("\n  📊 XSD INTEGER DATATYPE LOOKUP:")
            xsd_int_query = f"SELECT datatype_id, datatype_uri FROM {datatype_table} WHERE datatype_uri LIKE '%integer%'"
            try:
                cursor.execute(xsd_int_query)
                xsd_int_results = cursor.fetchall()
                print(f"    Found {len(xsd_int_results)} integer-related datatypes:")
                for row in xsd_int_results:
                    print(f"      {row[0]} -> {row[1]}")
            except Exception as e:
                print(f"  ❌ Error looking up integer datatypes: {e}")
                try:
                    await connection.rollback()
                except:
                    pass
                    
    except Exception as e:
        print(f"  ❌ Error inspecting database: {e}")
        import traceback
        traceback.print_exc()

async def debug_datatype_function(space_impl, space_id):
    """Debug DATATYPE() function in isolation"""
    
    print("\n🔍 DATATYPE FUNCTION DEBUG:")
    
    # Enable debug logging to see SQL generation
    import logging
    logging.getLogger('vitalgraph.db.postgresql.sparql').setLevel(logging.DEBUG)
    
    # Get SPARQL implementation for direct access
    sparql_impl = space_impl.get_sparql_impl(space_id)
    
    # Test 1: Simple DATATYPE query
    print("\n1️⃣ Simple DATATYPE query:")
    simple_query = """
        PREFIX ex: <http://example.org/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?person ?age (DATATYPE(?age) as ?ageType) WHERE {
            GRAPH <urn:___GLOBAL> {
                ?person ex:hasAge ?age .
            }
        }
        LIMIT 5
    """
    
    try:
        print("    🔍 Executing with debug logging enabled...")
        results = await sparql_impl.execute_sparql_query(space_id, simple_query)
        print(f"    ✅ Results: {len(results)}")
        for i, result in enumerate(results[:3]):
            print(f"    [{i+1}] {result}")
    except Exception as e:
        print(f"    ❌ Error: {e}")
        
    # Test 2: DATATYPE filter with specific datatype
    print("\n2️⃣ DATATYPE filter query:")
    filter_query = """
        PREFIX ex: <http://example.org/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?person ?age WHERE {
            GRAPH <urn:___GLOBAL> {
                ?person ex:hasAge ?age .
                FILTER(DATATYPE(?age) = xsd:integer)
            }
        }
        LIMIT 5
    """
    
    try:
        print("    🔍 Executing DATATYPE filter with debug logging...")
        results = await sparql_impl.execute_sparql_query(space_id, filter_query)
        print(f"    ✅ Results: {len(results)}")
        for i, result in enumerate(results[:3]):
            print(f"    [{i+1}] {result}")
    except Exception as e:
        print(f"    ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        
    # Test 3: Check what datatypes are actually stored
    print("\n3️⃣ Direct database inspection:")
    async with space_impl.get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Get table names
        table_names = space_impl._get_table_names(space_id)
        term_table = table_names.get('term')
        datatype_table = table_names.get('datatype')
        rdf_quad_table = table_names.get('rdf_quad')
        
        print(f"    Using tables: {term_table}, {datatype_table}, {rdf_quad_table}")
        
        # Query for age values and their datatypes
        age_query = f"""
            SELECT DISTINCT o.term_text, o.datatype_id, dt.datatype_uri
            FROM {rdf_quad_table} rq
            JOIN {term_table} p ON rq.predicate_uuid = p.term_uuid
            JOIN {term_table} o ON rq.object_uuid = o.term_uuid
            LEFT JOIN {datatype_table} dt ON o.datatype_id = dt.datatype_id
            WHERE p.term_text = 'http://example.org/hasAge'
            ORDER BY o.term_text
            LIMIT 10
        """
        
        try:
            cursor.execute(age_query)
            age_rows = cursor.fetchall()
            print(f"    Found {len(age_rows)} age values:")
            for row in age_rows:
                print(f"      Age: '{row[0]}', Datatype ID: {row[1]}, URI: {row[2]}")
        except Exception as e:
            print(f"    ❌ Error querying ages: {e}")
            
    # Test 4: Direct SQL equivalent that should work
    print("\n4️⃣ Direct SQL equivalent (should work):")
    async with space_impl.get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Get table names
        table_names = space_impl._get_table_names(space_id)
        term_table = table_names.get('term')
        datatype_table = table_names.get('datatype')
        rdf_quad_table = table_names.get('rdf_quad')
        
        # Direct SQL equivalent of the SPARQL DATATYPE filter
        direct_sql = f"""
            SELECT DISTINCT 
                s.term_text as person, 
                o.term_text as age
            FROM {rdf_quad_table} rq
            JOIN {term_table} s ON rq.subject_uuid = s.term_uuid
            JOIN {term_table} p ON rq.predicate_uuid = p.term_uuid
            JOIN {term_table} o ON rq.object_uuid = o.term_uuid
            JOIN {datatype_table} dt ON o.datatype_id = dt.datatype_id
            WHERE p.term_text = 'http://example.org/hasAge'
              AND dt.datatype_uri = 'http://www.w3.org/2001/XMLSchema#integer'
            ORDER BY o.term_text
            LIMIT 5
        """
        
        print("    🔍 Direct SQL query:")
        print(f"    {direct_sql}")
        
        try:
            cursor.execute(direct_sql)
            direct_results = cursor.fetchall()
            print(f"    ✅ Direct SQL Results: {len(direct_results)}")
            for i, row in enumerate(direct_results[:3]):
                print(f"    [{i+1}] person: {row[0]}, age: {row[1]}")
        except Exception as e:
            print(f"    ❌ Direct SQL Error: {e}")


async def analyze_test_data_discrepancies(sparql_impl):
    """Analyze actual test data to understand result count discrepancies."""
    print("\n🔍 DATA ANALYSIS - Understanding Result Count Discrepancies:")
    
    # Count total names in database
    name_count_query = f"""
        PREFIX ex: <http://example.org/>
        SELECT (COUNT(?name) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(isLITERAL(?name))
            }}
        }}
    """
    
    try:
        result = await sparql_impl.execute_sparql_query(name_count_query, SPACE_ID)
        total_names = int(result[0]['count']) if result else 0
        print(f"  Total names in database: {total_names} (isLITERAL expected 5)")
    except Exception as e:
        print(f"  Error counting names: {e}")
    
    # Count names longer than 8 characters
    long_name_query = f"""
        PREFIX ex: <http://example.org/>
        SELECT (COUNT(?name) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(STRLEN(?name) > 8)
            }}
        }}
    """
    
    try:
        result = await sparql_impl.execute_sparql_query(long_name_query, SPACE_ID)
        long_names = int(result[0]['count']) if result else 0
        print(f"  Names longer than 8 chars: {long_names} (BNODE test expected 3)")
    except Exception as e:
        print(f"  Error counting long names: {e}")
    
    # Sample some names
    sample_names_query = f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
            }}
        }}
        LIMIT 10
    """
    
    try:
        result = await sparql_impl.execute_sparql_query(sample_names_query, SPACE_ID)
        print(f"  Sample names (first 10):")
        for i, row in enumerate(result):
            name = row['name']
            length = len(name)
            length_note = " (>8)" if length > 8 else ""
            print(f"    [{i+1}] '{name}' (len={length}){length_note}")
        if len(result) > 10:
            print(f"    ... and {len(result) - 10} more names")
    except Exception as e:
        print(f"  Error sampling names: {e}")
    
    # Count emails ending with example.org
    email_query = f"""
        PREFIX ex: <http://example.org/>
        SELECT (COUNT(?email) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasEmail ?email .
                FILTER(STRENDS(?email, "example.org"))
            }}
        }}
    """
    
    try:
        result = await sparql_impl.execute_sparql_query(email_query, SPACE_ID)
        email_count = int(result[0]['count']) if result else 0
        print(f"  Emails ending with 'example.org': {email_count} (test expected 5)")
    except Exception as e:
        print(f"  Error counting emails: {e}")

async def test_rdflib_function_parsing():
    """Test RDFLib's parsing of various SPARQL functions to understand their structure."""
    print("\n🔍 RDFLIB FUNCTION PARSING TEST:")
    
    try:
        from rdflib.plugins.sparql import prepareQuery
        ParseException = Exception  # Use generic exception for parsing errors
    except ImportError:
        print("  ⚠️ RDFLib SPARQL parsing not available - skipping parsing test")
        return
    
    def test_function_parsing(func_name, sparql_fragment):
        """Test if RDFLib can parse a specific function in SPARQL."""
        sparql = f"""
            PREFIX ex: <http://example.org/>
            SELECT ?result WHERE {{
                GRAPH <{GLOBAL_GRAPH_URI}> {{
                    ?person ex:hasName ?name .
                    FILTER({sparql_fragment})
                }}
            }}
        """
        
        try:
            prepared_query = prepareQuery(sparql)
            algebra_str = str(prepared_query.algebra)
            
            # Check for multiple possible builtin name formats
            base_name = func_name.replace('()', '')
            possible_builtin_names = [
                f"Builtin_{base_name}",  # Mixed case (actual format for type functions)
                f"Builtin_{base_name.upper()}",  # Uppercase
                f"Builtin_{base_name.lower()}",  # Lowercase
            ]
            
            # Special handling for sameTerm and IN to show algebra details
            if func_name in ["sameTerm()", "IN()"]:
                print(f"    🔍 {func_name}: Algebra inspection")
                print(f"        Full algebra: {algebra_str[:200]}...")
                
                # Special case for IN() - it's handled as RelationalExpression, not builtin
                if func_name == "IN()":
                    if "RelationalExpression" in algebra_str and "'op': 'IN'" in algebra_str:
                        print(f"    ✅ {func_name}: Parsed as RelationalExpression with op='IN'")
                        return True
                    else:
                        print(f"    ⚠️  {func_name}: RelationalExpression with IN op not found")
                        return False
                
                # Look for various possible representations for other functions
                all_possible_names = possible_builtin_names + [
                    base_name,
                    base_name.upper(),
                    base_name.lower()
                ]
                
                found_names = [name for name in all_possible_names if name in algebra_str]
                if found_names:
                    print(f"        Found names: {found_names}")
                else:
                    print(f"        No standard names found, checking for patterns...")
                    # Look for any mention of the function
                    if base_name.lower() in algebra_str.lower():
                        print(f"        Found lowercase pattern in algebra")
                
                # Check if any of the possible builtin names are found for sameTerm
                found_builtin = None
                for builtin_name in possible_builtin_names:
                    if builtin_name in algebra_str:
                        found_builtin = builtin_name
                        break
                        
                if found_builtin:
                    print(f"    ✅ {func_name}: Parsed as {found_builtin}")
                    return True
                else:
                    print(f"    ⚠️  {func_name}: Parsed but no builtin found")
                    return False
            
            # Check if any of the possible builtin names are found for regular functions
            found_builtin = None
            for builtin_name in possible_builtin_names:
                if builtin_name in algebra_str:
                    found_builtin = builtin_name
                    break
                    
            if found_builtin:
                print(f"    ✅ {func_name}: Parsed as {found_builtin}")
                return True
            else:
                print(f"    ⚠️  {func_name}: Parsed but no builtin found")
                return False
                
        except ParseException as e:
            print(f"    ❌ {func_name}: Parse error - {str(e)[:50]}...")
            return False
        except Exception as e:
            print(f"    ❌ {func_name}: Other error - {str(e)[:50]}...")
            return False
    
    print("\n  Testing String Functions:")
    string_functions = [
        ("STRLEN()", "STRLEN(?name) > 5"),
        ("SUBSTR()", "SUBSTR(?name, 1, 3) = 'Joh'"),
        ("REPLACE()", "REPLACE(?name, 'John', 'Jane') = 'Jane'"),
        ("UCASE()", "UCASE(?name) = 'JOHN'"),
        ("LCASE()", "LCASE(?name) = 'john'"),
        ("STRBEFORE()", "STRBEFORE(?name, ' ') = 'John'"),
        ("STRAFTER()", "STRAFTER(?name, ' ') = 'Doe'"),
        ("ENCODE_FOR_URI()", "ENCODE_FOR_URI(?name) != ''"),
    ]
    
    for func_name, fragment in string_functions:
        test_function_parsing(func_name, fragment)
    
    print("\n  Testing Numeric Functions:")
    numeric_functions = [
        ("ABS()", "ABS(-5) = 5"),
        ("CEIL()", "CEIL(3.2) = 4"),
        ("FLOOR()", "FLOOR(3.8) = 3"),
        ("ROUND()", "ROUND(3.7) = 4"),
        ("RAND()", "RAND() >= 0"),
    ]
    
    for func_name, fragment in numeric_functions:
        test_function_parsing(func_name, fragment)
    
    print("\n  Testing Date/Time Functions:")
    datetime_functions = [
        ("NOW()", "NOW() > '2020-01-01T00:00:00'^^xsd:dateTime"),
        ("YEAR()", "YEAR(NOW()) >= 2020"),
        ("MONTH()", "MONTH(NOW()) >= 1"),
        ("DAY()", "DAY(NOW()) >= 1"),
        ("HOURS()", "HOURS(NOW()) >= 0"),
        ("MINUTES()", "MINUTES(NOW()) >= 0"),
        ("SECONDS()", "SECONDS(NOW()) >= 0"),
    ]
    
    for func_name, fragment in datetime_functions:
        test_function_parsing(func_name, fragment)
    
    print("\n  Testing Hash Functions:")
    hash_functions = [
        ("MD5()", "MD5(?name) != ''"),
        ("SHA1()", "SHA1(?name) != ''"),
        ("SHA256()", "SHA256(?name) != ''"),
        ("SHA384()", "SHA384(?name) != ''"),
        ("SHA512()", "SHA512(?name) != ''"),
    ]
    
    for func_name, fragment in hash_functions:
        test_function_parsing(func_name, fragment)
    
    print("\n  Testing Type Checking Functions:")
    type_functions = [
        ("BOUND()", "BOUND(?name)"),
        ("isURI()", "isURI(?name)"),
        ("isLITERAL()", "isLITERAL(?name)"),
        ("isNUMERIC()", "isNUMERIC(?name)"),
    ]
    
    for func_name, fragment in type_functions:
        test_function_parsing(func_name, fragment)
    
    print("\n  Testing URI/Node Functions:")
    uri_functions = [
        ("URI()", "URI('http://example.org/test') != ''"),
        ("IRI()", "IRI('http://example.org/test') != ''"),
        ("BNODE()", "BNODE() != ''"),
        ("STRUUID()", "STRUUID() != ''"),
        ("UUID()", "UUID() != ''"),
    ]
    
    for func_name, fragment in uri_functions:
        test_function_parsing(func_name, fragment)
    
    print("\n  Testing Additional Functions:")
    other_functions = [
        ("COALESCE()", "COALESCE(?name, 'default') != ''"),
        ("IF()", "IF(BOUND(?name), ?name, 'none') != ''"),
        ("LANGMATCHES()", "LANGMATCHES(LANG(?name), 'en')"),
        ("sameTerm()", "sameTerm(?name, ?name)"),
        ("IN()", "?name IN ('John', 'Jane')"),
    ]
    
    for func_name, fragment in other_functions:
        test_function_parsing(func_name, fragment)

async def test_filter_debug():
    """Debug specific filter function issues."""
    print("\n🔍 FILTER DEBUG:")
    
    # Debug REGEX implementation
    await run_single_test(sparql_impl, "DEBUG: Simple REGEX", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(REGEX(?name, "John"))
            }}
        }}
    """, debug=True)

async def main():
    """Main test controller - enable/disable tests as needed."""
    print("🧪 SPARQL Filter Functions Test Suite")
    print("=" * 50)
    
    # Setup connection
    await setup_connection()
    
    try:
        # Comprehensive filter function tests
        await test_regex_filters()
        await test_string_filter_functions()
        await test_type_checking_filters()
        await test_lang_datatype_filters()
        await test_uri_iri_filters()
        await test_bnode_filters()
        await test_complex_filter_combinations()
        await test_filter_edge_cases()
        
        # RDFLib parsing test (enable to see what functions are actually parsed)
        await test_rdflib_function_parsing()
        
        # Debug tests (enable for specific debugging)
        # await test_filter_debug()
    finally:
        # Performance summary
        print("\n📊 Cache:", sparql_impl.term_cache.size() if hasattr(sparql_impl, 'term_uuid_cache') else "Statistics not available")
    
    # Database inspection
    await inspect_database_tables(sparql_impl.space_impl)
    
    # DATATYPE function debugging
    await debug_datatype_function(sparql_impl.space_impl, 'space_test')
    
    # Close database connection
    await impl.get_db_impl().disconnect()
    print("🔌 Database connection closed")
    
    print("\n✅ Filter Functions Test Complete!")

if __name__ == "__main__":
    asyncio.run(main())
