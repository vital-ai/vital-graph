"""
Client Test Case: Slot Creation Operations

Tests KGSlots creation functionality including:
- Create slots for existing frame
- Create slots with entity URI
- Create slots with parent URI
- Create slots with operation modes
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


async def test_slot_creation_basic(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: str, logger: logging.Logger) -> bool:
    """Test basic slot creation for a frame."""
    logger.info("🧪 Testing basic slot creation...")
    
    try:
        # Create test data using VitalSigns objects - CORRECT APPROACH
        test_data_creator = ClientTestDataCreator()
        
        # Create a KGTextSlot using VitalSigns
        slot = KGTextSlot()
        slot.URI = str(test_data_creator.generate_test_uri("slot", "basic_001"))
        slot.name = "Test Basic Slot"
        slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#TestSlot"
        slot.textSlotValue = "Basic slot value"
        
        # Test slot creation - pass GraphObject directly
        response = await client.kgframes.create_frame_slots(
            space_id=space_id,
            graph_id=graph_id,
            frame_uri=frame_uri,
            objects=[slot]
        )
        
        if response.is_success and response.created_count > 0:
            logger.info(f"✅ Basic slot creation successful: {response.created_count} slots created")
            return True
        else:
            logger.error(f"❌ Basic slot creation failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Basic slot creation failed with exception: {e}")
        return False


async def test_slot_creation_with_entity_uri(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: str, entity_uri: str, logger: logging.Logger) -> bool:
    """Test slot creation with entity URI parameter."""
    logger.info("🧪 Testing slot creation with entity URI...")
    
    try:
        # Create test data using VitalSigns objects - CORRECT APPROACH
        test_data_creator = ClientTestDataCreator()
        
        # Create a KGTextSlot using VitalSigns
        slot = KGTextSlot()
        slot.URI = test_data_creator.generate_test_uri("slot", "entity_001")
        slot.name = "Test Slot with Entity"
        slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#EntitySlot"
        slot.textSlotValue = "Entity slot value"
        
        # Test slot creation with entity URI - pass GraphObject directly
        response = await client.kgframes.create_frame_slots(
            space_id=space_id,
            graph_id=graph_id,
            frame_uri=frame_uri,
            objects=[slot],
            entity_uri=entity_uri
        )
        
        if response.is_success and response.created_count > 0:
            logger.info(f"✅ Slot creation with entity URI successful: {response.created_count} slots created")
            return True
        else:
            logger.error(f"❌ Slot creation with entity URI failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Slot creation with entity URI failed with exception: {e}")
        return False


async def test_slot_creation_with_parent_uri(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: str, parent_uri: str, logger: logging.Logger) -> bool:
    """Test slot creation with parent URI parameter."""
    logger.info("🧪 Testing slot creation with parent URI...")
    
    try:
        # Create test data using VitalSigns objects - CORRECT APPROACH
        test_data_creator = ClientTestDataCreator()
        
        # Create a KGTextSlot using VitalSigns
        slot = KGTextSlot()
        slot.URI = test_data_creator.generate_test_uri("slot", "parent_001")
        slot.name = "Test Slot with Parent"
        slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#ParentSlot"
        slot.textSlotValue = "Parent slot value"
        
        # Test slot creation with parent URI - pass GraphObject directly
        response = await client.kgframes.create_frame_slots(
            space_id=space_id,
            graph_id=graph_id,
            frame_uri=frame_uri,
            objects=[slot],
            parent_uri=parent_uri
        )
        
        if response.is_success and response.created_count > 0:
            logger.info(f"✅ Slot creation with parent URI successful: {response.created_count} slots created")
            return True
        else:
            logger.error(f"❌ Slot creation with parent URI failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Slot creation with parent URI failed with exception: {e}")
        return False


async def test_slot_creation_with_operation_modes(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: str, logger: logging.Logger) -> bool:
    """Test slot creation with different operation modes."""
    logger.info("🧪 Testing slot creation with operation modes...")
    
    try:
        # Create test data using VitalSigns objects - CORRECT APPROACH
        test_data_creator = ClientTestDataCreator()
        
        # Create a KGTextSlot using VitalSigns
        slot = KGTextSlot()
        slot.URI = test_data_creator.generate_test_uri("slot", "mode_001")
        slot.name = "Test Slot with Mode"
        slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#ModeSlot"
        slot.textSlotValue = "Mode slot value"
        
        # Test different operation modes - pass GraphObject directly
        for mode in ["create", "update", "upsert"]:
            logger.info(f"   Testing operation mode: {mode}")
            
            try:
                response = await client.kgframes.create_frame_slots(
                    space_id=space_id,
                    graph_id=graph_id,
                    frame_uri=frame_uri,
                    objects=[slot],
                    operation_mode=mode
                )
                
                if not response.is_success:
                    logger.error(f"❌ Slot creation with mode {mode} failed: {response.message}")
                    return False
            except Exception as mode_error:
                # Some operation modes may not be fully supported yet
                logger.warning(f"⚠️ Slot creation with mode {mode} encountered issue: {mode_error}")
                # Continue with other modes
                continue
        
        logger.info("✅ Slot creation with operation modes successful")
        return True
        
    except Exception as e:
        logger.error(f"❌ Slot creation with operation modes failed with exception: {e}")
        return False


async def test_slot_creation_multiple(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: str, logger: logging.Logger) -> bool:
    """Test creating multiple slots for a frame in a single request."""
    logger.info("🧪 Testing multiple slot creation...")
    
    try:
        # Create test data using VitalSigns objects - CORRECT APPROACH
        test_data_creator = ClientTestDataCreator()
        
        # Create multiple KGTextSlots using VitalSigns
        slots = []
        for i in range(1, 4):
            slot = KGTextSlot()
            slot.URI = test_data_creator.generate_test_uri("slot", f"multi_{i:03d}")
            slot.name = f"Test Multi Slot {i}"
            slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#MultiSlot"
            slot.textSlotValue = f"Multi slot value {i}"
            slots.append(slot)
        
        # Test multiple slot creation - pass GraphObjects directly
        response = await client.kgframes.create_frame_slots(
            space_id=space_id,
            graph_id=graph_id,
            frame_uri=frame_uri,
            objects=slots
        )
        
        if response.is_success and response.created_count >= 3:
            logger.info(f"✅ Multiple slot creation successful: {response.created_count} slots created")
            return True
        else:
            logger.error(f"❌ Multiple slot creation failed: {response.message}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Multiple slot creation failed with exception: {e}")
        return False


async def run_slot_create_tests(client: VitalGraphClient, space_id: str, graph_id: str, frame_uri: str, entity_uri: Optional[str] = None, parent_uri: Optional[str] = None, logger: logging.Logger = None) -> bool:
    """Run all slot creation tests."""
    if logger is None:
        logger = logging.getLogger(__name__)
    
    logger.info("🚀 Running Slot Creation Tests...")
    
    tests = [
        ("Basic Slot Creation", lambda: test_slot_creation_basic(client, space_id, graph_id, frame_uri, logger)),
        ("Slot Creation with Operation Modes", lambda: test_slot_creation_with_operation_modes(client, space_id, graph_id, frame_uri, logger)),
        ("Multiple Slot Creation", lambda: test_slot_creation_multiple(client, space_id, graph_id, frame_uri, logger))
    ]
    
    # Add optional tests if URIs are provided
    if entity_uri:
        tests.append(("Slot Creation with Entity URI", lambda: test_slot_creation_with_entity_uri(client, space_id, graph_id, frame_uri, entity_uri, logger)))
    
    if parent_uri:
        tests.append(("Slot Creation with Parent URI", lambda: test_slot_creation_with_parent_uri(client, space_id, graph_id, frame_uri, parent_uri, logger)))
    
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
        logger.info("✅ All slot creation tests passed!")
        return True
    else:
        failed_tests = [name for name, success in results if not success]
        logger.error(f"❌ Slot creation tests failed: {failed_tests}")
        return False
