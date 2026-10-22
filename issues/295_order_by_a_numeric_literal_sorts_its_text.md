# 295 — ORDER BY a numeric literal sorts its text

## Status: FIXED 2026-10-22 for bare-variable sort keys, not yet released. Expression sort keys (COALESCE) still sort lexically: see "Not fixed".

**Related:** `issues/293` (found while checking a held-out query there),
`issues/075`/`078` (stable paging orders by uuid, deliberately).

## Found

On `sp_lead_synth_100k`, 59 leads have an `MQLRating` of `100.0`:

```sparql
SELECT ?r WHERE { GRAPH <urn:sp_lead_synth_100k> {
  ?s h:hasKGSlotType <urn:acme:kg:slot:MQLRating> ; h:hasDoubleSlotValue ?r .
} } ORDER BY DESC(?r) LIMIT 5
```

returns five rows of `99.9`. The values are typed `xsd:float`, and the
generated SQL sorts on the term's TEXT:

    ORDER BY p0.v1 DESC

`"99.9"` sorts above `"100.0"` as text, so every numeric `ORDER BY` on a
literal from a triple pattern is wrong once values differ in digit count:
doubles, floats, decimals and integers alike, ascending and descending. It is
not a planning effect: the same SQL is emitted with every rewrite off.

SPARQL 1.1 §15.1 orders literals with the `<` operator, which compares
numerics by value and `xsd:dateTime` chronologically.

## Cause

Two emitters write a user's ORDER BY, and both sort on the text column only:

- `emit_order.emit_order`: `collate(alias.v)`; a computed variable on a typed
  lane (`typed_lane`) already sorts on its value, and stable paging on uuid;
- `emit_project` re-applies the ORDER BY on the outer SELECT (an ORDER BY
  inside a subquery is not guaranteed to survive): plain `p0.v`, no lanes.

The term columns are there: a variable from a triple pattern carries `__num`
and `__dt` companions (`sql_type_generation.ColumnInfo`).

## Fix

One key builder for both emitters: `__num`, then `__dt`, then the collated
text. Numeric literals compare by value, datetimes chronologically, and every
other term keeps the text order it has today (its `__num`/`__dt` are NULL, so
they tie and the text decides). Stable paging (uuid) and typed computed
variables keep their branches.

Not changed: the relative order of numeric and non-numeric values in one
variable (implementation-defined in SPARQL), and where unbound sorts (today,
last ascending; SPARQL puts it first). Both are separate questions.

## A reversed decision

`tests/integration/test_sequence_ordering.py` recorded this as "a standing
backend limitation, NOT scheduled for a fix: changing it would mean touching
the shared ORDER BY path, which affects every SPARQL query that sorts", worked
around at the query layer (an `xsd:integer` BIND, per
`planning/planning_sequence/frame_slot_sequence_sort_paging_plan.md`), with
strict xfails that "fail loudly" if the backend ever gains numeric sort keys.
It was fixed on request on 2026-10-22, after:

- the DAWG sort/order conformance tests: 30 passed (`sort-1`..`sort-10`,
  builtin, expression and function sorts, a non-projected sort variable);
- `tests/api`: 677 passed; `tests/integration`: 835 passed, with the four
  strict xfails on bare-variable sorts turning into XPASS as designed (removed);
- unit: the test that pinned the lexical order is rewritten to pin the value
  order, plus one for the `emit_project` lift;
- the lead fixture: `ORDER BY DESC(?r)` returns 100.0 first, ASC 0.0 first.

The query-layer workaround can now be retired; that is a separate change.

## Not fixed

An EXPRESSION sort key. `COALESCE(?seq, 2147483647)` mixes a text-lane
variable with a numeric literal, and the expression emitter casts every
argument to TEXT, so the sentinel still sorts lexically. Two strict xfails
remain on it (`test_coalesce_in_order_by_sorts_missing_last`,
`test_coalesce_sentinel_orders_1_to_12_numerically`).
