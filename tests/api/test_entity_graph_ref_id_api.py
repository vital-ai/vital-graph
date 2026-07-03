"""API tests: Entity Graph Reference ID regression via VitalGraphClient.

Regression test for include_entity_graph + reference_id duplication bug.
When an entity has hasKGGraphURI pointing to itself, the UNION query used
to return triples twice, causing multi-valued properties to accumulate.
Based on test_scripts/vitalgraph_client_test/sparql_sql/case_entity_graph_ref_id.py
"""

from __future__ import annotations

import uuid

import pytest

from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

NS = "http://example.org/apitest/refid/"
REF_ID = "REFID-TEST-001"


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _make_entity_with_frame():
    """Create entity with reference ID, one frame, and two slots."""
    entity_uri = f"{NS}entity_{_uid()}"
    frame_uri = f"{NS}frame_{_uid()}"
    slot1_uri = f"{NS}slot1_{_uid()}"
    slot2_uri = f"{NS}slot2_{_uid()}"

    entity = KGEntity()
    entity.URI = entity_uri
    entity.name = "RefID Test Entity"
    entity.referenceIdentifier = REF_ID

    frame = KGFrame()
    frame.URI = frame_uri
    frame.name = "Test Frame"

    slot1 = KGTextSlot()
    slot1.URI = slot1_uri
    slot1.name = "Slot Alpha"
    slot1.textSlotValue = "alpha_value"

    slot2 = KGTextSlot()
    slot2.URI = slot2_uri
    slot2.name = "Slot Beta"
    slot2.textSlotValue = "beta_value"

    edge_ef = Edge_hasEntityKGFrame()
    edge_ef.URI = f"{NS}edge_ef_{_uid()}"
    edge_ef.edgeSource = entity_uri
    edge_ef.edgeDestination = frame_uri

    edge_fs1 = Edge_hasKGSlot()
    edge_fs1.URI = f"{NS}edge_fs1_{_uid()}"
    edge_fs1.edgeSource = frame_uri
    edge_fs1.edgeDestination = slot1_uri

    edge_fs2 = Edge_hasKGSlot()
    edge_fs2.URI = f"{NS}edge_fs2_{_uid()}"
    edge_fs2.edgeSource = frame_uri
    edge_fs2.edgeDestination = slot2_uri

    return {
        "entity_uri": entity_uri,
        "objects": [entity, frame, slot1, slot2, edge_ef, edge_fs1, edge_fs2],
    }


def _extract_ref_id(objects) -> str:
    """Extract referenceIdentifier from KGEntity in object list."""
    for obj in objects:
        if isinstance(obj, KGEntity) and hasattr(obj, 'referenceIdentifier'):
            val = obj.referenceIdentifier
            if val is not None:
                return str(val)
    return ""


class TestEntityGraphRefId:
    """Regression: include_entity_graph must not duplicate multi-valued properties."""

    async def test_create_entity_with_frame(self, vg_client, test_space, test_graph):
        """Create entity + frame + slots + edges."""
        data = _make_entity_with_frame()
        cr = await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=data["objects"])
        assert cr.is_success
        assert cr.created_count >= 1

    async def test_get_by_ref_id_no_graph(self, vg_client, test_space, test_graph):
        """Get by reference_id without entity graph — clean ref ID."""
        data = _make_entity_with_frame()
        await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=data["objects"])

        resp = await vg_client.kgentities.get_kgentity(
            space_id=test_space, graph_id=test_graph,
            reference_id=REF_ID, include_entity_graph=False)
        assert resp.is_success
        assert resp.objects is not None
        got_ref = _extract_ref_id(resp.objects)
        assert got_ref == REF_ID, f"expected {REF_ID!r}, got {got_ref!r}"

    async def test_get_by_ref_id_with_graph(self, vg_client, test_space, test_graph):
        """Get by reference_id WITH entity graph — must not duplicate ref ID."""
        data = _make_entity_with_frame()
        await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=data["objects"])

        resp = await vg_client.kgentities.get_kgentity(
            space_id=test_space, graph_id=test_graph,
            reference_id=REF_ID, include_entity_graph=True)
        assert resp.is_success
        assert resp.objects is not None
        eg = resp.objects
        obj_list = eg.objects if hasattr(eg, 'objects') else []
        got_ref = _extract_ref_id(obj_list)
        assert got_ref == REF_ID, f"DUPLICATION BUG: expected {REF_ID!r}, got {got_ref!r}"

    async def test_get_by_uri_with_graph(self, vg_client, test_space, test_graph):
        """Get by URI WITH entity graph — must not duplicate ref ID."""
        data = _make_entity_with_frame()
        await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=data["objects"])
        entity_uri = data["entity_uri"]

        resp = await vg_client.kgentities.get_kgentity(
            space_id=test_space, graph_id=test_graph,
            uri=entity_uri, include_entity_graph=True)
        assert resp.is_success
        assert resp.objects is not None
        eg = resp.objects
        obj_list = eg.objects if hasattr(eg, 'objects') else []
        got_ref = _extract_ref_id(obj_list)
        assert got_ref == REF_ID, f"DUPLICATION BUG: expected {REF_ID!r}, got {got_ref!r}"

    async def test_entity_graph_object_count(self, vg_client, test_space, test_graph):
        """Entity graph should have 7 objects (entity + frame + 2 slots + 3 edges)."""
        data = _make_entity_with_frame()
        await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=data["objects"])
        entity_uri = data["entity_uri"]

        resp = await vg_client.kgentities.get_kgentity(
            space_id=test_space, graph_id=test_graph,
            uri=entity_uri, include_entity_graph=True)
        assert resp.is_success
        eg = resp.objects
        obj_list = eg.objects if hasattr(eg, 'objects') else []
        assert len(obj_list) == 7, f"expected 7 objects, got {len(obj_list)}"
