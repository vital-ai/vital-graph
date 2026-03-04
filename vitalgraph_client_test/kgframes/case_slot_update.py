"""
Client Test Case: Slot Update Operations

Tests KGSlots update functionality including:
- Update slots for existing frame
- Update slots with entity URI
- Update slots with parent URI
- Batch slot updates
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


async def test_slot_update_basic(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: str, slot_uri: str, logger: logging.Logger) -> bool:
    """Test basic slot update for a frame."""
    logger.info("🧪 Testing basic slot update...")
    
    try:
        # Create test data using VitalSigns objects - CORRECT APPROACH
        test_data_creator = ClientTestDataCreator()
        
        # Create updated KGTextSlot using VitalSigns
        slot = KGTextSlot()
        slot.URI = slot_uri
        slot.name = "Updated Test Slot"
        slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#UpdatedSlot"
        slot.textSlotValue = "Updated slot value"
        
        # Test slot update - pass GraphObject directly
        response = await client.kgframes.update_frame_slots(
            space_id=space_id,
            graph_id=graph_id,
            frame_uri=frame_uri,
            objects=[slot]
        )
        
        if response.is_success:
            logger.info(f"✅ Basic slot update successful: updated_uri={response.updated_uri}")
            return True
        else:
            logger.error(f"❌ Basic slot update failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Basic slot update failed with exception: {e}")
        return False


async def test_slot_update_with_entity_uri(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: str, slot_uri: str, entity_uri: str, logger: logging.Logger) -> bool:
    """Test slot update with entity URI parameter."""
    logger.info("🧪 Testing slot update with entity URI...")
    
    try:
        # Create test data using VitalSigns objects - CORRECT APPROACH
        test_data_creator = ClientTestDataCreator()
        
        # Create updated KGTextSlot using VitalSigns
        slot = KGTextSlot()
        slot.URI = slot_uri
        slot.name = "Updated Slot with Entity"
        slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#EntityUpdatedSlot"
        slot.textSlotValue = "Updated entity slot value"
        
        # Test slot update with entity URI - pass GraphObject directly
        response = await client.kgframes.update_frame_slots(
            space_id=space_id,
            graph_id=graph_id,
            frame_uri=frame_uri,
            objects=[slot],
            entity_uri=entity_uri
        )
        
        if response.is_success:
            logger.info(f"✅ Slot update with entity URI successful: updated_uri={response.updated_uri}")
            return True
        else:
            logger.error(f"❌ Slot update with entity URI failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Slot update with entity URI failed with exception: {e}")
        return False


async def test_slot_update_with_parent_uri(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: str, slot_uri: str, parent_uri: str, logger: logging.Logger) -> bool:
    """Test slot update with parent URI parameter."""
    logger.info("🧪 Testing slot update with parent URI...")
    
    try:
        # Create test data using VitalSigns objects - CORRECT APPROACH
        test_data_creator = ClientTestDataCreator()
        
        # Create updated KGTextSlot using VitalSigns
        slot = KGTextSlot()
        slot.URI = slot_uri
        slot.name = "Updated Slot with Parent"
        slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#ParentUpdatedSlot"
        slot.textSlotValue = "Updated parent slot value"
        
        # Test slot update with parent URI - pass GraphObject directly
        response = await client.kgframes.update_frame_slots(
            space_id=space_id,
            graph_id=graph_id,
            frame_uri=frame_uri,
            objects=[slot],
            parent_uri=parent_uri
        )
        
        if response.is_success:
            logger.info(f"✅ Slot update with parent URI successful: updated_uri={response.updated_uri}")
            return True
        else:
            logger.error(f"❌ Slot update with parent URI failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Slot update with parent URI failed with exception: {e}")
        return False


async def test_slot_update_multiple(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: str, slot_uris: list[str], logger: logging.Logger) -> bool:
    """Test updating multiple slots for a frame in a single request."""
    logger.info("🧪 Testing multiple slot update...")
    
    try:
        # Create test data using VitalSigns objects - CORRECT APPROACH
        test_data_creator = ClientTestDataCreator()
        
        # Create multiple updated KGTextSlots using VitalSigns
        slots = []
        for i, slot_uri in enumerate(slot_uris):
            slot = KGTextSlot()
            slot.URI = slot_uri
            slot.name = f"Batch Updated Slot {i+1}"
            slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#BatchUpdatedSlot"
            slot.textSlotValue = f"Batch updated slot value {i+1}"
            slots.append(slot)
        
        # Test multiple slot update - pass GraphObjects directly
        response = await client.kgframes.update_frame_slots(
            space_id=space_id,
            graph_id=graph_id,
            frame_uri=frame_uri,
            objects=slots
        )
        
        if response.is_success:
            logger.info(f"✅ Multiple slot update successful: updated_uri={response.updated_uri}")
            return True
        else:
            logger.error(f"❌ Multiple slot update failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Multiple slot update failed with exception: {e}")
        return False


async def run_slot_update_tests(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: str, slot_uri: Optional[str] = None, slot_uris: Optional[list[str]] = None, entity_uri: Optional[str] = None, parent_uri: Optional[str] = None, logger: logging.Logger = None) -> bool:
    """Run all slot update tests."""
    if logger is None:
        logger = logging.getLogger(__name__)
    
    logger.info("🚀 Running Slot Update Tests...")
    
    tests = []
    
    # Add tests if slot URI is provided
    if slot_uri:
        tests.append(("Basic Slot Update", lambda: test_slot_update_basic(client, space_id, graph_id, frame_uri, slot_uri, logger)))
        
        if entity_uri:
            tests.append(("Slot Update with Entity URI", lambda: test_slot_update_with_entity_uri(client, space_id, graph_id, frame_uri, slot_uri, entity_uri, logger)))
        
        if parent_uri:
            tests.append(("Slot Update with Parent URI", lambda: test_slot_update_with_parent_uri(client, space_id, graph_id, frame_uri, slot_uri, parent_uri, logger)))
    
    # Add multiple slot update test if slot URIs are provided
    if slot_uris and len(slot_uris) > 1:
        tests.append(("Multiple Slot Update", lambda: test_slot_update_multiple(client, space_id, graph_id, frame_uri, slot_uris, logger)))
    
    if not tests:
        logger.warning("⚠️ No slot update tests to run - no slot URIs provided")
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
        logger.info("✅ All slot update tests passed!")
        return True
    else:
        failed_tests = [name for name, success in results if not success]
        logger.error(f"❌ Slot update tests failed: {failed_tests}")
        return False
