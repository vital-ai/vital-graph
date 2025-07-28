#!/usr/bin/env python3

import asyncio
from pathlib import Path

# Configuration
SPACE_ID = "wordnet_space"

async def debug_filter_results():
    """Debug the exact results from the failing FILTER test."""
    
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
    
    print("🔍 DEBUGGING FILTER RESULTS MISMATCH")
    print("=" * 60)
    
    # Execute with original implementation
    print("\n📊 ORIGINAL IMPLEMENTATION RESULTS:")
    try:
        original_results = await original_sparql.execute_sparql_query(SPACE_ID, query)
        print(f"Count: {len(original_results)}")
        for i, result in enumerate(original_results, 1):
            print(f"[{i}] {result}")
    except Exception as e:
        print(f"❌ Original failed: {e}")
    
    # Execute with refactored implementation  
    print("\n📊 REFACTORED IMPLEMENTATION RESULTS:")
    try:
        refactored_results = await refactored_sparql.execute_sparql_query(SPACE_ID, query)
        print(f"Count: {len(refactored_results)}")
        for i, result in enumerate(refactored_results, 1):
            print(f"[{i}] {result}")
    except Exception as e:
        print(f"❌ Refactored failed: {e}")
    
    # Compare results
    print("\n🔍 DETAILED COMPARISON:")
    if 'original_results' in locals() and 'refactored_results' in locals():
        if len(original_results) == len(refactored_results):
            print(f"✅ Same count: {len(original_results)}")
            
            # Check if results are identical
            original_set = {frozenset(r.items()) for r in original_results}
            refactored_set = {frozenset(r.items()) for r in refactored_results}
            
            if original_set == refactored_set:
                print("✅ Results are identical!")
            else:
                print("❌ Results differ in content:")
                print(f"   Original only: {original_set - refactored_set}")
                print(f"   Refactored only: {refactored_set - original_set}")
        else:
            print(f"❌ Different counts: Original={len(original_results)}, Refactored={len(refactored_results)}")

if __name__ == "__main__":
    asyncio.run(debug_filter_results())
