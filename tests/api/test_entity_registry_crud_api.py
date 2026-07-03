"""API tests: Entity Registry CRUD via VitalGraphClient.

Tests the full entity registry CRUD surface:
  - Entity CRUD: create, get, list, update, delete
  - Identifiers: add, list, lookup, remove
  - Aliases: add, list, remove
  - Categories: create, assign, list by entity, list entities by category, remove
  - Locations: create location type, add location, list, update, remove

The entity registry is GLOBAL (not space-scoped). All test data uses a
``regtest_<uuid>`` prefix and is cleaned up in fixture finalizers.

Search endpoints are covered by test_registry_search_api.py.
"""

from __future__ import annotations

import uuid
from typing import List

import pytest

from vitalgraph.model.entity_registry_model import (
    EntityCreateRequest,
    EntityUpdateRequest,
    IdentifierCreateRequest,
    AliasCreateRequest,
    CategoryCreateRequest,
    EntityCategoryRequest,
    LocationTypeCreateRequest,
    LocationCreateRequest,
    LocationUpdateRequest,
)

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]


def _uid() -> str:
    return uuid.uuid4().hex[:8]


PREFIX = f"regtest_{_uid()}"


# ---------------------------------------------------------------------------
# Entity CRUD
# ---------------------------------------------------------------------------

class TestEntityCrud:
    """Entity create → get → list → update → delete lifecycle."""

    async def test_create_entity(self, vg_client):
        """Create an entity and verify the response."""
        req = EntityCreateRequest(
            type_key="business",
            primary_name=f"{PREFIX}_create_entity",
            description="Test entity for CRUD",
            country="US",
        )
        resp = await vg_client.entity_registry.create_entity(req)
        assert resp.success is True
        assert resp.entity_id
        assert resp.entity.primary_name == f"{PREFIX}_create_entity"
        # Store for cleanup
        TestEntityCrud._created_id = resp.entity_id

    async def test_get_entity(self, vg_client):
        """Get the created entity by ID."""
        entity_id = getattr(TestEntityCrud, "_created_id", None)
        assert entity_id, "test_create_entity must run first"

        resp = await vg_client.entity_registry.get_entity(entity_id)
        assert resp.entity_id == entity_id
        assert resp.primary_name == f"{PREFIX}_create_entity"
        assert resp.type_key == "business"
        assert resp.country == "US"

    async def test_list_entities(self, vg_client):
        """List entities and verify our entity appears."""
        resp = await vg_client.entity_registry.search_entities(
            query=PREFIX, page=1, page_size=50,
        )
        assert resp.success is True
        found_ids = [e.entity_id for e in resp.entities]
        assert TestEntityCrud._created_id in found_ids

    async def test_update_entity(self, vg_client):
        """Update entity name and verify."""
        entity_id = TestEntityCrud._created_id
        req = EntityUpdateRequest(
            primary_name=f"{PREFIX}_updated_entity",
            description="Updated description",
        )
        resp = await vg_client.entity_registry.update_entity(entity_id, req)
        assert resp.primary_name == f"{PREFIX}_updated_entity"
        assert resp.description == "Updated description"

    async def test_delete_entity(self, vg_client):
        """Delete entity and verify it's gone from listing."""
        entity_id = TestEntityCrud._created_id
        result = await vg_client.entity_registry.delete_entity(entity_id)
        assert result.get("success") is True or result.get("deleted") is True

        # Verify removed from search results
        resp = await vg_client.entity_registry.search_entities(
            query=f"{PREFIX}_updated_entity", page=1, page_size=50,
        )
        found_ids = [e.entity_id for e in resp.entities]
        assert entity_id not in found_ids

    async def test_create_for_subsequent_tests(self, vg_client):
        """Create a fresh entity for identifier/alias/category/location tests."""
        req = EntityCreateRequest(
            type_key="business",
            primary_name=f"{PREFIX}_shared_entity",
            description="Shared entity for sub-resource tests",
        )
        resp = await vg_client.entity_registry.create_entity(req)
        assert resp.success is True
        TestEntityCrud._shared_id = resp.entity_id


# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------

class TestIdentifiers:
    """Add, list, lookup, remove identifiers on an entity."""

    async def test_add_identifier(self, vg_client):
        """Add an identifier to the shared entity."""
        entity_id = getattr(TestEntityCrud, "_shared_id", None)
        assert entity_id, "TestEntityCrud.test_create_for_subsequent_tests must run first"

        req = IdentifierCreateRequest(
            identifier_namespace="DUNS",
            identifier_value=f"DUNS-{_uid()}",
            is_primary=True,
        )
        resp = await vg_client.entity_registry.add_identifier(entity_id, req)
        assert resp.entity_id == entity_id
        assert resp.identifier_namespace == "DUNS"
        TestIdentifiers._id = resp.identifier_id
        TestIdentifiers._value = req.identifier_value

    async def test_list_identifiers(self, vg_client):
        """List identifiers for the shared entity."""
        entity_id = TestEntityCrud._shared_id
        ids = await vg_client.entity_registry.list_identifiers(entity_id)
        assert isinstance(ids, list)
        assert any(i.identifier_id == TestIdentifiers._id for i in ids)

    async def test_lookup_by_identifier(self, vg_client):
        """Lookup entity by namespace + value."""
        results = await vg_client.entity_registry.lookup_by_identifier(
            namespace="DUNS", value=TestIdentifiers._value,
        )
        assert isinstance(results, list)
        assert any(e.entity_id == TestEntityCrud._shared_id for e in results)

    async def test_remove_identifier(self, vg_client):
        """Remove the identifier and verify it's gone."""
        result = await vg_client.entity_registry.remove_identifier(TestIdentifiers._id)
        assert result.get("success") is True or result.get("retracted") is True

        ids = await vg_client.entity_registry.list_identifiers(TestEntityCrud._shared_id)
        assert not any(i.identifier_id == TestIdentifiers._id for i in ids)


# ---------------------------------------------------------------------------
# Aliases
# ---------------------------------------------------------------------------

class TestAliases:
    """Add, list, remove aliases on an entity."""

    async def test_add_alias(self, vg_client):
        """Add an alias to the shared entity."""
        entity_id = TestEntityCrud._shared_id
        req = AliasCreateRequest(
            alias_name=f"{PREFIX}_alias",
            alias_type="aka",
            is_primary=False,
        )
        resp = await vg_client.entity_registry.add_alias(entity_id, req)
        assert resp.entity_id == entity_id
        assert resp.alias_name == f"{PREFIX}_alias"
        TestAliases._id = resp.alias_id

    async def test_list_aliases(self, vg_client):
        """List aliases for the shared entity."""
        aliases = await vg_client.entity_registry.list_aliases(TestEntityCrud._shared_id)
        assert isinstance(aliases, list)
        assert any(a.alias_id == TestAliases._id for a in aliases)

    async def test_remove_alias(self, vg_client):
        """Remove alias and verify it's gone."""
        result = await vg_client.entity_registry.remove_alias(TestAliases._id)
        assert result.get("success") is True or result.get("retracted") is True

        aliases = await vg_client.entity_registry.list_aliases(TestEntityCrud._shared_id)
        assert not any(a.alias_id == TestAliases._id for a in aliases)


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

class TestCategories:
    """Create category, assign to entity, list, remove."""

    async def test_create_category(self, vg_client):
        """Create a new category."""
        req = CategoryCreateRequest(
            category_key=f"{PREFIX}_cat",
            category_label=f"Test Category {PREFIX}",
            category_description="Category for testing",
        )
        resp = await vg_client.entity_registry.create_category(req)
        assert resp.category_key == f"{PREFIX}_cat"
        TestCategories._key = resp.category_key

    async def test_list_categories(self, vg_client):
        """List all categories and verify ours exists."""
        cats = await vg_client.entity_registry.list_categories()
        assert isinstance(cats, list)
        assert any(c.category_key == TestCategories._key for c in cats)

    async def test_assign_category_to_entity(self, vg_client):
        """Assign category to the shared entity."""
        entity_id = TestEntityCrud._shared_id
        req = EntityCategoryRequest(category_key=TestCategories._key)
        resp = await vg_client.entity_registry.add_entity_category(entity_id, req)
        assert resp.entity_id == entity_id
        assert resp.category_key == TestCategories._key

    async def test_list_entity_categories(self, vg_client):
        """List categories for the shared entity."""
        cats = await vg_client.entity_registry.list_entity_categories(
            TestEntityCrud._shared_id,
        )
        assert isinstance(cats, list)
        assert any(c.category_key == TestCategories._key for c in cats)

    async def test_list_entities_by_category(self, vg_client):
        """List entities belonging to our test category."""
        entities = await vg_client.entity_registry.list_entities_by_category(
            TestCategories._key,
        )
        assert isinstance(entities, list)
        assert any(e.entity_id == TestEntityCrud._shared_id for e in entities)

    async def test_remove_entity_category(self, vg_client):
        """Remove category from entity and verify."""
        result = await vg_client.entity_registry.remove_entity_category(
            TestEntityCrud._shared_id, TestCategories._key,
        )
        assert result.get("success") is True or result.get("removed") is True

        cats = await vg_client.entity_registry.list_entity_categories(
            TestEntityCrud._shared_id,
        )
        assert not any(c.category_key == TestCategories._key for c in cats)


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

class TestLocations:
    """Create location type, add/list/update/remove location on entity."""

    async def test_create_location_type(self, vg_client):
        """Create a location type."""
        req = LocationTypeCreateRequest(
            type_key=f"{PREFIX}_loctype",
            type_label=f"Test Location Type {PREFIX}",
            type_description="For testing",
        )
        resp = await vg_client.entity_registry.create_location_type(req)
        assert resp.type_key == f"{PREFIX}_loctype"
        TestLocations._type_key = resp.type_key

    async def test_list_location_types(self, vg_client):
        """List location types and verify ours exists."""
        types = await vg_client.entity_registry.list_location_types()
        assert isinstance(types, list)
        assert any(t.type_key == TestLocations._type_key for t in types)

    async def test_create_location(self, vg_client):
        """Add a location to the shared entity."""
        entity_id = TestEntityCrud._shared_id
        req = LocationCreateRequest(
            location_type_key=TestLocations._type_key,
            location_name="Test HQ",
            address_line_1="123 Test St",
            locality="Testville",
            admin_area_1="TS",
            country="US",
            postal_code="12345",
            latitude=40.7128,
            longitude=-74.0060,
        )
        resp = await vg_client.entity_registry.create_location(entity_id, req)
        assert resp.entity_id == entity_id
        assert resp.location_name == "Test HQ"
        assert resp.locality == "Testville"
        TestLocations._loc_id = resp.location_id

    async def test_list_locations(self, vg_client):
        """List locations for the shared entity."""
        locs = await vg_client.entity_registry.list_locations(TestEntityCrud._shared_id)
        assert isinstance(locs, list)
        assert any(loc.location_id == TestLocations._loc_id for loc in locs)

    async def test_update_location(self, vg_client):
        """Update location name and verify."""
        req = LocationUpdateRequest(
            location_name="Updated HQ",
            locality="NewTestville",
        )
        resp = await vg_client.entity_registry.update_location(
            TestLocations._loc_id, req,
        )
        assert resp.location_name == "Updated HQ"
        assert resp.locality == "NewTestville"

    async def test_remove_location(self, vg_client):
        """Remove location and verify it's gone."""
        result = await vg_client.entity_registry.remove_location(TestLocations._loc_id)
        assert result.get("success") is True or result.get("retracted") is True

        locs = await vg_client.entity_registry.list_locations(TestEntityCrud._shared_id)
        assert not any(loc.location_id == TestLocations._loc_id for loc in locs)


# ---------------------------------------------------------------------------
# Cleanup: delete the shared entity at the end
# ---------------------------------------------------------------------------

class TestCleanup:
    """Final cleanup of test data."""

    async def test_delete_shared_entity(self, vg_client):
        """Delete the shared entity used across sub-resource tests."""
        entity_id = getattr(TestEntityCrud, "_shared_id", None)
        if entity_id:
            await vg_client.entity_registry.delete_entity(entity_id)
