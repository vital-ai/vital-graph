# Boolean Comparisons Use the Text Lane — `operator does not exist: text <> boolean`

## Status: FIXED 2026-08-08

Any FILTER comparing a variable to a boolean literal generated SQL that
PostgreSQL refuses to plan:

```
WHERE (v8 != TRUE)
  ERROR: operator does not exist: text <> boolean
```

Not a performance problem — the query cannot run at all.

## Root cause

`emit_expressions._cmp_pair` chooses a typed lane when either side is numeric:

```python
if left_num or right_num:
    return _numeric_arg(left, ctx), _numeric_arg(right, ctx)
```

There was no boolean equivalent, so a boolean comparison fell through to the
default lane, which is `term_text`. The typed lane exists and is already emitted
alongside every variable —

```sql
CASE WHEN datatype_id = 2 AND term_text IN ('true','false','1','0')
     THEN (term_text = 'true') END AS v0__bool
```

— it simply was not selected.

Fixed by adding `_is_boolean_expr` / `_boolean_arg`, mirroring the numeric pair.
`_is_boolean_expr` trusts `typed_lane == "bool"` for variables rather than the
mere presence of `bool_col`, for the same reason `_is_numeric_expr` does: the
column is a CASE that yields NULL for non-boolean terms, so its existence proves
nothing about the variable.

## Why it survived this long

`eq` on a boolean slot works, which made the whole area look healthy. It works
for a reason that does not generalise: the builder turns equality into a **triple
pattern** —

```sparql
?slot haley:hasBooleanSlotValue true .
```

— matched on term identity, where no lane is involved. Every other comparator
becomes a FILTER:

```sparql
?slot haley:hasBooleanSlotValue ?val . FILTER(?val != true)
```

and every one of those hit the defect. So `ne`, `gt`, `lt`, `lte` on booleans
were all broken, and nothing exercised any of them — `eq` and `gte` are the only
two comparators with any test coverage at all, on any slot class.

The builder's SPARQL was correct throughout (`FILTER(?val != true)`, lowercase
literal). The defect was entirely in SQL emission.

## Found by

`scripts/perf_shape_matrix.py`, on its first run — the first thing to sweep
comparators rather than fix one. It reported the cell as `no-plan`, which is the
class reserved for "generation or planning failed".

## Regression

2,280 tests across performance, unit and conformance: 0 failures.
The matrix now reports 0 `no-plan` cells.

## Related

- `scripts/perf_shape_matrix.py` — the sweep
- `issues/050` — the fixture gap the same sweep exposed
