"""Frame `create` refuses an existing frame, through the API (`issues/256` item 3).

ONLY MEANINGFUL WITH THE SERVER SWITCH ON: `VITALGRAPH_FRAME_CREATE_REFUSES_EXISTING`
is read by the SERVER, and a test cannot set the server's environment. So this
module runs only when `VG_TEST_FRAME_CREATE_REFUSES_EXISTING=1` says the stack
under test was started with it. With the switch off, create still overwrites,
and the existing suites pin that.
"""

from __future__ import annotations

import os
import uuid

import pytest

from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot

pytestmark = [
    pytest.mark.api, pytest.mark.asyncio(loop_scope="session"),
    pytest.mark.skipif(
        os.getenv("VG_TEST_FRAME_CREATE_REFUSES_EXISTING", "") not in ("1", "true"),
        reason="the server under test must run with VITALGRAPH_FRAME_CREATE_REFUSES_EXISTING=1; "
               "set VG_TEST_FRAME_CREATE_REFUSES_EXISTING=1 when it does"),
]

NS = "http://vital.ai/test/create_refuses/"


def _uid():
    return uuid.uuid4().hex[:8]


def _frame(value="v", frame_uri=None, slot_uri=None):
    frame_uri = frame_uri or f"{NS}frame_{_uid()}"
    slot_uri = slot_uri or f"{NS}slot_{_uid()}"
    f = KGFrame(); f.URI = frame_uri; f.name = "Probe"
    s = KGTextSlot(); s.URI = slot_uri; s.name = "Value"; s.textSlotValue = value
    e = Edge_hasKGSlot(); e.URI = f"{NS}edge_{_uid()}"; e.edgeSource = frame_uri; e.edgeDestination = slot_uri
    return frame_uri, slot_uri, [f, s, e]


async def _slot_value(pg_conn, space, slot_uri):
    return await pg_conn.fetchval(
        f"SELECT tt.term_text FROM {space}_rdf_quad q "
        f"JOIN {space}_term tt ON tt.term_uuid = q.object_uuid "
        f"WHERE q.subject_uuid = vitalgraph_term_uuid($1, 'U') "
        f"AND q.predicate_uuid = vitalgraph_term_uuid($2, 'U')",
        slot_uri, "http://vital.ai/ontology/haley-ai-kg#hasTextSlotValue")


async def test_entity_frame_create_refuses_an_existing_frame(
        vg_client, test_space, test_graph, pg_conn):
    e = KGEntity(); e.URI = f"{NS}entity_{_uid()}"; e.name = "x"
    assert (await vg_client.kgentities.create_kgentities(
        space_id=test_space, graph_id=test_graph, objects=[e])).is_success
    frame, slot, objs = _frame("first")
    r = await vg_client.kgentities.create_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=str(e.URI), objects=objs)
    assert r.is_success, r.message

    _, _, objs = _frame("second", frame_uri=frame, slot_uri=slot)
    r = await vg_client.kgentities.create_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=str(e.URI), objects=objs)
    assert r.status == "already_exists", f"{r.status}: {r.message or r.error_message}"
    assert await _slot_value(pg_conn, test_space, slot) == "first", "create overwrote"

    r = await vg_client.kgentities.create_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=str(e.URI), objects=objs,
        operation_mode="upsert")
    assert r.is_success and await _slot_value(pg_conn, test_space, slot) == "second"


async def test_kgframes_create_refuses_an_existing_frame(
        vg_client, test_space, test_graph, pg_conn):
    frame, slot, objs = _frame("first")
    assert (await vg_client.kgframes.create_kgframes(
        space_id=test_space, graph_id=test_graph, objects=objs)).is_success
    _, _, objs = _frame("second", frame_uri=frame, slot_uri=slot)
    r = await vg_client.kgframes.create_kgframes(
        space_id=test_space, graph_id=test_graph, objects=objs)
    assert r.status == "already_exists", f"{r.status}: {r.message or r.error_message}"
    assert await _slot_value(pg_conn, test_space, slot) == "first", "create overwrote"


async def test_a_create_reusing_one_existing_slot_is_refused(
        vg_client, test_space, test_graph, pg_conn):
    """Not only the frame: any existing object in the payload refuses it."""
    _, slot, objs = _frame("first")
    assert (await vg_client.kgframes.create_kgframes(
        space_id=test_space, graph_id=test_graph, objects=objs)).is_success
    new_frame, _, objs = _frame("second", slot_uri=slot)
    r = await vg_client.kgframes.create_kgframes(
        space_id=test_space, graph_id=test_graph, objects=objs)
    assert r.status == "already_exists", f"{r.status}: {r.message or r.error_message}"
    assert await _slot_value(pg_conn, test_space, slot) == "first"
