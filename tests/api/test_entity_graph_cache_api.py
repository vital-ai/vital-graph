"""API tests: Entity Graph Cache lifecycle via VitalGraphClient.

Tests in-memory entity graph cache: miss → populate, hit, invalidation on
update/delete, and cache stats endpoint.
Based on test_scripts/vitalgraph_client_test/sparql_sql/case_entity_graph_cache.py
"""

from __future__ import annotations

import uuid

import pytest

from ai_haley_kg_domain.model.KGEntity import KGEntity

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

NS = "http://example.org/apitest/cache/"


def _make_entity(name: str) -> KGEntity:
    e = KGEntity()
    e.URI = f"{NS}{uuid.uuid4().hex[:12]}"
    e.name = name
    return e


class TestEntityGraphCache:
    """Cache lifecycle: miss → hit → invalidate on update → miss → invalidate on delete."""

    async def test_get_entity_graph_cache_miss(self, vg_client, test_space, test_graph):
        """First GET with include_entity_graph=True is a cache miss; verify entity name."""
        entity = _make_entity("Cache Miss Entity")
        cr = await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=[entity])
        assert cr.is_success
        assert cr.created_count == 1

        gr = await vg_client.kgentities.get_kgentity(
            space_id=test_space, graph_id=test_graph,
            uri=str(entity.URI), include_entity_graph=True)
        assert gr.is_success
        assert gr.objects is not None
        # Verify entity name is in the returned entity graph
        eg = gr.objects
        obj_list = eg.objects if hasattr(eg, 'objects') else []
        names = [str(o.name) for o in obj_list if hasattr(o, 'name') and o.name]
        assert "Cache Miss Entity" in names

        # Cleanup
        await vg_client.kgentities.delete_kgentity(
            space_id=test_space, graph_id=test_graph, uri=str(entity.URI))

    async def test_get_entity_graph_cache_hit(self, vg_client, test_space, test_graph):
        """Second GET should be a cache hit (hits counter increases)."""
        entity = _make_entity("Cache Hit Entity")
        cr = await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=[entity])
        assert cr.is_success

        # First GET → populate
        await vg_client.kgentities.get_kgentity(
            space_id=test_space, graph_id=test_graph,
            uri=str(entity.URI), include_entity_graph=True)

        stats_before = await vg_client.cache_stats()
        hits_before = stats_before.get("entity_graph_cache", {}).get("hits", 0)

        # Second GET → should be hit
        gr2 = await vg_client.kgentities.get_kgentity(
            space_id=test_space, graph_id=test_graph,
            uri=str(entity.URI), include_entity_graph=True)
        assert gr2.is_success

        stats_after = await vg_client.cache_stats()
        hits_after = stats_after.get("entity_graph_cache", {}).get("hits", 0)
        assert hits_after > hits_before, f"hits did not increase: {hits_before}→{hits_after}"

        # Cleanup
        await vg_client.kgentities.delete_kgentity(
            space_id=test_space, graph_id=test_graph, uri=str(entity.URI))

    async def test_update_invalidates_cache(self, vg_client, test_space, test_graph):
        """Update entity invalidates cache; next GET returns new name."""
        entity = _make_entity("Before Cache Update")
        cr = await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=[entity])
        assert cr.is_success

        # Populate cache
        await vg_client.kgentities.get_kgentity(
            space_id=test_space, graph_id=test_graph,
            uri=str(entity.URI), include_entity_graph=True)

        # Update
        entity.name = "After Cache Update"
        ur = await vg_client.kgentities.update_kgentities(
            space_id=test_space, graph_id=test_graph, objects=[entity])
        assert ur.is_success

        stats_before = await vg_client.cache_stats()
        misses_before = stats_before.get("entity_graph_cache", {}).get("misses", 0)

        # GET after update → should be miss (cache invalidated)
        gr = await vg_client.kgentities.get_kgentity(
            space_id=test_space, graph_id=test_graph,
            uri=str(entity.URI), include_entity_graph=True)
        assert gr.is_success

        stats_after = await vg_client.cache_stats()
        misses_after = stats_after.get("entity_graph_cache", {}).get("misses", 0)
        assert misses_after > misses_before, f"misses did not increase: {misses_before}→{misses_after}"

        # Verify the returned entity has the NEW name
        eg = gr.objects
        obj_list = eg.objects if hasattr(eg, 'objects') else []
        names = [str(o.name) for o in obj_list if hasattr(o, 'name') and o.name]
        assert "After Cache Update" in names

        # Cleanup
        await vg_client.kgentities.delete_kgentity(
            space_id=test_space, graph_id=test_graph, uri=str(entity.URI))

    async def test_delete_invalidates_cache(self, vg_client, test_space, test_graph):
        """Delete entity invalidates cache entry."""
        entity = _make_entity("Delete Cache Entity")
        cr = await vg_client.kgentities.create_kgentities(
            space_id=test_space, graph_id=test_graph, objects=[entity])
        assert cr.is_success

        # Populate cache
        await vg_client.kgentities.get_kgentity(
            space_id=test_space, graph_id=test_graph,
            uri=str(entity.URI), include_entity_graph=True)

        stats_before = await vg_client.cache_stats()
        inv_before = stats_before.get("entity_graph_cache", {}).get("invalidations", 0)

        # Delete
        dr = await vg_client.kgentities.delete_kgentity(
            space_id=test_space, graph_id=test_graph, uri=str(entity.URI))
        assert dr.is_success

        stats_after = await vg_client.cache_stats()
        inv_after = stats_after.get("entity_graph_cache", {}).get("invalidations", 0)
        assert inv_after > inv_before, f"invalidations did not increase: {inv_before}→{inv_after}"

    async def test_cache_stats_endpoint(self, vg_client):
        """Verify /health/cache returns expected structure."""
        stats = await vg_client.cache_stats()
        assert "entity_graph_cache" in stats
        cache = stats["entity_graph_cache"]
        assert "hits" in cache
        assert "misses" in cache
