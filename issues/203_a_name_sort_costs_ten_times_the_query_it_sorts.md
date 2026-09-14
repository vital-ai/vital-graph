# A Name Sort Costs Ten Times The Query It Sorts

## Status: OPEN — found by the first concurrency baseline (`issues/192`),
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
