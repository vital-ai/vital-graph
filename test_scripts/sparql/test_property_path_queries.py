#!/usr/bin/env python3
"""
SPARQL Property Path Test Script for VitalGraph

This script tests SPARQL 1.1 property path functionality including:
- Transitive paths (+, *)
- Sequence paths (/)
- Alternative paths (|)
- Inverse paths (~)
- Negated paths (!)
- Complex combinations

The test data includes:
- Social networks with transitive 'knows' relationships
- Organizational hierarchies with 'manages' relationships
- Family relationships for inverse path testing
- Location hierarchies for nested sequence paths
- Transportation networks for alternative paths
- Academic relationships for complex combinations

Usage:
    python test_property_path_queries.py

Requirements:
    - VitalGraph server running
    - Test data loaded (run reload_test_data.py first)
"""

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import List, Dict, Any

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.db.postgresql.postgresql_sparql_impl import PostgreSQLSparqlImpl

# Configure detailed logging for SPARQL debugging
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s - %(name)s - %(message)s')

# Enable detailed logging for SPARQL translation modules
logging.getLogger('vitalgraph.db.postgresql.sparql.postgresql_sparql_property_paths').setLevel(logging.DEBUG)
logging.getLogger('vitalgraph.db.postgresql.sparql.postgresql_sparql_patterns').setLevel(logging.DEBUG)
logging.getLogger('vitalgraph.db.postgresql.sparql.postgresql_sparql_orchestrator').setLevel(logging.DEBUG)
logging.getLogger('vitalgraph.db.postgresql.sparql.postgresql_sparql_cache_integration').setLevel(logging.DEBUG)
logging.getLogger('vitalgraph.db.postgresql.sparql.postgresql_sparql_queries').setLevel(logging.DEBUG)

# Reduce logging chatter from other modules
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

# ===== TRANSITIVE PATH TESTS (+, *) =====

async def diagnose_database_predicates():
    """Check what predicates are actually in the database."""
    print("\n🔍 DATABASE DIAGNOSTICS")
    print("=" * 40)
    
    try:
        # Query for predicates containing our test terms
        result = await impl.db_impl.execute_query('''
            SELECT DISTINCT term_text 
            FROM vitalgraph1__space_test__term 
            WHERE term_text LIKE '%knows%' OR term_text LIKE '%hasName%' OR term_text LIKE '%example%'
            ORDER BY term_text
        ''')
        
        print(f"Found {len(result)} predicates with 'knows', 'hasName', or 'example':")
        for row in result:
            print(f"  📋 {row[0]}")
            
        # Check total quad count
        quad_result = await impl.db_impl.execute_query('''
            SELECT COUNT(*) FROM vitalgraph1__space_test__rdf_quad
        ''')
        print(f"\n📊 Total quads in database: {quad_result[0][0]}")
        
        # Check global graph quads
        global_result = await impl.db_impl.execute_query('''
            SELECT COUNT(*) 
            FROM vitalgraph1__space_test__rdf_quad q
            JOIN vitalgraph1__space_test__term t ON q.context_uuid = t.term_uuid
            WHERE t.term_text = 'urn:___GLOBAL'
        ''')
        print(f"📊 Quads in global graph: {global_result[0][0]}")
        
    except Exception as e:
        print(f"❌ Diagnostics failed: {e}")

async def test_transitive_plus_path(sparql_impl):
    """Test transitive plus paths (one or more): ?x knows+ ?y"""
    
    await run_query(sparql_impl, "Transitive Plus Path (knows+)", f"""
    PREFIX ex: <http://example.org/>
    
    SELECT ?person1 ?person2 ?name1 ?name2
    WHERE {{
        GRAPH <{GLOBAL_GRAPH_URI}> {{
            ?person1 ex:knows+ ?person2 .
            ?person1 ex:hasName ?name1 .
            ?person2 ex:hasName ?name2 .
        }}
    }}
    ORDER BY ?name1 ?name2
    """, debug=True)

async def test_transitive_star_path():
    """Test transitive star paths (zero or more): ?x knows* ?y"""
    
    query = """
    PREFIX ex: <http://vital.ai/example/>
    
    SELECT ?person1 ?person2 ?name1 ?name2
    WHERE {
        ?person1 ex:knows* ?person2 .
        ?person1 ex:hasName ?name1 .
        ?person2 ex:hasName ?name2 .
    }
    ORDER BY ?name1 ?name2
    """
    
    results = await execute_sparql_query(
        query, 
        "Testing transitive star path: ?person1 knows* ?person2 (zero or more knows relationships)"
    )
    
    # Expected: All transitive relationships PLUS reflexive relationships (person knows themselves)
    expected_min_results = 20  # At least 20 relationships including reflexive
    
    if len(results) >= expected_min_results:
        print(f"✅ Transitive star path test passed: found {len(results)} relationships (including reflexive)")
    else:
        print(f"❌ Transitive star path test failed: expected at least {expected_min_results} results, got {len(results)}")

async def test_management_hierarchy():
    """Test transitive management hierarchy: CEO manages+ all employees"""
    
    query = """
    PREFIX ex: <http://vital.ai/example/>
    
    SELECT ?manager ?employee ?managerName ?employeeName ?employeeTitle
    WHERE {
        ?manager ex:manages+ ?employee .
        ?manager ex:hasName ?managerName .
        ?employee ex:hasName ?employeeName .
        ?employee ex:hasTitle ?employeeTitle .
        FILTER(?manager = ex:ceo)
    }
    ORDER BY ?employeeTitle ?employeeName
    """
    
    results = await execute_sparql_query(
        query, 
        "Testing management hierarchy: CEO manages+ all employees transitively"
    )
    
    # Expected: CEO transitively manages VP, Directors, Senior Devs, Junior Devs
    expected_min_results = 5  # At least 5 employees under CEO
    
    if len(results) >= expected_min_results:
        print(f"✅ Management hierarchy test passed: CEO manages {len(results)} employees transitively")
    else:
        print(f"❌ Management hierarchy test failed: expected at least {expected_min_results} results, got {len(results)}")

# ===== SEQUENCE PATH TESTS (/) =====

async def test_sequence_path_knows_name():
    """Test sequence paths: ?x knows/hasName ?name"""
    
    query = """
    PREFIX ex: <http://vital.ai/example/>
    
    SELECT ?person ?friendName ?personName
    WHERE {
        ?person ex:knows/ex:hasName ?friendName .
        ?person ex:hasName ?personName .
    }
    ORDER BY ?personName ?friendName
    """
    
    results = await execute_sparql_query(
        query, 
        "Testing sequence path: ?person knows/hasName ?friendName (names of people they directly know)"
    )
    
    # Expected: Each person's direct friends' names
    expected_min_results = 5  # At least 5 direct know relationships
    
    if len(results) >= expected_min_results:
        print(f"✅ Sequence path (knows/hasName) test passed: found {len(results)} friend names")
    else:
        print(f"❌ Sequence path (knows/hasName) test failed: expected at least {expected_min_results} results, got {len(results)}")

async def test_sequence_path_transitive_name():
    """Test complex sequence paths: ?x knows+/hasName ?name"""
    
    query = """
    PREFIX ex: <http://vital.ai/example/>
    
    SELECT ?person ?transitiveFriendName ?personName
    WHERE {
        ?person ex:knows+/ex:hasName ?transitiveFriendName .
        ?person ex:hasName ?personName .
        FILTER(?person = ex:alice)
    }
    ORDER BY ?transitiveFriendName
    """
    
    results = await execute_sparql_query(
        query, 
        "Testing complex sequence path: Alice knows+/hasName ?name (names of all people Alice knows transitively)"
    )
    
    # Expected: Names of all people Alice knows transitively (Bob, Charlie, David, Eve)
    expected_min_results = 4  # At least 4 people Alice knows transitively
    
    if len(results) >= expected_min_results:
        print(f"✅ Complex sequence path test passed: Alice transitively knows {len(results)} people")
    else:
        print(f"❌ Complex sequence path test failed: expected at least {expected_min_results} results, got {len(results)}")

async def test_location_hierarchy_sequence():
    """Test nested sequence paths: ?building locatedIn+/hasName ?locationName"""
    
    query = """
    PREFIX ex: <http://vital.ai/example/>
    
    SELECT ?building ?locationName ?buildingName
    WHERE {
        ?building ex:locatedIn+/ex:hasName ?locationName .
        ?building ex:hasName ?buildingName .
        FILTER(?building = ex:building_123_main)
    }
    ORDER BY ?locationName
    """
    
    results = await execute_sparql_query(
        query, 
        "Testing location hierarchy: building locatedIn+/hasName ?locationName (all containing locations)"
    )
    
    # Expected: Building is located in Mission District, San Francisco, California, United States
    expected_min_results = 4  # At least 4 containing locations
    
    if len(results) >= expected_min_results:
        print(f"✅ Location hierarchy sequence test passed: building is in {len(results)} locations")
    else:
        print(f"❌ Location hierarchy sequence test failed: expected at least {expected_min_results} results, got {len(results)}")

# ===== ALTERNATIVE PATH TESTS (|) =====

async def test_alternative_paths_transport():
    """Test alternative paths: ?station (busRoute|trainRoute|subwayRoute) ?destination"""
    
    query = """
    PREFIX ex: <http://vital.ai/example/>
    
    SELECT ?station ?destination ?stationName ?destName
    WHERE {
        ?station (ex:busRoute|ex:trainRoute|ex:subwayRoute) ?destination .
        ?station ex:hasName ?stationName .
        ?destination ex:hasName ?destName .
    }
    ORDER BY ?stationName ?destName
    """
    
    results = await execute_sparql_query(
        query, 
        "Testing alternative paths: ?station (busRoute|trainRoute|subwayRoute) ?destination"
    )
    
    # Expected: All transport connections between stations
    expected_min_results = 5  # At least 5 transport connections
    
    if len(results) >= expected_min_results:
        print(f"✅ Alternative paths test passed: found {len(results)} transport connections")
    else:
        print(f"❌ Alternative paths test failed: expected at least {expected_min_results} results, got {len(results)}")

async def test_alternative_paths_management():
    """Test alternative management paths: ?manager (manages|supervises) ?employee"""
    
    query = """
    PREFIX ex: <http://vital.ai/example/>
    
    SELECT ?manager ?employee ?managerName ?employeeName
    WHERE {
        ?manager (ex:manages|ex:supervises) ?employee .
        ?manager ex:hasName ?managerName .
        ?employee ex:hasName ?employeeName .
    }
    ORDER BY ?managerName ?employeeName
    """
    
    results = await execute_sparql_query(
        query, 
        "Testing alternative management paths: ?manager (manages|supervises) ?employee"
    )
    
    # Expected: All management relationships (both manages and supervises)
    expected_min_results = 8  # At least 8 management relationships (both types)
    
    if len(results) >= expected_min_results:
        print(f"✅ Alternative management paths test passed: found {len(results)} management relationships")
    else:
        print(f"❌ Alternative management paths test failed: expected at least {expected_min_results} results, got {len(results)}")

async def test_alternative_paths_with_transitive():
    """Test alternative paths with transitive: ?person (knows|directlyKnows)+ ?other"""
    
    query = """
    PREFIX ex: <http://vital.ai/example/>
    
    SELECT ?person ?other ?personName ?otherName
    WHERE {
        ?person (ex:knows|ex:directlyKnows)+ ?other .
        ?person ex:hasName ?personName .
        ?other ex:hasName ?otherName .
        FILTER(?person = ex:alice)
    }
    ORDER BY ?otherName
    """
    
    results = await execute_sparql_query(
        query, 
        "Testing alternative paths with transitive: Alice (knows|directlyKnows)+ ?other"
    )
    
    # Expected: All people Alice knows transitively through either property
    expected_min_results = 4  # At least 4 people Alice knows transitively
    
    if len(results) >= expected_min_results:
        print(f"✅ Alternative transitive paths test passed: Alice knows {len(results)} people via alternative paths")
    else:
        print(f"❌ Alternative transitive paths test failed: expected at least {expected_min_results} results, got {len(results)}")

# ===== INVERSE PATH TESTS (~) =====

async def test_inverse_paths():
    """Test inverse paths: ?child ~parentOf ?parent (equivalent to ?parent parentOf ?child)"""
    
    query = """
    PREFIX ex: <http://vital.ai/example/>
    
    SELECT ?child ?parent ?childName ?parentName
    WHERE {
        ?child ~ex:parentOf ?parent .
        ?child ex:hasName ?childName .
        ?parent ex:hasName ?parentName .
    }
    ORDER BY ?childName ?parentName
    """
    
    results = await execute_sparql_query(
        query, 
        "Testing inverse paths: ?child ~parentOf ?parent (children and their parents)"
    )
    
    # Expected: All parent-child relationships viewed from child perspective
    expected_min_results = 3  # At least 3 parent-child relationships
    
    if len(results) >= expected_min_results:
        print(f"✅ Inverse paths test passed: found {len(results)} parent-child relationships")
    else:
        print(f"❌ Inverse paths test failed: expected at least {expected_min_results} results, got {len(results)}")

async def test_inverse_paths_with_transitive():
    """Test inverse paths with transitive: ?employee ~manages+ ?topManager"""
    
    query = """
    PREFIX ex: <http://vital.ai/example/>
    
    SELECT ?employee ?topManager ?employeeName ?managerName
    WHERE {
        ?employee ~ex:manages+ ?topManager .
        ?employee ex:hasName ?employeeName .
        ?topManager ex:hasName ?managerName .
        FILTER(?topManager = ex:ceo)
    }
    ORDER BY ?employeeName
    """
    
    results = await execute_sparql_query(
        query, 
        "Testing inverse transitive paths: ?employee ~manages+ CEO (all employees under CEO)"
    )
    
    # Expected: All employees who are transitively managed by CEO
    expected_min_results = 5  # At least 5 employees under CEO
    
    if len(results) >= expected_min_results:
        print(f"✅ Inverse transitive paths test passed: found {len(results)} employees under CEO")
    else:
        print(f"❌ Inverse transitive paths test failed: expected at least {expected_min_results} results, got {len(results)}")

# ===== NEGATED PATH TESTS (!) =====

async def test_negated_paths():
    """Test negated paths: ?person !knows ?other (people who don't know each other directly)"""
    
    query = """
    PREFIX ex: <http://vital.ai/example/>
    
    SELECT ?person ?other ?personName ?otherName
    WHERE {
        ?person a ex:Person .
        ?other a ex:Person .
        ?person !ex:knows ?other .
        ?person ex:hasName ?personName .
        ?other ex:hasName ?otherName .
        FILTER(?person != ?other)
    }
    ORDER BY ?personName ?otherName
    LIMIT 10
    """
    
    results = await execute_sparql_query(
        query, 
        "Testing negated paths: ?person !knows ?other (people who don't know each other directly)"
    )
    
    # Expected: Pairs of people who don't have direct knows relationships
    # This should return some results since not everyone knows everyone directly
    expected_min_results = 1  # At least 1 pair who don't know each other
    
    if len(results) >= expected_min_results:
        print(f"✅ Negated paths test passed: found {len(results)} pairs who don't know each other directly")
    else:
        print(f"❌ Negated paths test failed: expected at least {expected_min_results} results, got {len(results)}")

# ===== COMPLEX COMBINATION TESTS =====

async def test_complex_path_combinations():
    """Test complex path combinations: academic relationships"""
    
    query = """
    PREFIX ex: <http://vital.ai/example/>
    
    SELECT ?professor ?student ?studentName ?professorName
    WHERE {
        ?professor (ex:advises|ex:mentors)+ ?student .
        ?professor ex:hasName ?professorName .
        ?student ex:hasName ?studentName .
        ?student a ex:Academic .
    }
    ORDER BY ?professorName ?studentName
    """
    
    results = await execute_sparql_query(
        query, 
        "Testing complex combinations: ?professor (advises|mentors)+ ?student"
    )
    
    # Expected: Academic advisory relationships
    expected_min_results = 1  # At least 1 advisory relationship
    
    if len(results) >= expected_min_results:
        print(f"✅ Complex path combinations test passed: found {len(results)} academic relationships")
    else:
        print(f"❌ Complex path combinations test failed: expected at least {expected_min_results} results, got {len(results)}")

async def test_nested_sequence_with_alternatives():
    """Test nested sequence with alternatives: transport connections to names"""
    
    query = """
    PREFIX ex: <http://vital.ai/example/>
    
    SELECT ?station ?destinationName ?stationName
    WHERE {
        ?station (ex:busRoute|ex:trainRoute|ex:subwayRoute)+/ex:hasName ?destinationName .
        ?station ex:hasName ?stationName .
        FILTER(?station = ex:station_a)
    }
    ORDER BY ?destinationName
    """
    
    results = await execute_sparql_query(
        query, 
        "Testing nested sequence with alternatives: Station A (busRoute|trainRoute|subwayRoute)+/hasName ?name"
    )
    
    # Expected: Names of all stations reachable from Station A via any transport
    expected_min_results = 2  # At least 2 reachable stations
    
    if len(results) >= expected_min_results:
        print(f"✅ Nested sequence with alternatives test passed: Station A can reach {len(results)} stations")
    else:
        print(f"❌ Nested sequence with alternatives test failed: expected at least {expected_min_results} results, got {len(results)}")

# ===== ZERO-OR-MORE AND SELF-REFERENTIAL TESTS =====

async def test_zero_or_more_self_referential():
    """Test zero-or-more with self-referential relationships"""
    
    query = """
    PREFIX ex: <http://vital.ai/example/>
    
    SELECT ?node1 ?node2 ?name1 ?name2
    WHERE {
        ?node1 ex:connectsTo* ?node2 .
        ?node1 ex:hasName ?name1 .
        ?node2 ex:hasName ?name2 .
        ?node1 a ex:GraphNode .
        ?node2 a ex:GraphNode .
    }
    ORDER BY ?name1 ?name2
    """
    
    results = await execute_sparql_query(
        query, 
        "Testing zero-or-more with self-referential: ?node1 connectsTo* ?node2"
    )
    
    # Expected: All reachable nodes including reflexive relationships
    expected_min_results = 4  # At least 4 relationships (including self-loops and bidirectional)
    
    if len(results) >= expected_min_results:
        print(f"✅ Zero-or-more self-referential test passed: found {len(results)} connections")
    else:
        print(f"❌ Zero-or-more self-referential test failed: expected at least {expected_min_results} results, got {len(results)}")

# ===== PERFORMANCE AND CYCLE DETECTION TESTS =====

async def test_cycle_detection():
    """Test cycle detection in transitive paths"""
    
    query = """
    PREFIX ex: <http://vital.ai/example/>
    
    SELECT ?person ?reachable ?personName ?reachableName
    WHERE {
        ?person ex:knows+ ?reachable .
        ?person ex:hasName ?personName .
        ?reachable ex:hasName ?reachableName .
        FILTER(?person = ex:alice && ?reachable = ex:alice)
    }
    """
    
    results = await execute_sparql_query(
        query, 
        "Testing cycle detection: Alice knows+ Alice (should find cyclic path)"
    )
    
    # Expected: Alice should be reachable from herself via the cycle
    expected_results = 1  # Exactly 1 result showing Alice can reach herself
    
    if len(results) == expected_results:
        print(f"✅ Cycle detection test passed: found cyclic path Alice -> ... -> Alice")
    else:
        print(f"❌ Cycle detection test failed: expected {expected_results} result, got {len(results)}")

async def test_negated_path():
    """Test negated paths (!): Find people who do NOT know each other directly"""
    
    query = """
    PREFIX ex: <http://example.org/>
    
    SELECT ?person1 ?person2 ?name1 ?name2
    WHERE {
        GRAPH <urn:___GLOBAL> {
            ?person1 !ex:knows ?person2 .
            ?person1 ex:hasName ?name1 .
            ?person2 ex:hasName ?name2 .
            FILTER(?person1 != ?person2)  # Exclude self-pairs
        }
    }
    ORDER BY ?name1 ?name2
    LIMIT 10
    """
    
    # run_query returns None on success, so we need to use a different approach
    # Let's use the direct sparql execution method
    try:
        start_time = time.time()
        results = await sparql_impl.execute_sparql_query("space_test", query)
        end_time = time.time()
        execution_time = end_time - start_time
        
        # Expected: Should find pairs of people who are not directly connected by 'knows'
        # This should be a significant number since not everyone knows everyone
        expected_min_results = 5  # At least 5 pairs who don't know each other
        
        if len(results) >= expected_min_results:
            print(f"✅ Negated path test passed: found {len(results)} pairs who don't know each other directly in {execution_time:.3f}s")
            # Show a few examples
            for i, result in enumerate(results[:3]):
                print(f"   Example {i+1}: {result['name1']} does NOT know {result['name2']}")
        else:
            print(f"❌ Negated path test failed: expected at least {expected_min_results} results, got {len(results)} in {execution_time:.3f}s")
    except Exception as e:
        print(f"❌ Negated path test failed with error: {e}")

# ===== MAIN TEST RUNNER =====

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



async def main():
    """Run property path tests."""
    print("🧪 VitalGraph SPARQL Property Paths Test Suite")
    print("=" * 60)
    
    # Setup connection
    await setup_connection()
    
    try:
        # Run diagnostics first
        await diagnose_database_predicates()
        
        # Test basic knows relationships first
        # Test 1: Transitive Plus Path (knows+)
        plus_query = """
            PREFIX ex: <http://example.org/>
            SELECT ?person ?name
            WHERE {
                GRAPH <urn:___GLOBAL> {
                    ex:Alice ex:knows+ ?person .
                    ?person ex:hasName ?name .
                }
            }
            ORDER BY ?name
        """
        
        print("🔍 Testing transitive plus path: ex:knows+")
        start_time = time.time()
        results = await sparql_impl.execute_sparql_query("space_test", plus_query)
        end_time = time.time()
        execution_time = end_time - start_time
        print(f"✅ Transitive Plus Path (knows+): {len(results)} results in {execution_time:.3f}s")
        
        print("\n🔄 TRANSITIVE PATH TESTS")
        print("-" * 40)
        await test_transitive_plus_path(sparql_impl)
        
        print("\n🚫 NEGATED PATH TESTS")
        print("-" * 40)
        await test_negated_path()
        
    finally:
        # Cleanup
        await cleanup_connection()
        print("\n✅ Property Path Test Complete!")

if __name__ == "__main__":
    asyncio.run(main())
