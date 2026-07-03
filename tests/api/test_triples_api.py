"""API tests: Triples CRUD via VitalGraphClient.

Tests add, list, filter (subject/predicate/object_filter), and delete triples.
Based on test_scripts/vitalgraph_client_test/sparql_sql/case_triples_crud.py
"""

from __future__ import annotations

import pytest

from vitalgraph.model.quad_model import Quad, QuadRequest

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

NS = "http://example.org/apitest/triples/"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
XSD_INT = "http://www.w3.org/2001/XMLSchema#integer"


class TestTriplesCrud:
    """Triple lifecycle: add → list → filter → delete → verify."""

    async def test_add_triples(self, vg_client, test_space, test_graph):
        """Add 7 triples (2 persons with type/name/age + 1 knows edge)."""
        alice = f"{NS}person/alice"
        bob = f"{NS}person/bob"

        quads = QuadRequest(quads=[
            Quad(s=f"<{alice}>", p=f"<{RDF_TYPE}>", o=f"<{NS}Person>", g=f"<{test_graph}>"),
            Quad(s=f"<{alice}>", p=f"<{NS}name>", o='"Alice"', g=f"<{test_graph}>"),
            Quad(s=f"<{alice}>", p=f"<{NS}age>", o=f'"30"^^<{XSD_INT}>', g=f"<{test_graph}>"),
            Quad(s=f"<{bob}>", p=f"<{RDF_TYPE}>", o=f"<{NS}Person>", g=f"<{test_graph}>"),
            Quad(s=f"<{bob}>", p=f"<{NS}name>", o='"Bob"', g=f"<{test_graph}>"),
            Quad(s=f"<{bob}>", p=f"<{NS}age>", o=f'"25"^^<{XSD_INT}>', g=f"<{test_graph}>"),
            Quad(s=f"<{alice}>", p=f"<{NS}knows>", o=f"<{bob}>", g=f"<{test_graph}>"),
        ])

        ar = await vg_client.triples.add_triples(test_space, test_graph, quads)
        assert ar.success, f"Add triples failed: {ar.message}"

    async def test_list_all_triples(self, vg_client, test_space, test_graph):
        """List all triples — should have at least 7."""
        lr = await vg_client.triples.list_triples(test_space, test_graph, page_size=50)
        assert lr.success
        assert lr.total_count >= 7

    async def test_filter_by_subject(self, vg_client, test_space, test_graph):
        """Filter by subject (alice) — type + name + age + knows = 4."""
        alice = f"{NS}person/alice"
        fr = await vg_client.triples.list_triples(
            test_space, test_graph, page_size=50, subject=alice
        )
        assert fr.success
        assert fr.total_count >= 4

    async def test_filter_by_predicate(self, vg_client, test_space, test_graph):
        """Filter by predicate (rdf:type) — alice + bob = 2."""
        fr = await vg_client.triples.list_triples(
            test_space, test_graph, page_size=50, predicate=RDF_TYPE
        )
        assert fr.success
        assert fr.total_count >= 2

    async def test_filter_by_object(self, vg_client, test_space, test_graph):
        """Filter by object_filter keyword 'Alice' — at least 1 match."""
        fr = await vg_client.triples.list_triples(
            test_space, test_graph, page_size=50, object_filter="Alice"
        )
        assert fr.success
        assert fr.total_count >= 1

    async def test_delete_by_subject(self, vg_client, test_space, test_graph):
        """Delete bob's triples, verify 0 remain for bob."""
        bob = f"{NS}person/bob"
        dr = await vg_client.triples.delete_triples(test_space, test_graph, subject=bob)
        assert dr.success

        # Verify bob gone
        fr = await vg_client.triples.list_triples(
            test_space, test_graph, page_size=50, subject=bob
        )
        assert fr.success
        assert fr.total_count == 0

    async def test_delete_by_predicate(self, vg_client, test_space, test_graph):
        """Delete 'knows' predicate triples."""
        dr = await vg_client.triples.delete_triples(
            test_space, test_graph, predicate=f"{NS}knows"
        )
        assert dr.success

    async def test_delete_remaining_and_verify_empty(self, vg_client, test_space, test_graph):
        """Delete alice triples, verify graph has 0 triples."""
        alice = f"{NS}person/alice"
        dr = await vg_client.triples.delete_triples(test_space, test_graph, subject=alice)
        assert dr.success

        lr = await vg_client.triples.list_triples(test_space, test_graph, page_size=50)
        assert lr.success
        assert lr.total_count == 0
