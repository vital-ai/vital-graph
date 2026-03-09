"""
Tests for the Type Binding Module (sql_type_binding.py).
"""

from __future__ import annotations

import decimal

from .sql_type_binding import (
    SparqlBinding, sql_to_sparql_binding, sql_row_to_bindings,
    normalize_numeric,
    XSD_INTEGER, XSD_DECIMAL, XSD_DOUBLE, XSD_BOOLEAN, XSD_STRING,
    RDF_LANG_STRING,
)


def test_binding_uri_from_companion():
    """URI detected from __type='U' companion."""
    row = {"v0": "http://example.org/s", "v0__type": "U"}
    b = sql_to_sparql_binding("v0", "http://example.org/s", row)
    assert b is not None
    assert b.type == "uri"
    assert b.value == "http://example.org/s"
    print("  PASS test_binding_uri_from_companion")


def test_binding_literal_with_lang():
    """Literal with language tag from companion columns."""
    row = {"v0": "hello", "v0__type": "L", "v0__lang": "en", "v0__datatype": ""}
    b = sql_to_sparql_binding("v0", "hello", row)
    assert b.type == "literal"
    assert b.lang == "en"
    assert b.datatype == RDF_LANG_STRING
    print("  PASS test_binding_literal_with_lang")


def test_binding_literal_with_datatype():
    """Literal with explicit datatype."""
    row = {"v0": "42", "v0__type": "L", "v0__lang": "", "v0__datatype": XSD_INTEGER}
    b = sql_to_sparql_binding("v0", "42", row)
    assert b.type == "literal"
    assert b.datatype == XSD_INTEGER
    assert b.lang is None
    print("  PASS test_binding_literal_with_datatype")


def test_binding_strips_xsd_string():
    """xsd:string is stripped (RDF 1.1 default)."""
    row = {"v0": "hello", "v0__type": "L", "v0__lang": "", "v0__datatype": XSD_STRING}
    b = sql_to_sparql_binding("v0", "hello", row)
    assert b.datatype is None
    print("  PASS test_binding_strips_xsd_string")


def test_binding_bnode():
    """Blank node from companion."""
    row = {"v0": "b0", "v0__type": "B"}
    b = sql_to_sparql_binding("v0", "b0", row)
    assert b.type == "bnode"
    print("  PASS test_binding_bnode")


def test_binding_null_is_unbound():
    """NULL value → None (unbound)."""
    row = {"v0": None}
    b = sql_to_sparql_binding("v0", None, row)
    assert b is None
    print("  PASS test_binding_null_is_unbound")


def test_binding_python_int():
    """Python int (no companions) → xsd:integer."""
    row = {"v0": 42}
    b = sql_to_sparql_binding("v0", 42, row)
    assert b.type == "literal"
    assert b.value == "42"
    assert b.datatype == XSD_INTEGER
    print("  PASS test_binding_python_int")


def test_binding_python_decimal():
    """Python Decimal → xsd:integer or xsd:decimal."""
    row = {"v0": decimal.Decimal("3.14")}
    b = sql_to_sparql_binding("v0", decimal.Decimal("3.14"), row)
    assert b.type == "literal"
    assert b.datatype == XSD_DECIMAL

    row2 = {"v0": decimal.Decimal("7")}
    b2 = sql_to_sparql_binding("v0", decimal.Decimal("7"), row2)
    assert b2.datatype == XSD_INTEGER
    assert b2.value == "7"
    print("  PASS test_binding_python_decimal")


def test_binding_python_bool():
    """Python bool → xsd:boolean with lowercase."""
    row = {"v0": True}
    b = sql_to_sparql_binding("v0", True, row)
    assert b.value == "true"
    assert b.datatype == XSD_BOOLEAN
    print("  PASS test_binding_python_bool")


def test_binding_uri_heuristic():
    """URI heuristic for strings without companions."""
    row = {"v0": "http://example.org/thing"}
    b = sql_to_sparql_binding("v0", "http://example.org/thing", row)
    assert b.type == "uri"
    print("  PASS test_binding_uri_heuristic")


def test_binding_plain_string():
    """Plain string without companions → literal."""
    row = {"v0": "hello world"}
    b = sql_to_sparql_binding("v0", "hello world", row)
    assert b.type == "literal"
    assert b.datatype is None
    print("  PASS test_binding_plain_string")


def test_sql_row_to_bindings():
    """Full row conversion with var_map."""
    row = {
        "v0": "http://example.org/s", "v0__type": "U",
        "v0__uuid": "abc", "v0__lang": "", "v0__datatype": "",
        "v1": "42", "v1__type": "L",
        "v1__uuid": "def", "v1__lang": "", "v1__datatype": XSD_INTEGER,
    }
    var_map = {"v0": "s", "v1": "count"}
    bindings = sql_row_to_bindings(row, var_map, ["s", "count"])
    assert "s" in bindings
    assert bindings["s"].type == "uri"
    assert "count" in bindings
    assert bindings["count"].datatype == XSD_INTEGER
    print("  PASS test_sql_row_to_bindings")


def test_normalize_numeric_integer():
    assert normalize_numeric(42) == "42"
    assert normalize_numeric(decimal.Decimal("7.0"), XSD_INTEGER) == "7"
    print("  PASS test_normalize_numeric_integer")


def test_normalize_numeric_decimal():
    assert normalize_numeric(decimal.Decimal("3.14")) == "3.14"
    print("  PASS test_normalize_numeric_decimal")


def test_normalize_numeric_bool():
    assert normalize_numeric(True) == "true"
    assert normalize_numeric(False) == "false"
    print("  PASS test_normalize_numeric_bool")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

ALL_TESTS = [
    test_binding_uri_from_companion,
    test_binding_literal_with_lang,
    test_binding_literal_with_datatype,
    test_binding_strips_xsd_string,
    test_binding_bnode,
    test_binding_null_is_unbound,
    test_binding_python_int,
    test_binding_python_decimal,
    test_binding_python_bool,
    test_binding_uri_heuristic,
    test_binding_plain_string,
    test_sql_row_to_bindings,
    test_normalize_numeric_integer,
    test_normalize_numeric_decimal,
    test_normalize_numeric_bool,
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
    print(f"\nType Binding Tests: {passed}/{total} passed"
          f" ({failed} failed, {errors} errors)")
    return failed == 0 and errors == 0


if __name__ == "__main__":
    import sys
    ok = run_all()
    sys.exit(0 if ok else 1)
