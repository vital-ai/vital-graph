#!/usr/bin/env python3
"""
Test script to verify VitalSparql integration and SPARQL parse tree logging.
"""

import logging
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vitalgraph.store.store import VitalGraphSQLStore
from rdflib import Dataset, URIRef, Literal
from rdflib.namespace import RDF, RDFS, FOAF

def setup_logging():
    """Set up logging configuration."""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

def test_sparql_query_logging(logger):
    """Test SPARQL query parse tree logging."""
    logger.info("=== Testing SPARQL Query Parse Tree Logging ===")
    
    # Create store and dataset
    store = VitalGraphSQLStore(identifier="sparql-test-store")
    dataset = Dataset(store=store)
    
    # Test SPARQL SELECT query
    select_query = """
    PREFIX foaf: <http://xmlns.com/foaf/0.1/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    
    SELECT ?person ?name ?email
    WHERE {
        ?person a foaf:Person .
        ?person foaf:name ?name .
        OPTIONAL { ?person foaf:email ?email }
        FILTER(CONTAINS(LCASE(?name), "john"))
    }
    ORDER BY ?name
    LIMIT 10
    """
    
    logger.info("Testing SELECT query parse tree logging...")
    try:
        # This will trigger VitalSparql parse tree logging
        result = dataset.query(select_query)
    except NotImplementedError:
        logger.info("✓ Query parsing completed (NotImplementedError expected)")
    except Exception as e:
        logger.error(f"✗ Unexpected error during query parsing: {e}")
    
    return True

def test_sparql_update_logging(logger):
    """Test SPARQL update parse tree logging."""
    logger.info("=== Testing SPARQL Update Parse Tree Logging ===")
    
    # Create store and dataset
    store = VitalGraphSQLStore(identifier="sparql-update-test-store")
    dataset = Dataset(store=store)
    
    # Test SPARQL UPDATE query
    update_query = """
    PREFIX foaf: <http://xmlns.com/foaf/0.1/>
    PREFIX ex: <http://example.org/>
    
    INSERT DATA {
        ex:john a foaf:Person ;
                foaf:name "John Doe" ;
                foaf:email "john@example.org" .
        
        ex:jane a foaf:Person ;
                foaf:name "Jane Smith" ;
                foaf:email "jane@example.org" .
    }
    """
    
    logger.info("Testing UPDATE query parse tree logging...")
    try:
        # This will trigger VitalSparql parse tree logging
        dataset.update(update_query)
    except NotImplementedError:
        logger.info("✓ Update parsing completed (NotImplementedError expected)")
    except Exception as e:
        logger.error(f"✗ Unexpected error during update parsing: {e}")
    
    return True

def test_triples_logging(logger):
    """Test enhanced triples method logging."""
    logger.info("=== Testing Enhanced Triples Method Logging ===")
    
    # Create store
    store = VitalGraphSQLStore(identifier="triples-test-store")
    
    # Test various triple patterns
    test_patterns = [
        # (subject, predicate, object) - description
        (None, None, None, "Full wildcard pattern"),
        (URIRef("http://example.org/john"), None, None, "Subject-only pattern"),
        (None, RDF.type, None, "Predicate-only pattern"),
        (None, None, Literal("John Doe"), "Object-only pattern"),
        (URIRef("http://example.org/john"), RDF.type, FOAF.Person, "Fully specified pattern"),
        (URIRef("http://example.org/john"), FOAF.name, None, "Subject-predicate pattern"),
    ]
    
    for subject, predicate, obj, description in test_patterns:
        logger.info(f"Testing {description}:")
        try:
            # This will trigger enhanced triples logging
            results = list(store.triples((subject, predicate, obj)))
            logger.info(f"✓ Triples query completed (returned {len(results)} results)")
        except Exception as e:
            logger.error(f"✗ Error in triples query: {e}")
    
    return True

def test_triples_choices_logging(logger):
    """Test enhanced triples_choices method logging."""
    logger.info("=== Testing Enhanced Triples Choices Method Logging ===")
    
    # Create store
    store = VitalGraphSQLStore(identifier="triples-choices-test-store")
    
    # Test various choice patterns
    test_patterns = [
        # (subject, predicate, object) - description
        ([URIRef("http://example.org/john"), URIRef("http://example.org/jane")], RDF.type, FOAF.Person, "Subject choices"),
        (URIRef("http://example.org/john"), [FOAF.name, FOAF.mbox], None, "Predicate choices"),
        (None, RDF.type, [FOAF.Person, RDFS.Class], "Object choices"),
        ([URIRef("http://example.org/john"), URIRef("http://example.org/jane")], 
         [FOAF.name, FOAF.mbox], 
         [Literal("John Doe"), Literal("Jane Smith")], "All choices"),
    ]
    
    for subject, predicate, obj, description in test_patterns:
        logger.info(f"Testing {description}:")
        try:
            # This will trigger enhanced triples_choices logging
            results = list(store.triples_choices((subject, predicate, obj)))
            logger.info(f"✓ Triples choices query completed (returned {len(results)} results)")
        except Exception as e:
            logger.error(f"✗ Error in triples_choices query: {e}")
    
    return True

def main():
    """Main test function."""
    logger = setup_logging()
    
    logger.info("==================================================")
    logger.info("VitalSparql Integration Test Suite")
    logger.info("==================================================")
    
    try:
        # Test SPARQL query logging
        test_sparql_query_logging(logger)
        
        # Test SPARQL update logging  
        test_sparql_update_logging(logger)
        
        # Test enhanced triples logging
        test_triples_logging(logger)
        
        # Test enhanced triples_choices logging
        test_triples_choices_logging(logger)
        
        logger.info("==================================================")
        logger.info("VitalSparql Integration Test Suite Completed!")
        logger.info("==================================================")
        
        return 0
        
    except Exception as e:
        logger.error(f"Test suite failed with error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 1

if __name__ == "__main__":
    sys.exit(main())
