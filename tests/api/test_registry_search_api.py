"""API tests: Registry Search endpoints via VitalGraphClient.

Tests entity registry semantic/geo search and agent registry search.
These are smoke tests that verify endpoints respond without error.
Results depend on pre-loaded data; we assert structure, not specific records.
Based on test_scripts/vitalgraph_client_test/sparql_sql/case_registry_search_verify.py
"""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]


class TestEntityRegistrySearch:
    """Entity registry search: semantic, geo, identifier."""

    async def test_entity_semantic_search(self, vg_client):
        """Semantic search returns success with results containing scored entities."""
        resp = await vg_client.entity_registry.search_entity(
            q="corporation business", min_certainty=0.3, limit=10)
        assert resp.success is True
        assert isinstance(resp.results, list)
        if resp.results:
            top = resp.results[0]
            assert top.score > 0, f"Top result score should be > 0, got {top.score}"
            assert top.entity_id, "Top result must have an entity_id"
            assert top.primary_name, "Top result must have a primary_name"

    async def test_entity_search_type_filter(self, vg_client):
        """Search with type_key filter returns success."""
        resp = await vg_client.entity_registry.search_entity(
            q="consulting", type_key="person", min_certainty=0.3, limit=10)
        assert resp.success is True
        # All results should match filter if any returned
        if resp.results:
            assert all(r.type_key == "person" for r in resp.results)

    async def test_entity_geo_search(self, vg_client):
        """Geo-only search (near SF) returns success with results list."""
        resp = await vg_client.entity_registry.search_entity(
            latitude=37.79, longitude=-122.40, radius_km=50, limit=10)
        assert resp.success is True
        assert isinstance(resp.results, list)
        assert len(resp.results) <= 10

    async def test_entity_combined_semantic_geo(self, vg_client):
        """Combined semantic + geo search returns success with bounded results."""
        resp = await vg_client.entity_registry.search_entity(
            q="corporation", latitude=37.79, longitude=-122.40,
            radius_km=50, min_certainty=0.3, limit=10)
        assert resp.success is True
        assert isinstance(resp.results, list)
        assert len(resp.results) <= 10

    async def test_entity_identifier_search(self, vg_client):
        """Identifier search for unknown ID returns success with 0 results."""
        resp = await vg_client.entity_registry.search_entity(
            identifier_value="nonexistent-id-xyz-000", limit=5)
        assert resp.success is True
        assert len(resp.results) == 0


class TestLocationRegistrySearch:
    """Location registry search: geo, semantic, address."""

    async def test_location_geo_search(self, vg_client):
        """Location geo search (near SF) returns success with results list."""
        resp = await vg_client.entity_registry.search_location(
            latitude=37.79, longitude=-122.40, radius_km=50, limit=10)
        assert resp.success is True
        assert isinstance(resp.results, list)
        assert len(resp.results) <= 10

    async def test_location_semantic_search(self, vg_client):
        """Location search with semantic query returns success with bounded results."""
        resp = await vg_client.entity_registry.search_location(
            latitude=37.79, longitude=-122.40, radius_km=100,
            q="office headquarters", min_certainty=0.3, limit=10)
        assert resp.success is True
        assert isinstance(resp.results, list)
        assert len(resp.results) <= 10

    async def test_location_address_search(self, vg_client):
        """Location search with address keyword returns success with bounded results."""
        resp = await vg_client.entity_registry.search_location(
            latitude=37.79, longitude=-122.40, radius_km=100,
            address="Market Street", limit=10)
        assert resp.success is True
        assert isinstance(resp.results, list)
        assert len(resp.results) <= 10


class TestAgentRegistrySearch:
    """Agent registry search."""

    async def test_agent_search(self, vg_client):
        """Agent text search returns agents list and consistent total_count."""
        resp = await vg_client.agent_registry.search_agents(query="bot")
        assert resp.total_count >= 0
        assert isinstance(resp.agents, list)
        assert resp.total_count >= len(resp.agents)

    async def test_agent_search_type_filter(self, vg_client):
        """Agent search with type filter returns consistent response."""
        resp = await vg_client.agent_registry.search_agents(
            query="", type_key="chatbot")
        assert resp.total_count >= 0
        assert isinstance(resp.agents, list)
        assert resp.total_count >= len(resp.agents)
