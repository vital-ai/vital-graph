"""Blank nodes end to end through a real space (issues/069 tests 1, 2 and 11).

The unit tests cover identity — one term uuid whatever the write path, one
convention for the stored text. These cover what a caller actually observes:
write a blank node, read it back, and see what DESCRIBE does when it meets one.

Test 11 is not a bug report. `_describe_triples` is a forward, non-recursive
CBD *by design*, so a described subject with a blank-node object returns a
dangling stub. Pinning it makes changing `_describe_triples` a deliberate act
rather than an accident, which is what `blank_nodes.md` §4.5 asks for.
"""

from __future__ import annotations

import pytest
from rdflib import BNode, Literal, URIRef

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

GRAPH = URIRef("urn:test:bnrt")
P = URIRef("urn:test:bnrt:p")
HAS = URIRef("urn:test:bnrt:hasThing")


class TestWriteReadRoundTrip:
    """Test 1 — write a blank node, read it back."""

    async def test_stored_text_has_no_prefix(
        self, test_space, space_impl, pg_conn
    ):
        """`term_text` holds the bare label; `_:` is serialization syntax only.

        The write path is the one that used to diverge: a blank node written
        through SPARQL UPDATE was stored `_:b1` while every other path stored
        `b1` (issues/065). Asserted on what is actually in the column.
        """
        await space_impl.add_rdf_quads_batch(
            test_space, [(BNode("rt1"), P, Literal("v"), GRAPH)])
        rows = await pg_conn.fetch(
            f"SELECT term_text FROM {test_space}_term WHERE term_type = 'B'")
        assert rows, "no blank-node term was written at all"
        for r in rows:
            assert not r["term_text"].startswith("_:"), (
                f"stored {r['term_text']!r} with the prefix; export would "
                f"double it to `_:_:...`, which is not valid N-Triples")

    async def test_the_blank_node_is_queryable_as_a_blank_node(
        self, test_space, space_impl, pg_conn
    ):
        """Round-trip: written, then found again with its type intact."""
        b = BNode("rt2")
        await space_impl.add_rdf_quads_batch(
            test_space, [(b, P, Literal("findme"), GRAPH)])
        n = await pg_conn.fetchval(f"""
            SELECT count(*) FROM {test_space}_rdf_quad q
            JOIN {test_space}_term s ON s.term_uuid = q.subject_uuid
            JOIN {test_space}_term o ON o.term_uuid = q.object_uuid
            WHERE s.term_type = 'B' AND o.term_text = 'findme'
        """)
        assert n == 1


class TestLoadUpdateAgreement:
    """Test 2 — the load path and the UPDATE path must agree on identity.

    The issue framed this as "load `_:b1`, then DELETE DATA the same triple;
    currently deletes nothing". The expected outcome has since changed: SPARQL
    forbids a blank node in DELETE DATA at all, so the correct behaviour is a
    REJECTION rather than a successful delete (issues/076 facet 1b). The
    underlying agreement is covered at the identity level in
    test_term_normalize.py; what is asserted here is that the operation is
    refused rather than silently matching nothing.
    """

    async def test_delete_data_with_a_blank_node_is_refused(
        self, test_space, space_impl, pg_conn
    ):
        b = BNode("agree1")
        await space_impl.add_rdf_quads_batch(
            test_space, [(b, P, Literal("keep"), GRAPH)])
        before = await pg_conn.fetchval(
            f"SELECT count(*) FROM {test_space}_rdf_quad")

        update = (f"DELETE DATA {{ GRAPH <{GRAPH}> "
                  f"{{ _:agree1 <{P}> \"keep\" }} }}")
        # Refusal can arrive two ways and both are correct: the sidecar's
        # parser rejects the construct outright, or emit_update's guard raises.
        # The test asserts REFUSED, not which layer refused.
        refused = False
        try:
            ok = await space_impl.execute_sparql_update(test_space, update)
            refused = not ok
        except Exception:
            refused = True

        after = await pg_conn.fetchval(
            f"SELECT count(*) FROM {test_space}_rdf_quad")
        assert after == before, (
            "DELETE DATA naming a blank node removed something; there is no "
            "way to name an existing blank node in a data block, so whatever "
            "it matched, it was not what the caller meant")
        assert refused, (
            "DELETE DATA with a blank node was accepted and silently deleted "
            "nothing — the failure mode this rule exists to prevent")


class TestDescribeWithABlankNodeObject:
    """Test 11 — pin the documented forward, non-recursive CBD."""

    async def test_a_blank_node_object_comes_back_as_a_stub(
        self, test_space, space_impl, pg_conn
    ):
        """DESCRIBE returns the subject's triples, not the blank node's.

        DESIGN, not defect: a recursive CBD can return unboundedly more of the
        graph for a well-connected node, so `_describe_triples` declines it.
        Sound for URI-only data, which is ours. If blank-node-structured RDF is
        ever ingested, DESCRIBE is a known casualty — this test is the record.
        """
        s = URIRef("urn:test:bnrt:described")
        b = BNode("stub1")
        await space_impl.add_rdf_quads_batch(test_space, [
            (s, HAS, b, GRAPH),
            (b, P, Literal("inner detail"), GRAPH),
        ])

        triples = await space_impl._describe_triples(test_space, [str(s)])
        # Keys are subject/predicate/object. An earlier version of this test
        # read t["o"], which is always absent — so every assertion passed
        # vacuously against an empty string. A harness reading the wrong key
        # tests nothing while looking green.
        objs = [t["object"]["value"] for t in triples if "object" in t]
        assert objs, "DESCRIBE returned nothing for the subject"

        # The subject's own triple IS returned, blank-node object and all.
        assert "stub1" in objs, (
            f"the blank-node object was not returned at all: {objs}")
        # And its type survives as a blank node, with the bare label.
        types = {t["object"]["type"] for t in triples if "object" in t}
        assert "bnode" in types
        assert not any(o.startswith("_:") for o in objs), (
            "the `_:` prefix leaked into a result value; the binding carries "
            "the bare label")

        # The blank node's OWN triple is absent — the dangling stub.
        assert "inner detail" not in objs, (
            "DESCRIBE expanded the blank node's own triples. That may be an "
            "improvement, but it is a deliberate change to _describe_triples "
            "and to the bounded-result guarantee in its docstring — update "
            "blank_nodes.md §4.5 with it.")
