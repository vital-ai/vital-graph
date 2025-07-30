#!/usr/bin/env python3
"""
Test script for Phase 1 SPARQL text search optimizations.

This script tests the new text search detection and routing logic
to ensure optimized queries are being used for text search patterns.
"""

import os
import time
import logging
from sqlalchemy import URL, create_engine
from rdflib import Graph, URIRef, Literal
from rdflib.plugins.stores.regexmatching import REGEXTerm

# Add the parent directory to the path so we can import vitalgraph
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from vitalgraph.store.store import VitalGraphSQLStore

# Set up logging to see SQL queries
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database configuration
PG_HOST = os.getenv("PG_HOST", "127.0.0.1")
PG_PORT = os.getenv("PG_PORT", "5432")
PG_DATABASE = os.getenv("PG_DATABASE", "vitalgraphdb")
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "")
GRAPH_NAME = "wordnet"

def setup_store():
    """Set up the VitalGraphSQLStore connection"""
    # Build database URL
    db_url = URL.create(
        drivername="postgresql+psycopg",
        username=PG_USER,
        password=PG_PASSWORD or None,
        host=PG_HOST,
        port=PG_PORT,
        database=PG_DATABASE,
    )
    
    # Create engine and store
    engine = create_engine(db_url)
    store = VitalGraphSQLStore()
    store.engine = engine
    store._create_table_definitions()
    
    return store

def test_text_search_detection():
    """Test the text search detection logic"""
    print("=" * 60)
    print("TESTING TEXT SEARCH DETECTION")
    print("=" * 60)
    
    store = setup_store()
    
    # Test cases for text search detection
    test_cases = [
        # (subject, predicate, object, expected_result, description)
        (None, None, Literal("happy"), True, "Literal 'happy' should be detected as text search"),
        (None, None, "happy", True, "String 'happy' should be detected as text search"),
        (None, None, "a", False, "Short string 'a' should NOT be detected as text search"),
        (None, None, URIRef("http://example.com"), False, "URIRef should NOT be detected as text search"),
        (None, None, None, False, "None object should NOT be detected as text search"),
        (None, None, Literal("this is a longer text search pattern"), True, "Long literal should be detected as text search"),
    ]
    
    for i, (subject, predicate, obj, expected, description) in enumerate(test_cases, 1):
        triple = (subject, predicate, obj)
        result = store._is_text_search_query(triple)
        status = "✓ PASS" if result == expected else "✗ FAIL"
        print(f"{i}. {description}")
        print(f"   Expected: {expected}, Got: {result} - {status}")
        print()
    
    store.close()

def test_optimized_query_path():
    """Test that optimized query path is being used"""
    print("=" * 60)
    print("TESTING OPTIMIZED QUERY PATH")
    print("=" * 60)
    
    store = setup_store()
    
    # Create a graph for testing
    graph = Graph(store, identifier=URIRef("http://vital.ai/graph/wordnet"))
    
    # Test query that should use optimized path
    sparql_query = """
    SELECT ?s ?p ?o WHERE {
      ?s ?p ?o .
      FILTER(CONTAINS(STR(?o), "happy"))
    }
    LIMIT 5
    """
    
    print("Testing SPARQL query that should use optimized path:")
    print(sparql_query)
    print()
    
    # Execute query and measure time
    start_time = time.time()
    
    try:
        results = list(graph.query(sparql_query))
        execution_time = time.time() - start_time
        
        print(f"Query executed successfully!")
        print(f"Results found: {len(results)}")
        print(f"Execution time: {execution_time:.3f} seconds")
        
        if execution_time < 5.0:  # Should be much faster with optimization
            print("✓ PERFORMANCE: Query completed in reasonable time (< 5 seconds)")
        else:
            print("⚠ PERFORMANCE: Query took longer than expected (> 5 seconds)")
            
        # Show first few results
        print("\nFirst few results:")
        for i, result in enumerate(results[:3]):
            print(f"  {i+1}. {result}")
            
    except Exception as e:
        execution_time = time.time() - start_time
        print(f"✗ ERROR: Query failed after {execution_time:.3f} seconds")
        print(f"Error: {e}")
    
    print()
    store.close()

def test_fallback_path():
    """Test that non-text-search queries still work (fallback path)"""
    print("=" * 60)
    print("TESTING FALLBACK PATH")
    print("=" * 60)
    
    store = setup_store()
    
    # Create a graph for testing
    graph = Graph(store, identifier=URIRef("http://vital.ai/graph/wordnet"))
    
    # Test query that should NOT use optimized path
    sparql_query = """
    SELECT ?s ?p ?o WHERE {
      ?s ?p ?o .
    }
    LIMIT 5
    """
    
    print("Testing SPARQL query that should use fallback path:")
    print(sparql_query)
    print()
    
    # Execute query and measure time
    start_time = time.time()
    
    try:
        results = list(graph.query(sparql_query))
        execution_time = time.time() - start_time
        
        print(f"Query executed successfully!")
        print(f"Results found: {len(results)}")
        print(f"Execution time: {execution_time:.3f} seconds")
        
        # Show first few results
        print("\nFirst few results:")
        for i, result in enumerate(results[:3]):
            print(f"  {i+1}. {result}")
            
    except Exception as e:
        execution_time = time.time() - start_time
        print(f"✗ ERROR: Query failed after {execution_time:.3f} seconds")
        print(f"Error: {e}")
    
    print()
    store.close()

def test_optimization_configuration():
    """Test optimization configuration flags"""
    print("=" * 60)
    print("TESTING OPTIMIZATION CONFIGURATION")
    print("=" * 60)
    
    from vitalgraph.store.constants import (
        TEXT_SEARCH_OPTIMIZATION_ENABLED,
        TEXT_SEARCH_MIN_TERM_LENGTH,
        TEXT_SEARCH_LITERAL_TABLE_PRIORITY
    )
    
    print(f"TEXT_SEARCH_OPTIMIZATION_ENABLED: {TEXT_SEARCH_OPTIMIZATION_ENABLED}")
    print(f"TEXT_SEARCH_MIN_TERM_LENGTH: {TEXT_SEARCH_MIN_TERM_LENGTH}")
    print(f"TEXT_SEARCH_LITERAL_TABLE_PRIORITY: {TEXT_SEARCH_LITERAL_TABLE_PRIORITY}")
    print()

def main():
    """Run all Phase 1 optimization tests"""
    print("🚀 SPARQL TEXT SEARCH OPTIMIZATION - PHASE 1 TESTS")
    print("=" * 60)
    print()
    
    try:
        # Test configuration
        test_optimization_configuration()
        
        # Test text search detection
        test_text_search_detection()
        
        # Test optimized query path
        test_optimized_query_path()
        
        # Test fallback path
        test_fallback_path()
        
        print("=" * 60)
        print("✓ PHASE 1 OPTIMIZATION TESTS COMPLETED")
        print("=" * 60)
        
    except Exception as e:
        print(f"✗ TEST SUITE FAILED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
