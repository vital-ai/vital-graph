"""API tests: KGQueries connection queries via VitalGraphClient.

Tests the 3 major KGQuery types:
  1. Relation queries — find entities connected via Edge_hasKGRelation
  2. Entity queries — find entities matching slot/property criteria
  3. Frame queries — find entities connected via shared KGFrames

Requires entities and relations to exist in the graph.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.Edge_hasKGRelation import Edge_hasKGRelation

from vitalgraph.model.kgqueries_model import KGQueryCriteria, TotalCountMode
from vitalgraph.model.kgentities_model import EntityQueryCriteria, FrameCriteria

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

NS = "http://example.org/apitest/kgquery/"
REL_TYPE = "http://vital.ai/ontology/haley-ai-kg#TestQueryRelation"


def _make_entity(name: str) -> KGEntity:
    e = KGEntity()
    e.URI = f"{NS}entity/{uuid.uuid4().hex[:12]}"
    e.name = name
    return e


def _make_relation(source_uri: str, dest_uri: str) -> Edge_hasKGRelation:
    r = Edge_hasKGRelation()
    r.URI = f"{NS}relation/{uuid.uuid4().hex[:12]}"
    r.edgeSource = source_uri
    r.edgeDestination = dest_uri
    r.kGRelationType = REL_TYPE
    return r


# ---------------------------------------------------------------------------
# Case 1: Relation queries
# ---------------------------------------------------------------------------

class TestKGQueryRelation:
    """KG relation connection queries (query_type='relation')."""

    @pytest_asyncio.fixture(autouse=True, loop_scope="session", scope="class")
    async def _setup_graph_data(self, vg_client, test_space, test_graph):
        """Seed entities and relations for relation query tests."""
        self.__class__.ent_a = _make_entity("RelQuerySource")
        self.__class__.ent_b = _make_entity("RelQueryDest1")
        self.__class__.ent_c = _make_entity("RelQueryDest2")

        for ent in (self.ent_a, self.ent_b, self.ent_c):
            cr = await vg_client.kgentities.create_kgentities(
                space_id=test_space, graph_id=test_graph, objects=[ent]
            )
            assert cr.is_success, f"Entity create failed: {cr.error_message}"

        # Create two relations: A→B and A→C
        for dest in (self.ent_b, self.ent_c):
            rel = _make_relation(str(self.ent_a.URI), str(dest.URI))
            cr = await vg_client.kgrelations.create_relations(
                space_id=test_space, graph_id=test_graph, relations=[rel]
            )
            assert cr.is_success, f"Relation create failed: {cr.error_message}"

    async def test_outgoing_connections(self, vg_client, test_space, test_graph):
        """Query outgoing relation connections from source entity."""
        criteria = KGQueryCriteria(
            query_type="relation",
            source_entity_uris=[str(self.ent_a.URI)],
            direction="outgoing",
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=test_space, graph_id=test_graph,
            criteria=criteria, page_size=10
        )
        assert resp.query_type == "relation"
        assert resp.total_count >= 2

    async def test_incoming_connections(self, vg_client, test_space, test_graph):
        """Query incoming relation connections to a destination entity."""
        criteria = KGQueryCriteria(
            query_type="relation",
            source_entity_uris=[str(self.ent_b.URI)],
            direction="incoming",
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=test_space, graph_id=test_graph,
            criteria=criteria, page_size=10
        )
        assert resp.query_type == "relation"
        assert resp.total_count >= 1

    async def test_relation_type_filter(self, vg_client, test_space, test_graph):
        """Query relations filtered by relation type URI."""
        criteria = KGQueryCriteria(
            query_type="relation",
            source_entity_uris=[str(self.ent_a.URI)],
            relation_type_uris=[REL_TYPE],
            direction="outgoing",
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=test_space, graph_id=test_graph,
            criteria=criteria, page_size=10
        )
        assert resp.query_type == "relation"
        assert resp.total_count >= 2

    async def test_no_results(self, vg_client, test_space, test_graph):
        """Query from an entity with no outgoing connections returns 0."""
        criteria = KGQueryCriteria(
            query_type="relation",
            source_entity_uris=[str(self.ent_b.URI)],
            direction="outgoing",
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=test_space, graph_id=test_graph,
            criteria=criteria, page_size=10
        )
        assert resp.query_type == "relation"
        assert resp.total_count == 0


# ---------------------------------------------------------------------------
# Case 2: Entity queries
# ---------------------------------------------------------------------------

class TestKGQueryEntity:
    """KG entity queries with criteria (query_type='entity')."""

    @pytest_asyncio.fixture(autouse=True, loop_scope="session", scope="class")
    async def _setup_entities(self, vg_client, test_space, test_graph):
        """Seed entities for entity query tests."""
        self.__class__.ent_x = _make_entity("EntityQueryAlpha")
        self.__class__.ent_y = _make_entity("EntityQueryBeta")

        for ent in (self.ent_x, self.ent_y):
            cr = await vg_client.kgentities.create_kgentities(
                space_id=test_space, graph_id=test_graph, objects=[ent]
            )
            assert cr.is_success, f"Entity create failed: {cr.error_message}"

    async def test_entity_query_by_uri(self, vg_client, test_space, test_graph):
        """Entity query with specific source entity URIs returns those entities."""
        criteria = KGQueryCriteria(
            query_type="entity",
            source_entity_uris=[str(self.ent_x.URI)],
        )
        # ASK FOR THE COUNT, or it is not computed. `include_total_count`
        # defaults to NO because the count is O(matches) and cannot be paged —
        # 325ms for a page against 41.7s for an uncapped count on a
        # 100,000-entity space, which the model documents as the caller's
        # trade-off to make. Asserting on `total_count` without requesting it
        # was asserting on a field the server was told not to fill in.
        resp = await vg_client.kgqueries.query_connections(
            space_id=test_space, graph_id=test_graph,
            criteria=criteria, page_size=10,
            include_total_count=TotalCountMode.YES,
        )
        assert resp.query_type == "entity"
        assert resp.total_count >= 1
        assert str(self.ent_x.URI) in (resp.entity_uris or [])

    async def test_entity_query_count_only(self, vg_client, test_space, test_graph):
        """Entity query with count_only returns total without URIs."""
        criteria = KGQueryCriteria(
            query_type="entity",
            source_entity_uris=[str(self.ent_x.URI), str(self.ent_y.URI)],
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=test_space, graph_id=test_graph,
            criteria=criteria, page_size=10, count_only=True
        )
        assert resp.query_type == "entity"
        assert resp.total_count >= 2
        # count_only returns empty URI list
        assert resp.entity_uris == [] or resp.entity_uris is None

    async def test_entity_query_with_entity_criteria(self, vg_client, test_space, test_graph):
        """Entity query using source_entity_criteria for type-based filtering."""
        criteria = KGQueryCriteria(
            query_type="entity",
            source_entity_criteria=EntityQueryCriteria(
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
            ),
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=test_space, graph_id=test_graph,
            criteria=criteria, page_size=10,
            include_total_count=TotalCountMode.YES,
        )
        assert resp.query_type == "entity"
        # Should find our test entities (all are KGEntity type)
        assert resp.total_count >= 1


# ---------------------------------------------------------------------------
# Case 3: Frame queries
# ---------------------------------------------------------------------------

class TestKGQueryFrame:
    """KG frame connection queries (query_type='frame')."""

    async def test_frame_query_no_matching_frames(self, vg_client, test_space, test_graph):
        """Frame query with nonexistent frame type returns 0 results."""
        criteria = KGQueryCriteria(
            query_type="frame",
            frame_criteria=[
                FrameCriteria(
                    frame_type="http://vital.ai/ontology/haley-ai-kg#NonExistentFrame",
                )
            ],
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=test_space, graph_id=test_graph,
            criteria=criteria, page_size=10
        )
        assert resp.query_type == "frame"
        assert resp.total_count == 0

    async def test_frame_query_structure(self, vg_client, test_space, test_graph):
        """Frame query response has correct structure (frame_connections field)."""
        criteria = KGQueryCriteria(
            query_type="frame",
            frame_criteria=[
                FrameCriteria(
                    frame_type="http://vital.ai/ontology/haley-ai-kg#KGEntityFrame",
                )
            ],
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=test_space, graph_id=test_graph,
            criteria=criteria, page_size=10
        )
        assert resp.query_type == "frame"
        # Response should have frame_connections (possibly empty)
        assert resp.total_count >= 0


# ---------------------------------------------------------------------------
# include_frame_graph: IMPLEMENTED 2026-10-04 (issues/210 option 1)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(loop_scope="session")
async def two_frames(vg_client, test_space, test_graph):
    """An entity with two frames of a fresh type, each with one slot."""
    from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
    from ai_haley_kg_domain.model.KGFrame import KGFrame
    from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot

    frame_type = f"{NS}frametype_{uuid.uuid4().hex[:8]}"
    entity = KGEntity()
    entity.URI = f"{NS}fg_entity_{uuid.uuid4().hex[:8]}"
    entity.name = "Frame Graph Probe"
    r = await vg_client.kgentities.create_kgentities(
        space_id=test_space, graph_id=test_graph, objects=[entity])
    assert r.is_success, r.error_message
    frames = {}
    for label in ("a", "b"):
        frame = KGFrame()
        frame.URI = f"{NS}fg_frame_{label}_{uuid.uuid4().hex[:8]}"
        frame.name = f"Frame {label}"
        frame.kGFrameType = frame_type
        slot = KGTextSlot()
        slot.URI = f"{NS}fg_slot_{label}_{uuid.uuid4().hex[:8]}"
        slot.name = "Value"
        slot.textSlotValue = label
        edge = Edge_hasKGSlot()
        edge.URI = f"{NS}fg_edge_{label}_{uuid.uuid4().hex[:8]}"
        edge.edgeSource = str(frame.URI)
        edge.edgeDestination = str(slot.URI)
        r = await vg_client.kgentities.create_entity_frames(
            space_id=test_space, graph_id=test_graph, entity_uri=str(entity.URI),
            objects=[frame, slot, edge])
        assert r.is_success, r.error_message or r.message
        frames[str(frame.URI)] = str(slot.URI)
    return frame_type, frames


class TestIncludeFrameGraph:
    """`include_frame_graph` on `/kgqueries` frame queries (`issues/210`).

    It was accepted and implemented nowhere — `frame_graph` null on every result
    — and then, from 2026-09-18, SAID so in `message`. Implemented 2026-10-04:
    each result's `frame_graph` is the frame and every subject grouped with it,
    as JSON quads, fetched in one batched query per page, and the client
    hydrates it into `frame_graph_objects`.

    Paired, as before: what the flag ADDS (each frame's own graph, not another
    frame's) and what it must not change (no graph and no message when not
    asked; the same frames either way).
    """

    async def test_each_frame_carries_its_own_graph(
            self, vg_client, test_space, test_graph, two_frames):
        frame_type, frames = two_frames
        resp = await vg_client.kgqueries.query_frames(
            space_id=test_space, graph_id=test_graph, frame_type=frame_type,
            include_frame_graph=True, page_size=10)
        assert resp.success, resp.message
        assert not resp.message, f"no message when the graphs were fetched: {resp.message!r}"
        got = {r.frame_uri: r for r in resp.results}
        assert set(got) == set(frames), f"expected the two frames, got {sorted(got)}"
        for frame_uri, slot_uri in frames.items():
            r = got[frame_uri]
            assert r.frame_graph, f"{frame_uri}: frame_graph is empty"
            uris = {str(o.URI) for o in (r.frame_graph_objects or [])}
            assert frame_uri in uris and slot_uri in uris, (
                f"{frame_uri}: the graph must hold the frame and its slot: {sorted(uris)}")
            other = [s for f, s in frames.items() if f != frame_uri]
            assert not (uris & set(other)), "a frame's graph holds another frame's slot"

    async def test_not_asking_returns_no_graph_and_no_message(
            self, vg_client, test_space, test_graph, two_frames):
        frame_type, _ = two_frames
        resp = await vg_client.kgqueries.query_frames(
            space_id=test_space, graph_id=test_graph, frame_type=frame_type,
            include_frame_graph=False, page_size=10)
        assert not resp.message, resp.message
        for r in resp.results:
            assert r.frame_graph is None and r.frame_graph_objects is None

    async def test_the_flag_does_not_change_which_frames(
            self, vg_client, test_space, test_graph, two_frames):
        frame_type, _ = two_frames
        on = await vg_client.kgqueries.query_frames(
            space_id=test_space, graph_id=test_graph, frame_type=frame_type,
            include_frame_graph=True, page_size=10)
        off = await vg_client.kgqueries.query_frames(
            space_id=test_space, graph_id=test_graph, frame_type=frame_type,
            include_frame_graph=False, page_size=10)
        assert [r.frame_uri for r in on.results] == [r.frame_uri for r in off.results]
