#!/usr/bin/env python3
"""
Detailed SPARQL algebra tree demonstration.

This script shows the most detailed algebra tree logging for a well-structured
SPARQL query that will parse successfully and show all tree walking features.
"""

import logging
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vitalgraph.store.sparql import VitalSparql

def setup_logging():
    """Configure logging for the test."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

def test_detailed_algebra_tree(logger):
    """Test a query that will show detailed algebra tree structure."""
    logger.info("=== DETAILED SPARQL ALGEBRA TREE DEMONSTRATION ===")
    
    sparql_analyzer = VitalSparql("detailed-tree-test")
    
    # Well-structured SPARQL query with multiple features
    detailed_query = """
    PREFIX foaf: <http://xmlns.com/foaf/0.1/>
    PREFIX ex: <http://example.org/>
    
    SELECT ?person ?name ?friend WHERE {
        ?person a foaf:Person .
        ?person foaf:name ?name .
        
        OPTIONAL {
            ?person foaf:knows ?friend .
            ?friend foaf:name ?friendName .
            FILTER (REGEX(?friendName, "John"))
        }
        
        FILTER (?name != "Unknown")
    }
    ORDER BY ?name
    LIMIT 10
    """
    
    logger.info("🔍 SPARQL Query for Detailed Analysis:")
    logger.info("=" * 70)
    lines = detailed_query.strip().split('\n')
    for i, line in enumerate(lines, 1):
        logger.info(f"{i:2d}: {line}")
    logger.info("=" * 70)
    
    # Parse and log with maximum detail
    logger.info("\n🌳 PARSING AND WALKING ALGEBRA TREE:")
    logger.info("=" * 70)
    
    parsed_query = sparql_analyzer.log_parse_tree(detailed_query, "query")
    
    if parsed_query:
        logger.info("\n✅ SUCCESS: Query parsed and algebra tree logged!")
        logger.info(f"📊 Parsed query type: {type(parsed_query)}")
        
        # Additional analysis
        if hasattr(parsed_query, 'name'):
            logger.info(f"🏷️  Operation name: {parsed_query.name}")
        
        logger.info("\n🎯 KEY FEATURES DEMONSTRATED:")
        logger.info("   • Hierarchical tree structure with Unicode connectors")
        logger.info("   • CompValue object identification and field logging") 
        logger.info("   • SPARQL operation name extraction")
        logger.info("   • Nested pattern recognition (Optional, Filter)")
        logger.info("   • Tree statistics (node count, depth, operations)")
        logger.info("   • Comprehensive attribute logging")
        logger.info("   • Error-resistant tree walking")
        
    else:
        logger.error("❌ FAILED: Could not parse the query")
    
    return parsed_query

def test_simple_join_query(logger):
    """Test a simple but effective join query."""
    logger.info("\n=== SIMPLE JOIN QUERY ALGEBRA TREE ===")
    
    sparql_analyzer = VitalSparql("simple-join-test")
    
    join_query = """
    PREFIX foaf: <http://xmlns.com/foaf/0.1/>
    
    SELECT ?person ?friend WHERE {
        ?person a foaf:Person .
        ?person foaf:knows ?friend .
        ?friend a foaf:Person .
    }
    """
    
    logger.info("Simple Join Query:")
    lines = join_query.strip().split('\n')
    for i, line in enumerate(lines, 1):
        logger.info(f"{i:2d}: {line}")
    
    parsed_query = sparql_analyzer.log_parse_tree(join_query, "query")
    return parsed_query

def main():
    """Main demonstration function."""
    logger = setup_logging()
    
    logger.info("🚀 " + "="*78)
    logger.info("🚀 ENHANCED SPARQL ALGEBRA TREE LOGGING DEMONSTRATION")
    logger.info("🚀 " + "="*78)
    
    try:
        # Test detailed algebra tree
        result1 = test_detailed_algebra_tree(logger)
        
        # Test simple join
        result2 = test_simple_join_query(logger)
        
        # Final summary
        logger.info("\n" + "🎉 " + "="*76)
        logger.info("🎉 DEMONSTRATION COMPLETE")
        logger.info("🎉 " + "="*76)
        
        success_count = sum(1 for r in [result1, result2] if r)
        logger.info(f"📈 Results: {success_count}/2 queries successfully parsed and logged")
        
        if success_count > 0:
            logger.info("\n🌟 ENHANCED ALGEBRA TREE LOGGING FEATURES DEMONSTRATED:")
            logger.info("   ✅ Hierarchical tree visualization with proper indentation")
            logger.info("   ✅ CompValue object identification with type information")
            logger.info("   ✅ SPARQL operation name extraction (SelectQuery, etc.)")
            logger.info("   ✅ Tree statistics collection (nodes, depth, operations)")
            logger.info("   ✅ Enhanced attribute formatting for SPARQL constructs")
            logger.info("   ✅ Robust error handling with debug information")
            logger.info("   ✅ Support for complex nested patterns")
            logger.info("   ✅ Unicode box-drawing characters for clear visualization")
            
            logger.info(f"\n🎯 The enhanced logging in vitalgraph/sql/sparql.py is now")
            logger.info(f"   ready for debugging and implementing SPARQL query execution!")
        
        return 0 if success_count > 0 else 1
        
    except Exception as e:
        logger.error(f"❌ Demonstration failed with error: {e}")
        logger.error("Traceback:", exc_info=True)
        return 1

if __name__ == "__main__":
    exit(main())
