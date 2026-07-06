"""API tests: OpenAI Vector Model — End-to-End integration.

Verifies the full lifecycle using OpenAI as the embedding provider
instead of the default local VitalSigns model.

Flow under test:
  1. Create vector index with provider="openai", model="text-embedding-3-small"
  2. Create search mapping for kgentity with source_type="properties"
  3. Create 5 KGEntities with semantically distinct descriptions
  4. Trigger reindex — server calls OpenAI API to embed entity text
  5. Poll get_vectors until all entities have stored embeddings
  6. Verify embedding dimensions == 1536
  7. Semantic search for domain-specific queries — assert correct ranking
  8. Cleanup: delete entities, mapping, index

Requires: OPENAI_API_KEY environment variable.  Skips if not set.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import pytest_asyncio

from ai_haley_kg_domain.model.KGEntity import KGEntity

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

INDEX_NAME = f"openai_test_{uuid.uuid4().hex[:8]}"
DIMENSIONS = 1536  # text-embedding-3-small default
NS = "http://example.org/apitest/openai/"

# Semantically distinct entities
ENTITIES = [
    ("quantum_physicist", "Dr. Quantum — quantum physics researcher studying subatomic particles and wave functions"),
    ("italian_chef", "Chef Marco — Italian chef specializing in pasta, risotto, and traditional Tuscan cuisine"),
    ("jazz_musician", "Miles Blue — jazz musician playing trumpet and saxophone in New York City clubs"),
    ("marine_biologist", "Dr. Ocean — marine biologist studying coral reef ecosystems and deep sea organisms"),
    ("financial_analyst", "Alex Capital — financial analyst covering stock market trends and portfolio management"),
]


def _require_openai_key():
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        pytest.skip("OPENAI_API_KEY not set")
    return key


def _make_entity(name: str, description: str) -> KGEntity:
    e = KGEntity()
    e.URI = f"{NS}entity_{uuid.uuid4().hex[:12]}"
    e.name = name
    e.kGraphDescription = description
    return e


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def openai_env(vg_client, test_space, test_graph):
    """Create search mapping + OpenAI vector index + entities, reindex, teardown."""
    _require_openai_key()

    # ── 1. Create search mapping (defines what to vectorize) ──────────
    mapping = await vg_client.search_mappings.create_mapping(
        space_id=test_space,
        index_name=INDEX_NAME,
        mapping_type="kgentity",
        enabled=True,
        source_type="properties",
    )

    # ── 2. Create vector index with OpenAI provider ──────────────────
    idx = await vg_client.vector_indexes.create_index(
        space_id=test_space,
        index_name=INDEX_NAME,
        dimensions=DIMENSIONS,
        distance_metric="cosine",
        provider="openai",
        model_name="text-embedding-3-small",
        provider_config={"api_key_env": "OPENAI_API_KEY"},
        description="OpenAI integration test index",
    )

    # ── 3. Attach index to mapping via junction table ─────────────────
    await vg_client.search_mappings.add_index(
        space_id=test_space,
        mapping_id=mapping.mapping_id,
        index_type="vector",
        index_name=INDEX_NAME,
    )

    # ── 4. Create entities ───────────────────────────────────────────
    entities = [_make_entity(name, desc) for name, desc in ENTITIES]
    ecr = await vg_client.kgentities.create_kgentities(
        test_space, test_graph, entities,
    )
    assert ecr.is_success, f"Failed to create entities: {ecr.error_message}"

    # ── 5. Trigger reindex — server calls OpenAI to embed ────────────
    resp = await vg_client.vector_indexes.reindex(
        space_id=test_space,
        index_name=INDEX_NAME,
        graph_uri=test_graph,
        mapping_type="kgentity",
    )
    assert resp.message is not None

    # ── 6. Poll until vectors appear ─────────────────────────────────
    for _ in range(30):
        await asyncio.sleep(2.0)
        check = await vg_client.vector_indexes.get_vectors(
            space_id=test_space,
            index_name=INDEX_NAME,
            graph_uri=test_graph,
        )
        if check.total_count >= len(ENTITIES):
            break

    yield {
        "space_id": test_space,
        "graph_id": test_graph,
        "index_name": INDEX_NAME,
        "mapping": mapping,
        "entities": entities,
    }

    # ── Teardown ─────────────────────────────────────────────────────
    try:
        await vg_client.search_mappings.delete_mapping(
            test_space, mapping.mapping_id,
        )
    except Exception:
        pass
    try:
        await vg_client.vector_indexes.delete_index(test_space, INDEX_NAME)
    except Exception:
        pass


class TestOpenAIVectorIntegration:
    """Verify OpenAI provider → entity vectorization → semantic search."""

    async def test_vectors_populated(self, vg_client, openai_env):
        """After reindex, all entities should have vectors."""
        check = await vg_client.vector_indexes.get_vectors(
            space_id=openai_env["space_id"],
            index_name=openai_env["index_name"],
            graph_uri=openai_env["graph_id"],
        )
        assert check.total_count >= len(ENTITIES), (
            f"Expected >={len(ENTITIES)} vectors, got {check.total_count}"
        )

    async def test_embedding_dimensions(self, vg_client, openai_env):
        """Embeddings should have 1536 dimensions (text-embedding-3-small)."""
        check = await vg_client.vector_indexes.get_vectors(
            space_id=openai_env["space_id"],
            index_name=openai_env["index_name"],
            graph_uri=openai_env["graph_id"],
        )
        assert check.total_count > 0, "No vectors found"
        vec = check.vectors[0]
        assert len(vec.embedding) == DIMENSIONS, (
            f"Expected {DIMENSIONS}-dim embedding, got {len(vec.embedding)}"
        )

    async def test_search_cooking_finds_chef(self, vg_client, openai_env):
        """Search 'cooking recipes pasta' should rank the chef entity first."""
        from vitalgraph.model.kgqueries_model import KGQueryCriteria
        from vitalgraph.model.kgentities_model import VectorSearchCriteria

        criteria = KGQueryCriteria(
            query_type="entity",
            vector_criteria=VectorSearchCriteria(
                search_text="cooking recipes pasta",
                index_name=openai_env["index_name"],
                top_k=5,
            ),
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=openai_env["space_id"],
            graph_id=openai_env["graph_id"],
            criteria=criteria,
            page_size=10,
        )
        assert resp is not None
        result_uris = resp.entity_uris or []
        assert len(result_uris) > 0, "No results for 'cooking recipes pasta'"

        # Chef entity should be in results
        chef_uri = str(openai_env["entities"][1].URI)  # italian_chef
        assert chef_uri in result_uris, (
            f"Expected chef entity in results. Got: {result_uris}"
        )
        # Chef should rank first
        assert result_uris[0] == chef_uri, (
            f"Expected chef at rank 0, got it at {result_uris.index(chef_uri)}"
        )

    async def test_search_stock_market_finds_analyst(self, vg_client, openai_env):
        """Search 'stock market trading' should rank the financial analyst first."""
        from vitalgraph.model.kgqueries_model import KGQueryCriteria
        from vitalgraph.model.kgentities_model import VectorSearchCriteria

        criteria = KGQueryCriteria(
            query_type="entity",
            vector_criteria=VectorSearchCriteria(
                search_text="stock market trading",
                index_name=openai_env["index_name"],
                top_k=5,
            ),
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=openai_env["space_id"],
            graph_id=openai_env["graph_id"],
            criteria=criteria,
            page_size=10,
        )
        assert resp is not None
        result_uris = resp.entity_uris or []
        assert len(result_uris) > 0, "No results for 'stock market trading'"

        analyst_uri = str(openai_env["entities"][4].URI)  # financial_analyst
        assert analyst_uri in result_uris, (
            f"Expected analyst entity in results. Got: {result_uris}"
        )
        assert result_uris[0] == analyst_uri, (
            f"Expected analyst at rank 0, got it at {result_uris.index(analyst_uri)}"
        )

    async def test_search_coral_reef_finds_biologist(self, vg_client, openai_env):
        """Search 'coral reef ocean ecosystems' should rank the marine biologist first."""
        from vitalgraph.model.kgqueries_model import KGQueryCriteria
        from vitalgraph.model.kgentities_model import VectorSearchCriteria

        criteria = KGQueryCriteria(
            query_type="entity",
            vector_criteria=VectorSearchCriteria(
                search_text="coral reef ocean ecosystems",
                index_name=openai_env["index_name"],
                top_k=5,
            ),
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=openai_env["space_id"],
            graph_id=openai_env["graph_id"],
            criteria=criteria,
            page_size=10,
        )
        assert resp is not None
        result_uris = resp.entity_uris or []
        assert len(result_uris) > 0, "No results for 'coral reef ocean ecosystems'"

        biologist_uri = str(openai_env["entities"][3].URI)  # marine_biologist
        assert biologist_uri in result_uris, (
            f"Expected biologist entity in results. Got: {result_uris}"
        )
        assert result_uris[0] == biologist_uri, (
            f"Expected biologist at rank 0, got it at {result_uris.index(biologist_uri)}"
        )

    async def test_search_trumpet_finds_musician(self, vg_client, openai_env):
        """Search 'trumpet saxophone jazz performance' should rank the musician first."""
        from vitalgraph.model.kgqueries_model import KGQueryCriteria
        from vitalgraph.model.kgentities_model import VectorSearchCriteria

        criteria = KGQueryCriteria(
            query_type="entity",
            vector_criteria=VectorSearchCriteria(
                search_text="trumpet saxophone jazz performance",
                index_name=openai_env["index_name"],
                top_k=5,
            ),
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=openai_env["space_id"],
            graph_id=openai_env["graph_id"],
            criteria=criteria,
            page_size=10,
        )
        assert resp is not None
        result_uris = resp.entity_uris or []
        assert len(result_uris) > 0, "No results for 'trumpet saxophone jazz performance'"

        musician_uri = str(openai_env["entities"][2].URI)  # jazz_musician
        assert musician_uri in result_uris, (
            f"Expected musician entity in results. Got: {result_uris}"
        )
        assert result_uris[0] == musician_uri, (
            f"Expected musician at rank 0, got it at {result_uris.index(musician_uri)}"
        )

    async def test_negative_ranking(self, vg_client, openai_env):
        """Search 'quantum physics particles' should NOT rank chef or musician first."""
        from vitalgraph.model.kgqueries_model import KGQueryCriteria
        from vitalgraph.model.kgentities_model import VectorSearchCriteria

        criteria = KGQueryCriteria(
            query_type="entity",
            vector_criteria=VectorSearchCriteria(
                search_text="quantum physics particles",
                index_name=openai_env["index_name"],
                top_k=5,
            ),
        )
        resp = await vg_client.kgqueries.query_connections(
            space_id=openai_env["space_id"],
            graph_id=openai_env["graph_id"],
            criteria=criteria,
            page_size=10,
        )
        assert resp is not None
        result_uris = resp.entity_uris or []
        assert len(result_uris) > 0, "No results for 'quantum physics particles'"

        physicist_uri = str(openai_env["entities"][0].URI)  # quantum_physicist
        chef_uri = str(openai_env["entities"][1].URI)
        musician_uri = str(openai_env["entities"][2].URI)

        # Physicist should be in results and ranked above chef/musician
        assert physicist_uri in result_uris, (
            f"Expected physicist in results. Got: {result_uris}"
        )
        phys_idx = result_uris.index(physicist_uri)

        for label, uri in [("chef", chef_uri), ("musician", musician_uri)]:
            if uri in result_uris:
                other_idx = result_uris.index(uri)
                assert phys_idx < other_idx, (
                    f"Physicist (idx={phys_idx}) should rank above {label} "
                    f"(idx={other_idx}) for 'quantum physics particles'"
                )

    async def test_index_metadata(self, vg_client, openai_env):
        """Verify index was created with OpenAI provider metadata."""
        idx = await vg_client.vector_indexes.get_index(
            openai_env["space_id"], openai_env["index_name"],
        )
        assert idx.index_name == INDEX_NAME
        assert idx.dimensions == DIMENSIONS
        assert idx.provider == "openai"
        assert idx.distance_metric == "cosine"
