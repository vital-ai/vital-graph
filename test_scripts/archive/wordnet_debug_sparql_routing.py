#!/usr/bin/env python3
"""
Debug script to understand how SPARQL queries are routed through the VitalGraphSQLStore.
This will help us understand why our optimizations aren't being triggered.
"""

import os
import time
import logging
from sqlalchemy import URL, create_engine
from rdflib import Graph, URIRef, Literal

# Add the parent directory to the path so we can import vitalgraph
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from vitalgraph.store.store import VitalGraphSQLStore

# Set up detailed logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Database configuration
PG_HOST = os.getenv("PG_HOST", "127.0.0.1")
PG_PORT = os.getenv("PG_PORT", "5432")
PG_DATABASE = os.getenv("PG_DATABASE", "vitalgraphdb")
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "")

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

class DebuggingVitalGraphSQLStore(VitalGraphSQLStore):
    """Extended store with debugging capabilities"""
    
    def __init__(self):
        super().__init__()
        self.optimization_calls = {
            'text_search_detection': 0,
            'optimized_path_used': 0,
            'fallback_path_used': 0,
            'triples_helper_calls': 0,
            'do_triples_select_calls': 0
        }
    
    def _is_text_search_query(self, triple, context=None):
        """Debug version of text search detection"""
        self.optimization_calls['text_search_detection'] += 1
        result = super()._is_text_search_query(triple, context)
        print(f"🔍 TEXT SEARCH DETECTION: {triple} -> {result}")
        return result
    
    def _triples_helper_optimized_text_search(self, triple, context=None):
        """Debug version of optimized text search"""
        self.optimization_calls['optimized_path_used'] += 1
        print(f"🚀 USING OPTIMIZED PATH: {triple}")
        return super()._triples_helper_optimized_text_search(triple, context)
    
    def _triples_helper(self, triple, context=None):
        """Debug version of triples helper"""
        self.optimization_calls['triples_helper_calls'] += 1
        print(f"🔧 TRIPLES HELPER CALLED: {triple}")
        
        # Check if optimization path is taken
        if self._is_text_search_query(triple, context):
            print("✅ Text search detected - using optimized path")
            return self._triples_helper_optimized_text_search(triple, context)
        else:
            print("⚪ No text search detected - using fallback path")
            self.optimization_calls['fallback_path_used'] += 1
            return super()._triples_helper(triple, context)
    
    def _do_triples_select(self, selects, context):
        """Debug version of do triples select"""
        self.optimization_calls['do_triples_select_calls'] += 1
        print(f"📊 DO TRIPLES SELECT: {len(selects)} selects")
        for i, (table, clause, table_type) in enumerate(selects):
            print(f"   {i+1}. Table type: {table_type}, Clause: {clause}")
        return super()._do_triples_select(selects, context)
    
    def triples(self, triple, context=None):
        """Debug version of triples method"""
        print(f"🎯 TRIPLES METHOD CALLED: {triple}")
        return super().triples(triple, context)

def test_direct_triples_call():
    """Test calling triples method directly"""
    print("=" * 60)
    print("TESTING DIRECT TRIPLES() CALL")
    print("=" * 60)
    
    store = DebuggingVitalGraphSQLStore()
    
    # Build database URL and setup
    db_url = URL.create(
        drivername="postgresql+psycopg",
        username=PG_USER,
        password=PG_PASSWORD or None,
        host=PG_HOST,
        port=PG_PORT,
        database=PG_DATABASE,
    )
    
    engine = create_engine(db_url)
    store.engine = engine
    store._create_table_definitions()
    
    # Test direct call to triples method
    print("Testing direct call to store.triples() with text search pattern...")
    
    # Create a triple pattern that should trigger text search optimization
    triple = (None, None, Literal("happy"))
    context = URIRef("http://vital.ai/graph/wordnet")
    
    start_time = time.time()
    results = list(store.triples(triple, context))
    elapsed = time.time() - start_time
    
    print(f"\nResults: {len(results)} found in {elapsed:.3f} seconds")
    print(f"Optimization calls: {store.optimization_calls}")
    
    return store

def test_sparql_query_routing():
    """Test how SPARQL queries are routed"""
    print("=" * 60)
    print("TESTING SPARQL QUERY ROUTING")
    print("=" * 60)
    
    store = DebuggingVitalGraphSQLStore()
    
    # Build database URL and setup
    db_url = URL.create(
        drivername="postgresql+psycopg",
        username=PG_USER,
        password=PG_PASSWORD or None,
        host=PG_HOST,
        port=PG_PORT,
        database=PG_DATABASE,
    )
    
    engine = create_engine(db_url)
    store.engine = engine
    store._create_table_definitions()
    
    # Create graph with debugging store
    graph = Graph(store, identifier=URIRef("http://vital.ai/graph/wordnet"))
    
    print("Testing SPARQL query routing...")
    
    sparql_query = """
    SELECT ?s ?p ?o WHERE {
      ?s ?p ?o .
      FILTER(CONTAINS(STR(?o), "happy"))
    }
    LIMIT 3
    """
    
    print(f"SPARQL Query: {sparql_query}")
    
    start_time = time.time()
    results = list(graph.query(sparql_query))
    elapsed = time.time() - start_time
    
    print(f"\nResults: {len(results)} found in {elapsed:.3f} seconds")
    print(f"Optimization calls: {store.optimization_calls}")
    
    # Check if our optimizations were called at all
    if store.optimization_calls['triples_helper_calls'] == 0:
        print("❌ PROBLEM: Our triples_helper was never called!")
        print("   SPARQL engine is bypassing our optimization layer.")
    elif store.optimization_calls['optimized_path_used'] == 0:
        print("⚠️  ISSUE: triples_helper was called but optimization path wasn't used")
    else:
        print("✅ SUCCESS: Optimization path was used!")
    
    return store

def main():
    """Run SPARQL routing debugging tests"""
    print("🔍 SPARQL ROUTING DEBUG ANALYSIS")
    print("=" * 60)
    print()
    
    try:
        # Test direct triples call
        store1 = test_direct_triples_call()
        print()
        
        # Test SPARQL query routing
        store2 = test_sparql_query_routing()
        print()
        
        print("=" * 60)
        print("🎯 DEBUGGING ANALYSIS COMPLETE")
        print("=" * 60)
        
        # Summary
        print("\nSUMMARY:")
        print(f"Direct triples() calls: {store1.optimization_calls}")
        print(f"SPARQL query calls: {store2.optimization_calls}")
        
        if store2.optimization_calls['triples_helper_calls'] == 0:
            print("\n🚨 ROOT CAUSE IDENTIFIED:")
            print("   SPARQL queries bypass our triples_helper optimization layer!")
            print("   We need to hook into a different part of the query execution pipeline.")
        
    except Exception as e:
        print(f"✗ DEBUG ANALYSIS FAILED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
