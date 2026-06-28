#!/usr/bin/env python3

"""Test setting hasKGGraphURI property."""

import sys
import os

# Add the parent directory to the path so we can import vitalgraph
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_grouping_uri():
    """Test setting hasKGGraphURI property."""
    
    print("🧪 Testing hasKGGraphURI Property")
    print("=" * 35)
    
    try:
        from ai_haley_kg_domain.model.KGEntity import KGEntity
        
        entity = KGEntity()
        entity.URI = "http://example.org/entity1"
        entity.name = "Test Entity"
        
        print(f"Created entity: {entity.URI}")
        
        # Test 1: Try setting with full URI
        print("\n1. Testing full URI property setting...")
        full_uri = "http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI"
        try:
            entity.set_property(full_uri, "http://example.org/entity1")
            retrieved_value = entity.get_property(full_uri)
            print(f"✅ Full URI successful: {retrieved_value}")
        except Exception as e:
            print(f"❌ Full URI failed: {e}")
        
        # Test 2: Try setting with short name (if it exists)
        print("\n2. Testing short name property setting...")
        
        # Find the trait class for this property
        domain_props = entity.get_allowed_domain_properties()
        kg_graph_uri_prop = None
        
        for prop in domain_props:
            if prop.get('uri') == full_uri:
                kg_graph_uri_prop = prop
                break
        
        if kg_graph_uri_prop:
            print(f"Found property: {kg_graph_uri_prop}")
            
            # Try to get the short name
            try:
                from vital_ai_vitalsigns.impl.vitalsigns_impl import VitalSignsImpl
                trait_class = VitalSignsImpl.get_trait_class_from_uri(full_uri)
                if trait_class:
                    short_name = trait_class.get_short_name()
                    print(f"Short name: {short_name}")
                    
                    # Try setting with short name
                    setattr(entity, short_name, "http://example.org/entity1")
                    retrieved_value = getattr(entity, short_name)
                    print(f"✅ Short name successful: {retrieved_value}")
                else:
                    print("❌ No trait class found")
            except Exception as e:
                print(f"❌ Short name failed: {e}")
        else:
            print("❌ Property not found in domain properties")
        
        # Test 3: Try direct attribute setting
        print("\n3. Testing direct attribute setting...")
        try:
            # Try common short names
            possible_names = ['hasKGGraphURI', 'kgGraphURI', 'KGGraphURI']
            
            for name in possible_names:
                try:
                    setattr(entity, name, "http://example.org/entity1")
                    retrieved_value = getattr(entity, name)
                    print(f"✅ Direct attribute '{name}' successful: {retrieved_value}")
                    break
                except Exception as e:
                    print(f"   '{name}' failed: {e}")
        except Exception as e:
            print(f"❌ Direct attribute setting failed: {e}")
        
        # Test 4: Check what properties are actually set
        print("\n4. Checking set properties...")
        try:
            keys = entity.keys()
            print(f"Entity has {len(keys)} properties set:")
            for key in keys:
                try:
                    value = entity.get_property(key)
                    print(f"   • {key}: {value}")
                except:
                    print(f"   • {key}: <could not retrieve>")
        except Exception as e:
            print(f"❌ Could not list properties: {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ Grouping URI test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    test_grouping_uri()
