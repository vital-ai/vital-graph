"""Entity-frame writes keep the derived stores in step — `issues/256`.

Vector, geo, fuzzy and FTS rows for a frame's slots are maintained by auto-sync,
which a write route schedules after its commit. The standalone `/kgframes` route
always did. The entity-frame routes (`POST /kgentities/kgframes` create, upsert
and update, and entity-frame replace) scheduled NOTHING for the subjects they
wrote, so a slot written or rewritten there was never (re-)embedded, geocoded
or indexed until something else touched it.

Checked through GEO, which needs no embedding model. A `KGGeoLocationSlot` is
geocoded by auto-sync into a `{space}_geo` row keyed on the slot
(`source_slot_uuid`), so the row exists only if auto-sync ran for the slot, and
moves only if it ran again after a rewrite.

Runs against the vg-test stack (:8002, Postgres :5433).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio

from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGGeoLocationSlot import KGGeoLocationSlot

pytestmark = [pytest.mark.api, pytest.mark.asyncio(loop_scope="session")]

NS = "http://vital.ai/test/entity_frame_auto_sync/"
_WAIT_S = 15.0
NYC = ("POINT(-73.98 40.75)", 40.75)
LONDON = ("POINT(-0.12 51.5)", 51.5)


def _u(kind: str) -> str:
    return f"{NS}{kind}_{uuid.uuid4().hex[:8]}"


def _geo_frame(frame_uri, slot_uri, wkt):
    f = KGFrame()
    f.URI = frame_uri
    f.name = "Auto-sync Probe Frame"
    s = KGGeoLocationSlot()
    s.URI = slot_uri
    s.name = "Auto-sync Probe Location"
    s.geoLocationSlotValue = wkt
    e = Edge_hasKGSlot()
    e.URI = f"{frame_uri}#edge"
    e.edgeSource = frame_uri
    e.edgeDestination = slot_uri
    return [f, s, e]


async def _slot_latitude(pg_conn, space, graph, slot_uri, want):
    """Poll for the slot-keyed geo row; return its latitude (None if absent)."""
    deadline = asyncio.get_running_loop().time() + _WAIT_S
    lat = None
    while asyncio.get_running_loop().time() < deadline:
        lat = await pg_conn.fetchval(
            f"SELECT latitude FROM {space}_geo "
            f"WHERE subject_uuid = vitalgraph_term_uuid($1, 'U') "
            f"AND source_slot_uuid = vitalgraph_term_uuid($1, 'U') "
            f"AND context_uuid = vitalgraph_term_uuid($2, 'U')", slot_uri, graph)
        if lat is not None and abs(lat - want) < 1e-6:
            return lat
        await asyncio.sleep(0.25)
    return lat


@pytest_asyncio.fixture(loop_scope="session")
async def geo_entity(vg_client, test_space, test_graph):
    cfg = await vg_client.geo_config.update_config(
        space_id=test_space, enabled=True, auto_sync=True)
    assert cfg.enabled and cfg.auto_sync
    e = KGEntity()
    e.URI = _u("entity")
    e.name = "Auto-sync Probe Entity"
    r = await vg_client.kgentities.create_kgentities(
        space_id=test_space, graph_id=test_graph, objects=[e])
    assert r.is_success, r.error_message
    return str(e.URI)


async def test_entity_frame_create_syncs_its_slots(vg_client, test_space, test_graph,
                                                   pg_conn, geo_entity):
    f, s = _u("frame"), _u("slot")
    r = await vg_client.kgentities.create_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=geo_entity,
        objects=_geo_frame(f, s, NYC[0]))
    assert r.is_success, r.error_message

    lat = await _slot_latitude(pg_conn, test_space, test_graph, s, NYC[1])
    assert lat == pytest.approx(NYC[1]), (
        f"no geo row for the slot after {_WAIT_S}s (got {lat}): the entity-frame "
        f"create scheduled no auto-sync for what it wrote")


@pytest.mark.parametrize("mode", ["update", "upsert"])
async def test_entity_frame_rewrite_resyncs_its_slots(vg_client, test_space, test_graph,
                                                      pg_conn, geo_entity, mode):
    f, s = _u("frame"), _u("slot")
    r = await vg_client.kgentities.create_entity_frames(
        space_id=test_space, graph_id=test_graph, entity_uri=geo_entity,
        objects=_geo_frame(f, s, NYC[0]))
    assert r.is_success, r.error_message
    await _slot_latitude(pg_conn, test_space, test_graph, s, NYC[1])

    if mode == "update":
        r = await vg_client.kgentities.update_entity_frames(
            space_id=test_space, graph_id=test_graph, entity_uri=geo_entity,
            objects=_geo_frame(f, s, LONDON[0]))
    else:
        r = await vg_client.kgentities.create_entity_frames(
            space_id=test_space, graph_id=test_graph, entity_uri=geo_entity,
            objects=_geo_frame(f, s, LONDON[0]), operation_mode="upsert")
    assert r.is_success, r.error_message

    lat = await _slot_latitude(pg_conn, test_space, test_graph, s, LONDON[1])
    assert lat == pytest.approx(LONDON[1]), (
        f"after an entity-frame {mode} the slot's geo row is at latitude {lat}, "
        f"not {LONDON[1]}: the rewrite was not re-synced")


async def test_control_entity_create_syncs_the_same_slot(
        vg_client, test_space, test_graph, pg_conn, geo_entity):
    # CONTROL. `POST /kgentities` (entity + its frame graph) already schedules
    # auto-sync, so this passes before and after the fix. If it fails, the geo
    # mechanism is broken and the entity-frame failures above prove nothing.
    # (The geo handler keys a slot's row through its OWNING ENTITY, reached by
    # Edge_hasKGSlot and Edge_hasEntityKGFrame, so a standalone frame, which has
    # no entity, is not a valid control.)
    from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
    e = KGEntity()
    e.URI = _u("entity")
    e.name = "Auto-sync Control Entity"
    f, s = _u("frame"), _u("slot")
    ef = Edge_hasEntityKGFrame()
    ef.URI = f"{f}#entity_edge"
    ef.edgeSource = str(e.URI)
    ef.edgeDestination = f
    r = await vg_client.kgentities.create_kgentities(
        space_id=test_space, graph_id=test_graph,
        objects=[e, ef] + _geo_frame(f, s, NYC[0]))
    assert r.is_success, r.error_message
    lat = await _slot_latitude(pg_conn, test_space, test_graph, s, NYC[1])
    assert lat == pytest.approx(NYC[1]), f"the control produced no geo row ({lat})"
