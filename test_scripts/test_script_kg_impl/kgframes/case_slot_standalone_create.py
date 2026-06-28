#!/usr/bin/env python3
"""
Standalone Slot Creation Test Case

Tests KGFrames endpoint slot creation functionality independent of entities.
This test validates slot CRUD operations for standalone frames.
"""

import logging
from typing import List
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGDoubleSlot import KGDoubleSlot
from ai_haley_kg_domain.model.KGDateTimeSlot import KGDateTimeSlot
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from .test_utils import convert_to_quads


def create_standalone_frame_for_slots(base_uri: str = "http://vital.ai/test/slots") -> KGFrame:
    """Create a standalone frame to attach slots to."""
    frame = KGFrame()
    frame.URI = f"{base_uri}/frame/slot_test_frame"
    frame.name = "Slot Test Frame"
    frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#TestFrame"
    # Note: Using name instead of kGFrameDescription as the property may not exist
    return frame


def create_standalone_slot_objects(frame_uri: str, base_uri: str = "http://vital.ai/test/slots") -> List[GraphObject]:
    """Create standalone slot objects for a given frame."""
    objects = []
    
    # Create text slot
    text_slot = KGTextSlot()
    text_slot.URI = f"{base_uri}/slot/text_slot_001"
    text_slot.name = "Test Text Slot"
    text_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#TestTextSlot"
    text_slot.textSlotValue = "Standalone text slot value"
    objects.append(text_slot)
    
    # Create edge connecting frame to text slot
    text_edge = Edge_hasKGSlot()
    text_edge.URI = f"{base_uri}/edge/frame_to_text_slot"
    text_edge.edgeSource = frame_uri
    text_edge.edgeDestination = text_slot.URI
    objects.append(text_edge)
    
    # Create double slot
    double_slot = KGDoubleSlot()
    double_slot.URI = f"{base_uri}/slot/double_slot_001"
    double_slot.name = "Test Double Slot"
    double_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#TestDoubleSlot"
    double_slot.doubleSlotValue = 123.45
    objects.append(double_slot)
    
    # Create edge connecting frame to double slot
    double_edge = Edge_hasKGSlot()
    double_edge.URI = f"{base_uri}/edge/frame_to_double_slot"
    double_edge.edgeSource = frame_uri
    double_edge.edgeDestination = double_slot.URI
    objects.append(double_edge)
    
    return objects


def create_multiple_slot_types(frame_uri: str, base_uri: str = "http://vital.ai/test/multislots") -> List[GraphObject]:
    """Create multiple different slot types for comprehensive testing."""
    objects = []
    
    slot_configs = [
        {
            "class": KGTextSlot,
            "uri_suffix": "text_slot_multi",
            "name": "Multi Text Slot",
            "type": "MultiTextSlot",
            "value_prop": "textSlotValue",
            "value": "Multi-type text value"
        },
        {
            "class": KGDoubleSlot,
            "uri_suffix": "double_slot_multi",
            "name": "Multi Double Slot", 
            "type": "MultiDoubleSlot",
            "value_prop": "doubleSlotValue",
            "value": 999.99
        },
        {
            "class": KGDateTimeSlot,
            "uri_suffix": "datetime_slot_multi",
            "name": "Multi DateTime Slot",
            "type": "MultiDateTimeSlot", 
            "value_prop": "dateTimeSlotValue",
            "value": "2023-12-15T10:30:00Z"
        }
    ]
    
    for i, config in enumerate(slot_configs):
        # Create slot
        slot = config["class"]()
        slot.URI = f"{base_uri}/slot/{config['uri_suffix']}"
        slot.name = config["name"]
        slot.kGSlotType = f"http://vital.ai/ontology/haley-ai-kg#{config['type']}"
        setattr(slot, config["value_prop"], config["value"])
        objects.append(slot)
        
        # Create edge
        edge = Edge_hasKGSlot()
        edge.URI = f"{base_uri}/edge/frame_to_{config['uri_suffix']}"
        edge.edgeSource = frame_uri
        edge.edgeDestination = slot.URI
        objects.append(edge)
    
    return objects


async def test_basic_standalone_slot_creation(endpoint, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test basic standalone slot creation for a standalone frame."""
    try:
        logger.info("🔧 Testing basic standalone slot creation...")
        
        # First create a standalone frame
        frame = create_standalone_frame_for_slots()
        
        # Convert to quads
        frame_quads = convert_to_quads([frame], graph_id)
        
        # Create the frame first
        frame_response = await endpoint._create_frames(
            space_id=space_id,
            graph_id=graph_id,
            quads=frame_quads,
            operation_mode="CREATE"
        )
        
        if not frame_response or not hasattr(frame_response, 'created_count') or frame_response.created_count == 0:
            logger.error("Failed to create standalone frame for slot testing")
            return False
        
        # Now create slots for the frame
        slot_objects = create_standalone_slot_objects(frame.URI)
        
        # Convert slots to quads
        slot_quads = convert_to_quads(slot_objects, graph_id)
        
        # Create slots via endpoint
        slot_response = await endpoint._create_slots(
            space_id=space_id,
            graph_id=graph_id,
            quads=slot_quads,
            operation_mode="CREATE"
        )
        
        if not slot_response or not hasattr(slot_response, 'created_count') or slot_response.created_count == 0:
            logger.error("Failed to create standalone slots")
            return False
            
        logger.info(f"✅ Created {slot_response.created_count} standalone slots")
        return True
        
    except Exception as e:
        logger.error(f"Basic standalone slot creation test failed: {e}")
        return False


async def test_multiple_slot_types_creation(endpoint, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test creation of multiple slot types for a standalone frame."""
    try:
        logger.info("🔧 Testing multiple slot types creation...")
        
        # Create standalone frame
        frame = create_standalone_frame_for_slots("http://vital.ai/test/multislots")
        
        # Convert to quads
        frame_quads = convert_to_quads([frame], graph_id)
        
        # Create the frame
        frame_response = await endpoint._create_frames(
            space_id=space_id,
            graph_id=graph_id,
            quads=frame_quads,
            operation_mode="CREATE"
        )
        
        if not frame_response or not hasattr(frame_response, 'created_count') or frame_response.created_count == 0:
            logger.error("Failed to create frame for multiple slot types test")
            return False
        
        # Create multiple slot types
        slot_objects = create_multiple_slot_types(frame.URI)
        
        # Convert to quads
        slot_quads = convert_to_quads(slot_objects, graph_id)
        
        # Create slots via endpoint
        slot_response = await endpoint._create_slots(
            space_id=space_id,
            graph_id=graph_id,
            quads=slot_quads,
            operation_mode="CREATE"
        )
        
        if not slot_response or not hasattr(slot_response, 'created_count') or slot_response.created_count == 0:
            logger.error("Failed to create multiple slot types")
            return False
            
        logger.info(f"✅ Created {slot_response.created_count} slots of multiple types")
        return True
        
    except Exception as e:
        logger.error(f"Multiple slot types creation test failed: {e}")
        return False


async def test_standalone_slot_batch_creation(endpoint, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test batch creation of slots for multiple standalone frames."""
    try:
        logger.info("🔧 Testing standalone slot batch creation...")
        
        # Create multiple standalone frames
        all_objects = []
        frame_uris = []
        base_uri = "http://vital.ai/test/batchslots"
        
        # Create 2 frames
        for i in range(2):
            frame = KGFrame()
            frame.URI = f"{base_uri}/frame/batch_frame_{i+1}"
            frame.name = f"Batch Frame {i+1}"
            frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#TestFrame"
            # Note: Using name instead of kGFrameDescription as the property may not exist
            all_objects.append(frame)
            frame_uris.append(str(frame.URI))
        
        # Create frames first
        frame_quads = convert_to_quads(all_objects, graph_id)
        
        frame_response = await endpoint._create_frames(
            space_id=space_id,
            graph_id=graph_id,
            quads=frame_quads,
            operation_mode="CREATE"
        )
        
        if not frame_response or not hasattr(frame_response, 'created_count') or frame_response.created_count != 2:
            logger.error("Failed to create batch frames for slot testing")
            return False
        
        # Create slots for each frame
        all_slot_objects = []
        for i, frame_uri in enumerate(frame_uris):
            slot_objects = create_standalone_slot_objects(frame_uri, f"{base_uri}/frame_{i+1}")
            all_slot_objects.extend(slot_objects)
        
        # Convert to quads
        slot_quads = convert_to_quads(all_slot_objects, graph_id)
        
        # Create all slots in batch
        slot_response = await endpoint._create_slots(
            space_id=space_id,
            graph_id=graph_id,
            quads=slot_quads,
            operation_mode="CREATE"
        )
        
        if not slot_response or not hasattr(slot_response, 'created_count') or slot_response.created_count == 0:
            logger.error("Failed to create batch slots")
            return False
            
        logger.info(f"✅ Created {slot_response.created_count} slots in batch for multiple frames")
        return True
        
    except Exception as e:
        logger.error(f"Standalone slot batch creation test failed: {e}")
        return False


async def test_standalone_slot_upsert(endpoint, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test UPSERT operation on standalone slots."""
    try:
        logger.info("🔧 Testing standalone slot UPSERT operation...")
        
        # Create standalone frame for UPSERT test
        frame = create_standalone_frame_for_slots("http://vital.ai/test/upsertframe")
        
        # Convert to quads
        frame_quads = convert_to_quads([frame], graph_id)
        
        # Create the frame
        frame_response = await endpoint._create_frames(
            space_id=space_id,
            graph_id=graph_id,
            quads=frame_quads,
            operation_mode="CREATE"
        )
        
        if not frame_response or not hasattr(frame_response, 'created_count') or frame_response.created_count == 0:
            logger.error("Failed to create frame for slot UPSERT test")
            return False
        
        # Create slots for UPSERT testing
        slot_objects = create_standalone_slot_objects(frame.URI, "http://vital.ai/test/upsertslots")
        
        # Convert to quads
        slot_quads = convert_to_quads(slot_objects, graph_id)
        
        # UPSERT slots (should create since they don't exist)
        slot_response = await endpoint._create_slots(
            space_id=space_id,
            graph_id=graph_id,
            quads=slot_quads,
            operation_mode="UPSERT"
        )
        
        if not slot_response or not hasattr(slot_response, 'created_count') or slot_response.created_count == 0:
            logger.error("Failed to UPSERT standalone slots")
            return False
            
        logger.info("✅ Standalone slot UPSERT operation successful")
        return True
        
    except Exception as e:
        logger.error(f"Standalone slot UPSERT test failed: {e}")
        return False


async def run_standalone_slot_creation_tests(endpoint, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Run all standalone slot creation tests."""
    logger.info("🧪 Running standalone slot creation tests...")
    
    tests = [
        ("Basic standalone slot creation", test_basic_standalone_slot_creation),
        ("Multiple slot types creation", test_multiple_slot_types_creation),
        ("Standalone slot batch creation", test_standalone_slot_batch_creation),
        ("Standalone slot UPSERT", test_standalone_slot_upsert)
    ]
    
    results = []
    for test_name, test_func in tests:
        logger.info(f"🔧 Running: {test_name}")
        try:
            result = await test_func(endpoint, space_id, graph_id, logger)
            results.append(result)
            if result:
                logger.info(f"✅ {test_name} passed")
            else:
                logger.error(f"❌ {test_name} failed")
        except Exception as e:
            logger.error(f"❌ {test_name} failed with exception: {e}")
            results.append(False)
    
    success_count = sum(results)
    total_count = len(results)
    logger.info(f"📊 Standalone slot creation tests: {success_count}/{total_count} passed")
    
    return all(results)
