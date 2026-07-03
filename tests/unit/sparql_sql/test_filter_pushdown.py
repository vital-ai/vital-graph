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
