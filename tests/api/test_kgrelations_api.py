"""API tests: KGRelations CRUD lifecycle via VitalGraphClient.

Tests create, list, get, update, delete KGRelations.
Relations are edges connecting KGEntities in the knowledge graph.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.Edge_hasKGRelation import Edge_hasKGRelation

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

NS = "http://example.org/apitest/relation/"
ENT_NS = "http://example.org/apitest/relent/"
REL_TYPE = "http://vital.ai/ontology/haley-ai-kg#TestRelationType"


def _make_entity(name: str) -> KGEntity:
    """Create a KGEntity with a unique URI."""
    e = KGEntity()
    e.URI = f"{ENT_NS}{uuid.uuid4().hex[:12]}"
    e.name = name
    return e


def _make_relation(source_uri: str, dest_uri: str, rel_type: str = REL_TYPE) -> Edge_hasKGRelation:
    """Create an Edge_hasKGRelation linking two entities."""
    r = Edge_hasKGRelation()
    r.URI = f"{NS}{uuid.uuid4().hex[:12]}"
    r.edgeSource = source_uri
    r.edgeDestination = dest_uri
    r.kGRelationType = rel_type
    return r


# ---------------------------------------------------------------------------
# Full CRUD lifecycle
# ---------------------------------------------------------------------------

class TestKGRelationsCrud:
    """KGRelation lifecycle: create entities → create relation → list → get → delete."""

    @pytest_asyncio.fixture(autouse=True, loop_scope="session")
    async def _setup_entities(self, vg_client, test_space, test_graph):
        """Create two source entities used by all relation tests."""
        self.ent_a = _make_entity("RelSource")
        self.ent_b = _make_entity("RelDest")
        self.ent_c = _make_entity("RelDest2")

        for ent in (self.ent_a, self.ent_b, self.ent_c):
            cr = await vg_client.kgentities.create_kgentities(
                space_id=test_space, graph_id=test_graph, objects=[ent]
            )
            assert cr.is_success, f"Entity create failed: {cr.error_message}"

    async def test_create_relation(self, vg_client, test_space, test_graph):
        """Create a relation between two entities."""
        rel = _make_relation(str(self.ent_a.URI), str(self.ent_b.URI))
        resp = await vg_client.kgrelations.create_relations(
            space_id=test_space, graph_id=test_graph, relations=[rel]
        )
        assert resp.is_success, f"Create failed: {resp.error_message}"
        assert resp.created_count >= 1
        assert len(resp.created_uris) >= 1

    async def test_list_relations(self, vg_client, test_space, test_graph):
        """Create then list relations, verifying at least one is present."""
        rel = _make_relation(str(self.ent_a.URI), str(self.ent_b.URI))
        await vg_client.kgrelations.create_relations(
            space_id=test_space, graph_id=test_graph, relations=[rel]
        )

        resp = await vg_client.kgrelations.list_relations(
            space_id=test_space, graph_id=test_graph
        )
        assert resp.is_success, f"List failed: {resp.error_message}"
        assert len(resp.objects) >= 1

    async def test_list_relations_filter_by_source(self, vg_client, test_space, test_graph):
        """Filter relations by source entity URI."""
        rel = _make_relation(str(self.ent_a.URI), str(self.ent_b.URI))
        await vg_client.kgrelations.create_relations(
            space_id=test_space, graph_id=test_graph, relations=[rel]
        )

        resp = await vg_client.kgrelations.list_relations(
            space_id=test_space, graph_id=test_graph,
            entity_source_uri=str(self.ent_a.URI)
        )
        assert resp.is_success, f"List by source failed: {resp.error_message}"
        # All returned relations should have ent_a as source
        for obj in resp.objects:
            assert str(obj.edgeSource) == str(self.ent_a.URI)

    async def test_get_relation_by_uri(self, vg_client, test_space, test_graph):
        """Get a specific relation by its URI."""
        rel = _make_relation(str(self.ent_a.URI), str(self.ent_b.URI))
        cr = await vg_client.kgrelations.create_relations(
            space_id=test_space, graph_id=test_graph, relations=[rel]
        )
        assert cr.is_success
        created_uri = cr.created_uris[0]

        resp = await vg_client.kgrelations.get_relation(
            space_id=test_space, graph_id=test_graph, relation_uri=created_uri
        )
        assert resp.is_success, f"Get failed: {resp.error_message}"
        assert len(resp.objects) >= 1
        assert str(resp.objects[0].URI) == created_uri

    async def test_delete_relation(self, vg_client, test_space, test_graph):
        """Create then delete a relation and verify it's gone."""
        rel = _make_relation(str(self.ent_a.URI), str(self.ent_c.URI))
        cr = await vg_client.kgrelations.create_relations(
            space_id=test_space, graph_id=test_graph, relations=[rel]
        )
        assert cr.is_success
        created_uri = cr.created_uris[0]

        # Delete
        del_resp = await vg_client.kgrelations.delete_relations(
            space_id=test_space, graph_id=test_graph,
            relation_uris=[created_uri]
        )
        assert del_resp.is_success, f"Delete failed: {del_resp.error_message}"
        assert del_resp.deleted_count >= 1

        # Verify gone
        get_resp = await vg_client.kgrelations.get_relation(
            space_id=test_space, graph_id=test_graph, relation_uri=created_uri
        )
        # Should return empty or failure
        if get_resp.is_success:
            assert len(get_resp.objects) == 0
