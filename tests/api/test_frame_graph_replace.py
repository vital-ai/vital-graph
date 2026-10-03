"""Frame update and upsert REPLACE the frame graph — `issues/256`, item 1.

`hasFrameGraphURI` IS the frame graph (decided 2026-10-03). An update or upsert
of a frame deletes everything grouped under it that the request does not
re-send. Before this, both deleted only the subjects in the request: a slot
left out SURVIVED, still attached by its Edge_hasKGSlot and returned on every
read. That is a merge, and a caller removing a slot got a success and kept the
slot.

What must NOT be replaced:
  - a CHILD frame, its slots, or the parent -> child link: `update` is shallow
    (`frame_hierarchy_consistency_plan.md` §3), and an Edge_hasKGFrame carries no
    grouping, so none of that is in the parent's frame graph;
  - another frame on the same entity: a write touches only the frames it names,
    which is what lets two services co-own one entity's frames.

And a removed slot's derived rows go with it: FTS in the transaction, and
vector/geo/fuzzy through auto-sync, checked here through geo.

Runs against the vg-test stack (:8002, Postgres :5433).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot

pytestmark = [pytest.mark.api, pytest.mark.asyncio(loop_scope="session")]

NS = "http://vital.ai/test/frame_graph_replace/"
TEXT_VALUE = "http://vital.ai/ontology/haley-ai-kg#hasTextSlotValue"


def _u(kind: str) -> str:
    return f"{NS}{kind}_{uuid.uuid4().hex[:8]}"


def _frame(uri):
    f = KGFrame()
    f.URI = uri
    f.name = "Replace Probe Frame"
    return f


def _slot(uri, value="v"):
    s = KGTextSlot()
    s.URI = uri
    s.name = "Replace Probe Slot"
    s.textSlotValue = value
    return s


def _edge(frame_uri, slot_uri):
    e = Edge_hasKGSlot()
    e.URI = f"{frame_uri}#edge_to_{slot_uri.rsplit('_', 1)[-1]}"
    e.edgeSource = frame_uri
    e.edgeDestination = slot_uri
    return e


def _frame_graph(frame_uri, slots):
    """A frame, its slots (uri -> value) and their edges."""
    objs = [_frame(frame_uri)]
    for uri, value in slots.items():
        objs += [_slot(uri, value), _edge(frame_uri, uri)]
    return objs


async def _quads(pg_conn, space, uri) -> int:
    return await pg_conn.fetchval(
        f"SELECT count(*) FROM {space}_rdf_quad "
        f"WHERE subject_uuid = vitalgraph_term_uuid($1, 'U')", uri)


async def _value(pg_conn, space, slot_uri):
    return await pg_conn.fetchval(
        f"SELECT o.term_text FROM {space}_rdf_quad q "
        f"JOIN {space}_term o ON o.term_uuid = q.object_uuid "
        f"WHERE q.subject_uuid = vitalgraph_term_uuid($1, 'U') "
        f"AND q.predicate_uuid = vitalgraph_term_uuid($2, 'U')", slot_uri, TEXT_VALUE)


async def _entity(vg_client, space, graph):
    e = KGEntity()
    e.URI = _u("entity")
    e.name = "Replace Probe Entity"
    r = await vg_client.kgentities.create_kgentities(space_id=space, graph_id=graph, objects=[e])
    assert r.is_success, r.error_message
    return str(e.URI)


# ---------------------------------------------------------------------------
# A slot left out of an update / upsert is GONE, with its edge — both routes
# ---------------------------------------------------------------------------

async def _write(vg_client, space, graph, route, mode, objects, entity=None):
    if route == "entity":
        if mode == "update":
            return await vg_client.kgentities.update_entity_frames(
                space_id=space, graph_id=graph, entity_uri=entity, objects=objects)
        return await vg_client.kgentities.create_entity_frames(
            space_id=space, graph_id=graph, entity_uri=entity, objects=objects,
            operation_mode=mode)
    if mode == "update":
        return await vg_client.kgframes.update_kgframes(
            space_id=space, graph_id=graph, objects=objects)
    return await vg_client.kgframes.create_kgframes(
        space_id=space, graph_id=graph, objects=objects, operation_mode=mode)


@pytest.mark.parametrize("route", ["entity", "standalone"])
@pytest.mark.parametrize("mode", ["update", "upsert"])
async def test_a_slot_left_out_is_removed(vg_client, test_space, test_graph, pg_conn,
                                          route, mode):
    entity = await _entity(vg_client, test_space, test_graph) if route == "entity" else None
    f, keep, drop = _u("frame"), _u("slot"), _u("slot")
    cr = await _write(vg_client, test_space, test_graph, route, "create",
                      _frame_graph(f, {keep: "keep", drop: "drop"}), entity)
    assert cr.is_success, cr.error_message
    drop_edge = str(_edge(f, drop).URI)
    assert await _quads(pg_conn, test_space, drop) and await _quads(pg_conn, test_space, drop_edge)

    r = await _write(vg_client, test_space, test_graph, route, mode,
                     _frame_graph(f, {keep: "kept"}), entity)
    assert r.is_success, r.error_message

    assert await _quads(pg_conn, test_space, drop) == 0, (
        f"{route} {mode} MERGED: the slot left out of the request survived")
    assert await _quads(pg_conn, test_space, drop_edge) == 0, (
        f"{route} {mode} left the removed slot's Edge_hasKGSlot behind")
    assert await _value(pg_conn, test_space, keep) == "kept"


# ---------------------------------------------------------------------------
# Shallow: a parent's update leaves its child subtree and the link alone
# ---------------------------------------------------------------------------

async def test_updating_a_parent_leaves_its_child_alone(vg_client, test_space, test_graph,
                                                        pg_conn):
    parent, child, ps, cs = _u("frame"), _u("frame"), _u("slot"), _u("slot")
    r = await vg_client.kgframes.create_kgframes(
        space_id=test_space, graph_id=test_graph, objects=_frame_graph(parent, {ps: "p"}))
    assert r.is_success, r.error_message
    r = await vg_client.kgframes.create_kgframes(
        space_id=test_space, graph_id=test_graph, objects=_frame_graph(child, {cs: "c"}),
        parent_uri=parent)
    assert r.is_success, r.error_message
    links = await pg_conn.fetchval(
        f"SELECT count(*) FROM {test_space}_rdf_quad q "
        f"WHERE q.predicate_uuid = vitalgraph_term_uuid($1, 'U') "
        f"AND q.object_uuid = vitalgraph_term_uuid($2, 'U')",
        "http://vital.ai/ontology/vital-core#hasEdgeDestination", child)
    assert links, "no parent -> child link was written"

    r = await vg_client.kgframes.update_kgframes(
        space_id=test_space, graph_id=test_graph, objects=_frame_graph(parent, {ps: "p2"}))
    assert r.is_success, r.error_message

    assert await _value(pg_conn, test_space, ps) == "p2"
    assert await _quads(pg_conn, test_space, child), "the parent's update deleted the CHILD frame"
    assert await _value(pg_conn, test_space, cs) == "c", "the parent's update reached the child's slot"
    after = await pg_conn.fetchval(
        f"SELECT count(*) FROM {test_space}_rdf_quad q "
        f"WHERE q.predicate_uuid = vitalgraph_term_uuid($1, 'U') "
        f"AND q.object_uuid = vitalgraph_term_uuid($2, 'U')",
        "http://vital.ai/ontology/vital-core#hasEdgeDestination", child)
    assert after == links, "the parent's update removed the parent -> child link"


# ---------------------------------------------------------------------------
# Co-ownership: an upsert of one frame leaves another frame on the entity alone
# ---------------------------------------------------------------------------

async def test_upserting_one_frame_leaves_another_alone(vg_client, test_space, test_graph,
                                                        pg_conn):
    entity = await _entity(vg_client, test_space, test_graph)
    f1, f2, s1, s2 = _u("frame"), _u("frame"), _u("slot"), _u("slot")
    for f, s, v in ((f1, s1, "one"), (f2, s2, "two")):
        r = await vg_client.kgentities.create_entity_frames(
            space_id=test_space, graph_id=test_graph, entity_uri=entity,
            objects=_frame_graph(f, {s: v}))
        assert r.is_success, r.error_message
    before = (await _quads(pg_conn, test_space, f2), await _quads(pg_conn, test_space, s2))

    r = await vg_client.kgentities.create_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=entity,
        objects=_frame_graph(f1, {s1: "one-changed"}), operation_mode="upsert")
    assert r.is_success, r.error_message

    assert await _value(pg_conn, test_space, s1) == "one-changed"
    assert (await _quads(pg_conn, test_space, f2),
            await _quads(pg_conn, test_space, s2)) == before, (
        "an upsert of one frame changed ANOTHER frame on the same entity")
    assert await _value(pg_conn, test_space, s2) == "two"


# ---------------------------------------------------------------------------
# A removed slot's derived rows go with it (through geo, as test_delete_contract)
# ---------------------------------------------------------------------------

async def test_a_removed_slots_derived_rows_go_with_it(vg_client, test_space, test_graph,
                                                       pg_conn):
    cfg = await vg_client.geo_config.update_config(
        space_id=test_space, enabled=True, auto_sync=True)
    assert cfg.enabled and cfg.auto_sync
    f, keep, drop = _u("frame"), _u("slot"), _u("slot")
    r = await vg_client.kgframes.create_kgframes(
        space_id=test_space, graph_id=test_graph,
        objects=_frame_graph(f, {keep: "k", drop: "d"}))
    assert r.is_success, r.error_message
    await pg_conn.execute(
        f"INSERT INTO {test_space}_geo (subject_uuid, location, latitude, longitude, context_uuid) "
        f"VALUES (vitalgraph_term_uuid($1, 'U'), "
        f"ST_SetSRID(ST_MakePoint(-73.98, 40.75), 4326)::geography, 40.75, -73.98, "
        f"vitalgraph_term_uuid($2, 'U'))", drop, test_graph)

    r = await vg_client.kgframes.update_kgframes(
        space_id=test_space, graph_id=test_graph, objects=_frame_graph(f, {keep: "k"}))
    assert r.is_success, r.error_message
    assert await _quads(pg_conn, test_space, drop) == 0

    left = 1
    deadline = asyncio.get_running_loop().time() + 15
    while left and asyncio.get_running_loop().time() < deadline:
        left = await pg_conn.fetchval(
            f"SELECT count(*) FROM {test_space}_geo "
            f"WHERE subject_uuid = vitalgraph_term_uuid($1, 'U')", drop)
        if left:
            await asyncio.sleep(0.25)
    assert left == 0, "the removed slot's geo row outlived it"
