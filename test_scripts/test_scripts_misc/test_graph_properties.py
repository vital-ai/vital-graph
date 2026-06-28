#!/usr/bin/env python3

"""Search for graph-related properties."""

import sys
import os

# Add the parent directory to the path so we can import vitalgraph
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_graph_properties():
    """Search for graph-related properties."""
    
    print("🔍 Searching for Graph-Related Properties")
    print("=" * 45)
    
    try:
        from ai_haley_kg_domain.model.KGEntity import KGEntity
        
        entity = KGEntity()
        domain_props = entity.get_allowed_domain_properties()
        
        print(f"Searching through {len(domain_props)} properties...")
        
        graph_props = []
        uri_props = []
        frame_props = []
        
        for prop in domain_props:
            prop_uri = prop.get('uri', '').lower()
            
            if 'graph' in prop_uri:
                graph_props.append(prop)
            if 'uri' in prop_uri and 'graph' in prop_uri:
                uri_props.append(prop)
            if 'frame' in prop_uri:
                frame_props.append(prop)
        
        print(f"\n📋 Properties containing 'graph' ({len(graph_props)}):")
        for prop in graph_props:
            uri = prop.get('uri', '')
            print(f"   • {uri}")
        
        print(f"\n📋 Properties containing 'frame' ({len(frame_props)}):")
        for prop in frame_props:
            uri = prop.get('uri', '')
            print(f"   • {uri}")
        
        print(f"\n📋 Properties containing both 'uri' and 'graph' ({len(uri_props)}):")
        for prop in uri_props:
            uri = prop.get('uri', '')
            print(f"   • {uri}")
        
        # Search for any property that might be related to grouping
        print(f"\n🔍 Searching for grouping-related properties:")
        grouping_keywords = ['group', 'container', 'parent', 'owner', 'belongs']
        
        for keyword in grouping_keywords:
            matching_props = []
            for prop in domain_props:
                prop_uri = prop.get('uri', '').lower()
                if keyword in prop_uri:
                    matching_props.append(prop)
            
            if matching_props:
                print(f"\n   Properties containing '{keyword}' ({len(matching_props)}):")
                for prop in matching_props:
                    uri = prop.get('uri', '')
                    print(f"     • {uri}")
        
        # Try setting properties using short names
        print(f"\n🧪 Testing short name property access:")
        
        try:
            # Test basic properties that should exist
            entity.name = "Test Entity"  # Short name
            print(f"✅ Short name 'name' set successfully: {entity.name}")
        except Exception as e:
            print(f"❌ Short name 'name' failed: {e}")
        
        try:
            # Test URI property
            print(f"✅ URI property accessible: {entity.URI}")
        except Exception as e:
            print(f"❌ URI property failed: {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ Graph properties search failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    test_graph_properties()
