"""API tests: Mapping Standalone CRUD via VitalGraphClient.

Tests vector, fuzzy, and search mapping lifecycle:
  - list, create, get, update, delete for each mapping type.
"""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

INDEX_NAME = "test_api_index"
ENTITY_TYPE = "http://vital.ai/ontology/haley-ai-kg#KGEntity"


# ---------------------------------------------------------------------------
# Vector Mappings
# ---------------------------------------------------------------------------

class TestVectorMappingsCrud:
    """Vector mapping lifecycle: list → create → get → update → delete."""

    async def test_list_vector_mappings_empty(self, vg_client, test_space):
        """List vector mappings — returns valid structure."""
        resp = await vg_client.vector_mappings.list_mappings(space_id=test_space)
        assert resp.mappings is not None
        assert isinstance(resp.mappings, list)

    async def test_create_vector_mapping(self, vg_client, test_space):
        """Create a vector mapping and verify returned fields."""
        m = await vg_client.vector_mappings.create_mapping(
            space_id=test_space,
            index_name=INDEX_NAME,
            mapping_type="kgentity",
            type_uri=ENTITY_TYPE,
            enabled=True,
        )
        assert m.mapping_id is not None
        assert m.mapping_type == "kgentity"
        # Store for subsequent tests
        TestVectorMappingsCrud._mapping_id = m.mapping_id

    async def test_get_vector_mapping(self, vg_client, test_space):
        """Get the created mapping by ID."""
        mid = getattr(TestVectorMappingsCrud, "_mapping_id", None)
        assert mid is not None, "create test must run first"
        m = await vg_client.vector_mappings.get_mapping(
            space_id=test_space, mapping_id=mid
        )
        assert m.mapping_id == mid
        assert m.index_name == INDEX_NAME

    async def test_update_vector_mapping(self, vg_client, test_space):
        """Update enabled flag."""
        mid = TestVectorMappingsCrud._mapping_id
        m = await vg_client.vector_mappings.update_mapping(
            space_id=test_space, mapping_id=mid, enabled=False
        )
        assert m.enabled is False

    async def test_delete_vector_mapping(self, vg_client, test_space):
        """Delete the mapping."""
        mid = TestVectorMappingsCrud._mapping_id
        resp = await vg_client.vector_mappings.delete_mapping(
            space_id=test_space, mapping_id=mid
        )
        assert resp.get("message") or resp.get("success") or "deleted" in str(resp).lower()


# ---------------------------------------------------------------------------
# Fuzzy Mappings
# ---------------------------------------------------------------------------

class TestFuzzyMappingsCrud:
    """Fuzzy mapping lifecycle: list → create → get → update → delete."""

    async def test_list_fuzzy_mappings_empty(self, vg_client, test_space):
        """List fuzzy mappings — returns valid structure."""
        resp = await vg_client.fuzzy_mappings.list_mappings(space_id=test_space)
        assert resp.mappings is not None
        assert isinstance(resp.mappings, list)

    async def test_create_fuzzy_mapping(self, vg_client, test_space):
        """Create a fuzzy mapping."""
        m = await vg_client.fuzzy_mappings.create_mapping(
            space_id=test_space,
            index_name=INDEX_NAME,
            mapping_type="kgentity",
            type_uri=ENTITY_TYPE,
            enabled=True,
        )
        assert m.mapping_id is not None
        assert m.mapping_type == "kgentity"
        TestFuzzyMappingsCrud._mapping_id = m.mapping_id

    async def test_get_fuzzy_mapping(self, vg_client, test_space):
        """Get the created fuzzy mapping by ID."""
        mid = getattr(TestFuzzyMappingsCrud, "_mapping_id", None)
        assert mid is not None
        m = await vg_client.fuzzy_mappings.get_mapping(
            space_id=test_space, mapping_id=mid
        )
        assert m.mapping_id == mid

    async def test_update_fuzzy_mapping(self, vg_client, test_space):
        """Update enabled flag."""
        mid = TestFuzzyMappingsCrud._mapping_id
        m = await vg_client.fuzzy_mappings.update_mapping(
            space_id=test_space, mapping_id=mid, enabled=False
        )
        assert m.enabled is False

    async def test_delete_fuzzy_mapping(self, vg_client, test_space):
        """Delete the fuzzy mapping."""
        mid = TestFuzzyMappingsCrud._mapping_id
        resp = await vg_client.fuzzy_mappings.delete_mapping(
            space_id=test_space, mapping_id=mid
        )
        assert resp.get("message") or resp.get("success") or "deleted" in str(resp).lower()


# ---------------------------------------------------------------------------
# Search Mappings
# ---------------------------------------------------------------------------

class TestSearchMappingsCrud:
    """Search mapping lifecycle: list → create → get → update → delete."""

    async def test_list_search_mappings_empty(self, vg_client, test_space):
        """List search mappings — returns valid structure."""
        resp = await vg_client.search_mappings.list_mappings(space_id=test_space)
        assert resp.mappings is not None
        assert isinstance(resp.mappings, list)

    async def test_create_search_mapping(self, vg_client, test_space):
        """Create a search mapping."""
        m = await vg_client.search_mappings.create_mapping(
            space_id=test_space,
            index_name=INDEX_NAME,
            mapping_type="kgentity",
            type_uri=ENTITY_TYPE,
            enabled=True,
        )
        assert m.mapping_id is not None
        assert m.mapping_type == "kgentity"
        TestSearchMappingsCrud._mapping_id = m.mapping_id

    async def test_get_search_mapping(self, vg_client, test_space):
        """Get the created search mapping by ID."""
        mid = getattr(TestSearchMappingsCrud, "_mapping_id", None)
        assert mid is not None
        m = await vg_client.search_mappings.get_mapping(
            space_id=test_space, mapping_id=mid
        )
        assert m.mapping_id == mid

    async def test_update_search_mapping(self, vg_client, test_space):
        """Update enabled flag."""
        mid = TestSearchMappingsCrud._mapping_id
        m = await vg_client.search_mappings.update_mapping(
            space_id=test_space, mapping_id=mid, enabled=False
        )
        assert m.enabled is False

    async def test_delete_search_mapping(self, vg_client, test_space):
        """Delete the search mapping."""
        mid = TestSearchMappingsCrud._mapping_id
        resp = await vg_client.search_mappings.delete_mapping(
            space_id=test_space, mapping_id=mid
        )
        assert resp.message is not None


# ---------------------------------------------------------------------------
# Property-Level CRUD
# ---------------------------------------------------------------------------

PROP_URI = "http://vital.ai/ontology/haley-ai-kg#hasName"
PROP_URI_2 = "http://vital.ai/ontology/haley-ai-kg#hasDescription"


class TestVectorMappingProperties:
    """Add and remove properties on a vector mapping."""

    async def test_add_property(self, vg_client, test_space):
        """Create mapping then add a property."""
        m = await vg_client.vector_mappings.create_mapping(
            space_id=test_space,
            index_name=INDEX_NAME,
            mapping_type="kgentity",
            enabled=True,
        )
        TestVectorMappingProperties._mapping_id = m.mapping_id

        prop = await vg_client.vector_mappings.add_property(
            space_id=test_space,
            mapping_id=m.mapping_id,
            property_uri=PROP_URI,
            property_role="include",
            ordinal=1,
        )
        assert prop.property_id is not None
        assert prop.property_uri == PROP_URI
        assert prop.property_role == "include"
        TestVectorMappingProperties._property_id = prop.property_id

    async def test_get_mapping_shows_property(self, vg_client, test_space):
        """Get mapping verifies property is attached."""
        mid = TestVectorMappingProperties._mapping_id
        m = await vg_client.vector_mappings.get_mapping(
            space_id=test_space, mapping_id=mid
        )
        assert len(m.properties) >= 1
        uris = [p.property_uri for p in m.properties]
        assert PROP_URI in uris

    async def test_remove_property(self, vg_client, test_space):
        """Remove the property, verify it's gone."""
        mid = TestVectorMappingProperties._mapping_id
        pid = TestVectorMappingProperties._property_id
        resp = await vg_client.vector_mappings.remove_property(
            space_id=test_space, mapping_id=mid, property_id=pid
        )
        assert resp.get("message") or resp.get("deleted") or "removed" in str(resp).lower()

        # Verify property removed
        m = await vg_client.vector_mappings.get_mapping(
            space_id=test_space, mapping_id=mid
        )
        uris = [p.property_uri for p in m.properties]
        assert PROP_URI not in uris

        # Cleanup
        await vg_client.vector_mappings.delete_mapping(
            space_id=test_space, mapping_id=mid
        )


class TestFuzzyMappingProperties:
    """Add and remove properties on a fuzzy mapping."""

    async def test_add_property(self, vg_client, test_space):
        """Create mapping then add a property."""
        m = await vg_client.fuzzy_mappings.create_mapping(
            space_id=test_space,
            index_name=INDEX_NAME,
            mapping_type="kgentity",
            enabled=True,
        )
        TestFuzzyMappingProperties._mapping_id = m.mapping_id

        prop = await vg_client.fuzzy_mappings.add_property(
            space_id=test_space,
            mapping_id=m.mapping_id,
            property_uri=PROP_URI,
            property_role="primary",
            ordinal=1,
        )
        assert prop.property_id is not None
        assert prop.property_uri == PROP_URI
        TestFuzzyMappingProperties._property_id = prop.property_id

    async def test_remove_property(self, vg_client, test_space):
        """Remove the property."""
        mid = TestFuzzyMappingProperties._mapping_id
        pid = TestFuzzyMappingProperties._property_id
        resp = await vg_client.fuzzy_mappings.remove_property(
            space_id=test_space, mapping_id=mid, property_id=pid
        )
        assert resp.get("message") or resp.get("deleted") or "removed" in str(resp).lower()

        # Cleanup
        await vg_client.fuzzy_mappings.delete_mapping(
            space_id=test_space, mapping_id=mid
        )


class TestSearchMappingProperties:
    """Add and remove properties on a search mapping."""

    async def test_add_property(self, vg_client, test_space):
        """Create mapping then add a property."""
        m = await vg_client.search_mappings.create_mapping(
            space_id=test_space,
            index_name=INDEX_NAME,
            mapping_type="kgentity",
            enabled=True,
        )
        TestSearchMappingProperties._mapping_id = m.mapping_id

        prop = await vg_client.search_mappings.add_property(
            space_id=test_space,
            mapping_id=m.mapping_id,
            property_uri=PROP_URI,
            property_role="include",
            ordinal=1,
        )
        assert prop.property_id is not None
        assert prop.property_uri == PROP_URI
        TestSearchMappingProperties._property_id = prop.property_id

    async def test_add_second_property(self, vg_client, test_space):
        """Add a second property to verify multi-property support."""
        mid = TestSearchMappingProperties._mapping_id
        prop = await vg_client.search_mappings.add_property(
            space_id=test_space,
            mapping_id=mid,
            property_uri=PROP_URI_2,
            property_role="include",
            ordinal=2,
        )
        assert prop.property_id is not None
        TestSearchMappingProperties._property_id_2 = prop.property_id

        # Verify both properties present
        m = await vg_client.search_mappings.get_mapping(
            space_id=test_space, mapping_id=mid
        )
        uris = [p.property_uri for p in m.properties]
        assert PROP_URI in uris
        assert PROP_URI_2 in uris

    async def test_remove_property(self, vg_client, test_space):
        """Remove first property, second remains."""
        mid = TestSearchMappingProperties._mapping_id
        pid = TestSearchMappingProperties._property_id
        resp = await vg_client.search_mappings.remove_property(
            space_id=test_space, mapping_id=mid, property_id=pid
        )
        assert resp.message is not None

        m = await vg_client.search_mappings.get_mapping(
            space_id=test_space, mapping_id=mid
        )
        uris = [p.property_uri for p in m.properties]
        assert PROP_URI not in uris
        assert PROP_URI_2 in uris

        # Cleanup
        await vg_client.search_mappings.delete_mapping(
            space_id=test_space, mapping_id=mid
        )
