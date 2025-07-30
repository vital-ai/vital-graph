#!/usr/bin/env python3
"""
Test script for demonstrating SPARQL algebra tree logging with a complex SELECT query
that RDFLib can actually parse successfully.
"""

import logging
import sys
import os

# Add the parent directory to the path so we can import vitalgraph
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from vitalgraph.store.sparql import VitalSparql

def setup_logging():
    """Set up logging configuration."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )
    return logging.getLogger(__name__)

def test_parseable_complex_select(logger):
    """Test a complex but parseable SELECT query."""
    logger.info("=== Testing Parseable Complex SELECT Query ===")
    
    sparql_analyzer = VitalSparql("parseable-complex-test")
    
    # A complex query that RDFLib can parse - avoiding problematic features
    complex_select = """
    PREFIX foaf: <http://xmlns.com/foaf/0.1/>
    PREFIX ex: <http://example.org/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
    
    SELECT DISTINCT ?person ?name ?email ?friend ?project WHERE {
        # Main person pattern
        ?person a foaf:Person ;
                foaf:name ?name .
        
        # Age filter
        ?person foaf:age ?age .
        FILTER (?age >= 18)
        
        # Optional email with regex
        OPTIONAL {
            ?person foaf:mbox ?email .
            FILTER (REGEX(STR(?email), "@example\\.com$"))
        }
        
        # Friend relationship
        ?person foaf:knows ?friend .
        ?friend a foaf:Person .
        
        # Optional project involvement
        OPTIONAL {
            ?person ex:worksOn ?project .
            ?project a ex:Project ;
                     rdfs:label ?projectLabel .
            FILTER (STRLEN(?projectLabel) > 5)
        }
        
        # Name exclusion filter
        FILTER (!REGEX(?name, "^Test"))
        
        # Union for contact type
        {
            ?person foaf:phone ?contact .
        } UNION {
            ?person foaf:homepage ?contact .
        }
    }
    ORDER BY ?name
    LIMIT 20
    """
    
    logger.info("Complex SELECT Query:")
    logger.info("=" * 60)
    lines = complex_select.strip().split('\n')
    for i, line in enumerate(lines, 1):
        logger.info(f"{i:3d}: {line}")
    logger.info("=" * 60)
    
    # Parse and log the algebra tree
    logger.info("\n" + "="*60)
    logger.info("PARSING COMPLEX SELECT QUERY")
    logger.info("="*60)
    
    parsed_query = sparql_analyzer.log_parse_tree(complex_select, "query")
    
    if parsed_query:
        logger.info("✓ Complex SELECT query parsed successfully!")
        logger.info(f"Parsed query type: {type(parsed_query)}")
        return True
    else:
        logger.error("✗ Failed to parse complex SELECT query")
        return False

def test_simple_join_select(logger):
    """Test a simpler SELECT with joins that should definitely parse."""
    logger.info("\n=== Testing Simple Join SELECT Query ===")
    
    sparql_analyzer = VitalSparql("simple-join-test")
    
    simple_join = """
    PREFIX foaf: <http://xmlns.com/foaf/0.1/>
    
    SELECT ?person ?name ?friend ?friendName WHERE {
        ?person a foaf:Person ;
                foaf:name ?name ;
                foaf:knows ?friend .
        
        ?friend a foaf:Person ;
                foaf:name ?friendName .
        
        FILTER (?name != ?friendName)
        
        OPTIONAL {
            ?person foaf:age ?age .
            FILTER (?age > 21)
        }
    }
    ORDER BY ?name ?friendName
    LIMIT 10
    """
    
    logger.info("Simple Join Query:")
    logger.info("-" * 40)
    lines = simple_join.strip().split('\n')
    for i, line in enumerate(lines, 1):
        logger.info(f"{i:2d}: {line}")
    logger.info("-" * 40)
    
    parsed_query = sparql_analyzer.log_parse_tree(simple_join, "query")
    
    if parsed_query:
        logger.info("✓ Simple join query parsed successfully!")
        return True
    else:
        logger.error("✗ Failed to parse simple join query")
        return False

def main():
    """Main test function."""
    logger = setup_logging()
    
    logger.info("🚀 TESTING PARSEABLE COMPLEX SELECT QUERIES")
    logger.info("=" * 80)
    
    results = []
    
    # Test the complex but parseable SELECT
    results.append(test_parseable_complex_select(logger))
    
    # Test a simpler join SELECT
    results.append(test_simple_join_select(logger))
    
    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("TEST SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Complex SELECT query parsed: {'✓' if results[0] else '✗'}")
    logger.info(f"Simple JOIN query parsed: {'✓' if results[1] else '✗'}")
    logger.info(f"Success rate: {sum(results)}/{len(results)} queries")
    
    if all(results):
        logger.info("🎉 All queries parsed successfully - algebra trees logged!")
    else:
        logger.warning("⚠️  Some queries failed to parse")

if __name__ == "__main__":
    main()
