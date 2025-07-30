#!/usr/bin/env python3
"""
ASK and DESCRIBE Queries Test Script
====================================

Testing SPARQL ASK (boolean existence check) and DESCRIBE (resource description)
query support using test data.

ASK queries return boolean results indicating whether a pattern exists.
DESCRIBE queries return all properties (triples) of specified resources.
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
        
        # Show results with appropriate formatting
        for i, result in enumerate(results):
            if isinstance(result, dict):
                # For ASK queries, show boolean result clearly
                if 'ask' in result:
                    print(f"    [{i+1}] ASK result: {result['ask']}")
                else:
                    print(f"    [{i+1}] {dict(result)}")
            else:
                print(f"    [{i+1}] {result}")
            
        if debug:
            print("\n" + "=" * 60)
            
    except Exception as e:
        print(f"    ❌ Error: {e}")
        if debug:
            import traceback
            traceback.print_exc()
    
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
    
    # Load config and initialize
    project_root = Path(__file__).parent.parent.parent
    config_path = project_root / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    db_impl = impl.get_db_impl()
    await db_impl.connect()
    
    space_impl = db_impl.get_space_impl()
    sparql_impl = PostgreSQLSparqlImpl(space_impl)

async def cleanup_connection():
    """Clean up database connection."""
    global impl
    if impl:
        db_impl = impl.get_db_impl()
        if db_impl:
            await db_impl.disconnect()

async def test_basic_ask_queries():
    """Test basic ASK queries for existence checking."""
    print("\n❓ BASIC ASK QUERIES:")
    
    # Test 1: ASK if any persons exist (should be true)
    await run_query(sparql_impl, "ASK if any persons exist", f"""
        PREFIX ex: <http://example.org/>
        ASK {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person a ex:Person .
            }}
        }}
    """)
    
    # Test 2: ASK if any products exist (should be true)
    await run_query(sparql_impl, "ASK if any products exist", f"""
        PREFIX ex: <http://example.org/>
        ASK {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?product a ex:Product .
            }}
        }}
    """)
    
    # Test 3: ASK for non-existent pattern (should be false)
    await run_query(sparql_impl, "ASK for non-existent Dragons", f"""
        PREFIX ex: <http://example.org/>
        ASK {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?dragon a ex:Dragon .
            }}
        }}
    """)
    
    # Test 4: ASK with specific property (should be true)
    await run_query(sparql_impl, "ASK if anyone has an age", f"""
        PREFIX ex: <http://example.org/>
        ASK {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
            }}
        }}
    """)
    
    # Test 5: ASK with specific value (should be true)
    await run_query(sparql_impl, "ASK if Alice exists", f"""
        PREFIX ex: <http://example.org/>
        ASK {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName "Alice" .
            }}
        }}
    """)

async def test_complex_ask_queries():
    """Test complex ASK queries with filters and multiple patterns."""
    print("\n🔍 COMPLEX ASK QUERIES:")
    
    # Test 1: ASK with filter condition
    await run_query(sparql_impl, "ASK if anyone is over 30", f"""
        PREFIX ex: <http://example.org/>
        ASK {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
                FILTER(?age > 30)
            }}
        }}
    """)
    
    # Test 2: ASK with multiple patterns
    await run_query(sparql_impl, "ASK if anyone has both name and age", f"""
        PREFIX ex: <http://example.org/>
        ASK {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name ;
                        ex:hasAge ?age .
            }}
        }}
    """)
    
    # Test 3: ASK with OPTIONAL pattern
    await run_query(sparql_impl, "ASK if anyone has name and optional email", f"""
        PREFIX ex: <http://example.org/>
        ASK {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasEmail ?email }}
            }}
        }}
    """)
    
    # Test 4: ASK with string function
    await run_query(sparql_impl, "ASK if any name contains 'Alice'", f"""
        PREFIX ex: <http://example.org/>
        ASK {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(CONTAINS(?name, "Alice"))
            }}
        }}
    """)

async def test_basic_describe_queries():
    """Test basic DESCRIBE queries for resource description."""
    print("\n📋 BASIC DESCRIBE QUERIES:")
    
    # Test 1: DESCRIBE a specific person
    await run_query(sparql_impl, "DESCRIBE Alice", f"""
        PREFIX ex: <http://example.org/>
        DESCRIBE ex:person1
    """)
    
    # Test 2: DESCRIBE a specific product
    await run_query(sparql_impl, "DESCRIBE a product", f"""
        PREFIX ex: <http://example.org/>
        DESCRIBE ex:product1
    """)
    
    # Test 3: DESCRIBE with variable (first person found)
    await run_query(sparql_impl, "DESCRIBE first person found", f"""
        PREFIX ex: <http://example.org/>
        DESCRIBE ?person WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person a ex:Person .
            }}
        }}
        LIMIT 1
    """)
    
    # Test 4: DESCRIBE multiple resources
    await run_query(sparql_impl, "DESCRIBE multiple persons", f"""
        PREFIX ex: <http://example.org/>
        DESCRIBE ?person WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person a ex:Person .
            }}
        }}
        LIMIT 3
    """)

async def test_complex_describe_queries():
    """Test complex DESCRIBE queries with filters and conditions."""
    print("\n🔍 COMPLEX DESCRIBE QUERIES:")
    
    # Test 1: DESCRIBE with filter condition
    await run_query(sparql_impl, "DESCRIBE persons over 25", f"""
        PREFIX ex: <http://example.org/>
        DESCRIBE ?person WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person a ex:Person ;
                        ex:hasAge ?age .
                FILTER(?age > 25)
            }}
        }}
    """)
    
    # Test 2: DESCRIBE with string matching
    await run_query(sparql_impl, "DESCRIBE persons with 'A' in name", f"""
        PREFIX ex: <http://example.org/>
        DESCRIBE ?person WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                FILTER(CONTAINS(?name, "A"))
            }}
        }}
    """)
    
    # Test 3: DESCRIBE with ORDER BY
    await run_query(sparql_impl, "DESCRIBE persons ordered by age", f"""
        PREFIX ex: <http://example.org/>
        DESCRIBE ?person WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person a ex:Person ;
                        ex:hasAge ?age .
            }}
        }}
        ORDER BY ?age
        LIMIT 2
    """)

async def test_edge_cases():
    """Test edge cases and error conditions."""
    print("\n⚠️  EDGE CASES:")
    
    # Test 1: ASK with empty pattern (should be true if any triples exist)
    await run_query(sparql_impl, "ASK if any triples exist", f"""
        ASK {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?s ?p ?o .
            }}
        }}
    """)
    
    # Test 2: DESCRIBE non-existent resource
    await run_query(sparql_impl, "DESCRIBE non-existent resource", f"""
        PREFIX ex: <http://example.org/>
        DESCRIBE ex:nonexistent
    """)
    
    # Test 3: ASK with complex nested pattern
    await run_query(sparql_impl, "ASK with nested pattern", f"""
        PREFIX ex: <http://example.org/>
        ASK {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person a ex:Person .
                {{
                    ?person ex:hasAge ?age .
                    FILTER(?age > 20)
                }} UNION {{
                    ?person ex:hasName ?name .
                    FILTER(STRLEN(?name) > 3)
                }}
            }}
        }}
    """)

async def test_ask_debug():
    """Debug ASK query to understand algebra structure."""
    print("\n🔍 DEBUG ASK QUERY:")
    
    # Simple ASK query for debugging
    sparql_query = f"""
        PREFIX ex: <http://example.org/>
        ASK {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person a ex:Person .
            }}
        }}
    """
    
    print("SPARQL Query:")
    print(sparql_query)
    print()
    
    # Parse and examine the algebra
    from rdflib.plugins.sparql import prepareQuery
    prepared_query = prepareQuery(sparql_query)
    print("Algebra structure:")
    print(prepared_query.algebra)
    print()
    
    # Run the query and see the results
    await run_query(sparql_impl, "ASK debug", sparql_query, debug=True)

async def test_describe_debug():
    """Debug DESCRIBE query to understand algebra structure."""
    print("\n🔍 DEBUG DESCRIBE QUERY:")
    
    # Simple DESCRIBE query for debugging
    sparql_query = f"""
        PREFIX ex: <http://example.org/>
        DESCRIBE ex:person1
    """
    
    print("SPARQL Query:")
    print(sparql_query)
    print()
    
    # Parse and examine the algebra
    from rdflib.plugins.sparql import prepareQuery
    prepared_query = prepareQuery(sparql_query)
    print("Algebra structure:")
    print(prepared_query.algebra)
    print()
    
    # Run the query and see the results
    await run_query(sparql_impl, "DESCRIBE debug", sparql_query, debug=True)

async def main():
    """Main test controller - enable/disable tests as needed."""
    print("🧪 SPARQL ASK & DESCRIBE Queries Test Suite")
    print("=" * 50)
    
    # Setup connection
    await setup_connection()
    
    try:
        # Comprehensive test suite
        await test_basic_ask_queries()
        await test_complex_ask_queries()
        await test_basic_describe_queries()
        await test_complex_describe_queries()
        await test_edge_cases()
        
        # Debug tests (enable for debugging)
        # await test_ask_debug()
        # await test_describe_debug()
        
    finally:
        # Performance summary
        print(f"\n📊 Cache: {sparql_impl.term_uuid_cache.size()} terms")
        
        # Cleanup
        await cleanup_connection()
        print("\n✅ ASK & DESCRIBE Queries Test Complete!")

if __name__ == "__main__":
    asyncio.run(main())
