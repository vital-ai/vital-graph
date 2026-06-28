#!/usr/bin/env python3
"""
Test script to understand how VitalSigns property short names work.
"""

from ai_haley_kg_domain.model.KGEntity import KGEntity

# Create an instance
entity = KGEntity()

# Get domain properties
domain_props = entity.get_allowed_domain_properties()

print("Testing property short name extraction:")
print("=" * 60)

# Test a few properties
test_uris = [
    "http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI",
    "http://vital.ai/ontology/haley-ai-kg#hasKGEntityType",
    "http://vital.ai/ontology/vital-core#hasName",
    "http://vital.ai/ontology/vital-aimp#hasReferenceIdentifier"
]

for prop_uri in test_uris:
    print(f"\nProperty: {prop_uri}")
    
    # Find the property in domain_props
    prop_info = None
    for prop in domain_props:
        if prop.get('uri') == prop_uri:
            prop_info = prop
            break
    
    if not prop_info:
        print("  ❌ Not found in domain properties")
        continue
    
    print(f"  Property class: {prop_info.get('prop_class')}")
    print(f"  Property dict keys: {prop_info.keys()}")
    
    # Try to get the property from the entity instance
    try:
        # Extract the property name from URI (after the #)
        prop_name = prop_uri.split('#')[-1]
        
        # Try different ways to access the property
        if hasattr(entity, prop_name):
            prop_attr = getattr(entity, prop_name)
            print(f"  ✓ Has attribute '{prop_name}': {type(prop_attr)}")
            if hasattr(prop_attr, 'short_name'):
                print(f"    Short name attribute: {prop_attr.short_name}")
            if hasattr(prop_attr, 'get_short_name'):
                print(f"    get_short_name(): {prop_attr.get_short_name()}")
        
        # Try without 'has' prefix
        prop_name_no_has = prop_name.replace('has', '', 1) if prop_name.startswith('has') else prop_name
        # Make first letter lowercase
        prop_name_no_has = prop_name_no_has[0].lower() + prop_name_no_has[1:] if prop_name_no_has else prop_name_no_has
        
        if hasattr(entity, prop_name_no_has):
            prop_attr = getattr(entity, prop_name_no_has)
            print(f"  ✓ Has attribute '{prop_name_no_has}': {type(prop_attr)}")
            if hasattr(prop_attr, 'short_name'):
                print(f"    Short name attribute: {prop_attr.short_name}")
        
    except Exception as e:
        print(f"  ❌ Error accessing property: {e}")

print("\n" + "=" * 60)
print("Checking if properties have short_name in their definition:")

# Check the property class itself
for prop in domain_props[:5]:
    prop_uri = prop.get('uri', '')
    prop_class = prop.get('prop_class')
    print(f"\n{prop_uri}")
    print(f"  Class: {prop_class}")
    print(f"  Class attributes: {dir(prop_class) if prop_class else 'N/A'}")
    
    # Check if the property trait has a short_name class attribute
    if prop_class and hasattr(prop_class, 'short_name'):
        print(f"  ✓ Has short_name class attribute: {prop_class.short_name}")
