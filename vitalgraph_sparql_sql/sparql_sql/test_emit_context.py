"""
Tests for EmitContext + ProcessingTrace (emit_context.py).
"""

from __future__ import annotations

from .emit_context import EmitContext, ProcessingTrace, TraceStep
from .ir import AliasGenerator
from .sql_type_generation import TypeRegistry


def test_trace_add_and_summary():
    """Trace records steps and produces summary."""
    trace = ProcessingTrace()
    trace.add(0, "emit", "bgp", "emitting BGP with 3 triples")
    trace.add(1, "emit", "filter", "applying FILTER")
    assert len(trace.steps) == 2
    assert trace.max_depth() == 1
    s = trace.summary()
    assert "2 steps" in s
    print("  PASS test_trace_add_and_summary")


def test_trace_log_step():
    """log_step records and returns step."""
    trace = ProcessingTrace()
    step = trace.log_step(0, "collect", "bgp", "collecting BGP")
    assert step.phase == "collect"
    assert step.plan_kind == "bgp"
    print("  PASS test_trace_log_step")


def test_trace_log_sql():
    """log_sql records SQL fragment."""
    trace = ProcessingTrace()
    step = trace.log_sql(0, "bgp", "SELECT * FROM rdf_quad")
    assert step.sql_fragment is not None
    assert "SELECT" in step.sql_fragment
    print("  PASS test_trace_log_sql")


def test_trace_log_column_map():
    """log_column_map records column mapping."""
    trace = ProcessingTrace()
    cols = {"s": "t0.term_text", "p": "t1.term_text"}
    step = trace.log_column_map(0, "bgp", cols)
    assert step.column_map == cols
    print("  PASS test_trace_log_column_map")


def test_trace_print_tree():
    """print_tree produces readable output."""
    trace = ProcessingTrace()
    trace.add(0, "emit", "project", "projecting s, p, o")
    trace.add(1, "emit", "filter", "applying FILTER")
    trace.add(2, "emit", "bgp", "emitting BGP")
    tree = trace.print_tree()
    assert "project" in tree
    assert "  [emit] filter" in tree
    assert "    [emit] bgp" in tree
    print("  PASS test_trace_print_tree")


def test_trace_to_json():
    """to_json produces valid JSON."""
    import json
    trace = ProcessingTrace()
    trace.add(0, "emit", "bgp", "test step")
    j = trace.to_json()
    parsed = json.loads(j)
    assert "steps" in parsed
    assert len(parsed["steps"]) == 1
    print("  PASS test_trace_to_json")


def test_trace_steps_for_kind():
    """Filter steps by plan kind."""
    trace = ProcessingTrace()
    trace.add(0, "emit", "bgp", "step 1")
    trace.add(1, "emit", "filter", "step 2")
    trace.add(2, "emit", "bgp", "step 3")
    bgp_steps = trace.steps_for_kind("bgp")
    assert len(bgp_steps) == 2
    print("  PASS test_trace_steps_for_kind")


def test_trace_column_map_at():
    """column_map_at retrieves correct step."""
    trace = ProcessingTrace()
    trace.add(0, "emit", "bgp", "no columns")
    trace.log_column_map(0, "bgp", {"s": "t0.term_text"})
    assert trace.column_map_at(0) is None
    assert trace.column_map_at(1) == {"s": "t0.term_text"}
    assert trace.column_map_at(99) is None
    print("  PASS test_trace_column_map_at")


# ---------------------------------------------------------------------------
# EmitContext tests
# ---------------------------------------------------------------------------

def test_emit_context_creation():
    """EmitContext initializes with defaults."""
    ctx = EmitContext(space_id="test_space")
    assert ctx.space_id == "test_space"
    assert ctx.quad_table == "test_space_rdf_quad"
    assert ctx.term_table == "test_space_term"
    assert ctx.depth == 0
    assert isinstance(ctx.aliases, AliasGenerator)
    assert isinstance(ctx.types, TypeRegistry)
    assert isinstance(ctx.trace, ProcessingTrace)
    print("  PASS test_emit_context_creation")


def test_emit_context_child():
    """Child context shares aliases/trace but has own type registry."""
    ctx = EmitContext(space_id="test_space")
    ctx.types.register_from_triple("s", "q0.subject_uuid", "t0")

    child = ctx.child()
    assert child.depth == 1
    assert child.aliases is ctx.aliases  # shared
    assert child.trace is ctx.trace  # shared
    assert child.types is not ctx.types  # separate
    assert child.types.has("s")  # inherited

    child.types.register_from_triple("p", "q0.predicate_uuid", "t1")
    assert not ctx.types.has("p")  # parent not affected
    print("  PASS test_emit_context_child")


def test_emit_context_log():
    """Context log methods delegate to trace."""
    ctx = EmitContext(space_id="test")
    ctx.log("bgp", "emitting BGP")
    ctx.log_sql("bgp", "SELECT * FROM test_rdf_quad")
    ctx.log_columns("bgp", {"s": "t0.term_text"})
    assert len(ctx.trace.steps) == 3
    print("  PASS test_emit_context_log")


def test_emit_context_nested_depth():
    """Nested child contexts increment depth."""
    ctx = EmitContext(space_id="test")
    c1 = ctx.child()
    c2 = c1.child()
    c3 = c2.child()
    assert c3.depth == 3
    # All share the same trace
    ctx.log("project", "outer")
    c3.log("bgp", "innermost")
    assert len(ctx.trace.steps) == 2
    assert ctx.trace.steps[0].depth == 0
    assert ctx.trace.steps[1].depth == 3
    print("  PASS test_emit_context_nested_depth")


def test_emit_context_graph_uri():
    """Graph URI propagates to children."""
    ctx = EmitContext(space_id="test", graph_uri="http://example.org/g")
    child = ctx.child()
    assert child.graph_uri == "http://example.org/g"
    print("  PASS test_emit_context_graph_uri")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

ALL_TESTS = [
    test_trace_add_and_summary,
    test_trace_log_step,
    test_trace_log_sql,
    test_trace_log_column_map,
    test_trace_print_tree,
    test_trace_to_json,
    test_trace_steps_for_kind,
    test_trace_column_map_at,
    test_emit_context_creation,
    test_emit_context_child,
    test_emit_context_log,
    test_emit_context_nested_depth,
    test_emit_context_graph_uri,
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
    print(f"\nEmitContext Tests: {passed}/{total} passed"
          f" ({failed} failed, {errors} errors)")
    return failed == 0 and errors == 0


if __name__ == "__main__":
    import sys
    ok = run_all()
    sys.exit(0 if ok else 1)
