# Equality Criteria Are Priced, But The Hop-Wise Gate Cannot See It

## Status: OPEN. Found 2026-09-04 on `lead_nurture_100k` (53.3M quads).

## Symptom

The production Nurture shape — an entity query whose slot criteria are all
`comparator="eq"` — always declines hop-wise traversal and runs the as-is
fan-out form. On a 53M-quad space that is the difference between a bounded walk
and a statement timeout:

    campaign uri = <head value>            78,871 rows   13.9-19.4 s
    campaign uri = <head> AND SFLeadId = <absent>   0 rows   TIMES OUT (60s
                                                    statement timeout, HTTP 500)

Adding a second equality constraint whose answer is provably ZERO makes the
query catastrophically slower than the same query without it. The absent value
is not even present in the term table.

## Evidence

Same space, same depth-2 frame shape, one criterion each, from the decision log:

    eq  campaign uri     Decision(as-is: depth 2, pinned but no measured
                         criterion — an unfiltered walk fans out)
    gte MQLRating >= 65  Decision(hop-wise: depth 2, driving from tail,
                         criterion admits 8%, drive from tail)

The range criterion is measured and goes hop-wise. The equality declines. The
gate is keyed on criterion FAMILY, not on whether the constraint is measurable.

## Mechanism

`generator.py` builds `_crit`/`_pred` (the `criterion_rows`/`predicate_rows`
passed to `decide_for_plan`) from exactly three sources:

    aliases.range_stats   keyed (p_uuid, op, literal), op in {">", ">=", "<", "<="}
    aliases.in_stats      keyed (p_uuid, values, negated)
    aliases.text_stats    keyed (p_uuid, cond)

`slot_sort_range.RANGE_OPS` is `{">=", ">", "<=", "<"}` — equality is not a
range op, and there is no `eq_stats`. An equality on a slot value is a CONSTANT
in the BGP, and constants are priced by `quad_stats` / `pair_rows`
(`(predicate_uuid, object_uuid) -> row_count`) plus `absence_bounds` for the
absent case. The criterion gate never reads either.

So in `traversal_decision.decide`:

    line 265  direction = choose_direction(chain, pair_rows, pair_bounds)
              -> NOT None. The constrained end is priced (or bounded), so the
                 "neither end pinned or constrained" decline is correctly avoided.

    line 306  if criterion_rows is None or not predicate_rows:  -> DECLINES

The direction that `choose_direction` just computed from the bound is discarded
by the next gate.

The comment at `traversal_decision.py:304` states "Ranges, IN, equality and
booleans have since been wired in". For this path that is not accurate:
equality reaches `pair_rows`, not `criterion_rows`.

## Relationship to issues/153

`issues/153` is implemented correctly and its bounds are right on this space.
Verified directly:

    cut depth 42,323 (hasEdgeSource). Every other predicate is fully
    enumerated below it, so unstored values bound at STATS_MIN_ROW_COUNT-1 = 1.
      hasTextSlotValue   606 pairs kept, min 644  -> absent value bounded <= 1
      hasUriSlotValue     40 pairs kept, min  69  -> absent value bounded <= 1

(40 kept URI pairs matches the fixture manifest's 4,960 singleton campaign URIs
— the fairness ordering and the DESC flip behave as designed at scale.)

The bound is computed, correct, tight, and reaches `choose_direction`. It cannot
affect the plan for an equality-only query because the criterion gate declines
afterwards. **`issues/153`'s benefit cannot appear on the production Nurture
shape until this is fixed**, which is why the one-hop probe evidence looked fine
while the real shape did not improve.

## Fix

Feed the equality criterion into `criterion_rows`. The numbers are already
loaded on `aliases`:

    criterion_rows  = pair_rows[(p_uuid, o_uuid)]      exact when stored,
                      or absence_bounds[p_uuid]         an UPPER bound when not
    predicate_rows  = pred_stats[p_uuid]                already used for the others

An upper bound is sound here for the same reason it is sound in `_end_sizes`:
it can only understate selectivity, and the gate reports selectivity rather
than thresholding it.

Care needed on the saturated-pair case: `_load_quad_stats` caps pair counts, and
`aliases.saturated_pairs` already marks pairs whose recorded value is a lower
bound. A lower bound must not be used as if it were a measurement here.

## Caveat on the timings above

The wall-clock numbers were taken while `backfill_server_properties_task` was
writing to the space every 0.5s and ANALYZE was running, so they carry real
variance (the same shape measured 13.9s and 19.4s in adjacent runs, and the
client retried the failing shape six times at ~55s). The DECISION log is not
timing-dependent and is the load-bearing evidence; the timeout is reproducible.

## Attempted fix 2026-09-04: REVERTED, made it worse

Implemented `_equality_criterion()` in `generator.py`, called after `_pairs` and
`_bounds` are built (they do not exist at the point `_crit` is computed). It
priced each chain constraint from `pair_rows`, fell back to `absence_bounds`,
and folded the result into the existing most-selective contest.

The gate stopped declining — exactly as intended:

    before   Decision(as-is: depth 2, pinned but no measured criterion)
    after    Decision(hop-wise: depth 2, driving from tail, criterion admits 2%)

And the plans got dramatically WORSE. Measured on `lead_nurture_100k`, warm,
after a Postgres restart (so both columns are cold-start-comparable):

    shape                    before        after
    eq campaign head         13.9 s        TIMEOUT (55s)
    eq campaign + ABSENT     TIMEOUT       TIMEOUT
    eq SFLeadId present      4 ms          TIMEOUT (55s)
    eq SFLeadId ABSENT       400 ms        19 ms

### Why it is wrong in MECHANISM, not just tuning

`SFLeadId present` matches ONE row out of 1,150,000 — maximally selective — and
it still timed out. So "hop-wise loses on common values, wins on rare ones" is
NOT the explanation, and a selectivity threshold on the equality would not have
saved it.

The reported selectivity was "admits 2%" on EVERY shape, including the ones
whose value criterion is 1-in-1,150,000. That means the equality price never won
the contest: a STRUCTURAL constant on the chain — a slot-type or frame-type URI,
which is present on every one of these queries and is not a filtering criterion
at all — won at 2% and drove the nested loop.

Feeding every `head_constraint`/`tail_constraint` into the contest is therefore
wrong. Those tuples include the structural constants that define the frame/slot
shape, not just the value the query filters on. A correct fix has to distinguish
"constant that identifies the shape being walked" from "constant that filters
what comes back", and only the latter is a criterion.

The one improvement (`SFLeadId ABSENT`, 400ms -> 19ms) is not evidence for the
approach: an absent term makes the `_const` CTE empty, which short-circuits
regardless of the plan chosen.

### What is still true

The DIAGNOSIS above stands and is independently verified: equality is invisible
to the criterion gate, and the A/B (`eq` declines, `gte` goes hop-wise on the
same space and shape) reproduces. `absence_bounds` reaches `choose_direction`
correctly. What is unresolved is how to admit an equality as a criterion without
admitting the structural constants alongside it.
