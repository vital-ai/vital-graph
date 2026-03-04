"""
Client Test Case: Frame Update Operations

Tests KGFrames update functionality including:
- Basic frame update
- Frame update with entity URI
- Frame update with parent URI
- Batch frame updates
"""

import logging
from typing import Optional
from vitalgraph.client.vitalgraph_client import VitalGraphClient

# VitalSigns imports - REQUIRED for proper test data creation
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGFrame import KGFrame
from vitalgraph_client_test.client_test_data import ClientTestDataCreator

# VitalSigns utilities
from vital_ai_vitalsigns.vitalsigns import VitalSigns


async def test_frame_update_basic(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: str, logger: logging.Logger) -> bool:
    """Test basic frame update without optional parameters."""
    logger.info("🧪 Testing basic frame update...")
    
    try:
        # Create test data using VitalSigns objects - CORRECT APPROACH
        test_data_creator = ClientTestDataCreator()
        
        # Create updated KGFrame using VitalSigns
        frame = KGFrame()
        frame.URI = frame_uri
        frame.name = "Updated Test Frame"
        frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#UpdatedFrame"
        
        # Test frame update - pass GraphObject directly
        response = await client.kgframes.update_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            objects=[frame]
        )
        
        if response.is_success:
            logger.info(f"✅ Basic frame update successful: updated_uri={response.updated_uri}")
            return True
        else:
            logger.error(f"❌ Basic frame update failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Basic frame update failed with exception: {e}")
        return False


async def test_frame_update_with_entity_uri(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: str, entity_uri: str, logger: logging.Logger) -> bool:
    """Test frame update with entity URI parameter."""
    logger.info("🧪 Testing frame update with entity URI...")
    
    try:
        # Create test data using VitalSigns objects - CORRECT APPROACH
        test_data_creator = ClientTestDataCreator()
        
        # Create updated KGFrame using VitalSigns
        frame = KGFrame()
        frame.URI = frame_uri
        frame.name = "Updated Frame with Entity"
        frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#EntityUpdatedFrame"
        
        # Test frame update with entity URI - pass GraphObject directly
        response = await client.kgframes.update_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            objects=[frame],
            entity_uri=entity_uri
        )
        
        if response.is_success:
            logger.info(f"✅ Frame update with entity URI successful: updated_uri={response.updated_uri}")
            return True
        else:
            logger.error(f"❌ Frame update with entity URI failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Frame update with entity URI failed with exception: {e}")
        return False


async def test_frame_update_with_parent_uri(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: str, parent_uri: str, logger: logging.Logger) -> bool:
    """Test frame update with parent URI parameter."""
    logger.info("🧪 Testing frame update with parent URI...")
    
    try:
        # Create test data using VitalSigns objects - CORRECT APPROACH
        test_data_creator = ClientTestDataCreator()
        
        # Create updated KGFrame using VitalSigns
        frame = KGFrame()
        frame.URI = frame_uri
        frame.name = "Updated Child Frame"
        frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#ChildUpdatedFrame"
        
        # Test frame update with parent URI - pass GraphObject directly
        response = await client.kgframes.update_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            objects=[frame],
            parent_uri=parent_uri
        )
        
        if response.is_success:
            logger.info(f"✅ Frame update with parent URI successful: updated_uri={response.updated_uri}")
            return True
        else:
            logger.error(f"❌ Frame update with parent URI failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Frame update with parent URI failed with exception: {e}")
        return False


async def test_frame_update_multiple(client: VitalGraphClient, space_id: str, graph_id: str, frame_uris: list[str], logger: logging.Logger) -> bool:
    """Test updating multiple frames in a single request."""
    logger.info("🧪 Testing multiple frame update...")
    
    try:
        # Create test data using VitalSigns objects - CORRECT APPROACH
        test_data_creator = ClientTestDataCreator()
        
        # Create multiple updated KGFrames using VitalSigns
        frames = []
        for i, frame_uri in enumerate(frame_uris):
            frame = KGFrame()
            frame.URI = frame_uri
            frame.name = f"Batch Updated Frame {i+1}"
            frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#BatchUpdatedFrame"
            frames.append(frame)
        
        # Test multiple frame update - pass GraphObjects directly
        response = await client.kgframes.update_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            objects=frames
        )
        
        if response.is_success:
            logger.info(f"✅ Multiple frame update successful: updated_uri={response.updated_uri}")
            return True
        else:
            logger.error(f"❌ Multiple frame update failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Multiple frame update failed with exception: {e}")
        return False


async def run_frame_update_tests(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: Optional[str] = None, frame_uris: Optional[list[str]] = None, entity_uri: Optional[str] = None, parent_uri: Optional[str] = None, logger: logging.Logger = None) -> bool:
    """Run all frame update tests."""
    if logger is None:
        logger = logging.getLogger(__name__)
    
    logger.info("🚀 Running Frame Update Tests...")
    
    tests = []
    
    # Add tests if frame URI is provided
    if frame_uri:
        tests.append(("Basic Frame Update", lambda: test_frame_update_basic(client, space_id, graph_id, frame_uri, logger)))
        
        if entity_uri:
            tests.append(("Frame Update with Entity URI", lambda: test_frame_update_with_entity_uri(client, space_id, graph_id, frame_uri, entity_uri, logger)))
        
        if parent_uri:
            tests.append(("Frame Update with Parent URI", lambda: test_frame_update_with_parent_uri(client, space_id, graph_id, frame_uri, parent_uri, logger)))
    
    # Add multiple frame update test if frame URIs are provided
    if frame_uris and len(frame_uris) > 1:
        tests.append(("Multiple Frame Update", lambda: test_frame_update_multiple(client, space_id, graph_id, frame_uris, logger)))
    
    if not tests:
        logger.warning("⚠️ No frame update tests to run - no frame URIs provided")
        return True
    
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
        logger.info("✅ All frame update tests passed!")
        return True
    else:
        failed_tests = [name for name, success in results if not success]
        logger.error(f"❌ Frame update tests failed: {failed_tests}")
        return False
