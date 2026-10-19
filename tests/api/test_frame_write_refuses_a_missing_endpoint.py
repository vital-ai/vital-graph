"""A frame write naming a frame it neither sends nor has is refused — issues/279.

The shape production stored 4,704 times in the UW space (2026-10-14..19): a
client's frame builder kept the parent frames, the child frames' slots, their
`Edge_hasKGSlot` and the parent -> child `Edge_hasKGFrame`, and dropped the
child `KGFrame` objects themselves. `POST /kgentities/kgframes` accepted it, so
every child's slots hang off a node that was never written: unreachable from
the entity, and reported only later by the maintenance job's dangling-endpoint
probe. `issues/212` found the same gap on the main KG space.

Each test sends that shape and asserts: the write is not a success, the reply
names the missing frame, and NOTHING of the request was stored.

The whole-entity create already refused it (`KGEntityValidator` requires every
edge endpoint in the request). The two frame routes now refuse it too, decided on
the write's OUTCOME inside its transaction (`kg_impl/frame_reachability.py`), so
the shapes no pre-write check can see are covered — an edge kept to a slot the
same upsert deletes. And the legitimate shapes, which name stored things, still
pass.
"""

from __future__ import annotations

import uuid

import pytest

from ai_haley_kg_domain.model.KGEntity import KGEntity
from vitalgraph.model.sparql_model import SPARQLQueryRequest
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

NS = "http://example.org/apitest/endpoint279/"

def _reply_text(r) -> str:
    return " ".join(str(x) for x in (getattr(r, "error_message", None),
                                     getattr(r, "message", None)) if x)


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _slot(uri, value):
    s = KGTextSlot()
    s.URI = uri
    s.textSlotValue = value
    return s


def _edge(cls, src, dst):
    e = cls()
    e.URI = f"{NS}edge_{_uid()}"
    e.edgeSource = src
    e.edgeDestination = dst
    return e


async def _entity(vg_client, space, graph):
    uri = f"{NS}entity_{_uid()}"
    e = KGEntity()
    e.URI = uri
    e.name = "host"
    r = await vg_client.kgentities.create_kgentities(space_id=space, graph_id=graph, objects=[e])
    assert r.is_success, r.error_message
    return uri


def _parent_with_absent_child():
    """A parent frame with one slot, and a child's slot + both edges — but no
    child `KGFrame`."""
    parent = KGFrame()
    parent.URI = f"{NS}frame_parent_{_uid()}"
    child_uri = f"{parent.URI}:frame:child:0"
    p_slot = _slot(f"{parent.URI}:slot:a", "parent value")
    c_slot = _slot(f"{child_uri}:slot:b", "child value")
    objs = [parent, p_slot,
            _edge(Edge_hasKGSlot, parent.URI, p_slot.URI),
            _edge(Edge_hasKGFrame, parent.URI, child_uri),
            c_slot,
            _edge(Edge_hasKGSlot, child_uri, c_slot.URI)]
    return parent.URI, child_uri, c_slot.URI, objs


async def _stored(vg_client, space, graph, uris):
    """URIs among `uris` that have any quad as subject."""
    vals = " ".join(f"<{u}>" for u in uris)
    q = f"SELECT DISTINCT ?s WHERE {{ GRAPH <{graph}> {{ VALUES ?s {{ {vals} }} ?s ?p ?o }} }}"
    r = await vg_client.sparql.execute_sparql_query(space, SPARQLQueryRequest(query=q))
    return {b["s"]["value"] for b in (r.results or {}).get("bindings", [])}


@pytest.mark.parametrize("mode", ["create", "upsert"])
async def test_a_child_frame_named_by_edges_but_never_sent_is_refused(
        vg_client, test_space, test_graph, mode):
    entity_uri = await _entity(vg_client, test_space, test_graph)
    parent_uri, child_uri, c_slot_uri, objs = _parent_with_absent_child()

    r = await vg_client.kgentities.create_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity_uri,
        objects=objs, operation_mode=mode)

    assert not r.is_success, (
        f"{mode}: a write whose edges name a frame it never sends was ACCEPTED")
    assert child_uri in _reply_text(r), (
        f"{mode}: the refusal must name the missing frame: {_reply_text(r)!r}")
    assert not await _stored(vg_client, test_space, test_graph,
                             [parent_uri, c_slot_uri]), f"{mode}: part of a refused write was stored"


async def test_an_entity_graph_naming_an_absent_child_frame_is_refused(
        vg_client, test_space, test_graph):
    """The whole-entity write (`POST /kgentities` with its frames) — the path a
    client takes to write an entity and its frames in one transaction."""
    from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
    ent = KGEntity()
    ent.URI = f"{NS}entity_{_uid()}"
    ent.name = "host"
    parent_uri, child_uri, c_slot_uri, objs = _parent_with_absent_child()
    objs = [ent, _edge(Edge_hasEntityKGFrame, ent.URI, parent_uri)] + objs

    r = await vg_client.kgentities.create_kgentities(
        space_id=test_space, graph_id=test_graph, objects=objs)

    assert not r.is_success, "an entity graph naming a frame it never sends was ACCEPTED"
    assert child_uri in _reply_text(r), _reply_text(r)
    assert not await _stored(vg_client, test_space, test_graph,
                             [ent.URI, parent_uri, c_slot_uri])


async def test_a_standalone_frame_write_naming_an_absent_child_is_refused(
        vg_client, test_space, test_graph):
    """`POST /kgframes`, no entity."""
    parent_uri, child_uri, c_slot_uri, objs = _parent_with_absent_child()

    r = await vg_client.kgframes.create_kgframes(
        space_id=test_space, graph_id=test_graph, objects=objs)

    assert not r.is_success, "a frame write naming a frame it never sends was ACCEPTED"
    assert child_uri in _reply_text(r), _reply_text(r)
    assert not await _stored(vg_client, test_space, test_graph, [parent_uri, c_slot_uri])


async def _frame_with_slot(vg_client, space, graph, entity_uri):
    f = KGFrame()
    f.URI = f"{NS}frame_{_uid()}"
    sl = _slot(f"{str(f.URI)}:slot:a", "kept")
    edge = _edge(Edge_hasKGSlot, str(f.URI), str(sl.URI))
    r = await vg_client.kgentities.create_entity_frames(
        space_id=space, graph_id=graph, entity_uri=entity_uri, objects=[f, sl, edge])
    assert r.is_success, _reply_text(r)
    return f, sl, edge


async def test_an_upsert_keeping_an_edge_to_a_slot_it_deletes_is_refused(
        vg_client, test_space, test_graph):
    """The shape a check BEFORE the write passes: the slot is stored when the
    request arrives, and the upsert's frame-graph replace deletes it."""
    entity_uri = await _entity(vg_client, test_space, test_graph)
    f, sl, edge = await _frame_with_slot(vg_client, test_space, test_graph, entity_uri)

    r = await vg_client.kgentities.create_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity_uri,
        objects=[f, edge], operation_mode="upsert")      # the slot is not re-sent

    assert not r.is_success, "an upsert that deletes the slot its edge names was ACCEPTED"
    assert str(sl.URI) in _reply_text(r), _reply_text(r)
    assert await _stored(vg_client, test_space, test_graph, [str(sl.URI)]) == {str(sl.URI)}, (
        "the refused upsert must leave the stored slot as it was")


async def test_a_slot_sent_without_its_edge_is_refused(vg_client, test_space, test_graph):
    entity_uri = await _entity(vg_client, test_space, test_graph)
    f = KGFrame()
    f.URI = f"{NS}frame_{_uid()}"
    loose = _slot(f"{str(f.URI)}:slot:loose", "no edge")

    r = await vg_client.kgentities.create_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity_uri,
        objects=[f, loose])

    assert not r.is_success, "a slot with no Edge_hasKGSlot was ACCEPTED"
    assert str(loose.URI) in _reply_text(r), _reply_text(r)
    assert not await _stored(vg_client, test_space, test_graph, [str(f.URI), str(loose.URI)])


async def test_children_under_a_stored_parent_are_written(vg_client, test_space, test_graph):
    """The route used one level per request, as designed: the parent is stored,
    and the child request names it only through `parent_frame_uri`."""
    entity_uri = await _entity(vg_client, test_space, test_graph)
    parent, _sl, _e = await _frame_with_slot(vg_client, test_space, test_graph, entity_uri)
    child = KGFrame()
    child.URI = f"{str(parent.URI)}:frame:child:0"
    c_slot = _slot(f"{str(child.URI)}:slot:b", "child value")

    for mode in ("create", "upsert"):
        r = await vg_client.kgentities.create_entity_frames(
            space_id=test_space, graph_id=test_graph, entity_uri=entity_uri,
            objects=[child, c_slot, _edge(Edge_hasKGSlot, str(child.URI), str(c_slot.URI))],
            parent_frame_uri=str(parent.URI), operation_mode=mode)
        assert r.is_success, f"{mode}: {_reply_text(r)}"
    assert await _stored(vg_client, test_space, test_graph,
                         [str(child.URI), str(c_slot.URI)]) == {str(child.URI), str(c_slot.URI)}


async def test_an_upsert_re_sending_its_slots_and_edges_is_written(
        vg_client, test_space, test_graph):
    entity_uri = await _entity(vg_client, test_space, test_graph)
    f, sl, edge = await _frame_with_slot(vg_client, test_space, test_graph, entity_uri)
    sl.textSlotValue = "changed"
    r = await vg_client.kgentities.create_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity_uri,
        objects=[f, sl, edge], operation_mode="upsert")
    assert r.is_success, _reply_text(r)
    assert "1 frame(s)" in _reply_text(r), (
        f"the message must count frames, not every URI: {_reply_text(r)!r}")


@pytest.mark.parametrize("mode", ["create", "upsert", "update"])
async def test_the_whole_entity_write_naming_an_absent_child_is_refused(
        vg_client, test_space, test_graph, mode):
    """`POST /kgentities` in every mode, with the entity and its frames together.
    For update and upsert the entity exists first, as a caller rewriting it would."""
    from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
    ent = KGEntity()
    ent.URI = f"{NS}entity_{_uid()}"
    ent.name = "host"
    if mode != "create":
        r0 = await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=[ent])
        assert r0.is_success, _reply_text(r0)
    parent_uri, child_uri, c_slot_uri, objs = _parent_with_absent_child()
    objs = [ent, _edge(Edge_hasEntityKGFrame, str(ent.URI), parent_uri)] + objs

    write = {"create": vg_client.kgentities.create_kgentities,
             "upsert": vg_client.kgentities.upsert_kgentities,
             "update": vg_client.kgentities.update_kgentities}[mode]
    r = await write(space_id=test_space, graph_id=test_graph, objects=objs)

    assert not r.is_success, (
        f"{mode}: an entity graph naming a frame it never sends was ACCEPTED: {_reply_text(r)}")
    assert child_uri in _reply_text(r), _reply_text(r)
    assert not await _stored(vg_client, test_space, test_graph, [parent_uri, c_slot_uri]), (
        f"{mode}: part of a refused write was stored")


@pytest.mark.parametrize("mode", ["create", "upsert", "update"])
async def test_the_whole_entity_write_with_a_slot_and_no_edge_is_refused(
        vg_client, test_space, test_graph, mode):
    from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
    ent = KGEntity()
    ent.URI = f"{NS}entity_{_uid()}"
    ent.name = "host"
    if mode != "create":
        r0 = await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=[ent])
        assert r0.is_success, _reply_text(r0)
    f = KGFrame()
    f.URI = f"{NS}frame_{_uid()}"
    loose = _slot(f"{f.URI}:slot:loose", "no edge")
    objs = [ent, _edge(Edge_hasEntityKGFrame, str(ent.URI), str(f.URI)), f, loose]

    write = {"create": vg_client.kgentities.create_kgentities,
             "upsert": vg_client.kgentities.upsert_kgentities,
             "update": vg_client.kgentities.update_kgentities}[mode]
    r = await write(space_id=test_space, graph_id=test_graph, objects=objs)

    assert not r.is_success, f"{mode}: a slot with no Edge_hasKGSlot was ACCEPTED"
    assert str(loose.URI) in _reply_text(r), _reply_text(r)
    assert not await _stored(vg_client, test_space, test_graph, [str(f.URI), str(loose.URI)])
