#!/usr/bin/env python3

"""Extract slot value properties from the generated JSON data."""

import json
import sys
import os

def extract_slot_value_properties():
    """Extract and display slot value properties."""
    
    json_file = "/Users/hadfield/Local/vital-git/vital-graph/planning/kg_classes_properties.json"
    
    try:
        with open(json_file, 'r') as f:
            data = json.load(f)
        
        print("🔍 KGSlot Subclasses and Their Value Properties")
        print("=" * 60)
        
        slot_value_properties = {}
        
        for class_name, class_info in data.items():
            if 'Slot' in class_name and class_name != 'KGSlot':
                # Look for value properties
                value_props = []
                for prop_uri, prop_info in class_info['properties'].items():
                    if 'SlotValue' in prop_uri:
                        value_props.append({
                            'uri': prop_uri,
                            'type': prop_info['property_class'],
                            'short_name': prop_uri.split('#')[-1]
                        })
                
                if value_props:
                    slot_value_properties[class_name] = value_props
        
        # Display results
        print(f"\nFound {len(slot_value_properties)} slot classes with value properties:\n")
        
        for class_name, value_props in sorted(slot_value_properties.items()):
            print(f"**{class_name}**")
            for prop in value_props:
                print(f"  - Property: `{prop['short_name']}`")
                print(f"  - URI: `{prop['uri']}`")
                print(f"  - Type: `{prop['type']}`")
            print()
        
        # Generate markdown table
        print("\n## Markdown Table for Documentation\n")
        print("| Slot Class | Value Property | Property Type | Full URI |")
        print("|------------|----------------|---------------|----------|")
        
        for class_name, value_props in sorted(slot_value_properties.items()):
            for prop in value_props:
                print(f"| {class_name} | `{prop['short_name']}` | {prop['type']} | `{prop['uri']}` |")
        
        return slot_value_properties
        
    except Exception as e:
        print(f"Error: {e}")
        return {}

if __name__ == "__main__":
    extract_slot_value_properties()
