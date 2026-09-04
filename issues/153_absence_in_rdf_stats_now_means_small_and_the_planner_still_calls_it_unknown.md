# What Absence In rdf_stats Means, And The Planner Still Calls It "Unknown"

## Status: IMPLEMENTED 2026-09-04, both halves. This file went through two wrong
## readings first; both are recorded below because the reasoning error is the
## reusable part.

## Why both halves were needed, and why one alone is worse than neither

The ordering fix and the planner fix are one change. Keeping each predicate's
LARGEST pairs makes the anchors visible to the semi-join gate — and it drops the
RARE end, which is the one `choose_direction` most needs. Measured against the
two consumers:

    consumer                        wants priced      ordering that serves it
    choose_direction (drive small)  the SMALL pair    ASC
    semi-join gate (price anchor)   the HUGE pair     DESC

Neither ordering serves both on its own. DESC plus "absence is an upper bound"
serves both: the anchor is stored exactly, and the absent end is known to be
smaller than everything stored for its predicate. Shipping DESC WITHOUT the
bound fixes the anchor case and regresses the commoner driving-set case — one
end constrained to a rare value and the other to a common one, which is the
Nurture-actions shape that started this incident.

## What was implemented

  * `sync_stats_tables.absence_bounds(quad_stats)` -> `{predicate: bound}`,
    derived from the preloaded table with no extra column and no extra query.
  * `traversal_decision._end_sizes(chain, pair_rows, pair_bounds)` falls back to
    that bound for a constrained end with no stored pair, instead of None.
    Threaded through `choose_direction` / `decide` / `decide_for_plan`.
  * `generator.py` computes the bounds from the PRELOAD, not from `_pairs`:
    `_pairs` has on-demand lookups merged in, and one extra row for a predicate
    would shift the inferred cut depth and mislabel it as cut.

Tests: `tests/unit/sparql_sql/test_absence_is_an_upper_bound.py`, including the
without-the-bound case pinned explicitly so the regression it fixes stays
visible, and the inconclusive case (`bound >= other`) where the bound must NOT
flip the choice.

## What was actually wrong, and is now fixed

`recompute_stats_tables` ranked each predicate's pairs `count(*) ASC`, so the
cap kept a predicate's SMALLEST pairs and dropped its LARGEST. That is the
opposite of the table's purpose: the planner reads it to RECOGNISE a huge end so
it does not drive from one, and a pair the table cannot see is a pair the
planner cannot avoid.

Removing the `<= STATS_MAX_ROW_COUNT` bound did NOT cover this. That bound only
decides what is ELIGIBLE; the ordering then discarded the anchor anyway for any
predicate holding more pairs than the cut depth. Reproduced at `keep_top_n=1000`
against one predicate with a 5,000-row pair and 3,000 pairs of 2:

    ASC    5,000-row anchor DROPPED, a smaller 4,000-row pair on another
           predicate KEPT
    DESC   5,000-row anchor KEPT, both predicates still represented

That is the `(rdf:type, Edge_hasKGSlot) = 304,859` shape exactly — a
high-cardinality predicate whose one enormous pair is the anchor.

FIXED: the window is now `ORDER BY count(*) DESC`, with `ORDER BY rn ASC`
unchanged so fairness across predicates still holds — every predicate's biggest
pair before any predicate's second-biggest. Regression tests in
`tests/integration/test_stats_recompute.py`
(`test_the_anchor_survives_a_cap_far_below_its_predicates_pair_count`,
`test_every_predicate_gets_its_biggest_before_any_gets_its_second`), both
verified to FAIL under the ascending order.

WHY THE EXISTING TESTS MISSED IT: in the `skewed_space` fixture the large pair
is the only pair its predicate has, so it is rank 1 in either direction and
survives both. Separating the two orders needs a predicate that has a big pair
AND a long tail — which is the realistic shape, and now a fixture.

## The distribution argument, which is the whole reason this is cheap

Any realistic graph has a few very large pairs and a long tail of tiny ones.
Measured here, 85-94% of all pairs are singletons — 15.6M of them on a 50M-quad
space. So the pairs worth storing are a small bounded set and the tail is what
the cap should drop. It is also why recomputing beats accumulating: the
accumulator spent its writes on the tail, where nearly all the CHANGES are and
almost none of the value is.

## What absence means now

One of two things, decided per predicate, and BOTH are upper bounds:

  * predicate not cut — every pair with `count >= 2` is stored, so an absent
    pair holds exactly ONE row;
  * predicate cut — its stored pairs are its largest, so an absent pair is
    `<= min(stored row_count for that predicate)`.

So absence can never hide a huge end. That is the safe direction, and it is the
direction that makes absence USEFUL rather than merely harmless.

## The part still open

`traversal_decision._end_sizes` returns None for an unpriced end and
`choose_direction` then drives from whichever end IS priced. With absence
bounded above, that is backwards: the absent end is the small one, and
`issues/090` measured 9.2x for driving from the smaller end.

It needs no schema change. The cut is a single `rn` boundary, so both facts fall
out of the table the reader already loads in full:

    D = max over predicates of (pairs stored for that predicate)
    stored_count(p) <  D  ->  not cut  ->  absence means row_count = 1
    stored_count(p) == D  ->  cut      ->  absence means <= min stored for p

A predicate that is not cut but happens to hold exactly D pairs is misclassified
as cut. That is the safe direction: it weakens a known 1 into a bound.

Not done here because it is a plan change and `issues/090`'s numbers swing 9.2x
one way and 4.2x the other, so it wants a before/after on a real query shape
where one end is constrained to a rare value — the Nurture-actions shape that
started this incident.

## Two wrong readings, recorded because the error is reusable

1. FIRST: "absence means small", from a GLOBAL measurement (largest absent 1,342
   vs largest present 570,696). The comparison was real and the conclusion did
   not follow: the cut is PER PREDICATE, and the global maximum was dominated by
   predicates that were never cut at all.

2. SECOND: "absence means large", from the per-predicate measurement
   (`cut_min >= kept_max` in 5 of 5 cut predicates). That was a correct
   measurement of the code AS IT THEN WAS — and it was measuring a bug. The
   right response was not to teach the planner about a lower bound but to ask
   why the table was keeping the small pairs at all.

The lesson in both: measure at the granularity the mechanism operates at, and
when a measurement says the data is shaped oddly, check the code that shaped it
before building on the observation.

## Future work, recorded elsewhere

Postgres already samples the largest (predicate, object) pairs on every space:
`stat_{space}_quad_po` is a multivariate MCV list on exactly this pair, built by
ANALYZE. Measured at 5.7-7.9 s for 131 estimated entries against 55 s for the
recompute's 50,000 exact ones, with 5.7-8.8% mean error over actual counts of
200 to 570,696.

That is the range where exactness does not matter, because the decision it
drives is "this end is huge, do not drive from it". Using it to supply the top
and shrinking the recompute to the middle is written up in
`planning/planning_performance/rdf_stats_recompute_not_accumulate_plan.md`
("FUTURE WORK"), including the open question that gates it: whether excluding
those pairs actually makes the aggregate cheaper, given the scan has to read
every row regardless.

Deliberately AFTER the current work lands.

