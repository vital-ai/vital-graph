#!/usr/bin/env python3
"""
OPTIONAL Query Test Script
==========================

Test SPARQL OPTIONAL pattern functionality in VitalGraph's PostgreSQL-backed SPARQL engine.
This file focuses specifically on OPTIONAL pattern translation and execution.

OPTIONAL patterns allow querying with optional data:
- ?s ?p ?o . OPTIONAL { ?s ?p2 ?o2 }
- Nested OPTIONAL patterns
- OPTIONAL with FILTER conditions
- OPTIONAL across different graphs
- OPTIONAL with BIND expressions

The test data includes entities with deliberately missing optional properties
to validate that OPTIONAL patterns work correctly with NULL values.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.db.postgresql.postgresql_sparql_impl import PostgreSQLSparqlImpl

# Import test utilities for consistent test execution and reporting
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tool_utils"))
from tool_utils import TestToolUtils

# Configure logging - TEMPORARILY SET TO DEBUG
logging.basicConfig(
    level=logging.DEBUG,
    format='%(levelname)s - %(name)s - %(message)s'
)

# Suppress verbose logging from other modules but keep SPARQL SQL logging
logging.getLogger('vitalgraph.rdf.rdf_utils').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.db.postgresql.postgresql_cache_term').setLevel(logging.WARNING)
# Keep SPARQL implementation logging at DEBUG level to see detailed SQL generation
logging.getLogger('vitalgraph.db.postgresql.postgresql_sparql_impl').setLevel(logging.DEBUG)

# Configuration
SPACE_ID = "space_test"
GRAPH_URI = "http://vital.ai/graph/test"
GLOBAL_GRAPH_URI = "urn:___GLOBAL"

async def run_optional_query(sparql_impl, query_name, query):
    """Run a single OPTIONAL query and display results."""
    print(f"  {query_name}:")
    
    # Log the RDFLib query algebra for debugging
    try:
        from rdflib.plugins.sparql import prepareQuery
        from rdflib.plugins.sparql.algebra import translateAlgebra
        
        print(f"    📋 Analyzing query algebra...")
        prepared_query = prepareQuery(query)
        algebra = translateAlgebra(prepared_query)
        
        # Log algebra structure
        print(f"    🔍 Query type: {algebra.name}")
        print(f"    🔍 Algebra structure:")
        
        def log_algebra_node(node, indent=6):
            """Recursively log algebra node structure."""
            spaces = " " * indent
            
            # Handle different node types
            if hasattr(node, 'name'):
                print(f"{spaces}📌 {node.name}")
                
                # Special handling for LeftJoin (OPTIONAL) patterns
                if node.name == 'LeftJoin':
                    if hasattr(node, 'p1') and node.p1:
                        print(f"{spaces}  ├─ REQUIRED PATTERN:")
                        log_algebra_node(node.p1, indent + 4)
                    if hasattr(node, 'p2') and node.p2:
                        print(f"{spaces}  ├─ OPTIONAL PATTERN:")
                        log_algebra_node(node.p2, indent + 4)
                    if hasattr(node, 'expr') and node.expr:
                        print(f"{spaces}  └─ FILTER EXPRESSION:")
                        print(f"{spaces}      {node.expr}")
                    return
                
                # Log nested pattern
                if hasattr(node, 'p') and node.p:
                    if hasattr(node.p, 'name'):
                        print(f"{spaces}  └─ p: {node.p.name}")
                        log_algebra_node(node.p, indent + 4)
                    else:
                        print(f"{spaces}  └─ p: {type(node.p).__name__}")
                
                # Log direct p1/p2 attributes
                if hasattr(node, 'p1') and node.p1:
                    if hasattr(node.p1, 'name'):
                        print(f"{spaces}  ├─ p1: {node.p1.name}")
                        log_algebra_node(node.p1, indent + 4)
                    else:
                        print(f"{spaces}  ├─ p1: {type(node.p1).__name__}")
                        
                if hasattr(node, 'p2') and node.p2:
                    if hasattr(node.p2, 'name'):
                        print(f"{spaces}  └─ p2: {node.p2.name}")
                        log_algebra_node(node.p2, indent + 4)
                    else:
                        print(f"{spaces}  └─ p2: {type(node.p2).__name__}")
                        
                # Log triples for BGP patterns
                if node.name == 'BGP' and hasattr(node, 'triples'):
                    for i, triple in enumerate(node.triples):
                        print(f"{spaces}  [{i+1}] {triple}")
            else:
                print(f"{spaces}📌 {type(node).__name__}")
        
        log_algebra_node(algebra)
        
    except Exception as e:
        print(f"    ⚠️  Could not analyze algebra: {e}")
    
    # Use TestToolUtils to run the query with proper result tracking
    result = await TestToolUtils.run_test_query(
        sparql_impl=sparql_impl,
        space_id=SPACE_ID,
        query_name=query_name,
        query=query,
        max_results=20  # Reasonable limit for display
    )
    return result

async def test_basic_optional_patterns(sparql_impl, GLOBAL_GRAPH_URI):
    """Test basic OPTIONAL patterns."""
    print("\n1. BASIC OPTIONAL PATTERNS:")
    
    # Test 1: Simple OPTIONAL - people with optional email addresses
    await run_optional_query(sparql_impl, "People with optional email addresses", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?email WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasEmail ?email }}
            }}
        }}
        ORDER BY ?name
    """)
    
    # Test 2: Multiple OPTIONAL properties
    await run_optional_query(sparql_impl, "People with optional email and phone", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?email ?phone WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasEmail ?email }}
                OPTIONAL {{ ?person ex:hasPhone ?phone }}
            }}
        }}
        ORDER BY ?name
    """)
    
    # Test 3: OPTIONAL with FILTER
    await run_optional_query(sparql_impl, "People with optional email containing 'wayne'", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?email WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ 
                    ?person ex:hasEmail ?email 
                    FILTER(CONTAINS(?email, "wayne"))
                }}
            }}
        }}
        ORDER BY ?name
    """)

async def test_bound_function_queries(sparql_impl, GLOBAL_GRAPH_URI):
    """Test SPARQL BOUND function in OPTIONAL contexts."""
    print("\n🎯 BOUND FUNCTION TESTS:")
    
    # Test with BOUND in BIND expression
    await run_optional_query(sparql_impl, "BOUND function test 1 - IF with BOUND", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?hasContact WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ 
                    ?person ex:hasEmail ?email 
                    BIND(true AS ?hasContact)
                }}
            }}
            BIND(IF(BOUND(?hasContact), ?hasContact, false) AS ?hasContact)
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    
    # Test with complex BOUND expression
    await run_optional_query(sparql_impl, "BOUND function test 2 - Complex BOUND with OR", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?complete WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasEmail ?email }}
                OPTIONAL {{ ?person ex:hasPhone ?phone }}
            }}
            BIND(IF(BOUND(?email) || BOUND(?phone), "yes", "no") AS ?complete)
        }}
        ORDER BY ?name
        LIMIT 5
    """)

async def test_nested_optional_patterns(sparql_impl, GLOBAL_GRAPH_URI):
    """Test nested OPTIONAL patterns."""
    print("\n2. NESTED OPTIONAL PATTERNS:")
    
    # Test 4: Nested OPTIONAL - employees with optional manager info
    await run_optional_query(sparql_impl, "Employees with optional manager details", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?employee ?empName ?manager ?managerName ?managerEmail WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?employee rdf:type ex:Person .
                ?employee ex:hasName ?empName .
                OPTIONAL {{
                    ?employee ex:reportsTo ?manager .
                    ?manager ex:hasName ?managerName .
                    OPTIONAL {{ ?manager ex:hasEmail ?managerEmail }}
                }}
            }}
        }}
        ORDER BY ?empName
    """)
    
    # Test 5: Multiple nested OPTIONAL - products with optional details
    await run_optional_query(sparql_impl, "Products with nested optional properties", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?product ?name ?category ?price ?warranty ?color WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?product rdf:type ex:Product .
                ?product ex:hasName ?name .
                OPTIONAL {{
                    ?product ex:hasCategory ?category .
                    OPTIONAL {{ ?product ex:hasPrice ?price }}
                }}
                OPTIONAL {{
                    ?product ex:hasWarranty ?warranty .
                    ?product ex:hasColor ?color 
                }}
            }}
        }}
        ORDER BY ?name
    """)

async def test_optional_queries():
    """Test OPTIONAL pattern functionality with various scenarios using TestToolUtils."""
    print("🧪 OPTIONAL Query Tests")
    print("=" * 60)
    
    # Initialize
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    # Get SPARQL implementation
    space_impl = impl.db_impl.get_space_impl()
    sparql_impl = PostgreSQLSparqlImpl(space_impl)
    
    print(f"✅ Connected | Testing OPTIONAL patterns with comprehensive test coverage")
    print(f"🎯 Target Graph: {GLOBAL_GRAPH_URI}")
    
    # Track test results for summary
    test_results = []
    
    TestToolUtils.print_test_section_header("1. BASIC OPTIONAL PATTERNS", "Testing fundamental OPTIONAL patterns")
    
    # Test 1: Basic OPTIONAL - people with optional email addresses
    result = await run_optional_query(sparql_impl, "People with optional email addresses", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?email WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasEmail ?email }}
            }}
        }}
        ORDER BY ?name
        LIMIT 10
    """)
    test_results.append(result)
    
    # Test 2: Multiple OPTIONAL properties
    result = await run_optional_query(sparql_impl, "People with optional email and phone", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?email ?phone WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasEmail ?email }}
                OPTIONAL {{ ?person ex:hasPhone ?phone }}
            }}
        }}
        ORDER BY ?name
        LIMIT 10
    """)
    test_results.append(result)
    
    # Test 3: OPTIONAL with FILTER
    result = await run_optional_query(sparql_impl, "People with optional email containing 'wayne'", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?email WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ 
                    ?person ex:hasEmail ?email 
                    FILTER(CONTAINS(?email, "wayne"))
                }}
            }}
        }}
        ORDER BY ?name
        LIMIT 10
    """)
    test_results.append(result)
    
    TestToolUtils.print_test_section_header("2. BOUND FUNCTION TESTS", "Testing BOUND function with OPTIONAL")
    
    # Test 4: BOUND function test 1 - IF with BOUND
    result = await run_optional_query(sparql_impl, "BOUND function test 1 - IF with BOUND", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?hasContact WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ 
                    ?person ex:hasEmail ?email 
                    BIND(true AS ?hasContact)
                }}
            }}
            BIND(IF(BOUND(?hasContact), ?hasContact, false) AS ?hasContact)
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)
    
    # Test 5: BOUND function test 2 - Complex BOUND with OR
    result = await run_optional_query(sparql_impl, "BOUND function test 2 - Complex BOUND with OR", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?complete WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasEmail ?email }}
                OPTIONAL {{ ?person ex:hasPhone ?phone }}
            }}
            BIND(IF(BOUND(?email) || BOUND(?phone), "yes", "no") AS ?complete)
        }}
        ORDER BY ?name
        LIMIT 5
    """)
    test_results.append(result)
    
    TestToolUtils.print_test_section_header("3. NESTED OPTIONAL PATTERNS", "Testing nested OPTIONAL structures")
    
    # Test 6: Nested OPTIONAL - employees with optional manager details
    result = await run_optional_query(sparql_impl, "Employees with optional manager details", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?employee ?empName ?department ?manager ?managerName ?managerTitle WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?employee rdf:type ex:Employee .
                ?employee ex:hasName ?empName .
                OPTIONAL {{ ?employee ex:hasDepartment ?department }}
                OPTIONAL {{ 
                    ?employee ex:hasManager ?manager .
                    OPTIONAL {{
                        ?manager ex:hasName ?managerName .
                        OPTIONAL {{ ?manager ex:hasTitle ?managerTitle }}
                    }}
                }}
            }}
        }}
        ORDER BY ?empName
    """)
    test_results.append(result)
    
    # Test 7: OPTIONAL with complex patterns - products with specifications
    result = await run_optional_query(sparql_impl, "Products with optional specifications", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?product ?name ?price ?warranty ?color WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?product rdf:type ex:Product .
                ?product ex:hasName ?name .
                OPTIONAL {{ ?product ex:hasPrice ?price }}
                OPTIONAL {{ 
                    ?product ex:hasWarranty ?warranty .
                    ?product ex:hasColor ?color 
                }}
            }}
        }}
        ORDER BY ?name
    """)
    test_results.append(result)
    
    TestToolUtils.print_test_section_header("4. OPTIONAL WITH BIND EXPRESSIONS", "Testing OPTIONAL with BIND")
    
    # Test 8: OPTIONAL with BIND - create computed values for optional data
    result = await run_optional_query(sparql_impl, "People with computed contact info", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?person ?name ?contactInfo ?hasContact WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ 
                    ?person ex:hasEmail ?email 
                    BIND(CONCAT("Email: ", ?email) AS ?contactInfo)
                    BIND(true AS ?hasContact)
                }}
                OPTIONAL {{ 
                    ?person ex:hasPhone ?phone 
                    BIND(CONCAT("Phone: ", ?phone) AS ?contactInfo)
                    BIND(true AS ?hasContact)
                }}
            }}
            BIND(IF(BOUND(?hasContact), ?hasContact, false) AS ?hasContact)
        }}
        ORDER BY ?name
    """)
    test_results.append(result)
    
    TestToolUtils.print_test_section_header("5. CROSS-GRAPH OPTIONAL", "Testing OPTIONAL across different graphs")
    
    # Test 9: OPTIONAL patterns across different graphs
    result = await run_optional_query(sparql_impl, "Cross-graph OPTIONAL patterns", f"""
        PREFIX ex: <http://example.org/>
        PREFIX test: <http://example.org/test#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?name ?testInfo WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?entity rdf:type ex:Person .
                ?entity ex:hasName ?name .
            }}
            OPTIONAL {{
                GRAPH <{GRAPH_URI}> {{
                    ?entity test:hasInfo ?testInfo
                }}
            }}
        }}
        ORDER BY ?name
    """)
    test_results.append(result)
    
    TestToolUtils.print_test_section_header("6. OPTIONAL WITH UNION", "Testing OPTIONAL combined with UNION")
    
    # Test 10: Combining OPTIONAL and UNION patterns
    result = await run_optional_query(sparql_impl, "OPTIONAL with UNION - flexible contact lookup", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?entity ?name ?contact ?contactType WHERE {{
            {{
                GRAPH <{GLOBAL_GRAPH_URI}> {{
                    ?entity rdf:type ex:Person .
                    ?entity ex:hasName ?name .
                    OPTIONAL {{ 
                        ?entity ex:hasEmail ?contact 
                        BIND("email" AS ?contactType)
                    }}
                }}
            }}
            UNION
            {{
                GRAPH <{GLOBAL_GRAPH_URI}> {{
                    ?entity rdf:type ex:Organization .
                    ?entity ex:hasName ?name .
                    OPTIONAL {{ 
                        ?entity ex:hasWebsite ?contact 
                        BIND("website" AS ?contactType)
                    }}
                }}
            }}
        }}
        ORDER BY ?contactType ?name
    """)
    test_results.append(result)
    
    TestToolUtils.print_test_section_header("7. COMPLEX OPTIONAL SCENARIOS", "Testing advanced OPTIONAL patterns")
    
    # Test 11: Organizations with optional project relationships
    result = await run_optional_query(sparql_impl, "Organizations with optional project relationships", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT ?org ?orgName ?orgType ?project ?projectName WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?org rdf:type ex:Organization .
                ?org ex:hasName ?orgName .
                OPTIONAL {{ ?org ex:hasType ?orgType }}
                OPTIONAL {{
                    ?person ex:worksFor ?org .
                    ?person ex:memberOf ?project .
                    ?project ex:hasName ?projectName
                }}
            }}
        }}
        ORDER BY ?orgName ?projectName
    """)
    test_results.append(result)
    
    # Test 12: CONSTRUCT with OPTIONAL patterns
    result = await run_optional_query(sparql_impl, "CONSTRUCT with OPTIONAL - unified profiles [CONSTRUCT LIMITATION]", f"""
        PREFIX ex: <http://example.org/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?person ex:hasProfile ?profile .
            ?profile ex:displayName ?name .
            ?profile ex:contactMethod ?contact .
            ?profile ex:hasCompleteInfo ?complete .
        }}
        WHERE {{
            GRAPH <{GLOBAL_GRAPH_URI}> {{
                ?person rdf:type ex:Person .
                ?person ex:hasName ?name .
                OPTIONAL {{ ?person ex:hasEmail ?email }}
                OPTIONAL {{ ?person ex:hasPhone ?phone }}
            }}
            BIND(URI(CONCAT("http://example.org/profile/", ENCODE_FOR_URI(?name))) AS ?profile)
            BIND(COALESCE(?email, ?phone, "none") AS ?contact)
            BIND(IF(BOUND(?email) || BOUND(?phone), "yes", "no") AS ?complete)
        }}
        LIMIT 5
    """)
    test_results.append(result)
    
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
    print("\n✅ OPTIONAL Query Tests Complete!")
    print("💡 These queries test OPTIONAL pattern functionality with various scenarios")
    print("🔗 Test data includes entities with deliberately missing optional properties")
    
    # Return test results for aggregation
    return test_results

if __name__ == "__main__":
    asyncio.run(test_optional_queries())
