#!/usr/bin/env python3

import logging
import time
from rdflib import Graph, URIRef
from vitalgraph.store.store import VitalGraphSQLStore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def debug_wordnet_query_step_by_step():
    """Debug the WordNet complex query step by step to find where it fails"""
    print("=== Debugging WordNet Query Step by Step ===")
    
    # Create store and graph
    store = VitalGraphSQLStore(identifier="hardcoded")
    graph_iri = URIRef("http://vital.ai/graph/wordnet")
    g = Graph(store=store, identifier=graph_iri)
    
    try:
        # Open the store with database connection
        db_url = "postgresql+psycopg://postgres@127.0.0.1:5432/vitalgraphdb"
        store.open(db_url, create=False)
        print("✅ Database connection established")
        
        # Step 1: Test each component of the complex query individually
        print("\n🔍 Step 1: Test individual query components")
        
        # Component 1: Find KGEntity instances
        component1_query = """
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        
        SELECT ?entity
        WHERE {
            ?entity a haley-ai-kg:KGEntity
        }
        LIMIT 5
        """
        
        start_time = time.time()
        comp1_results = list(g.query(component1_query))
        comp1_time = time.time() - start_time
        
        print(f"📊 Component 1 (KGEntity instances): {len(comp1_results)} results ({comp1_time:.3f}s)")
        if comp1_results:
            for i, (entity,) in enumerate(comp1_results[:3]):
                print(f"  {i+1}. {entity}")
        else:
            print("❌ No KGEntity instances found")
            return
            
        # Component 2: Find entities with names
        component2_query = """
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        
        SELECT ?entity ?name
        WHERE {
            ?entity a haley-ai-kg:KGEntity .
            ?entity vital-core:hasName ?name
        }
        LIMIT 5
        """
        
        start_time = time.time()
        comp2_results = list(g.query(component2_query))
        comp2_time = time.time() - start_time
        
        print(f"📊 Component 2 (Entities with names): {len(comp2_results)} results ({comp2_time:.3f}s)")
        if comp2_results:
            for i, (entity, name) in enumerate(comp2_results[:3]):
                print(f"  {i+1}. {entity}: {name}")
        else:
            print("❌ No entities with names found")
            return
            
        # Component 3: Find edges
        component3_query = """
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT ?edge ?source ?dest
        WHERE {
            ?edge vital-core:vital__hasEdgeSource ?source .
            ?edge vital-core:vital__hasEdgeDestination ?dest
        }
        LIMIT 5
        """
        
        start_time = time.time()
        comp3_results = list(g.query(component3_query))
        comp3_time = time.time() - start_time
        
        print(f"📊 Component 3 (Edges): {len(comp3_results)} results ({comp3_time:.3f}s)")
        if comp3_results:
            for i, (edge, source, dest) in enumerate(comp3_results[:3]):
                print(f"  {i+1}. {edge}: {source} -> {dest}")
        else:
            print("❌ No edges found")
            return
            
        # Component 4: Find edge types
        component4_query = """
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        
        SELECT ?edge ?edgeType
        WHERE {
            ?edge haley-ai-kg:vital__hasKGRelationType ?edgeType
        }
        LIMIT 5
        """
        
        start_time = time.time()
        comp4_results = list(g.query(component4_query))
        comp4_time = time.time() - start_time
        
        print(f"📊 Component 4 (Edge types): {len(comp4_results)} results ({comp4_time:.3f}s)")
        if comp4_results:
            for i, (edge, edge_type) in enumerate(comp4_results[:3]):
                print(f"  {i+1}. {edge}: {edge_type}")
        else:
            print("❌ No edge types found")
            return
            
        # Step 2: Try combining components progressively
        print("\n🔍 Step 2: Progressive combination of components")
        
        # Combination 1: Entity + Name
        combo1_query = """
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        
        SELECT ?entity ?entityName
        WHERE {
            ?entity a haley-ai-kg:KGEntity .
            ?entity vital-core:hasName ?entityName
        }
        LIMIT 5
        """
        
        start_time = time.time()
        combo1_results = list(g.query(combo1_query))
        combo1_time = time.time() - start_time
        
        print(f"📊 Combo 1 (Entity + Name): {len(combo1_results)} results ({combo1_time:.3f}s)")
        
        # Combination 2: Entity + Edge
        combo2_query = """
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        
        SELECT ?entity ?edge ?relatedEntity
        WHERE {
            ?entity a haley-ai-kg:KGEntity .
            ?edge vital-core:vital__hasEdgeSource ?entity .
            ?edge vital-core:vital__hasEdgeDestination ?relatedEntity
        }
        LIMIT 5
        """
        
        start_time = time.time()
        combo2_results = list(g.query(combo2_query))
        combo2_time = time.time() - start_time
        
        print(f"📊 Combo 2 (Entity + Edge): {len(combo2_results)} results ({combo2_time:.3f}s)")
        
        # Combination 3: Full join without filter
        combo3_query = """
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        
        SELECT ?entity ?entityName ?relatedEntity ?relatedName ?edgeType
        WHERE {
            ?entity a haley-ai-kg:KGEntity .
            ?entity vital-core:hasName ?entityName .
            
            ?edge vital-core:vital__hasEdgeSource ?entity .
            ?edge vital-core:vital__hasEdgeDestination ?relatedEntity .
            ?edge haley-ai-kg:vital__hasKGRelationType ?edgeType .
            
            ?relatedEntity a haley-ai-kg:KGEntity .
            ?relatedEntity vital-core:hasName ?relatedName
        }
        LIMIT 5
        """
        
        start_time = time.time()
        combo3_results = list(g.query(combo3_query))
        combo3_time = time.time() - start_time
        
        print(f"📊 Combo 3 (Full join without filter): {len(combo3_results)} results ({combo3_time:.3f}s)")
        
        if combo3_results:
            print("✅ SUCCESS! Full join works. Sample results:")
            for i, (entity, entity_name, related_entity, related_name, edge_type) in enumerate(combo3_results[:3]):
                print(f"  {i+1}. Entity: {entity}")
                print(f"     Name: {entity_name}")
                print(f"     Related: {related_entity}")
                print(f"     Related Name: {related_name}")
                print(f"     Edge Type: {edge_type}")
                print()
        else:
            print("❌ Full join failed - this is the problem!")
            
        # Step 3: Test the filter specifically
        print("\n🔍 Step 3: Test the filter condition")
        
        if combo3_results:
            # Test filter with actual data
            sample_edge_type = combo3_results[0][4]  # Get first edge type
            print(f"Testing filter with sample edge type: {sample_edge_type}")
            
            filter_test_query = f"""
            PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
            PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
            
            SELECT ?entity ?entityName ?relatedEntity ?relatedName ?edgeType
            WHERE {{
                ?entity a haley-ai-kg:KGEntity .
                ?entity vital-core:hasName ?entityName .
                
                ?edge vital-core:vital__hasEdgeSource ?entity .
                ?edge vital-core:vital__hasEdgeDestination ?relatedEntity .
                ?edge haley-ai-kg:vital__hasKGRelationType ?edgeType .
                
                ?relatedEntity a haley-ai-kg:KGEntity .
                ?relatedEntity vital-core:hasName ?relatedName .
                
                FILTER(CONTAINS(STR(?edgeType), "Wordnet"))
            }}
            LIMIT 5
            """
            
            start_time = time.time()
            filter_results = list(g.query(filter_test_query))
            filter_time = time.time() - start_time
            
            print(f"📊 Filter test: {len(filter_results)} results ({filter_time:.3f}s)")
            
            if filter_results:
                print("✅ Filter works!")
                for i, (entity, entity_name, related_entity, related_name, edge_type) in enumerate(filter_results[:3]):
                    print(f"  {i+1}. Edge Type: {edge_type}")
            else:
                print("❌ Filter eliminates all results - this is the issue!")
                print(f"Sample edge types to check filter logic:")
                for i, (_, _, _, _, edge_type) in enumerate(combo3_results[:5]):
                    contains_wordnet = "Wordnet" in str(edge_type)
                    print(f"  {i+1}. {edge_type} -> Contains 'Wordnet': {contains_wordnet}")
                    
        print(f"\n📋 DIAGNOSTIC SUMMARY:")
        print(f"- KGEntity instances: {len(comp1_results)}")
        print(f"- Entities with names: {len(comp2_results)}")
        print(f"- Edges: {len(comp3_results)}")
        print(f"- Edge types: {len(comp4_results)}")
        print(f"- Entity + Name combo: {len(combo1_results)}")
        print(f"- Entity + Edge combo: {len(combo2_results)}")
        print(f"- Full join (no filter): {len(combo3_results)}")
        if 'filter_results' in locals():
            print(f"- Full join (with filter): {len(filter_results)}")
            
    except Exception as e:
        print(f"❌ Error during debugging: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # Clean up
        try:
            store.close()
            print("🔒 Database connection closed")
        except:
            pass

if __name__ == "__main__":
    debug_wordnet_query_step_by_step()
    print("\n=== Step-by-step WordNet query debugging completed ===")
