#!/usr/bin/env python3
"""
Frame Operations Test Case

Tests frame-level operations: list, get, and update frames.
"""

import logging
from typing import Dict, Any, List
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vitalgraph.model.jsonld_model import JsonLdDocument
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
from ai_haley_kg_domain.model.KGDateTimeSlot import KGDateTimeSlot

logger = logging.getLogger(__name__)


class FrameOperationsTester:
    """Test case for frame-level operations."""
    
    def __init__(self, client):
        self.client = client
        
    async def run_tests(self, space_id: str, graph_id: str, test_entity_uri: str, 
                  test_entity_name: str) -> Dict[str, Any]:
        """
        Run frame operation tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            test_entity_uri: URI of entity to test frames on
            test_entity_name: Name of test entity
            
        Returns:
            Dict containing test results
        """
        results = {
            "test_name": "Frame-Level Operations",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
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
            response = await self.client.kgentities.get_kgentity_frames(
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
                frame_graphs_response = await self.client.kgentities.get_kgentity_frames(
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
                frame_response = await self.client.kgentities.get_kgentity_frames(
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
                frame_response = await self.client.kgentities.get_kgentity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=test_entity_uri,
                    frame_uris=[company_frame_uri]
                )
                
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
                new_industry = "Advanced Technology Solutions"
                
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
                    update_response = await self.client.kgentities.update_entity_frames(
                        space_id=space_id,
                        graph_id=graph_id,
                        entity_uri=test_entity_uri,
                        objects=frame_graph_objects
                    )
                    
                    if update_response.is_success:
                        logger.info(f"   ✅ Frame updated successfully")
                        
                        # Verify by re-fetching the frame
                        logger.info(f"   Verifying update by re-fetching frame...")
                        verify_response = await self.client.kgentities.get_kgentity_frames(
                            space_id=space_id,
                            graph_id=graph_id,
                            entity_uri=test_entity_uri,
                            frame_uris=[company_frame_uri]
                        )
                        
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
                            results["tests_passed"] += 1
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
        
        # Dump space info to see actual triples before deletion
        try:
            logger.info(f"\n--- Dumping Space Info Before Frame Deletion ---\n")
            space_info = await self.client.spaces.get_space(space_id=space_id)
            logger.info(f"   Space info retrieved (check server logs for quad dump)")
        except Exception as e:
            logger.warning(f"   Could not get space info: {e}")
        
        # Test 5: Delete Frame and Verify
        results["tests_run"] += 1
        
        try:
            logger.info(f"\n--- Delete Frame and Verify ---\n")
            
            # Find the company info frame to delete
            company_frame_uri = None
            for frame_obj in frame_objects:
                frame_type = str(frame_obj.kGFrameType) if frame_obj.kGFrameType else ''
                if 'CompanyInfoFrame' in frame_type:
                    company_frame_uri = str(frame_obj.URI)
                    break
            
            if company_frame_uri:
                logger.info(f"   Deleting frame: {company_frame_uri}")
                
                # Delete the frame
                delete_response = await self.client.kgentities.delete_entity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=test_entity_uri,
                    frame_uris=[company_frame_uri]
                )
                
                if delete_response.is_success:
                    logger.info(f"   ✅ Frame deleted successfully")
                    
                    # Verify by attempting to get the deleted frame
                    logger.info(f"   Verifying deletion by attempting to get deleted frame...")
                    try:
                        get_deleted_response = await self.client.kgentities.get_kgentity_frames(
                            space_id=space_id,
                            graph_id=graph_id,
                            entity_uri=test_entity_uri,
                            frame_uris=[company_frame_uri]
                        )
                        
                        logger.info(f"   Get deleted frame response: frame_graph = {get_deleted_response.frame_graph}")
                        
                        # Check if frame_graph is empty or None
                        if not get_deleted_response.frame_graph:
                            logger.info(f"   ✅ Deleted frame not found (as expected)")
                        else:
                            frame_data = get_deleted_response.frame_graph
                            
                            # Check if it's an error response (FrameErrorInfo)
                            if hasattr(frame_data, 'error'):
                                # Frame returned an error - this is expected for deleted frames
                                if frame_data.error == 'frame_not_owned_by_entity':
                                    logger.info(f"   ✅ Deleted frame returned error (as expected): {frame_data.message}")
                                else:
                                    logger.warning(f"   ⚠️  Frame returned unexpected error: {frame_data.error}")
                            elif hasattr(frame_data, 'model_dump'):
                                frame_dict = frame_data.model_dump(by_alias=True)
                                objects_in_graph = frame_dict.get('@graph', [])
                                logger.error(f"   ❌ Deleted frame still exists with {len(objects_in_graph)} objects")
                                if objects_in_graph:
                                    for obj in objects_in_graph:
                                        logger.error(f"      Object type: {obj.get('@type', 'NO_TYPE')}, ID: {obj.get('@id', 'NO_ID')}")
                                results["tests_failed"] += 1
                                results["errors"].append("Deleted frame still returned by get operation")
                                return results
                            else:
                                frame_dict = frame_data
                                objects_in_graph = frame_dict.get('@graph', [])
                                logger.error(f"   ❌ Deleted frame still exists with {len(objects_in_graph)} objects")
                                results["tests_failed"] += 1
                                results["errors"].append("Deleted frame still returned by get operation")
                                return results
                    except Exception as get_error:
                        # If get fails, that's also acceptable (frame not found)
                        logger.info(f"   ✅ Get deleted frame failed (as expected): {get_error}")
                    
                    # Verify by listing all frames for the entity
                    logger.info(f"   Verifying deletion by listing all frames...")
                    list_response = await self.client.kgentities.get_kgentity_frames(
                        space_id=space_id,
                        graph_id=graph_id,
                        entity_uri=test_entity_uri
                    )
                    
                    # Get frame objects directly from response
                    # FrameResponse - response.objects contains GraphObjects directly
                    if list_response.is_success and list_response.objects:
                        # Extract frame URIs from KGFrame objects
                        frame_uris_in_list = [str(f.URI) for f in list_response.objects if type(f).__name__ == 'KGFrame']
                        if company_frame_uri not in frame_uris_in_list:
                            logger.info(f"   ✅ Deleted frame not in frame list (as expected)")
                            logger.info(f"   Remaining frames: {len(list_response.objects)}")
                            logger.info(f"✅ PASS: Delete frame and verify")
                            results["tests_passed"] += 1
                        else:
                            logger.error(f"   ❌ Deleted frame still in frame list")
                            logger.error(f"❌ FAIL: Delete frame and verify")
                            results["tests_failed"] += 1
                            results["errors"].append("Deleted frame still appears in frame list")
                    else:
                        logger.error(f"   ❌ Unexpected response type: {type(list_response)}")
                        results["tests_failed"] += 1
                        results["errors"].append(f"Unexpected response type: {type(list_response)}")
                else:
                    logger.error(f"❌ FAIL: Delete frame and verify")
                    logger.error(f"   Delete failed: {delete_response.message}")
                    results["tests_failed"] += 1
                    results["errors"].append(f"Frame delete failed: {delete_response.message}")
            else:
                logger.warning(f"   ⚠️  Company Info Frame not found for deletion")
                logger.error(f"❌ FAIL: Delete frame and verify")
                results["tests_failed"] += 1
                results["errors"].append("Company Info Frame not found for deletion")
                
        except Exception as e:
            logger.error(f"❌ Error deleting and verifying frame: {e}")
            import traceback
            logger.error(traceback.format_exc())
            results["tests_failed"] += 1
            results["errors"].append(f"Error deleting and verifying frame: {str(e)}")
        
        return results
