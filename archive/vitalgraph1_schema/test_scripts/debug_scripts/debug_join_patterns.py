#!/usr/bin/env python3
"""
Debug script to test JOIN pattern combination that might cause duplicate aliases.
"""

import sys
import os
sys.path.append('/Users/hadfield/Local/vital-git/vital-graph')

from rdflib import Variable, URIRef
import asyncio

# Import the SPARQL modules
from vitalgraph.db.postgresql.sparql.postgresql_sparql_core import (
    AliasGenerator, TableConfig, TranslationContext, SQLComponents
)
from vitalgraph.db.postgresql.sparql.postgresql_sparql_cache_integration import (
    generate_bgp_sql_with_cache
)
from vitalgraph.db.postgresql.sparql.postgresql_sparql_patterns import (
    translate_join_pattern
)

async def test_join_pattern_duplicates():
    """Test if JOIN pattern combination creates duplicate aliases."""
    
    print("=== JOIN Pattern Duplicate Alias Debug Test ===")
    
    # Create shared alias generator (this simulates the shared context)
    alias_gen = AliasGenerator()
    table_config = TableConfig(
        quad_table="vitalgraph1__vitalgraph1_space_id__rdf_quad",
        term_table="vitalgraph1__vitalgraph1_space_id__term",
        graph_table="vitalgraph1__vitalgraph1_space_id__graph"
    )
    
    # Create two separate BGP patterns (like in a JOIN)
    bgp1_triples = [
        (Variable('entity'), URIRef('http://vital.ai/ontology/hasChatName'), Variable('name'))
    ]
    
    bgp2_triples = [
        (Variable('entity'), Variable('prop'), Variable('value'))
    ]
    
    print(f"BGP1 triples: {bgp1_triples}")
    print(f"BGP2 triples: {bgp2_triples}")
    
    try:
        # Generate SQL for first BGP
        print(f"\n=== Generating BGP1 SQL ===")
        left_sql = await generate_bgp_sql_with_cache(
            bgp1_triples, table_config, alias_gen, 
            projected_vars=None, term_cache=None, space_impl=None
        )
        
        print(f"BGP1 FROM: {left_sql.from_clause}")
        print(f"BGP1 JOINs: {left_sql.joins}")
        
        # Generate SQL for second BGP
        print(f"\n=== Generating BGP2 SQL ===")
        right_sql = await generate_bgp_sql_with_cache(
            bgp2_triples, table_config, alias_gen, 
            projected_vars=None, term_cache=None, space_impl=None
        )
        
        print(f"BGP2 FROM: {right_sql.from_clause}")
        print(f"BGP2 JOINs: {right_sql.joins}")
        
        # Now combine them with JOIN pattern
        print(f"\n=== Combining with JOIN Pattern ===")
        
        # Reset alias generator for JOIN combination
        join_alias_gen = AliasGenerator()
        
        combined_sql = await translate_join_pattern(left_sql, right_sql, join_alias_gen)
        
        print(f"Combined FROM: {combined_sql.from_clause}")
        print(f"Combined JOINs: {combined_sql.joins}")
        print(f"Combined WHERE: {combined_sql.where_conditions}")
        
        # Check for duplicate aliases in the combined result
        all_sql = combined_sql.from_clause + " " + " ".join(combined_sql.joins)
        print(f"\n=== Checking Combined SQL for Duplicates ===")
        print(f"Full SQL: {all_sql}")
        
        # Look for q0, q1, q2, etc.
        import re
        aliases = re.findall(r'\\bq\\d+\\b', all_sql)
        print(f"Found aliases: {aliases}")
        
        # Check for duplicates
        unique_aliases = set(aliases)
        if len(aliases) != len(unique_aliases):
            print(f"*** DUPLICATE ALIASES DETECTED IN JOIN COMBINATION! ***")
            print(f"Total aliases: {len(aliases)}, Unique aliases: {len(unique_aliases)}")
            
            # Find the duplicates
            from collections import Counter
            alias_counts = Counter(aliases)
            duplicates = {alias: count for alias, count in alias_counts.items() if count > 1}
            print(f"Duplicate aliases: {duplicates}")
            
            return True  # Found duplicates
        else:
            print(f"✅ No duplicate aliases found in JOIN combination")
            return False  # No duplicates
        
    except Exception as e:
        print(f"Error in JOIN test: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    has_duplicates = asyncio.run(test_join_pattern_duplicates())
    if has_duplicates:
        print(f"\n🚨 ROOT CAUSE CONFIRMED: JOIN pattern combination creates duplicate aliases!")
    else:
        print(f"\n✅ JOIN pattern combination works correctly")
