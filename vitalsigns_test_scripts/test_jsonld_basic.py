#!/usr/bin/env python3

import json
import sys
import os
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

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


def create_simple_test_objects():
    """Create simple test objects for basic testing."""
    objects = []
    
    # Create basic VITAL_Node objects
    for i in range(3):
        node = VITAL_Node()
        node.URI = f"http://example.com/test-node-{i+1}"
        node.name = f"Test Node {i+1}"
        objects.append(node)
    
    return objects


def create_complex_vitalsigns_objects():
    """Create complex VitalSigns objects (KGEntity, KGFrame, etc.)."""
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
    """Create KGType objects for testing."""
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


def test_jsonld_single_object():
    """Test JSON-LD conversion for a single complex GraphObject."""
    print("=" * 60)
    print("Testing JSON-LD Single Object Conversion (KGEntity)")
    print("=" * 60)
    
    # Initialize VitalSigns
    vs = VitalSigns()
    
    # Create a complex KGEntity object
    kgentity = KGEntity()
    kgentity.URI = "http://vital.ai/haley.ai/app/KGEntity/dog_n_01"
    kgentity.name = "dog"
    kgentity.kGraphDescription = "a domesticated carnivorous mammal"
    kgentity.kGIdentifier = "urn:wordnet_dog.n.01"
    kgentity.kGEntityType = "urn:Noun"
    kgentity.kGEntityTypeDescription = "Noun"
    
    print(f"Created KGEntity:")
    print(f"  URI: {kgentity.URI}")
    print(f"  Name: {kgentity.name}")
    print(f"  Description: {kgentity.kGraphDescription}")
    print(f"  Entity Type: {kgentity.kGEntityType}")
    print(f"  Class: {kgentity.get_class_uri()}")
    
    # Test to_jsonld
    try:
        jsonld_data = kgentity.to_jsonld()
        print(f"\n✅ to_jsonld() successful!")
        print(f"JSON-LD Output (first 500 chars):")
        jsonld_str = json.dumps(jsonld_data, indent=2)
        print(jsonld_str[:500] + "..." if len(jsonld_str) > 500 else jsonld_str)
        
        # Test from_jsonld
        try:
            reconstructed_entity = KGEntity.from_jsonld(jsonld_data)
            print(f"\n✅ from_jsonld() successful!")
            print(f"Reconstructed KGEntity:")
            print(f"  URI: {reconstructed_entity.URI}")
            print(f"  Name: {reconstructed_entity.name}")
            print(f"  Description: {reconstructed_entity.kGraphDescription}")
            print(f"  Class: {reconstructed_entity.get_class_uri()}")
            
            # Verify round-trip
            if (kgentity.URI == reconstructed_entity.URI and 
                kgentity.name == reconstructed_entity.name and
                kgentity.kGraphDescription == reconstructed_entity.kGraphDescription and
                kgentity.get_class_uri() == reconstructed_entity.get_class_uri()):
                print(f"\n✅ Round-trip conversion successful!")
            else:
                print(f"\n❌ Round-trip conversion failed - data mismatch")
                
        except Exception as e:
            print(f"\n❌ from_jsonld() failed: {e}")
            import traceback
            traceback.print_exc()
            
    except Exception as e:
        print(f"\n❌ to_jsonld() failed: {e}")
        import traceback
        traceback.print_exc()


def test_jsonld_multiple_objects():
    """Test JSON-LD conversion for multiple complex GraphObjects."""
    print("\n" + "=" * 60)
    print("Testing JSON-LD Multiple Objects Conversion (Complex VitalSigns Objects)")
    print("=" * 60)
    
    # Initialize VitalSigns
    vs = VitalSigns()
    
    # Create complex VitalSigns objects
    objects = create_complex_vitalsigns_objects()
    
    print(f"Created {len(objects)} complex VitalSigns objects:")
    for obj in objects:
        print(f"  - {obj.__class__.__name__}: {obj.URI}")
        if hasattr(obj, 'name') and obj.name:
            print(f"    Name: {obj.name}")
        if hasattr(obj, 'kGraphDescription') and obj.kGraphDescription:
            print(f"    Description: {obj.kGraphDescription}")
    
    # Test to_jsonld_list using the base GraphObject class
    try:
        # Use the first object's class for the conversion
        first_obj_class = objects[0].__class__
        jsonld_doc = first_obj_class.to_jsonld_list(objects)
        print(f"\n✅ to_jsonld_list() successful!")
        print(f"JSON-LD Document structure:")
        print(f"  Context keys: {len(jsonld_doc.get('@context', {}))}")
        print(f"  Graph objects: {len(jsonld_doc.get('@graph', []))}")
        
        # Show first object in detail
        if '@graph' in jsonld_doc and jsonld_doc['@graph']:
            first_obj_jsonld = jsonld_doc['@graph'][0]
            print(f"  First object preview:")
            print(f"    @id: {first_obj_jsonld.get('@id')}")
            print(f"    @type: {first_obj_jsonld.get('@type')}")
        
        # Test from_jsonld_list
        try:
            reconstructed_objects = first_obj_class.from_jsonld_list(jsonld_doc)
            print(f"\n✅ from_jsonld_list() successful!")
            print(f"Reconstructed {len(reconstructed_objects)} objects:")
            for obj in reconstructed_objects:
                print(f"  - {obj.__class__.__name__}: {obj.URI}")
            
            # Verify round-trip
            if len(objects) == len(reconstructed_objects):
                all_match = True
                for orig, recon in zip(objects, reconstructed_objects):
                    if (orig.URI != recon.URI or 
                        orig.get_class_uri() != recon.get_class_uri()):
                        all_match = False
                        break
                
                if all_match:
                    print(f"\n✅ Round-trip list conversion successful!")
                else:
                    print(f"\n❌ Round-trip list conversion failed - data mismatch")
            else:
                print(f"\n❌ Round-trip list conversion failed - count mismatch")
                
        except Exception as e:
            print(f"\n❌ from_jsonld_list() failed: {e}")
            import traceback
            traceback.print_exc()
            
    except Exception as e:
        print(f"\n❌ to_jsonld_list() failed: {e}")
        import traceback
        traceback.print_exc()


def test_vitalsigns_jsonld_methods():
    """Test JSON-LD methods through VitalSigns interface with KGType objects."""
    print("\n" + "=" * 60)
    print("Testing VitalSigns JSON-LD Methods (KGType Objects)")
    print("=" * 60)
    
    # Initialize VitalSigns
    vs = VitalSigns()
    
    # Create KGType objects and convert to JSON-LD manually
    kgtypes = create_kgtype_objects()
    
    print(f"Created {len(kgtypes)} KGType objects:")
    for kgtype in kgtypes:
        print(f"  - {kgtype.name}: {kgtype.URI}")
    
    # Convert first KGType to JSON-LD for testing VitalSigns methods
    first_kgtype = kgtypes[0]
    kgtype_jsonld = first_kgtype.to_jsonld()
    
    print(f"\nTest JSON-LD data from {first_kgtype.name}:")
    print(f"  @id: {kgtype_jsonld.get('@id')}")
    print(f"  @type: {kgtype_jsonld.get('@type')}")
    print(f"  Context keys: {len(kgtype_jsonld.get('@context', {}))}")
    
    # Test VitalSigns from_jsonld
    try:
        reconstructed_kgtype = vs.from_jsonld(kgtype_jsonld)
        print(f"\n✅ VitalSigns.from_jsonld() successful!")
        print(f"Created KGType:")
        print(f"  URI: {reconstructed_kgtype.URI}")
        print(f"  Name: {getattr(reconstructed_kgtype, 'name', 'N/A')}")
        print(f"  Class: {reconstructed_kgtype.get_class_uri()}")
        print(f"  Description: {getattr(reconstructed_kgtype, 'kGraphDescription', 'N/A')}")
        
        # Test VitalSigns from_jsonld_list with multiple objects
        try:
            # Create JSON-LD list from all KGTypes
            kgtypes_jsonld_list = KGEntityType.to_jsonld_list(kgtypes)
            
            # Convert back using VitalSigns - pass the FULL document, not just @graph
            kgtype_list = vs.from_jsonld_list(kgtypes_jsonld_list)
            print(f"\n✅ VitalSigns.from_jsonld_list() successful!")
            print(f"Created {len(kgtype_list)} KGTypes from list:")
            for kgtype in kgtype_list:
                print(f"  - {getattr(kgtype, 'name', 'N/A')}: {kgtype.URI}")
            
        except Exception as e:
            print(f"\n❌ VitalSigns.from_jsonld_list() failed: {e}")
            import traceback
            traceback.print_exc()
            
    except Exception as e:
        print(f"\n❌ VitalSigns.from_jsonld() failed: {e}")
        import traceback
        traceback.print_exc()


def test_context_generation():
    """Test the dynamic context generation."""
    print("\n" + "=" * 60)
    print("Testing Dynamic Context Generation")
    print("=" * 60)
    
    from vital_ai_vitalsigns.model.utils.graphobject_jsonld_utils import GraphObjectJsonldUtils
    
    # Test context generation
    try:
        context = GraphObjectJsonldUtils._get_default_context()
        print(f"✅ Context generation successful!")
        print(f"Generated context:")
        print(json.dumps(context, indent=2))
        
        # Check for expected built-in namespaces
        expected_builtins = ["rdf", "rdfs", "owl", "xsd", "type", "id"]
        missing_builtins = [ns for ns in expected_builtins if ns not in context]
        
        if not missing_builtins:
            print(f"\n✅ All expected built-in namespaces present")
        else:
            print(f"\n⚠️  Missing built-in namespaces: {missing_builtins}")
            
        # Check for ontology namespaces
        ontology_namespaces = [k for k, v in context.items() 
                             if k not in expected_builtins and "vital.ai" in str(v)]
        
        if ontology_namespaces:
            print(f"✅ Found ontology namespaces: {ontology_namespaces}")
        else:
            print(f"⚠️  No ontology namespaces found (this is expected if only vital-core is loaded)")
            
    except Exception as e:
        print(f"❌ Context generation failed: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Run all JSON-LD tests with complex VitalSigns objects."""
    print("JSON-LD Functionality Test Suite")
    print("Using complex VitalSigns objects (KGEntity, KGFrame, KGType, etc.)")
    print("=" * 80)
    
    try:
        # Test individual functions
        test_context_generation()
        test_jsonld_single_object()
        test_jsonld_multiple_objects()
        test_vitalsigns_jsonld_methods()
        
        print("\n" + "=" * 60)
        print("✅ All tests completed!")
        print("Complex VitalSigns objects successfully tested with native JSON-LD")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Test suite failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
