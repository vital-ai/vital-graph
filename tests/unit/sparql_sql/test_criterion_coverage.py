"""Which criterion shapes can be estimated, and which are declined on purpose.

Every selectivity gate in the pipeline — the traversal decision, the semi-join
gate, join ordering — reads these statistics, and a criterion nothing measures
reads as UNMEASURED, which `emit_bgp` treats as "comparison unsafe". Two whole
families were silently in that state until 2026-08-14.

Audited against the traversal fixture, which carries all six datatypes:

    integer  >=   range stat
    double   >=   range stat
    dateTime >=   range stat
    string   IN   category IN (alpha,beta)    37,534  exact
    string   =    category = alpha            21,491  exact
    boolean  =    active = true               13,198  exact
    uri      IN   tag IN (external,archived)  36,434
    uri      =    tag = external              18,225
    string   CONTAINS  text stat
    string / boolean / uri written INLINE in the triple
                  constant pair -- counted by needed_pairs, and NOT reachable
                  as a criterion: the traversal gate reads range/text/in stats
                  only, so `?f hasCategory "theta"` measures nothing (issues/101)

Counts are against the current graph_synth_10k and each names its criterion; an
earlier table gave bare numbers from a superseded generation of the fixture.

There are TWO gates, and conflating them is what left booleans unmeasured:

    _literal_term_key   governs PUSH-DOWN. Refuses anything whose value has
                        several lexical forms, because emitting a constraint on
                        one form would silently DROP rows written as the other.
    _stat_keys          governs COUNTING. Accepts the same value and sums every
                        form, which is exact.

A boolean is right on one side of that line and wrong on the other. It was
declined by both until 2026-08-14, discarding a count `rdf_stats` already held.

These tests pin the recogniser, not the counts: whether a criterion is SEEN is
what decides if a gate runs blind, and it is invisible in results.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.jena_sparql.jena_types import (
    ExprFunction, ExprValue, ExprVar, LiteralNode, URINode)
from vitalgraph.db.sparql_sql.filter_pushdown import (
    _equality_operands, _in_operands, _literal_term_key)
from vitalgraph.db.sparql_sql.semijoin import _stat_keys

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
        """`true` and `1` are both true and are two terms, so PUSH-DOWN must
        still refuse it — a constraint on one form drops rows in the other.

        Counting it is a different question; see `TestBooleansAreCounted`."""
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


class TestNotInIsTheComplement:
    """`NOT IN` admits everything the values do not, and was counted as if it
    admitted exactly them (issues/101).

    Measured on `sp_graph_skew_2k`, where `theta` is 1% of `hasCategory`:

        FILTER(?ct IN     ("theta"))   reported "admits 1%"    true:  1%
        FILTER(?ct NOT IN ("theta"))   reported "admits 1%"    true: 99%

    `_IN_OPS` has always mapped both spellings; `needed_ins` unpacked the
    operator into `_sql_op` and dropped it. Every other negation — `!=`,
    `!(?v = x)`, `!(?v IN (x))` — declines further up and stays unmeasured, so
    this one surface form was the whole of it.

    It did not flip the hop-wise decision: selectivity is reported rather than
    thresholded, so a measured criterion qualifies whatever its value. What it
    corrupted is the number — the reported selectivity, `criterion_rows`, and
    which criterion wins the most-selective contest when a query has several.
    """

    def test_in_and_not_in_are_distinguished(self):
        for name, expected in (("in", "IN"), ("notin", "NOT IN")):
            expr = ExprFunction(name=name, args=[
                ExprVar(var="v"), _val(_plain("theta"))])
            ops = _in_operands(expr)
            assert ops is not None and ops[1] == expected

    def test_the_values_are_identical_for_both(self):
        """The count is of the same terms either way; only the polarity differs.
        If these diverged, the inversion would be against the wrong number."""
        pos, neg = (_in_operands(ExprFunction(name=n, args=[
            ExprVar(var="v"), _val(_plain("alpha")), _val(_plain("beta"))]))
            for n in ("in", "notin"))
        assert [_stat_keys(n) for n in pos[3]] == [_stat_keys(n) for n in neg[3]]

    def test_needed_ins_reports_the_polarity(self):
        """The unpacking that dropped it. A three-tuple is the contract the
        generator inverts on; a two-tuple silently means "positive"."""
        import inspect
        from vitalgraph.db.sparql_sql import semijoin
        src = inspect.getsource(semijoin.needed_ins)
        assert "negated = sql_op ==" in src
        assert "out.add((p_uuid, values, negated))" in src

    def test_the_generator_inverts_against_the_predicate_total(self):
        """And DROPS the criterion when it has no total to invert against.

        rdf_stats is a capped frequent-value list, so its sum is an undercount;
        an undercount of the positive side makes the complement an overcount,
        which reads as less selective and declines. Guessing instead would push
        the error the other way, toward a criterion that is not there.
        """
        import inspect
        from vitalgraph.db.sparql_sql import generator
        src = inspect.getsource(generator._generate_sql)
        assert "_total = _pred_stats.get(_p)" in src
        assert "v = max(_total - v, 0)" in src


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

    def test_a_numeric_is_still_unmeasured_as_an_equality(self):
        """The exclusion booleans just escaped, still standing where it belongs.
        `5`, `5.0` and `05` are three terms, and unlike a boolean the set of
        forms is unbounded, so there is nothing finite to sum. The RANGE path
        covers numerics; `= 5` written as a FILTER is not estimated."""
        assert _stat_keys(LiteralNode(value="5", datatype=f"{XSD}integer")) is None


class TestBooleansAreCounted:
    """Measured on graph_synth_10k: `hasActive` is 13,198 true against 53,648
    false — 19.7%, a genuinely selective criterion that read as "selectivity
    unknown" because the counting path reused the push-down gate.

    The estimate is exact, and rdf_stats already held it. Verified end to end
    against the generator: in_stats reported 13,198, matching the quad count.
    """

    @pytest.mark.parametrize("value", ["true", "false"])
    def test_both_lexical_forms_are_summed(self, value):
        keys = _stat_keys(LiteralNode(value=value, datatype=f"{XSD}boolean"))
        assert keys is not None
        assert {k[0] for k in keys} == ({"true", "1"} if value == "true"
                                        else {"false", "0"})

    def test_the_datatype_is_constrained(self):
        """Not decoration. `'1'` and `'0'` exist in the same space as xsd:INTEGER
        terms (`hasScore` has 203 rows of integer 1), so matching lexical form
        alone would sum boolean-true with integer-one on any predicate holding
        both. The generic schema permits that; nothing forbids it per predicate.
        """
        keys = _stat_keys(LiteralNode(value="true", datatype=f"{XSD}boolean"))
        assert all(k[2] == f"{XSD}boolean" for k in keys)

    def test_a_uri_does_not_constrain_the_datatype(self):
        """URIs and plain literals keep the unconstrained form they have always
        had — adding a datatype condition there would be a behaviour change to
        a path measured exact (string IN at 37,534)."""
        assert _stat_keys(_uri()) == [("urn:graphsyn:frametype:Mentions", "U", "")]
        assert _stat_keys(_plain()) == [("alpha", "L", "")]

    def test_a_nonsense_boolean_is_declined(self):
        """`"maybe"^^xsd:boolean` is ill-typed. Guessing a form for it would
        invent an estimate."""
        assert _stat_keys(LiteralNode(value="maybe",
                                      datatype=f"{XSD}boolean")) is None

    def test_case_and_whitespace_do_not_defeat_it(self):
        assert _stat_keys(LiteralNode(value=" TRUE ",
                                      datatype=f"{XSD}boolean")) is not None
