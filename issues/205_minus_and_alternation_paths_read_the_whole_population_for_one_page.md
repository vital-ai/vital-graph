# MINUS And An Alternation Path Read The Whole Population For One Page

## Status: OPEN, found 2026-09-15 by the first run of the `issues/193` shape
## bench — which is the point of that issue.

## The measurement

Seven SPARQL shapes, each `LIMIT 25`, each returning exactly 25 rows, on
`sp_lead_synth_10k` (7.4M quads). `EXPLAIN (ANALYZE, BUFFERS)`, warmed first:

    MINUS                 661,626 buffers      ~5.2 GB
    alternation path      477,751 buffers      ~3.7 GB
    sub-SELECT              1,575
    OPTIONAL                  406
    BIND / LCASE+CONTAINS     127
    UNION (bound var)         127

Identical to the buffer on a second run (661,626 and 477,751 again), so this is
the PLAN, not a cold cache.

A 5,000x spread between shapes returning the same 25 rows.

## What the two expensive shapes have in common

    MINUS       ?s vitaltype KGTextSlot . MINUS { ?s hasBooleanSlotValue ?b }
    path        ?e hasEdgeSource|hasEdgeDestination ?n

Both are O(POPULATION), not O(page): the anti-join has to be resolved for every
candidate before `LIMIT` can take 25, and the alternation appears to materialise
both arms rather than stopping once 25 rows exist. `KGTextSlot` has 115,000+
instances in this fixture and the two edge predicates 527,700 each, so the page
is paying for the whole set either way.

That is the same shape as `issues/040` — "kgquery paging is O(matches), not
O(page)" — arriving through a different operator, and the same property
`fast_prop_sort` is valued for: staying flat as the page deepens.

## Why nothing caught it

`issues/193` counted the operators appearing anywhere in `tests/performance`:
`MINUS` **0**, property paths **0**. Both were entirely unbenched, so there was
no number to regress. This was found by the first run of the bench written to
close that gap, before it had measured anything twice.

## Not yet established

- Whether the LIMIT can push through either shape at all, or whether the cost is
  semantic (an anti-join genuinely needs the population) rather than a plan
  defect. `MINUS` may be irreducible; the alternation probably is not.
- Whether a deeper page costs more, which distinguishes "O(population) once"
  from "O(offset) per page" — `fast_prop_sort` documents that distinction as the
  one that actually matters to a user.
- Whether the generated SQL for an alternation path is a UNION of two scans (in
  which case the LIMIT should be pushable into each arm) or something else.

## Where to look

`tests/performance/test_sparql_shape_coverage.py` reproduces both in about a
second each. The generated SQL comes through `_generate_sql`, so the plan is one
`EXPLAIN` away.
