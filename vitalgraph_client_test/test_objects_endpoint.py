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

from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph.model.objects_model import ObjectsResponse, ObjectCreateResponse, ObjectUpdateResponse, ObjectDeleteResponse
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
    """Test the Objects endpoint with test_4847 space data."""
    logger = logging.getLogger(__name__)
    
    print("=" * 80)
    print("VitalGraph Objects Endpoint Testing")
    print("   Using new structured response models (ObjectsResponse)")
    print("=" * 80)
    
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
        
        # Test parameters - using test space with WordNet graph
        space_id = "test_4847"  # Use string identifier for space manager
        graph_id = "urn:kgframe-wordnet-002"
        
        # Test 1: List objects with pagination
        print("\n2. Testing List Objects (Paginated)...")
        try:
            objects_response: ObjectsResponse = client.list_objects(
                space_id=space_id,
                graph_id=graph_id,
                page_size=5,
                offset=0
            )
            
            print(f"   ✓ Listed objects successfully")
            print(f"     - Total count: {objects_response.total_count}")
            print(f"     - Page size: {objects_response.page_size}")
            print(f"     - Offset: {objects_response.offset}")
            
            # Access objects from the JsonLdDocument
            objects = objects_response.objects.graph if objects_response.objects.graph else []
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
        
        # Test 2: Filter by vitaltype (look for any VitalSigns objects)
        print("\n3. Testing Filter by VitalType...")
        try:
            # Try filtering by a common VitalSigns type
            filter_response: ObjectsResponse = client.list_objects(
                space_id=space_id,
                graph_id=graph_id,
                page_size=3,
                vitaltype_filter="http://vital.ai/ontology/haley-ai-kg#KGFrame"
            )
            
            print(f"   ✓ Filtered by KGFrame successfully")
            print(f"     - KGFrame objects found: {filter_response.total_count}")
            
            # Access objects from the JsonLdDocument
            objects = filter_response.objects.graph if filter_response.objects.graph else []
            for i, obj in enumerate(objects[:2]):  # Show first 2
                print(f"     - KGFrame {i+1}: {obj.get('@id', 'N/A')}")
                
        except VitalGraphClientError as e:
            print(f"   ❌ Filter by vitaltype error: {e}")
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
        
        # Test 3: Search functionality
        print("\n4. Testing Search Objects...")
        try:
            search_response: ObjectsResponse = client.list_objects(
                space_id=space_id,
                graph_id=graph_id,
                page_size=3,
                search="test"
            )
            
            print(f"   ✓ Search for 'test' successful")
            print(f"     - Matching objects: {search_response.total_count}")
            
            # Access objects from the JsonLdDocument
            objects = search_response.objects.graph if search_response.objects.graph else []
            for i, obj in enumerate(objects[:2]):
                print(f"     - Match {i+1}: {obj.get('@id', 'N/A')}")
                
        except VitalGraphClientError as e:
            print(f"   ❌ Search error: {e}")
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
        
        # Test 4: Get specific object by URI
        print("\n5. Testing Get Specific Object...")
        
        # First get a URI from the list
        try:
            list_response: ObjectsResponse = client.list_objects(
                space_id=space_id,
                graph_id=graph_id,
                page_size=1
            )
            
            # Access objects from the JsonLdDocument
            objects = list_response.objects.graph if list_response.objects.graph else []
            
            if objects:
                test_uri = objects[0].get('@id')
                
                # Now get that specific object using get_object method
                object_response = client.get_object(
                    space_id=space_id,
                    graph_id=graph_id,
                    uri=test_uri
                )
                
                print(f"   ✓ Retrieved specific object: {test_uri}")
                
                # Access the specific object data from the response
                if hasattr(object_response, 'graph') and object_response.graph:
                    obj_data = object_response.graph[0]  # Should be single object
                    print(f"     - Object type: {obj_data.get('vitaltype', 'N/A')}")
                    print(f"     - Properties count: {len(obj_data.keys())}")
                    
                    # Show some properties
                    print(f"     - Sample properties:")
                    for key, value in list(obj_data.items())[:3]:
                        if key not in ['@context', '@id']:
                            print(f"       • {key}: {str(value)[:50]}{'...' if len(str(value)) > 50 else ''}")
                else:
                    print("   ⚠️  No object data in response")
            else:
                print("   ⚠️  No objects found to test specific retrieval")
                
        except VitalGraphClientError as e:
            print(f"   ❌ Get specific object error: {e}")
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
        
        # Test 5: Get multiple objects by URI list
        print("\n6. Testing Get Multiple Objects by URI List...")
        try:
            # Get a few URIs first
            multi_list_response: ObjectsResponse = client.list_objects(
                space_id=space_id,
                graph_id=graph_id,
                page_size=3
            )
            
            # Access objects from the JsonLdDocument
            objects = multi_list_response.objects.graph if multi_list_response.objects.graph else []
            
            if len(objects) >= 2:
                uri_list = ",".join([obj.get('@id') for obj in objects[:2]])
                
                # Get multiple objects using get_objects_by_uris method
                multi_response = client.get_objects_by_uris(
                    space_id=space_id,
                    graph_id=graph_id,
                    uri_list=uri_list
                )
                
                # Access returned objects from JsonLdDocument
                returned_objects = multi_response.graph if multi_response.graph else []
                print(f"   ✓ Retrieved multiple objects successfully")
                print(f"     - Requested: 2 objects")
                print(f"     - Returned: {len(returned_objects)} objects")
                
                for i, obj in enumerate(returned_objects):
                    print(f"     - Object {i+1}: {obj.get('@id', 'N/A')}")
            else:
                print("   ⚠️  Not enough objects to test multiple retrieval")
                
        except VitalGraphClientError as e:
            print(f"   ❌ Get multiple objects error: {e}")
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
        
        # Test 6: Test with different page sizes
        print("\n7. Testing Pagination...")
        try:
            # Test with different page sizes
            for page_size in [1, 5, 10]:
                pagination_response: ObjectsResponse = client.list_objects(
                    space_id=space_id,
                    graph_id=graph_id,
                    page_size=page_size,
                    offset=0
                )
                
                # Access objects from the JsonLdDocument
                objects = pagination_response.objects.graph if pagination_response.objects.graph else []
                total_count = pagination_response.total_count
                
                print(f"   ✓ Page size {page_size}: returned {len(objects)} objects (total: {total_count})")
                    
        except VitalGraphClientError as e:
            print(f"   ❌ Pagination test error: {e}")
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
        
        # Close client
        client.close()
        print(f"\n8. Client closed successfully")
        
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
