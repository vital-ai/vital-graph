#!/usr/bin/env python3
"""
Test to see what happens during JSON-LD round-trip conversion with rdf:type.
"""

import json
import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vital_ai_vitalsigns.vitalsigns import VitalSigns
from ai_haley_kg_domain.model.KGEntity import KGEntity

def test_rdf_type_roundtrip():
    """Test what happens with rdf:type during round-trip conversion."""
    print("🔄 Testing RDF Type Round-Trip Conversion")
    print("=" * 50)
    
    # Create original object
    entity = KGEntity()
    entity.URI = "http://example.com/test-entity"
    entity.name = "Test Entity"
    
    print(f"Original object:")
    print(f"  Class URI: {entity.get_class_uri()}")
    print(f"  Vitaltype: {getattr(entity, 'vitaltype', 'N/A')}")
    
    # Convert to JSON-LD
    jsonld = entity.to_jsonld()
    
    print(f"\nJSON-LD contains:")
    print(f"  @type: {jsonld.get('@type', 'NOT FOUND')}")
    print(f"  type: {jsonld.get('type', 'NOT FOUND')}")
    print(f"  rdf:type: {jsonld.get('http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'NOT FOUND')}")
    print(f"  vitaltype: {jsonld.get('http://vital.ai/ontology/vital-core#vitaltype', 'NOT FOUND')}")
    
    # Convert back from JSON-LD
    reconstructed = KGEntity.from_jsonld(jsonld)
    
    print(f"\nReconstructed object:")
    print(f"  Class URI: {reconstructed.get_class_uri()}")
    print(f"  Vitaltype: {getattr(reconstructed, 'vitaltype', 'N/A')}")
    
    # Test with manually added rdf:type
    print(f"\n" + "=" * 50)
    print("Testing with manually added rdf:type")
    
    # Add rdf:type to JSON-LD
    jsonld_with_rdf_type = jsonld.copy()
    jsonld_with_rdf_type["http://www.w3.org/1999/02/22-rdf-syntax-ns#type"] = {
        "id": "http://vital.ai/ontology/haley-ai-kg#KGEntity"
    }
    
    print(f"Modified JSON-LD now contains:")
    print(f"  @type: {jsonld_with_rdf_type.get('@type', 'NOT FOUND')}")
    print(f"  type: {jsonld_with_rdf_type.get('type', 'NOT FOUND')}")
    print(f"  rdf:type: {jsonld_with_rdf_type.get('http://www.w3.org/1999/02/22-rdf-syntax-ns#type', 'NOT FOUND')}")
    
    try:
        reconstructed_with_rdf = KGEntity.from_jsonld(jsonld_with_rdf_type)
        print(f"\nReconstructed with rdf:type:")
        print(f"  Class URI: {reconstructed_with_rdf.get_class_uri()}")
        print(f"  Vitaltype: {getattr(reconstructed_with_rdf, 'vitaltype', 'N/A')}")
        print(f"  ✅ Conversion successful!")
    except Exception as e:
        print(f"\n❌ Conversion with rdf:type failed: {e}")
    
    # Test what VitalSigns expects
    print(f"\n" + "=" * 50)
    print("Testing VitalSigns.from_jsonld() expectations")
    
    vs = VitalSigns()
    
    # Test 1: Original JSON-LD (no rdf:type)
    try:
        vs_result1 = vs.from_jsonld(jsonld)
        print(f"✅ VitalSigns.from_jsonld() works WITHOUT rdf:type")
        print(f"  Result class: {vs_result1.get_class_uri()}")
    except Exception as e:
        print(f"❌ VitalSigns.from_jsonld() failed WITHOUT rdf:type: {e}")
    
    # Test 2: JSON-LD with rdf:type
    try:
        vs_result2 = vs.from_jsonld(jsonld_with_rdf_type)
        print(f"✅ VitalSigns.from_jsonld() works WITH rdf:type")
        print(f"  Result class: {vs_result2.get_class_uri()}")
    except Exception as e:
        print(f"❌ VitalSigns.from_jsonld() failed WITH rdf:type: {e}")

if __name__ == "__main__":
    test_rdf_type_roundtrip()
