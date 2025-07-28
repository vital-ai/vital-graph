#!/usr/bin/env python3

import asyncio
import logging
from pathlib import Path
from rdflib.plugins.sparql import prepareQuery
from rdflib.plugins.sparql.algebra import translateQuery

# Configuration
SPACE_ID = "wordnet_space"

async def debug_filter_structure():
    """Debug the exact structure of the FILTER expression."""
    
    # The failing query
    query = """
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT ?s ?p ?o WHERE {
            ?s ?p ?o .
            FILTER(
                ?s = <http://example.org/person/alice> ||
                ?s = <http://vital.ai/haley.ai/chat-saas/KGEntity/1447109393012_1265235442>
            )
        }
        LIMIT 10
    """
    
    print("🔍 DEBUGGING FILTER EXPRESSION STRUCTURE")
    print("=" * 60)
    
    # Parse the SPARQL query to examine the algebra structure
    try:
        parsed_query = prepareQuery(query)
        algebra = parsed_query.algebra
        
        def examine_filter_expr(node, path=""):
            """Recursively examine Filter expressions."""
            node_name = type(node).__name__
            current_path = f"{path}.{node_name}" if path else node_name
            
            if node_name == "Filter":
                print(f"\n🎯 FOUND FILTER at {current_path}")
                filter_expr = node.expr
                print(f"   Filter expression type: {type(filter_expr).__name__}")
                print(f"   Filter expression: {filter_expr}")
                
                # Examine the structure in detail
                print(f"\n   📊 DETAILED STRUCTURE:")
                print(f"   - Has 'expr' attr: {hasattr(filter_expr, 'expr')}")
                print(f"   - Has 'other' attr: {hasattr(filter_expr, 'other')}")
                
                if hasattr(filter_expr, 'expr'):
                    expr_val = filter_expr.expr
                    print(f"   - expr value: {expr_val}")
                    print(f"   - expr type: {type(expr_val).__name__}")
                    
                    # Check if it has dictionary-style access
                    try:
                        dict_expr = filter_expr['expr']
                        print(f"   - dict['expr'] works: {dict_expr}")
                    except:
                        print(f"   - dict['expr'] fails")
                
                if hasattr(filter_expr, 'other'):
                    other_val = filter_expr.other
                    print(f"   - other value: {other_val}")
                    print(f"   - other type: {type(other_val).__name__}")
                    
                    # Check if other is a list
                    if isinstance(other_val, list):
                        print(f"   - other is list with {len(other_val)} items:")
                        for i, item in enumerate(other_val):
                            print(f"     [{i}] {type(item).__name__}: {item}")
                    
                    # Check if it has dictionary-style access
                    try:
                        dict_other = filter_expr['other']
                        print(f"   - dict['other'] works: {dict_other}")
                    except:
                        print(f"   - dict['other'] fails")
                
                # Test manual translation
                print(f"\n   🧪 MANUAL TRANSLATION TEST:")
                
                # Import the translation function
                from vitalgraph.db.postgresql.sparql.postgresql_sparql_expressions import translate_filter_expression
                
                # Create dummy variable mappings
                dummy_mappings = {
                    'Variable(s)': 's_term.term_text',
                    'Variable(p)': 'p_term.term_text', 
                    'Variable(o)': 'o_term.term_text'
                }
                
                try:
                    result = translate_filter_expression(filter_expr, dummy_mappings)
                    print(f"   ✅ Translation result: {result}")
                except Exception as e:
                    print(f"   ❌ Translation failed: {e}")
                    import traceback
                    traceback.print_exc()
            
            # Recursively search child patterns
            for attr_name in dir(node):
                if not attr_name.startswith('_'):
                    attr_value = getattr(node, attr_name)
                    if hasattr(attr_value, '__class__') and hasattr(attr_value.__class__, '__name__'):
                        if attr_value.__class__.__name__ in ['BGP', 'Filter', 'Join', 'Union', 'Project', 'Slice']:
                            examine_filter_expr(attr_value, f"{current_path}.{attr_name}")
        
        examine_filter_expr(algebra)
        
    except Exception as e:
        print(f"❌ Failed to parse query: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_filter_structure())
