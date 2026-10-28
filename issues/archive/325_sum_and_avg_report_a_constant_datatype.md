# 325 — SUM and AVG report a constant datatype, not their inputs' promoted type

## Status: RESOLVED 2026-10-27. Verified on the vg test stack rebuilt for the fix: unit, DAWG conformance, integration and API suites, 0 failures.

## Defect

`SUM(?v)` reported `xsd:integer` and `AVG(?v)` `xsd:decimal` whatever the group held
(`sql_type_generation._agg_datatype`: constants only, "aggregate results live after GROUP BY").
SPARQL applies XSD numeric promotion: a group holding a double sums to a double.

    SELECT ?k (SUM(?v) AS ?a) … GROUP BY ?k      # 10 + 1.0E1 + 99
    → "119"^^xsd:integer, where SPARQL gives "119.0E0"^^xsd:double

The value was right; its type was wrong, which changes `DATATYPE(?a)`, a typed comparison
downstream, and how a client renders it. Found by the differential sweep against Oxigraph
(`test_scripts_internal/sweep`), as issues/324.

## Fix

`emit_group.aggregate_columns` (the one translation of an aggregate, both paths): SUM / AVG of a
variable emits its `__datatype` per group, the highest promotion rank among the inputs'
datatypes (integer < decimal < float < double; AVG at least decimal), and registers it as the
result's datatype. The value keeps its numeric lane: `TypedExpr.numeric_hint` carries a
variable's numeric lane through `infer_expr_type` when its datatype is a column, or the
projection re-registered `?a` with no lane and no `__num` (ordering by it failed:
"collations are not supported by type numeric").

## Test

`tests/integration/test_sum_avg_promote_their_datatype.py`: SUM and AVG over integer, decimal and
double groups, and a HAVING / ORDER BY over the sum.
