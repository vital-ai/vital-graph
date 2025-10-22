#!/usr/bin/env python3
"""
Quick test to check if VitalSigns JSON-LD includes rdf:type properties.
"""

import json
import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.VITAL_Node import VITAL_Node
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGEntityType import KGEntityType

def check_rdf_type_in_jsonld():
    """Check if VitalSigns JSON-LD includes rdf:type properties."""
    print("🔍 Checking RDF Type Properties in VitalSigns JSON-LD")
    print("=" * 60)
    
    # Test 1: VITAL_Node
    print("\n1. VITAL_Node:")
    node = VITAL_Node()
    node.URI = "http://example.com/test-node"
    node.name = "Test Node"
    
    node_jsonld = node.to_jsonld()
    print(f"   Class URI: {node.get_class_uri()}")
    print(f"   Vitaltype: {getattr(node, 'vitaltype', 'N/A')}")
    
    # Check for rdf:type and vitaltype in JSON-LD
    rdf_type_key = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
    vitaltype_key = "http://vital.ai/ontology/vital-core#vitaltype"
    
    print(f"   JSON-LD @type: {node_jsonld.get('@type', 'NOT FOUND')}")
    print(f"   JSON-LD rdf:type: {node_jsonld.get(rdf_type_key, 'NOT FOUND')}")
    print(f"   JSON-LD vitaltype: {node_jsonld.get(vitaltype_key, 'NOT FOUND')}")
    
    # Test 2: KGEntity
    print("\n2. KGEntity:")
    entity = KGEntity()
    entity.URI = "http://example.com/test-entity"
    entity.name = "Test Entity"
    
    entity_jsonld = entity.to_jsonld()
    print(f"   Class URI: {entity.get_class_uri()}")
    print(f"   Vitaltype: {getattr(entity, 'vitaltype', 'N/A')}")
    print(f"   JSON-LD @type: {entity_jsonld.get('@type', 'NOT FOUND')}")
    print(f"   JSON-LD rdf:type: {entity_jsonld.get(rdf_type_key, 'NOT FOUND')}")
    print(f"   JSON-LD vitaltype: {entity_jsonld.get(vitaltype_key, 'NOT FOUND')}")
    
    # Test 3: KGEntityType
    print("\n3. KGEntityType:")
    kgtype = KGEntityType()
    kgtype.URI = "http://example.com/test-type"
    kgtype.name = "Test Type"
    
    kgtype_jsonld = kgtype.to_jsonld()
    print(f"   Class URI: {kgtype.get_class_uri()}")
    print(f"   Vitaltype: {getattr(kgtype, 'vitaltype', 'N/A')}")
    print(f"   JSON-LD @type: {kgtype_jsonld.get('@type', 'NOT FOUND')}")
    print(f"   JSON-LD rdf:type: {kgtype_jsonld.get(rdf_type_key, 'NOT FOUND')}")
    print(f"   JSON-LD vitaltype: {kgtype_jsonld.get(vitaltype_key, 'NOT FOUND')}")
    
    # Test 4: Check all keys in JSON-LD to see what's actually there
    print(f"\n4. All JSON-LD keys in KGEntity:")
    for key in sorted(entity_jsonld.keys()):
        if key not in ['@context']:  # Skip the large context
            value = entity_jsonld[key]
            if isinstance(value, dict):
                print(f"   {key}: {type(value)} with keys {list(value.keys())}")
            else:
                print(f"   {key}: {value}")
    
    # Test 5: Check if rdf:type exists in any form
    print(f"\n5. Searching for 'type' in all keys:")
    for key in entity_jsonld.keys():
        if 'type' in key.lower():
            print(f"   Found type-related key: {key} = {entity_jsonld[key]}")

if __name__ == "__main__":
    check_rdf_type_in_jsonld()
