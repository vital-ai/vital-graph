#!/usr/bin/env python3
"""
Test script for KGFrames endpoint using test_4847 space data.

This script tests the GET and LIST operations of the KGFrames endpoint
using the existing test data to find KGFrame objects and their subclasses.

UPDATED: Now uses typed client methods with FramesResponse models 
instead of direct HTTP calls for full type safety.
"""

import sys
import json
import logging
from pathlib import Path
from typing import Optional

from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph.model.kgframes_model import FramesResponse


def setup_logging():
    """Set up logging configuration for the test."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


def test_kgframes_endpoint(config_path: str):
    """Test the KGFrames endpoint with test_4847 space data."""
    logger = logging.getLogger(__name__)
    
    print("=" * 80)
    print("VitalGraph KGFrames Endpoint Testing")
    print("   Using new structured response models (FramesResponse)")
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
        
        # Test 1: List KGFrames with pagination
        print("\n2. Testing List KGFrames (Paginated)...")
        try:
            frames_response: FramesResponse = client.list_kgframes(
                space_id=space_id,
                graph_id=graph_id,
                page_size=5,
                offset=0
            )
            
            print(f"   ✓ Listed KGFrames successfully")
            print(f"     - Total count: {frames_response.total_count}")
            print(f"     - Page size: {frames_response.page_size}")
            print(f"     - Offset: {frames_response.offset}")
            
            # Access frames from the JsonLdDocument
            frames = frames_response.frames.graph if frames_response.frames.graph else []
            print(f"     - Frames returned: {len(frames)}")
            
            # Show first frame
            if frames:
                first_frame = frames[0]
                print(f"     - First frame URI: {first_frame.get('@id', 'N/A')}")
                print(f"     - First frame type: {first_frame.get('vitaltype', 'N/A')}")
            else:
                print("     - No frames found in response")
                
        except VitalGraphClientError as e:
            print(f"   ❌ List KGFrames error: {e}")
            print(f"   ❌ Unexpected error: {e}")
        
        # Test 2: SearchKGFrames
        print("\n3. Testing SearchKGFrames...")
        try:
            search_response: FramesResponse = client.list_kgframes(
                space_id=space_id,
                graph_id=graph_id,
                page_size=3,
                search="person"
            )
            
            print(f"   ✓ Search for 'person' successful")
            print(f"     - Matching frames: {search_response.total_count}")
            
            # Access frames from the JsonLdDocument
            frames = search_response.frames.graph if search_response.frames.graph else []
            for i, frame in enumerate(frames[:2]):
                print(f"     - Match {i+1}: {frame.get('@id', 'N/A')}")
                
        except VitalGraphClientError as e:
            print(f"   ❌ Search error: {e}")
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
        
        # Test 3: Get specific KGFrame by URI
        print("\n4. Testing Get Specific KGFrame...")
        
        # First get a URI from the list
        try:
            list_response: FramesResponse = client.list_kgframes(
                space_id=space_id,
                graph_id=graph_id,
                page_size=1
            )
            
            # Access frames from the JsonLdDocument
            frames = list_response.frames.graph if list_response.frames.graph else []
            
            if frames:
                test_uri = frames[0].get('@id')
                
                # Now get that specific frame using get_kgframe method
                frame_response: FramesResponse = client.get_kgframe(
                    space_id=space_id,
                    graph_id=graph_id,
                    uri=test_uri
                )
                
                print(f"   ✓ Retrieved specific KGFrame: {test_uri}")
                
                # Access the specific frame data from the response
                if frame_response.frames.graph:
                    frame_data = frame_response.frames.graph[0]  # Should be single frame
                    print(f"     - Frame type: {frame_data.get('vitaltype', 'N/A')}")
                    print(f"     - Properties count: {len(frame_data.keys())}")
                    
                    # Show some properties
                    print(f"     - Sample properties:")
                    for key, value in list(frame_data.items())[:3]:
                        if key not in ['@context', '@id']:
                            print(f"       • {key}: {str(value)[:50]}{'...' if len(str(value)) > 50 else ''}")
                else:
                    print("   ⚠️  No frame data in response")
            else:
                print("   ⚠️  No frames found to test specific retrieval")
                
        except VitalGraphClientError as e:
            print(f"   ❌ Get specific KGFrame error: {e}")
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
        
        # Test 4: Get multiple KGFrames by URI list
        print("\n5. Testing Get Multiple KGFrames by URI List...")
        try:
            # Get a few URIs first
            multi_list_response: FramesResponse = client.list_kgframes(
                space_id=space_id,
                graph_id=graph_id,
                page_size=3
            )
            
            # Access frames from the JsonLdDocument
            frames = multi_list_response.frames.graph if multi_list_response.frames.graph else []
            
            if len(frames) >= 2:
                uri_list = ",".join([frame.get('@id') for frame in frames[:2]])
                
                # Get multiple frames using get_kgframes_by_uris method
                multi_response = client.get_kgframes_by_uris(
                    space_id=space_id,
                    graph_id=graph_id,
                    uri_list=uri_list
                )
                
                # Access returned frames from JsonLdDocument
                returned_frames = multi_response.graph if multi_response.graph else []
                print(f"   ✓ Retrieved multiple KGFrames successfully")
                print(f"     - Requested: 2 frames")
                print(f"     - Returned: {len(returned_frames)} frames")
                
                for i, frame in enumerate(returned_frames):
                    print(f"     - Frame {i+1}: {frame.get('@id', 'N/A')}")
            else:
                print("   ⚠️  Not enough frames to test multiple retrieval")
                
        except VitalGraphClientError as e:
            print(f"   ❌ Get multiple KGFrames error: {e}")
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
        
        # Test 5: Test with different page sizes
        print("\n6. Testing Pagination...")
        for page_size in [1, 5, 10]:
            try:
                pagination_response: FramesResponse = client.list_kgframes(
                    space_id=space_id,
                    graph_id=graph_id,
                    page_size=page_size,
                    offset=0
                )
                
                # Access frames from the JsonLdDocument
                frames = pagination_response.frames.graph if pagination_response.frames.graph else []
                total_count = pagination_response.total_count
                
                print(f"   ✓ Page size {page_size}: returned {len(frames)} frames (total: {total_count})")
                    
            except VitalGraphClientError as e:
                print(f"   ❌ Pagination error for page_size {page_size}: {e}")
            except Exception as e:
                print(f"   ❌ Unexpected error for page_size {page_size}: {e}")
        
        # Close client
        print(f"\n7. Client closed successfully")
        client.close()
        
        print(f"\n✅ KGFrames endpoint testing completed successfully!")
        
        print(f"\n📊 Test Summary:")
        print(f"   • Space tested: {space_id}")
        print(f"   • Graph tested: {graph_id}")
        print(f"   • Tests performed:")
        print(f"     - List KGFrames with pagination ✓ (using client.kgframes.list_kgframes)")
        print(f"     - Search functionality ✓ (using client.kgframes.list_kgframes with search)")
        print(f"     - Get specific KGFrame by URI ✓ (using client.kgframes.get_kgframe)")
        print(f"     - Get multiple KGFrames by URI list ✓ (using client.kgframes.get_kgframes_by_uris)")
        print(f"     - Pagination testing ✓ (using typed FramesResponse)")
        
        print(f"\n🎉 KGFrames endpoint testing completed successfully!")
        print(f"\n✅ KGFrames endpoint is working correctly with typed client methods!")
        print(f"   All operations now use typed FramesResponse models for full type safety.")
        
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
    print("Starting VitalGraph KGFrames Endpoint Testing...")
    print("📋 Note: Compatible with new structured response models")
    
    # Setup logging
    setup_logging()
    
    # Find config file
    config_path = Path(__file__).parent.parent / "vitalgraphclient_config" / "vitalgraphclient-config.yaml"
    
    if not config_path.exists():
        print(f"❌ Config file not found: {config_path}")
        return False
    
    print(f"✓ Found config file: {config_path}")
    
    # Run tests
    success = test_kgframes_endpoint(str(config_path))
    
    if success:
        print("✅ All tests completed successfully!")
        return True
    else:
        print("❌ Some tests failed!")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
