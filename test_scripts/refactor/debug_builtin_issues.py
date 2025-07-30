#!/usr/bin/env python3
"""
Debug script to identify specific issues with builtin function implementations
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl

# Import BOTH implementations for comparison
from vitalgraph.db.postgresql.postgresql_sparql_impl import PostgreSQLSparqlImpl as OriginalSparqlImpl
from vitalgraph.db.postgresql.sparql.postgres_sparql_impl import PostgreSQLSparqlImpl as RefactoredSparqlImpl

# Reduce logging chatter
logging.getLogger('vitalgraph.db.postgresql.postgresql_space_impl').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.rdf.rdf_utils').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.db.postgresql.postgresql_cache_term').setLevel(logging.WARNING)

# Configuration
SPACE_ID = "space_test"
GRAPH_URI = "http://vital.ai/graph/test"
GLOBAL_GRAPH_URI = "urn:___GLOBAL"

async def test_substr_issue():
    """Test SUBSTR function specifically to identify the issue"""
    
    # Initialize using the same pattern as working test scripts
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    space_impl = impl.db_impl.get_space_impl()
    
    # Initialize BOTH implementations with the same space_impl
    original_sparql_impl = OriginalSparqlImpl(space_impl)
    refactored_sparql_impl = RefactoredSparqlImpl(space_impl)
    
    # Test SUBSTR function
    sparql_query = '''
    PREFIX ex: <http://example.org/>
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    
    SELECT ?person ?name ?substring WHERE {
        GRAPH <urn:___GLOBAL> {
            ?person rdf:type ex:Person ;
                   ex:hasName ?name .
            BIND(SUBSTR(?name, 1, 3) AS ?substring)
        }
    } LIMIT 3
    '''
    
    print("🔍 Testing SUBSTR function:")
    print(f"Query: {sparql_query.strip()}")
    
    try:
        # Test original implementation
        print("\n📊 Original implementation:")
        original_results = await original_sparql_impl.execute_sparql_query(SPACE_ID, sparql_query)
        print(f"Results: {len(original_results)}")
        for i, result in enumerate(original_results[:2]):
            print(f"  [{i+1}] {result}")
            
    except Exception as e:
        print(f"❌ Original error: {e}")
        
    try:
        # Test refactored implementation
        print("\n📊 Refactored implementation:")
        refactored_results = await refactored_sparql_impl.execute_sparql_query(SPACE_ID, sparql_query)
        print(f"Results: {len(refactored_results)}")
        for i, result in enumerate(refactored_results[:2]):
            print(f"  [{i+1}] {result}")
            
    except Exception as e:
        print(f"❌ Refactored error: {e}")
        import traceback
        traceback.print_exc()

async def test_contains_issue():
    """Test CONTAINS function specifically to identify the issue"""
    
    # Initialize using the same pattern as working test scripts
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    space_impl = impl.db_impl.get_space_impl()
    
    # Initialize BOTH implementations with the same space_impl
    original_sparql_impl = OriginalSparqlImpl(space_impl)
    refactored_sparql_impl = RefactoredSparqlImpl(space_impl)
    
    # Test CONTAINS function
    sparql_query = '''
    PREFIX ex: <http://example.org/>
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    
    SELECT ?person ?name ?hasA WHERE {
        GRAPH <urn:___GLOBAL> {
            ?person rdf:type ex:Person ;
                   ex:hasName ?name .
            BIND(CONTAINS(?name, "A") AS ?hasA)
        }
    } LIMIT 3
    '''
    
    print("\n🔍 Testing CONTAINS function:")
    print(f"Query: {sparql_query.strip()}")
    
    try:
        # Test original implementation
        print("\n📊 Original implementation:")
        original_results = await original_sparql_impl.execute_sparql_query(SPACE_ID, sparql_query)
        print(f"Results: {len(original_results)}")
        for i, result in enumerate(original_results[:2]):
            print(f"  [{i+1}] {result}")
            
    except Exception as e:
        print(f"❌ Original error: {e}")
        
    try:
        # Test refactored implementation
        print("\n📊 Refactored implementation:")
        refactored_results = await refactored_sparql_impl.execute_sparql_query(SPACE_ID, sparql_query)
        print(f"Results: {len(refactored_results)}")
        for i, result in enumerate(refactored_results[:2]):
            print(f"  [{i+1}] {result}")
            
    except Exception as e:
        print(f"❌ Refactored error: {e}")
        import traceback
        traceback.print_exc()

async def test_string_search_functions():
    """Test STRSTARTS, STRENDS functions"""
    
    # Initialize using the same pattern as working test scripts
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    space_impl = impl.db_impl.get_space_impl()
    
    # Initialize BOTH implementations with the same space_impl
    original_sparql_impl = OriginalSparqlImpl(space_impl)
    refactored_sparql_impl = RefactoredSparqlImpl(space_impl)
    
    # Test STRSTARTS function
    sparql_query = '''
    PREFIX ex: <http://example.org/>
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    
    SELECT ?person ?name ?startsWithJ WHERE {
        GRAPH <urn:___GLOBAL> {
            ?person rdf:type ex:Person ;
                   ex:hasName ?name .
            BIND(STRSTARTS(?name, "J") AS ?startsWithJ)
        }
    } LIMIT 3
    '''
    
    print("\n🔍 Testing STRSTARTS function:")
    print(f"Query: {sparql_query.strip()}")
    
    try:
        print("\n📊 Original implementation:")
        original_results = await original_sparql_impl.execute_sparql_query(SPACE_ID, sparql_query)
        print(f"Results: {len(original_results)}")
        for i, result in enumerate(original_results[:2]):
            print(f"  [{i+1}] {result}")
    except Exception as e:
        print(f"❌ Original error: {e}")
        
    try:
        print("\n📊 Refactored implementation:")
        refactored_results = await refactored_sparql_impl.execute_sparql_query(SPACE_ID, sparql_query)
        print(f"Results: {len(refactored_results)}")
        for i, result in enumerate(refactored_results[:2]):
            print(f"  [{i+1}] {result}")
    except Exception as e:
        print(f"❌ Refactored error: {e}")
        import traceback
        traceback.print_exc()

async def test_replace_function():
    """Test REPLACE function"""
    
    # Initialize using the same pattern as working test scripts
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    space_impl = impl.db_impl.get_space_impl()
    
    # Initialize BOTH implementations with the same space_impl
    original_sparql_impl = OriginalSparqlImpl(space_impl)
    refactored_sparql_impl = RefactoredSparqlImpl(space_impl)
    
    # Test REPLACE function
    sparql_query = '''
    PREFIX ex: <http://example.org/>
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    
    SELECT ?person ?name ?replaced WHERE {
        GRAPH <urn:___GLOBAL> {
            ?person rdf:type ex:Person ;
                   ex:hasName ?name .
            BIND(REPLACE(?name, "Johnson", "Smith") AS ?replaced)
        }
    } LIMIT 3
    '''
    
    print("\n🔍 Testing REPLACE function:")
    print(f"Query: {sparql_query.strip()}")
    
    try:
        print("\n📊 Original implementation:")
        original_results = await original_sparql_impl.execute_sparql_query(SPACE_ID, sparql_query)
        print(f"Results: {len(original_results)}")
        for i, result in enumerate(original_results[:2]):
            print(f"  [{i+1}] {result}")
    except Exception as e:
        print(f"❌ Original error: {e}")
        
    try:
        print("\n📊 Refactored implementation:")
        refactored_results = await refactored_sparql_impl.execute_sparql_query(SPACE_ID, sparql_query)
        print(f"Results: {len(refactored_results)}")
        for i, result in enumerate(refactored_results[:2]):
            print(f"  [{i+1}] {result}")
    except Exception as e:
        print(f"❌ Refactored error: {e}")
        import traceback
        traceback.print_exc()

async def test_filter_expression_issue():
    """Test the problematic filter expression with LCASE"""
    
    # Initialize using the same pattern as working test scripts
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    space_impl = impl.db_impl.get_space_impl()
    
    # Initialize BOTH implementations with the same space_impl
    original_sparql_impl = OriginalSparqlImpl(space_impl)
    refactored_sparql_impl = RefactoredSparqlImpl(space_impl)
    
    # Test problematic filter expression
    sparql_query = '''
    PREFIX ex: <http://example.org/>
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    
    SELECT ?person ?name WHERE {
        GRAPH <urn:___GLOBAL> {
            ?person rdf:type ex:Person ;
                   ex:hasName ?name .
            FILTER(STRLEN(?name) > 4 && CONTAINS(LCASE(?name), "j"))
        }
    } LIMIT 3
    '''
    
    print("\n🔍 Testing problematic FILTER expression with LCASE:")
    print(f"Query: {sparql_query.strip()}")
    
    try:
        print("\n📊 Original implementation:")
        original_results = await original_sparql_impl.execute_sparql_query(SPACE_ID, sparql_query)
        print(f"Results: {len(original_results)}")
        for i, result in enumerate(original_results[:2]):
            print(f"  [{i+1}] {result}")
    except Exception as e:
        print(f"❌ Original error: {e}")
        
    try:
        print("\n📊 Refactored implementation:")
        refactored_results = await refactored_sparql_impl.execute_sparql_query(SPACE_ID, sparql_query)
        print(f"Results: {len(refactored_results)}")
        for i, result in enumerate(refactored_results[:2]):
            print(f"  [{i+1}] {result}")
    except Exception as e:
        print(f"❌ Refactored error: {e}")
        import traceback
        traceback.print_exc()

async def main():
    """Main test function"""
    print("🧪 COMPREHENSIVE BUILTIN FUNCTION DEBUG TEST")
    print("=" * 60)
    
    await test_substr_issue()
    await test_contains_issue()
    await test_string_search_functions()
    await test_replace_function()
    await test_filter_expression_issue()
    
    print("\n✅ Comprehensive debug test complete!")

if __name__ == "__main__":
    asyncio.run(main())
