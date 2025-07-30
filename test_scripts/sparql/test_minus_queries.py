#!/usr/bin/env python3
"""
MINUS Pattern Test Script
=========================

Comprehensive testing of SPARQL MINUS patterns for excluding matching patterns
from query results using test data.

MINUS patterns work by excluding results from the left pattern that match 
variables in the right pattern.

Example: { ?s ?p ?o } MINUS { ?s ex:excludeProperty ?value }
This returns all triples EXCEPT those where the subject has ex:excludeProperty.
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
        
        # Show results (limit to first 10 for readability)
        for i, result in enumerate(results[:10]):
            print(f"    [{i+1}] {dict(result)}")
        
        if len(results) > 10:
            print(f"    ... and {len(results) - 10} more results")
            
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

async def debug_minus_algebra():
    """Debug MINUS query algebra structure."""
    print("🔍 Debug MINUS Algebra")
    print("=" * 50)
    
    from rdflib.plugins.sparql import prepareQuery
    
    # Simple MINUS query
    sparql = f'''
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
            }}
            MINUS {{
                ?person ex:isExcluded "true" .
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

# Global variables for database connection
impl = None
sparql_impl = None

async def setup_connection():
    """Initialize database connection for tests."""
    global impl, sparql_impl
    
    # Initialize VitalGraphImpl with config file
    project_root = Path(__file__).parent.parent.parent
    config_path = project_root / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    space_impl = impl.db_impl.get_space_impl()
    sparql_impl = PostgreSQLSparqlImpl(space_impl)

async def cleanup_connection():
    """Clean up database connection."""
    global impl
    if impl:
        if impl.db_impl:
            await impl.db_impl.disconnect()

async def test_basic_minus():
    """Test basic MINUS patterns."""
    print("\n🚫 BASIC MINUS PATTERNS:")
    
    await run_query(sparql_impl, "All people MINUS those excluded", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
            }}
            MINUS {{
                ?person ex:isExcluded "true" .
            }}
        }}
    """)
    
    await run_query(sparql_impl, "All products MINUS those discontinued", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?product ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?product a ex:Product ;
                        ex:hasName ?name .
            }}
            MINUS {{
                ?product ex:isDiscontinued "true" .
            }}
        }}
    """)

async def test_minus_with_multiple_variables():
    """Test MINUS patterns with multiple shared variables."""
    print("\n🔗 MINUS WITH MULTIPLE VARIABLES:")
    
    await run_query(sparql_impl, "People with ages MINUS those in specific departments", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
            }}
            MINUS {{
                ?person ex:hasDepartment "HR" .
            }}
        }}
    """)
    
    await run_query(sparql_impl, "Products with prices MINUS those in specific categories", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?product ?price WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?product ex:hasPrice ?price .
            }}
            MINUS {{
                ?product ex:hasCategory "discontinued" .
            }}
        }}
    """)

async def test_minus_with_filters():
    """Test MINUS patterns combined with FILTER conditions."""
    print("\n🔍 MINUS WITH FILTERS:")
    
    await run_query(sparql_impl, "Young people MINUS those excluded", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
                FILTER(?age < 30)
            }}
            MINUS {{
                ?person ex:isExcluded "true" .
            }}
        }}
    """)
    
    await run_query(sparql_impl, "Expensive products MINUS those discontinued", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?product ?price WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?product ex:hasPrice ?price .
                FILTER(?price > 100)
            }}
            MINUS {{
                ?product ex:isDiscontinued "true" .
            }}
        }}
    """)

async def test_minus_with_optional():
    """Test MINUS patterns combined with OPTIONAL."""
    print("\n❓ MINUS WITH OPTIONAL:")
    
    await run_query(sparql_impl, "People with optional emails MINUS those excluded", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name ?email WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasEmail ?email }}
            }}
            MINUS {{
                ?person ex:isExcluded "true" .
            }}
        }}
    """)

async def test_complex_minus_patterns():
    """Test complex MINUS patterns with multiple conditions."""
    print("\n🧩 COMPLEX MINUS PATTERNS:")
    
    await run_query(sparql_impl, "People MINUS those with specific age and department", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name ;
                        ex:hasAge ?someAge .
            }}
            MINUS {{
                ?person ex:hasAge ?age ;
                        ex:hasDepartment ?dept .
                FILTER(?age > 30 && ?dept = "IT")
            }}
        }}
    """)
    
    await run_query(sparql_impl, "Products MINUS those with high price and specific category", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?product ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?product ex:hasName ?name ;
                        ex:hasPrice ?somePrice .
            }}
            MINUS {{
                ?product ex:hasPrice ?price ;
                        ex:hasCategory ?category .
                FILTER(?price > 50 && ?category = "electronics")
            }}
        }}
    """)

async def test_nested_minus():
    """Test nested MINUS patterns."""
    print("\n🪆 NESTED MINUS PATTERNS:")
    
    await run_query(sparql_impl, "Complex nested MINUS", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                MINUS {{
                    ?person ex:hasDepartment "HR" .
                    MINUS {{
                        ?person ex:hasRole "manager" .
                    }}
                }}
            }}
        }}
    """)

async def test_minus_edge_cases():
    """Test MINUS edge cases and boundary conditions."""
    print("\n🎯 MINUS EDGE CASES:")
    
    await run_query(sparql_impl, "MINUS with no shared variables", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name ;
                        ex:hasAge ?age .
            }}
            MINUS {{
                ?other ex:isGlobal "true" .
            }}
        }}
    """)
    
    await run_query(sparql_impl, "MINUS with empty pattern", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name ;
                        ex:hasAge ?age .
            }}
            MINUS {{
                ?person ex:nonExistentProperty ?value .
            }}
        }}
    """)

async def test_minus_debug():
    """Debug MINUS implementation with comprehensive diagnostics."""
    print("\n🔍 DEBUG MINUS IMPLEMENTATION:")
    
    # Test 1: Simple MINUS query
    print("\n📋 Test 1: Simple MINUS (should work)")
    sparql_query = f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
            }}
            MINUS {{
                ?person ex:isExcluded "true" .
            }}
        }}
    """
    await run_query(sparql_impl, "Simple MINUS debug", sparql_query, debug=True)
    
    # Test 2: MINUS with FILTER (problematic case)
    print("\n📋 Test 2: MINUS with FILTER (problematic case)")
    sparql_query_filter = f"""
        PREFIX ex: <http://example.org/>
        SELECT ?person ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
            }}
            MINUS {{
                ?person ex:hasAge ?age .
                FILTER(?age > 30)
            }}
        }}
    """
    await run_query(sparql_impl, "MINUS with FILTER debug", sparql_query_filter, debug=True)
    
    # Test 3: Check variable mappings in exclude pattern
    print("\n📋 Test 3: Complex MINUS with multiple variables")
    sparql_query_complex = f"""
        PREFIX ex: <http://example.org/>
        SELECT ?product ?name WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?product ex:hasName ?name .
            }}
            MINUS {{
                ?product ex:hasPrice ?price ;
                        ex:hasCategory ?category .
                FILTER(?price > 50 && ?category = "electronics")
            }}
        }}
    """
    await run_query(sparql_impl, "Complex MINUS debug", sparql_query_complex, debug=True)
    
    # Test 4: Algebra structure analysis
    print("\n📋 Test 4: Algebra structure analysis")
    from rdflib.plugins.sparql import prepareQuery
    
    print("\n🔬 Analyzing SPARQL algebra for MINUS with FILTER:")
    prepared_query = prepareQuery(sparql_query_filter)
    print(f"Query algebra: {prepared_query.algebra}")
    
    # Check if MINUS pattern has proper structure
    if hasattr(prepared_query.algebra, 'p') and hasattr(prepared_query.algebra.p, 'name'):
        pattern = prepared_query.algebra.p
        print(f"Main pattern type: {pattern.name}")
        if pattern.name == 'Minus':
            print(f"MINUS p1 (main): {getattr(pattern.p1, 'name', type(pattern.p1).__name__)}")
            print(f"MINUS p2 (exclude): {getattr(pattern.p2, 'name', type(pattern.p2).__name__)}")
            
            # Check if exclude pattern has FILTER
            if hasattr(pattern.p2, 'name') and pattern.p2.name == 'Filter':
                print(f"Exclude pattern is FILTER with inner pattern: {getattr(pattern.p2.p, 'name', 'unknown')}")
                print(f"Filter expression: {pattern.p2.expr}")

async def diagnose_variable_mapping_issue():
    """Diagnose the specific UNMAPPED variable issue in MINUS patterns."""
    print("\n🔍 DIAGNOSING VARIABLE MAPPING ISSUE:")
    print("=" * 60)
    
    # Enable detailed logging for this diagnosis
    import logging
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
        print("\n📋 Testing simple MINUS without FILTER (should work):")
        simple_query = f"""
            PREFIX ex: <http://example.org/>
            SELECT ?person ?name WHERE {{
                GRAPH <{GLOBAL_GRAPH_URI}> {{
                    ?person ex:hasName ?name .
                }}
                MINUS {{
                    ?person ex:isExcluded "true" .
                }}
            }}
        """
        
        try:
            results = await sparql_impl.execute_sparql_query(SPACE_ID, simple_query)
            print(f"✅ Simple MINUS works: {len(results)} results")
        except Exception as e:
            print(f"❌ Simple MINUS failed: {e}")
        
        print("\n📋 Testing MINUS with FILTER (problematic case):")
        filter_query = f"""
            PREFIX ex: <http://example.org/>
            SELECT ?person ?name WHERE {{
                GRAPH <{GLOBAL_GRAPH_URI}> {{
                    ?person ex:hasName ?name .
                }}
                MINUS {{
                    ?person ex:hasAge ?age .
                    FILTER(?age > 30)
                }}
            }}
        """
        
        try:
            results = await sparql_impl.execute_sparql_query(SPACE_ID, filter_query)
            print(f"✅ MINUS with FILTER works: {len(results)} results")
        except Exception as e:
            print(f"❌ MINUS with FILTER failed: {e}")
            print(f"Error details: {type(e).__name__}: {str(e)}")
            
            # Check if it's the UNMAPPED variable issue
            if "UNMAPPED" in str(e):
                print("\n🔴 CONFIRMED: UNMAPPED variable issue detected!")
                print("This suggests that variables in the MINUS exclude pattern")
                print("are not being properly mapped to SQL columns.")
                
                print("\n🔧 POTENTIAL CAUSES:")
                print("1. projected_vars not being passed correctly to exclude pattern")
                print("2. Variable mappings from exclude pattern not being used in FILTER translation")
                print("3. FILTER expressions in MINUS patterns need special handling")
    
    finally:
        # Restore original logging level
        sparql_logger.setLevel(original_level)

async def main():
    """Main test controller - enable/disable tests as needed."""
    print("🧪 SPARQL MINUS Pattern Test Suite")
    print("=" * 50)
    
    # Setup connection
    await setup_connection()
    
    try:
        # First, diagnose the variable mapping issue
        await diagnose_variable_mapping_issue()
        
        # Debug algebra structure
        await debug_minus_algebra()
        
        # Run comprehensive test suite - all tests should now pass!
        print("\n🚀 RUNNING FULL MINUS TEST SUITE (all tests enabled)")
        
        await test_basic_minus()
        await test_minus_with_multiple_variables()
        await test_minus_with_filters()  # Now fixed!
        await test_minus_with_optional()
        await test_complex_minus_patterns()  # Now fixed!
        await test_nested_minus()
        await test_minus_edge_cases()
        
        # Optional debug test for detailed analysis
        # await test_minus_debug()
        
    finally:
        # Performance summary
        print(f"\n📊 Cache: {sparql_impl.term_cache.size()} terms")
        
        # Cleanup
        await cleanup_connection()
        print("\n✅ MINUS Pattern Test Complete!")

if __name__ == "__main__":
    asyncio.run(main())
