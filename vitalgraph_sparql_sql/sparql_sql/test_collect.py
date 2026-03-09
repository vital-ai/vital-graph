"""
Structural tests for the v2 collect pass.

These tests verify that SPARQL queries produce the expected nested PlanV2
tree shapes WITHOUT executing any SQL. They work by:
1. Sending SPARQL to the Jena sidecar for algebra compilation
2. Mapping the JSON response to Op types
3. Running the v2 collect pass
4. Asserting on the plan tree structure

Requires: Jena sidecar running on localhost:7070
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any, Dict, List

from ..jena_sparql.jena_ast_mapper import map_compile_response
from .ir import (
    PlanV2, AliasGenerator,
    KIND_BGP, KIND_JOIN, KIND_LEFT_JOIN, KIND_UNION, KIND_MINUS,
    KIND_TABLE, KIND_NULL, KIND_PATH,
    KIND_PROJECT, KIND_DISTINCT, KIND_REDUCED, KIND_SLICE,
    KIND_ORDER, KIND_FILTER, KIND_EXTEND, KIND_GROUP,
)
from .collect import collect

logger = logging.getLogger(__name__)

SIDECAR_URL = "http://localhost:7070"
SPACE_ID = "test_v2"


def _compile_sparql(sparql: str) -> Dict[str, Any]:
    """Send SPARQL to the sidecar and return the raw JSON response."""
    req = urllib.request.Request(
        f"{SIDECAR_URL}/v1/sparql/compile",
        data=json.dumps({"sparql": sparql}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _collect_sparql(sparql: str) -> PlanV2:
    """Compile SPARQL → Op tree → v2 PlanV2 tree."""
    raw = _compile_sparql(sparql)
    cr = map_compile_response(raw)
    assert cr.ok, f"Sidecar error: {cr.error}"
    assert cr.algebra is not None, "No algebra in response"
    aliases = AliasGenerator()
    return collect(cr.algebra, SPACE_ID, aliases)


def _kind_tree(plan: PlanV2) -> Any:
    """Extract a nested list of kinds for easy structural comparison.

    Returns: kind string for leaves, (kind, [children...]) for nodes with children.
    """
    if not plan.children:
        return plan.kind
    child_trees = [_kind_tree(c) for c in plan.children]
    return (plan.kind, child_trees)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_simple_bgp():
    """SELECT ?s ?p ?o WHERE { ?s ?p ?o } → project(bgp)"""
    plan = _collect_sparql("SELECT ?s ?p ?o WHERE { ?s ?p ?o }")
    assert plan.kind == KIND_PROJECT
    assert plan.project_vars == ["s", "p", "o"]
    assert plan.child.kind == KIND_BGP
    assert "s" in plan.child.var_slots
    assert "p" in plan.child.var_slots
    assert "o" in plan.child.var_slots
    print("  PASS test_simple_bgp")


def test_filter_wraps_bgp():
    """SELECT ?s WHERE { ?s ?p ?o . FILTER(?o > 5) } → project(filter(bgp))"""
    plan = _collect_sparql(
        "SELECT ?s WHERE { ?s ?p ?o . FILTER(?o > 5) }"
    )
    assert plan.kind == KIND_PROJECT
    assert plan.child.kind == KIND_FILTER
    assert len(plan.child.filter_exprs) == 1
    assert plan.child.child.kind == KIND_BGP
    print("  PASS test_filter_wraps_bgp")


def test_optional_is_left_join():
    """SELECT * WHERE { ?s ?p ?o . OPTIONAL { ?o ?q ?r } }
    Jena emits OpLeftJoin at top level for SELECT * (no OpProject wrapper)."""
    plan = _collect_sparql(
        "SELECT * WHERE { ?s ?p ?o . OPTIONAL { ?o ?q ?r } }"
    )
    # Jena may or may not wrap in OpProject for SELECT *
    target = plan.child if plan.kind == KIND_PROJECT else plan
    assert target.kind == KIND_LEFT_JOIN, f"Expected left_join, got {target.kind}"
    assert len(target.children) == 2
    assert target.children[0].kind == KIND_BGP
    assert target.children[1].kind == KIND_BGP
    print("  PASS test_optional_is_left_join")


def test_union():
    """SELECT * WHERE { { ?s ?p ?o } UNION { ?a ?b ?c } }
    Jena emits OpUnion at top level for SELECT * (no OpProject wrapper)."""
    plan = _collect_sparql(
        "SELECT * WHERE { { ?s ?p ?o } UNION { ?a ?b ?c } }"
    )
    target = plan.child if plan.kind == KIND_PROJECT else plan
    assert target.kind == KIND_UNION, f"Expected union, got {target.kind}"
    assert target.children[0].kind == KIND_BGP
    assert target.children[1].kind == KIND_BGP
    print("  PASS test_union")


def test_bind_is_extend():
    """BIND(expr AS ?var) → extend wrapping inner plan"""
    plan = _collect_sparql(
        "SELECT ?s ?z WHERE { ?s ?p ?o . BIND(?o AS ?z) }"
    )
    assert plan.kind == KIND_PROJECT
    # Jena produces: project(extend(join(bgp, table) or extend(bgp)))
    # Walk down to find the extend node
    found_extend = False
    for node in plan.walk():
        if node.kind == KIND_EXTEND:
            assert node.extend_var == "z"
            assert node.extend_expr is not None
            found_extend = True
            break
    assert found_extend, "No extend node found"
    print("  PASS test_bind_is_extend")


def test_group_by_simple():
    """GROUP BY ?s → group(bgp) with group_vars"""
    plan = _collect_sparql(
        "SELECT ?s (COUNT(*) AS ?c) WHERE { ?s ?p ?o } GROUP BY ?s"
    )
    # Walk to find group node
    found_group = False
    for node in plan.walk():
        if node.kind == KIND_GROUP:
            assert len(node.group_vars) == 1
            assert node.group_vars[0].var == "s"
            assert node.group_vars[0].expr is None  # plain var, no expr
            assert node.aggregates is not None
            found_group = True
            break
    assert found_group, "No group node found"
    print("  PASS test_group_by_simple")


def test_group_by_expr_alias():
    """GROUP BY (DATATYPE(?o) AS ?d) → group with expr on GroupVar"""
    plan = _collect_sparql(
        "SELECT ?d (COUNT(*) AS ?c) WHERE { ?s ?p ?o } "
        "GROUP BY (DATATYPE(?o) AS ?d)"
    )
    found_group = False
    for node in plan.walk():
        if node.kind == KIND_GROUP:
            assert len(node.group_vars) == 1
            gv = node.group_vars[0]
            assert gv.var == "d"
            assert gv.expr is not None, "GROUP BY expression alias not preserved!"
            assert gv.expr.name == "datatype"
            found_group = True
            break
    assert found_group, "No group node found"
    print("  PASS test_group_by_expr_alias")


def test_distinct():
    """SELECT DISTINCT ?s → distinct(project(bgp))"""
    plan = _collect_sparql(
        "SELECT DISTINCT ?s WHERE { ?s ?p ?o }"
    )
    assert plan.kind == KIND_DISTINCT
    assert plan.child.kind == KIND_PROJECT
    print("  PASS test_distinct")


def test_order_limit_offset():
    """ORDER BY ?s LIMIT 10 OFFSET 5 → slice(project(order(bgp)))
    Jena nesting: OpSlice wraps OpProject wraps OpOrder."""
    plan = _collect_sparql(
        "SELECT ?s WHERE { ?s ?p ?o } ORDER BY ?s LIMIT 10 OFFSET 5"
    )
    assert plan.kind == KIND_SLICE
    assert plan.limit == 10
    assert plan.offset == 5
    # Jena: slice → project → order
    assert plan.child.kind == KIND_PROJECT
    assert plan.child.child.kind == KIND_ORDER
    assert len(plan.child.child.order_conditions) == 1
    print("  PASS test_order_limit_offset")


def test_values():
    """VALUES clause → table node"""
    plan = _collect_sparql(
        "SELECT ?x WHERE { VALUES ?x { 1 2 3 } }"
    )
    found_table = False
    for node in plan.walk():
        if node.kind == KIND_TABLE:
            assert node.values_vars is not None
            assert "x" in node.values_vars
            found_table = True
            break
    assert found_table, "No table node found"
    print("  PASS test_values")


def test_minus():
    """MINUS → minus(bgp, bgp)"""
    plan = _collect_sparql(
        "SELECT ?s WHERE { ?s ?p ?o MINUS { ?s ?q ?r } }"
    )
    found_minus = False
    for node in plan.walk():
        if node.kind == KIND_MINUS:
            assert len(node.children) == 2
            found_minus = True
            break
    assert found_minus, "No minus node found"
    print("  PASS test_minus")


def test_nested_modifiers_preserve_order():
    """The key structural test: modifiers must be nested, not flattened.

    SELECT ?s (COUNT(*) AS ?c)
    WHERE { ?s ?p ?o . FILTER(?o > 5) }
    GROUP BY ?s
    HAVING (COUNT(*) > 1)
    ORDER BY ?c
    LIMIT 10

    Expected nesting (outermost first):
      slice → order → project → filter → extend → group → filter → bgp

    In v1, the filter/extend/group/order/slice would all be flattened onto bgp.
    """
    plan = _collect_sparql("""
        SELECT ?s (COUNT(*) AS ?c)
        WHERE { ?s ?p ?o . FILTER(?o > 5) }
        GROUP BY ?s
        HAVING (COUNT(*) > 1)
        ORDER BY ?c
        LIMIT 10
    """)

    # Walk down the spine collecting modifier kinds
    spine = []
    node = plan
    while node.is_modifier:
        spine.append(node.kind)
        node = node.child
    spine.append(node.kind)  # final relation kind

    # Verify nesting order (outermost to innermost)
    assert spine[0] == KIND_SLICE, f"Expected slice at top, got {spine[0]}"
    assert KIND_ORDER in spine, "Expected order in spine"
    assert KIND_PROJECT in spine, "Expected project in spine"
    assert KIND_GROUP in spine, "Expected group in spine"
    assert spine[-1] == KIND_BGP, f"Expected bgp at bottom, got {spine[-1]}"

    # Verify group is below project (correct evaluation order)
    proj_idx = spine.index(KIND_PROJECT)
    grp_idx = spine.index(KIND_GROUP)
    assert grp_idx > proj_idx, (
        f"group (idx {grp_idx}) should be nested deeper than project (idx {proj_idx})"
    )

    print(f"  PASS test_nested_modifiers_preserve_order (spine: {spine})")


def test_complex_aggregate_inner_expr():
    """AVG(IF(isNumeric(?p), ?p, 0)) should have ExprFunction inner, not None"""
    plan = _collect_sparql(
        "SELECT (AVG(IF(isNumeric(?p), ?p, 0)) AS ?avg) "
        "WHERE { ?s ?p ?o } GROUP BY ?s"
    )
    found_group = False
    for node in plan.walk():
        if node.kind == KIND_GROUP:
            assert node.aggregates is not None
            for var, agg in node.aggregates.items():
                assert agg.expr is not None, (
                    f"Aggregate {var} has None inner expr — "
                    "complex expression was dropped!"
                )
                assert agg.expr.name == "if", (
                    f"Expected IF inner expr, got {agg.expr.name}"
                )
            found_group = True
            break
    assert found_group
    print("  PASS test_complex_aggregate_inner_expr")


def test_base_uri_in_metadata():
    """BASE URI should be in ParsedQueryMeta"""
    raw = _compile_sparql("BASE <http://example.org/> SELECT ?s WHERE { ?s ?p ?o }")
    cr = map_compile_response(raw)
    assert cr.meta.base_uri == "http://example.org/"
    print("  PASS test_base_uri_in_metadata")


def test_summary_output():
    """Verify summary() produces readable output without crashing."""
    plan = _collect_sparql(
        "SELECT ?s (COUNT(*) AS ?c) WHERE { ?s ?p ?o } "
        "GROUP BY ?s ORDER BY ?c LIMIT 5"
    )
    summary = plan.summary()
    assert "slice" in summary
    assert "order" in summary
    assert "group" in summary
    assert "bgp" in summary
    print(f"  PASS test_summary_output\n{summary}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

ALL_TESTS = [
    test_simple_bgp,
    test_filter_wraps_bgp,
    test_optional_is_left_join,
    test_union,
    test_bind_is_extend,
    test_group_by_simple,
    test_group_by_expr_alias,
    test_distinct,
    test_order_limit_offset,
    test_values,
    test_minus,
    test_nested_modifiers_preserve_order,
    test_complex_aggregate_inner_expr,
    test_base_uri_in_metadata,
    test_summary_output,
]


def run_all():
    """Run all structural tests."""
    passed = 0
    failed = 0
    errors = 0

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
    print(f"\nv2 Collect Tests: {passed}/{total} passed"
          f" ({failed} failed, {errors} errors)")
    return failed == 0 and errors == 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import sys
    ok = run_all()
    sys.exit(0 if ok else 1)
