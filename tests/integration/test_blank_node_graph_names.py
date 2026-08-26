"""A blank node in the GRAPH position — what happens today.

`named_graph_semantics` §4.5. N-Quads permits a blank node as the graph name.
The doc recorded this as untested, "likely wrong, low impact, and worth a test
before it is worth a fix". This is that test: it pins the CURRENT behaviour and
names what is wrong about it, so a fix has something to change and a regression
has something to trip.

WHAT IS WRONG. The two write paths type the graph term BY CLASS -- a `BNode`
graph becomes a `'B'` term -- while `remove_rdf_quad` forces `'U'`:

    add_rdf_quad        g_uuid = await self._ensure_term(conn, t, g)   # by class
    add_rdf_quads_batch g_uuid = await self._ensure_term(conn, t, g)   # by class
    remove_rdf_quad     g_uuid = _generate_term_uuid(g, 'U')           # forced

`term_uuid` is a UUIDv5 over `(text, type, ...)`, so those are two different
terms for one graph. A quad written into a blank-node graph therefore cannot be
removed through `remove_rdf_quad`: it computes a uuid nothing was stored under,
matches no row, and reports success.

That asymmetry is the finding. Whether a blank-node graph name SHOULD be
supported at all is a separate question -- the doc leans no, and the write path
predating this was documented as forcing `'U'` deliberately.
"""

from __future__ import annotations

import pytest
from rdflib import BNode, Literal, URIRef

from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

P = URIRef("urn:test:bng:p")


class TestTheTwoPathsDisagreeAboutTheGraphTerm:
    """The uuids differ, so insert and remove address different graphs."""

    def test_forcing_U_and_typing_by_class_give_different_uuids(self):
        """No infrastructure needed — this is arithmetic over the term key.

        `str(BNode("g1"))` is the bare label `g1`, matching the "term_text holds
        the bare value" convention (issues/065). Typed `'U'` it is one term,
        typed `'B'` another.
        """
        label = str(BNode("g1"))
        assert label == "g1", "the bare-label convention changed"
        as_uri = _generate_term_uuid(label, "U")
        as_bnode = _generate_term_uuid(label, "B")
        assert as_uri != as_bnode, (
            "if these ever agree, the insert/remove asymmetry below is moot "
            "and this whole file can go")


class TestBlankNodeGraphRoundTrip:
    """What actually lands, and what comes back."""

    async def test_a_blank_node_graph_is_stored_as_a_blank_node_term(
        self, test_space, space_impl, pg_conn
    ):
        """The write path types by class, so the graph term is 'B'.

        Recording this rather than asserting it is RIGHT. §2 of the doc says
        the write path types graph terms `'U'`; that is true of the bulk COPY
        path and not of these two, which is itself the inconsistency.
        """
        g = BNode("bng1")
        await space_impl.add_rdf_quads_batch(
            test_space, [(URIRef("urn:test:bng:s1"), P, Literal("v"), g)])
        row = await pg_conn.fetchrow(
            f"""SELECT t.term_type FROM {test_space}_rdf_quad q
                JOIN {test_space}_term t ON t.term_uuid = q.context_uuid
                WHERE t.term_text = 'bng1'""")
        assert row is not None, "the quad did not land in any graph named bng1"
        assert row["term_type"] == "B", (
            f"graph term stored as {row['term_type']!r}; this test encodes 'B' "
            f"because that is what `_ensure_term` produces for a BNode")

    async def test_remove_cannot_reach_a_blank_node_graph(
        self, test_space, space_impl, pg_conn
    ):
        """THE defect. Written as 'B', removed as 'U', so nothing is removed.

        `remove_rdf_quad` takes strings, so it cannot know the graph was a
        blank node, and forces `'U'`. It matches no row and returns without
        complaint -- a silent no-op, which is the shape worth catching.
        """
        g = BNode("bng2")
        s = URIRef("urn:test:bng:s2")
        await space_impl.add_rdf_quads_batch(
            test_space, [(s, P, Literal("v"), g)])

        def _count():
            return pg_conn.fetchval(
                f"""SELECT count(*) FROM {test_space}_rdf_quad q
                    JOIN {test_space}_term t ON t.term_uuid = q.context_uuid
                    WHERE t.term_text = 'bng2'""")

        assert await _count() == 1, "setup failed: the quad is not there"
        # Raises rather than silently removing nothing (`issues/135`).
        with pytest.raises(TypeError):
            await space_impl.remove_rdf_quad(
                test_space, str(s), str(P), "v", str(g))
        assert await _count() == 1, (
            "a BARE STRING reached the blank-node graph. It should not: "
            "`bng2` is a blank node label or a literal and nothing in the "
            "characters says which, so `_term_type_of` types it 'U'. A caller "
            "who means the blank node passes the TERM -- see the test below.")

    async def test_remove_reaches_it_when_the_caller_passes_the_term(
        self, test_space, space_impl, pg_conn
    ):
        """The fix (`issues/135`). Types come from the term, in every position.

        Subject, predicate and graph used to be hardcoded `'U'` in both batch
        delete paths and in `remove_rdf_quad`, while the object beside them was
        typed from its class. So a blank-node graph went in as `'B'` and was
        looked up as `'U'`: no row matched and the delete reported success.

        This is the case production takes -- `get_existing_quads_for_uris`
        returns rdflib Identifiers, so the live delete path always has terms.
        """
        g = BNode("bng3")
        s = URIRef("urn:test:bng:s3")
        await space_impl.add_rdf_quads_batch(
            test_space, [(s, P, Literal("v"), g)])

        def _count():
            return pg_conn.fetchval(
                f"""SELECT count(*) FROM {test_space}_rdf_quad q
                    JOIN {test_space}_term t ON t.term_uuid = q.context_uuid
                    WHERE t.term_text = 'bng3'""")

        assert await _count() == 1, "setup failed: the quad is not there"
        await space_impl.remove_rdf_quad(test_space, s, P, Literal("v"), g)
        assert await _count() == 0, (
            "the quad survived: some position is still typing the graph by "
            "something other than the term")
