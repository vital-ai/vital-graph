#!/usr/bin/env python3
"""
KGFrame Hierarchy Test Case

Client-side tests for the top-level /kgframes endpoint hierarchy operations:
  - Delete with children fails (recursive=false)
  - Recursive delete cascades to all descendants
  - Update with parent_uri validates parent-child relationship
  - Shallow update preserves children
  - Replace mode swaps entire subtree
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


class KGFrameHierarchyTester:
    """Client-side test case for top-level /kgframes hierarchy operations."""

    def __init__(self, client: VitalGraphClient, test_data_creator: ClientTestDataCreator):
        self.client = client
        self.tdc = test_data_creator
        self.created_entity_uris: List[str] = []
        self.created_frame_uris: List[str] = []

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _make_frame_objects(self, frame_id: str, frame_name: str) -> List[GraphObject]:
        """Create a KGFrame + slot + edge suitable for create_kgframes.
        
        Note: kGGraphURI is NOT set — it is server-side only (entity-scoped).
        frameGraphURI is NOT set — the server processor assigns it.
        """
        frame = KGFrame()
        frame.URI = self.tdc.generate_test_uri("frame", frame_id)
        frame.name = frame_name
        frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#OfficerFrame"

        slot = KGTextSlot()
        slot.URI = self.tdc.generate_test_uri("slot", f"{frame_id}_name")
        slot.name = f"{frame_name} Name"
        slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#OfficerNameSlot"
        slot.textSlotValue = frame_name

        edge = Edge_hasKGSlot()
        edge.URI = self.tdc.generate_test_uri("edge", f"{frame_id}_slot_edge")
        edge.edgeSource = str(frame.URI)
        edge.edgeDestination = str(slot.URI)

        return [frame, slot, edge]

    def _make_hierarchy_objects(
        self, root_uri: str,
        child_name: str, grandchild_name: str
    ) -> List[GraphObject]:
        """Build a 3-level frame hierarchy (root + child + grandchild) as a flat object list.

        Returns all frames, slots, slot-edges, and Edge_hasKGFrame edges needed to
        represent:
            root  →  child  →  grandchild
        The root frame URI is set to ``root_uri`` so that replace mode can preserve it.

        Note: kGGraphURI and frameGraphURI are NOT set — server handles grouping.
        """
        uid = uuid.uuid4().hex[:6]

        # --- root ---
        root_objs = self._make_frame_objects(f"rh_root_{uid}", "Replaced Root")
        root_frame = root_objs[0]
        root_frame.URI = root_uri  # preserve original URI
        root_objs[2].edgeSource = root_uri  # slot edge source

        # --- child ---
        child_objs = self._make_frame_objects(f"rh_child_{uid}", child_name)
        child_frame = child_objs[0]
        child_uri = str(child_frame.URI)

        # Edge_hasKGFrame: root → child
        rc_edge = Edge_hasKGFrame()
        rc_edge.URI = self.tdc.generate_test_uri("edge", f"rh_rc_{uid}")
        rc_edge.edgeSource = root_uri
        rc_edge.edgeDestination = child_uri

        # --- grandchild ---
        gc_objs = self._make_frame_objects(f"rh_gc_{uid}", grandchild_name)
        gc_frame = gc_objs[0]
        gc_uri = str(gc_frame.URI)

        # Edge_hasKGFrame: child → grandchild
        cg_edge = Edge_hasKGFrame()
        cg_edge.URI = self.tdc.generate_test_uri("edge", f"rh_cg_{uid}")
        cg_edge.edgeSource = child_uri
        cg_edge.edgeDestination = gc_uri

        all_objects = root_objs + [rc_edge] + child_objs + [cg_edge] + gc_objs
        return all_objects

    async def _setup_entity_and_root_frame(self, space_id: str, graph_id: str) -> Optional[Dict[str, str]]:
        """Create an entity with frames via kgentities, return {entity_uri, root_frame_uri}."""
        unique_name = f"FrameHier {uuid.uuid4().hex[:8]}"
        entity_objects = self.tdc.create_organization_with_address(unique_name)

        entity_resp = await self.client.kgentities.create_kgentities(
            space_id=space_id, graph_id=graph_id, objects=entity_objects
        )
        if not entity_resp or not entity_resp.created_uris:
            logger.error("Failed to create test entity")
            return None

        entity_uri = str(entity_objects[0].URI)
        self.created_entity_uris.append(entity_uri)

        frames_resp = await self.client.kgentities.get_kgentity_frames(
            space_id=space_id, graph_id=graph_id, entity_uri=entity_uri
        )
        if not hasattr(frames_resp, 'objects') or not frames_resp.objects:
            logger.error("Entity has no frames after creation")
            return None

        root_frame_uri = str(frames_resp.objects[0].URI)
        return {"entity_uri": entity_uri, "root_frame_uri": root_frame_uri}

    async def _create_child_via_entity(self, space_id: str, graph_id: str,
                                       entity_uri: str, parent_frame_uri: str,
                                       child_id: str, child_name: str) -> Optional[str]:
        """Create a child frame via the entity endpoint (since hierarchy edges need entity context)."""
        objs = self._make_frame_objects(child_id, child_name)
        child_uri = str(objs[0].URI)
        resp = await self.client.kgentities.create_entity_frames(
            space_id=space_id, graph_id=graph_id,
            entity_uri=entity_uri, objects=objs,
            parent_frame_uri=parent_frame_uri
        )
        if not resp.is_success:
            logger.error(f"  create child failed: {resp.error_message}")
            return None
        self.created_frame_uris.append(child_uri)
        return child_uri

    # ------------------------------------------------------------------
    # Test 1: Delete fails if frame has children (recursive=false)
    # ------------------------------------------------------------------

    async def test_delete_fails_if_children(self, space_id: str, graph_id: str) -> bool:
        """Deleting a frame that has children should fail when recursive=false."""
        try:
            logger.info("🧪 Test: /kgframes delete fails if frame has children")

            setup = await self._setup_entity_and_root_frame(space_id, graph_id)
            if not setup:
                return False
            entity_uri = setup["entity_uri"]
            root_uri = setup["root_frame_uri"]

            # Add a child under the root frame
            child_uri = await self._create_child_via_entity(
                space_id, graph_id, entity_uri, root_uri,
                f"fh_block_{uuid.uuid4().hex[:8]}", "Blocking Child"
            )
            if not child_uri:
                return False

            # Try to delete root frame via top-level /kgframes without recursive
            del_resp = await self.client.kgframes.delete_kgframe(
                space_id=space_id, graph_id=graph_id,
                uri=root_uri, recursive=False
            )

            if del_resp.is_success:
                logger.error("  Delete succeeded but should have been rejected")
                return False

            err = del_resp.error_message or ""
            if "children" not in err.lower() and "recursive" not in err.lower():
                logger.error(f"  Expected children/recursive error, got: {err}")
                return False

            logger.info(f"  ✅ Correctly rejected: {err}")
            return True

        except Exception as e:
            logger.error(f"  test_delete_fails_if_children failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Test 2: Recursive delete cascades to all descendants
    # ------------------------------------------------------------------

    async def test_recursive_delete(self, space_id: str, graph_id: str) -> bool:
        """Recursive delete should remove parent and all descendants."""
        try:
            logger.info("🧪 Test: /kgframes recursive delete cascades")

            setup = await self._setup_entity_and_root_frame(space_id, graph_id)
            if not setup:
                return False
            entity_uri = setup["entity_uri"]
            root_uri = setup["root_frame_uri"]

            # Create child under root
            child_uri = await self._create_child_via_entity(
                space_id, graph_id, entity_uri, root_uri,
                f"fh_rc1_{uuid.uuid4().hex[:8]}", "Recursive Child"
            )
            if not child_uri:
                return False

            # Create grandchild under child
            gc_uri = await self._create_child_via_entity(
                space_id, graph_id, entity_uri, child_uri,
                f"fh_rc2_{uuid.uuid4().hex[:8]}", "Recursive Grandchild"
            )
            if not gc_uri:
                return False

            # Delete root with recursive=True via top-level /kgframes
            del_resp = await self.client.kgframes.delete_kgframe(
                space_id=space_id, graph_id=graph_id,
                uri=root_uri, recursive=True
            )

            if not del_resp.is_success:
                logger.error(f"  Recursive delete failed: {del_resp.error_message}")
                return False

            # Verify root, child, and grandchild are gone
            for label, uri in [("root", root_uri), ("child", child_uri), ("grandchild", gc_uri)]:
                try:
                    check = await self.client.kgframes.get_kgframe(
                        space_id=space_id, graph_id=graph_id, uri=uri
                    )
                    if hasattr(check, 'frame_graph') and check.frame_graph:
                        logger.error(f"  {label} frame still exists after recursive delete")
                        return False
                except Exception:
                    pass  # Expected — frame not found

            logger.info("  ✅ Recursive delete removed parent and all descendants")
            return True

        except Exception as e:
            logger.error(f"  test_recursive_delete failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Test 3: Update with parent_uri validates parent-child relationship
    # ------------------------------------------------------------------

    async def test_update_validates_parent(self, space_id: str, graph_id: str) -> bool:
        """Update with parent_uri should reject if frame is not a child of that parent."""
        try:
            logger.info("🧪 Test: /kgframes update validates parent_uri")

            setup = await self._setup_entity_and_root_frame(space_id, graph_id)
            if not setup:
                return False
            entity_uri = setup["entity_uri"]
            root_uri = setup["root_frame_uri"]

            # Create a child under root
            child_uri = await self._create_child_via_entity(
                space_id, graph_id, entity_uri, root_uri,
                f"fh_uv_{uuid.uuid4().hex[:8]}", "Update Validation Child"
            )
            if not child_uri:
                return False

            # Create a second top-level frame (NOT a child of root)
            other_objects = self._make_frame_objects(
                f"fh_other_{uuid.uuid4().hex[:8]}", "Other Frame"
            )
            other_uri = str(other_objects[0].URI)
            other_resp = await self.client.kgentities.create_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri, objects=other_objects
            )
            if not other_resp.is_success:
                logger.error(f"  Setup: create other frame failed: {other_resp.error_message}")
                return False
            self.created_frame_uris.append(other_uri)

            # Try to update other_frame claiming root_uri as parent — should fail
            update_objects = self._make_frame_objects(other_uri.split("/")[-1], "Updated Other")
            # Override the URI to match the existing other_frame
            update_objects[0].URI = other_uri
            update_resp = await self.client.kgframes.create_kgframes(
                space_id=space_id, graph_id=graph_id,
                objects=update_objects,
                parent_uri=root_uri,
                operation_mode="update"
            )

            if update_resp.is_success:
                logger.error("  Update succeeded but should have been rejected (not a child of parent)")
                return False

            logger.info(f"  ✅ Correctly rejected update with wrong parent_uri")
            return True

        except Exception as e:
            logger.error(f"  test_update_validates_parent failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Test 4: Shallow update preserves children
    # ------------------------------------------------------------------

    async def test_update_preserves_children(self, space_id: str, graph_id: str) -> bool:
        """operation_mode=update should only modify the target frame, children remain intact."""
        try:
            logger.info("🧪 Test: /kgframes shallow update preserves children")

            setup = await self._setup_entity_and_root_frame(space_id, graph_id)
            if not setup:
                return False
            entity_uri = setup["entity_uri"]
            root_uri = setup["root_frame_uri"]

            # Create child under root
            child_uri = await self._create_child_via_entity(
                space_id, graph_id, entity_uri, root_uri,
                f"fh_up_{uuid.uuid4().hex[:8]}", "Preserved Child"
            )
            if not child_uri:
                return False

            # Update the root frame's properties via top-level /kgframes
            update_objects = self._make_frame_objects(root_uri.split("/")[-1], "Updated Root Name")
            update_objects[0].URI = root_uri
            update_resp = await self.client.kgframes.create_kgframes(
                space_id=space_id, graph_id=graph_id,
                objects=update_objects,
                operation_mode="update"
            )

            if not update_resp.is_success:
                logger.error(f"  Update failed: {update_resp.error_message}")
                return False

            # Verify child frame still exists
            child_check = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id, entity_uri=entity_uri,
                parent_frame_uri=root_uri, page_size=100
            )
            child_uris = [str(f.URI) for f in child_check.objects] if hasattr(child_check, 'objects') and child_check.objects else []

            if child_uri not in child_uris:
                logger.error("  Child frame disappeared after shallow update")
                return False

            # Verify the root frame name was actually updated
            root_check = await self.client.kgframes.get_kgframe(
                space_id=space_id, graph_id=graph_id, uri=root_uri
            )
            if not (hasattr(root_check, 'frame_graph') and root_check.frame_graph):
                logger.error("  Root frame not found after update")
                return False
            root_frame_obj = None
            for obj in root_check.frame_graph.objects:
                if isinstance(obj, KGFrame) and str(obj.URI) == root_uri:
                    root_frame_obj = obj
                    break
            if root_frame_obj is None:
                logger.error("  Root KGFrame object not found in frame_graph")
                return False
            actual_name = getattr(root_frame_obj, 'name', None)
            if actual_name != "Updated Root Name":
                logger.error(f"  Root frame name not updated: expected 'Updated Root Name', got '{actual_name}'")
                return False

            logger.info("  ✅ Shallow update preserved children and updated root name")
            return True

        except Exception as e:
            logger.error(f"  test_update_preserves_children failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Test 5: Replace mode swaps entire subtree
    # ------------------------------------------------------------------

    async def test_replace_mode(self, space_id: str, graph_id: str) -> bool:
        """operation_mode=replace should delete old subtree and insert new graph."""
        try:
            logger.info("🧪 Test: /kgframes replace mode swaps subtree")

            setup = await self._setup_entity_and_root_frame(space_id, graph_id)
            if not setup:
                return False
            entity_uri = setup["entity_uri"]
            root_uri = setup["root_frame_uri"]

            # Create child under root
            child_uri = await self._create_child_via_entity(
                space_id, graph_id, entity_uri, root_uri,
                f"fh_rp1_{uuid.uuid4().hex[:8]}", "Old Child"
            )
            if not child_uri:
                return False

            # Replace root with new graph (same root URI, different child)
            replace_objects = self._make_frame_objects(root_uri.split("/")[-1], "Replaced Root")
            replace_objects[0].URI = root_uri  # Preserve root URI

            replace_resp = await self.client.kgframes.create_kgframes(
                space_id=space_id, graph_id=graph_id,
                objects=replace_objects,
                operation_mode="replace"
            )

            if not replace_resp.is_success:
                logger.error(f"  Replace failed: {replace_resp.error_message}")
                return False

            # Verify old child is gone
            child_check = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id, entity_uri=entity_uri,
                parent_frame_uri=root_uri, page_size=100
            )
            child_uris = [str(f.URI) for f in child_check.objects] if hasattr(child_check, 'objects') and child_check.objects else []

            if child_uri in child_uris:
                logger.error("  Old child still exists after replace")
                return False

            # Verify root frame still exists after replace
            root_check = await self.client.kgframes.get_kgframe(
                space_id=space_id, graph_id=graph_id, uri=root_uri
            )
            if not (hasattr(root_check, 'frame_graph') and root_check.frame_graph):
                logger.error("  Root frame not found after replace")
                return False
            root_frame_obj = None
            for obj in root_check.frame_graph.objects:
                if isinstance(obj, KGFrame) and str(obj.URI) == root_uri:
                    root_frame_obj = obj
                    break
            if root_frame_obj is None:
                logger.error("  Root KGFrame object not found in frame_graph after replace")
                return False

            logger.info("  ✅ Replace mode removed old subtree, root preserved")
            return True

        except Exception as e:
            logger.error(f"  test_replace_mode failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Test 6: Replace with multi-level hierarchy
    # ------------------------------------------------------------------

    async def test_replace_with_hierarchy(self, space_id: str, graph_id: str) -> bool:
        """Replace should accept a replacement graph containing child and grandchild frames."""
        try:
            logger.info("🧪 Test: /kgframes replace with child + grandchild")

            setup = await self._setup_entity_and_root_frame(space_id, graph_id)
            if not setup:
                return False
            entity_uri = setup["entity_uri"]
            root_uri = setup["root_frame_uri"]

            # Create an old child so we can verify it's removed
            old_child_uri = await self._create_child_via_entity(
                space_id, graph_id, entity_uri, root_uri,
                f"fh_oldc_{uuid.uuid4().hex[:8]}", "Old Child"
            )
            if not old_child_uri:
                return False

            # Build replacement hierarchy: root → New Child → New Grandchild
            replace_objects = self._make_hierarchy_objects(
                root_uri, "New Child", "New Grandchild"
            )
            # Extract URIs for verification
            new_child_uri = None
            new_gc_uri = None
            for obj in replace_objects:
                if isinstance(obj, KGFrame) and str(obj.URI) != root_uri:
                    if new_child_uri is None:
                        new_child_uri = str(obj.URI)
                    else:
                        new_gc_uri = str(obj.URI)

            replace_resp = await self.client.kgframes.create_kgframes(
                space_id=space_id, graph_id=graph_id,
                objects=replace_objects,
                operation_mode="replace"
            )

            if not replace_resp.is_success:
                logger.error(f"  Replace failed: {replace_resp.error_message}")
                return False

            # Verify old child is gone
            child_check = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id, entity_uri=entity_uri,
                parent_frame_uri=root_uri, page_size=100
            )
            child_uris = [str(f.URI) for f in child_check.objects] if hasattr(child_check, 'objects') and child_check.objects else []

            if old_child_uri in child_uris:
                logger.error("  Old child still exists after replace")
                return False

            # Verify new child exists under root
            if new_child_uri and new_child_uri not in child_uris:
                logger.error(f"  New child {new_child_uri} not found under root (children: {child_uris})")
                return False

            # Verify new grandchild exists under new child
            if new_child_uri and new_gc_uri:
                gc_check = await self.client.kgentities.get_kgentity_frames(
                    space_id=space_id, graph_id=graph_id, entity_uri=entity_uri,
                    parent_frame_uri=new_child_uri, page_size=100
                )
                gc_uris = [str(f.URI) for f in gc_check.objects] if hasattr(gc_check, 'objects') and gc_check.objects else []
                if new_gc_uri not in gc_uris:
                    logger.error(f"  Grandchild {new_gc_uri} not found under child (gc_uris: {gc_uris})")
                    return False

            # Verify root frame still exists
            try:
                root_check = await self.client.kgframes.get_kgframe(
                    space_id=space_id, graph_id=graph_id, uri=root_uri
                )
                if not (hasattr(root_check, 'frame_graph') and root_check.frame_graph):
                    logger.error("  Root frame URI not preserved after replace")
                    return False
            except Exception:
                logger.error("  Root frame URI not found after replace")
                return False

            logger.info(f"  ✅ Replace with hierarchy: old child removed, root preserved, new hierarchy inserted")
            return True

        except Exception as e:
            logger.error(f"  test_replace_with_hierarchy failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Test 7: frameGraphURI assigned to immediate owning frame
    # ------------------------------------------------------------------

    async def test_frame_grouping_uri_assignment(self, space_id: str, graph_id: str) -> bool:
        """Verify the server sets frameGraphURI to the immediate owning frame in a hierarchy.

        Creates root → child (each with a slot) via the standalone /kgframes endpoint,
        then queries SPARQL to verify:
          - child slot has hasFrameGraphURI = child_frame_uri  (NOT root_frame_uri)
          - child frame has frameGraphURI = child_frame_uri     (self-referencing)
        """
        try:
            logger.info("🧪 Test: /kgframes frameGraphURI points to immediate owning frame")

            # Use the entity endpoint to set up the hierarchy edge, then verify
            setup = await self._setup_entity_and_root_frame(space_id, graph_id)
            if not setup:
                return False
            entity_uri = setup["entity_uri"]
            root_uri = setup["root_frame_uri"]

            # Create a child frame with a slot under the root
            uid = uuid.uuid4().hex[:8]
            child_objs = self._make_frame_objects(f"fgu_sc_{uid}", "Standalone Grouping Child")
            child_frame_uri = str(child_objs[0].URI)
            child_slot_uri = str(child_objs[1].URI)

            child_uri = await self._create_child_via_entity(
                space_id, graph_id, entity_uri, root_uri,
                f"fgu_sc_{uid}", "Standalone Grouping Child"
            )
            if not child_uri:
                return False

            # Query hasFrameGraphURI for the child's slot
            from vitalgraph.model.sparql_model import SPARQLQueryRequest
            haley = "http://vital.ai/ontology/haley-ai-kg#"

            slot_query = f"""
            SELECT ?frameGraphURI WHERE {{
                GRAPH <{graph_id}> {{
                    <{child_slot_uri}> <{haley}hasFrameGraphURI> ?frameGraphURI .
                }}
            }}
            """
            sparql_resp = await self.client.execute_sparql_query(
                space_id, SPARQLQueryRequest(query=slot_query)
            )

            bindings = []
            if hasattr(sparql_resp, 'results') and sparql_resp.results:
                bindings = sparql_resp.results.get('bindings', [])

            if not bindings:
                logger.error(f"    No hasFrameGraphURI found for slot {child_slot_uri}")
                return False

            actual_fgu = bindings[0].get('frameGraphURI', {}).get('value', '')
            if actual_fgu != child_frame_uri:
                logger.error(
                    f"    Slot frameGraphURI mismatch: expected {child_frame_uri}, got {actual_fgu}"
                )
                return False

            # Verify the child frame's own frameGraphURI points to itself
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

            logger.info("  ✅ frameGraphURI correctly assigned to immediate owning frame (standalone)")
            return True

        except Exception as e:
            logger.error(f"  test_frame_grouping_uri_assignment failed: {e}")
            return False

    # ------------------------------------------------------------------
    # cleanup
    # ------------------------------------------------------------------

    async def cleanup_created_resources(self, space_id: str, graph_id: str) -> bool:
        """Clean up resources created during testing."""
        try:
            logger.info("🧹 Cleaning up frame hierarchy test resources")
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
