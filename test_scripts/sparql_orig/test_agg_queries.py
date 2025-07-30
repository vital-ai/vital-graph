#!/usr/bin/env python3
"""
Aggregate Functions Test Script
===============================

Focused testing of SPARQL aggregate functions (COUNT, SUM, AVG, MIN, MAX)
with GROUP BY and HAVING clauses using test data.
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
        
        # Show all results for aggregate queries (usually small result sets)
        for i, result in enumerate(results):
            print(f"    [{i+1}] {dict(result)}")
            
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

async def debug_aggregate_algebra():
    """Debug aggregate query algebra structure."""
    print("🔍 Debug Aggregate Algebra")
    print("=" * 50)
    
    from rdflib.plugins.sparql import prepareQuery
    
    # Simple COUNT query
    sparql = f'''
        PREFIX ex: <http://example.org/>
        SELECT (COUNT(?person) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person a ex:Person .
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
    
    # GROUP BY query
    sparql_group = f'''
        PREFIX ex: <http://example.org/>
        SELECT ?dept (COUNT(?person) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person a ex:Person ;
                        ex:department ?dept .
            }}
        }}
        GROUP BY ?dept
    '''
    
    print("GROUP BY Query:")
    print(sparql_group)
    print()
    
    prepared_group = prepareQuery(sparql_group)
    print("GROUP BY Algebra structure:")
    print(prepared_group.algebra)
    print()
    print("GROUP BY Projection variables:")
    print(prepared_group.algebra.get('PV', []))
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

async def test_basic_count():
    """Test basic COUNT aggregate functions."""
    print("\n🔢 BASIC COUNT FUNCTIONS:")
    
    await run_query(sparql_impl, "Count all people", f"""
        PREFIX ex: <http://example.org/>
        SELECT (COUNT(?person) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person a ex:Person .
            }}
        }}
    """)
    
    await run_query(sparql_impl, "Count all products", f"""
        PREFIX ex: <http://example.org/>
        SELECT (COUNT(?product) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?product a ex:Product .
            }}
        }}
    """)
    
    await run_query(sparql_impl, "Count all entities (DISTINCT)", f"""
        PREFIX ex: <http://example.org/>
        SELECT (COUNT(DISTINCT ?entity) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?entity a ?type .
            }}
        }}
    """)

async def test_numeric_aggregates():
    """Test numeric aggregate functions (SUM, AVG, MIN, MAX)."""
    print("\n📊 NUMERIC AGGREGATE FUNCTIONS:")
    
    await run_query(sparql_impl, "Sum of all ages", f"""
        PREFIX ex: <http://example.org/>
        SELECT (SUM(?age) AS ?totalAge) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
            }}
        }}
    """)
    
    await run_query(sparql_impl, "Average age", f"""
        PREFIX ex: <http://example.org/>
        SELECT (AVG(?age) AS ?avgAge) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
            }}
        }}
    """)
    
    await run_query(sparql_impl, "Min and Max age", f"""
        PREFIX ex: <http://example.org/>
        SELECT (MIN(?age) AS ?minAge) (MAX(?age) AS ?maxAge) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
            }}
        }}
    """)

async def test_string_aggregates():
    """Test string aggregate functions."""
    print("\n📝 STRING AGGREGATE FUNCTIONS:")
    
    await run_query(sparql_impl, "Min and Max names (alphabetical)", f"""
        PREFIX ex: <http://example.org/>
        SELECT (MIN(?name) AS ?minName) (MAX(?name) AS ?maxName) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
            }}
        }}
    """)
    
    await run_query(sparql_impl, "Count of different departments", f"""
        PREFIX ex: <http://example.org/>
        SELECT (COUNT(DISTINCT ?dept) AS ?deptCount) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?employee ex:hasDepartment ?dept .
            }}
        }}
    """)

async def test_group_by():
    """Test GROUP BY queries."""
    print("\n👥 GROUP BY QUERIES:")
    
    await run_query(sparql_impl, "Count people by department", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?dept (COUNT(?employee) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?employee ex:hasDepartment ?dept .
            }}
        }}
        GROUP BY ?dept
    """)
    
    await run_query(sparql_impl, "Count entities by type", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?type (COUNT(?entity) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?entity a ?type .
            }}
        }}
        GROUP BY ?type
    """)
    
    await run_query(sparql_impl, "Average age by department", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?dept (AVG(?age) AS ?avgAge) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasDepartment ?dept .
                ?person ex:hasAge ?age .
            }}
        }}
        GROUP BY ?dept
    """)
    
    await run_query(sparql_impl, "Product statistics by color", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?color (COUNT(?product) AS ?count) (AVG(?price) AS ?avgPrice) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?product ex:hasColor ?color .
                ?product ex:hasPrice ?price .
            }}
        }}
        GROUP BY ?color
    """)

async def test_having_clauses():
    """Test HAVING clauses with aggregates."""
    print("\n🔍 HAVING CLAUSES:")
    
    await run_query(sparql_impl, "Departments with more than 1 employee", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?dept (COUNT(?employee) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?employee ex:hasDepartment ?dept .
            }}
        }}
        GROUP BY ?dept
        HAVING (COUNT(?employee) > 1)
    """)
    
    await run_query(sparql_impl, "Types with average age over 30", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?type (AVG(?age) AS ?avgAge) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?entity a ?type .
                ?entity ex:hasAge ?age .
            }}
        }}
        GROUP BY ?type
        HAVING (AVG(?age) > 30)
    """)

async def test_complex_aggregates():
    """Test complex aggregate queries with OPTIONAL and BIND."""
    print("\n🧩 COMPLEX AGGREGATE QUERIES:")
    
    await run_query(sparql_impl, "Department statistics with OPTIONAL data", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?dept (COUNT(?employee) AS ?empCount) (COUNT(?manager) AS ?mgrCount) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?employee ex:hasDepartment ?dept .
                OPTIONAL {{ ?employee ex:hasManager ?manager }}
            }}
        }}
        GROUP BY ?dept
    """)
    
    await run_query(sparql_impl, "Product price ranges by category", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?category (COUNT(?product) AS ?count) (MIN(?price) AS ?minPrice) (MAX(?price) AS ?maxPrice) (AVG(?price) AS ?avgPrice) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?product a ex:Product .
                ?product ex:hasPrice ?price .
                OPTIONAL {{ ?product ex:hasCategory ?category }}
            }}
        }}
        GROUP BY ?category
    """)
    
    await run_query(sparql_impl, "Multi-level aggregation with BIND", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?ageGroup (COUNT(?person) AS ?count) (AVG(?age) AS ?avgAge) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
                BIND(IF(?age < 30, "Young", "Older") AS ?ageGroup)
            }}
        }}
        GROUP BY ?ageGroup
    """)

async def test_order_by_aggregates():
    """Test aggregates with ORDER BY and LIMIT."""
    print("\n📈 AGGREGATE WITH ORDER BY:")
    
    await run_query(sparql_impl, "Departments ordered by employee count", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?dept (COUNT(?employee) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?employee ex:hasDepartment ?dept .
            }}
        }}
        GROUP BY ?dept
        ORDER BY DESC(?count)
    """)
    
    await run_query(sparql_impl, "Top 3 most expensive products", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?product ?price WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?product ex:hasPrice ?price .
            }}
        }}
        ORDER BY DESC(?price)
        LIMIT 3
    """)

async def test_having_debug():
    """Debug HAVING clause to understand algebra structure."""
    print("\n🔍 DEBUG HAVING CLAUSE:")
    
    # Simple HAVING query
    sparql_query = f"""
        PREFIX ex: <http://example.org/>
        SELECT ?dept (COUNT(?employee) AS ?count) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?employee ex:hasDepartment ?dept .
            }}
        }}
        GROUP BY ?dept
        HAVING (COUNT(?employee) > 0)
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
    await run_query(sparql_impl, "HAVING debug", sparql_query)

async def test_simple_sum_debug():
    """Debug a simple SUM query to understand variable mapping issues."""
    print("\n🔍 DEBUG SIMPLE SUM QUERY:")
    
    # Simple SUM query that should work
    sparql_query = f"""
        PREFIX ex: <http://example.org/>
        SELECT (SUM(?age) AS ?totalAge) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
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
    await run_query(sparql_impl, "Simple SUM debug", sparql_query)

async def test_nested_aggregates():
    """Test nested aggregate queries."""
    print("\n🔗 NESTED AGGREGATES:")
    
    await run_query(sparql_impl, "Count of departments with employees", f"""
        PREFIX ex: <http://example.org/>
        SELECT (COUNT(DISTINCT ?dept) AS ?deptWithEmployees) WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?employee ex:hasDepartment ?dept .
            }}
        }}
    """)

async def main():
    """Main test controller - enable/disable tests as needed."""
    print("🧪 SPARQL Aggregate Functions Test Suite")
    print("=" * 50)
    
    # Setup connection
    await setup_connection()
    
    try:
        # Comprehensive test suite - now with HAVING clause support!
        await test_basic_count()
        await test_numeric_aggregates()
        await test_string_aggregates()
        await test_group_by()
        await test_having_clauses()
        await test_complex_aggregates()
        await test_order_by_aggregates()
        await test_nested_aggregates()
        
        # Debug tests (disable for comprehensive run)
        # await test_having_debug()  # Debug HAVING clause
        # await test_simple_sum_debug()  # Debug single SUM query
        
    finally:
        # Performance summary
        print(f"\n📊 Cache: {sparql_impl.term_uuid_cache.size()} terms")
        
        # Cleanup
        await cleanup_connection()
        print("\n✅ Aggregate Functions Test Complete!")

if __name__ == "__main__":
    asyncio.run(main())
