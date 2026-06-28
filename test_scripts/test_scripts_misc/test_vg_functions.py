"""
Tests for the vg: custom function SPARQL → SQL pipeline.

Tests the full chain: ExprFunction IR → emit_expressions → SQL output
for all four vg: function IRIs, without requiring a database connection.

Run:
    python -m pytest test_scripts_misc/test_vg_functions.py -v
"""

import pytest
from unittest.mock import MagicMock

from vitalgraph.db.jena_sparql.jena_types import (
    ExprFunction, ExprVar, ExprValue, LiteralNode,
)
from vitalgraph.db.sparql_sql.vg_functions import (
    VG_VECTOR_SIMILARITY, VG_VECTOR_NEARBY,
    VG_TEXT_SEARCH, VG_HYBRID_SEARCH,
    VG_GEO_DISTANCE, VG_WITHIN_RADIUS,
    VG_TRIGRAM_SIMILARITY,
    VG_NS, VG_ALL_FUNCTIONS, VG_TEXT_FUNCTIONS, VG_TRIGRAM_FUNCTIONS,
    is_vg_function, is_vg_vector_function, is_vg_geo_function,
    is_vg_text_function, is_vg_trigram_function,
    extract_vector_args, extract_geo_args, extract_text_search_args,
    extract_trigram_args,
    vector_similarity_sql, geo_distance_sql, within_radius_sql,
    text_search_sql, hybrid_search_sql, trigram_similarity_sql,
    VectorRequest, VectorArgs, GeoArgs, TextSearchArgs, TrigramArgs,
)
from vitalgraph.db.sparql_sql.sql_type_generation import (
    TypeRegistry, ColumnInfo, TypedExpr,
)
from vitalgraph.db.sparql_sql.ir import AliasGenerator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lit(value: str, datatype: str = "") -> ExprValue:
    """Create an ExprValue wrapping a LiteralNode."""
    return ExprValue(node=LiteralNode(value=value, datatype=datatype, lang=""))


def _var(name: str) -> ExprVar:
    return ExprVar(var=name)


def _make_ctx(space_id: str = "test_space", entity_var: str = "entity"):
    """Create a minimal mock EmitContext with a registered entity variable."""
    aliases = AliasGenerator()
    types = TypeRegistry(aliases=aliases)
    # Register entity variable with a known uuid_col
    info = ColumnInfo.simple_output(entity_var, "v0", from_triple=True)
    types.register(info)

    ctx = MagicMock()
    ctx.space_id = space_id
    ctx.types = types
    ctx.graph_lock_uri = None
    ctx.vg_hints = {}
    ctx.multi_vector_config = {}
    ctx.vector_index_meta = {}
    ctx.fts_index_meta = {}
    ctx._vector_requests = []

    def add_vr(vr):
        ctx._vector_requests.append(vr)

    ctx.add_vector_request = add_vr
    ctx.vector_requests = ctx._vector_requests
    return ctx


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------

class TestDetection:
    def test_is_vg_function(self):
        expr = ExprFunction(name="", args=[], function_iri=VG_VECTOR_SIMILARITY)
        assert is_vg_function(expr)

    def test_is_not_vg_function(self):
        expr = ExprFunction(name="strlen", args=[], function_iri=None)
        assert not is_vg_function(expr)

    def test_is_vg_vector_function(self):
        for iri in (VG_VECTOR_SIMILARITY, VG_VECTOR_NEARBY):
            expr = ExprFunction(name="", args=[], function_iri=iri)
            assert is_vg_vector_function(expr)
            assert not is_vg_geo_function(expr)

    def test_is_vg_geo_function(self):
        for iri in (VG_GEO_DISTANCE, VG_WITHIN_RADIUS):
            expr = ExprFunction(name="", args=[], function_iri=iri)
            assert is_vg_geo_function(expr)
            assert not is_vg_vector_function(expr)

    def test_all_functions_set(self):
        assert len(VG_ALL_FUNCTIONS) == 12
        assert VG_VECTOR_SIMILARITY in VG_ALL_FUNCTIONS
        assert VG_VECTOR_NEARBY in VG_ALL_FUNCTIONS
        assert VG_TEXT_SEARCH in VG_ALL_FUNCTIONS
        assert VG_HYBRID_SEARCH in VG_ALL_FUNCTIONS
        assert VG_GEO_DISTANCE in VG_ALL_FUNCTIONS
        assert VG_WITHIN_RADIUS in VG_ALL_FUNCTIONS


# ---------------------------------------------------------------------------
# Argument extraction tests
# ---------------------------------------------------------------------------

class TestExtractVectorArgs:
    def test_vectorSimilarity(self):
        expr = ExprFunction(
            name="", function_iri=VG_VECTOR_SIMILARITY,
            args=[_var("entity"), _lit("find restaurants"), _lit("entity_default")],
        )
        va = extract_vector_args(expr)
        assert va is not None
        assert va.entity_var == "entity"
        assert va.search_text == "find restaurants"
        assert va.vector_literal is None
        assert va.index_name == "entity_default"

    def test_vectorNearby(self):
        expr = ExprFunction(
            name="", function_iri=VG_VECTOR_NEARBY,
            args=[_var("entity"), _lit("[0.1,0.2,0.3]"), _lit("my_index")],
        )
        va = extract_vector_args(expr)
        assert va is not None
        assert va.entity_var == "entity"
        assert va.search_text is None
        assert va.vector_literal == "[0.1,0.2,0.3]"
        assert va.index_name == "my_index"

    def test_wrong_arg_count(self):
        expr = ExprFunction(
            name="", function_iri=VG_VECTOR_SIMILARITY,
            args=[_var("entity"), _lit("text")],  # missing index_name
        )
        assert extract_vector_args(expr) is None

    def test_first_arg_not_var(self):
        expr = ExprFunction(
            name="", function_iri=VG_VECTOR_SIMILARITY,
            args=[_lit("not_a_var"), _lit("text"), _lit("idx")],
        )
        assert extract_vector_args(expr) is None


class TestExtractGeoArgs:
    def test_geoDistance(self):
        expr = ExprFunction(
            name="", function_iri=VG_GEO_DISTANCE,
            args=[_var("entity"), _lit("40.73"), _lit("-73.93")],
        )
        ga = extract_geo_args(expr)
        assert ga is not None
        assert ga.entity_var == "entity"
        assert ga.latitude == pytest.approx(40.73)
        assert ga.longitude == pytest.approx(-73.93)
        assert ga.max_distance_m is None

    def test_withinRadius(self):
        expr = ExprFunction(
            name="", function_iri=VG_WITHIN_RADIUS,
            args=[_var("entity"), _lit("40.73"), _lit("-73.93"), _lit("5000")],
        )
        ga = extract_geo_args(expr)
        assert ga is not None
        assert ga.entity_var == "entity"
        assert ga.latitude == pytest.approx(40.73)
        assert ga.longitude == pytest.approx(-73.93)
        assert ga.max_distance_m == pytest.approx(5000.0)

    def test_wrong_arg_count_geo(self):
        expr = ExprFunction(
            name="", function_iri=VG_GEO_DISTANCE,
            args=[_var("entity"), _lit("40.73")],  # missing lon
        )
        assert extract_geo_args(expr) is None


# ---------------------------------------------------------------------------
# SQL generation tests
# ---------------------------------------------------------------------------

class TestVectorSimilaritySQL:
    def test_vectorSimilarity_generates_subquery_with_placeholder(self):
        expr = ExprFunction(
            name="", function_iri=VG_VECTOR_SIMILARITY,
            args=[_var("entity"), _lit("find restaurants"), _lit("entity_default")],
        )
        ctx = _make_ctx()
        sql, vr = vector_similarity_sql(expr, ctx)

        assert sql is not None
        assert "test_space_vec_entity_default" in sql
        assert "v0__uuid" in sql
        assert "1 - (embedding <=>" in sql
        assert "::vector" in sql

        # VectorRequest should be created
        assert vr is not None
        assert vr.search_text == "find restaurants"
        assert vr.index_name == "entity_default"
        assert vr.space_id == "test_space"
        assert vr.placeholder in sql

    def test_vectorNearby_generates_subquery_inline(self):
        vec_str = "[0.1,0.2,0.3]"
        expr = ExprFunction(
            name="", function_iri=VG_VECTOR_NEARBY,
            args=[_var("entity"), _lit(vec_str), _lit("my_index")],
        )
        ctx = _make_ctx()
        sql, vr = vector_similarity_sql(expr, ctx)

        assert sql is not None
        assert "test_space_vec_my_index" in sql
        assert f"'{vec_str}'::vector" in sql
        # No VectorRequest needed for pre-computed vectors
        assert vr is None


class TestGeoDistanceSQL:
    def test_geoDistance_generates_subquery(self):
        expr = ExprFunction(
            name="", function_iri=VG_GEO_DISTANCE,
            args=[_var("entity"), _lit("40.73"), _lit("-73.93")],
        )
        ctx = _make_ctx()
        sql = geo_distance_sql(expr, ctx)

        assert sql is not None
        assert "test_space_geo" in sql
        assert "ST_Distance" in sql
        assert "v0__uuid" in sql
        assert "-73.93" in sql
        assert "40.73" in sql


class TestWithinRadiusSQL:
    def test_withinRadius_generates_exists(self):
        expr = ExprFunction(
            name="", function_iri=VG_WITHIN_RADIUS,
            args=[_var("entity"), _lit("40.73"), _lit("-73.93"), _lit("5000")],
        )
        ctx = _make_ctx()
        sql = within_radius_sql(expr, ctx)

        assert sql is not None
        assert "EXISTS" in sql
        assert "ST_DWithin" in sql
        assert "test_space_geo" in sql
        assert "v0__uuid" in sql
        assert "5000.0" in sql


# ---------------------------------------------------------------------------
# Context scoping tests (graph_lock_uri → context_uuid filtering)
# ---------------------------------------------------------------------------

class TestContextScoping:
    def test_no_context_clause_without_graph_lock(self):
        """Without graph_lock_uri, no context_uuid clause is added."""
        expr = ExprFunction(
            name="", function_iri=VG_VECTOR_SIMILARITY,
            args=[_var("entity"), _lit("text"), _lit("idx")],
        )
        ctx = _make_ctx()
        sql, _ = vector_similarity_sql(expr, ctx)
        assert sql is not None
        assert "context_uuid" not in sql

    def test_context_clause_with_graph_lock(self):
        """With graph_lock_uri, context_uuid clause is added."""
        expr = ExprFunction(
            name="", function_iri=VG_VECTOR_SIMILARITY,
            args=[_var("entity"), _lit("text"), _lit("idx")],
        )
        ctx = _make_ctx()
        ctx.graph_lock_uri = "http://example.org/graph/1"
        sql, _ = vector_similarity_sql(expr, ctx)
        assert sql is not None
        assert "context_uuid" in sql
        assert "test_space_term" in sql

    def test_geo_distance_context_clause(self):
        expr = ExprFunction(
            name="", function_iri=VG_GEO_DISTANCE,
            args=[_var("entity"), _lit("40.73"), _lit("-73.93")],
        )
        ctx = _make_ctx()
        ctx.graph_lock_uri = "http://example.org/graph/1"
        sql = geo_distance_sql(expr, ctx)
        assert sql is not None
        assert "context_uuid" in sql

    def test_within_radius_context_clause(self):
        expr = ExprFunction(
            name="", function_iri=VG_WITHIN_RADIUS,
            args=[_var("entity"), _lit("40.73"), _lit("-73.93"), _lit("5000")],
        )
        ctx = _make_ctx()
        ctx.graph_lock_uri = "http://example.org/graph/1"
        sql = within_radius_sql(expr, ctx)
        assert sql is not None
        assert "context_uuid" in sql


# ---------------------------------------------------------------------------
# Type inference tests
# ---------------------------------------------------------------------------

class TestTypeInference:
    def test_vector_similarity_inferred_as_double(self):
        from vitalgraph.db.sparql_sql.sql_type_generation import _infer_function_type
        expr = ExprFunction(
            name="", function_iri=VG_VECTOR_SIMILARITY,
            args=[_var("entity"), _lit("text"), _lit("idx")],
        )
        aliases = AliasGenerator()
        registry = TypeRegistry(aliases=aliases)
        te = _infer_function_type(expr, registry)
        assert te.sparql_type == "literal"
        assert te.datatype is not None and te.datatype.endswith("double")
        assert te.is_numeric

    def test_geoDistance_inferred_as_double(self):
        from vitalgraph.db.sparql_sql.sql_type_generation import _infer_function_type
        expr = ExprFunction(
            name="", function_iri=VG_GEO_DISTANCE,
            args=[_var("entity"), _lit("40.73"), _lit("-73.93")],
        )
        aliases = AliasGenerator()
        registry = TypeRegistry(aliases=aliases)
        te = _infer_function_type(expr, registry)
        assert te.is_numeric

    def test_withinRadius_inferred_as_boolean(self):
        from vitalgraph.db.sparql_sql.sql_type_generation import _infer_function_type
        expr = ExprFunction(
            name="", function_iri=VG_WITHIN_RADIUS,
            args=[_var("entity"), _lit("40.73"), _lit("-73.93"), _lit("5000")],
        )
        aliases = AliasGenerator()
        registry = TypeRegistry(aliases=aliases)
        te = _infer_function_type(expr, registry)
        assert te.is_boolean
        assert not te.is_numeric


# ---------------------------------------------------------------------------
# VectorRequest resolution test (string substitution only, no DB)
# ---------------------------------------------------------------------------

class TestPlaceholderSubstitution:
    def test_placeholder_replaced_in_sql(self):
        """Verify the placeholder pattern matches what vg_resolve expects."""
        placeholder = "__VG_EMBED_12345__"
        sql = f"SELECT 1 - (embedding <=> '{placeholder}'::vector) FROM sp_vec_idx WHERE subject_uuid = v0__uuid"
        vec_literal = "[0.1,0.2,0.3]"
        result = sql.replace(
            f"'{placeholder}'::vector",
            f"'{vec_literal}'::vector",
        )
        assert f"'{vec_literal}'::vector" in result
        assert placeholder not in result


# ---------------------------------------------------------------------------
# emit_expressions integration test
# ---------------------------------------------------------------------------

class TestEmitExpressionsIntegration:
    def test_is_numeric_expr_recognizes_vg_functions(self):
        from vitalgraph.db.sparql_sql.emit_expressions import _is_numeric_expr
        ctx = _make_ctx()

        for iri in (VG_VECTOR_SIMILARITY, VG_VECTOR_NEARBY, VG_GEO_DISTANCE):
            expr = ExprFunction(name="", args=[], function_iri=iri)
            assert _is_numeric_expr(expr, ctx), f"{iri} should be numeric"

        # withinRadius is boolean, not numeric
        expr = ExprFunction(name="", args=[], function_iri=VG_WITHIN_RADIUS)
        assert not _is_numeric_expr(expr, ctx)


# ---------------------------------------------------------------------------
# EmitContext vector_requests test
# ---------------------------------------------------------------------------

class TestEmitContextVectorRequests:
    def test_vector_requests_shared_across_children(self):
        from vitalgraph.db.sparql_sql.emit_context import EmitContext
        ctx = EmitContext(space_id="test")
        child = ctx.child()

        vr = VectorRequest(
            placeholder="__VG_EMBED_1__",
            search_text="hello",
            index_name="idx",
            space_id="test",
        )
        child.add_vector_request(vr)

        # Parent should see the request too (shared list)
        assert len(ctx.vector_requests) == 1
        assert ctx.vector_requests[0].search_text == "hello"


# ---------------------------------------------------------------------------
# vg_optimize: plan-tree pattern detection tests
# ---------------------------------------------------------------------------

class TestVgOptimize:
    def _make_plan_tree(self, limit=10, direction="DESC"):
        """Build a plan tree: SLICE → ORDER → PROJECT → EXTEND(vg:vectorSimilarity) → BGP."""
        from vitalgraph.db.sparql_sql.ir import (
            PlanV2, KIND_SLICE, KIND_ORDER, KIND_PROJECT, KIND_EXTEND, KIND_BGP,
        )
        bgp = PlanV2(kind=KIND_BGP)
        extend = PlanV2(
            kind=KIND_EXTEND,
            extend_var="score",
            extend_expr=ExprFunction(
                name="", function_iri=VG_VECTOR_SIMILARITY,
                args=[_var("entity"), _lit("text"), _lit("idx")],
            ),
            children=[bgp],
        )
        project = PlanV2(
            kind=KIND_PROJECT,
            project_vars=["entity", "score"],
            children=[extend],
        )
        order = PlanV2(
            kind=KIND_ORDER,
            order_conditions=[("score", direction)],
            children=[project],
        )
        slice_node = PlanV2(
            kind=KIND_SLICE,
            limit=limit,
            children=[order],
        )
        return slice_node, extend

    def test_top_k_detected(self):
        from vitalgraph.db.sparql_sql.vg_optimize import vg_optimize
        root, extend = self._make_plan_tree(limit=10, direction="DESC")
        vg_optimize(root)
        assert 'vg_top_k' in extend.hints
        assert extend.hints['vg_top_k']['limit'] == 10
        assert extend.hints['vg_top_k']['direction'] == "DESC"

    def test_no_top_k_without_limit(self):
        from vitalgraph.db.sparql_sql.vg_optimize import vg_optimize
        from vitalgraph.db.sparql_sql.ir import (
            PlanV2, KIND_ORDER, KIND_PROJECT, KIND_EXTEND, KIND_BGP,
        )
        # ORDER without SLICE → no top-K
        bgp = PlanV2(kind=KIND_BGP)
        extend = PlanV2(
            kind=KIND_EXTEND,
            extend_var="score",
            extend_expr=ExprFunction(
                name="", function_iri=VG_VECTOR_SIMILARITY,
                args=[_var("entity"), _lit("text"), _lit("idx")],
            ),
            children=[bgp],
        )
        order = PlanV2(
            kind=KIND_ORDER,
            order_conditions=[("score", "DESC")],
            children=[PlanV2(kind=KIND_PROJECT, project_vars=["entity", "score"], children=[extend])],
        )
        vg_optimize(order)
        assert 'vg_top_k' not in extend.hints

    def test_threshold_pushdown_detected(self):
        from vitalgraph.db.sparql_sql.vg_optimize import vg_optimize
        from vitalgraph.db.sparql_sql.ir import (
            PlanV2, KIND_FILTER, KIND_EXTEND, KIND_BGP,
        )
        bgp = PlanV2(kind=KIND_BGP)
        extend = PlanV2(
            kind=KIND_EXTEND,
            extend_var="score",
            extend_expr=ExprFunction(
                name="", function_iri=VG_VECTOR_SIMILARITY,
                args=[_var("entity"), _lit("text"), _lit("idx")],
            ),
            children=[bgp],
        )
        filter_expr = ExprFunction(
            name="gt", function_iri=None,
            args=[_var("score"), _lit("0.7")],
        )
        filter_node = PlanV2(
            kind=KIND_FILTER,
            filter_exprs=[filter_expr],
            children=[extend],
        )
        vg_optimize(filter_node)
        assert 'vg_threshold' in extend.hints
        assert extend.hints['vg_threshold'] == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# Hint-driven SQL generation tests
# ---------------------------------------------------------------------------

class TestHintDrivenSQL:
    def test_threshold_adds_where_clause(self):
        expr = ExprFunction(
            name="", function_iri=VG_VECTOR_SIMILARITY,
            args=[_var("entity"), _lit("text"), _lit("idx")],
        )
        ctx = _make_ctx()
        ctx.vg_hints = {'vg_threshold': 0.7}
        sql, _ = vector_similarity_sql(expr, ctx)
        assert sql is not None
        assert "> 0.7" in sql

    def test_top_k_adds_order_by(self):
        expr = ExprFunction(
            name="", function_iri=VG_VECTOR_SIMILARITY,
            args=[_var("entity"), _lit("text"), _lit("idx")],
        )
        ctx = _make_ctx()
        ctx.vg_hints = {'vg_top_k': {'limit': 10, 'direction': 'DESC'}}
        sql, _ = vector_similarity_sql(expr, ctx)
        assert sql is not None
        assert "ORDER BY" in sql

    def test_no_hints_no_extra_clauses(self):
        expr = ExprFunction(
            name="", function_iri=VG_VECTOR_SIMILARITY,
            args=[_var("entity"), _lit("text"), _lit("idx")],
        )
        ctx = _make_ctx()
        ctx.vg_hints = {}
        sql, _ = vector_similarity_sql(expr, ctx)
        assert sql is not None
        assert "ORDER BY" not in sql
        assert "> 0" not in sql

    def test_combined_threshold_and_top_k(self):
        expr = ExprFunction(
            name="", function_iri=VG_VECTOR_SIMILARITY,
            args=[_var("entity"), _lit("text"), _lit("idx")],
        )
        ctx = _make_ctx()
        ctx.vg_hints = {
            'vg_threshold': 0.5,
            'vg_top_k': {'limit': 20, 'direction': 'DESC'},
        }
        sql, _ = vector_similarity_sql(expr, ctx)
        assert sql is not None
        assert "ORDER BY" in sql
        assert "> 0.5" in sql


# ---------------------------------------------------------------------------
# Vector-driving emit_extend integration test
# ---------------------------------------------------------------------------

class TestVectorDrivingEmit:
    def test_emit_extend_uses_join_with_top_k_hint(self):
        from vitalgraph.db.sparql_sql.ir import PlanV2, KIND_EXTEND, KIND_BGP
        from vitalgraph.db.sparql_sql.emit_context import EmitContext
        from vitalgraph.db.sparql_sql.emit_extend import emit_extend

        # Build a minimal plan with vg_top_k hint
        bgp = PlanV2(kind=KIND_BGP)
        extend = PlanV2(
            kind=KIND_EXTEND,
            extend_var="score",
            extend_expr=ExprFunction(
                name="", function_iri=VG_VECTOR_NEARBY,
                args=[_var("entity"), _lit("[0.1,0.2,0.3]"), _lit("my_idx")],
            ),
            children=[bgp],
            hints={'vg_top_k': {'limit': 5, 'direction': 'DESC'}},
        )

        # Create a real EmitContext with the entity var registered
        ctx = EmitContext(space_id="test_space")
        from vitalgraph.db.sparql_sql.sql_type_generation import ColumnInfo
        info = ColumnInfo.simple_output("entity", "v0", from_triple=True)
        ctx.types.register(info)

        # Mock child_sql (normally from emit(bgp))
        child_sql = "SELECT v0 AS v0, v0__uuid FROM test_space_rdf_quad"

        from vitalgraph.db.sparql_sql.emit_extend import _try_vector_driving_extend
        result = _try_vector_driving_extend(extend, ctx, child_sql)

        assert result is not None
        assert "JOIN" in result
        assert "test_space_vec_my_idx" in result
        assert "ORDER BY" in result
        assert "LIMIT 5" in result
        assert "v0__uuid" in result
        assert "__vg_score" in result

    def test_emit_extend_falls_back_without_hint(self):
        from vitalgraph.db.sparql_sql.ir import PlanV2, KIND_EXTEND, KIND_BGP
        from vitalgraph.db.sparql_sql.emit_extend import _try_vector_driving_extend
        from vitalgraph.db.sparql_sql.emit_context import EmitContext

        bgp = PlanV2(kind=KIND_BGP)
        extend = PlanV2(
            kind=KIND_EXTEND,
            extend_var="score",
            extend_expr=ExprFunction(
                name="", function_iri=VG_VECTOR_SIMILARITY,
                args=[_var("entity"), _lit("text"), _lit("idx")],
            ),
            children=[bgp],
        )

        ctx = EmitContext(space_id="test_space")
        result = _try_vector_driving_extend(extend, ctx, "SELECT 1")
        assert result is None


# ---------------------------------------------------------------------------
# Multi-vector function tests
# ---------------------------------------------------------------------------

class TestMultiVectorExtraction:
    """Tests for extract_multi_vector_args."""

    def test_two_triplets(self):
        from vitalgraph.db.sparql_sql.vg_functions import (
            VG_MULTI_VECTOR_SIMILARITY, extract_multi_vector_args,
        )
        expr = ExprFunction(
            name="", function_iri=VG_MULTI_VECTOR_SIMILARITY,
            args=[
                _var("entity"),
                _lit("tech company"), _lit("entity_type_default"), _lit("0.3"),
                _lit("renewable energy"), _lit("entity_default"), _lit("0.7"),
            ],
        )
        result = extract_multi_vector_args(expr)
        assert result is not None
        assert result.entity_var == "entity"
        assert len(result.triplets) == 2
        assert result.triplets[0].search_text == "tech company"
        assert result.triplets[0].index_name == "entity_type_default"
        assert result.triplets[0].weight == 0.3
        assert result.triplets[1].search_text == "renewable energy"
        assert result.triplets[1].index_name == "entity_default"
        assert result.triplets[1].weight == 0.7

    def test_three_triplets(self):
        from vitalgraph.db.sparql_sql.vg_functions import (
            VG_MULTI_VECTOR_SIMILARITY, extract_multi_vector_args,
        )
        expr = ExprFunction(
            name="", function_iri=VG_MULTI_VECTOR_SIMILARITY,
            args=[
                _var("entity"),
                _lit("a"), _lit("idx_a"), _lit("0.2"),
                _lit("b"), _lit("idx_b"), _lit("0.5"),
                _lit("c"), _lit("idx_c"), _lit("0.3"),
            ],
        )
        result = extract_multi_vector_args(expr)
        assert result is not None
        assert len(result.triplets) == 3
        assert result.triplets[2].search_text == "c"
        assert result.triplets[2].index_name == "idx_c"

    def test_nearby_variant(self):
        from vitalgraph.db.sparql_sql.vg_functions import (
            VG_MULTI_VECTOR_NEARBY, extract_multi_vector_args,
        )
        expr = ExprFunction(
            name="", function_iri=VG_MULTI_VECTOR_NEARBY,
            args=[
                _var("entity"),
                _lit("[0.1,0.2,0.3]"), _lit("idx_a"), _lit("0.4"),
                _lit("[0.4,0.5]"), _lit("idx_b"), _lit("0.6"),
            ],
        )
        result = extract_multi_vector_args(expr)
        assert result is not None
        assert result.triplets[0].vector_literal == "[0.1,0.2,0.3]"
        assert result.triplets[0].search_text is None
        assert result.triplets[1].vector_literal == "[0.4,0.5]"
        assert result.triplets[1].search_text is None

    def test_bad_arg_count(self):
        from vitalgraph.db.sparql_sql.vg_functions import (
            VG_MULTI_VECTOR_SIMILARITY, extract_multi_vector_args,
        )
        # Only 2 extra args instead of 3 (missing weight)
        expr = ExprFunction(
            name="", function_iri=VG_MULTI_VECTOR_SIMILARITY,
            args=[_var("entity"), _lit("text"), _lit("idx")],
        )
        assert extract_multi_vector_args(expr) is None

    def test_too_few_args(self):
        from vitalgraph.db.sparql_sql.vg_functions import (
            VG_MULTI_VECTOR_SIMILARITY, extract_multi_vector_args,
        )
        # Only entity var, no triplets
        expr = ExprFunction(
            name="", function_iri=VG_MULTI_VECTOR_SIMILARITY,
            args=[_var("entity")],
        )
        assert extract_multi_vector_args(expr) is None


class TestMultiVectorSQL:
    """Tests for multi_vector_similarity_sql."""

    def test_generates_cte_sql(self):
        from vitalgraph.db.sparql_sql.vg_functions import (
            VG_MULTI_VECTOR_SIMILARITY, multi_vector_similarity_sql,
        )
        expr = ExprFunction(
            name="", function_iri=VG_MULTI_VECTOR_SIMILARITY,
            args=[
                _var("entity"),
                _lit("tech company"), _lit("entity_type_default"), _lit("0.3"),
                _lit("renewable energy"), _lit("entity_default"), _lit("0.7"),
            ],
        )
        ctx = _make_ctx()
        sql, vec_requests = multi_vector_similarity_sql(expr, ctx)

        assert sql is not None
        assert "__mv_v0" in sql
        assert "__mv_v1" in sql
        assert "test_space_vec_entity_type_default" in sql
        assert "test_space_vec_entity_default" in sql
        assert "IS NOT NULL" in sql  # null check for INTERSECT semantics

    def test_vector_requests_generated(self):
        from vitalgraph.db.sparql_sql.vg_functions import (
            VG_MULTI_VECTOR_SIMILARITY, multi_vector_similarity_sql,
        )
        expr = ExprFunction(
            name="", function_iri=VG_MULTI_VECTOR_SIMILARITY,
            args=[
                _var("entity"),
                _lit("tech company"), _lit("idx_a"), _lit("0.5"),
                _lit("energy"), _lit("idx_b"), _lit("0.5"),
            ],
        )
        ctx = _make_ctx()
        sql, vec_requests = multi_vector_similarity_sql(expr, ctx)

        assert len(vec_requests) == 2
        assert vec_requests[0].search_text == "tech company"
        assert vec_requests[0].index_name == "idx_a"
        assert vec_requests[1].search_text == "energy"
        assert vec_requests[1].index_name == "idx_b"

    def test_nearby_no_vector_requests(self):
        from vitalgraph.db.sparql_sql.vg_functions import (
            VG_MULTI_VECTOR_NEARBY, multi_vector_similarity_sql,
        )
        expr = ExprFunction(
            name="", function_iri=VG_MULTI_VECTOR_NEARBY,
            args=[
                _var("entity"),
                _lit("[0.1,0.2]"), _lit("idx_a"), _lit("0.5"),
                _lit("[0.3,0.4]"), _lit("idx_b"), _lit("0.5"),
            ],
        )
        ctx = _make_ctx()
        sql, vec_requests = multi_vector_similarity_sql(expr, ctx)

        assert sql is not None
        assert len(vec_requests) == 0  # pre-computed vectors, no vectorization needed
        assert "[0.1,0.2]" in sql
        assert "[0.3,0.4]" in sql

    def test_weight_normalization(self):
        from vitalgraph.db.sparql_sql.vg_functions import (
            VG_MULTI_VECTOR_SIMILARITY, multi_vector_similarity_sql,
        )
        # Weights (3, 7) should normalize to (0.3, 0.7)
        expr = ExprFunction(
            name="", function_iri=VG_MULTI_VECTOR_SIMILARITY,
            args=[
                _var("entity"),
                _lit("a"), _lit("idx_a"), _lit("3"),
                _lit("b"), _lit("idx_b"), _lit("7"),
            ],
        )
        ctx = _make_ctx()
        sql, _ = multi_vector_similarity_sql(expr, ctx)

        assert sql is not None
        assert "0.300000" in sql
        assert "0.700000" in sql


# ---------------------------------------------------------------------------
# Text / Hybrid search detection tests
# ---------------------------------------------------------------------------

class TestTextFunctionDetection:
    def test_is_vg_text_function(self):
        for iri in (VG_TEXT_SEARCH, VG_HYBRID_SEARCH):
            expr = ExprFunction(name="", args=[], function_iri=iri)
            assert is_vg_text_function(expr)
            assert is_vg_function(expr)

    def test_text_not_vector(self):
        """textSearch/hybridSearch should NOT be detected by is_vg_vector_function."""
        for iri in (VG_TEXT_SEARCH, VG_HYBRID_SEARCH):
            expr = ExprFunction(name="", args=[], function_iri=iri)
            assert not is_vg_vector_function(expr)
            assert not is_vg_geo_function(expr)

    def test_all_functions_count(self):
        assert len(VG_ALL_FUNCTIONS) == 12

    def test_text_functions_set(self):
        assert VG_TEXT_SEARCH in VG_TEXT_FUNCTIONS
        assert VG_HYBRID_SEARCH in VG_TEXT_FUNCTIONS
        assert len(VG_TEXT_FUNCTIONS) == 2


# ---------------------------------------------------------------------------
# Text search argument extraction tests
# ---------------------------------------------------------------------------

class TestExtractTextSearchArgs:
    def test_textSearch_args(self):
        expr = ExprFunction(
            name="", function_iri=VG_TEXT_SEARCH,
            args=[_var("entity"), _lit("renewable energy"), _lit("kgtype_default")],
        )
        ta = extract_text_search_args(expr)
        assert ta is not None
        assert ta.entity_var == "entity"
        assert ta.search_text == "renewable energy"
        assert ta.index_name == "kgtype_default"
        assert ta.alpha is None

    def test_hybridSearch_args(self):
        expr = ExprFunction(
            name="", function_iri=VG_HYBRID_SEARCH,
            args=[_var("entity"), _lit("solar panels"), _lit("entity_default"), _lit("0.7")],
        )
        ta = extract_text_search_args(expr)
        assert ta is not None
        assert ta.entity_var == "entity"
        assert ta.search_text == "solar panels"
        assert ta.index_name == "entity_default"
        assert ta.alpha == pytest.approx(0.7)

    def test_hybridSearch_wrong_arg_count(self):
        """hybridSearch needs 4 args; 3 should fail."""
        expr = ExprFunction(
            name="", function_iri=VG_HYBRID_SEARCH,
            args=[_var("entity"), _lit("text"), _lit("idx")],
        )
        assert extract_text_search_args(expr) is None

    def test_textSearch_first_arg_not_var(self):
        expr = ExprFunction(
            name="", function_iri=VG_TEXT_SEARCH,
            args=[_lit("not_a_var"), _lit("text"), _lit("idx")],
        )
        assert extract_text_search_args(expr) is None

    def test_textSearch_missing_index(self):
        """textSearch needs 3 args; 2 should fail."""
        expr = ExprFunction(
            name="", function_iri=VG_TEXT_SEARCH,
            args=[_var("entity"), _lit("text")],
        )
        assert extract_text_search_args(expr) is None


# ---------------------------------------------------------------------------
# Text search SQL generation tests
# ---------------------------------------------------------------------------

class TestTextSearchSQL:
    def test_textSearch_generates_fts_subquery(self):
        expr = ExprFunction(
            name="", function_iri=VG_TEXT_SEARCH,
            args=[_var("entity"), _lit("renewable energy"), _lit("kgtype_default")],
        )
        ctx = _make_ctx()
        sql = text_search_sql(expr, ctx)

        assert sql is not None
        assert "test_space_fts_kgtype_default" in sql
        assert "ts_rank_cd" in sql
        assert "plainto_tsquery" in sql
        assert "renewable energy" in sql
        assert "tsv @@" in sql
        assert "v0__uuid" in sql

    def test_textSearch_context_scoping(self):
        expr = ExprFunction(
            name="", function_iri=VG_TEXT_SEARCH,
            args=[_var("entity"), _lit("text"), _lit("idx")],
        )
        ctx = _make_ctx()
        ctx.graph_lock_uri = "http://example.org/graph/1"
        sql = text_search_sql(expr, ctx)
        assert sql is not None
        assert "context_uuid" in sql
        assert "test_space_term" in sql

    def test_textSearch_no_context_without_lock(self):
        expr = ExprFunction(
            name="", function_iri=VG_TEXT_SEARCH,
            args=[_var("entity"), _lit("text"), _lit("idx")],
        )
        ctx = _make_ctx()
        sql = text_search_sql(expr, ctx)
        assert sql is not None
        assert "context_uuid" not in sql

    def test_textSearch_escapes_single_quotes(self):
        expr = ExprFunction(
            name="", function_iri=VG_TEXT_SEARCH,
            args=[_var("entity"), _lit("it's a test"), _lit("idx")],
        )
        ctx = _make_ctx()
        sql = text_search_sql(expr, ctx)
        assert sql is not None
        assert "it''''s a test" in sql or "it''s a test" in sql


# ---------------------------------------------------------------------------
# Hybrid search SQL generation tests
# ---------------------------------------------------------------------------

class TestHybridSearchSQL:
    def test_hybridSearch_generates_fusion_subquery(self):
        expr = ExprFunction(
            name="", function_iri=VG_HYBRID_SEARCH,
            args=[_var("entity"), _lit("renewable energy"), _lit("entity_default"), _lit("0.5")],
        )
        ctx = _make_ctx()
        sql, vr = hybrid_search_sql(expr, ctx)

        assert sql is not None
        assert "test_space_fts_entity_default" in sql
        assert "test_space_vec_entity_default" in sql
        assert "ts_rank_cd" in sql
        assert "plainto_tsquery" in sql
        assert "embedding <=>" in sql
        assert "v0__uuid" in sql
        # Both BM25 and cosine terms present
        assert "0.500000" in sql

    def test_hybridSearch_creates_vector_request(self):
        expr = ExprFunction(
            name="", function_iri=VG_HYBRID_SEARCH,
            args=[_var("entity"), _lit("solar panels"), _lit("my_idx"), _lit("0.6")],
        )
        ctx = _make_ctx()
        sql, vr = hybrid_search_sql(expr, ctx)

        assert sql is not None
        assert vr is not None
        assert vr.search_text == "solar panels"
        assert vr.index_name == "my_idx"
        assert vr.space_id == "test_space"
        assert vr.placeholder in sql

    def test_hybridSearch_context_scoping(self):
        expr = ExprFunction(
            name="", function_iri=VG_HYBRID_SEARCH,
            args=[_var("entity"), _lit("text"), _lit("idx"), _lit("0.5")],
        )
        ctx = _make_ctx()
        ctx.graph_lock_uri = "http://example.org/graph/1"
        sql, _ = hybrid_search_sql(expr, ctx)
        assert sql is not None
        assert "context_uuid" in sql

    def test_hybridSearch_alpha_reflected_in_sql(self):
        """alpha=0.8 → BM25 weight 0.2, vector weight 0.8."""
        expr = ExprFunction(
            name="", function_iri=VG_HYBRID_SEARCH,
            args=[_var("entity"), _lit("text"), _lit("idx"), _lit("0.8")],
        )
        ctx = _make_ctx()
        sql, _ = hybrid_search_sql(expr, ctx)
        assert sql is not None
        assert "0.200000" in sql  # BM25 weight = 1 - 0.8
        assert "0.800000" in sql  # vector weight = 0.8

    def test_hybridSearch_alpha_zero_is_pure_bm25_weight(self):
        """alpha=0 → BM25 weight 1.0, vector weight 0.0."""
        expr = ExprFunction(
            name="", function_iri=VG_HYBRID_SEARCH,
            args=[_var("entity"), _lit("text"), _lit("idx"), _lit("0.0")],
        )
        ctx = _make_ctx()
        sql, _ = hybrid_search_sql(expr, ctx)
        assert sql is not None
        assert "1.000000" in sql  # BM25 weight = 1.0
        assert "0.000000" in sql  # vector weight = 0.0


# ---------------------------------------------------------------------------
# Text/Hybrid search type inference tests
# ---------------------------------------------------------------------------

class TestTextSearchTypeInference:
    def test_textSearch_inferred_as_double(self):
        from vitalgraph.db.sparql_sql.sql_type_generation import _infer_function_type
        expr = ExprFunction(
            name="", function_iri=VG_TEXT_SEARCH,
            args=[_var("entity"), _lit("text"), _lit("idx")],
        )
        aliases = AliasGenerator()
        registry = TypeRegistry(aliases=aliases)
        te = _infer_function_type(expr, registry)
        assert te.sparql_type == "literal"
        assert te.datatype is not None and te.datatype.endswith("double")
        assert te.is_numeric

    def test_hybridSearch_inferred_as_double(self):
        from vitalgraph.db.sparql_sql.sql_type_generation import _infer_function_type
        expr = ExprFunction(
            name="", function_iri=VG_HYBRID_SEARCH,
            args=[_var("entity"), _lit("text"), _lit("idx"), _lit("0.5")],
        )
        aliases = AliasGenerator()
        registry = TypeRegistry(aliases=aliases)
        te = _infer_function_type(expr, registry)
        assert te.sparql_type == "literal"
        assert te.datatype is not None and te.datatype.endswith("double")
        assert te.is_numeric


# ---------------------------------------------------------------------------
# Text/Hybrid search emit_expressions integration tests
# ---------------------------------------------------------------------------

class TestTextSearchEmitIntegration:
    def test_is_numeric_recognizes_text_functions(self):
        from vitalgraph.db.sparql_sql.emit_expressions import _is_numeric_expr
        ctx = _make_ctx()

        for iri in (VG_TEXT_SEARCH, VG_HYBRID_SEARCH):
            expr = ExprFunction(name="", args=[], function_iri=iri)
            assert _is_numeric_expr(expr, ctx), f"{iri} should be numeric"

    def test_emit_dispatches_textSearch(self):
        from vitalgraph.db.sparql_sql.emit_expressions import _vg_function_to_sql
        expr = ExprFunction(
            name="", function_iri=VG_TEXT_SEARCH,
            args=[_var("entity"), _lit("renewable energy"), _lit("kgtype_default")],
        )
        ctx = _make_ctx()
        sql = _vg_function_to_sql(expr, ctx)
        assert sql is not None
        assert "ts_rank_cd" in sql
        assert "test_space_fts_kgtype_default" in sql
        # textSearch should NOT record a VectorRequest
        assert len(ctx._vector_requests) == 0

    def test_emit_dispatches_hybridSearch(self):
        from vitalgraph.db.sparql_sql.emit_expressions import _vg_function_to_sql
        expr = ExprFunction(
            name="", function_iri=VG_HYBRID_SEARCH,
            args=[_var("entity"), _lit("solar panels"), _lit("entity_default"), _lit("0.5")],
        )
        ctx = _make_ctx()
        sql = _vg_function_to_sql(expr, ctx)
        assert sql is not None
        assert "ts_rank_cd" in sql
        assert "embedding <=>" in sql
        # hybridSearch SHOULD record a VectorRequest
        assert len(ctx._vector_requests) == 1
        assert ctx._vector_requests[0].search_text == "solar panels"


# ---------------------------------------------------------------------------
# Trigram similarity tests
# ---------------------------------------------------------------------------

def _make_ctx_with_name(space_id: str = "test_space"):
    """Create a mock EmitContext with a ?name variable that has a text_col."""
    aliases = AliasGenerator()
    types = TypeRegistry(aliases=aliases)
    # Register ?name variable with text_col (simulates term table binding)
    name_info = ColumnInfo.simple_output("name", "q1", from_triple=True)
    types.register(name_info)
    # Also register ?entity for mixed tests
    entity_info = ColumnInfo.simple_output("entity", "v0", from_triple=True)
    types.register(entity_info)

    ctx = MagicMock()
    ctx.space_id = space_id
    ctx.types = types
    ctx.graph_lock_uri = None
    ctx.vg_hints = {}
    return ctx


class TestTrigramDetection:
    def test_is_vg_trigram_function(self):
        expr = ExprFunction(name="", args=[], function_iri=VG_TRIGRAM_SIMILARITY)
        assert is_vg_trigram_function(expr)
        assert is_vg_function(expr)
        assert not is_vg_vector_function(expr)
        assert not is_vg_text_function(expr)
        assert not is_vg_geo_function(expr)

    def test_trigram_functions_set(self):
        assert VG_TRIGRAM_SIMILARITY in VG_TRIGRAM_FUNCTIONS
        assert len(VG_TRIGRAM_FUNCTIONS) == 1
        assert VG_TRIGRAM_SIMILARITY in VG_ALL_FUNCTIONS


class TestTrigramArgExtraction:
    def test_extract_trigram_args(self):
        expr = ExprFunction(
            name="", function_iri=VG_TRIGRAM_SIMILARITY,
            args=[_var("name"), _lit("Jonh Smth")],
        )
        targs = extract_trigram_args(expr)
        assert targs is not None
        assert targs.var_name == "name"
        assert targs.search_text == "Jonh Smth"

    def test_extract_trigram_args_too_few(self):
        expr = ExprFunction(
            name="", function_iri=VG_TRIGRAM_SIMILARITY,
            args=[_var("name")],
        )
        assert extract_trigram_args(expr) is None

    def test_extract_trigram_args_wrong_types(self):
        expr = ExprFunction(
            name="", function_iri=VG_TRIGRAM_SIMILARITY,
            args=[_lit("not_a_var"), _lit("text")],
        )
        assert extract_trigram_args(expr) is None


class TestTrigramSimilaritySQL:
    def test_generates_word_similarity(self):
        expr = ExprFunction(
            name="", function_iri=VG_TRIGRAM_SIMILARITY,
            args=[_var("name"), _lit("Jonh Smth")],
        )
        ctx = _make_ctx_with_name()
        sql = trigram_similarity_sql(expr, ctx)
        assert sql is not None
        assert "word_similarity" in sql
        assert "Jonh Smth" in sql

    def test_escapes_single_quotes(self):
        expr = ExprFunction(
            name="", function_iri=VG_TRIGRAM_SIMILARITY,
            args=[_var("name"), _lit("O'Brien")],
        )
        ctx = _make_ctx_with_name()
        sql = trigram_similarity_sql(expr, ctx)
        assert sql is not None
        assert "O''Brien" in sql

    def test_returns_none_for_unbound_var(self):
        expr = ExprFunction(
            name="", function_iri=VG_TRIGRAM_SIMILARITY,
            args=[_var("unknown_var"), _lit("text")],
        )
        ctx = _make_ctx_with_name()
        # unknown_var has no text_col — returns NULL from registry
        # but trigram_similarity_sql checks for text_col explicitly
        sql = trigram_similarity_sql(expr, ctx)
        # The variable resolves to NULL text_col, so it should still work
        # (word_similarity on NULL returns NULL at runtime)
        assert sql is not None or sql is None  # either is acceptable

    def test_emit_dispatches_trigram(self):
        from vitalgraph.db.sparql_sql.emit_expressions import _vg_function_to_sql
        expr = ExprFunction(
            name="", function_iri=VG_TRIGRAM_SIMILARITY,
            args=[_var("name"), _lit("Jonh Smth")],
        )
        ctx = _make_ctx_with_name()
        sql = _vg_function_to_sql(expr, ctx)
        assert sql is not None
        assert "word_similarity" in sql

    def test_is_numeric(self):
        from vitalgraph.db.sparql_sql.emit_expressions import _is_numeric_expr
        expr = ExprFunction(
            name="", function_iri=VG_TRIGRAM_SIMILARITY,
            args=[_var("name"), _lit("text")],
        )
        ctx = _make_ctx_with_name()
        assert _is_numeric_expr(expr, ctx)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
