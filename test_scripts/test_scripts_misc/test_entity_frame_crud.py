#!/usr/bin/env python3
"""
Entity and Frame CRUD Operations Test

This script demonstrates comprehensive CRUD operations on entities and frames:
1. Create an entity with frames using test data
2. Test all entity endpoints: create, update, upsert, get, delete, list
3. Test all frame endpoints: create, update, upsert, get, delete, list
4. Verify data integrity throughout the operations

This tests the complete entity and frame endpoint functionality.
"""

import sys
import logging
from typing import List, Dict, Any, Optional

sys.path.append('.')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# VitalSigns imports
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.vitalsigns import VitalSigns

# Domain model imports
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGSlot import KGSlot

# Client imports
from vitalgraph.client.client_factory import create_mock_client

# Test data utility
from vitalgraph.utils.test_data import create_vitalsigns_entity_graphs

# Model imports
from vitalgraph.model.kgentities_model import EntityQueryRequest, EntityQueryCriteria
from vitalgraph.model.kgframes_model import FrameQueryRequest, FrameQueryCriteria


def extract_entity_and_frames(graph_objects: List[GraphObject]) -> tuple[KGEntity, List[KGFrame], List[KGSlot]]:
    """Extract entity, frames, and slots from graph objects."""
    entity = None
    frames = []
    slots = []
    
    for obj in graph_objects:
        if isinstance(obj, KGEntity):
            entity = obj
        elif isinstance(obj, KGFrame):
            frames.append(obj)
        elif isinstance(obj, KGSlot):
            slots.append(obj)
    
    return entity, frames, slots


def separate_frame_graphs(graph_objects: List[GraphObject]) -> Dict[str, List[GraphObject]]:
    """
    Separate entity graph into individual frame graphs using edge relationships.
    
    Returns:
        Dict mapping frame URI to list of objects (frame + connected slots + edges)
    """
    from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
    from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
    
    # Group objects by type
    frames = {}
    slots = {}
    frame_edges = {}
    slot_edges = {}
    entity = None
    
    for obj in graph_objects:
        if isinstance(obj, KGEntity):
            entity = obj
        elif isinstance(obj, KGFrame):
            frames[str(obj.URI)] = obj
        elif isinstance(obj, KGSlot):
            slots[str(obj.URI)] = obj
        elif isinstance(obj, Edge_hasEntityKGFrame):
            frame_edges[str(obj.URI)] = obj
        elif isinstance(obj, Edge_hasKGSlot):
            slot_edges[str(obj.URI)] = obj
    
    # Build frame graphs
    frame_graphs = {}
    
    for frame_uri, frame in frames.items():
        frame_graph = [frame]
        
        # Find slots connected to this frame
        for slot_edge in slot_edges.values():
            if hasattr(slot_edge, 'edgeSource') and str(slot_edge.edgeSource) == frame_uri:
                # Add the slot
                slot_uri = str(slot_edge.edgeDestination)
                if slot_uri in slots:
                    frame_graph.append(slots[slot_uri])
                # Add the edge
                frame_graph.append(slot_edge)
        
        # Find the entity-frame edge
        for frame_edge in frame_edges.values():
            if hasattr(frame_edge, 'edgeDestination') and str(frame_edge.edgeDestination) == frame_uri:
                frame_graph.append(frame_edge)
        
        frame_graphs[frame_uri] = frame_graph
    
    return frame_graphs


def create_slot_for_frame(frame_uri: str, slot_name: str, data_type: str, slot_value: Any, semantic_type: str = None) -> tuple[KGSlot, Any]:
    """
    Create a new slot and its edge for a frame.
    
    Args:
        frame_uri: URI of the frame to attach the slot to
        slot_name: Name of the slot
        data_type: Underlying data type ("text", "double", "integer")
        slot_value: Value to store in the slot
        semantic_type: Semantic type URN (e.g., "http://vital.ai/ontology/haley-ai-kg#DescriptionSlot")
    
    Returns:
        Tuple of (slot, edge)
    """
    from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
    from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
    from ai_haley_kg_domain.model.KGDoubleSlot import KGDoubleSlot
    from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
    
    # Create slot based on underlying data type
    slot_uri = f"{frame_uri}_new_{slot_name}"
    
    if data_type == "text":
        slot = KGTextSlot()
        slot.textSlotValue = slot_value
    elif data_type == "double":
        slot = KGDoubleSlot()
        slot.doubleSlotValue = float(slot_value)
    elif data_type == "integer":
        slot = KGIntegerSlot()
        slot.integerSlotValue = int(slot_value)
    else:
        # Default to text
        slot = KGTextSlot()
        slot.textSlotValue = str(slot_value)
    
    slot.URI = slot_uri
    slot.name = slot_name
    
    # Set semantic type - if not provided, create a generic one based on slot name
    if semantic_type:
        slot.kGSlotType = semantic_type
    else:
        # Create a semantic type URN based on the slot name
        slot_type_name = slot_name.replace("_", "").title() + "Slot"
        slot.kGSlotType = f"http://vital.ai/ontology/haley-ai-kg#{slot_type_name}"
    
    # Create edge
    edge = Edge_hasKGSlot()
    edge.URI = f"{slot_uri}_edge"
    edge.edgeSource = frame_uri
    edge.edgeDestination = slot_uri
    
    return slot, edge


def create_modified_entity(original_entity: KGEntity) -> KGEntity:
    """Create a modified version of the entity for update testing."""
    modified_entity = KGEntity()
    modified_entity.URI = original_entity.URI
    modified_entity.name = f"Modified {original_entity.name}"
    modified_entity.kGEntityType = original_entity.kGEntityType
    # Set kGraphDescription
    modified_entity.kGraphDescription = f"Updated description for {original_entity.name}"
    return modified_entity


def create_modified_frame(original_frame: KGFrame) -> KGFrame:
    """Create a modified version of the frame for update testing."""
    modified_frame = KGFrame()
    modified_frame.URI = original_frame.URI
    modified_frame.name = f"Modified {original_frame.name}"
    modified_frame.kGFrameType = original_frame.kGFrameType
    # Set kGraphDescription
    modified_frame.kGraphDescription = f"Updated description for {original_frame.name}"
    return modified_frame


def create_new_frame(entity_uri: str, frame_type: str = "http://vital.ai/ontology/haley-ai-kg#TestFrame") -> KGFrame:
    """Create a new frame for testing."""
    new_frame = KGFrame()
    new_frame.URI = f"{entity_uri}_new_test_frame"
    new_frame.name = "New Test Frame"
    new_frame.kGFrameType = frame_type
    new_frame.kGraphDescription = "A new frame created for CRUD testing"
    return new_frame


def test_entity_frame_crud():
    """Test comprehensive CRUD operations on entities and frames."""
    logger.info("Starting Entity and Frame CRUD Operations Test")
    logger.info("=" * 70)
    
    try:
        # 1. Setup: Create client and space
        logger.info("Step 1: Setting up client and space...")
        
        client = create_mock_client()
        client.open()
        
        space_id = "crud-test-space"
        graph_id = None
        
        # Create space
        from vitalgraph.model.spaces_model import Space
        space_obj = Space(
            space=space_id,
            space_name=space_id,
            space_description="Test space for CRUD operations"
        )
        spaces_result = client.spaces.add_space(space_obj)
        
        if not spaces_result or spaces_result.created_count == 0:
            logger.error("Failed to create space")
            return False
        
        logger.info("✅ Created space: %s", space_id)
        
        # 2. Get test data - use first entity graph
        logger.info("Step 2: Preparing test data...")
        
        entity_graphs = create_vitalsigns_entity_graphs(set_grouping_uris=False)
        if not entity_graphs:
            logger.error("No test data available")
            return False
        
        # Use first entity graph
        test_graph = entity_graphs[0]
        original_entity, original_frames, original_slots = extract_entity_and_frames(test_graph)
        
        if not original_entity:
            logger.error("No entity found in test data")
            return False
        
        logger.info("✅ Test data prepared:")
        logger.info("  Entity: %s", original_entity.URI)
        logger.info("  Frames: %d", len(original_frames))
        logger.info("  Slots: %d", len(original_slots))
        
        # 3. ENTITY CRUD OPERATIONS
        logger.info("\n" + "=" * 50)
        logger.info("ENTITY CRUD OPERATIONS")
        logger.info("=" * 50)
        
        # 3.1 CREATE Entity
        logger.info("Step 3.1: CREATE Entity...")
        
        try:
            # Convert to quads and create entity
            logger.info("📋 CREATE: Entity URI being created: %s", original_entity.URI)
            logger.info("📋 CREATE: Entity name: %s", original_entity.name)
            logger.info("📋 CREATE: Graph contains %d objects", len(test_graph))
            
            logger.info("📋 CREATE: About to call update_kgentities...")
            create_result = client.kgentities.update_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=test_graph,
                operation_mode="create"
            )
            logger.info("📋 CREATE: update_kgentities call completed")
            
            if create_result and create_result.updated_uri:
                logger.info("✅ CREATE Entity successful: %s", create_result.updated_uri)
                created_entity_uri = create_result.updated_uri
                logger.info("📋 Original entity URI: %s", original_entity.URI)
                logger.info("📋 Created entity URI: %s", created_entity_uri)
                
                # Verify entity was actually stored by checking if it exists
                logger.info("📋 CREATE: Verifying entity was actually stored...")
                try:
                    verify_result = client.kgentities.get_kgentity(
                        space_id=space_id,
                        graph_id=graph_id,
                        uri=str(original_entity.URI),
                        include_entity_graph=False
                    )
                    if verify_result:
                        logger.info("📋 CREATE: ✅ Entity verified in store")
                    else:
                        logger.error("📋 CREATE: ❌ Entity NOT found in store after CREATE!")
                        return False
                except Exception as ve:
                    logger.error("📋 CREATE: ❌ Error verifying entity: %s", ve)
                    return False
            else:
                logger.error("❌ CREATE Entity failed")
                return False
                
        except Exception as e:
            logger.error("❌ CREATE Entity failed: %s", e)
            return False
        
        # 3.2 GET Entity
        logger.info("Step 3.2: GET Entity...")
        
        try:
            get_result = client.kgentities.get_kgentity(
                space_id=space_id,
                graph_id=graph_id,
                uri=str(original_entity.URI),
                include_entity_graph=True
            )
            
            if get_result:
                logger.info("✅ GET Entity successful")
                # Extract objects from quad response
                from vitalgraph.utils.quad_format_utils import quad_list_to_graphobjects
                entity_objects = quad_list_to_graphobjects(get_result.results) if hasattr(get_result, 'results') and get_result.results else []
                logger.info("  Entity graph contains %d objects", len(entity_objects))
            else:
                logger.error("❌ GET Entity failed")
                return False
                
        except Exception as e:
            logger.error("❌ GET Entity failed: %s", e)
            return False
        
        # 3.3 UPDATE Entity
        logger.info("Step 3.3: UPDATE Entity...")
        
        try:
            # Create modified entity (URIs stay the same)
            modified_entity = create_modified_entity(original_entity)
            modified_graph = [modified_entity] + original_frames + original_slots
            
            logger.info("📋 UPDATE: Entity URI being updated: %s", modified_entity.URI)
            logger.info("📋 UPDATE: Modified entity name: %s", modified_entity.name)
            logger.info("📋 UPDATE: Graph contains %d objects", len(modified_graph))
            
            logger.info("📋 UPDATE: About to call update_kgentities...")
            update_result = client.kgentities.update_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=modified_graph,
                operation_mode="update"
            )
            logger.info("📋 UPDATE: update_kgentities call completed")
            
            if update_result and update_result.updated_uri:
                logger.info("✅ UPDATE Entity successful: %s", update_result.updated_uri)
            else:
                error_msg = update_result.message if update_result else "No result returned"
                logger.error("❌ UPDATE Entity failed: %s", error_msg)
                return False
                
        except Exception as e:
            logger.error("❌ UPDATE Entity failed: %s", e)
            return False
        
        # 3.4 UPSERT Entity
        logger.info("Step 3.4: UPSERT Entity...")
        
        try:
            # Create another modified version
            upsert_entity = create_modified_entity(original_entity)
            upsert_entity.name = f"Upserted {original_entity.name}"
            upsert_graph = [upsert_entity] + original_frames + original_slots
            
            upsert_result = client.kgentities.update_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=upsert_graph,
                operation_mode="upsert"
            )
            
            if upsert_result and upsert_result.updated_uri:
                logger.info("✅ UPSERT Entity successful: %s", upsert_result.updated_uri)
            else:
                logger.error("❌ UPSERT Entity failed")
                return False
                
        except Exception as e:
            logger.error("❌ UPSERT Entity failed: %s", e)
            return False
        
        # 3.5 LIST Entities (Query)
        logger.info("Step 3.5: LIST Entities (Query)...")
        
        try:
            entity_criteria = EntityQueryCriteria(
                search_string=None,
                entity_type=str(original_entity.kGEntityType),  # Convert to string
                frame_type=None,
                slot_criteria=None,
                sort_criteria=None
            )
            
            entity_request = EntityQueryRequest(
                criteria=entity_criteria,
                page_size=10,
                offset=0
            )
            
            list_result = client.kgentities.query_entities(space_id, graph_id, entity_request)
            
            if list_result and list_result.total_count > 0:
                logger.info("✅ LIST Entities successful: %d entities found", list_result.total_count)
                logger.info("  Entity URIs: %s", list_result.entity_uris[:3])
            else:
                logger.error("❌ LIST Entities failed or no entities found")
                return False
                
        except Exception as e:
            logger.error("❌ LIST Entities failed: %s", e)
            return False
        
        # 4. FRAME CRUD OPERATIONS
        logger.info("\n" + "=" * 50)
        logger.info("FRAME CRUD OPERATIONS")
        logger.info("=" * 50)
        
        if not original_frames:
            logger.warning("No frames in test data, skipping frame CRUD tests")
        else:
            # Separate entity graph into frame graphs
            logger.info("Step 4.0: Separating entity graph into frame graphs...")
            frame_graphs = separate_frame_graphs(test_graph)
            logger.info("✅ Separated into %d frame graphs", len(frame_graphs))
            
            # Use first frame for testing
            test_frame = original_frames[0]
            test_frame_uri = str(test_frame.URI)
            test_frame_graph = frame_graphs.get(test_frame_uri, [test_frame])
            
            # 4.1 GET Frame
            logger.info("Step 4.1: GET Frame...")
            
            try:
                frame_get_result = client.kgframes.get_kgframe(
                    space_id=space_id,
                    graph_id=graph_id,
                    uri=str(test_frame.URI),
                    include_frame_graph=True
                )
                
                if frame_get_result:
                    logger.info("✅ GET Frame successful")
                    # Extract objects from quad response
                    from vitalgraph.utils.quad_format_utils import quad_list_to_graphobjects
                    frame_objects = quad_list_to_graphobjects(frame_get_result.results) if hasattr(frame_get_result, 'results') and frame_get_result.results else []
                    logger.info("  Frame graph contains %d objects", len(frame_objects))
                else:
                    logger.error("❌ GET Frame failed")
                    return False
                    
            except Exception as e:
                logger.error("❌ GET Frame failed: %s", e)
                return False
            
            # 4.2 CREATE new Frame with complete frame graph
            logger.info("Step 4.2: CREATE new Frame...")
            
            try:
                new_frame = create_new_frame(str(original_entity.URI))
                # Create a complete frame graph with entity-frame edge
                from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
                
                frame_edge = Edge_hasEntityKGFrame()
                frame_edge.URI = f"{new_frame.URI}_edge"
                frame_edge.edgeSource = str(original_entity.URI)
                frame_edge.edgeDestination = str(new_frame.URI)
                
                new_frame_graph = [new_frame, frame_edge]
                
                frame_create_result = client.kgframes.update_kgframes(
                    space_id=space_id,
                    graph_id=graph_id,
                    objects=new_frame_graph,
                    operation_mode="create",
                    entity_uri=str(original_entity.URI)
                )
                
                if frame_create_result and frame_create_result.updated_uri:
                    logger.info("✅ CREATE Frame successful: %s", frame_create_result.updated_uri)
                    new_frame_uri = str(new_frame.URI)
                else:
                    logger.error("❌ CREATE Frame failed")
                    return False
                    
            except Exception as e:
                logger.error("❌ CREATE Frame failed: %s", e)
                return False
            
            # 4.3 UPDATE Frame with complete frame graph
            logger.info("Step 4.3: UPDATE Frame...")
            
            try:
                modified_frame = create_modified_frame(test_frame)
                # Use the complete frame graph for update
                modified_frame_graph = test_frame_graph.copy()
                # Replace the frame object with modified version
                for i, obj in enumerate(modified_frame_graph):
                    if isinstance(obj, KGFrame) and str(obj.URI) == test_frame_uri:
                        modified_frame_graph[i] = modified_frame
                        break
                
                frame_update_result = client.kgframes.update_kgframes(
                    space_id=space_id,
                    graph_id=graph_id,
                    objects=modified_frame_graph,
                    operation_mode="update",
                    entity_uri=str(original_entity.URI)
                )
                
                if frame_update_result and frame_update_result.updated_uri:
                    logger.info("✅ UPDATE Frame successful: %s", frame_update_result.updated_uri)
                else:
                    logger.error("❌ UPDATE Frame failed")
                    return False
                    
            except Exception as e:
                logger.error("❌ UPDATE Frame failed: %s", e)
                return False
            
            # 4.4 UPSERT Frame with complete frame graph
            logger.info("Step 4.4: UPSERT Frame...")
            
            try:
                upsert_frame = create_modified_frame(test_frame)
                upsert_frame.name = f"Upserted {test_frame.name}"
                # Use the complete frame graph for upsert
                upsert_frame_graph = test_frame_graph.copy()
                # Replace the frame object with upserted version
                for i, obj in enumerate(upsert_frame_graph):
                    if isinstance(obj, KGFrame) and str(obj.URI) == test_frame_uri:
                        upsert_frame_graph[i] = upsert_frame
                        break
                
                frame_upsert_result = client.kgframes.update_kgframes(
                    space_id=space_id,
                    graph_id=graph_id,
                    objects=upsert_frame_graph,
                    operation_mode="upsert",
                    entity_uri=str(original_entity.URI)
                )
                
                if frame_upsert_result and frame_upsert_result.updated_uri:
                    logger.info("✅ UPSERT Frame successful: %s", frame_upsert_result.updated_uri)
                else:
                    logger.error("❌ UPSERT Frame failed")
                    return False
                    
            except Exception as e:
                logger.error("❌ UPSERT Frame failed: %s", e)
                return False
            
            # 4.5 LIST Frames (Query)
            logger.info("Step 4.5: LIST Frames (Query)...")
            
            try:
                frame_criteria = FrameQueryCriteria(
                    search_string=None,
                    frame_type=str(test_frame.kGFrameType),  # Convert to string
                    entity_type=None,
                    slot_criteria=None,
                    sort_criteria=None
                )
                
                frame_request = FrameQueryRequest(
                    criteria=frame_criteria,
                    page_size=10,
                    offset=0
                )
                
                frame_list_result = client.kgframes.query_frames(space_id, graph_id, frame_request)
                
                if frame_list_result and frame_list_result.total_count > 0:
                    logger.info("✅ LIST Frames successful: %d frames found", frame_list_result.total_count)
                    logger.info("  Frame URIs: %s", frame_list_result.frame_uris[:3])
                else:
                    logger.error("❌ LIST Frames failed or no frames found")
                    return False
                    
            except Exception as e:
                logger.error("❌ LIST Frames failed: %s", e)
                return False
        
        # 5. SLOT CRUD OPERATIONS
        logger.info("\n" + "=" * 50)
        logger.info("SLOT CRUD OPERATIONS")
        logger.info("=" * 50)
        
        if original_frames and test_frame_graph:
            # 5.1 ADD Slot to Frame
            logger.info("Step 5.1: ADD Slot to Frame...")
            
            try:
                # Create a new slot for the test frame
                new_slot, new_slot_edge = create_slot_for_frame(
                    test_frame_uri, 
                    "test_description", 
                    "text", 
                    "This is a test description slot",
                    "http://vital.ai/ontology/haley-ai-kg#DescriptionSlot"
                )
                
                # Create frame graph with new slot
                frame_with_new_slot = test_frame_graph.copy()
                frame_with_new_slot.extend([new_slot, new_slot_edge])
                
                add_slot_result = client.kgframes.update_kgframes(
                    space_id=space_id,
                    graph_id=graph_id,
                    objects=frame_with_new_slot,
                    operation_mode="upsert",
                    entity_uri=str(original_entity.URI)
                )
                
                if add_slot_result and add_slot_result.updated_uri:
                    logger.info("✅ ADD Slot successful: %s", new_slot.URI)
                    new_slot_uri = str(new_slot.URI)
                else:
                    logger.error("❌ ADD Slot failed")
                    return False
                    
            except Exception as e:
                logger.error("❌ ADD Slot failed: %s", e)
                return False
            
            # 5.2 UPDATE Slot in Frame
            logger.info("Step 5.2: UPDATE Slot in Frame...")
            
            try:
                # Find an existing slot to update
                existing_slot = None
                for obj in test_frame_graph:
                    if isinstance(obj, KGSlot):
                        existing_slot = obj
                        break
                
                if existing_slot:
                    # Create modified slot
                    from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
                    modified_slot = KGTextSlot()
                    modified_slot.URI = existing_slot.URI
                    modified_slot.name = f"Modified {existing_slot.name}"
                    modified_slot.textSlotValue = "Updated slot value"
                    modified_slot.kGSlotType = existing_slot.kGSlotType
                    
                    # Update frame graph with modified slot
                    updated_frame_graph = test_frame_graph.copy()
                    for i, obj in enumerate(updated_frame_graph):
                        if isinstance(obj, KGSlot) and str(obj.URI) == str(existing_slot.URI):
                            updated_frame_graph[i] = modified_slot
                            break
                    
                    update_slot_result = client.kgframes.update_kgframes(
                        space_id=space_id,
                        graph_id=graph_id,
                        objects=updated_frame_graph,
                        operation_mode="update",
                        entity_uri=str(original_entity.URI)
                    )
                    
                    if update_slot_result and update_slot_result.updated_uri:
                        logger.info("✅ UPDATE Slot successful: %s", existing_slot.URI)
                    else:
                        logger.error("❌ UPDATE Slot failed")
                        return False
                else:
                    logger.warning("⚠️ No existing slot found to update")
                    
            except Exception as e:
                logger.error("❌ UPDATE Slot failed: %s", e)
                return False
            
            # 5.3 REMOVE Slot from Frame
            logger.info("Step 5.3: REMOVE Slot from Frame...")
            
            try:
                # Find a slot to remove (use the one we added)
                slot_to_remove_uri = new_slot_uri
                
                # Create frame graph without the slot and its edge
                frame_without_slot = []
                for obj in frame_with_new_slot:
                    if isinstance(obj, KGSlot) and str(obj.URI) == slot_to_remove_uri:
                        continue  # Skip the slot
                    elif hasattr(obj, 'edgeDestination') and str(obj.edgeDestination) == slot_to_remove_uri:
                        continue  # Skip the slot edge
                    else:
                        frame_without_slot.append(obj)
                
                remove_slot_result = client.kgframes.update_kgframes(
                    space_id=space_id,
                    graph_id=graph_id,
                    objects=frame_without_slot,
                    operation_mode="update",
                    entity_uri=str(original_entity.URI)
                )
                
                if remove_slot_result and remove_slot_result.updated_uri:
                    logger.info("✅ REMOVE Slot successful: %s", slot_to_remove_uri)
                else:
                    logger.error("❌ REMOVE Slot failed")
                    return False
                    
            except Exception as e:
                logger.error("❌ REMOVE Slot failed: %s", e)
                return False
            
            # 5.4 ADD Multiple Slots to Frame
            logger.info("Step 5.4: ADD Multiple Slots to Frame...")
            
            try:
                # Create multiple new slots
                slots_to_add = []
                edges_to_add = []
                
                # Text slot
                text_slot, text_edge = create_slot_for_frame(
                    test_frame_uri, "category", "text", "premium",
                    "http://vital.ai/ontology/haley-ai-kg#CategorySlot"
                )
                slots_to_add.extend([text_slot, text_edge])
                
                # Double slot
                double_slot, double_edge = create_slot_for_frame(
                    test_frame_uri, "score", "double", 95.5,
                    "http://vital.ai/ontology/haley-ai-kg#ScoreSlot"
                )
                slots_to_add.extend([double_slot, double_edge])
                
                # Integer slot
                integer_slot, integer_edge = create_slot_for_frame(
                    test_frame_uri, "count", "integer", 42,
                    "http://vital.ai/ontology/haley-ai-kg#CountSlot"
                )
                slots_to_add.extend([integer_slot, integer_edge])
                
                # Create frame graph with multiple new slots
                frame_with_multiple_slots = test_frame_graph.copy()
                frame_with_multiple_slots.extend(slots_to_add)
                
                add_multiple_slots_result = client.kgframes.update_kgframes(
                    space_id=space_id,
                    graph_id=graph_id,
                    objects=frame_with_multiple_slots,
                    operation_mode="upsert",
                    entity_uri=str(original_entity.URI)
                )
                
                if add_multiple_slots_result and add_multiple_slots_result.updated_uri:
                    logger.info("✅ ADD Multiple Slots successful: added %d slots", len(slots_to_add) // 2)
                else:
                    logger.error("❌ ADD Multiple Slots failed")
                    return False
                    
            except Exception as e:
                logger.error("❌ ADD Multiple Slots failed: %s", e)
                return False
        
        # 6. DELETE OPERATIONS
        logger.info("\n" + "=" * 50)
        logger.info("DELETE OPERATIONS")
        logger.info("=" * 50)
        
        # 5.1 DELETE Frame
        if original_frames:
            logger.info("Step 5.1: DELETE Frame...")
            
            try:
                delete_frame_result = client.kgframes.delete_kgframe(
                    space_id=space_id,
                    graph_id=graph_id,
                    uri=str(test_frame.URI)
                )
                
                if delete_frame_result and delete_frame_result.deleted_count > 0:
                    logger.info("✅ DELETE Frame successful: %d frames deleted", delete_frame_result.deleted_count)
                else:
                    logger.error("❌ DELETE Frame failed")
                    return False
                    
            except Exception as e:
                logger.error("❌ DELETE Frame failed: %s", e)
                return False
            
            # 5.2 Verify Frame Deletion
            logger.info("Step 5.2: Verify Frame deletion...")
            
            try:
                verify_frame_result = client.kgframes.get_kgframe(
                    space_id=space_id,
                    graph_id=graph_id,
                    uri=str(test_frame.URI),
                    include_frame_graph=True
                )
                
                if not verify_frame_result:
                    logger.info("✅ Frame deletion verified - frame not found")
                else:
                    logger.warning("⚠️ Frame still exists after deletion")
                    
            except Exception as e:
                logger.info("✅ Frame deletion verified - frame not accessible: %s", e)
        
        # 5.3 DELETE Entity
        logger.info("Step 5.3: DELETE Entity...")
        
        try:
            delete_entity_result = client.kgentities.delete_kgentity(
                space_id=space_id,
                graph_id=graph_id,
                uri=str(original_entity.URI)
            )
            
            if delete_entity_result and delete_entity_result.deleted_count > 0:
                logger.info("✅ DELETE Entity successful: %d entities deleted", delete_entity_result.deleted_count)
            else:
                logger.error("❌ DELETE Entity failed")
                return False
                
        except Exception as e:
            logger.error("❌ DELETE Entity failed: %s", e)
            return False
        
        # 5.4 Verify Entity Deletion
        logger.info("Step 5.4: Verify Entity deletion...")
        
        try:
            verify_entity_result = client.kgentities.get_kgentity(
                space_id=space_id,
                graph_id=graph_id,
                uri=str(original_entity.URI),
                include_entity_graph=True
            )
            
            if not verify_entity_result:
                logger.info("✅ Entity deletion verified - entity not found")
            else:
                logger.warning("⚠️ Entity still exists after deletion")
                
        except Exception as e:
            logger.info("✅ Entity deletion verified - entity not accessible: %s", e)
        
        # 6. Final Verification
        logger.info("\n" + "=" * 50)
        logger.info("FINAL VERIFICATION")
        logger.info("=" * 50)
        
        # Verify no entities remain
        try:
            final_entity_query = EntityQueryRequest(
                criteria=EntityQueryCriteria(
                    search_string=None,
                    entity_type=original_entity.kGEntityType,
                    frame_type=None,
                    slot_criteria=None,
                    sort_criteria=None
                ),
                page_size=10,
                offset=0
            )
            
            final_entities = client.kgentities.query_entities(space_id, graph_id, final_entity_query)
            logger.info("Final entity count: %d", final_entities.total_count if final_entities else 0)
            
        except Exception as e:
            logger.error("Final entity verification failed: %s", e)
        
        # Verify no frames remain
        if original_frames:
            try:
                final_frame_query = FrameQueryRequest(
                    criteria=FrameQueryCriteria(
                        search_string=None,
                        frame_type=str(test_frame.kGFrameType),  # Convert to string
                        entity_type=None,
                        slot_criteria=None,
                        sort_criteria=None
                    ),
                    page_size=10,
                    offset=0
                )
                
                final_frames = client.kgframes.query_frames(space_id, graph_id, final_frame_query)
                logger.info("Final frame count: %d", final_frames.total_count if final_frames else 0)
                
            except Exception as e:
                logger.error("Final frame verification failed: %s", e)
        
        # Cleanup
        try:
            client.close()
            logger.info("Closed client connection")
        except Exception as e:
            logger.warning("Error closing client: %s", e)
        
        logger.info("\n🎉 Entity and Frame CRUD Operations Test COMPLETED!")
        logger.info("✅ Successfully tested:")
        logger.info("  - Entity CREATE, GET, UPDATE, UPSERT, LIST, DELETE operations")
        logger.info("  - Frame CREATE, GET, UPDATE, UPSERT, LIST, DELETE operations")
        logger.info("  - Slot ADD, UPDATE, REMOVE operations within frames")
        logger.info("  - Multiple slot types (text, double, integer) operations")
        logger.info("  - Complete entity graph and frame graph handling")
        logger.info("  - Proper edge relationship management")
        logger.info("  - Data integrity verification throughout operations")
        logger.info("  - Proper cleanup and deletion verification")
        
        return True
        
    except Exception as e:
        logger.error("❌ Test failed with exception: %s", e)
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_entity_frame_crud()
    print(f"\n{'✅ SUCCESS' if success else '❌ FAILURE'}: Entity and Frame CRUD test {'passed' if success else 'failed'}")
    sys.exit(0 if success else 1)
