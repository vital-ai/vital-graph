"""API tests: Multi-Vector Search workflow.

Full lifecycle:
  1. Create real KGEntities in the graph
  2. Create two vector indexes with designed score distributions
  3. Upsert vectors for the entities
  4. Run multi-vector queries and validate ranking order
  5. Verify INTERSECT semantics (entity missing from one index → excluded)
  6. Verify min_score threshold filtering
  7. Verify fusion strategies return consistent results
  8. Cleanup
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from ai_haley_kg_domain.model.KGEntity import KGEntity

from vitalgraph.model.kgqueries_model import KGQueryCriteria
from vitalgraph.model.kgentities_model import (
    MultiVectorSearchCriteria,
    WeightedVectorInput,
)

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

# Two indexes for multi-vector fusion
INDEX_A = f"mv_idx_a_{uuid.uuid4().hex[:6]}"
INDEX_B = f"mv_idx_b_{uuid.uuid4().hex[:6]}"
DIMENSIONS = 4

# Unique entity URIs for this test module
NS = "urn:test:mv:"
ENTITY_1 = f"{NS}{uuid.uuid4().hex[:8]}"  # strong in A, weak in B
ENTITY_2 = f"{NS}{uuid.uuid4().hex[:8]}"  # weak in A, strong in B
ENTITY_3 = f"{NS}{uuid.uuid4().hex[:8]}"  # moderate in both
ENTITY_4 = f"{NS}{uuid.uuid4().hex[:8]}"  # ONLY in INDEX_A (tests INTERSECT)

# Query vectors
QUERY_A = [0.1, 0.2, 0.3, 0.9]
QUERY_B = [0.9, 0.3, 0.2, 0.1]

# INDEX_A embeddings — ENTITY_1 is nearest to QUERY_A
VEC_A_1 = [0.1, 0.2, 0.3, 0.85]   # cosine ~0.999 to QUERY_A
VEC_A_2 = [0.7, 0.6, 0.5, 0.4]    # cosine ~0.75 to QUERY_A
VEC_A_3 = [0.3, 0.3, 0.4, 0.6]    # cosine ~0.93 to QUERY_A
VEC_A_4 = [0.2, 0.2, 0.3, 0.8]    # cosine ~0.998 to QUERY_A (only in A)

# INDEX_B embeddings — ENTITY_2 is nearest to QUERY_B
VEC_B_1 = [0.5, 0.5, 0.5, 0.5]    # cosine ~0.77 to QUERY_B
VEC_B_2 = [0.85, 0.3, 0.2, 0.1]   # cosine ~0.999 to QUERY_B
VEC_B_3 = [0.6, 0.3, 0.3, 0.3]    # cosine ~0.92 to QUERY_B
# ENTITY_4 intentionally NOT in INDEX_B


def _make_entity(uri: str, name: str) -> KGEntity:
    e = KGEntity()
    e.URI = uri
    e.name = name
    return e


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def mv_env(vg_client, test_space, test_graph):
    """Create real entities + two vector indexes with designed vectors."""
    # Create real KGEntities in the quad store
    entities = [
        _make_entity(ENTITY_1, "MultiVec Entity Alpha"),
        _make_entity(ENTITY_2, "MultiVec Entity Beta"),
        _make_entity(ENTITY_3, "MultiVec Entity Gamma"),
        _make_entity(ENTITY_4, "MultiVec Entity Delta"),
    ]
    await vg_client.kgentities.create_kgentities(
        space_id=test_space, graph_id=test_graph, objects=entities
    )

    # Create vector indexes
    await vg_client.vector_indexes.create_index(
        space_id=test_space,
        index_name=INDEX_A,
        dimensions=DIMENSIONS,
        distance_metric="cosine",
        provider="vitalsigns",
        description="Multi-vector test index A",
    )
    await vg_client.vector_indexes.create_index(
        space_id=test_space,
        index_name=INDEX_B,
        dimensions=DIMENSIONS,
        distance_metric="cosine",
        provider="vitalsigns",
        description="Multi-vector test index B",
    )

    # Upsert vectors into INDEX_A (all 4 entities)
    await vg_client.vector_indexes.upsert_vectors(
        space_id=test_space,
        index_name=INDEX_A,
        vectors=[
            {"subject_uri": ENTITY_1, "graph_uri": test_graph, "embedding": VEC_A_1},
            {"subject_uri": ENTITY_2, "graph_uri": test_graph, "embedding": VEC_A_2},
            {"subject_uri": ENTITY_3, "graph_uri": test_graph, "embedding": VEC_A_3},
            {"subject_uri": ENTITY_4, "graph_uri": test_graph, "embedding": VEC_A_4},
        ],
    )

    # Upsert vectors into INDEX_B (only 3 entities — ENTITY_4 missing)
    await vg_client.vector_indexes.upsert_vectors(
        space_id=test_space,
        index_name=INDEX_B,
        vectors=[
            {"subject_uri": ENTITY_1, "graph_uri": test_graph, "embedding": VEC_B_1},
            {"subject_uri": ENTITY_2, "graph_uri": test_graph, "embedding": VEC_B_2},
            {"subject_uri": ENTITY_3, "graph_uri": test_graph, "embedding": VEC_B_3},
        ],
    )

    yield {
        "space_id": test_space,
        "graph_id": test_graph,
        "index_a": INDEX_A,
        "index_b": INDEX_B,
    }

    # Cleanup
    for uri in [ENTITY_1, ENTITY_2, ENTITY_3, ENTITY_4]:
        try:
            await vg_client.kgentities.delete_kgentity(test_space, test_graph, uri)
        except Exception:
            pass
    for idx in [INDEX_A, INDEX_B]:
        try:
            await vg_client.vector_indexes.delete_index(test_space, idx)
        except Exception:
            pass


def _query(mv_env, weight_a: float, weight_b: float, **kwargs) -> KGQueryCriteria:
    """Helper to build a multi-vector query criteria."""
    return KGQueryCriteria(
        query_type="entity",
        multi_vector_criteria=MultiVectorSearchCriteria(
            vectors=[
                WeightedVectorInput(
                    vector=str(QUERY_A), index_name=mv_env["index_a"], weight=weight_a
                ),
                WeightedVectorInput(
                    vector=str(QUERY_B), index_name=mv_env["index_b"], weight=weight_b
                ),
            ],
            top_k=kwargs.get("top_k", 10),
            min_score=kwargs.get("min_score"),
            fusion_strategy=kwargs.get("fusion_strategy", "weighted_sum"),
            oversample_factor=kwargs.get("oversample_factor", 5),
        ),
    )


class TestMultiVectorWeightedSearch:
    """Multi-vector queries with weight-driven ranking validation."""

    async def test_equal_weights_returns_all_intersected(self, vg_client, mv_env):
        """Equal weights — returns entities present in BOTH indexes (not ENTITY_4)."""
        resp = await vg_client.kgqueries.query_connections(
            space_id=mv_env["space_id"],
            graph_id=mv_env["graph_id"],
            criteria=_query(mv_env, 1.0, 1.0),
            page_size=10,
        )
        assert resp is not None
        uris = resp.entity_uris or []
        assert len(uris) == 3, f"Expected 3 entities (INTERSECT), got {len(uris)}: {uris}"
        assert ENTITY_4 not in uris, "ENTITY_4 should be excluded (missing from INDEX_B)"
        # All three intersected entities should be present
        assert ENTITY_1 in uris
        assert ENTITY_2 in uris
        assert ENTITY_3 in uris

    async def test_heavy_weight_on_index_a_ranks_entity1_first(self, vg_client, mv_env):
        """Weight 0.95 on INDEX_A — ENTITY_1 (nearest in A) should rank first."""
        resp = await vg_client.kgqueries.query_connections(
            space_id=mv_env["space_id"],
            graph_id=mv_env["graph_id"],
            criteria=_query(mv_env, 0.95, 0.05),
            page_size=10,
        )
        uris = resp.entity_uris or []
        assert len(uris) >= 1, "Expected at least 1 result"
        assert uris[0] == ENTITY_1, (
            f"ENTITY_1 should rank first with heavy A-weight, got: {uris}"
        )

    async def test_heavy_weight_on_index_b_ranks_entity2_first(self, vg_client, mv_env):
        """Weight 0.95 on INDEX_B — ENTITY_2 (nearest in B) should rank first."""
        resp = await vg_client.kgqueries.query_connections(
            space_id=mv_env["space_id"],
            graph_id=mv_env["graph_id"],
            criteria=_query(mv_env, 0.05, 0.95),
            page_size=10,
        )
        uris = resp.entity_uris or []
        assert len(uris) >= 1, "Expected at least 1 result"
        assert uris[0] == ENTITY_2, (
            f"ENTITY_2 should rank first with heavy B-weight, got: {uris}"
        )


class TestMultiVectorFusionStrategies:
    """All fusion strategies return valid ranked results."""

    async def test_weighted_sum_returns_results(self, vg_client, mv_env):
        """weighted_sum — default, returns 3 intersected entities."""
        resp = await vg_client.kgqueries.query_connections(
            space_id=mv_env["space_id"],
            graph_id=mv_env["graph_id"],
            criteria=_query(mv_env, 0.5, 0.5, fusion_strategy="weighted_sum"),
            page_size=10,
        )
        uris = resp.entity_uris or []
        assert len(uris) == 3

    async def test_relative_score_returns_results(self, vg_client, mv_env):
        """relative_score — normalizes per-index, returns 3 entities."""
        resp = await vg_client.kgqueries.query_connections(
            space_id=mv_env["space_id"],
            graph_id=mv_env["graph_id"],
            criteria=_query(mv_env, 0.5, 0.5, fusion_strategy="relative_score"),
            page_size=10,
        )
        uris = resp.entity_uris or []
        assert len(uris) == 3

    async def test_ranked_fusion_returns_results(self, vg_client, mv_env):
        """ranked (RRF) — reciprocal rank fusion, returns 3 entities."""
        resp = await vg_client.kgqueries.query_connections(
            space_id=mv_env["space_id"],
            graph_id=mv_env["graph_id"],
            criteria=_query(mv_env, 0.5, 0.5, fusion_strategy="ranked"),
            page_size=10,
        )
        uris = resp.entity_uris or []
        assert len(uris) == 3


class TestMultiVectorThresholdAndSemantics:
    """Score thresholds, INTERSECT exclusion, and oversample."""

    async def test_intersect_excludes_entity4(self, vg_client, mv_env):
        """ENTITY_4 only in INDEX_A — must be excluded from results."""
        resp = await vg_client.kgqueries.query_connections(
            space_id=mv_env["space_id"],
            graph_id=mv_env["graph_id"],
            criteria=_query(mv_env, 0.5, 0.5),
            page_size=10,
        )
        uris = resp.entity_uris or []
        assert ENTITY_4 not in uris, (
            f"ENTITY_4 should be excluded by INTERSECT semantics, got: {uris}"
        )

    async def test_high_min_score_reduces_results(self, vg_client, mv_env):
        """min_score=0.99 — only the very best match(es) survive."""
        resp_all = await vg_client.kgqueries.query_connections(
            space_id=mv_env["space_id"],
            graph_id=mv_env["graph_id"],
            criteria=_query(mv_env, 0.5, 0.5),
            page_size=10,
        )
        resp_filtered = await vg_client.kgqueries.query_connections(
            space_id=mv_env["space_id"],
            graph_id=mv_env["graph_id"],
            criteria=_query(mv_env, 0.5, 0.5, min_score=0.99),
            page_size=10,
        )
        all_count = len(resp_all.entity_uris or [])
        filtered_count = len(resp_filtered.entity_uris or [])
        assert filtered_count < all_count, (
            f"min_score=0.99 should reduce results: {filtered_count} vs {all_count}"
        )

    async def test_oversample_factor_does_not_change_result_set(self, vg_client, mv_env):
        """Oversample factor affects candidate pool but not final results (small dataset)."""
        resp_default = await vg_client.kgqueries.query_connections(
            space_id=mv_env["space_id"],
            graph_id=mv_env["graph_id"],
            criteria=_query(mv_env, 0.5, 0.5, oversample_factor=5),
            page_size=10,
        )
        resp_high = await vg_client.kgqueries.query_connections(
            space_id=mv_env["space_id"],
            graph_id=mv_env["graph_id"],
            criteria=_query(mv_env, 0.5, 0.5, oversample_factor=20),
            page_size=10,
        )
        # Same small dataset → same results regardless of oversample
        assert set(resp_default.entity_uris or []) == set(resp_high.entity_uris or [])
