#!/usr/bin/env python3
"""
KGEntity Serialization Test Script

This script tests the serialization and deserialization of KGEntity objects
to/from JSON and JSON-LD formats to identify property mapping issues.
"""

import json
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def test_kgentity_serialization():
    """Test KGEntity serialization to JSON and JSON-LD formats."""
    
    print("=" * 80)
    print("KGEntity Serialization Test")
    print("=" * 80)
    
    try:
        # Initialize VitalSigns
        from vital_ai_vitalsigns.vitalsigns import VitalSigns
        vs = VitalSigns()
        
        # Import KGEntity
        from ai_haley_kg_domain.model.KGEntity import KGEntity
        
        print("\n1. Creating KGEntity with properties...")
        
        # Create KGEntity with various properties
        entity = KGEntity()
        entity.URI = "http://vital.ai/haley.ai/app/KGEntity/test_entity_01"
        entity.name = "Test Entity"
        
        # Basic KGEntity properties
        entity.kGEntityType = "urn:TestEntity"
        entity.kGEntityTypeDescription = "Test Entity Description"
        
        # Try KGNode inherited properties
        try:
            entity.kGIdentifier = "urn:test_entity_identifier"
            print("✅ kGIdentifier set successfully")
        except Exception as e:
            print(f"❌ kGIdentifier failed: {e}")
        
        try:
            entity.kGraphDescription = "A test entity for serialization testing"
            print("✅ kGraphDescription set successfully")
        except Exception as e:
            print(f"❌ kGraphDescription failed: {e}")
        
        try:
            entity.kGIndexDateTime = datetime.now().isoformat()
            print("✅ kGIndexDateTime set successfully")
        except Exception as e:
            print(f"❌ kGIndexDateTime failed: {e}")
        
        try:
            entity.kGGraphAssertionDateTime = datetime.now().isoformat()
            print("✅ kGGraphAssertionDateTime set successfully")
        except Exception as e:
            print(f"❌ kGGraphAssertionDateTime failed: {e}")
        
        try:
            entity.kGNodeCacheDateTime = datetime.now().isoformat()
            print("✅ kGNodeCacheDateTime set successfully")
        except Exception as e:
            print(f"❌ kGNodeCacheDateTime failed: {e}")
        
        # Try VITAL properties (certainty, pageRank)
        try:
            entity.certainty = 0.95
            print("✅ certainty set successfully")
        except Exception as e:
            print(f"❌ certainty failed: {e}")
        
        try:
            entity.pageRank = 0.85
            print("✅ pageRank set successfully")
        except Exception as e:
            print(f"❌ pageRank failed: {e}")
        
        print(f"\n2. Entity created with URI: {entity.URI}")
        
        # Test property access
        print("\n3. Testing property access...")
        properties_to_test = [
            'name', 'kGEntityType', 'kGEntityTypeDescription', 
            'kGIdentifier', 'kGraphDescription', 'kGIndexDateTime',
            'kGGraphAssertionDateTime', 'kGNodeCacheDateTime', 
            'certainty', 'pageRank'
        ]
        
        for prop in properties_to_test:
            try:
                value = getattr(entity, prop)
                print(f"✅ {prop}: {value}")
            except AttributeError as e:
                print(f"❌ {prop}: AttributeError - {e}")
            except Exception as e:
                print(f"❌ {prop}: {type(e).__name__} - {e}")
        
        # Test allowed properties
        print("\n4. Checking allowed properties...")
        allowed_props = entity.get_allowed_domain_properties()
        print(f"Total allowed properties: {len(allowed_props)}")
        
        # Check for specific properties we're interested in
        allowed_uris = {prop['uri'] for prop in allowed_props}
        properties_of_interest = [
            'http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier',
            'http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime',
            'http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription',
            'http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime',
            'http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime',
            'http://vital.ai/ontology/vital#hasCertainty',
            'http://vital.ai/ontology/vital#hasPageRank'
        ]
        
        print("\nChecking specific property URIs:")
        for uri in properties_of_interest:
            if uri in allowed_uris:
                print(f"✅ {uri}")
            else:
                print(f"❌ {uri} - NOT ALLOWED")
        
        # Test JSON serialization
        print("\n5. Testing JSON serialization...")
        try:
            json_str = entity.to_json()
            print("✅ JSON serialization successful")
            print(f"JSON length: {len(json_str)} characters")
            
            # Parse and pretty print JSON
            json_obj = json.loads(json_str)
            print("\nJSON structure:")
            print(json.dumps(json_obj, indent=2))
            
        except Exception as e:
            print(f"❌ JSON serialization failed: {e}")
            import traceback
            traceback.print_exc()
        
        # Test JSON-LD serialization
        print("\n6. Testing JSON-LD serialization...")
        try:
            jsonld_obj = entity.to_jsonld()
            print("✅ JSON-LD serialization successful")
            print("\nJSON-LD structure:")
            print(json.dumps(jsonld_obj, indent=2))
            
        except Exception as e:
            print(f"❌ JSON-LD serialization failed: {e}")
            import traceback
            traceback.print_exc()
        
        # Test JSON deserialization
        print("\n7. Testing JSON deserialization...")
        try:
            json_str = entity.to_json()
            restored_entity = KGEntity.from_json(json_str)
            print("✅ JSON deserialization successful")
            print(f"Restored entity URI: {restored_entity.URI}")
            
            # Compare properties
            print("\nComparing properties after JSON round-trip:")
            for prop in properties_to_test:
                try:
                    original_val = getattr(entity, prop, None)
                    restored_val = getattr(restored_entity, prop, None)
                    if original_val == restored_val:
                        print(f"✅ {prop}: {original_val}")
                    else:
                        print(f"❌ {prop}: Original={original_val}, Restored={restored_val}")
                except Exception as e:
                    print(f"❌ {prop}: Error comparing - {e}")
                    
        except Exception as e:
            print(f"❌ JSON deserialization failed: {e}")
            import traceback
            traceback.print_exc()
        
        # Test JSON-LD deserialization
        print("\n8. Testing JSON-LD deserialization...")
        try:
            jsonld_obj = entity.to_jsonld()
            restored_entity = KGEntity.from_jsonld(jsonld_obj)
            print("✅ JSON-LD deserialization successful")
            print(f"Restored entity URI: {restored_entity.URI}")
            
            # Compare properties
            print("\nComparing properties after JSON-LD round-trip:")
            for prop in properties_to_test:
                try:
                    original_val = getattr(entity, prop, None)
                    restored_val = getattr(restored_entity, prop, None)
                    if original_val == restored_val:
                        print(f"✅ {prop}: {original_val}")
                    else:
                        print(f"❌ {prop}: Original={original_val}, Restored={restored_val}")
                except Exception as e:
                    print(f"❌ {prop}: Error comparing - {e}")
                    
        except Exception as e:
            print(f"❌ JSON-LD deserialization failed: {e}")
            import traceback
            traceback.print_exc()
        
        print("\n" + "=" * 80)
        print("Test completed!")
        print("=" * 80)
        
    except Exception as e:
        print(f"❌ Test setup failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_kgentity_serialization()
