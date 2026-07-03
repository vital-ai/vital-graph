"""API tests: KGEntity CRUD lifecycle via VitalGraphClient.

Tests create, list, get, update, delete, and batch delete KGEntities.
Based on test_scripts/vitalgraph_client_test/sparql_sql/case_kgentities_crud.py
"""

from __future__ import annotations

import uuid

import pytest

from ai_haley_kg_domain.model.KGEntity import KGEntity

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

NS = "http://example.org/apitest/entity/"


def _make_entity(name: str) -> KGEntity:
    """Create a KGEntity with a unique URI."""
    e = KGEntity()
    e.URI = f"{NS}{uuid.uuid4().hex[:12]}"
    e.name = name
    return e


# ---------------------------------------------------------------------------
# Full CRUD lifecycle (mirrors case_kgentities_crud.py)
# ---------------------------------------------------------------------------

class TestKGEntitiesCrud:
    """KGEntity lifecycle: create → list → get → update → delete → batch delete."""

    async def test_create_entities(self, vg_client, test_space, test_graph):
        """Create 3 KGEntities individually."""
        total_created = 0
        for name in ("Alpha Entity", "Beta Entity", "Gamma Entity"):
            e = _make_entity(name)
            cr = await vg_client.kgentities.create_kgentities(
                space_id=test_space, graph_id=test_graph, objects=[e]
            )
            assert cr.is_success, f"create '{name}' failed: {cr.error_message}"
            total_created += cr.created_count
        assert total_created == 3

    async def test_list_entities(self, vg_client, test_space, test_graph):
        """List returns at least the entities created above."""
        lr = await vg_client.kgentities.list_kgentities(
            space_id=test_space, graph_id=test_graph, page_size=50
        )
        assert lr.is_success
        assert len(lr.objects) >= 3

    async def test_get_entity_by_uri(self, vg_client, test_space, test_graph):
        """Create then get a specific entity by URI."""
        e = _make_entity("GetMe Entity")
        await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=[e]
        )

        gr = await vg_client.kgentities.get_kgentity(
            space_id=test_space, graph_id=test_graph, uri=e.URI
        )
        assert gr.is_success
        assert gr.objects is not None and len(gr.objects) >= 1
        got_name = None
        for obj in gr.objects:
            if hasattr(obj, "name") and obj.name:
                got_name = str(obj.name)
                break
        assert got_name == "GetMe Entity"

    async def test_update_entity(self, vg_client, test_space, test_graph):
        """Create, update name, verify updated name is persisted."""
        e = _make_entity("Before Update")
        await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=[e]
        )

        # Update
        e.name = "After Update"
        ur = await vg_client.kgentities.update_kgentities(
            space_id=test_space, graph_id=test_graph, objects=[e]
        )
        assert ur.is_success, f"update failed: {ur.error_message}"

        # Verify
        gr = await vg_client.kgentities.get_kgentity(
            space_id=test_space, graph_id=test_graph, uri=e.URI
        )
        assert gr.is_success
        got_name = None
        for obj in gr.objects:
            if hasattr(obj, "name") and obj.name:
                got_name = str(obj.name)
                break
        assert got_name == "After Update"

    async def test_delete_entity(self, vg_client, test_space, test_graph):
        """Create then delete a single entity, verify it's gone."""
        e = _make_entity("DeleteMe Entity")
        await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=[e]
        )

        dr = await vg_client.kgentities.delete_kgentity(
            space_id=test_space, graph_id=test_graph, uri=str(e.URI)
        )
        assert dr.is_success

        # Verify gone
        gr = await vg_client.kgentities.get_kgentity(
            space_id=test_space, graph_id=test_graph, uri=e.URI
        )
        assert not gr.is_success or not gr.objects or len(gr.objects) == 0

    async def test_batch_delete(self, vg_client, test_space, test_graph):
        """Create 2 entities then batch-delete them."""
        e1 = _make_entity("Batch1")
        e2 = _make_entity("Batch2")
        await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=[e1]
        )
        await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=[e2]
        )

        dr = await vg_client.kgentities.delete_kgentities_batch(
            space_id=test_space, graph_id=test_graph,
            uri_list=[str(e1.URI), str(e2.URI)]
        )
        assert dr.is_success


# ---------------------------------------------------------------------------
# Entity count endpoints
# ---------------------------------------------------------------------------

class TestEntityCount:
    """GET /kgentities/count and POST /kgentities/counts (batch)."""

    async def test_count_entities_empty_graph(self, vg_client, test_space, test_graph):
        """Count in fresh graph should be zero or a non-negative int."""
        count = await vg_client.kgentities.count_kgentities(
            space_id=test_space, graph_id=test_graph
        )
        assert isinstance(count, int)
        assert count >= 0

    async def test_count_entities_after_create(self, vg_client, test_space, test_graph):
        """Create entities, then count should reflect them."""
        e1 = _make_entity("Count1")
        e2 = _make_entity("Count2")
        await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=[e1, e2]
        )

        count = await vg_client.kgentities.count_kgentities(
            space_id=test_space, graph_id=test_graph
        )
        assert count >= 2

        # Cleanup
        await vg_client.kgentities.delete_kgentities_batch(
            space_id=test_space, graph_id=test_graph,
            uri_list=[str(e1.URI), str(e2.URI)]
        )

    async def test_batch_count_entities(self, vg_client, test_space, test_graph):
        """Batch count with multiple filter sets."""
        e = _make_entity("BatchCount")
        await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=[e]
        )

        results = await vg_client.kgentities.batch_count_kgentities(
            space_id=test_space,
            graph_id=test_graph,
            count_requests=[
                {"label": "all"},
                {"label": "typed", "entity_type_uri": "http://vital.ai/ontology/haley-ai-kg#KGEntity"},
            ]
        )
        assert isinstance(results, list)
        assert len(results) == 2
        for r in results:
            assert "label" in r
            assert "count" in r
            assert isinstance(r["count"], int)

        # Cleanup
        await vg_client.kgentities.delete_kgentity(
            space_id=test_space, graph_id=test_graph, uri=str(e.URI)
        )
