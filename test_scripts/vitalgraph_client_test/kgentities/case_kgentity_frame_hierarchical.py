#!/usr/bin/env python3
"""
KGEntity Hierarchical Frame Test Case

Client-side test case for KG entity hierarchical frame operations using VitalGraph client.
Tests that parent_frame_uri actually creates Edge_hasKGFrame edges, that child frames
are discoverable via their parent, and that delete with parent_frame_uri validation works.
"""

import logging
import uuid
from typing import Dict, Any, List, Optional

from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame

from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph_client_test.client_test_data import ClientTestDataCreator

logger = logging.getLogger(__name__)


class KGEntityHierarchicalFrameTester:
    """Client-side test case for KG entity hierarchical frame operations."""
    
    def __init__(self, client: VitalGraphClient, test_data_creator: ClientTestDataCreator):
        self.client = client
        self.test_data_creator = test_data_creator
        self.created_entity_uris: List[str] = []
        self.created_frame_uris: List[str] = []
    
    def _make_child_frame_objects(self, child_id: str, child_name: str) -> List[GraphObject]:
        """Create a child KGFrame with a slot and edge, suitable for create_entity_frames.
        
        Note: kGGraphURI and frameGraphURI are NOT set — server enforces these.
        """
        frame = KGFrame()
        frame.URI = self.test_data_creator.generate_test_uri("frame", child_id)
        frame.name = child_name
        frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#OfficerFrame"
        
        slot = KGTextSlot()
        slot.URI = self.test_data_creator.generate_test_uri("slot", f"{child_id}_name")
        slot.name = f"{child_name} Name"
        slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#OfficerNameSlot"
        slot.textSlotValue = child_name
        
        edge = Edge_hasKGSlot()
        edge.URI = self.test_data_creator.generate_test_uri("edge", f"{child_id}_slot_edge")
        edge.edgeSource = str(frame.URI)
        edge.edgeDestination = str(slot.URI)
        
        return [frame, slot, edge]
    
    async def _setup_entity_with_parent_frame(self, space_id: str, graph_id: str) -> Optional[Dict[str, str]]:
        """Create an entity and identify its first frame as the parent. Returns dict with entity_uri, parent_frame_uri."""
        unique_name = f"Hier Test Org {uuid.uuid4().hex[:8]}"
        entity_objects = self.test_data_creator.create_organization_with_address(unique_name)
        entity_response = await self.client.kgentities.create_kgentities(
            space_id=space_id, graph_id=graph_id, objects=entity_objects
        )
        if not entity_response or not entity_response.created_uris:
            logger.error("Failed to create test entity")
            return None
        
        entity_uri = str(entity_objects[0].URI)
        self.created_entity_uris.append(entity_uri)
        
        # Get existing frames to use first as parent
        frames_resp = await self.client.kgentities.get_kgentity_frames(
            space_id=space_id, graph_id=graph_id, entity_uri=entity_uri
        )
        if not hasattr(frames_resp, 'objects') or not frames_resp.objects:
            logger.error("Entity has no frames after creation")
            return None
        
        parent_frame_uri = str(frames_resp.objects[0].URI)
        return {"entity_uri": entity_uri, "parent_frame_uri": parent_frame_uri}
    
    async def test_create_child_frame(self, space_id: str, graph_id: str) -> bool:
        """
        Test that creating a frame with parent_frame_uri produces an Edge_hasKGFrame
        linking parent → child, and the child is retrievable via entity frames.
        """
        try:
            logger.info("🧪 Test: Create child frame with parent_frame_uri")
            
            setup = await self._setup_entity_with_parent_frame(space_id, graph_id)
            if not setup:
                return False
            entity_uri = setup["entity_uri"]
            parent_frame_uri = setup["parent_frame_uri"]
            
            # Count child frames of parent before
            before = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id, entity_uri=entity_uri,
                parent_frame_uri=parent_frame_uri, page_size=100
            )
            before_count = len(before.objects) if hasattr(before, 'objects') and before.objects else 0
            
            # Create child frame with parent_frame_uri
            child_objects = self._make_child_frame_objects(f"hier_child_{uuid.uuid4().hex[:8]}", "VP Engineering")
            child_frame_uri = str(child_objects[0].URI)
            
            create_resp = await self.client.kgentities.create_entity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                objects=child_objects,
                parent_frame_uri=parent_frame_uri
            )
            
            if not create_resp.is_success:
                logger.error(f"    create_entity_frames failed: {create_resp.error_message}")
                return False
            
            self.created_frame_uris.append(child_frame_uri)
            logger.info(f"  Created child frame: {child_frame_uri}")
            
            # Verify: child frame count under parent increased
            after = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id, entity_uri=entity_uri,
                parent_frame_uri=parent_frame_uri, page_size=100
            )
            after_count = len(after.objects) if hasattr(after, 'objects') and after.objects else 0
            
            if after_count <= before_count:
                logger.error(f"    Frame count did not increase: before={before_count}, after={after_count}")
                return False
            
            # Verify: child frame is retrievable by URI
            frame_graph_resp = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id, entity_uri=entity_uri,
                frame_uris=[child_frame_uri]
            )
            if hasattr(frame_graph_resp, 'error_message') and frame_graph_resp.error_message:
                logger.error(f"    Child frame not retrievable: {frame_graph_resp.error_message}")
                return False
            
            logger.info(f"  ✅ Child frame created and retrievable. Frames: {before_count} → {after_count}")
            return True
            
        except Exception as e:
            logger.error(f"    create_child_frame failed: {e}")
            return False
    
    async def test_delete_child_frame_with_parent(self, space_id: str, graph_id: str) -> bool:
        """
        Test that deleting a child frame with parent_frame_uri succeeds
        (server validates Edge_hasKGFrame exists before allowing delete).
        """
        try:
            logger.info("🧪 Test: Delete child frame with parent_frame_uri validation")
            
            setup = await self._setup_entity_with_parent_frame(space_id, graph_id)
            if not setup:
                return False
            entity_uri = setup["entity_uri"]
            parent_frame_uri = setup["parent_frame_uri"]
            
            # Create child frame
            child_objects = self._make_child_frame_objects(f"hier_del_{uuid.uuid4().hex[:8]}", "Temp Officer")
            child_frame_uri = str(child_objects[0].URI)
            
            create_resp = await self.client.kgentities.create_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri, objects=child_objects,
                parent_frame_uri=parent_frame_uri
            )
            if not create_resp.is_success:
                logger.error(f"    Setup: create child frame failed: {create_resp.error_message}")
                return False
            
            # Delete with parent_frame_uri — triggers parent-child validation
            delete_resp = await self.client.kgentities.delete_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri,
                frame_uris=[child_frame_uri],
                parent_frame_uri=parent_frame_uri
            )
            
            if not delete_resp.is_success:
                logger.error(f"    delete_entity_frames (parent) failed: {delete_resp.error_message}")
                return False
            
            # Verify frame is gone
            after = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id, entity_uri=entity_uri,
                frame_uris=[child_frame_uri]
            )
            # Should get frame_not_found error
            if hasattr(after, 'objects') and after.objects:
                logger.error("    Deleted frame still retrievable")
                return False
            
            logger.info("  ✅ Child frame deleted with parent validation")
            return True
            
        except Exception as e:
            logger.error(f"    delete_child_frame_with_parent failed: {e}")
            return False
    
    async def test_delete_non_child_rejected(self, space_id: str, graph_id: str) -> bool:
        """
        Test that deleting a frame with wrong parent_frame_uri is rejected.
        The frame exists but is NOT a child of the specified parent.
        """
        try:
            logger.info("🧪 Test: Delete with wrong parent_frame_uri is rejected")
            
            setup = await self._setup_entity_with_parent_frame(space_id, graph_id)
            if not setup:
                return False
            entity_uri = setup["entity_uri"]
            parent_frame_uri = setup["parent_frame_uri"]
            
            # Create child frame WITHOUT parent_frame_uri (top-level frame)
            child_objects = self._make_child_frame_objects(f"hier_top_{uuid.uuid4().hex[:8]}", "Top Level Frame")
            child_frame_uri = str(child_objects[0].URI)
            
            create_resp = await self.client.kgentities.create_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri, objects=child_objects
                # NOTE: no parent_frame_uri — created as top-level
            )
            if not create_resp.is_success:
                logger.error(f"    Setup: create top-level frame failed: {create_resp.error_message}")
                return False
            self.created_frame_uris.append(child_frame_uri)
            
            # Try to delete with parent_frame_uri — should be rejected since frame is NOT a child
            delete_resp = await self.client.kgentities.delete_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri,
                frame_uris=[child_frame_uri],
                parent_frame_uri=parent_frame_uri  # wrong parent
            )
            
            if delete_resp.is_success:
                logger.error("    Delete succeeded but should have been rejected (frame is not child of parent)")
                return False
            
            logger.info(f"  ✅ Correctly rejected: {delete_resp.error_message}")
            return True
            
        except Exception as e:
            logger.error(f"    delete_non_child_rejected failed: {e}")
            return False
    
    async def test_multi_level_hierarchy(self, space_id: str, graph_id: str) -> bool:
        """
        Test creating a 3-level hierarchy: entity → parent frame → child frame → grandchild frame.
        Verify all levels are retrievable.
        """
        try:
            logger.info("🧪 Test: Multi-level hierarchy (3 levels)")
            
            setup = await self._setup_entity_with_parent_frame(space_id, graph_id)
            if not setup:
                return False
            entity_uri = setup["entity_uri"]
            parent_frame_uri = setup["parent_frame_uri"]
            
            # Level 2: child frame under parent
            child_objects = self._make_child_frame_objects(f"hier_l2_{uuid.uuid4().hex[:8]}", "Level 2 Frame")
            child_frame_uri = str(child_objects[0].URI)
            
            resp1 = await self.client.kgentities.create_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri, objects=child_objects,
                parent_frame_uri=parent_frame_uri
            )
            if not resp1.is_success:
                logger.error(f"    Level 2 create failed: {resp1.error_message}")
                return False
            self.created_frame_uris.append(child_frame_uri)
            
            # Level 3: grandchild frame under child
            grandchild_objects = self._make_child_frame_objects(f"hier_l3_{uuid.uuid4().hex[:8]}", "Level 3 Frame")
            grandchild_frame_uri = str(grandchild_objects[0].URI)
            
            resp2 = await self.client.kgentities.create_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri, objects=grandchild_objects,
                parent_frame_uri=child_frame_uri
            )
            if not resp2.is_success:
                logger.error(f"    Level 3 create failed: {resp2.error_message}")
                return False
            self.created_frame_uris.append(grandchild_frame_uri)
            
            # Verify level 2 is a child of parent
            l2_frames = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id, entity_uri=entity_uri,
                parent_frame_uri=parent_frame_uri, page_size=100
            )
            l2_uris = [str(f.URI) for f in l2_frames.objects] if hasattr(l2_frames, 'objects') and l2_frames.objects else []
            
            if child_frame_uri not in l2_uris:
                logger.error(f"    Level 2 frame not found under parent")
                return False
            
            # Verify level 3 is a child of level 2
            l3_frames = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id, entity_uri=entity_uri,
                parent_frame_uri=child_frame_uri, page_size=100
            )
            l3_uris = [str(f.URI) for f in l3_frames.objects] if hasattr(l3_frames, 'objects') and l3_frames.objects else []
            
            if grandchild_frame_uri not in l3_uris:
                logger.error(f"    Level 3 frame not found under level 2")
                return False
            
            # Verify delete of grandchild with parent validation works
            del_resp = await self.client.kgentities.delete_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri,
                frame_uris=[grandchild_frame_uri],
                parent_frame_uri=child_frame_uri
            )
            if not del_resp.is_success:
                logger.error(f"    Grandchild delete with parent validation failed: {del_resp.error_message}")
                return False
            
            logger.info("  ✅ 3-level hierarchy created and grandchild deleted with parent validation")
            return True
            
        except Exception as e:
            logger.error(f"    multi_level_hierarchy failed: {e}")
            return False
    
    async def test_delete_fails_if_children(self, space_id: str, graph_id: str) -> bool:
        """
        Test that deleting a frame with children fails by default (recursive=False).
        """
        try:
            logger.info("🧪 Test: Delete fails if frame has children (default mode)")
            
            setup = await self._setup_entity_with_parent_frame(space_id, graph_id)
            if not setup:
                return False
            entity_uri = setup["entity_uri"]
            parent_frame_uri = setup["parent_frame_uri"]
            
            # Create a child frame under the parent
            child_objects = self._make_child_frame_objects(f"hier_block_{uuid.uuid4().hex[:8]}", "Blocking Child")
            child_frame_uri = str(child_objects[0].URI)
            
            create_resp = await self.client.kgentities.create_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri, objects=child_objects,
                parent_frame_uri=parent_frame_uri
            )
            if not create_resp.is_success:
                logger.error(f"    Setup: create child frame failed: {create_resp.error_message}")
                return False
            self.created_frame_uris.append(child_frame_uri)
            
            # Try to delete the parent frame (which has children) without recursive
            delete_resp = await self.client.kgentities.delete_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri,
                frame_uris=[parent_frame_uri],
                recursive=False
            )
            
            if delete_resp.is_success:
                logger.error("    Delete succeeded but should have been rejected (frame has children)")
                return False
            
            if "children" not in (delete_resp.error_message or "").lower() and "recursive" not in (delete_resp.error_message or "").lower():
                logger.error(f"    Expected children/recursive error, got: {delete_resp.error_message}")
                return False
            
            logger.info(f"  ✅ Correctly rejected: {delete_resp.error_message}")
            return True
            
        except Exception as e:
            logger.error(f"    delete_fails_if_children failed: {e}")
            return False
    
    async def test_recursive_delete(self, space_id: str, graph_id: str) -> bool:
        """
        Test that deleting a frame with children succeeds when recursive=True,
        and all descendants are removed.
        """
        try:
            logger.info("🧪 Test: Recursive delete removes parent and all descendants")
            
            setup = await self._setup_entity_with_parent_frame(space_id, graph_id)
            if not setup:
                return False
            entity_uri = setup["entity_uri"]
            parent_frame_uri = setup["parent_frame_uri"]
            
            # Create child under parent
            child_objects = self._make_child_frame_objects(f"hier_rc1_{uuid.uuid4().hex[:8]}", "Recursive Child")
            child_frame_uri = str(child_objects[0].URI)
            
            resp1 = await self.client.kgentities.create_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri, objects=child_objects,
                parent_frame_uri=parent_frame_uri
            )
            if not resp1.is_success:
                logger.error(f"    Setup: create child failed: {resp1.error_message}")
                return False
            
            # Create grandchild under child
            gc_objects = self._make_child_frame_objects(f"hier_rc2_{uuid.uuid4().hex[:8]}", "Recursive Grandchild")
            gc_frame_uri = str(gc_objects[0].URI)
            
            resp2 = await self.client.kgentities.create_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri, objects=gc_objects,
                parent_frame_uri=child_frame_uri
            )
            if not resp2.is_success:
                logger.error(f"    Setup: create grandchild failed: {resp2.error_message}")
                return False
            
            # Verify both exist
            l1 = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id, entity_uri=entity_uri,
                parent_frame_uri=parent_frame_uri, page_size=100
            )
            l1_uris = [str(f.URI) for f in l1.objects] if hasattr(l1, 'objects') and l1.objects else []
            if child_frame_uri not in l1_uris:
                logger.error("    Child frame not found before recursive delete")
                return False
            
            # Delete parent with recursive=True — should delete child and grandchild too
            del_resp = await self.client.kgentities.delete_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri,
                frame_uris=[parent_frame_uri],
                recursive=True
            )
            
            if not del_resp.is_success:
                logger.error(f"    Recursive delete failed: {del_resp.error_message}")
                return False
            
            # Verify child and grandchild are gone
            l2 = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id, entity_uri=entity_uri,
                parent_frame_uri=parent_frame_uri, page_size=100
            )
            l2_uris = [str(f.URI) for f in l2.objects] if hasattr(l2, 'objects') and l2.objects else []
            if child_frame_uri in l2_uris:
                logger.error("    Child frame still exists after recursive delete")
                return False
            
            l3 = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id, entity_uri=entity_uri,
                parent_frame_uri=child_frame_uri, page_size=100
            )
            l3_uris = [str(f.URI) for f in l3.objects] if hasattr(l3, 'objects') and l3.objects else []
            if gc_frame_uri in l3_uris:
                logger.error("    Grandchild frame still exists after recursive delete")
                return False
            
            logger.info("  ✅ Recursive delete removed parent and all descendants")
            return True
            
        except Exception as e:
            logger.error(f"    recursive_delete failed: {e}")
            return False
    
    async def test_frame_grouping_uri_assignment(self, space_id: str, graph_id: str) -> bool:
        """
        Verify the server assigns frameGraphURI correctly in a hierarchy.
        
        Creates: entity → parent_frame → child_frame (each with a slot).
        Checks via SPARQL that each slot's hasFrameGraphURI points to its
        immediate owning frame, NOT the root frame.
        """
        try:
            logger.info("🧪 Test: frameGraphURI assigned to immediate owning frame")
            
            setup = await self._setup_entity_with_parent_frame(space_id, graph_id)
            if not setup:
                return False
            entity_uri = setup["entity_uri"]
            parent_frame_uri = setup["parent_frame_uri"]
            
            # Create child frame with its own slot under the parent
            uid = uuid.uuid4().hex[:8]
            child_objects = self._make_child_frame_objects(f"fgu_child_{uid}", "Grouping Child")
            child_frame_uri = str(child_objects[0].URI)
            child_slot_uri = str(child_objects[1].URI)
            
            resp = await self.client.kgentities.create_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri, objects=child_objects,
                parent_frame_uri=parent_frame_uri
            )
            if not resp.is_success:
                logger.error(f"    Setup: create child failed: {resp.error_message}")
                return False
            self.created_frame_uris.append(child_frame_uri)
            
            # Query frameGraphURI for the child's slot via SPARQL
            from vitalgraph.model.sparql_model import SPARQLQueryRequest
            haley = "http://vital.ai/ontology/haley-ai-kg#"
            query = f"""
            SELECT ?slot ?frameGraphURI WHERE {{
                GRAPH <{graph_id}> {{
                    <{child_slot_uri}> <{haley}hasFrameGraphURI> ?frameGraphURI .
                    BIND(<{child_slot_uri}> AS ?slot)
                }}
            }}
            """
            sparql_resp = await self.client.execute_sparql_query(
                space_id, SPARQLQueryRequest(query=query)
            )
            
            bindings = []
            if hasattr(sparql_resp, 'results') and sparql_resp.results:
                bindings = sparql_resp.results.get('bindings', [])
            
            if not bindings:
                logger.error(f"    No frameGraphURI found for slot {child_slot_uri}")
                return False
            
            actual_fgu = bindings[0].get('frameGraphURI', {}).get('value', '')
            
            if actual_fgu != child_frame_uri:
                logger.error(
                    f"    frameGraphURI mismatch: expected {child_frame_uri}, got {actual_fgu}"
                )
                return False
            
            # Also verify the child frame's own frameGraphURI points to itself
            frame_query = f"""
            SELECT ?frameGraphURI WHERE {{
                GRAPH <{graph_id}> {{
                    <{child_frame_uri}> <{haley}hasFrameGraphURI> ?frameGraphURI .
                }}
            }}
            """
            frame_resp = await self.client.execute_sparql_query(
                space_id, SPARQLQueryRequest(query=frame_query)
            )
            
            frame_bindings = []
            if hasattr(frame_resp, 'results') and frame_resp.results:
                frame_bindings = frame_resp.results.get('bindings', [])
            
            if not frame_bindings:
                logger.error(f"    No frameGraphURI found for frame {child_frame_uri}")
                return False
            
            actual_frame_fgu = frame_bindings[0].get('frameGraphURI', {}).get('value', '')
            if actual_frame_fgu != child_frame_uri:
                logger.error(
                    f"    Frame frameGraphURI mismatch: expected {child_frame_uri}, got {actual_frame_fgu}"
                )
                return False
            
            logger.info("  ✅ frameGraphURI correctly assigned to immediate owning frame")
            return True
            
        except Exception as e:
            logger.error(f"    test_frame_grouping_uri_assignment failed: {e}")
            return False
    
    async def test_replace_flat(self, space_id: str, graph_id: str) -> bool:
        """
        Test flat replace via entity frames endpoint: replace a frame that has a child,
        verify old child is removed and root URI is preserved.
        """
        try:
            logger.info("🧪 Test: Entity frames flat replace removes old children")
            
            setup = await self._setup_entity_with_parent_frame(space_id, graph_id)
            if not setup:
                return False
            entity_uri = setup["entity_uri"]
            parent_frame_uri = setup["parent_frame_uri"]
            
            # Create a child under the parent
            child_objects = self._make_child_frame_objects(
                f"hier_rflat_{uuid.uuid4().hex[:8]}", "Old Flat Child"
            )
            old_child_uri = str(child_objects[0].URI)
            create_resp = await self.client.kgentities.create_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri, objects=child_objects,
                parent_frame_uri=parent_frame_uri
            )
            if not create_resp.is_success:
                logger.error(f"    Setup: create child failed: {create_resp.error_message}")
                return False
            self.created_frame_uris.append(old_child_uri)
            
            # Replace parent with a flat frame graph (same URI, no children)
            replace_objects = self._make_child_frame_objects(
                f"hier_rflat_new_{uuid.uuid4().hex[:8]}", "Replaced Parent"
            )
            replace_objects[0].URI = parent_frame_uri  # preserve URI
            replace_objects[2].edgeSource = parent_frame_uri
            
            replace_resp = await self.client.kgentities.create_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri, objects=replace_objects,
                operation_mode="replace"
            )
            
            if not replace_resp.is_success:
                logger.error(f"    Replace failed: {replace_resp.error_message}")
                return False
            
            # Verify old child is gone
            child_check = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id, entity_uri=entity_uri,
                parent_frame_uri=parent_frame_uri, page_size=100
            )
            child_uris = [str(f.URI) for f in child_check.objects] if hasattr(child_check, 'objects') and child_check.objects else []
            
            if old_child_uri in child_uris:
                logger.error("    Old child still exists after flat replace")
                return False
            
            # Verify parent frame still exists
            frame_check = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id, entity_uri=entity_uri,
                frame_uris=[parent_frame_uri]
            )
            if not (hasattr(frame_check, 'objects') and frame_check.objects):
                logger.error("    Parent frame URI not preserved after flat replace")
                return False
            
            logger.info("  ✅ Entity frames flat replace: old child removed, root preserved")
            return True
            
        except Exception as e:
            logger.error(f"    test_replace_flat failed: {e}")
            return False
    
    def _make_hierarchy_objects(
        self, root_uri: str,
        child_name: str, grandchild_name: str
    ) -> List[GraphObject]:
        """Build a 3-level replacement hierarchy (root + child + grandchild).

        Returns all frames, slots, slot-edges, and Edge_hasKGFrame edges.
        Root frame URI is set to ``root_uri`` to preserve it during replace.
        """
        uid = uuid.uuid4().hex[:6]

        # root
        root_objs = self._make_child_frame_objects(f"rh_root_{uid}", "Replaced Root")
        root_frame = root_objs[0]
        root_frame.URI = root_uri
        root_objs[2].edgeSource = root_uri

        # child
        child_objs = self._make_child_frame_objects(f"rh_child_{uid}", child_name)
        child_uri = str(child_objs[0].URI)

        rc_edge = Edge_hasKGFrame()
        rc_edge.URI = self.test_data_creator.generate_test_uri("edge", f"rh_rc_{uid}")
        rc_edge.edgeSource = root_uri
        rc_edge.edgeDestination = child_uri

        # grandchild
        gc_objs = self._make_child_frame_objects(f"rh_gc_{uid}", grandchild_name)
        gc_uri = str(gc_objs[0].URI)

        cg_edge = Edge_hasKGFrame()
        cg_edge.URI = self.test_data_creator.generate_test_uri("edge", f"rh_cg_{uid}")
        cg_edge.edgeSource = child_uri
        cg_edge.edgeDestination = gc_uri

        return root_objs + [rc_edge] + child_objs + [cg_edge] + gc_objs

    async def test_replace_with_hierarchy(self, space_id: str, graph_id: str) -> bool:
        """
        Test replace mode via entity frames endpoint with a multi-level replacement graph
        containing child and grandchild frames.
        """
        try:
            logger.info("🧪 Test: Entity frames replace with child + grandchild")

            setup = await self._setup_entity_with_parent_frame(space_id, graph_id)
            if not setup:
                return False
            entity_uri = setup["entity_uri"]
            parent_frame_uri = setup["parent_frame_uri"]

            # Create an old child so we can verify it's removed
            old_child_objects = self._make_child_frame_objects(
                f"hier_oldc_{uuid.uuid4().hex[:8]}", "Old Child"
            )
            old_child_uri = str(old_child_objects[0].URI)
            create_resp = await self.client.kgentities.create_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri, objects=old_child_objects,
                parent_frame_uri=parent_frame_uri
            )
            if not create_resp.is_success:
                logger.error(f"    Setup: create old child failed: {create_resp.error_message}")
                return False
            self.created_frame_uris.append(old_child_uri)

            # Build replacement hierarchy: parent → New Child → New Grandchild
            replace_objects = self._make_hierarchy_objects(
                parent_frame_uri, "New Child", "New Grandchild"
            )

            # Extract new URIs for verification
            new_child_uri = None
            new_gc_uri = None
            for obj in replace_objects:
                if isinstance(obj, KGFrame) and str(obj.URI) != parent_frame_uri:
                    if new_child_uri is None:
                        new_child_uri = str(obj.URI)
                    else:
                        new_gc_uri = str(obj.URI)

            # Call replace via entity frames endpoint
            from vitalgraph.client.vitalgraph_client import VitalGraphClientError
            replace_resp = await self.client.kgentities.create_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri, objects=replace_objects,
                operation_mode="replace"
            )

            if not replace_resp.is_success:
                logger.error(f"    Replace failed: {replace_resp.error_message}")
                return False

            # Verify old child is gone
            child_check = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id, entity_uri=entity_uri,
                parent_frame_uri=parent_frame_uri, page_size=100
            )
            child_uris = [str(f.URI) for f in child_check.objects] if hasattr(child_check, 'objects') and child_check.objects else []

            if old_child_uri in child_uris:
                logger.error("    Old child still exists after replace")
                return False

            # Verify new child exists under root
            if new_child_uri and new_child_uri not in child_uris:
                logger.warning(f"    New child {new_child_uri} not found under root (children: {child_uris})")

            # Verify grandchild under new child
            if new_child_uri and new_gc_uri:
                gc_check = await self.client.kgentities.get_kgentity_frames(
                    space_id=space_id, graph_id=graph_id, entity_uri=entity_uri,
                    parent_frame_uri=new_child_uri, page_size=100
                )
                gc_uris = [str(f.URI) for f in gc_check.objects] if hasattr(gc_check, 'objects') and gc_check.objects else []
                if new_gc_uri not in gc_uris:
                    logger.warning(f"    Grandchild {new_gc_uri} not found under child (gc_uris: {gc_uris})")

            # Verify parent frame still exists
            frame_check = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id, entity_uri=entity_uri,
                frame_uris=[parent_frame_uri]
            )
            if not (hasattr(frame_check, 'objects') and frame_check.objects):
                logger.error("    Parent frame URI not preserved after replace")
                return False

            logger.info("  ✅ Entity frames replace with hierarchy: old child removed, root preserved")
            return True

        except Exception as e:
            logger.error(f"    test_replace_with_hierarchy failed: {e}")
            return False

    async def cleanup_created_resources(self, space_id: str, graph_id: str) -> bool:
        """Clean up resources created during testing."""
        try:
            logger.info("🧹 Cleaning up hierarchical frame test resources")
            for entity_uri in self.created_entity_uris:
                try:
                    await self.client.kgentities.delete_kgentity(
                        space_id=space_id, graph_id=graph_id,
                        uri=entity_uri, delete_entity_graph=True
                    )
                except Exception as e:
                    logger.warning(f"Failed to delete entity {entity_uri}: {e}")
            self.created_entity_uris.clear()
            self.created_frame_uris.clear()
            return True
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            return False
