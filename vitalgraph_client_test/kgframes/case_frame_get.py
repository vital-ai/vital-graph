"""
Client Test Case: Frame Retrieval Operations

Tests KGFrames retrieval functionality including:
- Get single frame by URI
- Get frame with complete graph
- List frames with pagination
- List frames with filtering
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


async def test_get_frame_by_uri(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: str, logger: logging.Logger) -> bool:
    """Test getting a single frame by URI."""
    logger.info("🧪 Testing get frame by URI...")
    
    try:
        # Test basic frame retrieval
        response = client.kgframes.get_kgframe(
            space_id=space_id,
            graph_id=graph_id,
            uri=frame_uri
        )
        
        if response.success and response.frame:
            # JsonLdObject is a Pydantic model, access id attribute directly
            frame_id = getattr(response.frame, 'id', 'Unknown URI')
            logger.info(f"✅ Get frame by URI successful: {frame_id}")
            return True
        else:
            logger.error(f"❌ Get frame by URI failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Get frame by URI failed with exception: {e}")
        return False


async def test_get_frame_with_complete_graph(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: str, logger: logging.Logger) -> bool:
    """Test getting a frame with complete graph."""
    logger.info("🧪 Testing get frame with complete graph...")
    
    try:
        # Test frame retrieval with complete graph
        response = client.kgframes.get_kgframe(
            space_id=space_id,
            graph_id=graph_id,
            uri=frame_uri,
            include_frame_graph=True
        )
        
        if response.success and response.frame:
            logger.info(f"✅ Get frame with complete graph successful")
            if response.complete_graph:
                # complete_graph is a JsonLdDocument object, access graph attribute
                graph_items = response.complete_graph.graph if hasattr(response.complete_graph, 'graph') else []
                logger.info(f"   Complete graph included with {len(graph_items)} components")
            return True
        else:
            logger.error(f"❌ Get frame with complete graph failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Get frame with complete graph failed with exception: {e}")
        return False


async def test_list_frames_basic(client: VitalGraphClient, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test basic frame listing with pagination."""
    logger.info("🧪 Testing basic frame listing...")
    
    try:
        # Test basic frame listing
        response = client.kgframes.list_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            page_size=10,
            offset=0
        )
        
        if response.success:
            logger.info(f"✅ Basic frame listing successful: {response.total_count} total frames")
            logger.info(f"   Retrieved {len(response.frames)} frames on this page")
            return True
        else:
            logger.error(f"❌ Basic frame listing failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Basic frame listing failed with exception: {e}")
        return False


async def test_list_frames_with_entity_filter(client: VitalGraphClient, space_id: str, graph_id: str, entity_uri: str, logger: logging.Logger) -> bool:
    """Test frame listing with entity URI filter."""
    logger.info("🧪 Testing frame listing with entity filter...")
    
    try:
        # Test frame listing with entity filter
        response = client.kgframes.list_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            page_size=10,
            offset=0,
            entity_uri=entity_uri
        )
        
        if response.success:
            logger.info(f"✅ Frame listing with entity filter successful: {response.total_count} frames for entity")
            return True
        else:
            logger.error(f"❌ Frame listing with entity filter failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Frame listing with entity filter failed with exception: {e}")
        return False


async def test_list_frames_with_parent_filter(client: VitalGraphClient, space_id: str, graph_id: str, parent_uri: str, logger: logging.Logger) -> bool:
    """Test frame listing with parent URI filter."""
    logger.info("🧪 Testing frame listing with parent filter...")
    
    try:
        # Test frame listing with parent filter
        response = client.kgframes.list_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            page_size=10,
            offset=0,
            parent_uri=parent_uri
        )
        
        if response.success:
            logger.info(f"✅ Frame listing with parent filter successful: {response.total_count} child frames")
            return True
        else:
            logger.error(f"❌ Frame listing with parent filter failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Frame listing with parent filter failed with exception: {e}")
        return False


async def test_list_frames_with_search(client: VitalGraphClient, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test frame listing with search term."""
    logger.info("🧪 Testing frame listing with search...")
    
    try:
        # Test frame listing with search
        response = client.kgframes.list_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            page_size=10,
            offset=0,
            search="Test"
        )
        
        if response.success:
            logger.info(f"✅ Frame listing with search successful: {response.total_count} matching frames")
            return True
        else:
            logger.error(f"❌ Frame listing with search failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Frame listing with search failed with exception: {e}")
        return False


async def run_frame_get_tests(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: Optional[str] = None, entity_uri: Optional[str] = None, parent_uri: Optional[str] = None, logger: logging.Logger = None) -> bool:
    """Run all frame retrieval tests."""
    if logger is None:
        logger = logging.getLogger(__name__)
    
    logger.info("🚀 Running Frame Retrieval Tests...")
    
    tests = [
        ("Basic Frame Listing", lambda: test_list_frames_basic(client, space_id, graph_id, logger)),
        ("Frame Listing with Search", lambda: test_list_frames_with_search(client, space_id, graph_id, logger))
    ]
    
    # Add optional tests if URIs are provided
    if frame_uri:
        tests.extend([
            ("Get Frame by URI", lambda: test_get_frame_by_uri(client, space_id, graph_id, frame_uri, logger)),
            ("Get Frame with Complete Graph", lambda: test_get_frame_with_complete_graph(client, space_id, graph_id, frame_uri, logger))
        ])
    
    if entity_uri:
        tests.append(("Frame Listing with Entity Filter", lambda: test_list_frames_with_entity_filter(client, space_id, graph_id, entity_uri, logger)))
    
    if parent_uri:
        tests.append(("Frame Listing with Parent Filter", lambda: test_list_frames_with_parent_filter(client, space_id, graph_id, parent_uri, logger)))
    
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
        logger.info("✅ All frame retrieval tests passed!")
        return True
    else:
        failed_tests = [name for name, success in results if not success]
        logger.error(f"❌ Frame retrieval tests failed: {failed_tests}")
        return False
