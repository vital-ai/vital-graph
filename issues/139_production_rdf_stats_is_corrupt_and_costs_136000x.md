# Production `rdf_stats` Is Corrupt, And It Costs 136,000x On The Hottest Query

## Status: REOPENED 2026-09-02 — the repair did NOT hold; see `issues/142`.
## Previously: RESOLVED on production 2026-09-02 — `main` deployed AND a MANUAL
## resync run. It did not self-heal (`issues/141`), and a resync alone does not
## hold under the old prune, so it needed both. Result: the dominant statement
## went 133,783 ms -> under 1 ms warm, 12,998,472 buffers -> ~270.
## The "rebuild alone, no deploy" framing below is superseded — see The repair.

## The finding

`{space}_rdf_stats` maps `(predicate_uuid, object_uuid) -> row_count`. On
production it is wrong by four orders of magnitude:

    pair (hasKGEntityType, NurtureAction)
      rdf_stats says      13
      actual count        76,323

    whole table
      rows stored         51,887
      sum of row_counts   120,853       <- against 44,979,880 quad rows (0.27%)
      max row_count       344           <- real pairs run to millions

A true rebuild of the same pairs yields **553,718 entries with a maximum of
2,712,885**. The stored table is not stale by a margin; it is a fragment.

## Why it matters this much

`quad_stats` is not decoration. It drives `reorder_bgp`, the join-order
heuristic. Fed counts that are uniformly ~4 orders too small and roughly flat,
the heuristic cannot tell a 1-row leaf from a 76,000-row one, so it orders an
8-way join essentially arbitrarily — and an arbitrary order on this shape is a
nested-loop blowup.

Measured on production, same SPARQL and same bound value, **deployed generator
in both columns** — the only variable is the contents of `rdf_stats`:

| shape | corrupt (today) | rebuilt |
|---|---|---|
| one frame, one slot | 2.720 ms | **0.569 ms** |
| two frames, two slots — the 24,340-call statement | 133,783 ms | **0.982 ms** |

**136,000x on the statement that carries the P1**, with no deploy.

That reframes the whole investigation. `issues/136` recorded these two
statements burning 805,249 CPU-seconds — 13.9% of the instance's entire budget
over 33.5 days — and every one of the 24,340 SELECT calls returning zero rows.
That cost is not inherent to the query shape. It is a broken statistics table.

## CORRECTED 2026-09-01 — the mechanism is NOT `issues/103`

The section below blamed `issues/103`'s non-atomic resync. **Wrong.** Measured: a
verified rebuild was undone within minutes, and neither a race nor a timeout is
involved. The deployed `prune_stats_tables` is two DELETEs against `rdf_stats`
with no aggregate over `rdf_quad`, so the 60s fence never fires. Step 2 is
`ORDER BY row_count ASC ... OFFSET 50000` — it keeps the 50,000 LOWEST counts and
deletes the high ones, so the 76,323-row anchor pair is removed BY DESIGN every
cycle. The deployed `sync_stats_after_insert` has no notion of pruning
(`grep -c pruned` = 0), so the next write re-inserts the pair holding only the
post-prune delta: 6. That is `issues/062`, not `issues/103`.

`main` fixes it: the `pruned` flag (30 references) degrades the incremental
writer to UPDATE-only, so a pruned pair stays ABSENT rather than reappearing
wrong-low — and absent is recoverable (on-demand count, saturated, and
`issues/138`'s guard) where wrong-low is not.

## How it got this way — SUPERSEDED, see above

`issues/103` describes the mechanism exactly, and records fixing it on
**2026-08-18** — after the currently deployed build was cut on **2026-07-30**
(`issues/137`). So production is running the pre-fix code:

* `resync_stats_tables` was a `TRUNCATE` then an `INSERT`, non-atomic, with each
  `execute` autocommitting.
* `maintenance_job._audit_stats` samples recorded pairs, finds them disagreeing
  with the quad table mid-rebuild — the `TRUNCATE` is what makes them disagree —
  and starts a competing rebuild.
* The second `INSERT` collides with rows the first wrote and fails, leaving the
  `TRUNCATE` committed and the table partially filled.

`issues/103` names that state precisely: "the worst available state rather than
a neutral one, since absence means ZERO to every [reader]". 51,887 rows summing
to 0.27% of the table is that state, sitting in production for weeks.

## The repair

**Rebuilding it is the single highest-value action available on this system.**

> **Superseded 2026-09-02.** "It needs no deploy" was wrong. A rebuild under
> `v0.0.48` is undone within one maintenance cycle by the old prune, so it buys
> hours at most. The deploy is what makes a rebuild HOLD. Both are required,
> in that order: deploy, then resync.

The hazard is that the deployed code is the code that broke it. A rebuild
performed through the running application can be raced by `_audit_stats` exactly
as before, and the advisory lock that prevents this is in `main`, not in
production. So:

1. Rebuild in a **single atomic statement** taken directly against the database
   rather than through the app's resync path, so there is no window in which the
   table is empty and committed.
2. Or take `pg_advisory_lock(hashtext('vitalgraph.stats.<space>'))` manually for
   the duration, which is what `main` does automatically.
3. Do it per space; `lead_prod` and `lead_data` should be checked too — only
   the KG space was measured here.

Then confirm: `sum(row_count)` should be within a few percent of the quad-table
row count, and `max(row_count)` in the millions, not the hundreds.

Deploying `main` afterwards prevents recurrence (`issues/103`'s advisory lock
and atomic rebuild), but **must** carry `issues/138`'s identity fix, or the
semi-join gate reads the newly-correct denominator through a truncated key and
regresses the selective shape 20,000x.

## What is NOT claimed

Two bound values, one per shape, measured once each. The direction and magnitude
are far outside noise — 133,783 ms against 0.982 ms, with buffer counts moving
from 12,998,472 to a few hundred — but the exact multiplier is one sample.

The `0.982 ms` reading was taken after several earlier runs had warmed the
relevant pages. It is a warm number. The 133,783 ms baseline was equally warm
(12.9M of its 13.0M buffers were hits, not reads), so the comparison holds, but
a cold rebuild-and-measure would be worth doing before quoting the figure
externally.

## Related

- `issues/103` — the concurrency defect that produced this state. FIXED in
  `main` on 2026-08-18, still live in production.
- `issues/137` — production runs a 2026-07-28 build, which is why it predates
  that fix.
- `issues/136` — attributes 13.9% of instance CPU to two statements. This is why
  those statements cost what they do.
- `issues/138` — the semi-join gate reads this table; both fixes are required
  before `main` ships.
- `issues/119` — concluded "do not fix the estimate" for the PostgreSQL planner's
  own statistics. Unrelated to this: `rdf_stats` is the application's own table,
  it is simply wrong, and correcting it is not a plan-flip gamble.

---

## Outcome, measured 2026-09-02

`main` deployed, `rdf_stats` **manually** resynced, and the `ctx_pred` index
rebuilt with `object_uuid` as a KEY column. Same SPARQL, same bound values,
regenerated against live statistics:

| shape | before | after |
|---|---|---|
| one frame, one slot | 2.720 ms, 53 buffers | **0.57-0.62 ms**, 48 buffers |
| two frames — the 24,340-call statement | **133,783 ms**, 12,998,472 buffers | **0.97-18.4 ms**, ~270 buffers |

A ~48,000x reduction in buffers on the statement that carried the P1 — the
figure that does not depend on cache state or instance load.

    stats:  50,071 rows / max 37   ->   11,904,097 rows / max 188,893
    pair:   (hasKGEntityType, NurtureAction)  76,827 recorded = 76,827 actual

The semi-join gate now reads real statistics correctly, with no patching:

    semijoin selectivity: 1/76827 = 0.000 -> join

**It did not self-heal.** `_run_stats_integrity` samples the three HIGHEST
recorded pairs and this corruption makes recorded values LOW, so the wrong rows
sort out of the sample — `issues/141`.

**A measurement trap worth recording.** Re-running the SQL captured BEFORE the
repair still timed out at 60s, and was very nearly reported as "no improvement".
The app-side statistics shape the join order baked into the EMITTED SQL, not the
PostgreSQL planner — SQL generated under corrupt statistics carries a bad join
order permanently, and fixing the database cannot rescue it. The query must be
REGENERATED to measure the fix. Any before/after comparison run from a saved
`.sql` file is measuring the old join order.

