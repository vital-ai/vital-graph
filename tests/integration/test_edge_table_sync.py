"""Integration tests: {space}_edge stays in sync with rdf_quad on insert.

The edge table is a denormalized mirror of the hasEdgeSource + hasEdgeDestination
quad pair, consumed by the edge-table query rewrite. `add_rdf_quads_batch` must
keep it in sync — including the tricky case where an edge's source and
destination quads arrive in *different* batches (the second batch carries the
edge_uuid as a subject, so its sync completes the pair).

Requires PostgreSQL (no sidecar needed — these exercise the write path directly).

See planning/planning_performance/edge_table_integrity_bug.md
"""

from __future__ import annotations

import pytest
from rdflib import URIRef

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

HAS_EDGE_SOURCE = URIRef("http://vital.ai/ontology/vital-core#hasEdgeSource")
HAS_EDGE_DEST = URIRef("http://vital.ai/ontology/vital-core#hasEdgeDestination")
GRAPH = URIRef("urn:test:edge_sync_graph")


async def _edge_row(conn, space_id: str, edge_uri: str):
    """Return (source_text, dest_text) for the edge, or None if absent."""
    return await conn.fetchrow(
        f"""
        SELECT ts.term_text AS src, td.term_text AS dst
        FROM {space_id}_edge e
        JOIN {space_id}_term te ON te.term_uuid = e.edge_uuid
        JOIN {space_id}_term ts ON ts.term_uuid = e.source_node_uuid
        JOIN {space_id}_term td ON td.term_uuid = e.dest_node_uuid
        WHERE te.term_text = $1
        """,
        edge_uri,
    )


class TestEdgeTableSync:
    async def test_edge_sync_within_single_batch(
        self, test_space, space_impl, pg_conn
    ):
        """Both source + destination quads in one batch → edge row appears."""
        edge = URIRef("urn:test:edge_single")
        src = URIRef("urn:test:src_single")
        dst = URIRef("urn:test:dst_single")

        await space_impl.add_rdf_quads_batch(test_space, [
            (edge, HAS_EDGE_SOURCE, src, GRAPH),
            (edge, HAS_EDGE_DEST, dst, GRAPH),
        ])

        row = await _edge_row(pg_conn, test_space, str(edge))
        assert row is not None, "edge row missing after single-batch insert"
        assert row["src"] == str(src)
        assert row["dst"] == str(dst)

    async def test_edge_sync_over_chunk_boundary(self, space_impl, make_space):
        """>SYNC_CHUNK edges in one bulk insert sync correctly across chunks."""
        from vitalgraph.db.sparql_sql.sync_edge_table import SYNC_CHUNK

        n = SYNC_CHUNK + 500  # -> 2 aux-sync chunks
        sid = await make_space()
        quads = []
        for i in range(n):
            e = URIRef(f"urn:test:ce:{i}")
            quads.append((e, HAS_EDGE_SOURCE, URIRef(f"urn:test:cs:{i}"), GRAPH))
            quads.append((e, HAS_EDGE_DEST, URIRef(f"urn:test:cd:{i}"), GRAPH))
        await space_impl.add_rdf_quads_batch_bulk(sid, quads)
        async with space_impl.db_impl.connection_pool.acquire() as conn:
            cnt = await conn.fetchval(f"SELECT count(*) FROM {sid}_edge")
        assert cnt == n, cnt  # every edge synced, no chunk dropped/double-counted

    async def test_edge_sync_across_batches(
        self, test_space, space_impl, pg_conn
    ):
        """Source in batch 1, destination in batch 2 → edge row appears only
        after the batch that completes the pair (regression guard for the
        cross-batch sync path)."""
        edge = URIRef("urn:test:edge_split")
        src = URIRef("urn:test:src_split")
        dst = URIRef("urn:test:dst_split")

        # Batch 1: only the source side — the edge is incomplete, so no row yet.
        await space_impl.add_rdf_quads_batch(test_space, [
            (edge, HAS_EDGE_SOURCE, src, GRAPH),
        ])
        assert await _edge_row(pg_conn, test_space, str(edge)) is None, \
            "edge row should not exist until the destination quad is inserted"

        # Batch 2: the destination side — subject is the edge_uuid, so this
        # batch's sync scans it and finds the (already-committed) source too.
        await space_impl.add_rdf_quads_batch(test_space, [
            (edge, HAS_EDGE_DEST, dst, GRAPH),
        ])

        row = await _edge_row(pg_conn, test_space, str(edge))
        assert row is not None, "edge row missing after cross-batch completion"
        assert row["src"] == str(src)
        assert row["dst"] == str(dst)

    async def test_edge_sync_single_quad_path(
        self, test_space, space_impl, pg_conn
    ):
        """add_rdf_quad (single-quad path) also syncs the edge table."""
        edge = URIRef("urn:test:edge_one")
        src = URIRef("urn:test:src_one")
        dst = URIRef("urn:test:dst_one")

        await space_impl.add_rdf_quad(test_space, (edge, HAS_EDGE_SOURCE, src, GRAPH))
        assert await _edge_row(pg_conn, test_space, str(edge)) is None
        await space_impl.add_rdf_quad(test_space, (edge, HAS_EDGE_DEST, dst, GRAPH))

        row = await _edge_row(pg_conn, test_space, str(edge))
        assert row is not None
        assert row["src"] == str(src)
        assert row["dst"] == str(dst)

    async def test_backfill_repairs_drift(
        self, test_space, space_impl, pg_conn
    ):
        """edge_table_drift detects a stale edge table and backfill_edge_table
        repairs it by adding only the missing edges (the maintenance self-heal
        path). Simulates drift by deleting an edge row that rdf_quad still has."""
        from vitalgraph.db.sparql_sql.sync_edge_table import (
            edge_table_drift, backfill_edge_table,
        )

        edge = URIRef("urn:test:edge_drift")
        src = URIRef("urn:test:src_drift")
        dst = URIRef("urn:test:dst_drift")
        await space_impl.add_rdf_quads_batch(test_space, [
            (edge, HAS_EDGE_SOURCE, src, GRAPH),
            (edge, HAS_EDGE_DEST, dst, GRAPH),
        ])
        assert await _edge_row(pg_conn, test_space, str(edge)) is not None

        # Simulate drift: delete the edge row while the quads remain.
        await pg_conn.execute(
            f"DELETE FROM {test_space}_edge WHERE edge_uuid IN "
            f"(SELECT term_uuid FROM {test_space}_term WHERE term_text = $1)",
            str(edge),
        )
        assert await _edge_row(pg_conn, test_space, str(edge)) is None
        src_quads, edge_rows = await edge_table_drift(pg_conn, test_space)
        assert src_quads > edge_rows, "drift should be detected (more edge quads than rows)"

        # Backfill adds the missing edge back without a TRUNCATE.
        added = await backfill_edge_table(pg_conn, test_space)
        assert added >= 1
        row = await _edge_row(pg_conn, test_space, str(edge))
        assert row is not None and row["src"] == str(src) and row["dst"] == str(dst)


class TestEdgeSyncSparqlUpdate:
    """The SPARQL UPDATE path (execute_sparql_update) syncs the edge table inline."""

    async def test_sparql_insert_data_syncs_edge(
        self, test_space, space_impl, pg_conn
    ):
        edge, src, dst = "urn:test:edge_su1", "urn:test:src_su1", "urn:test:dst_su1"
        ok = await space_impl.execute_sparql_update(test_space, f"""
            INSERT DATA {{ GRAPH <{GRAPH}> {{
              <{edge}> <{HAS_EDGE_SOURCE}> <{src}> .
              <{edge}> <{HAS_EDGE_DEST}> <{dst}> .
            }} }}""")
        assert ok
        row = await _edge_row(pg_conn, test_space, edge)
        assert row is not None, "edge row missing after SPARQL INSERT DATA"
        assert row["src"] == src and row["dst"] == dst

    async def test_sparql_delete_data_removes_orphan_edge(
        self, test_space, space_impl, pg_conn
    ):
        edge, src, dst = "urn:test:edge_su2", "urn:test:src_su2", "urn:test:dst_su2"
        await space_impl.execute_sparql_update(test_space, f"""
            INSERT DATA {{ GRAPH <{GRAPH}> {{
              <{edge}> <{HAS_EDGE_SOURCE}> <{src}> .
              <{edge}> <{HAS_EDGE_DEST}> <{dst}> .
            }} }}""")
        assert await _edge_row(pg_conn, test_space, edge) is not None

        # Delete the destination quad → the edge is now incomplete → row removed.
        await space_impl.execute_sparql_update(test_space, f"""
            DELETE DATA {{ GRAPH <{GRAPH}> {{
              <{edge}> <{HAS_EDGE_DEST}> <{dst}> .
            }} }}""")
        assert await _edge_row(pg_conn, test_space, edge) is None, \
            "orphaned edge row should be removed after SPARQL DELETE DATA"
