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

# VitalSigns utilities
from vital_ai_vitalsigns.vitalsigns import VitalSigns


async def test_get_frames_with_slots(client: VitalGraphClient, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test getting frames with their associated slots."""
    logger.info("🧪 Testing get frames with slots...")
    
    try:
        # Test basic frames with slots retrieval
        test_frame_uri = "http://vital.ai/test/kgentity/frame/test_person_contact"
        response = await client.kgframes.get_kgframes_with_slots(
            space_id=space_id,
            graph_id=graph_id,
            frame_uri=test_frame_uri,
            page_size=10,
            offset=0
        )
        
        if response.is_success:
            total_count = getattr(response, 'total_count', 0)
            objects = response.objects or []
            logger.info(f"✅ Get frames with slots successful: {total_count} total")
            logger.info(f"   Retrieved {len(objects)} objects on this page")
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
        response = await client.kgframes.get_kgframes_with_slots(
            space_id=space_id,
            graph_id=graph_id,
            frame_uri=test_frame_uri,
            page_size=10,
            offset=0,
            entity_uri=entity_uri
        )
        
        if response.is_success:
            total_count = getattr(response, 'total_count', 0)
            logger.info(f"✅ Get frames with slots (filtered) successful: {total_count} items for entity")
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
        
        # Test frame with slots creation - pass GraphObjects directly
        response = await client.kgframes.create_kgframes_with_slots(
            space_id=space_id,
            graph_id=graph_id,
            objects=[frame, slot1, slot2],
            entity_uri=entity_uri
        )
        
        if response.is_success and response.created_count > 0:
            logger.info(f"✅ Create frames with slots successful: {response.created_count} items created")
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
        
        # Test frame with slots update - pass GraphObjects directly
        response = await client.kgframes.update_kgframes_with_slots(
            space_id=space_id,
            graph_id=graph_id,
            objects=[frame, slot1, slot2, edge1, edge2],
            entity_uri=entity_uri
        )
        
        if response.is_success:
            logger.info(f"✅ Update frames with slots successful: updated_uri={response.updated_uri}")
            return True
        else:
            logger.error(f"❌ Update frames with slots failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Update frames with slots failed with exception: {e}")
        return False


async def test_delete_frames_with_slots(client: VitalGraphClient, space_id: str, graph_id: str, entity_uri: Optional[str], logger: logging.Logger) -> bool:
    """Test deleting frames with slots cascading. Creates its own temp data to avoid destroying shared test data."""
    logger.info("🧪 Testing delete frames with slots...")
    
    try:
        # Create temporary frames specifically for this delete test
        test_data_creator = ClientTestDataCreator()
        
        temp_frames = []
        for i in range(2):
            frame = KGFrame()
            frame.URI = str(test_data_creator.generate_test_uri("frame", f"delete_test_{i:03d}"))
            frame.name = f"Temp Delete Test Frame {i}"
            frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#TempDeleteFrame"
            temp_frames.append(frame)
        
        # Create the temp frames first
        create_response = await client.kgframes.create_kgframes(
            space_id=space_id,
            graph_id=graph_id,
            objects=temp_frames,
            entity_uri=entity_uri
        )
        
        if not create_response.is_success:
            logger.error(f"❌ Failed to create temp frames for delete test: {create_response.message}")
            return False
        
        temp_uris = [str(f.URI) for f in temp_frames]
        
        # Now test deletion of the temp frames
        response = await client.kgframes.delete_kgframes_with_slots(
            space_id=space_id,
            graph_id=graph_id,
            uri_list=",".join(temp_uris)
        )
        
        if response.is_success and response.deleted_count > 0:
            logger.info(f"✅ Delete frames with slots successful: {response.deleted_count} items deleted")
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
        tests.append(("Delete Frames with Slots", lambda: test_delete_frames_with_slots(client, space_id, graph_id, entity_uri, logger)))
    
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
