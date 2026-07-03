"""Unit tests for vitalgraph.db.sparql_sql.var_scope — variable scoping."""

from __future__ import annotations

import pytest

from vitalgraph.db.jena_sparql.jena_types import ExprVar, ExprFunction, ExprAggregator, GroupVar
from vitalgraph.db.sparql_sql.ir import (
    PlanV2,
    VarSlot,
    KIND_BGP,
    KIND_JOIN,
    KIND_LEFT_JOIN,
    KIND_UNION,
    KIND_MINUS,
    KIND_TABLE,
    KIND_NULL,
    KIND_PATH,
    KIND_PROJECT,
    KIND_DISTINCT,
    KIND_FILTER,
    KIND_EXTEND,
    KIND_GROUP,
    KIND_SLICE,
    KIND_ORDER,
)
from vitalgraph.db.sparql_sql.var_scope import (
    VarScope,
    compute_scope,
    vars_in_expr,
    compute_text_needed_vars,
)


# ---------------------------------------------------------------------------
# VarScope dataclass
# ---------------------------------------------------------------------------

class TestVarScope:

    def test_empty_scope(self):
        s = VarScope()
        assert s.defined == frozenset()
        assert s.maybe == frozenset()
        assert s.all_visible == frozenset()

    def test_with_defined(self):
        s = VarScope().with_defined("x", "y")
        assert s.defined == frozenset({"x", "y"})
        assert s.maybe == frozenset()
        assert s.all_visible == frozenset({"x", "y"})

    def test_with_defined_promotes_from_maybe(self):
        s = VarScope(maybe=frozenset({"x"})).with_defined("x")
        assert s.defined == frozenset({"x"})
        assert s.maybe == frozenset()  # promoted out of maybe

    def test_with_maybe(self):
        s = VarScope(defined=frozenset({"x"})).with_maybe("y")
        assert s.defined == frozenset({"x"})
        assert s.maybe == frozenset({"y"})
        assert s.all_visible == frozenset({"x", "y"})

    def test_restrict_to(self):
        s = VarScope(defined=frozenset({"x", "y", "z"}), maybe=frozenset({"w"}))
        r = s.restrict_to({"x", "w"})
        assert r.defined == frozenset({"x"})
        assert r.maybe == frozenset({"w"})

    # --- Merge operations ---

    def test_merge_join(self):
        left = VarScope(defined=frozenset({"x"}))
        right = VarScope(defined=frozenset({"y"}), maybe=frozenset({"z"}))
        merged = left.merge_join(right)
        assert merged.defined == frozenset({"x", "y"})
        assert merged.maybe == frozenset({"z"})

    def test_merge_left_join(self):
        left = VarScope(defined=frozenset({"x"}))
        right = VarScope(defined=frozenset({"y", "z"}))
        merged = left.merge_left_join(right)
        assert merged.defined == frozenset({"x"})
        assert "y" in merged.maybe
        assert "z" in merged.maybe

    def test_merge_union_both_branches(self):
        left = VarScope(defined=frozenset({"x", "a"}))
        right = VarScope(defined=frozenset({"x", "b"}))
        merged = left.merge_union(right)
        assert merged.defined == frozenset({"x"})  # in both
        assert "a" in merged.maybe  # only in left
        assert "b" in merged.maybe  # only in right

    def test_merge_union_no_overlap(self):
        left = VarScope(defined=frozenset({"a"}))
        right = VarScope(defined=frozenset({"b"}))
        merged = left.merge_union(right)
        assert merged.defined == frozenset()
        assert merged.maybe == frozenset({"a", "b"})

    def test_merge_minus(self):
        left = VarScope(defined=frozenset({"x", "y"}))
        right = VarScope(defined=frozenset({"x", "z"}))
        merged = left.merge_minus(right)
        assert merged is left  # MINUS doesn't change scope

    def test_after_group(self):
        s = VarScope(defined=frozenset({"x", "y", "z"}))
        grouped = s.after_group({"x"}, {"count_y"})
        assert grouped.defined == frozenset({"x", "count_y"})
        assert grouped.maybe == frozenset()


# ---------------------------------------------------------------------------
# compute_scope — from PlanV2 trees
# ---------------------------------------------------------------------------

def _bgp(*vars: str) -> PlanV2:
    """Helper: create a BGP plan with the given variable names."""
    return PlanV2(
        kind=KIND_BGP,
        var_slots={v: VarSlot(name=v) for v in vars},
    )


class TestComputeScope:

    def test_bgp_leaf(self):
        plan = _bgp("x", "y")
        scope = compute_scope(plan)
        assert scope.defined == frozenset({"x", "y"})

    def test_null_leaf(self):
        plan = PlanV2(kind=KIND_NULL)
        scope = compute_scope(plan)
        assert scope.all_visible == frozenset()

    def test_table_leaf(self):
        plan = PlanV2(kind=KIND_TABLE, values_vars=["a", "b"])
        scope = compute_scope(plan)
        assert scope.defined == frozenset({"a", "b"})

    def test_path_leaf(self):
        plan = PlanV2(kind=KIND_PATH, var_slots={"s": VarSlot(name="s"), "o": VarSlot(name="o")})
        scope = compute_scope(plan)
        assert scope.defined == frozenset({"s", "o"})

    def test_join(self):
        plan = PlanV2(kind=KIND_JOIN, children=[_bgp("x", "y"), _bgp("y", "z")])
        scope = compute_scope(plan)
        assert scope.defined == frozenset({"x", "y", "z"})

    def test_left_join(self):
        plan = PlanV2(kind=KIND_LEFT_JOIN, children=[_bgp("x"), _bgp("y")])
        scope = compute_scope(plan)
        assert scope.defined == frozenset({"x"})
        assert "y" in scope.maybe

    def test_union(self):
        plan = PlanV2(kind=KIND_UNION, children=[_bgp("x", "a"), _bgp("x", "b")])
        scope = compute_scope(plan)
        assert scope.defined == frozenset({"x"})
        assert "a" in scope.maybe
        assert "b" in scope.maybe

    def test_minus(self):
        plan = PlanV2(kind=KIND_MINUS, children=[_bgp("x", "y"), _bgp("x", "z")])
        scope = compute_scope(plan)
        assert scope.defined == frozenset({"x", "y"})
        assert "z" not in scope.all_visible

    def test_filter_passthrough(self):
        plan = PlanV2(kind=KIND_FILTER, children=[_bgp("x")])
        scope = compute_scope(plan)
        assert scope.defined == frozenset({"x"})

    def test_extend_adds_var(self):
        plan = PlanV2(
            kind=KIND_EXTEND,
            children=[_bgp("x")],
            extend_var="y",
            extend_expr=ExprVar(var="x"),
        )
        scope = compute_scope(plan)
        assert scope.defined == frozenset({"x", "y"})

    def test_project_restricts(self):
        plan = PlanV2(
            kind=KIND_PROJECT,
            children=[_bgp("x", "y", "z")],
            project_vars=["x", "y"],
        )
        scope = compute_scope(plan)
        assert scope.defined == frozenset({"x", "y"})
        assert "z" not in scope.all_visible

    def test_group(self):
        plan = PlanV2(
            kind=KIND_GROUP,
            children=[_bgp("x", "y")],
            group_vars=[GroupVar(var="x")],
            aggregates={"cnt": ExprAggregator(name="COUNT", expr=ExprVar(var="y"))},
        )
        scope = compute_scope(plan)
        assert scope.defined == frozenset({"x", "cnt"})
        assert "y" not in scope.all_visible

    def test_distinct_passthrough(self):
        inner = PlanV2(
            kind=KIND_PROJECT,
            children=[_bgp("x", "y")],
            project_vars=["x"],
        )
        plan = PlanV2(kind=KIND_DISTINCT, children=[inner])
        scope = compute_scope(plan)
        assert scope.defined == frozenset({"x"})

    def test_slice_passthrough(self):
        plan = PlanV2(kind=KIND_SLICE, children=[_bgp("x")], limit=10)
        scope = compute_scope(plan)
        assert scope.defined == frozenset({"x"})

    def test_order_passthrough(self):
        plan = PlanV2(kind=KIND_ORDER, children=[_bgp("x")])
        scope = compute_scope(plan)
        assert scope.defined == frozenset({"x"})

    def test_nested_plan(self):
        """SELECT DISTINCT ?x WHERE { ?x ?y ?z . OPTIONAL { ?z ?w ?v } } LIMIT 10"""
        bgp1 = _bgp("x", "y", "z")
        bgp2 = _bgp("z", "w", "v")
        left_join = PlanV2(kind=KIND_LEFT_JOIN, children=[bgp1, bgp2])
        project = PlanV2(kind=KIND_PROJECT, children=[left_join], project_vars=["x"])
        distinct = PlanV2(kind=KIND_DISTINCT, children=[project])
        sliced = PlanV2(kind=KIND_SLICE, children=[distinct], limit=10)

        scope = compute_scope(sliced)
        assert scope.defined == frozenset({"x"})
        assert scope.maybe == frozenset()


# ---------------------------------------------------------------------------
# vars_in_expr
# ---------------------------------------------------------------------------

class TestVarsInExpr:

    def test_var(self):
        assert vars_in_expr(ExprVar(var="x")) == {"x"}

    def test_function(self):
        expr = ExprFunction(name="CONTAINS", args=[ExprVar(var="x"), ExprVar(var="y")])
        assert vars_in_expr(expr) == {"x", "y"}

    def test_nested_function(self):
        inner = ExprFunction(name="STR", args=[ExprVar(var="x")])
        outer = ExprFunction(name="CONTAINS", args=[inner, ExprVar(var="y")])
        assert vars_in_expr(outer) == {"x", "y"}

    def test_aggregator_with_expr(self):
        agg = ExprAggregator(name="COUNT", expr=ExprVar(var="x"))
        assert vars_in_expr(agg) == {"x"}

    def test_aggregator_count_star(self):
        agg = ExprAggregator(name="COUNT", expr=None)
        assert vars_in_expr(agg) == set()

    def test_unknown_type(self):
        assert vars_in_expr("not_an_expr") == set()


# ---------------------------------------------------------------------------
# compute_text_needed_vars
# ---------------------------------------------------------------------------

class TestComputeTextNeededVars:

    def test_no_project_all_vars_needed(self):
        """SELECT * { ?x ?y ?z } — all vars need text."""
        plan = _bgp("x", "y", "z")
        needed = compute_text_needed_vars(plan)
        assert needed == {"x", "y", "z"}

    def test_projected_vars_needed(self):
        """SELECT ?x { ?x ?y ?z } — x is projected, y/z are internal."""
        plan = PlanV2(
            kind=KIND_PROJECT,
            children=[_bgp("x", "y", "z")],
            project_vars=["x"],
        )
        needed = compute_text_needed_vars(plan)
        assert "x" in needed
        # y and z are internal-only — may or may not be needed depending on
        # whether they appear in filters etc.

    def test_filter_references_var(self):
        """SELECT ?x { ?x ?y ?z . FILTER(?y = 'foo') } — y is referenced."""
        bgp = _bgp("x", "y", "z")
        filtered = PlanV2(
            kind=KIND_FILTER,
            children=[bgp],
            filter_exprs=[ExprFunction(name="=", args=[ExprVar(var="y"), ExprVar(var="x")])],
        )
        plan = PlanV2(
            kind=KIND_PROJECT,
            children=[filtered],
            project_vars=["x"],
        )
        needed = compute_text_needed_vars(plan)
        assert "x" in needed
        assert "y" in needed  # referenced by FILTER

    def test_empty_bgp(self):
        plan = PlanV2(kind=KIND_BGP)
        needed = compute_text_needed_vars(plan)
        assert needed == set()
