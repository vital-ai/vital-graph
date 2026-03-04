"""
Client Test Case: Frame Deletion Operations

Tests KGFrames deletion functionality including:
- Delete single frame by URI
- Delete multiple frames by URI list
- Delete frames with cascading effects
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


async def test_delete_single_frame(client: VitalGraphClient, space_id: str, graph_id: str, entity_uri: Optional[str], logger: logging.Logger) -> bool:
    """Test deleting a single frame by URI. Creates its own temp frame to avoid destroying shared data."""
    logger.info("🧪 Testing single frame deletion...")
    
    try:
        # Create a temp frame for this delete test
        test_data_creator = ClientTestDataCreator()
        temp_frame = KGFrame()
        temp_frame.URI = str(test_data_creator.generate_test_uri("frame", "single_delete_001"))
        temp_frame.name = "Temp Single Delete Frame"
        temp_frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#TempDeleteFrame"
        
        create_response = await client.kgframes.create_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            objects=[temp_frame],
            entity_uri=entity_uri
        )
        if not create_response.is_success:
            logger.error(f"❌ Failed to create temp frame for single delete test: {create_response.message}")
            return False
        
        # Test single frame deletion
        response = await client.kgframes.delete_kgframe(
            space_id=space_id,
            graph_id=graph_id,
            uri=str(temp_frame.URI)
        )
        
        if response.is_success and response.deleted_count > 0:
            logger.info(f"✅ Single frame deletion successful: {response.deleted_count} frames deleted")
            return True
        else:
            logger.error(f"❌ Single frame deletion failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Single frame deletion failed with exception: {e}")
        return False


async def test_delete_multiple_frames(client: VitalGraphClient, space_id: str, graph_id: str, entity_uri: Optional[str], logger: logging.Logger) -> bool:
    """Test deleting multiple frames by URI list. Creates its own temp frames to avoid destroying shared data."""
    logger.info("🧪 Testing multiple frame deletion...")
    
    try:
        # Create temp frames for this delete test
        test_data_creator = ClientTestDataCreator()
        temp_frames = []
        for i in range(3):
            frame = KGFrame()
            frame.URI = str(test_data_creator.generate_test_uri("frame", f"multi_delete_{i:03d}"))
            frame.name = f"Temp Multi Delete Frame {i}"
            frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#TempDeleteFrame"
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
        
        # Test multiple frame deletion
        response = await client.kgframes.delete_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            uri_list=",".join(temp_uris)
        )
        
        if response.is_success and response.deleted_count > 0:
            logger.info(f"✅ Multiple frame deletion successful: {response.deleted_count} frames deleted")
            return True
        else:
            logger.error(f"❌ Multiple frame deletion failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Multiple frame deletion failed with exception: {e}")
        return False


async def test_delete_nonexistent_frame(client: VitalGraphClient, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test deleting a non-existent frame (should handle gracefully)."""
    logger.info("🧪 Testing non-existent frame deletion...")
    
    try:
        # Test deletion of non-existent frame
        nonexistent_uri = "urn:test-nonexistent-frame-999"
        response = await client.kgframes.delete_kgframe(
            space_id=space_id,
            graph_id=graph_id,
            uri=nonexistent_uri
        )
        
        # Should either succeed with 0 deletions or fail gracefully
        if response.is_success or (response.message and "not found" in response.message.lower()):
            logger.info(f"✅ Non-existent frame deletion handled gracefully")
            return True
        else:
            logger.error(f"❌ Non-existent frame deletion failed unexpectedly: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Non-existent frame deletion failed with exception: {e}")
        return False


async def test_delete_frame_with_dependencies(client: VitalGraphClient, space_id: str, graph_id: str, parent_frame_uri: str, logger: logging.Logger) -> bool:
    """Test deleting a frame that has dependencies (slots, child frames)."""
    logger.info("🧪 Testing frame deletion with dependencies...")
    
    try:
        # Test deletion of frame with dependencies
        response = await client.kgframes.delete_kgframe(
            space_id=space_id,
            graph_id=graph_id,
            uri=parent_frame_uri
        )
        
        if response.is_success:
            logger.info(f"✅ Frame deletion with dependencies successful: {response.deleted_count} items deleted")
            return True
        else:
            logger.error(f"❌ Frame deletion with dependencies failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Frame deletion with dependencies failed with exception: {e}")
        return False


async def run_frame_delete_tests(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: Optional[str] = None, frame_uris: Optional[list[str]] = None, parent_frame_uri: Optional[str] = None, entity_uri: Optional[str] = None, logger: logging.Logger = None) -> bool:
    """Run all frame deletion tests."""
    if logger is None:
        logger = logging.getLogger(__name__)
    
    logger.info("🚀 Running Frame Deletion Tests...")
    
    tests = [
        ("Non-existent Frame Deletion", lambda: test_delete_nonexistent_frame(client, space_id, graph_id, logger))
    ]
    
    # Delete tests create their own temp data
    tests.append(("Single Frame Deletion", lambda: test_delete_single_frame(client, space_id, graph_id, entity_uri, logger)))
    tests.append(("Multiple Frame Deletion", lambda: test_delete_multiple_frames(client, space_id, graph_id, entity_uri, logger)))
    
    if parent_frame_uri:
        tests.append(("Frame Deletion with Dependencies", lambda: test_delete_frame_with_dependencies(client, space_id, graph_id, parent_frame_uri, logger)))
    
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
        logger.info("✅ All frame deletion tests passed!")
        return True
    else:
        failed_tests = [name for name, success in results if not success]
        logger.error(f"❌ Frame deletion tests failed: {failed_tests}")
        return False
