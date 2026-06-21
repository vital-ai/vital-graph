#!/usr/bin/env python3
"""
KGEntity Child Frame Update Test Case

Regression test for the child frame update duplication bug.
Verifies that update_entity_frames with parent_frame_uri does NOT create
duplicate Edge_hasKGFrame edges, and that child frame updates are atomic
without affecting siblings.

Bug: The endpoint was unconditionally creating new Edge_hasKGFrame edges
during child frame updates, causing duplicate frames to appear on reload.
Fix: Removed redundant hierarchical edge creation block from _update_entity_frames.
"""

import logging
import uuid
from typing import Dict, List, Optional

from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot

from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph_client_test.client_test_data import ClientTestDataCreator

logger = logging.getLogger(__name__)


class KGEntityChildFrameUpdateTester:
    """Regression tests for child frame update without duplication."""

    def __init__(self, client: VitalGraphClient, test_data_creator: ClientTestDataCreator):
        self.client = client
        self.test_data_creator = test_data_creator
        self.created_entity_uris: List[str] = []

    def _make_frame_with_slots(self, frame_id: str, frame_name: str,
                                slot_values: Dict[str, str]) -> List[GraphObject]:
        """Create a KGFrame with named text slots and connecting edges."""
        frame = KGFrame()
        frame.URI = self.test_data_creator.generate_test_uri("frame", frame_id)
        frame.name = frame_name
        frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#GenericFrame"

        objects: List[GraphObject] = [frame]

        for slot_key, slot_value in slot_values.items():
            slot = KGTextSlot()
            slot.URI = self.test_data_creator.generate_test_uri("slot", f"{frame_id}_{slot_key}")
            slot.name = f"{frame_name} {slot_key}"
            slot.kGSlotType = f"http://vital.ai/ontology/haley-ai-kg#{slot_key}Slot"
            slot.textSlotValue = slot_value
            objects.append(slot)

            edge = Edge_hasKGSlot()
            edge.URI = self.test_data_creator.generate_test_uri("edge", f"{frame_id}_{slot_key}_edge")
            edge.edgeSource = str(frame.URI)
            edge.edgeDestination = str(slot.URI)
            objects.append(edge)

        return objects

    async def _setup_entity_with_parent_and_children(
        self, space_id: str, graph_id: str
    ) -> Optional[Dict[str, str]]:
        """
        Create an entity with a parent frame and two child frames.

        Returns dict with:
            entity_uri, parent_frame_uri, child_0_uri, child_1_uri
        """
        uid = uuid.uuid4().hex[:8]

        # Create entity with a single frame (will be the parent)
        entity_objects = self.test_data_creator.create_person_with_contact(f"ChildUpdate Test {uid}")
        entity_response = await self.client.kgentities.create_kgentities(
            space_id=space_id, graph_id=graph_id, objects=entity_objects
        )
        if not entity_response or not entity_response.created_uris:
            logger.error("Failed to create test entity")
            return None

        entity_uri = str(entity_objects[0].URI)
        self.created_entity_uris.append(entity_uri)

        # Get the first frame as parent
        frames_resp = await self.client.kgentities.get_kgentity_frames(
            space_id=space_id, graph_id=graph_id, entity_uri=entity_uri
        )
        if not hasattr(frames_resp, 'objects') or not frames_resp.objects:
            logger.error("Entity has no frames after creation")
            return None

        parent_frame_uri = str(frames_resp.objects[0].URI)

        # Create child_0
        child_0_objects = self._make_frame_with_slots(
            f"child_0_{uid}", "Child Frame 0",
            {"status": "active", "priority": "high"}
        )
        child_0_uri = str(child_0_objects[0].URI)

        resp_0 = await self.client.kgentities.create_entity_frames(
            space_id=space_id, graph_id=graph_id,
            entity_uri=entity_uri, objects=child_0_objects,
            parent_frame_uri=parent_frame_uri
        )
        if not resp_0.is_success:
            logger.error(f"Failed to create child_0: {resp_0.error_message}")
            return None

        # Create child_1
        child_1_objects = self._make_frame_with_slots(
            f"child_1_{uid}", "Child Frame 1",
            {"status": "pending", "priority": "low"}
        )
        child_1_uri = str(child_1_objects[0].URI)

        resp_1 = await self.client.kgentities.create_entity_frames(
            space_id=space_id, graph_id=graph_id,
            entity_uri=entity_uri, objects=child_1_objects,
            parent_frame_uri=parent_frame_uri
        )
        if not resp_1.is_success:
            logger.error(f"Failed to create child_1: {resp_1.error_message}")
            return None

        logger.info(f"  Setup complete: entity={entity_uri}, parent={parent_frame_uri}, "
                    f"child_0={child_0_uri}, child_1={child_1_uri}")

        return {
            "entity_uri": entity_uri,
            "parent_frame_uri": parent_frame_uri,
            "child_0_uri": child_0_uri,
            "child_1_uri": child_1_uri,
        }

    async def _get_child_frame_uris(self, space_id: str, graph_id: str,
                                     entity_uri: str, parent_frame_uri: str) -> List[str]:
        """Get URIs of child frames under a parent."""
        resp = await self.client.kgentities.get_kgentity_frames(
            space_id=space_id, graph_id=graph_id, entity_uri=entity_uri,
            parent_frame_uri=parent_frame_uri, page_size=100
        )
        if hasattr(resp, 'objects') and resp.objects:
            return [str(obj.URI) for obj in resp.objects if isinstance(obj, KGFrame)]
        return []

    async def _get_frame_graph_objects(self, space_id: str, graph_id: str,
                                       entity_uri: str, frame_uri: str) -> List[GraphObject]:
        """Get full frame graph objects (frame + slots + edges) for a specific frame URI.
        
        Returns the list of GraphObjects from FrameGraphResponse.frame_graph.objects.
        """
        resp = await self.client.kgentities.get_kgentity_frames(
            space_id=space_id, graph_id=graph_id, entity_uri=entity_uri,
            frame_uris=[frame_uri]
        )
        # FrameGraphResponse has frame_graph.objects (not resp.objects)
        if hasattr(resp, 'frame_graph') and resp.frame_graph:
            return list(resp.frame_graph.objects) if resp.frame_graph.objects else []
        return []


    async def test_update_child_frame_preserves_count(self, space_id: str, graph_id: str) -> bool:
        """
        Regression test: Update child frame → child frame count stays the same.
        Previously this would create a duplicate Edge_hasKGFrame, inflating the count.
        """
        try:
            logger.info("🧪 Test: Update child frame preserves frame count (no duplication)")

            setup = await self._setup_entity_with_parent_and_children(space_id, graph_id)
            if not setup:
                return False

            entity_uri = setup["entity_uri"]
            parent_frame_uri = setup["parent_frame_uri"]
            child_0_uri = setup["child_0_uri"]

            # Count children before update
            before_children = await self._get_child_frame_uris(
                space_id, graph_id, entity_uri, parent_frame_uri)
            before_count = len(before_children)
            logger.info(f"  Before update: {before_count} child frames")

            if before_count < 2:
                logger.error(f"  Expected at least 2 children, got {before_count}")
                return False

            # Rebuild child_0 with updated slot value
            uid = uuid.uuid4().hex[:8]
            updated_objects = self._make_frame_with_slots(
                f"placeholder_{uid}", "Child Frame 0",
                {"status": "updated_value", "priority": "high"}
            )
            # Override the frame URI to match existing child_0
            updated_objects[0].URI = child_0_uri
            # Fix slot/edge URIs to use child_0's URI prefix for proper replacement
            for obj in updated_objects[1:]:
                if isinstance(obj, Edge_hasKGSlot):
                    obj.edgeSource = child_0_uri

            # Update child frame
            update_resp = await self.client.kgentities.update_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri, objects=updated_objects,
                parent_frame_uri=parent_frame_uri
            )

            if hasattr(update_resp, 'is_success') and not update_resp.is_success:
                logger.error(f"  Update failed: {update_resp.error_message}")
                return False

            # Count children after update
            after_children = await self._get_child_frame_uris(
                space_id, graph_id, entity_uri, parent_frame_uri)
            after_count = len(after_children)
            logger.info(f"  After update: {after_count} child frames")

            if after_count != before_count:
                logger.error(f"  ❌ Frame count changed! before={before_count}, after={after_count} "
                             f"(duplication bug)")
                return False

            logger.info("  ✅ Child frame count preserved after update")
            return True

        except Exception as e:
            logger.error(f"  test_update_child_frame_preserves_count failed: {e}")
            return False

    async def test_update_child_frame_slot_persists(self, space_id: str, graph_id: str) -> bool:
        """
        Test: Retrieve full child frame graph, modify a slot value in-place,
        send entire frame graph back via update → verify new value persists.
        """
        try:
            logger.info("🧪 Test: Update child frame slot persists")

            setup = await self._setup_entity_with_parent_and_children(space_id, graph_id)
            if not setup:
                return False

            entity_uri = setup["entity_uri"]
            parent_frame_uri = setup["parent_frame_uri"]
            child_0_uri = setup["child_0_uri"]

            slot_type_uri = "http://vital.ai/ontology/haley-ai-kg#statusSlot"

            # 1. Retrieve the full frame graph for child_0
            frame_objects = await self._get_frame_graph_objects(
                space_id, graph_id, entity_uri, child_0_uri)
            logger.info(f"  Retrieved frame graph: {len(frame_objects)} objects")

            if not frame_objects:
                logger.error(f"  ❌ Could not retrieve frame graph for {child_0_uri}")
                return False

            # 2. Find the status slot and modify its value in-place
            slot_found = False
            for obj in frame_objects:
                if isinstance(obj, KGTextSlot):
                    if hasattr(obj, 'kGSlotType') and str(obj.kGSlotType) == slot_type_uri:
                        logger.info(f"  Original status value: {obj.textSlotValue}")
                        obj.textSlotValue = "slot_update_test_value"
                        slot_found = True
                        break

            if not slot_found:
                logger.error(f"  ❌ No slot with kGSlotType={slot_type_uri} found in frame graph")
                return False

            # 3. Send the entire frame graph back as update
            await self.client.kgentities.update_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri, objects=frame_objects,
                parent_frame_uri=parent_frame_uri
            )

            # 4. Re-retrieve and verify the value persisted
            after_objects = await self._get_frame_graph_objects(
                space_id, graph_id, entity_uri, child_0_uri)
            logger.info(f"  After update frame graph: {len(after_objects)} objects")

            for obj in after_objects:
                if isinstance(obj, KGTextSlot):
                    if hasattr(obj, 'kGSlotType') and str(obj.kGSlotType) == slot_type_uri:
                        val = str(obj.textSlotValue) if obj.textSlotValue else None
                        if val == "slot_update_test_value":
                            logger.info("  ✅ Child frame slot value persisted after update")
                            return True
                        else:
                            logger.error(f"  ❌ Slot value not updated. Expected 'slot_update_test_value', got '{val}'")
                            return False

            logger.error(f"  ❌ Status slot not found in frame graph after update")
            return False

        except Exception as e:
            logger.error(f"  test_update_child_frame_slot_persists failed: {e}")
            return False

    async def test_update_child_frame_sibling_untouched(self, space_id: str, graph_id: str) -> bool:
        """
        Test: Updating child_0 does NOT affect child_1's properties.
        """
        try:
            logger.info("🧪 Test: Update child frame leaves sibling untouched")

            setup = await self._setup_entity_with_parent_and_children(space_id, graph_id)
            if not setup:
                return False

            entity_uri = setup["entity_uri"]
            parent_frame_uri = setup["parent_frame_uri"]
            child_0_uri = setup["child_0_uri"]
            child_1_uri = setup["child_1_uri"]

            # Get child_1 name before
            resp_before = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id, entity_uri=entity_uri,
                parent_frame_uri=parent_frame_uri, page_size=100
            )
            child_1_name_before = None
            if hasattr(resp_before, 'objects') and resp_before.objects:
                for obj in resp_before.objects:
                    if isinstance(obj, KGFrame) and str(obj.URI) == child_1_uri:
                        child_1_name_before = str(obj.name) if hasattr(obj, 'name') and obj.name else None
                        break
            logger.info(f"  child_1 name before: {child_1_name_before}")

            # Update child_0 only with a different name
            uid = uuid.uuid4().hex[:8]
            updated_objects = self._make_frame_with_slots(
                f"placeholder_{uid}", "MODIFIED_CHILD_0",
                {"status": "modified_child_0", "priority": "high"}
            )
            updated_objects[0].URI = child_0_uri
            for obj in updated_objects[1:]:
                if isinstance(obj, Edge_hasKGSlot):
                    obj.edgeSource = child_0_uri

            await self.client.kgentities.update_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri, objects=updated_objects,
                parent_frame_uri=parent_frame_uri
            )

            # Verify child_1 name unchanged
            resp_after = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id, entity_uri=entity_uri,
                parent_frame_uri=parent_frame_uri, page_size=100
            )
            child_1_name_after = None
            if hasattr(resp_after, 'objects') and resp_after.objects:
                for obj in resp_after.objects:
                    if isinstance(obj, KGFrame) and str(obj.URI) == child_1_uri:
                        child_1_name_after = str(obj.name) if hasattr(obj, 'name') and obj.name else None
                        break
            logger.info(f"  child_1 name after: {child_1_name_after}")

            if child_1_name_after != child_1_name_before:
                logger.error(f"  ❌ Sibling modified! before='{child_1_name_before}', after='{child_1_name_after}'")
                return False

            logger.info("  ✅ Sibling frame untouched after child update")
            return True

        except Exception as e:
            logger.error(f"  test_update_child_frame_sibling_untouched failed: {e}")
            return False

    async def test_update_top_level_frame_no_duplication(self, space_id: str, graph_id: str) -> bool:
        """
        Test: Updating a top-level frame with parent_frame_uri=None preserves frame count.
        """
        try:
            logger.info("🧪 Test: Update top-level frame with parent_frame_uri=None (no duplication)")

            uid = uuid.uuid4().hex[:8]
            entity_objects = self.test_data_creator.create_person_with_contact(f"TopLevel Test {uid}")
            entity_response = await self.client.kgentities.create_kgentities(
                space_id=space_id, graph_id=graph_id, objects=entity_objects
            )
            if not entity_response or not entity_response.created_uris:
                logger.error("Failed to create entity")
                return False

            entity_uri = str(entity_objects[0].URI)
            self.created_entity_uris.append(entity_uri)

            # Get all frames
            frames_resp = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id, entity_uri=entity_uri
            )
            if not hasattr(frames_resp, 'objects') or not frames_resp.objects:
                logger.error("No frames found")
                return False

            all_frames = [obj for obj in frames_resp.objects if isinstance(obj, KGFrame)]
            before_count = len(all_frames)
            target_frame = all_frames[0]
            target_frame_uri = str(target_frame.URI)
            logger.info(f"  Before: {before_count} top-level frames, updating {target_frame_uri}")

            # Build a minimal update payload with the target frame and a modified slot
            uid2 = uuid.uuid4().hex[:8]
            update_objects = self._make_frame_with_slots(
                f"placeholder_{uid2}", "Top Level Update",
                {"info": "top_level_update_test"}
            )
            # Override frame URI to match target
            update_objects[0].URI = target_frame_uri
            for obj in update_objects[1:]:
                if isinstance(obj, Edge_hasKGSlot):
                    obj.edgeSource = target_frame_uri

            # Update with parent_frame_uri=None (top-level)
            await self.client.kgentities.update_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri, objects=update_objects,
                parent_frame_uri=None
            )

            # Verify frame count
            after_resp = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id, entity_uri=entity_uri
            )
            after_frames = [obj for obj in after_resp.objects if isinstance(obj, KGFrame)] if hasattr(after_resp, 'objects') and after_resp.objects else []
            after_count = len(after_frames)
            logger.info(f"  After: {after_count} top-level frames")

            if after_count != before_count:
                logger.error(f"  ❌ Top-level frame count changed: {before_count} → {after_count}")
                return False

            logger.info("  ✅ Top-level frame update preserved frame count")
            return True

        except Exception as e:
            logger.error(f"  test_update_top_level_frame_no_duplication failed: {e}")
            return False

    async def test_create_new_child_frame_creates_edge(self, space_id: str, graph_id: str) -> bool:
        """
        Test: create_entity_frames with a new child frame correctly creates Edge_hasKGFrame.
        Ensures the fix didn't break CREATE path.
        """
        try:
            logger.info("🧪 Test: create_entity_frames with new child correctly creates edge")

            setup = await self._setup_entity_with_parent_and_children(space_id, graph_id)
            if not setup:
                return False

            entity_uri = setup["entity_uri"]
            parent_frame_uri = setup["parent_frame_uri"]

            # Count before
            before_children = await self._get_child_frame_uris(
                space_id, graph_id, entity_uri, parent_frame_uri)
            before_count = len(before_children)

            # Create a new child frame
            uid = uuid.uuid4().hex[:8]
            new_child_objects = self._make_frame_with_slots(
                f"new_child_{uid}", "Newly Created Child",
                {"description": "created_after_fix"}
            )
            new_child_uri = str(new_child_objects[0].URI)

            create_resp = await self.client.kgentities.create_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri, objects=new_child_objects,
                parent_frame_uri=parent_frame_uri
            )

            if not create_resp.is_success:
                logger.error(f"  create_entity_frames failed: {create_resp.error_message}")
                return False

            # Verify child count increased by exactly 1
            after_children = await self._get_child_frame_uris(
                space_id, graph_id, entity_uri, parent_frame_uri)
            after_count = len(after_children)

            if after_count != before_count + 1:
                logger.error(f"  ❌ Expected {before_count + 1} children, got {after_count}")
                return False

            # Verify new child is in the list
            if new_child_uri not in after_children:
                logger.error(f"  ❌ New child {new_child_uri} not found in children: {after_children}")
                return False

            logger.info(f"  ✅ New child frame created with edge. Children: {before_count} → {after_count}")
            return True

        except Exception as e:
            logger.error(f"  test_create_new_child_frame_creates_edge failed: {e}")
            return False

    async def run_all_tests(self, space_id: str, graph_id: str) -> Dict[str, bool]:
        """Run all child frame update tests and return results."""
        results = {}

        tests = [
            ("update_child_frame_preserves_count", self.test_update_child_frame_preserves_count),
            ("update_child_frame_slot_persists", self.test_update_child_frame_slot_persists),
            ("update_child_frame_sibling_untouched", self.test_update_child_frame_sibling_untouched),
            ("update_top_level_frame_no_duplication", self.test_update_top_level_frame_no_duplication),
            ("create_new_child_frame_creates_edge", self.test_create_new_child_frame_creates_edge),
        ]

        for test_name, test_fn in tests:
            try:
                results[test_name] = await test_fn(space_id, graph_id)
            except Exception as e:
                logger.error(f"  {test_name} raised unexpected exception: {e}")
                results[test_name] = False

        passed = sum(1 for v in results.values() if v)
        total = len(results)
        logger.info(f"\n{'='*60}")
        logger.info(f"  Child Frame Update Tests: {passed}/{total} passed")
        for name, result in results.items():
            status = "✅" if result else "❌"
            logger.info(f"    {status} {name}")
        logger.info(f"{'='*60}")

        return results

    async def cleanup_created_resources(self, space_id: str, graph_id: str) -> bool:
        """Clean up entities created during testing."""
        try:
            logger.info("🧹 Cleaning up child frame update test resources")
            for entity_uri in self.created_entity_uris:
                try:
                    await self.client.kgentities.delete_kgentity(
                        space_id=space_id, graph_id=graph_id,
                        uri=entity_uri, delete_entity_graph=True
                    )
                except Exception as e:
                    logger.warning(f"  Failed to delete entity {entity_uri}: {e}")
            self.created_entity_uris.clear()
            return True
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            return False
