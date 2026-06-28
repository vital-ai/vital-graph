#!/usr/bin/env python3
"""
Simple SPARQL Test for Correctness Verification
==============================================

Test the reverted separate term JOINs approach to ensure it produces correct results.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.db.postgresql.postgresql_space_impl import PostgreSQLSpaceImpl

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Reduce logging chatter
logging.getLogger('vitalgraph.db.postgresql.postgresql_space_impl').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.rdf.rdf_utils').setLevel(logging.WARNING)

async def test_simple_sparql_correctness():
    """Test simple SPARQL query for correctness with reverted approach."""
    
    print("🧪 Testing SPARQL correctness with separate term JOINs approach...")
    
    # Initialize VitalGraph
    vitalgraph = VitalGraphImpl()
    
    try:
        # Simple SPARQL query
        query = """
        SELECT ?subject ?predicate ?object WHERE {
            ?subject ?predicate ?object .
        } LIMIT 5
        """
        
        print(f"📝 Query: {query.strip()}")
        
        # Execute query and measure time
        start_time = time.time()
        results = await vitalgraph.sparql_query('wordnet_frames', query)
        end_time = time.time()
        
        execution_time = end_time - start_time
        
        print(f"⏱️  Execution time: {execution_time:.3f}s")
        print(f"📊 Result count: {len(results)}")
        
        if results:
            print("📝 Sample results:")
            for i, result in enumerate(results[:3]):
                print(f"  {i+1}: {result}")
                
            # Check if results have all three variables filled
            complete_results = 0
            for result in results:
                if (result.get('subject') and 
                    result.get('predicate') and 
                    result.get('object')):
                    complete_results += 1
            
            print(f"✅ Complete results (all 3 variables): {complete_results}/{len(results)}")
            
            if complete_results == len(results):
                print("🎉 SUCCESS: All results are complete!")
                return True
            else:
                print("❌ ISSUE: Some results are incomplete!")
                return False
        else:
            print("❌ No results returned!")
            return False
            
    except Exception as e:
        print(f"❌ Query failed: {e}")
        return False
    finally:
        await vitalgraph.close()

if __name__ == "__main__":
    success = asyncio.run(test_simple_sparql_correctness())
    if success:
        print("\n✅ Correctness test PASSED!")
    else:
        print("\n❌ Correctness test FAILED!")
