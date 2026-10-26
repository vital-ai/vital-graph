# 318 — A BIND of arithmetic over a stored decimal, float or double reports xsd:integer

## Status: FIXED 2026-10-26, on the default path. Open until the vg test stack runs the full suite on the rebuilt image.

## Defect

On the default path, which production runs:

```sparql
SELECT ?w WHERE { ex:a ex:f ?v BIND(?v * 2 AS ?w) }      # ?v = "1.5"^^xsd:float
```

This answered `"3.0"^^xsd:integer`, a wrong datatype whose lexical form isn't even a valid
integer. A double or a decimal gave the same. `DATATYPE(?v * 2)` in the same query reported
xsd:float.

The cause: a computed value's `__datatype` companion came from `infer_expr_type`. For
arithmetic that is XSD promotion over operands known statically. An operand known only at run
time (a variable read from the term table) counts as the floor, xsd:integer. The inference has to
stay static, because it classifies (`is_numeric`, collations, GROUP BY). `DATATYPE()` uses
`promotion_datatype_sql`, which ranks per row. The companion never did.

## How it was found

The planner's contract check on a UNION branch computing `?v * 2` over `hasDoubleSlotValue`.
Both paths reported `127.2` typed xsd:integer, because they share the translator.

## Fix

`emit_extend.arith_datatype_companion`: an arithmetic BIND's `__datatype` column is the promoted
type per row, ranked recursively through nested arithmetic (`?v * 2 + 1`). Expressions whose
operands are all static keep the inferred answer. The planner's BIND and aggregate-result levels
call the same function.

## Test

`tests/integration/test_arithmetic_result_keeps_its_operands_datatype.py` covers:
- float, double and decimal times an integer;
- nested arithmetic;
- integer / integer as xsd:decimal;
- an all-constant expression.

The first four failed before the fix.
