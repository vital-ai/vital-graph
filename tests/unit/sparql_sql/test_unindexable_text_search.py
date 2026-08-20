"""A text search the trigram index cannot serve is declined, and sometimes refused.

`issues/070`. The GIN trigram index serves an INFIX match only when the needle
yields a trigram that can be REQUIRED, and every trigram of a short string is
padded. Pushing such a needle emits

    ?v IN (SELECT term_uuid FROM term WHERE term_text ILIKE '%XQ%')

which reads every term in the space however selective the rest of the query is —
the opposite of what a push-down is for. 12,613 ms to find nothing on 10.4M
terms.

TWO THINGS ARE TESTED, AND THEY ARE NOT THE SAME THING.

**Declining** is structural and always safe: the same FILTER is evaluated above
the join instead, over rows the query already produced. Identical answers.

**Refusing** is an error, and fires only where declining would trade a term scan
for something worse — when nothing else bounds the BGP, so "above the join" is
the whole graph. It is gated on the term table actually being large, which is
the part most likely to bite: an error that appears in production and not on a
fixture is worse than the scan. That gate is why `term_rows=None` must never
refuse.

WHY NOT SIMPLY REJECT NEEDLES UNDER THREE CHARACTERS

Tried, and wrong. `CONTAINS(?str, "a")`, `regex(?val, "a.c")` and
`regex(?val, "ab*c")` are legal SPARQL in the W3C corpus, and
`CONTAINS("abc"@en, "b")` has no variable at all. 29 DAWG `.rq` files use these
operators. Declining a push-down is invisible to conformance; refusing a query
is not, and `TestConformanceShapesSurvive` holds that line.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.jena_sparql.jena_types import (
    ExprVar, ExprValue, ExprFunction, LiteralNode,
)
from vitalgraph.db.sparql_sql.ir import (
    PlanV2, TableRef, VarSlot, KIND_BGP, KIND_FILTER,
)
from vitalgraph.db.sparql_sql.filter_pushdown import push_text_filters
from vitalgraph.db.sparql_sql import text_needle
from vitalgraph.db.sparql_sql.text_needle import (
    UnindexableTextSearch, is_servable, longest_required_literal_run,
    bgp_is_unbounded,
)

SPACE = "test_space"


class _Aliases:
    def __init__(self, term_rows=None):
        self.term_rows = term_rows
        self.constants = {}
        self.resolved_constants = {}


class _Ctx:
    def __init__(self, term_rows=None):
        self.aliases = _Aliases(term_rows)
        self.space_id = SPACE
        self.in_correlated_subquery = False
        self.datatype_cache = {}


def _bgp(bound=False):
    b = PlanV2(kind=KIND_BGP,
               tables=[TableRef(ref_id="q0", kind="quad",
                                table_name=f"{SPACE}_rdf_quad", alias="q0")],
               var_slots={"x": VarSlot(name="x",
                                       positions=[("q0", "object_uuid")])})
    if bound:
        # A constant leaf — something for the join to drive from, which is what
        # makes evaluating the filter above it bounded.
        b.leaf_terms[("q0", "predicate_uuid")] = ("http://ex/p", "U")
    return b


def _filter(bgp, expr):
    return PlanV2(kind=KIND_FILTER, children=[bgp], filter_exprs=[expr])


def _fn(op, needle, var="x"):
    return ExprFunction(name=op, args=[
        ExprVar(var=var), ExprValue(node=LiteralNode(value=needle))])


class TestWhatTheIndexCanServe:

    @pytest.mark.parametrize("needle", ["abc", "hello", "50%_"])
    def test_three_or_more_characters_is_servable(self, needle):
        assert is_servable("contains", needle)

    @pytest.mark.parametrize("needle", ["a", "XQ", ""])
    def test_a_short_infix_needle_is_not(self, needle):
        assert not is_servable("contains", needle)

    @pytest.mark.parametrize("op", ["strstarts", "strends"])
    def test_anchored_operators_are_servable_at_any_length(self, op):
        """'XQ%' is 1.0 ms and '%XQ' is 0.03 ms against 12,613 ms for the infix
        form — the padding holds at an anchor, so length is irrelevant."""
        assert is_servable(op, "X")


class TestRegexServability:
    """Approximate, and deliberately conservative in ONE direction.

    Under-counting costs a push-down. Over-counting costs 12 seconds, so every
    construct that makes a character optional or non-literal must be seen.
    """

    @pytest.mark.parametrize("pattern,expected", [
        ("abc", 3), ("remote", 6), ("DeFghI", 6),
        ("a.c", 1),                 # the dot is not a literal
        ("ab*c", 1),                # b is optional, so the run is not 'ab'
        ("ab?c", 1),
        ("a[^b]c", 1),              # a class matches ONE character
        ("[abc]x", 1),              # ...and its contents are not a run
        ("ab{2}c", 2),              # the quantifier's digits are not literals
        ("ab{1,2}c", 2),
        ("ab{0,2}c", 1),            # {0,..} makes b optional too
        ("abc{2}d", 3),
        (r"example\.com", 11),      # an escaped metacharacter IS a literal
        ("a?+*.{}()", 0),
    ])
    def test_longest_required_run(self, pattern, expected):
        assert longest_required_literal_run(pattern) == expected

    def test_a_prefix_anchor_makes_any_length_servable(self):
        assert is_servable("regex", "^ab")

    def test_a_trailing_dollar_does_not(self):
        """`$` anchors the end, which pg_trgm cannot use the way a prefix can —
        so this is NOT symmetric with STRENDS, where the LIKE form is."""
        assert not is_servable("regex", "ab$")

    def test_an_unknown_operator_is_assumed_servable(self):
        """This function must never be the reason a NEW operator silently stops
        pushing."""
        assert is_servable("soundslike", "ab")


class TestDeclining:

    def test_an_unservable_needle_is_not_pushed(self):
        bgp = _bgp(bound=True)
        push_text_filters(_filter(bgp, _fn("contains", "XQ")), SPACE, _Ctx())
        assert bgp.tagged_constraints == []

    def test_a_servable_needle_still_is(self):
        bgp = _bgp(bound=True)
        push_text_filters(_filter(bgp, _fn("contains", "XQZ")), SPACE, _Ctx())
        assert len(bgp.tagged_constraints) == 1

    def test_the_no_op_concatenation_is_gone(self):
        """`(term_text || '')` was a value-preserving expression chosen to make
        the index INAPPLICABLE, so the planner took a sequential scan (12,613 ms
        -> 4,041 ms). Nothing should emit it now: the case it served is declined
        before the condition is built."""
        for needle in ("XQ", "a", "XQZ", "hello"):
            bgp = _bgp(bound=True)
            push_text_filters(_filter(bgp, _fn("contains", needle)), SPACE, _Ctx())
            for _, sql in bgp.tagged_constraints:
                assert "|| ''" not in sql

    def test_declining_leaves_the_filter_for_evaluation_above_the_join(self):
        """The answer must not change. A declined filter stays in the plan."""
        bgp = _bgp(bound=True)
        plan = _filter(bgp, _fn("contains", "XQ"))
        push_text_filters(plan, SPACE, _Ctx())
        assert len(plan.filter_exprs) == 1


class TestRefusingTheUnboundedCase:

    def test_unbounded_and_large_refuses(self):
        bgp = _bgp(bound=False)
        with pytest.raises(UnindexableTextSearch) as exc:
            push_text_filters(_filter(bgp, _fn("contains", "XQ")), SPACE,
                              _Ctx(term_rows=10_400_000))
        msg = str(exc.value)
        assert "STRSTARTS" in msg, "the message must name the way out"
        assert "10,400,000" in msg, "and what it would have cost"

    def test_a_bound_bgp_is_only_declined(self):
        """Something else drives the join, so evaluating above it is bounded."""
        bgp = _bgp(bound=True)
        push_text_filters(_filter(bgp, _fn("contains", "XQ")), SPACE,
                          _Ctx(term_rows=10_400_000))
        assert bgp.tagged_constraints == []

    def test_a_small_term_table_is_only_declined(self):
        """A sequential scan of a small term table is milliseconds. Erroring on
        it would buy nothing and cost a working query."""
        bgp = _bgp(bound=False)
        push_text_filters(_filter(bgp, _fn("contains", "XQ")), SPACE,
                          _Ctx(term_rows=5_000))
        assert bgp.tagged_constraints == []

    def test_an_unmeasured_term_table_never_refuses(self):
        """None means the size was never established — no connection, no
        `reltuples`, a failed lookup. The one outcome this gate must not produce
        is an error on a query that would have been fine."""
        bgp = _bgp(bound=False)
        push_text_filters(_filter(bgp, _fn("contains", "XQ")), SPACE,
                          _Ctx(term_rows=None))
        assert bgp.tagged_constraints == []

    def test_a_servable_needle_is_never_refused_however_unbounded(self):
        bgp = _bgp(bound=False)
        push_text_filters(_filter(bgp, _fn("contains", "XQZ")), SPACE,
                          _Ctx(term_rows=10_400_000))
        assert len(bgp.tagged_constraints) == 1

    def test_a_graph_lock_alone_does_not_bound_anything(self):
        """A GRAPH clause says WHICH graph, not which rows.

        It arrives three ways depending on the shape — a `leaf_terms` entry and
        `q0.context_uuid = ...` in both constraint lists — and counting any of
        them as narrowing made every BGP inside a named graph read as bounded,
        so the refusal never fired. Measured before the fix: `?s ?p ?o` with
        `CONTAINS(?o,"XQ")` on sp_lead_synth_100k was declined instead of
        refused and ran past 60 seconds.
        """
        bgp = _bgp(bound=False)
        bgp.constraints.append("q0.context_uuid = __CONST_c_0__")
        bgp.tagged_constraints.append(("q0", "q0.context_uuid = __CONST_c_0__"))
        bgp.leaf_terms[("q0", "context_uuid")] = ("urn:g", "U")
        assert bgp_is_unbounded(bgp)

        with pytest.raises(UnindexableTextSearch):
            push_text_filters(_filter(bgp, _fn("contains", "XQ")), SPACE,
                              _Ctx(term_rows=10_400_000))

    def test_boundedness_counts_a_pushed_constraint(self):
        bgp = _bgp(bound=False)
        assert bgp_is_unbounded(bgp)
        bgp.tagged_constraints.append(("q0", "q0.predicate_uuid = 'x'"))
        assert not bgp_is_unbounded(bgp)


class TestConformanceShapesSurvive:
    """The exact patterns in the W3C corpus a lexical refusal would have broken.

    None of these may raise. Declining is invisible to an answer; refusing is
    not, and these are all spec-legal.
    """

    @pytest.mark.parametrize("op,needle", [
        ("contains", "a"),          # contains01.rq
        ("regex", "a.c"),
        ("regex", "ab*c"),
        ("regex", "a[^b]c"),
        ("regex", "ab{2}c"),
        ("regex", "GHI"),
        ("regex", "remote"),
    ])
    def test_no_dawg_shape_raises(self, op, needle):
        bgp = _bgp(bound=True)
        push_text_filters(_filter(bgp, _fn(op, needle)), SPACE,
                          _Ctx(term_rows=10_400_000))


class TestTheSizeGateIsReadOnlyWhereItIsWritten:

    def test_the_threshold_is_stated_once(self):
        assert text_needle.UNBOUNDED_SCAN_TERMS >= 1_000_000

    def test_the_endpoint_guard_agrees_with_the_layer(self):
        """`MIN_CONTAINS_LENGTH` gives a UI input an immediate answer; the layer
        is what actually decides. Two independent constants for one rule drift,
        and the drift is silent in the direction that matters — an endpoint
        accepting a needle the layer then refuses."""
        from vitalgraph.model.kgentities_model import MIN_CONTAINS_LENGTH
        assert MIN_CONTAINS_LENGTH == text_needle.MIN_TRIGRAM_NEEDLE

    def test_aliases_default_to_unmeasured(self):
        from vitalgraph.db.sparql_sql.ir import AliasGenerator
        assert AliasGenerator().term_rows is None


class TestBothEndsAgreeOnServability:
    """`semijoin` and the emitter must accept EXACTLY the same expressions.

    `semijoin` asks `_text_search_var` whether a variable is pushable and, when
    it is, skips that variable's term JOIN — on the grounds that the filter will
    consume it. `_try_text_filter` DECLINES an unservable needle, so the FILTER
    stays above the join and needs its value materialised after all. With only
    the emitter taught the servability rule the two ends disagreed and the query
    stopped generating:

        Variable(s) lost their value while in scope: ?val_0_0_0

    `_text_search_operands`' docstring names this exact hazard — "see issues/054
    and issues/058 for what happens when the two ends drift" — and it drifted
    anyway, because the rule was added in one place.

    It shipped green: every bench that would have caught it
    (`test_comparator_coverage`, 26 cases, whose `contains` needle is the
    two-character "CA") was SKIPPING on a fixture nobody had loaded.
    """

    def _contains(self, needle):
        return ExprFunction(name="contains", args=[
            ExprVar(var="v"), ExprValue(node=LiteralNode(value=needle))])

    def test_an_unservable_needle_is_not_pushable(self):
        from vitalgraph.db.sparql_sql.filter_pushdown import _text_search_var
        assert _text_search_var(self._contains("CA")) is None, (
            "saying pushable here skips the term join, and the declined filter "
            "then has no value to compare")

    def test_a_servable_needle_still_is(self):
        from vitalgraph.db.sparql_sql.filter_pushdown import _text_search_var
        assert _text_search_var(self._contains("CAL")) == "v"

    def test_an_anchored_needle_is_pushable_at_any_length(self):
        from vitalgraph.db.sparql_sql.filter_pushdown import _text_search_var
        expr = ExprFunction(name="strstarts", args=[
            ExprVar(var="v"), ExprValue(node=LiteralNode(value="C"))])
        assert _text_search_var(expr) == "v"

    def test_the_two_ends_agree_on_every_needle(self):
        """The property, not three examples: whatever `_try_text_filter` will
        decline, the gate must not call pushable."""
        from vitalgraph.db.sparql_sql.filter_pushdown import _text_search_var
        for needle in ("a", "CA", "CAL", "hello", "50%_", ""):
            pushable = _text_search_var(self._contains(needle)) is not None
            assert pushable == is_servable("contains", needle), needle
