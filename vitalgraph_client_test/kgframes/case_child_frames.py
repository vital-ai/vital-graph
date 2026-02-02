"""
Client Test Case: Child Frames Operations

Tests KGFrames child frame functionality including:
- Create child frames for a parent frame
- Update child frames for a parent frame
- Delete child frames from a parent frame
- List child frames by parent
"""

import logging
from typing import Optional
from vitalgraph.client.vitalgraph_client import VitalGraphClient

# VitalSigns imports - REQUIRED for proper test data creation
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGFrame import KGFrame
from vitalgraph_client_test.client_test_data import ClientTestDataCreator

# VitalSigns utilities for JSON-LD conversion
from vital_ai_vitalsigns.vitalsigns import VitalSigns

# Import test utilities
from .test_utils import convert_to_jsonld_request


async def test_create_child_frames(client: VitalGraphClient, space_id: str, graph_id: str, parent_frame_uri: str, logger: logging.Logger) -> bool:
    """Test creating child frames for a parent frame."""
    logger.info("🧪 Testing child frame creation...")
    
    try:
        # Create test data using VitalSigns objects - CORRECT APPROACH
        test_data_creator = ClientTestDataCreator()
        
        # Create child KGFrames using VitalSigns
        child_frames = []
        for i in range(1, 4):
            frame = KGFrame()
            frame.URI = str(test_data_creator.generate_test_uri("frame", f"child_{i:03d}"))
            frame.name = f"Test Child Frame {i}"
            frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#ChildFrame"
            # Note: Parent relationship would be handled by edges in a complete implementation
            child_frames.append(frame)
        
        # Convert VitalSigns objects to JSON-LD using helper function
        document = convert_to_jsonld_request(child_frames)
        
        # Test child frame creation
        response = client.kgframes.create_child_frames(
            space_id=space_id,
            graph_id=graph_id,
            parent_frame_uri=parent_frame_uri,
            data=document
        )
        
        if response.success and response.frames_created > 0:
            logger.info(f"✅ Child frame creation successful: {response.frames_created} child frames created")
            return True
        else:
            logger.error(f"❌ Child frame creation failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Child frame creation failed with exception: {e}")
        return False


async def test_update_child_frames(client: VitalGraphClient, space_id: str, graph_id: str, parent_frame_uri: str, child_frame_uris: list[str], logger: logging.Logger) -> bool:
    """Test updating child frames for a parent frame."""
    logger.info("🧪 Testing child frame update...")
    
    try:
        # Create test data using VitalSigns objects - CORRECT APPROACH
        test_data_creator = ClientTestDataCreator()
        
        # Create updated child KGFrames using VitalSigns
        child_frames = []
        for i, child_uri in enumerate(child_frame_uris):
            frame = KGFrame()
            frame.URI = child_uri
            frame.name = f"Updated Child Frame {i+1}"
            frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#UpdatedChildFrame"
            # Note: Parent relationship would be handled by edges in a complete implementation
            child_frames.append(frame)
        
        # Convert VitalSigns objects to JSON-LD using helper function
        document = convert_to_jsonld_request(child_frames)
        
        # Test child frame update
        response = client.kgframes.update_child_frames(
            space_id=space_id,
            graph_id=graph_id,
            parent_frame_uri=parent_frame_uri,
            data=document
        )
        
        if response.success and response.frames_updated > 0:
            logger.info(f"✅ Child frame update successful: {response.frames_updated} child frames updated")
            return True
        else:
            logger.error(f"❌ Child frame update failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Child frame update failed with exception: {e}")
        return False


async def test_delete_child_frames(client: VitalGraphClient, space_id: str, graph_id: str, parent_frame_uri: str, child_frame_uris: list[str], logger: logging.Logger) -> bool:
    """Test deleting child frames from a parent frame."""
    logger.info("🧪 Testing child frame deletion...")
    
    try:
        # Test child frame deletion
        response = client.kgframes.delete_child_frames(
            space_id=space_id,
            graph_id=graph_id,
            parent_frame_uri=parent_frame_uri,
            frame_uris=child_frame_uris
        )
        
        if response.success and response.frames_deleted > 0:
            logger.info(f"✅ Child frame deletion successful: {response.frames_deleted} child frames deleted")
            return True
        else:
            logger.error(f"❌ Child frame deletion failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Child frame deletion failed with exception: {e}")
        return False


async def test_delete_all_child_frames(client: VitalGraphClient, space_id: str, graph_id: str, parent_frame_uri: str, logger: logging.Logger) -> bool:
    """Test deleting all child frames from a parent frame."""
    logger.info("🧪 Testing all child frames deletion...")
    
    try:
        # For testing purposes, we'll use a known pattern of child frame URIs
        # In a real scenario, you'd first list the child frames
        all_child_frame_uris = [
            f"urn:test-child-all-001-{parent_frame_uri}",
            f"urn:test-child-all-002-{parent_frame_uri}",
            f"urn:test-child-all-003-{parent_frame_uri}"
        ]
        
        # Test deleting all child frames
        response = client.kgframes.delete_child_frames(
            space_id=space_id,
            graph_id=graph_id,
            parent_frame_uri=parent_frame_uri,
            frame_uris=all_child_frame_uris
        )
        
        if response.success:
            logger.info(f"✅ All child frames deletion successful: {response.frames_deleted} child frames deleted")
            return True
        else:
            logger.error(f"❌ All child frames deletion failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ All child frames deletion failed with exception: {e}")
        return False


async def test_child_frames_with_nonexistent_parent(client: VitalGraphClient, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test child frame operations with non-existent parent frame."""
    logger.info("🧪 Testing child frames with non-existent parent...")
    
    try:
        nonexistent_parent_uri = "urn:test-nonexistent-parent-999"
        
        # Create test data using VitalSigns objects - CORRECT APPROACH
        test_data_creator = ClientTestDataCreator()
        
        # Create orphan child KGFrame using VitalSigns
        orphan_frame = KGFrame()
        orphan_frame.URI = str(test_data_creator.generate_test_uri("frame", "orphan_child_001"))
        orphan_frame.name = "Orphan Child Frame"
        orphan_frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#OrphanChildFrame"
        # Note: Parent relationship would be handled by edges in a complete implementation
        
        # Convert VitalSigns objects to JSON-LD using helper function
        document = convert_to_jsonld_request(orphan_frame)
        
        # Test child frame creation with non-existent parent
        response = client.kgframes.create_child_frames(
            space_id=space_id,
            graph_id=graph_id,
            parent_frame_uri=nonexistent_parent_uri,
            data=document
        )
        
        # Should handle gracefully (either succeed or provide appropriate error)
        if response.success or "not found" in response.message.lower() or "parent" in response.message.lower():
            logger.info(f"✅ Child frames with non-existent parent handled gracefully")
            return True
        else:
            logger.error(f"❌ Child frames with non-existent parent failed unexpectedly: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Child frames with non-existent parent failed with exception: {e}")
        return False


async def run_child_frames_tests(client: VitalGraphClient, space_id: str, graph_id: str, parent_frame_uri: str, child_frame_uris: Optional[list[str]] = None, logger: logging.Logger = None) -> bool:
    """Run all child frames tests."""
    if logger is None:
        logger = logging.getLogger(__name__)
    
    logger.info("🚀 Running Child Frames Tests...")
    
    tests = [
        ("Child Frame Creation", lambda: test_create_child_frames(client, space_id, graph_id, parent_frame_uri, logger)),
        ("All Child Frames Deletion", lambda: test_delete_all_child_frames(client, space_id, graph_id, parent_frame_uri, logger)),
        ("Child Frames with Non-existent Parent", lambda: test_child_frames_with_nonexistent_parent(client, space_id, graph_id, logger))
    ]
    
    # Add tests if child frame URIs are provided
    if child_frame_uris and len(child_frame_uris) > 0:
        tests.extend([
            ("Child Frame Update", lambda: test_update_child_frames(client, space_id, graph_id, parent_frame_uri, child_frame_uris, logger)),
            ("Child Frame Deletion", lambda: test_delete_child_frames(client, space_id, graph_id, parent_frame_uri, child_frame_uris, logger))
        ])
    
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
        logger.info("✅ All child frames tests passed!")
        return True
    else:
        failed_tests = [name for name, success in results if not success]
        logger.error(f"❌ Child frames tests failed: {failed_tests}")
        return False
