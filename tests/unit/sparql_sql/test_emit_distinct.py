"""Unit tests for emit_distinct.py — DISTINCT/REDUCED modifier."""
# pyright: reportOperatorIssue=false, reportArgumentType=false

from __future__ import annotations

from vitalgraph.db.sparql_sql.ir import (
    PlanV2, KIND_DISTINCT, KIND_REDUCED, KIND_PROJECT, KIND_ORDER,
    KIND_FILTER, KIND_BGP,
)

from .emit_helpers import _make_ctx, _leaf_bgp


class TestEmitDistinct:
    """Tests for emit_distinct.py — DISTINCT/REDUCED modifier."""

    def test_simple_distinct(self):
        """Basic DISTINCT wraps child with SELECT DISTINCT *."""
        ctx = _make_ctx({"s": "text"})
        plan = PlanV2(
            kind=KIND_DISTINCT,
            children=[_leaf_bgp()],
        )
        from vitalgraph.db.sparql_sql.emit_distinct import emit_distinct
        sql = emit_distinct(plan, ctx)
        assert "DISTINCT" in sql

    def test_reduced_same_as_distinct(self):
        """REDUCED uses same handler as DISTINCT."""
        ctx = _make_ctx({"s": "text"})
        plan = PlanV2(
            kind=KIND_REDUCED,
            children=[_leaf_bgp()],
        )
        from vitalgraph.db.sparql_sql.emit_distinct import emit_distinct
        sql = emit_distinct(plan, ctx)
        assert "DISTINCT" in sql

    # --- Pushdown checks ---

    def test_can_pushdown_true(self):
        """text_needed non-empty + simple child chain → True."""
        from vitalgraph.db.sparql_sql.emit_distinct import _can_pushdown
        ctx = _make_ctx({"s": "text"}, text_needed={"s"})
        plan = PlanV2(
            kind=KIND_DISTINCT,
            children=[_leaf_bgp()],
        )
        assert _can_pushdown(plan, ctx) is True

    def test_can_pushdown_false_no_text_needed(self):
        """text_needed_vars=None → False."""
        from vitalgraph.db.sparql_sql.emit_distinct import _can_pushdown
        ctx = _make_ctx({"s": "text"}, text_needed=None)
        plan = PlanV2(
            kind=KIND_DISTINCT,
            children=[_leaf_bgp()],
        )
        assert _can_pushdown(plan, ctx) is False

    def test_can_pushdown_false_empty_text_needed(self):
        """text_needed_vars=set() (empty) → False."""
        from vitalgraph.db.sparql_sql.emit_distinct import _can_pushdown
        ctx = _make_ctx({"s": "text"}, text_needed=set())
        plan = PlanV2(
            kind=KIND_DISTINCT,
            children=[_leaf_bgp()],
        )
        assert _can_pushdown(plan, ctx) is False

    def test_can_pushdown_false_unsafe_child(self):
        """FILTER child → False (may reference text)."""
        from vitalgraph.db.sparql_sql.emit_distinct import _can_pushdown
        ctx = _make_ctx({"s": "text"}, text_needed={"s"})
        plan = PlanV2(
            kind=KIND_DISTINCT,
            children=[PlanV2(kind=KIND_FILTER, children=[_leaf_bgp()])],
        )
        assert _can_pushdown(plan, ctx) is False

    def test_can_pushdown_through_safe_modifiers(self):
        """PROJECT → ORDER → BGP chain → True."""
        from vitalgraph.db.sparql_sql.emit_distinct import _can_pushdown
        ctx = _make_ctx({"s": "text"}, text_needed={"s"})
        plan = PlanV2(
            kind=KIND_DISTINCT,
            children=[PlanV2(
                kind=KIND_PROJECT,
                project_vars=["s"],
                children=[PlanV2(
                    kind=KIND_ORDER,
                    children=[_leaf_bgp()],
                )],
            )],
        )
        assert _can_pushdown(plan, ctx) is True

    # --- _output_vars ---

    def test_output_vars_from_project(self):
        """PROJECT vars should be returned."""
        from vitalgraph.db.sparql_sql.emit_distinct import _output_vars
        ctx = _make_ctx({"s": "text", "p": "text", "o": "text"})
        node = PlanV2(
            kind=KIND_PROJECT,
            project_vars=["s", "o"],
            children=[_leaf_bgp()],
        )
        result = _output_vars(node, ctx)
        assert result == ["s", "o"]

    def test_output_vars_no_project(self):
        """No PROJECT → all registered vars (sorted)."""
        from vitalgraph.db.sparql_sql.emit_distinct import _output_vars
        ctx = _make_ctx({"s": "text", "p": "text"})
        node = _leaf_bgp()
        result = _output_vars(node, ctx)
        assert sorted(result) == ["p", "s"]

    def test_output_vars_no_children(self):
        """Node with no children and no PROJECT → all vars."""
        from vitalgraph.db.sparql_sql.emit_distinct import _output_vars
        ctx = _make_ctx({"x": "text"})
        node = PlanV2(kind=KIND_ORDER, children=[])
        result = _output_vars(node, ctx)
        assert "x" in result

    def test_can_pushdown_child_no_children(self):
        """Child modifier with no children → False."""
        from vitalgraph.db.sparql_sql.emit_distinct import _can_pushdown
        ctx = _make_ctx({"s": "text"}, text_needed={"s"})
        plan = PlanV2(
            kind=KIND_DISTINCT,
            children=[PlanV2(kind=KIND_PROJECT, project_vars=["s"], children=[])],
        )
        assert _can_pushdown(plan, ctx) is False

    # --- Full pushdown integration ---

    def test_pushdown_full_path(self):
        """Full pushdown: DISTINCT over BGP with text_needed vars → UUID dedup + term JOIN."""
        from vitalgraph.db.sparql_sql.emit_distinct import emit_distinct
        # Need a var registered as from_triple=True and text_needed
        ctx = _make_ctx({"s": "full"}, text_needed={"s"})
        plan = PlanV2(
            kind=KIND_DISTINCT,
            children=[_leaf_bgp()],
        )
        sql = emit_distinct(plan, ctx)
        assert "DISTINCT" in sql
        # Pushdown should produce UUID-based DISTINCT + term JOIN
        assert "__uuid" in sql
        assert "term_uuid" in sql

    def test_pushdown_with_non_text_var(self):
        """Pushdown: var NOT in text_needed → null companions passthrough."""
        from vitalgraph.db.sparql_sql.emit_distinct import emit_distinct
        # s is text_needed (from_triple), p is NOT text_needed
        ctx = _make_ctx({"s": "full", "p": "full"}, text_needed={"s"})
        plan = PlanV2(
            kind=KIND_DISTINCT,
            children=[_leaf_bgp()],
        )
        sql = emit_distinct(plan, ctx)
        assert "DISTINCT" in sql
        # Should have both vars' UUIDs in the DISTINCT
        assert "__uuid" in sql

    def test_pushdown_no_vars_to_resolve_fallback(self):
        """Pushdown eligible but no from_triple vars in text_needed → plain DISTINCT."""
        from vitalgraph.db.sparql_sql.emit_distinct import emit_distinct
        # text_needed has "s" but "s" is NOT from_triple (use "text" kind which has from_triple=True)
        # Actually we need a var NOT in text_needed to trigger the fallback
        # Use text_needed={"z"} where z doesn't exist in the registered vars
        ctx = _make_ctx({"s": "text"}, text_needed={"z"})
        plan = PlanV2(
            kind=KIND_DISTINCT,
            children=[_leaf_bgp()],
        )
        sql = emit_distinct(plan, ctx)
        assert "DISTINCT" in sql
