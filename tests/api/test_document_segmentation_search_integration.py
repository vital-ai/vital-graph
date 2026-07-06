"""API tests: Document Segmentation → Vector Search — End-to-End integration.

Verifies the full KGDocument lifecycle:
  1. Register a segmentation config
  2. Create vector index + search mapping for document segments
  3. Create a KGDocument whose type matches the config
  4. Auto-segmentation fires → document split into segments
  5. Trigger vector reindex → segments get 384-dim embeddings
  6. Semantic search returns relevant segments ranked correctly
  7. Cleanup cascades properly

Requires: Running VitalGraph server with segmentation worker active.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio

from ai_haley_kg_domain.model.KGDocument import KGDocument

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INDEX_NAME = "document_segments"
DIMENSIONS = 384
DOC_TYPE = "urn:kgdoctype:test_article"
SEG_METHOD = "urn:segmethod:plain_recursive_split"

CLIMATE_ARTICLE = """
Global temperatures have risen by approximately 1.1 degrees Celsius above
pre-industrial levels. Ocean temperatures are increasing dramatically, leading
to widespread coral bleaching events and rising sea levels that threaten
coastal communities around the world. Arctic ice sheets are melting at
unprecedented rates, contributing to sea level rise projections of up to
one meter by 2100. Marine ecosystems face severe disruption as water
temperatures shift faster than many species can adapt.

Renewable energy adoption has accelerated significantly in the past decade.
Solar panel efficiency has improved from 15 percent to over 25 percent in
commercial installations. Wind turbine capacity factors now routinely exceed
50 percent in optimal locations, making wind power cost-competitive with
natural gas and coal. Battery storage technology has dropped in price by
over 80 percent since 2010, enabling grid-scale renewable deployments.

Carbon capture and storage technologies represent a third pillar of climate
mitigation strategy. Direct air capture facilities can now remove carbon
dioxide at costs below 200 dollars per tonne. Underground geological
sequestration has proven safe in multiple pilot projects across different
continents. However, significant scaling of these carbon capture technologies
is needed to meaningfully impact global emissions trajectories and reach
net-zero targets by mid-century.
""".strip()


# ---------------------------------------------------------------------------
# Fixture: set up segmentation config + vector infra + document
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def seg_env(vg_client, test_space, test_graph):
    """Create segmentation config, vector index, mapping, document; teardown after."""

    config_id = None
    mapping_id = None
    doc_uri = None

    # ── 1. Create segmentation config ──────────────────────────────────
    config = await vg_client.kgdocuments.create_segmentation_config(
        space_id=test_space,
        document_type_uri=DOC_TYPE,
        segment_method_uri=SEG_METHOD,
        max_segment_tokens=128,
        min_segment_tokens=20,
        overlap_tokens=0,
        enabled=True,
        auto_vectorize=True,
    )
    config_id = config.config_id
    assert config_id is not None, f"Failed to create segmentation config: {config}"

    # ── 2. Create vector index (delete first to ensure correct config) ─
    try:
        await vg_client.vector_indexes.delete_index(
            space_id=test_space, index_name=INDEX_NAME,
        )
    except Exception:
        pass  # May not exist yet
    await vg_client.vector_indexes.create_index(
        space_id=test_space,
        index_name=INDEX_NAME,
        dimensions=DIMENSIONS,
        distance_metric="cosine",
        provider="vitalsigns",
        model_name="paraphrase-multilingual-MiniLM-L12-v2",
        description="Document segment test embeddings",
    )

    # ── 3. Create search mapping ───────────────────────────────────────
    mapping = await vg_client.search_mappings.create_mapping(
        space_id=test_space,
        index_name=INDEX_NAME,
        mapping_type="kgdocument_segment",
        enabled=True,
        source_type="default",
    )
    mapping_id = mapping.mapping_id

    # ── 4. Attach index to mapping ─────────────────────────────────────
    await vg_client.search_mappings.add_index(
        space_id=test_space,
        mapping_id=mapping_id,
        index_type="vector",
        index_name=INDEX_NAME,
    )

    # ── 5. Create KGDocument ───────────────────────────────────────────
    doc = KGDocument()
    doc.URI = f"urn:test:doc:{uuid.uuid4().hex[:12]}"
    doc.name = "Climate and Energy Article"
    doc.kGDocumentType = DOC_TYPE
    doc.kGDocumentContent = CLIMATE_ARTICLE
    doc.kGraphDescription = CLIMATE_ARTICLE
    doc_uri = str(doc.URI)

    resp = await vg_client.kgdocuments.create_kgdocuments(
        test_space, test_graph, [doc],
    )
    assert resp.is_success, f"Failed to create document: {resp.error_message}"

    # ── 6. Trigger segmentation explicitly ─────────────────────────────
    seg_result = await vg_client.kgdocuments.segment_document(
        space_id=test_space,
        graph_id=test_graph,
        document_uri=doc_uri,
        segment_method_uri=SEG_METHOD,
        max_segment_tokens=128,
    )
    # Poll segmentation status until completed
    completed = False
    for _ in range(45):
        await asyncio.sleep(2.0)
        status = await vg_client.kgdocuments.get_segmentation_status(
            space_id=test_space,
            document_uri=doc_uri,
        )
        jobs = status.jobs
        if any(j.get("status") == "completed" for j in jobs):
            completed = True
            break
        # If segment_document returned synchronously, check result
        if seg_result and seg_result.segment_count > 0:
            completed = True
            break

    # ── 7. List segments ───────────────────────────────────────────────
    segments_resp = await vg_client.kgdocuments.list_segments(
        test_space, test_graph, parent_uri=doc_uri,
    )

    # ── 8. Trigger reindex ─────────────────────────────────────────────
    await vg_client.vector_indexes.reindex(
        space_id=test_space,
        index_name=INDEX_NAME,
        graph_uri=test_graph,
        mapping_type="kgdocument_segment",
    )

    # ── 9. Poll vectors ────────────────────────────────────────────────
    vectors_ready = False
    for _ in range(30):
        await asyncio.sleep(2.0)
        vecs = await vg_client.vector_indexes.get_vectors(
            space_id=test_space,
            index_name=INDEX_NAME,
            graph_uri=test_graph,
        )
        if vecs.total_count > 0:
            vectors_ready = True
            break

    yield {
        "space_id": test_space,
        "graph_id": test_graph,
        "doc_uri": doc_uri,
        "config_id": config_id,
        "mapping_id": mapping_id,
        "segmentation_completed": completed,
        "segments_resp": segments_resp,
        "vectors_ready": vectors_ready,
        "vectors": vecs,
    }

    # ── Teardown ───────────────────────────────────────────────────────
    try:
        await vg_client.kgdocuments.delete_kgdocument(
            test_space, test_graph, doc_uri,
        )
    except Exception:
        pass
    try:
        await vg_client.search_mappings.delete_mapping(test_space, mapping_id)
    except Exception:
        pass
    try:
        await vg_client.vector_indexes.delete_index(test_space, INDEX_NAME)
    except Exception:
        pass
    try:
        await vg_client.kgdocuments.delete_segmentation_config(
            test_space, config_id,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Test: Segmentation
# ---------------------------------------------------------------------------

class TestDocumentSegmentation:
    """Verify auto-segmentation fires and produces segments."""

    async def test_segmentation_completes(self, vg_client, seg_env):
        """Segmentation job should reach 'completed' status."""
        assert seg_env["segmentation_completed"], (
            "Segmentation did not complete within timeout"
        )

    async def test_segments_created(self, vg_client, seg_env):
        """Document should be split into multiple segments."""
        resp = seg_env["segments_resp"]
        assert resp.count >= 2, (
            f"Expected >= 2 segments, got {resp.count}"
        )

    async def test_segment_content_nonempty(self, vg_client, seg_env):
        """Each segment should have non-empty content."""
        resp = seg_env["segments_resp"]
        if resp.count == 0:
            pytest.skip("No segments created")
        for seg in resp.segments:
            content = (
                getattr(seg, "kGDocumentContent", None)
                or getattr(seg, "kGraphDescription", None)
                or ""
            )
            assert len(content.strip()) > 0, (
                f"Segment {getattr(seg, 'URI', '?')} has empty content"
            )


# ---------------------------------------------------------------------------
# Test: Vectorization
# ---------------------------------------------------------------------------

class TestSegmentVectorization:
    """Verify segments are vectorized with correct dimensions."""

    async def test_vectors_populated(self, vg_client, seg_env):
        """After reindex, segment vectors should be stored."""
        assert seg_env["vectors_ready"], "Vectors not populated within timeout"
        assert seg_env["vectors"].total_count > 0, "No vectors stored"

    async def test_embedding_dimensions(self, vg_client, seg_env):
        """Embeddings should have consistent, valid dimensions (384 local or 1536 OpenAI)."""
        if not seg_env["vectors_ready"]:
            pytest.skip("Vectors not ready")
        vec = seg_env["vectors"].vectors[0]
        dim = len(vec.embedding)
        assert dim in (384, 1536), (
            f"Unexpected embedding dimension: {dim} (expected 384 for MiniLM or 1536 for OpenAI)"
        )
        # All vectors should have the same dimension
        for v in seg_env["vectors"].vectors:
            assert len(v.embedding) == dim, "Inconsistent embedding dimensions"


# ---------------------------------------------------------------------------
# Test: Semantic Search
# ---------------------------------------------------------------------------

class TestSegmentSemanticSearch:
    """Verify semantic search returns relevant segments via SPARQL."""

    async def _search(self, vg_client, seg_env, search_text: str):
        """Helper: run SPARQL vector similarity search on document segments.

        The triple pattern must come BEFORE the vg:vectorSimilarity BIND
        so the SPARQL→SQL translator can resolve the subject UUID column.
        """
        from vitalgraph.model.sparql_model import SPARQLQueryRequest

        if not seg_env["vectors_ready"]:
            pytest.skip("Vectors not ready")

        sparql = (
            "PREFIX vg: <http://vital.ai/ontology/vitalgraph#>\n"
            "PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>\n"
            "SELECT ?segment ?score ?content WHERE {\n"
            "    ?segment haley:hasKGDocumentContent ?content .\n"
            f'    BIND(vg:vectorSimilarity(?segment, "{search_text}", "{INDEX_NAME}") AS ?score)\n'
            "    FILTER(?score > 0.0)\n"
            "}\n"
            "ORDER BY DESC(?score) LIMIT 5"
        )
        request = SPARQLQueryRequest(query=sparql)
        resp = await vg_client.sparql.execute_sparql_query(
            space_id=seg_env["space_id"],
            request=request,
        )
        bindings = (resp.results or {}).get("bindings", [])
        return bindings

    async def test_search_renewable_energy(self, vg_client, seg_env):
        """Search 'solar panel efficiency renewable' should return results."""
        bindings = await self._search(
            vg_client, seg_env,
            "solar panel efficiency renewable energy wind turbine",
        )
        assert len(bindings) > 0, "No results for renewable energy query"
        top_content = bindings[0].get("content", {}).get("value", "").lower()
        assert "solar" in top_content or "renewable" in top_content or "wind" in top_content, (
            f"Top result doesn't mention renewable energy: {top_content[:200]}"
        )

    async def test_search_climate_ocean(self, vg_client, seg_env):
        """Search 'ocean temperature coral bleaching sea level' should return results."""
        bindings = await self._search(
            vg_client, seg_env,
            "ocean temperature coral bleaching sea level rise",
        )
        assert len(bindings) > 0, "No results for climate/ocean query"
        top_content = bindings[0].get("content", {}).get("value", "").lower()
        assert "ocean" in top_content or "coral" in top_content or "sea level" in top_content, (
            f"Top result doesn't mention climate/ocean: {top_content[:200]}"
        )

    async def test_search_carbon_capture(self, vg_client, seg_env):
        """Search 'carbon capture storage sequestration' should return results."""
        bindings = await self._search(
            vg_client, seg_env,
            "carbon capture storage geological sequestration direct air",
        )
        assert len(bindings) > 0, "No results for carbon capture query"
        top_content = bindings[0].get("content", {}).get("value", "").lower()
        assert "carbon" in top_content or "capture" in top_content or "sequestration" in top_content, (
            f"Top result doesn't mention carbon capture: {top_content[:200]}"
        )

    async def test_different_queries_different_top_results(self, vg_client, seg_env):
        """Different semantic queries should return different top-ranked segments."""
        bindings1 = await self._search(
            vg_client, seg_env,
            "solar panel wind turbine battery renewable electricity",
        )
        bindings2 = await self._search(
            vg_client, seg_env,
            "ocean coral bleaching arctic ice melting sea level",
        )

        if not bindings1 or not bindings2:
            pytest.skip("Insufficient results for ranking comparison")

        uri1 = bindings1[0].get("segment", {}).get("value", "")
        uri2 = bindings2[0].get("segment", {}).get("value", "")

        # Top results should differ (different topics → different segments)
        assert uri1 != uri2, (
            f"Expected different top results for different topics, "
            f"both returned {uri1}"
        )
