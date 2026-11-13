# 341: `xsd:integer` of a decimal returns unbound instead of truncating

## Status: OPEN. Found 2026-11-12; not fixed.

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
