#!/usr/bin/env python3
"""
Standalone Frame Creation Test Case

Tests KGFrames endpoint frame creation functionality independent of entities.
This test validates frame CRUD operations without any entity dependencies.
"""

import logging
from typing import List
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject

# Import test utilities
from .test_utils import convert_to_quads

from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot


def create_standalone_frame_objects(base_uri: str = "http://vital.ai/test/standalone") -> List[GraphObject]:
    """Create standalone frame objects without entity dependencies."""
    objects = []
    
    # Create standalone KGFrame
    frame = KGFrame()
    frame.URI = f"{base_uri}/frame/standalone_frame_001"
    frame.name = "Standalone Test Frame"
    frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#TestFrame"
    # Note: Using name instead of kGFrameDescription as the property may not exist
    objects.append(frame)
    
    return objects


def create_standalone_frame_with_slots(base_uri: str = "http://vital.ai/test/standalone") -> List[GraphObject]:
    """Create standalone frame with associated slots."""
    objects = []
    
    # Create standalone KGFrame
    frame = KGFrame()
    frame.URI = f"{base_uri}/frame/standalone_frame_with_slots"
    frame.name = "Standalone Frame with Slots"
    frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#TestFrame"
    # Note: Using name instead of kGFrameDescription as the property may not exist
    objects.append(frame)
    
    # Create slots for the frame
    slot_data = [
        {"name": "Title Slot", "value": "Standalone Frame Title", "type": "TitleSlot"},
        {"name": "Description Slot", "value": "This is a standalone frame description", "type": "DescriptionSlot"},
        {"name": "Category Slot", "value": "Test Category", "type": "CategorySlot"}
    ]
    
    for i, slot_info in enumerate(slot_data):
        # Create slot
        slot = KGTextSlot()
        slot.URI = f"{base_uri}/slot/standalone_slot_{i+1}"
        slot.name = slot_info["name"]
        slot.kGSlotType = f"http://vital.ai/ontology/haley-ai-kg#{slot_info['type']}"
        slot.textSlotValue = slot_info["value"]
        objects.append(slot)
        
        # Create edge connecting frame to slot
        edge = Edge_hasKGSlot()
        edge.URI = f"{base_uri}/edge/frame_to_slot_{i+1}"
        edge.edgeSource = frame.URI
        edge.edgeDestination = slot.URI
        objects.append(edge)
    
    return objects


async def test_basic_standalone_frame_creation(endpoint, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test basic standalone frame creation without entity dependencies."""
    try:
        logger.info("🔧 Testing basic standalone frame creation...")
        
        # Create standalone frame objects
        frame_objects = create_standalone_frame_objects()
        
        # Convert to quads
        frame_quads = convert_to_quads(frame_objects, graph_id)
        
        # Create frames via endpoint
        response = await endpoint._create_frames(
            space_id=space_id,
            graph_id=graph_id,
            quads=frame_quads,
            operation_mode="CREATE"
        )
        
        if not response or not hasattr(response, 'created_count') or response.created_count == 0:
            logger.error("Failed to create standalone frame")
            return False
            
        logger.info(f"✅ Created {response.created_count} standalone frame(s)")
        return True
        
    except Exception as e:
        logger.error(f"Standalone frame creation test failed: {e}")
        return False


async def test_standalone_frame_with_slots_creation(endpoint, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test standalone frame creation with associated slots."""
    try:
        logger.info("🔧 Testing standalone frame with slots creation...")
        
        # Create standalone frame with slots
        frame_with_slots = create_standalone_frame_with_slots()
        
        # Convert to quads
        frame_quads = convert_to_quads(frame_with_slots, graph_id)
        
        # Create frames with slots via endpoint
        response = await endpoint._create_frames(
            space_id=space_id,
            graph_id=graph_id,
            quads=frame_quads,
            operation_mode="CREATE"
        )
        
        if not response or not hasattr(response, 'created_count') or response.created_count == 0:
            logger.error("Failed to create standalone frame with slots")
            return False
            
        logger.info(f"✅ Created standalone frame with {len(frame_with_slots)} total objects (frame + slots + edges)")
        return True
        
    except Exception as e:
        logger.error(f"Standalone frame with slots creation test failed: {e}")
        return False


async def test_multiple_standalone_frames_creation(endpoint, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test creation of multiple standalone frames in batch."""
    try:
        logger.info("🔧 Testing multiple standalone frames creation...")
        
        # Create multiple standalone frames
        all_frame_objects = []
        base_uri = "http://vital.ai/test/standalone/batch"
        
        for i in range(3):
            frame = KGFrame()
            frame.URI = f"{base_uri}/frame/batch_frame_{i+1}"
            frame.name = f"Batch Standalone Frame {i+1}"
            frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#TestFrame"
            # Note: Using name instead of kGFrameDescription as the property may not exist
            all_frame_objects.append(frame)
        
        # Convert to quads
        frame_quads = convert_to_quads(all_frame_objects, graph_id)
        
        # Create multiple frames via endpoint
        response = await endpoint._create_frames(
            space_id=space_id,
            graph_id=graph_id,
            quads=frame_quads,
            operation_mode="CREATE"
        )
        
        if not response or not hasattr(response, 'created_count') or response.created_count != 3:
            logger.error(f"Failed to create 3 standalone frames, got: {response.created_count if response else 0}")
            return False
            
        logger.info(f"✅ Created {response.created_count} standalone frames in batch")
        return True
        
    except Exception as e:
        logger.error(f"Multiple standalone frames creation test failed: {e}")
        return False


async def test_standalone_frame_upsert(endpoint, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test UPSERT operation on standalone frames."""
    try:
        logger.info("🔧 Testing standalone frame UPSERT operation...")
        
        # Create initial frame
        frame_objects = create_standalone_frame_objects("http://vital.ai/test/upsert")
        frame_quads = convert_to_quads(frame_objects, graph_id)
        
        # UPSERT frames (should create since they don't exist)
        response = await endpoint._create_frames(
            space_id=space_id,
            graph_id=graph_id,
            quads=frame_quads,
            operation_mode="UPSERT"
        )
        
        if not response or not hasattr(response, 'created_count') or response.created_count == 0:
            logger.error("Failed to UPSERT standalone frames")
            return False
            
        logger.info("✅ Standalone frame UPSERT operation successful")
        return True
        
    except Exception as e:
        logger.error(f"Standalone frame UPSERT test failed: {e}")
        return False


async def run_standalone_frame_creation_tests(endpoint, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Run all standalone frame creation tests."""
    logger.info("🧪 Running standalone frame creation tests...")
    
    tests = [
        ("Basic standalone frame creation", test_basic_standalone_frame_creation),
        ("Standalone frame with slots creation", test_standalone_frame_with_slots_creation),
        ("Multiple standalone frames creation", test_multiple_standalone_frames_creation),
        ("Standalone frame UPSERT", test_standalone_frame_upsert)
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
    logger.info(f"📊 Standalone frame creation tests: {success_count}/{total_count} passed")
    
    return all(results)
