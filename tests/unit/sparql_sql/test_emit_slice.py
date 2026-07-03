"""Unit tests for emit_slice.py — LIMIT/OFFSET emission."""
# pyright: reportOperatorIssue=false, reportArgumentType=false

from __future__ import annotations

from vitalgraph.db.sparql_sql.ir import (
    PlanV2, KIND_SLICE, KIND_ORDER, KIND_PROJECT, KIND_DISTINCT,
)

from .emit_helpers import _make_ctx, _leaf_bgp


class TestEmitSlice:
    """Tests for emit_slice.py — LIMIT/OFFSET emission."""

    def test_limit_only(self):
        """LIMIT 10 should append LIMIT clause."""
        ctx = _make_ctx({"s": "text"})
        plan = PlanV2(
            kind=KIND_SLICE,
            limit=10,
            offset=0,
            children=[_leaf_bgp()],
        )
        from vitalgraph.db.sparql_sql.emit_slice import emit_slice
        sql = emit_slice(plan, ctx)
        assert "LIMIT 10" in sql
        assert "OFFSET" not in sql

    def test_offset_only(self):
        """OFFSET 5 should append OFFSET clause."""
        ctx = _make_ctx({"s": "text"})
        plan = PlanV2(
            kind=KIND_SLICE,
            limit=-1,
            offset=5,
            children=[_leaf_bgp()],
        )
        from vitalgraph.db.sparql_sql.emit_slice import emit_slice
        sql = emit_slice(plan, ctx)
        assert "OFFSET 5" in sql
        assert "LIMIT" not in sql

    def test_limit_and_offset(self):
        """LIMIT 10 OFFSET 20 should produce both clauses."""
        ctx = _make_ctx({"s": "text"})
        plan = PlanV2(
            kind=KIND_SLICE,
            limit=10,
            offset=20,
            children=[_leaf_bgp()],
        )
        from vitalgraph.db.sparql_sql.emit_slice import emit_slice
        sql = emit_slice(plan, ctx)
        assert "LIMIT 10" in sql
        assert "OFFSET 20" in sql

    def test_no_limit_no_offset_passthrough(self):
        """No LIMIT and no OFFSET → return child SQL unchanged."""
        ctx = _make_ctx({"s": "text"})
        plan = PlanV2(
            kind=KIND_SLICE,
            limit=-1,
            offset=0,
            children=[_leaf_bgp()],
        )
        from vitalgraph.db.sparql_sql.emit_slice import emit_slice
        sql = emit_slice(plan, ctx)
        # Should be identical to child SQL
        assert "LIMIT" not in sql
        assert "OFFSET" not in sql

    def test_buried_order_in_distinct(self):
        """SLICE wrapping DISTINCT→PROJECT→ORDER should re-apply ORDER BY."""
        from vitalgraph.db.sparql_sql.emit_slice import _find_buried_order
        order_node = PlanV2(
            kind=KIND_ORDER,
            order_conditions=[("s", "ASC"), ("o", "DESC")],
            children=[_leaf_bgp()],
        )
        project_node = PlanV2(
            kind=KIND_PROJECT,
            project_vars=["s", "o"],
            children=[order_node],
        )
        distinct_node = PlanV2(
            kind=KIND_DISTINCT,
            children=[project_node],
        )
        result = _find_buried_order(distinct_node)
        assert len(result) == 2
        assert result[0] == ("s", "ASC")
        assert result[1] == ("o", "DESC")

    def test_buried_order_not_found(self):
        """No ORDER in child chain → empty list."""
        from vitalgraph.db.sparql_sql.emit_slice import _find_buried_order
        project_node = PlanV2(
            kind=KIND_PROJECT,
            project_vars=["s"],
            children=[_leaf_bgp()],
        )
        distinct_node = PlanV2(
            kind=KIND_DISTINCT,
            children=[project_node],
        )
        result = _find_buried_order(distinct_node)
        assert result == []

    def test_buried_order_depth_limit(self):
        """Depth > 4 → stop searching."""
        from vitalgraph.db.sparql_sql.emit_slice import _find_buried_order
        # Build a chain of 6 DISTINCT nodes
        node = PlanV2(kind=KIND_ORDER, order_conditions=[("x", "ASC")],
                      children=[_leaf_bgp()])
        for _ in range(6):
            node = PlanV2(kind=KIND_DISTINCT, children=[node])
        result = _find_buried_order(node)
        assert result == []

    def test_slice_with_reorder(self):
        """SLICE wrapping DISTINCT with buried ORDER → re-apply ORDER BY."""
        ctx = _make_ctx({"s": "text", "o": "text"})
        order_node = PlanV2(
            kind=KIND_ORDER,
            order_conditions=[("s", "ASC")],
            children=[_leaf_bgp()],
        )
        project_node = PlanV2(
            kind=KIND_PROJECT,
            project_vars=["s", "o"],
            children=[order_node],
        )
        distinct_node = PlanV2(
            kind=KIND_DISTINCT,
            children=[project_node],
        )
        plan = PlanV2(
            kind=KIND_SLICE,
            limit=10,
            children=[distinct_node],
        )
        from vitalgraph.db.sparql_sql.emit_slice import emit_slice
        sql = emit_slice(plan, ctx)
        assert "ORDER BY" in sql
        assert "LIMIT 10" in sql
