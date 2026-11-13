# 337: ORDER BY a `vg:fuzzyMatch` score fails

## Status: FIXED 2026-11-12 (uncommitted), verified on the vg test stack: unit 6,343 passed; W3C/DAWG conformance 1,532 passed; fuzzy integration 14; API 37 (new + mappings) and 73 (auto-sync, kgqueries, text and geo search).

Reported 2026-11-12 by a client service's session while building a
funder-name index on the local dev server (a dedicated funder space, 1,748
entities). It worked around the bug by ranking in Python.

## The defect

```sparql
BIND(vg:fuzzyMatch(?n, "FUNDING METRICS LLC", 50) AS ?score)
FILTER(?score > 0)
} ORDER BY DESC(?score)
```

- `ORDER BY DESC(?score)` failed: `collations are not supported by type numeric`.
- `ORDER BY DESC(xsd:double(?score))` failed: `operator does not exist: numeric ~ unknown`.
- With no ORDER BY, the same query worked (14 rows, scores like 94.6).

It does not depend on the query's shape (extra patterns, VALUES).

## Cause: two defects

**1. fuzzyMatch was not typed as a number.**
`sql_type_generation.infer_expr_type` types the vg score functions as
`xsd:double` when they are bound with BIND. The list included vectorSimilarity,
vectorNearby, the multi-vector pair, textSearch, hybridSearch, geoDistance and
trigramSimilarity, but **not fuzzyMatch**. So `?score` was registered as an
untyped literal, while its SQL column is the numeric `CASE` that the fuzzy
resolver substitutes. `emit_order.variable_order_parts` saw a text variable
and wrapped that column in `COLLATE "C"`, which PostgreSQL refuses on numeric.

`FILTER(?score > 0)` worked because the expression path
(`emit_expressions._is_numeric_expr`) did list `VG_FUZZY_MATCH`. The two lists
had drifted apart.

**2. Casting any computed number failed.** This is the `xsd:double` error, and
it is wider than fuzzy matching. A BIND on the numeric, boolean or datetime
lane holds its value itself in its main column, and its `text_col` names that
same column. The XSD cast emitter's lexical branches apply `~` (a regex) and
`CAST` to `text_col` as if it were text. PostgreSQL type-checks every CASE
branch, taken or not, so the statement failed. Before the fix, all of these
failed on the test stack and on the dev server:

- `BIND(1+1 AS ?x) BIND(xsd:double(?x) AS ?y)`: `integer ~ unknown`;
- `BIND(2.5*2 AS ?x) BIND(xsd:integer(?x) AS ?y)`: `numeric ~ unknown`;
- `ORDER BY DESC(xsd:double(?x))` over a computed `?x`.

Fixing 1 alone did not fix this; the API test caught it.

`test_scripts/test_fuzzy_sparql_e2e.py` uses the same `ORDER BY DESC(?score)`.
It is a script, not part of a suite, so nothing ran it.

## Fix

1. `VG_FUZZY_MATCH` added to the BIND typing list.
2. `emit_expressions._cast_operand_is_text`: a cast whose operand is not
   already text (a variable on a typed lane, or any computed expression)
   renders it with `::text` before the lexical branches. On a text column that
   is a no-op, and stored terms are unchanged. The typed `num_col`/`bool_col`
   branches still take precedence where they exist.

## Found alongside, not fixed here

- `issues/340`: numbers bound with `VALUES` do not compute.
- `issues/341`: `xsd:integer` of a decimal returns unbound.

## Tests

- `tests/unit/sparql_sql/test_sql_type_generation.py::test_a_vg_score_function_infers_a_numeric_lane`,
  parametrised over every vg score function, so the next one left out fails.
  On the old code it fails for `fuzzyMatch` only.
- `tests/unit/sparql_sql/test_emit_expressions.py::TestXSDCasts`:
  `test_a_cast_of_a_computed_number_matches_text_not_the_number` (double,
  decimal, integer, float, dateTime; all 5 fail on the old emitter) and
  `test_a_cast_of_a_stored_term_keeps_its_text_column`.
- `tests/api/test_fuzzy_match_api.py`:
  - `test_a_fuzzy_score_can_be_ordered`: `ORDER BY DESC(?score)`,
    `ORDER BY DESC(xsd:double(?score))` and `ORDER BY ?score`, with the rows
    checked to be in order;
  - `test_a_computed_number_can_be_cast`: five cast shapes without fuzzy.
