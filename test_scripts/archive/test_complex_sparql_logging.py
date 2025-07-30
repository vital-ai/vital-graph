#!/usr/bin/env python3
"""
Test script for complex SPARQL algebra tree logging.

This script demonstrates the enhanced SPARQL algebra tree logging with
a complex query involving joins, regex, filters, optional patterns,
aggregation, and other advanced SPARQL features.
"""

import logging
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vitalgraph.store.sparql import VitalSparql
from rdflib import URIRef, Literal, Namespace
from rdflib.namespace import RDF, RDFS, FOAF, XSD

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

def test_complex_sparql_query(logger):
    """Test complex SPARQL query with advanced features."""
    logger.info("=== Testing Complex SPARQL Query with Advanced Features ===")
    
    # Create VitalSparql analyzer
    sparql_analyzer = VitalSparql("complex-query-test")
    
    # Complex SPARQL query with multiple advanced features
    complex_query = """
    PREFIX foaf: <http://xmlns.com/foaf/0.1/>
    PREFIX ex: <http://example.org/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
    
    SELECT DISTINCT ?person ?name ?age ?friendName ?projectTitle WHERE {
        # Main person pattern with type constraint
        ?person a foaf:Person ;
                foaf:name ?name ;
                foaf:age ?age .
        
        # Filter for adults only
        FILTER (?age >= 18)
        
        # Join with friends (another person)
        ?person foaf:knows ?friend .
        ?friend a foaf:Person ;
                foaf:name ?friendName .
        
        # Optional project involvement with constraints
        OPTIONAL {
            ?person ex:worksOn ?project .
            ?project rdfs:label ?projectTitle ;
                     ex:budget ?projectBudget .
            
            # Filter for significant projects only
            FILTER (?projectBudget > 10000)
            
            # Additional constraint on project type
            ?project a ex:Project .
        }
        
        # Exclude certain names using regex
        FILTER (!REGEX(?name, "^Test", "i"))
        
        # Date-based filtering (if birth date exists)
        OPTIONAL {
            ?person foaf:birthday ?birthday .
            FILTER (?birthday > "1990-01-01"^^xsd:date)
        }
    }
    ORDER BY ?name ?friendName
    LIMIT 20
    """
    
    logger.info("Complex SPARQL Query:")
    logger.info("=" * 80)
    lines = complex_query.strip().split('\n')
    for i, line in enumerate(lines, 1):
        logger.info(f"{i:3d}: {line}")
    logger.info("=" * 80)
    
    # Parse and log the algebra tree
    logger.info("\n" + "="*80)
    logger.info("PARSING COMPLEX SPARQL QUERY")
    logger.info("="*80)
    
    try:
        parsed_query = sparql_analyzer.log_parse_tree(complex_query, "query")
        
        if parsed_query:
            logger.info("✓ Complex SPARQL query parsed successfully!")
            logger.info(f"Parsed query type: {type(parsed_query)}")
        else:
            logger.error("✗ Failed to parse complex SPARQL query - no result returned")
        
        return parsed_query
    except Exception as e:
        logger.error(f"✗ Failed to parse complex SPARQL query with error: {e}")
        logger.error(f"Error type: {type(e).__name__}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return None

def test_complex_update_query(logger):
    """Test complex SPARQL UPDATE with multiple operations."""
    logger.info("\n=== Testing Complex SPARQL UPDATE Query ===")
    
    sparql_analyzer = VitalSparql("complex-update-test")
    
    complex_update = """
    PREFIX foaf: <http://xmlns.com/foaf/0.1/>
    PREFIX ex: <http://example.org/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
    
    # Multi-operation update with conditional logic
    
    # First: Insert new project data
    INSERT DATA {
        GRAPH ex:projects {
            ex:project123 a ex:Project ;
                         rdfs:label "AI Research Initiative" ;
                         ex:budget 150000 ;
                         ex:startDate "2024-01-01"^^xsd:date ;
                         ex:status "active" .
        }
    } ;
    
    # Second: Update person records with conditional logic
    DELETE {
        GRAPH ex:people {
            ?person ex:status ?oldStatus .
            ?person ex:lastUpdated ?oldDate .
        }
    }
    INSERT {
        GRAPH ex:people {
            ?person ex:status "verified" .
            ?person ex:lastUpdated ?now .
            ?person ex:projectCount ?projectCount .
        }
    }
    WHERE {
        GRAPH ex:people {
            ?person a foaf:Person ;
                   foaf:name ?name .
            
            # Only update if person has projects
            {
                SELECT ?person (COUNT(?project) AS ?projectCount) WHERE {
                    ?person ex:worksOn ?project .
                    ?project a ex:Project .
                }
                GROUP BY ?person
                HAVING (COUNT(?project) > 0)
            }
            
            # Get current timestamp
            BIND (NOW() AS ?now)
            
            # Optional old values to delete
            OPTIONAL { ?person ex:status ?oldStatus }
            OPTIONAL { ?person ex:lastUpdated ?oldDate }
            
            # Filter for active persons only
            FILTER NOT EXISTS {
                ?person ex:status "inactive" .
            }
        }
    } ;
    
    # Third: Clean up orphaned data
    DELETE {
        GRAPH ex:projects {
            ?project ?p ?o .
        }
    }
    WHERE {
        GRAPH ex:projects {
            ?project a ex:Project ;
                    ?p ?o .
            
            # Delete projects with no team members
            FILTER NOT EXISTS {
                ?person ex:worksOn ?project .
            }
            
            # And projects older than 5 years
            ?project ex:startDate ?startDate .
            FILTER (?startDate < "2019-01-01"^^xsd:date)
        }
    }
    """
    
    logger.info("Complex SPARQL UPDATE:")
    logger.info("=" * 80)
    lines = complex_update.strip().split('\n')
    for i, line in enumerate(lines, 1):
        logger.info(f"{i:3d}: {line}")
    logger.info("=" * 80)
    
    # Parse and log the algebra tree
    logger.info("\n" + "="*80)
    logger.info("PARSING COMPLEX SPARQL UPDATE")
    logger.info("="*80)
    
    parsed_update = sparql_analyzer.log_parse_tree(complex_update, "update")
    
    if parsed_update:
        logger.info("✓ Complex SPARQL update parsed successfully!")
        logger.info(f"Parsed update type: {type(parsed_update)}")
    else:
        logger.error("✗ Failed to parse complex SPARQL update")
    
    return parsed_update

def main():
    """Main test function."""
    logger = setup_logging()
    
    logger.info("="*80)
    logger.info("COMPLEX SPARQL ALGEBRA TREE LOGGING TEST")
    logger.info("="*80)
    
    try:
        # Test complex SELECT query
        query_result = test_complex_sparql_query(logger)
        
        # Test complex UPDATE query
        update_result = test_complex_update_query(logger)
        
        # Summary
        logger.info("\n" + "="*80)
        logger.info("TEST SUMMARY")
        logger.info("="*80)
        logger.info(f"Complex SELECT query parsed: {'✓' if query_result else '✗'}")
        logger.info(f"Complex UPDATE query parsed: {'✓' if update_result else '✗'}")
        
        if query_result and update_result:
            logger.info("🎉 All complex SPARQL queries parsed successfully!")
            logger.info("The enhanced algebra tree logging provides detailed insights into:")
            logger.info("  • Query structure and operations")
            logger.info("  • Join patterns and relationships")
            logger.info("  • Filter expressions and regex patterns")
            logger.info("  • Optional patterns and unions")
            logger.info("  • Aggregation and grouping")
            logger.info("  • Subqueries and nested patterns")
            logger.info("  • Update operations and graph management")
        else:
            logger.warning("Some queries failed to parse - check RDFLib installation")
        
    except Exception as e:
        logger.error(f"Test suite failed with error: {e}")
        logger.error("Traceback:", exc_info=True)
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
