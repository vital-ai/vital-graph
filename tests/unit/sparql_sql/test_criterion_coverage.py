"""Which criterion shapes can be estimated, and which are declined on purpose.

Every selectivity gate in the pipeline — the traversal decision, the semi-join
gate, join ordering — reads these statistics, and a criterion nothing measures
reads as UNMEASURED, which `emit_bgp` treats as "comparison unsafe". Two whole
families were silently in that state until 2026-08-14.

Audited against the traversal fixture, which carries all six datatypes:

    integer  >=            range stat
    double   >=            range stat
    dateTime >=            range stat
    string   IN            in/eq stat   38,368  exact
    uri      IN            in/eq stat   23,719
    string   CONTAINS      text stat
    string   = (FILTER)    in/eq stat   21,852  exact
    uri      = (FILTER)    in/eq stat   11,823
    boolean  = (FILTER)    NOT measured -- deliberate, see below
    string / boolean / uri written INLINE in the triple
                           constant pair -- already counted by needed_pairs

These tests pin the recogniser, not the counts: whether a criterion is SEEN is
what decides if a gate runs blind, and it is invisible in results.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.jena_sparql.jena_types import (
    ExprFunction, ExprValue, ExprVar, LiteralNode, URINode)
from vitalgraph.db.sparql_sql.filter_pushdown import (
    _equality_operands, _in_operands, _literal_term_key)

pytestmark = pytest.mark.unit

XSD = "http://www.w3.org/2001/XMLSchema#"


def _val(node):
    return ExprValue(node=node)


def _uri(v="urn:graphsyn:frametype:Mentions"):
    return URINode(value=v)


def _plain(v="alpha"):
    return LiteralNode(value=v, datatype=None)


class TestWhatCountsAsOneTerm:
    """`_literal_term_key` is the gate on every equality/IN estimate: it decides
    whether summing per-term counts answers the question asked."""

    def test_a_uri_is_one_term(self):
        assert _literal_term_key(_uri()) == ("urn:graphsyn:frametype:Mentions", "U")

    def test_a_plain_literal_is_one_term(self):
        assert _literal_term_key(_plain()) == ("alpha", "L")

    def test_an_xsd_string_is_the_same_term_as_a_plain_one(self):
        """RDF 1.1 — so both must key identically or the same query estimates
        differently depending on how it was written."""
        typed = LiteralNode(value="alpha", datatype=f"{XSD}string")
        assert _literal_term_key(typed) == _literal_term_key(_plain())

    def test_a_typed_numeric_is_not_one_term(self):
        """`5`, `5.0` and `05` are three terms and one value. Summing term
        counts would answer a different question; the range path owns this."""
        assert _literal_term_key(
            LiteralNode(value="5", datatype=f"{XSD}integer")) is None

    def test_a_boolean_is_not_one_term(self):
        """`true` and `1` are both true and are two terms — the same reason
        numerics are excluded. Deliberate, and the inline form is still counted
        as a constant pair, so booleans are not entirely unmeasured."""
        assert _literal_term_key(
            LiteralNode(value="true", datatype=f"{XSD}boolean")) is None

    def test_a_language_tagged_literal_is_not(self):
        """`"x"@en` and `"x"` are different terms; one must not estimate for
        the other."""
        assert _literal_term_key(
            LiteralNode(value="alpha", datatype=None, lang="en")) is None


class TestEqualityIsRecognised:
    """An equality is an IN of one value and needs the same estimate. Before
    this, string, boolean and uri were each counted INLINE and all three were
    unmeasured as a FILTER."""

    @pytest.mark.parametrize("node,label", [(_uri(), "uri"), (_plain(), "string")],
                             ids=["uri", "string"])
    def test_filter_equality_is_matched(self, node, label):
        expr = ExprFunction(name="eq", args=[ExprVar(var="v"), _val(node)])
        got = _equality_operands(expr)
        assert got is not None
        assert got[0] == "v"
        assert _literal_term_key(got[1]) is not None

    def test_operand_order_does_not_matter(self):
        expr = ExprFunction(name="eq", args=[_val(_uri()), ExprVar(var="v")])
        assert _equality_operands(expr)[0] == "v"

    def test_a_range_operator_is_not_an_equality(self):
        """`ge` belongs to the range path; matching it here would estimate a
        threshold as though it were a single value."""
        expr = ExprFunction(name="ge", args=[ExprVar(var="v"),
                                             _val(LiteralNode(value="50", datatype=None))])
        assert _equality_operands(expr) is None


class TestInIsRecognised:

    def test_an_in_over_uris_is_matched(self):
        expr = ExprFunction(name="in", args=[
            ExprVar(var="v"), _val(_uri()), _val(_uri("urn:other"))])
        ops = _in_operands(expr)
        assert ops is not None and ops[0] == "v"
        assert all(_literal_term_key(n) is not None for n in ops[3])

    def test_an_in_over_plain_literals_is_matched(self):
        expr = ExprFunction(name="in", args=[
            ExprVar(var="v"), _val(_plain("alpha")), _val(_plain("beta"))])
        ops = _in_operands(expr)
        assert ops is not None
        assert [_literal_term_key(n) for n in ops[3]] == [("alpha", "L"), ("beta", "L")]


class TestKnownLimits:
    """Stated so they are decisions rather than surprises."""

    def test_the_estimate_counts_quads_not_subjects(self):
        """`rdf_stats.row_count` is quads. On a MULTI-VALUED predicate a subject
        with two matching values contributes twice, so an IN sum exceeds the
        number of matching subjects.

        This used to SKIP: every criterion predicate in the fixture was
        single-valued, so the two counts were identical and the difference could
        not be observed. The generator now emits `hasTag`, one to four values per
        edge, and the case is measured for real in
        `tests/performance/test_graph_traversal_fixture.py` — 1.63 quads per
        subject, and an IN over two tags estimating 36,266 quads against 32,487
        matching subjects, a 12% overcount.

        Kept here as the statement of the SEMANTICS, with the measurement
        living where a database is available.
        """
        # The unit-level fact: nothing in the term-key machinery knows about
        # cardinality, so nothing here can distinguish the two counts. That is
        # precisely why the check belongs against real data.
        assert _literal_term_key(_uri()) is not None

    def test_boolean_filter_equality_is_declined(self):
        """Not an oversight: `true` and `1` are two terms and one value. The
        inline form is counted as a constant pair, so a boolean criterion is
        only unmeasured when written as a FILTER."""
        assert _literal_term_key(
            LiteralNode(value="true", datatype=f"{XSD}boolean")) is None
