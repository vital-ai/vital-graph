#!/usr/bin/env python3
"""
SPARQL to SQL Conversion Test Script
===================================

This script converts SPARQL queries to SQL using the VitalGraph PostgreSQL functionality
and logs the generated SQL without executing it. This is useful for debugging SPARQL
translation issues and understanding the generated SQL structure.

Usage:
    python test_scripts/db/test_sparql_to_sql.py

The script will test the provided SPARQL query and log the generated SQL.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.db.postgresql.postgresql_sparql_impl import PostgreSQLSparqlImpl
from vitalgraph.db.postgresql.postgresql_space_impl import PostgreSQLSpaceImpl

# Import SPARQL orchestrator components for SQL generation
from vitalgraph.db.postgresql.sparql.postgresql_sparql_orchestrator import (
    create_table_config, _has_distinct_pattern, _extract_limit_offset,
    _translate_ask_query, _translate_describe_query, build_construct_query_from_components
)
from vitalgraph.db.postgresql.sparql.postgresql_sparql_patterns import (
    translate_algebra_pattern_to_components
)
from vitalgraph.db.postgresql.sparql.postgresql_sparql_queries import (
    build_select_query, build_construct_query
)
from vitalgraph.db.postgresql.sparql.postgresql_sparql_core import (
    SparqlContext, AliasGenerator
)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Reduce logging chatter from other modules
logging.getLogger('vitalgraph.db.postgresql.postgresql_space_impl').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.rdf.rdf_utils').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.db.postgresql.postgresql_cache_term').setLevel(logging.WARNING)

# Configuration
SPACE_ID = "wordnet_frames"  # Using the space from the user's query
GRAPH_URI = "http://vital.ai/graph/kgwordnetframes"

# Global variables for database connection
impl = None
sparql_impl = None
space_impl = None

# Test SPARQL query from the user
TEST_SPARQL_QUERY = """
PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
PREFIX vital: <http://vital.ai/ontology/vital#>
PREFIX vital-aimp: <http://vital.ai/ontology/vital-aimp#>
PREFIX haley: <http://vital.ai/ontology/haley>
PREFIX haley-ai-question: <http://vital.ai/ontology/haley-ai-question#>
PREFIX haley-ai-kg: <http://vital.ai/ontology/haley-ai-kg#>

CONSTRUCT {
  _:bnode1 <urn:hasEntity> ?entity .
  _:bnode1 <urn:hasFrame> ?frame .
  _:bnode1 <urn:hasSourceSlot> ?sourceSlot .
  _:bnode1 <urn:hasDestinationSlot> ?destinationSlot .
  _:bnode1 <urn:hasSourceSlotEntity> ?sourceSlotEntity .
  _:bnode1 <urn:hasDestinationSlotEntity> ?destinationSlotEntity .
}
WHERE {
  GRAPH <http://vital.ai/graph/kgwordnetframes> {
    SELECT ?entity ?frame ?sourceSlot ?destinationSlot ?sourceSlotEntity ?destinationSlotEntity WHERE {
      {
        ?sourceSlotEntity a haley-ai-kg:KGEntity .
        ?sourceSlotEntity haley-ai-kg:hasKGraphDescription ?description1 .
        FILTER(CONTAINS(LCASE(STR(?description1)), "happy"))
        BIND(?sourceSlotEntity AS ?entity)
      }
      UNION
      {
        ?destinationSlotEntity a haley-ai-kg:KGEntity .
        ?destinationSlotEntity haley-ai-kg:hasKGraphDescription ?description2 .
        FILTER(CONTAINS(LCASE(STR(?description2)), "happy"))
        BIND(?destinationSlotEntity AS ?entity)
      }
      ?frame a haley-ai-kg:KGFrame .
      
      ?sourceEdge a haley-ai-kg:Edge_hasKGSlot .
      ?sourceEdge vital-core:hasEdgeSource ?frame .
      ?sourceEdge vital-core:hasEdgeDestination ?sourceSlot .
      ?sourceSlot a haley-ai-kg:KGEntitySlot .
      ?sourceSlot haley-ai-kg:hasEntitySlotValue ?sourceSlotEntity .
      ?sourceSlot haley-ai-kg:hasKGSlotType <urn:hasSourceEntity> .
      
      ?destinationEdge a haley-ai-kg:Edge_hasKGSlot .
      ?destinationEdge vital-core:hasEdgeSource ?frame .
      ?destinationEdge vital-core:hasEdgeDestination ?destinationSlot .
      ?destinationSlot a haley-ai-kg:KGEntitySlot .
      ?destinationSlot haley-ai-kg:hasEntitySlotValue ?destinationSlotEntity .
      ?destinationSlot haley-ai-kg:hasKGSlotType <urn:hasDestinationEntity> .
    }
  }
}
ORDER BY ?entity
LIMIT 10
OFFSET 0
"""


async def setup_connection():
    """Initialize database connection for tests."""
    global impl, sparql_impl, space_impl
    
    print("🔌 Setting up database connection...")
    
    # Initialize VitalGraphAppImpl with config file
    project_root = Path(__file__).parent.parent.parent
    config_path = project_root / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    # Get space implementation for direct database operations
    space_impl = impl.db_impl.get_space_impl()
    
    # Initialize SPARQL implementation for any SPARQL operations
    sparql_impl = PostgreSQLSparqlImpl(space_impl)
    
    print(f"✅ Connected to database")


async def cleanup_connection():
    """Clean up database connection."""
    global impl, sparql_impl, space_impl
    
    if impl:
        await impl.db_impl.disconnect()
        print("🔌 Database connection closed")
    
    # Clear global references
    impl = None
    sparql_impl = None
    space_impl = None


async def convert_sparql_to_sql_only(space_id: str, sparql_query: str) -> str:
    """
    Convert SPARQL query to SQL without executing it using the orchestrator path.
    
    This function uses the actual orchestrator logic including global optimization
    but stops before executing the SQL, returning the generated SQL string instead.
    
    Args:
        space_id: Space identifier
        sparql_query: SPARQL query string
        
    Returns:
        Generated SQL query string
    """
    logger = logging.getLogger(__name__)
    logger.info(f"🚀 Converting SPARQL to SQL for space '{space_id}' using orchestrator path")
    logger.info(f"📝 Query preview: {sparql_query[:100]}...")
    
    try:
        # Use the orchestrator's SQL translation method that includes global optimization
        from vitalgraph.db.postgresql.sparql.postgresql_sparql_orchestrator import orchestrate_sparql_query
        
        # Create a mock result collector to capture the SQL without execution
        original_execute_sql = None
        captured_sql = None
        
        # Monkey patch the SQL execution to capture SQL instead of executing
        import vitalgraph.db.postgresql.sparql.postgresql_sparql_orchestrator as orchestrator_module
        
        async def capture_sql_instead_of_execute(space_impl, sql_query, max_rows, max_memory_mb):
            nonlocal captured_sql
            captured_sql = sql_query
            logger.info(f"📝 Captured SQL query ({len(sql_query)} chars)")
            # Return empty result to avoid execution
            return []
        
        # Temporarily replace the SQL execution function
        original_execute_sql = orchestrator_module._execute_sql_query_with_space_impl
        orchestrator_module._execute_sql_query_with_space_impl = capture_sql_instead_of_execute
        
        try:
            # Call the orchestrator which will include global optimization
            logger.warning(f"🧪 TEST: About to call orchestrator for space '{space_id}'")
            print(f"🧪 TEST PRINT: About to call orchestrator for space '{space_id}'")
            
            result = await orchestrate_sparql_query(
                space_impl=space_impl,
                space_id=space_id,
                sparql_query=sparql_query,
                max_rows=1000,  # Small limit since we're not actually executing
                max_memory_mb=100,  # Small limit since we're not actually executing
                graph_cache={}
            )
            
            logger.warning(f"🧪 TEST: Orchestrator returned result: {type(result)}")
            print(f"🧪 TEST PRINT: Orchestrator returned result: {type(result)}")
            
            if captured_sql:
                logger.info(f"✅ Successfully captured SQL using orchestrator path with global optimization")
                return captured_sql
            else:
                raise Exception("Failed to capture SQL from orchestrator")
                
        finally:
            # Restore original function
            if original_execute_sql:
                orchestrator_module._execute_sql_query_with_space_impl = original_execute_sql
        
    except Exception as e:
        logger.error(f"Error converting SPARQL to SQL: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise


def analyze_join_structure(sql_query: str) -> None:
    """
    Analyze the JOIN structure of the generated SQL to understand optimizer behavior.
    
    Args:
        sql_query: Generated SQL query string
    """
    import re
    
    print(f"\n🔍 JOIN Structure Analysis:")
    
    # Extract table aliases and their relationships
    quad_tables = re.findall(r'\b(q\d+)\b', sql_query)
    term_tables = re.findall(r'\b(\w+_term_\w+)\s+(\w+_term_\d+)', sql_query)
    
    print(f"  - Quad table aliases: {len(set(quad_tables))} unique ({', '.join(sorted(set(quad_tables))[:10])}{', ...' if len(set(quad_tables)) > 10 else ''})")
    print(f"  - Term table joins: {len(term_tables)} term lookups")
    
    # Analyze WHERE conditions for selectivity
    where_conditions = []
    if 'WHERE' in sql_query:
        where_part = sql_query.split('WHERE', 1)[1]
        if 'ORDER BY' in where_part:
            where_part = where_part.split('ORDER BY')[0]
        
        # Count different types of conditions
        uuid_conditions = len(re.findall(r'\w+_uuid = \'[^\']+\'', where_part))
        join_conditions = len(re.findall(r'\w+\.\w+_uuid = \w+\.\w+_uuid', where_part))
        text_filters = len(re.findall(r'LIKE|ILIKE', where_part))
        
        print(f"  - UUID equality conditions: {uuid_conditions} (highly selective)")
        print(f"  - Join conditions: {join_conditions} (connect tables)")
        print(f"  - Text search filters: {text_filters} (may be less selective)")
    
    # Analyze optimizer opportunities
    print(f"\n🧠 Optimizer Opportunities:")
    print(f"  - CROSS JOINs allow PostgreSQL to choose optimal join order")
    print(f"  - Optimizer can use statistics to identify most selective conditions first")
    print(f"  - UUID equality conditions will likely be processed early (high selectivity)")
    print(f"  - Text search conditions may be deferred (lower selectivity)")
    
    # Check for subquery structure
    if 'UNION' in sql_query:
        union_count = sql_query.count('UNION')
        print(f"  - {union_count} UNION operation(s) - optimizer may materialize subquery")
    
    if sql_query.count('FROM') > 1:
        print(f"  - Multiple FROM clauses detected - complex subquery structure")
    
    # Estimate join complexity
    total_tables = len(set(quad_tables)) + len(term_tables)
    if total_tables > 10:
        print(f"  - High join complexity ({total_tables} tables) - optimizer will use heuristics")
        print(f"  - Consider increasing join_collapse_limit if needed")


def format_sql_for_display(sql_query: str) -> str:
    """
    Format SQL query for better readability in console output.
    
    Args:
        sql_query: Raw SQL query string
        
    Returns:
        Formatted SQL query string
    """
    # Basic SQL formatting - add line breaks after major clauses
    formatted = sql_query
    
    # Add line breaks after major SQL keywords
    keywords = ['SELECT', 'FROM', 'WHERE', 'JOIN', 'LEFT JOIN', 'INNER JOIN', 'CROSS JOIN', 
                'GROUP BY', 'HAVING', 'ORDER BY', 'LIMIT', 'OFFSET', 'UNION']
    
    for keyword in keywords:
        formatted = formatted.replace(f' {keyword} ', f'\n{keyword} ')
        formatted = formatted.replace(f'\n{keyword} ', f'\n{keyword} ')
    
    # Clean up extra whitespace
    lines = [line.strip() for line in formatted.split('\n') if line.strip()]
    return '\n'.join(lines)


async def test_sparql_to_sql_conversion():
    """Test the SPARQL to SQL conversion with the provided query."""
    print("🧪 SPARQL to SQL Conversion Test")
    print("=" * 60)
    
    try:
        print(f"📝 Testing SPARQL Query:")
        print("-" * 40)
        print(TEST_SPARQL_QUERY.strip())
        print("-" * 40)
        
        print(f"\n🔄 Converting SPARQL to SQL...")
        start_time = time.time()
        
        # Convert SPARQL to SQL without execution
        sql_query = await convert_sparql_to_sql_only(SPACE_ID, TEST_SPARQL_QUERY)
        
        conversion_time = time.time() - start_time
        print(f"⏱️  Conversion completed in {conversion_time:.3f}s")
        
        print(f"\n🔍 Generated SQL Query:")
        print("=" * 60)
        formatted_sql = format_sql_for_display(sql_query)
        print(formatted_sql)
        print("=" * 60)
        
        # Analyze the SQL structure
        print(f"\n📊 SQL Analysis:")
        print(f"  - Query length: {len(sql_query)} characters")
        print(f"  - Lines: {len(sql_query.split(chr(10)))}")
        print(f"  - Contains CROSS JOIN: {'CROSS JOIN' in sql_query}")
        print(f"  - Contains UNION: {'UNION' in sql_query}")
        print(f"  - Contains DISTINCT: {'DISTINCT' in sql_query}")
        print(f"  - Contains LIKE (text search): {'LIKE' in sql_query}")
        print(f"  - Contains trigram ops (%%): {'%%' in sql_query}")
        
        # Detailed JOIN analysis
        analyze_join_structure(sql_query)
        
        # Check for potential performance issues
        print(f"\n⚠️  Query Optimization Notes:")
        cross_join_count = sql_query.count('CROSS JOIN')
        if cross_join_count > 0:
            print(f"  - {cross_join_count} CROSS JOIN(s) detected - allows optimizer flexibility")
            print(f"  - PostgreSQL optimizer can rearrange joins based on statistics and costs")
        
        if 'LIKE' in sql_query and '%%' not in sql_query:
            print(f"  - LIKE without trigram operators - consider using ILIKE for better indexing")
        
        if len(sql_query) > 5000:
            print(f"  - Complex query ({len(sql_query)} chars) - optimizer has many choices")
            
        print(f"\n✅ SPARQL to SQL conversion completed successfully!")
        
    except Exception as e:
        print(f"❌ Error during SPARQL to SQL conversion: {e}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")


async def main():
    """Main test controller."""
    print("🚀 SPARQL to SQL Test Suite")
    print("=" * 50)
    
    # Setup connection
    await setup_connection()
    
    try:
        # Test SPARQL to SQL conversion
        await test_sparql_to_sql_conversion()
        
    finally:
        # Cleanup
        await cleanup_connection()
        print("\n✅ SPARQL to SQL Test Complete!")


if __name__ == "__main__":
    asyncio.run(main())
