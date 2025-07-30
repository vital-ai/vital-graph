#!/usr/bin/env python3
"""
Reverse engineer the graph identifier by testing what produces bec6803d52
"""

import hashlib
import itertools
import string

def generate_interned_id(identifier):
    """Generate interned ID the same way VitalGraphSQLStore does"""
    identifier_hash = hashlib.sha1(identifier.encode("utf8")).hexdigest()[:10]
    return f"kb_{identifier_hash}"

def main():
    target_hash = "bec6803d52"
    target_interned_id = f"kb_{target_hash}"
    
    print(f"Reverse engineering graph identifier for: {target_interned_id}")
    print("=" * 60)
    
    # Since we know the data contains haley.ai entities, try variations around that
    base_patterns = [
        "http://vital.ai/haley.ai/chat-saas/",
        "http://vital.ai/haley.ai/",
        "haley.ai/chat-saas",
        "haley.ai",
        "chat-saas",
        "http://vital.ai/ontology/haley-ai-kg/",
        "http://vital.ai/ontology/haley-ai-kg",
        "haley-ai-kg",
        "http://vital.ai/graph/haley-ai-kg",
        "http://vital.ai/graph/chat-saas",
        "http://vital.ai/haley.ai/chat-saas/graph",
        "http://vital.ai/haley.ai/graph",
        "http://vital.ai/graph/haley.ai"
    ]
    
    # Test each base pattern
    print("Testing base patterns...")
    for pattern in base_patterns:
        generated_id = generate_interned_id(pattern)
        if generated_id == target_interned_id:
            print(f"✓ FOUND MATCH: {pattern}")
            return pattern
        else:
            print(f"  {pattern} -> {generated_id}")
    
    # Try with different suffixes/prefixes
    print("\nTesting with variations...")
    suffixes = ["", "/", "#", "/graph", "/wordnet", "/kg", "/data"]
    prefixes = ["", "http://", "https://", "urn:", "vital:"]
    
    test_bases = [
        "vital.ai/haley.ai/chat-saas",
        "haley.ai/chat-saas",
        "vital.ai/graph/wordnet",
        "vital.ai/haley.ai",
        "haley.ai/wordnet"
    ]
    
    for base in test_bases:
        for prefix in prefixes:
            for suffix in suffixes:
                test_id = f"{prefix}{base}{suffix}"
                generated_id = generate_interned_id(test_id)
                if generated_id == target_interned_id:
                    print(f"✓ FOUND MATCH: {test_id}")
                    return test_id
    
    # If still not found, try a more systematic approach
    print("\nTrying systematic variations of known working identifier...")
    
    # We know http://vital.ai/graph/wordnet generates kb_5e9e5feadf
    # Let's try small modifications
    base = "http://vital.ai/graph/wordnet"
    
    modifications = [
        base.replace("wordnet", "haley"),
        base.replace("wordnet", "chat-saas"),
        base.replace("wordnet", "kg"),
        base.replace("graph", "haley.ai"),
        base.replace("graph/wordnet", "haley.ai/chat-saas"),
        base.replace("vital.ai", "haley.ai"),
        "http://haley.ai/chat-saas/wordnet",
        "http://haley.ai/graph/wordnet",
        "http://vital.ai/haley.ai/wordnet"
    ]
    
    for mod in modifications:
        generated_id = generate_interned_id(mod)
        if generated_id == target_interned_id:
            print(f"✓ FOUND MATCH: {mod}")
            return mod
        else:
            print(f"  {mod} -> {generated_id}")
    
    print(f"\n❌ Could not reverse engineer the identifier")
    print(f"The identifier that generates {target_hash} is not in our test patterns")
    
    # As a last resort, suggest using the interned ID directly
    print(f"\n💡 Alternative solution:")
    print(f"Instead of finding the original identifier, we can:")
    print(f"1. Modify the scripts to use interned ID 'bec6803d52' directly")
    print(f"2. Or create a custom store that points to the correct tables")
    
    return None

if __name__ == "__main__":
    result = main()
    if result:
        print(f"\n🎉 SUCCESS: Use graph identifier '{result}' in your scripts")
    else:
        print(f"\n⚠️  Consider alternative approaches to access the data")
