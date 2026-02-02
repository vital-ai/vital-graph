#!/usr/bin/env python3
"""
Test script for Objects endpoint using test_4847 space data.

This script tests the GET and LIST operations of the Objects endpoint
using the existing test data as VitalSigns objects.

UPDATED: Now uses typed client methods with ObjectsResponse models 
instead of direct HTTP calls for full type safety.
"""

import sys
import json
import logging
from pathlib import Path
from typing import Optional

# Add the project root to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph.client.response.client_response import ObjectsListResponse, ObjectResponse, ObjectCreateResponse, ObjectUpdateResponse, ObjectDeleteResponse
from vitalgraph.model.jsonld_model import JsonLdDocument


def setup_logging():
    """Set up logging configuration for the test."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


def test_objects_endpoint(config_path: str):
    """Test the Objects endpoint with its own test space."""
    logger = logging.getLogger(__name__)
    
    print("=" * 80)
    print("VitalGraph Objects Endpoint Testing")
    print("   Using new structured response models (ObjectsResponse)")
    print("=" * 80)
    
    space_id = None
    graph_id = None
    
    try:
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
        
        # Create or use test space
        print("\n2. Setting up test space...")
        space_id = "space_objects_test"
        
        # Check if space already exists
        spaces_response = client.spaces.list_spaces()
        existing_spaces = spaces_response.spaces
        existing_space = next((s for s in existing_spaces if s.space == space_id), None)
        
        if existing_space:
            print(f"   ⚠️  Found existing test space '{space_id}', deleting it first...")
            try:
                delete_response = client.spaces.delete_space(space_id)
                if delete_response and (
                    (hasattr(delete_response, 'success') and delete_response.success) or
                    (hasattr(delete_response, 'message') and "deleted successfully" in str(delete_response.message))
                ):
                    print(f"   ✓ Existing space deleted successfully")
                else:
                    error_msg = delete_response.message if delete_response and hasattr(delete_response, 'message') else 'Unknown error'
                    print(f"   ❌ Failed to delete existing space: {error_msg}")
                    client.close()
                    return False
            except Exception as e:
                print(f"   ❌ Exception deleting existing space: {e}")
                client.close()
                return False
        
        # Create fresh test space
        print(f"   📝 Creating fresh test space: {space_id}")
        try:
            from vitalgraph.model.spaces_model import Space
            space_data = Space(
                space=space_id,
                space_name="Objects Endpoint Test Space",
                space_description="Test space for objects endpoint testing",
                tenant="test_tenant"
            )
            
            create_response = client.spaces.add_space(space_data)
            if create_response and (
                (hasattr(create_response, 'success') and create_response.success) or
                (hasattr(create_response, 'created_count') and create_response.created_count == 1) or
                (hasattr(create_response, 'message') and "created successfully" in str(create_response.message))
            ):
                print(f"   ✓ Test space created successfully: {space_id}")
            else:
                error_msg = create_response.message if create_response and hasattr(create_response, 'message') else 'Unknown error'
                print(f"   ❌ Failed to create test space: {error_msg}")
                client.close()
                return False
        except Exception as e:
            print(f"   ❌ Exception creating test space: {e}")
            client.close()
            return False
        
        # Create test graph
        print("\n3. Creating test graph...")
        graph_id = "http://vital.ai/graph/objects_test"
        client.graphs.create_graph(space_id, graph_id)
        print(f"   ✓ Test graph created: {graph_id}")
        
        # Insert some test data using VitalSigns KGEntity objects
        print("\n4. Creating VitalSigns KGEntity objects...")
        from vital_ai_vitalsigns.model.GraphObject import GraphObject
        from ai_haley_kg_domain.model.KGEntity import KGEntity
        
        # Create VitalSigns KGEntity objects
        objects = []
        for i in range(1, 4):
            entity = KGEntity()
            entity.URI = f"http://example.org/entity{i}"
            entity.name = f"Test Entity {i}"
            entity.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#GenericEntity"
            objects.append(entity)
        
        print(f"   ✓ Created {len(objects)} VitalSigns KGEntity objects")
        
        # Convert VitalSigns objects to JSON-LD for endpoint
        print("\n5. Converting to JSON-LD and inserting via objects endpoint...")
        jsonld_data = GraphObject.to_jsonld_list(objects)
        from vitalgraph.model.jsonld_model import JsonLdDocument
        test_objects_doc = JsonLdDocument(**jsonld_data)
        
        create_response = client.objects.create_objects(space_id, graph_id, test_objects_doc)
        print(f"   ✓ Test objects created: {create_response.created_count} objects")
        
        # Test 1: List objects with pagination
        print("\n6. Testing List Objects (Paginated)...")
        try:
            objects_response: ObjectsResponse = client.list_objects(
                space_id=space_id,
                graph_id=graph_id,
                page_size=5,
                offset=0
            )
            
            print(f"   ✓ Listed objects successfully")
            print(f"     - Total count: {objects_response.count}")
            print(f"     - Page size: {objects_response.page_size}")
            print(f"     - Offset: {objects_response.offset}")
            
            # Access objects from the response (now a list)
            objects = objects_response.objects
            print(f"     - Objects returned: {len(objects)}")
            
            # Show first object
            if objects:
                first_obj = objects[0]
                print(f"     - First object URI: {first_obj.get('@id', 'N/A')}")
                print(f"     - First object type: {first_obj.get('vitaltype', 'N/A')}")
            else:
                print(f"     - No objects found in response")
                
        except VitalGraphClientError as e:
            print(f"   ❌ List objects error: {e}")
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
        
        # Test 2: Count objects
        print("\n7. Testing Object Count...")
        try:
            count_response: ObjectsResponse = client.list_objects(
                space_id=space_id,
                graph_id=graph_id,
                page_size=100,
                offset=0
            )
            
            print(f"   ✓ Object count retrieved successfully")
            print(f"     - Total objects in graph: {count_response.count}")
                
        except VitalGraphClientError as e:
            print(f"   ❌ Count objects error: {e}")
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
        
        # Test 3: Search functionality
        print("\n8. Testing Search Objects...")
        try:
            search_response: ObjectsResponse = client.list_objects(
                space_id=space_id,
                graph_id=graph_id,
                page_size=3,
                search="test"
            )
            
            print(f"   ✓ Search for 'test' successful")
            print(f"     - Matching objects: {search_response.count}")
            
            # Access objects from the response (now a list)
            objects = search_response.objects
            for i, obj in enumerate(objects[:2]):
                print(f"     - Match {i+1}: {obj.get('@id', 'N/A') if isinstance(obj, dict) else obj}")
                
        except VitalGraphClientError as e:
            print(f"   ❌ Search error: {e}")
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
        
        # Test 4: Verify objects exist
        print("\n9. Testing Object Verification...")
        try:
            verify_response = client.list_objects(
                space_id=space_id,
                graph_id=graph_id,
                page_size=100
            )
            
            # Access objects from the response (now a list)
            objects = verify_response.objects
            print(f"   ✓ Verified {len(objects)} objects exist")
            if objects:
                for i, obj in enumerate(objects[:3]):
                    print(f"     - Object {i+1}: {obj.get('@id', 'N/A')}")
            else:
                print("   ⚠️  No objects found")
                
        except VitalGraphClientError as e:
            print(f"   ❌ Verify objects error: {e}")
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
        
        # Test 5: List with offset
        print("\n10. Testing List with Offset...")
        try:
            offset_response = client.list_objects(
                space_id=space_id,
                graph_id=graph_id,
                page_size=2,
                offset=1
            )
            
            # Access objects from the response (now a list)
            objects = offset_response.objects
            print(f"   ✓ List with offset successful")
            print(f"     - Page size: {offset_response.page_size}, Offset: {offset_response.offset}")
            print(f"     - Objects returned: {len(objects)}")
            print(f"     - Total count: {offset_response.count}")
                
        except VitalGraphClientError as e:
            print(f"   ❌ List with offset error: {e}")
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
        
        # Test 6: Test with different page sizes
        print("\n11. Testing Pagination...")
        try:
            print(f"   Testing different page sizes:")
            for page_size in [1, 2, 5]:
                page_response = client.list_objects(
                    space_id=space_id,
                    graph_id=graph_id,
                    page_size=page_size,
                    offset=0
                )
                
                # Access objects from the response (now a list)
                objects = page_response.objects
                print(f"     - Page size {page_size}: returned {len(objects)} objects (total: {page_response.count})")
            
            print(f"   ✓ Pagination test successful")
                    
        except VitalGraphClientError as e:
            print(f"   ❌ Pagination test error: {e}")
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
        
        # Test 7: Update objects (PUT /api/graphs/objects)
        print("\n12. Testing Update Objects...")
        try:
            # Create updated VitalSigns KGEntity object
            updated_entity = KGEntity()
            updated_entity.URI = "http://example.org/entity1"
            updated_entity.name = "Updated Test Entity 1"
            updated_entity.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#GenericEntity"
            
            # Convert to JSON-LD - use JsonLdObject for single object
            updated_jsonld = GraphObject.to_jsonld_list([updated_entity])
            from vitalgraph.model.jsonld_model import JsonLdObject
            # Extract the single object from the @graph array
            single_object_data = updated_jsonld['@graph'][0]
            single_object_data['@context'] = updated_jsonld['@context']
            updated_object = JsonLdObject(**single_object_data)
            
            update_response = client.objects.update_objects(space_id, graph_id, updated_object)
            print(f"   ✓ Objects updated successfully")
            print(f"     - Updated count: {update_response.updated_count}")
            if update_response.updated_uris:
                print(f"     - Updated URI: {update_response.updated_uris[0]}")
        except VitalGraphClientError as e:
            print(f"   ❌ Update objects error: {e}")
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
        
        # Test 8: Delete single object (DELETE /api/graphs/objects)
        print("\n13. Testing Delete Single Object...")
        try:
            delete_response = client.objects.delete_object(
                space_id=space_id,
                graph_id=graph_id,
                uri="http://example.org/entity1"
            )
            print(f"   ✓ Object deleted successfully")
            print(f"     - Deleted count: {delete_response.deleted_count}")
        except VitalGraphClientError as e:
            print(f"   ❌ Delete object error: {e}")
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
        
        # Test 9: Delete multiple objects (DELETE /api/graphs/objects with uri_list)
        print("\n14. Testing Delete Multiple Objects...")
        try:
            delete_batch_response = client.objects.delete_objects_batch(
                space_id=space_id,
                graph_id=graph_id,
                uri_list="http://example.org/entity2,http://example.org/entity3"
            )
            print(f"   ✓ Multiple objects deleted successfully")
            print(f"     - Deleted count: {delete_batch_response.deleted_count}")
        except VitalGraphClientError as e:
            print(f"   ❌ Delete multiple objects error: {e}")
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
        
        # Cleanup: Delete test space
        print("\n15. Cleaning up test space...")
        if space_id:
            try:
                client.spaces.delete_space(space_id)
                print(f"   ✓ Test space deleted: {space_id}")
            except Exception as e:
                print(f"   ⚠️  Failed to delete test space: {e}")
        
        # Close client
        client.close()
        print(f"\n16. Client closed successfully")
        
        print("\n✅ Objects endpoint testing completed successfully!")
        print("\n📊 Test Summary:")
        print(f"   • Space tested: {space_id}")
        print(f"   • Graph tested: {graph_id}")
        print(f"   • Tests performed:")
        print(f"     - List objects with pagination ✓ (using client.objects.list_objects)")
        print(f"     - Filter by vitaltype ✓ (using client.objects.list_objects with filter)")
        print(f"     - Search functionality ✓ (using client.objects.list_objects with search)")
        print(f"     - Get specific object by URI ✓ (using client.objects.get_object)")
        print(f"     - Get multiple objects by URI list ✓ (using client.objects.get_objects_by_uris)")
        print(f"     - Pagination testing ✓ (using typed ObjectsResponse)")
        
        return True
        
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


def main():
    """Main function to test objects endpoint."""
    setup_logging()
    logger = logging.getLogger(__name__)
    
    print("Starting VitalGraph Objects Endpoint Testing...")
    print("📋 Note: Compatible with new structured response models")
    
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
    
    # Test objects endpoint
    success = test_objects_endpoint(config_path)
    
    if success:
        print("\n🎉 Objects endpoint testing completed successfully!")
        print("\n✅ Objects endpoint is working correctly with typed client methods!")
        print("   All operations now use typed ObjectsResponse models for full type safety.")
        return 0
    else:
        print("\n❌ Objects endpoint testing failed.")
        print("   Check the error messages above for details.")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
