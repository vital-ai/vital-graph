#!/usr/bin/env python3
"""
Test script for VitalGraphSQLStore implementation.

This script creates an RDFLib Dataset using the new VitalGraphSQLStore
with identifier "vitalgraph-test-1" to test and help implement store functions.
"""

import logging
import sys
import traceback
from rdflib import Dataset, Graph, URIRef, Literal, BNode, Namespace
from rdflib.namespace import RDF, RDFS, FOAF
from vitalgraph.store.store import VitalGraphSQLStore

# Database configuration
PG_HOST = "127.0.0.1"
PG_PORT = 5432
PG_USER = "postgres"
PG_PASSWORD = ""  # empty password
PG_DATABASE = "vitalgraphdb"

# Test identifier
STORE_IDENTIFIER = "vitalgraph-test-1"

# Test namespaces
EX = Namespace("http://example.org/")
TEST = Namespace("http://vitalgraph.test/")


def setup_logging():
    """Setup logging to see what's happening in the store."""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    # Get logger for this test script
    return logging.getLogger(__name__)


def create_db_uri():
    """Create the database connection URI."""
    driver = "postgresql+psycopg"  # Use psycopg3 driver
    if PG_PASSWORD:
        return f"{driver}://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"
    else:
        return f"{driver}://{PG_USER}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"


def test_store_creation(logger):
    """Test basic store creation and initialization."""
    logger.info("=== Testing Store Creation ===")
    
    try:
        logger.info(f"Attempting to create VitalGraphSQLStore with identifier: {STORE_IDENTIFIER}")
        
        # Create store with our test identifier
        store = VitalGraphSQLStore(identifier=STORE_IDENTIFIER)
        logger.info(f"✓ Created VitalGraphSQLStore with identifier: {STORE_IDENTIFIER}")
        
        # Check store properties
        logger.info(f"✓ Store properties:")
        logger.info(f"  - context_aware: {store.context_aware}")
        logger.info(f"  - formula_aware: {store.formula_aware}")
        logger.info(f"  - transaction_aware: {store.transaction_aware}")
        logger.info(f"  - graph_aware: {store.graph_aware}")
        
        logger.debug(f"Store object type: {type(store)}")
        logger.debug(f"Store object: {store}")
        
        return store
        
    except Exception as e:
        logger.error(f"✗ Failed to create store: {e}")
        logger.error(traceback.format_exc())
        return None


def test_dataset_creation(store, logger):
    """Test Dataset creation with the VitalGraphSQLStore."""
    logger.info("=== Testing Dataset Creation ===")
    
    try:
        # Create Dataset with our store
        dataset = Dataset(store=store)
        logger.info("✓ Created Dataset with VitalGraphSQLStore")
        
        # Try to open the store
        db_uri = create_db_uri()
        logger.info(f"✓ Attempting to open store with URI: {db_uri}")
        
        result = dataset.open(db_uri, create=True)
        logger.info(f"✓ Store open result: {result}")
        
        return dataset
        
    except Exception as e:
        logger.error(f"✗ Failed to create/open dataset: {e}")
        logger.error(traceback.format_exc())
        return None


def test_basic_graph_operations(dataset, logger):
    """Test basic graph operations."""
    logger.info("=== Testing Basic Graph Operations ===")
    
    try:
        # Get default graph
        default_graph = dataset.default_context
        logger.info("✓ Got default graph from dataset")
        
        # Create a named graph
        named_graph_uri = URIRef("http://vitalgraph.test/graph1")
        named_graph = dataset.graph(named_graph_uri)
        logger.info(f"✓ Created named graph: {named_graph_uri}")
        
        # Test graph length (should call __len__)
        try:
            length = len(default_graph)
            logger.info(f"✓ Default graph length: {length}")
        except Exception as e:
            logger.warning(f"⚠ Graph length failed (expected): {e}")
        
        return default_graph, named_graph
        
    except Exception as e:
        logger.error(f"✗ Failed basic graph operations: {e}")
        logger.error(traceback.format_exc())
        return None, None


def test_triple_operations(graph, logger):
    """Test adding and querying triples."""
    logger.info("=== Testing Triple Operations ===")
    
    if graph is None:
        logger.error("✗ No graph available for testing")
        return
    
    try:
        # Create test triples
        subject = EX.person1
        predicate = RDF.type
        obj = FOAF.Person
        
        logger.info(f"✓ Attempting to add triple: {subject} {predicate} {obj}")
        
        # Test add() method
        try:
            graph.add((subject, predicate, obj))
            logger.info("✓ Triple add() called successfully")
        except Exception as e:
            logger.warning(f"⚠ Triple add failed (expected): {e}")
        
        # Test addN() method with multiple triples
        triples = [
            (EX.person1, FOAF.name, Literal("John Doe")),
            (EX.person1, FOAF.age, Literal(30)),
            (EX.person2, RDF.type, FOAF.Person),
            (EX.person2, FOAF.name, Literal("Jane Smith")),
        ]
        
        try:
            for triple in triples:
                graph.add(triple)
            logger.info(f"✓ Added {len(triples)} additional triples")
        except Exception as e:
            logger.warning(f"⚠ Bulk triple add failed (expected): {e}")
        
        # Test triples() method - pattern matching
        try:
            logger.info("✓ Testing triple pattern matching:")
            
            # Find all triples
            all_triples = list(graph.triples((None, None, None)))
            logger.info(f"  - All triples: {len(all_triples)}")
            
            # Find triples by type
            person_triples = list(graph.triples((None, RDF.type, FOAF.Person)))
            logger.info(f"  - Person type triples: {len(person_triples)}")
            
            # Find triples by subject
            person1_triples = list(graph.triples((EX.person1, None, None)))
            logger.info(f"  - Person1 triples: {len(person1_triples)}")
            
        except Exception as e:
            logger.warning(f"⚠ Triple pattern matching failed (expected): {e}")
        
    except Exception as e:
        logger.error(f"✗ Triple operations failed: {e}")
        logger.error(traceback.format_exc())


def test_namespace_operations(graph, logger):
    """Test namespace binding operations."""
    logger.info("=== Testing Namespace Operations ===")
    
    if graph is None:
        logger.error("✗ No graph available for testing")
        return
    
    try:
        # Test namespace binding
        try:
            graph.bind("ex", EX)
            graph.bind("test", TEST)
            logger.info("✓ Namespace bind() called successfully")
        except Exception as e:
            logger.warning(f"⚠ Namespace binding failed (expected): {e}")
        
        # Test namespace lookup
        try:
            ex_ns = graph.namespace("ex")
            logger.info(f"✓ Namespace lookup for 'ex': {ex_ns}")
        except Exception as e:
            logger.warning(f"⚠ Namespace lookup failed (expected): {e}")
        
        # Test prefix lookup
        try:
            ex_prefix = graph.prefix(EX)
            logger.info(f"✓ Prefix lookup for {EX}: {ex_prefix}")
        except Exception as e:
            logger.warning(f"⚠ Prefix lookup failed (expected): {e}")
        
        # Test all namespaces
        try:
            all_ns = list(graph.namespaces())
            logger.info(f"✓ All namespaces: {len(all_ns)}")
        except Exception as e:
            logger.warning(f"⚠ Namespace enumeration failed (expected): {e}")
        
    except Exception as e:
        logger.error(f"✗ Namespace operations failed: {e}")
        logger.error(traceback.format_exc())


def test_query_operations(graph, logger):
    """Test SPARQL query operations."""
    logger.info("=== Testing Query Operations ===")
    
    if graph is None:
        logger.error("✗ No graph available for testing")
        return
    
    try:
        # Test simple SPARQL query
        query = """
        SELECT ?s ?p ?o
        WHERE {
            ?s ?p ?o .
        }
        LIMIT 10
        """
        
        try:
            results = graph.query(query)
            logger.info(f"✓ SPARQL query executed, results: {len(list(results))}")
        except NotImplementedError as e:
            logger.warning(f"⚠ SPARQL query not implemented (expected): {e}")
        except Exception as e:
            logger.warning(f"⚠ SPARQL query failed: {e}")
        
        # Test SPARQL update
        update = """
        INSERT DATA {
            <http://example.org/person3> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://xmlns.com/foaf/0.1/Person> .
        }
        """
        
        try:
            graph.update(update)
            logger.info("✓ SPARQL update executed")
        except NotImplementedError as e:
            logger.warning(f"⚠ SPARQL update not implemented (expected): {e}")
        except Exception as e:
            logger.warning(f"⚠ SPARQL update failed: {e}")
        
    except Exception as e:
        logger.error(f"✗ Query operations failed: {e}")
        logger.error(traceback.format_exc())


def test_transaction_operations(dataset, logger):
    """Test transaction operations."""
    logger.info("=== Testing Transaction Operations ===")
    
    if dataset is None:
        logger.error("✗ No dataset available for testing")
        return
    
    try:
        store = dataset.store
        
        # Test commit
        try:
            store.commit()
            logger.info("✓ Transaction commit() called successfully")
        except Exception as e:
            logger.warning(f"⚠ Transaction commit failed (expected): {e}")
        
        # Test rollback
        try:
            store.rollback()
            logger.info("✓ Transaction rollback() called successfully")
        except Exception as e:
            logger.warning(f"⚠ Transaction rollback failed (expected): {e}")
        
    except Exception as e:
        logger.error(f"✗ Transaction operations failed: {e}")
        logger.error(traceback.format_exc())


def test_context_operations(dataset, logger):
    """Test context/graph operations."""
    logger.info("=== Testing Context Operations ===")
    
    if dataset is None:
        logger.error("✗ No dataset available for testing")
        return
    
    try:
        store = dataset.store
        
        # Test contexts enumeration
        try:
            contexts = list(store.contexts())
            logger.info(f"✓ Contexts enumeration: {len(contexts)} contexts")
        except Exception as e:
            logger.warning(f"⚠ Context enumeration failed (expected): {e}")
        
        # Test add_graph
        try:
            test_graph = Graph(identifier=URIRef("http://vitalgraph.test/testgraph"))
            store.add_graph(test_graph)
            logger.info("✓ add_graph() called successfully")
        except Exception as e:
            logger.warning(f"⚠ add_graph failed (expected): {e}")
        
        # Test remove_graph
        try:
            store.remove_graph(test_graph)
            logger.info("✓ remove_graph() called successfully")
        except Exception as e:
            logger.warning(f"⚠ remove_graph failed (expected): {e}")
        
    except Exception as e:
        logger.error(f"✗ Context operations failed: {e}")
        logger.error(traceback.format_exc())


def cleanup_test(dataset, logger):
    """Clean up test resources."""
    logger.info("=== Cleanup ===")
    
    try:
        if dataset:
            dataset.close()
            logger.info("✓ Dataset closed successfully")
    except Exception as e:
        logger.warning(f"⚠ Cleanup failed: {e}")


def main():
    """Main test function."""
    logger = setup_logging()
    
    logger.info("VitalGraphSQLStore Test Suite")
    logger.info("=" * 50)
    
    # Test sequence
    store = test_store_creation(logger)
    if store is None:
        logger.error("✗ Cannot continue without store")
        return 1
    
    dataset = test_dataset_creation(store, logger)
    if dataset is None:
        logger.error("✗ Cannot continue without dataset")
        return 1
    
    default_graph, named_graph = test_basic_graph_operations(dataset, logger)
    
    test_triple_operations(default_graph, logger)
    test_namespace_operations(default_graph, logger)
    test_query_operations(default_graph, logger)
    test_transaction_operations(dataset, logger)
    test_context_operations(dataset, logger)
    
    cleanup_test(dataset, logger)
    
    logger.info("=" * 50)
    logger.info("Test suite completed!")
    logger.info("Note: Many operations are expected to fail until store methods are implemented.")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
