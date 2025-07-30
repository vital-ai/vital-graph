#!/usr/bin/env python3

import logging
import sys
import time
from rdflib import Graph, URIRef, Literal
from vitalgraph.store.store import VitalGraphSQLStore
from sqlalchemy import text

# Configure logging to show IMMEDIATELY
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d [%(name)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stdout
)

# Force immediate output
sys.stdout.reconfigure(line_buffering=True)

# Enable vitalgraph logging
vitalgraph_logger = logging.getLogger('vitalgraph.store')
vitalgraph_logger.setLevel(logging.INFO)

# Get logger for this script
_logger = logging.getLogger(__name__)

print("🚀 STARTING IMMEDIATE LOGGING TEST")
print(f"⏰ Current time: {time.time()}")
_logger.info("🚀 SCRIPT STARTED - IMMEDIATE LOG")
sys.stdout.flush()  # Force immediate output

try:
    # Connect to PostgreSQL
    print("📡 Connecting to PostgreSQL...")
    _logger.info("🚀 ABOUT TO CREATE VitalGraphSQLStore")
    sys.stdout.flush()
    
    config = "postgresql+psycopg://postgres@127.0.0.1:5432/vitalgraphdb"
    store = VitalGraphSQLStore(identifier="hardcoded")
    
    _logger.info("🚀 VitalGraphSQLStore CREATED - ABOUT TO OPEN")
    sys.stdout.flush()
    print("🔧 Opening store...")
    store.open(config)
    
    _logger.info("🚀 STORE OPENED SUCCESSFULLY")
    sys.stdout.flush()
    
    print("📊 Creating ConjunctiveGraph...")
    _logger.info("🚀 ABOUT TO CREATE GRAPH WITH WORDNET CONTEXT")
    sys.stdout.flush()
    
    # Use the correct WordNet graph context
    wordnet_context = "http://vital.ai/graph/wordnet"
    graph = Graph(store=store, identifier=wordnet_context)
    
    _logger.info("🚀 GRAPH CREATED SUCCESSFULLY")
    sys.stdout.flush()
    
    # First, let's check what data exists in the database
    print("🔍 Checking database contents...")
    
    # Check total row counts in each table
    with store.engine.connect() as conn:
        tables = ['literal_statements', 'asserted_statements', 'type_statements', 'quoted_statements']
        for table_name in tables:
            full_table_name = f"kb_bec6803d52_{table_name}"
            try:
                result = conn.execute(text(f"SELECT COUNT(*) FROM {full_table_name}"))
                count = result.fetchone()[0]
                print(f"  📋 {full_table_name}: {count:,} rows")
            except Exception as e:
                print(f"  ❌ {full_table_name}: Error - {e}")
    
    # Check what contexts exist
    print("\n🔍 Checking available contexts...")
    with store.engine.connect() as conn:
        try:
            result = conn.execute(text("SELECT DISTINCT context FROM kb_bec6803d52_literal_statements LIMIT 10"))
            contexts = [row[0] for row in result.fetchall()]
            print(f"  📋 Found {len(contexts)} contexts in literal_statements:")
            for ctx in contexts:
                print(f"    - {ctx}")
        except Exception as e:
            print(f"  ❌ Error checking contexts: {e}")
    
    print("\n🔍 About to execute SIMPLE SPARQL query...")
    print(f"⏰ Query start time: {time.time()}")
    
    # Simple query that should trigger logging immediately
    simple_query = """
    SELECT ?s ?p ?o WHERE {
        ?s ?p ?o .
    } LIMIT 5
    """
    
    print("🎯 CALLING graph.query() NOW...")
    
    # Add comprehensive logging to trace the delay
    _logger.info("🚀 ABOUT TO CALL graph.query() - IMMEDIATE LOG")
    sys.stdout.flush()
    
    # Enable ALL rdflib logging to see what's happening
    logging.getLogger('rdflib').setLevel(logging.DEBUG)
    logging.getLogger('rdflib.plugins.sparql').setLevel(logging.DEBUG)
    
    _logger.info("🚀 CALLING graph.query() - START NOW")
    sys.stdout.flush()
    query_start_time = time.time()
    print(f"🔥 IMMEDIATE: About to execute query at {query_start_time}")
    sys.stdout.flush()
    
    results = list(graph.query(simple_query))
    
    query_end_time = time.time()
    _logger.info(f"🚀 graph.query() COMPLETED in {query_end_time - query_start_time:.3f} seconds")
    
    print(f"🎯 QUERY COMPLETED at {time.time()}")
    
    print(f"✅ Got {len(results)} results")
    for i, result in enumerate(results):
        print(f"  Result {i+1}: {result}")
        
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()

print("🏁 Test completed")
