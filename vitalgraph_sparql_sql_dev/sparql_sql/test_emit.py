"""
End-to-end emit tests for the v2 pipeline.

SPARQL → sidecar → Op tree → PlanV2 (collect) → SQL (emit)

These tests verify that the v2 emitter produces valid SQL for various
SPARQL query patterns. They do NOT execute the SQL against a database —
they only verify that SQL is generated without errors and has expected
structural properties.

Requires: Jena sidecar running on localhost:7070
"""

from __future__ import annotations

import json
import logging
import urllib.request

from ..jena_sparql.jena_ast_mapper import map_compile_response

from .ir import AliasGenerator, PlanV2
from .collect import collect
from .emit import emit
from .emit_context import EmitContext

logger = logging.getLogger(__name__)

SIDECAR_URL = "http://localhost:7070"
SPACE_ID = "dawg_test"


def _sparql_to_sql(sparql: str) -> str:
    """Full v2 pipeline: SPARQL → SQL string."""
    req = urllib.request.Request(
        f"{SIDECAR_URL}/v1/sparql/compile",
        data=json.dumps({"sparql": sparql}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        raw = json.loads(resp.read())

    cr = map_compile_response(raw)
    assert cr.ok, f"Sidecar error: {cr.error}"

    aliases = AliasGenerator()
    plan = collect(cr.algebra, SPACE_ID, aliases)

    ctx = EmitContext(space_id=SPACE_ID, aliases=aliases)
    sql = emit(plan, ctx)
    return sql


def _assert_sql_has(sql: str, *fragments: str):
    """Assert SQL contains all given fragments (case-insensitive)."""
    sql_lower = sql.lower()
    for frag in fragments:
        assert frag.lower() in sql_lower, (
            f"Expected '{frag}' in SQL:\n{sql[:500]}"
        )


# ---------------------------------------------------------------------------
# Simple BGP
# ---------------------------------------------------------------------------

def test_emit_simple_bgp():
    """Simple triple pattern produces SELECT with FROM quad table."""
    sql = _sparql_to_sql("SELECT ?s ?p ?o WHERE { ?s ?p ?o }")
    _assert_sql_has(sql, "SELECT", "FROM", "dawg_test")
    assert len(sql) > 50
    print("  PASS test_emit_simple_bgp")


def test_emit_bgp_with_constant():
    """BGP with a constant predicate."""
    sql = _sparql_to_sql("""
        SELECT ?s ?o WHERE {
            ?s <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> ?o
        }
    """)
    _assert_sql_has(sql, "SELECT", "FROM")
    print("  PASS test_emit_bgp_with_constant")


# ---------------------------------------------------------------------------
# FILTER
# ---------------------------------------------------------------------------

def test_emit_filter():
    """FILTER wraps child in WHERE clause."""
    sql = _sparql_to_sql("""
        SELECT ?s ?o WHERE {
            ?s ?p ?o .
            FILTER(?o = "hello")
        }
    """)
    _assert_sql_has(sql, "SELECT", "WHERE")
    print("  PASS test_emit_filter")


# ---------------------------------------------------------------------------
# OPTIONAL (LEFT JOIN)
# ---------------------------------------------------------------------------

def test_emit_optional():
    """OPTIONAL produces LEFT JOIN."""
    sql = _sparql_to_sql("""
        SELECT * WHERE {
            ?s ?p ?o .
            OPTIONAL { ?o ?q ?r }
        }
    """)
    _assert_sql_has(sql, "LEFT JOIN")
    print("  PASS test_emit_optional")


# ---------------------------------------------------------------------------
# UNION
# ---------------------------------------------------------------------------

def test_emit_union():
    """UNION produces UNION ALL."""
    sql = _sparql_to_sql("""
        SELECT * WHERE {
            { ?s <http://ex.org/a> ?o }
            UNION
            { ?s <http://ex.org/b> ?o }
        }
    """)
    _assert_sql_has(sql, "UNION ALL")
    print("  PASS test_emit_union")


# ---------------------------------------------------------------------------
# BIND / EXTEND
# ---------------------------------------------------------------------------

def test_emit_bind():
    """BIND produces computed column."""
    sql = _sparql_to_sql("""
        SELECT ?s ?z WHERE {
            ?s ?p ?o .
            BIND(?o AS ?z)
        }
    """)
    _assert_sql_has(sql, "SELECT")
    # BIND should produce companion columns (__type, __lang, etc.)
    # With opaque naming, SPARQL names don't appear — check for companion pattern
    assert "__type" in sql, f"Expected companion columns in SQL:\n{sql[:500]}"
    assert "__datatype" in sql, f"Expected __datatype companion in SQL:\n{sql[:500]}"
    print("  PASS test_emit_bind")


# ---------------------------------------------------------------------------
# GROUP BY + aggregate
# ---------------------------------------------------------------------------

def test_emit_group_by_count():
    """GROUP BY with COUNT produces GROUP BY + COUNT(*)."""
    sql = _sparql_to_sql("""
        SELECT ?s (COUNT(*) AS ?c) WHERE {
            ?s ?p ?o
        } GROUP BY ?s
    """)
    _assert_sql_has(sql, "GROUP BY", "COUNT")
    print("  PASS test_emit_group_by_count")


# ---------------------------------------------------------------------------
# DISTINCT
# ---------------------------------------------------------------------------

def test_emit_distinct():
    """DISTINCT wraps with SELECT DISTINCT."""
    sql = _sparql_to_sql("""
        SELECT DISTINCT ?s WHERE { ?s ?p ?o }
    """)
    _assert_sql_has(sql, "DISTINCT")
    print("  PASS test_emit_distinct")


# ---------------------------------------------------------------------------
# ORDER BY + LIMIT + OFFSET
# ---------------------------------------------------------------------------

def test_emit_order_limit():
    """ORDER BY + LIMIT + OFFSET."""
    sql = _sparql_to_sql("""
        SELECT ?s WHERE { ?s ?p ?o }
        ORDER BY ?s LIMIT 10 OFFSET 5
    """)
    _assert_sql_has(sql, "ORDER BY", "LIMIT 10", "OFFSET 5")
    print("  PASS test_emit_order_limit")


# ---------------------------------------------------------------------------
# VALUES
# ---------------------------------------------------------------------------

def test_emit_values():
    """VALUES inline data."""
    sql = _sparql_to_sql("""
        SELECT ?x WHERE {
            VALUES ?x { "a" "b" "c" }
            ?x ?p ?o .
        }
    """)
    _assert_sql_has(sql, "SELECT")
    print("  PASS test_emit_values")


# ---------------------------------------------------------------------------
# MINUS
# ---------------------------------------------------------------------------

def test_emit_minus():
    """MINUS produces NOT EXISTS."""
    sql = _sparql_to_sql("""
        SELECT ?s WHERE {
            ?s ?p ?o .
            MINUS { ?s <http://ex.org/bad> ?o }
        }
    """)
    _assert_sql_has(sql, "NOT EXISTS")
    print("  PASS test_emit_minus")


# ---------------------------------------------------------------------------
# Nested modifiers
# ---------------------------------------------------------------------------

def test_emit_nested_modifiers():
    """Complex query with GROUP BY + COUNT + ORDER + LIMIT."""
    sql = _sparql_to_sql("""
        SELECT ?s (COUNT(?o) AS ?c) WHERE {
            ?s ?p ?o
        }
        GROUP BY ?s
        ORDER BY ?s
        LIMIT 5
    """)
    _assert_sql_has(sql, "SELECT", "GROUP BY", "ORDER BY", "LIMIT 5")
    print("  PASS test_emit_nested_modifiers")


# ---------------------------------------------------------------------------
# Trace output
# ---------------------------------------------------------------------------

def test_emit_trace():
    """Verify trace records steps during emission."""
    req = urllib.request.Request(
        f"{SIDECAR_URL}/v1/sparql/compile",
        data=json.dumps({"sparql": "SELECT ?s WHERE { ?s ?p ?o }"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        raw = json.loads(resp.read())
    cr = map_compile_response(raw)
    aliases = AliasGenerator()
    plan = collect(cr.algebra, SPACE_ID, aliases)
    ctx = EmitContext(space_id=SPACE_ID, aliases=aliases)
    sql = emit(plan, ctx)

    assert len(ctx.trace.steps) > 0, "Trace should record steps"
    tree = ctx.trace.print_tree()
    assert "bgp" in tree.lower(), f"Trace should mention bgp:\n{tree}"
    print(f"  PASS test_emit_trace ({len(ctx.trace.steps)} trace steps)")


def test_trace_structural():
    """§8.4: Structural testing — verify trace APIs without SQL execution."""
    from .emit_context import ProcessingTrace
    sparql = "SELECT ?s WHERE { ?s ?p ?o }"
    req = urllib.request.Request(
        f"{SIDECAR_URL}/v1/sparql/compile",
        data=json.dumps({"sparql": sparql}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        raw = json.loads(resp.read())
    cr = map_compile_response(raw)
    aliases = AliasGenerator()
    plan = collect(cr.algebra, SPACE_ID, aliases)
    trace = ProcessingTrace(sparql_query=sparql)
    ctx = EmitContext(space_id=SPACE_ID, aliases=aliases, trace=trace)
    sql = emit(plan, ctx)

    # §8.4: find_step by phase
    dispatch = trace.find_step(phase="dispatch")
    assert dispatch is not None, "Should find a dispatch step"

    # §8.4: find_step by plan_kind
    bgp_step = trace.find_step(plan_kind="bgp")
    assert bgp_step is not None, "Should find a bgp step"

    # §8.4: column map phases exist
    col_steps = trace.steps_for_phase("columns")
    assert len(col_steps) > 0, f"Should have column map steps, got {len(col_steps)}"

    # §8.4: final_column_map returns registered vars
    final = trace.final_column_map()
    # At least 's' should be in the column map (projected variable)
    found_s = any('s' in k for k in final.keys())
    assert found_s, f"final_column_map should include 's': {final}"

    # §8.4: scope steps exist
    scope_steps = trace.steps_for_phase("scope")
    assert len(scope_steps) > 0, f"Should have scope steps, got {len(scope_steps)}"

    # §8.4: sparql_query stored on trace
    assert trace.sparql_query == sparql

    # §8.4: print_tree includes SPARQL header
    tree = trace.print_tree()
    assert "SPARQL:" in tree, f"print_tree should include SPARQL header:\n{tree[:200]}"

    # §8.4: trace_enabled=False suppresses trace
    aliases2 = AliasGenerator()
    plan2 = collect(cr.algebra, SPACE_ID, aliases2)
    ctx2 = EmitContext(space_id=SPACE_ID, aliases=aliases2, trace_enabled=False)
    sql2 = emit(plan2, ctx2)
    assert len(ctx2.trace.steps) == 0, (
        f"trace_enabled=False should produce 0 steps, got {len(ctx2.trace.steps)}")

    print(f"  PASS test_trace_structural ({len(trace.steps)} steps, "
          f"{len(col_steps)} column maps, {len(scope_steps)} scope logs)")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

ALL_TESTS = [
    test_emit_simple_bgp,
    test_emit_bgp_with_constant,
    test_emit_filter,
    test_emit_optional,
    test_emit_union,
    test_emit_bind,
    test_emit_group_by_count,
    test_emit_distinct,
    test_emit_order_limit,
    test_emit_values,
    test_emit_minus,
    test_emit_nested_modifiers,
    test_emit_trace,
    test_trace_structural,
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
            print(f"  ERROR {test_fn.__name__}: {type(e).__name__}: {e}")
            errors += 1
    total = passed + failed + errors
    print(f"\nv2 Emit Tests: {passed}/{total} passed"
          f" ({failed} failed, {errors} errors)")
    return failed == 0 and errors == 0


if __name__ == "__main__":
    import sys
    ok = run_all()
    sys.exit(0 if ok else 1)
