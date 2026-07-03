"""API tests: KGTypes CRUD, search, relationships, and documentation.

Tests create, list, get, update, delete, batch delete, batch get by URIs,
keyword/fts/vector/hybrid search, type relationships, and type documentation.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio

from ai_haley_kg_domain.model.KGType import KGType
from ai_haley_kg_domain.model.KGEntityType import KGEntityType
from ai_haley_kg_domain.model.KGFrameType import KGFrameType

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

NS = "http://example.org/apitest/kgtype/"

# The centralized system space for KG Types
SP_KG_TYPES = "sp_kg_types"


def _make_kgtype(name: str, description: str, version: str = "1.0", cls=KGType):
    """Create a KGType with a unique URI."""
    t = cls()
    t.URI = f"{NS}{uuid.uuid4().hex[:12]}"
    t.name = name
    t.kGraphDescription = description
    t.kGTypeVersion = version
    t.kGModelVersion = "2024.1"
    return t


def _make_entity_type(name: str, description: str):
    """Create a KGEntityType with name and kGraphDescription.

    The kgtype_default vector index indexes hasName + hasKGraphDescription,
    so the description text drives vector similarity search.
    """
    t = KGEntityType()
    t.URI = f"{NS}{uuid.uuid4().hex[:12]}"
    t.name = name
    t.kGraphDescription = description
    t.kGTypeVersion = "1.0"
    t.kGModelVersion = "2024.1"
    return t


class TestKGTypesCrud:
    """KGType lifecycle: create → list → get → update → delete → batch delete."""

    async def test_create_kgtypes(self, vg_client, test_space):
        """Create 3 KGTypes (base, entity type, frame type)."""
        types = [
            _make_kgtype("Person", "Represents a person entity"),
            _make_kgtype("Organization", "Represents an organization", cls=KGEntityType),
            _make_kgtype("AddressFrame", "Frame type for addresses", cls=KGFrameType),
        ]
        cr = await vg_client.kgtypes.create_kgtypes(test_space, types)
        assert cr.is_success, f"create failed: {cr.error_message}"
        assert cr.created_count == 3

    async def test_list_kgtypes(self, vg_client, test_space):
        """List returns at least the 3 types created above."""
        lr = await vg_client.kgtypes.list_kgtypes(test_space, page_size=50)
        assert lr.is_success
        assert lr.count >= 3

    async def test_get_kgtype_by_uri(self, vg_client, test_space):
        """Create a type then get it by URI."""
        t = _make_kgtype("Gettable", "Type to get by URI")
        await vg_client.kgtypes.create_kgtypes(test_space, [t])

        gr = await vg_client.kgtypes.get_kgtype(test_space, str(t.URI))
        assert gr.is_success
        assert gr.type is not None
        assert str(gr.type.name) == "Gettable"

    async def test_update_kgtype(self, vg_client, test_space):
        """Create, update name/version, verify persisted."""
        t = _make_kgtype("BeforeUpdate", "Original description")
        await vg_client.kgtypes.create_kgtypes(test_space, [t])

        # Update
        t.name = "AfterUpdate"
        t.kGTypeVersion = "2.0"
        ur = await vg_client.kgtypes.update_kgtypes(test_space, [t])
        assert ur.is_success, f"update failed: {ur.error_message}"

        # Verify
        gr = await vg_client.kgtypes.get_kgtype(test_space, str(t.URI))
        assert gr.is_success
        assert str(gr.type.name) == "AfterUpdate"

    async def test_delete_kgtype(self, vg_client, test_space):
        """Create then delete a KGType, verify gone."""
        t = _make_kgtype("DeleteMe", "Type to delete")
        await vg_client.kgtypes.create_kgtypes(test_space, [t])

        dr = await vg_client.kgtypes.delete_kgtype(test_space, str(t.URI))
        assert dr.is_success

        gr = await vg_client.kgtypes.get_kgtype(test_space, str(t.URI))
        assert not gr.is_success or gr.type is None

    async def test_batch_delete_kgtypes(self, vg_client, test_space):
        """Create 2 types then batch-delete them, verify both gone."""
        t1 = _make_kgtype("Batch1", "Batch delete 1")
        t2 = _make_kgtype("Batch2", "Batch delete 2")
        await vg_client.kgtypes.create_kgtypes(test_space, [t1, t2])

        uri_csv = f"{t1.URI},{t2.URI}"
        dr = await vg_client.kgtypes.delete_kgtypes_batch(test_space, uri_csv)
        assert dr.is_success

        # Verify both are gone
        gr1 = await vg_client.kgtypes.get_kgtype(test_space, str(t1.URI))
        assert not gr1.is_success or gr1.type is None
        gr2 = await vg_client.kgtypes.get_kgtype(test_space, str(t2.URI))
        assert not gr2.is_success or gr2.type is None


# ---------------------------------------------------------------------------
# Get by URIs
# ---------------------------------------------------------------------------


class TestKGTypesGetByUris:
    """Batch get multiple KGTypes by URI list."""

    async def test_get_kgtypes_by_uris(self, vg_client, test_space):
        """Create 3 types, fetch 2 by comma-separated URI list."""
        t1 = _make_kgtype("ByUri1", "First type for batch get")
        t2 = _make_kgtype("ByUri2", "Second type for batch get")
        t3 = _make_kgtype("ByUri3", "Third type (not fetched)")
        await vg_client.kgtypes.create_kgtypes(test_space, [t1, t2, t3])

        uri_csv = f"{t1.URI},{t2.URI}"
        lr = await vg_client.kgtypes.get_kgtypes_by_uris(test_space, uri_csv)
        assert lr.is_success, f"get_kgtypes_by_uris failed: {lr.error_message}"
        assert lr.count >= 2
        returned_names = {str(t.name) for t in lr.types} if lr.types else set()
        assert "ByUri1" in returned_names
        assert "ByUri2" in returned_names

    async def test_get_kgtypes_by_uris_empty(self, vg_client, test_space):
        """Request non-existent URIs — should return 0 types."""
        fake_uri = f"{NS}nonexistent_{uuid.uuid4().hex[:8]}"
        lr = await vg_client.kgtypes.get_kgtypes_by_uris(test_space, fake_uri)
        # Either returns success with 0 or returns an error
        if lr.is_success:
            assert lr.count == 0


# ---------------------------------------------------------------------------
# Search (keyword, FTS, vector, hybrid)
# ---------------------------------------------------------------------------

# Types created specifically for search tests — use KGEntityType so
# hasKGEntityTypeDescription flows into the kgtype_default vector index.

SEARCH_TYPES = None  # populated by fixture


@pytest_asyncio.fixture(scope="class", loop_scope="session")
async def search_env(vg_client):
    """Create KGEntityTypes in sp_kg_types for search testing.

    The kgtype_default vector index auto-syncs new types in the background,
    so we allow a brief delay for embeddings to appear.
    """
    person = _make_entity_type(
        "PersonSearchTest",
        "A human individual, man or woman, member of society",
    )
    business = _make_entity_type(
        "BusinessSearchTest",
        "A commercial enterprise, company, or organization",
    )
    restaurant = _make_entity_type(
        "RestaurantSearchTest",
        "A food service establishment, eatery, dining venue",
    )

    cr = await vg_client.kgtypes.create_kgtypes(SP_KG_TYPES, [person, business, restaurant])
    assert cr.is_success, f"Failed to create search test types: {cr.error_message}"

    # Allow time for kgtype_default auto-sync to vectorize the new types
    await asyncio.sleep(3.0)

    yield {
        "person": person,
        "business": business,
        "restaurant": restaurant,
        "person_uri": str(person.URI),
        "business_uri": str(business.URI),
        "restaurant_uri": str(restaurant.URI),
    }

    # Teardown — remove test types
    uri_csv = f"{person.URI},{business.URI},{restaurant.URI}"
    await vg_client.kgtypes.delete_kgtypes_batch(SP_KG_TYPES, uri_csv)


class TestKGTypeSearch:
    """Search KGTypes across all 4 modes: keyword, fts, vector, hybrid."""

    # ── Keyword ───────────────────────────────────────────────────

    async def test_keyword_search(self, vg_client, search_env):
        """Keyword substring match: 'PersonSearch' should find PersonSearchTest."""
        resp = await vg_client.kgtypes.search_types(
            SP_KG_TYPES, query="PersonSearch", search_mode="keyword",
        )
        assert resp.is_success, f"keyword search failed: {resp.error_message}"
        assert resp.count >= 1
        names = [t.get("name", "") for t in resp.types]
        assert any("PersonSearchTest" in n for n in names), (
            f"Expected PersonSearchTest in results, got: {names}"
        )

    async def test_keyword_no_results(self, vg_client, search_env):
        """Keyword search for nonsense should return 0 results."""
        resp = await vg_client.kgtypes.search_types(
            SP_KG_TYPES, query=f"xyzzy_{uuid.uuid4().hex[:6]}", search_mode="keyword",
        )
        assert resp.is_success
        assert resp.count == 0

    # ── FTS ────────────────────────────────────────────────────────

    async def test_fts_search(self, vg_client, search_env):
        """Full-text search: 'human individual' should match PersonSearchTest.

        The kGraphDescription 'A human individual, man or woman, member of
        society' is indexed by FTS. We search on description tokens rather
        than the camelCase name which may not tokenize as expected.
        """
        resp = await vg_client.kgtypes.search_types(
            SP_KG_TYPES, query="human individual", search_mode="fts",
        )
        assert resp.is_success, f"FTS search failed: {resp.error_message}"
        assert resp.count >= 1, (
            f"Expected >=1 FTS result for 'human individual', got {resp.count}"
        )
        names = [t.get("name", "") for t in resp.types]
        assert any("PersonSearchTest" in n for n in names), (
            f"Expected PersonSearchTest in FTS results, got: {names}"
        )

    # ── Vector similarity ─────────────────────────────────────────

    async def test_vector_search_man_finds_person(self, vg_client, search_env):
        """Vector search: 'man' should be semantically similar to PersonSearchTest.

        PersonSearchTest has kGEntityTypeDescription = 'A human individual,
        man or woman, member of society'. The vector embedding should be close
        to the query 'man'. BusinessSearchTest and RestaurantSearchTest should
        score lower or not appear.
        """
        resp = await vg_client.kgtypes.search_types(
            SP_KG_TYPES, query="man", search_mode="vector",
        )
        assert resp.is_success, f"vector search failed: {resp.error_message}"
        assert resp.count >= 1, "Expected at least 1 result for vector search 'man'"

        # Find positions of our test types in results
        names = [t.get("name", "") for t in resp.types]
        person_idx = next((i for i, n in enumerate(names) if "PersonSearchTest" in n), None)
        business_idx = next((i for i, n in enumerate(names) if "BusinessSearchTest" in n), None)
        restaurant_idx = next((i for i, n in enumerate(names) if "RestaurantSearchTest" in n), None)

        assert person_idx is not None, (
            f"PersonSearchTest not found in vector search for 'man'. Results: {names}"
        )

        # Person should rank higher (lower index) than Business and Restaurant
        if business_idx is not None:
            assert person_idx < business_idx, (
                f"Person (idx={person_idx}) should rank above Business (idx={business_idx})"
            )
        if restaurant_idx is not None:
            assert person_idx < restaurant_idx, (
                f"Person (idx={person_idx}) should rank above Restaurant (idx={restaurant_idx})"
            )

    async def test_vector_search_restaurant(self, vg_client, search_env):
        """Vector search: 'dining' should find RestaurantSearchTest highly ranked."""
        resp = await vg_client.kgtypes.search_types(
            SP_KG_TYPES, query="dining", search_mode="vector",
        )
        assert resp.is_success, f"vector search failed: {resp.error_message}"
        assert resp.count >= 1

        names = [t.get("name", "") for t in resp.types]
        restaurant_idx = next((i for i, n in enumerate(names) if "RestaurantSearchTest" in n), None)
        person_idx = next((i for i, n in enumerate(names) if "PersonSearchTest" in n), None)

        assert restaurant_idx is not None, (
            f"RestaurantSearchTest not found in vector search for 'dining'. Results: {names}"
        )

        if person_idx is not None:
            assert restaurant_idx < person_idx, (
                f"Restaurant (idx={restaurant_idx}) should rank above Person (idx={person_idx}) for 'dining'"
            )

    async def test_vector_search_company(self, vg_client, search_env):
        """Vector search: 'company' should find BusinessSearchTest highly ranked."""
        resp = await vg_client.kgtypes.search_types(
            SP_KG_TYPES, query="company", search_mode="vector",
        )
        assert resp.is_success, f"vector search failed: {resp.error_message}"
        assert resp.count >= 1

        names = [t.get("name", "") for t in resp.types]
        business_idx = next((i for i, n in enumerate(names) if "BusinessSearchTest" in n), None)
        assert business_idx is not None, (
            f"BusinessSearchTest not found in vector search for 'company'. Results: {names}"
        )

    # ── Hybrid ────────────────────────────────────────────────────

    async def test_hybrid_search(self, vg_client, search_env):
        """Hybrid search (alpha=0.7, vector-weighted): 'individual human' → Person."""
        resp = await vg_client.kgtypes.search_types(
            SP_KG_TYPES, query="individual human",
            search_mode="hybrid", alpha=0.7,
        )
        assert resp.is_success, f"hybrid search failed: {resp.error_message}"
        assert resp.count >= 1

        names = [t.get("name", "") for t in resp.types]
        person_idx = next((i for i, n in enumerate(names) if "PersonSearchTest" in n), None)
        assert person_idx is not None, (
            f"PersonSearchTest not found in hybrid search. Results: {names}"
        )

    # ── Type filter ───────────────────────────────────────────────

    async def test_search_with_type_filter(self, vg_client, search_env):
        """Search with type=entity filter — should only return entity types."""
        resp = await vg_client.kgtypes.search_types(
            SP_KG_TYPES, query="SearchTest",
            search_mode="keyword", type="entity",
        )
        assert resp.is_success, f"filtered search failed: {resp.error_message}"
        # Our test types are all KGEntityType, so they should appear
        if resp.count > 0:
            # Verify no non-entity types leak through (e.g. frame types)
            for t in resp.types:
                vitaltype = t.get("vitaltype", "")
                if vitaltype:
                    assert "Entity" in vitaltype or "entity" in vitaltype.lower(), (
                        f"Non-entity type leaked through filter: {vitaltype}"
                    )


# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------


class TestKGTypeRelationships:
    """Type-level relationship lifecycle: create → get → delete."""

    async def test_relationship_lifecycle(self, vg_client, test_space):
        """Create two types, link them, verify, then delete the edge."""
        t1 = _make_kgtype("ParentType", "Parent in relationship test")
        t2 = _make_kgtype("ChildType", "Child in relationship test")
        await vg_client.kgtypes.create_kgtypes(test_space, [t1, t2])

        # Create relationship
        edge_type = "http://vital.ai/ontology/haley-ai-kg#Edge_hasSubKGEntityType"
        cr = await vg_client.kgtypes.create_type_relationship(
            test_space, str(t1.URI), edge_type, str(t2.URI),
        )
        assert cr.is_success, f"create relationship failed: {cr.error_message}"
        edge_uri = cr.edge_uri
        assert edge_uri, "Expected edge_uri in create response"

        # Get relationships
        rr = await vg_client.kgtypes.get_type_relationships(test_space, str(t1.URI))
        assert rr.is_success, f"get relationships failed: {rr.error_message}"
        assert len(rr.edges) >= 1, f"Expected at least 1 edge, got {len(rr.edges)}"

        # Delete relationship
        dr = await vg_client.kgtypes.delete_type_relationship(
            test_space, str(t1.URI), edge_uri,
        )
        assert dr.is_success, f"delete relationship failed: {dr.error_message}"

        # Verify gone
        rr2 = await vg_client.kgtypes.get_type_relationships(test_space, str(t1.URI))
        assert rr2.is_success
        edge_uris = [e.get("uri", e.get("edge_uri", "")) for e in rr2.edges]
        assert edge_uri not in edge_uris, "Deleted edge still present"

    async def test_relationships_empty(self, vg_client, test_space):
        """Get relationships for a type with no edges — should return empty list."""
        t = _make_kgtype("IsolatedType", "Type with no relationships")
        await vg_client.kgtypes.create_kgtypes(test_space, [t])

        rr = await vg_client.kgtypes.get_type_relationships(test_space, str(t.URI))
        assert rr.is_success
        assert len(rr.edges) == 0


# ---------------------------------------------------------------------------
# Documentation
# ---------------------------------------------------------------------------


class TestKGTypeDocumentation:
    """Type documentation lifecycle: create → get → update → delete."""

    async def test_documentation_lifecycle(self, vg_client, test_space):
        """Full documentation lifecycle on a single type."""
        t = _make_kgtype("DocTestType", "Type for documentation tests")
        await vg_client.kgtypes.create_kgtypes(test_space, [t])
        type_uri = str(t.URI)

        # 1. Get docs — should be empty
        gr = await vg_client.kgtypes.get_type_documentation(test_space, type_uri)
        assert gr.is_success
        assert not gr.has_documentation, "Expected no documentation initially"

        # 2. Create documentation
        content_v1 = "# DocTestType\n\nThis is the initial documentation."
        ur = await vg_client.kgtypes.update_type_documentation(
            test_space, type_uri, content_v1,
        )
        assert ur.is_success, f"create doc failed: {ur.error_message}"
        assert ur.created is True, "Expected created=True for first write"

        # 3. Get documentation — verify content
        gr2 = await vg_client.kgtypes.get_type_documentation(test_space, type_uri)
        assert gr2.is_success
        assert gr2.has_documentation is True
        assert gr2.content is not None
        assert "initial documentation" in gr2.content

        # 4. Update documentation
        content_v2 = "# DocTestType\n\nUpdated documentation with more details."
        ur2 = await vg_client.kgtypes.update_type_documentation(
            test_space, type_uri, content_v2,
        )
        assert ur2.is_success
        assert ur2.created is False, "Expected created=False for update"

        # 5. Verify updated content
        gr3 = await vg_client.kgtypes.get_type_documentation(test_space, type_uri)
        assert gr3.is_success
        assert "Updated documentation" in gr3.content

        # 6. Delete documentation
        dr = await vg_client.kgtypes.delete_type_documentation(test_space, type_uri)
        assert dr.is_success
        assert dr.deleted is True

        # 7. Verify deleted
        gr4 = await vg_client.kgtypes.get_type_documentation(test_space, type_uri)
        assert gr4.is_success
        assert not gr4.has_documentation


# ---------------------------------------------------------------------------
# KGType Description
# ---------------------------------------------------------------------------

class TestKGTypeDescription:
    """GET /kgtypes/description — fetch type description text."""

    async def test_description_known_type(self, vg_client):
        """Fetching description for a known entity type returns structured response."""
        # Use a type that likely exists in sp_kg_types
        resp = await vg_client.kgtypes.get_type_description(
            "http://vital.ai/ontology/haley-ai-kg#KGEntity", "kgentity"
        )
        assert resp.type_uri == "http://vital.ai/ontology/haley-ai-kg#KGEntity"
        assert resp.mapping_type == "kgentity"
        # description may be None if no description text stored, but response is valid

    async def test_description_unknown_type(self, vg_client):
        """Unknown type URI returns response with None description."""
        resp = await vg_client.kgtypes.get_type_description(
            "http://example.org/nonexistent/type", "kgentity"
        )
        assert resp.type_uri == "http://example.org/nonexistent/type"
        assert resp.description is None
