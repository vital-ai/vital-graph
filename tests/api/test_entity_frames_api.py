"""API tests: Entity Frames CRUD via VitalGraphClient.

Tests create frames on an entity, list, get by URI, update slot value, delete frame.
Based on test_scripts/vitalgraph_client_test/sparql_sql/case_entity_frames_crud.py
"""

from __future__ import annotations

import uuid

import pytest

from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

NS = "http://example.org/apitest/frames/"


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _make_frame_objects(entity_uri: str):
    """Create a frame with 2 text slots and all required edges."""
    frame_uri = f"{NS}frame_{_uid()}"
    slot1_uri = f"{NS}slot_name_{_uid()}"
    slot2_uri = f"{NS}slot_city_{_uid()}"

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
    edge_ef.URI = f"{NS}edge_ef_{_uid()}"
    edge_ef.edgeSource = entity_uri
    edge_ef.edgeDestination = frame_uri

    edge_fs1 = Edge_hasKGSlot()
    edge_fs1.URI = f"{NS}edge_fs1_{_uid()}"
    edge_fs1.edgeSource = frame_uri
    edge_fs1.edgeDestination = slot1_uri

    edge_fs2 = Edge_hasKGSlot()
    edge_fs2.URI = f"{NS}edge_fs2_{_uid()}"
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


class TestEntityFramesCrud:
    """Entity frame lifecycle: create → list → get → update → delete."""

    async def test_create_entity_frames(self, vg_client, test_space, test_graph):
        """Create a host entity then attach a frame with slots."""
        entity_uri = f"{NS}entity_host_{_uid()}"
        entity = KGEntity()
        entity.URI = entity_uri
        entity.name = "Host Entity for Frames"

        cr = await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=[entity]
        )
        assert cr.is_success, f"host entity create failed: {cr.error_message}"

        fd = _make_frame_objects(entity_uri)
        fr = await vg_client.kgentities.create_entity_frames(
            space_id=test_space, graph_id=test_graph,
            entity_uri=entity_uri, objects=fd["objects"]
        )
        assert fr.is_success, f"create frames failed: {fr.error_message}"

    async def test_list_entity_frames(self, vg_client, test_space, test_graph):
        """Create entity+frame, list frames, expect at least 1 KGFrame."""
        entity_uri = f"{NS}entity_list_{_uid()}"
        entity = KGEntity()
        entity.URI = entity_uri
        entity.name = "List Frames Entity"

        await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=[entity]
        )
        fd = _make_frame_objects(entity_uri)
        await vg_client.kgentities.create_entity_frames(
            space_id=test_space, graph_id=test_graph,
            entity_uri=entity_uri, objects=fd["objects"]
        )

        lr = await vg_client.kgentities.get_kgentity_frames(
            space_id=test_space, graph_id=test_graph,
            entity_uri=entity_uri, page_size=50
        )
        assert lr.is_success
        frames = [obj for obj in (lr.objects or []) if isinstance(obj, KGFrame)]
        assert len(frames) >= 1

    async def test_get_frame_by_uri(self, vg_client, test_space, test_graph):
        """Get a specific frame by URI and verify slot value."""
        entity_uri = f"{NS}entity_get_{_uid()}"
        entity = KGEntity()
        entity.URI = entity_uri
        entity.name = "Get Frame Entity"

        await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=[entity]
        )
        fd = _make_frame_objects(entity_uri)
        await vg_client.kgentities.create_entity_frames(
            space_id=test_space, graph_id=test_graph,
            entity_uri=entity_uri, objects=fd["objects"]
        )

        gr = await vg_client.kgentities.get_kgentity_frames(
            space_id=test_space, graph_id=test_graph,
            entity_uri=entity_uri, frame_uris=[fd["frame_uri"]]
        )
        assert gr.is_success
        fg = getattr(gr, "frame_graph", None)
        assert fg is not None and fg.objects and len(fg.objects) >= 1

        # Find slot1 and verify value
        slot_val = None
        for obj in fg.objects:
            if isinstance(obj, KGTextSlot) and str(obj.URI) == fd["slot1_uri"]:
                slot_val = str(obj.textSlotValue) if obj.textSlotValue else None
        assert slot_val == "Alice Smith"

    async def test_update_entity_frame(self, vg_client, test_space, test_graph):
        """Update a slot value in a frame, verify change persisted."""
        entity_uri = f"{NS}entity_upd_{_uid()}"
        entity = KGEntity()
        entity.URI = entity_uri
        entity.name = "Update Frame Entity"

        await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=[entity]
        )
        fd = _make_frame_objects(entity_uri)
        await vg_client.kgentities.create_entity_frames(
            space_id=test_space, graph_id=test_graph,
            entity_uri=entity_uri, objects=fd["objects"]
        )

        # Modify slot1 value
        updated_slot = KGTextSlot()
        updated_slot.URI = fd["slot1_uri"]
        updated_slot.name = "Full Name"
        updated_slot.textSlotValue = "Alice Johnson"

        edges = [o for o in fd["objects"] if isinstance(o, Edge_hasKGSlot)]
        update_objects = [fd["frame"], updated_slot, fd["slot2"]] + edges

        ur = await vg_client.kgentities.update_entity_frames(
            space_id=test_space, graph_id=test_graph,
            entity_uri=entity_uri, objects=update_objects
        )
        assert ur.is_success, f"update frame failed: {ur.error_message}"

        # Verify
        gr = await vg_client.kgentities.get_kgentity_frames(
            space_id=test_space, graph_id=test_graph,
            entity_uri=entity_uri, frame_uris=[fd["frame_uri"]]
        )
        assert gr.is_success
        fg = getattr(gr, "frame_graph", None)
        slot_val = None
        if fg and fg.objects:
            for obj in fg.objects:
                if isinstance(obj, KGTextSlot) and str(obj.URI) == fd["slot1_uri"]:
                    slot_val = str(obj.textSlotValue) if obj.textSlotValue else None
        assert slot_val == "Alice Johnson"

    async def test_delete_entity_frame(self, vg_client, test_space, test_graph):
        """Delete a frame, verify 0 frames remain."""
        entity_uri = f"{NS}entity_del_{_uid()}"
        entity = KGEntity()
        entity.URI = entity_uri
        entity.name = "Delete Frame Entity"

        await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=[entity]
        )
        fd = _make_frame_objects(entity_uri)
        await vg_client.kgentities.create_entity_frames(
            space_id=test_space, graph_id=test_graph,
            entity_uri=entity_uri, objects=fd["objects"]
        )

        dr = await vg_client.kgentities.delete_entity_frames(
            space_id=test_space, graph_id=test_graph,
            entity_uri=entity_uri, frame_uris=[fd["frame_uri"]]
        )
        assert dr.is_success

        # Verify gone
        lr = await vg_client.kgentities.get_kgentity_frames(
            space_id=test_space, graph_id=test_graph,
            entity_uri=entity_uri, page_size=50
        )
        frames = [obj for obj in (lr.objects or []) if isinstance(obj, KGFrame)]
        assert len(frames) == 0
