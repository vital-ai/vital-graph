#!/usr/bin/env python3
"""
Debug RDF data loading in pyoxigraph via N-Quads from GraphObjects.
"""

import pyoxigraph as px
from ai_haley_kg_domain.model.KGEntity import KGEntity
from vitalgraph.utils.quad_format_utils import graphobjects_to_nquads

def test_nquads_loading():
    """Test N-Quads loading directly with pyoxigraph."""
    
    print("🧪 Testing N-Quads loading with pyoxigraph")
    print("=" * 60)
    
    # Create test GraphObject
    entity = KGEntity()
    entity.URI = "http://example.com/test/entity/customer1"
    entity.name = "Premium Customer Alpha"
    
    # Test 1: Load into default graph
    print("🔍 Test 1: N-Quads loading into default graph")
    try:
        store = px.Store()
        nquads_str = graphobjects_to_nquads([entity])
        print(f"N-Quads ({len(nquads_str)} bytes)")
        
        store.load(
            input=nquads_str,
            format=px.RdfFormat.N_QUADS,
            base_iri="http://example.com/"
        )
        
        count = len(list(store.quads_for_pattern(None, None, None, None)))
        print(f"✅ SUCCESS: Loaded {count} triples")
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
    
    # Test 2: Load into specific graph
    print("\n🔍 Test 2: N-Quads loading to specific graph")
    try:
        store2 = px.Store()
        target_graph = px.NamedNode("http://example.com/test-graph")
        graph_uri = "http://example.com/test-graph"
        
        nquads_str = graphobjects_to_nquads([entity], graph_uri=graph_uri)
        
        store2.load(
            input=nquads_str,
            format=px.RdfFormat.N_QUADS,
            base_iri="http://example.com/"
        )
        
        count = len(list(store2.quads_for_pattern(None, None, None, target_graph)))
        print(f"✅ SUCCESS: Loaded {count} triples to specific graph")
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
    
    # Test 3: Round-trip via quad_list
    print("\n🔍 Test 3: GraphObject round-trip via quads")
    try:
        from vitalgraph.utils.quad_format_utils import graphobjects_to_quad_list, quad_list_to_graphobjects
        
        quads = graphobjects_to_quad_list([entity])
        reconstructed = quad_list_to_graphobjects(quads)
        
        print(f"✅ SUCCESS: Round-trip produced {len(reconstructed)} objects")
        for obj in reconstructed:
            print(f"   Type: {type(obj).__name__}, URI: {obj.URI}, Name: {obj.name}")
        
    except Exception as e:
        print(f"❌ FAILED: {e}")

if __name__ == "__main__":
    test_nquads_loading()
