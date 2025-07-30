#!/usr/bin/env python3
"""
Simple debug script to examine SPARQL algebra parsing.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from rdflib.plugins.sparql import prepareQuery

def debug_sparql_parsing():
    """Debug SPARQL parsing to see the algebra structure."""
    
    # Test a simple SPARQL query
    simple_query = """
    SELECT ?entity ?name WHERE {
        ?entity <http://vital.ai/ontology/vital-core#hasName> ?name .
    }
    LIMIT 5
    """
    
    print("=" * 60)
    print("DEBUGGING SPARQL PARSING")
    print("=" * 60)
    print(f"Original SPARQL query:")
    print(simple_query)
    print()
    
    # Parse the query
    prepared_query = prepareQuery(simple_query)
    algebra = prepared_query.algebra
    
    print("SPARQL Algebra:")
    print(f"  Algebra name: {algebra.name}")
    print(f"  Algebra structure: {algebra}")
    print()
    
    # Examine the structure
    if hasattr(algebra, 'p'):
        print("Pattern (p):")
        pattern = algebra.p
        print(f"  Pattern name: {pattern.name}")
        print(f"  Pattern structure: {pattern}")
        
        if hasattr(pattern, 'triples'):
            print(f"  Triples: {pattern.triples}")
        elif hasattr(pattern, 'p'):
            print(f"  Nested pattern: {pattern.p}")
            if hasattr(pattern.p, 'triples'):
                print(f"  Nested triples: {pattern.p.triples}")
    
    if hasattr(algebra, 'PV'):
        print(f"Projection Variables (PV): {algebra.PV}")
    
    print()

if __name__ == "__main__":
    debug_sparql_parsing()
