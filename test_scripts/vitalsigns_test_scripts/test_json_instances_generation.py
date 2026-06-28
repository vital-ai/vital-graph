#!/usr/bin/env python3
"""
Test script for JSON instances generation from OWL individuals.

This script demonstrates how to use the VitalSignsJSONSchemaGenerator
to generate JSON instances from OWL individuals in loaded ontologies.
"""

import os
import json
import logging
from pathlib import Path
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns_generate.generate.json_schema_generator import VitalSignsJSONSchemaGenerator

def main():
    """Test JSON instances generation for loaded ontologies."""
    
    print("=== VitalSigns JSON Instances Generation Test ===")
    
    # Initialize VitalSigns
    print("Initializing VitalSigns...")
    vs = VitalSigns()
    
    # Get loaded ontologies
    ontology_manager = vs.get_ontology_manager()
    loaded_ontologies = ontology_manager.get_ontology_iri_list()
    
    print(f"Found {len(loaded_ontologies)} loaded ontologies:")
    for i, iri in enumerate(loaded_ontologies, 1):
        print(f"  {i}. {iri}")
    
    # Create output directory
    output_dir = Path("/Users/hadfield/Local/vital-git/vital-graph/domain_schema")
    output_dir.mkdir(exist_ok=True)
    print(f"Output directory: {output_dir.absolute()}")
    
    # Initialize JSON Schema Generator
    generator = VitalSignsJSONSchemaGenerator()
    
    # Generate instances for all loaded ontologies
    generated_files = []
    
    for ontology_iri in loaded_ontologies:
        try:
            print(f"\n=== Detailed Test: {ontology_iri} ===")
            
            instances_path = generator.generate_json_instances_for_ontology(
                ontology_iri, 
                str(output_dir)
            )
            
            generated_files.append(instances_path)
            print(f"  ✓ Generated: {instances_path}")
            
            # Validate the generated instances
            validate_generated_instances(instances_path)
            
        except Exception as e:
            print(f"  ✗ Error generating instances for {ontology_iri}: {e}")
            import traceback
            traceback.print_exc()
    
    # Summary
    print(f"\n=== Generation Complete ===")
    print(f"Successfully generated {len(generated_files)} instance files:")
    for file_path in generated_files:
        if os.path.exists(file_path):
            file_size = Path(file_path).stat().st_size
            line_count = count_jsonl_lines(file_path)
            print(f"  - {file_path} ({file_size:,} bytes, {line_count} instances)")
        else:
            print(f"  - {file_path} (file not found)")

def validate_generated_instances(instances_path: str):
    """Validate that the generated JSONL file has proper structure."""
    
    vs = VitalSigns()
    
    try:
        line_count = 0
        valid_count = 0
        instance_types = set()
        
        with open(instances_path, 'r') as f:
            for line in f:
                line_count += 1
                line = line.strip()
                if line:
                    try:
                        # Parse JSON line into GraphObject via VitalSigns
                        json_data = json.loads(line)
                        objects = vs.from_json_list([json_data])
                        
                        if objects and len(objects) > 0:
                            obj = objects[0]
                            valid_count += 1
                            obj_type = type(obj).__name__
                            instance_types.add(obj_type)
                            if line_count <= 3:  # Show first few instances
                                print(f"    ✓ Valid instance: {obj_type}")
                                print(f"      URI: {obj.URI}")
                        else:
                            print(f"    ⚠ Could not parse GraphObject from line {line_count}")
                            
                    except json.JSONDecodeError as e:
                        print(f"    ✗ Invalid JSON on line {line_count}: {e}")
                    except Exception as e:
                        print(f"    ⚠ Failed to parse line {line_count}: {e}")
        
        print(f"    ✓ Processed {line_count} lines, {valid_count} valid GraphObject instances")
        print(f"    ✓ Found {len(instance_types)} different instance types:")
        for obj_type in sorted(list(instance_types)[:5]):  # Show first 5 types
            print(f"      - {obj_type}")
        if len(instance_types) > 5:
            print(f"      ... and {len(instance_types) - 5} more types")
        
    except Exception as e:
        print(f"    ✗ Validation error: {e}")

def count_jsonl_lines(file_path: str) -> int:
    """Count non-empty lines in JSONL file."""
    try:
        with open(file_path, 'r') as f:
            return sum(1 for line in f if line.strip())
    except:
        return 0

def test_specific_ontology():
    """Test with a specific ontology if available."""
    
    print("\n=== Testing Specific Ontology ===")
    
    # Test with vital-core if available
    generator = VitalSignsJSONSchemaGenerator()
    output_dir = Path("./generated_instances")
    output_dir.mkdir(exist_ok=True)
    
    test_ontologies = [
        # "http://vital.ai/ontology/vital-core#",
        # "http://vital.ai/ontology/haley-ai-kg#"
        "http://vital.ai/ontology/chat-ai#"
    ]
    
    for ontology_uri in test_ontologies:
        try:
            print(f"\nTesting {ontology_uri}...")
            
            instances_path = generator.generate_json_instances_for_ontology(
                ontology_uri,
                str(output_dir)
            )
            
            # Load and inspect a few instances
            with open(instances_path, 'r') as f:
                lines = f.readlines()
                
            print(f"Generated {len(lines)} instances")
            
            # Show first instance details
            if lines:
                vs = VitalSigns()
                first_json = json.loads(lines[0].strip())
                first_objects = vs.from_json_list([first_json])
                if first_objects:
                    first_obj = first_objects[0]
                    print(f"First instance:")
                    print(f"  Type: {type(first_obj).__name__}")
                    print(f"  URI: {first_obj.URI}")
            
        except Exception as e:
            print(f"Test failed for {ontology_uri}: {e}")

if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
    
    try:
        main()
        test_specific_ontology()
    except Exception as e:
        print(f"Test script failed: {e}")
        import traceback
        traceback.print_exc()
