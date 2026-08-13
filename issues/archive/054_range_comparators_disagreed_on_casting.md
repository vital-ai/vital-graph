# 054 — the four range comparators disagreed about casting, and `gt` paid for it

**Status:** fixed (builder unified); the underlying data-typing assumption is documented below and still stands.

## What happened

`gt` on a double slot timed out at 60s. `gte` on the *same slot, same threshold,
same fixture* returned in 505ms. `lt` and `lte` returned in ~190ms.

The difference was one cast:

    gt    FILTER(xsd:double(?val_0_0_0) > 65.0)
    gte   FILTER(?val_0_0_0 >= 65.0)
    lt    FILTER(?val_0_0_0 < 65.0)
    lte   FILTER(?val_0_0_0 <= 65.0)

`filter_pushdown._try_numeric_filter` requires a bare `ExprVar` on one side. A
cast wraps the variable in an `ExprFunction`, so the push-down declined, the
`num_val` semi-join was never emitted, and the query fell back to scanning.

## The part worth keeping

`gt` was the only one of the four that identified numeric slots *correctly*.
It called `_is_numeric_slot(slot_class_uri, slot_type)`, which checks both. The
other three compared `slot_type` directly against a class URI:

    if slot_type == "...#KGDoubleSlot":

`slot_type` is a slot *instance* URI (`urn:...:slot:mqlrating`). It is never a
class URI, so that branch was dead and all three always fell through to the
uncast form. They were fast by accident. Had anyone ever "fixed" that
comparison, `gte`, `lt` and `lte` would each have acquired the 60-second
timeout, and the fix would have looked like a correctness improvement.

## Why the cast could not simply be pushed down

Teaching `_try_numeric_filter` to unwrap `xsd:double(...)` is unsound, because
push-down **replaces** the filter rather than restricting it —
`push_filters` ends with `plan.filter_exprs = remaining`. The pushed constraint
therefore has to be exactly equivalent, not merely a superset:

* `?v >= 65` — SPARQL raises a type error for a string-typed value and excludes
  the row. `num_val` is NULL for exactly those terms. **Equivalent.**
* `xsd:double(?v) >= 65` — SPARQL casts numeric-looking *strings* and includes
  them. `num_val` still excludes them. **Not equivalent**; unwrapping would
  silently drop rows, in precisely the case the cast was written for.

A sound push-down for the cast form needs a second generated column holding the
numeric value of any numeric-looking text regardless of datatype, plus its
index — a table rewrite to serve one comparator. Not worth it unless the
assumption below turns out to be false.

## Fix

All four comparators now emit the uncast form from one table (`_RANGE_OPS`),
and `_is_numeric_slot` / `_NUMERIC_SLOT_CLASSES` are deleted rather than left
as a dead branch that would reintroduce the timeout if it ever started
matching.

## The assumption this bakes in

**Range comparators only match values stored as properly typed numeric
literals.** A numeric value stored as an untyped or `xsd:string` literal will
not match `gt`, `gte`, `lt` or `lte`.

This was already true of `gte`/`lt`/`lte`, which is what production uses — the
change makes `gt` agree with them rather than answering differently from `gte`
at an adjacent threshold. But it is now the behaviour of all four, so it should
be checked against real data. The related datetime question was checked and the
answer was *not* reassuring: production datetimes appear in three distinct
lexical forms (issues/053). If numeric literals are similarly inconsistent,
the second generated column above becomes worth building.

## Test

`test_comparator_coverage.py::test_range_comparators_partition_the_population`.
`gt`'s exact count cannot be pinned from the manifest — mqlrating carries one
decimal place, so a couple of entities sit exactly on the 65.0 threshold and the
generator does not tally them. The partition identity needs no such tally and is
still exact: `gt(x) + lte(x)` and `gte(x) + lt(x)` each equal the valued
population. It also refuses a zero on either side, since two comparators both
returning nothing sum to nothing and would otherwise "pass".
