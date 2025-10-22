#!/usr/bin/env python3
"""
Test script for KGTypes endpoint using VitalSigns objects.

This script tests the GET, LIST, CREATE, UPDATE, and DELETE operations 
of the KGTypes endpoint using proper VitalSigns object creation.

UPDATED: Now uses typed client methods with KGTypeListResponse models 
instead of direct HTTP calls for full type safety.
"""

import sys
import json
from pathlib import Path
from typing import Optional

from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph.model.kgtypes_model import KGTypeListResponse, KGTypeCreateResponse, KGTypeUpdateResponse, KGTypeDeleteResponse
from vitalgraph.model.jsonld_model import JsonLdDocument
from vitalgraph.model.spaces_model import Space, SpaceCreateResponse
from ai_haley_kg_domain.model.KGType import KGType
from ai_haley_kg_domain.model.KGEntityType import KGEntityType
from ai_haley_kg_domain.model.KGFrameType import KGFrameType
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.utils.uri_generator import URIGenerator
from rdflib import Graph, Namespace, URIRef
from typing import List, Union


def setup_logging():
    """Set up logging configuration for the test."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


def create_kgtype_object(description: str, model_version: str = "1.0", type_version: str = "1.0", kgtype_class=None):
    """Create a KGType object with VitalSigns randomized URI."""
    # Instantiate the correct class (vitaltype comes with class instantiation)
    if kgtype_class is None:
        kgtype_class = KGType
    
    kgtype = kgtype_class()
    
    # Generate randomized URI using VitalSigns URIGenerator
    kgtype.URI = URIGenerator.generate_uri()
    
    # Set properties
    kgtype.kGModelVersion = model_version
    kgtype.kGTypeVersion = type_version
    kgtype.kGraphDescription = description
    
    return kgtype


def kgtypes_to_jsonld_document(kgtypes: list) -> dict:
    """Convert list of KGType objects to JSON-LD document format."""
    # Convert each KGType to JSON and create JSON-LD structure
    graph_objects = []
    
    for kgtype in kgtypes:
        # Convert KGType to JSON representation
        kgtype_json = kgtype.to_json()
        kgtype_dict = json.loads(kgtype_json)
        
        # Ensure proper JSON-LD structure
        if '@id' not in kgtype_dict and 'URI' in kgtype_dict:
            kgtype_dict['@id'] = kgtype_dict['URI']
        
        # Add rdf:type for VitalSigns compatibility
        vitaltype = kgtype_dict.get('vitaltype')
        if vitaltype:
            # Add both @type (for JSON-LD) and explicit rdf:type property
            kgtype_dict['@type'] = vitaltype
            kgtype_dict['http://www.w3.org/1999/02/22-rdf-syntax-ns#type'] = vitaltype
        
        graph_objects.append(kgtype_dict)
    
    # Create JSON-LD document structure
    jsonld_doc = {
        "@context": {
            "haley": "http://vital.ai/ontology/haley-ai-kg#",
            "vital": "http://vital.ai/ontology/vital-core#",
            "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
            "vitaltype": "vital:vitaltype",
            "URI": "vital:URI",  # Map URI to vital:URI property
            "@type": "rdf:type"  # Map @type to rdf:type
        },
        "@graph": graph_objects
    }
    
    return {
        "document": jsonld_doc
    }


def jsonld_to_vitalsigns_objects(jsonld_response: dict) -> List[GraphObject]:
    """
    Convert JSON-LD response from VitalGraph service back to VitalSigns objects.
    Uses PyLD library to convert JSON-LD to RDF N-Triples, then VitalSigns.from_triples_list()
    for efficient batch processing of multiple objects.
    
    Args:
        jsonld_response: JSON-LD response from VitalGraph API
        
    Returns:
        List of VitalSigns GraphObject instances
    """
    try:
        from pyld import jsonld
        
        # Initialize VitalSigns
        vs = VitalSigns()
        
        # Extract the data from the response
        data = jsonld_response.get('data', {})
        
        # Use RDFLib to parse JSON-LD directly
        from rdflib import Graph
        import json
        
        g = Graph()
        # Convert data to JSON string for RDFLib
        json_str = json.dumps(data)
        
        g.parse(data=json_str, format='json-ld')
        
        # Use the RDFLib graph directly as the triples generator!
        if len(g) > 0:
            # Ensure we have rdf:type triples for VitalSigns compatibility
            from rdflib import URIRef
            rdf_type_uriref = URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
            has_rdf_type = any(p == rdf_type_uriref for s, p, o in g)
            
            if not has_rdf_type:
                # Add rdf:type triples based on vitaltype for VitalSigns compatibility
                vitaltype_uriref = URIRef("http://vital.ai/ontology/vital-core#vitaltype")
                
                # Find all vitaltype triples and add corresponding rdf:type triples
                for s, p, o in list(g):
                    if p == vitaltype_uriref:
                        # Add rdf:type triple
                        g.add((s, rdf_type_uriref, o))
            
            # RDFLib graph is already an iterator of (s, p, o) tuples
            graph_objects = vs.from_triples_list(g, modified=False)
            
            # Convert to list if it's not already
            return list(graph_objects) if graph_objects else []
        else:
            return []
                
    except Exception as e:
        print(f"Error processing JSON-LD response: {e}")
        return []



def log_test_data(title: str, data: dict, kgtypes: list = None):
    """Log test data in a readable format for dry run mode."""
    print(f"\n📋 {title}")
    print("-" * 60)
    
    if kgtypes:
        print("VitalSigns KGType Objects:")
        for i, kgtype in enumerate(kgtypes, 1):
            print(f"  {i}. KGType Object:")
            print(f"     - URI: {kgtype.URI}")
            print(f"     - Class: {kgtype.__class__.__name__}")
            print(f"     - Model Version: {getattr(kgtype, 'kGModelVersion', 'N/A')}")
            print(f"     - Type Version: {getattr(kgtype, 'kGTypeVersion', 'N/A')}")
            print(f"     - Description: {getattr(kgtype, 'kGraphDescription', 'N/A')}")
            print()
    
    print("JSON-LD Document Structure:")
    print(json.dumps(data, indent=2))
    print("-" * 60)


def test_kgtypes_endpoint(config_path: str, dry_run: bool = False):
    """Test the KGTypes endpoint with VitalSigns KGType objects."""
    logger = logging.getLogger(__name__)
    
    # Initialize global variables for storing test URIs
    global test_kgtype_uris, product_kgtype_uri
    test_kgtype_uris = {}
    product_kgtype_uri = None
    
    print("=" * 80)
    if dry_run:
        print("VitalGraph KGTypes Endpoint Testing - DRY RUN MODE")
        print("(Test data creation only - no API calls)")
    else:
        print("VitalGraph KGTypes Endpoint Testing")
    print("=" * 80)
    
    try:
        # Test parameters - create new space for KGTypes testing (max 15 chars)
        import time
        timestamp = str(int(time.time()))[-6:]  # Last 6 digits of timestamp
        space_id = f"kg_test_{timestamp}"  # Format: kg_test_123456 (14 chars max)
        graph_id = "urn:test_kgtypes"
        
        if not dry_run:
            # Initialize and connect client with JWT
            print("\n1. Initializing and connecting JWT client...")
            client = VitalGraphClient(config_path)
            
            client.open()
            print(f"   ✓ JWT client connected: {client.is_connected()}")
            
            # Display JWT authentication status
            server_info = client.get_server_info()
            auth_info = server_info.get('authentication', {})
            print(f"   ✓ JWT Authentication Active:")
            print(f"     - Access Token: {'✓' if auth_info.get('has_access_token') else '✗'}")
            print(f"     - Refresh Token: {'✓' if auth_info.get('has_refresh_token') else '✗'}")
            
            base_url = f"{client.config.get_server_url()}/api/graphs/kgtypes"
        else:
            print("\n1. Skipping client connection (dry run mode)")
            client = None
            base_url = "http://localhost:8001/api/graphs/kgtypes"
        
        # Setup: Create space and add test data
        print("\n2. Setting up test space and data...")
        try:
            if not dry_run:
                # Check if space already exists and delete it for clean test environment
                try:
                    spaces_response = client.list_spaces()
                    existing_spaces = []
                    if hasattr(spaces_response, 'spaces') and spaces_response.spaces:
                        existing_spaces = [space.space_id for space in spaces_response.spaces]
                    elif hasattr(spaces_response, 'data') and spaces_response.data:
                        # Handle different response formats
                        if isinstance(spaces_response.data, list):
                            existing_spaces = [space.get('space_id', space.get('space', '')) for space in spaces_response.data]
                    
                    if space_id in existing_spaces:
                        print(f"   🗑️ Deleting existing test space: {space_id}")
                        try:
                            delete_response = client.delete_space(space_id)
                            print(f"   ✓ Deleted existing space: {space_id}")
                        except Exception as delete_e:
                            print(f"   ⚠ Warning: Could not delete existing space: {delete_e}")
                            # Continue anyway
                    
                except Exception as list_e:
                    print(f"   ⚠ Warning: Could not check existing spaces: {list_e}")
                    # Continue anyway
                
                # Create fresh space
                try:
                    space_data = {
                        "space": space_id,
                        "space_name": "KGTypes Test Space",
                        "space_description": "Test space for KGTypes endpoint testing"
                    }
                    # Create Space object from dictionary
                    test_space = Space(
                        space=space_data["space"],
                        space_name=space_data["space_name"],
                        space_description=space_data["space_description"]
                    )
                    add_response: SpaceCreateResponse = client.add_space(test_space)
                    print(f"   ✓ Created test space: {space_id}")
                    print(f"     - Message: {add_response.message}")
                    print(f"     - Created count: {add_response.created_count}")
                    print(f"     - Created URIs: {add_response.created_uris}")
                    
                    # Create the test graph
                    try:
                        create_result = client.execute_sparql_graph_operation(
                            space_id,
                            "CREATE",
                            target_graph_uri=graph_id
                        )
                        print(f"   ✓ Created test graph: {graph_id}")
                    except Exception as graph_e:
                        print(f"   ⚠ Graph creation warning: {graph_e}")
                        # Continue anyway - graph might already exist
                        
                except VitalGraphClientError as e:
                    print(f"   ✗ Space creation failed: {e}")
                    print(f"   Cannot continue without valid test space. Exiting.")
                    return False
            else:
                print(f"   📝 Would create test space: {space_id}")
            
            # Create test KGTypes using VitalSigns objects
            print("   Creating KGType objects with VitalSigns...")
            
            # Create KGType objects using different subclasses
            person_type = create_kgtype_object("Represents a person entity type", kgtype_class=KGEntityType)
            org_type = create_kgtype_object("Represents an organization entity type", kgtype_class=KGEntityType)
            location_type = create_kgtype_object("Represents a location entity type", kgtype_class=KGFrameType)
            
            # Store URIs for later use in tests
            test_kgtype_uris = {
                'person': person_type.URI,
                'organization': org_type.URI,
                'location': location_type.URI
            }
            
            print(f"   Generated URIs:")
            print(f"     - Person: {person_type.URI} (KGEntityType)")
            print(f"     - Organization: {org_type.URI} (KGEntityType)")
            print(f"     - Location: {location_type.URI} (KGFrameType)")
            
            # Convert to JSON-LD document
            test_kgtypes = kgtypes_to_jsonld_document([person_type, org_type, location_type])
            
            if dry_run:
                # Log test data instead of making API call
                log_test_data("Initial Test Data (3 KGTypes)", test_kgtypes, [person_type, org_type, location_type])
                
                # Test round-trip conversion: VitalSigns → JSON-LD → VitalSigns
                print("\n🔄 Testing Round-Trip Conversion (VitalSigns → JSON-LD → VitalSigns)")
                print("-" * 70)
                
                try:
                    # Simulate API response format
                    simulated_response = {
                        'data': test_kgtypes['document'],
                        'pagination': {'total': 3, 'offset': 0, 'page_size': 10}
                    }
                    
                    # Convert back to VitalSigns objects
                    converted_objects = jsonld_to_vitalsigns_objects(simulated_response)
                    
                    print(f"✓ Round-trip conversion successful!")
                    print(f"  - Original objects: {len([person_type, org_type, location_type])}")
                    print(f"  - Converted objects: {len(converted_objects)}")
                    
                    # Compare original vs converted objects by URI matching
                    original_objects = [person_type, org_type, location_type]
                    
                    # Create URI to object mapping for converted objects
                    converted_by_uri = {obj.URI: obj for obj in converted_objects}
                    
                    print("\n📊 Object Comparison (matched by URI):")
                    matches = 0
                    for i, orig in enumerate(original_objects):
                        print(f"  {i+1}. Original Object:")
                        print(f"     URI: {orig.URI}")
                        print(f"     Class: {orig.__class__.__name__}")
                        print(f"     Description: {getattr(orig, 'kGraphDescription', 'N/A')}")
                        
                        # Find matching converted object by URI
                        conv = converted_by_uri.get(orig.URI)
                        if conv:
                            print(f"     ✓ Found matching converted object:")
                            print(f"       Class: {conv.__class__.__name__}")
                            print(f"       Description: {getattr(conv, 'kGraphDescription', 'N/A')}")
                            
                            # Check matches
                            class_match = orig.__class__.__name__ == conv.__class__.__name__
                            desc_match = getattr(orig, 'kGraphDescription', None) == getattr(conv, 'kGraphDescription', None)
                            
                            print(f"       Class Match: {'✓' if class_match else '✗'}")
                            print(f"       Description Match: {'✓' if desc_match else '✗'}")
                            
                            if class_match and desc_match:
                                matches += 1
                        else:
                            print(f"     ✗ No matching converted object found")
                        print()
                    
                    print(f"📈 Overall Success Rate: {matches}/{len(original_objects)} objects fully matched")
                    
                    print("🎉 Round-trip conversion test completed!")
                    
                except Exception as e:
                    print(f"❌ Round-trip conversion failed: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                # Create the test KGTypes using client method
                jsonld_doc = JsonLdDocument(data=test_kgtypes)
                result: KGTypeCreateResponse = client.create_kgtypes(space_id, graph_id, jsonld_doc)
                created_count = getattr(result, 'created_count', 0)
                print(f"   ✓ Created test KGTypes: {created_count} types")
                
        except Exception as e:
            print(f"   ⚠ Setup error (continuing): {e}")
        
        if dry_run:
            print("\n3-5. Skipping List/Search/Get tests (dry run mode)")
            print("   📝 These tests would query the API for existing data")
        else:
            # Test 1: List KGTypes with pagination
            print("\n3. Testing List KGTypes (Paginated)...")
            try:
                # Use typed client method to list KGTypes
                kgtypes_response: KGTypeListResponse = client.kgtypes.list_kgtypes(
                    space_id=space_id,
                    graph_id=graph_id,
                    page_size=5,
                    offset=0
                )
                print(f"   ✓ Listed KGTypes successfully")
                print(f"     - Total count: {kgtypes_response.total_count}")
                print(f"     - Page size: {kgtypes_response.page_size}")
                print(f"     - Offset: {kgtypes_response.offset}")
                
                # Access KGTypes from the JsonLdDocument
                kgtypes_list = kgtypes_response.data.graph if kgtypes_response.data.graph else []
                print(f"     - KGTypes returned: {len(kgtypes_list)}")
                
                # Create compatible data structure for existing code
                data = {'data': {'@graph': kgtypes_list}, 'pagination': {'total': kgtypes_response.total_count}}
                
                # Convert JSON-LD response back to VitalSigns objects
                vitalsigns_objects = jsonld_to_vitalsigns_objects(data)
                print(f"     - Converted to VitalSigns objects: {len(vitalsigns_objects)}")
                
                # Show first KGType as both JSON-LD and VitalSigns object
                if kgtypes_list and vitalsigns_objects:
                    first_kgtype_json = kgtypes_list[0]
                    first_kgtype_vs = vitalsigns_objects[0]
                    
                    print(f"     - First KGType (JSON-LD): {first_kgtype_json.get('@id', 'No @id')}")
                    vitaltype = first_kgtype_json.get('http://vital.ai/ontology/vital-core#vitaltype', 
                                                     first_kgtype_json.get('vitaltype', 'No vitaltype'))
                    print(f"       - Type: {vitaltype}")
                    
                    print(f"     - First KGType (VitalSigns): {first_kgtype_vs.URI}")
                    print(f"       - Class: {first_kgtype_vs.__class__.__name__}")
                    print(f"       - Model Version: {getattr(first_kgtype_vs, 'kGModelVersion', 'N/A')}")
                    print(f"       - Description: {getattr(first_kgtype_vs, 'kGraphDescription', 'N/A')}")
                else:
                    print(f"     - No KGTypes found")
                    
            except VitalGraphClientError as e:
                print(f"   ✗ Error listing KGTypes: {e}")
            except Exception as e:
                print(f"   ✗ Unexpected error: {e}")
        
        # Test 2: Search KGTypes
        print("\n4. Testing Search KGTypes...")
        try:
            # Use typed client method to search KGTypes
            search_response: KGTypeListResponse = client.kgtypes.list_kgtypes(
                space_id=space_id,
                graph_id=graph_id,
                search="type",  # Search for types containing "type"
                page_size=3,
                offset=0
            )
            
            print(f"   ✓ Search completed successfully")
            print(f"     - Found {search_response.total_count} KGTypes matching 'type'")
            
            # Show search results
            kgtypes = search_response.data.graph if search_response.data.graph else []
            for i, kgtype in enumerate(kgtypes[:3]):
                print(f"     - Result {i+1}: {kgtype.get('@id', 'No @id')}")
                
        except VitalGraphClientError as e:
            print(f"   ✗ Error searching KGTypes: {e}")
        except Exception as e:
            print(f"   ✗ Unexpected error: {e}")
        
        # Test 3: Get specific KGType by URI (if any exist)
        print("\n5. Testing Get KGType by URI...")
        try:
            # First get a list to find a URI to test with
            list_response: KGTypeListResponse = client.kgtypes.list_kgtypes(
                space_id=space_id,
                graph_id=graph_id,
                page_size=1,
                offset=0
            )
            
            kgtypes = list_response.data.graph if list_response.data.graph else []
            
            if kgtypes:
                test_uri = kgtypes[0].get('@id')
                print(f"   Testing with URI: {test_uri}")
                
                # Get specific KGType using typed client method
                # Note: Assuming there's a get_kgtype method, or we can use list with URI filter
                uri_response: KGTypeListResponse = client.kgtypes.list_kgtypes(
                    space_id=space_id,
                    graph_id=graph_id,
                    uri=test_uri
                )
                
                kgtype_list = uri_response.data.graph if uri_response.data.graph else []
                if kgtype_list:
                    kgtype = kgtype_list[0]
                    print(f"   ✓ Retrieved KGType successfully")
                    print(f"     - URI: {kgtype.get('@id')}")
                    vitaltype = kgtype.get('http://vital.ai/ontology/vital-core#vitaltype', 
                                         kgtype.get('vitaltype', 'None'))
                    print(f"     - Type: {vitaltype}")
                else:
                    print(f"   ✗ No KGType data in response")
            else:
                print(f"   ⚠ No KGTypes available to test URI lookup")
                
        except VitalGraphClientError as e:
            print(f"   ✗ Error getting KGType by URI: {e}")
        except Exception as e:
            print(f"   ✗ Unexpected error: {e}")
        
        # Test 4: Create KGType
        print("\n6. Testing Create KGType...")
        try:
            # Create a new KGType using VitalSigns
            product_type = create_kgtype_object("Represents a product entity type")
            print(f"   Generated Product KGType URI: {product_type.URI}")
            
            # Store for later tests (convert to string to avoid CombinedProperty issues)
            product_kgtype_uri = str(product_type.URI)
            
            # Convert to JSON-LD document
            create_data = kgtypes_to_jsonld_document([product_type])
            
            if dry_run:
                # Log test data instead of making API call
                log_test_data("Create Product KGType", create_data, [product_type])
            else:
                # Use typed client method to create KGType
                jsonld_doc = JsonLdDocument(data=create_data)
                create_response: KGTypeCreateResponse = client.create_kgtypes(space_id, graph_id, jsonld_doc)
                print(f"   ✓ Create request completed")
                print(f"     - Message: {create_response.message}")
                print(f"     - Created count: {create_response.created_count}")
                if create_response.created_uris:
                    print(f"     - Created URIs: {create_response.created_uris}")
                    
        except VitalGraphClientError as e:
            print(f"   ✗ Error creating KGType: {e}")
        except Exception as e:
            print(f"   ✗ Unexpected error: {e}")
        
        # Test 5: Update KGType
        print("\n7. Testing Update KGType...")
        try:
            # Create updated KGType using VitalSigns with same URI
            updated_product_type = KGType()
            updated_product_type.URI = product_kgtype_uri  # Use same URI for update
            updated_product_type.kGModelVersion = "1.1"
            updated_product_type.kGTypeVersion = "1.1"
            updated_product_type.kGraphDescription = "Updated product entity type with enhanced features"
            
            print(f"   Updating Product KGType URI: {updated_product_type.URI}")
            
            # Convert to JSON-LD document
            update_data = kgtypes_to_jsonld_document([updated_product_type])
            
            if dry_run:
                # Log test data instead of making API call
                log_test_data("Update Product KGType", update_data, [updated_product_type])
            else:
                # Use typed client method to update KGType
                jsonld_doc = JsonLdDocument(data=update_data)
                update_response: KGTypeUpdateResponse = client.update_kgtypes(space_id, graph_id, jsonld_doc)
                print(f"   ✓ Update request completed")
                print(f"     - Message: {update_response.message}")
                if hasattr(update_response, 'updated_uri'):
                    print(f"     - Updated URI: {update_response.updated_uri}")
                    
        except VitalGraphClientError as e:
            print(f"   ✗ Error updating KGType: {e}")
        except Exception as e:
            print(f"   ✗ Unexpected error: {e}")
        
        # Test 8: Delete KGType by URI
        print("\n8. Testing Delete KGType by URI...")
        try:
            print(f"   Deleting Product KGType URI: {product_kgtype_uri}")
            
            if dry_run:
                print(f"   📝 Would delete KGType with URI: {product_kgtype_uri}")
                print(f"   📝 DELETE request would be sent to: {base_url}")
                print(f"   📝 Parameters: space_id={space_id}, graph_id={graph_id}, uri={product_kgtype_uri}")
            else:
                # Use typed client method to delete KGType
                delete_response: KGTypeDeleteResponse = client.kgtypes.delete_kgtypes(
                    space_id=space_id,
                    graph_id=graph_id,
                    uri=product_kgtype_uri
                )
                print(f"   ✓ Delete request completed")
                print(f"     - Message: {delete_response.message}")
                print(f"     - Deleted count: {delete_response.deleted_count}")
                if delete_response.deleted_uris:
                    # Handle potential list or single URI
                    if hasattr(delete_response.deleted_uris, '__iter__') and not isinstance(delete_response.deleted_uris, str):
                        try:
                            deleted_uris_list = list(delete_response.deleted_uris)
                            print(f"     - Deleted URIs: {deleted_uris_list}")
                        except Exception:
                            print(f"     - Deleted URIs: {delete_response.deleted_uris}")
                    else:
                        print(f"     - Deleted URIs: {delete_response.deleted_uris}")
                        
        except VitalGraphClientError as e:
            print(f"   ✗ Error deleting KGType: {e}")
        except Exception as e:
            print(f"   ✗ Unexpected error: {e}")
        
        # Test 9: Retrieve and Display All KGTypes as VitalSigns Objects
        print("\n9. Testing Retrieve All KGTypes and Convert to VitalSigns...")
        retrieved_kgtypes = []
        try:
            # Get all KGTypes from server using typed client method
            response: KGTypeListResponse = client.kgtypes.list_kgtypes(
                space_id=space_id,
                graph_id=graph_id,
                page_size=100,
                offset=0
            )
            
            # Check if we got KGTypes back
            if response.data:
                print(f"   ✓ Retrieved KGTypes from server")
                print(f"   Response data type: {type(response.data)}")
                
                # Log the full JsonLdDocument content for debugging
                try:
                    jsonld_dict = response.data.model_dump(by_alias=True)
                    import json
                    pretty_jsonld = json.dumps(jsonld_dict, indent=2, ensure_ascii=False)
                    print(f"   📋 Full JsonLdDocument content:")
                    print(f"   {pretty_jsonld}")
                except Exception as log_error:
                    print(f"   ⚠ Could not log JsonLdDocument: {log_error}")
                    print(f"   Raw response.data: {response.data}")
                
                # The response.data is a JsonLdDocument, convert to VitalSigns objects
                try:
                    # Convert JsonLdDocument to dict for processing (use by_alias=True for @context/@graph)
                    jsonld_dict = response.data.model_dump(by_alias=True)
                    print(f"   ✓ Extracted JSON-LD data with {len(jsonld_dict.get('@graph', []))} objects")
                    
                    # Convert JSON-LD to VitalSigns GraphObjects using the same utility as the server
                    from vitalgraph.utils.data_format_utils import jsonld_to_graphobjects
                    import asyncio
                    
                    # Run the async conversion
                    graph_objects = asyncio.run(jsonld_to_graphobjects(jsonld_dict))
                    retrieved_kgtypes = graph_objects
                    
                    print(f"   ✓ Converted to {len(retrieved_kgtypes)} VitalSigns GraphObjects")
                    
                    # Print summary
                    for i, kgtype in enumerate(retrieved_kgtypes):
                        print(f"     - KGType {i+1}: {kgtype.URI}")
                        print(f"       Type: {getattr(kgtype, 'vitaltype', 'N/A')}")
                        print(f"       Description: {getattr(kgtype, 'kGraphDescription', 'N/A')}")
                    
                except Exception as conversion_error:
                    print(f"   ✗ Error converting JSON-LD to VitalSigns: {conversion_error}")
                    retrieved_kgtypes = []
            else:
                print(f"   ⚠ No KGTypes found in response")
                print(f"   Response type: {type(response)}")
                print(f"   Response data: {getattr(response, 'data', 'No data attribute')}")
                print(f"   Response total_count: {getattr(response, 'total_count', 'No total_count')}")
                
        except Exception as e:
            print(f"   ✗ Error retrieving KGTypes: {e}")
            import traceback
            traceback.print_exc()

        # Test results summary
        print("\n" + "="*80)
        print("KGTypes Endpoint Testing Complete")
        print("="*80)
        
        # Pretty print all retrieved KGTypes as JSON
        if retrieved_kgtypes:
            print(f"\n📋 Retrieved KGTypes as VitalSigns GraphObjects ({len(retrieved_kgtypes)} total):")
            print("="*80)
            
            import json
            for i, kgtype in enumerate(retrieved_kgtypes):
                print(f"\n🔹 KGType {i+1}:")
                try:
                    # Convert VitalSigns object to JSON
                    kgtype_json_str = kgtype.to_json()
                    kgtype_json = json.loads(kgtype_json_str)
                    
                    # Pretty print the JSON
                    pretty_json = json.dumps(kgtype_json, indent=2, ensure_ascii=False)
                    print(pretty_json)
                    
                except Exception as e:
                    print(f"   ✗ Error converting KGType to JSON: {e}")
                    print(f"   Raw object: {kgtype}")
        else:
            print(f"\n📋 No KGTypes were retrieved to display.")
        
    except VitalGraphClientError as e:
        print(f"\n✗ VitalGraph client error: {e}")
        return False
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if not dry_run and client:
            try:
                client.close()
                print(f"\n✓ Client connection closed")
            except:
                pass
    
    return True


def main():
    """Main function to run the test."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test KGTypes endpoint with VitalSigns objects")
    parser.add_argument("--dry-run", action="store_true", 
                       help="Dry run mode - create test data but don't make API calls")
    parser.add_argument("--config", default="vitalgraphclient_config/vitalgraphclient-config.yaml",
                       help="Path to VitalGraph client config file")
    
    args = parser.parse_args()
    
    setup_logging()
    
    print(f"Using config: {args.config}")
    if args.dry_run:
        print("🔍 Running in DRY RUN mode - test data creation only")
    
    success = test_kgtypes_endpoint(args.config, dry_run=args.dry_run)
    
    if success:
        if args.dry_run:
            print("\n✓ KGTypes test data creation completed")
        else:
            print("\n✓ KGTypes endpoint test completed")
        sys.exit(0)
    else:
        if args.dry_run:
            print("\n❌ KGTypes test data creation failed!")
        else:
            print("\n❌ KGTypes endpoint test failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
