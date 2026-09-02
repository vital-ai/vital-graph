# The Prune Discards 41,146 Rows With 41,146 Slots Free, And The Integrity Check Rebuilds Them Every 10 Minutes

## Status: FIXED 2026-09-02. Found from the maintenance log, not from the code.

## The observation

    21:51:05  Stats integrity: prod_kg recorded pair 259 vs 192091 actual — rebuilding
    21:52:49  prune_stats_tables(prod_kg): kept 5 rows (cap 50000)      ~79571 -> 5
    22:01:04  Stats integrity: prod_kg recorded pair 290 vs 192122 — rebuilding
    22:02:53  prune_stats_tables(prod_kg): kept 5 rows                  ~99435 -> 5

`issues/141`'s audit is working exactly as designed — it detects the corruption
and rebuilds. The next prune collapses the table again. The two have been
fighting on a ~10 minute cycle, each one correct in isolation.

## What the prune was actually doing

Measured on production 2026-09-02:

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
and drops everything above. The pair `issues/141` kept reporting — 192,091
actual, recorded 259 — is precisely one of those. The semi-join gate needs to
know a pair is large; the prune was systematically removing that knowledge.

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

## Relationship to `issues/142`

Not the same defect, and this does not close 142. 142 is about a dropped pair
coming back holding only a delta (`129 -> ABSENT -> 1`), which needs `pruned` to
be set and is instrumented separately. This is about the prune dropping pairs it
had room to keep. They compound: fewer wrongly-dropped pairs means fewer chances
for 142's delta-only re-creation to fire, but the flag logic is untouched here.

Still visible on production and unexplained by this fix: one predicate holds
**79,579 rows at row_count = 1 with `pruned = FALSE`**. That is 142's signature
and the instrumentation added in `2209009` should name it on the next cycle.

## Why it was not found by reading the code

The keep-query is one statement with a window function, a WHERE, an ORDER BY and
a LIMIT, and every clause has a defensible rationale written beside it. The
redundancy between `WHERE rn <= N` and `ORDER BY rn ASC ... LIMIT M` is only
visible if you ask what the two do TOGETHER on real data. It took the maintenance
log — "kept 5 rows (cap 50000)" is self-evidently wrong, and no amount of reading
produced that.

The same lesson as `issues/145`: the log said the answer, and the code review
did not. Both times the give-away was a number that could not be right, next to
a cap that said what right would have been.
