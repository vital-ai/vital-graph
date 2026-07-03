"""API tests: Objects CRUD via VitalGraphClient.

Tests create, list, get, update, delete, and batch delete generic objects.
Based on test_scripts/vitalgraph_client_test/sparql_sql/case_objects_crud.py
"""

from __future__ import annotations

import uuid

import pytest

from ai_haley_kg_domain.model.KGEntity import KGEntity

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

NS = "http://example.org/apitest/objects/"


def _make_entity(name: str) -> KGEntity:
    """Create a KGEntity object with a unique URI."""
    e = KGEntity()
    e.URI = f"{NS}{uuid.uuid4().hex[:12]}"
    e.name = name
    e.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#GenericEntity"
    return e


class TestObjectsCrud:
    """Objects lifecycle: create → list → get → update → delete → batch delete."""

    async def test_create_objects(self, vg_client, test_space, test_graph):
        """Create 3 objects."""
        objs = [_make_entity("Alice"), _make_entity("Bob"), _make_entity("Charlie")]
        cr = await vg_client.objects.create_objects(test_space, test_graph, objs)
        assert cr.is_success, f"create failed: {cr.error_message}"
        assert cr.created_count == 3

    async def test_list_objects(self, vg_client, test_space, test_graph):
        """List returns at least 3 objects."""
        lr = await vg_client.objects.list_objects(test_space, test_graph, page_size=50)
        assert lr.is_success
        assert lr.count >= 3

    async def test_get_object_by_uri(self, vg_client, test_space, test_graph):
        """Create then get an object by URI."""
        obj = _make_entity("Gettable")
        await vg_client.objects.create_objects(test_space, test_graph, [obj])

        gr = await vg_client.objects.get_object(test_space, test_graph, str(obj.URI))
        assert gr.is_success
        assert gr.object is not None
        assert str(gr.object.name) == "Gettable"

    async def test_update_object(self, vg_client, test_space, test_graph):
        """Create, update name, verify persisted."""
        obj = _make_entity("BeforeUpdate")
        await vg_client.objects.create_objects(test_space, test_graph, [obj])

        obj.name = "AfterUpdate"
        ur = await vg_client.objects.update_objects(test_space, test_graph, [obj])
        assert ur.is_success, f"update failed: {ur.error_message}"

        gr = await vg_client.objects.get_object(test_space, test_graph, str(obj.URI))
        assert gr.is_success
        assert str(gr.object.name) == "AfterUpdate"

    async def test_delete_object(self, vg_client, test_space, test_graph):
        """Create then delete an object, verify gone."""
        obj = _make_entity("DeleteMe")
        await vg_client.objects.create_objects(test_space, test_graph, [obj])

        dr = await vg_client.objects.delete_object(test_space, test_graph, str(obj.URI))
        assert dr.is_success

        gr = await vg_client.objects.get_object(test_space, test_graph, str(obj.URI))
        assert not gr.is_success or gr.object is None

    async def test_batch_delete_objects(self, vg_client, test_space, test_graph):
        """Create 2 objects then batch-delete them, verify both gone."""
        o1 = _make_entity("Batch1")
        o2 = _make_entity("Batch2")
        await vg_client.objects.create_objects(test_space, test_graph, [o1, o2])

        uri_csv = f"{o1.URI},{o2.URI}"
        dr = await vg_client.objects.delete_objects_batch(test_space, test_graph, uri_csv)
        assert dr.is_success

        # Verify both are gone
        gr1 = await vg_client.objects.get_object(test_space, test_graph, str(o1.URI))
        assert not gr1.is_success or gr1.object is None
        gr2 = await vg_client.objects.get_object(test_space, test_graph, str(o2.URI))
        assert not gr2.is_success or gr2.object is None
