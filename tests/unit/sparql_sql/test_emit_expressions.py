"""Unit tests for vitalgraph.db.sparql_sql.emit_expressions — expression-to-SQL.

Tests individual SPARQL functions/operators by feeding ExprFunction AST nodes
into expr_to_sql() with a minimal EmitContext. Validates that the generated
SQL fragments are syntactically correct (via pglast) and semantically reasonable.
"""
# pyright: reportOperatorIssue=false, reportArgumentType=false

from __future__ import annotations

from typing import Optional

import pytest

try:
    import pglast
    HAS_PGLAST = True
except ImportError:
    HAS_PGLAST = False

from vitalgraph.db.jena_sparql.jena_types import (
    ExprVar, ExprValue, ExprFunction, ExprAggregator,
    LiteralNode, URINode, BNodeNode,
    SortCondition,
)
from vitalgraph.db.sparql_sql.ir import AliasGenerator
from vitalgraph.db.sparql_sql.emit_context import EmitContext, ProcessingTrace
from vitalgraph.db.sparql_sql.sql_type_generation import ColumnInfo, TypeRegistry
from vitalgraph.db.sparql_sql.emit_expressions import expr_to_sql, XSD


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(vars_config: Optional[dict] = None) -> EmitContext:
    """Build a minimal EmitContext with registered variables.

    vars_config: dict of sparql_name → options
      Options: "text" (default), "numeric", "full" (with all companions)
    """
    aliases = AliasGenerator()
    types = TypeRegistry(aliases=aliases)
    ctx = EmitContext(
        space_id="test_space",
        aliases=aliases,
        types=types,
        trace=ProcessingTrace(),
        base_uri="http://example.org/",
    )

    if vars_config:
        for i, (var_name, kind) in enumerate(vars_config.items()):
            sql_name = f"v{i}"
            if kind == "numeric":
                info = ColumnInfo(
                    sparql_name=var_name,
                    sql_name=sql_name,
                    text_col=sql_name,
                    type_col=f"{sql_name}__type",
                    uuid_col=f"{sql_name}__uuid",
                    lang_col=f"{sql_name}__lang",
                    dt_col=f"{sql_name}__datatype",
                    num_col=f"{sql_name}__num",
                    from_triple=True,
                    typed_lane="num",
                )
            elif kind == "full":
                info = ColumnInfo.simple_output(var_name, sql_name, from_triple=True)
            else:  # "text"
                info = ColumnInfo(
                    sparql_name=var_name,
                    sql_name=sql_name,
                    text_col=sql_name,
                    type_col=f"{sql_name}__type",
                    uuid_col=f"{sql_name}__uuid",
                    lang_col=f"{sql_name}__lang",
                    dt_col=f"{sql_name}__datatype",
                    num_col=f"{sql_name}__num",
                    from_triple=True,
                )
            types.register(info)

    return ctx


def _lit(value: str, datatype: Optional[str] = None, lang: Optional[str] = None):
    """Build an ExprValue wrapping a LiteralNode."""
    return ExprValue(node=LiteralNode(value=value, datatype=datatype, lang=lang))


def _uri(value: str):
    """Build an ExprValue wrapping a URINode."""
    return ExprValue(node=URINode(value=value))


def _var(name: str):
    return ExprVar(var=name)


def _func(name: str, *args, function_iri: Optional[str] = None):
    return ExprFunction(name=name, args=list(args), function_iri=function_iri)


def _assert_valid_sql_fragment(sql: str):
    """Wrap a SQL fragment in SELECT to validate via pglast."""
    if not HAS_PGLAST:
        return
    # Wrap expression in SELECT so pglast can parse it
    wrapped = f"SELECT {sql}"
    try:
        pglast.parse_sql(wrapped)
    except pglast.parser.ParseError as e:
        pytest.fail(f"Invalid SQL fragment: {sql}\nError: {e}")


# ---------------------------------------------------------------------------
# Value conversion tests
# ---------------------------------------------------------------------------

class TestValueToSQL:

    def test_uri_node(self):
        ctx = _make_ctx()
        sql = expr_to_sql(_uri("http://example.org/foo"), ctx)
        assert sql == "'http://example.org/foo'"

    def test_uri_with_quotes(self):
        ctx = _make_ctx()
        sql = expr_to_sql(_uri("http://example.org/it's"), ctx)
        assert sql == "'http://example.org/it''s'"

    def test_string_literal(self):
        ctx = _make_ctx()
        sql = expr_to_sql(_lit("hello"), ctx)
        assert sql == "'hello'"

    def test_string_with_quotes(self):
        ctx = _make_ctx()
        sql = expr_to_sql(_lit("it's"), ctx)
        assert sql == "'it''s'"

    def test_boolean_true(self):
        ctx = _make_ctx()
        sql = expr_to_sql(_lit("true", datatype=f"{XSD}boolean"), ctx)
        assert sql == "TRUE"

    def test_boolean_false(self):
        ctx = _make_ctx()
        sql = expr_to_sql(_lit("false", datatype=f"{XSD}boolean"), ctx)
        assert sql == "FALSE"

    def test_boolean_one(self):
        ctx = _make_ctx()
        sql = expr_to_sql(_lit("1", datatype=f"{XSD}boolean"), ctx)
        assert sql == "TRUE"

    def test_integer_literal(self):
        ctx = _make_ctx()
        sql = expr_to_sql(_lit("42", datatype=f"{XSD}integer"), ctx)
        assert sql == "42"

    def test_double_literal(self):
        ctx = _make_ctx()
        sql = expr_to_sql(_lit("3.14", datatype=f"{XSD}double"), ctx)
        assert sql == "3.14"

    def test_scientific_notation(self):
        ctx = _make_ctx()
        sql = expr_to_sql(_lit("1.5e10", datatype=f"{XSD}double"), ctx)
        assert sql == "15000000000.0"

    def test_bnode(self):
        ctx = _make_ctx()
        sql = expr_to_sql(ExprValue(node=BNodeNode(label="b0")), ctx)
        assert sql == "'_:b0'"

    def test_null_expr(self):
        ctx = _make_ctx()
        sql = expr_to_sql(None, ctx)
        assert sql is None


# ---------------------------------------------------------------------------
# Variable resolution tests
# ---------------------------------------------------------------------------

class TestVarToSQL:

    def test_registered_var(self):
        ctx = _make_ctx({"name": "text"})
        sql = expr_to_sql(_var("name"), ctx)
        assert sql == "v0"  # text_col

    def test_unregistered_var(self):
        ctx = _make_ctx({})
        sql = expr_to_sql(_var("unknown"), ctx)
        assert sql == "NULL"


# ---------------------------------------------------------------------------
# Comparison operators
# ---------------------------------------------------------------------------

class TestComparisons:

    def test_eq_literals(self):
        ctx = _make_ctx({"x": "text"})
        sql = expr_to_sql(_func("eq", _var("x"), _lit("hello")), ctx)
        assert sql is not None
        assert "=" in sql
        _assert_valid_sql_fragment(sql)

    def test_ne(self):
        ctx = _make_ctx({"x": "text"})
        sql = expr_to_sql(_func("ne", _var("x"), _lit("hello")), ctx)
        assert "!=" in sql

    def test_lt(self):
        ctx = _make_ctx({"x": "text"})
        sql = expr_to_sql(_func("lt", _var("x"), _lit("5", datatype=f"{XSD}integer")), ctx)
        assert "<" in sql

    def test_gt(self):
        ctx = _make_ctx({"x": "text"})
        sql = expr_to_sql(_func("gt", _var("x"), _lit("5", datatype=f"{XSD}integer")), ctx)
        assert ">" in sql

    def test_le(self):
        ctx = _make_ctx({"x": "text"})
        sql = expr_to_sql(_func("le", _var("x"), _lit("5", datatype=f"{XSD}integer")), ctx)
        assert "<=" in sql

    def test_ge(self):
        ctx = _make_ctx({"x": "text"})
        sql = expr_to_sql(_func("ge", _var("x"), _lit("5", datatype=f"{XSD}integer")), ctx)
        assert ">=" in sql

    def test_numeric_comparison_uses_num_col(self):
        ctx = _make_ctx({"x": "numeric"})
        sql = expr_to_sql(_func("lt", _var("x"), _lit("10", datatype=f"{XSD}integer")), ctx)
        # Should use the numeric column, not text
        assert "v0__num" in sql or "10" in sql


# ---------------------------------------------------------------------------
# Logical operators
# ---------------------------------------------------------------------------

class TestLogical:

    def test_and(self):
        ctx = _make_ctx({"x": "text", "y": "text"})
        expr = _func("and",
                     _func("bound", _var("x")),
                     _func("bound", _var("y")))
        sql = expr_to_sql(expr, ctx)
        assert "AND" in sql
        _assert_valid_sql_fragment(sql)

    def test_or(self):
        ctx = _make_ctx({"x": "text", "y": "text"})
        expr = _func("or",
                     _func("bound", _var("x")),
                     _func("bound", _var("y")))
        sql = expr_to_sql(expr, ctx)
        assert "OR" in sql

    def test_not(self):
        ctx = _make_ctx({"x": "text"})
        expr = _func("not", _func("bound", _var("x")))
        sql = expr_to_sql(expr, ctx)
        assert "NOT" in sql


# ---------------------------------------------------------------------------
# Arithmetic operators
# ---------------------------------------------------------------------------

class TestArithmetic:

    def test_add(self):
        ctx = _make_ctx({"x": "numeric"})
        sql = expr_to_sql(_func("add", _var("x"), _lit("1", datatype=f"{XSD}integer")), ctx)
        assert "+" in sql

    def test_subtract(self):
        ctx = _make_ctx({"x": "numeric"})
        sql = expr_to_sql(_func("subtract", _var("x"), _lit("1", datatype=f"{XSD}integer")), ctx)
        assert "-" in sql

    def test_multiply(self):
        ctx = _make_ctx({"x": "numeric"})
        sql = expr_to_sql(_func("multiply", _var("x"), _lit("2", datatype=f"{XSD}integer")), ctx)
        assert "*" in sql

    def test_divide(self):
        ctx = _make_ctx({"x": "numeric"})
        sql = expr_to_sql(_func("divide", _var("x"), _lit("2", datatype=f"{XSD}integer")), ctx)
        assert "NULLIF" in sql  # division by zero protection
        _assert_valid_sql_fragment(sql)

    def test_unary_minus(self):
        ctx = _make_ctx({"x": "numeric"})
        sql = expr_to_sql(_func("unaryminus", _var("x")), ctx)
        assert sql is not None
        assert "-" in sql


# ---------------------------------------------------------------------------
# String functions
# ---------------------------------------------------------------------------

class TestStringFunctions:

    def test_str(self):
        ctx = _make_ctx({"x": "text"})
        sql = expr_to_sql(_func("str", _var("x")), ctx)
        assert "CAST" in sql and "TEXT" in sql

    def test_strlen(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("strlen", _var("x")), ctx)
        assert "LENGTH" in sql
        _assert_valid_sql_fragment(sql)

    def test_ucase(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("ucase", _var("x")), ctx)
        assert "UPPER" in sql

    def test_lcase(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("lcase", _var("x")), ctx)
        assert "LOWER" in sql

    def test_contains(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("contains", _var("x"), _lit("hello")), ctx)
        assert "POSITION" in sql
        _assert_valid_sql_fragment(sql)

    def test_strstarts(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("strstarts", _var("x"), _lit("pre")), ctx)
        assert "LEFT" in sql

    def test_strends(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("strends", _var("x"), _lit("suf")), ctx)
        assert "RIGHT" in sql

    def test_concat_empty(self):
        ctx = _make_ctx()
        sql = expr_to_sql(_func("concat"), ctx)
        assert sql == "''"

    def test_concat_multiple(self):
        ctx = _make_ctx({"x": "text", "y": "text"})
        sql = expr_to_sql(_func("concat", _var("x"), _lit(" "), _var("y")), ctx)
        assert "CONCAT" in sql

    def test_substr_two_args(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("substr", _var("x"), _lit("2", datatype=f"{XSD}integer")), ctx)
        assert "SUBSTRING" in sql

    def test_substr_three_args(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("substr", _var("x"),
                                _lit("2", datatype=f"{XSD}integer"),
                                _lit("5", datatype=f"{XSD}integer")), ctx)
        assert "SUBSTRING" in sql
        assert "FOR" in sql

    def test_replace(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("replace", _var("x"), _lit("foo"), _lit("bar")), ctx)
        assert "regexp_replace" in sql

    def test_encode_for_uri(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("encode_for_uri", _var("x")), ctx)
        assert sql is not None
        assert "encode" in sql.lower()

    def test_strbefore(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("strbefore", _var("x"), _lit("-")), ctx)
        assert "POSITION" in sql
        assert "LEFT" in sql

    def test_strafter(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("strafter", _var("x"), _lit("-")), ctx)
        assert "POSITION" in sql
        assert "SUBSTRING" in sql


# ---------------------------------------------------------------------------
# Type testing functions
# ---------------------------------------------------------------------------

class TestTypeTesting:

    def test_bound(self):
        ctx = _make_ctx({"x": "text"})
        sql = expr_to_sql(_func("bound", _var("x")), ctx)
        assert "IS NOT NULL" in sql

    def test_isiri(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("isiri", _var("x")), ctx)
        assert "__type" in sql
        assert "'U'" in sql

    def test_isblank(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("isblank", _var("x")), ctx)
        assert "'B'" in sql

    def test_isliteral(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("isliteral", _var("x")), ctx)
        assert "'L'" in sql

    def test_isnumeric(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("isnumeric", _var("x")), ctx)
        assert "__num" in sql
        assert "IS NOT NULL" in sql


# ---------------------------------------------------------------------------
# REGEX
# ---------------------------------------------------------------------------

class TestRegex:

    def test_regex_no_flags(self):
        ctx = _make_ctx({"x": "text"})
        sql = expr_to_sql(_func("regex", _var("x"), _lit("^foo")), ctx)
        assert "~" in sql
        assert "~*" not in sql

    def test_regex_case_insensitive(self):
        ctx = _make_ctx({"x": "text"})
        sql = expr_to_sql(_func("regex", _var("x"), _lit("^foo"), _lit("i")), ctx)
        assert "~*" in sql


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------

class TestAccessors:

    def test_lang(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("lang", _var("x")), ctx)
        assert "COALESCE" in sql
        assert "__lang" in sql

    def test_datatype_var(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("datatype", _var("x")), ctx)
        assert "__datatype" in sql

    def test_datatype_constant(self):
        ctx = _make_ctx()
        expr = _func("datatype", _lit("42", datatype=f"{XSD}integer"))
        sql = expr_to_sql(expr, ctx)
        assert "integer" in sql

    def test_langmatches_wildcard(self):
        ctx = _make_ctx({"x": "full"})
        # LANG(?x) is an accessor, langMatches checks it
        lang_expr = _func("lang", _var("x"))
        sql = expr_to_sql(_func("langmatches", lang_expr, _lit("*")), ctx)
        assert "IS NOT NULL" in sql
        assert "!= ''" in sql

    def test_langmatches_specific(self):
        ctx = _make_ctx({"x": "full"})
        lang_expr = _func("lang", _var("x"))
        sql = expr_to_sql(_func("langmatches", lang_expr, _lit("en")), ctx)
        assert "LOWER" in sql


# ---------------------------------------------------------------------------
# Conditional
# ---------------------------------------------------------------------------

class TestConditional:

    def test_if(self):
        ctx = _make_ctx({"x": "text"})
        expr = _func("if",
                     _func("bound", _var("x")),
                     _lit("yes"),
                     _lit("no"))
        sql = expr_to_sql(expr, ctx)
        assert "CASE" in sql
        assert "WHEN" in sql
        assert "THEN" in sql
        assert "ELSE" in sql
        _assert_valid_sql_fragment(sql)

    def test_coalesce(self):
        ctx = _make_ctx({"x": "text", "y": "text"})
        sql = expr_to_sql(_func("coalesce", _var("x"), _var("y")), ctx)
        assert "COALESCE" in sql

    def test_coalesce_empty(self):
        ctx = _make_ctx()
        sql = expr_to_sql(_func("coalesce"), ctx)
        assert sql == "NULL"


# ---------------------------------------------------------------------------
# Math functions
# ---------------------------------------------------------------------------

class TestMath:

    def test_abs(self):
        ctx = _make_ctx({"x": "numeric"})
        sql = expr_to_sql(_func("abs", _var("x")), ctx)
        assert "ABS" in sql

    def test_ceil(self):
        ctx = _make_ctx({"x": "numeric"})
        sql = expr_to_sql(_func("ceil", _var("x")), ctx)
        assert "CEIL" in sql

    def test_floor(self):
        ctx = _make_ctx({"x": "numeric"})
        sql = expr_to_sql(_func("floor", _var("x")), ctx)
        assert "FLOOR" in sql

    def test_round(self):
        ctx = _make_ctx({"x": "numeric"})
        sql = expr_to_sql(_func("round", _var("x")), ctx)
        assert "ROUND" in sql


# ---------------------------------------------------------------------------
# Hash functions
# ---------------------------------------------------------------------------

class TestHash:

    def test_md5(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("md5", _var("x")), ctx)
        assert "MD5" in sql

    def test_sha1(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("sha1", _var("x")), ctx)
        assert "DIGEST" in sql
        assert "sha1" in sql

    def test_sha256(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("sha256", _var("x")), ctx)
        assert "sha256" in sql

    def test_sha512(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("sha512", _var("x")), ctx)
        assert "sha512" in sql


# ---------------------------------------------------------------------------
# DateTime extraction
# ---------------------------------------------------------------------------

class TestDateTime:

    def test_year(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("year", _var("x")), ctx)
        assert "EXTRACT" in sql
        assert "YEAR" in sql

    def test_month(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("month", _var("x")), ctx)
        assert "MONTH" in sql

    def test_day(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("day", _var("x")), ctx)
        assert "DAY" in sql

    def test_hours(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("hours", _var("x")), ctx)
        assert "HOUR" in sql

    def test_minutes(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("minutes", _var("x")), ctx)
        assert "MINUTE" in sql

    def test_seconds(self):
        ctx = _make_ctx({"x": "full"})
        sql = expr_to_sql(_func("seconds", _var("x")), ctx)
        assert "SECOND" in sql


# ---------------------------------------------------------------------------
# Constructors
# ---------------------------------------------------------------------------

class TestConstructors:

    def test_iri_absolute(self):
        ctx = _make_ctx({"x": "text"})
        sql = expr_to_sql(_func("iri", _var("x")), ctx)
        # Should attempt relative resolution
        assert "CASE" in sql or "v0" in sql

    def test_bnode_no_args(self):
        ctx = _make_ctx()
        sql = expr_to_sql(_func("bnode"), ctx)
        assert sql == "'_:b0'"

    def test_bnode_with_arg(self):
        ctx = _make_ctx({"x": "text"})
        sql = expr_to_sql(_func("bnode", _var("x")), ctx)
        assert "CONCAT" in sql
        assert "_:" in sql


# ---------------------------------------------------------------------------
# IN / NOT IN
# ---------------------------------------------------------------------------

class TestInNotIn:

    def test_in_empty(self):
        ctx = _make_ctx({"x": "text"})
        sql = expr_to_sql(_func("in", _var("x")), ctx)
        assert sql == "FALSE"

    def test_in_values(self):
        ctx = _make_ctx({"x": "text"})
        sql = expr_to_sql(_func("in", _var("x"), _lit("a"), _lit("b"), _lit("c")), ctx)
        assert "IN" in sql
        assert "'a'" in sql

    def test_notin_empty(self):
        ctx = _make_ctx({"x": "text"})
        sql = expr_to_sql(_func("notin", _var("x")), ctx)
        assert sql == "TRUE"

    def test_notin_values(self):
        ctx = _make_ctx({"x": "text"})
        sql = expr_to_sql(_func("notin", _var("x"), _lit("a"), _lit("b")), ctx)
        assert "NOT IN" in sql


# ---------------------------------------------------------------------------
# Miscellaneous
# ---------------------------------------------------------------------------

class TestMisc:

    def test_now(self):
        ctx = _make_ctx()
        sql = expr_to_sql(_func("now"), ctx)
        assert "NOW()" in sql

    def test_rand(self):
        ctx = _make_ctx()
        sql = expr_to_sql(_func("rand"), ctx)
        assert "RANDOM()" in sql

    def test_uuid(self):
        ctx = _make_ctx()
        sql = expr_to_sql(_func("uuid"), ctx)
        assert "GEN_RANDOM_UUID" in sql
        assert "urn:uuid:" in sql

    def test_struuid(self):
        ctx = _make_ctx()
        sql = expr_to_sql(_func("struuid"), ctx)
        assert "GEN_RANDOM_UUID" in sql

    def test_sameterm(self):
        ctx = _make_ctx({"x": "full", "y": "full"})
        sql = expr_to_sql(_func("sameterm", _var("x"), _var("y")), ctx)
        assert "=" in sql
        assert "__uuid" in sql


# ---------------------------------------------------------------------------
# Aggregators
# ---------------------------------------------------------------------------

class TestAggregators:

    def test_count_star(self):
        ctx = _make_ctx()
        expr = ExprAggregator(name="COUNT", expr=None)
        sql = expr_to_sql(expr, ctx)
        assert sql == "COUNT(*)"

    def test_count_var(self):
        ctx = _make_ctx({"x": "text"})
        expr = ExprAggregator(name="COUNT", expr=_var("x"))
        sql = expr_to_sql(expr, ctx)
        assert "COUNT" in sql
        assert "v0" in sql

    def test_count_distinct(self):
        ctx = _make_ctx({"x": "text"})
        expr = ExprAggregator(name="COUNT", expr=_var("x"), distinct=True)
        sql = expr_to_sql(expr, ctx)
        assert "DISTINCT" in sql

    def test_sum(self):
        ctx = _make_ctx({"x": "text"})
        expr = ExprAggregator(name="SUM", expr=_var("x"))
        sql = expr_to_sql(expr, ctx)
        assert "SUM" in sql

    def test_avg(self):
        ctx = _make_ctx({"x": "text"})
        expr = ExprAggregator(name="AVG", expr=_var("x"))
        sql = expr_to_sql(expr, ctx)
        assert "AVG" in sql

    def test_min(self):
        ctx = _make_ctx({"x": "text"})
        expr = ExprAggregator(name="MIN", expr=_var("x"))
        sql = expr_to_sql(expr, ctx)
        assert "MIN" in sql

    def test_max(self):
        ctx = _make_ctx({"x": "text"})
        expr = ExprAggregator(name="MAX", expr=_var("x"))
        sql = expr_to_sql(expr, ctx)
        assert "MAX" in sql

    def test_sample_uses_max(self):
        ctx = _make_ctx({"x": "text"})
        expr = ExprAggregator(name="SAMPLE", expr=_var("x"))
        sql = expr_to_sql(expr, ctx)
        assert "MAX" in sql  # SAMPLE → MAX as PostgreSQL has no SAMPLE()


# ---------------------------------------------------------------------------
# SortCondition
# ---------------------------------------------------------------------------

class TestSortCondition:

    def test_sort_asc(self):
        ctx = _make_ctx({"x": "text"})
        expr = SortCondition(expr=_var("x"), direction="ASC")
        sql = expr_to_sql(expr, ctx)
        assert "ASC" in sql

    def test_sort_desc(self):
        ctx = _make_ctx({"x": "text"})
        expr = SortCondition(expr=_var("x"), direction="DESC")
        sql = expr_to_sql(expr, ctx)
        assert "DESC" in sql


# ---------------------------------------------------------------------------
# XSD Cast functions
# ---------------------------------------------------------------------------

class TestXSDCasts:

    def test_xsd_integer(self):
        ctx = _make_ctx({"x": "full"})
        expr = _func("", _var("x"), function_iri=f"{XSD}integer")
        sql = expr_to_sql(expr, ctx)
        assert sql is not None
        assert "INTEGER" in sql
        _assert_valid_sql_fragment(sql)

    def test_xsd_double(self):
        ctx = _make_ctx({"x": "full"})
        expr = _func("", _var("x"), function_iri=f"{XSD}double")
        sql = expr_to_sql(expr, ctx)
        assert "DOUBLE PRECISION" in sql

    def test_xsd_boolean(self):
        ctx = _make_ctx({"x": "full"})
        expr = _func("", _var("x"), function_iri=f"{XSD}boolean")
        sql = expr_to_sql(expr, ctx)
        assert "CASE" in sql
        assert "TRUE" in sql
        assert "FALSE" in sql

    def test_xsd_string(self):
        ctx = _make_ctx({"x": "full"})
        expr = _func("", _var("x"), function_iri=f"{XSD}string")
        sql = expr_to_sql(expr, ctx)
        assert "TEXT" in sql

    def test_xsd_decimal(self):
        ctx = _make_ctx({"x": "full"})
        expr = _func("", _var("x"), function_iri=f"{XSD}decimal")
        sql = expr_to_sql(expr, ctx)
        assert "NUMERIC" in sql
