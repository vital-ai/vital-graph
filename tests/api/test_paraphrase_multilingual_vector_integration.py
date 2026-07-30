"""API tests: paraphrase-multilingual-MiniLM-L12-v2 vector model — End-to-End integration.

Mirrors test_openai_vector_integration.py, but for the local
`paraphrase_multilingual_minilm_l12_v2` provider — the model Weaviate's
text2vec-transformers uses, wrapped by WeaviateLocalVectorizer.

Flow under test:
  1. Create vector index with provider="paraphrase_multilingual_minilm_l12_v2"
  2. Create search mapping for kgentity with source_type="properties"
  3. Create 5 KGEntities with semantically distinct descriptions
  4. Trigger reindex — server embeds entity text with the local HF model
  5. Poll get_vectors until all entities have stored embeddings
  6. Verify embedding dimensions == 384
  7. Semantic search — assert correct ranking
  8. Cross-lingual search — the reason this provider exists (see below)
  9. Cleanup: delete entities, mapping, index

Why the cross-lingual case matters: this model and the default
`vitalsigns_onnx` model (paraphrase-MiniLM-L3-v2) BOTH emit 384 dims, so a
mixed-up provider produces a well-formed vector in the wrong space rather than
an error.  Non-Latin-script retrieval is the cheapest behavioural assertion
that distinguishes them — vitalsigns_onnx uses an English BERT wordpiece vocab
(30522); this model uses XLM-R (250002).  See
test_cross_lingual_search_finds_chef for the measured separation.

Requires: running VitalGraph server whose environment can load
sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 (downloaded from
HuggingFace on first use, ~470MB).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio

from ai_haley_kg_domain.model.KGEntity import KGEntity

pytestmark = [
    pytest.mark.api,
    pytest.mark.slow,
    pytest.mark.asyncio(loop_scope="session"),
]

PROVIDER = "paraphrase_multilingual_minilm_l12_v2"
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
INDEX_NAME = f"paraphrase_test_{uuid.uuid4().hex[:8]}"
DIMENSIONS = 384
NS = "http://example.org/apitest/paraphrase/"

# Semantically distinct entities — same cast as the OpenAI test so the two
# providers can be compared directly.
ENTITIES = [
    ("quantum_physicist", "Dr. Quantum — quantum physics researcher studying subatomic particles and wave functions"),
    ("italian_chef", "Chef Marco — Italian chef specializing in pasta, risotto, and traditional Tuscan cuisine"),
    ("jazz_musician", "Miles Blue — jazz musician playing trumpet and saxophone in New York City clubs"),
    ("marine_biologist", "Dr. Ocean — marine biologist studying coral reef ecosystems and deep sea organisms"),
    ("financial_analyst", "Alex Capital — financial analyst covering stock market trends and portfolio management"),
]

IDX_CHEF = 1
IDX_BIOLOGIST = 3
IDX_ANALYST = 4


def _make_entity(name: str, description: str) -> KGEntity:
    e = KGEntity()
    e.URI = f"{NS}entity_{uuid.uuid4().hex[:12]}"
    e.name = name
    e.kGraphDescription = description
    return e


async def _search(vg_client, env, text: str, top_k: int = 5) -> list[str]:
    """Run a vector search and return the ranked entity URIs."""
    from vitalgraph.model.kgqueries_model import KGQueryCriteria
    from vitalgraph.model.kgentities_model import VectorSearchCriteria

    criteria = KGQueryCriteria(
        query_type="entity",
        vector_criteria=VectorSearchCriteria(
            search_text=text,
            index_name=env["index_name"],
            top_k=top_k,
        ),
    )
    resp = await vg_client.kgqueries.query_connections(
        space_id=env["space_id"],
        graph_id=env["graph_id"],
        criteria=criteria,
        page_size=10,
    )
    assert resp is not None, f"No response for {text!r}"
    return resp.entity_uris or []


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def paraphrase_env(vg_client, test_space, test_graph):
    """Create search mapping + paraphrase vector index + entities, reindex, teardown."""
    # ── 1. Create search mapping (defines what to vectorize) ──────────
    mapping = await vg_client.search_mappings.create_mapping(
        space_id=test_space,
        index_name=INDEX_NAME,
        mapping_type="kgentity",
        enabled=True,
        source_type="properties",
    )

    # ── 2. Create vector index with the multilingual provider ─────────
    idx = await vg_client.vector_indexes.create_index(
        space_id=test_space,
        index_name=INDEX_NAME,
        dimensions=DIMENSIONS,
        distance_metric="cosine",
        provider=PROVIDER,
        model_name=MODEL_NAME,
        description="paraphrase-multilingual-MiniLM-L12-v2 integration test index",
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

    # ── 5. Trigger reindex — server embeds with the local HF model ────
    resp = await vg_client.vector_indexes.reindex(
        space_id=test_space,
        index_name=INDEX_NAME,
        graph_uri=test_graph,
        mapping_type="kgentity",
    )
    assert resp.message is not None

    # ── 6. Poll until vectors appear (first run may download the model) ──
    for _ in range(45):
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
        "index": idx,
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


class TestParaphraseMultilingualVectorIntegration:
    """Verify the multilingual provider → entity vectorization → semantic search."""

    async def test_index_records_provider_and_model(self, vg_client, paraphrase_env):
        """The index row must persist the provider — vg_resolve reads it at query time."""
        idx = await vg_client.vector_indexes.get_index(
            space_id=paraphrase_env["space_id"],
            index_name=paraphrase_env["index_name"],
        )
        assert idx is not None
        assert idx.provider == PROVIDER, (
            f"Index stored provider={idx.provider!r}; query embedding would use "
            f"the wrong model"
        )
        assert idx.dimensions == DIMENSIONS

    async def test_vectors_populated(self, vg_client, paraphrase_env):
        """After reindex, all entities should have vectors."""
        check = await vg_client.vector_indexes.get_vectors(
            space_id=paraphrase_env["space_id"],
            index_name=paraphrase_env["index_name"],
            graph_uri=paraphrase_env["graph_id"],
        )
        assert check.total_count >= len(ENTITIES), (
            f"Expected >={len(ENTITIES)} vectors, got {check.total_count}"
        )

    async def test_embedding_dimensions(self, vg_client, paraphrase_env):
        """Embeddings should have 384 dimensions."""
        check = await vg_client.vector_indexes.get_vectors(
            space_id=paraphrase_env["space_id"],
            index_name=paraphrase_env["index_name"],
            graph_uri=paraphrase_env["graph_id"],
        )
        assert check.total_count > 0, "No vectors found"
        vec = check.vectors[0]
        assert len(vec.embedding) == DIMENSIONS, (
            f"Expected {DIMENSIONS}-dim embedding, got {len(vec.embedding)}"
        )

    async def test_embeddings_are_not_zero_vectors(self, vg_client, paraphrase_env):
        """A failed provider lookup degrades to '[]'::vector — catch that explicitly."""
        check = await vg_client.vector_indexes.get_vectors(
            space_id=paraphrase_env["space_id"],
            index_name=paraphrase_env["index_name"],
            graph_uri=paraphrase_env["graph_id"],
        )
        assert check.total_count > 0, "No vectors found"
        for vec in check.vectors:
            assert any(abs(x) > 1e-9 for x in vec.embedding), (
                "All-zero embedding — provider resolution likely failed server-side"
            )

    async def test_search_cooking_finds_chef(self, vg_client, paraphrase_env):
        """Search 'cooking recipes pasta' should rank the chef entity first."""
        result_uris = await _search(vg_client, paraphrase_env, "cooking recipes pasta")
        assert len(result_uris) > 0, "No results for 'cooking recipes pasta'"

        chef_uri = str(paraphrase_env["entities"][IDX_CHEF].URI)
        assert chef_uri in result_uris, (
            f"Expected chef entity in results. Got: {result_uris}"
        )
        assert result_uris[0] == chef_uri, (
            f"Expected chef at rank 0, got it at {result_uris.index(chef_uri)}"
        )

    async def test_search_stock_market_finds_analyst(self, vg_client, paraphrase_env):
        """Search 'stock market trading' should rank the financial analyst first."""
        result_uris = await _search(vg_client, paraphrase_env, "stock market trading")
        assert len(result_uris) > 0, "No results for 'stock market trading'"

        analyst_uri = str(paraphrase_env["entities"][IDX_ANALYST].URI)
        assert analyst_uri in result_uris, (
            f"Expected analyst entity in results. Got: {result_uris}"
        )
        assert result_uris[0] == analyst_uri, (
            f"Expected analyst at rank 0, got it at {result_uris.index(analyst_uri)}"
        )

    async def test_search_coral_reef_finds_biologist(self, vg_client, paraphrase_env):
        """Search 'coral reef ocean ecosystems' should rank the marine biologist first."""
        result_uris = await _search(
            vg_client, paraphrase_env, "coral reef ocean ecosystems",
        )
        assert len(result_uris) > 0, "No results for 'coral reef ocean ecosystems'"

        biologist_uri = str(paraphrase_env["entities"][IDX_BIOLOGIST].URI)
        assert biologist_uri in result_uris, (
            f"Expected biologist entity in results. Got: {result_uris}"
        )
        assert result_uris[0] == biologist_uri, (
            f"Expected biologist at rank 0, got it at {result_uris.index(biologist_uri)}"
        )

    @pytest.mark.parametrize(
        "query,lang",
        [
            ("イタリア料理のシェフで、麺類と伝統的な地方料理を専門としています", "ja"),
            ("итальянский повар, специализирующийся на лапше и традиционной кухне", "ru"),
            ("意大利厨师，专门制作面食和传统地方菜肴", "zh"),
        ],
    )
    async def test_cross_lingual_search_finds_chef(
        self, vg_client, paraphrase_env, query, lang,
    ):
        """Non-Latin-script query against English entity text — the multilingual case.

        This is the assertion that actually pins the index to the right model.
        Measured cosine of translation-vs-English source:

            model                                   ja      ru      zh
            vitalsigns_onnx (English wordpiece)   0.087  -0.012   0.071
            paraphrase-multilingual-MiniLM-L12    0.865   0.884   0.876

        Under vitalsigns_onnx the translation is not even closer than an
        unrelated sentence, so the chef will not be retrieved.

        Note a Spanish/French query would NOT discriminate — shared tokens
        ("chef", "pasta", "italiano") carry the English-only model to ~0.87 as
        well.  Non-Latin script is what forces the vocabulary to matter.
        """
        result_uris = await _search(vg_client, paraphrase_env, query, top_k=5)
        assert len(result_uris) > 0, f"No results for {lang} query {query!r}"

        chef_uri = str(paraphrase_env["entities"][IDX_CHEF].URI)
        physicist_uri = str(paraphrase_env["entities"][0].URI)

        assert chef_uri in result_uris, (
            f"{lang} query did not retrieve the chef entity — the index is "
            f"probably not using a multilingual model. Got: {result_uris}"
        )
        if physicist_uri in result_uris:
            assert result_uris.index(chef_uri) < result_uris.index(physicist_uri), (
                f"{lang} query ranked the quantum physicist above the chef — "
                f"suggests the index is not using a multilingual model"
            )
