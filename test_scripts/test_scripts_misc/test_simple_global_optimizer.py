#!/usr/bin/env python3
"""
Simple test to verify global optimization is working.
This bypasses the complex test script and directly tests the global optimizer.
"""

import asyncio
import logging
import sys
import os

# Add the project root to Python path
sys.path.insert(0, '/Users/hadfield/Local/vital-git/vital-graph')

# Set up logging to see WARNING level messages
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_global_optimizer():
    """Test the global optimizer directly."""
    print("🧪 Testing Global Optimizer")
    print("=" * 50)
    
    try:
        # Import required modules
        from vitalgraph.db.postgresql.sparql.postgresql_sparql_global_optimizer import create_global_optimization_state
        from vitalgraph.db.postgresql.sparql.postgresql_sparql_core import AliasGenerator, SparqlContext
        from rdflib.plugins.sparql import prepareQuery
        
        # Simple SPARQL query for testing
        test_query = """
        SELECT ?s ?p ?o WHERE {
            ?s ?p ?o .
            ?s <http://example.com/type> <http://example.com/Person> .
            ?s <http://example.com/name> ?name .
        }
        """
        
        print(f"📝 Test Query: {test_query.strip()}")
        
        # Parse the query
        print("🔄 Parsing SPARQL query...")
        prepared_query = prepareQuery(test_query)
        query_algebra = prepared_query.algebra
        
        print(f"✅ Parsed query algebra: {type(query_algebra).__name__}")
        
        # Create alias generator and context
        alias_gen = AliasGenerator()
        context = SparqlContext(
            alias_generator=alias_gen,
            term_cache=None,
            space_impl=None,
            table_config=None,
            datatype_cache=None,
            space_id="test"
        )
        
        # Test the global optimizer
        print("🌍 Testing global optimizer...")
        global_state = create_global_optimization_state(query_algebra, alias_gen, context)
        
        print(f"✅ Global optimizer completed!")
        print(f"📊 Results:")
        print(f"   - Total variables: {global_state.total_variables}")
        print(f"   - Alias assignments: {len(global_state.alias_assignments)}")
        print(f"   - Estimated table reduction: {global_state.estimated_table_reduction:.1%}")
        
        if global_state.alias_assignments:
            print(f"🔗 Alias assignments:")
            for var, alias in global_state.alias_assignments.items():
                print(f"   - {var} -> {alias}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_global_optimizer())
    if success:
        print("\n✅ Global optimizer test completed successfully!")
    else:
        print("\n❌ Global optimizer test failed!")
        sys.exit(1)
