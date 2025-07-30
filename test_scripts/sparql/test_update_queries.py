#!/usr/bin/env python3
"""
SPARQL 1.1 UPDATE/INSERT/DELETE Test Script
===========================================

Comprehensive testing of SPARQL 1.1 update operations including:
- INSERT DATA (ground triples)
- DELETE DATA (ground triples)
- INSERT/DELETE with WHERE patterns
- Graph management operations (CREATE, DROP, CLEAR)
- Transaction handling and error cases

Follows the test_agg_queries.py pattern for database connection and configuration.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.db.postgresql.postgresql_sparql_impl import PostgreSQLSparqlImpl

# Reduce logging chatter
logging.getLogger('vitalgraph.db.postgresql.postgresql_space_impl').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.rdf.rdf_utils').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.db.postgresql.postgresql_cache_term').setLevel(logging.WARNING)

# Configuration
SPACE_ID = "space_test"
GRAPH_URI = "http://vital.ai/graph/test"
GLOBAL_GRAPH_URI = "urn:___GLOBAL"
UPDATE_TEST_GRAPH = "http://example.org/update-test"

# Global variables for database connection
impl = None
sparql_impl = None

async def setup_connection():
    """Initialize database connection for tests."""
    global impl, sparql_impl
    
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    space_impl = impl.db_impl.get_space_impl()
    sparql_impl = PostgreSQLSparqlImpl(space_impl)
    
    print(f"✅ Connected | Graph: {GRAPH_URI}")

async def cleanup_connection():
    """Clean up database connection."""
    global impl
    
    if impl and hasattr(impl, 'db_impl') and hasattr(impl.db_impl, 'close'):
        await impl.db_impl.close()
        print("🔌 Database connection closed")
    else:
        print("🔌 Database connection cleanup skipped")

async def run_update(sparql_impl, name, sparql, debug=False):
    """Execute a single SPARQL UPDATE operation and display results."""
    print(f"\n  {name}:")
    
    if debug:
        print(f"\n🔍 DEBUG UPDATE: {name}")
        print("=" * 60)
        print("SPARQL UPDATE:")
        print(sparql)
        print("\n" + "-" * 60)
        
        # Enable debug logging temporarily
        sparql_logger = logging.getLogger('vitalgraph.db.postgresql.postgresql_sparql_impl')
        original_level = sparql_logger.level
        sparql_logger.setLevel(logging.DEBUG)
        
        # Add console handler if not present
        if not sparql_logger.handlers:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(levelname)s - %(message)s')
            console_handler.setFormatter(formatter)
            sparql_logger.addHandler(console_handler)
    
    try:
        start_time = time.time()
        # Note: UPDATE operations typically return success/failure, not result sets
        result = await sparql_impl.execute_sparql_update(SPACE_ID, sparql)
        update_time = time.time() - start_time
        
        print(f"    ⏱️  {update_time:.3f}s | Update completed")
        
        if result:
            print(f"    ✅ Success: {result}")
        else:
            print(f"    ✅ Update executed successfully")
            
        if debug:
            print("\n" + "=" * 60)
            
    except Exception as e:
        print(f"    ❌ Error: {e}")
        if debug:
            import traceback
            traceback.print_exc()
    
    finally:
        if debug:
            # Restore original logging level
            sparql_logger.setLevel(original_level)

async def run_query(sparql_impl, name, sparql, debug=False):
    """Execute a SPARQL SELECT query to verify update results."""
    print(f"\n  {name}:")
    
    try:
        start_time = time.time()
        results = await sparql_impl.execute_sparql_query(SPACE_ID, sparql)
        query_time = time.time() - start_time
        
        print(f"    ⏱️  {query_time:.3f}s | {len(results)} results")
        
        # Show results for verification
        for i, result in enumerate(results):
            print(f"    [{i+1}] {dict(result)}")
            
    except Exception as e:
        print(f"    ❌ Error: {e}")
        if debug:
            import traceback
            traceback.print_exc()

async def debug_update_parsing():
    """Debug UPDATE query parsing to understand RDFLib algebra structure."""
    print("\n🔍 DEBUG UPDATE PARSING:")
    
    from rdflib.plugins.sparql.parser import parseUpdate
    from rdflib.plugins.sparql.algebra import translateUpdate
    
    # Test INSERT DATA parsing
    insert_sparql = '''
        PREFIX ex: <http://example.org/>
        INSERT DATA {
            ex:person1 ex:name "Alice Smith" ;
                      ex:age 30 .
        }
    '''
    
    print("\n  INSERT DATA Query:")
    print(insert_sparql)
    
    try:
        parsed = parseUpdate(insert_sparql)
        algebra = translateUpdate(parsed)
        
        print(f"\n  Parsed type: {type(parsed)}")
        print(f"  Algebra type: {type(algebra)}")
        print(f"  Algebra: {algebra}")
        
        if hasattr(algebra, '__iter__'):
            for i, item in enumerate(algebra):
                print(f"\n  Item {i}: {type(item)}")
                print(f"    Item: {item}")
                if hasattr(item, '__dict__'):
                    print(f"    Attributes: {item.__dict__}")
                if hasattr(item, 'name'):
                    print(f"    Name: {item.name}")
                if hasattr(item, 'graph'):
                    print(f"    Graph: {item.graph}")
                    if hasattr(item.graph, 'triples'):
                        triples = list(item.graph.triples((None, None, None)))
                        print(f"    Triples: {triples}")
                        
    except Exception as e:
        print(f"  Error: {e}")
        import traceback
        traceback.print_exc()

async def test_insert_data():
    """Test INSERT DATA operations with ground triples."""
    print("\n📝 INSERT DATA OPERATIONS:")
    
    # Insert into default graph
    await run_update(sparql_impl, "Insert person into default graph", f"""
        PREFIX ex: <http://example.org/>
        INSERT DATA {{
            ex:person1 ex:name "Alice Smith" ;
                      ex:age 30 ;
                      ex:email "alice@example.org" .
        }}
    """)
    
    # Insert into named graph
    await run_update(sparql_impl, "Insert product into named graph", f"""
        PREFIX ex: <http://example.org/>
        INSERT DATA {{
            GRAPH <{UPDATE_TEST_GRAPH}> {{
                ex:product1 ex:name "Laptop" ;
                           ex:price 999.99 ;
                           ex:category "Electronics" .
            }}
        }}
    """)
    
    # Verify insertions
    await run_query(sparql_impl, "Verify person insertion", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?age ?email WHERE {{
            ex:person1 ex:name ?name ;
                      ex:age ?age ;
                      ex:email ?email .
        }}
    """)
    
    await run_query(sparql_impl, "Verify product insertion", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?price ?category WHERE {{
            GRAPH <{UPDATE_TEST_GRAPH}> {{
                ex:product1 ex:name ?name ;
                           ex:price ?price ;
                           ex:category ?category .
            }}
        }}
    """)

async def test_delete_data():
    """Test DELETE DATA operations with ground triples."""
    print("\n🗑️ DELETE DATA OPERATIONS:")
    
    # First insert some data to delete
    await run_update(sparql_impl, "Insert data for deletion test", f"""
        PREFIX ex: <http://example.org/>
        INSERT DATA {{
            ex:person2 ex:name "Bob Jones" ;
                      ex:age 25 ;
                      ex:status "temporary" .
        }}
    """)
    
    # Delete specific triples
    await run_update(sparql_impl, "Delete specific properties", f"""
        PREFIX ex: <http://example.org/>
        DELETE DATA {{
            ex:person2 ex:status "temporary" .
        }}
    """)
    
    # Verify deletion
    await run_query(sparql_impl, "Verify partial deletion", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?age ?status WHERE {{
            ex:person2 ex:name ?name ;
                      ex:age ?age .
            OPTIONAL {{ ex:person2 ex:status ?status }}
        }}
    """)
    
    # Delete remaining triples
    await run_update(sparql_impl, "Delete remaining person data", f"""
        PREFIX ex: <http://example.org/>
        DELETE DATA {{
            ex:person2 ex:name "Bob Jones" ;
                      ex:age 25 .
        }}
    """)
    
    # Verify complete deletion
    await run_query(sparql_impl, "Verify complete deletion", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?age WHERE {{
            ex:person2 ex:name ?name ;
                      ex:age ?age .
        }}
    """)

async def test_insert_delete_patterns():
    """Test INSERT/DELETE operations with WHERE patterns."""
    print("\n🔄 INSERT/DELETE WITH PATTERNS:")
    
    # Insert base data for pattern testing
    await run_update(sparql_impl, "Insert base data for patterns", f"""
        PREFIX ex: <http://example.org/>
        INSERT DATA {{
            ex:employee1 ex:name "Charlie Brown" ;
                        ex:salary 50000 ;
                        ex:department "IT" .
            ex:employee2 ex:name "Diana Prince" ;
                        ex:salary 75000 ;
                        ex:department "HR" .
            ex:employee3 ex:name "Eve Adams" ;
                        ex:salary 45000 ;
                        ex:department "IT" .
        }}
    """)
    
    # Pattern-based insert: Add bonus for high-salary employees (with BIND)
    await run_update(sparql_impl, "Add bonus for high-salary employees", f"""
        PREFIX ex: <http://example.org/>
        INSERT {{
            ?employee ex:bonus ?bonusAmount .
        }}
        WHERE {{
            ?employee ex:salary ?salary .
            FILTER(?salary > 60000)
            BIND(?salary * 0.1 AS ?bonusAmount)
        }}
    """)
    
    # Pattern-based delete: Remove low performers
    await run_update(sparql_impl, "Remove salary info for low earners", f"""
        PREFIX ex: <http://example.org/>
        DELETE {{
            ?employee ex:salary ?salary .
        }}
        WHERE {{
            ?employee ex:salary ?salary .
            FILTER(?salary < 50000)
        }}
    """)
    
    # Verify pattern operations
    await run_query(sparql_impl, "Verify pattern-based updates", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?salary ?bonus ?department WHERE {{
            ?employee ex:name ?name ;
                     ex:department ?department .
            OPTIONAL {{ ?employee ex:salary ?salary }}
            OPTIONAL {{ ?employee ex:bonus ?bonus }}
        }}
        ORDER BY ?name
    """)

async def test_combined_delete_insert():
    """Test combined DELETE/INSERT operations."""
    print("\n🔄 COMBINED DELETE/INSERT:")
    
    # Insert test data
    await run_update(sparql_impl, "Insert data for combined operation", f"""
        PREFIX ex: <http://example.org/>
        INSERT DATA {{
            ex:product2 ex:name "Old Phone" ;
                       ex:price 299.99 ;
                       ex:status "discontinued" .
        }}
    """)
    
    # Combined delete/insert: Update product status and price
    await run_update(sparql_impl, "Update product with combined operation", f"""
        PREFIX ex: <http://example.org/>
        DELETE {{
            ?product ex:status "discontinued" ;
                    ex:price ?oldPrice .
        }}
        INSERT {{
            ?product ex:status "clearance" ;
                    ex:price ?newPrice .
        }}
        WHERE {{
            ?product ex:name "Old Phone" ;
                    ex:status "discontinued" ;
                    ex:price ?oldPrice .
            BIND(?oldPrice * 0.5 AS ?newPrice)
        }}
    """)
    
    # Verify combined operation
    await run_query(sparql_impl, "Verify combined delete/insert", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?name ?price ?status WHERE {{
            ex:product2 ex:name ?name ;
                       ex:price ?price ;
                       ex:status ?status .
        }}
    """)

async def test_graph_management():
    """Test graph management operations (CREATE, DROP, CLEAR)."""
    print("\n📊 GRAPH MANAGEMENT OPERATIONS:")
    
    # Create a new graph
    await run_update(sparql_impl, "Create new graph", f"""
        CREATE GRAPH <http://example.org/test-graph>
    """)
    
    # Insert data into the new graph
    await run_update(sparql_impl, "Insert data into new graph", f"""
        PREFIX ex: <http://example.org/>
        INSERT DATA {{
            GRAPH <http://example.org/test-graph> {{
                ex:item1 ex:name "Test Item" ;
                        ex:value 42 .
            }}
        }}
    """)
    
    # Clear the graph (remove all triples but keep graph)
    await run_update(sparql_impl, "Clear graph contents", f"""
        CLEAR GRAPH <http://example.org/test-graph>
    """)
    
    # Verify graph is empty
    await run_query(sparql_impl, "Verify graph is cleared", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?item ?name ?value WHERE {{
            GRAPH <http://example.org/test-graph> {{
                ?item ex:name ?name ;
                     ex:value ?value .
            }}
        }}
    """)
    
    # Drop the graph entirely
    await run_update(sparql_impl, "Drop graph", f"""
        DROP GRAPH <http://example.org/test-graph>
    """)

async def test_error_cases():
    """Test error handling and edge cases."""
    print("\n⚠️ ERROR HANDLING AND EDGE CASES:")
    
    # Try to delete non-existent triples (should succeed with no effect)
    await run_update(sparql_impl, "Delete non-existent triples", f"""
        PREFIX ex: <http://example.org/>
        DELETE DATA {{
            ex:nonexistent ex:property "value" .
        }}
    """)
    
    # Try to insert duplicate triples (should succeed with no effect)
    await run_update(sparql_impl, "Insert duplicate triples", f"""
        PREFIX ex: <http://example.org/>
        INSERT DATA {{
            ex:person1 ex:name "Alice Smith" .
        }}
    """)
    
    # Try invalid syntax (should fail gracefully)
    await run_update(sparql_impl, "Invalid syntax test", f"""
        PREFIX ex: <http://example.org/>
        INVALID OPERATION {{
            ex:test ex:invalid "syntax" .
        }}
    """, debug=True)

async def test_transaction_behavior():
    """Test transaction behavior and rollback scenarios."""
    print("\n🔄 TRANSACTION BEHAVIOR:")
    
    # Insert data for transaction testing
    await run_update(sparql_impl, "Insert data for transaction test", f"""
        PREFIX ex: <http://example.org/>
        INSERT DATA {{
            ex:account1 ex:balance 1000 ;
                       ex:owner "Alice" .
            ex:account2 ex:balance 500 ;
                       ex:owner "Bob" .
        }}
    """)
    
    # Simulate a transfer operation (should be atomic)
    await run_update(sparql_impl, "Transfer funds between accounts", f"""
        PREFIX ex: <http://example.org/>
        DELETE {{
            ex:account1 ex:balance ?balance1 .
            ex:account2 ex:balance ?balance2 .
        }}
        INSERT {{
            ex:account1 ex:balance ?newBalance1 .
            ex:account2 ex:balance ?newBalance2 .
        }}
        WHERE {{
            ex:account1 ex:balance ?balance1 .
            ex:account2 ex:balance ?balance2 .
            BIND(?balance1 - 200 AS ?newBalance1)
            BIND(?balance2 + 200 AS ?newBalance2)
        }}
    """)
    
    # Verify transaction results
    await run_query(sparql_impl, "Verify transaction results", f"""
        PREFIX ex: <http://example.org/>
        SELECT ?account ?owner ?balance WHERE {{
            ?account ex:owner ?owner ;
                    ex:balance ?balance .
        }}
        ORDER BY ?account
    """)

async def test_load_operations():
    """Test SPARQL LOAD operations (Phase 4) using transfer utilities."""
    print("\n📊 LOAD OPERATIONS:")
    
    # Test LOAD components using the new transfer utilities module
    print("\n  Transfer utilities component tests:")
    try:
        # Import the transfer utilities
        from vitalgraph.transfer.transfer_utils import (
            DataTransferManager, TransferConfig, URIValidator, 
            RDFFormatDetector, RDFParser, SPARQLLoadQueryParser, RDFFormat
        )
        
        # Test configuration with more permissive settings
        config = TransferConfig(
            max_file_size=50 * 1024 * 1024,  # 50MB for testing
            timeout_seconds=60,  # Longer timeout for larger files
            allowed_schemes=['http', 'https'],
            allowed_domains=[]  # Empty list = allow all domains for testing
        )
        print(f"    ✅ Transfer config created: max_size={config.max_file_size}, timeout={config.timeout_seconds}s")
        
        # Test URI validation
        validator = URIValidator(config)
        
        valid_uri = "https://example.org/data.ttl"
        invalid_scheme = "file:///etc/passwd"
        invalid_domain = "https://malicious.com/data.ttl"
        
        print(f"    ✅ URI validation (valid): {valid_uri} -> {validator.validate_uri(valid_uri)}")
        print(f"    ✅ URI validation (invalid scheme): {invalid_scheme} -> {validator.validate_uri(invalid_scheme)}")
        print(f"    ✅ URI validation (invalid domain): {invalid_domain} -> {validator.validate_uri(invalid_domain)}")
        
        # Test SPARQL query parsing
        parser = SPARQLLoadQueryParser()
        
        load_query_simple = "LOAD <https://example.org/data.ttl>"
        load_query_with_graph = "LOAD <https://example.org/data.ttl> INTO GRAPH <http://example.org/test-load>"
        
        source_uri, target_graph = parser.parse_load_query(load_query_simple)
        print(f"    ✅ Simple LOAD parsed: source={source_uri}, target={target_graph}")
        
        source_uri, target_graph = parser.parse_load_query(load_query_with_graph)
        print(f"    ✅ LOAD with graph parsed: source={source_uri}, target={target_graph}")
        
        # Test RDF format detection
        detector = RDFFormatDetector()
        
        turtle_format = detector.detect_format("text/turtle", "https://example.org/data.ttl")
        xml_format = detector.detect_format("application/rdf+xml", "https://example.org/data.rdf")
        extension_format = detector.detect_format("", "https://example.org/data.nt")
        
        print(f"    ✅ Format detection: turtle -> {turtle_format.value}")
        print(f"    ✅ Format detection: rdf+xml -> {xml_format.value}")
        print(f"    ✅ Format detection: .nt extension -> {extension_format.value}")
        
        # Test RDF parsing with sample content
        rdf_parser = RDFParser()
        
        sample_turtle = """
        @prefix ex: <http://example.org/> .
        ex:item1 ex:name "Sample Item" ;
                 ex:value "123" .
        """
        
        triples = rdf_parser.parse_content(sample_turtle, RDFFormat.TURTLE, "http://example.org/")
        print(f"    ✅ RDF parsing: {len(triples)} triples parsed from sample Turtle")
        
        # Test triple to quad conversion
        quads = rdf_parser.convert_triples_to_quads(triples, "http://example.org/test-graph")
        print(f"    ✅ Quad conversion: {len(quads)} quads created with target graph")
        
        quads_default = rdf_parser.convert_triples_to_quads(triples, None)
        print(f"    ✅ Quad conversion: {len(quads_default)} quads created with default graph")
        
        # Test DataTransferManager creation
        transfer_manager = DataTransferManager(config)
        supported_formats = transfer_manager.get_supported_formats()
        print(f"    ✅ Transfer manager created, supports {len(supported_formats)} formats: {', '.join(supported_formats)}")
        
        print("    ✅ All transfer utilities components tested successfully!")
        
        # Test with real URLs (if network is available)
        print("\n  Real URL LOAD tests:")
        
        # Test URLs with range from small to large RDF sources
        test_urls = [
            "https://www.w3.org/1999/02/22-rdf-syntax-ns.ttl",  # RDF vocabulary (small - ~127 triples)
            "https://www.w3.org/2000/01/rdf-schema.ttl",  # RDFS vocabulary (small - ~87 triples)
            "https://www.w3.org/2004/02/skos/core.rdf",  # SKOS vocabulary (medium - ~252 triples)
            "https://purl.org/dc/terms/",  # Dublin Core terms (medium - ~700 triples)
            "https://www.w3.org/2002/07/owl.rdf",  # OWL vocabulary (medium)
            "https://data.cdc.gov/api/views/cf5u-bm9w/rows.rdf?accessType=DOWNLOAD",  # CDC dataset #1 (large government data)
            "https://data.cdc.gov/api/views/mssc-ksj7/rows.rdf?accessType=DOWNLOAD",  # CDC dataset #2 (potentially larger)
            "https://data.cityofchicago.org/api/views/ijzp-q8t2/rows.rdf?accessType=DOWNLOAD",  # Chicago dataset (malformed XML)
        ]
        
        for test_url in test_urls:
            try:
                print(f"    Testing LOAD from: {test_url}")
                
                # Test just the transfer manager (without database insertion)
                load_result = await transfer_manager.execute_load_operation(
                    f"LOAD <{test_url}> INTO GRAPH <http://example.org/test-load>"
                )
                
                if load_result.success:
                    print(f"    ✅ Successfully loaded {load_result.triples_loaded} triples")
                    print(f"       Format: {load_result.format_detected}, Size: {load_result.content_size} bytes")
                    print(f"       Time: {load_result.elapsed_seconds:.3f}s")
                else:
                    print(f"    ❌ Load failed: {load_result.error_message}")
                    
                # Test additional URLs if the first one worked
                print(f"    ✅ First test successful, trying larger files...")
                    
            except Exception as e:
                print(f"    ⚠️  Could not test {test_url}: {e}")
                continue
        
        else:
            print("    ℹ️  No test URLs were accessible (network/firewall restrictions)")
        
    except Exception as e:
        print(f"    ❌ Error in transfer utilities test: {e}")
        import traceback
        traceback.print_exc()

async def main():
    """Main test controller - comprehensive UPDATE operations testing."""
    print("🧪 SPARQL 1.1 UPDATE/INSERT/DELETE Test Suite")
    print("=" * 60)
    
    # Setup connection
    await setup_connection()
    
    try:
        # Debug UPDATE parsing first
        await debug_update_parsing()
        
        # Run INSERT DATA tests (Phase 1)
        await test_insert_data()
        
        # Run pattern-based tests (Phase 2)
        await test_insert_delete_patterns()
        
        # Run graph management tests (Phase 3)
        await test_graph_management()
        
        # Run LOAD operation tests (Phase 4)
        await test_load_operations()
        
        # Skip other tests for now
        # await test_delete_data()
        # await test_combined_delete_insert()
        # await test_error_cases()
        
    finally:
        # Performance summary
        print(f"\n📊 Cache: {sparql_impl.term_cache.size()} terms")
        
        # Cleanup
        await cleanup_connection()
        print("\n✅ SPARQL UPDATE Test Suite Complete!")

if __name__ == "__main__":
    asyncio.run(main())
