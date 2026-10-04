"""Entity-frame upsert's checks, and the mode answers (`issues/256` items 2, 3, 5, 7).

ITEM 2. Entity-frame upsert validated nothing: it overwrote another entity's
frame (and re-stamped its `hasKGGraphURI`), wrote frames onto an entity that
did not exist, and created a frame without linking it, so reads walking
`Edge_hasEntityKGFrame` missed it. Now the entity and ownership are checked
under the entity lock, and a frame without its link gets one.

ITEM 3 (unblocked half). `/kgframes` update of a missing frame created it; it
answers NOT_FOUND. (Create refusing an existing frame waits for the portal.)

ITEM 5. An unknown `/kgframes` mode became a create; it answers INVALID_REQUEST.

ITEM 7. A successful entity-frame upsert answered CREATED.

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

NS = "http://vital.ai/test/upsert_contract/"


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _frame(value: str = "v", frame_uri: str | None = None):
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
    e.name = "Upsert Probe"
    r = await vg_client.kgentities.create_kgentities(
        space_id=space, graph_id=graph, objects=[e])
    assert r.is_success, r.error_message or r.message
    return uri


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


def _msg(r) -> str:
    return r.message or r.error_message or ""


async def _upsert(vg_client, space, graph, entity, objs, parent=None):
    return await vg_client.kgentities.create_entity_frames(
        space_id=space, graph_id=graph, entity_uri=entity, objects=objs,
        parent_frame_uri=parent, operation_mode="upsert")


# ---------------------------------------------------------------------------
# Item 2 — entity-frame upsert
# ---------------------------------------------------------------------------

async def test_upsert_creates_a_linked_frame_and_says_upserted(
        vg_client, test_space, test_graph, pg_conn):
    entity = await _entity(vg_client, test_space, test_graph)
    frame, slot, objs = _frame()
    r = await _upsert(vg_client, test_space, test_graph, entity, objs)

    assert r.is_success, f"{r.status}: {_msg(r)}"
    assert r.status == "upserted", f"item 7: answered {r.status!r}"
    assert await _quads(pg_conn, test_space, frame, slot) > 0
    assert await _links_into(pg_conn, test_space, frame) == 1, (
        "an upsert that creates a frame must link it from the entity")

    frames = await vg_client.kgentities.get_kgentity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity)
    assert frame in str(frames), "the new frame is missing from the entity's frames"


async def test_upserting_again_does_not_add_a_second_link(
        vg_client, test_space, test_graph, pg_conn):
    entity = await _entity(vg_client, test_space, test_graph)
    frame, _, objs = _frame("one")
    assert (await _upsert(vg_client, test_space, test_graph, entity, objs)).is_success
    _, _, objs = _frame("two", frame_uri=frame)
    assert (await _upsert(vg_client, test_space, test_graph, entity, objs)).is_success
    assert await _links_into(pg_conn, test_space, frame) == 1


async def test_upsert_under_a_parent_links_from_the_parent(
        vg_client, test_space, test_graph, pg_conn):
    entity = await _entity(vg_client, test_space, test_graph)
    parent, _, objs = _frame()
    assert (await _upsert(vg_client, test_space, test_graph, entity, objs)).is_success
    child, _, objs = _frame()
    r = await _upsert(vg_client, test_space, test_graph, entity, objs, parent=parent)
    assert r.is_success, f"{r.status}: {_msg(r)}"
    assert await _links_into(pg_conn, test_space, child) == 1


async def test_upsert_of_another_entitys_frame_is_refused(
        vg_client, test_space, test_graph, pg_conn):
    mine = await _entity(vg_client, test_space, test_graph)
    theirs = await _entity(vg_client, test_space, test_graph)
    frame, their_slot, objs = _frame("theirs")
    assert (await _upsert(vg_client, test_space, test_graph, theirs, objs)).is_success

    _, my_slot, objs = _frame("hijack", frame_uri=frame)
    r = await _upsert(vg_client, test_space, test_graph, mine, objs)

    assert r.status == "invalid_request", f"{r.status}: {_msg(r)}"
    assert await _quads(pg_conn, test_space, their_slot) > 0, "their slot was replaced"
    assert await _quads(pg_conn, test_space, my_slot) == 0


async def test_upsert_onto_a_missing_entity_writes_nothing(
        vg_client, test_space, test_graph, pg_conn):
    missing = f"{NS}never_{_uid()}"
    frame, slot, objs = _frame()
    r = await _upsert(vg_client, test_space, test_graph, missing, objs)
    assert not r.is_success
    assert "not found" in _msg(r)
    assert await _quads(pg_conn, test_space, frame, slot) == 0


# ---------------------------------------------------------------------------
# Items 3 and 5 — /kgframes
# ---------------------------------------------------------------------------

async def test_kgframes_update_of_a_missing_frame_is_not_found(
        vg_client, test_space, test_graph, pg_conn):
    frame, slot, objs = _frame()
    r = await vg_client.kgframes.update_kgframes(
        space_id=test_space, graph_id=test_graph, objects=objs)
    assert r.status == "not_found", f"{r.status}: {_msg(r)}"
    assert await _quads(pg_conn, test_space, frame, slot) == 0, "update created it"


async def test_kgframes_unknown_mode_is_refused(
        vg_client, test_space, test_graph, pg_conn):
    frame, slot, objs = _frame()
    r = await vg_client.kgframes.create_kgframes(
        space_id=test_space, graph_id=test_graph, objects=objs,
        operation_mode="upsrt")
    assert r.status == "invalid_request", f"{r.status}: {_msg(r)}"
    assert await _quads(pg_conn, test_space, frame, slot) == 0, "a typo became a create"
