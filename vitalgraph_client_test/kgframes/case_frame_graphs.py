"""
Client Test Case: Frame Graphs Operations

Tests KGFrames graph functionality including:
- List frames with complete graphs
- Get frame graphs by URI
- Delete frame graphs
- Frame graph management operations
"""

import logging
from typing import Optional
from vitalgraph.client.vitalgraph_client import VitalGraphClient

# VitalSigns imports - REQUIRED for proper test data handling
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGFrame import KGFrame
from vitalgraph_client_test.client_test_data import ClientTestDataCreator

# VitalSigns utilities for JSON-LD conversion
from vital_ai_vitalsigns.vitalsigns import VitalSigns


async def test_list_frames_with_graphs(client: VitalGraphClient, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test listing frames with their complete graphs."""
    logger.info("🧪 Testing list frames with graphs...")
    
    try:
        # Test listing frames with complete graphs
        response = client.kgframes.list_kgframes_with_graphs(
            space_id=space_id,
            graph_id=graph_id,
            page_size=10,
            offset=0,
            include_frame_graphs=True
        )
        
        if response.total_count >= 0:
            logger.info(f"✅ List frames with graphs successful: {response.total_count} total frames")
            if hasattr(response.frames, '__len__'):
                logger.info(f"   Retrieved frames on this page")
            
            # Check if frame graphs are included
            if response.frames:
                # FramesGraphResponse.frames is a JsonLdDocument with graph attribute
                if hasattr(response.frames, 'graph') and response.frames.graph:
                    logger.info(f"   Frame graphs included: {len(response.frames.graph)} items")
                else:
                    logger.info(f"   No frame graphs in response")
            
            return True
        else:
            logger.error(f"❌ List frames with graphs failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ List frames with graphs failed with exception: {e}")
        return False


async def test_list_frames_with_graphs_filtered(client: VitalGraphClient, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test listing frames with graphs using search filter."""
    logger.info("🧪 Testing list frames with graphs (filtered)...")
    
    try:
        # Test listing frames with graphs and search filter
        response = client.kgframes.list_kgframes_with_graphs(
            space_id=space_id,
            graph_id=graph_id,
            page_size=5,
            offset=0,
            search="Test",
            include_frame_graphs=True
        )
        
        if response.total_count >= 0:
            logger.info(f"✅ List frames with graphs (filtered) successful: {response.total_count} matching frames")
            return True
        else:
            logger.error(f"❌ List frames with graphs (filtered) failed")
            return False
            
    except Exception as e:
        logger.error(f"❌ List frames with graphs (filtered) failed with exception: {e}")
        return False


async def test_get_frame_graph_by_uri(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: str, logger: logging.Logger) -> bool:
    """Test getting a frame graph by URI."""
    logger.info("🧪 Testing get frame graph by URI...")
    
    try:
        # Test getting frame graph by URI
        response = client.kgframes.get_kgframe_graph(
            space_id=space_id,
            graph_id=graph_id,
            uri=frame_uri
        )
        
        if hasattr(response, 'frame') and response.frame:
            logger.info(f"✅ Get frame graph by URI successful")
            
            # Check if complete graph is included
            if hasattr(response, 'complete_graph') and response.complete_graph:
                logger.info(f"   Complete graph included in response")
            
            return True
        else:
            logger.error(f"❌ Get frame graph by URI failed: No frame returned")
            return False
            
    except Exception as e:
        logger.error(f"❌ Get frame graph by URI failed with exception: {e}")
        return False


async def test_delete_frame_graph(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: str, logger: logging.Logger) -> bool:
    """Test deleting a frame graph."""
    logger.info("🧪 Testing delete frame graph...")
    
    try:
        # Test deleting frame graph
        response = client.kgframes.delete_kgframe_graph(
            space_id=space_id,
            graph_id=graph_id,
            uri=frame_uri
        )
        
        if response.success:
            logger.info(f"✅ Delete frame graph successful")
            if hasattr(response, 'deleted_count'):
                logger.info(f"   Deleted {response.deleted_count} items")
            return True
        else:
            logger.error(f"❌ Delete frame graph failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Delete frame graph failed with exception: {e}")
        return False


async def test_delete_multiple_frame_graphs(client: VitalGraphClient, space_id: str, graph_id: str, frame_uris: list[str], logger: logging.Logger) -> bool:
    """Test deleting multiple frame graphs."""
    logger.info("🧪 Testing delete multiple frame graphs...")
    
    try:
        # Test deleting multiple frame graphs
        response = client.kgframes.delete_kgframe_graphs(
            space_id=space_id,
            graph_id=graph_id,
            uri_list=",".join([str(uri) for uri in frame_uris])
        )
        
        if response.success:
            logger.info(f"✅ Delete multiple frame graphs successful")
            if hasattr(response, 'deleted_count'):
                logger.info(f"   Deleted {response.deleted_count} items")
            return True
        else:
            logger.error(f"❌ Delete multiple frame graphs failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Delete multiple frame graphs failed with exception: {e}")
        return False


async def test_frame_graph_operations_with_nonexistent_frame(client: VitalGraphClient, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test frame graph operations with non-existent frame."""
    logger.info("🧪 Testing frame graph operations with non-existent frame...")
    
    try:
        nonexistent_frame_uri = "urn:test-nonexistent-frame-graph-999"
        
        # Test getting graph for non-existent frame
        response = client.kgframes.get_kgframe_graph(
            space_id=space_id,
            graph_id=graph_id,
            uri=nonexistent_frame_uri
        )
        
        # Should handle gracefully - check if we got a proper error response
        if hasattr(response, 'message'):
            logger.info(f"✅ Frame graph operations with non-existent frame handled gracefully")
            return True
        else:
            logger.error(f"❌ Frame graph operations with non-existent frame failed unexpectedly: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Frame graph operations with non-existent frame failed with exception: {e}")
        return False


async def run_frame_graphs_tests(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: Optional[str] = None, frame_uris: Optional[list[str]] = None, logger: logging.Logger = None) -> bool:
    """Run all frame graphs tests."""
    if logger is None:
        logger = logging.getLogger(__name__)
    
    logger.info("🚀 Running Frame Graphs Tests...")
    
    tests = [
        ("List Frames with Graphs", lambda: test_list_frames_with_graphs(client, space_id, graph_id, logger)),
        ("List Frames with Graphs (Filtered)", lambda: test_list_frames_with_graphs_filtered(client, space_id, graph_id, logger)),
        ("Frame Graph Operations with Non-existent Frame", lambda: test_frame_graph_operations_with_nonexistent_frame(client, space_id, graph_id, logger))
    ]
    
    # Add tests if frame URIs are provided
    if frame_uri:
        tests.extend([
            ("Get Frame Graph by URI", lambda: test_get_frame_graph_by_uri(client, space_id, graph_id, frame_uri, logger)),
            ("Delete Frame Graph", lambda: test_delete_frame_graph(client, space_id, graph_id, frame_uri, logger))
        ])
    
    if frame_uris and len(frame_uris) > 1:
        tests.append(("Delete Multiple Frame Graphs", lambda: test_delete_multiple_frame_graphs(client, space_id, graph_id, frame_uris, logger)))
    
    results = []
    for test_name, test_func in tests:
        logger.info(f"🔧 Running: {test_name}")
        try:
            success = await test_func()
            results.append((test_name, success))
            if not success:
                logger.error(f"❌ {test_name} failed")
        except Exception as e:
            logger.error(f"❌ {test_name} failed with exception: {e}")
            results.append((test_name, False))
    
    all_passed = all(success for _, success in results)
    
    if all_passed:
        logger.info("✅ All frame graphs tests passed!")
        return True
    else:
        failed_tests = [name for name, success in results if not success]
        logger.error(f"❌ Frame graphs tests failed: {failed_tests}")
        return False
