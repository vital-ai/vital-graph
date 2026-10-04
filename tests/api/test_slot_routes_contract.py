"""The slot routes' contract, through the API (`issues/256`, decided 2026-10-04).

TWO ROUTES, mirroring the frame routes:
- `/kgframes/kgslots` writes and deletes a STANDALONE frame's slots, locked and
  guarded on the frame, and REFUSES an entity's frame — as `/kgframes` does.
- `/kgentities/kgframes/kgslots` (new) does it for an entity's frame, locked,
  guarded and stamped on the ENTITY, and the frame must be that entity's.

ONE CONTRACT on both, decided under the lock: `create` refuses an existing slot,
`update` a missing one, `upsert` takes either; a slot of another frame is
refused (update used to rewrite it and move it under this frame); an
`Edge_hasKGSlot` is minted only for a new slot (an upsert duplicated the edge of
a slot written by the entity route); delete is one transaction, an absent slot
is NO_OP, and an unknown mode is refused.

Asserted by raw count in the quad table as well as by status. Runs against the
vg-test stack (:8002, Postgres :5433).
"""

from __future__ import annotations

import uuid

import pytest

from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot

pytestmark = [pytest.mark.api, pytest.mark.asyncio(loop_scope="session")]

NS = "http://vital.ai/test/slot_routes/"
_STALE = "2000-01-01T00:00:00+00:00"


def _uid():
    return uuid.uuid4().hex[:8]


def _slot(value="v", uri=None):
    s = KGTextSlot()
    s.URI = uri or f"{NS}slot_{_uid()}"
    s.name = "Value"
    s.textSlotValue = value
    return s


def _frame_objs(slot_value="v"):
    frame_uri = f"{NS}frame_{_uid()}"
    f = KGFrame(); f.URI = frame_uri; f.name = "Probe"
    s = _slot(slot_value)
    e = Edge_hasKGSlot(); e.URI = f"{NS}edge_{_uid()}"
    e.edgeSource = frame_uri; e.edgeDestination = str(s.URI)
    return frame_uri, str(s.URI), [f, s, e]


async def _entity_with_frame(vg_client, space, graph):
    e = KGEntity(); e.URI = f"{NS}entity_{_uid()}"; e.name = "Slot Probe"
    assert (await vg_client.kgentities.create_kgentities(
        space_id=space, graph_id=graph, objects=[e])).is_success
    frame, slot, objs = _frame_objs()
    r = await vg_client.kgentities.create_entity_frames(
        space_id=space, graph_id=graph, entity_uri=str(e.URI), objects=objs)
    assert r.is_success, r.message
    return str(e.URI), frame, slot


async def _standalone_frame(vg_client, space, graph):
    frame, slot, objs = _frame_objs()
    assert (await vg_client.kgframes.create_kgframes(
        space_id=space, graph_id=graph, objects=objs)).is_success
    return frame, slot


async def _quads(pg_conn, space, *uris):
    return await pg_conn.fetchval(
        f"SELECT count(*) FROM {space}_rdf_quad WHERE subject_uuid = ANY("
        f"ARRAY(SELECT vitalgraph_term_uuid(u, 'U') FROM unnest($1::text[]) u))",
        list(uris))


async def _edges_into(pg_conn, space, uri):
    return await pg_conn.fetchval(
        f"SELECT count(*) FROM {space}_rdf_quad "
        f"WHERE predicate_uuid = vitalgraph_term_uuid($1, 'U') "
        f"AND object_uuid = vitalgraph_term_uuid($2, 'U')",
        "http://vital.ai/ontology/vital-core#hasEdgeDestination", uri)


async def _value(pg_conn, space, slot_uri):
    return await pg_conn.fetchval(
        f"SELECT tt.term_text FROM {space}_rdf_quad q "
        f"JOIN {space}_term tt ON tt.term_uuid = q.object_uuid "
        f"WHERE q.subject_uuid = vitalgraph_term_uuid($1, 'U') "
        f"AND q.predicate_uuid = vitalgraph_term_uuid($2, 'U')",
        slot_uri, "http://vital.ai/ontology/haley-ai-kg#hasTextSlotValue")


async def _entity_stamp(vg_client, space, graph, entity):
    r = await vg_client.kgentities.get_kgentity(
        space_id=space, graph_id=graph, uri=entity, include_entity_graph=True)
    return r.modification_stamp


def _msg(r):
    return r.message or r.error_message or ""


# ---------------------------------------------------------------------------
# /kgframes/kgslots refuses an entity's frame
# ---------------------------------------------------------------------------

async def test_the_standalone_route_refuses_an_entitys_frame(
        vg_client, test_space, test_graph, pg_conn):
    _, frame, slot = await _entity_with_frame(vg_client, test_space, test_graph)
    new = _slot("intruder")
    r = await vg_client.kgframes.create_frame_slots(
        space_id=test_space, graph_id=test_graph, frame_uri=frame, objects=[new])
    assert r.status == "invalid_request", f"{r.status}: {_msg(r)}"
    assert "/kgentities/kgframes/kgslots" in _msg(r)
    assert await _quads(pg_conn, test_space, str(new.URI)) == 0

    r = await vg_client.kgframes.delete_frame_slots(
        space_id=test_space, graph_id=test_graph, frame_uri=frame, slot_uris=[slot])
    assert r.status == "invalid_request", f"{r.status}: {_msg(r)}"
    assert await _quads(pg_conn, test_space, slot) > 0


async def test_the_standalone_route_still_serves_standalone_frames(
        vg_client, test_space, test_graph, pg_conn):
    frame, _ = await _standalone_frame(vg_client, test_space, test_graph)
    new = _slot("added")
    r = await vg_client.kgframes.create_frame_slots(
        space_id=test_space, graph_id=test_graph, frame_uri=frame, objects=[new])
    assert r.is_success, _msg(r)
    assert await _edges_into(pg_conn, test_space, str(new.URI)) == 1
    r = await vg_client.kgframes.delete_frame_slots(
        space_id=test_space, graph_id=test_graph, frame_uri=frame, slot_uris=[str(new.URI)])
    assert r.status == "deleted", f"{r.status}: {_msg(r)}"
    assert await _quads(pg_conn, test_space, str(new.URI)) == 0
    assert await _edges_into(pg_conn, test_space, str(new.URI)) == 0


# ---------------------------------------------------------------------------
# /kgentities/kgframes/kgslots
# ---------------------------------------------------------------------------

async def test_the_entity_route_creates_and_shows_in_the_entity_graph(
        vg_client, test_space, test_graph, pg_conn):
    entity, frame, _ = await _entity_with_frame(vg_client, test_space, test_graph)
    before = await _entity_stamp(vg_client, test_space, test_graph, entity)
    new = _slot("added")
    r = await vg_client.kgentities.create_entity_frame_slots(
        space_id=test_space, graph_id=test_graph, entity_uri=entity,
        frame_uri=frame, objects=[new])
    assert r.status == "created", f"{r.status}: {_msg(r)}"
    assert await _edges_into(pg_conn, test_space, str(new.URI)) == 1
    assert await _entity_stamp(vg_client, test_space, test_graph, entity) != before, (
        "the write did not advance the ENTITY's version")
    g = await vg_client.kgentities.get_kgentity(
        space_id=test_space, graph_id=test_graph, uri=entity, include_entity_graph=True)
    uris = {str(o.URI) for o in (g.objects.objects if g.objects else [])}
    assert str(new.URI) in uris, "the cached entity graph does not show the new slot"


async def test_upsert_of_an_existing_slot_does_not_duplicate_its_edge(
        vg_client, test_space, test_graph, pg_conn):
    entity, frame, slot = await _entity_with_frame(vg_client, test_space, test_graph)
    r = await vg_client.kgentities.create_entity_frame_slots(
        space_id=test_space, graph_id=test_graph, entity_uri=entity,
        frame_uri=frame, objects=[_slot("changed", uri=slot)], operation_mode="upsert")
    assert r.status == "upserted", f"{r.status}: {_msg(r)}"
    assert await _value(pg_conn, test_space, slot) == "changed"
    assert await _edges_into(pg_conn, test_space, slot) == 1, (
        "upsert minted a second Edge_hasKGSlot for a slot that had one")


async def test_the_modes(vg_client, test_space, test_graph, pg_conn):
    entity, frame, slot = await _entity_with_frame(vg_client, test_space, test_graph)
    kw = dict(space_id=test_space, graph_id=test_graph, entity_uri=entity, frame_uri=frame)

    r = await vg_client.kgentities.create_entity_frame_slots(
        objects=[_slot("again", uri=slot)], **kw)
    assert r.status == "already_exists", f"create of an existing slot: {r.status}"
    missing = _slot("ghost")
    r = await vg_client.kgentities.create_entity_frame_slots(
        objects=[missing], operation_mode="update", **kw)
    assert r.status == "not_found", f"update of a missing slot: {r.status}"
    assert await _quads(pg_conn, test_space, str(missing.URI)) == 0, "update created it"
    r = await vg_client.kgentities.create_entity_frame_slots(
        objects=[_slot("x")], operation_mode="upsrt", **kw)
    assert r.status == "invalid_request", f"unknown mode: {r.status}"
    r = await vg_client.kgentities.create_entity_frame_slots(
        objects=[_slot("updated", uri=slot)], operation_mode="update", **kw)
    assert r.status == "updated", f"{r.status}: {_msg(r)}"
    assert await _value(pg_conn, test_space, slot) == "updated"


async def test_a_slot_of_another_frame_is_refused(
        vg_client, test_space, test_graph, pg_conn):
    entity, frame, _ = await _entity_with_frame(vg_client, test_space, test_graph)
    other_frame, other_slot, objs = _frame_objs("theirs")
    assert (await vg_client.kgentities.create_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity, objects=objs)).is_success

    r = await vg_client.kgentities.create_entity_frame_slots(
        space_id=test_space, graph_id=test_graph, entity_uri=entity, frame_uri=frame,
        objects=[_slot("moved", uri=other_slot)], operation_mode="update")
    assert r.status == "invalid_request", (
        f"{r.status}: update rewrote another frame's slot and moved it")
    assert await _value(pg_conn, test_space, other_slot) == "theirs"


async def test_a_frame_of_another_entity_is_refused(
        vg_client, test_space, test_graph, pg_conn):
    mine, _, _ = await _entity_with_frame(vg_client, test_space, test_graph)
    _, their_frame, _ = await _entity_with_frame(vg_client, test_space, test_graph)
    new = _slot("intruder")
    r = await vg_client.kgentities.create_entity_frame_slots(
        space_id=test_space, graph_id=test_graph, entity_uri=mine,
        frame_uri=their_frame, objects=[new])
    assert r.status == "invalid_request", f"{r.status}: {_msg(r)}"
    assert await _quads(pg_conn, test_space, str(new.URI)) == 0


async def test_a_stale_slot_write_is_a_conflict(
        vg_client, test_space, test_graph, pg_conn):
    entity, frame, slot = await _entity_with_frame(vg_client, test_space, test_graph)
    r = await vg_client.kgentities.create_entity_frame_slots(
        space_id=test_space, graph_id=test_graph, entity_uri=entity, frame_uri=frame,
        objects=[_slot("loser", uri=slot)], operation_mode="update",
        if_unmodified_since=_STALE)
    assert r.is_conflict, f"{r.status}: {_msg(r)}"
    assert await _value(pg_conn, test_space, slot) == "v"


async def test_the_entity_route_deletes(vg_client, test_space, test_graph, pg_conn):
    entity, frame, slot = await _entity_with_frame(vg_client, test_space, test_graph)
    kw = dict(space_id=test_space, graph_id=test_graph, entity_uri=entity, frame_uri=frame)

    r = await vg_client.kgentities.delete_entity_frame_slots(
        slot_uris=[slot], if_unmodified_since=_STALE, **kw)
    assert r.is_conflict, f"stale delete: {r.status}"
    assert await _quads(pg_conn, test_space, slot) > 0

    absent = f"{NS}never_{_uid()}"
    r = await vg_client.kgentities.delete_entity_frame_slots(slot_uris=[slot, absent], **kw)
    assert r.status == "deleted", f"{r.status}: {_msg(r)}"
    assert r.deleted_uris == [slot] and r.absent_uris == [absent]
    assert await _quads(pg_conn, test_space, slot) == 0
    assert await _edges_into(pg_conn, test_space, slot) == 0, "the slot's edge survived"

    r = await vg_client.kgentities.delete_entity_frame_slots(slot_uris=[slot], **kw)
    assert r.status == "no_op", f"deleting an absent slot: {r.status}"
