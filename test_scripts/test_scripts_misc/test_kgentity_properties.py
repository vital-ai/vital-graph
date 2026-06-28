#!/usr/bin/env python3

"""Test KGEntity properties."""

import sys
import os

# Add the parent directory to the path so we can import vitalgraph
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_kgentity_properties():
    """Test what properties are available on KGEntity."""
    
    print("🔍 Discovering KGEntity Properties")
    print("=" * 40)
    
    try:
        from ai_haley_kg_domain.model.KGEntity import KGEntity
        
        entity = KGEntity()
        entity.URI = "http://example.org/entity1"
        entity.name = "Test Entity"
        
        print("Available properties on KGEntity:")
        
        # Get allowed domain properties
        domain_props = entity.get_allowed_domain_properties()
        
        print(f"\nFound {len(domain_props)} domain properties:")
        
        haley_props = []
        core_props = []
        other_props = []
        
        for prop in domain_props:
            prop_uri = prop.get('uri', '')
            if 'haley-ai-kg' in prop_uri:
                haley_props.append(prop)
            elif 'vital-core' in prop_uri:
                core_props.append(prop)
            else:
                other_props.append(prop)
        
        print(f"\n📋 Haley KG Properties ({len(haley_props)}):")
        for prop in haley_props[:10]:  # Show first 10
            uri = prop.get('uri', '')
            prop_class = prop.get('prop_class', '')
            print(f"   • {uri}")
            if 'hasKGGraphURI' in uri or 'hasFrameGraphURI' in uri:
                print(f"     ⭐ FOUND GROUPING URI PROPERTY!")
        
        print(f"\n📋 Vital Core Properties ({len(core_props)}):")
        for prop in core_props[:5]:  # Show first 5
            uri = prop.get('uri', '')
            print(f"   • {uri}")
        
        print(f"\n📋 Other Properties ({len(other_props)}):")
        for prop in other_props[:5]:  # Show first 5
            uri = prop.get('uri', '')
            print(f"   • {uri}")
        
        # Test setting a known property
        print(f"\n🧪 Testing property setting:")
        
        # Try setting a core property
        try:
            entity.set_property("http://vital.ai/ontology/vital-core#name", "Updated Name")
            retrieved_name = entity.get_property("http://vital.ai/ontology/vital-core#name")
            print(f"✅ Core property set/get successful: {retrieved_name}")
        except Exception as e:
            print(f"❌ Core property failed: {e}")
        
        # Try setting a haley property if available
        if haley_props:
            test_prop = haley_props[0]['uri']
            try:
                entity.set_property(test_prop, "test_value")
                retrieved_value = entity.get_property(test_prop)
                print(f"✅ Haley property set/get successful: {test_prop} = {retrieved_value}")
            except Exception as e:
                print(f"❌ Haley property failed: {test_prop} - {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ Property discovery failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    test_kgentity_properties()
