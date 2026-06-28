#!/usr/bin/env python3
"""
Debug script to check if slot values are being stored correctly.
"""

import sys
sys.path.insert(0, '/Users/hadfield/Local/vital-git/vital-graph')

from vitalgraph.utils.test_data import create_vitalsigns_test_data
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGDoubleSlot import KGDoubleSlot

def debug_slot_values():
    """Debug slot values in test data."""
    print("🔍 Debugging slot values in test data...")
    
    # Create test data
    test_objects = create_vitalsigns_test_data()
    
    # Find postal code and salary slots
    postal_slots = []
    salary_slots = []
    
    for obj in test_objects:
        if isinstance(obj, KGTextSlot) and 'postal_code' in str(obj.URI):
            postal_slots.append(obj)
        elif isinstance(obj, KGDoubleSlot) and 'salary' in str(obj.URI):
            salary_slots.append(obj)
    
    print(f"\n📋 Found {len(postal_slots)} postal code slots:")
    for slot in postal_slots:
        print(f"  URI: {slot.URI}")
        print(f"  Name: {slot.name}")
        print(f"  Slot Type: {slot.kGSlotType}")
        print(f"  Text Value: {slot.textSlotValue}")
        print(f"  Text Value (str): {str(slot.textSlotValue) if slot.textSlotValue else 'None'}")
        print()
    
    print(f"📋 Found {len(salary_slots)} salary slots:")
    for slot in salary_slots:
        print(f"  URI: {slot.URI}")
        print(f"  Name: {slot.name}")
        print(f"  Slot Type: {slot.kGSlotType}")
        print(f"  Double Value: {slot.doubleSlotValue}")
        print(f"  Double Value (float): {float(slot.doubleSlotValue) if slot.doubleSlotValue else 'None'}")
        print()
    
    # Test RDF conversion
    if postal_slots:
        print("🔄 Testing RDF conversion for postal slot...")
        postal_slot = postal_slots[0]
        try:
            rdf_triples = postal_slot.to_rdf()
            print(f"RDF triples count: {len(rdf_triples)}")
            
            # Look for slot value triples
            value_triples = []
            for triple in rdf_triples:
                if 'hasTextSlotValue' in triple or 'textSlotValue' in triple or '10001' in triple:
                    value_triples.append(triple)
            
            print(f"Found {len(value_triples)} potential value triples:")
            for triple in value_triples[:5]:  # Show first 5
                print(f"  {triple}")
                
        except Exception as e:
            print(f"  Error converting to RDF: {e}")
    
    if salary_slots:
        print("🔄 Testing RDF conversion for salary slot...")
        salary_slot = salary_slots[0]
        try:
            rdf_triples = salary_slot.to_rdf()
            print(f"RDF triples count: {len(rdf_triples)}")
            
            # Look for slot value triples
            value_triples = []
            for triple in rdf_triples:
                if 'hasDoubleSlotValue' in triple or 'doubleSlotValue' in triple or '75000' in triple:
                    value_triples.append(triple)
            
            print(f"Found {len(value_triples)} potential value triples:")
            for triple in value_triples[:5]:  # Show first 5
                print(f"  {triple}")
                
        except Exception as e:
            print(f"  Error converting to RDF: {e}")

if __name__ == "__main__":
    debug_slot_values()
