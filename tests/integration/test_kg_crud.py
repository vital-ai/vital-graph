"""Integration tests: KG Entity CRUD lifecycle.

Verifies Create, Read, Update, Delete operations on KG entities,
frames, and slots via the SparqlSQLBackendAdapter.

Requires PostgreSQL + Jena sidecar.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from .conftest import skip_no_infra, TEST_SPACE_PREFIX

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]


# ---------------------------------------------------------------------------
# Module-scoped KG test space
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def kg_space(space_impl):
    """Create an ephemeral space for KG CRUD tests."""
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

    space_id = f"{TEST_SPACE_PREFIX}kgcrud_{uuid.uuid4().hex[:8]}"
    async with space_impl.db_impl.connection_pool.acquire() as conn:
        await SparqlSQLSchema.create_space(conn, space_id)

    yield space_id

    async with space_impl.db_impl.connection_pool.acquire() as conn:
        await SparqlSQLSchema.drop_space(conn, space_id)


@pytest.fixture
def graph_uri(kg_space):
    """Unique graph URI per test."""
    return f"http://example.org/graph/{kg_space}/{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Entity lifecycle: Create → Read → Update → Delete
# ---------------------------------------------------------------------------

class TestEntityLifecycle:
    """Full CRUD lifecycle for a KGEntity."""

    async def test_create_entity(self, backend_adapter, kg_space, graph_uri):
        """Store a KGEntity and verify it exists."""
        from ai_haley_kg_domain.model.KGEntity import KGEntity

        entity = KGEntity()
        entity.URI = f"http://example.org/entity/{uuid.uuid4()}"
        entity.name = "Integration Test Entity"

        result = await backend_adapter.store_objects(kg_space, graph_uri, [entity])
        assert result.success, f"store_objects failed: {result.message}"
        assert result.data["stored_count"] == 1
        assert result.data["quad_count"] >= 3  # type + vitaltype + URIProp + name

    async def test_entity_exists_after_create(self, backend_adapter, kg_space, graph_uri):
        """object_exists returns True for stored entity."""
        from ai_haley_kg_domain.model.KGEntity import KGEntity

        entity = KGEntity()
        entity.URI = f"http://example.org/entity/{uuid.uuid4()}"
        entity.name = "Exists Check"

        await backend_adapter.store_objects(kg_space, graph_uri, [entity])
        exists = await backend_adapter.object_exists(kg_space, graph_uri, entity.URI)
        assert exists is True

    async def test_get_entity(self, backend_adapter, kg_space, graph_uri):
        """get_entity retrieves stored entity with correct properties."""
        from ai_haley_kg_domain.model.KGEntity import KGEntity

        entity = KGEntity()
        entity.URI = f"http://example.org/entity/{uuid.uuid4()}"
        entity.name = "Retrievable Entity"

        await backend_adapter.store_objects(kg_space, graph_uri, [entity])
        result = await backend_adapter.get_entity(kg_space, graph_uri, entity.URI)

        assert result.success
        assert result.objects is not None
        assert len(result.objects) >= 1

        retrieved = result.objects[0]
        assert retrieved.URI == entity.URI
        assert retrieved.name == "Retrievable Entity"

    async def test_delete_entity(self, backend_adapter, kg_space, graph_uri):
        """delete_object removes entity from the graph."""
        from ai_haley_kg_domain.model.KGEntity import KGEntity

        entity = KGEntity()
        entity.URI = f"http://example.org/entity/{uuid.uuid4()}"
        entity.name = "To Be Deleted"

        await backend_adapter.store_objects(kg_space, graph_uri, [entity])
        assert await backend_adapter.object_exists(kg_space, graph_uri, entity.URI)

        del_result = await backend_adapter.delete_object(kg_space, graph_uri, entity.URI)
        assert del_result.success

        exists = await backend_adapter.object_exists(kg_space, graph_uri, entity.URI)
        assert exists is False

    async def test_delete_nonexistent_entity(self, backend_adapter, kg_space, graph_uri):
        """Deleting a non-existent entity succeeds without error."""
        fake_uri = f"http://example.org/entity/{uuid.uuid4()}"
        result = await backend_adapter.delete_object(kg_space, graph_uri, fake_uri)
        assert result.success


# ---------------------------------------------------------------------------
# Multiple entities
# ---------------------------------------------------------------------------

class TestMultipleEntities:
    """Batch operations with multiple KGEntities."""

    async def test_store_multiple_entities(self, backend_adapter, kg_space, graph_uri):
        """Store 5 entities in a single call."""
        from ai_haley_kg_domain.model.KGEntity import KGEntity

        entities = []
        for i in range(5):
            e = KGEntity()
            e.URI = f"http://example.org/entity/batch_{uuid.uuid4().hex[:8]}"
            e.name = f"Batch Entity {i}"
            entities.append(e)

        result = await backend_adapter.store_objects(kg_space, graph_uri, entities)
        assert result.success
        assert result.data["stored_count"] == 5

        # Verify each exists
        for e in entities:
            exists = await backend_adapter.object_exists(kg_space, graph_uri, e.URI)
            assert exists, f"Entity {e.URI} not found after batch store"

    async def test_delete_one_leaves_others(self, backend_adapter, kg_space, graph_uri):
        """Deleting one entity doesn't affect other entities in same graph."""
        from ai_haley_kg_domain.model.KGEntity import KGEntity

        e1 = KGEntity()
        e1.URI = f"http://example.org/entity/keep_{uuid.uuid4().hex[:8]}"
        e1.name = "Keep Me"

        e2 = KGEntity()
        e2.URI = f"http://example.org/entity/del_{uuid.uuid4().hex[:8]}"
        e2.name = "Delete Me"

        await backend_adapter.store_objects(kg_space, graph_uri, [e1, e2])

        # Delete e2
        await backend_adapter.delete_object(kg_space, graph_uri, e2.URI)

        # e1 still exists
        assert await backend_adapter.object_exists(kg_space, graph_uri, e1.URI)
        # e2 is gone
        assert not await backend_adapter.object_exists(kg_space, graph_uri, e2.URI)


# ---------------------------------------------------------------------------
# Frame lifecycle
# ---------------------------------------------------------------------------

class TestFrameLifecycle:
    """CRUD operations on KGFrame objects."""

    async def test_store_and_retrieve_frame(self, backend_adapter, kg_space, graph_uri):
        """Store a KGFrame and retrieve it."""
        from ai_haley_kg_domain.model.KGFrame import KGFrame

        frame = KGFrame()
        frame.URI = f"http://example.org/frame/{uuid.uuid4()}"
        frame.name = "Test Frame"

        result = await backend_adapter.store_objects(kg_space, graph_uri, [frame])
        assert result.success

        exists = await backend_adapter.object_exists(kg_space, graph_uri, frame.URI)
        assert exists

    async def test_delete_frame(self, backend_adapter, kg_space, graph_uri):
        """Delete a KGFrame."""
        from ai_haley_kg_domain.model.KGFrame import KGFrame

        frame = KGFrame()
        frame.URI = f"http://example.org/frame/{uuid.uuid4()}"
        frame.name = "Deletable Frame"

        await backend_adapter.store_objects(kg_space, graph_uri, [frame])
        await backend_adapter.delete_object(kg_space, graph_uri, frame.URI)

        exists = await backend_adapter.object_exists(kg_space, graph_uri, frame.URI)
        assert exists is False


# ---------------------------------------------------------------------------
# Slot lifecycle
# ---------------------------------------------------------------------------

class TestSlotLifecycle:
    """CRUD operations on KGSlot objects."""

    async def test_store_and_retrieve_slot(self, backend_adapter, kg_space, graph_uri):
        """Store a KGSlot and retrieve it."""
        from ai_haley_kg_domain.model.KGSlot import KGSlot

        slot = KGSlot()
        slot.URI = f"http://example.org/slot/{uuid.uuid4()}"
        slot.name = "Test Slot"

        result = await backend_adapter.store_objects(kg_space, graph_uri, [slot])
        assert result.success

        exists = await backend_adapter.object_exists(kg_space, graph_uri, slot.URI)
        assert exists

    async def test_delete_slot(self, backend_adapter, kg_space, graph_uri):
        """Delete a KGSlot."""
        from ai_haley_kg_domain.model.KGSlot import KGSlot

        slot = KGSlot()
        slot.URI = f"http://example.org/slot/{uuid.uuid4()}"
        slot.name = "Deletable Slot"

        await backend_adapter.store_objects(kg_space, graph_uri, [slot])
        await backend_adapter.delete_object(kg_space, graph_uri, slot.URI)

        exists = await backend_adapter.object_exists(kg_space, graph_uri, slot.URI)
        assert exists is False


# ---------------------------------------------------------------------------
# Entity graph (entity + frames + slots + edges)
# ---------------------------------------------------------------------------

class TestEntityGraph:
    """Full entity graph with frames, slots, and edges."""

    async def test_store_entity_with_frame_and_slot(
        self, backend_adapter, kg_space, graph_uri,
    ):
        """Store an entity graph: entity + edge + frame + edge + slot."""
        from ai_haley_kg_domain.model.KGEntity import KGEntity
        from ai_haley_kg_domain.model.KGFrame import KGFrame
        from ai_haley_kg_domain.model.KGSlot import KGSlot
        from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame
        from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot

        entity = KGEntity()
        entity.URI = f"http://example.org/entity/{uuid.uuid4()}"
        entity.name = "Graph Entity"

        frame = KGFrame()
        frame.URI = f"http://example.org/frame/{uuid.uuid4()}"
        frame.name = "Graph Frame"

        slot = KGSlot()
        slot.URI = f"http://example.org/slot/{uuid.uuid4()}"
        slot.name = "Graph Slot"

        edge_ef = Edge_hasKGFrame()
        edge_ef.URI = f"http://example.org/edge/{uuid.uuid4()}"
        edge_ef.edgeSource = entity.URI
        edge_ef.edgeDestination = frame.URI

        edge_fs = Edge_hasKGSlot()
        edge_fs.URI = f"http://example.org/edge/{uuid.uuid4()}"
        edge_fs.edgeSource = frame.URI
        edge_fs.edgeDestination = slot.URI

        objects = [entity, frame, slot, edge_ef, edge_fs]
        result = await backend_adapter.store_objects(kg_space, graph_uri, objects)
        assert result.success
        assert result.data["stored_count"] == 5

        # All objects exist
        for obj in objects:
            exists = await backend_adapter.object_exists(kg_space, graph_uri, obj.URI)
            assert exists, f"Object {obj.URI} not found"

    async def test_get_entity_graph(self, backend_adapter, kg_space, graph_uri):
        """get_entity_graph retrieves entity and its connected graph."""
        from ai_haley_kg_domain.model.KGEntity import KGEntity
        from ai_haley_kg_domain.model.KGFrame import KGFrame
        from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame

        entity = KGEntity()
        entity.URI = f"http://example.org/entity/{uuid.uuid4()}"
        entity.name = "Full Graph Entity"

        frame = KGFrame()
        frame.URI = f"http://example.org/frame/{uuid.uuid4()}"
        frame.name = "Full Graph Frame"

        edge = Edge_hasKGFrame()
        edge.URI = f"http://example.org/edge/{uuid.uuid4()}"
        edge.edgeSource = entity.URI
        edge.edgeDestination = frame.URI

        await backend_adapter.store_objects(
            kg_space, graph_uri, [entity, frame, edge]
        )

        result = await backend_adapter.get_entity_graph(
            kg_space, graph_uri, entity.URI
        )
        assert result.success
        assert result.objects is not None
        # Should contain entity + frame + edge (at minimum the entity)
        assert len(result.objects) >= 1

        uris = {obj.URI for obj in result.objects}
        assert entity.URI in uris


# ---------------------------------------------------------------------------
# Graph isolation
# ---------------------------------------------------------------------------

class TestKGGraphIsolation:
    """Entities in different graphs are isolated."""

    async def test_entity_not_visible_in_other_graph(
        self, backend_adapter, kg_space,
    ):
        """Entity stored in graph A is not visible in graph B."""
        from ai_haley_kg_domain.model.KGEntity import KGEntity

        graph_a = f"http://example.org/graph/iso_a_{uuid.uuid4().hex[:8]}"
        graph_b = f"http://example.org/graph/iso_b_{uuid.uuid4().hex[:8]}"

        entity = KGEntity()
        entity.URI = f"http://example.org/entity/{uuid.uuid4()}"
        entity.name = "Isolated Entity"

        await backend_adapter.store_objects(kg_space, graph_a, [entity])

        # Visible in graph_a
        assert await backend_adapter.object_exists(kg_space, graph_a, entity.URI)
        # Not visible in graph_b
        assert not await backend_adapter.object_exists(kg_space, graph_b, entity.URI)
