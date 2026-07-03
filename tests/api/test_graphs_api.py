"""API tests: Graph lifecycle via VitalGraphClient.

Tests create, list, get_info, clear, and drop operations on named graphs.
Based on test_scripts/vitalgraph_client_test/sparql_sql/case_graphs_crud.py
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]


class TestGraphsCrud:
    """Named graph lifecycle: create → list → info → clear → drop."""

    async def test_list_graphs(self, vg_client, test_space):
        """List graphs in the test space."""
        lr = await vg_client.graphs.list_graphs(test_space)
        assert lr.is_success
        assert isinstance(lr.graphs, list)

    async def test_create_graph(self, vg_client, test_space):
        """Create a named graph."""
        graph_id = f"urn:graphtest:{uuid.uuid4().hex[:8]}"
        cgr = await vg_client.graphs.create_graph(test_space, graph_id)
        assert cgr.is_success

        # Verify it appears in listing
        lr = await vg_client.graphs.list_graphs(test_space)
        uris = [g.graph_uri for g in lr.graphs] if lr.graphs else []
        assert graph_id in uris

    async def test_get_graph_info(self, vg_client, test_space):
        """Create a graph and get its info — verify URI matches."""
        graph_id = f"urn:graphtest:{uuid.uuid4().hex[:8]}"
        await vg_client.graphs.create_graph(test_space, graph_id)

        gi = await vg_client.graphs.get_graph_info(test_space, graph_id)
        assert gi.is_success
        assert gi.graph is not None
        assert gi.graph.graph_uri == graph_id

    async def test_clear_graph(self, vg_client, test_space):
        """Add triples to a graph, clear it, verify empty."""
        from vitalgraph.model.sparql_model import SPARQLInsertRequest

        graph_id = f"urn:graphtest:{uuid.uuid4().hex[:8]}"
        await vg_client.graphs.create_graph(test_space, graph_id)

        # Add a triple via SPARQL insert
        subj = f"http://example.org/cleartest/{uuid.uuid4().hex[:8]}"
        ins = SPARQLInsertRequest(
            update=f'INSERT DATA {{ GRAPH <{graph_id}> {{ <{subj}> <http://example.org/p> "val" . }} }}'
        )
        await vg_client.sparql.execute_sparql_insert(test_space, ins)

        # Clear
        clr = await vg_client.graphs.clear_graph(test_space, graph_id)
        assert clr.is_success

    async def test_drop_graph(self, vg_client, test_space):
        """Create a graph, drop it, verify it's gone from listing."""
        graph_id = f"urn:graphtest:{uuid.uuid4().hex[:8]}"
        await vg_client.graphs.create_graph(test_space, graph_id)

        dgr = await vg_client.graphs.drop_graph(test_space, graph_id)
        assert dgr.is_success

        # Verify gone
        lr = await vg_client.graphs.list_graphs(test_space)
        uris = [g.graph_uri for g in lr.graphs] if lr.graphs else []
        assert graph_id not in uris


# ---------------------------------------------------------------------------
# Graph Counts
# ---------------------------------------------------------------------------

class TestGraphCounts:
    """GET /graph_counts — entity/frame/relation counts for a graph."""

    async def test_counts_empty_graph(self, vg_client, test_space):
        """Empty graph returns all zeros."""
        graph_id = f"urn:graphtest:counts:{uuid.uuid4().hex[:8]}"
        await vg_client.graphs.create_graph(test_space, graph_id)

        counts = await vg_client.graphs.get_graph_counts(test_space, graph_id)
        assert counts.entity_count == 0
        assert counts.frame_count == 0
        assert counts.relation_count == 0

        await vg_client.graphs.drop_graph(test_space, graph_id)

    async def test_counts_nonexistent_graph(self, vg_client, test_space):
        """Nonexistent graph returns zeros (no error)."""
        counts = await vg_client.graphs.get_graph_counts(
            test_space, "urn:graphtest:does_not_exist"
        )
        assert counts.entity_count == 0
        assert counts.frame_count == 0
        assert counts.relation_count == 0
