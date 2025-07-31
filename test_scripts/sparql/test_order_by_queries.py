#!/usr/bin/env python3
"""
ORDER BY Query Test Script
==========================

Test SPARQL ORDER BY functionality in VitalGraph's PostgreSQL-backed SPARQL engine.
This file focuses specifically on ORDER BY pattern translation and execution.

ORDER BY patterns allow sorting query results:
- ORDER BY ?var (ascending by default)
- ORDER BY DESC(?var) (descending)
- ORDER BY ?var1 DESC(?var2) (multiple variables)
- ORDER BY expressions like STRLEN(?name)
- ORDER BY with aggregation functions
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

def verify_order(results, order_by_vars, order_directions=None):
    """Verify that results are properly ordered according to ORDER BY specification."""
    if not results or len(results) < 2:
        return True, "Not enough results to verify ordering"
    
    if not order_by_vars:
        return True, "No ORDER BY variables specified"
    
    # Default to ascending if no directions specified
    if order_directions is None:
        order_directions = ['ASC'] * len(order_by_vars)
    
    for i in range(len(results) - 1):
        current = results[i]
        next_result = results[i + 1]
        
        for var_idx, var in enumerate(order_by_vars):
            direction = order_directions[var_idx] if var_idx < len(order_directions) else 'ASC'
            
            current_val = current.get(var)
            next_val = next_result.get(var)
            
            # Skip if either value is missing
            if current_val is None or next_val is None:
                continue
            
            # Convert to comparable values
            try:
                # Try numeric comparison first
                current_num = float(current_val)
                next_num = float(next_val)
                current_val, next_val = current_num, next_num
            except (ValueError, TypeError):
                # Fall back to string comparison
                current_val = str(current_val)
                next_val = str(next_val)
            
            # Check ordering
            if direction.upper() == 'ASC':
                if current_val > next_val:
                    return False, f"ASC order violation: {current_val} > {next_val} for variable {var}"
                elif current_val < next_val:
                    break  # This variable determines order, move to next pair
            else:  # DESC
                if current_val < next_val:
                    return False, f"DESC order violation: {current_val} < {next_val} for variable {var}"
                elif current_val > next_val:
                    break  # This variable determines order, move to next pair
    
    return True, "Results are properly ordered"

async def run_order_by_query(sparql_impl, query_name, query, order_by_vars=None, order_directions=None):
    """Run a single ORDER BY query and verify ordering using TestToolUtils."""
    # Use the utility function to run the complete test with all features
    result = await TestToolUtils.run_test_query(
        sparql_impl=sparql_impl,
        space_id=SPACE_ID,
        query_name=query_name,
        query=query,
        enable_algebra_logging=True,
        max_results=20  # Get more results to better verify ordering
    )
    
    # Verify ordering if specified
    if result.get('success', False) and order_by_vars:
        results = result.get('results', [])
        is_ordered, order_msg = verify_order(results, order_by_vars, order_directions)
        
        if is_ordered:
            print(f"   ✅ ORDER BY verification: {order_msg}")
            result['order_verified'] = True
        else:
            print(f"   ❌ ORDER BY verification FAILED: {order_msg}")
            result['order_verified'] = False
            result['order_error'] = order_msg
            
            # Show first few results for debugging
            print(f"   🔍 First few results for debugging:")
            for i, res in enumerate(results[:5]):
                values = [f"{var}={res.get(var, 'N/A')}" for var in order_by_vars]
                print(f"      {i+1}. {', '.join(values)}")
    
    return result

async def test_order_by_queries():
    """Test ORDER BY pattern functionality with various scenarios using TestToolUtils."""
    print("📊 ORDER BY Query Tests - Testing Sorting Functionality")
    print("=" * 50)
    
    # Initialize
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    space_impl = impl.db_impl.get_space_impl()
    sparql_impl = PostgreSQLSparqlImpl(space_impl)
    
    print(f"✅ Connected | Testing ORDER BY patterns with utility modules")
    
    # Track test results for summary
    test_results = []
    
    TestToolUtils.print_test_section_header("1. BASIC ORDER BY PATTERNS", "Testing fundamental ORDER BY query patterns")
    
    # Test 1: Simple ascending order (default)
    result = await run_order_by_query(sparql_impl, "Simple ORDER BY ASC - names", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?name WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity test:hasName ?name .
            }}
        }}
        ORDER BY ?name
        LIMIT 8
    """, order_by_vars=['name'], order_directions=['ASC'])
    test_results.append(result)
    
    # Test 2: Simple descending order
    result = await run_order_by_query(sparql_impl, "Simple ORDER BY DESC - ages", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasAge ?age .
            }}
        }}
        ORDER BY DESC(?age)
        LIMIT 8
    """, order_by_vars=['age'], order_directions=['DESC'])
    test_results.append(result)
    
    # Test 3: Multiple variable ordering
    result = await run_order_by_query(sparql_impl, "Multiple ORDER BY - category then name", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?category ?name WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity test:hasCategory ?category .
                ?entity test:hasName ?name .
            }}
        }}
        ORDER BY ?category DESC(?name)
        LIMIT 10
    """, order_by_vars=['category', 'name'], order_directions=['ASC', 'DESC'])
    test_results.append(result)
    
    TestToolUtils.print_test_section_header("2. ORDER BY WITH LIMIT/OFFSET", "Testing ORDER BY with result pagination")
    
    # Test 4: ORDER BY with LIMIT
    result = await run_order_by_query(sparql_impl, "ORDER BY with LIMIT - top 3 oldest", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                ?person ex:hasAge ?age .
            }}
        }}
        ORDER BY DESC(?age)
        LIMIT 3
    """, order_by_vars=['age'], order_directions=['DESC'])
    test_results.append(result)
    
    # Test 4: ORDER BY with LIMIT and OFFSET
    result = await run_order_by_query(sparql_impl, "ORDER BY with LIMIT/OFFSET - paginated names", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?name WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity test:hasName ?name .
            }}
        }}
        ORDER BY ?name
        LIMIT 5 OFFSET 3
    """, order_by_vars=['name'], order_directions=['ASC'])
    test_results.append(result)
    
    TestToolUtils.print_test_section_header("3. ORDER BY WITH AGGREGATION", "Testing ORDER BY with GROUP BY and aggregate functions")
    
    # Test 6: ORDER BY with COUNT aggregation
    result = await run_order_by_query(sparql_impl, "ORDER BY COUNT - categories by frequency", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?category (COUNT(?entity) AS ?count) WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity test:hasCategory ?category .
            }}
        }}
        GROUP BY ?category
        ORDER BY DESC(?count)
    """, order_by_vars=['count'], order_directions=['DESC'])
    test_results.append(result)
    
    TestToolUtils.print_test_section_header("4. ORDER BY WITH COMPLEX PATTERNS", "Testing ORDER BY with OPTIONAL, FILTER, and expressions")
    
    # Test 7: ORDER BY with OPTIONAL
    result = await run_order_by_query(sparql_impl, "ORDER BY with OPTIONAL - names with optional descriptions", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?name ?description WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity test:hasName ?name .
                OPTIONAL {{ ?entity test:hasDescription ?description }}
            }}
        }}
        ORDER BY ?name
        LIMIT 8
    """, order_by_vars=['name'], order_directions=['ASC'])
    test_results.append(result)
    
    # Test 8: ORDER BY with FILTER
    result = await run_order_by_query(sparql_impl, "ORDER BY with FILTER - adults only, sorted by age", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?age WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person ex:hasName ?name .
                ?person ex:hasAge ?age .
                FILTER(?age >= 25)
            }}
        }}
        ORDER BY DESC(?age)
    """, order_by_vars=['age'], order_directions=['DESC'])
    test_results.append(result)
    
    # Test 9: ORDER BY with UNION
    result = await run_order_by_query(sparql_impl, "ORDER BY with UNION - names from multiple graphs", f"""
        PREFIX test: <http://example.org/test#>
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?name ?source WHERE {{
            {{
                GRAPH <{GRAPH_URI}> {{
                    ?entity test:hasName ?name .
                    BIND("test_graph" AS ?source)
                }}
            }}
            UNION
            {{
                GRAPH <{GLOBAL_GRAPH_URI}> {{
                    ?entity ex:hasName ?name .
                    BIND("global_graph" AS ?source)
                }}
            }}
        }}
        ORDER BY ?source ?name
        LIMIT 10
    """, order_by_vars=['source', 'name'], order_directions=['ASC', 'ASC'])
    test_results.append(result)
    
    # Test results summary
    total_tests = len(test_results)
    successful_tests = sum(1 for result in test_results if result.get('success', False))
    failed_tests = total_tests - successful_tests
    success_rate = (successful_tests / total_tests * 100) if total_tests > 0 else 0
    
    # ORDER BY verification summary
    order_verified_tests = sum(1 for result in test_results if result.get('order_verified', False))
    order_failed_tests = sum(1 for result in test_results if result.get('order_verified') == False)
    order_verification_rate = (order_verified_tests / total_tests * 100) if total_tests > 0 else 0
    
    print(f"\n📊 Test Results Summary:")
    print(f"   Total Tests: {total_tests}")
    print(f"   ✅ Query Execution Passed: {successful_tests}")
    print(f"   ❌ Query Execution Failed: {failed_tests}")
    print(f"   📈 Query Success Rate: {success_rate:.1f}%")
    print(f"   \n🔄 ORDER BY Verification:")
    print(f"   ✅ Properly Ordered: {order_verified_tests}")
    print(f"   ❌ Order Verification Failed: {order_failed_tests}")
    print(f"   📈 Order Verification Rate: {order_verification_rate:.1f}%")
    
    if failed_tests > 0:
        print(f"\n❌ Failed Query Executions:")
        for result in test_results:
            if not result.get('success', False):
                print(f"   • {result.get('query_name', 'Unknown')}: {result.get('error_msg', 'Unknown error')}")
    
    if order_failed_tests > 0:
        print(f"\n❌ Failed ORDER BY Verifications:")
        for result in test_results:
            if result.get('order_verified') == False:
                print(f"   • {result.get('query_name', 'Unknown')}: {result.get('order_error', 'Unknown order error')}")
    
    # Performance summary
    print(f"\n📊 Cache: {sparql_impl.term_cache.size()} terms")
    
    await impl.db_impl.disconnect()
    print("\n✅ ORDER BY Query Tests Complete!")
    print("📊 Test data includes entities, numbers, and relationships with various sorting scenarios")
    
    # Return test results for aggregation
    return test_results

if __name__ == "__main__":
    asyncio.run(test_order_by_queries())
