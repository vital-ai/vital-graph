#!/usr/bin/env python3
"""
Test URIRef string conversion for hashing
"""

import os
import sys
import hashlib

# Add the parent directory to the path so we can import vitalgraph
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from rdflib import URIRef

def main():
    print("Testing URIRef string conversion for hashing...")
    print("=" * 50)
    
    # Test the exact same way as in wordnet_load.py
    GRAPH_NAME = 'wordnet'
    identifier = URIRef(f'http://vital.ai/graph/{GRAPH_NAME}')
    
    print(f'GRAPH_NAME: {GRAPH_NAME}')
    print(f'URIRef object: {identifier}')
    print(f'URIRef type: {type(identifier)}')
    print(f'URIRef str(): {str(identifier)}')
    print(f'URIRef repr(): {repr(identifier)}')
    
    # Test hashing with str() conversion (what VitalGraphSQLStore likely does)
    identifier_str = str(identifier)
    identifier_hash = hashlib.sha1(identifier_str.encode('utf8')).hexdigest()[:10]
    interned_id = f'kb_{identifier_hash}'
    
    print(f'\nString for hashing: "{identifier_str}"')
    print(f'Hash: {identifier_hash}')
    print(f'Interned ID: {interned_id}')
    print(f'Target: kb_bec6803d52')
    print(f'Match: {interned_id == "kb_bec6803d52"}')
    
    # Test other possible string representations
    print(f'\nTesting other string representations:')
    
    test_strings = [
        str(identifier),
        repr(identifier),
        identifier.toPython(),
        f'http://vital.ai/graph/{GRAPH_NAME}',  # Raw string
    ]
    
    target = 'bec6803d52'
    
    for i, test_str in enumerate(test_strings):
        try:
            test_hash = hashlib.sha1(test_str.encode('utf8')).hexdigest()[:10]
            test_interned = f'kb_{test_hash}'
            match = '✓ MATCH!' if test_hash == target else ''
            print(f'  {i+1}: "{test_str}" -> {test_hash} {match}')
        except Exception as e:
            print(f'  {i+1}: Error - {e}')
    
    # Let's also check what VitalGraphSQLStore.generate_interned_id actually does
    print(f'\nChecking VitalGraphSQLStore.generate_interned_id...')
    
    try:
        from vitalgraph.store.store import generate_interned_id
        
        # Test with URIRef object
        store_result1 = generate_interned_id(identifier)
        print(f'generate_interned_id(URIRef): {store_result1}')
        
        # Test with string
        store_result2 = generate_interned_id(str(identifier))
        print(f'generate_interned_id(str): {store_result2}')
        
        print(f'Target: kb_bec6803d52')
        print(f'URIRef match: {store_result1 == "kb_bec6803d52"}')
        print(f'String match: {store_result2 == "kb_bec6803d52"}')
        
    except Exception as e:
        print(f'Error testing generate_interned_id: {e}')

if __name__ == "__main__":
    main()
