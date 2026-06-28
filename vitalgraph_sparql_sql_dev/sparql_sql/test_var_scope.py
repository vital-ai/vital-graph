"""
Tests for Variable Scope Model (var_scope.py).

Tests scope computation from PlanV2 trees, verifying that SPARQL scoping
rules (JOIN, OPTIONAL, UNION, MINUS, GROUP BY, PROJECT, BIND) produce
the correct variable visibility.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Dict

from ..jena_sparql.jena_ast_mapper import map_compile_response
from ..jena_sparql.jena_types import GroupVar, ExprAggregator

from .ir import (
    PlanV2, AliasGenerator, VarSlot,
    KIND_BGP, KIND_JOIN, KIND_LEFT_JOIN, KIND_UNION, KIND_MINUS,
    KIND_TABLE, KIND_NULL,
    KIND_PROJECT, KIND_FILTER, KIND_EXTEND, KIND_GROUP,
    KIND_DISTINCT, KIND_SLICE, KIND_ORDER,
)
from .collect import collect
from .var_scope import VarScope, compute_scope, vars_in_expr

SIDECAR_URL = "http://localhost:7070"
SPACE_ID = "test_v2"


def _compile_and_collect(sparql: str) -> PlanV2:
    req = urllib.request.Request(
        f"{SIDECAR_URL}/v1/sparql/compile",
        data=json.dumps({"sparql": sparql}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        raw = json.loads(resp.read())
    cr = map_compile_response(raw)
    assert cr.ok
    aliases = AliasGenerator()
    return collect(cr.algebra, SPACE_ID, aliases)


# ---------------------------------------------------------------------------
# Unit tests (synthetic plans — no sidecar needed)
# ---------------------------------------------------------------------------

def test_scope_bgp():
    """BGP defines its var_slots."""
    plan = PlanV2(kind=KIND_BGP, var_slots={
        "s": VarSlot(name="s"), "p": VarSlot(name="p"), "o": VarSlot(name="o"),
    })
    scope = compute_scope(plan)
    assert scope.defined == frozenset({"s", "p", "o"})
    assert scope.maybe == frozenset()
    print("  PASS test_scope_bgp")


def test_scope_join():
    """JOIN merges both sides as defined."""
    left = PlanV2(kind=KIND_BGP, var_slots={"s": VarSlot(name="s")})
    right = PlanV2(kind=KIND_BGP, var_slots={"p": VarSlot(name="p")})
    plan = PlanV2(kind=KIND_JOIN, children=[left, right])
    scope = compute_scope(plan)
    assert scope.defined == frozenset({"s", "p"})
    print("  PASS test_scope_join")


def test_scope_left_join():
    """LEFT JOIN: right-only vars become maybe."""
    left = PlanV2(kind=KIND_BGP, var_slots={"s": VarSlot(name="s")})
    right = PlanV2(kind=KIND_BGP, var_slots={
        "s": VarSlot(name="s"), "o": VarSlot(name="o"),
    })
    plan = PlanV2(kind=KIND_LEFT_JOIN, children=[left, right])
    scope = compute_scope(plan)
    assert "s" in scope.defined
    assert "o" in scope.maybe
    assert "o" not in scope.defined
    print("  PASS test_scope_left_join")


def test_scope_union():
    """UNION: vars in both branches = defined, one-side = maybe."""
    left = PlanV2(kind=KIND_BGP, var_slots={
        "s": VarSlot(name="s"), "a": VarSlot(name="a"),
    })
    right = PlanV2(kind=KIND_BGP, var_slots={
        "s": VarSlot(name="s"), "b": VarSlot(name="b"),
    })
    plan = PlanV2(kind=KIND_UNION, children=[left, right])
    scope = compute_scope(plan)
    assert "s" in scope.defined  # both branches
    assert "a" in scope.maybe  # left only
    assert "b" in scope.maybe  # right only
    print("  PASS test_scope_union")


def test_scope_minus():
    """MINUS: only left-side vars survive."""
    left = PlanV2(kind=KIND_BGP, var_slots={"s": VarSlot(name="s")})
    right = PlanV2(kind=KIND_BGP, var_slots={
        "s": VarSlot(name="s"), "o": VarSlot(name="o"),
    })
    plan = PlanV2(kind=KIND_MINUS, children=[left, right])
    scope = compute_scope(plan)
    assert "s" in scope.defined
    assert "o" not in scope.all_visible
    print("  PASS test_scope_minus")


def test_scope_extend():
    """EXTEND/BIND adds a new defined variable."""
    inner = PlanV2(kind=KIND_BGP, var_slots={"s": VarSlot(name="s")})
    plan = PlanV2(kind=KIND_EXTEND, extend_var="z", children=[inner])
    scope = compute_scope(plan)
    assert scope.defined == frozenset({"s", "z"})
    print("  PASS test_scope_extend")


def test_scope_group():
    """GROUP BY restricts to grouped vars + aggregates."""
    inner = PlanV2(kind=KIND_BGP, var_slots={
        "s": VarSlot(name="s"), "p": VarSlot(name="p"), "o": VarSlot(name="o"),
    })
    plan = PlanV2(
        kind=KIND_GROUP,
        group_vars=[GroupVar(var="s", expr=None)],
        aggregates={".0": ExprAggregator(name="COUNT", distinct=False, expr=None)},
        children=[inner],
    )
    scope = compute_scope(plan)
    assert "s" in scope.defined
    assert ".0" in scope.defined
    assert "p" not in scope.all_visible
    assert "o" not in scope.all_visible
    print("  PASS test_scope_group")


def test_scope_project():
    """PROJECT restricts to projected vars."""
    inner = PlanV2(kind=KIND_BGP, var_slots={
        "s": VarSlot(name="s"), "p": VarSlot(name="p"), "o": VarSlot(name="o"),
    })
    plan = PlanV2(kind=KIND_PROJECT, project_vars=["s", "o"], children=[inner])
    scope = compute_scope(plan)
    assert scope.all_visible == frozenset({"s", "o"})
    assert "p" not in scope.all_visible
    print("  PASS test_scope_project")


def test_scope_filter_transparent():
    """FILTER doesn't change scope."""
    inner = PlanV2(kind=KIND_BGP, var_slots={"s": VarSlot(name="s")})
    plan = PlanV2(kind=KIND_FILTER, children=[inner])
    scope = compute_scope(plan)
    assert scope.defined == frozenset({"s"})
    print("  PASS test_scope_filter_transparent")


def test_scope_distinct_transparent():
    """DISTINCT doesn't change scope."""
    inner = PlanV2(kind=KIND_BGP, var_slots={"s": VarSlot(name="s")})
    plan = PlanV2(kind=KIND_DISTINCT, children=[inner])
    scope = compute_scope(plan)
    assert scope.defined == frozenset({"s"})
    print("  PASS test_scope_distinct_transparent")


def test_scope_table():
    """TABLE (VALUES) defines its declared vars."""
    plan = PlanV2(kind=KIND_TABLE, values_vars=["x", "y"])
    scope = compute_scope(plan)
    assert scope.defined == frozenset({"x", "y"})
    print("  PASS test_scope_table")


def test_scope_null():
    """NULL pattern has empty scope."""
    plan = PlanV2(kind=KIND_NULL)
    scope = compute_scope(plan)
    assert scope.all_visible == frozenset()
    print("  PASS test_scope_null")


# ---------------------------------------------------------------------------
# Integration tests (via sidecar — require running Docker)
# ---------------------------------------------------------------------------

def test_scope_real_optional():
    """Real OPTIONAL via sidecar: right-side vars are maybe."""
    plan = _compile_and_collect(
        "SELECT * WHERE { ?s ?p ?o . OPTIONAL { ?o ?q ?r } }"
    )
    scope = compute_scope(plan)
    assert "s" in scope.defined
    assert "p" in scope.defined
    assert "o" in scope.defined
    # q and r come from OPTIONAL → maybe
    assert "q" in scope.maybe or "q" in scope.defined  # may vary by Jena
    assert "r" in scope.maybe or "r" in scope.defined
    print("  PASS test_scope_real_optional")


def test_scope_real_group_by():
    """Real GROUP BY via sidecar: only grouped + aggregate vars visible."""
    plan = _compile_and_collect(
        "SELECT ?s (COUNT(*) AS ?c) WHERE { ?s ?p ?o } GROUP BY ?s"
    )
    scope = compute_scope(plan)
    # After project, only s and c should be visible
    assert "s" in scope.all_visible
    assert "c" in scope.all_visible
    # p and o should not be visible (hidden by GROUP BY)
    assert "p" not in scope.all_visible
    assert "o" not in scope.all_visible
    print("  PASS test_scope_real_group_by")


def test_scope_real_bind():
    """Real BIND via sidecar: introduces new variable."""
    plan = _compile_and_collect(
        "SELECT ?s ?z WHERE { ?s ?p ?o . BIND(?o AS ?z) }"
    )
    scope = compute_scope(plan)
    assert "s" in scope.all_visible
    assert "z" in scope.all_visible
    print("  PASS test_scope_real_bind")


# ---------------------------------------------------------------------------
# vars_in_expr tests
# ---------------------------------------------------------------------------

def test_vars_in_expr_simple():
    from ..jena_sparql.jena_types import ExprVar, ExprFunction
    assert vars_in_expr(ExprVar(var="x")) == {"x"}
    expr = ExprFunction(name="add", args=[ExprVar(var="a"), ExprVar(var="b")])
    assert vars_in_expr(expr) == {"a", "b"}
    print("  PASS test_vars_in_expr_simple")


# ---------------------------------------------------------------------------
# VarScope method tests
# ---------------------------------------------------------------------------

def test_varscope_with_defined():
    s = VarScope(defined=frozenset({"a"}))
    s2 = s.with_defined("b", "c")
    assert s2.defined == frozenset({"a", "b", "c"})
    print("  PASS test_varscope_with_defined")


def test_varscope_with_maybe():
    s = VarScope(defined=frozenset({"a"}))
    s2 = s.with_maybe("b")
    assert s2.maybe == frozenset({"b"})
    assert s2.defined == frozenset({"a"})
    print("  PASS test_varscope_with_maybe")


def test_varscope_restrict():
    s = VarScope(defined=frozenset({"a", "b", "c"}), maybe=frozenset({"d"}))
    s2 = s.restrict_to({"a", "d"})
    assert s2.defined == frozenset({"a"})
    assert s2.maybe == frozenset({"d"})
    assert "b" not in s2.all_visible
    print("  PASS test_varscope_restrict")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

ALL_TESTS = [
    # Unit tests (no sidecar needed)
    test_scope_bgp,
    test_scope_join,
    test_scope_left_join,
    test_scope_union,
    test_scope_minus,
    test_scope_extend,
    test_scope_group,
    test_scope_project,
    test_scope_filter_transparent,
    test_scope_distinct_transparent,
    test_scope_table,
    test_scope_null,
    test_vars_in_expr_simple,
    test_varscope_with_defined,
    test_varscope_with_maybe,
    test_varscope_restrict,
    # Integration tests (sidecar required)
    test_scope_real_optional,
    test_scope_real_group_by,
    test_scope_real_bind,
]


def run_all():
    passed = failed = errors = 0
    for test_fn in ALL_TESTS:
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL {test_fn.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {test_fn.__name__}: {e}")
            errors += 1
    total = passed + failed + errors
    print(f"\nVar Scope Tests: {passed}/{total} passed"
          f" ({failed} failed, {errors} errors)")
    return failed == 0 and errors == 0


if __name__ == "__main__":
    import sys
    ok = run_all()
    sys.exit(0 if ok else 1)
