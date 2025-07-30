#!/usr/bin/env python3
"""
Case-Sensitive SPARQL Variables Test Script
==========================================

Test case-sensitive SPARQL variable handling to ensure that variables like
?HasName and ?hasName are treated as completely separate variables, which is
required by the SPARQL specification.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.db.postgresql.postgresql_sparql_impl import PostgreSQLSparqlImpl

# Reduce logging chatter
logging.getLogger('vitalgraph.db.postgresql.postgresql_space_impl').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.rdf.rdf_utils').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.db.postgresql.postgresql_cache_term').setLevel(logging.WARNING)

# Configuration
SPACE_ID = "wordnet_space"
GRAPH_URI = "http://vital.ai/graph/wordnet"

async def run_case_sensitive_query(sparql_impl, query_name, query):
    """Run a single case-sensitive variable query and display results."""
    print(f"  {query_name}:")
    
    try:
        start_time = time.time()
        results = await sparql_impl.execute_sparql_query(SPACE_ID, query)
        elapsed = time.time() - start_time
        
        print(f"    ⏱️  {elapsed:.3f}s | {len(results)} results")
        
        if results:
            # Check if case-sensitive variables are preserved
            first_result = results[0]
            result_keys = list(first_result.keys())
            
            # Look for case variations in the keys
            case_variations = []
            for key in result_keys:
                if any(other_key.lower() == key.lower() and other_key != key for other_key in result_keys):
                    case_variations.append(key)
            
            if case_variations:
                print(f"    ✅ Case-sensitive variables detected: {case_variations}")
            
            # Show first few results with preserved case
            for i, result in enumerate(results[:3], 1):
                print(f"    [{i}] {dict(list(result.items())[:4])}")
            
            if len(results) > 3:
                print(f"    ... and {len(results) - 3} more results")
        else:
            print("    ℹ️  No results (expected if no matching data)")
            
    except Exception as e:
        print(f"    ❌ Error: {e}")
        raise

async def test_case_sensitive_variables():
    """Test case-sensitive SPARQL variable handling."""
    
    print("🧪 Case-Sensitive SPARQL Variables Test")
    print("=" * 45)
    
    # Initialize - follow exact pattern from working test scripts
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    space_impl = impl.db_impl.get_space_impl()
    sparql_impl = PostgreSQLSparqlImpl(space_impl)
    
    print(f"✅ Connected | Space: {SPACE_ID}")
    
    try:
        # Test queries with case-sensitive variables
        queries = {
            "Mixed Case Variables": """
                SELECT ?Entity ?entity ?ENTITY WHERE {
                    ?Entity <http://vital.ai/haley.ai/chat-saas#hasName> ?entity .
                    ?ENTITY <http://vital.ai/haley.ai/chat-saas#category> "wordnet-concept" .
                    FILTER(?Entity = ?ENTITY)
                }
                LIMIT 3
            """,
            
            "HasName vs hasName": """
                SELECT ?HasName ?hasName ?entity WHERE {
                    ?entity <http://vital.ai/haley.ai/chat-saas#hasName> ?HasName .
                    ?entity <http://vital.ai/haley.ai/chat-saas#category> ?hasName .
                }
                LIMIT 3
            """,
            
            "All Uppercase vs Lowercase": """
                SELECT ?NAME ?name ?Entity WHERE {
                    ?Entity <http://vital.ai/haley.ai/chat-saas#hasName> ?NAME .
                    ?Entity <http://vital.ai/haley.ai/chat-saas#hasName> ?name .
                }
                LIMIT 2
            """
        }
        
        print(f"🔍 Running {len(queries)} case-sensitivity tests...\n")
        
        for query_name, query in queries.items():
            await run_case_sensitive_query(sparql_impl, query_name, query)
            print()
        
        # Show cache info if available
        if hasattr(sparql_impl, 'term_cache') and hasattr(sparql_impl.term_cache, 'cache_size'):
            print(f"📊 Cache: {sparql_impl.term_cache.cache_size()} terms")
        else:
            print("📊 Cache: N/A")
        
    except Exception as e:
        print(f"❌ Error during testing: {e}")
        raise
    finally:
        # Close database connection
        if hasattr(impl.db_impl, 'disconnect'):
            await impl.db_impl.disconnect()
        elif hasattr(impl.db_impl, 'close'):
            await impl.db_impl.close()
        
    print("✅ Case-Sensitive Variables Tests Complete!")
    print("💡 Variables with different cases should be treated as separate variables")

if __name__ == "__main__":
    asyncio.run(test_case_sensitive_variables())
