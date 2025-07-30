#!/usr/bin/env python3
"""
GRAPH Query Test Script
=======================

Focused testing of SPARQL GRAPH patterns with WordNet data.
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

# Reduce logging chatter
logging.getLogger('vitalgraph.db.postgresql.postgresql_space_impl').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.rdf.rdf_utils').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.db.postgresql.postgresql_cache_term').setLevel(logging.WARNING)

# Configuration
SPACE_ID = "wordnet_space"
GRAPH_URI = "http://vital.ai/graph/wordnet"

async def run_query(sparql_impl, name, sparql, debug=False):
    """Execute a single SPARQL query using TestToolUtils for clean, maintainable code."""
    # Use the utility function to run the complete test with all features
    result = await TestToolUtils.run_test_query(
        sparql_impl=sparql_impl,
        space_id=SPACE_ID,
        query_name=name,
        query=sparql,
        enable_algebra_logging=debug,  # Enable detailed logging only if debug is True
        max_results=2  # Show first 2 results like the original
    )
    return result

async def test_graph_queries():
    """Test GRAPH pattern queries using TestToolUtils for clean, maintainable code."""
    print("🧪 GRAPH Query Tests - Refactored with Utilities")
    print("=" * 50)
    
    # Initialize
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    space_impl = impl.db_impl.get_space_impl()
    sparql_impl = PostgreSQLSparqlImpl(space_impl)
    
    print(f"✅ Connected | Testing GRAPH patterns with utility modules")
    print(f"🎯 Target Graph: {GRAPH_URI}")
    
    # Track test results for summary
    test_results = []
    
    TestToolUtils.print_test_section_header("1. NAMED GRAPH QUERIES", "Testing specific named graph patterns")
    
    result = await run_query(sparql_impl, "Count entities in WordNet graph", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT (COUNT(?entity) AS ?count) WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
            }}
        }}
    """)
    test_results.append(result)
    
    result = await run_query(sparql_impl, "Entities with names in WordNet graph", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT ?entity ?name WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity <http://vital.ai/ontology/vital-core#hasName> ?name .
            }}
        }}
        LIMIT 3
    """)
    test_results.append(result)
    
    result = await run_query(sparql_impl, "Non-existent graph (should return 0)", """
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT ?entity WHERE {
            GRAPH <http://example.com/nonexistent> {
                ?entity rdf:type haley:KGEntity .
            }
        }
    """)
    test_results.append(result)
    
    print("\n2. VARIABLE GRAPH QUERIES:")
    
    result = await run_query(sparql_impl, "Count entities by graph", """
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT ?g (COUNT(?entity) AS ?count) WHERE {
            GRAPH ?g {
                ?entity rdf:type haley:KGEntity .
            }
        }
        GROUP BY ?g
    """)
    test_results.append(result)
    
    result = await run_query(sparql_impl, "Variable graph with filtered entities", """
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT ?g ?entity ?name WHERE {
            GRAPH ?g {
                ?entity rdf:type haley:KGEntity .
                ?entity <http://vital.ai/ontology/vital-core#hasName> ?name .
            }
            FILTER(CONTAINS(?name, "happy"))
        }
        LIMIT 3
    """)
    test_results.append(result)
    
    print("\n3. GLOBAL GRAPH QUERIES:")
    
    result = await run_query(sparql_impl, "Query global graph directly", """
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT ?person ?name ?age WHERE {
            GRAPH <urn:___GLOBAL> {
                ?person rdf:type <http://example.org/Person> .
                ?person <http://example.org/hasName> ?name .
                ?person <http://example.org/hasAge> ?age .
            }
        }
    """)
    test_results.append(result)
    
    result = await run_query(sparql_impl, "Global graph relationships", """
        SELECT ?person1 ?name1 ?person2 ?name2 WHERE {
            GRAPH <urn:___GLOBAL> {
                ?person1 <http://example.org/knows> ?person2 .
                ?person1 <http://example.org/hasName> ?name1 .
                ?person2 <http://example.org/hasName> ?name2 .
            }
        }
    """)
    test_results.append(result)
    
    result = await run_query(sparql_impl, "Global test entities", """
        SELECT ?entity ?value WHERE {
            GRAPH <urn:___GLOBAL> {
                ?entity <http://example.org/hasProperty> ?value .
            }
        }
    """)
    test_results.append(result)
    
    print("\n4. DEFAULT GRAPH UNION QUERIES:")
    
    result = await run_query(sparql_impl, "Default graph union - should include both named and global data", """
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT ?s ?p ?o WHERE {
            ?s ?p ?o .
            FILTER(
                ?s = <http://example.org/person/alice> ||
                ?s = <http://vital.ai/haley.ai/chat-saas/KGEntity/1447109393012_1265235442>
            )
        }
        LIMIT 10
    """)
    test_results.append(result)
    
    result = await run_query(sparql_impl, "Count all entities across all graphs (union)", """
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT (COUNT(?entity) AS ?count) WHERE {
            {
                ?entity rdf:type haley:KGEntity .
            } UNION {
                ?entity rdf:type <http://example.org/Person> .
            }
        }
    """)
    test_results.append(result)
    
    print("\n5. COMPLEX GRAPH PATTERNS:")
    
    result = await run_query(sparql_impl, "Graph with connected entities", f"""
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT ?entity ?name ?edge ?connected WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity <http://vital.ai/ontology/vital-core#hasName> ?name .
                ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeSource> ?entity .
                ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeDestination> ?connected .
            }}
            FILTER(CONTAINS(?name, "happy"))
        }}
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
    print("\n✅ GRAPH Query Tests Complete!")
    
    # Return test results for aggregation
    return test_results

if __name__ == "__main__":
    asyncio.run(test_graph_queries())
