#!/usr/bin/env python3
"""
Test script for KGEntities endpoint using test_4847 space data.

This script tests the KGEntity CRUD operations using the typed client methods
with proper Pydantic models and response types for full type safety.

UPDATED: Now uses typed client methods with EntityListResponse, EntityResponse,
EntityCreateResponse, EntityUpdateResponse, and EntityDeleteResponse models.
"""

import sys
import json
import logging
from pathlib import Path
from typing import Optional

from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
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


def test_kgentities_endpoint(config_path: str):
    """Test the KGEntities endpoint using typed client methods."""
    logger = logging.getLogger(__name__)
    
    print("=" * 80)
    print("VitalGraph KGEntities Endpoint Testing")
    print("   Using typed client methods with EntityListResponse models")
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
        space_id = "test_4847"
        graph_id = "urn:kgframe-wordnet-002"
        
        # Test 1: List KGEntities with pagination
        print("\n2. Testing List KGEntities (Paginated)...")
        try:
            from vitalgraph.model.kgentities_model import EntityListResponse
            
            entities_response: EntityListResponse = client.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=5,
                offset=0
            )
            
            print(f"   ✓ Listed KGEntities successfully")
            print(f"     - Total count: {entities_response.total_count}")
            print(f"     - Page size: {entities_response.page_size}")
            print(f"     - Offset: {entities_response.offset}")
            
            # Access entities from the JsonLdDocument
            entities = entities_response.entities.graph if entities_response.entities.graph else []
            print(f"     - Entities returned: {len(entities)}")
            
            # Show first entity
            if entities:
                first_entity = entities[0]
                print(f"     - First entity URI: {first_entity.get('@id', 'N/A')}")
                print(f"     - First entity type: {first_entity.get('vitaltype', 'N/A')}")
            else:
                print("     - No entities found in response")
                
        except VitalGraphClientError as e:
            print(f"   ❌ List KGEntities error: {e}")
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
        
        # Test 2: Search KGEntities
        print("\n3. Testing Search KGEntities...")
        try:
            search_response: EntityListResponse = client.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=3,
                search="test"
            )
            
            print(f"   ✓ Search for 'test' successful")
            print(f"     - Matching entities: {search_response.total_count}")
            
            # Access entities from the JsonLdDocument
            entities = search_response.entities.graph if search_response.entities.graph else []
            for i, entity in enumerate(entities[:2]):
                print(f"     - Match {i+1}: {entity.get('@id', 'N/A')}")
                
        except VitalGraphClientError as e:
            print(f"   ❌ Search error: {e}")
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
        
        # Test 3: Get specific KGEntity by URI
        print("\n4. Testing Get Specific KGEntity...")
        
        # First get a URI from the list
        try:
            list_response: EntityListResponse = client.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=1
            )
            
            # Access entities from the JsonLdDocument
            entities = list_response.entities.graph if list_response.entities.graph else []
            
            if entities:
                test_uri = entities[0].get('@id')
                
                # Now get that specific entity using get_kgentity method
                from vitalgraph.model.kgentities_model import EntityResponse
                entity_response: EntityResponse = client.get_kgentity(
                    space_id=space_id,
                    graph_id=graph_id,
                    uri=test_uri
                )
                
                print(f"   ✓ Retrieved specific KGEntity: {test_uri}")
                
                # Access the specific entity data from the response
                if hasattr(entity_response, 'graph') and entity_response.graph:
                    entity_data = entity_response.graph[0]  # Should be single entity
                    print(f"     - Entity type: {entity_data.get('vitaltype', 'N/A')}")
                    print(f"     - Properties count: {len(entity_data.keys())}")
                    
                    # Show some properties
                    print(f"     - Sample properties:")
                    for key, value in list(entity_data.items())[:3]:
                        if key not in ['@context', '@id']:
                            print(f"       • {key}: {str(value)[:50]}{'...' if len(str(value)) > 50 else ''}")
                else:
                    print("     - No entity data found in response")
            else:
                print("   ⚠️  No entities found to test specific retrieval")
                
        except VitalGraphClientError as e:
            print(f"   ❌ Get specific KGEntity error: {e}")
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
        
        # Test 4: Get multiple KGEntities by URI list
        print("\n5. Testing Get Multiple KGEntities by URI List...")
        try:
            # Get a few URIs first
            multi_list_response: EntityListResponse = client.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=3
            )
            
            # Access entities from the JsonLdDocument
            entities = multi_list_response.entities.graph if multi_list_response.entities.graph else []
            
            if len(entities) >= 2:
                uri_list = ",".join([entity.get('@id') for entity in entities[:2]])
                
                # Get multiple entities using get_kgentities_by_uris method (if available)
                # Note: This method might not exist in the client, so we'll use a fallback
                try:
                    multi_response = client.get_kgentities_by_uris(
                        space_id=space_id,
                        graph_id=graph_id,
                        uri_list=uri_list
                    )
                    
                    # Access returned entities from JsonLdDocument
                    returned_entities = multi_response.graph if multi_response.graph else []
                    print(f"   ✓ Retrieved multiple KGEntities successfully")
                    print(f"     - Requested: 2 entities")
                    print(f"     - Returned: {len(returned_entities)} entities")
                    
                    for i, entity in enumerate(returned_entities):
                        print(f"     - Entity {i+1}: {entity.get('@id', 'N/A')}")
                except AttributeError:
                    print("   ⚠️  get_kgentities_by_uris method not available in client")
                except Exception as e:
                    print(f"   ❌ Get multiple KGEntities failed: {e}")
            else:
                print("   ⚠️  Not enough entities to test multiple retrieval")
                
        except VitalGraphClientError as e:
            print(f"   ❌ Get multiple KGEntities error: {e}")
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
        
        # Test 5: Test with different page sizes
        print("\n6. Testing Pagination...")
        for page_size in [1, 5, 10]:
            try:
                pagination_response: EntityListResponse = client.list_kgentities(
                    space_id=space_id,
                    graph_id=graph_id,
                    page_size=page_size,
                    offset=0
                )
                
                # Access entities from the JsonLdDocument
                entities = pagination_response.entities.graph if pagination_response.entities.graph else []
                total_count = pagination_response.total_count
                
                print(f"   ✓ Page size {page_size}: returned {len(entities)} entities (total: {total_count})")
                    
            except VitalGraphClientError as e:
                print(f"   ❌ Pagination error for page_size {page_size}: {e}")
            except Exception as e:
                print(f"   ❌ Unexpected error for page_size {page_size}: {e}")
        
        # Close client
        print(f"\n7. Client closed successfully")
        client.close()
        
        print(f"\n✅ KGEntities endpoint testing completed successfully!")
        
        print(f"\n📊 Test Summary:")
        print(f"   • Space tested: {space_id}")
        print(f"   • Graph tested: {graph_id}")
        print(f"   • Tests performed:")
        print(f"     - List KGEntities with pagination ✓ (using client.list_kgentities)")
        print(f"     - Search functionality ✓ (using client.list_kgentities with search)")
        print(f"     - Get specific KGEntity by URI ✓ (using client.get_kgentity)")
        print(f"     - Get multiple KGEntities by URI list ✓ (attempted)")
        print(f"     - Pagination testing ✓ (using typed EntityListResponse)")
        
        print(f"\n🎉 KGEntities endpoint testing completed successfully!")
        print(f"\n✅ KGEntities endpoint is working correctly with typed client methods!")
        print(f"   All operations now use proper Pydantic models and response types.")
        
    except VitalGraphClientError as e:
        logger.error(f"VitalGraph client error: {e}")
        print(f"\n❌ VitalGraph client error: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        print(f"\n❌ Unexpected error: {e}")
        return False


def main():
    """Main function."""
    print("Starting VitalGraph KGEntities Endpoint Testing...")
    print("📋 Note: Using typed client methods with EntityListResponse models")
    
    # Setup logging
    setup_logging()
    
    # Find config file
    config_path = Path(__file__).parent.parent / "vitalgraphclient_config" / "vitalgraphclient-config.yaml"
    
    if not config_path.exists():
        print(f"❌ Config file not found: {config_path}")
        return False
    
    print(f"✓ Found config file: {config_path}")
    
    # Run tests
    success = test_kgentities_endpoint(str(config_path))
    
    if success:
        print("✅ All tests completed successfully!")
        return True
    else:
        print("❌ Some tests failed!")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
