"""Unit tests for emit_group.py — GROUP BY + aggregate emission."""
# pyright: reportOperatorIssue=false, reportArgumentType=false

from __future__ import annotations

from vitalgraph.db.jena_sparql.jena_types import ExprAggregator, GroupVar
from vitalgraph.db.sparql_sql.ir import PlanV2, KIND_GROUP, KIND_FILTER
from vitalgraph.db.sparql_sql.sql_type_generation import ColumnInfo

from .emit_helpers import _make_ctx, _leaf_bgp, _var, _lit, _func


class TestEmitGroup:
    """Tests for emit_group.py — GROUP BY + aggregate emission."""

    def test_simple_group_by_variable(self):
        """GROUP BY ?type with COUNT(*) AS ?c."""
        ctx = _make_ctx({"type": "text", "s": "text"})
        plan = PlanV2(
            kind=KIND_GROUP,
            group_vars=[GroupVar(var="type")],
            aggregates={"c": ExprAggregator(name="COUNT", expr=None, distinct=False)},
            children=[_leaf_bgp()],
        )
        from vitalgraph.db.sparql_sql.emit_group import emit_group
        sql = emit_group(plan, ctx)
        assert "GROUP BY" in sql
        assert "COUNT(*)" in sql

    def test_group_by_with_count_distinct(self):
        """COUNT(DISTINCT ?s) should produce COUNT(DISTINCT ...)."""
        ctx = _make_ctx({"type": "text", "s": "text"})
        plan = PlanV2(
            kind=KIND_GROUP,
            group_vars=[GroupVar(var="type")],
            aggregates={"c": ExprAggregator(name="COUNT", expr=_var("s"), distinct=True)},
            children=[_leaf_bgp()],
        )
        from vitalgraph.db.sparql_sql.emit_group import emit_group
        sql = emit_group(plan, ctx)
        assert "COUNT(DISTINCT" in sql

    def test_group_by_sum_aggregate(self):
        """SUM(?val) should use numeric companion column."""
        ctx = _make_ctx({"type": "text", "val": "numeric"})
        plan = PlanV2(
            kind=KIND_GROUP,
            group_vars=[GroupVar(var="type")],
            aggregates={"total": ExprAggregator(name="SUM", expr=_var("val"), distinct=False)},
            children=[_leaf_bgp()],
        )
        from vitalgraph.db.sparql_sql.emit_group import emit_group
        sql = emit_group(plan, ctx)
        assert "GROUP BY" in sql
        # SUM should use __num column with error guard
        assert "SUM(" in sql
        assert "COUNT(*)" in sql  # error guard

    def test_group_by_avg_aggregate(self):
        """AVG(?val) should produce CASE with COUNT guard and AVG."""
        ctx = _make_ctx({"type": "text", "val": "numeric"})
        plan = PlanV2(
            kind=KIND_GROUP,
            group_vars=[GroupVar(var="type")],
            aggregates={"avg_val": ExprAggregator(name="AVG", expr=_var("val"), distinct=False)},
            children=[_leaf_bgp()],
        )
        from vitalgraph.db.sparql_sql.emit_group import emit_group
        sql = emit_group(plan, ctx)
        assert "AVG(" in sql
        assert "CASE WHEN" in sql  # error guard for AVG
        assert "COUNT(*) = 0 THEN 0" in sql  # AVG empty group = 0

    def test_group_by_min_max(self):
        """MIN/MAX should use text column."""
        for agg_name in ("MIN", "MAX"):
            ctx = _make_ctx({"type": "text", "val": "text"})
            plan = PlanV2(
                kind=KIND_GROUP,
                group_vars=[GroupVar(var="type")],
                aggregates={"result": ExprAggregator(
                    name=agg_name, expr=_var("val"), distinct=False)},
                children=[_leaf_bgp()],
            )
            from vitalgraph.db.sparql_sql.emit_group import emit_group
            sql = emit_group(plan, ctx)
            assert f"{agg_name}(" in sql

    def test_group_concat(self):
        """GROUP_CONCAT should emit string_agg."""
        ctx = _make_ctx({"type": "text", "name": "text"})
        plan = PlanV2(
            kind=KIND_GROUP,
            group_vars=[GroupVar(var="type")],
            aggregates={"names": ExprAggregator(
                name="GROUP_CONCAT", expr=_var("name"),
                distinct=False, separator=", ")},
            children=[_leaf_bgp()],
        )
        from vitalgraph.db.sparql_sql.emit_group import emit_group
        sql = emit_group(plan, ctx)
        assert "string_agg(" in sql
        assert ", " in sql  # separator

    def test_group_concat_distinct(self):
        """GROUP_CONCAT with DISTINCT."""
        ctx = _make_ctx({"type": "text", "name": "text"})
        plan = PlanV2(
            kind=KIND_GROUP,
            group_vars=[GroupVar(var="type")],
            aggregates={"names": ExprAggregator(
                name="GROUP_CONCAT", expr=_var("name"),
                distinct=True, separator="; ")},
            children=[_leaf_bgp()],
        )
        from vitalgraph.db.sparql_sql.emit_group import emit_group
        sql = emit_group(plan, ctx)
        assert "DISTINCT" in sql
        assert "string_agg(" in sql

    def test_sample_aggregate(self):
        """SAMPLE(?x) should emit MAX() as stand-in."""
        ctx = _make_ctx({"type": "text", "x": "text"})
        plan = PlanV2(
            kind=KIND_GROUP,
            group_vars=[GroupVar(var="type")],
            aggregates={"sx": ExprAggregator(
                name="SAMPLE", expr=_var("x"), distinct=False)},
            children=[_leaf_bgp()],
        )
        from vitalgraph.db.sparql_sql.emit_group import emit_group
        sql = emit_group(plan, ctx)
        assert "MAX(" in sql  # SAMPLE → MAX

    def test_expression_group_key(self):
        """GROUP BY (DATATYPE(?o) AS ?d) — expression-based key."""
        ctx = _make_ctx({"o": "text"})
        plan = PlanV2(
            kind=KIND_GROUP,
            group_vars=[GroupVar(var="d", expr=_func("datatype", _var("o")))],
            aggregates={"c": ExprAggregator(name="COUNT", expr=None, distinct=False)},
            children=[_leaf_bgp()],
        )
        from vitalgraph.db.sparql_sql.emit_group import emit_group
        sql = emit_group(plan, ctx)
        assert "GROUP BY" in sql
        assert "COUNT(*)" in sql

    def test_having_clause(self):
        """HAVING with a filter expression should emit HAVING in SQL."""
        ctx = _make_ctx({"type": "text", "s": "text"})
        # First emit the group to register aggregate var "c"
        plan = PlanV2(
            kind=KIND_GROUP,
            group_vars=[GroupVar(var="type")],
            aggregates={"c": ExprAggregator(name="COUNT", expr=None, distinct=False)},
            # Use a simple expression: ?c > 5 — after COUNT is registered
            # the var "c" is known to the TypeRegistry.
            having_exprs=[_func("gt", _var("c"),
                _lit("5", datatype="http://www.w3.org/2001/XMLSchema#integer"),
            )],
            children=[_leaf_bgp()],
        )
        from vitalgraph.db.sparql_sql.emit_group import emit_group
        sql = emit_group(plan, ctx)
        assert "HAVING" in sql

    def test_no_group_keys_count_only(self):
        """SELECT (COUNT(*) AS ?c) WHERE { ... } — no group keys."""
        ctx = _make_ctx({"s": "text"}, text_needed={"s"})
        plan = PlanV2(
            kind=KIND_GROUP,
            group_vars=[],
            aggregates={"c": ExprAggregator(name="COUNT", expr=None, distinct=False)},
            children=[_leaf_bgp()],
        )
        from vitalgraph.db.sparql_sql.emit_group import emit_group
        sql = emit_group(plan, ctx)
        assert "COUNT(*)" in sql

    def test_null_placeholder_group_key(self):
        """Out-of-scope variable as group key → NULL companions."""
        ctx = _make_ctx({})
        plan = PlanV2(
            kind=KIND_GROUP,
            group_vars=[GroupVar(var="unknown")],
            aggregates={"c": ExprAggregator(name="COUNT", expr=None, distinct=False)},
            children=[_leaf_bgp()],
        )
        from vitalgraph.db.sparql_sql.emit_group import emit_group
        sql = emit_group(plan, ctx)
        assert "NULL" in sql
        assert "GROUP BY" in sql

    def test_empty_select_produces_dummy(self):
        """When no group vars and no aggregates, emit 1 AS _dummy."""
        ctx = _make_ctx({})
        plan = PlanV2(
            kind=KIND_GROUP,
            group_vars=[],
            aggregates={},
            children=[_leaf_bgp()],
        )
        from vitalgraph.db.sparql_sql.emit_group import emit_group
        sql = emit_group(plan, ctx)
        assert "_dummy" in sql

    # --- Pushdown candidates ---

    def test_pushdown_count_only(self):
        """All COUNT aggregates + simple keys + text_needed → pushdown."""
        from vitalgraph.db.sparql_sql.emit_group import _pushdown_candidates
        ctx = _make_ctx({"type": "text", "s": "text"}, text_needed={"type", "s"})
        plan = PlanV2(
            kind=KIND_GROUP,
            group_vars=[GroupVar(var="type")],
            aggregates={"c": ExprAggregator(name="COUNT", expr=None, distinct=False)},
            children=[_leaf_bgp()],
        )
        cands = _pushdown_candidates(plan, ctx)
        assert "type" in cands

    def test_pushdown_blocked_by_non_count(self):
        """SUM aggregate → no pushdown."""
        from vitalgraph.db.sparql_sql.emit_group import _pushdown_candidates
        ctx = _make_ctx({"type": "text", "val": "numeric"}, text_needed={"type"})
        plan = PlanV2(
            kind=KIND_GROUP,
            group_vars=[GroupVar(var="type")],
            aggregates={"total": ExprAggregator(name="SUM", expr=_var("val"), distinct=False)},
            children=[_leaf_bgp()],
        )
        cands = _pushdown_candidates(plan, ctx)
        assert cands == set()

    def test_pushdown_blocked_by_having(self):
        """HAVING clause → no pushdown."""
        from vitalgraph.db.sparql_sql.emit_group import _pushdown_candidates
        ctx = _make_ctx({"type": "text"}, text_needed={"type"})
        plan = PlanV2(
            kind=KIND_GROUP,
            group_vars=[GroupVar(var="type")],
            aggregates={"c": ExprAggregator(name="COUNT", expr=None, distinct=False)},
            having_exprs=[_func(">", _var("c"), _lit("5"))],
            children=[_leaf_bgp()],
        )
        cands = _pushdown_candidates(plan, ctx)
        assert cands == set()

    def test_pushdown_blocked_by_expression_key(self):
        """Expression-based group key → no pushdown."""
        from vitalgraph.db.sparql_sql.emit_group import _pushdown_candidates
        ctx = _make_ctx({"o": "text"}, text_needed={"o"})
        plan = PlanV2(
            kind=KIND_GROUP,
            group_vars=[GroupVar(var="d", expr=_func("datatype", _var("o")))],
            aggregates={"c": ExprAggregator(name="COUNT", expr=None, distinct=False)},
            children=[_leaf_bgp()],
        )
        cands = _pushdown_candidates(plan, ctx)
        assert cands == set()

    def test_pushdown_blocked_by_no_text_needed(self):
        """text_needed_vars=None → no pushdown."""
        from vitalgraph.db.sparql_sql.emit_group import _pushdown_candidates
        ctx = _make_ctx({"type": "text"}, text_needed=None)
        plan = PlanV2(
            kind=KIND_GROUP,
            group_vars=[GroupVar(var="type")],
            aggregates={"c": ExprAggregator(name="COUNT", expr=None, distinct=False)},
            children=[_leaf_bgp()],
        )
        cands = _pushdown_candidates(plan, ctx)
        assert cands == set()

    def test_pushdown_blocked_by_unsafe_child(self):
        """FILTER child → no pushdown (may reference text)."""
        from vitalgraph.db.sparql_sql.emit_group import _pushdown_candidates
        ctx = _make_ctx({"type": "text"}, text_needed={"type"})
        plan = PlanV2(
            kind=KIND_GROUP,
            group_vars=[GroupVar(var="type")],
            aggregates={"c": ExprAggregator(name="COUNT", expr=None, distinct=False)},
            children=[PlanV2(kind=KIND_FILTER, children=[_leaf_bgp()])],
        )
        cands = _pushdown_candidates(plan, ctx)
        assert cands == set()

    # --- _all_count_no_keys ---

    def test_all_count_no_keys_true(self):
        """No group keys + all COUNT + simple child → True."""
        from vitalgraph.db.sparql_sql.emit_group import _all_count_no_keys
        ctx = _make_ctx({"s": "text"}, text_needed={"s"})
        plan = PlanV2(
            kind=KIND_GROUP,
            group_vars=[],
            aggregates={"c": ExprAggregator(name="COUNT", expr=None, distinct=False)},
            children=[_leaf_bgp()],
        )
        assert _all_count_no_keys(plan, ctx) is True

    def test_all_count_no_keys_false_with_keys(self):
        """Group keys present → False."""
        from vitalgraph.db.sparql_sql.emit_group import _all_count_no_keys
        ctx = _make_ctx({"type": "text"}, text_needed={"type"})
        plan = PlanV2(
            kind=KIND_GROUP,
            group_vars=[GroupVar(var="type")],
            aggregates={"c": ExprAggregator(name="COUNT", expr=None, distinct=False)},
            children=[_leaf_bgp()],
        )
        assert _all_count_no_keys(plan, ctx) is False

    def test_all_count_no_keys_false_with_sum(self):
        """SUM aggregate → False."""
        from vitalgraph.db.sparql_sql.emit_group import _all_count_no_keys
        ctx = _make_ctx({"val": "numeric"}, text_needed={"val"})
        plan = PlanV2(
            kind=KIND_GROUP,
            group_vars=[],
            aggregates={"total": ExprAggregator(name="SUM", expr=_var("val"), distinct=False)},
            children=[_leaf_bgp()],
        )
        assert _all_count_no_keys(plan, ctx) is False

    # --- _qualify_agg_inner ---

    def test_qualify_agg_inner_sum_uses_num(self):
        """SUM inner var should reference __num column."""
        from vitalgraph.db.sparql_sql.emit_group import _qualify_agg_inner
        ctx = _make_ctx({"val": "numeric"})
        inner = _var("val")
        agg = ExprAggregator(name="SUM", expr=inner, distinct=False)
        result = _qualify_agg_inner(inner, agg, "g0", ctx)
        assert result is not None
        assert "__num" in result

    def test_qualify_agg_inner_count_uses_uuid(self):
        """COUNT inner var (from_triple) should reference __uuid column."""
        from vitalgraph.db.sparql_sql.emit_group import _qualify_agg_inner
        ctx = _make_ctx({"s": "text"})
        inner = _var("s")
        agg = ExprAggregator(name="COUNT", expr=inner, distinct=False)
        result = _qualify_agg_inner(inner, agg, "g0", ctx)
        assert result is not None
        assert "__uuid" in result

    def test_qualify_agg_inner_min_uses_text(self):
        """MIN inner var should reference text column."""
        from vitalgraph.db.sparql_sql.emit_group import _qualify_agg_inner
        ctx = _make_ctx({"val": "text"})
        inner = _var("val")
        agg = ExprAggregator(name="MIN", expr=inner, distinct=False)
        result = _qualify_agg_inner(inner, agg, "g0", ctx)
        assert result is not None
        assert "g0.v0" == result  # text column, no __num

    def test_qualify_agg_inner_non_exprvar_returns_none(self):
        """Non-ExprVar inner returns None (falls back to expr_to_sql)."""
        from vitalgraph.db.sparql_sql.emit_group import _qualify_agg_inner
        ctx = _make_ctx({"val": "text"})
        inner = _func("strlen", _var("val"))
        agg = ExprAggregator(name="SUM", expr=inner, distinct=False)
        result = _qualify_agg_inner(inner, agg, "g0", ctx)
        assert result is None

    def test_qualify_agg_inner_null_placeholder(self):
        """Null-placeholder variable returns 'NULL'."""
        from vitalgraph.db.sparql_sql.emit_group import _qualify_agg_inner
        ctx = _make_ctx({})
        sn = ctx.types.allocate("ghost")
        info = ColumnInfo(sparql_name="ghost", sql_name=sn, text_col=sn)
        info._is_null_placeholder = True  # type: ignore[attr-defined]  # dynamic attr
        ctx.types.register(info)
        inner = _var("ghost")
        agg = ExprAggregator(name="SUM", expr=inner, distinct=False)
        result = _qualify_agg_inner(inner, agg, "g0", ctx)
        assert result == "NULL"

    # --- _esc_agg ---

    def test_esc_agg_escapes_quotes(self):
        from vitalgraph.db.sparql_sql.emit_group import _esc_agg
        assert _esc_agg("it's") == "it''s"
        assert _esc_agg(", ") == ", "
