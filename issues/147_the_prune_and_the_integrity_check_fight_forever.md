# The Prune Keeps Only The Smallest Pairs Of A High-Cardinality Predicate

## Status: FIXED 2026-09-02. **The original framing of this issue was WRONG and
>
> **SUPERSEDED IN PART.** This is a consequence of `rdf_stats` being an
> incrementally-maintained accumulator that cannot validate itself. A
> proposal to recompute the reader's 10,000-row window instead — measured
> at 41 s on production — would remove the mechanism this issue describes
> rather than repair it. See
> `planning/planning_performance/rdf_stats_recompute_not_accumulate_plan.md`
> before doing further work here.

## is retracted in full below — read §"Retraction" before anything else.** The
## fix is correct; the causal story that motivated it was not.

## CONFIRMED LIVE 2026-09-02 22:41:59, on production

Sampling every ~3 minutes caught the prune running against a healthy table and
producing, in its own log:

    prune_stats_tables(prod_kg): kept 8866 rows (cap 50000)
    Stats prune: prod_kg ~205292 -> 8866 rows

    sampler:  22:41:06  in_window 50,146   pruned_preds  6
              22:43:56  in_window  8,867   pruned_preds 12

8,866 kept against a cap of 50,000 — 41,000 slots free — which is the defect
this issue describes, at the exact magnitude predicted from the keep-query
measurement. The fix in `342efc5` is therefore confirmed against live behaviour,
not just against a hand-run query.

Note this is a SECOND, separate destructive event from the one at 22:29 (max
row_count 192,183 -> 200 with the population intact). That one is still
unexplained and is NOT this. Two different things were eating the table.

## Retraction — what this file first claimed

Filed as "the prune and the integrity check fight forever", claiming the prune
CAUSED the observed loop:

    21:51  Stats integrity: recorded pair 259 vs 192091 — rebuilding
    21:52  prune_stats_tables: kept 5 rows (cap 50000)

**That is not what happened.** Those prunes ran against a table that was already
corrupt — max recorded pair 290, ~79k rows nearly all at row_count=1. With
all-singleton input, 5 non-singleton keepers is the CORRECT output. The prune
was downstream of the corruption, not its cause, and "kept 5 rows (cap 50000)"
is not evidence of the prune malfunctioning.

I reached the wrong conclusion by measuring the keep-query against the table
AFTER a resync had repopulated it, then attributing the pre-resync log lines to
what I had measured on post-resync data. Two different table states, one causal
story laid across both.

The defect below is real, was found by that measurement, and is worth fixing.
It is simply not the explanation for the 10-minute cycle.

## The real defect

On a HEALTHY, repopulated table the keep-query discards the large pairs of any
predicate with more than `per_predicate_n` pairs in the window. Measured on
production 2026-09-02, per predicate, showing the largest pair each one would
retain under `rn <= 2000`:

    predicate            pruned  in_window  biggest_pair  biggest_kept_OLD
    hasTextSlotValue     t         41,749        75,671                 2
    hasEdgeSource        f          3,273             7                 2
    hasUriSlotValue      f          1,221        75,571            75,571
    hasIntegerSlotValue  f            104        82,523            82,523

For `hasTextSlotValue` the largest surviving pair has **row_count 2** —
everything from 3 to 75,671 is dropped, every prune. The cut only bites on
high-cardinality predicates, which are precisely the ones where knowing a pair
is large matters to the semi-join gate. Predicates under the threshold keep
their large pairs untouched, which is why this was invisible on the small
fixtures: wordnet keeps 6,427 and the synths 8-10k, all well under 2,000 pairs
per predicate.

Aggregate effect on the same table:

    total rows in rdf_stats                     130,327
    row_count = 1 (singletons, never read)       80,220
    in the reorder's window (2 .. 200,000)       50,107     <- cap is 50,000
    what the keep-query returned                  8,850     <- 41,257 discarded

Two separate mistakes compounding.

**1. The keep-query truncated below its own cap.** It applied
`WHERE r.rn <= per_predicate_n` (2,000) on TOP of
`ORDER BY r.rn ASC ... LIMIT keep_top_n` (50,000). The rank cut existed to stop
one high-cardinality predicate evicting every other — but the ORDER BY already
does that, and better: it takes rank 1 of every predicate, then rank 2 of every
predicate, until the cap is full. Round-robin fairness cut at exactly the depth
that fits, rather than a fixed depth guessed in advance. The WHERE clause was
redundant with the ORDER BY, and destructive.

**2. What it discarded were the LARGEST pairs.** The ordering is
`row_count ASC`, so `rn <= 2000` keeps the 2,000 SMALLEST counts per predicate
and drops everything above. The semi-join gate needs to know a pair is large;
the prune was systematically removing that knowledge from exactly the predicates
that have enough pairs for it to matter.

**Note the keep-query does NOT filter on `pruned`.** An early reading of this
suspected it excluded pruned predicates' pairs wholesale; it does not. The
predicate-level `pruned` flag and the per-predicate rank cut are independent
mechanisms, and only the second one is the defect here.

Measured, same table and cap, with only the WHERE clause removed:

                             rows kept   predicates   largest pair kept
    with `rn <= 2000`            8,854           20              (small)
    ordering + LIMIT alone      50,000           20             192,159

Better on every axis: the cap is reached, all 20 predicates are still
represented, and the large pairs survive.

## Why the trigger is not the bug

`_run_stats_prune` selects on `reltuples > STATS_KEEP_DEFAULT`, which counts
EVERY row including the singletons. That looks wrong at first — the prune fires
for a table whose read window is already under the cap — but it is right:
singletons are exactly the bloat the prune exists to remove, and one predicate
holding 79,579 of them is a real reason to run. The defect was that the
keep-query then shrank the window as well, paying for one predicate's
singletons out of a DIFFERENT predicate's 41,749 legitimate pairs.

A note is left at the trigger: if it is ever narrowed to count only the window,
the keep-query's assumption that it may be called with nothing to do has to be
revisited.

## Relationship to `issues/141` and `issues/142`

**This does not explain the 10-minute rebuild cycle**, see the retraction. What
drives that is the table becoming all-singletons between cycles, which is
`issues/142`'s delta-only mechanism, not the prune.

What this fix DOES change is that once the table is healthy, a prune no longer
strips the large anchor pairs back out of it — so a resync's work survives
instead of being partially undone. Whether that is enough to hold the table
steady is an open question that wants watching across several cycles, not an
assertion.

Not the same defect as 142, and this does not close it. 142 is about a dropped pair
coming back holding only a delta (`129 -> ABSENT -> 1`), which needs `pruned` to
be set and is instrumented separately. This is about the prune dropping pairs it
had room to keep. They compound: fewer wrongly-dropped pairs means fewer chances
for 142's delta-only re-creation to fire, but the flag logic is untouched here.

Still visible on production and unexplained by this fix: one predicate holds
**79,579 rows at row_count = 1 with `pruned = FALSE`**. That is 142's signature
and the instrumentation added in `2209009` should name it on the next cycle.

## Why the small fixtures never showed it

The docstring's "a few thousand rows" is accurate for wordnet (6,427) and the
synth fixtures (8-10k) — none of them has a predicate with more than 2,000
pairs in the window, so the rank cut never binds. It binds only at production
cardinality, on one predicate, which is why every test passed.

## Why it was not found by reading the code

The keep-query is one statement with a window function, a WHERE, an ORDER BY and
a LIMIT, and every clause has a defensible rationale written beside it. The
redundancy between `WHERE rn <= N` and `ORDER BY rn ASC ... LIMIT M` is only
visible if you ask what the two do TOGETHER on real data. It took the maintenance
log — "kept 5 rows (cap 50000)" is self-evidently wrong, and no amount of reading
produced that.

The lesson is NOT the one this file first drew. "kept 5 rows (cap 50000)" looks
self-evidently wrong and is not — it is correct output for corrupt input. The
number that actually indicts the code is the per-predicate one above:
`biggest_kept = 2` against `biggest_pair = 75,671`. Reading a suspicious log
line and then measuring a DIFFERENT table state to explain it is how a wrong
causal story gets written with real numbers attached to it.
