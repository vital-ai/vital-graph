#!/usr/bin/env python3
"""
Create Test Space with Data Script

Creates the space_test_crud space and inserts comprehensive test data
using the VitalGraph JWT client. This data is designed for testing
SPARQL queries, BIND expressions, UNION operations, and built-in functions.

UPDATED: Now uses typed client methods with SpacesListResponse, 
SpaceCreateResponse, and SPARQL response models for full type safety.
"""

import sys
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

# Add the project root to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph.model.spaces_model import SpacesListResponse, SpaceCreateResponse, Space
from vitalgraph.model.sparql_model import SPARQLQueryResponse, SPARQLInsertResponse, SPARQLQueryRequest, SPARQLInsertRequest


def setup_logging():
    """Set up logging configuration for the test."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


def create_test_space_with_data(config_path: str) -> bool:
    """
    Create the space_test_crud space and insert comprehensive test data.
    
    Args:
        config_path: Path to configuration file (required)
        
    Returns:
        bool: True if creation was successful, False otherwise
    """
    logger = logging.getLogger(__name__)
    
    print("=" * 80)
    print("VitalGraph Test Space Creation with Data (JWT)")
    print("=" * 80)
    
    try:
        # Initialize and connect client with JWT
        print("\n1. Initializing and connecting JWT client...")
        client = VitalGraphClient(config_path)
        
        client.open()
        print(f"   ✓ JWT client connected: {client.is_connected()}")
        
        # Display JWT authentication status
        server_info: Dict[str, Any] = client.get_server_info()
        auth_info = server_info.get('authentication', {})
        print(f"   ✓ JWT Authentication Active:")
        print(f"     - Access Token: {'✓' if auth_info.get('has_access_token') else '✗'}")
        print(f"     - Refresh Token: {'✓' if auth_info.get('has_refresh_token') else '✗'}")
        
        # Check if space already exists and exit if found
        print("\n2. Checking for existing test space...")
        spaces_response: SpacesListResponse = client.list_spaces()
        existing_spaces = spaces_response.spaces
        print(f"   📊 Found {len(existing_spaces)} total spaces (total: {spaces_response.total_count})")
        print(f"   ✓ Response pagination: page_size={spaces_response.page_size}, offset={spaces_response.offset}")
        
        # Validate response structure
        if spaces_response.total_count != len(existing_spaces):
            print(f"   ⚠️  Warning: total_count ({spaces_response.total_count}) != actual count ({len(existing_spaces)})")
        else:
            print(f"   ✓ Response structure validated: counts match")
        
        test_space_identifier = "space_test_crud"
        existing_test_space = next((s for s in existing_spaces if s.space == test_space_identifier), None)
        
        if existing_test_space:
            print(f"   ⚠️  Found existing test space '{test_space_identifier}' (ID: {existing_test_space.id})")
            print(f"   🛑 Exiting to avoid conflicts. Please delete the existing space first using:")
            print(f"      python delete_test_space.py {test_space_identifier}")
            print(f"   Then run this script again to create fresh test data.")
            return False
        else:
            print(f"   ✓ No existing test space found, ready to proceed")
        
        # Create new test space
        print("\n3. Creating new test space...")
        test_space_data = {
            "tenant": "test_tenant",
            "space": test_space_identifier,
            "space_name": "SPARQL Test Space with Data",
            "space_description": "Test space with comprehensive data for SPARQL query testing"
        }
        print(f"   Space data to create:")
        print(f"   {json.dumps(test_space_data, indent=4)}")
        
        # Create Space object from dictionary
        test_space = Space(
            tenant=test_space_data["tenant"],
            space=test_space_data["space"],
            space_name=test_space_data["space_name"],
            space_description=test_space_data["space_description"]
        )
        add_response: SpaceCreateResponse = client.add_space(test_space)
        print(f"   ✓ Space created successfully:")
        print(f"   Message: {add_response.message}")
        print(f"   Created count: {add_response.created_count}")
        print(f"   Created URIs: {add_response.created_uris}")
        
        # Validate create response structure
        if add_response.created_count != 1:
            print(f"   ⚠️  Warning: Expected created_count=1, got {add_response.created_count}")
        if not add_response.created_uris or len(add_response.created_uris) != 1:
            raise VitalGraphClientError(f"Expected 1 created URI, got {len(add_response.created_uris) if add_response.created_uris else 0}")
        
        # Extract space ID from the response
        space_id = add_response.created_uris[0]
        if not space_id:
            raise VitalGraphClientError("Created space does not have an ID")
        print(f"   ✓ Space ID extracted: {space_id}")
        
        # Create test graph first
        print("\n4. Creating test graph...")
        test_graph_uri = "http://vital.ai/graph/test"
        global_graph_uri = "urn:___GLOBAL"
        
        try:
            # Create the main test graph using SPARQL UPDATE
            create_graph_query = f"CREATE GRAPH <{test_graph_uri}>"
            create_request = SPARQLInsertRequest(update=create_graph_query)
            create_result = client.execute_sparql_insert(test_space_identifier, create_request)
            print(f"   ✓ Test graph created: {test_graph_uri}")
        except Exception as e:
            print(f"   ⚠️  Graph creation warning: {e}")
            # Continue anyway - graph might already exist
        
        # Insert comprehensive test data
        print("\n5. Inserting comprehensive test data...")
        
        # Basic test entities for string operations
        print("   📝 Inserting basic test entities...")
        basic_entities_insert = f"""
        INSERT DATA {{
            GRAPH <{test_graph_uri}> {{
                <http://example.org/test#entity1> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/test#TestEntity> .
                <http://example.org/test#entity1> <http://example.org/test#hasName> "Hello World" .
                <http://example.org/test#entity1> <http://example.org/test#hasDescription> "A simple greeting message" .
                <http://example.org/test#entity1> <http://example.org/test#hasCategory> "greeting" .
                <http://example.org/test#entity1> <http://example.org/test#hasLength> 11 .
                <http://example.org/test#entity1> <http://example.org/test#hasAge> 25 .
                <http://example.org/test#entity1> <http://example.org/test#hasID> "entity1" .
                <http://example.org/test#entity1> <http://example.org/test#createdAt> "{datetime.now().isoformat()}" .
                
                <http://example.org/test#entity2> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/test#TestEntity> .
                <http://example.org/test#entity2> <http://example.org/test#hasName> "SPARQL Query Language" .
                <http://example.org/test#entity2> <http://example.org/test#hasDescription> "A powerful query language for RDF data" .
                <http://example.org/test#entity2> <http://example.org/test#hasCategory> "technology" .
                <http://example.org/test#entity2> <http://example.org/test#hasLength> 20 .
                <http://example.org/test#entity2> <http://example.org/test#hasAge> 15 .
                <http://example.org/test#entity2> <http://example.org/test#hasID> "entity2" .
                <http://example.org/test#entity2> <http://example.org/test#createdAt> "{datetime.now().isoformat()}" .
                
                <http://example.org/test#entity3> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/test#TestEntity> .
                <http://example.org/test#entity3> <http://example.org/test#hasName> "Test" .
                <http://example.org/test#entity3> <http://example.org/test#hasDescription> "Short test string for edge cases" .
                <http://example.org/test#entity3> <http://example.org/test#hasCategory> "test" .
                <http://example.org/test#entity3> <http://example.org/test#hasLength> 4 .
                <http://example.org/test#entity3> <http://example.org/test#hasAge> 35 .
                <http://example.org/test#entity3> <http://example.org/test#hasID> "entity3" .
                <http://example.org/test#entity3> <http://example.org/test#createdAt> "{datetime.now().isoformat()}" .
                
                <http://example.org/test#entity4> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/test#TestEntity> .
                <http://example.org/test#entity4> <http://example.org/test#hasName> "VitalGraph Database System" .
                <http://example.org/test#entity4> <http://example.org/test#hasDescription> "A graph database built on PostgreSQL" .
                <http://example.org/test#entity4> <http://example.org/test#hasCategory> "database" .
                <http://example.org/test#entity4> <http://example.org/test#hasLength> 26 .
                <http://example.org/test#entity4> <http://example.org/test#hasAge> 45 .
                <http://example.org/test#entity4> <http://example.org/test#hasID> "entity4" .
                <http://example.org/test#entity4> <http://example.org/test#createdAt> "{datetime.now().isoformat()}" .
                
                <http://example.org/test#entity5> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/test#TestEntity> .
                <http://example.org/test#entity5> <http://example.org/test#hasName> "AI" .
                <http://example.org/test#entity5> <http://example.org/test#hasDescription> "Artificial Intelligence abbreviation" .
                <http://example.org/test#entity5> <http://example.org/test#hasCategory> "ai" .
                <http://example.org/test#entity5> <http://example.org/test#hasLength> 2 .
                <http://example.org/test#entity5> <http://example.org/test#hasAge> 5 .
                <http://example.org/test#entity5> <http://example.org/test#hasID> "entity5" .
                <http://example.org/test#entity5> <http://example.org/test#createdAt> "{datetime.now().isoformat()}" .
            }}
        }}
        """
        
        insert_request = SPARQLInsertRequest(update=basic_entities_insert)
        result: SPARQLInsertResponse = client.execute_sparql_insert(test_space_identifier, insert_request)
        print(f"   ✓ Basic entities inserted successfully")
        
        # Add relationships between entities
        print("   🔗 Inserting entity relationships...")
        relationships_insert = f"""
        INSERT DATA {{
            GRAPH <{test_graph_uri}> {{
                <http://example.org/test#entity1> <http://example.org/test#relatedTo> <http://example.org/test#entity2> .
                <http://example.org/test#entity2> <http://example.org/test#relatedTo> <http://example.org/test#entity3> .
                <http://example.org/test#entity3> <http://example.org/test#relatedTo> <http://example.org/test#entity4> .
                <http://example.org/test#entity4> <http://example.org/test#relatedTo> <http://example.org/test#entity5> .
                <http://example.org/test#entity5> <http://example.org/test#relatedTo> <http://example.org/test#entity1> .
            }}
        }}
        """
        
        insert_request = SPARQLInsertRequest(update=relationships_insert)
        result: SPARQLInsertResponse = client.execute_sparql_insert(test_space_identifier, insert_request)
        print(f"   ✓ Entity relationships inserted successfully")
        
        # Add numeric test data
        print("   🔢 Inserting numeric test data...")
        numeric_insert = f"""
        INSERT DATA {{
            GRAPH <{test_graph_uri}> {{
                <http://example.org/test#number1> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/test#NumberEntity> .
                <http://example.org/test#number1> <http://example.org/test#hasValue> 10 .
                <http://example.org/test#number1> <http://example.org/test#hasDoubleValue> 20 .
                <http://example.org/test#number1> <http://example.org/test#hasLabel> "Number 10" .
                
                <http://example.org/test#number2> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/test#NumberEntity> .
                <http://example.org/test#number2> <http://example.org/test#hasValue> 25 .
                <http://example.org/test#number2> <http://example.org/test#hasDoubleValue> 50 .
                <http://example.org/test#number2> <http://example.org/test#hasLabel> "Number 25" .
                
                <http://example.org/test#number3> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/test#NumberEntity> .
                <http://example.org/test#number3> <http://example.org/test#hasValue> 50 .
                <http://example.org/test#number3> <http://example.org/test#hasDoubleValue> 100 .
                <http://example.org/test#number3> <http://example.org/test#hasLabel> "Number 50" .
                
                <http://example.org/test#number4> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/test#NumberEntity> .
                <http://example.org/test#number4> <http://example.org/test#hasValue> 100 .
                <http://example.org/test#number4> <http://example.org/test#hasDoubleValue> 200 .
                <http://example.org/test#number4> <http://example.org/test#hasLabel> "Number 100" .
                
                <http://example.org/test#number5> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/test#NumberEntity> .
                <http://example.org/test#number5> <http://example.org/test#hasValue> 0 .
                <http://example.org/test#number5> <http://example.org/test#hasDoubleValue> 0 .
                <http://example.org/test#number5> <http://example.org/test#hasLabel> "Number 0" .
            }}
        }}
        """
        
        insert_request = SPARQLInsertRequest(update=numeric_insert)
        result: SPARQLInsertResponse = client.execute_sparql_insert(test_space_identifier, insert_request)
        print(f"   ✓ Numeric test data inserted successfully")
        
        # Add UNION-specific test data
        print("   🔗 Inserting UNION test data...")
        union_insert = f"""
        INSERT DATA {{
            GRAPH <{test_graph_uri}> {{
                <http://example.org/test#unionEntity1> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/test#UnionTestEntity> .
                <http://example.org/test#unionEntity1> <http://example.org/test#hasName> "Entity with Description" .
                <http://example.org/test#unionEntity1> <http://example.org/test#hasDescription> "This entity has both name and description" .
                <http://example.org/test#unionEntity1> <http://example.org/test#hasCategory> "complete" .
                
                <http://example.org/test#unionEntity2> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/test#UnionTestEntity> .
                <http://example.org/test#unionEntity2> <http://example.org/test#hasName> "Entity without Description" .
                <http://example.org/test#unionEntity2> <http://example.org/test#hasCategory> "incomplete" .
                
                <http://example.org/test#unionEntity3> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/test#UnionTestEntity> .
                <http://example.org/test#unionEntity3> <http://example.org/test#hasName> "Another Complete Entity" .
                <http://example.org/test#unionEntity3> <http://example.org/test#hasDescription> "Another entity with description for UNION testing" .
                <http://example.org/test#unionEntity3> <http://example.org/test#hasCategory> "complete" .
                
                <http://example.org/test#unionEntity4> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/test#UnionTestEntity> .
                <http://example.org/test#unionEntity4> <http://example.org/test#hasName> "Minimal Entity" .
                <http://example.org/test#unionEntity4> <http://example.org/test#hasCategory> "minimal" .
            }}
        }}
        """
        
        insert_request = SPARQLInsertRequest(update=union_insert)
        result: SPARQLInsertResponse = client.execute_sparql_insert(test_space_identifier, insert_request)
        print(f"   ✓ UNION test data inserted successfully")
        
        # Add person entities to global graph for comprehensive testing
        print("   👥 Inserting person test data to global graph...")
        person_insert = f"""
        INSERT DATA {{
            GRAPH <{global_graph_uri}> {{
                <http://example.org/person1> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/Person> .
                <http://example.org/person1> <http://example.org/hasName> "Alice Johnson" .
                <http://example.org/person1> <http://example.org/hasAge> 28 .
                <http://example.org/person1> <http://example.org/hasEmail> "alice@example.com" .
                <http://example.org/person1> <http://example.org/hasPhone> "+1-555-0101" .
                <http://example.org/person1> <http://example.org/hasBirthDate> "1995-03-15"^^<http://www.w3.org/2001/XMLSchema#date> .
                
                <http://example.org/person2> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/Person> .
                <http://example.org/person2> <http://example.org/hasName> "Bob Smith" .
                <http://example.org/person2> <http://example.org/hasAge> 35 .
                <http://example.org/person2> <http://example.org/hasEmail> "bob@example.com" .
                <http://example.org/person2> <http://example.org/hasBirthDate> "1988-07-22"^^<http://www.w3.org/2001/XMLSchema#date> .
                
                <http://example.org/person3> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/Person> .
                <http://example.org/person3> <http://example.org/hasName> "Charlie Brown" .
                <http://example.org/person3> <http://example.org/hasAge> 22 .
                <http://example.org/person3> <http://example.org/hasPhone> "+1-555-0303" .
                <http://example.org/person3> <http://example.org/hasBirthDate> "2001-12-05"^^<http://www.w3.org/2001/XMLSchema#date> .
                
                <http://example.org/person4> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/Person> .
                <http://example.org/person4> <http://example.org/hasName> "Diana Prince" .
                <http://example.org/person4> <http://example.org/hasAge> 30 .
                <http://example.org/person4> <http://example.org/hasTitle> "Wonder Woman" .
                <http://example.org/person4> <http://example.org/hasBirthDate> "1993-10-21"^^<http://www.w3.org/2001/XMLSchema#date> .
                
                <http://example.org/person5> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/Person> .
                <http://example.org/person5> <http://example.org/hasName> "Clark Kent" .
                <http://example.org/person5> <http://example.org/hasAge> 32 .
                <http://example.org/person5> <http://example.org/hasPhone> "+1-555-0505" .
                <http://example.org/person5> <http://example.org/hasTitle> "Superman" .
                <http://example.org/person5> <http://example.org/hasBirthDate> "1991-06-18"^^<http://www.w3.org/2001/XMLSchema#date> .
            }}
        }}
        """
        
        insert_request = SPARQLInsertRequest(update=person_insert)
        result: SPARQLInsertResponse = client.execute_sparql_insert(test_space_identifier, insert_request)
        print(f"   ✓ Person test data inserted to global graph successfully")
        
        # Add product entities for numeric testing
        print("   🛍️  Inserting product test data...")
        product_insert = f"""
        INSERT DATA {{
            GRAPH <{test_graph_uri}> {{
                <http://example.org/product1> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/Product> .
                <http://example.org/product1> <http://example.org/hasName> "Laptop Computer" .
                <http://example.org/product1> <http://example.org/hasPrice> 1299.99 .
                <http://example.org/product1> <http://example.org/hasWarrantyMonths> 24 .
                <http://example.org/product1> <http://example.org/hasRating> 4.5 .
                
                <http://example.org/product2> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/Product> .
                <http://example.org/product2> <http://example.org/hasName> "Smartphone" .
                <http://example.org/product2> <http://example.org/hasPrice> 799.50 .
                <http://example.org/product2> <http://example.org/hasWarrantyMonths> 12 .
                <http://example.org/product2> <http://example.org/hasRating> 4.2 .
                
                <http://example.org/product3> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/Product> .
                <http://example.org/product3> <http://example.org/hasName> "Tablet Device" .
                <http://example.org/product3> <http://example.org/hasPrice> 449.00 .
                <http://example.org/product3> <http://example.org/hasWarrantyMonths> 18 .
                <http://example.org/product3> <http://example.org/hasRating> 4.0 .
                
                <http://example.org/product4> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/Product> .
                <http://example.org/product4> <http://example.org/hasName> "Wireless Headphones" .
                <http://example.org/product4> <http://example.org/hasPrice> 199.99 .
                <http://example.org/product4> <http://example.org/hasWarrantyMonths> 6 .
                <http://example.org/product4> <http://example.org/hasRating> 4.7 .
                
                <http://example.org/product5> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/Product> .
                <http://example.org/product5> <http://example.org/hasName> "Smart Watch" .
                <http://example.org/product5> <http://example.org/hasPrice> 349.00 .
                <http://example.org/product5> <http://example.org/hasWarrantyMonths> 12 .
                <http://example.org/product5> <http://example.org/hasRating> 3.8 .
            }}
        }}
        """
        
        insert_request = SPARQLInsertRequest(update=product_insert)
        result: SPARQLInsertResponse = client.execute_sparql_insert(test_space_identifier, insert_request)
        print(f"   ✓ Product test data inserted successfully")
        
        # Verify data insertion with a simple query
        print("\n6. Verifying data insertion...")
        verify_query = f"""
        SELECT (COUNT(*) AS ?count) WHERE {{
            GRAPH <{test_graph_uri}> {{
                ?s ?p ?o
            }}
        }}
        """
        
        query_request = SPARQLQueryRequest(query=verify_query, format="json")
        result: SPARQLQueryResponse = client.execute_sparql_query(test_space_identifier, query_request)
        
        # Handle different response formats - could be dict or object
        if result:
            # Check if result is a dict (raw response) or SPARQLQueryResponse object
            if isinstance(result, dict):
                # Handle raw dict response
                bindings = result.get('results', {}).get('bindings', [])
            else:
                # Handle SPARQLQueryResponse object
                bindings = result.results.bindings if result.results and hasattr(result.results, 'bindings') else []
            
            if bindings:
                # Handle both formats: {'count': {'value': 104}} and {'count': 104}
                count_data = bindings[0].get('count', 0)
                if isinstance(count_data, dict) and 'value' in count_data:
                    count = count_data['value']
                else:
                    count = count_data
                print(f"   ✓ Data verification successful: {count} triples in test graph")
            else:
                print(f"   ⚠️  No count result returned")
        else:
            print(f"   ⚠️  Verification query returned no result")
        
        # Verify global graph data
        global_verify_query = f"""
        SELECT (COUNT(*) AS ?count) WHERE {{
            GRAPH <{global_graph_uri}> {{
                ?s ?p ?o
            }}
        }}
        """
        
        query_request = SPARQLQueryRequest(query=global_verify_query, format="json")
        result: SPARQLQueryResponse = client.execute_sparql_query(test_space_identifier, query_request)
        
        # Handle different response formats - could be dict or object
        if result:
            # Check if result is a dict (raw response) or SPARQLQueryResponse object
            if isinstance(result, dict):
                # Handle raw dict response
                bindings = result.get('results', {}).get('bindings', [])
            else:
                # Handle SPARQLQueryResponse object
                bindings = result.results.bindings if result.results and hasattr(result.results, 'bindings') else []
            
            if bindings:
                # Handle both formats: {'count': {'value': 104}} and {'count': 104}
                count_data = bindings[0].get('count', 0)
                if isinstance(count_data, dict) and 'value' in count_data:
                    count = count_data['value']
                else:
                    count = count_data
                print(f"   ✓ Global graph verification successful: {count} triples in global graph")
            else:
                print(f"   ⚠️  No global count result returned")
        else:
            print(f"   ⚠️  Global verification query returned no result")
        
        # Close client
        client.close()
        print(f"\n7. Client closed successfully")
        
        print("\n✅ Test space creation and data insertion completed successfully!")
        print("\n📊 Summary:")
        print(f"   • Space created: {test_space_identifier} (ID: {space_id})")
        print(f"   • Test graph: {test_graph_uri}")
        print(f"   • Global graph: {global_graph_uri}")
        print(f"   • Data types inserted:")
        print(f"     - Basic test entities (5 entities)")
        print(f"     - Entity relationships")
        print(f"     - Numeric test data (5 numbers)")
        print(f"     - UNION test entities (4 entities)")
        print(f"     - Person entities in global graph (5 people)")
        print(f"     - Product entities (5 products)")
        print(f"   • Ready for SPARQL query testing!")
        
    except VitalGraphClientError as e:
        print(f"   ❌ VitalGraph client error: {e}")
        logger.error(f"Client error: {e}")
        return False
    except Exception as e:
        print(f"   ❌ Unexpected error: {e}")
        logger.error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


def main() -> int:
    """Main function to create test space with data.
    
    Returns:
        int: Exit code (0 for success, 1 for failure)
    """
    setup_logging()
    logger = logging.getLogger(__name__)
    
    print("Starting VitalGraph Test Space Creation with Data...")
    
    # Determine config file path (required for JWT client)
    config_dir = Path(__file__).parent.parent / "vitalgraphclient_config"
    config_file = config_dir / "vitalgraphclient-config.yaml"
    
    if config_file.exists():
        config_path = str(config_file)
        print(f"✓ Found config file: {config_path}")
    else:
        print(f"❌ Config file not found: {config_file}")
        print("   JWT client requires a configuration file.")
        print("   Please ensure vitalgraphclient-config.yaml exists in the vitalgraphclient_config directory.")
        return 1
    
    # Create test space with data
    success = create_test_space_with_data(config_path)
    
    if success:
        print("\n🎉 Test space creation with data completed successfully!")
        print("\n✅ Ready for SPARQL query testing with typed client methods!")
        print("   You can now run SPARQL test scripts against the 'space_test_crud' space.")
        print("   Used typed SpaceCreateResponse, SPARQLInsertResponse, and SPARQLQueryResponse models.")
        return 0
    else:
        print("\n❌ Test space creation failed.")
        print("   Check the error messages above for details.")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
