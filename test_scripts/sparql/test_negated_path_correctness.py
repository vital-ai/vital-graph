#!/usr/bin/env python3
"""
Correctness verification test for optimized negated path queries.
This test compares results with different LIMIT values to ensure we're not missing valid results.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl

# Reduce logging chatter for timing test
logging.basicConfig(level=logging.WARNING)

async def main():
    print("🔍 Negated Path Correctness Verification Test")
    print("=" * 60)
    
    # Initialize with proper configuration
    try:
        config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
        
        from vitalgraph.config.config_loader import get_config
        config = get_config(str(config_path))
        
        vital_graph = VitalGraphImpl(config=config)
        await vital_graph.db_impl.connect()
        print("✅ Connected to database")
    except Exception as e:
        print(f"❌ Failed to initialize: {e}")
        return
    
    try:
        # Get the test space
        space_manager = vital_graph.space_manager
        space_impl = vital_graph.db_impl.get_space_impl()
        
        # Test query with negated path - get more results to verify correctness
        query_large = """
            PREFIX ex: <http://example.org/>
            SELECT ?person1 ?person2 ?name1 ?name2
            WHERE {
                GRAPH <urn:___GLOBAL> {
                    ?person1 ex:hasName ?name1 .
                    ?person2 ex:hasName ?name2 .
                    ?person1 !ex:knows ?person2 .
                    FILTER(?person1 != ?person2)
                }
            }
            ORDER BY ?name1 ?name2
            LIMIT 50
        """
        
        print("🔍 Testing negated path query with LIMIT 50...")
        
        from vitalgraph.db.postgresql.postgresql_sparql_impl import PostgreSQLSparqlImpl
        sparql_impl = PostgreSQLSparqlImpl(space_impl)
        
        start_time = time.time()
        results_50 = await sparql_impl.execute_sparql_query("space_test", query_large)
        end_time = time.time()
        execution_time = end_time - start_time
        
        print(f"📊 Results with LIMIT 50: {len(results_50)} pairs in {execution_time:.3f}s")
        
        # Now let's also test with a smaller limit to see if we get consistent results
        query_small = """
            PREFIX ex: <http://example.org/>
            SELECT ?person1 ?person2 ?name1 ?name2
            WHERE {
                GRAPH <urn:___GLOBAL> {
                    ?person1 ex:hasName ?name1 .
                    ?person2 ex:hasName ?name2 .
                    ?person1 !ex:knows ?person2 .
                    FILTER(?person1 != ?person2)
                }
            }
            ORDER BY ?name1 ?name2
            LIMIT 10
        """
        
        print("🔍 Testing negated path query with LIMIT 10...")
        
        start_time = time.time()
        results_10 = await sparql_impl.execute_sparql_query("space_test", query_small)
        end_time = time.time()
        execution_time = end_time - start_time
        
        print(f"📊 Results with LIMIT 10: {len(results_10)} pairs in {execution_time:.3f}s")
        
        # Verify that the first 10 results are consistent
        print("\n🔍 Consistency Check:")
        if len(results_50) >= 10 and len(results_10) == 10:
            consistent = True
            for i in range(10):
                if (results_50[i]['name1'] != results_10[i]['name1'] or 
                    results_50[i]['name2'] != results_10[i]['name2']):
                    consistent = False
                    break
            
            if consistent:
                print("✅ Results are consistent - first 10 results match between queries")
            else:
                print("❌ Results are inconsistent - ordering or content differs")
        else:
            print("⚠️  Cannot verify consistency - insufficient results")
        
        # Show some example results
        print(f"\n📋 Example results (showing first 5 of {len(results_50)}):")
        for i, result in enumerate(results_50[:5], 1):
            print(f"  [{i}] {result['name1']} does NOT know {result['name2']}")
        
        # Test a specific known relationship to verify the NOT EXISTS logic
        print("\n🔍 Verification Test: Check known relationships")
        
        # First, let's see what relationships DO exist
        knows_query = """
            PREFIX ex: <http://example.org/>
            SELECT ?person1 ?person2 ?name1 ?name2
            WHERE {
                GRAPH <urn:___GLOBAL> {
                    ?person1 ex:knows ?person2 .
                    ?person1 ex:hasName ?name1 .
                    ?person2 ex:hasName ?name2 .
                }
            }
            ORDER BY ?name1 ?name2
        """
        
        knows_results = await sparql_impl.execute_sparql_query("space_test", knows_query)
        print(f"📊 Found {len(knows_results)} direct 'knows' relationships")
        
        if knows_results:
            print("📋 Direct 'knows' relationships:")
            for i, result in enumerate(knows_results[:3], 1):
                print(f"  [{i}] {result['name1']} KNOWS {result['name2']}")
            
            # Verify that these known relationships are NOT in our negated results
            known_pairs = {(r['name1'], r['name2']) for r in knows_results}
            negated_pairs = {(r['name1'], r['name2']) for r in results_50}
            
            overlap = known_pairs.intersection(negated_pairs)
            if overlap:
                print(f"❌ ERROR: Found {len(overlap)} pairs that exist in both 'knows' and '!knows' results!")
                for pair in list(overlap)[:3]:
                    print(f"  Conflicting pair: {pair[0]} - {pair[1]}")
            else:
                print("✅ Verification passed: No overlap between 'knows' and '!knows' results")
        
    finally:
        # Disconnect
        try:
            await space_manager.disconnect()
            print("\n🔌 Disconnected")
        except Exception as e:
            print(f"❌ Error during disconnect: {e}")

if __name__ == "__main__":
    asyncio.run(main())
