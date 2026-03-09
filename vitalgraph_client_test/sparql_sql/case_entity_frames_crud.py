"""
Entity Frames CRUD Test Case — SPARQL-SQL Backend

Tests entity frame lifecycle: create frames on an entity, list, get by URI,
update slot value, delete frame — all via the kgentities endpoint.
Uses programmatically created KGEntity + KGFrame + KGTextSlot + edges.
"""

import logging
import uuid
from typing import Dict, Any

from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot

logger = logging.getLogger(__name__)

NS = "http://example.org/sqlframes/"


def _uid() -> str:
    return str(uuid.uuid4())[:8]


def _make_frame_objects(entity_uri: str):
    """Create a frame with 2 text slots and all required edges."""

    frame_uri = f"{NS}frame_{_uid()}"
    slot1_uri = f"{NS}slot_name_{_uid()}"
    slot2_uri = f"{NS}slot_city_{_uid()}"
    edge_ef_uri = f"{NS}edge_ef_{_uid()}"
    edge_fs1_uri = f"{NS}edge_fs1_{_uid()}"
    edge_fs2_uri = f"{NS}edge_fs2_{_uid()}"

    frame = KGFrame()
    frame.URI = frame_uri
    frame.name = "Contact Info"

    slot1 = KGTextSlot()
    slot1.URI = slot1_uri
    slot1.name = "Full Name"
    slot1.textSlotValue = "Alice Smith"

    slot2 = KGTextSlot()
    slot2.URI = slot2_uri
    slot2.name = "City"
    slot2.textSlotValue = "New York"

    edge_ef = Edge_hasEntityKGFrame()
    edge_ef.URI = edge_ef_uri
    edge_ef.edgeSource = entity_uri
    edge_ef.edgeDestination = frame_uri

    edge_fs1 = Edge_hasKGSlot()
    edge_fs1.URI = edge_fs1_uri
    edge_fs1.edgeSource = frame_uri
    edge_fs1.edgeDestination = slot1_uri

    edge_fs2 = Edge_hasKGSlot()
    edge_fs2.URI = edge_fs2_uri
    edge_fs2.edgeSource = frame_uri
    edge_fs2.edgeDestination = slot2_uri

    return {
        "frame": frame,
        "slot1": slot1,
        "slot2": slot2,
        "objects": [frame, slot1, slot2, edge_ef, edge_fs1, edge_fs2],
        "frame_uri": frame_uri,
        "slot1_uri": slot1_uri,
        "slot2_uri": slot2_uri,
    }


class EntityFramesCrudTester:
    """Client-based test for entity frames CRUD against sparql_sql backend."""

    def __init__(self, client):
        self.client = client

    def _pass(self, results, label):
        logger.info(f"✅ PASS: {label}")
        results["tests_passed"] += 1

    def _fail(self, results, label, err):
        logger.error(f"❌ FAIL: {label} — {err}")
        results["errors"].append(f"{label}: {err}")
        results["tests_failed"] += 1

    async def run_tests(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        results = {
            "test_name": "Entity Frames CRUD",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
        }

        logger.info(f"\n{'=' * 80}")
        logger.info(f"  Entity Frames CRUD")
        logger.info(f"{'=' * 80}")

        # ---- Setup: create host entity ----
        entity_uri = f"{NS}entity_host"
        entity = KGEntity()
        entity.URI = entity_uri
        entity.name = "Host Entity for Frames"

        cr = await self.client.kgentities.create_kgentities(
            space_id=space_id, graph_id=graph_id, objects=[entity])
        if not cr.is_success:
            logger.error(f"❌ Setup failed: could not create host entity — {cr.error_message}")
            return results

        # Build frame + slots
        fd = _make_frame_objects(entity_uri)

        # --- 1. Create entity frames ---
        results["tests_run"] += 1
        try:
            fr = await self.client.kgentities.create_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri,
                objects=fd["objects"])
            if fr.is_success:
                self._pass(results, f"Create entity frame — {len(fd['objects'])} objects")
            else:
                raise Exception(f"msg={getattr(fr, 'error_message', fr)}")
        except Exception as e:
            self._fail(results, "Create entity frames", e)
            return results  # can't continue without frames

        # --- 2. List frames for entity ---
        results["tests_run"] += 1
        try:
            lr = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri, page_size=50)
            frames_found = []
            if lr.is_success and lr.objects:
                for obj in lr.objects:
                    if isinstance(obj, KGFrame):
                        frames_found.append(obj)
            if len(frames_found) >= 1:
                self._pass(results, f"List entity frames — {len(frames_found)} frame(s)")
            else:
                raise Exception(f"expected ≥1 frame, got {len(frames_found)}")
        except Exception as e:
            self._fail(results, "List entity frames", e)

        # --- 3. Get specific frame by URI ---
        results["tests_run"] += 1
        try:
            gr = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri,
                frame_uris=[fd["frame_uri"]])
            if gr.is_success:
                # FrameGraphResponse — check frame_graph
                fg = getattr(gr, 'frame_graph', None)
                obj_count = len(fg.objects) if fg and fg.objects else 0
                if obj_count >= 1:
                    self._pass(results, f"Get frame by URI — {obj_count} objects in frame graph")
                else:
                    raise Exception(f"frame_graph has {obj_count} objects")
            else:
                raise Exception(f"msg={getattr(gr, 'error_message', gr)}")
        except Exception as e:
            self._fail(results, "Get frame by URI", e)

        # --- 4. Verify slot value ---
        results["tests_run"] += 1
        try:
            gr2 = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri,
                frame_uris=[fd["frame_uri"]])
            slot_val = None
            if gr2.is_success:
                fg = getattr(gr2, 'frame_graph', None)
                if fg and fg.objects:
                    for obj in fg.objects:
                        if isinstance(obj, KGTextSlot) and str(obj.URI) == fd["slot1_uri"]:
                            slot_val = str(obj.textSlotValue) if obj.textSlotValue else None
            if slot_val == "Alice Smith":
                self._pass(results, f"Verify slot value — textSlotValue='{slot_val}'")
            else:
                raise Exception(f"expected 'Alice Smith', got '{slot_val}'")
        except Exception as e:
            self._fail(results, "Verify slot value", e)

        # --- 5. Update frame (modify slot value) ---
        results["tests_run"] += 1
        try:
            # Rebuild slot1 with updated value
            updated_slot = KGTextSlot()
            updated_slot.URI = fd["slot1_uri"]
            updated_slot.name = "Full Name"
            updated_slot.textSlotValue = "Alice Johnson"

            # Send complete frame graph — server does delete+reinsert
            edges = [o for o in fd["objects"] if isinstance(o, Edge_hasKGSlot)]
            update_objects = [fd["frame"], updated_slot, fd["slot2"]] + edges

            ur = await self.client.kgentities.update_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri,
                objects=update_objects)
            if ur.is_success:
                self._pass(results, "Update entity frame")
            else:
                raise Exception(f"msg={getattr(ur, 'error_message', ur)}")
        except Exception as e:
            self._fail(results, "Update entity frame", e)

        # --- 6. Verify update ---
        results["tests_run"] += 1
        try:
            gr3 = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri,
                frame_uris=[fd["frame_uri"]])
            slot_val = None
            if gr3.is_success:
                fg = getattr(gr3, 'frame_graph', None)
                if fg and fg.objects:
                    for obj in fg.objects:
                        if isinstance(obj, KGTextSlot) and str(obj.URI) == fd["slot1_uri"]:
                            slot_val = str(obj.textSlotValue) if obj.textSlotValue else None
            if slot_val == "Alice Johnson":
                self._pass(results, f"Verify frame update — textSlotValue='{slot_val}'")
            else:
                raise Exception(f"expected 'Alice Johnson', got '{slot_val}'")
        except Exception as e:
            self._fail(results, "Verify frame update", e)

        # --- 7. Delete frame ---
        results["tests_run"] += 1
        try:
            dr = await self.client.kgentities.delete_entity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri,
                frame_uris=[fd["frame_uri"]])
            if dr.is_success:
                self._pass(results, "Delete entity frame")
            else:
                raise Exception(f"msg={getattr(dr, 'error_message', dr)}")
        except Exception as e:
            self._fail(results, "Delete entity frame", e)

        # --- 8. Verify frame deleted ---
        results["tests_run"] += 1
        try:
            lr2 = await self.client.kgentities.get_kgentity_frames(
                space_id=space_id, graph_id=graph_id,
                entity_uri=entity_uri, page_size=50)
            frames_remaining = []
            if lr2.is_success and lr2.objects:
                for obj in lr2.objects:
                    if isinstance(obj, KGFrame):
                        frames_remaining.append(obj)
            if len(frames_remaining) == 0:
                self._pass(results, "Verify frame deleted — 0 frames remaining")
            else:
                raise Exception(f"expected 0 frames, got {len(frames_remaining)}")
        except Exception as e:
            self._fail(results, "Verify frame deleted", e)

        results["tests_failed"] = results["tests_run"] - results["tests_passed"]
        return results
