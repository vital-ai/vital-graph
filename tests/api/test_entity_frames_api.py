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


class TestEntityFramesSorting:
    """GET /kgentities/kgframes sort_by — ordering through the Python client.

    Frame sequence is deliberately the REVERSE of URI order, so an ignored
    ORDER BY (or an order lost while rebuilding objects from triples) shows up
    immediately.
    """

    SEQ_PROP = "http://vital.ai/ontology/haley-ai-kg#hasFrameSequence"

    async def _seed(self, vg_client, test_space, test_graph):
        ns = f"{NS}sort_{_uid()}/"
        entity = KGEntity()
        entity.URI = f"{ns}entity"
        entity.name = "Sort Test Entity"
        objs = [entity]
        for i in range(1, 6):
            f = KGFrame()
            f.URI = f"{ns}f{i:02d}"
            f.name = f"Frame {i}"
            f.frameSequence = 6 - i          # f01→5 … f05→1
            e = Edge_hasEntityKGFrame()
            e.URI = f"{ns}edge{i}"
            e.edgeSource = str(entity.URI)
            e.edgeDestination = str(f.URI)
            objs += [f, e]
        cr = await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=objs)
        assert cr.is_success, cr.error_message
        return ns, str(entity.URI)

    async def _frames(self, vg_client, test_space, test_graph, ns, entity_uri, **kw):
        r = await vg_client.get_kgentity_frames(
            space_id=test_space, graph_id=test_graph, entity_uri=entity_uri,
            page_size=100, **kw)
        objs = getattr(r, "objects", None) or []
        return [str(o.URI).rsplit("/", 1)[-1]
                for o in objs if str(o.URI).startswith(f"{ns}f")]

    async def test_sort_by_sequence_ascending(self, vg_client, test_space, test_graph):
        ns, entity_uri = await self._seed(vg_client, test_space, test_graph)
        got = await self._frames(vg_client, test_space, test_graph, ns, entity_uri,
                                 sort_by=self.SEQ_PROP, sort_order="asc")
        assert got == ["f05", "f04", "f03", "f02", "f01"], got

    async def test_sort_by_sequence_descending(self, vg_client, test_space, test_graph):
        ns, entity_uri = await self._seed(vg_client, test_space, test_graph)
        got = await self._frames(vg_client, test_space, test_graph, ns, entity_uri,
                                 sort_by=self.SEQ_PROP, sort_order="desc")
        assert got == ["f01", "f02", "f03", "f04", "f05"], got

    async def test_client_passes_page_size_not_into_frame_uris(
        self, vg_client, test_space, test_graph
    ):
        """Regression: the facade used to call the endpoint positionally, so
        page_size landed in the frame_uris parameter and changed the response
        shape entirely."""
        ns, entity_uri = await self._seed(vg_client, test_space, test_graph)
        page = await vg_client.get_kgentity_frames(
            space_id=test_space, graph_id=test_graph, entity_uri=entity_uri,
            page_size=2, offset=0, sort_by=self.SEQ_PROP, sort_order="asc")
        objs = getattr(page, "objects", None) or []
        # page_size must actually bound the result. When it was mis-passed as
        # frame_uris, the endpoint took the single-frame-graph branch instead.
        assert len(objs) == 2, [str(o.URI) for o in objs]
        assert [str(o.URI).rsplit("/", 1)[-1] for o in objs] == ["f05", "f04"]

        # ...and offset must advance within the same sorted order.
        page2 = await vg_client.get_kgentity_frames(
            space_id=test_space, graph_id=test_graph, entity_uri=entity_uri,
            page_size=2, offset=2, sort_by=self.SEQ_PROP, sort_order="asc")
        objs2 = getattr(page2, "objects", None) or []
        assert [str(o.URI).rsplit("/", 1)[-1] for o in objs2] == ["f03", "f02"]


class TestEntityFrameSlotsPaging:
    """GET /kgentities/kgframes/kgslots — slots of one frame, sorted and paged.

    The second half of the two-endpoint model. Slot sequence is the REVERSE of
    slot URI order so an ignored ORDER BY (or an order lost while rebuilding
    objects from triples) is immediately visible.
    """

    SLOT_SEQ = "http://vital.ai/ontology/haley-ai-kg#hasSlotSequence"
    N_SLOTS = 7

    async def _seed(self, vg_client, test_space, test_graph):
        ns = f"{NS}slotpage_{_uid()}/"
        entity = KGEntity()
        entity.URI = f"{ns}entity"
        entity.name = "Slot Paging Entity"
        frame = KGFrame()
        frame.URI = f"{ns}frame"
        frame.name = "Slot Paging Frame"
        e_ef = Edge_hasEntityKGFrame()
        e_ef.URI = f"{ns}edge_ef"
        e_ef.edgeSource = str(entity.URI)
        e_ef.edgeDestination = str(frame.URI)
        objs = [entity, frame, e_ef]
        for i in range(1, self.N_SLOTS + 1):
            s = KGTextSlot()
            s.URI = f"{ns}s{i:02d}"
            s.name = f"Slot {i}"
            s.textSlotValue = f"v{i}"
            s.slotSequence = self.N_SLOTS + 1 - i     # s01→7 … s07→1
            e = Edge_hasKGSlot()
            e.URI = f"{ns}edge_fs{i}"
            e.edgeSource = str(frame.URI)
            e.edgeDestination = str(s.URI)
            objs += [s, e]
        cr = await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=objs)
        assert cr.is_success, cr.error_message
        return ns, str(entity.URI), str(frame.URI)

    async def _slots(self, vg_client, test_space, test_graph, frame_uri, **kw):
        r = await vg_client.get_entity_frame_slots(
            space_id=test_space, graph_id=test_graph, frame_uri=frame_uri, **kw)
        assert r.is_success, r.error_message
        return [str(o.URI).rsplit("/", 1)[-1] for o in (r.objects or [])], r

    async def test_returns_only_slots_not_the_frame(
        self, vg_client, test_space, test_graph
    ):
        """Unlike /kgframes/kgslots, the frame itself is not in the result."""
        ns, entity_uri, frame_uri = await self._seed(vg_client, test_space, test_graph)
        got, r = await self._slots(vg_client, test_space, test_graph, frame_uri,
                                   page_size=100)
        assert len(got) == self.N_SLOTS, got
        assert "frame" not in got
        assert r.total_count == self.N_SLOTS, r.total_count

    async def test_sort_by_slot_sequence_ascending(
        self, vg_client, test_space, test_graph
    ):
        """Sequence 1..7 — the exact reverse of slot URI order."""
        ns, entity_uri, frame_uri = await self._seed(vg_client, test_space, test_graph)
        got, _ = await self._slots(vg_client, test_space, test_graph, frame_uri,
                                   page_size=100, sort_by=self.SLOT_SEQ,
                                   sort_order="asc")
        assert got == [f"s{i:02d}" for i in range(self.N_SLOTS, 0, -1)], got

    async def test_sort_by_slot_sequence_descending(
        self, vg_client, test_space, test_graph
    ):
        ns, entity_uri, frame_uri = await self._seed(vg_client, test_space, test_graph)
        got, _ = await self._slots(vg_client, test_space, test_graph, frame_uri,
                                   page_size=100, sort_by=self.SLOT_SEQ,
                                   sort_order="desc")
        assert got == [f"s{i:02d}" for i in range(1, self.N_SLOTS + 1)], got

    async def test_sorted_paging_partitions_slots(
        self, vg_client, test_space, test_graph
    ):
        """Concatenated pages equal the unpaged sorted order, each slot once.

        page_size=3 over 7 slots leaves a ragged final page, which is where
        off-by-one paging errors show up.
        """
        ns, entity_uri, frame_uri = await self._seed(vg_client, test_space, test_graph)
        expected, _ = await self._slots(
            vg_client, test_space, test_graph, frame_uri,
            page_size=100, sort_by=self.SLOT_SEQ, sort_order="asc")

        page_size = 3
        seen = []
        for offset in range(0, self.N_SLOTS + page_size, page_size):
            got, _ = await self._slots(
                vg_client, test_space, test_graph, frame_uri,
                page_size=page_size, offset=offset,
                sort_by=self.SLOT_SEQ, sort_order="asc")
            assert len(got) <= page_size, got
            seen.extend(got)

        assert seen == expected, f"paged {seen} != unpaged {expected}"
        assert len(set(seen)) == self.N_SLOTS

    async def test_total_count_is_independent_of_page(
        self, vg_client, test_space, test_graph
    ):
        """total_count reports the full slot set, not the page length."""
        ns, entity_uri, frame_uri = await self._seed(vg_client, test_space, test_graph)
        _, r = await self._slots(vg_client, test_space, test_graph, frame_uri,
                                 page_size=2, sort_by=self.SLOT_SEQ)
        assert r.total_count == self.N_SLOTS, r.total_count

    async def test_invalid_sort_by_is_a_domain_outcome(
        self, vg_client, test_space, test_graph
    ):
        """Unknown sort property → INVALID_REQUEST body, still HTTP 200."""
        ns, entity_uri, frame_uri = await self._seed(vg_client, test_space, test_graph)
        r = await vg_client.get_entity_frame_slots(
            space_id=test_space, graph_id=test_graph, frame_uri=frame_uri,
            sort_by="http://example.org/not-sortable")
        assert r.status_code == 200, r.status_code
        assert not r.is_success
        # The client rewrites `message`, so assert on the status discriminator.
        assert r.status == "invalid_request", r.status


class TestEntityFramesSlotCounts:
    """GET /kgentities/kgframes?include_slot_counts=true — per-frame slot counts.

    Lets a UI decide whether a frame needs slot pagination WITHOUT fetching its
    slots (planning/planning_ui/entity_graph_frame_slot_paging_plan.md §4a).
    """

    async def _seed(self, vg_client, test_space, test_graph, slot_counts):
        """One entity with len(slot_counts) frames; frame i gets slot_counts[i] slots."""
        ns = f"{NS}counts_{_uid()}/"
        entity = KGEntity()
        entity.URI = f"{ns}entity"
        entity.name = "Slot Count Entity"
        objs = [entity]
        for i, n_slots in enumerate(slot_counts):
            f = KGFrame()
            f.URI = f"{ns}f{i}"
            f.name = f"Frame {i}"
            f.frameSequence = i
            e = Edge_hasEntityKGFrame()
            e.URI = f"{ns}ef{i}"
            e.edgeSource = str(entity.URI)
            e.edgeDestination = str(f.URI)
            objs += [f, e]
            for j in range(n_slots):
                s = KGTextSlot()
                s.URI = f"{ns}f{i}s{j}"
                s.name = f"Slot {j}"
                s.textSlotValue = "v"
                se = Edge_hasKGSlot()
                se.URI = f"{ns}f{i}se{j}"
                se.edgeSource = str(f.URI)
                se.edgeDestination = str(s.URI)
                objs += [s, se]
        cr = await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=objs)
        assert cr.is_success, cr.error_message
        return ns, str(entity.URI)

    async def test_counts_returned_per_frame(self, vg_client, test_space, test_graph):
        ns, entity_uri = await self._seed(
            vg_client, test_space, test_graph, [2, 5, 1])

        r = await vg_client.get_kgentity_frames(
            space_id=test_space, graph_id=test_graph, entity_uri=entity_uri,
            page_size=100, include_slot_counts=True)

        counts = getattr(r, "slot_counts", None)
        assert counts, f"no slot_counts on response: {r}"
        assert counts.get(f"{ns}f0") == 2, counts
        assert counts.get(f"{ns}f1") == 5, counts
        assert counts.get(f"{ns}f2") == 1, counts

    async def test_zero_slot_frame_reports_zero_not_missing(
        self, vg_client, test_space, test_graph
    ):
        """The documented trap: a frame with no slots produces no GROUP BY row.

        The grouped COUNT omits it entirely, so the server seeds every frame on
        the page to 0. Without that, a client lookup yields None/undefined and
        the frame renders as 'unknown slots' rather than 'no slots'.
        """
        ns, entity_uri = await self._seed(
            vg_client, test_space, test_graph, [3, 0])

        r = await vg_client.get_kgentity_frames(
            space_id=test_space, graph_id=test_graph, entity_uri=entity_uri,
            page_size=100, include_slot_counts=True)

        counts = getattr(r, "slot_counts", None)
        assert counts is not None
        assert counts.get(f"{ns}f0") == 3, counts
        assert f"{ns}f1" in counts, f"zero-slot frame missing from map: {counts}"
        assert counts[f"{ns}f1"] == 0, counts

    async def test_counts_absent_unless_requested(
        self, vg_client, test_space, test_graph
    ):
        """Opt-in: no extra query, no field, when the caller does not ask."""
        _, entity_uri = await self._seed(vg_client, test_space, test_graph, [2])

        r = await vg_client.get_kgentity_frames(
            space_id=test_space, graph_id=test_graph, entity_uri=entity_uri,
            page_size=100)
        assert getattr(r, "slot_counts", None) is None

    async def test_counts_cover_only_the_requested_page(
        self, vg_client, test_space, test_graph
    ):
        """Counts describe the page returned, not the whole frame set."""
        ns, entity_uri = await self._seed(
            vg_client, test_space, test_graph, [1, 2, 3, 4])

        r = await vg_client.get_kgentity_frames(
            space_id=test_space, graph_id=test_graph, entity_uri=entity_uri,
            page_size=2, offset=0,
            sort_by="http://vital.ai/ontology/haley-ai-kg#hasFrameSequence",
            sort_order="asc", include_slot_counts=True)

        counts = getattr(r, "slot_counts", None)
        assert counts is not None
        mine = {k: v for k, v in counts.items() if k.startswith(ns)}
        assert len(mine) == 2, mine
        assert mine.get(f"{ns}f0") == 1, mine
        assert mine.get(f"{ns}f1") == 2, mine
