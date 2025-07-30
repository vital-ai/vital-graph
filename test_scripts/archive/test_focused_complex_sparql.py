#!/usr/bin/env python3
"""
Focused test for complex SPARQL algebra tree logging.

This script demonstrates the enhanced algebra tree logging with
well-supported complex SPARQL features that should parse successfully.
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

def test_complex_select_with_joins_and_filters(logger):
    """Test complex SELECT query with joins, filters, and optional patterns."""
    logger.info("=== Complex SELECT Query with Joins, Filters, and Optional Patterns ===")
    
    sparql_analyzer = VitalSparql("complex-select-test")
    
    # Complex but well-supported SPARQL query
    complex_query = """
    PREFIX foaf: <http://xmlns.com/foaf/0.1/>
    PREFIX ex: <http://example.org/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    
    SELECT DISTINCT ?person ?name ?email ?friendName ?projectTitle WHERE {
        # Main person pattern
        ?person a foaf:Person .
        ?person foaf:name ?name .
        
        # Filter for names containing specific pattern
        FILTER (REGEX(?name, "John|Jane", "i"))
        
        # Optional email pattern
        OPTIONAL {
            ?person foaf:mbox ?email .
            FILTER (REGEX(STR(?email), "@example\\.org$"))
        }
        
        # Join with friends
        ?person foaf:knows ?friend .
        ?friend foaf:name ?friendName .
        
        # Optional project involvement
        OPTIONAL {
            ?person ex:worksOn ?project .
            ?project rdfs:label ?projectTitle .
            
            # Nested filter in optional block
            FILTER (STRLEN(?projectTitle) > 5)
        }
        
        # Union for additional constraints
        {
            ?person foaf:age ?age .
            FILTER (?age > 25)
        } UNION {
            ?person ex:experience ?exp .
            FILTER (?exp > "5 years")
        }
    }
    ORDER BY ?name ?friendName
    LIMIT 20
    """
    
    logger.info("Complex SELECT Query:")
    logger.info("=" * 60)
    lines = complex_query.strip().split('\n')
    for i, line in enumerate(lines, 1):
        logger.info(f"{i:2d}: {line}")
    logger.info("=" * 60)
    
    # Parse and log the algebra tree
    parsed_query = sparql_analyzer.log_parse_tree(complex_query, "query")
    
    return parsed_query

def test_nested_optional_and_union(logger):
    """Test query with nested optional patterns and unions."""
    logger.info("\n=== Query with Nested Optional Patterns and Unions ===")
    
    sparql_analyzer = VitalSparql("nested-patterns-test")
    
    nested_query = """
    PREFIX foaf: <http://xmlns.com/foaf/0.1/>
    PREFIX ex: <http://example.org/>
    
    SELECT ?person ?name ?contact ?contactType WHERE {
        ?person a foaf:Person ;
                foaf:name ?name .
        
        # Nested optional with union inside
        OPTIONAL {
            {
                ?person foaf:phone ?contact .
                BIND("phone" AS ?contactType)
            } UNION {
                ?person foaf:mbox ?contact .
                BIND("email" AS ?contactType)
            } UNION {
                ?person foaf:homepage ?contact .
                BIND("website" AS ?contactType)
            }
            
            # Filter within the optional block
            FILTER (BOUND(?contact))
        }
        
        # Another optional with subpattern
        OPTIONAL {
            ?person ex:location ?location .
            ?location ex:city ?city .
            FILTER (?city != "Unknown")
        }
    }
    """
    
    logger.info("Nested Optional and Union Query:")
    logger.info("=" * 50)
    lines = nested_query.strip().split('\n')
    for i, line in enumerate(lines, 1):
        logger.info(f"{i:2d}: {line}")
    logger.info("=" * 50)
    
    parsed_query = sparql_analyzer.log_parse_tree(nested_query, "query")
    
    return parsed_query

def test_filter_expressions(logger):
    """Test query with various filter expressions."""
    logger.info("\n=== Query with Various Filter Expressions ===")
    
    sparql_analyzer = VitalSparql("filter-expressions-test")
    
    filter_query = """
    PREFIX foaf: <http://xmlns.com/foaf/0.1/>
    PREFIX ex: <http://example.org/>
    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
    
    SELECT ?person ?name ?age ?score WHERE {
        ?person a foaf:Person ;
                foaf:name ?name .
        
        OPTIONAL { ?person foaf:age ?age }
        OPTIONAL { ?person ex:score ?score }
        
        # Multiple filter conditions
        FILTER (
            (BOUND(?age) && ?age >= 18 && ?age <= 65) ||
            (!BOUND(?age) && REGEX(?name, "^[A-Z]"))
        )
        
        # Numeric and string filters
        FILTER (
            IF(BOUND(?score), 
               ?score > 75.0, 
               STRLEN(?name) > 3)
        )
        
        # Existence filters
        FILTER EXISTS {
            ?person foaf:knows ?someone .
            ?someone a foaf:Person .
        }
        
        FILTER NOT EXISTS {
            ?person ex:status "inactive" .
        }
    }
    """
    
    logger.info("Filter Expressions Query:")
    logger.info("=" * 45)
    lines = filter_query.strip().split('\n')
    for i, line in enumerate(lines, 1):
        logger.info(f"{i:2d}: {line}")
    logger.info("=" * 45)
    
    parsed_query = sparql_analyzer.log_parse_tree(filter_query, "query")
    
    return parsed_query

def main():
    """Main test function."""
    logger = setup_logging()
    
    logger.info("="*80)
    logger.info("FOCUSED COMPLEX SPARQL ALGEBRA TREE LOGGING TEST")
    logger.info("="*80)
    
    results = []
    
    try:
        # Test 1: Complex SELECT with joins and filters
        result1 = test_complex_select_with_joins_and_filters(logger)
        results.append(("Complex SELECT with joins/filters", result1))
        
        # Test 2: Nested optional and union patterns
        result2 = test_nested_optional_and_union(logger)
        results.append(("Nested optional and union", result2))
        
        # Test 3: Various filter expressions
        result3 = test_filter_expressions(logger)
        results.append(("Filter expressions", result3))
        
        # Summary
        logger.info("\n" + "="*80)
        logger.info("TEST SUMMARY")
        logger.info("="*80)
        
        success_count = 0
        for test_name, result in results:
            status = "✓" if result else "✗"
            logger.info(f"{status} {test_name}: {'PASSED' if result else 'FAILED'}")
            if result:
                success_count += 1
        
        logger.info(f"\nOverall: {success_count}/{len(results)} tests passed")
        
        if success_count > 0:
            logger.info("\n🎉 Enhanced SPARQL algebra tree logging demonstrated!")
            logger.info("Key features showcased:")
            logger.info("  • Hierarchical tree structure with proper indentation")
            logger.info("  • CompValue object identification and field logging")
            logger.info("  • Nested pattern recognition (Optional, Union, Filter)")
            logger.info("  • Join pattern analysis")
            logger.info("  • Filter expression tree walking")
            logger.info("  • SPARQL operation statistics")
            logger.info("  • Comprehensive error handling")
        
        return 0 if success_count == len(results) else 1
        
    except Exception as e:
        logger.error(f"Test suite failed with error: {e}")
        logger.error("Traceback:", exc_info=True)
        return 1

if __name__ == "__main__":
    exit(main())
