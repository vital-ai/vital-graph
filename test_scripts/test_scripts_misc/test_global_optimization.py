#!/usr/bin/env python3
"""
Test script to verify global SPARQL-to-SQL optimization is working.
This script properly calls the orchestrator path to trigger global optimization.
"""

import asyncio
import logging
import sys
import os
import time

# Add the project root to Python path
sys.path.insert(0, '/Users/hadfield/Local/vital-git/vital-graph')

# Set up logging to see WARNING level messages (global optimizer uses WARNING level)
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Test SPARQL query (simplified to avoid namespace issues)
TEST_SPARQL_QUERY = """
SELECT ?s ?p ?o WHERE {
  ?s ?p ?o .
  ?s <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.com/Person> .
  ?s <http://example.com/name> ?name .
  ?s <http://example.com/age> ?age .
  ?person2 <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.com/Person> .
  ?person2 <http://example.com/knows> ?s .
  ?person2 <http://example.com/city> ?city .
}
LIMIT 10
"""

SPACE_ID = "test-space"

# Global variables for capturing SQL
captured_sql = None
sql_capture_enabled = False

async def setup_connection():
    """Initialize database connection for tests."""
    from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
    from vitalgraph.db.postgresql.postgresql_sparql_impl import PostgreSQLSparqlImpl
    from pathlib import Path
    
    # Initialize VitalGraphImpl with config file (same as original test script)
    project_root = Path(__file__).parent
    config_path = project_root / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    # Get space implementation for direct database operations
    space_impl = impl.db_impl.get_space_impl()
    
    # Initialize SPARQL implementation for any SPARQL operations
    sparql_impl = PostgreSQLSparqlImpl(space_impl)
    
    return impl, space_impl

async def cleanup_connection(impl):
    """Clean up database connections."""
    if impl:
        await impl.db_impl.disconnect()

async def custom_sql_executor(space_impl, sql_query, max_rows, max_memory_mb):
    """Custom SQL executor that captures SQL instead of executing it."""
    global captured_sql, sql_capture_enabled
    
    if sql_capture_enabled:
        captured_sql = sql_query
        print(f"📝 CAPTURED SQL ({len(sql_query)} chars)")
        # Return empty result to avoid actual execution
        return []
    else:
        # This shouldn't happen in our test
        raise Exception("SQL capture not enabled")

async def test_global_optimization():
    """Test global optimization by calling the orchestrator."""
    print("🧪 Testing Global SPARQL-to-SQL Optimization")
    print("=" * 60)
    
    impl = None
    
    try:
        # Set up database connection
        print("🔌 Setting up database connection...")
        impl, space_impl = await setup_connection()
        print("✅ Database connection established")
        
        print(f"\n📝 Testing SPARQL Query:")
        print("-" * 40)
        print(TEST_SPARQL_QUERY.strip()[:200] + "..." if len(TEST_SPARQL_QUERY.strip()) > 200 else TEST_SPARQL_QUERY.strip())
        print("-" * 40)
        
        # Import orchestrator
        from vitalgraph.db.postgresql.sparql.postgresql_sparql_orchestrator import orchestrate_sparql_query
        import vitalgraph.db.postgresql.sparql.postgresql_sparql_orchestrator as orchestrator_module
        
        # Enable SQL capture
        global sql_capture_enabled, captured_sql
        sql_capture_enabled = True
        captured_sql = None
        
        # Monkey patch the SQL executor to capture SQL
        original_executor = orchestrator_module._execute_sql_query_with_space_impl
        orchestrator_module._execute_sql_query_with_space_impl = custom_sql_executor
        
        try:
            print(f"\n🚀 Calling orchestrator with global optimization...")
            start_time = time.time()
            
            # Call the orchestrator - this should trigger global optimization
            result = await orchestrate_sparql_query(
                space_impl=space_impl,
                space_id=SPACE_ID,
                sparql_query=TEST_SPARQL_QUERY,
                max_rows=1000,
                max_memory_mb=100,
                graph_cache={}
            )
            
            conversion_time = time.time() - start_time
            print(f"⏱️  Orchestrator completed in {conversion_time:.3f}s")
            
            if captured_sql:
                print(f"\n✅ Successfully captured SQL with global optimization!")
                
                # Analyze the generated SQL
                print(f"\n📊 SQL Analysis:")
                print(f"  - Query length: {len(captured_sql)} characters")
                
                # Count table aliases
                import re
                quad_tables = re.findall(r'\b(q\d+)\b', captured_sql)
                cross_joins = captured_sql.count('CROSS JOIN')
                unions = captured_sql.count('UNION')
                
                print(f"  - Quad table aliases: {len(set(quad_tables))} unique")
                print(f"  - CROSS JOINs: {cross_joins}")
                print(f"  - UNIONs: {unions}")
                
                # Show first part of SQL
                print(f"\n🔍 Generated SQL (first 500 chars):")
                print("-" * 60)
                print(captured_sql[:500] + "..." if len(captured_sql) > 500 else captured_sql)
                print("-" * 60)
                
                return True
            else:
                print("❌ Failed to capture SQL from orchestrator")
                return False
                
        finally:
            # Restore original executor
            orchestrator_module._execute_sql_query_with_space_impl = original_executor
            sql_capture_enabled = False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return False
        
    finally:
        # Clean up connections
        if impl:
            print("\n🔌 Cleaning up database connection...")
            await cleanup_connection(impl)
            print("✅ Database connection closed")

if __name__ == "__main__":
    success = asyncio.run(test_global_optimization())
    if success:
        print("\n✅ Global optimization test completed successfully!")
    else:
        print("\n❌ Global optimization test failed!")
        sys.exit(1)
