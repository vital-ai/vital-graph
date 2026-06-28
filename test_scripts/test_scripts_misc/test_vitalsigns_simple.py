#!/usr/bin/env python3

"""Simple test of VitalSigns conversion functionality."""

import sys
import os

# Add the parent directory to the path so we can import vitalgraph
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_vitalsigns_basic():
    """Test basic VitalSigns conversion without mock endpoint."""
    
    print("🧪 Testing Basic VitalSigns Conversion")
    print("=" * 50)
    
    try:
        # Test 1: Import VitalSigns
        print("1. Testing VitalSigns import...")
        from vital_ai_vitalsigns.vitalsigns import VitalSigns
        vitalsigns = VitalSigns()
        print("✅ VitalSigns imported and initialized successfully")
        
        # Test 2: Test GraphObject construction and quad round-trip
        print("\n2. Testing GraphObject construction and quad round-trip...")
        
        from ai_haley_kg_domain.model.KGEntity import KGEntity
        from vitalgraph.utils.quad_format_utils import graphobjects_to_quad_list, quad_list_to_graphobjects
        
        entity = KGEntity()
        entity.URI = "http://example.org/entity1"
        entity.name = "Test Entity"
        
        quads = graphobjects_to_quad_list([entity])
        objects = quad_list_to_graphobjects(quads)
        if objects:
            print(f"✅ quad round-trip returned {len(objects)} objects")
            
            # Test accessing properties
            for obj in objects:
                try:
                    print(f"   Object URI: {obj.URI}")
                    print(f"   Object vitaltype: {obj.vitaltype}")
                except Exception as e:
                    print(f"   ⚠️  Error accessing object properties: {e}")
        else:
            print("❌ quad round-trip returned no objects")
            return False
        
        # Test 3: Test from_triples_list conversion
        print("\n3. Testing from_triples_list conversion...")
        
        sample_triples = [
            ("http://example.org/entity2", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "http://vital.ai/ontology/haley-ai-kg#KGEntity"),
            ("http://example.org/entity2", "http://vital.ai/ontology/vital-core#name", "Test Entity 2"),
            ("http://example.org/entity2", "http://vital.ai/ontology/vital-core#vitaltype", "http://vital.ai/ontology/haley-ai-kg#KGEntity"),
            ("http://example.org/entity2", "http://vital.ai/ontology/vital-core#URIProp", "http://example.org/entity2")
        ]
        
        objects2 = vitalsigns.from_triples_list(sample_triples)
        if objects2:
            print(f"✅ from_triples_list returned {len(objects2)} objects")
            
            # Test to_json conversion
            for obj in objects2:
                try:
                    json_result = obj.to_json()
                    print(f"   Object converted to JSON: {type(json_result)}")
                except Exception as e:
                    print(f"   ⚠️  Error converting to JSON: {e}")
        else:
            print("❌ from_triples_list returned no objects")
            return False
        
        print("\n🎉 Basic VitalSigns conversion tests completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Basic VitalSigns test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run the basic VitalSigns test."""
    
    success = test_vitalsigns_basic()
    
    if success:
        print("\n✅ All basic VitalSigns tests passed!")
        sys.exit(0)
    else:
        print("\n💥 Basic VitalSigns tests failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
