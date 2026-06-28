#!/usr/bin/env python3
"""
Regression tests for SPARQL VALUES bug fix.

Root cause: compute_text_needed_vars() did not mark VALUES variables as
"referenced", so when a variable appeared in both a BGP and an inline
VALUES clause but was NOT projected or filtered, the BGP skipped term
table resolution for that variable.  The resulting NULL text column
caused the JOIN condition (text equality) against the VALUES literals
to always fail → 0 results.

Fix: _collect_referenced_vars() now includes KIND_TABLE.values_vars in
the referenced set, ensuring the BGP always resolves text for variables
that participate in VALUES joins.

Run:
    python test_scripts/sparql/test_values_text_needed.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from vitalgraph.db.sparql_sql.ir import (
    PlanV2, VarSlot, TableRef,
    KIND_BGP, KIND_JOIN, KIND_LEFT_JOIN, KIND_TABLE,
    KIND_PROJECT, KIND_FILTER,
)
from vitalgraph.db.sparql_sql.var_scope import (
    compute_scope, compute_text_needed_vars,
)
from vitalgraph.db.jena_sparql.jena_types import (
    URINode, LiteralNode, ExprFunction, ExprVar,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bgp(*vars_with_terms):
    """Build a BGP plan with term refs for given variable names."""
    var_slots = {}
    tables = []
    for i, name in enumerate(vars_with_terms):
        ref_id = f"t{i}"
        var_slots[name] = VarSlot(
            name=name, term_ref_id=ref_id,
            positions=[(f"q{i}", "object_uuid")],
        )
        tables.append(TableRef(
            ref_id=ref_id, kind="term",
            table_name="test_term", join_col="", alias=ref_id,
        ))
    plan = PlanV2(kind=KIND_BGP, var_slots=var_slots)
    plan.tables = tables
    return plan


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_text_needed_values_shared_var():
    """VALUES variable shared with BGP MUST be in text_needed_vars.

    This is the core regression test for the VALUES bug: ?vt is in both
    the BGP and the VALUES table but is NOT projected or filtered.
    Without the fix, ?vt was excluded from text_needed_vars, its text
    was NULL, and the JOIN condition always failed.
    """
    bgp = _make_bgp("s", "vt", "name")
    table = PlanV2(
        kind=KIND_TABLE,
        values_vars=["vt"],
        values_rows=[
            {"vt": URINode(value="http://vital.ai/ontology/haley-ai-kg#KGType")},
            {"vt": URINode(value="http://vital.ai/ontology/haley-ai-kg#KGFrameType")},
        ],
    )
    join = PlanV2(kind=KIND_JOIN, children=[bgp, table])
    filt = PlanV2(kind=KIND_FILTER, children=[join])
    filt.filter_exprs = [
        ExprFunction(name="contains", args=[ExprVar(var="name"), ExprVar(var="name")])
    ]
    proj = PlanV2(kind=KIND_PROJECT, children=[filt])
    proj.project_vars = ["s", "name"]

    text_needed = compute_text_needed_vars(proj)

    assert "vt" in text_needed, (
        f"FAIL: vt must be in text_needed_vars for VALUES join. "
        f"Got: {sorted(text_needed)}"
    )
    assert "s" in text_needed
    assert "name" in text_needed
    print("  PASS test_text_needed_values_shared_var")


def test_text_needed_values_only_var_excluded():
    """A VALUES-only variable (not in any BGP) is NOT in text_needed_vars.

    text_needed_vars tracks BGP variables that need term-table JOINs.
    A variable that exists ONLY in a TABLE node already has its text
    inline (as a literal string) — no term resolution needed.
    """
    bgp = _make_bgp("s", "o")
    table = PlanV2(
        kind=KIND_TABLE,
        values_vars=["x"],
        values_rows=[{"x": URINode(value="http://ex.org/A")}],
    )
    join = PlanV2(kind=KIND_JOIN, children=[bgp, table])
    proj = PlanV2(kind=KIND_PROJECT, children=[join])
    proj.project_vars = ["s", "o", "x"]

    text_needed = compute_text_needed_vars(proj)

    assert "x" not in text_needed, (
        f"FAIL: x is only in TABLE (not BGP), should not be in text_needed. "
        f"Got: {sorted(text_needed)}"
    )
    assert "s" in text_needed
    assert "o" in text_needed
    print("  PASS test_text_needed_values_only_var_excluded")


def test_text_needed_internal_var_without_values():
    """Without VALUES, an internal-only BGP var is correctly excluded."""
    bgp = _make_bgp("s", "internal")
    proj = PlanV2(kind=KIND_PROJECT, children=[bgp])
    proj.project_vars = ["s"]

    text_needed = compute_text_needed_vars(proj)

    assert "s" in text_needed
    assert "internal" not in text_needed, (
        f"FAIL: 'internal' is not projected/filtered, should be excluded. "
        f"Got: {sorted(text_needed)}"
    )
    print("  PASS test_text_needed_internal_var_without_values")


def test_text_needed_values_left_join():
    """VALUES variable in a LEFT JOIN still gets text resolution."""
    bgp = _make_bgp("s", "name")
    table = PlanV2(
        kind=KIND_TABLE,
        values_vars=["cat"],
        values_rows=[
            {"cat": LiteralNode(value="A", lang=None, datatype=None)},
            {"cat": LiteralNode(value="B", lang=None, datatype=None)},
        ],
    )
    # BGP with cat variable too
    bgp_with_cat = _make_bgp("s", "cat", "name")
    left_join = PlanV2(kind=KIND_LEFT_JOIN, children=[bgp_with_cat, table])
    proj = PlanV2(kind=KIND_PROJECT, children=[left_join])
    proj.project_vars = ["s", "name"]

    text_needed = compute_text_needed_vars(proj)

    assert "cat" in text_needed, (
        f"FAIL: cat shared with VALUES TABLE must be in text_needed. "
        f"Got: {sorted(text_needed)}"
    )
    print("  PASS test_text_needed_values_left_join")


def test_scope_table_defines_vars():
    """TABLE (VALUES) scope defines its declared variables."""
    table = PlanV2(
        kind=KIND_TABLE,
        values_vars=["x", "y"],
        values_rows=[{"x": URINode(value="a"), "y": URINode(value="b")}],
    )
    scope = compute_scope(table)
    assert scope.defined == frozenset({"x", "y"})
    assert scope.all_visible == frozenset({"x", "y"})
    print("  PASS test_scope_table_defines_vars")


def test_scope_join_with_table():
    """JOIN(BGP, TABLE) merges both scopes — shared var in both."""
    bgp = _make_bgp("s", "vt", "name")
    table = PlanV2(kind=KIND_TABLE, values_vars=["vt"],
                   values_rows=[{"vt": URINode(value="http://ex.org/T")}])
    join = PlanV2(kind=KIND_JOIN, children=[bgp, table])

    scope = compute_scope(join)
    assert "s" in scope.all_visible
    assert "vt" in scope.all_visible
    assert "name" in scope.all_visible
    print("  PASS test_scope_join_with_table")


def test_text_needed_multiple_values_vars():
    """Multiple VALUES variables all get text resolution."""
    bgp = _make_bgp("s", "type", "status")
    table = PlanV2(
        kind=KIND_TABLE,
        values_vars=["type", "status"],
        values_rows=[
            {"type": URINode(value="http://ex.org/T1"), "status": LiteralNode(value="active", lang=None, datatype=None)},
        ],
    )
    join = PlanV2(kind=KIND_JOIN, children=[bgp, table])
    proj = PlanV2(kind=KIND_PROJECT, children=[join])
    proj.project_vars = ["s"]

    text_needed = compute_text_needed_vars(proj)

    assert "type" in text_needed, f"FAIL: type missing. Got: {sorted(text_needed)}"
    assert "status" in text_needed, f"FAIL: status missing. Got: {sorted(text_needed)}"
    assert "s" in text_needed
    print("  PASS test_text_needed_multiple_values_vars")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

ALL_TESTS = [
    test_text_needed_values_shared_var,
    test_text_needed_values_only_var_excluded,
    test_text_needed_internal_var_without_values,
    test_text_needed_values_left_join,
    test_scope_table_defines_vars,
    test_scope_join_with_table,
    test_text_needed_multiple_values_vars,
]


def main():
    print("SPARQL VALUES text_needed_vars regression tests")
    print("=" * 55)
    passed = failed = 0
    for test_fn in ALL_TESTS:
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL {test_fn.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {test_fn.__name__}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\nResults: {passed}/{passed + failed} passed")
    if failed:
        print(f"  {failed} FAILED")
    return failed == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
