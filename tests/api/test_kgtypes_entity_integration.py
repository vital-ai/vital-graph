"""API tests: KGTypes → Entity vectorization integration.

End-to-end scenario verifying that KGType descriptions in sp_kg_types flow
into entity vector embeddings via the cross-space type description lookup.

Flow under test:
  1. Create KGEntityTypes in sp_kg_types with rich kGraphDescription
  2. Create a test space with a vector index + mapping (source_type='type_description')
  3. Create KGEntity instances with kGEntityType pointing to the type URIs
  4. Trigger reindex (populator reads type descriptions from sp_kg_types)
  5. Vector similarity search using semantic queries ("man", "company", "dining")
  6. Verify correct entities ranked highest based on their type's description

NOTE: KGTypes in sp_kg_types are global and survive space teardowns.
Fixtures MUST clean up types explicitly. See testing_plan.md §"Test fixture caution".
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio

from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGEntityType import KGEntityType

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

NS = "http://example.org/apitest/kgtype_entity/"
SP_KG_TYPES = "sp_kg_types"

# Vector index dimensions — uses server-side embedding model so no dimension needed
# (the server's paraphrase-multilingual-MiniLM-L12-v2 produces 384-dim vectors)
INDEX_DIMS = 384
INDEX_NAME = f"vec_typeint_{uuid.uuid4().hex[:8]}"


def _make_entity_type(name: str, description: str) -> KGEntityType:
    """Create a KGEntityType for sp_kg_types."""
    t = KGEntityType()
    t.URI = f"{NS}type_{uuid.uuid4().hex[:12]}"
    t.name = name
    t.kGraphDescription = description
    t.kGTypeVersion = "1.0"
    t.kGModelVersion = "2024.1"
    return t


def _make_entity(name: str, type_uri: str) -> KGEntity:
    """Create a KGEntity with kGEntityType set."""
    e = KGEntity()
    e.URI = f"{NS}entity_{uuid.uuid4().hex[:12]}"
    e.name = name
    e.kGEntityType = type_uri
    return e


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def type_entity_env(vg_client, test_space, test_graph):
    """Set up the full integration environment:

    - 3 KGEntityTypes in sp_kg_types
    - Vector index + mapping with source_type='type_description' in test space
    - 4 KGEntity instances referencing the types
    - Reindex to vectorize entities (populator reads type descriptions)
    """
    # ── 1. Create types in sp_kg_types ────────────────────────────────
    person_type = _make_entity_type(
        "IntegPersonType",
        "A human individual, man or woman, member of society",
    )
    business_type = _make_entity_type(
        "IntegBusinessType",
        "A commercial enterprise, company, or organization",
    )
    restaurant_type = _make_entity_type(
        "IntegRestaurantType",
        "A food service establishment, eatery, dining venue",
    )

    types = [person_type, business_type, restaurant_type]
    cr = await vg_client.kgtypes.create_kgtypes(SP_KG_TYPES, types)
    assert cr.is_success, f"Failed to create types: {cr.error_message}"

    # ── 2. Create vector index + mapping with source_type='type_description' ──
    await vg_client.vector_indexes.create_index(
        space_id=test_space,
        index_name=INDEX_NAME,
        dimensions=INDEX_DIMS,
        distance_metric="cosine",
        provider="vitalsigns",
        description="Type integration test vector index",
    )

    mapping = await vg_client.vector_mappings.create_mapping(
        space_id=test_space,
        index_name=INDEX_NAME,
        mapping_type="kgentity",
        enabled=True,
        source_type="type_description",
    )

    # ── 3. Create typed entities ──────────────────────────────────────
    john = _make_entity("John Smith", str(person_type.URI))
    jane = _make_entity("Jane Doe", str(person_type.URI))
    acme = _make_entity("Acme Corp", str(business_type.URI))
    pizza = _make_entity("Pizza Palace", str(restaurant_type.URI))

    entities = [john, jane, acme, pizza]
    ecr = await vg_client.kgentities.create_kgentities(
        test_space, test_graph, entities,
    )
    assert ecr.is_success, f"Failed to create entities: {ecr.error_message}"

    # ── 4. Trigger reindex — populator reads type descriptions ────────
    resp = await vg_client.vector_indexes.reindex(
        space_id=test_space,
        index_name=INDEX_NAME,
        graph_uri=test_graph,
        mapping_type="kgentity",
    )
    assert resp.message is not None

    # Poll until vectors appear (reindex is async)
    for _ in range(20):
        await asyncio.sleep(1.5)
        check = await vg_client.vector_indexes.get_vectors(
            space_id=test_space,
            index_name=INDEX_NAME,
            graph_uri=test_graph,
        )
        if check.total_count >= 4:
            break

    yield {
        "space_id": test_space,
        "graph_id": test_graph,
        "index_name": INDEX_NAME,
        "mapping": mapping,
        "person_type": person_type,
        "business_type": business_type,
        "restaurant_type": restaurant_type,
        "john": john,
        "jane": jane,
        "acme": acme,
        "pizza": pizza,
    }

    # ── Teardown ──────────────────────────────────────────────────────
    # Delete types from sp_kg_types (global — must clean up)
    uri_csv = ",".join(str(t.URI) for t in types)
    await vg_client.kgtypes.delete_kgtypes_batch(SP_KG_TYPES, uri_csv)

    # Delete mapping and index
    try:
        await vg_client.vector_mappings.delete_mapping(test_space, mapping.mapping_id)
    except Exception:
        pass
    try:
        await vg_client.vector_indexes.delete_index(test_space, INDEX_NAME)
    except Exception:
        pass


class TestKGTypeEntityIntegration:
    """Verify type description → entity vector → semantic search."""

    async def test_vectors_populated(self, vg_client, type_entity_env):
        """After reindex, all 4 entities should have vectors."""
        check = await vg_client.vector_indexes.get_vectors(
            space_id=type_entity_env["space_id"],
            index_name=type_entity_env["index_name"],
            graph_uri=type_entity_env["graph_id"],
        )
        assert check.total_count >= 4, (
            f"Expected >=4 vectors after reindex, got {check.total_count}"
        )

    async def test_search_man_finds_person_entities(self, vg_client, type_entity_env):
        """Search 'man' should find Person entities (type desc includes 'man')."""
        from vitalgraph.model.kgqueries_model import KGQueryCriteria
        from vitalgraph.model.kgentities_model import VectorSearchCriteria

        criteria = KGQueryCriteria(
            query_type="entity",
            vector_criteria=VectorSearchCriteria(
                search_text="man",
                index_name=type_entity_env["index_name"],
                top_k=10,
            ),
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=type_entity_env["space_id"],
            graph_id=type_entity_env["graph_id"],
            criteria=criteria,
            page_size=10,
        )
        assert resp is not None
        result_uris = resp.entity_uris or []

        john_uri = str(type_entity_env["john"].URI)
        jane_uri = str(type_entity_env["jane"].URI)
        acme_uri = str(type_entity_env["acme"].URI)

        # At least one Person entity should appear in results
        person_found = john_uri in result_uris or jane_uri in result_uris
        assert person_found, (
            f"Expected John or Jane in results for 'man'. Got URIs: {result_uris}"
        )

        # If Business also appears, it should rank lower than Person
        if acme_uri in result_uris and (john_uri in result_uris or jane_uri in result_uris):
            person_idx = min(
                result_uris.index(john_uri) if john_uri in result_uris else 999,
                result_uris.index(jane_uri) if jane_uri in result_uris else 999,
            )
            acme_idx = result_uris.index(acme_uri)
            assert person_idx < acme_idx, (
                f"Person (idx={person_idx}) should rank above Acme (idx={acme_idx}) for 'man'"
            )

    async def test_search_company_finds_business(self, vg_client, type_entity_env):
        """Search 'company' should find Acme Corp (type desc includes 'company')."""
        from vitalgraph.model.kgqueries_model import KGQueryCriteria
        from vitalgraph.model.kgentities_model import VectorSearchCriteria

        criteria = KGQueryCriteria(
            query_type="entity",
            vector_criteria=VectorSearchCriteria(
                search_text="company",
                index_name=type_entity_env["index_name"],
                top_k=10,
            ),
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=type_entity_env["space_id"],
            graph_id=type_entity_env["graph_id"],
            criteria=criteria,
            page_size=10,
        )
        assert resp is not None
        result_uris = resp.entity_uris or []

        acme_uri = str(type_entity_env["acme"].URI)
        assert acme_uri in result_uris, (
            f"Expected Acme Corp in results for 'company'. Got URIs: {result_uris}"
        )

    async def test_search_dining_finds_restaurant(self, vg_client, type_entity_env):
        """Search 'dining' should find Pizza Palace (type desc includes 'dining')."""
        from vitalgraph.model.kgqueries_model import KGQueryCriteria
        from vitalgraph.model.kgentities_model import VectorSearchCriteria

        criteria = KGQueryCriteria(
            query_type="entity",
            vector_criteria=VectorSearchCriteria(
                search_text="dining",
                index_name=type_entity_env["index_name"],
                top_k=10,
            ),
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=type_entity_env["space_id"],
            graph_id=type_entity_env["graph_id"],
            criteria=criteria,
            page_size=10,
        )
        assert resp is not None
        result_uris = resp.entity_uris or []

        pizza_uri = str(type_entity_env["pizza"].URI)
        assert pizza_uri in result_uris, (
            f"Expected Pizza Palace in results for 'dining'. Got URIs: {result_uris}"
        )

    async def test_search_negative_case(self, vg_client, type_entity_env):
        """Search 'man' should NOT rank Acme/Pizza above Person entities."""
        from vitalgraph.model.kgqueries_model import KGQueryCriteria
        from vitalgraph.model.kgentities_model import VectorSearchCriteria

        criteria = KGQueryCriteria(
            query_type="entity",
            vector_criteria=VectorSearchCriteria(
                search_text="man",
                index_name=type_entity_env["index_name"],
                top_k=10,
            ),
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=type_entity_env["space_id"],
            graph_id=type_entity_env["graph_id"],
            criteria=criteria,
            page_size=10,
        )
        assert resp is not None
        result_uris = resp.entity_uris or []

        pizza_uri = str(type_entity_env["pizza"].URI)
        john_uri = str(type_entity_env["john"].URI)
        jane_uri = str(type_entity_env["jane"].URI)

        # Pizza Palace should NOT appear before Person entities for "man"
        if pizza_uri in result_uris and (john_uri in result_uris or jane_uri in result_uris):
            pizza_idx = result_uris.index(pizza_uri)
            person_idx = min(
                result_uris.index(john_uri) if john_uri in result_uris else 999,
                result_uris.index(jane_uri) if jane_uri in result_uris else 999,
            )
            assert person_idx < pizza_idx, (
                f"Pizza (idx={pizza_idx}) should NOT rank above Person (idx={person_idx}) for 'man'"
            )
