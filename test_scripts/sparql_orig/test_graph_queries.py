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
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.db.postgresql.postgresql_sparql_impl import PostgreSQLSparqlImpl

# Reduce logging chatter
logging.getLogger('vitalgraph.db.postgresql.postgresql_space_impl').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.rdf.rdf_utils').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.db.postgresql.postgresql_cache_term').setLevel(logging.WARNING)

# Configuration
SPACE_ID = "wordnet_space"
GRAPH_URI = "http://vital.ai/graph/wordnet"

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
        
        # Show first 2 results
        for i, result in enumerate(results[:2]):
            print(f"    [{i+1}] {dict(result)}")
        if len(results) > 2:
            print(f"    ... +{len(results) - 2} more")
            
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

async def test_graph_queries():
    """Test GRAPH pattern queries."""
    print("🧪 GRAPH Query Tests")
    print("=" * 50)
    
    # Initialize
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    space_impl = impl.db_impl.get_space_impl()
    sparql_impl = PostgreSQLSparqlImpl(space_impl)
    
    print(f"✅ Connected | Graph: {GRAPH_URI}")
    
    # Test queries focused on GRAPH patterns
    print("\n1. NAMED GRAPH QUERIES:")
    
    await run_query(sparql_impl, "Count entities in WordNet graph", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT (COUNT(?entity) AS ?count) WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
            }}
        }}
    """)
    
    await run_query(sparql_impl, "Entities with names in WordNet graph", f"""
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
    
    await run_query(sparql_impl, "Non-existent graph (should return 0)", """
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT ?entity WHERE {
            GRAPH <http://example.com/nonexistent> {
                ?entity rdf:type haley:KGEntity .
            }
        }
    """)
    
    print("\n2. VARIABLE GRAPH QUERIES:")
    
    await run_query(sparql_impl, "Count entities by graph", """
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT ?g (COUNT(?entity) AS ?count) WHERE {
            GRAPH ?g {
                ?entity rdf:type haley:KGEntity .
            }
        }
        GROUP BY ?g
    """)
    
    await run_query(sparql_impl, "Variable graph with filtered entities", """
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
    
    print("\n3. GLOBAL GRAPH QUERIES:")
    
    await run_query(sparql_impl, "Query global graph directly", """
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT ?person ?name ?age WHERE {
            GRAPH <urn:___GLOBAL> {
                ?person rdf:type <http://example.org/Person> .
                ?person <http://example.org/hasName> ?name .
                ?person <http://example.org/hasAge> ?age .
            }
        }
    """)
    
    await run_query(sparql_impl, "Global graph relationships", """
        SELECT ?person1 ?name1 ?person2 ?name2 WHERE {
            GRAPH <urn:___GLOBAL> {
                ?person1 <http://example.org/knows> ?person2 .
                ?person1 <http://example.org/hasName> ?name1 .
                ?person2 <http://example.org/hasName> ?name2 .
            }
        }
    """)
    
    await run_query(sparql_impl, "Global test entities", """
        SELECT ?entity ?value WHERE {
            GRAPH <urn:___GLOBAL> {
                ?entity <http://example.org/hasProperty> ?value .
            }
        }
    """)
    
    print("\n4. DEFAULT GRAPH UNION QUERIES:")
    
    await run_query(sparql_impl, "Default graph union - should include both named and global data", """
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
    
    await run_query(sparql_impl, "Count all entities across all graphs (union)", """
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
    
    print("\n5. COMPLEX GRAPH PATTERNS:")
    
    await run_query(sparql_impl, "Graph with connected entities", f"""
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
    
    # Performance summary
    print(f"\n📊 Cache: {sparql_impl.term_uuid_cache.size()} terms")
    
    await impl.db_impl.disconnect()
    print("\n✅ GRAPH Query Tests Complete!")

if __name__ == "__main__":
    asyncio.run(test_graph_queries())
