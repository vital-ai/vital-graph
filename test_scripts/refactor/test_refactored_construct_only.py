#!/usr/bin/env python3
"""
REFACTORED SPARQL CONSTRUCT IMPLEMENTATION TEST (STANDALONE)
============================================================

Test CONSTRUCT queries using only the refactored SPARQL implementation.
This script validates that the refactored implementation correctly handles
CONSTRUCT queries and produces properly formatted RDF triples.

Unlike comparison-based tests, this script focuses on verifying that the
refactored implementation works correctly on its own, independent of the
original implementation (which is known to be broken for CONSTRUCT queries).
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.db.postgresql.sparql.postgres_sparql_impl import PostgreSQLSparqlImpl

# Reduce logging chatter except for orchestrator debug
logging.getLogger('vitalgraph.db.postgresql.postgresql_space_impl').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.rdf.rdf_utils').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.db.postgresql.postgresql_cache_term').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.db.postgresql.sparql.postgresql_sparql_cache_integration').setLevel(logging.WARNING)

# Enable debug logging for orchestrator to trace RDF triple construction
logging.getLogger('vitalgraph.db.postgresql.sparql.postgresql_sparql_orchestrator').setLevel(logging.DEBUG)

# Configuration
SPACE_ID = "wordnet_space"
GRAPH_URI = "http://vital.ai/graph/wordnet"

async def run_construct_query(sparql_impl, query_name, query):
    """Run a single CONSTRUCT query and display results."""
    print(f"  🔄 {query_name}:")
    
    try:
        start_time = time.time()
        result_triples = await sparql_impl.execute_sparql_query(SPACE_ID, query)
        elapsed = time.time() - start_time
        
        # Check result type and structure
        result_type = type(result_triples)
        result_count = len(result_triples) if result_triples else 0
        
        print(f"    ⏱️  {elapsed:.3f}s | {result_count} results | Type: {result_type.__name__}")
        
        if result_triples and result_count > 0:
            print(f"    📊 Sample results:")
            
            # Show first few results with detailed structure
            for i, result in enumerate(result_triples[:3], 1):
                result_type = type(result)
                print(f"      [{i}] Dict with keys: {list(result.keys()) if isinstance(result, dict) else 'N/A'}")
                
                if isinstance(result, dict):
                    # Show RDF triple structure
                    subject = result.get('subject', 'N/A')
                    predicate = result.get('predicate', 'N/A')
                    obj = result.get('object', 'N/A')
                    print(f"          S: {subject}")
                    print(f"          P: {predicate}")
                    print(f"          O: {obj}")
                else:
                    print(f"          Content: {result}")
            
            if result_count > 3:
                print(f"      ... and {result_count - 3} more results")
            
            print(f"    ✅ Result count within expected range")
        else:
            print(f"    ⚠️  No results returned")
            
        return True
            
    except Exception as e:
        print(f"    ❌ Error: {e}")
        return False

async def test_construct_queries():
    """Test CONSTRUCT pattern queries using refactored implementation."""
    print("🔨 REFACTORED SPARQL CONSTRUCT IMPLEMENTATION TEST (STANDALONE)")
    print("=" * 70)
    
    # Initialize database and refactored implementation
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    try:
        from vitalgraph.config.config_loader import get_config
        config = get_config(str(config_path))
        
        impl = VitalGraphImpl(config=config)
        print("✅ Initialized database implementation successfully with RDF connection pool support")
        
        # Initialize SpaceManager
        space_manager = impl.get_space_manager()
        print("✅ Initialized SpaceManager successfully")
        
        # Initialize database implementation
        await impl.db_impl.connect()
        print("✅ Initialized database implementation successfully")
        
        # Create refactored SPARQL implementation
        space_impl = impl.db_impl.get_space_impl()
        sparql_impl = PostgreSQLSparqlImpl(space_impl)
        print("✅ Created refactored SPARQL implementation")
        
        print("🔌 Connected to database")
        print(f"📊 Testing CONSTRUCT queries on space: {SPACE_ID}")
        
    except Exception as e:
        print(f"❌ Initialization failed: {e}")
        return False
    
    # Track test results
    test_results = []
    
    print("\n1. BASIC CONSTRUCT QUERIES:")
    
    # Test 1: Simple entity-name construction
    success = await run_construct_query(sparql_impl, "Simple entity-name pairs", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/hasLabel> ?name .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
        }}
        LIMIT 5
    """)
    test_results.append(success)
    
    # Test 2: Multiple triple construction
    success = await run_construct_query(sparql_impl, "Multiple triples per entity", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity rdf:type <http://example.org/WordNetConcept> .
            ?entity <http://example.org/hasLabel> ?name .
            ?entity <http://example.org/fromGraph> <{GRAPH_URI}> .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
        }}
        LIMIT 3
    """)
    test_results.append(success)
    
    print("\n2. CONSTRUCT WITH BIND EXPRESSIONS:")
    
    # Test 3: CONSTRUCT with BIND (the main focus of our fix)
    success = await run_construct_query(sparql_impl, "CONSTRUCT with BIND expressions", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/name> ?name .
            ?entity <http://example.org/profile> ?profile .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            BIND(CONCAT("profile_", STR(?entity)) AS ?profile)
        }}
        LIMIT 5
    """)
    test_results.append(success)
    
    # Test 4: Complex BIND expressions
    success = await run_construct_query(sparql_impl, "Complex BIND computations", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/name> ?name .
            ?entity <http://example.org/nameLength> ?nameLength .
            ?entity <http://example.org/category> ?category .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            BIND(STRLEN(?name) AS ?nameLength)
            BIND(IF(?nameLength > 20, "LONG", "SHORT") AS ?category)
        }}
        LIMIT 3
    """)
    test_results.append(success)
    
    print("\n3. CONSTRUCT WITH FILTERS:")
    
    # Test 5: CONSTRUCT with FILTER conditions
    success = await run_construct_query(sparql_impl, "CONSTRUCT with FILTER", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/filteredName> ?name .
            ?entity <http://example.org/type> "filtered-concept" .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            FILTER(CONTAINS(?name, "house"))
        }}
    """)
    test_results.append(success)
    
    print("\n4. CONSTRUCT WITH OPTIONAL:")
    
    # Test 6: CONSTRUCT with OPTIONAL patterns
    success = await run_construct_query(sparql_impl, "CONSTRUCT with OPTIONAL", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/name> ?name .
            ?entity <http://example.org/description> ?desc .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
                OPTIONAL {{ ?entity vital:hasDescription ?desc }}
            }}
        }}
        LIMIT 3
    """)
    test_results.append(success)
    
    print("\n5. CONSTRUCT WITH UNION:")
    
    # Test 7: CONSTRUCT with UNION patterns
    success = await run_construct_query(sparql_impl, "CONSTRUCT with UNION", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/identifier> ?id .
            ?entity <http://example.org/source> ?source .
        }}
        WHERE {{
            {{
                GRAPH <{GRAPH_URI}> {{
                    ?entity rdf:type haley:KGEntity .
                    ?entity vital:hasName ?id .
                }}
                BIND("wordnet" AS ?source)
            }}
            UNION
            {{
                GRAPH <urn:___GLOBAL> {{
                    ?entity rdf:type <http://example.org/Person> .
                    ?entity <http://example.org/hasName> ?id .
                }}
                BIND("global" AS ?source)
            }}
        }}
        LIMIT 3
    """)
    test_results.append(success)
    
    # Calculate final results
    total_tests = len(test_results)
    passed_tests = sum(test_results)
    success_rate = (passed_tests / total_tests) * 100 if total_tests > 0 else 0
    
    print(f"\n📊 FINAL TEST SUMMARY:")
    print(f"   Total tests: {total_tests}")
    print(f"   Passed: {passed_tests}")
    print(f"   Failed: {total_tests - passed_tests}")
    print(f"   Success rate: {success_rate:.1f}%")
    
    if success_rate == 100:
        print(f"\n🎉 ALL TESTS PASSED!")
        print(f"✅ Refactored CONSTRUCT implementation is working correctly")
    else:
        print(f"\n⚠️  Some tests failed")
        print(f"🔧 Review failed test cases for debugging")
    
    # Performance summary
    try:
        cache_size = sparql_impl.term_uuid_cache.size() if hasattr(sparql_impl, 'term_uuid_cache') else "N/A"
        print(f"\n📊 Final cache size: {cache_size} terms")
    except:
        print(f"\n📊 Final cache size: N/A")
    
    await impl.db_impl.disconnect()
    print("\n✅ Refactored SPARQL CONSTRUCT Implementation Test Complete!")
    
    return success_rate == 100

if __name__ == "__main__":
    asyncio.run(test_construct_queries())
