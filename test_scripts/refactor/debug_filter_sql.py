#!/usr/bin/env python3

import asyncio
import logging
from pathlib import Path
from rdflib.plugins.sparql import prepareQuery
from rdflib.plugins.sparql.algebra import translateQuery

# Configuration
SPACE_ID = "wordnet_space"

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def debug_filter_sql():
    """Debug the exact SQL generation for the failing FILTER query."""
    
    # Initialize using the same pattern as the test script
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
    from vitalgraph.db.postgresql.postgresql_sparql_impl import PostgreSQLSparqlImpl as OriginalSparqlImpl
    from vitalgraph.db.postgresql.sparql.postgres_sparql_impl import PostgreSQLSparqlImpl as RefactoredSparqlImpl
    
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    space_impl = impl.db_impl.get_space_impl()
    
    # Create both implementations
    original_sparql = OriginalSparqlImpl(space_impl)
    refactored_sparql = RefactoredSparqlImpl(space_impl)
    
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
    
    print("🔍 DEBUGGING FILTER SQL GENERATION")
    print("=" * 60)
    print("Query:")
    print(query)
    print("\n" + "=" * 60)
    
    # Parse the SPARQL query to see the algebra
    try:
        parsed_query = prepareQuery(query)
        algebra = translateQuery(parsed_query)
        print(f"\n📊 SPARQL ALGEBRA:")
        print(f"Type: {type(algebra).__name__}")
        print(f"Structure: {algebra}")
        
        # Look for Filter pattern
        def find_filter_patterns(node, path=""):
            """Recursively find Filter patterns in the algebra tree."""
            node_name = type(node).__name__
            current_path = f"{path}.{node_name}" if path else node_name
            
            print(f"  {current_path}: {node_name}")
            
            if node_name == "Filter":
                print(f"    🎯 FOUND FILTER at {current_path}")
                print(f"       Filter expression: {node.expr}")
                print(f"       Filter expr type: {type(node.expr).__name__}")
                print(f"       Base pattern: {type(node.p).__name__}")
            
            # Recursively search child patterns
            for attr_name in dir(node):
                if not attr_name.startswith('_'):
                    attr_value = getattr(node, attr_name)
                    if hasattr(attr_value, '__class__') and hasattr(attr_value.__class__, '__name__'):
                        if attr_value.__class__.__name__ in ['BGP', 'Filter', 'Join', 'Union', 'Project', 'Slice']:
                            find_filter_patterns(attr_value, f"{current_path}.{attr_name}")
        
        print(f"\n📊 ALGEBRA TREE ANALYSIS:")
        find_filter_patterns(algebra.algebra)
        
    except Exception as e:
        print(f"❌ Failed to parse query: {e}")
    
    print(f"\n" + "=" * 60)
    print("🔍 SQL GENERATION COMPARISON")
    print("=" * 60)
    
    # Try to examine the SQL generation process for the refactored implementation
    try:
        print("\n📊 REFACTORED IMPLEMENTATION SQL GENERATION:")
        
        # Enable debug logging for the refactored implementation
        refactored_logger = logging.getLogger('vitalgraph.db.postgresql.sparql')
        refactored_logger.setLevel(logging.DEBUG)
        
        # Execute the query and capture debug output
        refactored_results = await refactored_sparql.execute_sparql_query(SPACE_ID, query)
        print(f"✅ Refactored execution completed: {len(refactored_results)} results")
        
    except Exception as e:
        print(f"❌ Refactored SQL generation failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_filter_sql())
