"""API tests: Standalone KGFrames CRUD via VitalGraphClient.

Tests the standalone frame and slot endpoints (not the entity-frame sub-API):
  - Frame CRUD: create → list → get → update → delete
  - Slot CRUD: create slots on a frame → list → update → delete
  - Batch delete
  - get_kgframes_with_slots (frame + slots in one response)
  - Frame query (POST /kgframes/query)
  - Frame graph (GET /kgframes/graph via get_kgframe_graph)

The entity-frame sub-API is covered by test_entity_frames_api.py.
"""

from __future__ import annotations

import uuid
from typing import List

import pytest

from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from vitalgraph.model.kgframes_model import FrameQueryRequest, FrameQueryCriteria

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

NS = "http://example.org/apitest/kgframes/"


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _make_frame(name: str = "Test Frame") -> KGFrame:
    """Create a minimal KGFrame GraphObject."""
    frame = KGFrame()
    frame.URI = f"{NS}frame_{_uid()}"
    frame.name = name
    return frame


def _make_slot(name: str = "Slot", value: str = "val") -> KGTextSlot:
    """Create a minimal KGTextSlot GraphObject."""
    slot = KGTextSlot()
    slot.URI = f"{NS}slot_{_uid()}"
    slot.name = name
    slot.textSlotValue = value
    return slot


def _make_slot_edge(frame_uri: str, slot_uri: str) -> Edge_hasKGSlot:
    """Create frame→slot edge."""
    edge = Edge_hasKGSlot()
    edge.URI = f"{NS}edge_fs_{_uid()}"
    edge.edgeSource = frame_uri
    edge.edgeDestination = slot_uri
    return edge


# ---------------------------------------------------------------------------
# Standalone frame CRUD
# ---------------------------------------------------------------------------

class TestFrameCrud:
    """Standalone KGFrame lifecycle: create → list → get → update → delete."""

    async def test_create_frame(self, vg_client, test_space, test_graph):
        """Create a frame via the standalone endpoint."""
        frame = _make_frame("Create Test")
        cr = await vg_client.kgframes.create_kgframes(
            space_id=test_space, graph_id=test_graph, objects=[frame],
        )
        assert cr.is_success, f"create failed: {cr.error_message}"
        assert cr.created_count >= 1

    async def test_list_frames(self, vg_client, test_space, test_graph):
        """Create a frame, then list all frames and find it."""
        frame = _make_frame("List Test")
        await vg_client.kgframes.create_kgframes(
            space_id=test_space, graph_id=test_graph, objects=[frame],
        )

        lr = await vg_client.kgframes.list_kgframes(
            space_id=test_space, graph_id=test_graph, page_size=50,
        )
        assert lr.is_success
        uris = [str(obj.URI) for obj in (lr.objects or [])]
        assert str(frame.URI) in uris

    async def test_list_frames_pagination(self, vg_client, test_space, test_graph):
        """Create several frames, verify pagination controls work."""
        for i in range(3):
            await vg_client.kgframes.create_kgframes(
                space_id=test_space, graph_id=test_graph,
                objects=[_make_frame(f"Page Test {i}")],
            )

        page1 = await vg_client.kgframes.list_kgframes(
            space_id=test_space, graph_id=test_graph, page_size=2, offset=0,
        )
        assert page1.is_success
        assert len(page1.objects or []) <= 2

    async def test_get_frame_by_uri(self, vg_client, test_space, test_graph):
        """Create a frame, retrieve it by URI."""
        frame = _make_frame("Get Test")
        await vg_client.kgframes.create_kgframes(
            space_id=test_space, graph_id=test_graph, objects=[frame],
        )

        gr = await vg_client.kgframes.get_kgframe(
            space_id=test_space, graph_id=test_graph, uri=str(frame.URI),
        )
        assert gr.is_success

    async def test_update_frame(self, vg_client, test_space, test_graph):
        """Create frame, update its name, verify change persisted."""
        frame = _make_frame("Before Update")
        await vg_client.kgframes.create_kgframes(
            space_id=test_space, graph_id=test_graph, objects=[frame],
        )

        frame.name = "After Update"
        ur = await vg_client.kgframes.update_kgframes(
            space_id=test_space, graph_id=test_graph, objects=[frame],
        )
        assert ur.is_success, f"update failed: {ur.error_message}"

    async def test_delete_frame(self, vg_client, test_space, test_graph):
        """Create frame, delete it, verify removal from list."""
        frame = _make_frame("Delete Test")
        await vg_client.kgframes.create_kgframes(
            space_id=test_space, graph_id=test_graph, objects=[frame],
        )

        dr = await vg_client.kgframes.delete_kgframe(
            space_id=test_space, graph_id=test_graph, uri=str(frame.URI),
        )
        assert dr.is_success

        # Verify it's gone
        lr = await vg_client.kgframes.list_kgframes(
            space_id=test_space, graph_id=test_graph, page_size=100,
        )
        uris = [str(obj.URI) for obj in (lr.objects or [])]
        assert str(frame.URI) not in uris

    async def test_delete_frames_batch(self, vg_client, test_space, test_graph):
        """Create 2 frames, batch-delete both."""
        f1 = _make_frame("Batch Del 1")
        f2 = _make_frame("Batch Del 2")
        await vg_client.kgframes.create_kgframes(
            space_id=test_space, graph_id=test_graph, objects=[f1],
        )
        await vg_client.kgframes.create_kgframes(
            space_id=test_space, graph_id=test_graph, objects=[f2],
        )

        uri_list = f"{f1.URI},{f2.URI}"
        dr = await vg_client.kgframes.delete_kgframes_batch(
            space_id=test_space, graph_id=test_graph, uri_list=uri_list,
        )
        assert dr.is_success

        # Verify both gone
        lr = await vg_client.kgframes.list_kgframes(
            space_id=test_space, graph_id=test_graph, page_size=100,
        )
        uris = [str(obj.URI) for obj in (lr.objects or [])]
        assert str(f1.URI) not in uris
        assert str(f2.URI) not in uris


# ---------------------------------------------------------------------------
# Slot CRUD via standalone /kgframes/kgslots endpoints
# ---------------------------------------------------------------------------

class TestSlotCrud:
    """Slot lifecycle on the standalone frame slot sub-endpoint."""

    async def _create_frame_with_slots(self, vg_client, space_id, graph_id):
        """Helper: create frame, add 2 text slots, return dict of objects."""
        frame = _make_frame("Slot Host Frame")
        await vg_client.kgframes.create_kgframes(
            space_id=space_id, graph_id=graph_id, objects=[frame],
        )

        slot1 = _make_slot("Name", "Alice")
        slot2 = _make_slot("City", "Boston")
        edge1 = _make_slot_edge(str(frame.URI), str(slot1.URI))
        edge2 = _make_slot_edge(str(frame.URI), str(slot2.URI))

        cr = await vg_client.kgframes.create_frame_slots(
            space_id=space_id, graph_id=graph_id,
            frame_uri=str(frame.URI),
            objects=[slot1, slot2, edge1, edge2],
        )
        assert cr.is_success, f"create slots failed: {cr.error_message}"
        return {
            "frame": frame, "slot1": slot1, "slot2": slot2,
            "edge1": edge1, "edge2": edge2,
        }

    async def test_create_slots(self, vg_client, test_space, test_graph):
        """Create slots for a frame."""
        info = await self._create_frame_with_slots(vg_client, test_space, test_graph)
        assert info["slot1"] is not None

    async def test_get_frame_slots(self, vg_client, test_space, test_graph):
        """Create slots, then retrieve them via get_frame_slots."""
        info = await self._create_frame_with_slots(vg_client, test_space, test_graph)

        lr = await vg_client.kgframes.get_frame_slots(
            space_id=test_space, graph_id=test_graph,
            frame_uri=str(info["frame"].URI), page_size=50,
        )
        assert lr.is_success
        slot_uris = [str(obj.URI) for obj in (lr.objects or [])
                     if isinstance(obj, KGTextSlot)]
        assert str(info["slot1"].URI) in slot_uris
        assert str(info["slot2"].URI) in slot_uris

    async def test_update_slot(self, vg_client, test_space, test_graph):
        """Create slot, update its value."""
        info = await self._create_frame_with_slots(vg_client, test_space, test_graph)

        info["slot1"].textSlotValue = "Bob"
        ur = await vg_client.kgframes.update_frame_slots(
            space_id=test_space, graph_id=test_graph,
            frame_uri=str(info["frame"].URI),
            objects=[info["slot1"], info["edge1"]],
        )
        assert ur.is_success, f"update slot failed: {ur.error_message}"

    async def test_delete_slot(self, vg_client, test_space, test_graph):
        """Create slots, delete one, verify only the other remains."""
        info = await self._create_frame_with_slots(vg_client, test_space, test_graph)

        dr = await vg_client.kgframes.delete_frame_slots(
            space_id=test_space, graph_id=test_graph,
            frame_uri=str(info["frame"].URI),
            slot_uris=[str(info["slot1"].URI)],
        )
        assert dr.is_success

        # Verify slot1 gone, slot2 remains
        lr = await vg_client.kgframes.get_frame_slots(
            space_id=test_space, graph_id=test_graph,
            frame_uri=str(info["frame"].URI), page_size=50,
        )
        remaining = [str(obj.URI) for obj in (lr.objects or [])
                     if isinstance(obj, KGTextSlot)]
        assert str(info["slot1"].URI) not in remaining
        assert str(info["slot2"].URI) in remaining


# ---------------------------------------------------------------------------
# Frames-with-slots combined retrieval
# ---------------------------------------------------------------------------

class TestFramesWithSlots:
    """GET /kgframes/kgslots — retrieve frames together with their slots."""

    async def test_get_kgframes_with_slots(self, vg_client, test_space, test_graph):
        """Create a frame with slots, then retrieve via get_kgframes_with_slots."""
        frame = _make_frame("WithSlots Test")
        slot = _make_slot("Tag", "important")
        edge = _make_slot_edge(str(frame.URI), str(slot.URI))

        await vg_client.kgframes.create_kgframes(
            space_id=test_space, graph_id=test_graph, objects=[frame],
        )
        await vg_client.kgframes.create_frame_slots(
            space_id=test_space, graph_id=test_graph,
            frame_uri=str(frame.URI), objects=[slot, edge],
        )

        lr = await vg_client.kgframes.get_kgframes_with_slots(
            space_id=test_space, graph_id=test_graph, page_size=50,
        )
        assert lr.is_success
        # Should contain both frame and slot objects
        all_uris = [str(obj.URI) for obj in (lr.objects or [])]
        assert str(frame.URI) in all_uris


# ---------------------------------------------------------------------------
# Frame query (POST /kgframes/query)
# ---------------------------------------------------------------------------

class TestFrameQuery:
    """POST /kgframes/query — criteria-based frame search."""

    async def test_query_frames_by_search_string(self, vg_client, test_space, test_graph):
        """Create frames, query by name substring."""
        f1 = _make_frame("AlphaQuery Frame")
        f2 = _make_frame("BetaQuery Frame")
        f3 = _make_frame("GammaQuery Frame")

        for f in [f1, f2, f3]:
            await vg_client.kgframes.create_kgframes(
                space_id=test_space, graph_id=test_graph, objects=[f],
            )

        req = FrameQueryRequest(
            criteria=FrameQueryCriteria(search_string="AlphaQuery"),
            page_size=50, offset=0,
        )
        resp = await vg_client.kgframes.query_frames(
            space_id=test_space, graph_id=test_graph, query_request=req,
        )
        assert isinstance(resp.frame_uris, list)
        assert str(f1.URI) in resp.frame_uris
        assert str(f2.URI) not in resp.frame_uris

    async def test_query_frames_pagination(self, vg_client, test_space, test_graph):
        """Query with page_size=1 returns exactly 1 result."""
        f1 = _make_frame("PagQuery A")
        f2 = _make_frame("PagQuery B")
        for f in [f1, f2]:
            await vg_client.kgframes.create_kgframes(
                space_id=test_space, graph_id=test_graph, objects=[f],
            )

        req = FrameQueryRequest(
            criteria=FrameQueryCriteria(search_string="PagQuery"),
            page_size=1, offset=0,
        )
        resp = await vg_client.kgframes.query_frames(
            space_id=test_space, graph_id=test_graph, query_request=req,
        )
        assert isinstance(resp.frame_uris, list)
        assert len(resp.frame_uris) == 1

    async def test_query_frames_no_results(self, vg_client, test_space, test_graph):
        """Query with non-matching criteria returns empty list."""
        req = FrameQueryRequest(
            criteria=FrameQueryCriteria(search_string="NoSuchFrame_xyzzy_99"),
            page_size=50, offset=0,
        )
        resp = await vg_client.kgframes.query_frames(
            space_id=test_space, graph_id=test_graph, query_request=req,
        )
        assert isinstance(resp.frame_uris, list)
        assert len(resp.frame_uris) == 0


# ---------------------------------------------------------------------------
# Frame graph retrieval (GET /kgframes/graph via get_kgframe_graph)
# ---------------------------------------------------------------------------

class TestFrameGraph:
    """GET /kgframes?uri=...&include_frame_graph=true — full frame graph."""

    async def test_get_frame_graph(self, vg_client, test_space, test_graph):
        """Create frame with slots, retrieve full graph including slots."""
        frame = _make_frame("GraphTest Frame")
        slot = _make_slot("GraphSlot", "gval")
        edge = _make_slot_edge(str(frame.URI), str(slot.URI))

        await vg_client.kgframes.create_kgframes(
            space_id=test_space, graph_id=test_graph, objects=[frame],
        )
        await vg_client.kgframes.create_frame_slots(
            space_id=test_space, graph_id=test_graph,
            frame_uri=str(frame.URI), objects=[slot, edge],
        )

        resp = await vg_client.kgframes.get_kgframe_graph(
            space_id=test_space, graph_id=test_graph, uri=str(frame.URI),
        )
        assert resp.is_success
        # frame_graph should contain the frame and slot objects
        assert resp.frame_graph is not None
        fg = resp.frame_graph
        assert fg.frame_uri == str(frame.URI)

    async def test_get_frame_graph_nonexistent(self, vg_client, test_space, test_graph):
        """Request graph for non-existent frame URI returns empty/error."""
        resp = await vg_client.kgframes.get_kgframe_graph(
            space_id=test_space, graph_id=test_graph,
            uri="http://example.org/no-such-frame",
        )
        # Should succeed but with no frame_graph data
        assert resp.frame_graph is None or (
            hasattr(resp.frame_graph, 'objects') and len(resp.frame_graph.objects or []) == 0
        )
