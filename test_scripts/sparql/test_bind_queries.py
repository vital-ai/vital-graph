#!/usr/bin/env python3
"""
BIND Query Tests
================

Test SPARQL BIND statement functionality in VitalGraph's PostgreSQL-backed SPARQL engine.
This file focuses specifically on BIND expression translation and execution.
"""

import sys
import asyncio
import time
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.db.postgresql.postgresql_sparql_impl import PostgreSQLSparqlImpl

SPACE_ID = "wordnet_space"
GRAPH_URI = "http://vital.ai/graph/wordnet"

async def run_bind_query(sparql_impl, query_name, query):
    """Run a single BIND query and display results."""
    print(f"  {query_name}:")
    
    try:
        start_time = time.time()
        result_graph = await sparql_impl.execute_sparql_query(SPACE_ID, query)
        elapsed = time.time() - start_time
        
        # Check if result is an RDFLib Graph
        if hasattr(result_graph, '__len__') and hasattr(result_graph, '__iter__'):
            # It's an RDFLib Graph
            triple_count = len(result_graph)
            print(f"    ⏱️  {elapsed:.3f}s | {triple_count} triples constructed")
            
            # Show first few triples from the graph
            triples_shown = 0
            for subject, predicate, obj in result_graph:
                if triples_shown >= 3:
                    break
                print(f"    [{triples_shown+1}] {subject} -> {predicate} -> {obj}")
                triples_shown += 1
                
            if triple_count > 3:
                print(f"    ... and {triple_count - 3} more triples")
        else:
            print(f"    ⏱️  {elapsed:.3f}s | No results or unexpected result type")
            
    except Exception as e:
        print(f"    ❌ Error: {e}")

async def test_bind_queries():
    """Test BIND statement functionality with various expressions."""
    print("🔧 BIND Query Tests")
    print("=" * 50)
    
    # Initialize
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    space_impl = impl.db_impl.get_space_impl()
    sparql_impl = PostgreSQLSparqlImpl(space_impl)
    
    print("✅ Connected | Testing BIND expressions")
    
    print("\n1. BASIC BIND EXPRESSIONS:")
    
    # Test 1: Simple CONCAT with STR
    await run_bind_query(sparql_impl, "CONCAT with STR function", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/profile> ?profile .
            ?entity <http://example.org/originalName> ?name .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            BIND(CONCAT("profile_", STR(?entity)) AS ?profile)
        }}
        LIMIT 3
    """)
    
    # Test 2: String length with STRLEN
    await run_bind_query(sparql_impl, "STRLEN function", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/name> ?name .
            ?entity <http://example.org/nameLength> ?length .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            BIND(STRLEN(?name) AS ?length)
        }}
        LIMIT 3
    """)
    
    # Test 3: Case conversion with UCASE/LCASE
    await run_bind_query(sparql_impl, "UCASE and LCASE functions", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/originalName> ?name .
            ?entity <http://example.org/upperName> ?upperName .
            ?entity <http://example.org/lowerName> ?lowerName .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            BIND(UCASE(?name) AS ?upperName)
            BIND(LCASE(?name) AS ?lowerName)
        }}
        LIMIT 2
    """)
    
    print("\n2. ADVANCED BIND EXPRESSIONS:")
    
    # Test 4: Hash functions (MD5 fallback for SHA1)
    await run_bind_query(sparql_impl, "Hash functions (SHA1/MD5)", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/name> ?name .
            ?entity <http://example.org/nameHash> ?nameHash .
            ?entity <http://example.org/nameMD5> ?nameMD5 .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            BIND(SHA1(?name) AS ?nameHash)
            BIND(MD5(?name) AS ?nameMD5)
        }}
        LIMIT 2
    """)
    
    # Test 5: SUBSTR function
    await run_bind_query(sparql_impl, "SUBSTR function", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/name> ?name .
            ?entity <http://example.org/namePrefix> ?prefix .
            ?entity <http://example.org/computedId> ?computedId .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            BIND(SUBSTR(?name, 1, 5) AS ?prefix)
            BIND(CONCAT("computed_", SUBSTR(STR(?entity), 50)) AS ?computedId)
        }}
        LIMIT 2
    """)
    
    print("\n3. CONDITIONAL BIND EXPRESSIONS:")
    
    # Test 6: IF function with conditions
    await run_bind_query(sparql_impl, "IF conditional function", """
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {
            ?person <http://example.org/name> ?name .
            ?person <http://example.org/age> ?age .
            ?person <http://example.org/ageGroup> ?ageGroup .
        }
        WHERE {
            GRAPH <urn:___GLOBAL> {
                ?person rdf:type <http://example.org/Person> .
                ?person <http://example.org/hasName> ?name .
                ?person <http://example.org/hasAge> ?age .
            }
            BIND(IF(?age < 30, "young", "mature") AS ?ageGroup)
        }
    """)
    
    # Test 7: Multiple BIND expressions in one query
    await run_bind_query(sparql_impl, "Multiple BIND expressions", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/name> ?name .
            ?entity <http://example.org/category> ?category .
            ?entity <http://example.org/shortName> ?shortName .
            ?entity <http://example.org/isShort> ?isShort .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            BIND("wordnet-concept" AS ?category)
            BIND(SUBSTR(?name, 1, 10) AS ?shortName)
            BIND(IF(STRLEN(?name) < 10, "yes", "no") AS ?isShort)
        }}
        LIMIT 2
    """)
    
    print("\n4. BIND ERROR HANDLING:")
    
    # Test 8: Test with unsupported functions
    await run_bind_query(sparql_impl, "Unsupported BIND functions", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/name> ?name .
            ?entity <http://example.org/uuid> ?uuid .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            BIND(UUID() AS ?uuid)
        }}
        LIMIT 1
    """)
    
    # Performance summary
    print(f"\n📊 Cache: {sparql_impl.term_uuid_cache.size()} terms")
    
    # 5. NESTED BIND EXPRESSIONS (using test data space)
    print("\n5. NESTED BIND EXPRESSIONS:")
    print("  ℹ️  Switching to space_test for nested BIND tests...")
    
    # Simple 2-level nesting: STRLEN(SUBSTR(...))
    print("  Simple nesting - STRLEN(SUBSTR(...)):")
    nested_query1 = """
    CONSTRUCT {
        ?entity <http://example.org/name> ?name .
        ?entity <http://example.org/shortLength> ?shortLength .
    }
    WHERE {
        GRAPH <http://vital.ai/graph/test> {
            ?entity <http://vital.ai/vital#hasName> ?name .
        }
        BIND(STRLEN(SUBSTR(?name, 1, 10)) AS ?shortLength)
    }
    LIMIT 2
    """
    
    try:
        import time
        start_time = time.time()
        result_graph = await sparql_impl.execute_sparql_query("space_test", nested_query1)
        elapsed = time.time() - start_time
        
        if hasattr(result_graph, '__len__') and hasattr(result_graph, '__iter__'):
            triple_count = len(result_graph)
            print(f"    ⏱️  {elapsed:.3f}s | {triple_count} triples constructed")
            
            triples_shown = 0
            for s, p, o in result_graph:
                if triples_shown >= 4:
                    break
                print(f"    [{triples_shown+1}] {s} -> {p} -> {o}")
                triples_shown += 1
                
            if triple_count > 4:
                print(f"    ... and {triple_count - 4} more triples")
        else:
            print(f"    ⏱️  {elapsed:.3f}s | Unexpected result type: {type(result_graph)}")
    except Exception as e:
        print(f"    ❌ Error: {e}")
    
    # Complex nesting: IF with nested condition and values
    print("  Complex nesting - IF(STRLEN(...) > 10, SUBSTR(...), UCASE(...)):")
    nested_query2 = """
    CONSTRUCT {
        ?entity <http://example.org/name> ?name .
        ?entity <http://example.org/processed> ?processed .
    }
    WHERE {
        GRAPH <http://vital.ai/graph/test> {
            ?entity <http://vital.ai/vital#hasName> ?name .
        }
        BIND(IF(STRLEN(?name) > 10, SUBSTR(?name, 1, 10), UCASE(?name)) AS ?processed)
    }
    LIMIT 2
    """
    
    try:
        start_time = time.time()
        result_graph = await sparql_impl.execute_sparql_query("space_test", nested_query2)
        elapsed = time.time() - start_time
        
        if hasattr(result_graph, '__len__') and hasattr(result_graph, '__iter__'):
            triple_count = len(result_graph)
            print(f"    ⏱️  {elapsed:.3f}s | {triple_count} triples constructed")
            
            triples_shown = 0
            for s, p, o in result_graph:
                if triples_shown >= 4:
                    break
                print(f"    [{triples_shown+1}] {s} -> {p} -> {o}")
                triples_shown += 1
                
            if triple_count > 4:
                print(f"    ... and {triple_count - 4} more triples")
        else:
            print(f"    ⏱️  {elapsed:.3f}s | Unexpected result type: {type(result_graph)}")
    except Exception as e:
        print(f"    ❌ Error: {e}")
    
    # Multi-level nesting: CONCAT with nested IF and SUBSTR
    print("  Multi-level nesting - CONCAT('Result: ', IF(STRLEN(...) < 5, 'SHORT', SUBSTR(...))):")    
    nested_query3 = """
    CONSTRUCT {
        ?entity <http://example.org/name> ?name .
        ?entity <http://example.org/result> ?result .
    }
    WHERE {
        GRAPH <http://vital.ai/graph/test> {
            ?entity <http://vital.ai/vital#hasName> ?name .
        }
        BIND(CONCAT("Result: ", IF(STRLEN(?name) < 5, "SHORT", SUBSTR(?name, 1, 3))) AS ?result)
    }
    LIMIT 2
    """
    
    try:
        start_time = time.time()
        result_graph = await sparql_impl.execute_sparql_query("space_test", nested_query3)
        elapsed = time.time() - start_time
        
        if hasattr(result_graph, '__len__') and hasattr(result_graph, '__iter__'):
            triple_count = len(result_graph)
            print(f"    ⏱️  {elapsed:.3f}s | {triple_count} triples constructed")
            
            triples_shown = 0
            for s, p, o in result_graph:
                if triples_shown >= 4:
                    break
                print(f"    [{triples_shown+1}] {s} -> {p} -> {o}")
                triples_shown += 1
                
            if triple_count > 4:
                print(f"    ... and {triple_count - 4} more triples")
        else:
            print(f"    ⏱️  {elapsed:.3f}s | Unexpected result type: {type(result_graph)}")
    except Exception as e:
        print(f"    ❌ Error: {e}")
    
    # Function composition chain: UCASE(SUBSTR(CONCAT(...)))
    print("  Function composition - UCASE(SUBSTR(CONCAT(...), 1, 8)):")
    nested_query4 = """
    CONSTRUCT {
        ?entity <http://example.org/name> ?name .
        ?entity <http://example.org/composed> ?composed .
    }
    WHERE {
        GRAPH <http://vital.ai/graph/test> {
            ?entity <http://vital.ai/vital#hasName> ?name .
        }
        BIND(UCASE(SUBSTR(CONCAT("PREFIX_", ?name), 1, 8)) AS ?composed)
    }
    LIMIT 2
    """
    
    try:
        start_time = time.time()
        result_graph = await sparql_impl.execute_sparql_query("space_test", nested_query4)
        elapsed = time.time() - start_time
        
        if hasattr(result_graph, '__len__') and hasattr(result_graph, '__iter__'):
            triple_count = len(result_graph)
            print(f"    ⏱️  {elapsed:.3f}s | {triple_count} triples constructed")
            
            triples_shown = 0
            for s, p, o in result_graph:
                if triples_shown >= 4:
                    break
                print(f"    [{triples_shown+1}] {s} -> {p} -> {o}")
                triples_shown += 1
                
            if triple_count > 4:
                print(f"    ... and {triple_count - 4} more triples")
        else:
            print(f"    ⏱️  {elapsed:.3f}s | Unexpected result type: {type(result_graph)}")
    except Exception as e:
        print(f"    ❌ Error: {e}")

    print("\n📊 Cache:", sparql_impl.term_cache.size(), "terms")
    
    print("\n✅ BIND Query Tests Complete!")
    print("💡 BIND expressions are now implemented with PostgreSQL SQL translation")
    print("🔗 Nested BIND function analysis complete - check results above")

if __name__ == "__main__":
    asyncio.run(test_bind_queries())
