#!/usr/bin/env python3
"""Unit test for vg:fuzzyMatch SPARQL function implementation."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.db.sparql_sql.vg_functions import (
    VG_ALL_FUNCTIONS, VG_FUZZY_MATCH, VG_FUZZY_FUNCTIONS,
    is_vg_function, is_vg_fuzzy_function, extract_fuzzy_match_args, fuzzy_match_sql,
    FuzzyMatchArgs,
)
from vitalgraph.db.jena_sparql.jena_types import ExprFunction, ExprVar, ExprValue, LiteralNode


def make_expr(search_name, min_score=None):
    args = [
        ExprVar(var="entity"),
        ExprValue(node=LiteralNode(value=search_name, datatype=None, lang=None)),
    ]
    if min_score is not None:
        args.append(ExprValue(node=LiteralNode(value=str(min_score), datatype=None, lang=None)))
    return ExprFunction(name="fuzzyMatch", function_iri=VG_FUZZY_MATCH, args=args)


def test_detection():
    expr = make_expr("Apple Inc", 40)
    assert is_vg_function(expr), "is_vg_function should detect fuzzyMatch"
    assert is_vg_fuzzy_function(expr), "is_vg_fuzzy_function should detect fuzzyMatch"
    assert VG_FUZZY_MATCH in VG_ALL_FUNCTIONS
    assert VG_FUZZY_MATCH in VG_FUZZY_FUNCTIONS
    print("test_detection PASSED")


def test_extract_3_args():
    expr = make_expr("Apple Inc", 40)
    args = extract_fuzzy_match_args(expr)
    assert args is not None
    assert args.entity_var == "entity"
    assert args.search_name == "Apple Inc"
    assert args.min_score == 40.0
    print("test_extract_3_args PASSED")


def test_extract_2_args_default_threshold():
    expr = make_expr("Google LLC")
    args = extract_fuzzy_match_args(expr)
    assert args is not None
    assert args.entity_var == "entity"
    assert args.search_name == "Google LLC"
    assert args.min_score == 50.0, f"Expected 50.0 default, got {args.min_score}"
    print("test_extract_2_args_default_threshold PASSED")


def test_extract_invalid_args():
    # Too many args
    expr = ExprFunction(name="fuzzyMatch", function_iri=VG_FUZZY_MATCH, args=[
        ExprVar(var="entity"),
        ExprValue(node=LiteralNode(value="x", datatype=None, lang=None)),
        ExprValue(node=LiteralNode(value="50", datatype=None, lang=None)),
        ExprValue(node=LiteralNode(value="extra", datatype=None, lang=None)),
    ])
    assert extract_fuzzy_match_args(expr) is None
    print("test_extract_invalid_args PASSED")


def test_sql_generation():
    """Test that fuzzy_match_sql generates valid SQL structure."""

    class FakeTypeInfo:
        uuid_col = "v0__uuid"
        typed_lane = None

    class FakeCtx:
        space_id = "test_space"
        types = {"entity": FakeTypeInfo()}

    expr = make_expr("Acme Corp", 60)
    sql = fuzzy_match_sql(expr, FakeCtx())
    assert sql is not None, "fuzzy_match_sql returned None"
    assert "similarity" in sql, "SQL should contain similarity()"
    assert "test_space_term" in sql, "SQL should reference term table"
    assert "test_space_rdf_quad" in sql, "SQL should reference quad table"
    assert "Acme Corp" in sql, "SQL should contain search name"
    assert "0.6000" in sql, "SQL should contain threshold (60/100 = 0.6)"
    assert "v0__uuid" in sql, "SQL should reference uuid column"
    assert "hasName" in sql, "SQL should filter by hasName predicate"
    print("test_sql_generation PASSED")
    print(f"  Generated SQL: {sql[:200]}...")


def test_sql_escaping():
    """Test that single quotes in search name are escaped."""

    class FakeTypeInfo:
        uuid_col = "v0__uuid"
        typed_lane = None

    class FakeCtx:
        space_id = "test_space"
        types = {"entity": FakeTypeInfo()}

    expr = make_expr("O'Brien & Sons", 50)
    sql = fuzzy_match_sql(expr, FakeCtx())
    assert sql is not None
    assert "O''Brien" in sql, "Single quotes should be escaped"
    print("test_sql_escaping PASSED")


if __name__ == "__main__":
    test_detection()
    test_extract_3_args()
    test_extract_2_args_default_threshold()
    test_extract_invalid_args()
    test_sql_generation()
    test_sql_escaping()
    print("\nALL TESTS PASSED")
