#!/usr/bin/env python3
"""
Test script for CONSTRUCT query performance with "happy" entities.
Creates test data and measures CONSTRUCT query performance.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.config.config_loader import get_config

# Configure logging to show detailed output
logging.basicConfig(
    level=logging.DEBUG,
    format='%(levelname)s - %(name)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Configuration
SPACE_ID = "construct_test"
GRAPH_URI = "http://vital.ai/graph/test"

async def setup_test_data(space):
    """Set up test data with entities containing 'happy' in their names."""
    print("🔧 Setting up test data...")
    
    # Insert test entities with "happy" in their names
    test_data = [
        # Happy entities
        f"<http://example.org/entity1> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://vital.ai/ontology/haley-ai-kg#KGEntity> .",
        f"<http://example.org/entity1> <http://vital.ai/ontology/vital-core#hasName> \"happy person\" .",
        f"<http://example.org/entity1> <http://example.org/hasAge> \"25\" .",
        f"<http://example.org/entity1> <http://example.org/hasLocation> \"New York\" .",
        
        f"<http://example.org/entity2> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://vital.ai/ontology/haley-ai-kg#KGEntity> .",
        f"<http://example.org/entity2> <http://vital.ai/ontology/vital-core#hasName> \"very happy dog\" .",
        f"<http://example.org/entity2> <http://example.org/hasBreed> \"Golden Retriever\" .",
        f"<http://example.org/entity2> <http://example.org/hasOwner> <http://example.org/entity1> .",
        
        f"<http://example.org/entity3> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://vital.ai/ontology/haley-ai-kg#KGEntity> .",
        f"<http://example.org/entity3> <http://vital.ai/ontology/vital-core#hasName> \"Happy Valley\" .",
        f"<http://example.org/entity3> <http://example.org/hasType> \"Location\" .",
        f"<http://example.org/entity3> <http://example.org/hasPopulation> \"50000\" .",
        
        # Non-happy entities for contrast
        f"<http://example.org/entity4> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://vital.ai/ontology/haley-ai-kg#KGEntity> .",
        f"<http://example.org/entity4> <http://vital.ai/ontology/vital-core#hasName> \"sad person\" .",
        f"<http://example.org/entity4> <http://example.org/hasAge> \"30\" .",
        
        f"<http://example.org/entity5> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://vital.ai/ontology/haley-ai-kg#KGEntity> .",
        f"<http://example.org/entity5> <http://vital.ai/ontology/vital-core#hasName> \"neutral entity\" .",
        f"<http://example.org/entity5> <http://example.org/hasType> \"Object\" .",
    ]
    
    # Insert data as N-Triples
    ntriples_data = "\n".join(test_data)
    
    try:
        result = await space.insert_rdf_data(ntriples_data, "text/plain", GRAPH_URI)
        print(f"✅ Inserted {len(test_data)} triples successfully")
        return True
    except Exception as e:
        print(f"❌ Failed to insert test data: {e}")
        return False

async def run_construct_query(space):
    """Run the CONSTRUCT query and measure performance."""
    print("\n🔍 Running CONSTRUCT Query for Happy Entities")
    print("=" * 60)
    
    # The CONSTRUCT query to test
    construct_query = f"""
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        CONSTRUCT {{
            ?entity ?predicate ?object .
        }}
        WHERE {{
            {{
                SELECT DISTINCT ?entity WHERE {{
                    GRAPH <{GRAPH_URI}> {{
                        ?entity rdf:type haley:KGEntity .
                        ?entity vital:hasName ?name .
                        FILTER(REGEX(?name, "happy", "i"))
                    }}
                }}
            }}
            
            GRAPH <{GRAPH_URI}> {{
                ?entity ?predicate ?object .
            }}
        }}
        ORDER BY ?entity
    """
    
    print("SPARQL Query:")
    print(construct_query)
    print()
    print("-" * 60)
    
    # Execute the query with timing
    start_time = time.time()
    
    try:
        results = await space.execute_sparql_query(construct_query)
        
        end_time = time.time()
        execution_time = end_time - start_time
        
        print(f"⏱️  Execution Time: {execution_time:.3f}s")
        print(f"📊 Results Count: {len(results)}")
        
        # Display results for verification
        if results:
            print("\nResults:")
            for i, result in enumerate(results, 1):
                print(f"  [{i}] {result}")
        else:
            print("No results returned")
            
        return execution_time, len(results)
        
    except Exception as e:
        end_time = time.time()
        execution_time = end_time - start_time
        print(f"❌ Query failed after {execution_time:.3f}s: {e}")
        import traceback
        traceback.print_exc()
        return execution_time, 0

async def main():
    print("🧪 CONSTRUCT Query Performance Test - Happy Entities")
    print("=" * 60)
    
    # Initialize
    try:
        config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
        config = get_config(str(config_path))
        
        vital_graph = VitalGraphImpl(config=config)
        await vital_graph.db_impl.connect()
        print("✅ Connected to database")
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        return
    
    try:
        # Create test space
        space_manager = vital_graph.space_manager
        
        # Clean up any existing test space
        existing_space = space_manager.get_space(SPACE_ID)
        if existing_space:
            print(f"🧹 Cleaning up existing space '{SPACE_ID}'...")
            await space_manager.delete_space_with_tables(SPACE_ID)
        
        # Create new test space
        print(f"🏗️  Creating test space '{SPACE_ID}'...")
        space = await space_manager.create_space(SPACE_ID, "CONSTRUCT Performance Test Space")
        
        if not space:
            print(f"❌ Failed to create space '{SPACE_ID}'")
            return
        
        print(f"✅ Created space '{SPACE_ID}' successfully")
        
        # Set up test data
        if not await setup_test_data(space):
            return
        
        # Run the CONSTRUCT query test
        execution_time, result_count = await run_construct_query(space)
        
        print("\n" + "=" * 60)
        print("📈 Performance Summary:")
        print(f"   ⏱️  Execution Time: {execution_time:.3f}s")
        print(f"   📊 Results: {result_count}")
        
        if execution_time > 5.0:
            print("   ⚠️  Query is slow (>5s) - optimization needed")
        elif execution_time > 1.0:
            print("   ⚡ Query is moderately fast (1-5s)")
        else:
            print("   🚀 Query is fast (<1s)")
        
        # Clean up test space
        print(f"\n🧹 Cleaning up test space '{SPACE_ID}'...")
        await space_manager.delete_space_with_tables(SPACE_ID)
        print("✅ Test space cleaned up")
        
    finally:
        # Disconnect
        try:
            await vital_graph.db_impl.disconnect()
            print("🔌 Disconnected")
        except Exception as e:
            print(f"❌ Error during disconnect: {e}")
    
    print("\n✅ CONSTRUCT Query Performance Test Complete!")

if __name__ == "__main__":
    asyncio.run(main())
