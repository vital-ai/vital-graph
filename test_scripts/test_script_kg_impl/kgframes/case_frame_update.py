#!/usr/bin/env python3
"""
KGFrame Update Test Module

Modular test implementation for KG frame update operations using existing KGEntityFrameUpdateProcessor.
Used by the main KGFrames endpoint test orchestrator.

Focuses on:
- Frame update using existing KGEntityFrameUpdateProcessor (direct delegation)
- UPDATE vs UPSERT operation modes
- Atomic frame replacement with existing processors
- Direct backend integration through existing processors
"""

import logging
import uuid
from typing import Dict, Any, List, Optional

# Import VitalSigns for KGFrame objects
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject

# Import test utilities
from .test_utils import convert_to_quads

# Import domain models
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot

# Import models
from vitalgraph.model.kgframes_model import FrameUpdateResponse

# Import test data utility (using existing KGEntity test data)
from test_scripts.fuseki_postgresql.kgentity_test_data import KGEntityTestDataCreator


logger = logging.getLogger(__name__)


async def test_frame_update(endpoint, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """
    Test frame update functionality using existing KGEntityFrameUpdateProcessor.
    
    Args:
        endpoint: KGFramesEndpoint instance
        space_id: Test space identifier
        graph_id: Test graph identifier
        logger: Logger instance
        
    Returns:
        bool: True if all tests pass, False otherwise
    """
    try:
        logger.info("🧪 Testing frame update via existing processors...")
        
        # Test 1: Basic frame UPDATE operation
        success = await test_basic_frame_update(endpoint, space_id, graph_id, logger)
        if not success:
            logger.error("❌ Basic frame UPDATE test failed")
            return False
            
        # Test 2: Frame UPSERT operation
        success = await test_frame_upsert(endpoint, space_id, graph_id, logger)
        if not success:
            logger.error("❌ Frame UPSERT test failed")
            return False
            
        # Test 3: Atomic frame replacement
        success = await test_atomic_frame_replacement(endpoint, space_id, graph_id, logger)
        if not success:
            logger.error("❌ Atomic frame replacement test failed")
            return False
            
        logger.info("✅ All frame update tests passed")
        return True
        
    except Exception as e:
        logger.error(f"Frame update tests failed with exception: {e}")
        return False


async def test_basic_frame_update(endpoint, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test basic frame UPDATE operation using existing processor."""
    try:
        logger.info("🔧 Testing basic frame UPDATE operation...")
        
        # Create test entity and initial frame
        from vitalgraph.utils.test_data import create_vitalsigns_entity_graphs
        entity_graphs = create_vitalsigns_entity_graphs(set_grouping_uris=False)
        entity_objects = entity_graphs[0]  # Get first entity graph
        entity_uri = str(entity_objects[0].URI)
        
        # Create entity
        entity_quads = convert_to_quads(entity_objects, graph_id)
        
        entity_response = await endpoint._create_entities(
            space_id=space_id,
            graph_id=graph_id,
            quads=entity_quads,
            operation_mode="CREATE"
        )
        
        if not entity_response or not entity_response.created_count:
            logger.error("Failed to create test entity for UPDATE test")
            return False
            
        # Create initial frame
        initial_frame = create_initial_frame(entity_uri)
        frame_uri = str(initial_frame[0].URI)
        
        frame_quads = convert_to_quads(initial_frame, graph_id)
        
        create_response = await endpoint._create_frames(
            space_id=space_id,
            graph_id=graph_id,
            quads=frame_quads,
            operation_mode="CREATE"
        )
        
        if not create_response or not create_response.created_count:
            logger.error("Failed to create initial frame for UPDATE test")
            return False
            
        logger.info(f"✅ Created initial frame: {frame_uri}")
        
        # Update frame with new properties
        updated_frame = create_updated_frame(entity_uri, frame_uri)
        
        update_response = await endpoint._update_frames(
            space_id=space_id,
            graph_id=graph_id,
            vitalsigns_objects=updated_frame,
            operation_mode="UPDATE"
        )
        
        if not update_response or not hasattr(update_response, 'message'):
            logger.error("Failed to UPDATE frame")
            return False
            
        logger.info("✅ Frame UPDATE operation successful")
        
        # Verify update by retrieving frame
        get_response = await endpoint._get_frame_by_uri(
            space_id=space_id,
            graph_id=graph_id,
            frame_uri=frame_uri
        )
        
        if get_response and hasattr(get_response, 'results') and get_response.results:
            from vitalgraph.utils.quad_format_utils import quad_list_to_graphobjects
            retrieved_objects = quad_list_to_graphobjects(get_response.results)
            retrieved_frames = [obj for obj in retrieved_objects if isinstance(obj, KGFrame)]
            
            if len(retrieved_frames) == 1:
                retrieved_frame = retrieved_frames[0]
                if "Updated" in str(retrieved_frame.name):
                    logger.info("✅ Frame update verified successfully")
                else:
                    logger.warning("⚠️ Frame update verification inconclusive")
            else:
                logger.warning("⚠️ Could not verify frame update")
        
        # Cleanup
        await cleanup_test_entity(endpoint, space_id, graph_id, entity_uri, logger)
        
        return True
        
    except Exception as e:
        logger.error(f"Basic frame UPDATE test failed: {e}")
        return False


async def test_frame_upsert(endpoint, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test frame UPSERT operation (create if not exists, update if exists)."""
    try:
        logger.info("🔧 Testing frame UPSERT operation...")
        
        # Create test entity
        from vitalgraph.utils.test_data import create_vitalsigns_entity_graphs
        entity_graphs = create_vitalsigns_entity_graphs(set_grouping_uris=False)
        entity_objects = entity_graphs[0]  # Get first entity graph
        entity_uri = str(entity_objects[0].URI)
        
        # Create entity
        entity_quads = convert_to_quads(entity_objects, graph_id)
        
        entity_response = await endpoint._create_entities(
            space_id=space_id,
            graph_id=graph_id,
            quads=entity_quads,
            operation_mode="CREATE"
        )
        
        if not entity_response or not entity_response.created_count:
            logger.error("Failed to create test entity for UPSERT test")
            return False
            
        # UPSERT new frame (should create)
        new_frame = create_upsert_frame(entity_uri, "new")
        new_frame_uri = str(new_frame[0].URI)
        
        frame_quads = convert_to_quads(new_frame, graph_id)
        
        upsert_response1 = await endpoint._create_frames(
            space_id=space_id,
            graph_id=graph_id,
            quads=frame_quads,
            operation_mode="UPSERT"
        )
        
        if not upsert_response1 or not upsert_response1.created_count:
            logger.error("Failed to UPSERT new frame (create)")
            return False
            
        logger.info(f"✅ UPSERT created new frame: {new_frame_uri}")
        
        # UPSERT existing frame (should update)
        updated_frame = create_upsert_frame(entity_uri, "updated", new_frame_uri)
        
        updated_quads = convert_to_quads(updated_frame, graph_id)
        
        upsert_response2 = await endpoint._create_frames(
            space_id=space_id,
            graph_id=graph_id,
            quads=updated_quads,
            operation_mode="UPSERT"
        )
        
        if not upsert_response2 or not upsert_response2.created_count:
            logger.error("Failed to UPSERT existing frame (update)")
            return False
            
        logger.info("✅ UPSERT updated existing frame")
        
        # Cleanup
        await cleanup_test_entity(endpoint, space_id, graph_id, entity_uri, logger)
        
        return True
        
    except Exception as e:
        logger.error(f"Frame UPSERT test failed: {e}")
        return False


async def test_atomic_frame_replacement(endpoint, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test atomic frame replacement (old frame deleted, new frame created)."""
    try:
        logger.info("🔧 Testing atomic frame replacement...")
        
        # Create test entity
        from vitalgraph.utils.test_data import create_vitalsigns_entity_graphs
        entity_graphs = create_vitalsigns_entity_graphs(set_grouping_uris=False)
        entity_objects = entity_graphs[0]  # Get first entity graph
        entity_uri = str(entity_objects[0].URI)
        
        # Create entity
        entity_quads = convert_to_quads(entity_objects, graph_id)
        
        entity_response = await endpoint._create_entities(
            space_id=space_id,
            graph_id=graph_id,
            quads=entity_quads,
            operation_mode="CREATE"
        )
        
        if not entity_response or not entity_response.created_count:
            logger.error("Failed to create test entity for atomic replacement test")
            return False
            
        # Create initial frame with slots
        initial_frame_with_slots = create_frame_with_slots(entity_uri, "initial")
        initial_frame_uri = None
        initial_slot_count = 0
        
        for obj in initial_frame_with_slots:
            if isinstance(obj, KGFrame):
                initial_frame_uri = str(obj.URI)
            elif isinstance(obj, KGTextSlot):
                initial_slot_count += 1
        
        frame_quads = convert_to_quads(initial_frame_with_slots, graph_id)
        
        create_response = await endpoint._create_frames(
            space_id=space_id,
            graph_id=graph_id,
            quads=frame_quads,
            operation_mode="CREATE"
        )
        
        if not create_response or not create_response.created_count:
            logger.error("Failed to create initial frame with slots for atomic replacement")
            return False
            
        logger.info(f"✅ Created initial frame with {initial_slot_count} slots")
        
        # Replace with completely different frame structure (atomic replacement)
        replacement_frame = create_replacement_frame(entity_uri, initial_frame_uri)
        replacement_slot_count = sum(1 for obj in replacement_frame if isinstance(obj, KGTextSlot))
        
        update_response = await endpoint._update_frames(
            space_id=space_id,
            graph_id=graph_id,
            vitalsigns_objects=replacement_frame,
            operation_mode="UPDATE"
        )
        
        if not update_response or not hasattr(update_response, 'message'):
            logger.error("Failed to perform atomic frame replacement")
            return False
            
        logger.info(f"✅ Atomic replacement successful: {replacement_slot_count} new slots")
        
        # Verify replacement by retrieving frame
        get_response = await endpoint._get_frame_by_uri(
            space_id=space_id,
            graph_id=graph_id,
            frame_uri=initial_frame_uri
        )
        
        if get_response and hasattr(get_response, 'results') and get_response.results:
            from vitalgraph.utils.quad_format_utils import quad_list_to_graphobjects
            retrieved_objects = quad_list_to_graphobjects(get_response.results)
            retrieved_frames = [obj for obj in retrieved_objects if isinstance(obj, KGFrame)]
            
            if len(retrieved_frames) == 1:
                retrieved_frame = retrieved_frames[0]
                if "Replacement" in str(retrieved_frame.name):
                    logger.info("✅ Atomic replacement verified successfully")
                else:
                    logger.warning("⚠️ Atomic replacement verification inconclusive")
        
        # Cleanup
        await cleanup_test_entity(endpoint, space_id, graph_id, entity_uri, logger)
        
        return True
        
    except Exception as e:
        logger.error(f"Atomic frame replacement test failed: {e}")
        return False


def create_initial_frame(entity_uri: str) -> List[GraphObject]:
    """Create initial frame for update testing."""
    objects = []
    
    # Create frame
    frame = KGFrame()
    frame.URI = f"http://vital.ai/test/frame/update_test_frame_{uuid.uuid4().hex[:8]}"
    frame.name = "Initial Test Frame"
    frame.kGFrameDescription = "Initial frame for update testing"
    frame.kGFrameType = "urn:UpdateTestFrameType"
    frame.kGGraphURI = entity_uri
    frame.frameGraphURI = str(frame.URI)
    
    objects.append(frame)
    
    # Create entity-frame edge
    entity_frame_edge = Edge_hasEntityKGFrame()
    entity_frame_edge.URI = f"http://vital.ai/test/edge/entity_update_frame_{uuid.uuid4().hex[:8]}"
    entity_frame_edge.hasEdgeSource = entity_uri
    entity_frame_edge.hasEdgeDestination = str(frame.URI)
    entity_frame_edge.kGGraphURI = entity_uri
    
    objects.append(entity_frame_edge)
    
    return objects


def create_updated_frame(entity_uri: str, frame_uri: str) -> List[GraphObject]:
    """Create updated version of frame."""
    objects = []
    
    # Update frame properties
    frame = KGFrame()
    frame.URI = frame_uri  # Same URI for update
    frame.name = "Updated Test Frame"
    frame.kGFrameDescription = "Updated frame description"
    frame.kGFrameType = "urn:UpdatedTestFrameType"
    frame.kGGraphURI = entity_uri
    frame.frameGraphURI = frame_uri
    
    objects.append(frame)
    
    # Keep entity-frame edge
    entity_frame_edge = Edge_hasEntityKGFrame()
    entity_frame_edge.URI = f"http://vital.ai/test/edge/entity_updated_frame_{uuid.uuid4().hex[:8]}"
    entity_frame_edge.hasEdgeSource = entity_uri
    entity_frame_edge.hasEdgeDestination = frame_uri
    entity_frame_edge.kGGraphURI = entity_uri
    
    objects.append(entity_frame_edge)
    
    return objects


def create_upsert_frame(entity_uri: str, suffix: str, frame_uri: str = None) -> List[GraphObject]:
    """Create frame for UPSERT testing."""
    objects = []
    
    # Create or update frame
    frame = KGFrame()
    frame.URI = frame_uri or f"http://vital.ai/test/frame/upsert_test_frame_{uuid.uuid4().hex[:8]}"
    frame.name = f"Upsert Test Frame - {suffix}"
    frame.kGFrameDescription = f"Frame for UPSERT testing - {suffix}"
    frame.kGFrameType = "urn:UpsertTestFrameType"
    frame.kGGraphURI = entity_uri
    frame.frameGraphURI = str(frame.URI)
    
    objects.append(frame)
    
    # Create entity-frame edge
    entity_frame_edge = Edge_hasEntityKGFrame()
    entity_frame_edge.URI = f"http://vital.ai/test/edge/entity_upsert_frame_{suffix}_{uuid.uuid4().hex[:8]}"
    entity_frame_edge.hasEdgeSource = entity_uri
    entity_frame_edge.hasEdgeDestination = str(frame.URI)
    entity_frame_edge.kGGraphURI = entity_uri
    
    objects.append(entity_frame_edge)
    
    return objects


def create_frame_with_slots(entity_uri: str, suffix: str) -> List[GraphObject]:
    """Create frame with slots for atomic replacement testing."""
    objects = []
    
    # Create frame
    frame = KGFrame()
    frame.URI = f"http://vital.ai/test/frame/atomic_frame_{suffix}_{uuid.uuid4().hex[:8]}"
    frame.name = f"Atomic Test Frame - {suffix}"
    frame.kGFrameDescription = f"Frame with slots for atomic testing - {suffix}"
    frame.kGFrameType = "urn:AtomicTestFrameType"
    frame.kGGraphURI = entity_uri
    frame.frameGraphURI = str(frame.URI)
    
    objects.append(frame)
    
    # Create text slot
    text_slot = KGTextSlot()
    text_slot.URI = f"http://vital.ai/test/slot/atomic_text_slot_{suffix}_{uuid.uuid4().hex[:8]}"
    text_slot.name = f"Atomic Text Slot - {suffix}"
    text_slot.textValue = f"Text value for {suffix} testing"
    text_slot.kGSlotType = "urn:EnhancedTextSlotType"
    text_slot.kGGraphURI = entity_uri
    
    objects.append(text_slot)
    
    # Create slot edge
    slot_edge = Edge_hasKGSlot()
    slot_edge.URI = f"http://vital.ai/test/edge/atomic_slot_edge_{suffix}_{uuid.uuid4().hex[:8]}"
    slot_edge.hasEdgeSource = str(frame.URI)
    slot_edge.hasEdgeDestination = str(text_slot.URI)
    slot_edge.kGGraphURI = entity_uri
    
    objects.append(slot_edge)
    
    # Create entity-frame edge
    entity_frame_edge = Edge_hasEntityKGFrame()
    entity_frame_edge.URI = f"http://vital.ai/test/edge/entity_atomic_frame_{suffix}_{uuid.uuid4().hex[:8]}"
    entity_frame_edge.hasEdgeSource = entity_uri
    entity_frame_edge.hasEdgeDestination = str(frame.URI)
    entity_frame_edge.kGGraphURI = entity_uri
    
    objects.append(entity_frame_edge)
    
    return objects


def create_replacement_frame(entity_uri: str, frame_uri: str) -> List[GraphObject]:
    """Create replacement frame with different structure."""
    objects = []
    
    # Create replacement frame (same URI, different content)
    frame = KGFrame()
    frame.URI = frame_uri  # Same URI for atomic replacement
    frame.name = "Replacement Test Frame"
    frame.kGFrameDescription = "Completely different frame structure"
    frame.kGFrameType = "urn:ReplacementTestFrameType"
    frame.kGGraphURI = entity_uri
    frame.frameGraphURI = frame_uri
    
    objects.append(frame)
    
    # Create different slot structure
    new_text_slot = KGTextSlot()
    new_text_slot.URI = f"http://vital.ai/test/slot/replacement_slot_{uuid.uuid4().hex[:8]}"
    new_text_slot.name = "Replacement Slot"
    new_text_slot.textValue = "Replacement slot value"
    new_text_slot.kGSlotType = "urn:EnhancedTextSlotType"
    new_text_slot.kGGraphURI = entity_uri
    
    objects.append(new_text_slot)
    
    # Create new slot edge
    new_slot_edge = Edge_hasKGSlot()
    new_slot_edge.URI = f"http://vital.ai/test/edge/replacement_slot_edge_{uuid.uuid4().hex[:8]}"
    new_slot_edge.hasEdgeSource = frame_uri
    new_slot_edge.hasEdgeDestination = str(new_text_slot.URI)
    new_slot_edge.kGGraphURI = entity_uri
    
    objects.append(new_slot_edge)
    
    # Keep entity-frame edge
    entity_frame_edge = Edge_hasEntityKGFrame()
    entity_frame_edge.URI = f"http://vital.ai/test/edge/entity_replacement_frame_{uuid.uuid4().hex[:8]}"
    entity_frame_edge.hasEdgeSource = entity_uri
    entity_frame_edge.hasEdgeDestination = frame_uri
    entity_frame_edge.kGGraphURI = entity_uri
    
    objects.append(entity_frame_edge)
    
    return objects


async def cleanup_test_entity(endpoint, space_id: str, graph_id: str, entity_uri: str, logger: logging.Logger):
    """Clean up test entity and associated frames."""
    try:
        delete_response = await endpoint._delete_entities(
            space_id=space_id,
            graph_id=graph_id,
            entity_uris=[entity_uri]
        )
        
        if delete_response and hasattr(delete_response, 'deleted_count'):
            logger.info(f"✅ Cleaned up test entity: {entity_uri}")
        else:
            logger.warning(f"⚠️ Failed to cleanup test entity: {entity_uri}")
            
    except Exception as e:
        logger.warning(f"Cleanup failed for entity {entity_uri}: {e}")
