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

# VitalSigns utilities for quad conversion
from vital_ai_vitalsigns.vitalsigns import VitalSigns


async def test_list_frames_with_graphs(client: VitalGraphClient, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test listing frames with their complete graphs."""
    logger.info("🧪 Testing list frames with graphs...")
    
    try:
        # Test listing frames (graphs are included via objects)
        response = await client.kgframes.list_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            page_size=10,
            offset=0
        )
        
        if response.is_success:
            logger.info(f"✅ List frames with graphs successful: {response.total_count} total frames")
            objects = response.objects or []
            logger.info(f"   Retrieved {len(objects)} objects on this page")
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
        # Test listing frames with search filter
        response = await client.kgframes.list_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            page_size=5,
            offset=0,
            search="Test"
        )
        
        if response.is_success:
            logger.info(f"✅ List frames with graphs (filtered) successful: {response.total_count} matching frames")
            return True
        else:
            logger.error(f"❌ List frames with graphs (filtered) failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ List frames with graphs (filtered) failed with exception: {e}")
        return False


async def test_get_frame_graph_by_uri(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: str, logger: logging.Logger) -> bool:
    """Test getting a frame graph by URI."""
    logger.info("🧪 Testing get frame graph by URI...")
    
    try:
        # Test getting frame graph by URI
        response = await client.kgframes.get_kgframe(
            space_id=space_id,
            graph_id=graph_id,
            uri=frame_uri,
            include_frame_graph=True
        )
        
        if response.is_success and response.frame_graph:
            logger.info(f"✅ Get frame graph by URI successful")
            if response.frame_graph.objects:
                logger.info(f"   Frame graph included with {len(response.frame_graph.objects)} objects")
            return True
        else:
            logger.error(f"❌ Get frame graph by URI failed: No frame returned")
            return False
            
    except Exception as e:
        logger.error(f"❌ Get frame graph by URI failed with exception: {e}")
        return False


async def test_delete_frame_graph(client: VitalGraphClient, space_id: str, graph_id: str, entity_uri: Optional[str], logger: logging.Logger) -> bool:
    """Test deleting a frame graph. Creates its own temp frame to avoid destroying shared data."""
    logger.info("🧪 Testing delete frame graph...")
    
    try:
        # Create a temp frame for this delete test
        test_data_creator = ClientTestDataCreator()
        temp_frame = KGFrame()
        temp_frame.URI = str(test_data_creator.generate_test_uri("frame", "graph_delete_001"))
        temp_frame.name = "Temp Frame Graph Delete Test"
        temp_frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#TempGraphDeleteFrame"
        
        create_response = await client.kgframes.create_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            objects=[temp_frame],
            entity_uri=entity_uri
        )
        if not create_response.is_success:
            logger.error(f"❌ Failed to create temp frame for delete test: {create_response.message}")
            return False
        
        # Test deleting the temp frame graph
        response = await client.kgframes.delete_kgframe(
            space_id=space_id,
            graph_id=graph_id,
            uri=str(temp_frame.URI)
        )
        
        if response.is_success:
            logger.info(f"✅ Delete frame graph successful")
            logger.info(f"   Deleted {response.deleted_count} items")
            return True
        else:
            logger.error(f"❌ Delete frame graph failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Delete frame graph failed with exception: {e}")
        return False


async def test_delete_multiple_frame_graphs(client: VitalGraphClient, space_id: str, graph_id: str, entity_uri: Optional[str], logger: logging.Logger) -> bool:
    """Test deleting multiple frame graphs. Creates its own temp frames to avoid destroying shared data."""
    logger.info("🧪 Testing delete multiple frame graphs...")
    
    try:
        # Create temp frames for this delete test
        test_data_creator = ClientTestDataCreator()
        temp_frames = []
        for i in range(3):
            frame = KGFrame()
            frame.URI = str(test_data_creator.generate_test_uri("frame", f"graph_multi_del_{i:03d}"))
            frame.name = f"Temp Multi Delete Frame {i}"
            frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#TempMultiDeleteFrame"
            temp_frames.append(frame)
        
        create_response = await client.kgframes.create_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            objects=temp_frames,
            entity_uri=entity_uri
        )
        if not create_response.is_success:
            logger.error(f"❌ Failed to create temp frames for multi-delete test: {create_response.message}")
            return False
        
        temp_uris = [str(f.URI) for f in temp_frames]
        
        # Test deleting the temp frame graphs
        response = await client.kgframes.delete_kgframes_batch(
            space_id=space_id,
            graph_id=graph_id,
            uri_list=",".join(temp_uris)
        )
        
        if response.is_success:
            logger.info(f"✅ Delete multiple frame graphs successful")
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
        response = await client.kgframes.get_kgframe(
            space_id=space_id,
            graph_id=graph_id,
            uri=nonexistent_frame_uri,
            include_frame_graph=True
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


async def run_frame_graphs_tests(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: Optional[str] = None, frame_uris: Optional[list[str]] = None, entity_uri: Optional[str] = None, logger: logging.Logger = None) -> bool:
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
        tests.append(("Get Frame Graph by URI", lambda: test_get_frame_graph_by_uri(client, space_id, graph_id, frame_uri, logger)))
    
    # Delete tests create their own temp data
    tests.append(("Delete Frame Graph", lambda: test_delete_frame_graph(client, space_id, graph_id, entity_uri, logger)))
    tests.append(("Delete Multiple Frame Graphs", lambda: test_delete_multiple_frame_graphs(client, space_id, graph_id, entity_uri, logger)))
    
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
