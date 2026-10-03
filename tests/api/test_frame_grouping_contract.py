"""Frame groupings are decided by the server, through every write route.

`issues/257`. `hasFrameGraphURI` IS the frame graph, and every frame is grouped
with itself: a frame with its own URI, a slot with the frame its Edge_hasKGSlot
names. A census of real data found child subtrees grouped under their ROOT and
spaces with no grouping at all, and five live write paths that could store a
grouping the client sent:

  1. entity-frame create, a slot with no edge in a multi-frame request;
  2. entity-frame UPDATE, which took a slot's grouping from the client first;
  3. standalone /kgframes create, same shape as 1;
  4. the slot route, which grouped its slots but not its edges: the
     Edge_hasKGSlot it creates itself was stored with NO grouping, and one the
     client sent kept the client's value;
  5. entity create, single entity (shape 1) and multi-entity batch, whose frames
     and slots were never grouped at all.

Each test reads the stored grouping back from the quad table. A slot the server
cannot place is REFUSED (INVALID_REQUEST in a 200), and nothing is written.

Runs against the vg-test stack (:8002, Postgres :5433).
"""

from __future__ import annotations

import uuid

import pytest

from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot

pytestmark = [pytest.mark.api, pytest.mark.asyncio(loop_scope="session")]

NS = "http://vital.ai/test/frame_grouping/"
FGU = "http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI"
WRONG = f"{NS}client_sent_this"


def _u(kind: str) -> str:
    return f"{NS}{kind}_{uuid.uuid4().hex[:8]}"


def _frame(uri):
    f = KGFrame()
    f.URI = uri
    f.name = "Grouping Probe Frame"
    f.frameGraphURI = WRONG
    return f


def _slot(uri):
    s = KGTextSlot()
    s.URI = uri
    s.name = "Grouping Probe Slot"
    s.textSlotValue = "probe"
    s.frameGraphURI = WRONG
    return s


def _slot_edge(frame_uri, slot_uri):
    e = Edge_hasKGSlot()
    e.URI = _u("edge")
    e.edgeSource = frame_uri
    e.edgeDestination = slot_uri
    e.frameGraphURI = WRONG
    return e


async def _groupings(pg_conn, space, uri) -> set:
    rows = await pg_conn.fetch(
        f"SELECT o.term_text FROM {space}_rdf_quad q "
        f"JOIN {space}_term o ON o.term_uuid = q.object_uuid "
        f"WHERE q.subject_uuid = vitalgraph_term_uuid($1, 'U') "
        f"AND q.predicate_uuid = vitalgraph_term_uuid($2, 'U')", uri, FGU)
    return {r["term_text"] for r in rows}


async def _quads(pg_conn, space, uri) -> int:
    return await pg_conn.fetchval(
        f"SELECT count(*) FROM {space}_rdf_quad "
        f"WHERE subject_uuid = vitalgraph_term_uuid($1, 'U')", uri)


async def _host_entity(vg_client, space, graph):
    e = KGEntity()
    e.URI = _u("entity")
    e.name = "Grouping Probe Entity"
    r = await vg_client.kgentities.create_kgentities(
        space_id=space, graph_id=graph, objects=[e])
    assert r.is_success, r.error_message
    return str(e.URI)


def _refused(r) -> bool:
    return r.status == "invalid_request" and not r.is_success


# ---------------------------------------------------------------------------
# 1. entity-frame create
# ---------------------------------------------------------------------------

async def test_entity_frame_create_refuses_a_slot_it_cannot_place(
        vg_client, test_space, test_graph, pg_conn):
    entity = await _host_entity(vg_client, test_space, test_graph)
    f1, f2, s = _u("frame"), _u("frame"), _u("slot")
    r = await vg_client.kgentities.create_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity,
        objects=[_frame(f1), _frame(f2), _slot(s)])

    assert _refused(r), (
        f"answered {r.status!r}: two frames and a slot with no Edge_hasKGSlot, "
        f"so its frame is unknown; the slot was stored with "
        f"{await _groupings(pg_conn, test_space, s)}")
    assert await _quads(pg_conn, test_space, s) == 0
    assert await _quads(pg_conn, test_space, f1) == 0, "a refused request wrote its frames"


async def test_entity_frame_create_discards_the_clients_groupings(
        vg_client, test_space, test_graph, pg_conn):
    entity = await _host_entity(vg_client, test_space, test_graph)
    f1, f2, s = _u("frame"), _u("frame"), _u("slot")
    edge = _slot_edge(f2, s)
    r = await vg_client.kgentities.create_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity,
        objects=[_frame(f1), _frame(f2), _slot(s), edge])
    assert r.is_success, r.error_message

    assert await _groupings(pg_conn, test_space, f1) == {f1}
    assert await _groupings(pg_conn, test_space, s) == {f2}
    assert await _groupings(pg_conn, test_space, str(edge.URI)) == {f2}


# ---------------------------------------------------------------------------
# 2. entity-frame update
# ---------------------------------------------------------------------------

async def test_entity_frame_update_does_not_take_the_clients_slot_grouping(
        vg_client, test_space, test_graph, pg_conn):
    entity = await _host_entity(vg_client, test_space, test_graph)
    f1, f2, s1, s2 = _u("frame"), _u("frame"), _u("slot"), _u("slot")
    cr = await vg_client.kgentities.create_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity,
        objects=[_frame(f1), _frame(f2), _slot(s1), _slot(s2),
                 _slot_edge(f1, s1), _slot_edge(f2, s2)])
    assert cr.is_success, cr.error_message
    assert await _groupings(pg_conn, test_space, s1) == {f1}

    # Both frames, s1 WITHOUT its edge, and the client claiming s1 is f2's.
    s1_obj = _slot(s1)
    s1_obj.frameGraphURI = f2
    r = await vg_client.kgentities.update_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity,
        objects=[_frame(f1), _frame(f2), s1_obj])

    assert _refused(r), (
        f"answered {r.status!r}: s1 is now grouped "
        f"{await _groupings(pg_conn, test_space, s1)} — the server took the "
        f"client's word for which frame owns it")
    assert await _groupings(pg_conn, test_space, s1) == {f1}


# ---------------------------------------------------------------------------
# 3. standalone /kgframes create
# ---------------------------------------------------------------------------

async def test_standalone_frame_create_refuses_a_slot_it_cannot_place(
        vg_client, test_space, test_graph, pg_conn):
    f1, f2, s = _u("frame"), _u("frame"), _u("slot")
    r = await vg_client.kgframes.create_kgframes(
        space_id=test_space, graph_id=test_graph,
        objects=[_frame(f1), _frame(f2), _slot(s)])

    assert _refused(r), (
        f"answered {r.status!r}; the slot was stored with "
        f"{await _groupings(pg_conn, test_space, s)}")
    assert await _quads(pg_conn, test_space, s) == 0


# ---------------------------------------------------------------------------
# 4. the slot route
# ---------------------------------------------------------------------------

async def test_the_slot_route_groups_a_slot_with_its_frame(
        vg_client, test_space, test_graph, pg_conn):
    f = _u("frame")
    cr = await vg_client.kgframes.create_kgframes(
        space_id=test_space, graph_id=test_graph, objects=[_frame(f)])
    assert cr.is_success, cr.error_message

    s = _u("slot")
    client_edge = _slot_edge(f, s)
    r = await vg_client.kgframes.create_frame_slots(
        space_id=test_space, graph_id=test_graph, frame_uri=f,
        objects=[_slot(s), client_edge])
    assert r.is_success, r.error_message

    assert await _groupings(pg_conn, test_space, s) == {f}
    assert await _groupings(pg_conn, test_space, str(client_edge.URI)) == {f}, (
        "the slot route kept the client's grouping on the Edge_hasKGSlot it sent")
    # The route also creates its own edge, `{frame}_{slot}_edge`.
    assert await _groupings(pg_conn, test_space, f"{f}_{s}_edge") == {f}, (
        "the slot route stored the Edge_hasKGSlot it CREATED with no "
        "hasFrameGraphURI at all")


# ---------------------------------------------------------------------------
# 5. entity create (full graph)
# ---------------------------------------------------------------------------

async def test_entity_create_refuses_a_slot_it_cannot_place(
        vg_client, test_space, test_graph, pg_conn):
    e = KGEntity()
    e.URI = _u("entity")
    e.name = "Grouping Probe Entity"
    f1, f2, s = _u("frame"), _u("frame"), _u("slot")
    r = await vg_client.kgentities.create_kgentities(
        space_id=test_space, graph_id=test_graph,
        objects=[e, _frame(f1), _frame(f2), _slot(s)])

    assert _refused(r), (
        f"answered {r.status!r}; the slot was stored with "
        f"{await _groupings(pg_conn, test_space, s)}")
    assert await _quads(pg_conn, test_space, str(e.URI)) == 0


async def test_a_multi_entity_batch_groups_its_frames_and_slots(
        vg_client, test_space, test_graph, pg_conn):
    objects, expect = [], {}
    for _ in range(2):
        e = KGEntity()
        e.URI = _u("entity")
        e.name = "Grouping Probe Entity"
        f, s = _u("frame"), _u("slot")
        objects += [e, _frame(f), _slot(s), _slot_edge(f, s)]
        expect[f] = {f}
        expect[s] = {f}
    r = await vg_client.kgentities.create_kgentities(
        space_id=test_space, graph_id=test_graph, objects=objects)
    assert r.is_success, r.error_message

    got = {uri: await _groupings(pg_conn, test_space, uri) for uri in expect}
    assert got == expect, (
        "a multi-entity batch stored the client's groupings: its frames and "
        f"slots were never regrouped. got {got}")


# ---------------------------------------------------------------------------
# 6. a parent -> child Edge_hasKGFrame is in NO frame's graph (decided
#    2026-10-03). `/kgframes` grouped it with the child; a client-sent one on
#    the entity route kept the client's value.
# ---------------------------------------------------------------------------

HAS_KG_FRAME = "http://vital.ai/ontology/haley-ai-kg#Edge_hasKGFrame"
VITALTYPE = "http://vital.ai/ontology/vital-core#vitaltype"
EDGE_DST = "http://vital.ai/ontology/vital-core#hasEdgeDestination"


async def _parent_child_edge_groupings(pg_conn, space, child_uri) -> list:
    """The hasFrameGraphURI values on every Edge_hasKGFrame pointing at child."""
    rows = await pg_conn.fetch(
        f"SELECT q.subject_uuid, "
        f"  (SELECT array_agg(o.term_text) FROM {space}_rdf_quad g "
        f"     JOIN {space}_term o ON o.term_uuid = g.object_uuid "
        f"   WHERE g.subject_uuid = q.subject_uuid "
        f"     AND g.predicate_uuid = vitalgraph_term_uuid($3, 'U')) AS fgu "
        f"FROM {space}_rdf_quad q "
        f"JOIN {space}_rdf_quad d ON d.subject_uuid = q.subject_uuid "
        f"WHERE q.predicate_uuid = vitalgraph_term_uuid($1, 'U') "
        f"  AND q.object_uuid = vitalgraph_term_uuid($2, 'U') "
        f"  AND d.predicate_uuid = vitalgraph_term_uuid($4, 'U') "
        f"  AND d.object_uuid = vitalgraph_term_uuid($5, 'U')",
        VITALTYPE, HAS_KG_FRAME, FGU, EDGE_DST, child_uri)
    return [r["fgu"] for r in rows]


async def test_a_standalone_parent_child_edge_has_no_grouping(
        vg_client, test_space, test_graph, pg_conn):
    parent, child = _u("frame"), _u("frame")
    cr = await vg_client.kgframes.create_kgframes(
        space_id=test_space, graph_id=test_graph, objects=[_frame(parent)])
    assert cr.is_success, cr.error_message
    r = await vg_client.kgframes.create_kgframes(
        space_id=test_space, graph_id=test_graph, objects=[_frame(child)],
        parent_uri=parent)
    assert r.is_success, r.error_message

    edges = await _parent_child_edge_groupings(pg_conn, test_space, child)
    assert edges, "no Edge_hasKGFrame was written for the child"
    assert edges == [None] * len(edges), (
        f"the parent -> child edge is grouped {edges}; it belongs to no frame")
    assert await _groupings(pg_conn, test_space, child) == {child}


async def test_a_client_sent_parent_child_edge_loses_its_grouping(
        vg_client, test_space, test_graph, pg_conn):
    from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame
    entity = await _host_entity(vg_client, test_space, test_graph)
    parent, child = _u("frame"), _u("frame")
    pc = Edge_hasKGFrame()
    pc.URI = _u("pcedge")
    pc.edgeSource = parent
    pc.edgeDestination = child
    pc.frameGraphURI = WRONG
    r = await vg_client.kgentities.create_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity,
        objects=[_frame(parent), _frame(child), pc])
    assert r.is_success, r.error_message

    assert await _groupings(pg_conn, test_space, str(pc.URI)) == set(), (
        "the client's grouping on a parent -> child edge was stored")
