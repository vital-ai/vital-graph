#!/usr/bin/env python3

"""
Discover and document properties of KG classes from vital-ai-haley-kg.

This script uses VitalSigns to discover available properties for:
- KGEntity
- KGFrame  
- KGSlot subclasses
- hasFrame and hasSlot edge classes
"""

import sys
import os
from typing import Dict, List, Any
import json

# Add the parent directory to the path so we can import vitalgraph
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vital_ai_vitalsigns.impl.vitalsigns_impl import VitalSignsImpl

def get_class_properties(class_obj) -> Dict[str, Any]:
    """Get all available properties for a VitalSigns class using VitalSigns API."""
    try:
        # Create an instance to get domain properties
        instance = class_obj()
        domain_props = instance.get_allowed_domain_properties()
        
        properties = {}
        for prop in domain_props:
            prop_uri = prop.get('uri', '')
            prop_class = prop.get('prop_class', '')
            prop_class_name = prop_class.__name__ if hasattr(prop_class, '__name__') else str(prop_class)
            
            # Get short name using VitalSigns official API
            short_name = None
            local_name = None
            try:
                # Get the property trait class from the URI
                trait_class = VitalSignsImpl.get_trait_class_from_uri(prop_uri)
                
                if trait_class:
                    # Use the trait class's methods to get the proper names
                    short_name = trait_class.get_short_name()  # Follows naming convention (e.g., "hasName" -> "name")
                    local_name = trait_class.local_name  # Original name like "hasName"
                    
            except Exception as e:
                # Silently continue if we can't get trait class
                pass
            
            properties[prop_uri] = {
                'short_name': short_name,
                'local_name': local_name,
                'property_class': prop_class_name,
                'uri': prop_uri
            }
        
        return properties
    except Exception as e:
        print(f"Error getting properties for {class_obj.__name__}: {e}")
        return {}

def discover_kg_classes():
    """Discover all KG classes and their properties."""
    
    print("🔍 Discovering KG Classes and Properties")
    print("=" * 50)
    
    classes_info = {}
    
    # KGEntity
    print("\n📋 Discovering KGEntity properties...")
    try:
        from ai_haley_kg_domain.model.KGEntity import KGEntity
        classes_info['KGEntity'] = {
            'class_name': 'KGEntity',
            'module': 'ai_haley_kg_domain.model.KGEntity',
            'vitaltype': 'http://vital.ai/ontology/haley-ai-kg#KGEntity',
            'properties': get_class_properties(KGEntity)
        }
        print(f"   Found {len(classes_info['KGEntity']['properties'])} properties")
    except Exception as e:
        print(f"   ❌ Error with KGEntity: {e}")
    
    # KGFrame
    print("\n📋 Discovering KGFrame properties...")
    try:
        from ai_haley_kg_domain.model.KGFrame import KGFrame
        classes_info['KGFrame'] = {
            'class_name': 'KGFrame',
            'module': 'ai_haley_kg_domain.model.KGFrame',
            'vitaltype': 'http://vital.ai/ontology/haley-ai-kg#KGFrame',
            'properties': get_class_properties(KGFrame)
        }
        print(f"   Found {len(classes_info['KGFrame']['properties'])} properties")
    except Exception as e:
        print(f"   ❌ Error with KGFrame: {e}")
    
    # KGSlot and subclasses
    print("\n📋 Discovering KGSlot subclasses...")
    slot_classes = [
        'KGSlot', 'KGAudioSlot', 'KGBooleanSlot', 'KGChoiceOptionSlot', 'KGChoiceSlot',
        'KGCodeSlot', 'KGCurrencySlot', 'KGDateTimeSlot', 'KGDoubleSlot', 'KGEntitySlot',
        'KGFileUploadSlot', 'KGGeoLocationSlot', 'KGImageSlot', 'KGIntegerSlot', 'KGJSONSlot',
        'KGLongSlot', 'KGLongTextSlot', 'KGMultiChoiceOptionSlot', 'KGMultiChoiceSlot',
        'KGMultiTaxonomyOptionSlot', 'KGMultiTaxonomySlot', 'KGPropertySlot', 'KGRunSlot',
        'KGTaxonomyOptionSlot', 'KGTaxonomySlot', 'KGTextSlot', 'KGURISlot', 'KGVideoSlot'
    ]
    
    for slot_class_name in slot_classes:
        try:
            module = __import__(f'ai_haley_kg_domain.model.{slot_class_name}', fromlist=[slot_class_name])
            slot_class = getattr(module, slot_class_name)
            
            # Create instance to get vitaltype
            instance = slot_class()
            vitaltype = f"http://vital.ai/ontology/haley-ai-kg#{slot_class_name}"
            
            classes_info[slot_class_name] = {
                'class_name': slot_class_name,
                'module': f'ai_haley_kg_domain.model.{slot_class_name}',
                'vitaltype': vitaltype,
                'properties': get_class_properties(slot_class)
            }
            print(f"   {slot_class_name}: {len(classes_info[slot_class_name]['properties'])} properties")
            
        except Exception as e:
            print(f"   ❌ Error with {slot_class_name}: {e}")
    
    # Edge classes
    print("\n📋 Discovering Edge classes...")
    edge_classes = ['Edge_hasKGFrame', 'Edge_hasKGSlot', 'Edge_hasKGEdge']
    
    for edge_class_name in edge_classes:
        try:
            module = __import__(f'ai_haley_kg_domain.model.{edge_class_name}', fromlist=[edge_class_name])
            edge_class = getattr(module, edge_class_name)
            
            # Create instance to get vitaltype
            instance = edge_class()
            vitaltype = f"http://vital.ai/ontology/haley-ai-kg#{edge_class_name}"
            
            classes_info[edge_class_name] = {
                'class_name': edge_class_name,
                'module': f'ai_haley_kg_domain.model.{edge_class_name}',
                'vitaltype': vitaltype,
                'properties': get_class_properties(edge_class)
            }
            print(f"   {edge_class_name}: {len(classes_info[edge_class_name]['properties'])} properties")
            
        except Exception as e:
            print(f"   ❌ Error with {edge_class_name}: {e}")
    
    return classes_info

def generate_markdown_documentation(classes_info: Dict[str, Any]) -> str:
    """Generate comprehensive markdown documentation."""
    
    md_content = """# KG Classes Properties Documentation

This document provides comprehensive information about the properties available for Knowledge Graph (KG) classes in the vital-ai-haley-kg package.

## Overview

The KG classes are defined in the `vital-ai-haley-kg` package version 0.1.24. This documentation was generated using VitalSigns to discover all available properties for each class.

## VitalSigns Object Creation and Quad Conversion

### Creating VitalSigns Objects and Converting to Quads

```python
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from vitalgraph.utils.quad_format_utils import graphobjects_to_quad_list, quad_list_to_graphobjects

# Create objects directly
entity = KGEntity()
entity.URI = "http://example.org/entity1"
entity.name = "Test Entity"

slot = KGTextSlot()
slot.URI = "http://example.org/slot1"
slot.name = "Test Slot"
slot.kGTextSlotValue = "Test Text Value"

# Convert to quads (wire format)
quads = graphobjects_to_quad_list([entity, slot])

# Convert quads back to GraphObjects
objects = quad_list_to_graphobjects(quads)
```

### Setting Grouping URIs

```python
def set_grouping_uris(objects: list, entity_uri: str):
    \"\"\"Set hasKGGraphURI grouping property on all objects.\"\"\"
    for obj in objects:
        try:
            # Use short name property access - hasKGGraphURI short name is 'kGGraphURI'
            obj.kGGraphURI = entity_uri
        except Exception as e:
            print(f"Failed to set kGGraphURI on object {obj.URI}: {e}")
```

## Class Properties

"""
    
    # Sort classes by type
    entities = []
    frames = []
    slots = []
    edges = []
    
    for class_name, class_info in classes_info.items():
        if 'Entity' in class_name:
            entities.append((class_name, class_info))
        elif 'Frame' in class_name:
            frames.append((class_name, class_info))
        elif 'Slot' in class_name:
            slots.append((class_name, class_info))
        elif 'Edge' in class_name:
            edges.append((class_name, class_info))
    
    # Generate documentation for each category
    categories = [
        ("Entity Classes", entities),
        ("Frame Classes", frames), 
        ("Slot Classes", slots),
        ("Edge Classes", edges)
    ]
    
    for category_name, category_classes in categories:
        if not category_classes:
            continue
            
        md_content += f"\n### {category_name}\n\n"
        
        for class_name, class_info in sorted(category_classes):
            md_content += f"#### {class_name}\n\n"
            md_content += f"- **Module**: `{class_info['module']}`\n"
            md_content += f"- **VitalType**: `{class_info['vitaltype']}`\n"
            md_content += f"- **Properties**: {len(class_info['properties'])}\n\n"
            
            if class_info['properties']:
                md_content += "**Available Properties:**\n\n"
                
                # Group properties by namespace
                vital_props = []
                haley_props = []
                vital_aimp_props = []
                other_props = []
                
                for prop_uri, prop_info in sorted(class_info['properties'].items()):
                    if 'vital-core' in prop_uri:
                        vital_props.append((prop_uri, prop_info))
                    elif 'haley-ai-kg' in prop_uri:
                        haley_props.append((prop_uri, prop_info))
                    elif 'vital-aimp' in prop_uri:
                        vital_aimp_props.append((prop_uri, prop_info))
                    else:
                        other_props.append((prop_uri, prop_info))
                
                # Vital Core properties
                if vital_props:
                    md_content += "**Vital Core Properties:**\n\n"
                    for prop_uri, prop_info in vital_props:
                        short_name = prop_info.get('short_name', 'None')
                        local_name = prop_info.get('local_name', 'N/A')
                        prop_class = prop_info.get('property_class', 'Unknown')
                        md_content += f"- `{prop_uri}`\n"
                        md_content += f"  - Local name: `{local_name}`\n"
                        md_content += f"  - Short name: `{short_name}`\n"
                        md_content += f"  - Type: `{prop_class}`\n\n"
                
                # Haley KG properties
                if haley_props:
                    md_content += "**Haley KG Properties:**\n\n"
                    for prop_uri, prop_info in haley_props:
                        short_name = prop_info.get('short_name', 'None')
                        local_name = prop_info.get('local_name', 'N/A')
                        prop_class = prop_info.get('property_class', 'Unknown')
                        md_content += f"- `{prop_uri}`\n"
                        md_content += f"  - Local name: `{local_name}`\n"
                        md_content += f"  - Short name: `{short_name}`\n"
                        md_content += f"  - Type: `{prop_class}`\n\n"
                
                # Vital AIMP properties (including referenceIdentifier)
                if vital_aimp_props:
                    md_content += "**Vital AIMP Properties:**\n\n"
                    for prop_uri, prop_info in vital_aimp_props:
                        short_name = prop_info.get('short_name', 'None')
                        local_name = prop_info.get('local_name', 'N/A')
                        prop_class = prop_info.get('property_class', 'Unknown')
                        md_content += f"- `{prop_uri}`\n"
                        md_content += f"  - Local name: `{local_name}`\n"
                        md_content += f"  - Short name: `{short_name}`\n"
                        md_content += f"  - Type: `{prop_class}`\n\n"
                
                # Other properties
                if other_props:
                    md_content += "**Other Properties:**\n\n"
                    for prop_uri, prop_info in other_props[:10]:  # Limit to first 10
                        short_name = prop_info.get('short_name', 'None')
                        local_name = prop_info.get('local_name', 'N/A')
                        prop_class = prop_info.get('property_class', 'Unknown')
                        md_content += f"- `{prop_uri}`\n"
                        md_content += f"  - Local name: `{local_name}`\n"
                        md_content += f"  - Short name: `{short_name}`\n"
                        md_content += f"  - Type: `{prop_class}`\n\n"
                    
                    if len(other_props) > 10:
                        md_content += f"... and {len(other_props) - 10} more properties\n\n"
            
            md_content += "---\n\n"
    
    # Add summary
    md_content += "\n## Summary\n\n"
    md_content += f"- **Total Classes Documented**: {len(classes_info)}\n"
    md_content += f"- **Entity Classes**: {len(entities)}\n"
    md_content += f"- **Frame Classes**: {len(frames)}\n"
    md_content += f"- **Slot Classes**: {len(slots)}\n"
    md_content += f"- **Edge Classes**: {len(edges)}\n\n"
    
    md_content += "This documentation was generated automatically using VitalSigns property discovery.\n"
    
    return md_content

def main():
    """Main function to discover properties and generate documentation."""
    
    print("🚀 Starting KG Classes Property Discovery")
    print("=" * 60)
    
    try:
        # Discover all classes and their properties
        classes_info = discover_kg_classes()
        
        if not classes_info:
            print("❌ No classes discovered!")
            return
        
        print(f"\n✅ Successfully discovered {len(classes_info)} classes")
        
        # Generate markdown documentation
        print("\n📝 Generating markdown documentation...")
        md_content = generate_markdown_documentation(classes_info)
        
        # Write to file
        output_file = "/Users/hadfield/Local/vital-git/vital-graph/planning/kg_classes_properties.md"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(md_content)
        
        print(f"✅ Documentation written to: {output_file}")
        
        # Also save raw data as JSON for reference
        json_file = "/Users/hadfield/Local/vital-git/vital-graph/planning/kg_classes_properties.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(classes_info, f, indent=2, default=str)
        
        print(f"✅ Raw data saved to: {json_file}")
        
        print("\n🎉 Property discovery and documentation generation completed!")
        
    except Exception as e:
        print(f"❌ Error during property discovery: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
