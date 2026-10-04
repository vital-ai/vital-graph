"""`replace`, and one route per frame, through the API (`issues/256`).

REPLACE (item 4). Both routes deleted the old frames with separate SPARQL
updates, then created — no lock, no guard, and a failure in between left neither
the old frames nor the new. And the scope was wrong: the entity route deleted
EVERY top-level frame of the entity, and with a parent both routes deleted every
child of the parent, whatever the request named. Now: one transaction, scoped to
the named frames and their descendants, guarded, deep.

ONE ROUTE PER FRAME (decision 3, writes). `/kgframes` does not take an entity's
lock, so it refuses to write, replace or create over an entity's frame, or to
attach a frame under an entity or an entity's frame. Decided inside the write's
transaction, after its lock.

Absence and survival are asserted by RAW COUNT in the quad table as well as by
status. Runs against the vg-test stack (:8002, Postgres :5433).
"""

from __future__ import annotations

import uuid

import pytest

from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot

pytestmark = [pytest.mark.api, pytest.mark.asyncio(loop_scope="session")]

NS = "http://vital.ai/test/replace_contract/"
_STALE = "2000-01-01T00:00:00+00:00"


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _frame(value: str = "v", frame_uri: str | None = None):
    """(frame_uri, slot_uri, [frame, slot, edge])."""
    frame_uri = frame_uri or f"{NS}frame_{_uid()}"
    slot_uri = f"{NS}slot_{_uid()}"
    frame = KGFrame()
    frame.URI = frame_uri
    frame.name = "Probe Frame"
    slot = KGTextSlot()
    slot.URI = slot_uri
    slot.name = "Probe Slot"
    slot.textSlotValue = value
    edge = Edge_hasKGSlot()
    edge.URI = f"{NS}edge_{_uid()}"
    edge.edgeSource = frame_uri
    edge.edgeDestination = slot_uri
    return frame_uri, slot_uri, [frame, slot, edge]


async def _entity(vg_client, space, graph) -> str:
    uri = f"{NS}entity_{_uid()}"
    e = KGEntity()
    e.URI = uri
    e.name = "Replace Probe"
    r = await vg_client.kgentities.create_kgentities(
        space_id=space, graph_id=graph, objects=[e])
    assert r.is_success, r.error_message or r.message
    return uri


async def _entity_frame(vg_client, space, graph, entity, parent=None):
    frame_uri, slot_uri, objs = _frame()
    r = await vg_client.kgentities.create_entity_frames(
        space_id=space, graph_id=graph, entity_uri=entity, objects=objs,
        parent_frame_uri=parent)
    assert r.is_success, r.error_message or r.message
    return frame_uri, slot_uri


async def _standalone(vg_client, space, graph, parent=None):
    frame_uri, slot_uri, objs = _frame()
    if parent:
        r = await vg_client.kgframes.create_child_frames(
            space_id=space, graph_id=graph, parent_frame_uri=parent, objects=objs)
    else:
        r = await vg_client.kgframes.create_kgframes(
            space_id=space, graph_id=graph, objects=objs)
    assert r.is_success, r.error_message or r.message
    return frame_uri, slot_uri


async def _quads(pg_conn, space, *uris) -> int:
    return await pg_conn.fetchval(
        f"SELECT count(*) FROM {space}_rdf_quad WHERE subject_uuid = ANY("
        f"ARRAY(SELECT vitalgraph_term_uuid(u, 'U') FROM unnest($1::text[]) u))",
        list(uris))


async def _links_into(pg_conn, space, frame_uri) -> int:
    return await pg_conn.fetchval(
        f"SELECT count(*) FROM {space}_rdf_quad "
        f"WHERE predicate_uuid = vitalgraph_term_uuid($1, 'U') "
        f"AND object_uuid = vitalgraph_term_uuid($2, 'U')",
        "http://vital.ai/ontology/vital-core#hasEdgeDestination", frame_uri)


async def _entity_stamp(vg_client, space, graph, entity) -> str:
    r = await vg_client.kgentities.get_kgentity(
        space_id=space, graph_id=graph, uri=entity, include_entity_graph=True)
    assert r.is_success and r.modification_stamp
    return r.modification_stamp


def _msg(r) -> str:
    return r.message or r.error_message or ""


# ---------------------------------------------------------------------------
# Entity-frame replace
# ---------------------------------------------------------------------------

async def test_entity_replace_leaves_the_frames_it_does_not_name(
        vg_client, test_space, test_graph, pg_conn):
    entity = await _entity(vg_client, test_space, test_graph)
    target, old_slot = await _entity_frame(vg_client, test_space, test_graph, entity)
    other, other_slot = await _entity_frame(vg_client, test_space, test_graph, entity)

    _, new_slot, objs = _frame("replaced", frame_uri=target)
    r = await vg_client.kgentities.create_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity,
        objects=objs, operation_mode="replace")

    assert r.is_success, f"{r.status}: {_msg(r)}"
    assert await _quads(pg_conn, test_space, other, other_slot) > 0, (
        "replacing one frame deleted another root frame of the entity")
    assert await _quads(pg_conn, test_space, old_slot) == 0, "deep: old slot survived"
    assert await _quads(pg_conn, test_space, target, new_slot) > 0
    assert await _links_into(pg_conn, test_space, target) == 1, (
        "the replaced frame should have exactly one link from the entity")


async def test_entity_replace_is_deep(vg_client, test_space, test_graph, pg_conn):
    entity = await _entity(vg_client, test_space, test_graph)
    parent, _ = await _entity_frame(vg_client, test_space, test_graph, entity)
    child, child_slot = await _entity_frame(vg_client, test_space, test_graph,
                                            entity, parent=parent)

    _, _, objs = _frame("no children now", frame_uri=parent)
    r = await vg_client.kgentities.create_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity,
        objects=objs, operation_mode="replace")

    assert r.is_success, f"{r.status}: {_msg(r)}"
    assert await _quads(pg_conn, test_space, child, child_slot) == 0
    assert await _links_into(pg_conn, test_space, child) == 0


async def test_entity_replace_under_a_parent_leaves_the_siblings(
        vg_client, test_space, test_graph, pg_conn):
    entity = await _entity(vg_client, test_space, test_graph)
    parent, _ = await _entity_frame(vg_client, test_space, test_graph, entity)
    a, _ = await _entity_frame(vg_client, test_space, test_graph, entity, parent=parent)
    b, b_slot = await _entity_frame(vg_client, test_space, test_graph, entity, parent=parent)

    _, _, objs = _frame("a again", frame_uri=a)
    r = await vg_client.kgentities.create_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity,
        objects=objs, parent_frame_uri=parent, operation_mode="replace")

    assert r.is_success, f"{r.status}: {_msg(r)}"
    assert await _quads(pg_conn, test_space, b, b_slot) > 0, (
        "replacing one child deleted its sibling")
    assert await _links_into(pg_conn, test_space, a) == 1


async def test_a_stale_entity_replace_changes_nothing(
        vg_client, test_space, test_graph, pg_conn):
    entity = await _entity(vg_client, test_space, test_graph)
    target, old_slot = await _entity_frame(vg_client, test_space, test_graph, entity)

    _, new_slot, objs = _frame("loser", frame_uri=target)
    r = await vg_client.kgentities.create_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity,
        objects=objs, operation_mode="replace", if_unmodified_since=_STALE)

    assert r.is_conflict, f"{r.status}: {_msg(r)}"
    assert await _quads(pg_conn, test_space, old_slot) > 0, "a refused replace deleted"
    assert await _quads(pg_conn, test_space, new_slot) == 0

    stamp = await _entity_stamp(vg_client, test_space, test_graph, entity)
    r = await vg_client.kgentities.create_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity,
        objects=objs, operation_mode="replace", if_unmodified_since=stamp)
    assert r.is_success, f"current stamp: {r.status}: {_msg(r)}"
    assert await _quads(pg_conn, test_space, new_slot) > 0


async def test_entity_replace_of_another_entitys_frame_is_refused(
        vg_client, test_space, test_graph, pg_conn):
    mine = await _entity(vg_client, test_space, test_graph)
    theirs = await _entity(vg_client, test_space, test_graph)
    their_frame, their_slot = await _entity_frame(vg_client, test_space, test_graph, theirs)

    _, _, objs = _frame("hijack", frame_uri=their_frame)
    r = await vg_client.kgentities.create_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=mine,
        objects=objs, operation_mode="replace")

    assert r.status == "invalid_request", f"{r.status}: {_msg(r)}"
    assert await _quads(pg_conn, test_space, their_slot) > 0


async def test_replace_does_not_apply_to_an_entity(vg_client, test_space, test_graph):
    from vitalgraph.client.utils.format_helpers import serialize_graphobjects_for_request
    e = KGEntity()
    e.URI = f"{NS}entity_{_uid()}"
    e.name = "x"
    ep = vg_client.kgentities
    body, ctype = serialize_graphobjects_for_request([e], ep.wire_format)
    resp = await ep._make_request(
        'POST', f"{ep._get_server_url()}/api/graphs/kgentities",
        params={"space_id": test_space, "graph_id": test_graph,
                "operation_mode": "replace"},
        json=body, headers={'Content-Type': ctype})
    assert resp.status_code == 200, "was a 500"
    assert resp.json().get("status") == "invalid_request"


# ---------------------------------------------------------------------------
# Entity-frame create: the entity is checked under the lock
# ---------------------------------------------------------------------------

async def test_a_frame_onto_a_missing_entity_writes_nothing(
        vg_client, test_space, test_graph, pg_conn):
    missing = f"{NS}never_{_uid()}"
    frame, slot, objs = _frame()
    r = await vg_client.kgentities.create_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=missing, objects=objs)
    assert not r.is_success
    assert "not found" in _msg(r)
    assert await _quads(pg_conn, test_space, frame, slot) == 0


# ---------------------------------------------------------------------------
# /kgframes replace
# ---------------------------------------------------------------------------

async def test_kgframes_replace_of_a_child_keeps_it_attached(
        vg_client, test_space, test_graph, pg_conn):
    root, _ = await _standalone(vg_client, test_space, test_graph)
    child, old_slot = await _standalone(vg_client, test_space, test_graph, parent=root)

    _, new_slot, objs = _frame("new", frame_uri=child)
    r = await vg_client.kgframes.create_kgframes(
        space_id=test_space, graph_id=test_graph, objects=objs,
        operation_mode="replace")

    assert r.is_success, f"{r.status}: {_msg(r)}"
    assert await _links_into(pg_conn, test_space, child) == 1, (
        "a replace without parent_uri detached the frame from its parent")
    assert await _quads(pg_conn, test_space, old_slot) == 0
    assert await _quads(pg_conn, test_space, new_slot) > 0


async def test_kgframes_replace_under_a_parent_leaves_the_siblings(
        vg_client, test_space, test_graph, pg_conn):
    root, _ = await _standalone(vg_client, test_space, test_graph)
    a, _ = await _standalone(vg_client, test_space, test_graph, parent=root)
    b, b_slot = await _standalone(vg_client, test_space, test_graph, parent=root)

    _, _, objs = _frame("a again", frame_uri=a)
    r = await vg_client.kgframes.create_kgframes(
        space_id=test_space, graph_id=test_graph, objects=objs,
        parent_uri=root, operation_mode="replace")

    assert r.is_success, f"{r.status}: {_msg(r)}"
    assert await _quads(pg_conn, test_space, b, b_slot) > 0, (
        "replacing one child deleted every child of the parent")
    assert await _links_into(pg_conn, test_space, a) == 1


async def test_a_stale_kgframes_replace_changes_nothing(
        vg_client, test_space, test_graph, pg_conn):
    frame, old_slot = await _standalone(vg_client, test_space, test_graph)
    _, new_slot, objs = _frame("loser", frame_uri=frame)
    r = await vg_client.kgframes.create_kgframes(
        space_id=test_space, graph_id=test_graph, objects=objs,
        operation_mode="replace", if_unmodified_since=_STALE)
    assert r.is_conflict, f"{r.status}: {_msg(r)}"
    assert await _quads(pg_conn, test_space, old_slot) > 0
    assert await _quads(pg_conn, test_space, new_slot) == 0


# ---------------------------------------------------------------------------
# /kgframes refuses an entity's frame on writes (decision 3)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode", ["create", "update", "upsert", "replace"])
async def test_kgframes_will_not_write_an_entitys_frame(
        vg_client, test_space, test_graph, pg_conn, mode):
    entity = await _entity(vg_client, test_space, test_graph)
    frame, slot = await _entity_frame(vg_client, test_space, test_graph, entity)

    _, new_slot, objs = _frame("over the top", frame_uri=frame)
    r = await vg_client.kgframes.create_kgframes(
        space_id=test_space, graph_id=test_graph, objects=objs,
        operation_mode=mode)

    assert r.status == "invalid_request", f"{mode}: {r.status}: {_msg(r)}"
    assert "/kgentities/kgframes" in _msg(r)
    assert await _quads(pg_conn, test_space, slot) > 0
    assert await _quads(pg_conn, test_space, new_slot) == 0


async def test_kgframes_will_not_attach_under_an_entitys_frame(
        vg_client, test_space, test_graph, pg_conn):
    entity = await _entity(vg_client, test_space, test_graph)
    frame, _ = await _entity_frame(vg_client, test_space, test_graph, entity)
    child, child_slot, objs = _frame()
    r = await vg_client.kgframes.create_kgframes(
        space_id=test_space, graph_id=test_graph, objects=objs, parent_uri=frame)
    assert r.status == "invalid_request", f"{r.status}: {_msg(r)}"
    assert await _quads(pg_conn, test_space, child, child_slot) == 0


async def test_kgframes_will_not_attach_under_an_entity(
        vg_client, test_space, test_graph, pg_conn):
    entity = await _entity(vg_client, test_space, test_graph)
    child, child_slot, objs = _frame()
    r = await vg_client.kgframes.create_kgframes(
        space_id=test_space, graph_id=test_graph, objects=objs, parent_uri=entity)
    assert r.status == "invalid_request", f"{r.status}: {_msg(r)}"
    assert await _quads(pg_conn, test_space, child, child_slot) == 0
