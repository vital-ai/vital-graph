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

The whole-entity create already refuses it (`KGEntityValidator` requires every
edge endpoint in the request). The two frame routes do not, and are marked
`xfail(strict=True)` until they do: fixed, they pass, the mark fails the run, and
it comes off.
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

open_279 = pytest.mark.xfail(
    strict=True,
    reason="issues/279: the frame routes accept edges and slots naming a frame "
           "that is neither in the request nor in the store")


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


@open_279
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


@open_279
async def test_a_standalone_frame_write_naming_an_absent_child_is_refused(
        vg_client, test_space, test_graph):
    """`POST /kgframes`, no entity."""
    parent_uri, child_uri, c_slot_uri, objs = _parent_with_absent_child()

    r = await vg_client.kgframes.create_kgframes(
        space_id=test_space, graph_id=test_graph, objects=objs)

    assert not r.is_success, "a frame write naming a frame it never sends was ACCEPTED"
    assert child_uri in _reply_text(r), _reply_text(r)
    assert not await _stored(vg_client, test_space, test_graph, [parent_uri, c_slot_uri])
