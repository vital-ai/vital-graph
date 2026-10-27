# 319 — A [NOT] EXISTS nested inside a [NOT] EXISTS body is uncorrelated

## Status: FIXED 2026-10-27, on the default path. Open until the vg test stack runs the full suite on the rebuilt image.

## Defect

On the default path, which production runs:

```sparql
SELECT ?e WHERE { ?e a ex:T .
  FILTER NOT EXISTS { ?e ex:name ?n FILTER NOT EXISTS { ?e ex:status ex:ACTIVE } } }
```

The inner negation should ask "is THIS entity ACTIVE". Instead it asked "is ANY entity ACTIVE". With one
ACTIVE entity anywhere in the space, the inner NOT EXISTS was false for every row, the body was empty and
every outer row passed. The EXISTS form fails the same way. The answers are silently wrong.

Cause: every EXISTS body's AliasGenerator used the prefix `ex_`. So the body's `?e` and the nested body's
`?e` were both named `ex_v0`, and the nested correlation was written

```sql
... ) AS ex__ex0 WHERE ex_v0__uuid = ex__ex0.ex_v0__uuid
```

The unqualified `ex_v0__uuid` resolves to the innermost scope, the nested sub-query itself. The condition
compared a column with itself, which is always true. PostgreSQL then ran the nested sub-link once, as an
InitPlan.

With the planner's switch on, each body already had a prefix of its own (`ex1_`, `ex2_`, ...), so the
planner path was not affected.

## How it was found

Reading the plan of the planner's `n06` shape (a NOT EXISTS nested in a NOT EXISTS) beside today's SQL:
today's ran the nested sub-link once (`loops=1`), where a correlated one was expected. Both answered the
same on that data, because every named entity there is ACTIVE.

## Fix

`planner_ext.exists_alias_prefix(depth)`: `ex_` for a body of the query, `exd<depth>_` for a body nested
in another body. `prepare_exists_subplans` passes its depth. The emit-time fallback derives the depth from
the enclosing generator's prefix.

## Test

`tests/integration/test_nested_not_exists_is_correlated.py` covers nested NOT EXISTS and nested EXISTS.
Both returned the wrong entities before the fix.
