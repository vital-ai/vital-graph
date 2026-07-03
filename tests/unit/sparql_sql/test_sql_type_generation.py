"""Unit tests for vitalgraph.db.sparql_sql.sql_type_generation.

Tests ColumnInfo, TypedExpr, TypeRegistry, infer_expr_type, and helper functions
to ensure companion columns, typed lanes, and type inference are correct.
"""
# pyright: reportOperatorIssue=false, reportArgumentType=false

from __future__ import annotations

import pytest

from vitalgraph.db.jena_sparql.jena_types import (
    ExprVar, ExprValue, ExprFunction, ExprAggregator,
    LiteralNode, URINode,
)
from vitalgraph.db.sparql_sql.ir import AliasGenerator
from vitalgraph.db.sparql_sql.sql_type_generation import (
    ColumnInfo, TypedExpr, TypeRegistry,
    COMPANION_SUFFIXES, XSD, RDF_LANG_STRING,
    infer_expr_type, sparql_error_guard, _q,
)


# ---------------------------------------------------------------------------
# ColumnInfo
# ---------------------------------------------------------------------------

class TestColumnInfo:

    def test_simple_output(self):
        info = ColumnInfo.simple_output("name", "v0", from_triple=True)
        assert info.sparql_name == "name"
        assert info.sql_name == "v0"
        assert info.text_col == "v0"
        assert info.type_col == "v0__type"
        assert info.uuid_col == "v0__uuid"
        assert info.lang_col == "v0__lang"
        assert info.dt_col == "v0__datatype"
        assert info.num_col == "v0__num"
        assert info.from_triple is True

    def test_simple_output_typed_lane(self):
        info = ColumnInfo.simple_output("x", "v1", typed_lane="num")
        assert info.typed_lane == "num"

    def test_has_companions(self):
        info = ColumnInfo.simple_output("x", "v0")
        assert info.has_companions() is True

    def test_has_companions_false(self):
        info = ColumnInfo(sparql_name="x", type_col=None)
        assert info.has_companions() is False

    def test_companion_cols(self):
        info = ColumnInfo.simple_output("x", "v0")
        cols = info.companion_cols()
        assert "v0__uuid" in cols
        assert "v0__type" in cols
        assert "v0__lang" in cols
        assert "v0__datatype" in cols

    def test_companion_cols_null_fallbacks(self):
        info = ColumnInfo(sparql_name="x", sql_name="v0",
                         uuid_col=None, type_col=None,
                         lang_col=None, dt_col=None)
        cols = info.companion_cols()
        assert cols["v0__uuid"] == "NULL"
        assert cols["v0__type"] == "'L'"
        assert cols["v0__lang"] == "NULL"
        assert cols["v0__datatype"] == "NULL"


# ---------------------------------------------------------------------------
# TypedExpr
# ---------------------------------------------------------------------------

class TestTypedExpr:

    def test_type_sql_literal(self):
        te = TypedExpr(sql="expr", sparql_type="literal")
        assert te.type_sql == "'L'"

    def test_type_sql_uri(self):
        te = TypedExpr(sql="expr", sparql_type="uri")
        assert te.type_sql == "'U'"

    def test_type_sql_bnode(self):
        te = TypedExpr(sql="expr", sparql_type="bnode")
        assert te.type_sql == "'B'"

    def test_datatype_sql_none(self):
        te = TypedExpr(sql="expr")
        assert te.datatype_sql == "NULL"

    def test_datatype_sql_constant(self):
        te = TypedExpr(sql="expr", datatype=f"{XSD}integer")
        assert te.datatype_sql == f"'{XSD}integer'"

    def test_datatype_sql_dynamic(self):
        te = TypedExpr(sql="expr", datatype="sub.o__datatype",
                      datatype_is_sql=True)
        assert te.datatype_sql == "sub.o__datatype"

    def test_lang_sql_none(self):
        te = TypedExpr(sql="expr")
        assert te.lang_sql == "NULL"

    def test_lang_sql_constant(self):
        te = TypedExpr(sql="expr", lang="en")
        assert te.lang_sql == "'en'"

    def test_lang_sql_dynamic(self):
        te = TypedExpr(sql="expr", lang="sub.o__lang", lang_is_sql=True)
        assert te.lang_sql == "sub.o__lang"

    def test_is_numeric_integer(self):
        te = TypedExpr(sql="", datatype=f"{XSD}integer")
        assert te.is_numeric is True

    def test_is_numeric_double(self):
        te = TypedExpr(sql="", datatype=f"{XSD}double")
        assert te.is_numeric is True

    def test_is_numeric_decimal(self):
        te = TypedExpr(sql="", datatype=f"{XSD}decimal")
        assert te.is_numeric is True

    def test_is_numeric_false_for_string(self):
        te = TypedExpr(sql="", datatype=f"{XSD}string")
        assert te.is_numeric is False

    def test_is_numeric_false_for_sql_expr(self):
        te = TypedExpr(sql="", datatype="sub.dt", datatype_is_sql=True)
        assert te.is_numeric is False

    def test_is_boolean(self):
        te = TypedExpr(sql="", datatype=f"{XSD}boolean")
        assert te.is_boolean is True

    def test_is_boolean_false(self):
        te = TypedExpr(sql="", datatype=f"{XSD}integer")
        assert te.is_boolean is False

    def test_is_datetime(self):
        te = TypedExpr(sql="", datatype=f"{XSD}dateTime")
        assert te.is_datetime is True

    def test_is_datetime_date(self):
        te = TypedExpr(sql="", datatype=f"{XSD}date")
        assert te.is_datetime is True

    def test_is_datetime_false(self):
        te = TypedExpr(sql="", datatype=f"{XSD}string")
        assert te.is_datetime is False

    def test_typed_lane_num(self):
        te = TypedExpr(sql="", datatype=f"{XSD}integer")
        assert te.typed_lane == "num"

    def test_typed_lane_bool(self):
        te = TypedExpr(sql="", datatype=f"{XSD}boolean")
        assert te.typed_lane == "bool"

    def test_typed_lane_dt(self):
        te = TypedExpr(sql="", datatype=f"{XSD}dateTime")
        assert te.typed_lane == "dt"

    def test_typed_lane_none(self):
        te = TypedExpr(sql="", datatype=f"{XSD}string")
        assert te.typed_lane is None

    def test_produce_companions_literal(self):
        te = TypedExpr(sql="", sparql_type="literal",
                      datatype=f"{XSD}string")
        cols = te.produce_companions("x", "'hello'")
        assert cols[0] == "'hello' AS x"
        # Should have 1 value col + 7 companions = 8 total
        assert len(cols) == 8
        # type should be 'L'
        assert any("'L'" in c and "__type" in c for c in cols)

    def test_produce_companions_numeric(self):
        te = TypedExpr(sql="", sparql_type="literal",
                      datatype=f"{XSD}integer")
        cols = te.produce_companions("x", "42")
        # __num should use the expression itself (not NULL)
        num_cols = [c for c in cols if "__num" in c]
        assert len(num_cols) == 1
        assert "42" in num_cols[0]
        assert "NULL" not in num_cols[0]

    def test_produce_companions_uri(self):
        te = TypedExpr(sql="", sparql_type="uri")
        cols = te.produce_companions("x", "'http://foo'")
        type_cols = [c for c in cols if "__type" in c]
        assert any("'U'" in c for c in type_cols)

    def test_produce_companions_overrides(self):
        te = TypedExpr(sql="", sparql_type="literal",
                      _companion_overrides={"__type": "custom_expr"})
        cols = te.produce_companions("x", "val")
        type_cols = [c for c in cols if "__type" in c]
        assert any("custom_expr" in c for c in type_cols)

    def test_to_column_info(self):
        te = TypedExpr(sql="", sparql_type="uri", datatype=f"{XSD}string")
        info = te.to_column_info("x", "v0")
        assert info.sparql_name == "x"
        assert info.sql_name == "v0"
        assert info.text_col == "v0"
        assert info.type_col == "'U'"
        assert info.from_triple is False


# ---------------------------------------------------------------------------
# TypeRegistry — basic operations
# ---------------------------------------------------------------------------

class TestTypeRegistryBasic:

    def test_register_and_get(self):
        reg = TypeRegistry()
        info = ColumnInfo.simple_output("x", "v0")
        reg.register(info)
        assert reg.get("x") is info

    def test_get_unknown_returns_none(self):
        reg = TypeRegistry()
        assert reg.get("unknown") is None

    def test_has(self):
        reg = TypeRegistry()
        reg.register(ColumnInfo.simple_output("x", "v0"))
        assert reg.has("x") is True
        assert reg.has("y") is False

    def test_all_vars(self):
        reg = TypeRegistry()
        reg.register(ColumnInfo.simple_output("x", "v0"))
        reg.register(ColumnInfo.simple_output("y", "v1"))
        assert reg.all_vars() == {"x", "y"}

    def test_allocate_with_aliases(self):
        aliases = AliasGenerator()
        reg = TypeRegistry(aliases=aliases)
        name = reg.allocate("myvar")
        assert name.startswith("v")
        # var_map maps sql_name → sparql_name
        assert "myvar" in aliases.var_map.values()

    def test_allocate_without_aliases(self):
        reg = TypeRegistry()
        name = reg.allocate("myvar")
        assert name == "myvar"  # fallback


# ---------------------------------------------------------------------------
# TypeRegistry — registration methods
# ---------------------------------------------------------------------------

class TestTypeRegistryRegistration:

    def test_register_from_triple(self):
        reg = TypeRegistry()
        info = reg.register_from_triple("s", "q0.subject_uuid", "t0")
        assert info.sparql_name == "s"
        assert info.text_col == "t0.term_text"
        assert info.type_col == "t0.term_type"
        assert info.uuid_col == "q0.subject_uuid"
        assert info.lang_col == "t0.lang"
        assert info.num_col == "t0.term_num"
        assert info.from_triple is True
        assert reg.get("s") is info

    def test_register_from_subquery(self):
        reg = TypeRegistry()
        info = reg.register_from_subquery("x", "sub")
        assert info.text_col == "sub.x"
        assert info.type_col == "sub.x__type"
        assert info.uuid_col == "sub.x__uuid"
        assert info.lang_col == "sub.x__lang"
        assert info.dt_col == "sub.x__datatype"
        assert info.from_triple is False

    def test_register_from_subquery_no_text(self):
        reg = TypeRegistry()
        info = reg.register_from_subquery("x", "sub", has_text=False)
        assert info.text_col is None

    def test_register_extend(self):
        reg = TypeRegistry()
        te = TypedExpr(sql="", sparql_type="literal",
                      datatype=f"{XSD}integer")
        info = reg.register_extend("x", te, "v5")
        assert info.sparql_name == "x"
        assert info.sql_name == "v5"
        assert info.typed_lane == "num"
        assert reg.get("x") is info

    def test_register_aggregate_count(self):
        reg = TypeRegistry()
        info = reg.register_aggregate("cnt", "COUNT", "v0")
        assert info.sparql_name == "cnt"
        assert info.typed_lane == "num"
        assert f"{XSD}integer" in info.dt_col

    def test_register_aggregate_avg(self):
        reg = TypeRegistry()
        info = reg.register_aggregate("avg_val", "AVG", "v1")
        assert info.typed_lane == "num"
        assert f"{XSD}decimal" in info.dt_col

    def test_register_aggregate_max_inherits_lane(self):
        reg = TypeRegistry()
        # Register an input var with numeric lane
        reg.register(ColumnInfo(
            sparql_name="x", sql_name="v0",
            dt_col=f"'{XSD}integer'",
            typed_lane="num",
        ))
        info = reg.register_aggregate("mx", "MAX", "v1", input_var="x")
        assert info.typed_lane == "num"


# ---------------------------------------------------------------------------
# TypeRegistry — static helper methods
# ---------------------------------------------------------------------------

class TestTypeRegistryHelpers:

    def test_passthrough_columns(self):
        cols = TypeRegistry.passthrough_columns("v0", "sub")
        # value + 7 companions = 8
        assert len(cols) == 8
        assert cols[0] == "sub.v0 AS v0"
        assert "sub.v0__type AS v0__type" in cols
        assert "sub.v0__uuid AS v0__uuid" in cols
        assert "sub.v0__lang AS v0__lang" in cols
        assert "sub.v0__datatype AS v0__datatype" in cols
        assert "sub.v0__num AS v0__num" in cols

    def test_remap_columns_same_name(self):
        cols = TypeRegistry.remap_columns("v0", "v0", "sub")
        assert cols == TypeRegistry.passthrough_columns("v0", "sub")

    def test_remap_columns_different_name(self):
        cols = TypeRegistry.remap_columns("v0", "v3", "sub")
        assert len(cols) == 8
        assert cols[0] == "sub.v0 AS v3"
        assert "sub.v0__type AS v3__type" in cols
        assert "sub.v0__uuid AS v3__uuid" in cols

    def test_null_companions(self):
        cols = TypeRegistry.null_companions("v0")
        assert len(cols) == 8
        assert cols[0] == "NULL AS v0"
        # UUID should be typed NULL
        uuid_cols = [c for c in cols if "__uuid" in c]
        assert any("NULL::uuid" in c for c in uuid_cols)
        # Num should be typed NULL
        num_cols = [c for c in cols if "__num" in c]
        assert any("NULL::numeric" in c for c in num_cols)

    def test_coalesce_columns(self):
        cols = TypeRegistry.coalesce_columns("v0", "l", "v3", "r")
        assert len(cols) == 8
        assert cols[0] == "COALESCE(l.v0, r.v3) AS v0"
        assert "COALESCE(l.v0__type, r.v3__type) AS v0__type" in cols

    def test_term_table_columns_legacy(self):
        cols = TypeRegistry.term_table_columns(
            var="v0", t_alias="t0", sub_alias="q0",
            numeric_dt_sql_list="1,2,3",
            dt_case_sql="CASE WHEN t0.datatype_id = 1 THEN 'xsd:int' END",
        )
        assert len(cols) == 8
        assert "t0.term_text AS v0" in cols
        assert "t0.term_type AS v0__type" in cols
        assert "q0.v0__uuid AS v0__uuid" in cols
        assert "t0.lang AS v0__lang" in cols
        # datatype col
        dt_cols = [c for c in cols if "__datatype" in c]
        assert len(dt_cols) == 1
        assert "CASE" in dt_cols[0]

    def test_term_table_columns_cte(self):
        cols = TypeRegistry.term_table_columns(
            var="v0", t_alias="t0", sub_alias="q0",
            numeric_dt_sql_list="",
            dt_alias="dt_v0",
        )
        assert len(cols) == 8
        # CTE approach uses subquery from _dt
        dt_cols = [c for c in cols if "__datatype" in c]
        assert any("_dt" in c for c in dt_cols)


# ---------------------------------------------------------------------------
# TypeRegistry — child registry / scope
# ---------------------------------------------------------------------------

class TestTypeRegistryChild:

    def test_child_inherits(self):
        aliases = AliasGenerator()
        parent = TypeRegistry(aliases=aliases)
        parent.register(ColumnInfo.simple_output("x", "v0"))

        child = parent.child_registry()
        assert child.get("x") is not None

    def test_child_independent(self):
        aliases = AliasGenerator()
        parent = TypeRegistry(aliases=aliases)
        parent.register(ColumnInfo.simple_output("x", "v0"))

        child = parent.child_registry()
        child.register(ColumnInfo.simple_output("y", "v1"))

        assert child.has("y") is True
        assert parent.has("y") is False

    def test_child_shares_aliases(self):
        aliases = AliasGenerator()
        parent = TypeRegistry(aliases=aliases)
        child = parent.child_registry()
        n1 = parent.allocate("a")
        n2 = child.allocate("b")
        # Should be distinct names from the same counter
        assert n1 != n2


# ---------------------------------------------------------------------------
# TypeRegistry — group_by_companions
# ---------------------------------------------------------------------------

class TestGroupByCompanions:

    def test_dynamic_companions(self):
        reg = TypeRegistry()
        info = ColumnInfo.simple_output("x", "v0", from_triple=True)
        reg.register(info)
        companions = reg.group_by_companions("x")
        # type, lang, dt are all non-constant → included
        assert "v0__type" in companions
        assert "v0__lang" in companions
        assert "v0__datatype" in companions

    def test_constant_companions_excluded(self):
        reg = TypeRegistry()
        info = ColumnInfo(
            sparql_name="x", sql_name="v0",
            type_col="'L'", lang_col="NULL", dt_col="NULL",
        )
        reg.register(info)
        companions = reg.group_by_companions("x")
        assert companions == []

    def test_unknown_var(self):
        reg = TypeRegistry()
        assert reg.group_by_companions("unknown") == []


# ---------------------------------------------------------------------------
# infer_expr_type
# ---------------------------------------------------------------------------

class TestInferExprType:

    def _reg_with_var(self, var="x", dt_col=None, typed_lane=None):
        reg = TypeRegistry()
        info = ColumnInfo(
            sparql_name=var, sql_name="v0",
            text_col="v0", type_col="v0__type",
            lang_col="v0__lang", dt_col=dt_col,
            typed_lane=typed_lane,
        )
        reg.register(info)
        return reg

    def test_variable_reference(self):
        reg = self._reg_with_var(dt_col=f"'{XSD}integer'")
        te = infer_expr_type(ExprVar(var="x"), reg)
        assert te.datatype == f"{XSD}integer"
        assert te.datatype_is_sql is False

    def test_variable_dynamic_dt(self):
        reg = self._reg_with_var(dt_col="sub.dt")
        te = infer_expr_type(ExprVar(var="x"), reg)
        assert te.datatype == "sub.dt"
        assert te.datatype_is_sql is True

    def test_literal_string(self):
        reg = TypeRegistry()
        expr = ExprValue(node=LiteralNode(value="hello"))
        te = infer_expr_type(expr, reg)
        assert te.sparql_type == "literal"
        assert te.datatype is None

    def test_literal_typed(self):
        reg = TypeRegistry()
        expr = ExprValue(node=LiteralNode(value="42", datatype=f"{XSD}integer"))
        te = infer_expr_type(expr, reg)
        assert te.datatype == f"{XSD}integer"

    def test_literal_lang(self):
        reg = TypeRegistry()
        expr = ExprValue(node=LiteralNode(value="hello", lang="en"))
        te = infer_expr_type(expr, reg)
        assert te.lang == "en"
        assert te.datatype == RDF_LANG_STRING

    def test_uri_node(self):
        reg = TypeRegistry()
        expr = ExprValue(node=URINode(value="http://ex.org/x"))
        te = infer_expr_type(expr, reg)
        assert te.sparql_type == "uri"

    def test_xsd_cast(self):
        reg = TypeRegistry()
        expr = ExprFunction(name="", args=[ExprVar(var="x")],
                           function_iri=f"{XSD}double")
        te = infer_expr_type(expr, reg)
        assert te.datatype == f"{XSD}double"

    def test_iri_constructor(self):
        reg = TypeRegistry()
        expr = ExprFunction(name="iri", args=[ExprVar(var="x")])
        te = infer_expr_type(expr, reg)
        assert te.sparql_type == "uri"

    def test_bnode_constructor(self):
        reg = TypeRegistry()
        expr = ExprFunction(name="bnode", args=[])
        te = infer_expr_type(expr, reg)
        assert te.sparql_type == "bnode"

    def test_now_returns_datetime(self):
        reg = TypeRegistry()
        expr = ExprFunction(name="now", args=[])
        te = infer_expr_type(expr, reg)
        assert te.datatype == f"{XSD}dateTime"

    def test_rand_returns_double(self):
        reg = TypeRegistry()
        expr = ExprFunction(name="rand", args=[])
        te = infer_expr_type(expr, reg)
        assert te.datatype == f"{XSD}double"

    def test_strlen_returns_integer(self):
        reg = TypeRegistry()
        expr = ExprFunction(name="strlen", args=[ExprVar(var="x")])
        te = infer_expr_type(expr, reg)
        assert te.datatype == f"{XSD}integer"

    def test_divide_returns_decimal(self):
        reg = TypeRegistry()
        expr = ExprFunction(name="divide", args=[
            ExprVar(var="x"), ExprVar(var="y")])
        te = infer_expr_type(expr, reg)
        assert te.datatype == f"{XSD}decimal"

    def test_bound_returns_boolean(self):
        reg = TypeRegistry()
        expr = ExprFunction(name="bound", args=[ExprVar(var="x")])
        te = infer_expr_type(expr, reg)
        assert te.datatype == f"{XSD}boolean"

    def test_comparison_returns_boolean(self):
        reg = TypeRegistry()
        expr = ExprFunction(name="lt", args=[
            ExprVar(var="x"), ExprVar(var="y")])
        te = infer_expr_type(expr, reg)
        assert te.datatype == f"{XSD}boolean"

    def test_concat_returns_plain(self):
        reg = TypeRegistry()
        expr = ExprFunction(name="concat", args=[ExprVar(var="x")])
        te = infer_expr_type(expr, reg)
        assert te.datatype is None

    def test_count_aggregator(self):
        reg = TypeRegistry()
        expr = ExprAggregator(name="COUNT", expr=None)
        te = infer_expr_type(expr, reg)
        assert te.datatype == f"{XSD}integer"

    def test_avg_aggregator(self):
        reg = TypeRegistry()
        expr = ExprAggregator(name="AVG", expr=ExprVar(var="x"))
        te = infer_expr_type(expr, reg)
        assert te.datatype == f"{XSD}decimal"

    def test_group_concat(self):
        reg = TypeRegistry()
        expr = ExprAggregator(name="GROUP_CONCAT", expr=ExprVar(var="x"))
        te = infer_expr_type(expr, reg)
        assert te.datatype == f"{XSD}string"


# ---------------------------------------------------------------------------
# sparql_error_guard
# ---------------------------------------------------------------------------

class TestSparqlErrorGuard:

    def test_no_error(self):
        te = TypedExpr(sql="expr", can_error=False)
        result = sparql_error_guard("my_sql", te)
        assert result == "my_sql"

    def test_with_error(self):
        te = TypedExpr(sql="expr", can_error=True)
        result = sparql_error_guard("my_sql", te)
        assert "CASE" in result
        assert "IS NOT NULL" in result
        assert "my_sql" in result


# ---------------------------------------------------------------------------
# _q utility
# ---------------------------------------------------------------------------

class TestQuote:

    def test_simple_identifier(self):
        assert _q("name") == "name"

    def test_underscore_prefix(self):
        assert _q("_internal") == '"_internal"'

    def test_special_chars(self):
        assert _q("my-var") == '"my-var"'

    def test_numeric_prefix(self):
        assert _q("123abc") == '"123abc"'


# ---------------------------------------------------------------------------
# TypeRegistry.project_var and project_companions_only
# ---------------------------------------------------------------------------

class TestProjectVar:

    def _reg(self):
        aliases = AliasGenerator()
        return TypeRegistry(aliases=aliases)

    def test_project_var_unknown(self):
        """Unknown var → NULL AS <var>."""
        reg = self._reg()
        result = reg.project_var("unknown", "src.col")
        assert result == ['NULL AS unknown']

    def test_project_var_known(self):
        """Known var → value + companions."""
        reg = self._reg()
        info = ColumnInfo.simple_output("x", "v0", from_triple=True)
        reg.register(info)
        result = reg.project_var("x", "src.v0")
        assert any("src.v0 AS" in c for c in result)
        assert len(result) >= 2  # value + companions

    def test_project_companions_only_unknown(self):
        """Unknown var → NULL companions."""
        reg = self._reg()
        result = reg.project_companions_only("missing")
        assert any("NULL AS missing__uuid" in c for c in result)
        assert any("'L' AS missing__type" in c for c in result)

    def test_project_companions_only_known(self):
        """Known var → companion expressions."""
        reg = self._reg()
        info = ColumnInfo.simple_output("x", "v0", from_triple=True)
        reg.register(info)
        result = reg.project_companions_only("x")
        assert len(result) >= 1


# ---------------------------------------------------------------------------
# infer_expr_type — additional function coverage
# ---------------------------------------------------------------------------

class TestInferFunctionTypeExtra:

    def _reg(self):
        aliases = AliasGenerator()
        return TypeRegistry(aliases=aliases)

    def test_uuid_returns_uri(self):
        expr = ExprFunction(name="uuid", args=[])
        result = infer_expr_type(expr, self._reg())
        assert result.sparql_type == "uri"

    def test_struuid_returns_string(self):
        expr = ExprFunction(name="struuid", args=[])
        result = infer_expr_type(expr, self._reg())
        assert result.sparql_type == "literal"
        assert result.datatype == f"{XSD}string"

    def test_abs_preserves_input_type(self):
        """ABS(?x) where x is integer → integer."""
        reg = self._reg()
        info = ColumnInfo(sparql_name="x", sql_name="v0", text_col="v0",
                          dt_col=f"'{XSD}integer'")
        reg.register(info)
        expr = ExprFunction(name="abs", args=[ExprVar(var="x")])
        result = infer_expr_type(expr, reg)
        assert result.datatype == f"{XSD}integer"

    def test_abs_no_arg_defaults_decimal(self):
        """ABS() with no inferrable arg → decimal."""
        expr = ExprFunction(name="abs", args=[])
        result = infer_expr_type(expr, self._reg())
        assert result.datatype == f"{XSD}decimal"

    def test_seconds_returns_decimal(self):
        expr = ExprFunction(name="seconds", args=[ExprVar(var="x")])
        result = infer_expr_type(expr, self._reg())
        assert result.datatype == f"{XSD}decimal"

    def test_timezone_returns_daytime_duration(self):
        expr = ExprFunction(name="timezone", args=[ExprVar(var="x")])
        result = infer_expr_type(expr, self._reg())
        assert result.datatype == f"{XSD}dayTimeDuration"

    def test_tz_returns_plain_literal(self):
        expr = ExprFunction(name="tz", args=[ExprVar(var="x")])
        result = infer_expr_type(expr, self._reg())
        assert result.sparql_type == "literal"
        assert result.datatype is None

    def test_strdt_sets_datatype(self):
        """STRDT(?x, xsd:integer) → literal with integer datatype."""
        xsd_int = f"{XSD}integer"
        expr = ExprFunction(name="strdt", args=[
            ExprVar(var="x"),
            ExprValue(node=LiteralNode(value=xsd_int)),
        ])
        result = infer_expr_type(expr, self._reg())
        assert result.datatype == xsd_int

    def test_strlang_sets_lang(self):
        """STRLANG(?x, 'en') → rdf:langString with lang=en."""
        expr = ExprFunction(name="strlang", args=[
            ExprVar(var="x"),
            ExprValue(node=LiteralNode(value="en")),
        ])
        result = infer_expr_type(expr, self._reg())
        assert result.datatype == RDF_LANG_STRING
        assert result.lang == "en"

    def test_if_then_branch(self):
        """IF(cond, 42, 'x') → infers from then-branch."""
        xsd_int = f"{XSD}integer"
        expr = ExprFunction(name="if", args=[
            ExprFunction(name="bound", args=[ExprVar(var="x")]),
            ExprValue(node=LiteralNode(value="42", datatype=xsd_int)),
            ExprValue(node=LiteralNode(value="x")),
        ])
        result = infer_expr_type(expr, self._reg())
        assert result.datatype == xsd_int

    def test_if_else_branch(self):
        """IF(cond, ?y, 42) → infers from else-branch when then has no datatype."""
        xsd_int = f"{XSD}integer"
        expr = ExprFunction(name="if", args=[
            ExprFunction(name="bound", args=[ExprVar(var="x")]),
            ExprVar(var="y"),  # unregistered → no datatype
            ExprValue(node=LiteralNode(value="42", datatype=xsd_int)),
        ])
        result = infer_expr_type(expr, self._reg())
        assert result.datatype == xsd_int

    def test_if_no_branches_typed(self):
        """IF(cond, ?a, ?b) with no types → plain literal."""
        expr = ExprFunction(name="if", args=[
            ExprFunction(name="bound", args=[ExprVar(var="x")]),
            ExprVar(var="a"),
            ExprVar(var="b"),
        ])
        result = infer_expr_type(expr, self._reg())
        assert result.sparql_type == "literal"
        assert result.datatype is None

    def test_coalesce_dynamic_companions(self):
        """COALESCE(?x, 42) with dynamic companions → companion overrides."""
        reg = self._reg()
        info = ColumnInfo.simple_output("x", "v0", from_triple=True)
        reg.register(info)
        xsd_int = f"{XSD}integer"
        expr = ExprFunction(name="coalesce", args=[
            ExprVar(var="x"),
            ExprValue(node=LiteralNode(value="42", datatype=xsd_int)),
        ])
        result = infer_expr_type(expr, reg)
        assert result.datatype_is_sql is True
        assert result._companion_overrides is not None
        assert "__type" in result._companion_overrides

    def test_coalesce_fallback_static_type(self):
        """COALESCE(?unknown, "hello"^^xsd:string) → picks first static datatype."""
        reg = self._reg()
        xsd_str = f"{XSD}string"
        expr = ExprFunction(name="coalesce", args=[
            ExprVar(var="unknown"),
            ExprValue(node=LiteralNode(value="hello", datatype=xsd_str)),
        ])
        result = infer_expr_type(expr, reg)
        assert result.datatype == xsd_str

    def test_coalesce_no_types(self):
        """COALESCE(?a, ?b) with no types → plain literal."""
        expr = ExprFunction(name="coalesce", args=[
            ExprVar(var="a"),
            ExprVar(var="b"),
        ])
        result = infer_expr_type(expr, self._reg())
        assert result.sparql_type == "literal"

    def test_add_propagates_arg_type(self):
        """add(?x, ?y) where x=integer → integer."""
        reg = self._reg()
        info = ColumnInfo(sparql_name="x", sql_name="v0", text_col="v0",
                          dt_col=f"'{XSD}integer'")
        reg.register(info)
        expr = ExprFunction(name="add", args=[ExprVar(var="x"), ExprVar(var="y")])
        result = infer_expr_type(expr, reg)
        assert result.datatype == f"{XSD}integer"

    def test_add_no_arg_type_defaults_integer(self):
        """add() with no type info → integer."""
        expr = ExprFunction(name="add", args=[ExprVar(var="x")])
        result = infer_expr_type(expr, self._reg())
        assert result.datatype == f"{XSD}integer"

    def test_unknown_expr_fallback(self):
        """Non ExprVar/ExprValue/ExprFunction/ExprAggregator → empty TypedExpr."""
        result = infer_expr_type({"random": "thing"}, self._reg())
        assert result.sql == ""

    def test_var_with_sql_lang(self):
        """Variable with SQL-reference lang col → lang_is_sql=True."""
        reg = self._reg()
        info = ColumnInfo(sparql_name="x", sql_name="v0", text_col="v0",
                          lang_col="t0.lang", dt_col="t0.datatype")
        reg.register(info)
        result = infer_expr_type(ExprVar(var="x"), reg)
        assert result.lang_is_sql is True
        assert result.datatype_is_sql is True

    def test_var_with_constant_lang(self):
        """Variable with constant lang col → lang extracted."""
        reg = self._reg()
        info = ColumnInfo(sparql_name="x", sql_name="v0", text_col="v0",
                          lang_col="'en'", dt_col=f"'{XSD}string'")
        reg.register(info)
        result = infer_expr_type(ExprVar(var="x"), reg)
        assert result.lang == "en"
        assert result.lang_is_sql is False
        assert result.datatype == f"{XSD}string"
        assert result.datatype_is_sql is False

    def test_unregistered_var(self):
        """Unregistered variable → empty TypedExpr."""
        result = infer_expr_type(ExprVar(var="ghost"), self._reg())
        assert result.sql == ""
        assert result.datatype is None


# ---------------------------------------------------------------------------
# _infer_aggregator_type — additional coverage
# ---------------------------------------------------------------------------

class TestInferAggregatorTypeExtra:

    def _reg(self):
        aliases = AliasGenerator()
        return TypeRegistry(aliases=aliases)

    def test_sum_propagates_type(self):
        """SUM(?x) where x=integer → integer."""
        reg = self._reg()
        info = ColumnInfo(sparql_name="x", sql_name="v0", text_col="v0",
                          dt_col=f"'{XSD}integer'")
        reg.register(info)
        expr = ExprAggregator(name="SUM", distinct=False,
                              expr=ExprVar(var="x"))
        result = infer_expr_type(expr, reg)
        assert result.datatype == f"{XSD}integer"

    def test_sum_no_inner_type_defaults_integer(self):
        """SUM(?y) where y has no type → integer."""
        expr = ExprAggregator(name="SUM", distinct=False,
                              expr=ExprVar(var="y"))
        result = infer_expr_type(expr, self._reg())
        assert result.datatype == f"{XSD}integer"

    def test_sample_propagates_type(self):
        """SAMPLE(?x) → inherits x's datatype."""
        reg = self._reg()
        info = ColumnInfo(sparql_name="x", sql_name="v0", text_col="v0",
                          dt_col=f"'{XSD}double'")
        reg.register(info)
        expr = ExprAggregator(name="SAMPLE", distinct=False,
                              expr=ExprVar(var="x"))
        result = infer_expr_type(expr, reg)
        assert result.datatype == f"{XSD}double"

    def test_sample_no_type_returns_plain(self):
        """SAMPLE(?y) with no type → plain literal."""
        expr = ExprAggregator(name="SAMPLE", distinct=False,
                              expr=ExprVar(var="y"))
        result = infer_expr_type(expr, self._reg())
        assert result.sparql_type == "literal"
        assert result.datatype is None

    def test_unknown_agg_returns_literal(self):
        """Unknown aggregator → literal, no datatype."""
        expr = ExprAggregator(name="CUSTOM_AGG", distinct=False, expr=None)
        result = infer_expr_type(expr, self._reg())
        assert result.sparql_type == "literal"
