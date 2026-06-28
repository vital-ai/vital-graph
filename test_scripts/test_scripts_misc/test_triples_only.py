#!/usr/bin/env python3

"""Test only VitalSigns triples conversion."""

import sys
import os

# Add the parent directory to the path so we can import vitalgraph
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_triples_only():
    """Test only VitalSigns triples conversion."""
    
    print("🧪 Testing VitalSigns Triples Conversion Only")
    print("=" * 50)
    
    try:
        from vital_ai_vitalsigns.vitalsigns import VitalSigns
        vitalsigns = VitalSigns()
        print("✅ VitalSigns imported and initialized successfully")
        
        # Test triples conversion
        print("\n🔧 Testing from_triples_list conversion...")
        
        sample_triples = [
            ("http://example.org/entity2", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "http://vital.ai/ontology/haley-ai-kg#KGEntity"),
            ("http://example.org/entity2", "http://vital.ai/ontology/vital-core#name", "Test Entity 2"),
            ("http://example.org/entity2", "http://vital.ai/ontology/vital-core#vitaltype", "http://vital.ai/ontology/haley-ai-kg#KGEntity"),
            ("http://example.org/entity2", "http://vital.ai/ontology/vital-core#URI", "http://example.org/entity2")
        ]
        
        print(f"Input triples ({len(sample_triples)}):")
        for i, triple in enumerate(sample_triples):
            print(f"  {i}: {triple}")
        
        objects = vitalsigns.from_triples_list(sample_triples)
        if objects:
            print(f"\n✅ from_triples_list returned {len(objects)} objects")
            
            # Test accessing properties
            for i, obj in enumerate(objects):
                try:
                    print(f"  Object {i}:")
                    print(f"    URI: {obj.URI}")
                    print(f"    vitaltype: {obj.vitaltype}")
                    print(f"    name: {getattr(obj, 'name', 'N/A')}")
                except Exception as e:
                    print(f"    ⚠️  Error accessing object properties: {e}")
        else:
            print("❌ from_triples_list returned no objects")
            return False
        
        print("\n🎉 Triples conversion test completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Triples conversion test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    test_triples_only()
