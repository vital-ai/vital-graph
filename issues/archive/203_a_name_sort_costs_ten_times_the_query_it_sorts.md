# A Name Sort Costs Ten Times The Query It Sorts

## Status: FIXED 2026-09-15 (`24ccc380` + `23348a64`). The sort tax is 1.55x,
## against 10.5x: sorted 335.4ms -> 7.6ms, unsorted 32.0ms -> 4.9ms.
## Originally OPEN — found by the first concurrency baseline (`issues/192`),
## measured serially, cause located in code, not yet fixed.

## The measurement

The load driver runs two operations that are byte-identical except for one
argument. `kgquery_page1` and `kgquery_sorted` both ask for the same entity
type, the same frame criteria, `page_size=25`, `offset=0`. The second adds
a single `SortCriteria(sort_type="entity_property", property_uri=hasName)`.

Under 10 concurrent users, 60s, read-only, over a space of 400 entities:

    kgquery_page1      p50   37ms   p95   101ms
    kgquery_sorted     p50  338ms   p95   960ms

Concurrency is not the cause. Serially, one client, eight iterations, warm:

    page1  (no sort)   p50   32.0ms   min  29.5ms   max 240.8ms
    sorted (name   )   p50  335.4ms   min 312.5ms   max 445.8ms

Tight spread, reproducible across two runs. Sorting FOUR HUNDRED entities by
a name property costs 10.5x the query that produces them. By the standing
rule that no read-only query should take that long — if it does, the method
is wrong — this is a defect and not a cost of sorting.

## Why neither fast path takes it

Two independent refusals, either one sufficient:

1. `fast_slot_sort.sort_keys` (`fast_slot_sort.py:115`) accepts only
   `entity_frame_slot` and `frame_slot`. `entity_property` returns None, so
   `can_serve` is False. The sort table holds FRAME-BORNE slot rows; a
   property hanging directly off the entity is not in it at all.

2. `fast_slot_filter.can_serve_filter` declines whenever `sort_criteria` is
   set (`fast_slot_filter.py:147`) — "a sort is the OTHER path's job".

This is exactly the shape `issues/172` named: a filtered, sorted list served
by NEITHER path. 172 was fixed for slot sorts by teaching `can_serve` to
accept equality frame criteria. It did not close the gap for
`entity_property`, because that sort key is not in the table to begin with.
So 172's reasoning ("both refusals are individually correct, together they
mean a filtered sorted list is served by neither") still applies verbatim to
this sort type.

## A second finding, about the baseline itself

The load driver's filter would not reach the fast path even WITHOUT a sort.
`_state_criteria()` builds `SlotCriteria(slot_type=..., value="California",
comparator="eq")` with no `slot_class_uri`. `_eq_criteria` derives the lane
from exactly that field (`lane = _LANE.get(slot_class_uri or "")`) and
returns None when it is absent, so `can_serve_filter` is False for the
unsorted query too.

Both load-test kgquery operations therefore measure the GENERAL PIPELINE,
not the fast path the portal's list view uses. That does not invalidate the
baseline — it is a real client-to-service path — but the numbers must not be
read as the fast path's, and a later fast-path improvement will not move
them. Setting `slot_class_uri` in the driver would benchmark the other path;
that is a deliberate choice about what the load test is for, so it is
recorded here rather than changed.

## What is not yet known

- Where the curve bends. 400 entities already costs 335ms; the scaling of
  this shape has not been measured, which is the same open question
  `issues/172` carries for the served case.
- Whether the general pipeline sorts before or after applying the LIMIT.
  172's fixed case materialised the whole match set through a GroupAggregate
  and sorted it three times before the LIMIT; if this path does the same,
  that is the mechanism and the 10x is the 25-of-400 ratio showing through.
  A plan capture would settle it and has not been done.

## Reproduce

    LOAD_TEST_ENV=test python load_test_scripts/setup.py --entities 400
    LOAD_TEST_ENV=test python load_test_scripts/load_test.py \
        -u 10 -t 60 --read-only --record /tmp/load.json

## FIXED 2026-09-15 — the two fast paths each held one half

`fast_slot_sort` already learned FRAME CRITERIA when `issues/172` was fixed; it
simply refused any sort key that was not a slot. `fast_prop_sort` orders by an
entity property but knows nothing about frame criteria. So this shape — a
filtered list ordered by name, which is what clicking a column header on a
filtered view produces — was served by neither.

`fast_slot_sort` now accepts an ALL-entity-property key set and draws the
ordering value from `{space}_entity_prop_sort`, while the frame criteria stay
EXISTS clauses against `{space}_entity_slot_sort`, correlated on `entity_uuid`.
One table orders by the property, the other filters by the frame, and they join
on the entity.

    page1 (no sort)    32.0 ms -> 4.9 ms
    sorted (hasName)  335.4 ms -> 7.6 ms
    the sort tax        10.5x  -> 1.55x

Under load, 10 users / 60s: `kgquery_sorted` p50 338 ms -> 8.2 ms,
`kgquery_page1` 37 -> 5.6, `kgquery_deep_page` 45 -> 5.7.

### The driver had to change too, and this issue predicted it

The note above — "the driver's filter would not reach the fast path even
WITHOUT a sort, because `_state_criteria()` omits `slot_class_uri`" — was left
deliberately, on the grounds that changing it would swap one unserved path for
another while no fast path could serve the sorted shape. That is no longer true,
so the driver now sends the field, as a real client does because the model
carries it. Verified against the fixture rather than assumed: every subject with
`hasKGSlotType StateSlot` in `kg_load_test` has `vitaltype KGTextSlot`.

That is why the unsorted case improved 6.5x as well: the FILTER path could not
be reached either.

### What this needed that is not code

`kg_load_test` had no `{space}_entity_prop_sort`. The sorted path cannot serve
without it, and 0 of 41 spaces on the dev instance had one — which is the same
gap that made a dev listing take 23.7 s. Code and table are both required.

### Verified, not assumed

Correctness was checked by reading the page's names back FROM THE QUADS rather
than from the table it was ordered by: ordered, none missing the property, and
ZERO entities outside the page holding a smaller value — the silent wrong-page
failure a derived-table sort produces. ALL-or-none on the key set for the same
reason: a half-served multi-key sort orders by the right values in the wrong
precedence.