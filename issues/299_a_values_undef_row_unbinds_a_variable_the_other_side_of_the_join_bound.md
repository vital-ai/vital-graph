# 299 — A VALUES UNDEF row unbinds a variable the other side of the join bound

## Status: FIXED 2026-10-22, not yet released.

**Related:** `issues/293` (found while testing its VALUES guard rule against an
oracle), `issues/180` (the same projection rule for a UNION branch),
`issues/087` (VALUES boundness evidence).

## Found

```sparql
SELECT * WHERE {
  ?d :type :Decision .
  VALUES ?code { "a" UNDEF }
  ?r :of ?d ; :code ?code .
}
```

The UNDEF row matches every reason of every decision, as it should, but each
of those rows came back with `?code` **unbound**. SPARQL merges compatible
solutions so the bound value wins (§17.6: `mu1` unbound and `mu2` bound give
`mu2`'s value). pyoxigraph returns the code on every row. Same with
`VALUES (?d ?code) { (:d0 UNDEF) (UNDEF "b") }`, where the `(:d0 UNDEF)` row's
matches lost `?code`.

## Cause

`emit_join` projects a shared variable from the left side and COALESCEs it
with the right only when one side may leave it unbound: a direct child that
IS the VALUES table, a LEFT JOIN, or a variable `compute_scope` reports as
`maybe`. `compute_scope` does not model UNDEF: a VALUES block reports every
variable it lists as `defined`. With the block one level down
(`join(join(bgp, VALUES), bgp)`, which is how a VALUES in the middle of a
group compiles), no condition held, and the join took the left side's NULL:

    SELECT j2.v1 AS v1, ...      -- the VALUES side; j3.v1 never consulted

The join condition was right (the `IS NULL OR` guard is kept for a variable a
VALUES block binds), so the row count was right. Only the binding was lost:
a silent wrong answer, not an error.

## Fix

`emit_join._values_may_unbind(node, var)`: true when a VALUES block in the
subtree binds `var` to UNDEF on some row. A shared variable for which either
child answers true is COALESCEd like the other maybe-unbound cases.

## Tests

`tests/integration/test_values_join_guard_per_variable.py` runs five
VALUES/join shapes on the test stack and compares the full result multisets
with pyoxigraph. The two UNDEF shapes failed before the fix under both the old
and new 293 guard rules, and pass after it. DAWG conformance never reached
this (no test has UNDEF with the VALUES block below a join): 1,532 passed
before and after.
