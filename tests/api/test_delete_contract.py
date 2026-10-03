"""The delete contract of `issues/256`, through the API.

Two defects in the entity delete, both fixed alongside this file:

  ABSENT IS NOT A FAILURE (D3, D4). A graph delete of an entity that was not
  there answered STORE_FAILED, and a batch could only say "they may be absent,
  or the deletes may have failed". A delete of something already gone did what
  was asked, so it answers NO_OP, and `absent_uris` names what was gone.

  THE MEMBERS' DERIVED ROWS GO WITH THE ENTITY (D5b, D5c). Vector, geo and fuzzy
  rows are removed per subject by auto-sync, after the commit. The graph delete's
  fast path never told auto-sync which members it had removed, so it was handed
  the entity URI alone and every slot's rows outlived the entity. The batch
  delete passed no members at all.

The derived rows are checked through GEO because it is the cheapest to set up:
a `{space}_geo` row is keyed on (subject, context), exactly as vector and fuzzy
rows are, and auto-sync deletes all three from the same subject list. Geo
cleanup only runs when the space has geo ENABLED with `auto_sync` on
(`_sync_geo_for_subjects` returns early otherwise), so the tests turn that on
through the API first. The row is SEEDED for the slot after the create, rather
than produced by a geo-typed slot, so the test does not depend on geo
extraction, only on the delete reaching the slot.

Runs against the vg-test stack (:8002, Postgres :5433), never the dev server.
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

NS = "http://vital.ai/test/delete_contract/"

# Auto-sync runs after the response, on the internal pool. Generous, because a
# miss here is a failure and a slow stack is not the defect under test.
_SYNC_WAIT_S = 15.0


def _uid() -> str:
    return uuid.uuid4().hex[:8]


async def _entity(vg_client, space, graph, *, with_slot: bool):
    """An entity, optionally with one frame holding one text slot.

    Returns (entity_uri, slot_uri or None).
    """
    entity_uri = f"{NS}entity_{_uid()}"
    e = KGEntity()
    e.URI = entity_uri
    e.name = "Delete Contract Probe"
    cr = await vg_client.kgentities.create_kgentities(
        space_id=space, graph_id=graph, objects=[e])
    assert cr.is_success, f"entity create failed: {cr.error_message}"
    if not with_slot:
        return entity_uri, None

    frame_uri, slot_uri = f"{NS}frame_{_uid()}", f"{NS}slot_{_uid()}"
    frame = KGFrame()
    frame.URI = frame_uri
    frame.name = "Probe Frame"
    slot = KGTextSlot()
    slot.URI = slot_uri
    slot.name = "Probe Slot"
    slot.textSlotValue = "probe"
    edge = Edge_hasKGSlot()
    edge.URI = f"{NS}edge_{_uid()}"
    edge.edgeSource = frame_uri
    edge.edgeDestination = slot_uri
    fr = await vg_client.kgentities.create_entity_frames(
        space_id=space, graph_id=graph, entity_uri=entity_uri,
        objects=[frame, slot, edge])
    assert fr.is_success, f"frame create failed: {fr.error_message}"
    return entity_uri, slot_uri


async def _enable_geo_auto_sync(vg_client, space):
    """Geo cleanup is skipped for a space without geo enabled + auto_sync."""
    cfg = await vg_client.geo_config.update_config(
        space_id=space, enabled=True, auto_sync=True)
    assert cfg.enabled and cfg.auto_sync, f"geo config not applied: {cfg}"


async def _seed_geo(pg_conn, space, graph, subject_uri):
    await pg_conn.execute(
        f"INSERT INTO {space}_geo "
        f"(subject_uuid, location, latitude, longitude, context_uuid) "
        f"VALUES (vitalgraph_term_uuid($1, 'U'), "
        f"ST_SetSRID(ST_MakePoint(-73.98, 40.75), 4326)::geography, "
        f"40.75, -73.98, vitalgraph_term_uuid($2, 'U'))",
        subject_uri, graph)


async def _geo_rows(pg_conn, space, graph, subject_uri) -> int:
    return await pg_conn.fetchval(
        f"SELECT count(*) FROM {space}_geo "
        f"WHERE subject_uuid = vitalgraph_term_uuid($1, 'U') "
        f"AND context_uuid = vitalgraph_term_uuid($2, 'U')",
        subject_uri, graph)


async def _wait_until_gone(pg_conn, space, graph, subject_uri) -> int:
    """Poll until the slot's geo row is gone or the wait runs out; return rows."""
    deadline = asyncio.get_running_loop().time() + _SYNC_WAIT_S
    while True:
        n = await _geo_rows(pg_conn, space, graph, subject_uri)
        if n == 0 or asyncio.get_running_loop().time() > deadline:
            return n
        await asyncio.sleep(0.25)


# ---------------------------------------------------------------------------
# D3 — an absent entity is NO_OP, on both forms of the single delete
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("graph_delete", [True, False], ids=["graph", "entity_only"])
async def test_deleting_an_absent_entity_is_no_op(vg_client, test_space, test_graph,
                                                  graph_delete):
    absent = f"{NS}never_created_{_uid()}"
    r = await vg_client.kgentities.delete_kgentity(
        space_id=test_space, graph_id=test_graph, uri=absent,
        delete_entity_graph=graph_delete)

    assert r.status == "no_op", (
        f"an absent entity answered {r.status!r}: a delete of something already "
        f"gone achieved what was asked, so it is NO_OP, not a failure")
    assert r.is_success
    assert r.deleted_count == 0
    assert r.absent_uris == [absent]


# ---------------------------------------------------------------------------
# D4 — a batch counts absent as satisfied, and says which were absent
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("graph_delete", [True, False], ids=["graph", "entity_only"])
async def test_a_batch_with_an_absent_entity_is_deleted_and_names_it(
        vg_client, test_space, test_graph, pg_conn, graph_delete):
    present, _ = await _entity(vg_client, test_space, test_graph, with_slot=False)
    absent = f"{NS}never_created_{_uid()}"

    r = await vg_client.kgentities.delete_kgentities_batch(
        space_id=test_space, graph_id=test_graph, uri_list=[present, absent],
        delete_entity_graph=graph_delete)

    assert r.status == "deleted", (
        f"present + absent answered {r.status!r}; nothing failed, so the batch "
        f"is DELETED with the absent one named")
    assert r.deleted_uris == [present]
    assert r.absent_uris == [absent]
    left = await pg_conn.fetchval(
        f"SELECT count(*) FROM {test_space}_rdf_quad "
        f"WHERE subject_uuid = vitalgraph_term_uuid($1, 'U')", present)
    assert left == 0, f"the present entity was reported deleted and has {left} quads"


@pytest.mark.parametrize("graph_delete", [True, False], ids=["graph", "entity_only"])
async def test_a_batch_where_everything_is_absent_is_no_op(
        vg_client, test_space, test_graph, graph_delete):
    absent = [f"{NS}never_created_{_uid()}" for _ in range(2)]
    r = await vg_client.kgentities.delete_kgentities_batch(
        space_id=test_space, graph_id=test_graph, uri_list=absent,
        delete_entity_graph=graph_delete)

    assert r.status == "no_op", f"an all-absent batch answered {r.status!r}"
    assert r.is_success
    assert sorted(r.absent_uris) == sorted(absent)


# ---------------------------------------------------------------------------
# D5b / D5c — a member's derived rows go with the entity graph
# ---------------------------------------------------------------------------

async def test_graph_delete_removes_a_slots_derived_rows(vg_client, test_space,
                                                         test_graph, pg_conn):
    await _enable_geo_auto_sync(vg_client, test_space)
    entity_uri, slot_uri = await _entity(vg_client, test_space, test_graph,
                                         with_slot=True)
    await _seed_geo(pg_conn, test_space, test_graph, slot_uri)
    assert await _geo_rows(pg_conn, test_space, test_graph, slot_uri) == 1

    r = await vg_client.kgentities.delete_kgentity(
        space_id=test_space, graph_id=test_graph, uri=entity_uri,
        delete_entity_graph=True)
    assert r.status == "deleted", f"delete answered {r.status!r}: {r.error_message}"

    left = await _wait_until_gone(pg_conn, test_space, test_graph, slot_uri)
    assert left == 0, (
        f"the slot's geo row outlived its entity ({left} after {_SYNC_WAIT_S}s): "
        f"auto-sync was not told about the members of the deleted graph")


async def test_batch_graph_delete_removes_a_slots_derived_rows(vg_client, test_space,
                                                               test_graph, pg_conn):
    await _enable_geo_auto_sync(vg_client, test_space)
    entity_uri, slot_uri = await _entity(vg_client, test_space, test_graph,
                                         with_slot=True)
    await _seed_geo(pg_conn, test_space, test_graph, slot_uri)
    assert await _geo_rows(pg_conn, test_space, test_graph, slot_uri) == 1

    r = await vg_client.kgentities.delete_kgentities_batch(
        space_id=test_space, graph_id=test_graph, uri_list=[entity_uri],
        delete_entity_graph=True)
    assert r.status == "deleted", f"delete answered {r.status!r}: {r.error_message}"

    left = await _wait_until_gone(pg_conn, test_space, test_graph, slot_uri)
    assert left == 0, (
        f"the slot's geo row outlived its entity in a BATCH delete ({left} after "
        f"{_SYNC_WAIT_S}s): the batch passed auto-sync no members at all")
