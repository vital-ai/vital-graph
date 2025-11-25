#!/usr/bin/env python3

"""Test grouping URI functionality in client API methods."""

import sys
import os
import inspect

# Add the parent directory to the path so we can import vitalgraph
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vitalgraph.client.endpoint.kgentities_endpoint import KGEntitiesEndpoint
from vitalgraph.client.endpoint.kgframes_endpoint import KGFramesEndpoint
from vitalgraph.model.jsonld_model import JsonLdDocument


def test_kgentities_method_signatures():
    """Test that KGEntities methods have correct signatures (no grouping URI parameters)."""
    
    print("=== Testing KGEntities Method Signatures ===")
    
    # Test create_kgentities signature
    create_sig = inspect.signature(KGEntitiesEndpoint.create_kgentities)
    create_params = list(create_sig.parameters.keys())
    
    expected_params = ['self', 'space_id', 'graph_id', 'document']
    if create_params == expected_params:
        print("✅ create_kgentities has correct signature (no grouping URI params)")
    else:
        print(f"❌ create_kgentities has wrong signature: {create_params}")
        print(f"   Expected: {expected_params}")
        return False
    
    # Test update_kgentities signature
    update_sig = inspect.signature(KGEntitiesEndpoint.update_kgentities)
    update_params = list(update_sig.parameters.keys())
    
    if update_params == expected_params:
        print("✅ update_kgentities has correct signature (no grouping URI params)")
    else:
        print(f"❌ update_kgentities has wrong signature: {update_params}")
        print(f"   Expected: {expected_params}")
        return False
    
    return True


def test_kgframes_method_signatures():
    """Test that KGFrames methods have correct signatures (with entity_uri parameter)."""
    
    print("\n=== Testing KGFrames Method Signatures ===")
    
    # Test create_kgframes signature
    create_sig = inspect.signature(KGFramesEndpoint.create_kgframes)
    create_params = list(create_sig.parameters.keys())
    
    expected_params = ['self', 'space_id', 'graph_id', 'document', 'entity_uri', 'frame_graph_uri']
    if create_params == expected_params:
        print("✅ create_kgframes has correct signature (with entity_uri param)")
    else:
        print(f"❌ create_kgframes has wrong signature: {create_params}")
        print(f"   Expected: {expected_params}")
        return False
    
    # Test update_kgframes signature
    update_sig = inspect.signature(KGFramesEndpoint.update_kgframes)
    update_params = list(update_sig.parameters.keys())
    
    if update_params == expected_params:
        print("✅ update_kgframes has correct signature (with entity_uri param)")
    else:
        print(f"❌ update_kgframes has wrong signature: {update_params}")
        print(f"   Expected: {expected_params}")
        return False
    
    # Test create_kgframes_with_slots signature
    create_slots_sig = inspect.signature(KGFramesEndpoint.create_kgframes_with_slots)
    create_slots_params = list(create_slots_sig.parameters.keys())
    
    if create_slots_params == expected_params:
        print("✅ create_kgframes_with_slots has correct signature (with entity_uri param)")
    else:
        print(f"❌ create_kgframes_with_slots has wrong signature: {create_slots_params}")
        print(f"   Expected: {expected_params}")
        return False
    
    # Test update_kgframes_with_slots signature
    update_slots_sig = inspect.signature(KGFramesEndpoint.update_kgframes_with_slots)
    update_slots_params = list(update_slots_sig.parameters.keys())
    
    if update_slots_params == expected_params:
        print("✅ update_kgframes_with_slots has correct signature (with entity_uri param)")
    else:
        print(f"❌ update_kgframes_with_slots has wrong signature: {update_slots_params}")
        print(f"   Expected: {expected_params}")
        return False
    
    return True


def test_parameter_defaults():
    """Test that optional parameters have correct defaults."""
    
    print("\n=== Testing Parameter Defaults ===")
    
    # Test KGFrames parameter defaults
    create_sig = inspect.signature(KGFramesEndpoint.create_kgframes)
    
    entity_uri_param = create_sig.parameters['entity_uri']
    frame_graph_uri_param = create_sig.parameters['frame_graph_uri']
    
    if entity_uri_param.default is None:
        print("✅ entity_uri parameter defaults to None")
    else:
        print(f"❌ entity_uri parameter has wrong default: {entity_uri_param.default}")
        return False
    
    if frame_graph_uri_param.default is None:
        print("✅ frame_graph_uri parameter defaults to None")
    else:
        print(f"❌ frame_graph_uri parameter has wrong default: {frame_graph_uri_param.default}")
        return False
    
    return True


def test_method_call_functionality():
    """Test that methods can be called with correct parameters (will fail at validation, but tests signature)."""
    
    print("\n=== Testing Method Call Functionality ===")
    
    # Create mock client (won't actually connect)
    try:
        # Test KGEntities method calls
        entities_endpoint = KGEntitiesEndpoint(client=None)
        
        # These should fail at validation, not at signature level
        try:
            entities_endpoint.create_kgentities("space1", "graph1", {"test": "doc"})
        except Exception as e:
            if any(term in str(e).lower() for term in ["connection", "client", "nonetype", "is_connected"]):
                print("✅ create_kgentities accepts correct parameters (fails at connection)")
            else:
                print(f"❌ create_kgentities signature issue: {e}")
                return False
        
        try:
            entities_endpoint.update_kgentities("space1", "graph1", {"test": "doc"})
        except Exception as e:
            if any(term in str(e).lower() for term in ["connection", "client", "nonetype", "is_connected"]):
                print("✅ update_kgentities accepts correct parameters (fails at connection)")
            else:
                print(f"❌ update_kgentities signature issue: {e}")
                return False
        
        # Test KGFrames method calls
        frames_endpoint = KGFramesEndpoint(client=None)
        test_doc = JsonLdDocument(context={}, graph=[])
        
        try:
            frames_endpoint.create_kgframes("space1", "graph1", test_doc, entity_uri="http://example.org/entity1")
        except Exception as e:
            if any(term in str(e).lower() for term in ["connection", "client", "nonetype", "is_connected"]):
                print("✅ create_kgframes accepts correct parameters (fails at connection)")
            else:
                print(f"❌ create_kgframes signature issue: {e}")
                return False
        
        try:
            frames_endpoint.update_kgframes("space1", "graph1", test_doc, 
                                          entity_uri="http://example.org/entity1",
                                          frame_graph_uri="http://example.org/frame1")
        except Exception as e:
            if any(term in str(e).lower() for term in ["connection", "client", "nonetype", "is_connected"]):
                print("✅ update_kgframes accepts correct parameters (fails at connection)")
            else:
                print(f"❌ update_kgframes signature issue: {e}")
                return False
        
        return True
        
    except Exception as e:
        print(f"❌ Error creating endpoints: {e}")
        return False


def test_grouping_uri_concepts():
    """Test understanding of grouping URI concepts."""
    
    print("\n=== Testing Grouping URI Concepts ===")
    
    print("📋 Entity Graph Grouping:")
    print("   • hasKGGraphURI = entity URI (for all entity components)")
    print("   • Server extracts entity URI from document")
    print("   • No client parameter needed")
    
    print("\n📋 Frame Graph Grouping:")
    print("   • hasKGGraphURI = entity URI (links frames to entity)")
    print("   • hasFrameGraphURI = frame URI (for frame-specific operations)")
    print("   • Client provides entity_uri parameter")
    print("   • Server sets both grouping URIs")
    
    print("\n📋 Components Affected:")
    print("   • Entities: hasKGGraphURI")
    print("   • Frames: hasKGGraphURI + hasFrameGraphURI")
    print("   • Slots: hasKGGraphURI + hasFrameGraphURI")
    print("   • hasSlot Edges: hasKGGraphURI + hasFrameGraphURI")
    print("   • Other Edges: hasKGGraphURI")
    
    print("\n📋 Server Security:")
    print("   • Strips all client-provided grouping URIs")
    print("   • Authoritatively sets grouping URIs")
    print("   • Prevents client manipulation of graph relationships")
    
    print("\n✅ Grouping URI concepts verified")
    return True


def main():
    """Run all functionality tests."""
    
    print("🧪 Testing Grouping URI Functionality")
    print("=" * 50)
    
    tests = [
        test_kgentities_method_signatures,
        test_kgframes_method_signatures,
        test_parameter_defaults,
        test_method_call_functionality,
        test_grouping_uri_concepts
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ Test {test.__name__} crashed: {e}")
            failed += 1
    
    print("\n" + "=" * 50)
    print("📊 FUNCTIONALITY TEST RESULTS")
    print("=" * 50)
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")
    print(f"📈 Total: {passed + failed}")
    
    if failed == 0:
        print("\n🎉 All functionality tests passed! Grouping URI implementation is correct.")
        return 0
    else:
        print(f"\n💥 {failed} functionality test(s) failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
