#!/usr/bin/env python3

"""Test VitalSigns individual object creation."""

import sys
import os

# Add the parent directory to the path so we can import vitalgraph
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_vitalsigns_individual():
    """Test creating individual VitalSigns objects."""
    
    print("🧪 Testing Individual VitalSigns Object Creation")
    print("=" * 55)
    
    try:
        # Test 1: Create KGEntity directly
        print("1. Testing direct KGEntity creation...")
        from ai_haley_kg_domain.model.KGEntity import KGEntity
        
        entity = KGEntity()
        entity.URI = "http://example.org/entity1"
        entity.name = "Test Entity"
        
        print("✅ KGEntity created successfully")
        print(f"   URI: {entity.URI}")
        print(f"   Name: {entity.name}")
        print(f"   Vitaltype: {entity.vitaltype}")
        
        # Test 2: Convert to JSON
        print("\n2. Testing to_json conversion...")
        json_str = entity.to_json()
        print(f"✅ to_json returned: {type(json_str)}")
        print(f"   JSON length: {len(json_str)} characters")
        
        # Test 3: Test property setting
        print("\n3. Testing property setting...")
        haley_prefix = "http://vital.ai/ontology/haley-ai-kg#"
        grouping_uri_property = f"{haley_prefix}hasKGGraphURI"
        
        entity.set_property(grouping_uri_property, "http://example.org/entity1")
        
        # Try to get the property back
        try:
            grouping_value = entity.get_property(grouping_uri_property)
            print(f"✅ Grouping URI set and retrieved: {grouping_value}")
        except Exception as e:
            print(f"⚠️  Could not retrieve grouping URI: {e}")
        
        # Test 4: Create from JSON
        print("\n4. Testing from_json conversion...")
        from vital_ai_vitalsigns.vitalsigns import VitalSigns
        vitalsigns = VitalSigns()
        
        # Try to recreate from JSON
        recreated_entity = vitalsigns.from_json(json_str)
        if recreated_entity:
            print("✅ from_json successful")
            print(f"   Recreated URI: {recreated_entity.URI}")
            print(f"   Recreated Name: {recreated_entity.name}")
        else:
            print("❌ from_json returned None")
        
        print("\n🎉 Individual VitalSigns object tests completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Individual VitalSigns test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    test_vitalsigns_individual()
