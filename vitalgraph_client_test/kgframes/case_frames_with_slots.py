"""
Client Test Case: Frames with Slots Integration Operations

Tests KGFrames with KGSlots integration functionality including:
- Get frames with their associated slots
- Create frames with slots in single operation
- Update frames with slots in single operation
- Delete frames with slots cascading
"""

import logging
from typing import Optional
from vitalgraph.client.vitalgraph_client import VitalGraphClient

# VitalSigns imports - REQUIRED for proper test data creation
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from vitalgraph_client_test.client_test_data import ClientTestDataCreator

# VitalSigns utilities for JSON-LD conversion
from vital_ai_vitalsigns.vitalsigns import VitalSigns

# Import test utilities
from .test_utils import convert_to_jsonld_request


async def test_get_frames_with_slots(client: VitalGraphClient, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test getting frames with their associated slots."""
    logger.info("🧪 Testing get frames with slots...")
    
    try:
        # Test basic frames with slots retrieval
        test_frame_uri = "http://vital.ai/test/kgentity/frame/test_person_contact"
        response = client.kgframes.get_kgframes_with_slots(
            space_id=space_id,
            graph_id=graph_id,
            frame_uri=test_frame_uri,
            page_size=10,
            offset=0
        )
        
        if hasattr(response, 'success') and response.success:
            total_count = getattr(response, 'total_count', 0)
            frames = getattr(response, 'frames', [])
            logger.info(f"✅ Get frames with slots successful: {total_count} total frames")
            logger.info(f"   Retrieved {len(frames)} frames on this page")
            return True
        elif hasattr(response, 'frames'):
            frames = getattr(response, 'frames', [])
            logger.info(f"✅ Get frames with slots successful: Retrieved {len(frames)} frames")
            return True
        else:
            logger.error(f"❌ Get frames with slots failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Get frames with slots failed with exception: {e}")
        return False


async def test_get_frames_with_slots_filtered(client: VitalGraphClient, space_id: str, graph_id: str, entity_uri: str, logger: logging.Logger) -> bool:
    """Test getting frames with slots using entity filter."""
    logger.info("🧪 Testing get frames with slots (filtered)...")
    
    try:
        # Test frames with slots retrieval with entity filter
        test_frame_uri = "http://vital.ai/test/kgentity/frame/test_person_personal"
        response = client.kgframes.get_kgframes_with_slots(
            space_id=space_id,
            graph_id=graph_id,
            frame_uri=test_frame_uri,
            page_size=10,
            offset=0,
            entity_uri=entity_uri
        )
        
        if hasattr(response, 'success') and response.success:
            total_count = getattr(response, 'total_count', 0)
            logger.info(f"✅ Get frames with slots (filtered) successful: {total_count} frames for entity")
            return True
        elif hasattr(response, 'frames'):
            frames = getattr(response, 'frames', [])
            logger.info(f"✅ Get frames with slots (filtered) successful: Retrieved {len(frames)} frames")
            return True
        else:
            logger.error(f"❌ Get frames with slots (filtered) failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Get frames with slots (filtered) failed with exception: {e}")
        return False


async def test_create_frames_with_slots(client: VitalGraphClient, space_id: str, graph_id: str, entity_uri: Optional[str], logger: logging.Logger) -> bool:
    """Test creating frames with slots in a single operation."""
    logger.info("🧪 Testing create frames with slots...")
    
    try:
        # Create test data using VitalSigns objects - CORRECT APPROACH
        test_data_creator = ClientTestDataCreator()
        
        # Create KGFrame using VitalSigns
        frame = KGFrame()
        frame.URI = str(test_data_creator.generate_test_uri("frame", "with_slots_001"))
        frame.name = "Test Frame with Slots"
        frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#IntegratedFrame"
        
        # Create KGTextSlots using VitalSigns
        slot1 = KGTextSlot()
        slot1.URI = str(test_data_creator.generate_test_uri("slot", "integrated_001"))
        slot1.name = "Integrated Slot 1"
        slot1.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#IntegratedSlot"
        slot1.textSlotValue = "Integrated slot value 1"
        
        slot2 = KGTextSlot()
        slot2.URI = str(test_data_creator.generate_test_uri("slot", "integrated_002"))
        slot2.name = "Integrated Slot 2"
        slot2.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#IntegratedSlot"
        slot2.textSlotValue = "Integrated slot value 2"
        
        # Convert VitalSigns objects to JSON-LD using helper function
        document = convert_to_jsonld_request([frame, slot1, slot2])
        
        # Test frame with slots creation
        response = client.kgframes.create_kgframes_with_slots(
            space_id=space_id,
            graph_id=graph_id,
            data=document,
            entity_uri=entity_uri
        )
        
        if response.success and response.frames_created > 0:
            logger.info(f"✅ Create frames with slots successful: {response.frames_created} frames, {response.slots_created} slots created")
            return True
        else:
            logger.error(f"❌ Create frames with slots failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Create frames with slots failed with exception: {e}")
        return False


async def test_update_frames_with_slots(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: str, entity_uri: Optional[str], logger: logging.Logger) -> bool:
    """Test updating frames with slots in a single operation."""
    logger.info("🧪 Testing update frames with slots...")
    
    try:
        # Create test data using VitalSigns objects - CORRECT APPROACH
        test_data_creator = ClientTestDataCreator()
        
        # Create updated KGFrame using VitalSigns
        frame = KGFrame()
        frame.URI = frame_uri
        frame.name = "Updated Frame with Slots"
        frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#UpdatedIntegratedFrame"
        
        # Create updated KGTextSlots using VitalSigns
        slot1 = KGTextSlot()
        slot1.URI = str(test_data_creator.generate_test_uri("slot", "updated_001"))
        slot1.name = "Updated Integrated Slot 1"
        slot1.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#UpdatedIntegratedSlot"
        slot1.textSlotValue = "Updated integrated slot value 1"
        
        slot2 = KGTextSlot()
        slot2.URI = str(test_data_creator.generate_test_uri("slot", "updated_002"))
        slot2.name = "Updated Integrated Slot 2"
        slot2.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#UpdatedIntegratedSlot"
        slot2.textSlotValue = "Updated integrated slot value 2"
        
        # Create Edge_hasKGSlot relationships using VitalSigns
        edge1 = Edge_hasKGSlot()
        edge1.URI = str(test_data_creator.generate_test_uri("edge", "hasslot_updated_001"))
        edge1.edgeSource = str(frame_uri)
        edge1.edgeDestination = str(slot1.URI)
        
        edge2 = Edge_hasKGSlot()
        edge2.URI = str(test_data_creator.generate_test_uri("edge", "hasslot_updated_002"))
        edge2.edgeSource = str(frame_uri)
        edge2.edgeDestination = str(slot2.URI)
        
        # Convert VitalSigns objects to JSON-LD using helper function
        document = convert_to_jsonld_request([frame, slot1, slot2, edge1, edge2])
        
        # Test frame with slots update
        response = client.kgframes.update_kgframes_with_slots(
            space_id=space_id,
            graph_id=graph_id,
            data=document,
            entity_uri=entity_uri
        )
        
        if response.success and response.frames_updated > 0:
            logger.info(f"✅ Update frames with slots successful: {response.frames_updated} frames, {response.slots_updated} slots updated")
            return True
        else:
            logger.error(f"❌ Update frames with slots failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Update frames with slots failed with exception: {e}")
        return False


async def test_delete_frames_with_slots(client: VitalGraphClient, space_id: str, graph_id: str, frame_uris: list[str], logger: logging.Logger) -> bool:
    """Test deleting frames with slots cascading."""
    logger.info("🧪 Testing delete frames with slots...")
    
    try:
        # Test frame with slots deletion
        response = client.kgframes.delete_kgframes_with_slots(
            space_id=space_id,
            graph_id=graph_id,
            uri_list=",".join([str(uri) for uri in frame_uris])
        )
        
        if response.success and response.frames_deleted > 0:
            logger.info(f"✅ Delete frames with slots successful: {response.frames_deleted} frames deleted")
            if response.slots_deleted and response.slots_deleted > 0:
                logger.info(f"   Also deleted {response.slots_deleted} associated slots")
            return True
        else:
            logger.error(f"❌ Delete frames with slots failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Delete frames with slots failed with exception: {e}")
        return False


async def run_frames_with_slots_tests(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: Optional[str] = None, frame_uris: Optional[list[str]] = None, entity_uri: Optional[str] = None, logger: logging.Logger = None) -> bool:
    """Run all frames with slots integration tests."""
    if logger is None:
        logger = logging.getLogger(__name__)
    
    logger.info("🚀 Running Frames with Slots Integration Tests...")
    
    tests = [
        ("Get Frames with Slots", lambda: test_get_frames_with_slots(client, space_id, graph_id, logger)),
        ("Create Frames with Slots", lambda: test_create_frames_with_slots(client, space_id, graph_id, entity_uri, logger))
    ]
    
    # Add optional tests if parameters are provided
    if entity_uri:
        tests.append(("Get Frames with Slots (Filtered)", lambda: test_get_frames_with_slots_filtered(client, space_id, graph_id, entity_uri, logger)))
    
    if frame_uri:
        tests.append(("Update Frames with Slots", lambda: test_update_frames_with_slots(client, space_id, graph_id, frame_uri, entity_uri, logger)))
    
    if frame_uris and len(frame_uris) > 0:
        tests.append(("Delete Frames with Slots", lambda: test_delete_frames_with_slots(client, space_id, graph_id, frame_uris, logger)))
    
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
        logger.info("✅ All frames with slots integration tests passed!")
        return True
    else:
        failed_tests = [name for name, success in results if not success]
        logger.error(f"❌ Frames with slots integration tests failed: {failed_tests}")
        return False
