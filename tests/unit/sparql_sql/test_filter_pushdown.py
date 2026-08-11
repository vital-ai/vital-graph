"""Unit tests for vitalgraph.db.sparql_sql.filter_pushdown — text filter push-down."""

from __future__ import annotations

from typing import Optional

import pytest

from vitalgraph.db.jena_sparql.jena_types import (
    ExprVar, ExprValue, ExprFunction, LiteralNode, URINode,
)
from vitalgraph.db.sparql_sql.ir import (
    PlanV2, TableRef, VarSlot,
    KIND_BGP, KIND_FILTER, KIND_EXTEND, KIND_JOIN,
)
from vitalgraph.db.sparql_sql.filter_pushdown import push_text_filters


SPACE = "test_space"


def _make_bgp_with_var(var_name: str = "x", alias: str = "q0") -> PlanV2:
    """Create a BGP with one quad table and one variable."""
    return PlanV2(
        kind=KIND_BGP,
        tables=[TableRef(ref_id=alias, kind="quad", table_name=f"{SPACE}_rdf_quad", alias=alias)],
        var_slots={var_name: VarSlot(name=var_name, positions=[(alias, "object_uuid")])},
    )


def _make_filter(bgp: PlanV2, *filter_exprs) -> PlanV2:
    """Wrap a BGP in a FILTER node."""
    return PlanV2(kind=KIND_FILTER, children=[bgp], filter_exprs=list(filter_exprs))


def _contains_expr(var: str, literal: str) -> ExprFunction:
    return ExprFunction(
        name="contains",
        args=[ExprVar(var=var), ExprValue(node=LiteralNode(value=literal))],
    )


def _strstarts_expr(var: str, literal: str) -> ExprFunction:
    return ExprFunction(
        name="strstarts",
        args=[ExprVar(var=var), ExprValue(node=LiteralNode(value=literal))],
    )


def _strends_expr(var: str, literal: str) -> ExprFunction:
    return ExprFunction(
        name="strends",
        args=[ExprVar(var=var), ExprValue(node=LiteralNode(value=literal))],
    )


def _eq_expr(var: str, literal: str) -> ExprFunction:
    return ExprFunction(
        name="eq",
        args=[ExprVar(var=var), ExprValue(node=LiteralNode(value=literal))],
    )


def _regex_expr(var: str, pattern: str, flags: Optional[str] = None) -> ExprFunction:
    args = [ExprVar(var=var), ExprValue(node=LiteralNode(value=pattern))]
    if flags:
        args.append(ExprValue(node=LiteralNode(value=flags)))
    return ExprFunction(name="regex", args=args)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPushTextFilters:

    def test_contains_pushdown(self):
        bgp = _make_bgp_with_var("x")
        plan = _make_filter(bgp, _contains_expr("x", "hello"))
        push_text_filters(plan, SPACE)

        assert len(bgp.tagged_constraints) == 1
        tag, sql = bgp.tagged_constraints[0]
        assert tag == "q0"
        assert "LIKE '%hello%'" in sql
        assert f"{SPACE}_term" in sql
        assert plan.filter_exprs is None  # consumed

    def test_contains_pushdown_escapes_like_metachars(self):
        # CONTAINS(?x, "50%_") must escape the LIKE metacharacters so they match
        # literally (else '%' and '_' act as wildcards and over-match). Escaping
        # keeps the GIN trigram index usable (pg_trgm honors '\').
        bgp = _make_bgp_with_var("x")
        plan = _make_filter(bgp, _contains_expr("x", "50%_"))
        push_text_filters(plan, SPACE)

        _, sql = bgp.tagged_constraints[0]
        assert r"LIKE '%50\%\_%'" in sql, sql

    def test_strstarts_pushdown(self):
        bgp = _make_bgp_with_var("x")
        plan = _make_filter(bgp, _strstarts_expr("x", "prefix"))
        push_text_filters(plan, SPACE)

        _, sql = bgp.tagged_constraints[0]
        assert "LIKE 'prefix%'" in sql

    def test_strends_pushdown(self):
        bgp = _make_bgp_with_var("x")
        plan = _make_filter(bgp, _strends_expr("x", "suffix"))
        push_text_filters(plan, SPACE)

        _, sql = bgp.tagged_constraints[0]
        assert "LIKE '%suffix'" in sql

    def test_eq_pushdown(self):
        bgp = _make_bgp_with_var("x")
        plan = _make_filter(bgp, _eq_expr("x", "exact"))
        push_text_filters(plan, SPACE)

        _, sql = bgp.tagged_constraints[0]
        assert "= 'exact'" in sql

    def test_regex_pushdown_case_insensitive(self):
        bgp = _make_bgp_with_var("x")
        plan = _make_filter(bgp, _regex_expr("x", "^foo.*bar$", "i"))
        push_text_filters(plan, SPACE)

        _, sql = bgp.tagged_constraints[0]
        assert "~*" in sql

    def test_regex_pushdown_case_sensitive(self):
        bgp = _make_bgp_with_var("x")
        plan = _make_filter(bgp, _regex_expr("x", "^foo"))
        push_text_filters(plan, SPACE)

        _, sql = bgp.tagged_constraints[0]
        assert "~" in sql
        assert "~*" not in sql

    def test_non_text_filter_not_consumed(self):
        """Non-text filters (e.g., URI comparison) should remain."""
        bgp = _make_bgp_with_var("x")
        non_text = ExprFunction(
            name="eq",
            args=[ExprVar(var="x"), ExprValue(node=URINode(value="http://example.org"))],
        )
        plan = _make_filter(bgp, non_text)
        push_text_filters(plan, SPACE)

        assert len(bgp.tagged_constraints) == 0
        assert plan.filter_exprs is not None
        assert len(plan.filter_exprs) == 1

    def test_mixed_filters_partial_consumption(self):
        """One pushable + one non-pushable filter."""
        bgp = _make_bgp_with_var("x")
        text_filter = _contains_expr("x", "hello")
        non_text = ExprFunction(
            name="bound",
            args=[ExprVar(var="x")],
        )
        plan = _make_filter(bgp, text_filter, non_text)
        push_text_filters(plan, SPACE)

        assert len(bgp.tagged_constraints) == 1
        assert plan.filter_exprs is not None
        assert len(plan.filter_exprs) == 1  # non-text remains

    def test_no_filter_node_noop(self):
        bgp = _make_bgp_with_var("x")
        push_text_filters(bgp, SPACE)  # BGP, not FILTER
        assert len(bgp.tagged_constraints) == 0

    def test_filter_with_no_exprs_noop(self):
        bgp = _make_bgp_with_var("x")
        plan = PlanV2(kind=KIND_FILTER, children=[bgp], filter_exprs=None)
        push_text_filters(plan, SPACE)
        assert len(bgp.tagged_constraints) == 0

    def test_unknown_var_not_pushed(self):
        """Filter on a variable not in the BGP should not be pushed."""
        bgp = _make_bgp_with_var("x")
        plan = _make_filter(bgp, _contains_expr("unknown", "hello"))
        push_text_filters(plan, SPACE)

        assert len(bgp.tagged_constraints) == 0
        assert plan.filter_exprs is not None

    def test_filter_through_extend(self):
        """FILTER → EXTEND → BGP chain — filter should still reach BGP."""
        bgp = _make_bgp_with_var("x")
        extend = PlanV2(
            kind=KIND_EXTEND,
            children=[bgp],
            extend_var="y",
            extend_expr=ExprVar(var="x"),
        )
        plan = _make_filter(extend, _contains_expr("x", "hello"))
        push_text_filters(plan, SPACE)

        assert len(bgp.tagged_constraints) == 1

    def test_no_bgp_descendant(self):
        """FILTER → JOIN should not crash."""
        left = _make_bgp_with_var("x")
        right = _make_bgp_with_var("y", alias="q1")
        join = PlanV2(kind=KIND_JOIN, children=[left, right])
        plan = _make_filter(join, _contains_expr("x", "hello"))
        push_text_filters(plan, SPACE)

        assert len(left.tagged_constraints) == 0  # not pushed

    def test_sql_escaping(self):
        """Single quotes in literals should be escaped."""
        bgp = _make_bgp_with_var("x")
        plan = _make_filter(bgp, _contains_expr("x", "it's"))
        push_text_filters(plan, SPACE)

        _, sql = bgp.tagged_constraints[0]
        assert "''" in sql  # escaped single quote
        assert "it''s" in sql


def _lcase(node):
    return ExprFunction(name="lcase", args=[node])


def _in_expr(var: str, *literals: str) -> ExprFunction:
    return ExprFunction(
        name="in",
        args=[ExprVar(var=var)] + [ExprValue(node=LiteralNode(value=v))
                                   for v in literals],
    )


class _FakeCtx:
    """Minimal stand-in for EmitContext — push_filters only reads this flag."""

    def __init__(self, in_correlated_subquery: bool = False):
        self.in_correlated_subquery = in_correlated_subquery


class TestNoPushDownInsideCorrelatedSubquery:
    """A pushed constraint is an UNCORRELATED `IN (SELECT term_uuid ...)`.

    PostgreSQL will not hoist one of those out of a correlated subquery, so
    inside an EXISTS body it re-executes per outer row. Pushing `?v IN (...)`
    into a NOT EXISTS body cost 190x on not_has_any/Choice — 56 ms to 10.6 s —
    against a plan that was already fast because prepare_exists_subplans had
    materialised the body's constants to uuids.

    These pin the guard rather than the speed: the timing lives in the sweep,
    but nothing there fails loudly, and this regression reached a full sweep
    before anyone noticed.
    """

    def test_in_filter_pushes_in_the_main_plan(self):
        bgp = _make_bgp_with_var("x")
        plan = _make_filter(bgp, _in_expr("x", "CA", "NY"))
        push_text_filters(plan, SPACE, _FakeCtx(in_correlated_subquery=False))

        assert len(bgp.tagged_constraints) == 1
        _, sql = bgp.tagged_constraints[0]
        assert "SELECT term_uuid" in sql
        assert "'CA'" in sql and "'NY'" in sql

    def test_in_filter_declines_inside_a_correlated_subquery(self):
        bgp = _make_bgp_with_var("x")
        plan = _make_filter(bgp, _in_expr("x", "CA", "NY"))
        push_text_filters(plan, SPACE, _FakeCtx(in_correlated_subquery=True))

        assert bgp.tagged_constraints == []
        # and the filter is left in place to be evaluated above the join
        assert plan.filter_exprs and len(plan.filter_exprs) == 1

    def test_text_filter_declines_inside_a_correlated_subquery(self):
        bgp = _make_bgp_with_var("x")
        plan = _make_filter(bgp, _contains_expr("x", "hello"))
        push_text_filters(plan, SPACE, _FakeCtx(in_correlated_subquery=True))

        assert bgp.tagged_constraints == []
        assert plan.filter_exprs and len(plan.filter_exprs) == 1


class TestCaseFoldedTextSearch:
    """KGQuery emits CONTAINS(LCASE(?v), LCASE("x")), not CONTAINS(?v, "x").

    Matching only the bare-variable shape meant `contains` was never pushed at
    all, which is why it timed out — not the "no indexable push-down path
    exists" the issue recorded.
    """

    def test_matched_fold_pair_pushes_as_ilike(self):
        bgp = _make_bgp_with_var("x")
        expr = ExprFunction(name="contains", args=[
            _lcase(ExprVar(var="x")),
            _lcase(ExprValue(node=LiteralNode(value="Ca"))),
        ])
        plan = _make_filter(bgp, expr)
        push_text_filters(plan, SPACE, _FakeCtx())

        assert len(bgp.tagged_constraints) == 1
        _, sql = bgp.tagged_constraints[0]
        assert "ILIKE '%Ca%'" in sql

    def test_asymmetric_fold_is_declined(self):
        """LCASE(?v) against an UNFOLDED needle is not case-insensitive.

        ILIKE would over-match, which is a wrong answer rather than a slow one.
        """
        bgp = _make_bgp_with_var("x")
        expr = ExprFunction(name="contains", args=[
            _lcase(ExprVar(var="x")),
            ExprValue(node=LiteralNode(value="Ca")),
        ])
        plan = _make_filter(bgp, expr)
        push_text_filters(plan, SPACE, _FakeCtx())

        assert bgp.tagged_constraints == []

    def test_unfolded_contains_still_pushes_case_sensitively(self):
        bgp = _make_bgp_with_var("x")
        plan = _make_filter(bgp, _contains_expr("x", "Ca"))
        push_text_filters(plan, SPACE, _FakeCtx())

        _, sql = bgp.tagged_constraints[0]
        assert "LIKE '%Ca%'" in sql and "ILIKE" not in sql


class TestEqualityConditionDispatchesOnDatatype:
    """`_ne_equality_cond` must key on the DATATYPE, not on parseability.

    An earlier version asked `_numeric_literal` first. That helper only tries
    `float(value)` and ignores the datatype, so two unrelated literals took the
    numeric branch and both were wrong:

        "5"               a plain literal is an xsd:string in RDF 1.1, but it
                          pushed `num_val = 5` — excluding the INTEGER 5 and
                          failing to exclude the string "5"
        "1"^^xsd:boolean  pushed `num_val = 1`, conflating true with 1^^integer

    Neither is reachable from KGQuery, which types its literals; both are
    reachable from SPARQL a caller writes. These are correctness tests, not
    performance ones — the failure mode is a row silently included or dropped.
    """

    XSD = "http://www.w3.org/2001/XMLSchema#"

    def _cond(self, value, datatype=None):
        from vitalgraph.db.sparql_sql.filter_pushdown import _ne_equality_cond
        return _ne_equality_cond(LiteralNode(value=value, datatype=datatype))

    def test_plain_numeric_looking_literal_is_a_string(self):
        cond = self._cond("5")
        assert "num_val" not in cond
        assert "term_text = '5'" in cond and "term_type = 'L'" in cond

    def test_xsd_string_numeric_looking_literal_is_a_string(self):
        cond = self._cond("5", self.XSD + "string")
        assert "num_val" not in cond
        assert "term_text = '5'" in cond

    def test_typed_integer_is_numeric(self):
        assert self._cond("5", self.XSD + "integer") == "num_val = 5.0"

    def test_typed_double_matches_the_same_value(self):
        """5^^integer and 5.0^^double are one value, so one condition."""
        assert (self._cond("5", self.XSD + "integer")
                == self._cond("5.0", self.XSD + "double"))

    def test_boolean_one_is_not_numeric_one(self):
        cond = self._cond("1", self.XSD + "boolean")
        assert "num_val" not in cond
        assert "'true','1'" in cond

    def test_both_boolean_spellings_give_one_condition(self):
        assert (self._cond("true", self.XSD + "boolean")
                == self._cond("1", self.XSD + "boolean"))
        assert (self._cond("false", self.XSD + "boolean")
                == self._cond("0", self.XSD + "boolean"))

    def test_boolean_condition_pins_the_datatype(self):
        """Without the guard, the STRING "true" and the integer 1 would match."""
        cond = self._cond("true", self.XSD + "boolean")
        assert "datatype_id IN (" in cond

    def test_invalid_boolean_lexical_form_declines(self):
        assert self._cond("maybe", self.XSD + "boolean") is None

    def test_unparseable_numeric_declines(self):
        assert self._cond("x", self.XSD + "integer") is None

    def test_unknown_datatype_declines(self):
        assert self._cond("x", "http://example.org/myType") is None
