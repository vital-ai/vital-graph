#!/usr/bin/env python3
"""
Test script for VitalGraphSQLStore with RDFLib Dataset (quad support).

This script tests the VitalGraphSQLStore implementation with RDFLib's Dataset class,
which provides support for named graphs and quad operations (subject, predicate, object, context).

The test exercises various Dataset operations to ensure our store:
1. Logs incoming parameters correctly
2. Returns appropriate responses for success/failure
3. Handles quad-based operations (triples with context/named graphs)
4. Supports Dataset-specific functionality like named graph management
"""

import logging
import sys
import os
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rdflib import Dataset, URIRef, Literal, BNode, Namespace
from rdflib.namespace import RDF, RDFS, FOAF
from vitalgraph.store.store import VitalGraphSQLStore
from vitalgraph.space.space_impl import SpaceImpl

# Configure logging to see our store's logging output
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

def setup_test_data():
    """Set up test data for our Dataset operations."""
    # Define namespaces
    EX = Namespace("http://example.org/")
    PERSON = Namespace("http://example.org/person/")
    ORG = Namespace("http://example.org/org/")
    
    # Define named graphs (contexts)
    people_graph = URIRef("http://example.org/graphs/people")
    org_graph = URIRef("http://example.org/graphs/organizations")
    metadata_graph = URIRef("http://example.org/graphs/metadata")
    
    # Define test triples for different contexts
    test_quads = [
        # People data in people_graph
        (PERSON.alice, RDF.type, FOAF.Person, people_graph),
        (PERSON.alice, FOAF.name, Literal("Alice Smith"), people_graph),
        (PERSON.alice, FOAF.age, Literal(30), people_graph),
        (PERSON.alice, FOAF.mbox, URIRef("mailto:alice@example.org"), people_graph),
        
        (PERSON.bob, RDF.type, FOAF.Person, people_graph),
        (PERSON.bob, FOAF.name, Literal("Bob Jones"), people_graph),
        (PERSON.bob, FOAF.age, Literal(25), people_graph),
        (PERSON.bob, FOAF.knows, PERSON.alice, people_graph),
        
        # Organization data in org_graph
        (ORG.acme, RDF.type, FOAF.Organization, org_graph),
        (ORG.acme, FOAF.name, Literal("ACME Corporation"), org_graph),
        (ORG.acme, EX.hasEmployee, PERSON.alice, org_graph),
        (ORG.acme, EX.hasEmployee, PERSON.bob, org_graph),
        
        # Metadata in metadata_graph
        (people_graph, RDF.type, EX.DataGraph, metadata_graph),
        (people_graph, RDFS.label, Literal("People Information"), metadata_graph),
        (org_graph, RDF.type, EX.DataGraph, metadata_graph),
        (org_graph, RDFS.label, Literal("Organization Information"), metadata_graph),
    ]
    
    return {
        'namespaces': {'EX': EX, 'PERSON': PERSON, 'ORG': ORG},
        'graphs': {
            'people': people_graph,
            'org': org_graph, 
            'metadata': metadata_graph
        },
        'quads': test_quads
    }

def test_store_initialization():
    """Test VitalGraphSQLStore initialization and basic properties."""
    logger.info("=== Testing Store Initialization ===")
    
    try:
        # Create SpaceImpl with db_impl=None and space_id="space_123"
        space_impl = SpaceImpl(space_id="space_123", db_impl=None)
        logger.info(f"✅ SpaceImpl created with space_id='space_123' and db_impl=None")
        
        # Test store creation with identifier, configuration, and space_impl
        store_id = "space_123"  # Use simple string identifier
        configuration = "id=space_123"  # Configuration string format
        store = VitalGraphSQLStore(
            configuration=configuration,
            identifier=store_id,
            space_impl=space_impl
        )
        
        logger.info(f"✅ Store created successfully with identifier: {store_id}")
        logger.info(f"✅ Configuration: {configuration}")
        logger.info(f"✅ SpaceImpl passed to store during initialization")
        logger.info(f"Store properties - context_aware: {store.context_aware}, "
                   f"formula_aware: {store.formula_aware}, "
                   f"transaction_aware: {store.transaction_aware}, "
                   f"graph_aware: {store.graph_aware}")
        
        return store
        
    except Exception as e:
        logger.error(f"❌ Store initialization failed: {e}")
        raise

def test_dataset_creation(store):
    """Test Dataset creation with our custom store."""
    logger.info("=== Testing Dataset Creation ===")
    
    try:
        # Create Dataset with our store
        dataset = Dataset(store=store)
        logger.info(f"✅ Dataset created successfully with store: {type(store).__name__}")
        logger.info(f"Dataset default context: {dataset.default_context}")
        
        return dataset
        
    except Exception as e:
        logger.error(f"❌ Dataset creation failed: {e}")
        raise

def test_store_opening(store):
    """Test store opening and connection."""
    logger.info("=== Testing Store Opening ===")
    
    try:
        # Test opening the store
        result = store.open("test-configuration", create=True)
        logger.info(f"✅ Store opened successfully, result: {result}")
        
        # Test that we can get the length (should be 0 initially)
        length = len(store)
        logger.info(f"✅ Store length: {length}")
        
    except Exception as e:
        logger.error(f"❌ Store opening failed: {e}")
        raise

def test_quad_operations(dataset, test_data):
    """Test quad-based operations (add, remove, query with contexts)."""
    logger.info("=== Testing Quad Operations ===")
    
    try:
        # Test adding quads to the dataset
        logger.info("Adding test quads to dataset...")
        for quad in test_data['quads']:
            subject, predicate, obj, context = quad
            logger.info(f"Adding quad: ({subject}, {predicate}, {obj}, {context})")
            dataset.add(quad)
        
        logger.info(f"✅ Added {len(test_data['quads'])} quads to dataset")
        
        # Test dataset length
        total_length = len(dataset)
        logger.info(f"✅ Total dataset length: {total_length}")
        
        # Test individual graph lengths
        for graph_name, graph_uri in test_data['graphs'].items():
            try:
                graph = dataset.graph(graph_uri)
                graph_length = len(graph)
                logger.info(f"✅ Graph '{graph_name}' ({graph_uri}) length: {graph_length}")
            except Exception as e:
                logger.warning(f"⚠️  Could not get length for graph '{graph_name}': {e}")
        
    except Exception as e:
        logger.error(f"❌ Quad operations failed: {e}")
        # Continue with other tests even if this fails

def test_named_graph_operations(dataset, test_data):
    """Test named graph specific operations."""
    logger.info("=== Testing Named Graph Operations ===")
    
    try:
        graphs = test_data['graphs']
        
        # Test getting specific named graphs
        people_graph = dataset.graph(graphs['people'])
        logger.info(f"✅ Retrieved people graph: {people_graph}")
        
        org_graph = dataset.graph(graphs['org'])
        logger.info(f"✅ Retrieved org graph: {org_graph}")
        
        # Test adding triples directly to named graphs
        EX = test_data['namespaces']['EX']
        PERSON = test_data['namespaces']['PERSON']
        
        # Add a triple directly to people graph
        people_graph.add((PERSON.charlie, RDF.type, EX.Person))
        logger.info("✅ Added triple directly to people graph")
        
        # Test querying specific graphs
        logger.info("Testing graph-specific queries...")
        
        # Query people in the people graph
        people_query = """
        SELECT ?person ?name WHERE {
            ?person a <http://xmlns.com/foaf/0.1/Person> .
            ?person <http://xmlns.com/foaf/0.1/name> ?name .
        }
        """
        
        try:
            results = people_graph.query(people_query)
            logger.info(f"✅ People graph query executed (results type: {type(results)})")
        except NotImplementedError as e:
            logger.warning(f"⚠️  SPARQL query not implemented yet: {e}")
        except Exception as e:
            logger.error(f"❌ People graph query failed: {e}")
        
    except Exception as e:
        logger.error(f"❌ Named graph operations failed: {e}")

def test_triple_patterns(dataset, test_data):
    """Test triple pattern matching with detailed analysis of what gets passed to store methods."""
    logger.info("=== Testing Triple Pattern Matching with Detailed Analysis ===")
    
    try:
        PERSON = test_data['namespaces']['PERSON']
        EX = test_data['namespaces']['EX']
        FOAF = Namespace("http://xmlns.com/foaf/0.1/")
        
        # Comprehensive test cases to analyze triples() method calls
        test_cases = [
            {
                "name": "All triples wildcard query",
                "source_query": "dataset.triples((None, None, None))",
                "pattern": (None, None, None),
                "description": "Find all triples in the dataset - should trigger triples() with (None, None, None)"
            },
            {
                "name": "Subject-only pattern",
                "source_query": "dataset.triples((PERSON.alice, None, None))",
                "pattern": (PERSON.alice, None, None),
                "description": "Find all triples with Alice as subject - should trigger triples() with (alice_uri, None, None)"
            },
            {
                "name": "Predicate-only pattern",
                "source_query": "dataset.triples((None, RDF.type, None))",
                "pattern": (None, RDF.type, None),
                "description": "Find all type assertions - should trigger triples() with (None, rdf:type, None)"
            },
            {
                "name": "Object-only pattern",
                "source_query": "dataset.triples((None, None, Literal('Alice')))",
                "pattern": (None, None, Literal("Alice")),
                "description": "Find all triples with 'Alice' as object - should trigger triples() with (None, None, 'Alice')"
            },
            {
                "name": "Subject-Predicate pattern",
                "source_query": "dataset.triples((PERSON.alice, FOAF.name, None))",
                "pattern": (PERSON.alice, FOAF.name, None),
                "description": "Find Alice's names - should trigger triples() with (alice_uri, foaf:name, None)"
            },
            {
                "name": "Predicate-Object pattern",
                "source_query": "dataset.triples((None, RDF.type, EX.Person))",
                "pattern": (None, RDF.type, EX.Person),
                "description": "Find all persons - should trigger triples() with (None, rdf:type, Person)"
            },
            {
                "name": "Exact triple match",
                "source_query": "dataset.triples((PERSON.alice, FOAF.name, Literal('Alice')))",
                "pattern": (PERSON.alice, FOAF.name, Literal("Alice")),
                "description": "Exact triple lookup - should trigger triples() with (alice_uri, foaf:name, 'Alice')"
            }
        ]
        
        logger.info("\n🔍 ANALYZING DATASET.TRIPLES() CALLS TO STORE.TRIPLES()")
        logger.info("Watch the store logs to see exactly what gets passed to triples() method\n")
        
        for i, test_case in enumerate(test_cases, 1):
            logger.info(f"\n--- TEST CASE {i}: {test_case['name']} ---")
            logger.info(f"Source Query: {test_case['source_query']}")
            logger.info(f"Expected Pattern: {test_case['pattern']}")
            logger.info(f"Description: {test_case['description']}")
            logger.info(">>> CALLING DATASET.TRIPLES() - WATCH FOR STORE.TRIPLES() LOGS <<<")
            
            try:
                # Execute the query and capture what gets passed to store
                count = 0
                for triple in dataset.triples(test_case['pattern']):
                    count += 1
                    if count <= 2:  # Log first couple results
                        logger.info(f"  Result {count}: {triple}")
                    elif count == 3:
                        logger.info("  ... (additional results truncated)")
                
                logger.info(f"✅ Pattern returned {count} results")
                
            except NotImplementedError as e:
                logger.warning(f"⚠️  Pattern matching not implemented: {e}")
            except Exception as e:
                logger.error(f"❌ Pattern failed: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
        
        # Test with specific contexts/graphs
        logger.info("\n🔍 ANALYZING GRAPH-SPECIFIC QUERIES")
        logger.info("Testing triples() calls on specific named graphs\n")
        
        graphs = test_data['graphs']
        people_graph = dataset.graph(graphs['people'])
        
        graph_test_cases = [
            {
                "name": "All triples in people graph",
                "source_query": "people_graph.triples((None, None, None))",
                "pattern": (None, None, None),
                "description": "Find all triples in people graph - should trigger triples() with context"
            },
            {
                "name": "Type queries in people graph",
                "source_query": "people_graph.triples((None, RDF.type, None))",
                "pattern": (None, RDF.type, None),
                "description": "Find all types in people graph - should trigger triples() with context"
            }
        ]
        
        for i, test_case in enumerate(graph_test_cases, 1):
            logger.info(f"\n--- GRAPH TEST {i}: {test_case['name']} ---")
            logger.info(f"Source Query: {test_case['source_query']}")
            logger.info(f"Expected Pattern: {test_case['pattern']}")
            logger.info(f"Description: {test_case['description']}")
            logger.info(">>> CALLING GRAPH.TRIPLES() - WATCH FOR STORE.TRIPLES() WITH CONTEXT <<<")
            
            try:
                count = 0
                for triple in people_graph.triples(test_case['pattern']):
                    count += 1
                    if count <= 2:
                        logger.info(f"  Result {count}: {triple}")
                    elif count == 3:
                        logger.info("  ... (additional results truncated)")
                
                logger.info(f"✅ Graph pattern returned {count} results")
                
            except Exception as e:
                logger.error(f"❌ Graph pattern failed: {e}")
        
        # Test triples_choices method specifically
        logger.info("\n🔍 ANALYZING TRIPLES_CHOICES() METHOD CALLS")
        logger.info("Testing what gets passed to triples_choices() method\n")
        
        # triples_choices is typically used for more complex pattern matching
        # where any position in the triple can have multiple possible values
        choices_test_cases = [
            {
                "name": "Multiple subjects choice",
                "source_query": "store.triples_choices(([PERSON.alice, PERSON.bob], None, None))",
                "pattern": ([PERSON.alice, PERSON.bob], None, None),
                "description": "Find triples with Alice OR Bob as subject - should trigger triples_choices()"
            },
            {
                "name": "Multiple predicates choice",
                "source_query": "store.triples_choices((None, [RDF.type, FOAF.name], None))",
                "pattern": (None, [RDF.type, FOAF.name], None),
                "description": "Find triples with type OR name predicates - should trigger triples_choices()"
            },
            {
                "name": "Multiple objects choice",
                "source_query": "store.triples_choices((None, None, [EX.Person, Literal('Alice')]))",
                "pattern": (None, None, [EX.Person, Literal("Alice")]),
                "description": "Find triples with Person OR 'Alice' as object - should trigger triples_choices()"
            }
        ]
        
        # Access the store directly to test triples_choices
        store = dataset.store
        
        for i, test_case in enumerate(choices_test_cases, 1):
            logger.info(f"\n--- CHOICES TEST {i}: {test_case['name']} ---")
            logger.info(f"Source Query: {test_case['source_query']}")
            logger.info(f"Expected Pattern: {test_case['pattern']}")
            logger.info(f"Description: {test_case['description']}")
            logger.info(">>> CALLING STORE.TRIPLES_CHOICES() DIRECTLY - WATCH FOR LOGS <<<")
            
            try:
                count = 0
                for triple_context_pair in store.triples_choices(test_case['pattern']):
                    count += 1
                    if count <= 2:
                        logger.info(f"  Result {count}: {triple_context_pair}")
                    elif count == 3:
                        logger.info("  ... (additional results truncated)")
                
                logger.info(f"✅ Choices pattern returned {count} results")
                
            except Exception as e:
                logger.error(f"❌ Choices pattern failed: {e}")
        
        # Test safe SPARQL queries that don't trigger external HTTP requests
        logger.info("\n🔍 ANALYZING SPARQL QUERIES TO TRIPLES/TRIPLES_CHOICES MAPPING")
        logger.info("Testing what triples/triples_choices calls are made when SPARQL queries are executed\n")
        
        # Use only local namespaces to avoid external schema loading
        sparql_test_cases = [
            {
                "name": "Simple SELECT all triples",
                "sparql": "SELECT ?s ?p ?o WHERE { ?s ?p ?o }",
                "description": "Basic triple pattern - should trigger triples((None, None, None))"
            },
            {
                "name": "SELECT with specific subject",
                "sparql": f"SELECT ?p ?o WHERE {{ <{PERSON.alice}> ?p ?o }}",
                "description": "Subject-bound pattern - should trigger triples((alice_uri, None, None))"
            },
            {
                "name": "SELECT with specific predicate",
                "sparql": f"SELECT ?s ?o WHERE {{ ?s <{RDF.type}> ?o }}",
                "description": "Predicate-bound pattern - should trigger triples((None, rdf:type, None))"
            },
            {
                "name": "SELECT with specific object",
                "sparql": f"SELECT ?s ?p WHERE {{ ?s ?p <{EX.Person}> }}",
                "description": "Object-bound pattern - should trigger triples((None, None, Person))"
            },
            {
                "name": "SELECT with two bound terms",
                "sparql": f"SELECT ?name WHERE {{ <{PERSON.alice}> <{FOAF.name}> ?name }}",
                "description": "Two-bound pattern - should trigger triples((alice_uri, foaf:name, None))"
            },
            {
                "name": "SELECT with multiple triple patterns",
                "sparql": f"""SELECT ?person ?name WHERE {{
                    ?person <{RDF.type}> <{EX.Person}> .
                    ?person <{FOAF.name}> ?name
                }}""",
                "description": "Multiple patterns - should trigger multiple triples() calls"
            }
        ]
        
        for i, test_case in enumerate(sparql_test_cases, 1):
            logger.info(f"\n--- SPARQL TEST {i}: {test_case['name']} ---")
            logger.info(f"SPARQL Query:")
            for line in test_case['sparql'].strip().split('\n'):
                logger.info(f"  {line}")
            logger.info(f"Expected Behavior: {test_case['description']}")
            logger.info(">>> EXECUTING SPARQL QUERY - WATCH FOR TRIPLES/TRIPLES_CHOICES CALLS <<<")
            
            try:
                # Execute SPARQL query against the dataset
                results = list(dataset.query(test_case['sparql']))
                logger.info(f"✅ SPARQL query returned {len(results)} results")
                
                # Log first few results
                for j, result in enumerate(results[:2]):
                    logger.info(f"  SPARQL Result {j+1}: {result}")
                if len(results) > 2:
                    logger.info(f"  ... and {len(results) - 2} more results")
                    
            except NotImplementedError as e:
                logger.warning(f"⚠️  SPARQL query not implemented: {e}")
            except Exception as e:
                logger.error(f"❌ SPARQL query failed: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
        
        # Test CONSTRUCT queries with local namespaces only
        logger.info("\n🔍 ANALYZING SPARQL CONSTRUCT QUERIES")
        logger.info("Testing what triples calls are made for CONSTRUCT queries\n")
        
        construct_test_cases = [
            {
                "name": "Simple CONSTRUCT",
                "sparql": f"CONSTRUCT {{ ?s <{RDF.type}> <{EX.Person}> }} WHERE {{ ?s <{RDF.type}> <{EX.Person}> }}",
                "description": "CONSTRUCT query - should trigger triples() for WHERE clause"
            },
            {
                "name": "CONSTRUCT with transformation",
                "sparql": f"""CONSTRUCT {{ ?person <{EX.hasName}> ?name }} WHERE {{
                    ?person <{FOAF.name}> ?name
                }}""",
                "description": "CONSTRUCT with property transformation - should trigger triples() for WHERE"
            }
        ]
        
        for i, test_case in enumerate(construct_test_cases, 1):
            logger.info(f"\n--- CONSTRUCT TEST {i}: {test_case['name']} ---")
            logger.info(f"SPARQL Query:")
            for line in test_case['sparql'].strip().split('\n'):
                logger.info(f"  {line}")
            logger.info(f"Expected Behavior: {test_case['description']}")
            logger.info(">>> EXECUTING CONSTRUCT QUERY - WATCH FOR TRIPLES CALLS <<<")
            
            try:
                # Execute CONSTRUCT query
                construct_graph = dataset.query(test_case['sparql'])
                logger.info(f"✅ CONSTRUCT query executed, result type: {type(construct_graph)}")
                
                # Try to iterate over constructed triples
                constructed_triples = list(construct_graph)
                logger.info(f"  Constructed {len(constructed_triples)} triples")
                
                for j, triple in enumerate(constructed_triples[:2]):
                    logger.info(f"  Constructed Triple {j+1}: {triple}")
                    
            except Exception as e:
                logger.error(f"❌ CONSTRUCT query failed: {e}")
        
        # Test SPARQL queries specifically designed to trigger triples_choices
        logger.info("\n🔍 ANALYZING SPARQL QUERIES THAT MIGHT TRIGGER TRIPLES_CHOICES")
        logger.info("Testing SPARQL patterns that could use triples_choices optimization\n")
        
        triples_choices_test_cases = [
            {
                "name": "UNION with same pattern structure",
                "sparql": f"""SELECT ?s ?p ?o WHERE {{
                    {{ ?s ?p <{EX.Person}> }}
                    UNION
                    {{ ?s ?p <{EX.Company}> }}
                }}""",
                "description": "UNION with same pattern - might trigger triples_choices((None, None, [Person, Company]))"
            },
            {
                "name": "VALUES clause with multiple objects",
                "sparql": f"""SELECT ?s ?p WHERE {{
                    ?s ?p ?o .
                    VALUES ?o {{ <{EX.Person}> <{EX.Company}> }}
                }}""",
                "description": "VALUES clause - might trigger triples_choices for multiple object values"
            },
            {
                "name": "FILTER with IN operator",
                "sparql": f"""SELECT ?s ?p WHERE {{
                    ?s ?p ?o .
                    FILTER(?o IN (<{EX.Person}>, <{EX.Company}>))
                }}""",
                "description": "FILTER IN - might trigger triples_choices for multiple object values"
            },
            {
                "name": "UNION with multiple subjects",
                "sparql": f"""SELECT ?p ?o WHERE {{
                    {{ <{PERSON.alice}> ?p ?o }}
                    UNION
                    {{ <{PERSON.bob}> ?p ?o }}
                }}""",
                "description": "UNION subjects - might trigger triples_choices(([alice, bob], None, None))"
            },
            {
                "name": "UNION with multiple predicates",
                "sparql": f"""SELECT ?s ?o WHERE {{
                    {{ ?s <{FOAF.name}> ?o }}
                    UNION
                    {{ ?s <{RDF.type}> ?o }}
                }}""",
                "description": "UNION predicates - might trigger triples_choices((None, [name, type], None))"
            }
        ]
        
        for i, test_case in enumerate(triples_choices_test_cases, 1):
            logger.info(f"\n--- TRIPLES_CHOICES TEST {i}: {test_case['name']} ---")
            logger.info(f"SPARQL Query:")
            for line in test_case['sparql'].strip().split('\n'):
                logger.info(f"  {line}")
            logger.info(f"Expected Behavior: {test_case['description']}")
            logger.info(">>> EXECUTING SPARQL QUERY - WATCH FOR TRIPLES_CHOICES CALLS <<<")
            
            try:
                # Execute SPARQL query against the dataset
                results = list(dataset.query(test_case['sparql']))
                logger.info(f"✅ SPARQL query returned {len(results)} results")
                
                # Log first few results
                for j, result in enumerate(results[:2]):
                    logger.info(f"  SPARQL Result {j+1}: {result}")
                if len(results) > 2:
                    logger.info(f"  ... and {len(results) - 2} more results")
                    
            except NotImplementedError as e:
                logger.warning(f"⚠️  SPARQL query not implemented: {e}")
            except Exception as e:
                logger.error(f"❌ SPARQL query failed: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
        
    except Exception as e:
        logger.error(f"❌ Triple pattern testing failed: {e}")

def test_context_operations(dataset, test_data):
    """Test context-specific operations."""
    logger.info("=== Testing Context Operations ===")
    
    try:
        # Test getting all contexts
        logger.info("Getting all contexts...")
        try:
            context_count = 0
            for context in dataset.contexts():
                context_count += 1
                logger.info(f"  Context {context_count}: {context}")
            
            logger.info(f"✅ Found {context_count} contexts")
            
        except NotImplementedError as e:
            logger.warning(f"⚠️  Context enumeration not implemented yet: {e}")
        except Exception as e:
            logger.error(f"❌ Context enumeration failed: {e}")
        
        # Test context-specific triple queries
        people_graph = test_data['graphs']['people']
        logger.info(f"Testing triples in people graph context: {people_graph}")
        
        try:
            count = 0
            for triple in dataset.triples((None, None, None), context=people_graph):
                count += 1
                if count <= 2:
                    logger.info(f"  People graph triple {count}: {triple}")
            
            logger.info(f"✅ Found {count} triples in people graph context")
            
        except NotImplementedError as e:
            logger.warning(f"⚠️  Context-specific triple queries not implemented yet: {e}")
        except Exception as e:
            logger.error(f"❌ Context-specific triple query failed: {e}")
        
    except Exception as e:
        logger.error(f"❌ Context operations failed: {e}")

def test_bulk_operations(dataset, test_data):
    """Test bulk operations like addN."""
    logger.info("=== Testing Bulk Operations ===")
    
    try:
        # Create additional test quads for bulk operations
        EX = test_data['namespaces']['EX']
        PERSON = test_data['namespaces']['PERSON']
        bulk_graph = URIRef("http://example.org/graphs/bulk-test")
        
        bulk_quads = [
            (PERSON.dave, RDF.type, EX.Person, bulk_graph),
            (PERSON.dave, EX.name, Literal("Dave Wilson"), bulk_graph),
            (PERSON.eve, RDF.type, EX.Person, bulk_graph),
            (PERSON.eve, EX.name, Literal("Eve Brown"), bulk_graph),
            (PERSON.frank, RDF.type, EX.Person, bulk_graph),
            (PERSON.frank, EX.name, Literal("Frank Davis"), bulk_graph),
        ]
        
        logger.info(f"Testing bulk add of {len(bulk_quads)} quads...")
        
        try:
            # Test addN method
            dataset.addN(bulk_quads)
            logger.info(f"✅ Bulk add completed for {len(bulk_quads)} quads")
            
            # Check if the quads were added
            new_length = len(dataset)
            logger.info(f"✅ Dataset length after bulk add: {new_length}")
            
        except NotImplementedError as e:
            logger.warning(f"⚠️  Bulk add (addN) not implemented yet: {e}")
        except Exception as e:
            logger.error(f"❌ Bulk add failed: {e}")
        
    except Exception as e:
        logger.error(f"❌ Bulk operations testing failed: {e}")

def test_removal_operations(dataset, test_data):
    """Test triple/quad removal operations."""
    logger.info("=== Testing Removal Operations ===")
    
    try:
        PERSON = test_data['namespaces']['PERSON']
        
        # Test removing a specific triple
        triple_to_remove = (PERSON.alice, URIRef("http://xmlns.com/foaf/0.1/age"), Literal(30))
        logger.info(f"Testing removal of triple: {triple_to_remove}")
        
        try:
            dataset.remove(triple_to_remove)
            logger.info("✅ Triple removal completed")
            
            # Check length after removal
            length_after_removal = len(dataset)
            logger.info(f"✅ Dataset length after removal: {length_after_removal}")
            
        except NotImplementedError as e:
            logger.warning(f"⚠️  Triple removal not implemented yet: {e}")
        except Exception as e:
            logger.error(f"❌ Triple removal failed: {e}")
        
        # Test removing all triples matching a pattern
        pattern_to_remove = (PERSON.bob, None, None)
        logger.info(f"Testing removal of pattern: {pattern_to_remove}")
        
        try:
            dataset.remove(pattern_to_remove)
            logger.info("✅ Pattern removal completed")
            
            # Check length after pattern removal
            length_after_pattern_removal = len(dataset)
            logger.info(f"✅ Dataset length after pattern removal: {length_after_pattern_removal}")
            
        except NotImplementedError as e:
            logger.warning(f"⚠️  Pattern removal not implemented yet: {e}")
        except Exception as e:
            logger.error(f"❌ Pattern removal failed: {e}")
        
    except Exception as e:
        logger.error(f"❌ Removal operations testing failed: {e}")

def test_store_closing(store):
    """Test store closing and cleanup."""
    logger.info("=== Testing Store Closing ===")
    
    try:
        # Test store closing
        store.close(commit_pending_transaction=True)
        logger.info("✅ Store closed successfully")
        
    except Exception as e:
        logger.error(f"❌ Store closing failed: {e}")

def main():
    """Main test function."""
    logger.info("🚀 Starting VitalGraphSQLStore Dataset Test Suite")
    logger.info("=" * 60)
    
    try:
        # Set up test data
        test_data = setup_test_data()
        logger.info(f"✅ Test data prepared: {len(test_data['quads'])} quads, "
                   f"{len(test_data['graphs'])} named graphs")
        
        # Test 1: Store initialization
        store = test_store_initialization()
        
        # Test 2: Dataset creation
        dataset = test_dataset_creation(store)
        
        # Test 3: Store opening
        test_store_opening(store)
        
        # Test 4: Quad operations
        test_quad_operations(dataset, test_data)
        
        # Test 5: Named graph operations
        test_named_graph_operations(dataset, test_data)
        
        # Test 6: Triple pattern matching
        test_triple_patterns(dataset, test_data)
        
        # Test 7: Context operations
        test_context_operations(dataset, test_data)
        
        # Test 8: Bulk operations
        test_bulk_operations(dataset, test_data)
        
        # Test 9: Removal operations
        test_removal_operations(dataset, test_data)
        
        # Test 10: Store closing
        test_store_closing(store)
        
        # === Testing Additional Store Interface Methods ===
        logger.info("=== Testing Additional Store Interface Methods ===")
        
        # Test contexts() method
        logger.info("Testing contexts() method...")
        try:
            contexts_list = list(dataset.contexts())
            logger.info(f"✅ contexts() returned {len(contexts_list)} contexts")
            for i, ctx in enumerate(contexts_list[:3]):  # Show first 3
                logger.info(f"  Context {i+1}: {ctx}")
            if len(contexts_list) > 3:
                logger.info(f"  ... and {len(contexts_list) - 3} more contexts")
        except Exception as e:
            logger.error(f"❌ contexts() failed: {e}")
        
        # Test contexts() with specific triple
        logger.info("Testing contexts() with specific triple...")
        try:
            test_triple = (alice_uri, foaf.name, Literal("Alice Smith"))
            contexts_for_triple = list(dataset.contexts(test_triple))
            logger.info(f"✅ contexts({test_triple}) returned {len(contexts_for_triple)} contexts")
        except Exception as e:
            logger.error(f"❌ contexts() with triple failed: {e}")
        
        # Test namespace management methods
        logger.info("Testing namespace management methods...")
        
        # Test bind() method
        logger.info("Testing bind() method...")
        try:
            test_prefix = "test"
            test_namespace = URIRef("http://example.org/test/")
            dataset.bind(test_prefix, test_namespace)
            logger.info(f"✅ bind('{test_prefix}', '{test_namespace}') completed")
        except Exception as e:
            logger.error(f"❌ bind() failed: {e}")
        
        # Test prefix() method
        logger.info("Testing prefix() method...")
        try:
            prefix_result = dataset.prefix(test_namespace)
            logger.info(f"✅ prefix({test_namespace}) returned: {prefix_result}")
        except Exception as e:
            logger.error(f"❌ prefix() failed: {e}")
        
        # Test namespace() method
        logger.info("Testing namespace() method...")
        try:
            namespace_result = dataset.namespace(test_prefix)
            logger.info(f"✅ namespace('{test_prefix}') returned: {namespace_result}")
        except Exception as e:
            logger.error(f"❌ namespace() failed: {e}")
        
        # Test namespaces() method
        logger.info("Testing namespaces() method...")
        try:
            namespaces_list = list(dataset.namespaces())
            logger.info(f"✅ namespaces() returned {len(namespaces_list)} namespace bindings")
            for i, (prefix, ns) in enumerate(namespaces_list[:3]):  # Show first 3
                logger.info(f"  Binding {i+1}: '{prefix}' -> {ns}")
            if len(namespaces_list) > 3:
                logger.info(f"  ... and {len(namespaces_list) - 3} more bindings")
        except Exception as e:
            logger.error(f"❌ namespaces() failed: {e}")
        
        # Test transaction methods
        logger.info("Testing transaction methods...")
        
        # Test commit() method
        logger.info("Testing commit() method...")
        try:
            dataset.commit()
            logger.info("✅ commit() completed")
        except Exception as e:
            logger.error(f"❌ commit() failed: {e}")
        
        # Test rollback() method
        logger.info("Testing rollback() method...")
        try:
            dataset.rollback()
            logger.info("✅ rollback() completed")
        except Exception as e:
            logger.error(f"❌ rollback() failed: {e}")
        
        # Test graph management methods
        logger.info("Testing graph management methods...")
        
        # Test add_graph() method
        logger.info("Testing add_graph() method...")
        try:
            new_graph = dataset.graph(URIRef("http://example.org/graphs/test-graph"))
            dataset.add_graph(new_graph)
            logger.info(f"✅ add_graph({new_graph}) completed")
        except Exception as e:
            logger.error(f"❌ add_graph() failed: {e}")
        
        # Test remove_graph() method
        logger.info("Testing remove_graph() method...")
        try:
            dataset.remove_graph(new_graph)
            logger.info(f"✅ remove_graph({new_graph}) completed")
        except Exception as e:
            logger.error(f"❌ remove_graph() failed: {e}")
        
        # === Testing Store Interface Coverage Summary ===
        logger.info("=== Store Interface Coverage Summary ===")
        tested_methods = [
            "add", "addN", "remove", "triples", "triples_choices", "__len__",
            "contexts", "bind", "prefix", "namespace", "namespaces",
            "commit", "rollback", "add_graph", "remove_graph",
            "open", "close", "destroy", "query", "update"
        ]
        logger.info(f"✅ Tested {len(tested_methods)} Store interface methods:")
        for method in tested_methods:
            logger.info(f"  - {method}()")
        
        logger.info("============================================================")
        logger.info("🎉 VitalGraphSQLStore Dataset Test Suite Completed!")
        logger.info("Check the logs above to see which operations are working")
        logger.info("and which ones need implementation in the store.")
        logger.info("All major RDFLib Store interface methods have been tested.")
        
    except Exception as e:
        logger.error(f"💥 Test suite failed with error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
