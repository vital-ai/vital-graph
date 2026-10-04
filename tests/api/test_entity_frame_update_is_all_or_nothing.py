"""An entity-frame `update` writes every frame it names, or none (`issues/256`).

Each frame group of an entity-frame update is its own transaction, and a frame
that failed the ownership check — because it did not exist, or was another
entity's — was SKIPPED inside a success. Measured at 0.0.45: a batch of an
existing frame A and a new frame B answered `updated`, `is_success` true, wrote
A and dropped B. A caller falling back from a refused `create` to `update` lost
the new frames without being told.

Now the whole request is decided first: every frame it touches must exist and
be this entity's, or nothing is written — `not_found` for a missing frame (as
`/kgframes` update answers since item 3), `invalid_request` for another
entity's frame or for slots sent without their frame.

Runs against the vg-test stack (:8002).
"""

from __future__ import annotations

import pytest

from tests.api.test_replace_and_ownership_contract import (
    _entity, _entity_frame, _frame, _quads)

pytestmark = [pytest.mark.api, pytest.mark.asyncio(loop_scope="session")]


async def _update(vg_client, space, graph, entity, objects):
    return await vg_client.kgentities.create_entity_frames(
        space_id=space, graph_id=graph, entity_uri=entity, objects=objects,
        operation_mode="update")


async def test_an_update_naming_a_missing_frame_writes_nothing(
        vg_client, test_space, test_graph, pg_conn):
    entity = await _entity(vg_client, test_space, test_graph)
    a_uri, a_slot = await _entity_frame(vg_client, test_space, test_graph, entity)
    _, a_new_slot, a_objs = _frame("new value", frame_uri=a_uri)
    b_uri, _, b_objs = _frame("b")

    r = await _update(vg_client, test_space, test_graph, entity, a_objs + b_objs)

    assert r.status == "not_found", f"{r.status}: {r.message}"
    assert not r.is_success
    assert b_uri in (r.message or "")
    assert await _quads(pg_conn, test_space, b_uri) == 0, "the missing frame was created"
    assert await _quads(pg_conn, test_space, a_slot) > 0, (
        "frame A was rewritten although the request was refused")
    assert await _quads(pg_conn, test_space, a_new_slot) == 0


async def test_an_update_naming_another_entitys_frame_writes_nothing(
        vg_client, test_space, test_graph, pg_conn):
    entity = await _entity(vg_client, test_space, test_graph)
    other = await _entity(vg_client, test_space, test_graph)
    a_uri, a_slot = await _entity_frame(vg_client, test_space, test_graph, entity)
    o_uri, o_slot = await _entity_frame(vg_client, test_space, test_graph, other)
    _, _, a_objs = _frame("new a", frame_uri=a_uri)
    _, _, o_objs = _frame("hijack", frame_uri=o_uri)

    r = await _update(vg_client, test_space, test_graph, entity, a_objs + o_objs)

    assert r.status == "invalid_request", f"{r.status}: {r.message}"
    assert await _quads(pg_conn, test_space, a_slot) > 0, "frame A was rewritten"
    assert await _quads(pg_conn, test_space, o_slot) > 0, "the other entity's frame was touched"


async def test_slots_sent_without_their_frame_are_refused(
        vg_client, test_space, test_graph, pg_conn):
    """An update replaces the frame graph: slots alone would replace it without the frame."""
    entity = await _entity(vg_client, test_space, test_graph)
    a_uri, _ = await _entity_frame(vg_client, test_space, test_graph, entity)
    _, new_slot, objs = _frame("orphan", frame_uri=a_uri)
    slot_and_edge = objs[1:]

    r = await _update(vg_client, test_space, test_graph, entity, slot_and_edge)

    assert r.status == "invalid_request", f"{r.status}: {r.message}"
    assert await _quads(pg_conn, test_space, a_uri) > 0, "the frame was replaced away"
    assert await _quads(pg_conn, test_space, new_slot) == 0


async def test_an_update_of_existing_frames_still_writes_them_all(
        vg_client, test_space, test_graph, pg_conn):
    entity = await _entity(vg_client, test_space, test_graph)
    a_uri, a_slot = await _entity_frame(vg_client, test_space, test_graph, entity)
    b_uri, b_slot = await _entity_frame(vg_client, test_space, test_graph, entity)
    _, a_new, a_objs = _frame("a2", frame_uri=a_uri)
    _, b_new, b_objs = _frame("b2", frame_uri=b_uri)

    r = await _update(vg_client, test_space, test_graph, entity, a_objs + b_objs)

    assert r.status == "updated" and r.is_success, f"{r.status}: {r.message}"
    for old, new in ((a_slot, a_new), (b_slot, b_new)):
        assert await _quads(pg_conn, test_space, old) == 0, "update did not replace the frame graph"
        assert await _quads(pg_conn, test_space, new) > 0


async def test_upsert_of_the_same_mixed_batch_writes_both(
        vg_client, test_space, test_graph, pg_conn):
    """The answer for a caller that means create-or-replace."""
    entity = await _entity(vg_client, test_space, test_graph)
    a_uri, a_slot = await _entity_frame(vg_client, test_space, test_graph, entity)
    _, a_new, a_objs = _frame("a2", frame_uri=a_uri)
    b_uri, _, b_objs = _frame("b")

    r = await vg_client.kgentities.create_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity,
        objects=a_objs + b_objs, operation_mode="upsert")

    assert r.status == "upserted" and r.is_success, f"{r.status}: {r.message}"
    assert await _quads(pg_conn, test_space, b_uri) > 0
    assert await _quads(pg_conn, test_space, a_slot) == 0
    assert await _quads(pg_conn, test_space, a_new) > 0
