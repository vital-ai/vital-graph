#!/usr/bin/env python3
"""
Test script for VitalGraph data_format_utils JSON-LD functionality.

This script tests the local JSON-LD implementation in data_format_utils.py
using real VitalSigns objects and sample data patterns from the mock client tests.
It demonstrates the conversion pipeline: VitalSigns objects → JSON-LD → GraphObjects → RDF quads.

Tests include:
- Single object conversion using data_format_utils
- Multiple objects batch conversion
- Complex VitalSigns objects (KGEntity, KGFrame, Edge_hasKGSlot)
- Round-trip conversion validation
- Comparison with native VitalSigns JSON-LD methods
"""

import json
import sys
import os
import asyncio
from pathlib import Path
from typing import List, Any

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# VitalSigns imports
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.VITAL_Node import VITAL_Node
from vital_ai_vitalsigns.utils.uri_generator import URIGenerator

# Import real VitalSigns domain objects
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGEntitySlot import KGEntitySlot
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGType import KGType
from ai_haley_kg_domain.model.KGEntityType import KGEntityType

# Import VitalGraph data format utilities
from vitalgraph.utils.data_format_utils import (
    jsonld_to_graphobjects, 
    graphobjects_to_quads,
    batch_jsonld_to_graphobjects,
    batch_graphobjects_to_quads
)


def create_simple_test_objects():
    """Create simple test objects similar to test_jsonld_basic.py."""
    objects = []
    
    # Create basic VITAL_Node objects
    for i in range(3):
        node = VITAL_Node()
        node.URI = f"http://example.com/test-node-{i+1}"
        node.name = f"Test Node {i+1}"
        objects.append(node)
    
    return objects


def create_complex_vitalsigns_objects():
    """Create complex VitalSigns objects from test_vitalsigns_objects.py pattern."""
    objects = []
    
    # Create source KGEntity (representing a WordNet concept)
    source_kgentity = KGEntity()
    source_kgentity.URI = "http://vital.ai/haley.ai/app/KGEntity/dog_n_01"
    source_kgentity.name = "dog"
    source_kgentity.kGraphDescription = "a domesticated carnivorous mammal"
    source_kgentity.kGIdentifier = "urn:wordnet_dog.n.01"
    source_kgentity.kGEntityType = "urn:Noun"
    source_kgentity.kGEntityTypeDescription = "Noun"
    objects.append(source_kgentity)
    
    # Create destination KGEntity
    destination_kgentity = KGEntity()
    destination_kgentity.URI = "http://vital.ai/haley.ai/app/KGEntity/animal_n_01"
    destination_kgentity.name = "animal"
    destination_kgentity.kGraphDescription = "a living organism characterized by voluntary movement"
    destination_kgentity.kGIdentifier = "urn:wordnet_animal.n.01"
    destination_kgentity.kGEntityType = "urn:Noun"
    destination_kgentity.kGEntityTypeDescription = "Noun"
    objects.append(destination_kgentity)
    
    # Create KGFrame (representing the relationship)
    kgframe = KGFrame()
    kgframe.URI = "http://vital.ai/haley.ai/app/KGFrame/hypernym_relation_001"
    kgframe.kGFrameType = "urn:Hypernym"
    kgframe.kGFrameTypeDescription = "Hypernym relationship"
    objects.append(kgframe)
    
    # Create source entity slot
    source_slot = KGEntitySlot()
    source_slot.URI = URIGenerator.generate_uri()
    source_slot.kGSlotType = "urn:hasSourceEntity"
    source_slot.kGSlotTypeDescription = "hasSourceEntity"
    source_slot.entitySlotValue = source_kgentity.URI
    objects.append(source_slot)
    
    # Create destination entity slot
    destination_slot = KGEntitySlot()
    destination_slot.URI = URIGenerator.generate_uri()
    destination_slot.kGSlotType = "urn:hasDestinationEntity"
    destination_slot.kGSlotTypeDescription = "hasDestinationEntity"
    destination_slot.entitySlotValue = destination_kgentity.URI
    objects.append(destination_slot)
    
    # Create edge from frame to source slot
    source_slot_edge = Edge_hasKGSlot()
    source_slot_edge.URI = URIGenerator.generate_uri()
    source_slot_edge.edgeSource = kgframe.URI
    source_slot_edge.edgeDestination = source_slot.URI
    objects.append(source_slot_edge)
    
    # Create edge from frame to destination slot
    destination_slot_edge = Edge_hasKGSlot()
    destination_slot_edge.URI = URIGenerator.generate_uri()
    destination_slot_edge.edgeSource = kgframe.URI
    destination_slot_edge.edgeDestination = destination_slot.URI
    objects.append(destination_slot_edge)
    
    return objects


def create_kgtype_objects():
    """Create KGType objects similar to mock_client_example.py pattern."""
    objects = []
    
    # Create Person KGType
    person_type = KGEntityType()
    person_type.URI = "http://vital.ai/ontology/haley-ai-kg#Person"
    person_type.name = "Person"
    person_type.kGraphDescription = "A human being"
    person_type.kGModelVersion = "1.0"
    person_type.kGTypeVersion = "1.0"
    objects.append(person_type)
    
    # Create Organization KGType
    org_type = KGEntityType()
    org_type.URI = "http://vital.ai/ontology/haley-ai-kg#Organization"
    org_type.name = "Organization"
    org_type.kGraphDescription = "A business or institutional entity"
    org_type.kGModelVersion = "1.0"
    org_type.kGTypeVersion = "1.0"
    objects.append(org_type)
    
    return objects


def objects_to_manual_jsonld(objects):
    """Convert VitalSigns objects to JSON-LD manually (like mock client tests)."""
    graph = []
    
    for obj in objects:
        # Use VitalSigns to_json() method
        json_str = obj.to_json()
        vitalsigns_dict = json.loads(json_str)
        
        # Convert to JSON-LD format
        jsonld_dict = {
            "@id": vitalsigns_dict.get("URI"),
            "@type": vitalsigns_dict.get("type")
        }
        
        # Add all other properties, excluding VitalSigns metadata
        for key, value in vitalsigns_dict.items():
            if key not in ["URI", "type", "types", "http://vital.ai/ontology/vital-core#vitaltype"]:
                jsonld_dict[key] = value
        
        graph.append(jsonld_dict)
    
    # Create JSON-LD document structure
    jsonld_document = {
        "@context": {
            "haley": "http://vital.ai/ontology/haley-ai-kg#",
            "vital": "http://vital.ai/ontology/vital-core#",
            "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
            "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
            "owl": "http://www.w3.org/2002/07/owl#",
            "xsd": "http://www.w3.org/2001/XMLSchema#",
            "type": "@type",
            "id": "@id"
        },
        "@graph": graph
    }
    
    return jsonld_document


async def test_simple_objects_data_format_utils():
    """Test simple objects using data_format_utils."""
    print("=" * 60)
    print("Testing Simple Objects with data_format_utils")
    print("=" * 60)
    
    # Create simple test objects
    objects = create_simple_test_objects()
    print(f"Created {len(objects)} simple VITAL_Node objects:")
    for obj in objects:
        print(f"  - URI: {obj.URI}, Name: {obj.name}")
    
    # Convert to JSON-LD manually
    jsonld_document = objects_to_manual_jsonld(objects)
    print(f"\n✅ Manual JSON-LD conversion successful!")
    print(f"JSON-LD structure: @context + @graph with {len(jsonld_document['@graph'])} objects")
    
    # Test data_format_utils conversion: JSON-LD → GraphObjects
    try:
        converted_objects = await jsonld_to_graphobjects(jsonld_document)
        print(f"\n✅ data_format_utils.jsonld_to_graphobjects() successful!")
        print(f"Converted {len(converted_objects)} GraphObjects:")
        for obj in converted_objects:
            print(f"  - URI: {obj.URI}, Name: {getattr(obj, 'name', 'N/A')}, Class: {obj.get_class_uri()}")
        
        # Test GraphObjects → RDF quads
        try:
            graph_id = "http://example.org/test_graph"
            quads = await graphobjects_to_quads(converted_objects, graph_id)
            print(f"\n✅ data_format_utils.graphobjects_to_quads() successful!")
            print(f"Generated {len(quads)} RDF quads for graph: {graph_id}")
            
            # Show sample quads
            for i, quad in enumerate(quads[:5]):  # Show first 5 quads
                s, p, o, g = quad
                print(f"  Quad {i+1}: <{s}> <{p}> {o} <{g}>")
            if len(quads) > 5:
                print(f"  ... and {len(quads) - 5} more quads")
            
        except Exception as e:
            print(f"\n❌ graphobjects_to_quads() failed: {e}")
            import traceback
            traceback.print_exc()
            
    except Exception as e:
        print(f"\n❌ jsonld_to_graphobjects() failed: {e}")
        import traceback
        traceback.print_exc()


async def test_complex_objects_data_format_utils():
    """Test complex VitalSigns objects using data_format_utils."""
    print("\n" + "=" * 60)
    print("Testing Complex VitalSigns Objects with data_format_utils")
    print("=" * 60)
    
    # Create complex test objects
    objects = create_complex_vitalsigns_objects()
    print(f"Created {len(objects)} complex VitalSigns objects:")
    for obj in objects:
        print(f"  - {obj.__class__.__name__}: {obj.URI}")
    
    # Convert to JSON-LD manually
    jsonld_document = objects_to_manual_jsonld(objects)
    print(f"\n✅ Manual JSON-LD conversion successful!")
    
    # Test batch conversion: JSON-LD → GraphObjects
    try:
        # Use the full JSON-LD document for batch processing (updated approach)
        converted_objects = await batch_jsonld_to_graphobjects(jsonld_document)
        print(f"\n✅ data_format_utils.batch_jsonld_to_graphobjects() successful!")
        print(f"Converted {len(converted_objects)} GraphObjects:")
        for obj in converted_objects:
            print(f"  - {obj.__class__.__name__}: {obj.URI}")
        
        # Test batch GraphObjects → RDF quads
        try:
            graph_id = "http://example.org/complex_graph"
            quads = await batch_graphobjects_to_quads(converted_objects, graph_id)
            print(f"\n✅ data_format_utils.batch_graphobjects_to_quads() successful!")
            print(f"Generated {len(quads)} RDF quads for complex objects")
            
            # Group quads by subject for better readability
            quad_groups = {}
            for quad in quads:
                s, p, o, g = quad
                if str(s) not in quad_groups:
                    quad_groups[str(s)] = []
                quad_groups[str(s)].append((str(p), str(o)))
            
            print(f"Quads grouped by subject ({len(quad_groups)} subjects):")
            for i, (subject, predicates) in enumerate(list(quad_groups.items())[:3]):  # Show first 3 subjects
                print(f"  Subject {i+1}: {subject}")
                for p, o in predicates[:3]:  # Show first 3 predicates per subject
                    print(f"    → {p}: {o}")
                if len(predicates) > 3:
                    print(f"    ... and {len(predicates) - 3} more predicates")
            if len(quad_groups) > 3:
                print(f"  ... and {len(quad_groups) - 3} more subjects")
            
        except Exception as e:
            print(f"\n❌ batch_graphobjects_to_quads() failed: {e}")
            import traceback
            traceback.print_exc()
            
    except Exception as e:
        print(f"\n❌ batch_jsonld_to_graphobjects() failed: {e}")
        import traceback
        traceback.print_exc()


async def test_kgtype_objects_data_format_utils():
    """Test KGType objects using data_format_utils."""
    print("\n" + "=" * 60)
    print("Testing KGType Objects with data_format_utils")
    print("=" * 60)
    
    # Create KGType test objects
    objects = create_kgtype_objects()
    print(f"Created {len(objects)} KGType objects:")
    for obj in objects:
        print(f"  - {obj.name}: {obj.URI}")
        print(f"    Description: {obj.kGraphDescription}")
    
    # Convert to JSON-LD manually
    jsonld_document = objects_to_manual_jsonld(objects)
    print(f"\n✅ Manual JSON-LD conversion successful!")
    
    # Test data_format_utils conversion
    try:
        converted_objects = await jsonld_to_graphobjects(jsonld_document)
        print(f"\n✅ data_format_utils.jsonld_to_graphobjects() successful!")
        print(f"Converted {len(converted_objects)} KGType GraphObjects:")
        for obj in converted_objects:
            print(f"  - {getattr(obj, 'name', 'N/A')}: {obj.URI}")
            print(f"    Class: {obj.get_class_uri()}")
        
        # Test conversion to RDF quads
        try:
            graph_id = "http://example.org/kgtype_graph"
            quads = await graphobjects_to_quads(converted_objects, graph_id)
            print(f"\n✅ KGType objects converted to {len(quads)} RDF quads")
            
        except Exception as e:
            print(f"\n❌ KGType graphobjects_to_quads() failed: {e}")
            import traceback
            traceback.print_exc()
            
    except Exception as e:
        print(f"\n❌ KGType jsonld_to_graphobjects() failed: {e}")
        import traceback
        traceback.print_exc()


async def test_comparison_with_native_vitalsigns():
    """Compare data_format_utils with native VitalSigns JSON-LD methods."""
    print("\n" + "=" * 60)
    print("Comparing data_format_utils vs Native VitalSigns JSON-LD")
    print("=" * 60)
    
    # Create test objects
    objects = create_simple_test_objects()
    print(f"Testing with {len(objects)} VITAL_Node objects")
    
    # Test 1: Native VitalSigns JSON-LD
    print(f"\n🔹 Native VitalSigns JSON-LD:")
    try:
        native_jsonld = VITAL_Node.to_jsonld_list(objects)
        print(f"✅ Native to_jsonld_list() successful!")
        print(f"Context keys: {list(native_jsonld.get('@context', {}).keys())}")
        print(f"Graph objects: {len(native_jsonld.get('@graph', []))}")
        
        # Round-trip with native methods
        reconstructed_native = VITAL_Node.from_jsonld_list(native_jsonld)
        print(f"✅ Native round-trip successful: {len(reconstructed_native)} objects")
        
    except Exception as e:
        print(f"❌ Native VitalSigns JSON-LD failed: {e}")
        native_jsonld = None
        reconstructed_native = []
    
    # Test 2: data_format_utils JSON-LD
    print(f"\n🔹 data_format_utils JSON-LD:")
    try:
        manual_jsonld = objects_to_manual_jsonld(objects)
        print(f"✅ Manual JSON-LD creation successful!")
        print(f"Context keys: {list(manual_jsonld.get('@context', {}).keys())}")
        print(f"Graph objects: {len(manual_jsonld.get('@graph', []))}")
        
        # Convert with data_format_utils
        converted_utils = await jsonld_to_graphobjects(manual_jsonld)
        print(f"✅ data_format_utils conversion successful: {len(converted_utils)} objects")
        
    except Exception as e:
        print(f"❌ data_format_utils JSON-LD failed: {e}")
        converted_utils = []
    
    # Compare results
    print(f"\n🔍 Comparison Results:")
    if native_jsonld and converted_utils:
        print(f"  Native VitalSigns: {len(reconstructed_native)} objects")
        print(f"  data_format_utils: {len(converted_utils)} objects")
        
        # Compare object properties
        if len(reconstructed_native) == len(converted_utils):
            print(f"  ✅ Object count matches")
            
            # Check first object details
            if reconstructed_native and converted_utils:
                native_obj = reconstructed_native[0]
                utils_obj = converted_utils[0]
                print(f"  First object comparison:")
                print(f"    Native URI: {native_obj.URI}")
                print(f"    Utils URI:  {utils_obj.URI}")
                print(f"    Native Name: {getattr(native_obj, 'name', 'N/A')}")
                print(f"    Utils Name:  {getattr(utils_obj, 'name', 'N/A')}")
                print(f"    Native Class: {native_obj.get_class_uri()}")
                print(f"    Utils Class:  {utils_obj.get_class_uri()}")
                
                if (native_obj.URI == utils_obj.URI and 
                    getattr(native_obj, 'name', None) == getattr(utils_obj, 'name', None) and
                    native_obj.get_class_uri() == utils_obj.get_class_uri()):
                    print(f"  ✅ Object properties match!")
                else:
                    print(f"  ⚠️  Object properties differ")
        else:
            print(f"  ⚠️  Object count mismatch")
    else:
        print(f"  ❌ Cannot compare due to conversion failures")


async def main():
    """Run all data_format_utils JSON-LD tests."""
    print("VitalGraph data_format_utils JSON-LD Test Suite")
    print("Testing local JSON-LD implementation with VitalSigns objects")
    print("=" * 80)
    
    try:
        # Test individual functions
        await test_simple_objects_data_format_utils()
        await test_complex_objects_data_format_utils()
        await test_kgtype_objects_data_format_utils()
        await test_comparison_with_native_vitalsigns()
        
        print("\n" + "=" * 60)
        print("✅ All data_format_utils tests completed!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Test suite failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
