#!/usr/bin/env python3

import asyncio
import logging
from pathlib import Path

# Configuration
SPACE_ID = "wordnet_space"

async def debug_filter_sql_generation():
    """Debug the SQL generation for the failing FILTER query."""
    
    # Enable detailed debug logging
    logging.basicConfig(level=logging.DEBUG)
    
    # The failing query from the test
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
    print(f"Query: {query}")
    print()
    
    try:
        # Import the refactored implementation
        from vitalgraph.db.postgresql.sparql.postgres_sparql_impl import PostgreSQLSparqlImpl
        from vitalgraph.db.postgresql.postgresql_space_impl import PostgreSQLSpaceImpl
        from vitalgraph.db.postgresql.postgresql_db_impl import PostgreSQLDBImpl
        
        # Initialize the implementation (following the pattern from test scripts)
        db_impl = PostgreSQLDBImpl()
        await db_impl.initialize()
        
        space_impl = db_impl.get_space_impl(SPACE_ID)
        refactored_impl = PostgreSQLSparqlImpl(space_impl)
        
        print("🔧 EXECUTING QUERY WITH DEBUG LOGGING...")
        print()
        
        # Execute the query - this should show all the debug logging
        results = await refactored_impl.execute_sparql_query(SPACE_ID, query)
        
        print()
        print(f"📊 RESULTS: {len(results)} rows")
        for i, result in enumerate(results[:5], 1):  # Show first 5
            print(f"[{i}] {result}")
        if len(results) > 5:
            print(f"... +{len(results) - 5} more")
            
    except Exception as e:
        print(f"❌ Failed to execute query: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_filter_sql_generation())
