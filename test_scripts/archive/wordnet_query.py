from rdflib import URIRef
from sqlalchemy import URL
from vitalgraph.store.store import VitalGraphSQLStore
from vitalgraph.optimized_graph import OptimizedVitalGraph

PG_HOST     = "127.0.0.1"
PG_PORT     = 5432
PG_USER     = "postgres"
PG_PASSWORD = ""
PG_DATABASE = "vitalgraphdb"

# The WordNet graph name
GRAPH_NAME = "wordnet"


def main():
    # Build a fully-qualified VitalGraphSQLStore URL object for psycopg3
    db_url = URL.create(
        drivername="postgresql+psycopg",
        username=PG_USER,
        password=PG_PASSWORD or None,
        host=PG_HOST,
        port=PG_PORT,
        database=PG_DATABASE,
    )

    # Create store with "hardcoded" identifier (for table space kb_bec6803d52_*)
    store = VitalGraphSQLStore()  # defaults to "hardcoded" identifier
    store.open(db_url)
    
    # Use OptimizedVitalGraph with WordNet graph context URI
    graph_iri = URIRef(f"http://vital.ai/graph/{GRAPH_NAME}")
    g = OptimizedVitalGraph(store=store, identifier=graph_iri)
    print(f"Connected to WordNet graph '{GRAPH_NAME}' in PostgreSQL at {db_url}")

    # Check total triple count
    total_triples = len(g)
    print(f"Total triples in WordNet graph: {total_triples:,}")

    # Original complex SPARQL query for entities with 'happy' in name and their one-hop connections
    query_happy_entities = """
PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?entity ?entityName ?edge ?connectedEntity ?connectedName WHERE {
  ?entity a haley-ai-kg:KGEntity .
  ?entity vital-core:hasName ?entityName .
  FILTER(CONTAINS(LCASE(STR(?entityName)), "happy"))
  
  ?edge vital-core:vital__hasEdgeSource ?entity .
  ?edge vital-core:vital__hasEdgeDestination ?connectedEntity .
  
  ?connectedEntity vital-core:hasName ?connectedName .
}
ORDER BY ?entityName ?connectedName
LIMIT 20
"""

    # Fallback query: just find entities with 'happy' in descriptions (for comparison)
    query_happy_descriptions = """
PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>

SELECT ?entity ?entityName ?description WHERE {
  ?entity a haley-ai-kg:KGEntity .
  ?entity vital-core:hasName ?entityName .
  ?entity haley-ai-kg:vital__hasKGraphDescription ?description .
  FILTER(CONTAINS(LCASE(STR(?description)), "happy"))
}
ORDER BY ?entityName
LIMIT 10
"""

    import time
    
    # Test 1A: First, find entities with 'happy' in names (simple text search)
    print("\nTest 1A: Finding entities with 'happy' in names")
    
    simple_happy_query = """
    SELECT ?entity ?entityName WHERE {
      ?entity <http://vital.ai/ontology/vital-core#hasName> ?entityName .
      FILTER(CONTAINS(LCASE(STR(?entityName)), "happy"))
    }
    LIMIT 5
    """
    
    happy_entities = []
    start_time = time.time()
    try:
        results = g.query(simple_happy_query)
        end_time = time.time()
        elapsed = end_time - start_time
        
        for row in results:
            entity_uri = str(row['entity'])
            entity_name = str(row['entityName'])
            happy_entities.append(entity_uri)
            print(f"  Found: {entity_name}")
            print(f"  URI: {entity_uri}")
        
        print(f"✓ Found {len(happy_entities)} entities with 'happy' in names")
        print(f"Query time: {elapsed:.3f} seconds")
        
    except Exception as e:
        print(f"✗ Error in simple happy query: {e}")
    
    # Test 1B: Now check for edges using the specific URIs we found
    if happy_entities:
        print(f"\nTest 1B: Checking for edges from the first entity")
        first_entity = happy_entities[0]
        print(f"Checking edges for: {first_entity}")
        
        edge_query = f"""
        SELECT ?edge ?destination ?destName WHERE {{
          ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeSource> <{first_entity}> .
          ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeDestination> ?destination .
          OPTIONAL {{ ?destination <http://vital.ai/ontology/vital-core#hasName> ?destName . }}
        }}
        LIMIT 10
        """
        
        start_time = time.time()
        try:
            edge_results = list(g.query(edge_query))
            end_time = time.time()
            elapsed = end_time - start_time
            
            if edge_results:
                print(f"✓ Found {len(edge_results)} edges from this entity:")
                for i, row in enumerate(edge_results[:3]):
                    print(f"  Edge {i+1}: {row.get('edge', 'N/A')}")
                    print(f"    -> Destination: {row.get('destination', 'N/A')}")
                    print(f"    -> Name: {row.get('destName', 'N/A')}")
            else:
                print("✗ No edges found for this entity")
                
            print(f"Query time: {elapsed:.3f} seconds")
            
        except Exception as e:
            print(f"✗ Error in edge query: {e}")
        
        # Test 1C: Direct edge verification - check if ANY edges exist
        print(f"\nTest 1C: Direct edge verification (any edges in database)")
        
        direct_edge_query = """
        SELECT ?edge ?source ?dest WHERE {
          ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeSource> ?source .
          ?edge <http://vital.ai/ontology/vital-core#vital__hasEdgeDestination> ?dest .
        }
        LIMIT 5
        """
        
        start_time = time.time()
        try:
            direct_results = list(g.query(direct_edge_query))
            end_time = time.time()
            elapsed = end_time - start_time
            
            if direct_results:
                print(f"✓ Found {len(direct_results)} edges in database:")
                for i, row in enumerate(direct_results):
                    print(f"  Edge {i+1}: {row.get('edge', 'N/A')}")
                    print(f"    Source: {row.get('source', 'N/A')}")
                    print(f"    Dest: {row.get('dest', 'N/A')}")
            else:
                print("✗ No edges found in database at all")
                
            print(f"Query time: {elapsed:.3f} seconds")
            
        except Exception as e:
            print(f"✗ Error in direct edge query: {e}")
    
    # Test 1C: Original complex query for comparison
    print("\nTest 1C: Original complex query (for comparison)")
    
    start_time = time.time()
    try:
        results = g.query(query_happy_entities)
        end_time = time.time()
        elapsed = end_time - start_time
        
        result_count = 0
        for row in results:
            result_count += 1
            if result_count <= 5:  # Show first 5 connections
                print(f"\nConnection {result_count}:")
                print(f"  Entity: {row['entityName']}")
                print(f"  URI: {row['entity']}")
                print(f"  Edge: {row['edge']}")
                print(f"  Connected to: {row['connectedName']}")
                print(f"  Connected URI: {row['connectedEntity']}")
        
        if result_count == 0:
            print("No connections found for entities with 'happy' in their names.")
            print("This might indicate that the entities don't have outgoing edges in the data.")
        else:
            print(f"\n✓ Found {result_count} connections from entities with 'happy' in names")
        
        print(f"Query time: {elapsed:.3f} seconds")
        
    except Exception as e:
        print(f"✗ Error in edge traversal query: {e}")
        print("This complex query may not be optimized by our text search interception.")
        print("Let's try a simpler fallback query...")
    
    # Test 2: Fallback - Simple search for 'happy' in descriptions
    print("\nTest 2: Entities with 'happy' in descriptions (fallback)")
    
    start_time = time.time()
    try:
        desc_results = g.query(query_happy_descriptions)
        end_time = time.time()
        elapsed = end_time - start_time
        
        desc_count = 0
        for row in desc_results:
            desc_count += 1
            if desc_count <= 5:  # Show first 5 results
                description = str(row['description'])[:100] + "..." if len(str(row['description'])) > 100 else str(row['description'])
                print(f"Result {desc_count}: {row['entityName']} - {description}")
        
        print(f"\n✓ Found {desc_count} entities with 'happy' in descriptions")
        print(f"Query time: {elapsed:.3f} seconds")
        
    except Exception as e:
        print(f"✗ Error in descriptions query: {e}")
    
    # End of main query tests

    # Let's also try some basic queries to explore the data structure
    print("\nExploring data structure with basic queries...")
    
    # Query for distinct classes
    basic_query1 = """
    SELECT DISTINCT ?type WHERE {
      ?s a ?type .
    }
    LIMIT 20
    """
    
    print("\nDistinct classes in the data:")
    try:
        for row in g.query(basic_query1):
            print(f"  {row.type}")
    except Exception as e:
        print(f"Error querying classes: {e}")
    
    # Query for distinct predicates
    basic_query2 = """
    SELECT DISTINCT ?predicate WHERE {
      ?s ?predicate ?o .
    }
    LIMIT 20
    """
    
    print("\nDistinct predicates in the data:")
    try:
        for row in g.query(basic_query2):
            print(f"  {row.predicate}")
    except Exception as e:
        print(f"Error querying predicates: {e}")

    # Sample triples
    basic_query3 = """
    SELECT ?s ?p ?o WHERE {
      ?s ?p ?o .
    }
    LIMIT 10
    """
    
    print("\nSample triples:")
    try:
        for row in g.query(basic_query3):
            print(f"  {row.s} {row.p} {row.o}")
    except Exception as e:
        print(f"Error querying sample triples: {e}")

    g.close()


if __name__ == "__main__":
    main()
