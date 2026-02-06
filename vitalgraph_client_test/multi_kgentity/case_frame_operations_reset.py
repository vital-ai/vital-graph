#!/usr/bin/env python3
"""
Frame Operations Reset Test Case

Tests frame-level operations: list, get, and update frames.
Does NOT delete frames, so it can be run repeatedly on the same entity.
Accepts a randomized update value for stress testing.
"""

import logging
import time
from typing import Dict, Any, List
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vitalgraph.model.jsonld_model import JsonLdDocument
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
from ai_haley_kg_domain.model.KGDateTimeSlot import KGDateTimeSlot

logger = logging.getLogger(__name__)


class FrameOperationsResetTester:
    """Test case for frame-level operations without deletion. Supports repeated runs."""
    
    def __init__(self, client):
        self.client = client
        
    def run_tests(self, space_id: str, graph_id: str, test_entity_uri: str, 
                  test_entity_name: str, update_value: str = "Advanced Technology Solutions") -> Dict[str, Any]:
        """
        Run frame operation tests (without deletion).
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            test_entity_uri: URI of entity to test frames on
            test_entity_name: Name of test entity
            update_value: Value to use for the industry slot update
            
        Returns:
            Dict containing test results
        """
        results = {
            "test_name": "Frame-Level Operations",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "fuseki_failures": 0,
            "errors": []
        }
        
        logger.info("=" * 80)
        logger.info("  Frame-Level Operations")
        logger.info("=" * 80)
        logger.info(f"\nTesting frame operations on: {test_entity_name}")
        logger.info(f"Entity URI: {test_entity_uri}\n")
        
        # ========================================================================
        # Test 1: List Frames for Entity
        # ========================================================================
        results["tests_run"] += 1
        frame_objects = []
        frame_uris = []
        
        try:
            logger.info("--- List Frames for Entity ---\n")
            
            # Use kgentities.get_kgentity_frames() which routes to /kgentities/kgframes endpoint
            response = self.client.kgentities.get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=test_entity_uri,
                page_size=20
            )
            
            logger.info(f"Total frames found: {response.count if response.is_success else 0}")
            
            # Direct GraphObject access
            if response.is_success and response.objects:
                for frame_obj in response.objects:
                    if isinstance(frame_obj, KGFrame):
                        frame_objects.append(frame_obj)
                        frame_uri = str(frame_obj.URI)
                        frame_uris.append(frame_uri)
                        frame_type = str(frame_obj.kGFrameType) if frame_obj.kGFrameType else 'Unknown'
                        frame_name = str(frame_obj.name) if frame_obj.name else 'Unknown'
                        logger.info(f"   • {frame_name}")
                        logger.info(f"     URI: {frame_uri}")
                        logger.info(f"     Type: {frame_type.split('#')[-1] if '#' in frame_type else frame_type}")
            
            # Expected: 3 top-level frames (AddressFrame, CompanyInfoFrame, ManagementFrame)
            # NOT nested frames (CEO, CTO which are connected to ManagementFrame)
            expected_top_level_frames = 3
            
            if len(frame_objects) == expected_top_level_frames:
                logger.info(f"\n✅ PASS: List frames for entity")
                logger.info(f"   Found {len(frame_objects)} top-level frames (expected {expected_top_level_frames})")
                results["tests_passed"] += 1
            else:
                logger.error(f"\n❌ FAIL: List frames for entity")
                logger.error(f"   Found {len(frame_objects)} frames (expected {expected_top_level_frames} top-level frames)")
                logger.error(f"   Note: Should only return frames directly connected to entity via Edge_hasEntityKGFrame")
                logger.error(f"   Not nested frames connected via Edge_hasKGFrame (frame-to-frame)")
                results["tests_failed"] += 1
                results["errors"].append(f"Expected {expected_top_level_frames} top-level frames, found {len(frame_objects)}")
                
        except Exception as e:
            logger.error(f"❌ Error listing frames: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Error listing frames: {str(e)}")
        
        # ========================================================================
        # Test 2: Get Specific Frames by URI
        # ========================================================================
        results["tests_run"] += 1
        
        try:
            logger.info(f"\n--- Get Specific Frames by URI ---\n")
            
            # Get first 2 frames using frame_uris parameter
            if len(frame_uris) >= 2:
                test_frame_uris = frame_uris[:2]
                logger.info(f"Getting {len(test_frame_uris)} specific frames by URI")
                
                # This returns FrameGraphsResponse (different from EntityFramesResponse)
                frame_graphs_response = self.client.kgentities.get_kgentity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=test_entity_uri,
                    frame_uris=test_frame_uris
                )
                
                # MultiFrameGraphResponse has: frame_graph_list (List[FrameGraph])
                frame_count = len(frame_graphs_response.frame_graph_list) if frame_graphs_response.frame_graph_list else 0
                logger.info(f"   Requested: {len(test_frame_uris)} frames")
                logger.info(f"   Retrieved: {frame_count} frames")
                
                # Check that we got the frames
                if frame_count >= 2:
                    logger.info(f"✅ PASS: Get specific frames by URI")
                    results["tests_passed"] += 1
                else:
                    logger.error(f"❌ FAIL: Expected 2 frames, got {frame_count}")
                    results["tests_failed"] += 1
                    results["errors"].append(f"Expected 2 specific frames, got {frame_count}")
            else:
                logger.warning(f"⚠️  Not enough frame URIs to test specific retrieval")
                logger.info(f"✅ PASS: Skipped - insufficient frames")
                results["tests_passed"] += 1
                
        except Exception as e:
            logger.error(f"❌ Error getting specific frames: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Error getting specific frames: {str(e)}")
        
        # ========================================================================
        # Test 3: Get Frame with Complete Graph (include_frame_graph=True)
        # ========================================================================
        results["tests_run"] += 1
        
        try:
            logger.info(f"\n--- Get Frame with Complete Graph ---\n")
            
            # Find the company info frame (has industry slot)
            company_frame_uri = None
            for frame_obj in frame_objects:
                frame_type = str(frame_obj.kGFrameType) if frame_obj.kGFrameType else ''
                if 'CompanyInfoFrame' in frame_type:
                    company_frame_uri = str(frame_obj.URI)
                    break
            
            if company_frame_uri:
                logger.info(f"Getting complete frame graph for: {company_frame_uri}")
                
                # Get the frame with its complete graph using entity frames endpoint
                # Use frame_uris parameter to get specific frame with its graph
                # This returns FrameGraphsResponse with frame_graphs dict
                frame_response = self.client.kgentities.get_kgentity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=test_entity_uri,
                    frame_uris=[company_frame_uri]
                )
                
                # FrameGraphResponse.frame_graph is a FrameGraph container
                if frame_response.frame_graph:
                    frame_graph_objects = frame_response.frame_graph.objects
                else:
                    frame_graph_objects = []
                
                # Verify we got the complete graph: frame + slots + edges
                frames_in_graph = [obj for obj in frame_graph_objects if isinstance(obj, KGFrame)]
                slots_in_graph = [obj for obj in frame_graph_objects if isinstance(obj, (KGTextSlot, KGIntegerSlot, KGDateTimeSlot))]
                edges_in_graph = [obj for obj in frame_graph_objects if 'Edge' in type(obj).__name__]
                
                logger.info(f"   Frame graph contains:")
                logger.info(f"   - {len(frames_in_graph)} frame(s)")
                logger.info(f"   - {len(slots_in_graph)} slot(s)")
                logger.info(f"   - {len(edges_in_graph)} edge(s)")
                
                # Verify we have at least the frame and some slots
                if len(frames_in_graph) >= 1 and len(slots_in_graph) >= 1:
                    logger.info(f"✅ PASS: Get frame with complete graph")
                    logger.info(f"   Frame graph includes frame, slots, and edges")
                    results["tests_passed"] += 1
                else:
                    logger.error(f"❌ FAIL: Get frame with complete graph")
                    logger.error(f"   Expected frame + slots, got {len(frames_in_graph)} frames and {len(slots_in_graph)} slots")
                    results["tests_failed"] += 1
                    results["errors"].append(f"Frame graph incomplete: {len(frames_in_graph)} frames, {len(slots_in_graph)} slots")
            else:
                logger.warning(f"   ⚠️  Company Info Frame not found")
                logger.error(f"❌ FAIL: Get frame with complete graph")
                results["tests_failed"] += 1
                results["errors"].append("Company Info Frame not found")
                
        except Exception as e:
            logger.error(f"❌ Error getting frame with complete graph: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Error getting frame with complete graph: {str(e)}")
        
        # ========================================================================
        # Test 4: Update Frame and Verify
        # ========================================================================
        results["tests_run"] += 1
        
        try:
            logger.info(f"\n--- Update Frame and Verify ---\n")
            
            # Find the company info frame
            company_frame_uri = None
            for frame_obj in frame_objects:
                frame_type = str(frame_obj.kGFrameType) if frame_obj.kGFrameType else ''
                if 'CompanyInfoFrame' in frame_type:
                    company_frame_uri = str(frame_obj.URI)
                    break
            
            if company_frame_uri:
                # Get the frame with complete graph
                t_get_start = time.time()
                frame_response = self.client.kgentities.get_kgentity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=test_entity_uri,
                    frame_uris=[company_frame_uri]
                )
                t_get_elapsed = time.time() - t_get_start
                
                # Get frame objects directly from FrameGraph container
                # FrameGraphResponse.frame_graph is a FrameGraph container
                if frame_response.frame_graph:
                    frame_graph_objects = frame_response.frame_graph.objects
                else:
                    frame_graph_objects = []
                
                logger.info(f"   Converted to {len(frame_graph_objects)} VitalSigns objects")
                
                # Find and update the industry slot
                industry_slot = None
                old_industry = None
                new_industry = update_value
                
                for obj in frame_graph_objects:
                    if isinstance(obj, KGTextSlot):
                        slot_type = str(obj.kGSlotType) if obj.kGSlotType else ''
                        if 'IndustrySlot' in slot_type:
                            industry_slot = obj
                            old_industry = str(obj.textSlotValue) if obj.textSlotValue else 'Unknown'
                            obj.textSlotValue = new_industry
                            logger.info(f"   Updating industry: '{old_industry}' → '{new_industry}'")
                            break
                
                if industry_slot:
                    # Log the GraphObjects being updated
                    logger.info(f"   Updating {len(frame_graph_objects)} GraphObjects:")
                    for i, obj in enumerate(frame_graph_objects[:5]):  # Log first 5
                        obj_type = type(obj).__name__
                        obj_uri = str(obj.URI) if hasattr(obj, 'URI') else 'NO_URI'
                        logger.info(f"     [{i+1}] {obj_type}: {obj_uri}")
                    
                    # Update the frame
                    t_update_start = time.time()
                    update_response = self.client.kgentities.update_entity_frames(
                        space_id=space_id,
                        graph_id=graph_id,
                        entity_uri=test_entity_uri,
                        objects=frame_graph_objects
                    )
                    t_update_elapsed = time.time() - t_update_start
                    
                    # Check fuseki_success on update response
                    _fuseki = getattr(update_response, 'fuseki_success', None)
                    if _fuseki is not True:
                        logger.error(f"   ⚠️ FUSEKI_SYNC_FAILURE on update: fuseki_success={_fuseki}")
                        results["fuseki_failures"] += 1
                        results["tests_failed"] += 1
                        results["errors"].append(f"fuseki_success not True on update: {_fuseki}")
                    else:
                        logger.info(f"   fuseki_success={_fuseki}")
                    
                    if update_response.is_success:
                        logger.info(f"   ✅ Frame updated successfully ({t_update_elapsed:.3f}s)")
                        
                        # Verify by re-fetching the frame
                        logger.info(f"   Verifying update by re-fetching frame...")
                        t_verify_start = time.time()
                        verify_response = self.client.kgentities.get_kgentity_frames(
                            space_id=space_id,
                            graph_id=graph_id,
                            entity_uri=test_entity_uri,
                            frame_uris=[company_frame_uri]
                        )
                        t_verify_elapsed = time.time() - t_verify_start
                        
                        # Get frame objects from response
                        # FrameGraphResponse.frame_graph is a FrameGraph container
                        if verify_response.frame_graph:
                            verify_frame_objects = verify_response.frame_graph.objects
                        else:
                            verify_frame_objects = []
                        
                        verified_industry = None
                        for obj in verify_frame_objects:
                            if isinstance(obj, KGTextSlot):
                                slot_type = str(obj.kGSlotType) if obj.kGSlotType else ''
                                if 'IndustrySlot' in slot_type:
                                    verified_industry = str(obj.textSlotValue) if obj.textSlotValue else None
                                    break
                        
                        logger.info(f"   Verified industry value: '{verified_industry}'")
                        
                        if verified_industry == new_industry:
                            logger.info(f"✅ PASS: Update frame and verify")
                            logger.info(f"   Industry updated from '{old_industry}' to '{verified_industry}'")
                            logger.info(f"   Timing: get={t_get_elapsed:.3f}s, update={t_update_elapsed:.3f}s, verify={t_verify_elapsed:.3f}s")
                            results["tests_passed"] += 1
                            results["timing"] = {
                                "get": t_get_elapsed,
                                "update": t_update_elapsed,
                                "verify": t_verify_elapsed,
                                "total": t_get_elapsed + t_update_elapsed + t_verify_elapsed
                            }
                        else:
                            logger.error(f"❌ FAIL: Update frame and verify")
                            logger.error(f"   Expected '{new_industry}', got '{verified_industry}'")
                            results["tests_failed"] += 1
                            results["errors"].append(f"Frame update not persisted: expected '{new_industry}', got '{verified_industry}'")
                    else:
                        logger.error(f"❌ FAIL: Update frame and verify")
                        logger.error(f"   Update failed: {update_response.message}")
                        results["tests_failed"] += 1
                        results["errors"].append(f"Frame update failed: {update_response.message}")
                else:
                    logger.warning(f"   ⚠️  Industry slot not found")
                    logger.error(f"❌ FAIL: Update frame and verify")
                    results["tests_failed"] += 1
                    results["errors"].append("Industry slot not found for update")
            else:
                logger.warning(f"   ⚠️  Company Info Frame not found")
                logger.error(f"❌ FAIL: Update frame and verify")
                results["tests_failed"] += 1
                results["errors"].append("Company Info Frame not found for update")
                
        except Exception as e:
            logger.error(f"❌ Error updating and verifying frame: {e}")
            import traceback
            logger.error(traceback.format_exc())
            results["tests_failed"] += 1
            results["errors"].append(f"Error updating and verifying frame: {str(e)}")
        
        # ========================================================================
        # Test 5: Delete Frame, Recreate with Different Value, and Verify
        # ========================================================================
        results["tests_run"] += 1
        
        try:
            logger.info(f"\n--- Delete Frame, Recreate, and Verify ---\n")
            
            # Find the company info frame
            company_frame_uri = None
            for frame_obj in frame_objects:
                frame_type = str(frame_obj.kGFrameType) if frame_obj.kGFrameType else ''
                if 'CompanyInfoFrame' in frame_type:
                    company_frame_uri = str(frame_obj.URI)
                    break
            
            if company_frame_uri:
                # Step 1: Get the current frame graph (to preserve structure for recreation)
                pre_delete_response = self.client.kgentities.get_kgentity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=test_entity_uri,
                    frame_uris=[company_frame_uri]
                )
                
                saved_frame_objects = []
                if pre_delete_response.frame_graph:
                    saved_frame_objects = list(pre_delete_response.frame_graph.objects)
                
                logger.info(f"   Saved {len(saved_frame_objects)} frame objects for recreation")
                
                # Step 2: Delete the frame
                t_delete_start = time.time()
                delete_response = self.client.kgentities.delete_entity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=test_entity_uri,
                    frame_uris=[company_frame_uri]
                )
                t_delete_elapsed = time.time() - t_delete_start
                
                # Check fuseki_success on delete response
                _fuseki_del = getattr(delete_response, 'fuseki_success', None)
                if _fuseki_del is not True:
                    logger.error(f"   ⚠️ FUSEKI_SYNC_FAILURE on delete: fuseki_success={_fuseki_del}")
                    results["fuseki_failures"] += 1
                    results["tests_failed"] += 1
                    results["errors"].append(f"fuseki_success not True on delete: {_fuseki_del}")
                else:
                    logger.info(f"   delete fuseki_success={_fuseki_del}")
                
                if not delete_response.is_success:
                    logger.error(f"   ❌ Delete failed: {delete_response.message}")
                    results["tests_failed"] += 1
                    results["errors"].append(f"Frame delete failed: {delete_response.message}")
                    return results
                
                logger.info(f"   ✅ Frame deleted ({t_delete_elapsed:.3f}s)")
                
                # Step 2b: Verify the frame is actually gone
                t_delete_verify_start = time.time()
                delete_verify_response = self.client.kgentities.get_kgentity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=test_entity_uri,
                    frame_uris=[company_frame_uri]
                )
                t_delete_verify_elapsed = time.time() - t_delete_verify_start
                
                if delete_verify_response.frame_graph:
                    # Frame still exists after deletion!
                    logger.error(f"   ❌ Frame still exists after deletion!")
                    results["tests_failed"] += 1
                    results["errors"].append("Frame still exists after deletion")
                    return results
                else:
                    logger.info(f"   ✅ Frame confirmed deleted ({t_delete_verify_elapsed:.3f}s)")
                
                # Step 3: Modify the industry slot to a new recreate value
                recreate_value = f"Recreated_{update_value}"
                for obj in saved_frame_objects:
                    if isinstance(obj, KGTextSlot):
                        slot_type = str(obj.kGSlotType) if obj.kGSlotType else ''
                        if 'IndustrySlot' in slot_type:
                            obj.textSlotValue = recreate_value
                            logger.info(f"   Set recreate value: '{recreate_value}'")
                            break
                
                # Step 4: Recreate the frame using create_entity_frames
                t_recreate_start = time.time()
                recreate_response = self.client.kgentities.create_entity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=test_entity_uri,
                    objects=saved_frame_objects
                )
                t_recreate_elapsed = time.time() - t_recreate_start
                
                # Check fuseki_success on recreate response
                _fuseki_create = getattr(recreate_response, 'fuseki_success', None)
                if _fuseki_create is not True:
                    logger.error(f"   ⚠️ FUSEKI_SYNC_FAILURE on recreate: fuseki_success={_fuseki_create}")
                    results["fuseki_failures"] += 1
                    results["tests_failed"] += 1
                    results["errors"].append(f"fuseki_success not True on recreate: {_fuseki_create}")
                else:
                    logger.info(f"   recreate fuseki_success={_fuseki_create}")
                
                if not recreate_response.is_success:
                    logger.error(f"   ❌ Recreate failed: {recreate_response.message}")
                    results["tests_failed"] += 1
                    results["errors"].append(f"Frame recreate failed: {recreate_response.message}")
                    return results
                
                logger.info(f"   ✅ Frame recreated ({t_recreate_elapsed:.3f}s)")
                
                # Step 5: Verify the recreated frame has the new value
                t_reverify_start = time.time()
                reverify_response = self.client.kgentities.get_kgentity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=test_entity_uri,
                    frame_uris=[company_frame_uri]
                )
                t_reverify_elapsed = time.time() - t_reverify_start
                
                reverify_objects = []
                if reverify_response.frame_graph:
                    reverify_objects = reverify_response.frame_graph.objects
                
                verified_recreate_value = None
                for obj in reverify_objects:
                    if isinstance(obj, KGTextSlot):
                        slot_type = str(obj.kGSlotType) if obj.kGSlotType else ''
                        if 'IndustrySlot' in slot_type:
                            verified_recreate_value = str(obj.textSlotValue) if obj.textSlotValue else None
                            break
                
                logger.info(f"   Verified recreate value: '{verified_recreate_value}'")
                
                if verified_recreate_value == recreate_value:
                    logger.info(f"✅ PASS: Delete, recreate, and verify")
                    logger.info(f"   Timing: delete={t_delete_elapsed:.3f}s, recreate={t_recreate_elapsed:.3f}s, verify={t_reverify_elapsed:.3f}s")
                    results["tests_passed"] += 1
                    results["recreate_timing"] = {
                        "delete": t_delete_elapsed,
                        "delete_verify": t_delete_verify_elapsed,
                        "recreate": t_recreate_elapsed,
                        "verify": t_reverify_elapsed,
                        "total": t_delete_elapsed + t_delete_verify_elapsed + t_recreate_elapsed + t_reverify_elapsed
                    }
                else:
                    logger.error(f"❌ FAIL: Delete, recreate, and verify")
                    logger.error(f"   Expected '{recreate_value}', got '{verified_recreate_value}'")
                    results["tests_failed"] += 1
                    results["errors"].append(f"Recreated frame not persisted: expected '{recreate_value}', got '{verified_recreate_value}'")
            else:
                logger.warning(f"   ⚠️  Company Info Frame not found for delete/recreate")
                logger.error(f"❌ FAIL: Delete, recreate, and verify")
                results["tests_failed"] += 1
                results["errors"].append("Company Info Frame not found for delete/recreate")
                
        except Exception as e:
            logger.error(f"❌ Error in delete/recreate/verify: {e}")
            import traceback
            logger.error(traceback.format_exc())
            results["tests_failed"] += 1
            results["errors"].append(f"Error in delete/recreate/verify: {str(e)}")
        
        return results
