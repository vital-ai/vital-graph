"""Unit tests for emit_extend.py — BIND expression emission."""
# pyright: reportOperatorIssue=false, reportArgumentType=false

from __future__ import annotations

from vitalgraph.db.jena_sparql.jena_types import ExprValue, LiteralNode
from vitalgraph.db.sparql_sql.ir import PlanV2, KIND_EXTEND

from .emit_helpers import _make_ctx, _leaf_bgp, _var, _lit, _func


class TestEmitExtend:
    """Tests for emit_extend.py — BIND expression emission."""

    def test_simple_bind_literal(self):
        """BIND("hello" AS ?x) should produce a SELECT with computed column."""
        ctx = _make_ctx({"s": "text"})
        plan = PlanV2(
            kind=KIND_EXTEND,
            extend_var="x",
            extend_expr=_lit("hello"),
            children=[_leaf_bgp()],
        )
        from vitalgraph.db.sparql_sql.emit_extend import emit_extend
        sql = emit_extend(plan, ctx)
        assert "hello" in sql
        assert "SELECT" in sql

    def test_bind_variable_passthrough(self):
        """BIND(?s AS ?x) with companion columns → passthrough all companions."""
        ctx = _make_ctx({"s": "full"})
        # Mark the source var as having companions
        info = ctx.types.get("s")
        info._sql_has_companions = True  # type: ignore[attr-defined]  # dynamic attr

        plan = PlanV2(
            kind=KIND_EXTEND,
            extend_var="x",
            extend_expr=_var("s"),
            children=[_leaf_bgp()],
        )
        from vitalgraph.db.sparql_sql.emit_extend import emit_extend
        sql = emit_extend(plan, ctx)
        # Should passthrough companion columns
        assert "__type" in sql or "__uuid" in sql

    def test_bind_no_var_returns_child(self):
        """Missing extend_var → return child SQL unchanged."""
        ctx = _make_ctx({"s": "text"})
        plan = PlanV2(
            kind=KIND_EXTEND,
            extend_var=None,
            extend_expr=None,
            children=[_leaf_bgp()],
        )
        from vitalgraph.db.sparql_sql.emit_extend import emit_extend
        sql = emit_extend(plan, ctx)
        # Should just be the child SQL (minimal)
        assert sql is not None

    def test_bind_function_expression(self):
        """BIND(STRLEN(?s) AS ?len) should produce SQL expression."""
        ctx = _make_ctx({"s": "text"})
        plan = PlanV2(
            kind=KIND_EXTEND,
            extend_var="len",
            extend_expr=_func("strlen", _var("s")),
            children=[_leaf_bgp()],
        )
        from vitalgraph.db.sparql_sql.emit_extend import emit_extend
        sql = emit_extend(plan, ctx)
        assert "SELECT" in sql
        assert "LENGTH(" in sql or "strlen" in sql.lower()

    def test_bind_null_expression(self):
        """Expression producing empty SQL → NULL fallback."""
        ctx = _make_ctx({"s": "text"})
        plan = PlanV2(
            kind=KIND_EXTEND,
            extend_var="x",
            extend_expr=_func("unknown_function_xyz"),
            children=[_leaf_bgp()],
        )
        from vitalgraph.db.sparql_sql.emit_extend import emit_extend
        sql = emit_extend(plan, ctx)
        assert "NULL" in sql

    # --- Vector-driving top-K optimization ---

    def test_vector_driving_no_hint_returns_none(self):
        """No vg_top_k hint → _try_vector_driving_extend returns None."""
        from vitalgraph.db.sparql_sql.emit_extend import _try_vector_driving_extend
        from vitalgraph.db.sparql_sql.vg_functions import VG_VECTOR_SIMILARITY

        ctx = _make_ctx({"entity": "text"})
        expr = _func("vectorSimilarity", _var("entity"), _lit("cat"),
                      _lit("idx"), function_iri=VG_VECTOR_SIMILARITY)
        plan = PlanV2(
            kind=KIND_EXTEND,
            extend_var="score",
            extend_expr=expr,
            hints={},  # no vg_top_k
            children=[_leaf_bgp()],
        )
        result = _try_vector_driving_extend(plan, ctx, "SELECT 1")
        assert result is None

    def test_vector_driving_non_vector_func_returns_none(self):
        """vg_top_k hint but non-vector function → returns None."""
        from vitalgraph.db.sparql_sql.emit_extend import _try_vector_driving_extend

        ctx = _make_ctx({"s": "text"})
        plan = PlanV2(
            kind=KIND_EXTEND,
            extend_var="x",
            extend_expr=_func("strlen", _var("s")),
            hints={"vg_top_k": {"limit": 10}},
            children=[_leaf_bgp()],
        )
        result = _try_vector_driving_extend(plan, ctx, "SELECT 1")
        assert result is None

    def test_vector_driving_similarity_produces_join(self):
        """vg:vectorSimilarity with top-K hint → JOIN-based SQL."""
        from vitalgraph.db.sparql_sql.emit_extend import _try_vector_driving_extend
        from vitalgraph.db.sparql_sql.vg_functions import VG_VECTOR_SIMILARITY

        ctx = _make_ctx({"entity": "text"})
        expr = _func("vectorSimilarity", _var("entity"), _lit("find cats"),
                      _lit("my_index"), function_iri=VG_VECTOR_SIMILARITY)
        plan = PlanV2(
            kind=KIND_EXTEND,
            extend_var="score",
            extend_expr=expr,
            hints={"vg_top_k": {"limit": 10}},
            children=[_leaf_bgp()],
        )
        child_sql = "SELECT v0, v0__uuid FROM test_space_rdf_quad"
        result = _try_vector_driving_extend(plan, ctx, child_sql)
        assert result is not None
        assert "JOIN" in result
        assert "LIMIT 10" in result
        assert "__vg_score" in result
        assert "subject_uuid" in result

    def test_vector_driving_creates_vector_request(self):
        """vg:vectorSimilarity creates a VectorRequest with placeholder."""
        from vitalgraph.db.sparql_sql.emit_extend import _try_vector_driving_extend
        from vitalgraph.db.sparql_sql.vg_functions import VG_VECTOR_SIMILARITY

        ctx = _make_ctx({"entity": "text"})
        expr = _func("vectorSimilarity", _var("entity"), _lit("find cats"),
                      _lit("my_index"), function_iri=VG_VECTOR_SIMILARITY)
        plan = PlanV2(
            kind=KIND_EXTEND,
            extend_var="score",
            extend_expr=expr,
            hints={"vg_top_k": {"limit": 5}},
            children=[_leaf_bgp()],
        )
        child_sql = "SELECT v0, v0__uuid FROM test_space_rdf_quad"
        result = _try_vector_driving_extend(plan, ctx, child_sql)
        assert result is not None
        # Should have created a VectorRequest
        assert len(ctx._vector_requests) == 1
        vr = ctx._vector_requests[0]
        assert vr.search_text == "find cats"
        assert vr.index_name == "my_index"
        assert "__VG_EMBED_" in vr.placeholder

    def test_vector_driving_with_threshold(self):
        """vg_threshold hint adds a score filter to the vector subquery."""
        from vitalgraph.db.sparql_sql.emit_extend import _try_vector_driving_extend
        from vitalgraph.db.sparql_sql.vg_functions import VG_VECTOR_SIMILARITY

        ctx = _make_ctx({"entity": "text"})
        expr = _func("vectorSimilarity", _var("entity"), _lit("dogs"),
                      _lit("idx"), function_iri=VG_VECTOR_SIMILARITY)
        plan = PlanV2(
            kind=KIND_EXTEND,
            extend_var="score",
            extend_expr=expr,
            hints={"vg_top_k": {"limit": 20}, "vg_threshold": 0.7},
            children=[_leaf_bgp()],
        )
        child_sql = "SELECT v0, v0__uuid FROM test_space_rdf_quad"
        result = _try_vector_driving_extend(plan, ctx, child_sql)
        assert result is not None
        assert "0.7" in result  # threshold in WHERE clause

    def test_vector_driving_nearby_uses_literal_vector(self):
        """vg:vectorNearby with a raw vector literal → no VectorRequest."""
        from vitalgraph.db.sparql_sql.emit_extend import _try_vector_driving_extend
        from vitalgraph.db.sparql_sql.vg_functions import VG_VECTOR_NEARBY

        ctx = _make_ctx({"entity": "text"})
        vec = "[0.1,0.2,0.3]"
        expr = _func("vectorNearby", _var("entity"), _lit(vec),
                      _lit("idx"), function_iri=VG_VECTOR_NEARBY)
        plan = PlanV2(
            kind=KIND_EXTEND,
            extend_var="score",
            extend_expr=expr,
            hints={"vg_top_k": {"limit": 5}},
            children=[_leaf_bgp()],
        )
        child_sql = "SELECT v0, v0__uuid FROM test_space_rdf_quad"
        result = _try_vector_driving_extend(plan, ctx, child_sql)
        assert result is not None
        # No VectorRequest — raw vector literal used directly
        assert len(ctx._vector_requests) == 0
        assert "vector" in result.lower()

    def test_vector_driving_emit_extend_integration(self):
        """Full emit_extend with vector driving produces complete SQL."""
        from vitalgraph.db.sparql_sql.emit_extend import emit_extend
        from vitalgraph.db.sparql_sql.vg_functions import VG_VECTOR_SIMILARITY

        ctx = _make_ctx({"entity": "text"})
        expr = _func("vectorSimilarity", _var("entity"), _lit("search"),
                      _lit("idx"), function_iri=VG_VECTOR_SIMILARITY)
        plan = PlanV2(
            kind=KIND_EXTEND,
            extend_var="score",
            extend_expr=expr,
            hints={"vg_top_k": {"limit": 10}},
            children=[_leaf_bgp()],
        )
        sql = emit_extend(plan, ctx)
        assert "JOIN" in sql
        assert "LIMIT 10" in sql
        assert "SELECT" in sql

    # --- STRAFTER/STRBEFORE companion patching ---

    def test_strafter_patches_lang_companion(self):
        """STRAFTER should produce conditional lang companion."""
        from vitalgraph.db.sparql_sql.emit_extend import _patch_strafter_strbefore_companions
        from vitalgraph.db.sparql_sql.sql_type_generation import TypedExpr, infer_expr_type

        ctx = _make_ctx({"s": "text"})
        expr = _func("strafter", _var("s"), _lit("/"))
        typed = infer_expr_type(expr, ctx.types)
        plan = PlanV2(
            kind=KIND_EXTEND,
            extend_var="result",
            extend_expr=expr,
            children=[_leaf_bgp()],
        )
        _patch_strafter_strbefore_companions(plan, ctx, typed)
        assert typed.lang_is_sql is True
        assert "CASE WHEN" in (typed.lang or "")

    def test_strbefore_patches_datatype_companion(self):
        """STRBEFORE should produce conditional datatype companion."""
        from vitalgraph.db.sparql_sql.emit_extend import _patch_strafter_strbefore_companions
        from vitalgraph.db.sparql_sql.sql_type_generation import infer_expr_type

        ctx = _make_ctx({"s": "text"})
        expr = _func("strbefore", _var("s"), _lit(":"))
        typed = infer_expr_type(expr, ctx.types)
        plan = PlanV2(
            kind=KIND_EXTEND,
            extend_var="result",
            extend_expr=expr,
            children=[_leaf_bgp()],
        )
        _patch_strafter_strbefore_companions(plan, ctx, typed)
        assert typed.datatype_is_sql is True
        assert "CASE WHEN" in (typed.datatype or "")

    def test_strafter_non_exprvar_no_patch(self):
        """STRAFTER with non-variable first arg → no patch."""
        from vitalgraph.db.sparql_sql.emit_extend import _patch_strafter_strbefore_companions
        from vitalgraph.db.sparql_sql.sql_type_generation import infer_expr_type

        ctx = _make_ctx({})
        expr = _func("strafter", _lit("hello/world"), _lit("/"))
        typed = infer_expr_type(expr, ctx.types)
        plan = PlanV2(
            kind=KIND_EXTEND,
            extend_var="result",
            extend_expr=expr,
            children=[_leaf_bgp()],
        )
        _patch_strafter_strbefore_companions(plan, ctx, typed)
        assert typed.lang_is_sql is False

    # --- CONCAT companion patching ---

    def test_concat_patches_lang_when_same(self):
        """CONCAT with same-lang args should produce conditional lang."""
        from vitalgraph.db.sparql_sql.emit_extend import _patch_concat_companions
        from vitalgraph.db.sparql_sql.sql_type_generation import infer_expr_type

        ctx = _make_ctx({"a": "text", "b": "text"})
        expr = _func("concat", _var("a"), _var("b"))
        typed = infer_expr_type(expr, ctx.types)
        plan = PlanV2(
            kind=KIND_EXTEND,
            extend_var="result",
            extend_expr=expr,
            children=[_leaf_bgp()],
        )
        _patch_concat_companions(plan, ctx, typed)
        assert typed.lang_is_sql is True
        assert "CASE WHEN" in (typed.lang or "")

    def test_concat_clears_lang_for_plain_literal(self):
        """CONCAT with plain literal constant → lang = None."""
        from vitalgraph.db.sparql_sql.emit_extend import _patch_concat_companions
        from vitalgraph.db.sparql_sql.sql_type_generation import infer_expr_type

        ctx = _make_ctx({"a": "text"})
        # Plain literal (no lang) as second arg
        expr = _func("concat", _var("a"),
                      ExprValue(node=LiteralNode(value="hello")))
        typed = infer_expr_type(expr, ctx.types)
        plan = PlanV2(
            kind=KIND_EXTEND,
            extend_var="result",
            extend_expr=expr,
            children=[_leaf_bgp()],
        )
        _patch_concat_companions(plan, ctx, typed)
        assert typed.lang is None
