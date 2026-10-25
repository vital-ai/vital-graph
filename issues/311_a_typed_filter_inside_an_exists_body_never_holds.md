# 311 — A numeric, boolean or date FILTER inside an EXISTS / NOT EXISTS body never holds

## Status: FIXED, 2026-10-25, on the default path. Open until the vg test stack runs the full suite on the rebuilt image.

## Defect

Wrong answers, on the default (non-planner) path that production runs. Silent: the query
succeeds.

`emit_expressions` builds the EXISTS body's `EmitContext` directly, not through `ctx.child()`.
It passed the aliases, types and graph lock, but not the space's `datatype_cache`. Without the
cache, `dt_ids_for_uris` returns `NULL`, so every typed column of a body term row was:

```sql
CASE WHEN t_ex_v1.datatype_id IN (NULL) AND ... THEN CAST(t_ex_v1.term_text AS NUMERIC) END AS ex_v1__num
```

`__num`, `__bool`, `__dt` and `__datatype` were NULL for every term in the body. Effects:
- A numeric comparison (`FILTER(?v >= 50.0)`) or a date comparison never held. EXISTS was
  always false; NOT EXISTS was always true.
- A boolean's effective value fell back to its text, which is non-empty, so `FILTER(?b)` was
  true for `false` too.
- String functions were unaffected: they read `term_text`.

## How it was found

The planner's contract check on lead 10k (`corpus/negation_shapes/n09`) compared the planner
against today's SQL:

```sparql
SELECT (COUNT(*) AS ?c) WHERE { ?s haley:hasKGSlotType <urn:acme:kg:slot:MQLRating> .
  FILTER NOT EXISTS { ?s haley:hasDoubleSlotValue ?v FILTER(?v >= 50.0) } }
```

- Today's SQL: 10,000.
- The planner: 5,024.
- A direct SQL count: 4,976 of the 10,000 slots have a value of at least 50, so 5,024 is
  correct.

The planner evaluates body FILTERs with the outer context's datatype ids (`_value_level`), so it
was right.

The W3C suite did not catch it. Its EXISTS / negation tests filter on IRIs and plain
comparisons of variables, not on typed literals inside a body.

## Fix

`emit_expressions.py`: the body context gets `datatype_cache=ctx.datatype_cache`. It was the
only `EmitContext` built without it: `EmitContext.child()` passes it, and so does the
generator's own construction.

## Test

`tests/integration/test_exists_body_filter_reads_typed_values.py`:
- NOT EXISTS / EXISTS with a numeric body filter;
- a boolean body filter;
- a dateTime body filter;
- the same comparison outside a body, as the control.

The first four failed before the fix and pass after. Run in-process against the planner stack
(PostgreSQL 5434, sidecar 7072).

## Reach

Any query sending `FILTER [NOT] EXISTS { ... FILTER(<numeric | boolean | date comparison>) }`.
KGQuery's frame and slot criteria with negation would be the likely senders. Whether any
production query has this shape is unchecked. A production call-count grep for `EXISTS` with
a typed comparison inside would answer it.
