"""
Tests for the Type Generation Module (sql_type_generation.py).

Tests type inference, TypeRegistry, ColumnInfo, and TypedExpr without
executing any SQL — pure unit tests on the type system.
"""

from __future__ import annotations

from ..jena_sparql.jena_types import (
    ExprVar, ExprValue, ExprFunction, ExprAggregator,
    LiteralNode, URINode,
)

from .sql_type_generation import (
    ColumnInfo, TypedExpr, TypeRegistry,
    infer_expr_type, sparql_error_guard,
    XSD, RDF_LANG_STRING,
)


# ---------------------------------------------------------------------------
# ColumnInfo tests
# ---------------------------------------------------------------------------

def test_column_info_from_triple():
    """ColumnInfo from a triple pattern has all companions."""
    reg = TypeRegistry()
    info = reg.register_from_triple("s", "q0.subject_uuid", "t0")
    assert info.sparql_name == "s"
    assert info.text_col == "t0.term_text"
    assert info.type_col == "t0.term_type"
    assert info.uuid_col == "q0.subject_uuid"
    assert info.lang_col == "t0.lang"
    assert info.dt_col == "t0.datatype_id"
    assert info.from_triple is True
    assert info.has_companions()
    comps = info.companion_cols()
    assert "s__type" in comps
    assert comps["s__type"] == "t0.term_type"
    print("  PASS test_column_info_from_triple")


def test_column_info_from_subquery():
    """ColumnInfo from a subquery references sub.var__suffix."""
    reg = TypeRegistry()
    info = reg.register_from_subquery("x", "sub")
    assert info.text_col == "sub.x"
    assert info.type_col == "sub.x__type"
    assert info.uuid_col == "sub.x__uuid"
    print("  PASS test_column_info_from_subquery")


# ---------------------------------------------------------------------------
# TypedExpr tests
# ---------------------------------------------------------------------------

def test_typed_expr_uri():
    """URI typed expression has type 'U'."""
    te = TypedExpr(sql="'http://example.org/'", sparql_type="uri")
    assert te.type_sql == "'U'"
    assert te.datatype_sql == "NULL"
    assert te.lang_sql == "NULL"
    print("  PASS test_typed_expr_uri")


def test_typed_expr_literal_with_datatype():
    """Literal with constant datatype."""
    te = TypedExpr(sql="42", sparql_type="literal",
                   datatype=f"{XSD}integer")
    assert te.type_sql == "'L'"
    assert te.datatype_sql == f"'{XSD}integer'"
    print("  PASS test_typed_expr_literal_with_datatype")


def test_typed_expr_sql_datatype():
    """Literal with SQL expression as datatype."""
    te = TypedExpr(sql="sub.x", sparql_type="literal",
                   datatype="sub.x__datatype", datatype_is_sql=True)
    assert te.datatype_sql == "sub.x__datatype"
    print("  PASS test_typed_expr_sql_datatype")


def test_typed_expr_to_column_info():
    """TypedExpr.to_column_info() creates correct ColumnInfo."""
    te = TypedExpr(sql="", sparql_type="literal",
                   datatype=f"{XSD}string", lang="en")
    info = te.to_column_info("label", "label_sql")
    assert info.sparql_name == "label"
    assert info.text_col == "label_sql"
    assert info.type_col == "'L'"
    assert info.dt_col == f"'{XSD}string'"
    assert info.lang_col == "'en'"
    assert info.from_triple is False
    print("  PASS test_typed_expr_to_column_info")


# ---------------------------------------------------------------------------
# TypeRegistry tests
# ---------------------------------------------------------------------------

def test_registry_register_and_get():
    reg = TypeRegistry()
    reg.register_from_triple("s", "q0.subject_uuid", "t0")
    assert reg.has("s")
    assert not reg.has("p")
    info = reg.get("s")
    assert info.sparql_name == "s"
    print("  PASS test_registry_register_and_get")


def test_registry_project_var():
    """project_var() generates value + companion columns."""
    reg = TypeRegistry()
    reg.register_from_triple("s", "q0.subject_uuid", "t0")
    cols = reg.project_var("s", "t0.term_text")
    assert len(cols) == 5  # value + 4 companions
    assert cols[0] == 't0.term_text AS s'
    assert any("s__type" in c for c in cols)
    assert any("s__uuid" in c for c in cols)
    assert any("s__lang" in c for c in cols)
    assert any("s__datatype" in c for c in cols)
    print("  PASS test_registry_project_var")


def test_registry_project_unknown_var():
    """project_var() for unknown var returns NULL."""
    reg = TypeRegistry()
    cols = reg.project_var("unknown", "NULL")
    assert cols == ["NULL AS unknown"]
    print("  PASS test_registry_project_unknown_var")


def test_registry_aggregate():
    """register_aggregate() sets correct datatype for COUNT/AVG."""
    reg = TypeRegistry()
    info_count = reg.register_aggregate("c", "COUNT")
    assert f"{XSD}integer" in info_count.dt_col

    info_avg = reg.register_aggregate("a", "AVG")
    assert f"{XSD}decimal" in info_avg.dt_col
    print("  PASS test_registry_aggregate")


def test_registry_child():
    """child_registry() inherits parent registrations."""
    reg = TypeRegistry()
    reg.register_from_triple("s", "q0.subject_uuid", "t0")
    child = reg.child_registry()
    assert child.has("s")
    child.register_from_triple("p", "q0.predicate_uuid", "t1")
    assert child.has("p")
    assert not reg.has("p")  # parent not affected
    print("  PASS test_registry_child")


def test_registry_extend():
    """register_extend() stores computed type info."""
    reg = TypeRegistry()
    te = TypedExpr(sql="", sparql_type="literal",
                   datatype=f"{XSD}string")
    info = reg.register_extend("label", te, "CONCAT(a, b)")
    assert info.type_col == "'L'"
    assert f"{XSD}string" in info.dt_col
    assert info.from_triple is False
    print("  PASS test_registry_extend")


# ---------------------------------------------------------------------------
# infer_expr_type tests
# ---------------------------------------------------------------------------

def test_infer_literal_constant():
    """Literal constant → datatype from node."""
    node = LiteralNode(value="42", datatype=f"{XSD}integer")
    expr = ExprValue(node=node)
    reg = TypeRegistry()
    te = infer_expr_type(expr, reg)
    assert te.sparql_type == "literal"
    assert te.datatype == f"{XSD}integer"
    assert te.datatype_is_sql is False
    print("  PASS test_infer_literal_constant")


def test_infer_uri_constructor():
    """IRI() → uri type."""
    expr = ExprFunction(name="iri", args=[ExprVar(var="x")])
    reg = TypeRegistry()
    te = infer_expr_type(expr, reg)
    assert te.sparql_type == "uri"
    print("  PASS test_infer_uri_constructor")


def test_infer_arithmetic():
    """Division → xsd:decimal, addition → propagate or integer."""
    reg = TypeRegistry()
    div = ExprFunction(name="divide", args=[
        ExprVar(var="a"), ExprVar(var="b")
    ])
    te = infer_expr_type(div, reg)
    assert te.datatype == f"{XSD}decimal"

    add = ExprFunction(name="add", args=[
        ExprVar(var="a"), ExprVar(var="b")
    ])
    te2 = infer_expr_type(add, reg)
    assert te2.datatype == f"{XSD}integer"
    print("  PASS test_infer_arithmetic")


def test_infer_count():
    """COUNT aggregate → xsd:integer."""
    expr = ExprAggregator(name="COUNT", distinct=False, expr=None)
    reg = TypeRegistry()
    te = infer_expr_type(expr, reg)
    assert te.datatype == f"{XSD}integer"
    print("  PASS test_infer_count")


def test_infer_avg():
    """AVG aggregate → xsd:decimal."""
    expr = ExprAggregator(name="AVG", distinct=False,
                           expr=ExprVar(var="x"))
    reg = TypeRegistry()
    te = infer_expr_type(expr, reg)
    assert te.datatype == f"{XSD}decimal"
    print("  PASS test_infer_avg")


def test_infer_strlen():
    """STRLEN → xsd:integer."""
    expr = ExprFunction(name="strlen", args=[ExprVar(var="x")])
    reg = TypeRegistry()
    te = infer_expr_type(expr, reg)
    assert te.datatype == f"{XSD}integer"
    print("  PASS test_infer_strlen")


def test_infer_str_function():
    """str() → xsd:string."""
    expr = ExprFunction(name="str", args=[ExprVar(var="x")])
    reg = TypeRegistry()
    te = infer_expr_type(expr, reg)
    assert te.datatype == f"{XSD}string"
    print("  PASS test_infer_str_function")


def test_infer_lang_preserving():
    """LCASE on a var with lang → preserves lang."""
    reg = TypeRegistry()
    reg.register(ColumnInfo(
        sparql_name="x",
        text_col="t0.term_text",
        type_col="t0.term_type",
        lang_col="t0.lang",
        dt_col="t0.datatype",
    ))
    expr = ExprFunction(name="lcase", args=[ExprVar(var="x")])
    te = infer_expr_type(expr, reg)
    assert te.lang == "t0.lang"
    assert te.lang_is_sql is True
    assert te.datatype == "t0.datatype"
    assert te.datatype_is_sql is True
    print("  PASS test_infer_lang_preserving")


def test_infer_strlang():
    """STRLANG(expr, 'en') → rdf:langString with lang='en'."""
    expr = ExprFunction(name="strlang", args=[
        ExprVar(var="x"),
        ExprValue(node=LiteralNode(value="en")),
    ])
    reg = TypeRegistry()
    te = infer_expr_type(expr, reg)
    assert te.datatype == RDF_LANG_STRING
    assert te.lang == "en"
    print("  PASS test_infer_strlang")


def test_infer_if():
    """IF(cond, then, else) → datatype from branches."""
    expr = ExprFunction(name="if", args=[
        ExprVar(var="cond"),
        ExprValue(node=LiteralNode(value="42", datatype=f"{XSD}integer")),
        ExprValue(node=LiteralNode(value="0", datatype=f"{XSD}integer")),
    ])
    reg = TypeRegistry()
    te = infer_expr_type(expr, reg)
    assert te.datatype == f"{XSD}integer"
    print("  PASS test_infer_if")


def test_infer_bound():
    """BOUND(?x) → xsd:boolean."""
    expr = ExprFunction(name="bound", args=[ExprVar(var="x")])
    reg = TypeRegistry()
    te = infer_expr_type(expr, reg)
    assert te.datatype == f"{XSD}boolean"
    print("  PASS test_infer_bound")


def test_infer_group_concat():
    """GROUP_CONCAT → xsd:string."""
    expr = ExprAggregator(name="GROUP_CONCAT", distinct=False,
                           expr=ExprVar(var="x"), separator=", ")
    reg = TypeRegistry()
    te = infer_expr_type(expr, reg)
    assert te.datatype == f"{XSD}string"
    print("  PASS test_infer_group_concat")


def test_infer_var_from_registry():
    """Variable reference inherits type from registry."""
    reg = TypeRegistry()
    reg.register(ColumnInfo(
        sparql_name="x",
        text_col="t0.term_text",
        dt_col="t0.datatype",
        lang_col="t0.lang",
    ))
    te = infer_expr_type(ExprVar(var="x"), reg)
    assert te.datatype == "t0.datatype"
    assert te.datatype_is_sql is True
    assert te.lang == "t0.lang"
    assert te.lang_is_sql is True
    print("  PASS test_infer_var_from_registry")


# ---------------------------------------------------------------------------
# sparql_error_guard tests
# ---------------------------------------------------------------------------

def test_error_guard_no_error():
    """No guard when can_error is False."""
    te = TypedExpr(sql="42", can_error=False)
    result = sparql_error_guard("42", te)
    assert result == "42"
    print("  PASS test_error_guard_no_error")


def test_error_guard_with_error():
    """Guard wraps expression when can_error is True."""
    te = TypedExpr(sql="1/0", can_error=True)
    result = sparql_error_guard("1/0", te)
    assert "CASE WHEN" in result
    assert "NULL" in result
    print("  PASS test_error_guard_with_error")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

ALL_TESTS = [
    test_column_info_from_triple,
    test_column_info_from_subquery,
    test_typed_expr_uri,
    test_typed_expr_literal_with_datatype,
    test_typed_expr_sql_datatype,
    test_typed_expr_to_column_info,
    test_registry_register_and_get,
    test_registry_project_var,
    test_registry_project_unknown_var,
    test_registry_aggregate,
    test_registry_child,
    test_registry_extend,
    test_infer_literal_constant,
    test_infer_uri_constructor,
    test_infer_arithmetic,
    test_infer_count,
    test_infer_avg,
    test_infer_strlen,
    test_infer_str_function,
    test_infer_lang_preserving,
    test_infer_strlang,
    test_infer_if,
    test_infer_bound,
    test_infer_group_concat,
    test_infer_var_from_registry,
    test_error_guard_no_error,
    test_error_guard_with_error,
]


def run_all():
    """Run all type generation tests."""
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
    print(f"\nType Generation Tests: {passed}/{total} passed"
          f" ({failed} failed, {errors} errors)")
    return failed == 0 and errors == 0


if __name__ == "__main__":
    import sys
    ok = run_all()
    sys.exit(0 if ok else 1)
