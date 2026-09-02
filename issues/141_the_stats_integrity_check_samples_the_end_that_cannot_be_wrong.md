# The Stats Integrity Check Samples The End That Corruption Cannot Reach

## Status: FIXED IN `main`, UNDEPLOYED — the coverage audit is landed. After
## the deploy it should fire on the affected space and the anchor should snap
## back to its true count. That is falsifiable; check it. Original status: OPEN — `_run_stats_integrity` samples the three HIGHEST recorded
## pairs, but the corruption it exists to catch is what makes recorded values
## LOW. Found 2026-09-02 when a production deploy did not self-heal and a manual
## resync was required.

## The check

`maintenance_job._run_stats_integrity`:

    SAMPLE = 3
    rows = await conn.fetch(
        f"SELECT predicate_uuid, object_uuid, row_count "
        f"FROM {space_id}_rdf_stats "
        f"ORDER BY row_count DESC LIMIT {SAMPLE}")
    for r in rows:
        actual = await conn.fetchval("SELECT count(*) FROM …_rdf_quad WHERE …")
        if actual != r["row_count"]:
            bad = …; break

Disagreement triggers `resync_stats_tables`, which rebuilds the space. That is
the mechanism `issues/139` relies on and that the deploy runbook described as a
self-heal.

## Why it does not fire on the corruption it was written for

`issues/062` / `issues/139`: the prune DELETES high-count pairs, and the
incremental writer then re-inserts them holding only the post-prune delta. The
signature of the corruption is therefore **a recorded value far BELOW actual** —
a pair whose true count is 2,727,156 comes back as 80, or 6, or 4.

`ORDER BY row_count DESC LIMIT 3` samples the opposite end. A pair that
collapsed from millions to single digits sorts to the BOTTOM of the table,
which is exactly where the sample never looks. What surfaces at the top are the
largest survivors — often genuinely small pairs that were counted correctly —
and three correct rows read as a clean space.

**Confirmed on production 2026-09-02.** `main` was deployed with the fixed prune
and the `pruned` flag. The space did NOT self-heal. It took a manual
`resync_stats_tables`, after which the `(hasKGEntityType, NurtureAction)` pair
reads **76,827 = 76,827**. The rebuild holds only because the fixed prune is now
deployed; without it the old prune would have re-corrupted within a cycle.

It is a lottery rather than a guaranteed miss: an earlier sample on 2026-09-01
did catch `recorded 80 against 2,727,156 actual`, because that pair happened to
be in the top three by recorded value at that moment. Whether the check fires
depends on where the wrong rows happen to sort — which is not a property anyone
should be relying on.

## The cheap fix, and why it is better than raising SAMPLE

Raising `SAMPLE` does not fix the bias, it just buys more tickets in the same
lottery. The check needs a signal that corruption cannot hide from.

**Compare the TOTAL.** `rdf_stats` holds one row per distinct (predicate,
object) pair and `sum(row_count)` should account for most of the quad table. A
fragment does not:

    sum(row_count)   120,853        <- corrupted state, 2026-09-01
    quad rows     44,979,880        <- 0.27%

    stats rows    11,904,097        <- after the manual resync
    max row_count    188,893

That is two cheap aggregates and it would have flagged the corrupted state
immediately and unambiguously, at any point in the weeks it persisted. It is
also robust to the pruned steady state, where `sum(row_count)` is legitimately
lower — the threshold just has to account for what the prune removes, which is a
known quantity because the prune computes it.

Sampling by the largest ACTUAL count (via `rdf_pred_stats`, which is not pruned
and was verified correct) is a second option and catches the same class, at the
cost of a join.

## Related

- `issues/139` — the corruption this check failed to catch. Its "the deploy
  self-heals it" claim is corrected there.
- `issues/062` — the delta-after-prune mechanism that produces the wrong-low
  values.
- `issues/140` — the same family one level down: a signal that reads as normal
  because the failure mode makes it look normal.
