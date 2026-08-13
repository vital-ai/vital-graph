#!/usr/bin/env python3
"""
Debug script to isolate the duplicate table alias issue in CONSTRUCT queries.
"""

import sys
import os
sys.path.append('/Users/hadfield/Local/vital-git/vital-graph')

from rdflib.plugins.sparql.parser import parseQuery
from rdflib.plugins.sparql.algebra import translateQuery
from rdflib import Variable, URIRef

# Import the SPARQL modules
from vitalgraph.db.postgresql.sparql.postgresql_sparql_core import (
    AliasGenerator, TableConfig, TranslationContext
)
from vitalgraph.db.postgresql.sparql.postgresql_sparql_cache_integration import (
    generate_bgp_sql_with_cache
)

def test_duplicate_aliases():
    """Test if BGP generation creates duplicate aliases for multiple triples."""
    
    print("=== Duplicate Alias Debug Test ===")
    
    # Create test components
    alias_gen = AliasGenerator()
    table_config = TableConfig(
        quad_table="vitalgraph1__vitalgraph1_space_id__rdf_quad",
        term_table="vitalgraph1__vitalgraph1_space_id__term",
        graph_table="vitalgraph1__vitalgraph1_space_id__graph"
    )
    
    # Create two triples like in the CONSTRUCT query
    triples = [
        (Variable('entity'), URIRef('http://vital.ai/ontology/hasChatName'), Variable('name')),
        (Variable('entity'), Variable('prop'), Variable('value'))
    ]
    
    print(f"Testing BGP with {len(triples)} triples:")
    for i, triple in enumerate(triples):
        print(f"  Triple {i}: {triple}")
    
    # Test alias generation directly
    print(f"\nTesting AliasGenerator directly:")
    print(f"  First call: {alias_gen.next_quad_alias()}")
    print(f"  Second call: {alias_gen.next_quad_alias()}")
    print(f"  Third call: {alias_gen.next_quad_alias()}")
    
    # Reset alias generator
    alias_gen = AliasGenerator()
    
    # Test the BGP generation function (without cache/space_impl for now)
    try:
        import asyncio
        
        async def test_bgp():
            # Test BGP generation
            sql_components = await generate_bgp_sql_with_cache(
                triples, table_config, alias_gen, 
                projected_vars=None, term_cache=None, space_impl=None
            )
            
            print(f"\n=== BGP SQL Components ===")
            print(f"FROM clause: {sql_components.from_clause}")
            print(f"JOINs: {sql_components.joins}")
            print(f"WHERE conditions: {sql_components.where_conditions}")
            print(f"Variable mappings: {sql_components.variable_mappings}")
            
            # Check for duplicate aliases in FROM clause and JOINs
            all_sql = sql_components.from_clause + " " + " ".join(sql_components.joins)
            print(f"\n=== Checking for duplicate aliases ===")
            print(f"Combined SQL: {all_sql}")
            
            # Look for q0, q1, q2, etc.
            import re
            aliases = re.findall(r'\bq\d+\b', all_sql)
            print(f"Found aliases: {aliases}")
            
            # Check for duplicates
            unique_aliases = set(aliases)
            if len(aliases) != len(unique_aliases):
                print(f"*** DUPLICATE ALIASES DETECTED! ***")
                print(f"Total aliases: {len(aliases)}, Unique aliases: {len(unique_aliases)}")
                
                # Find the duplicates
                from collections import Counter
                alias_counts = Counter(aliases)
                duplicates = {alias: count for alias, count in alias_counts.items() if count > 1}
                print(f"Duplicate aliases: {duplicates}")
            else:
                print(f"✅ No duplicate aliases found")
        
        asyncio.run(test_bgp())
        
    except Exception as e:
        print(f"Error in BGP test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_duplicate_aliases()
