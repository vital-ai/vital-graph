#!/usr/bin/env python3
"""
CONSTRUCT Query Test Script
===========================

Test CONSTRUCT queries with WordNet data to validate CONSTRUCT implementation.
These queries will be used to test the CONSTRUCT functionality once implemented.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Set up DEBUG logging to see SQL queries
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s - %(name)s - %(message)s')

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

async def run_construct_query(sparql_impl, query_name, query):
    """Run a single CONSTRUCT query and display results."""
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

async def test_construct_queries():
    """Test CONSTRUCT pattern queries."""
    print("🔨 CONSTRUCT Query Tests")
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
    print("⚠️  Note: CONSTRUCT queries will fail until implementation is complete")
    
    # Test queries focused on CONSTRUCT patterns
    print("\n1. SIMPLE CONSTRUCT QUERIES:")
    
    await run_construct_query(sparql_impl, "Construct entity-name pairs", f"""
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
    
    await run_construct_query(sparql_impl, "Construct simplified entity types", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity rdf:type <http://example.org/WordNetConcept> .
            ?entity <http://example.org/fromGraph> <{GRAPH_URI}> .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
            }}
        }}
        LIMIT 10
    """)
    
    print("\n2. CONSTRUCT WITH FILTERS:")
    
    await run_construct_query(sparql_impl, "Construct entities with 'happy' in name", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/isHappyRelated> true .
            ?entity <http://example.org/originalName> ?name .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
                FILTER(CONTAINS(?name, "happy"))
            }}
        }}
    """)
    
    await run_construct_query(sparql_impl, "Construct short-named entities", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/hasShortName> ?name .
            ?entity <http://example.org/nameLength> ?length .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
                FILTER(STRLEN(?name) < 10)
            }}
        }}
        LIMIT 5
    """)
    
    print("\n3. CONSTRUCT WITH RELATIONSHIPS:")
    
    await run_construct_query(sparql_impl, "Construct entity connections", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity1 <http://example.org/relatedTo> ?entity2 .
            ?entity1 <http://example.org/relationshipType> ?edge .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity1 rdf:type haley:KGEntity .
                ?entity2 rdf:type haley:KGEntity .
                ?edge vital:vital__hasEdgeSource ?entity1 .
                ?edge vital:vital__hasEdgeDestination ?entity2 .
            }}
        }}
    """)
    
    await run_construct_query(sparql_impl, "Construct named entity relationships", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity1 <http://example.org/connectedTo> ?entity2 .
            ?entity1 <http://example.org/sourceName> ?name1 .
            ?entity2 <http://example.org/targetName> ?name2 .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity1 rdf:type haley:KGEntity .
                ?entity1 vital:vital__hasName ?name1 .
                ?edge vital:vital__hasEdgeSource ?entity1 .
                ?edge vital:vital__hasEdgeDestination ?entity2 .
                ?entity2 rdf:type haley:KGEntity .
                ?entity2 vital:vital__hasName ?name2 .
                FILTER(CONTAINS(?name1, "happy"))
            }}
        }}
    """)
    
    print("\n4. CONSTRUCT WITH GLOBAL GRAPH DATA:")
    
    await run_construct_query(sparql_impl, "Construct person profiles", """
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {
            ?person <http://example.org/profile> ?profile .
            ?profile <http://example.org/fullName> ?name .
            ?profile <http://example.org/ageGroup> ?ageGroup .
        }
        WHERE {
            GRAPH <urn:___GLOBAL> {
                ?person rdf:type <http://example.org/Person> .
                ?person <http://example.org/hasName> ?name .
                ?person <http://example.org/hasAge> ?age .
            }
            BIND(CONCAT("profile_", STR(?person)) AS ?profile)
            BIND(IF(?age < 30, "young", "mature") AS ?ageGroup)
        }
    """)
    
    await run_construct_query(sparql_impl, "Construct social network", """
        CONSTRUCT {
            ?person1 <http://example.org/friend> ?person2 .
            ?person1 <http://example.org/friendName> ?name2 .
        }
        WHERE {
            GRAPH <urn:___GLOBAL> {
                ?person1 <http://example.org/knows> ?person2 .
                ?person2 <http://example.org/hasName> ?name2 .
            }
        }
    """)
    
    print("\n5. COMPLEX CONSTRUCT PATTERNS:")
    
    await run_construct_query(sparql_impl, "Construct multi-graph summary", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            <http://example.org/summary> <http://example.org/hasWordNetEntity> ?entity .
            <http://example.org/summary> <http://example.org/hasPerson> ?person .
            ?entity <http://example.org/inGraph> <{GRAPH_URI}> .
            ?person <http://example.org/inGraph> <urn:___GLOBAL> .
        }}
        WHERE {{
            {{
                GRAPH <{GRAPH_URI}> {{
                    ?entity rdf:type haley:KGEntity .
                }}
            }}
            UNION
            {{
                GRAPH <urn:___GLOBAL> {{
                    ?person rdf:type <http://example.org/Person> .
                }}
            }}
        }}
        LIMIT 5
    """)
    
    await run_construct_query(sparql_impl, "Construct with computed values", f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity <http://example.org/computedId> ?computedId .
            ?entity <http://example.org/nameHash> ?nameHash .
            ?entity <http://example.org/category> "wordnet-concept" .
        }}
        WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?entity rdf:type haley:KGEntity .
                ?entity vital:hasName ?name .
            }}
            BIND(CONCAT("computed_", SUBSTR(STR(?entity), 50)) AS ?computedId)
            BIND(SHA1(?name) AS ?nameHash)
        }}
        LIMIT 3
    """)
    
    # Performance summary
    print(f"\n📊 Cache: {sparql_impl.term_cache.size()} terms")
    
    await impl.db_impl.disconnect()
    print("\n✅ CONSTRUCT Query Tests Complete!")

if __name__ == "__main__":
    asyncio.run(test_construct_queries())
