"""Do the derived tables project blank nodes? (issues/069 test 12, issues/076)

The edge and frame_entity tables model URI-based binary relations. A blank node
in a subject or object position has no representation there, so issues/076 asks
whether the sync SKIPS such rows or mis-projects them.

That question was answered by reading and reasoning in an earlier pass, and
recorded as unverified for exactly that reason: neither sync_edge_table nor
sync_frame_entity_table mentions term_type anywhere, so "they skip blank nodes"
was an assumption about code that contains no such check.

This file establishes the actual behaviour. It asserts what IS, with the
consequence spelled out, so that changing it is a deliberate act.
"""

from __future__ import annotations

import pytest
from rdflib import BNode, URIRef

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

VC = "http://vital.ai/ontology/vital-core#"
EDGE_SRC = URIRef(f"{VC}hasEdgeSource")
EDGE_DST = URIRef(f"{VC}hasEdgeDestination")
GRAPH = URIRef("urn:test:bnode_derived")


class TestEdgeTableWithBlankNodes:

    async def test_an_edge_with_a_blank_node_endpoint(
        self, test_space, space_impl, pg_conn
    ):
        """An edge whose DESTINATION is a blank node.

        The edge table stores dest_node_uuid as a plain uuid with no type
        column, so a blank node projects into it indistinguishably from a URI —
        unless something filters on term_type, and nothing does.
        """
        from vitalgraph.db.sparql_sql.sync_edge_table import resync_edge_table

        edge = URIRef("urn:test:bnode_derived:edge1")
        src = URIRef("urn:test:bnode_derived:src")
        dst = BNode("bnedge1")
        await space_impl.add_rdf_quads_batch(test_space, [
            (edge, EDGE_SRC, src, GRAPH),
            (edge, EDGE_DST, dst, GRAPH),
        ])
        await resync_edge_table(pg_conn, test_space)

        n = await pg_conn.fetchval(f"""
            SELECT count(*) FROM {test_space}_edge e
            JOIN {test_space}_term t ON t.term_uuid = e.dest_node_uuid
            WHERE t.term_type = 'B'
        """)
        # MEASURED, not assumed: the edge table DOES project a blank-node
        # endpoint. Nothing in sync_edge_table filters on term_type, and
        # dest_node_uuid is a plain uuid column with no type beside it, so a
        # blank node becomes an ordinary edge endpoint.
        #
        # issues/076 assumed the opposite ("confirm the sync SKIPS blank-node
        # rows rather than mis-projecting them") and so did an earlier pass of
        # mine, by reading code that contains no such check. Asserting the real
        # behaviour makes changing it deliberate.
        #
        # It is defensible: an edge to a blank node IS an edge, and dropping it
        # would make the edge table an incomplete mirror of rdf_quad — the
        # failure mode issues/041 and the edge-integrity work exist to prevent.
        # What it means is that any consumer treating an edge endpoint as a
        # dereferenceable URI can be handed a blank node.
        assert n == 1, (
            f"expected the blank-node endpoint to be projected (measured "
            f"behaviour), got {n} rows")


class TestFrameEntityWithBlankNodes:

    async def test_frame_entity_is_unaffected_by_blank_nodes(
        self, test_space, space_impl, pg_conn
    ):
        """frame_entity indexes connector frames, which are keyed on entity
        slots. A blank node cannot carry the slot structure, so no row should
        appear regardless of what the edge table did."""
        from vitalgraph.db.sparql_sql.sync_frame_entity_table import (
            resync_frame_entity_table)

        before = await pg_conn.fetchval(
            f"SELECT count(*) FROM {test_space}_frame_entity")
        edge = URIRef("urn:test:bnode_derived:edge2")
        await space_impl.add_rdf_quads_batch(test_space, [
            (edge, EDGE_SRC, BNode("bnfe1"), GRAPH),
            (edge, EDGE_DST, BNode("bnfe2"), GRAPH),
        ])
        await resync_frame_entity_table(pg_conn, test_space)
        after = await pg_conn.fetchval(
            f"SELECT count(*) FROM {test_space}_frame_entity")
        assert after == before, (
            "a pair of blank-node endpoints produced a frame_entity row; that "
            "table indexes connector frames keyed on entity slots, which a "
            "blank node cannot carry")
