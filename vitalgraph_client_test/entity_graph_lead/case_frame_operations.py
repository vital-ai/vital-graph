"""
Lead Frame Operations Test Case

Tests frame-level operations on lead entity graphs including list, get, update, and delete.
"""

import logging
from typing import Dict, Any, List
from vital_ai_vitalsigns.vitalsigns import VitalSigns

logger = logging.getLogger(__name__)


class LeadFrameOperationsTester:
    """Test case for lead entity frame operations."""
    
    def __init__(self, client):
        self.client = client
    
    def run_tests(self, space_id: str, graph_id: str, entity_uri: str, lead_id: str) -> Dict[str, Any]:
        """
        Run lead frame operation tests.
        
        Args:
            space_id: Space ID
            graph_id: Graph ID
            entity_uri: URI of the entity
            lead_id: Lead ID for logging
            
        Returns:
            Dict with test results
        """
        results = {
            "test_name": "Lead Frame Operations",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": []
        }
        
        vs = VitalSigns()
        
        logger.info(f"\n{'='*100}")
        logger.info(f"  Lead Frame Operations")
        logger.info(f"{'='*100}")
        logger.info(f"Testing frame operations on lead: {lead_id}")
        logger.info(f"Entity URI: {entity_uri}")
        
        # Test 0: Comprehensive frame hierarchy and slot verification
        results["tests_run"] += 1
        try:
            logger.info(f"\n--- Comprehensive Frame Hierarchy Test ---\n")
            
            # Get all top-level frames
            top_level_response = self.client.kgentities.get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                parent_frame_uri=None  # Top-level frames only
            )
            
            top_level_frames = []
            if top_level_response.is_success and top_level_response.objects:
                frame_objects = top_level_response.objects
                for obj in frame_objects:
                    if type(obj).__name__ == 'KGFrame':
                        top_level_frames.append(str(obj.URI))
            
            logger.info(f"   Found {len(top_level_frames)} top-level frames")
            
            total_child_frames = 0
            frames_with_slots = 0
            frames_without_slots = 0
            test_frame_with_slots = None  # Store a frame URI that has slots for update tests
            test_frame_parent = None  # Store the parent frame URI for the test frame
            
            # For each top-level frame, get its child frames
            for top_frame_uri in top_level_frames[:3]:  # Test first 3 to avoid too much output
                top_frame_name = top_frame_uri.split(':')[-2] if ':' in top_frame_uri else top_frame_uri
                logger.info(f"\n   Top-level frame: {top_frame_name}")
                
                # Get child frames of this parent
                child_response = self.client.kgentities.get_kgentity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=entity_uri,
                    parent_frame_uri=top_frame_uri
                )
                
                child_frame_uris = []
                if child_response.is_success and child_response.objects:
                    frame_objects = child_response.objects
                    for obj in frame_objects:
                        if type(obj).__name__ == 'KGFrame':
                            child_frame_uris.append(str(obj.URI))
                
                logger.info(f"     Found {len(child_frame_uris)} child frames")
                total_child_frames += len(child_frame_uris)
                
                # For each child frame, get its complete frame graph (should include slots)
                for child_uri in child_frame_uris[:2]:  # Test first 2 children
                    child_name = child_uri.split(':')[-2] if ':' in child_uri else child_uri
                    
                    # Get the complete frame graph
                    frame_graph_response = self.client.kgentities.get_kgentity_frames(
                        space_id=space_id,
                        graph_id=graph_id,
                        entity_uri=entity_uri,
                        frame_uris=[child_uri]
                    )
                    
                    # FrameGraphResponse.frame_graph is a FrameGraph container
                    if frame_graph_response.is_success and frame_graph_response.frame_graph:
                        frame_objects = frame_graph_response.frame_graph.objects
                        
                        # Count object types
                        object_counts = {}
                        slot_count = 0
                        for obj in frame_objects:
                            obj_type = type(obj).__name__
                            object_counts[obj_type] = object_counts.get(obj_type, 0) + 1
                            if 'Slot' in obj_type:
                                slot_count += 1
                        
                        if slot_count > 0:
                            frames_with_slots += 1
                            logger.info(f"       {child_name}: {len(frame_objects)} objects, {slot_count} slots")
                            # Store the first frame with slots for update tests
                            if test_frame_with_slots is None:
                                test_frame_with_slots = child_uri
                                test_frame_parent = top_frame_uri  # Store parent for child frame updates
                        else:
                            frames_without_slots += 1
                            logger.info(f"       {child_name}: {len(frame_objects)} objects, 0 slots (MISSING SLOTS!)")
                    else:
                        logger.error(f"       {child_name}: Error retrieving frame graph")
            
            logger.info(f"\n   Summary:")
            logger.info(f"     Total child frames tested: {total_child_frames}")
            logger.info(f"     Child frames with slots: {frames_with_slots}")
            logger.info(f"     Child frames WITHOUT slots: {frames_without_slots}")
            
            if frames_without_slots == 0 and frames_with_slots > 0:
                logger.info(f" PASS: All child frames have slots")
                results["tests_passed"] += 1
            else:
                logger.error(f" FAIL: {frames_without_slots} child frames missing slots")
                results["tests_failed"] += 1
                results["errors"].append(f"{frames_without_slots} child frames missing slots")
                
        except Exception as e:
            logger.error(f" Error in comprehensive frame test: {e}")
            import traceback
            logger.error(traceback.format_exc())
            results["tests_failed"] += 1
            results["errors"].append(f"Error in comprehensive frame test: {str(e)}")
        
        # Test 1: List all frames
        results["tests_run"] += 1
        
        try:
            logger.info(f"\n--- List All Frames ---\n")
            
            # Get all frames for the entity
            response = self.client.kgentities.get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri
            )
            
            # FrameResponse has objects (List[GraphObject]) directly
            if response.is_success and response.objects:
                frame_objects = response.objects
                logger.info(f"   Retrieved {len(frame_objects)} objects")
                
                # Extract frame URIs (only KGFrame objects)
                frame_uris = []
                for obj in frame_objects:
                    if type(obj).__name__ == 'KGFrame':
                        frame_uris.append(str(obj.URI))
                
                frame_count = len(frame_uris)
                logger.info(f"   Found {frame_count} frames")
                
                if frame_count > 0:
                    logger.info(f"✅ PASS: List all frames")
                    results["tests_passed"] += 1
                    # Use the frame with slots from comprehensive test if available
                    if test_frame_with_slots:
                        test_frame_uri = test_frame_with_slots
                        logger.info(f"   Using frame with slots from comprehensive test: {test_frame_uri.split(':')[-2]}")
                    else:
                        # Fallback: try to find a child frame
                        child_frames = [uri for uri in frame_uris if uri.count(':frame:') > 1]
                        test_frame_uri = child_frames[0] if child_frames else (frame_uris[0] if frame_uris else None)
                else:
                    logger.error(f"   ❌ FAIL: No frames found - expected frames to exist based on entity graph")
                    results["tests_failed"] += 1
                    results["errors"].append("No frames found when frames should exist")
                    test_frame_uri = None
            else:
                logger.error(f"   ❌ FAIL: No frames response - expected frames to exist")
                results["tests_failed"] += 1
                results["errors"].append("No frames response when frames should exist")
                test_frame_uri = None
                
        except Exception as e:
            logger.error(f"❌ Error listing frames: {e}")
            import traceback
            logger.error(traceback.format_exc())
            results["tests_failed"] += 1
            results["errors"].append(f"Error listing frames: {str(e)}")
            test_frame_uri = None
        
        # Test 2: Get specific frame (if frames exist)
        if test_frame_uri:
            results["tests_run"] += 1
            
            try:
                logger.info(f"\n--- Get Specific Frame ---\n")
                
                frame_name = test_frame_uri.split(':')[-1]
                logger.info(f"   Getting frame: {frame_name}")
                
                # Get specific frame with full graph
                frame_response = self.client.kgentities.get_kgentity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=entity_uri,
                    frame_uris=[test_frame_uri]
                )
                
                # FrameGraphResponse.frame_graph is a FrameGraph container
                if frame_response.frame_graph and frame_response.frame_graph.objects:
                    frame_objects = frame_response.frame_graph.objects
                    
                    logger.info(f"   Retrieved frame with {len(frame_objects)} objects")
                    
                    # Count object types
                    object_types = {}
                    for obj in frame_objects:
                        obj_type = type(obj).__name__
                        object_types[obj_type] = object_types.get(obj_type, 0) + 1
                    
                    logger.info(f"   Object types: {object_types}")
                    logger.info(f"✅ PASS: Get specific frame")
                    results["tests_passed"] += 1
                else:
                    logger.error(f"   ❌ No frame graphs in response")
                    results["tests_failed"] += 1
                    results["errors"].append("No frame graphs in response")
                    
            except Exception as e:
                logger.error(f"❌ Error getting specific frame: {e}")
                import traceback
                logger.error(traceback.format_exc())
                results["tests_failed"] += 1
                results["errors"].append(f"Error getting specific frame: {str(e)}")
        
        # Test 3: Update frame (if child frames exist with slots)
        # Use results from comprehensive test to find a frame with slots
        if test_frame_uri:
            results["tests_run"] += 1
            
            try:
                logger.info(f"\n--- Update Frame ---\n")
                
                frame_name = test_frame_uri.split(':')[-2] if ':' in test_frame_uri else test_frame_uri
                logger.info(f"   Updating frame: {frame_name}")
                
                # Get the frame with complete graph using frame_uris parameter
                # Include parent_frame_uri if this is a child frame
                frame_response = self.client.kgentities.get_kgentity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=entity_uri,
                    frame_uris=[test_frame_uri],
                    parent_frame_uri=test_frame_parent if test_frame_parent else None
                )
                
                # FrameGraphResponse.frame_graph is a FrameGraph container
                if frame_response.frame_graph and frame_response.frame_graph.objects:
                    frame_objects = frame_response.frame_graph.objects
                    
                    logger.info(f"   Received {len(frame_objects)} objects in frame graph")
                    
                    # Find any slot to modify - prioritize common types
                    # Skip the first text slot to avoid conflict with child frame update test
                    updateable_slot = None
                    slot_type = None
                    old_value = None
                    new_value = None
                    text_slots_found = 0
                    
                    for obj in frame_objects:
                        obj_type = type(obj).__name__
                        # Try boolean first (most common in lead data - 58 slots)
                        if obj_type == 'KGBooleanSlot' and hasattr(obj, 'booleanSlotValue'):
                            updateable_slot = obj
                            slot_type = 'boolean'
                            old_value = obj.booleanSlotValue
                            new_value = not old_value
                            obj.booleanSlotValue = new_value
                            break
                        # Then text (56 slots) - skip first one to avoid conflict with child frame test
                        elif obj_type == 'KGTextSlot' and hasattr(obj, 'textSlotValue'):
                            text_slots_found += 1
                            if text_slots_found > 1:  # Use second text slot, not first
                                updateable_slot = obj
                                slot_type = 'text'
                                old_value = str(obj.textSlotValue) if obj.textSlotValue else ""
                                # Use a unique timestamp-based value to ensure we can verify the exact change
                                import time
                                new_value = f"TEST_UPDATE_{int(time.time() * 1000)}"
                                obj.textSlotValue = new_value
                                break
                        # Then integer (4 slots)
                        elif obj_type == 'KGIntegerSlot' and hasattr(obj, 'integerSlotValue'):
                            updateable_slot = obj
                            slot_type = 'integer'
                            old_value = int(obj.integerSlotValue) if obj.integerSlotValue else 0
                            new_value = old_value + 1
                            obj.integerSlotValue = new_value
                            break
                    
                    if updateable_slot:
                        logger.info(f"   Updating {slot_type} slot: {old_value} → {new_value}")
                        
                        # Update the frame - pass GraphObjects directly
                        update_response = self.client.kgentities.update_entity_frames(
                            space_id=space_id,
                            graph_id=graph_id,
                            entity_uri=entity_uri,
                            objects=frame_objects,
                            parent_frame_uri=test_frame_parent if test_frame_parent else None
                        )
                        
                        if update_response.is_success:
                            logger.info(f"   ✅ Frame updated successfully")
                            
                            # Verify the update - use same parent_frame_uri as the update
                            verify_response = self.client.kgentities.get_kgentity_frames(
                                space_id=space_id,
                                graph_id=graph_id,
                                entity_uri=entity_uri,
                                frame_uris=[test_frame_uri],
                                parent_frame_uri=test_frame_parent if test_frame_parent else None
                            )
                            
                            # FrameGraphResponse.frame_graph is a FrameGraph container
                            if verify_response.frame_graph and verify_response.frame_graph.objects:
                                verify_objects = verify_response.frame_graph.objects
                                
                                logger.info(f"   Verifying update: retrieved {len(verify_objects)} objects")
                                
                                # Find the updated slot
                                updated_slot = None
                                for obj in verify_objects:
                                    if str(obj.URI) == str(updateable_slot.URI):
                                        updated_slot = obj
                                        break
                                
                                if not updated_slot:
                                    logger.error(f"   ❌ Could not find updated slot with URI: {updateable_slot.URI}")
                                    logger.error(f"   Available URIs in verify response:")
                                    for obj in verify_objects:
                                        if hasattr(obj, 'URI'):
                                            logger.error(f"     - {obj.URI}")
                                
                                # Verify based on slot type
                                verified = False
                                if updated_slot:
                                    if slot_type == 'boolean':
                                        actual_value = bool(updated_slot.booleanSlotValue)
                                        verified = actual_value == new_value
                                        logger.info(f"   Verifying boolean: expected={new_value}, actual={actual_value}, verified={verified}")
                                    elif slot_type == 'text':
                                        actual_value = str(updated_slot.textSlotValue)
                                        verified = actual_value == new_value
                                        logger.info(f"   Verifying text: expected='{new_value}', actual='{actual_value}', verified={verified}")
                                    elif slot_type == 'integer':
                                        actual_value = int(updated_slot.integerSlotValue)
                                        verified = actual_value == new_value
                                        logger.info(f"   Verifying integer: expected={new_value}, actual={actual_value}, verified={verified}")
                                    elif slot_type == 'double':
                                        verified = abs(float(updated_slot.doubleSlotValue) - new_value) < 0.001
                                    elif slot_type == 'datetime':
                                        verified = int(updated_slot.dateTimeSlotValue) == new_value
                                    elif slot_type == 'currency':
                                        verified = abs(float(updated_slot.currencySlotValue) - new_value) < 0.01
                                    elif slot_type == 'choice':
                                        verified = str(updated_slot.choiceSlotValue) == new_value
                                    elif slot_type == 'multichoice':
                                        verified = updated_slot.multiChoiceSlotValue == new_value
                                    elif slot_type == 'json':
                                        verified = str(updated_slot.jsonSlotValue) == new_value
                                
                                if verified:
                                    logger.info(f"   ✅ Update verified: {new_value}")
                                    logger.info(f"✅ PASS: Update frame")
                                    results["tests_passed"] += 1
                                else:
                                    logger.error(f"   ❌ Update not verified")
                                    results["tests_failed"] += 1
                                    results["errors"].append("Update not verified")
                            else:
                                logger.error(f"   ❌ Could not verify update")
                                results["tests_failed"] += 1
                                results["errors"].append("Could not verify update")
                        else:
                            logger.error(f"   ❌ Update failed: {update_response.message}")
                            results["tests_failed"] += 1
                            results["errors"].append(f"Update failed: {update_response.message}")
                    else:
                        logger.error(f"   ❌ FAIL: No updateable slot found")
                        results["tests_failed"] += 1
                        results["errors"].append("No updateable slot found in frame")
                else:
                    logger.error(f"   ❌ Could not retrieve frame for update")
                    results["tests_failed"] += 1
                    results["errors"].append("Could not retrieve frame for update")
                    
            except Exception as e:
                logger.error(f"❌ Error updating frame: {e}")
                import traceback
                logger.error(traceback.format_exc())
                results["tests_failed"] += 1
                results["errors"].append(f"Error updating frame: {str(e)}")
        
        # Test 4: Delete frame and verify (if frames exist)
        if test_frame_uri:
            results["tests_run"] += 1
            
            try:
                logger.info(f"\n--- Delete Frame and Verify ---\n")
                
                frame_name = test_frame_uri.split(':')[-1]
                logger.info(f"   Deleting frame: {frame_name}")
                
                # Delete the frame (include parent_frame_uri for child frames)
                delete_response = self.client.kgentities.delete_entity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=entity_uri,
                    frame_uris=[test_frame_uri],
                    parent_frame_uri=test_frame_parent if test_frame_parent else None
                )
                
                if delete_response.is_success:
                    logger.info(f"   ✅ Frame deleted successfully")
                    
                    # Verify deletion by attempting to get the frame
                    verify_response = self.client.kgentities.get_kgentity_frames(
                        space_id=space_id,
                        graph_id=graph_id,
                        entity_uri=entity_uri,
                        frame_uris=[test_frame_uri]
                    )
                    
                    # Check if frame is not in response or returns error
                    # FrameGraphResponse.frame_graph should be None for deleted frame
                    if not verify_response.frame_graph or not verify_response.frame_graph.objects:
                        logger.info(f"   ✅ Deleted frame not found (as expected)")
                        logger.info(f"✅ PASS: Delete frame and verify")
                        results["tests_passed"] += 1
                    else:
                        logger.error(f"   ❌ Deleted frame still exists")
                        results["tests_failed"] += 1
                        results["errors"].append("Deleted frame still exists")
                else:
                    logger.error(f"   ❌ Delete failed: {delete_response.message}")
                    results["tests_failed"] += 1
                    results["errors"].append(f"Delete failed: {delete_response.message}")
                    
            except Exception as e:
                logger.error(f"❌ Error deleting frame: {e}")
                import traceback
                logger.error(traceback.format_exc())
                results["tests_failed"] += 1
                results["errors"].append(f"Error deleting frame: {str(e)}")
        
        # ====================================================================
        # CHILD FRAME TESTS - Test hierarchical frame operations
        # ====================================================================
        logger.info(f"\n{'='*100}")
        logger.info(f"  Child Frame Operations (Hierarchical)")
        logger.info(f"{'='*100}")
        
        # Test 5: List top-level frames (parent_frame_uri=None)
        results["tests_run"] += 1
        
        try:
            logger.info(f"\n--- List Top-Level Frames (No Parent) ---\n")
            
            # Get top-level frames (children of entity)
            top_frames_response = self.client.kgentities.get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                parent_frame_uri=None  # Explicitly request top-level frames
            )
            
            if top_frames_response.is_success and top_frames_response.objects:
                frame_objects = top_frames_response.objects
                logger.info(f"   Retrieved {len(frame_objects)} objects")
                
                # Extract frame URIs (only KGFrame objects)
                top_frame_uris = []
                for obj in frame_objects:
                    if type(obj).__name__ == 'KGFrame':
                        top_frame_uris.append(str(obj.URI))
                
                top_frame_count = len(top_frame_uris)
                logger.info(f"   Found {top_frame_count} top-level frames")
                
                if top_frame_count > 0:
                    logger.info(f"✅ PASS: List top-level frames")
                    results["tests_passed"] += 1
                    # Store parent frame for child tests - try to find one that likely has children
                    # Frames like companyframe, marketingframe, leadstatusframe typically have children
                    parent_frame_uri = None
                    for uri in top_frame_uris:
                        # Look for frames that typically have hierarchical structure
                        if any(name in uri.lower() for name in ['company', 'marketing', 'leadstatus', 'integration', 'personalguarantor', 'plaidbanking', 'lendersubmission', 'system']):
                            parent_frame_uri = uri
                            break
                    # Fallback to first frame if no hierarchical frame found
                    if not parent_frame_uri:
                        parent_frame_uri = top_frame_uris[0]
                else:
                    logger.error(f"   ❌ FAIL: No top-level frames found - expected frames to exist")
                    results["tests_failed"] += 1
                    results["errors"].append("No top-level frames found when frames should exist")
                    parent_frame_uri = None
            else:
                logger.error(f"   ❌ FAIL: No top-level frames response - expected frames to exist")
                results["tests_failed"] += 1
                results["errors"].append("No top-level frames response when frames should exist")
                parent_frame_uri = None
                
        except Exception as e:
            logger.error(f"❌ Error listing top-level frames: {e}")
            import traceback
            logger.error(traceback.format_exc())
            results["tests_failed"] += 1
            results["errors"].append(f"Error listing top-level frames: {str(e)}")
            parent_frame_uri = None
        
        # Test 6: List child frames of a parent frame
        if parent_frame_uri:
            results["tests_run"] += 1
            
            try:
                logger.info(f"\n--- List Child Frames of Parent ---\n")
                
                parent_name = parent_frame_uri.split(':')[-1]
                logger.info(f"   Parent frame: {parent_name}")
                
                # Get child frames of the parent
                child_response = self.client.kgentities.get_kgentity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=entity_uri,
                    parent_frame_uri=parent_frame_uri  # Filter by parent
                )
                
                if child_response.is_success and child_response.objects:
                    child_frame_objects = child_response.objects
                    
                    # Extract frame URIs (only KGFrame objects)
                    child_frame_uris = []
                    for obj in child_frame_objects:
                        if type(obj).__name__ == 'KGFrame':
                            child_frame_uris.append(str(obj.URI))
                    
                    child_frame_count = len(child_frame_uris)
                    logger.info(f"   Found {child_frame_count} child frames")
                    
                    # Based on Edge_hasKGFrame objects in entity graph, there should be child frames
                    if child_frame_count > 0:
                        logger.info(f"✅ PASS: List child frames")
                        results["tests_passed"] += 1
                        # Use second child frame to avoid conflict with delete test (which uses first)
                        test_child_frame_uri = child_frame_uris[1] if len(child_frame_uris) > 1 else child_frame_uris[0]
                    else:
                        logger.error(f"   ❌ FAIL: No child frames found - expected hierarchical frame structure")
                        results["tests_failed"] += 1
                        results["errors"].append("No child frames found when hierarchical structure expected")
                        test_child_frame_uri = None
                else:
                    logger.error(f"   ❌ FAIL: No child frames response - expected hierarchical frame structure")
                    results["tests_failed"] += 1
                    results["errors"].append("No child frames response when hierarchical structure expected")
                    test_child_frame_uri = None
                    
            except Exception as e:
                logger.error(f"❌ Error listing child frames: {e}")
                import traceback
                logger.error(traceback.format_exc())
                results["tests_failed"] += 1
                results["errors"].append(f"Error listing child frames: {str(e)}")
                test_child_frame_uri = None
        else:
            test_child_frame_uri = None
        
        # Test 7: Get specific child frame with parent validation
        if test_child_frame_uri and parent_frame_uri:
            results["tests_run"] += 1
            
            try:
                logger.info(f"\n--- Get Child Frame with Parent Validation ---\n")
                
                child_name = test_child_frame_uri.split(':')[-1]
                parent_name = parent_frame_uri.split(':')[-1]
                logger.info(f"   Getting child frame: {child_name}")
                logger.info(f"   With parent: {parent_name}")
                
                # Get specific child frame with parent validation
                child_response = self.client.kgentities.get_kgentity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=entity_uri,
                    frame_uris=[test_child_frame_uri],
                    parent_frame_uri=parent_frame_uri  # Validate parent-child relationship
                )
                
                # FrameGraphResponse.frame_graph is a FrameGraph container
                if child_response.frame_graph and child_response.frame_graph.objects:
                    frame_objects = child_response.frame_graph.objects
                    
                    logger.info(f"   Retrieved child frame with {len(frame_objects)} objects")
                    logger.info(f"✅ PASS: Get child frame with parent validation")
                    results["tests_passed"] += 1
                else:
                    logger.error(f"   ❌ No frame graphs in response")
                    results["tests_failed"] += 1
                    results["errors"].append("No frame graphs in child response")
                    
            except Exception as e:
                logger.error(f"❌ Error getting child frame: {e}")
                import traceback
                logger.error(traceback.format_exc())
                results["tests_failed"] += 1
                results["errors"].append(f"Error getting child frame: {str(e)}")
        
        # Test 8: Update child frame with parent scoping
        if test_child_frame_uri and parent_frame_uri:
            results["tests_run"] += 1
            
            try:
                logger.info(f"\n--- Update Child Frame with Parent Scoping ---\n")
                
                child_name = test_child_frame_uri.split(':')[-1]
                parent_name = parent_frame_uri.split(':')[-1]
                logger.info(f"   Updating child frame: {child_name}")
                logger.info(f"   Scoped to parent: {parent_name}")
                
                # First get the child frame
                frame_response = self.client.kgentities.get_kgentity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=entity_uri,
                    frame_uris=[test_child_frame_uri]
                )
                
                # FrameGraphResponse.frame_graph is a FrameGraph container
                if frame_response.frame_graph and frame_response.frame_graph.objects:
                    frame_objects = frame_response.frame_graph.objects
                    
                    # Log what objects we received
                    logger.info(f"   Received {len(frame_objects)} objects in child frame")
                    object_types = {}
                    for obj in frame_objects:
                        obj_type = type(obj).__name__
                        object_types[obj_type] = object_types.get(obj_type, 0) + 1
                    logger.info(f"   Object types: {object_types}")
                    
                    # Log all objects in detail
                    import json
                    for i, obj in enumerate(frame_objects):
                        obj_json = obj.to_json()
                        logger.info(f"   Object {i+1}: {json.dumps(json.loads(obj_json), indent=2)}")
                    
                    # Find any slot to update (text, boolean, integer, etc.)
                    updateable_slot = None
                    slot_type = None
                    
                    for obj in frame_objects:
                        obj_type = type(obj).__name__
                        if obj_type == 'KGTextSlot' and hasattr(obj, 'textSlotValue'):
                            updateable_slot = obj
                            slot_type = 'text'
                            old_value = str(obj.textSlotValue) if obj.textSlotValue else ""
                            import time
                            new_value = f"CHILD_TEST_{int(time.time() * 1000)}"
                            obj.textSlotValue = new_value
                            break
                        elif obj_type == 'KGBooleanSlot' and hasattr(obj, 'booleanSlotValue'):
                            updateable_slot = obj
                            slot_type = 'boolean'
                            old_value = obj.booleanSlotValue
                            new_value = not old_value
                            obj.booleanSlotValue = new_value
                            break
                        elif obj_type == 'KGIntegerSlot' and hasattr(obj, 'integerSlotValue'):
                            updateable_slot = obj
                            slot_type = 'integer'
                            old_value = int(obj.integerSlotValue) if obj.integerSlotValue else 0
                            new_value = old_value + 100
                            obj.integerSlotValue = new_value
                            break
                        elif obj_type == 'KGCurrencySlot' and hasattr(obj, 'currencySlotValue'):
                            updateable_slot = obj
                            slot_type = 'currency'
                            old_value = float(obj.currencySlotValue) if obj.currencySlotValue else 0.0
                            new_value = old_value + 5000.0
                            obj.currencySlotValue = new_value
                            break
                        elif obj_type == 'KGDoubleSlot' and hasattr(obj, 'doubleSlotValue'):
                            updateable_slot = obj
                            slot_type = 'double'
                            old_value = float(obj.doubleSlotValue) if obj.doubleSlotValue else 0.0
                            new_value = old_value + 10.5
                            obj.doubleSlotValue = new_value
                            break
                    
                    if updateable_slot:
                        logger.info(f"   Updating {slot_type} slot: {old_value} → {new_value}")
                        
                        # Update with parent scoping - pass GraphObjects directly
                        update_response = self.client.kgentities.update_entity_frames(
                            space_id=space_id,
                            graph_id=graph_id,
                            entity_uri=entity_uri,
                            objects=frame_objects,
                            parent_frame_uri=parent_frame_uri  # Scope to parent
                        )
                        
                        if update_response.is_success:
                            logger.info(f"   ✅ Child frame updated with parent scoping")
                            logger.info(f"✅ PASS: Update child frame with parent scoping")
                            results["tests_passed"] += 1
                        else:
                            logger.error(f"   ❌ Update failed (error {update_response.error_code}): {update_response.error_message}")
                            results["tests_failed"] += 1
                            results["errors"].append(f"Child update failed: {update_response.error_message}")
                    else:
                        logger.error(f"   ❌ FAIL: No updateable slot in child frame")
                        results["tests_failed"] += 1
                        results["errors"].append("No updateable slot found in child frame")
                else:
                    logger.error(f"   ❌ Could not retrieve child frame")
                    results["tests_failed"] += 1
                    results["errors"].append("Could not retrieve child frame")
                    
            except Exception as e:
                logger.error(f"❌ Error updating child frame: {e}")
                import traceback
                logger.error(traceback.format_exc())
                results["tests_failed"] += 1
                results["errors"].append(f"Error updating child frame: {str(e)}")
        
        # Test 9: Delete child frame with parent validation
        if test_child_frame_uri and parent_frame_uri:
            results["tests_run"] += 1
            
            try:
                logger.info(f"\n--- Delete Child Frame with Parent Validation ---\n")
                
                child_name = test_child_frame_uri.split(':')[-1]
                parent_name = parent_frame_uri.split(':')[-1]
                logger.info(f"   Deleting child frame: {child_name}")
                logger.info(f"   With parent validation: {parent_name}")
                
                # Delete child frame with parent validation
                delete_response = self.client.kgentities.delete_entity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=entity_uri,
                    frame_uris=[test_child_frame_uri],
                    parent_frame_uri=parent_frame_uri  # Validate parent-child before deletion
                )
                
                if delete_response.is_success:
                    logger.info(f"   ✅ Child frame deleted with parent validation")
                    logger.info(f"✅ PASS: Delete child frame with parent validation")
                    results["tests_passed"] += 1
                else:
                    logger.error(f"   ❌ Delete failed: {delete_response.message}")
                    results["tests_failed"] += 1
                    results["errors"].append(f"Child delete failed: {delete_response.message}")
                    
            except Exception as e:
                logger.error(f"❌ Error deleting child frame: {e}")
                import traceback
                logger.error(traceback.format_exc())
                results["tests_failed"] += 1
                results["errors"].append(f"Error deleting child frame: {str(e)}")
        
        # Test 10: Negative test - Try to delete with wrong parent
        if parent_frame_uri and top_frame_uris and len(top_frame_uris) > 1:
            results["tests_run"] += 1
            
            try:
                logger.info(f"\n--- Negative Test: Delete with Wrong Parent ---\n")
                
                # Use a different top-level frame as "wrong parent"
                wrong_parent_uri = top_frame_uris[1]
                # Try to delete the first top-level frame claiming it's a child of the second
                target_frame_uri = top_frame_uris[0]
                
                wrong_parent_name = wrong_parent_uri.split(':')[-1]
                target_name = target_frame_uri.split(':')[-1]
                
                logger.info(f"   Attempting to delete: {target_name}")
                logger.info(f"   With wrong parent: {wrong_parent_name}")
                
                # This should fail validation
                delete_response = self.client.kgentities.delete_entity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=entity_uri,
                    frame_uris=[target_frame_uri],
                    parent_frame_uri=wrong_parent_uri  # Wrong parent!
                )
                
                # Should fail
                if not delete_response.is_success:
                    logger.info(f"   ✅ Delete correctly rejected (wrong parent)")
                    logger.info(f"   Message: {delete_response.message}")
                    logger.info(f"✅ PASS: Negative test - wrong parent rejected")
                    results["tests_passed"] += 1
                else:
                    logger.error(f"   ❌ Delete succeeded when it should have failed!")
                    results["tests_failed"] += 1
                    results["errors"].append("Delete with wrong parent should have failed")
                    
            except Exception as e:
                logger.error(f"❌ Error in negative test: {e}")
                import traceback
                logger.error(traceback.format_exc())
                results["tests_failed"] += 1
                results["errors"].append(f"Error in negative test: {str(e)}")
        
        return results
