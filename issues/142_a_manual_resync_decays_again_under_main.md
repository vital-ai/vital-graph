# A Manual Resync Decays Again Under `main`, With `pruned` Reading FALSE

> **UPDATE 2026-09-02 (`2209009`).** One confirmed producer of this state was
> found and fixed, and it is NOT the one this issue suspects. The maintenance
> job's oversized-pair repair DELETEd the row and never set `pruned`, despite
> the comment above `STATS_OVERSIZED_SAMPLE` saying "absence plus the flag is
> the intended state". That guarantees the next write re-creates a delta-only
> row — this issue's exact mechanism. It cannot explain the ORIGINAL
> observation, because that repair is not in `v0.0.50`; it would have become a
> second cause after the deploy.
>
> `prune_stats_tables` is now instrumented as this issue asked: it counts pairs
> dropped against predicates flagged and WARNs when they disagree. The anti-join
> still looks correct by inspection, so the next cycle should settle it with
> numbers instead.
>
> Ruled out by reading: the resync's `SET pruned = EXISTS(...)`, which uses a
> narrower definition of `pruned` than the schema's. It looks like the conflict
> — it can clear a flag the prune legitimately set — but the clear is paired
> with a full repopulation of every pair under the cap, so it is correct in
> isolation. Do not "fix" it without a repro.

## Status: OPEN — MECHANISM ISOLATED 2026-09-02 by sampling. The prune removes
>
> **SUPERSEDED IN PART.** This is a consequence of `rdf_stats` being an
> incrementally-maintained accumulator that cannot validate itself. A
> proposal to recompute the reader's 10,000-row window instead — measured
> at 41 s on production — would remove the mechanism this issue describes
> rather than repair it. See
> `planning/planning_performance/rdf_stats_recompute_not_accumulate_plan.md`
> before doing further work here.

## the pair and does NOT set `pruned`, so the next write re-creates the row
## holding only a delta. The fix is in `prune_stats_tables`'s flag update, not
## in the resync as this file first supposed.

## The observation

`issues/139` was closed on 2026-09-02 after `main` was deployed and
`rdf_stats` manually resynced. Roughly seven hours later it had decayed to the
same fragment:

    after the manual resync   11,904,097 rows   max 188,893   anchor 76,827 = 76,827
    seven hours later             79,613 rows   max     421   anchor      80 vs 76,346
                                  sum(row_count) 91,403 against 45,158,040 quad rows (0.2%)

The anchor pair carries a WRONG LOW value — the `issues/062` signature — and
its predicate reads:

    hasKGEntityType   pruned = FALSE   row_count 78,981

14 of 24 predicates in that space do carry `pruned = TRUE`, so the flag
mechanism is working for most of them.

The maintenance cycle is active on this space and both steps run:

    Stats integrity: prod_kg has a recorded pair of 406 against 189550 actual — rebuilding
    Stats prune: prod_kg ~79591 → 494 rows
    Stats prune: prod_kg ~79539 → 448 rows

## Why this matters

It contradicts the operating assumption written into the deploy runbook: that a
manual resync HOLDS once `main` is deployed, because `main`'s prune is atomic
and sets the `pruned` flag that stops `sync_stats_after_insert` re-inserting
post-prune deltas. It does not hold. The P1 will return as the table decays.

## What was checked, and why neither half explains it

**The resync's flag rule is correct for the state it leaves.**

    UPDATE {t_pred} SET pruned = EXISTS (
        SELECT 1 FROM {t_quad} q WHERE q.predicate_uuid = {t_pred}.predicate_uuid
        GROUP BY q.object_uuid HAVING COUNT(*) > STATS_MAX_ROW_COUNT)

After a resync every pair at or below `STATS_MAX_ROW_COUNT` is present, so
absence means zero for any predicate with no pair above it. `hasKGEntityType`'s
heaviest pair is 76,346, well under 200,000, so `FALSE` is the right answer for
the post-resync state.

**The prune's flag rule is correct for the state IT leaves.** `pruned_preds` is
computed BEFORE the rewrite by anti-joining the live table against the keeper
set, so any predicate losing a row is marked, and the mark plus the TRUNCATE and
re-insert are inside one `conn.transaction()`.

So each is individually right, and the end state of any cycle should be
`TRUE` for a predicate whose pairs the prune removed. The observed state is
`FALSE` with a delta value, which requires a write to have landed while the pair
was ABSENT and the flag was FALSE. No ordering of "resync then prune" produces
that window, which is why the mechanism is not established.

## Candidates, none confirmed

1. **The two steps are independently space-scoped.** `_run_stats_integrity` and
   `_run_stats_prune` each act on one space per cycle and pick independently, so
   a cycle can resync `prod_kg` while pruning `lead_prod`. Whether that opens
   a window depends on details not traced here.
2. **A third writer.** Something other than these two paths clearing the flag or
   deleting pairs.
3. **`pruned_preds` missing a predicate whose pairs were ALREADY absent** before
   this prune — it can only mark what it observes losing a row.

## The diagnostic that would settle it

Sample, every minute for one space, and correlate:

    SELECT now(), s.pruned, s.row_count AS pred_total,
           (SELECT row_count FROM {sp}_rdf_stats x
             WHERE x.predicate_uuid = s.predicate_uuid
               AND x.object_uuid = <anchor object>) AS anchor_recorded
      FROM {sp}_rdf_pred_stats s WHERE s.predicate_uuid = <hasKGEntityType>;

against the maintenance log lines for that space. The transition to watch is the
one where `anchor_recorded` goes from absent to a small number: whatever the flag
reads at that moment is the answer. Everything above is inference from end
states.

## Related

- `issues/139` — closed on the strength of a repair that has not held. Its
  Status needs revisiting once this is understood.
- `issues/062` — the delta-after-prune mechanism producing the wrong-low value.
- `issues/141` — why the integrity check is unreliable at spotting this; it does
  fire on this space now, but samples the end corruption does not reach.

---

## Caught in the act, 2026-09-02

Sampled once a minute: the flag, the predicate total, the anchor pair's
recorded value, and the table size.

    ts        pruned  pred_total  anchor_recorded  stats_rows  sum_rc
    13:10:25  f       79030       129              79965       98464
    13:11:26  f       79030       129              79966       98496
    13:12:26  f       79031       ABSENT           79161       79719   <- prune
    13:13:27  f       79032       1                79171       79838   <- write

Three facts, in one minute:

1. The prune REMOVED the anchor pair — `ABSENT`, and `stats_rows` drops 79,966
   -> 79,161.
2. **`pruned` stayed FALSE across the removal.** The prune did not flag the
   predicate whose pair it had just deleted.
3. The next write re-created the row holding only its delta: **1**. From there
   it climbs by ones — 127, 129 — and nothing ever restores the true 76,346.

That is `issues/062` reproduced end to end, and it settles what this file could
not: there is no resync/prune interleaving involved. `prune_stats_tables`
computes `pruned_preds` by anti-joining the live table against `_keep_stats` and
marks what it finds; `hasKGEntityType` lost a pair and was not marked. **The
defect is in that flag update, not in the resync.**

The three candidates listed above are therefore closed: not step scoping, not a
third writer, and not "already absent" — the pair was present at 13:11 and gone
at 13:12.

## What this means for the fix

`issues/141`'s coverage audit (landed 2026-09-02) DETECTS this state and
rebuilds the space, so it bounds the damage to one maintenance cycle. It does
not stop the state being created. The remaining work is to establish why the
anti-join missed this predicate — the query looks right by inspection, which is
exactly why it needs the same treatment this observation got: instrument the
prune to log `pruned_preds` alongside the rows it dropped, and compare.

## The full 90-minute run — reproducible, twice, flag never flips

The sampler above ran to completion: 90 samples over 90 minutes.

**`pruned` was FALSE in all 87 readable samples. It never once became TRUE.**
So this is not a race the prune sometimes loses — the prune never flags this
predicate at all.

Two complete cycles, identical in shape and ~28 minutes apart:

    13:11:26  f  anchor=129     stats_rows=79,966
    13:12:26  f  anchor=ABSENT  stats_rows=79,161     <- prune drops the pair
    13:13:27  f  anchor=1       stats_rows=79,171     <- write re-creates it

    13:39:37  f  anchor=23      stats_rows=79,335
    13:40:38  f  anchor=ABSENT  stats_rows=79,184     <- prune drops the pair
    13:41:38  f  anchor=1       stats_rows=79,200     <- write re-creates it

Between cycles the value climbs by ones — 1, 3, 5, 6 ... 23 ... 129 — and is
reset to 1 at the next prune. It never approaches the true 76,346, and no
resync in the window restored it.

That closes the remaining ambiguity. `prune_stats_tables` computes
`pruned_preds` by anti-joining the live table against `_keep_stats` and marks
what it finds; for this predicate it drops a pair on every cycle and marks
nothing, every time. A once-per-cycle deterministic miss is not a concurrency
problem, so the advisory lock and the transaction are not implicated — the
anti-join itself does not see this predicate.

**Next step is to instrument, not to reason.** The query reads correctly, and it
has now been read correctly three times while being wrong. Log `pruned_preds`
alongside the pairs the rewrite drops, for one cycle, and compare the two sets.

