#!/usr/bin/env python3

"""
Test the conservative optimization fix by temporarily patching the method
to see if complex SPARQL queries start working.
"""

import logging
import time
from rdflib import Graph, URIRef, RDF, Literal
from vitalgraph.store.store import VitalGraphSQLStore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def patch_conservative_optimization(store):
    """Temporarily patch the store with conservative optimization logic"""
    
    def conservative_can_use_single_table_optimization(self, triple, context=None):
        """Conservative single-table optimization that preserves multi-table joins"""
        subject, predicate, obj = triple
        
        # Be more conservative with single table optimization to avoid breaking multi-table joins
        # Only use single table optimization for very specific, safe cases
        
        if predicate and not hasattr(predicate, 'compiledExpr'):  # Not REGEXTerm
            # RDF.type queries can safely use type table only
            if predicate == RDF.type:
                return True  # Use type table only
                
            # Literal objects with known literal predicates can use literal table only
            elif isinstance(obj, Literal) and self._is_literal_predicate(predicate):
                return True  # Use literal table only for confirmed literal predicates
                
            # URI objects with known non-literal predicates can use asserted table only
            elif isinstance(obj, URIRef) and not self._is_literal_predicate(predicate):
                return True  # Use asserted table only for confirmed non-literal predicates
        
        # Handle type exploration patterns: ?s a ?type
        elif predicate == RDF.type and obj is None:
            return True  # Use type table for type exploration
        
        # For all other cases, especially when obj is None (unknown variables),
        # fall back to multi-table logic to ensure proper joins
        return False
    
    # Patch the method
    store._can_use_single_table_optimization = conservative_can_use_single_table_optimization.__get__(store, VitalGraphSQLStore)
    print("✅ Applied conservative optimization patch")

def test_conservative_fix():
    """Test if the conservative optimization fix resolves complex SPARQL queries"""
    print("=== Testing Conservative Optimization Fix ===")
    
    # Create store and graph
    store = VitalGraphSQLStore(identifier="hardcoded")
    graph_iri = URIRef("http://vital.ai/graph/wordnet")
    g = Graph(store=store, identifier=graph_iri)
    
    try:
        # Open the store with database connection
        db_url = "postgresql+psycopg://postgres@127.0.0.1:5432/vitalgraphdb"
        store.open(db_url, create=False)
        print("✅ Database connection established")
        
        # Apply the conservative optimization patch
        patch_conservative_optimization(store)
        
        # Test 1: Simple query (should still work)
        print("\n🔍 Test 1: Simple query (baseline)")
        simple_query = """
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        
        SELECT ?entity ?name
        WHERE {
            ?entity a haley-ai-kg:KGEntity .
            ?entity vital-core:hasName ?name
        }
        LIMIT 3
        """
        
        start_time = time.time()
        simple_results = list(g.query(simple_query))
        simple_time = time.time() - start_time
        
        print(f"📊 Simple query: {len(simple_results)} results ({simple_time:.3f}s)")
        
        if simple_results:
            print("✅ Simple query works")
        else:
            print("❌ Simple query broken - patch may have issues")
            return
            
        # Test 2: Complex multi-table join query (the main test)
        print("\n🔍 Test 2: Complex multi-table join query")
        complex_query = """
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
        complex_results = list(g.query(complex_query))
        complex_time = time.time() - start_time
        
        print(f"📊 Complex query: {len(complex_results)} results ({complex_time:.3f}s)")
        
        if complex_results:
            print("🎉 SUCCESS! Complex query now works with conservative optimization!")
            print("\n📋 Sample results:")
            for i, (entity, entity_name, related_entity, related_name, edge_type) in enumerate(complex_results[:2]):
                print(f"  {i+1}. Entity: {entity}")
                print(f"     Name: {entity_name}")
                print(f"     Related: {related_entity}")
                print(f"     Related Name: {related_name}")
                print(f"     Edge Type: {edge_type}")
                print()
        else:
            print("❌ Complex query still returns 0 results")
            
        # Test 3: Text search query (should still work)
        print("\n🔍 Test 3: Text search query")
        text_query = """
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>
        
        SELECT ?entity ?name
        WHERE {
            ?entity a haley-ai-kg:KGEntity .
            ?entity vital-core:hasName ?name .
            FILTER(CONTAINS(?name, "able"))
        }
        LIMIT 3
        """
        
        start_time = time.time()
        text_results = list(g.query(text_query))
        text_time = time.time() - start_time
        
        print(f"📊 Text search query: {len(text_results)} results ({text_time:.3f}s)")
        
        if text_results:
            print("✅ Text search still works")
        else:
            print("❌ Text search broken")
            
        print(f"\n📋 FINAL RESULTS:")
        if len(complex_results) > 0:
            print("🎯 FIX SUCCESSFUL!")
            print("✅ Conservative optimization restores multi-table joins")
            print("✅ Complex SPARQL queries now work correctly")
            print("✅ Simple queries still work")
            print("🔧 Ready to apply this fix to the actual codebase")
        else:
            print("❌ Fix not sufficient - need further investigation")
            
    except Exception as e:
        print(f"❌ Error during test: {e}")
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
    test_conservative_fix()
    print("\n=== Conservative optimization fix test completed ===")
