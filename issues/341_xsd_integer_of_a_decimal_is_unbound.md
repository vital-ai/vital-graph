# 341: `xsd:integer` of a decimal returns unbound instead of truncating

## Status: FIXED 2026-11-13 (uncommitted), with `340`; verified on the rebuilt vg test stack: unit 6,356 passed; W3C/DAWG conformance 1,532 passed (unchanged); API 31.

## Fix

Two changes in the XSD cast emitter (`emit_expressions`):

1. **A number truncates.** When the operand is known numeric at compile time
   (`_is_numeric_expr`: a decimal or double literal, arithmetic, a
   numeric-lane BIND, a cast), the integer branch adds
   `WHEN text ~ <number form> THEN CAST(TRUNC(CAST(text AS NUMERIC)) AS INTEGER)`.
   That covers the cases with no `__num` to read: a literal has none, and a
   numeric BIND keeps its value in the main column. A STRING still has to be
   in integer form, so `xsd:integer("5.0")` stays an error (unbound), as
   XPath says.
2. **A constant operand is cast through `::text`.** Testing (1) showed
   `xsd:integer("5.0")` did not return unbound, it FAILED THE QUERY:
   `invalid input syntax for type integer: "5.0"`. The emitter wrote
   `CASE WHEN '5.0' ~ … THEN CAST('5.0' AS INTEGER) …`, and PostgreSQL
   coerces a bare quoted literal while parsing, before the guard can act.
   `('5.0')::text` is an expression, and the planner drops the untaken branch
   without evaluating it (checked in psql). This affected every XSD cast of a
   string constant that is not in the target's form.

## Tests

- `tests/unit/sparql_sql/test_emit_expressions.py::TestXSDCasts`:
  `test_an_integer_cast_of_a_number_truncates` (decimal, double, arithmetic;
  fails on the old code), `test_an_integer_cast_of_a_string_needs_the_integer_form`,
  `test_a_cast_of_a_constant_string_is_typed_text`.
- `tests/api/test_values_numbers_api.py::test_an_integer_cast_of_a_number_truncates`:
  `5.0`→5, `"5.0"^^xsd:decimal`→5, `-2.7`→-2, `"1e3"^^xsd:double`→1000, a
  computed `2.5*2`→5, a VALUES `2.7`→2, `"5.0"`→unbound, `"7"`→7.

## Original report

Found while writing the API tests for `issues/337`.

## Reproduction (vg test stack)

| Query | Returned | SPARQL / XPath says |
|---|---|---|
| `SELECT ?y WHERE { BIND(xsd:integer(5.0) AS ?y) }` | `?y` unbound | `5` |
| `SELECT ?y WHERE { BIND(xsd:integer("5.0"^^xsd:decimal) AS ?y) }` | `?y` unbound | `5` |
| `SELECT ?y WHERE { BIND(2.5*2 AS ?x) BIND(xsd:integer(?x) AS ?y) }` | `?y` unbound (before `337` this was an error) | `5` |

SPARQL 1.1 §17.1 allows casting `xsd:decimal` to `xsd:integer`. XPath F&O
§19.1.2.2 defines it as truncation toward zero, so `5.0` becomes `5` and
`2.7` becomes `2`.

## Cause

`emit_expressions`, the XSD cast emitter's integer branch:

- it uses `TRUNC(num_col)` only when the operand has a `num_col`. A literal
  decimal and a BIND result reach it without one, which is worth checking: a
  BIND on the numeric lane should have `__num`;
- otherwise it accepts only `^[-+]?[0-9]+$` as a lexical form, so `"5.0"` is
  rejected and the result is NULL.

A decimal's lexical form (`[-+]?[0-9]*\.?[0-9]+`) is a valid input for an
integer cast once truncated. The branch should accept it and truncate.

## Fix sketch

In the INTEGER branch, accept the decimal lexical form and emit
`CAST(TRUNC(CAST(text AS NUMERIC)) AS INTEGER)`. Find out why a numeric-lane
BIND has no `num_col` at that point. Add unit and DAWG-style cases: `5.0`,
`-2.7`, `"2.7"^^xsd:decimal`, and `"1e3"^^xsd:double` (which must truncate the
double value, not reject the `e`).
