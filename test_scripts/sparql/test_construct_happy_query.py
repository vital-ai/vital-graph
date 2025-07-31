#!/usr/bin/env python3
"""
Test script for specific CONSTRUCT query with REGEX filter on "happy" entities.
This test is designed to examine logging output and performance characteristics.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.db.postgresql.postgresql_sparql_impl import PostgreSQLSparqlImpl

# Import test utilities for consistent test execution and reporting
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tool_utils"))
from tool_utils import TestToolUtils

# Configure logging to show detailed output
logging.basicConfig(
    level=logging.DEBUG,
    format='%(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Configuration
SPACE_ID = "wordnet_space"
GRAPH_URI = "http://vital.ai/graph/wordnet"

async def main():
    print("🧪 CONSTRUCT Query Test - Happy Entities with Logging")
    print("=" * 60)
    
    # Initialize like other test scripts
    try:
        config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
        
        from vitalgraph.config.config_loader import get_config
        config = get_config(str(config_path))
        
        impl = VitalGraphImpl(config=config)
        await impl.db_impl.connect()
        
        space_impl = impl.db_impl.get_space_impl()
        sparql_impl = PostgreSQLSparqlImpl(space_impl)
        
        print("✅ Connected | Testing CONSTRUCT query with REGEX filter")
        print(f"🎯 Target Graph: {GRAPH_URI}")
        print()
    except Exception as e:
        print(f"❌ Failed to initialize: {e}")
        import traceback
        traceback.print_exc()
        return
    
    try:
        # The specific CONSTRUCT query requested by the user
        construct_query = """
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            
            CONSTRUCT {
                ?entity ?predicate ?object .
            }
            WHERE {
                
                {
                    SELECT DISTINCT ?entity WHERE {
                        GRAPH <http://vital.ai/graph/wordnet> {
                            ?entity rdf:type haley:KGEntity .
                            ?entity <http://vital.ai/ontology/vital-core#hasName> ?name .
                            FILTER(REGEX(?name, "happy", "i"))
                        }
                    }
                }
                
                GRAPH <http://vital.ai/graph/wordnet> {
                    ?entity ?predicate ?object .
                }
            }
            ORDER BY ?entity
        """
        
        print("🔍 CONSTRUCT Query: Happy Entities with All Properties")
        print("=" * 60)
        print("SPARQL:")
        print(construct_query)
        print()
        print("-" * 60)
        
        # Execute the query with timing using TestToolUtils
        start_time = time.time()
        
        try:
            result = await TestToolUtils.run_test_query(
                sparql_impl=sparql_impl,
                space_id=SPACE_ID,
                query_name="CONSTRUCT Happy Entities",
                query=construct_query,
                enable_algebra_logging=True,
                max_results=10
            )
            
            end_time = time.time()
            execution_time = end_time - start_time
            
            print(f"⏱️  Execution Time: {execution_time:.3f}s")
            
            if result.get('success', False):
                results = result.get('results', [])
                print(f"📊 Results Count: {len(results)}")
                
                if results:
                    print("\nFirst 10 results:")
                    for i, res in enumerate(results[:10], 1):
                        print(f"  [{i}] {res}")
                    
                    if len(results) > 10:
                        print(f"  ... and {len(results) - 10} more results")
                else:
                    print("No results returned")
            else:
                print(f"❌ Query failed: {result.get('error_msg', 'Unknown error')}")
                
        except Exception as e:
            end_time = time.time()
            execution_time = end_time - start_time
            print(f"❌ Query failed after {execution_time:.3f}s: {e}")
            import traceback
            traceback.print_exc()
        
        print()
        print("=" * 60)
        
        # Check cache statistics
        try:
            if hasattr(sparql_impl, 'space_impl') and hasattr(sparql_impl.space_impl, '_term_cache'):
                cache_size = sparql_impl.space_impl._term_cache.size()
                print(f"📊 Term cache size after query: {cache_size} terms")
            else:
                print("📊 Term cache information not available")
        except Exception as e:
            print(f"📊 Could not retrieve cache statistics: {e}")
    
    finally:
        # Disconnect
        try:
            await impl.db_impl.disconnect()
            print("🔌 Disconnected")
        except Exception as e:
            print(f"❌ Error during disconnect: {e}")
    
    print()
    print("✅ CONSTRUCT Query Test Complete!")

if __name__ == "__main__":
    asyncio.run(main())
