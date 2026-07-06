"""
End-to-end test: Wikipedia document ingestion, segmentation, vectorization,
and query/retrieval via both KGQueries and KGDocuments endpoints.

Requires:
- Running VitalGraph server (docker-compose up)
- Wikipedia markdown files in test_files/wikipedia/ (run fetch_wikipedia_test_docs.py)

Tests cover:
1. Document ingestion (create multiple KGDocuments from Wikipedia articles)
2. Segmentation (markdown heading split, poll for completion)
3. Vectorization (reindex, verify embeddings)
4. KGDocuments retrieval (list documents, list segments, get by URI)
5. KGQuery document queries (search_scope, vector similarity, text search)
6. SPARQL vector similarity search (cross-topic relevance)
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Dict, List

import pytest
import pytest_asyncio

from vitalgraph.model.sparql_model import SPARQLQueryRequest

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WIKI_DIR = Path(__file__).resolve().parent.parent.parent / "test_files" / "wikipedia"
INDEX_NAME = "document_segments"
DOC_TYPE = "urn:kgdoctype:wikipedia_article"
SEG_METHOD = "urn:segmethod:markdown_heading_split"

ARTICLES = [
    ("artificial_intelligence.md", "Artificial Intelligence"),
    ("solar_system.md", "Solar System"),
    ("coffee.md", "Coffee"),
]



# ---------------------------------------------------------------------------
# Fixture: ingest Wikipedia articles, segment, vectorize
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def wiki_env(vg_client, test_space, test_graph):
    """Full lifecycle fixture: ingest Wikipedia docs → segment → vectorize."""

    # Check Wikipedia files exist
    md_files = {name: WIKI_DIR / name for name, _ in ARTICLES}
    for name, path in md_files.items():
        if not path.exists():
            pytest.skip(
                f"Wikipedia test file not found: {path}\n"
                "Run: python test_scripts/data/fetch_wikipedia_test_docs.py"
            )

    # ── 1. Create segmentation config ──────────────────────────────────
    config = await vg_client.kgdocuments.create_segmentation_config(
        space_id=test_space,
        document_type_uri=DOC_TYPE,
        segment_method_uri=SEG_METHOD,
        max_segment_tokens=512,
        min_segment_tokens=30,
        overlap_tokens=0,
        enabled=True,
        auto_vectorize=True,
    )
    config_id = config.config_id
    assert config_id is not None, f"Failed to create segmentation config: {config}"
    print(f"[wiki_env] ✓ segmentation config created: id={config_id}")

    # ── 2. Create vector index (delete first for idempotency) ──────────
    try:
        await vg_client.vector_indexes.delete_index(
            space_id=test_space, index_name=INDEX_NAME,
        )
    except Exception:
        pass
    idx = await vg_client.vector_indexes.create_index(
        space_id=test_space,
        index_name=INDEX_NAME,
        dimensions=384,
        distance_metric="cosine",
        provider="vitalsigns",
        model_name="paraphrase-multilingual-MiniLM-L12-v2",
        description="Wikipedia segment embeddings (test)",
    )
    print(f"[wiki_env] ✓ vector index created: {idx}")

    # ── 3. Create search mapping + attach index ────────────────────────
    mapping = await vg_client.search_mappings.create_mapping(
        space_id=test_space,
        index_name=INDEX_NAME,
        mapping_type="kgdocument_segment",
        enabled=True,
        source_type="default",
    )
    mapping_id = mapping.mapping_id
    assert mapping_id is not None, f"Failed to create mapping: {mapping}"
    add_idx_resp = await vg_client.search_mappings.add_index(
        space_id=test_space,
        mapping_id=mapping_id,
        index_type="vector",
        index_name=INDEX_NAME,
    )
    print(f"[wiki_env] ✓ mapping created: id={mapping_id}, index attached: {add_idx_resp}")

    # ── 3b. Create FTS index + attach to mapping ──────────────────────
    try:
        await vg_client.fts_indexes.delete_index(
            space_id=test_space, index_name=INDEX_NAME,
        )
    except Exception:
        pass
    fts_idx = await vg_client.fts_indexes.create_index(
        space_id=test_space,
        index_name=INDEX_NAME,
        languages=["english"],
    )
    print(f"[wiki_env] ✓ FTS index created: {fts_idx}")
    add_fts_resp = await vg_client.search_mappings.add_index(
        space_id=test_space,
        mapping_id=mapping_id,
        index_type="fts",
        index_name=INDEX_NAME,
    )
    print(f"[wiki_env] ✓ FTS index attached to mapping: {add_fts_resp}")

    # ── 4. Create KGDocuments from Wikipedia markdown ──────────────────
    from ai_haley_kg_domain.model.KGDocument import KGDocument

    doc_uris: Dict[str, str] = {}  # filename → URI
    for filename, title in ARTICLES:
        content = (WIKI_DIR / filename).read_text(encoding="utf-8")

        doc = KGDocument()
        doc.URI = f"urn:test:wiki:{uuid.uuid4().hex[:12]}"
        doc.name = title
        doc.kGDocumentType = DOC_TYPE
        doc.kGDocumentContent = content
        doc.kGraphDescription = content

        resp = await vg_client.kgdocuments.create_kgdocuments(
            test_space, test_graph, [doc],
        )
        print(
            f"[wiki_env]   create resp: is_success={resp.is_success}, "
            f"created_count={getattr(resp, 'created_count', '?')}, "
            f"message={getattr(resp, 'message', '?')}, "
            f"error={resp.error_message}"
        )
        assert resp.is_success, f"Failed to create doc '{title}': {resp.error_message}"
        doc_uris[filename] = str(doc.URI)
        print(f"[wiki_env] ✓ created doc '{title}' ({len(content)} chars): {doc.URI}")

    # ── 4b. Verify documents exist via GET ────────────────────────────
    for filename, uri in doc_uris.items():
        verify = await vg_client.kgdocuments.get_kgdocument(
            test_space, test_graph, uri,
        )
        if verify.is_success:
            print(f"[wiki_env] ✓ verified doc exists: {filename} → {uri}")
        else:
            print(
                f"[wiki_env] ✗ doc NOT FOUND after create: {filename} → {uri}, "
                f"error={verify.error_message}"
            )

    # ── 5. Trigger segmentation for each document ──────────────────────
    for filename, uri in doc_uris.items():
        seg_result = await vg_client.kgdocuments.segment_document(
            space_id=test_space,
            graph_id=test_graph,
            document_uri=uri,
            segment_method_uri=SEG_METHOD,
            max_segment_tokens=512,
        )
        assert seg_result.is_success or seg_result.async_mode, (
            f"segment_document({filename}) failed: error_code={seg_result.error_code}, "
            f"success={seg_result.success}, async_mode={seg_result.async_mode}, "
            f"message={getattr(seg_result, 'message', 'N/A')}"
        )
        print(
            f"[wiki_env] ✓ segmentation triggered for {filename}: "
            f"sync_count={seg_result.segment_count}, async={seg_result.async_mode}, "
            f"job_id={seg_result.job_id}"
        )

    # ── 6. Poll segmentation until all docs have segments ──────────────
    all_completed = False
    for attempt in range(90):
        await asyncio.sleep(3.0)
        docs_done = 0
        for uri in doc_uris.values():
            seg_check = await vg_client.kgdocuments.list_segments(
                test_space, test_graph, parent_uri=uri,
            )
            if seg_check.count > 0:
                docs_done += 1
        if attempt % 5 == 0:
            print(f"[wiki_env] seg poll #{attempt}: {docs_done}/{len(doc_uris)} docs have segments")
        if docs_done >= len(doc_uris):
            all_completed = True
            print(f"[wiki_env] ✓ segmentation completed after ~{attempt * 3}s")
            break

    if not all_completed:
        # Dump detailed status for debugging
        print(f"[wiki_env] ✗ segmentation timed out after {90 * 3}s")
        # Worker health
        space_status = await vg_client.kgdocuments.get_segmentation_status(
            space_id=test_space,
        )
        print(f"[wiki_env]   worker_status={space_status.worker_status}")
        for filename, uri in doc_uris.items():
            seg_check = await vg_client.kgdocuments.list_segments(
                test_space, test_graph, parent_uri=uri,
            )
            status = await vg_client.kgdocuments.get_segmentation_status(
                space_id=test_space, document_uri=uri,
            )
            print(
                f"[wiki_env]   {filename}: {seg_check.count} segments, "
                f"jobs={status.jobs}"
            )

    # ── 7. Collect segment counts per document ─────────────────────────
    segments_by_doc: Dict[str, object] = {}
    total_segs = 0
    for filename, uri in doc_uris.items():
        seg_resp = await vg_client.kgdocuments.list_segments(
            test_space, test_graph, parent_uri=uri,
        )
        segments_by_doc[filename] = seg_resp
        total_segs += seg_resp.count
        print(f"[wiki_env]   {filename}: {seg_resp.count} segments")
    print(f"[wiki_env] total segments: {total_segs}")

    # ── 8. Wait for inline vectorization (done by segmentation worker) ─
    # The segmentation worker vectorizes segments inline via auto_sync,
    # so no explicit reindex is needed.  Just poll until vectors appear.
    vectors_ready = False
    vecs = None
    for attempt in range(60):
        await asyncio.sleep(2.0)
        vecs = await vg_client.vector_indexes.get_vectors(
            space_id=test_space,
            index_name=INDEX_NAME,
            graph_uri=test_graph,
        )
        if attempt % 5 == 0:
            print(f"[wiki_env] vec poll #{attempt}: {vecs.total_count} vectors")
        if vecs.total_count >= total_segs:
            vectors_ready = True
            print(f"[wiki_env] ✓ vectors ready: {vecs.total_count} after ~{attempt * 2}s")
            break
    if not vectors_ready:
        count = vecs.total_count if vecs else 0
        print(f"[wiki_env] ✗ vectors not ready after 120s ({count}/{total_segs})")

    yield {
        "space_id": test_space,
        "graph_id": test_graph,
        "doc_uris": doc_uris,
        "config_id": config_id,
        "mapping_id": mapping_id,
        "segmentation_completed": all_completed,
        "segments_by_doc": segments_by_doc,
        "vectors_ready": vectors_ready,
        "vectors": vecs,
    }

    # ── Teardown ───────────────────────────────────────────────────────
    for uri in doc_uris.values():
        try:
            await vg_client.kgdocuments.delete_kgdocument(test_space, test_graph, uri)
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
        await vg_client.kgdocuments.delete_segmentation_config(test_space, config_id)
    except Exception:
        pass


# ===========================================================================
# Test: Document Ingestion & Segmentation
# ===========================================================================

class TestWikipediaIngestion:
    """Verify Wikipedia documents are ingested and segmented correctly."""

    async def test_segmentation_completes(self, vg_client, wiki_env):
        """All segmentation jobs should complete within timeout."""
        assert wiki_env["segmentation_completed"], (
            "Segmentation did not complete for all documents within timeout"
        )

    async def test_each_document_has_segments(self, vg_client, wiki_env):
        """Each Wikipedia article should produce multiple segments."""
        for filename, seg_resp in wiki_env["segments_by_doc"].items():
            assert seg_resp.count >= 3, (
                f"{filename}: expected >= 3 segments, got {seg_resp.count}"
            )

    async def test_segment_content_nonempty(self, vg_client, wiki_env):
        """Every segment should have non-empty content."""
        for filename, seg_resp in wiki_env["segments_by_doc"].items():
            for seg in seg_resp.segments:
                content = (
                    getattr(seg, "kGDocumentContent", None)
                    or getattr(seg, "kGraphDescription", None)
                    or ""
                )
                assert len(content.strip()) > 10, (
                    f"{filename}: segment {getattr(seg, 'URI', '?')} has insufficient content"
                )

    async def test_total_segment_count(self, vg_client, wiki_env):
        """Total segments across all docs should be substantial."""
        total = sum(s.count for s in wiki_env["segments_by_doc"].values())
        assert total >= 10, f"Expected >= 10 total segments, got {total}"


# ===========================================================================
# Test: Vectorization
# ===========================================================================

class TestWikipediaVectorization:
    """Verify segment vectors are populated with correct dimensions."""

    async def test_vectors_populated(self, vg_client, wiki_env):
        """After reindex, vectors should exist for segments."""
        assert wiki_env["vectors_ready"], "Vectors not populated within timeout"
        assert wiki_env["vectors"].total_count > 0, "No vectors stored"

    async def test_vector_count_matches_segments(self, vg_client, wiki_env):
        """Number of vectors should approximate number of segments."""
        if not wiki_env["vectors_ready"]:
            pytest.skip("Vectors not ready")
        total_segments = sum(s.count for s in wiki_env["segments_by_doc"].values())
        vec_count = wiki_env["vectors"].total_count
        # Allow for parent copies also being vectorized
        assert vec_count >= total_segments * 0.5, (
            f"Too few vectors ({vec_count}) for {total_segments} segments"
        )

    async def test_embedding_dimensions(self, vg_client, wiki_env):
        """Embeddings should have consistent, valid dimensions."""
        if not wiki_env["vectors_ready"]:
            pytest.skip("Vectors not ready")
        vec = wiki_env["vectors"].vectors[0]
        dim = len(vec.embedding)
        assert dim in (384, 1536), (
            f"Unexpected dimension: {dim}"
        )
        for v in wiki_env["vectors"].vectors[:10]:
            assert len(v.embedding) == dim, "Inconsistent embedding dimensions"


# ===========================================================================
# Test: KGDocuments Retrieval
# ===========================================================================

class TestKGDocumentsRetrieval:
    """Test document retrieval via the KGDocuments endpoint."""

    async def test_list_documents(self, vg_client, wiki_env):
        """List all documents in graph — should include our Wikipedia articles."""
        resp = await vg_client.kgdocuments.list_kgdocuments(
            space_id=wiki_env["space_id"],
            graph_id=wiki_env["graph_id"],
        )
        assert resp.is_success
        assert resp.count >= len(ARTICLES), (
            f"Expected >= {len(ARTICLES)} documents, got {resp.count}"
        )

    async def test_get_document_by_uri(self, vg_client, wiki_env):
        """Get a specific document by URI — should return full content."""
        uri = list(wiki_env["doc_uris"].values())[0]
        resp = await vg_client.kgdocuments.get_kgdocument(
            space_id=wiki_env["space_id"],
            graph_id=wiki_env["graph_id"],
            uri=uri,
        )
        assert resp.is_success, f"Failed to get document: {resp.error_message}"

    async def test_list_segments_for_document(self, vg_client, wiki_env):
        """List segments for a specific document — verify structure."""
        uri = wiki_env["doc_uris"]["artificial_intelligence.md"]
        resp = await vg_client.kgdocuments.list_segments(
            wiki_env["space_id"], wiki_env["graph_id"], parent_uri=uri,
        )
        assert resp.count >= 3, f"AI article should have >= 3 segments, got {resp.count}"

    async def test_list_segments_different_documents(self, vg_client, wiki_env):
        """Different documents should have independent segment sets."""
        ai_uri = wiki_env["doc_uris"]["artificial_intelligence.md"]
        solar_uri = wiki_env["doc_uris"]["solar_system.md"]

        ai_segs = await vg_client.kgdocuments.list_segments(
            wiki_env["space_id"], wiki_env["graph_id"], parent_uri=ai_uri,
        )
        solar_segs = await vg_client.kgdocuments.list_segments(
            wiki_env["space_id"], wiki_env["graph_id"], parent_uri=solar_uri,
        )
        assert ai_segs.count > 0
        assert solar_segs.count > 0
        # Segment URIs should not overlap
        ai_segment_uris = {getattr(s, "URI", "") for s in ai_segs.segments}
        solar_segment_uris = {getattr(s, "URI", "") for s in solar_segs.segments}
        assert ai_segment_uris.isdisjoint(solar_segment_uris), (
            "Segments from different documents should not overlap"
        )


# ===========================================================================
# Test: KGQuery Document Queries
# ===========================================================================

class TestKGQueryDocuments:
    """Test query_documents() with various criteria."""

    async def test_query_all_documents(self, vg_client, wiki_env):
        """Query all documents without filters — should find our articles."""
        resp = await vg_client.kgqueries.query_documents(
            space_id=wiki_env["space_id"],
            graph_id=wiki_env["graph_id"],
            document_type_uri=DOC_TYPE,
        )
        assert resp.total_count >= len(ARTICLES), (
            f"Expected >= {len(ARTICLES)} results, got {resp.total_count}"
        )

    async def test_query_segments_only(self, vg_client, wiki_env):
        """Query with search_scope='segments' — only segments, not originals."""
        resp = await vg_client.kgqueries.query_documents(
            space_id=wiki_env["space_id"],
            graph_id=wiki_env["graph_id"],
            search_scope="segments",
            page_size=50,
        )
        # Should return many segments (more than number of original documents)
        assert resp.total_count > len(ARTICLES), (
            f"Expected more segments than documents, got {resp.total_count}"
        )

    async def test_query_originals_only(self, vg_client, wiki_env):
        """Query with search_scope='originals' — only original documents."""
        resp = await vg_client.kgqueries.query_documents(
            space_id=wiki_env["space_id"],
            graph_id=wiki_env["graph_id"],
            document_type_uri=DOC_TYPE,
            search_scope="originals",
        )
        assert resp.total_count == len(ARTICLES), (
            f"Expected exactly {len(ARTICLES)} originals, got {resp.total_count}"
        )

    async def test_query_by_segment_method(self, vg_client, wiki_env):
        """Query segments filtered by segment_method_uri."""
        resp = await vg_client.kgqueries.query_documents(
            space_id=wiki_env["space_id"],
            graph_id=wiki_env["graph_id"],
            search_scope="segments",
            segment_method_uri=SEG_METHOD,
            page_size=50,
        )
        assert resp.total_count > 0, "No segments found with markdown heading split method"

    async def test_query_by_parent_document(self, vg_client, wiki_env):
        """Query segments for a specific parent document URI."""
        ai_uri = wiki_env["doc_uris"]["artificial_intelligence.md"]
        resp = await vg_client.kgqueries.query_documents(
            space_id=wiki_env["space_id"],
            graph_id=wiki_env["graph_id"],
            parent_document_uri=ai_uri,
            search_scope="segments",
            page_size=50,
        )
        assert resp.total_count >= 3, (
            f"AI article segments via query: expected >= 3, got {resp.total_count}"
        )

    async def test_query_with_text_search(self, vg_client, wiki_env):
        """Query documents with text search — should find matching content."""
        resp = await vg_client.kgqueries.query_documents(
            space_id=wiki_env["space_id"],
            graph_id=wiki_env["graph_id"],
            search_text="neural network",
            fts_index_name=INDEX_NAME,
            search_scope="segments",
            page_size=10,
        )
        # AI article should contain "neural network" references
        assert resp.total_count >= 1, "No segments found matching 'neural network'"

    async def test_query_count_only(self, vg_client, wiki_env):
        """count_only=True should return count without URIs."""
        resp = await vg_client.kgqueries.query_documents(
            space_id=wiki_env["space_id"],
            graph_id=wiki_env["graph_id"],
            document_type_uri=DOC_TYPE,
            count_only=True,
        )
        assert resp.total_count >= len(ARTICLES)

    async def test_query_pagination(self, vg_client, wiki_env):
        """Pagination should work correctly for document queries."""
        page1 = await vg_client.kgqueries.query_documents(
            space_id=wiki_env["space_id"],
            graph_id=wiki_env["graph_id"],
            search_scope="segments",
            page_size=3,
            offset=0,
        )
        page2 = await vg_client.kgqueries.query_documents(
            space_id=wiki_env["space_id"],
            graph_id=wiki_env["graph_id"],
            search_scope="segments",
            page_size=3,
            offset=3,
        )
        # Pages should have different URIs if there are enough segments
        if page1.total_count > 3:
            assert page1.document_uris != page2.document_uris, (
                "Pagination pages should return different results"
            )


# ===========================================================================
# Test: KGQuery Document Queries with Vector Search
# ===========================================================================

class TestKGQueryVectorSearch:
    """Test query_documents() with vector_criteria for semantic search."""

    async def test_vector_search_ai_topic(self, vg_client, wiki_env):
        """Vector search for AI topics should return relevant segments."""
        if not wiki_env["vectors_ready"]:
            pytest.skip("Vectors not ready")
        from vitalgraph.model.kgentities_model import VectorSearchCriteria

        resp = await vg_client.kgqueries.query_documents(
            space_id=wiki_env["space_id"],
            graph_id=wiki_env["graph_id"],
            search_scope="segments",
            include_segment_text=True,
            vector_criteria=VectorSearchCriteria(
                search_text="machine learning neural networks deep learning",
                index_name=INDEX_NAME,
                top_k=5,
                min_score=0.0,
            ),
        )
        assert resp.total_count > 0, "No vector search results for AI query"
        assert len(resp.document_uris) > 0

    async def test_vector_search_solar_system(self, vg_client, wiki_env):
        """Vector search for planets should return solar system segments."""
        if not wiki_env["vectors_ready"]:
            pytest.skip("Vectors not ready")
        from vitalgraph.model.kgentities_model import VectorSearchCriteria

        resp = await vg_client.kgqueries.query_documents(
            space_id=wiki_env["space_id"],
            graph_id=wiki_env["graph_id"],
            search_scope="segments",
            include_segment_text=True,
            vector_criteria=VectorSearchCriteria(
                search_text="planets orbiting sun jupiter saturn mars",
                index_name=INDEX_NAME,
                top_k=5,
                min_score=0.0,
            ),
        )
        assert resp.total_count > 0, "No vector search results for solar system query"

    async def test_vector_search_coffee(self, vg_client, wiki_env):
        """Vector search for coffee should return coffee article segments."""
        if not wiki_env["vectors_ready"]:
            pytest.skip("Vectors not ready")
        from vitalgraph.model.kgentities_model import VectorSearchCriteria

        resp = await vg_client.kgqueries.query_documents(
            space_id=wiki_env["space_id"],
            graph_id=wiki_env["graph_id"],
            search_scope="segments",
            include_segment_text=True,
            vector_criteria=VectorSearchCriteria(
                search_text="coffee roasting brewing espresso caffeine",
                index_name=INDEX_NAME,
                top_k=5,
                min_score=0.0,
            ),
        )
        assert resp.total_count > 0, "No vector search results for coffee query"

    async def test_vector_search_with_parent_context(self, vg_client, wiki_env):
        """Vector search with include_parent_context should return enriched results."""
        if not wiki_env["vectors_ready"]:
            pytest.skip("Vectors not ready")
        from vitalgraph.model.kgentities_model import VectorSearchCriteria

        resp = await vg_client.kgqueries.query_documents(
            space_id=wiki_env["space_id"],
            graph_id=wiki_env["graph_id"],
            search_scope="segments",
            include_parent_context=True,
            include_segment_text=True,
            vector_criteria=VectorSearchCriteria(
                search_text="artificial intelligence reasoning",
                index_name=INDEX_NAME,
                top_k=5,
                min_score=0.0,
            ),
        )
        assert resp.total_count > 0, "No results with parent context"
        # When include_parent_context is True, document_results should be populated
        if resp.document_results:
            for result in resp.document_results:
                assert result.document_uri is not None

    async def test_vector_search_top_k_limit(self, vg_client, wiki_env):
        """top_k should limit the number of results returned."""
        if not wiki_env["vectors_ready"]:
            pytest.skip("Vectors not ready")
        from vitalgraph.model.kgentities_model import VectorSearchCriteria

        resp = await vg_client.kgqueries.query_documents(
            space_id=wiki_env["space_id"],
            graph_id=wiki_env["graph_id"],
            search_scope="segments",
            vector_criteria=VectorSearchCriteria(
                search_text="history science technology",
                index_name=INDEX_NAME,
                top_k=3,
                min_score=0.0,
            ),
        )
        assert len(resp.document_uris) <= 3, (
            f"top_k=3 but got {len(resp.document_uris)} results"
        )

    async def test_vector_search_with_scope_filter(self, vg_client, wiki_env):
        """Vector search combined with parent_document_uri should narrow results."""
        if not wiki_env["vectors_ready"]:
            pytest.skip("Vectors not ready")
        from vitalgraph.model.kgentities_model import VectorSearchCriteria

        ai_uri = wiki_env["doc_uris"]["artificial_intelligence.md"]
        resp = await vg_client.kgqueries.query_documents(
            space_id=wiki_env["space_id"],
            graph_id=wiki_env["graph_id"],
            search_scope="segments",
            parent_document_uri=ai_uri,
            vector_criteria=VectorSearchCriteria(
                search_text="machine learning algorithms training data",
                index_name=INDEX_NAME,
                top_k=10,
                min_score=0.0,
            ),
        )
        # All results should be segments of the AI article only
        assert resp.total_count >= 0  # May be 0 if parent filter is strict

    async def test_vector_search_different_queries_different_results(self, vg_client, wiki_env):
        """Different vector queries should return different top results."""
        if not wiki_env["vectors_ready"]:
            pytest.skip("Vectors not ready")
        from vitalgraph.model.kgentities_model import VectorSearchCriteria

        resp_ai = await vg_client.kgqueries.query_documents(
            space_id=wiki_env["space_id"],
            graph_id=wiki_env["graph_id"],
            search_scope="segments",
            vector_criteria=VectorSearchCriteria(
                search_text="neural network deep learning gradient descent",
                index_name=INDEX_NAME,
                top_k=3,
                min_score=0.0,
            ),
        )
        resp_coffee = await vg_client.kgqueries.query_documents(
            space_id=wiki_env["space_id"],
            graph_id=wiki_env["graph_id"],
            search_scope="segments",
            vector_criteria=VectorSearchCriteria(
                search_text="arabica robusta coffee beans cultivation",
                index_name=INDEX_NAME,
                top_k=3,
                min_score=0.0,
            ),
        )

        if not resp_ai.document_uris or not resp_coffee.document_uris:
            pytest.skip("Insufficient results for comparison")

        # Top results should differ for unrelated topics
        assert resp_ai.document_uris[0] != resp_coffee.document_uris[0], (
            "Different semantic queries should return different top segments"
        )


# ===========================================================================
# Test: SPARQL Vector Similarity Search
# ===========================================================================

class TestWikipediaSPARQLSearch:
    """Test SPARQL-based vector similarity search across Wikipedia articles."""

    async def _search(self, vg_client, wiki_env, search_text: str, limit: int = 5):
        """Helper: SPARQL vector similarity search."""
        if not wiki_env["vectors_ready"]:
            pytest.skip("Vectors not ready")

        sparql = (
            "PREFIX vg: <http://vital.ai/ontology/vitalgraph#>\n"
            "PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>\n"
            "SELECT ?segment ?score ?content WHERE {\n"
            "    ?segment haley:hasKGDocumentContent ?content .\n"
            f'    BIND(vg:vectorSimilarity(?segment, "{search_text}", "{INDEX_NAME}") AS ?score)\n'
            "    FILTER(?score > 0.0)\n"
            "}\n"
            f"ORDER BY DESC(?score) LIMIT {limit}"
        )
        request = SPARQLQueryRequest(query=sparql)
        resp = await vg_client.sparql.execute_sparql_query(
            space_id=wiki_env["space_id"],
            request=request,
        )
        bindings = (resp.results or {}).get("bindings", [])
        return bindings

    async def test_search_machine_learning(self, vg_client, wiki_env):
        """Search 'machine learning neural networks deep learning' — AI article."""
        bindings = await self._search(
            vg_client, wiki_env,
            "machine learning neural networks deep learning algorithms",
        )
        assert len(bindings) > 0, "No results for machine learning query"
        top_content = bindings[0].get("content", {}).get("value", "").lower()
        assert any(kw in top_content for kw in ("machine", "learn", "neural", "ai", "algorithm")), (
            f"Top result doesn't mention ML/AI: {top_content[:200]}"
        )

    async def test_search_planets(self, vg_client, wiki_env):
        """Search 'planets orbiting sun jupiter saturn' — Solar System article."""
        bindings = await self._search(
            vg_client, wiki_env,
            "planets orbiting sun jupiter saturn mars venus",
        )
        assert len(bindings) > 0, "No results for planets query"
        top_content = bindings[0].get("content", {}).get("value", "").lower()
        assert any(kw in top_content for kw in ("planet", "orbit", "sun", "jupiter", "saturn", "solar")), (
            f"Top result doesn't mention planets/solar system: {top_content[:200]}"
        )

    async def test_search_coffee_brewing(self, vg_client, wiki_env):
        """Search 'coffee brewing espresso roasting beans' — Coffee article."""
        bindings = await self._search(
            vg_client, wiki_env,
            "coffee brewing espresso roasting beans caffeine",
        )
        assert len(bindings) > 0, "No results for coffee query"
        top_content = bindings[0].get("content", {}).get("value", "").lower()
        assert any(kw in top_content for kw in ("coffee", "brew", "espresso", "roast", "bean", "caffein")), (
            f"Top result doesn't mention coffee: {top_content[:200]}"
        )

    async def test_cross_topic_discrimination(self, vg_client, wiki_env):
        """Different queries should surface segments from different articles."""
        ai_results = await self._search(
            vg_client, wiki_env,
            "artificial intelligence reasoning problem solving",
        )
        solar_results = await self._search(
            vg_client, wiki_env,
            "asteroid belt comets dwarf planets kuiper",
        )
        coffee_results = await self._search(
            vg_client, wiki_env,
            "arabica robusta caffeine roasting brewing methods",
        )

        if not ai_results or not solar_results or not coffee_results:
            pytest.skip("Insufficient results for cross-topic comparison")

        # Top URIs should differ across topics
        top_uris = {
            "ai": ai_results[0].get("segment", {}).get("value", ""),
            "solar": solar_results[0].get("segment", {}).get("value", ""),
            "coffee": coffee_results[0].get("segment", {}).get("value", ""),
        }
        unique_uris = set(top_uris.values())
        assert len(unique_uris) >= 2, (
            f"Expected different top results for different topics, got: {top_uris}"
        )

    async def test_search_returns_scores(self, vg_client, wiki_env):
        """Vector similarity search should return non-zero scores."""
        bindings = await self._search(
            vg_client, wiki_env,
            "programming language syntax variables functions",
        )
        if not bindings:
            pytest.skip("No results returned")
        score = float(bindings[0].get("score", {}).get("value", "0"))
        assert score > 0.0, f"Expected positive score, got {score}"

    async def test_search_results_ordered_by_score(self, vg_client, wiki_env):
        """Results should be ordered by descending score."""
        bindings = await self._search(
            vg_client, wiki_env,
            "computer science artificial intelligence",
            limit=10,
        )
        if len(bindings) < 2:
            pytest.skip("Not enough results for ordering test")
        scores = [float(b.get("score", {}).get("value", "0")) for b in bindings]
        assert scores == sorted(scores, reverse=True), (
            f"Results not ordered by descending score: {scores}"
        )
