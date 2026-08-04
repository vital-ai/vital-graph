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

    async def test_paging_partitions_frames_with_slots(
        self, vg_client, test_space, test_graph
    ):
        """Paging over frames+slots must return each subject exactly once.

        Regression test for unstable paging: this endpoint applied
        LIMIT/OFFSET with no ORDER BY, so successive pages could repeat or
        skip subjects.  Small page_size maximizes the number of page
        boundaries and therefore the chance of catching it.

        See planning/planning_sequence/frame_slot_sequence_sort_paging_plan.md
        """
        # A handful of frames, each with a slot, so paging crosses the
        # frame/slot UNION boundary repeatedly.
        for i in range(4):
            f = _make_frame(f"Partition Test {i}")
            s = _make_slot(f"PartSlot{i}", f"v{i}")
            e = _make_slot_edge(str(f.URI), str(s.URI))
            await vg_client.kgframes.create_kgframes(
                space_id=test_space, graph_id=test_graph, objects=[f],
            )
            await vg_client.kgframes.create_frame_slots(
                space_id=test_space, graph_id=test_graph,
                frame_uri=str(f.URI), objects=[s, e],
            )

        unpaged = await vg_client.kgframes.get_kgframes_with_slots(
            space_id=test_space, graph_id=test_graph, page_size=1000,
        )
        assert unpaged.is_success
        expected = {str(o.URI) for o in (unpaged.objects or [])}
        assert len(expected) >= 8, "fixture did not produce enough subjects"

        page_size = 3
        seen: List[str] = []
        for offset in range(0, len(expected) + page_size, page_size):
            page = await vg_client.kgframes.get_kgframes_with_slots(
                space_id=test_space, graph_id=test_graph,
                page_size=page_size, offset=offset,
            )
            assert page.is_success
            seen.extend(str(o.URI) for o in (page.objects or []))

        # No subject may appear on two pages...
        assert len(seen) == len(set(seen)), (
            f"paging returned duplicate subjects: "
            f"{sorted(u for u in set(seen) if seen.count(u) > 1)}"
        )
        # ...and none may be skipped.
        assert set(seen) == expected, (
            f"paging lost subjects: {sorted(expected - set(seen))}"
        )



# ---------------------------------------------------------------------------
# Frame query (POST /kgframes/query)
# ---------------------------------------------------------------------------

class TestFrameSorting:
    """GET /kgframes sort_by — ordering must survive to the response.

    Fixtures decorrelate name order, sequence order and URI order from each
    other. If any two agreed, an ignored ORDER BY would look correct.
    """

    NAME_PROP = "http://vital.ai/ontology/vital-core#hasName"
    SEQ_PROP = "http://vital.ai/ontology/haley-ai-kg#hasFrameSequence"

    async def _seed(self, vg_client, test_space, test_graph):
        ns = f"{NS}sort_{_uid()}/"
        # URI order f01..f05; names reverse-alphabetical; sequence reversed too
        names = ["Zeta", "Yankee", "Xray", "Bravo", "Alpha"]
        objs = []
        for i, n in enumerate(names, 1):
            f = KGFrame()
            f.URI = f"{ns}f{i:02d}"
            f.name = n
            f.frameSequence = 6 - i
            objs.append(f)
        cr = await vg_client.kgframes.create_kgframes(
            space_id=test_space, graph_id=test_graph, objects=objs)
        assert cr.is_success, cr.error_message
        return ns

    async def _list(self, vg_client, test_space, test_graph, ns, **kw):
        lr = await vg_client.kgframes.list_kgframes(
            space_id=test_space, graph_id=test_graph, page_size=1000, **kw)
        assert lr.is_success
        return [str(o.URI).rsplit("/", 1)[-1]
                for o in (lr.objects or []) if str(o.URI).startswith(ns)]

    async def test_sort_by_name_ascending(self, vg_client, test_space, test_graph):
        """Alpha..Zeta — the exact reverse of URI order."""
        ns = await self._seed(vg_client, test_space, test_graph)
        got = await self._list(vg_client, test_space, test_graph, ns,
                               sort_by=self.NAME_PROP, sort_order="asc")
        assert got == ["f05", "f04", "f03", "f02", "f01"], got

    async def test_sort_by_name_descending(self, vg_client, test_space, test_graph):
        ns = await self._seed(vg_client, test_space, test_graph)
        got = await self._list(vg_client, test_space, test_graph, ns,
                               sort_by=self.NAME_PROP, sort_order="desc")
        assert got == ["f01", "f02", "f03", "f04", "f05"], got

    async def test_sort_by_sequence_ascending(self, vg_client, test_space, test_graph):
        """hasFrameSequence 1..5, which is the reverse of URI order."""
        ns = await self._seed(vg_client, test_space, test_graph)
        got = await self._list(vg_client, test_space, test_graph, ns,
                               sort_by=self.SEQ_PROP, sort_order="asc")
        assert got == ["f05", "f04", "f03", "f02", "f01"], got

    async def test_sort_by_sequence_descending(self, vg_client, test_space, test_graph):
        ns = await self._seed(vg_client, test_space, test_graph)
        got = await self._list(vg_client, test_space, test_graph, ns,
                               sort_by=self.SEQ_PROP, sort_order="desc")
        assert got == ["f01", "f02", "f03", "f04", "f05"], got

    async def test_sorted_paging_preserves_order(
        self, vg_client, test_space, test_graph
    ):
        """Concatenated pages equal the unpaged sorted order, each URI once.

        Pages the WHOLE space, not just this test's namespace: the space is
        module-scoped and other tests add frames, so a page boundary rarely
        lines up with the namespace. Filtering after paging is what makes the
        comparison meaningful.
        """
        ns = await self._seed(vg_client, test_space, test_graph)
        expected = await self._list(vg_client, test_space, test_graph, ns,
                                    sort_by=self.SEQ_PROP, sort_order="asc")
        assert len(expected) == 5, expected

        first = await vg_client.kgframes.list_kgframes(
            space_id=test_space, graph_id=test_graph, page_size=1,
            sort_by=self.SEQ_PROP, sort_order="asc")
        total = first.total_count

        page_size = 2
        seen = []
        for offset in range(0, total + page_size, page_size):
            lr = await vg_client.kgframes.list_kgframes(
                space_id=test_space, graph_id=test_graph, page_size=page_size,
                offset=offset, sort_by=self.SEQ_PROP, sort_order="asc")
            assert lr.is_success
            seen.extend(str(o.URI).rsplit("/", 1)[-1]
                        for o in (lr.objects or []) if str(o.URI).startswith(ns))

        assert seen == expected, f"paged {seen} != unpaged {expected}"


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


class TestFramesWithSlotsFilters:
    """GET /kgframes/kgslots — search and slot-type filters.

    Both were previously accepted and silently ignored: `search` reached the
    query builder but was never used, and the Python client sent `slot_type`
    while the route declares `kGSlotType`.
    """

    async def _seed(self, vg_client, test_space, test_graph):
        ns = f"{NS}filt_{_uid()}/"
        objs = []
        for label in ("Findable", "Otherwise"):
            f = KGFrame()
            f.URI = f"{ns}{label.lower()}_frame"
            f.name = f"{label} Frame"
            s = KGTextSlot()
            s.URI = f"{ns}{label.lower()}_slot"
            s.name = f"{label} Slot"
            s.textSlotValue = "v"
            e = _make_slot_edge(str(f.URI), str(s.URI))
            await vg_client.kgframes.create_kgframes(
                space_id=test_space, graph_id=test_graph, objects=[f])
            await vg_client.kgframes.create_frame_slots(
                space_id=test_space, graph_id=test_graph,
                frame_uri=str(f.URI), objects=[s, e])
            objs.append(str(f.URI))
        return ns

    async def test_search_narrows_to_matching_frames_and_their_slots(
        self, vg_client, test_space, test_graph
    ):
        """A search term returns the matching frame AND its slots, nothing else."""
        ns = await self._seed(vg_client, test_space, test_graph)

        lr = await vg_client.kgframes.get_kgframes_with_slots(
            space_id=test_space, graph_id=test_graph,
            page_size=1000, search="Findable")
        assert lr.is_success, lr.error_message

        mine = [str(o.URI) for o in (lr.objects or []) if str(o.URI).startswith(ns)]
        assert f"{ns}findable_frame" in mine, mine
        assert f"{ns}findable_slot" in mine, mine
        # the non-matching frame and its slot must be excluded
        assert f"{ns}otherwise_frame" not in mine, mine
        assert f"{ns}otherwise_slot" not in mine, mine

    async def test_search_is_ignored_when_absent(
        self, vg_client, test_space, test_graph
    ):
        """Without a search term both frames come back — guards over-filtering."""
        ns = await self._seed(vg_client, test_space, test_graph)

        lr = await vg_client.kgframes.get_kgframes_with_slots(
            space_id=test_space, graph_id=test_graph, page_size=1000)
        assert lr.is_success
        mine = [str(o.URI) for o in (lr.objects or []) if str(o.URI).startswith(ns)]
        assert f"{ns}findable_frame" in mine
        assert f"{ns}otherwise_frame" in mine

    async def test_search_term_with_a_quote_does_not_break_the_query(
        self, vg_client, test_space, test_graph
    ):
        """A double quote must be escaped, not terminate the SPARQL literal."""
        await self._seed(vg_client, test_space, test_graph)
        lr = await vg_client.kgframes.get_kgframes_with_slots(
            space_id=test_space, graph_id=test_graph,
            page_size=10, search='no"such"frame')
        assert lr.is_success, lr.error_message

    async def test_slot_type_filter_reaches_the_server(
        self, vg_client, test_space, test_graph
    ):
        """Regression: the client sent slot_type, the route reads kGSlotType.

        With a slot type that matches nothing, a working filter returns no
        slots. Before the fix the param was dropped and everything came back.
        """
        ns = await self._seed(vg_client, test_space, test_graph)

        lr = await vg_client.kgframes.get_frame_slots(
            space_id=test_space, graph_id=test_graph,
            frame_uri=f"{ns}findable_frame",
            slot_type="http://example.org/no-such-slot-type",
            page_size=1000)
        assert lr.is_success, lr.error_message
        slot_uris = [str(o.URI) for o in (lr.objects or [])
                     if str(o.URI).startswith(ns) and "_slot" in str(o.URI)]
        assert slot_uris == [], slot_uris


# ---------------------------------------------------------------------------
# Parent object validation (issues/024)
# ---------------------------------------------------------------------------

class TestParentObjectValidation:
    """_validate_parent_object must identify the parent's type via ASK.

    The observable effect is which parent edge gets created:
    KGEntity parent → Edge_hasEntityKGFrame, KGFrame parent → Edge_hasKGFrame,
    and an unknown parent → no edge at all. A regression that makes the ASK
    return a falsy boolean silently drops the parent edge, and no other test
    covers this.
    """

    _HALEY = "http://vital.ai/ontology/haley-ai-kg#"

    async def _edges_from(self, vg_client, test_space, test_graph, parent_uri):
        """Return the set of edge types whose source is parent_uri."""
        from vitalgraph.model.sparql_model import SPARQLQueryRequest

        q = (
            f'SELECT ?type WHERE {{ GRAPH <{test_graph}> {{ '
            f'?e <http://vital.ai/ontology/vital-core#hasEdgeSource> <{parent_uri}> . '
            f'?e a ?type . }} }}'
        )
        r = await vg_client.sparql.execute_sparql_query(
            test_space, SPARQLQueryRequest(query=q)
        )
        bindings = r.results.get("bindings", []) if r.results else []
        return {b["type"]["value"] for b in bindings}

    async def test_frame_parent_creates_frame_edge(
        self, vg_client, test_space, test_graph
    ):
        """A KGFrame parent must be identified as a frame and get Edge_hasKGFrame."""
        parent = _make_frame("Parent Frame")
        await vg_client.kgframes.create_kgframes(
            space_id=test_space, graph_id=test_graph, objects=[parent],
        )

        child = _make_frame("Child Frame")
        cr = await vg_client.kgframes.create_kgframes(
            space_id=test_space, graph_id=test_graph, objects=[child],
            parent_uri=str(parent.URI),
        )
        assert cr.is_success, f"create failed: {cr.error_message}"

        edge_types = await self._edges_from(
            vg_client, test_space, test_graph, str(parent.URI)
        )
        assert f"{self._HALEY}Edge_hasKGFrame" in edge_types, (
            f"parent edge missing or wrong type: {edge_types}"
        )

    async def test_unknown_parent_creates_no_edge(
        self, vg_client, test_space, test_graph
    ):
        """A parent URI that exists in no graph must yield no parent edge.

        The frame itself is still created — _handle_parent_relationships logs
        and returns the objects unchanged rather than failing the request.
        """
        bogus = f"{NS}nonexistent_{_uid()}"

        child = _make_frame("Orphan Child")
        cr = await vg_client.kgframes.create_kgframes(
            space_id=test_space, graph_id=test_graph, objects=[child],
            parent_uri=bogus,
        )
        assert cr.is_success, f"create failed: {cr.error_message}"

        edge_types = await self._edges_from(
            vg_client, test_space, test_graph, bogus
        )
        assert edge_types == set(), (
            f"edge created for a nonexistent parent: {edge_types}"
        )
