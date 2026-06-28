#!/usr/bin/env python3
"""
KGEntity Entity-Only Update Test Case

Tests the entity_only operation mode which updates only entity properties
without touching the frame graph (slots, edges, child frames).

Uses create_person_with_contact from ClientTestDataCreator which produces
entities with Edge_hasEntityKGFrame, frames, slots, and Edge_hasKGSlot edges.
"""

import logging
import uuid
from typing import Dict, List

from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame

from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError
from vitalgraph_client_test.client_test_data import ClientTestDataCreator

logger = logging.getLogger(__name__)


class KGEntityOnlyUpdateTester:
    """Tests for entity_only update mode."""

    def __init__(self, client: VitalGraphClient, test_data_creator: ClientTestDataCreator):
        self.client = client
        self.test_data_creator = test_data_creator
        self.created_entity_uris: List[str] = []

    async def _create_entity_with_frames(self, space_id: str, graph_id: str) -> Dict:
        """Create a test entity with frames and slots using the proven pattern."""
        uid = uuid.uuid4().hex[:8]
        name = f"EntityOnlyTest {uid}"

        # Use create_person_with_contact which includes Edge_hasEntityKGFrame
        all_objects = self.test_data_creator.create_person_with_contact(name)
        entity_uri = str(all_objects[0].URI)

        create_resp = await self.client.kgentities.create_kgentities(
            space_id=space_id, graph_id=graph_id, objects=all_objects
        )
        if not create_resp or not create_resp.created_uris:
            raise RuntimeError(f"Failed to create test entity: {create_resp}")

        self.created_entity_uris.append(entity_uri)

        return {
            "entity_uri": entity_uri,
            "entity_name": name,
            "uid": uid,
        }

    async def _get_entity_object(self, space_id: str, graph_id: str, entity_uri: str):
        """Retrieve a KGEntity object by URI."""
        resp = await self.client.kgentities.get_kgentity(
            space_id=space_id, graph_id=graph_id, uri=entity_uri
        )
        if hasattr(resp, 'objects') and resp.objects:
            for obj in resp.objects:
                if isinstance(obj, KGEntity):
                    return obj
        return None

    async def test_entity_only_preserves_frames(self, space_id: str, graph_id: str) -> bool:
        """Test: entity_only update preserves frames and slots."""
        try:
            logger.info("Test: entity_only update preserves frames")

            setup = await self._create_entity_with_frames(space_id, graph_id)
            entity_uri = setup["entity_uri"]

            # Count frames before update
            frames_before = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id, entity_uri=entity_uri
            )
            initial_count = len(frames_before.objects) if hasattr(frames_before, 'objects') and frames_before.objects else 0
            logger.info(f"  Frames before: {initial_count}")

            if initial_count == 0:
                logger.error("  FAIL: Entity has no frames after creation — test setup broken")
                return False

            # Get entity, modify name, update with entity_only
            entity_obj = await self._get_entity_object(space_id, graph_id, entity_uri)
            if not entity_obj:
                logger.error("  FAIL: Could not retrieve entity")
                return False

            entity_obj.name = "Updated Name via entity_only"
            resp = await self.client.kgentities.update_entity_only(
                space_id=space_id, graph_id=graph_id, objects=[entity_obj]
            )
            logger.info(f"  Update response: success={resp.is_success}, msg={resp.message}")

            if not resp.is_success:
                logger.error(f"  FAIL: update_entity_only returned failure: {resp.message}")
                return False

            # Verify frames still exist
            frames_after = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id, entity_uri=entity_uri
            )
            after_count = len(frames_after.objects) if hasattr(frames_after, 'objects') and frames_after.objects else 0
            logger.info(f"  Frames after: {after_count}")

            if after_count == 0:
                logger.error(f"  FAIL: Frames wiped! Was {initial_count}, now 0")
                return False

            if after_count < initial_count:
                logger.error(f"  FAIL: Frames reduced from {initial_count} to {after_count}")
                return False

            logger.info("  PASS: Frames preserved after entity_only update")
            return True

        except Exception as e:
            logger.error(f"  test_entity_only_preserves_frames failed: {e}", exc_info=True)
            return False

    async def test_entity_only_updates_properties(self, space_id: str, graph_id: str) -> bool:
        """Test: entity_only update actually changes entity properties."""
        try:
            logger.info("Test: entity_only updates entity properties")

            setup = await self._create_entity_with_frames(space_id, graph_id)
            entity_uri = setup["entity_uri"]

            entity_obj = await self._get_entity_object(space_id, graph_id, entity_uri)
            if not entity_obj:
                logger.error("  FAIL: Could not retrieve entity")
                return False

            original_name = str(entity_obj.name) if entity_obj.name else ""
            new_name = f"entity_only_renamed_{setup['uid']}"
            entity_obj.name = new_name

            resp = await self.client.kgentities.update_entity_only(
                space_id=space_id, graph_id=graph_id, objects=[entity_obj]
            )
            logger.info(f"  Update response: success={resp.is_success}, msg={resp.message}")

            if not resp.is_success:
                logger.error(f"  FAIL: update_entity_only returned failure: {resp.message}")
                return False

            # Re-retrieve and verify name changed
            entity_obj2 = await self._get_entity_object(space_id, graph_id, entity_uri)
            if not entity_obj2:
                logger.error("  FAIL: Could not retrieve entity after update")
                return False

            actual_name = str(entity_obj2.name) if entity_obj2.name else ""
            if actual_name != new_name:
                logger.error(f"  FAIL: Name not updated. Expected: {new_name}, Got: {actual_name}")
                return False

            logger.info(f"  PASS: Entity name updated from '{original_name}' to '{actual_name}'")
            return True

        except Exception as e:
            logger.error(f"  test_entity_only_updates_properties failed: {e}", exc_info=True)
            return False

    async def test_entity_only_rejects_non_entity(self, space_id: str, graph_id: str) -> bool:
        """Test: entity_only rejects payloads with non-KGEntity objects."""
        try:
            logger.info("Test: entity_only rejects non-entity objects")

            setup = await self._create_entity_with_frames(space_id, graph_id)
            entity_uri = setup["entity_uri"]

            entity_obj = await self._get_entity_object(space_id, graph_id, entity_uri)
            if not entity_obj:
                logger.error("  FAIL: Could not retrieve entity")
                return False

            # Try sending entity + a frame (should be rejected)
            frame = KGFrame()
            frame.URI = self.test_data_creator.generate_test_uri("frame", "rejected_frame")
            frame.name = "Should be rejected"

            try:
                resp = await self.client.kgentities.update_entity_only(
                    space_id=space_id, graph_id=graph_id, objects=[entity_obj, frame]
                )
                # Server returns 200 with error in message field
                if hasattr(resp, 'is_success') and not resp.is_success:
                    logger.info(f"  PASS: Correctly rejected (is_success=False): {resp.message}")
                    return True
                # Also check message for rejection text
                msg = str(resp.message) if hasattr(resp, 'message') else ""
                if "only accepts" in msg or "entity_only" in msg.lower():
                    logger.info(f"  PASS: Correctly rejected via message: {msg}")
                    return True
                logger.error(f"  FAIL: Should have rejected but got success. msg={msg}")
                return False
            except VitalGraphClientError as e:
                # HTTP error is also acceptable rejection
                logger.info(f"  PASS: Correctly rejected with error: {e}")
                return True

        except Exception as e:
            logger.error(f"  test_entity_only_rejects_non_entity failed: {e}", exc_info=True)
            return False

    async def test_entity_only_preserves_creation_time(self, space_id: str, graph_id: str) -> bool:
        """Test: entity_only preserves hasObjectCreationTime."""
        try:
            logger.info("Test: entity_only preserves creation time")

            setup = await self._create_entity_with_frames(space_id, graph_id)
            entity_uri = setup["entity_uri"]

            # Get entity to capture creation time
            entity_obj = await self._get_entity_object(space_id, graph_id, entity_uri)
            if not entity_obj:
                logger.error("  FAIL: Could not retrieve entity")
                return False

            creation_time = getattr(entity_obj, 'objectCreationTime', None)
            logger.info(f"  Creation time before: {creation_time}")

            if creation_time is None:
                logger.warning("  WARN: No creation time on entity (server may not have stamped it)")

            # Update name
            entity_obj.name = f"time_test_{setup['uid']}"
            resp = await self.client.kgentities.update_entity_only(
                space_id=space_id, graph_id=graph_id, objects=[entity_obj]
            )

            if not resp.is_success:
                logger.error(f"  FAIL: update_entity_only returned failure: {resp.message}")
                return False

            # Re-retrieve
            entity_obj2 = await self._get_entity_object(space_id, graph_id, entity_uri)
            if not entity_obj2:
                logger.error("  FAIL: Could not retrieve entity after update")
                return False

            creation_time2 = getattr(entity_obj2, 'objectCreationTime', None)
            logger.info(f"  Creation time after: {creation_time2}")

            if creation_time is not None and creation_time2 is not None:
                if str(creation_time) == str(creation_time2):
                    logger.info("  PASS: Creation time preserved")
                    return True
                else:
                    logger.error(f"  FAIL: Creation time changed: {creation_time} -> {creation_time2}")
                    return False
            elif creation_time is None and creation_time2 is None:
                logger.info("  PASS: No creation time set (both None) — acceptable")
                return True
            else:
                logger.error(f"  FAIL: Creation time mismatch: {creation_time} vs {creation_time2}")
                return False

        except Exception as e:
            logger.error(f"  test_entity_only_preserves_creation_time failed: {e}", exc_info=True)
            return False

    async def run_all_tests(self, space_id: str, graph_id: str) -> Dict[str, bool]:
        """Run all entity-only update tests."""
        results = {}

        results["entity_only_preserves_frames"] = await self.test_entity_only_preserves_frames(space_id, graph_id)
        results["entity_only_updates_properties"] = await self.test_entity_only_updates_properties(space_id, graph_id)
        results["entity_only_rejects_non_entity"] = await self.test_entity_only_rejects_non_entity(space_id, graph_id)
        results["entity_only_preserves_creation_time"] = await self.test_entity_only_preserves_creation_time(space_id, graph_id)

        passed = sum(1 for v in results.values() if v)
        total = len(results)
        logger.info(f"  Entity-Only Update Tests: {passed}/{total} passed")
        for name, result in results.items():
            logger.info(f"    {'PASS' if result else 'FAIL'} {name}")

        return results

    async def cleanup_created_resources(self, space_id: str, graph_id: str):
        """Delete test entities."""
        for uri in self.created_entity_uris:
            try:
                await self.client.kgentities.delete_kgentity(
                    space_id=space_id, graph_id=graph_id,
                    uri=uri, delete_entity_graph=True
                )
            except Exception:
                pass
        self.created_entity_uris.clear()
