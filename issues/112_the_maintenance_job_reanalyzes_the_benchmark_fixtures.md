# A Perf "Regression" With Identical Code: the App Re-ANALYZEs the Fixtures

## Status: CLOSED 2026-08-21, with a COST discovered 2026-08-22 that anyone
## enabling option 3 has to know about — see the end.

Both landed:

* **The statistics state is stamped.** `perf_record.stats_stamp` records
  `fixture_tables`, `fixture_live_tuples` and `fixture_last_analyze` into
  `env.stats`, beside the `env.pg` settings that `issues/081` added for the same
  reason one level up. `perf_compare` reports a change as a NOTE rather than a
  mismatch — a refreshed ANALYZE does not invalidate a run, it EXPLAINS it:

      NOTE stats.fixture_last_analyze: baseline=... run=... — the fixtures were
      re-ANALYZEd between these runs, so a plan flip here is not necessarily a
      code change

  A baseline with no stamp says so, in the same terms `issues/081` established:
  absence is not agreement.

* **Option 2 was BUILT, MEASURED, AND REVERTED.** A deterministic ANALYZE before
  each recorded run makes comparisons WORSE on two counts:

      with an ANALYZE before each run   174,341 / 333,407 buffers, alternating
      with no ANALYZE                   333,407 / 333,407 / 333,407

  **ANALYZE resamples.** `deep_paging.monotonic[100k]` sits on a planner cost tie
  between `Gather Merge` and a `Sort` above a `Gather`, and a fresh sample tips
  it either way. The refresh does not stabilise the measurement, it RANDOMISES
  it — 184 ms or 483 ms, by coin flip.

  **And it empties the cache.** Analyzing 260 tables and 126M live tuples evicts
  the working set, and the fixtures are 45 GB against a 16 GB `shared_buffers`,
  so nothing warms them back — `pg_prewarm` cannot help with a working set three
  times the pool. `shared_read` went 0 -> 233 across six benches from that alone,
  and `shared_read` is gated, so the run read as a broad regression.

  The reverting commit keeps the reasoning at the call site so it is not retried.

## The bigger correction: the 91% was never a regression

The original finding above — "the maintenance job's ANALYZE changed the plan" —
was half right and drew the wrong conclusion. The plan is **BISTABLE**. It is not
that fresh statistics are worse than stale ones; it is that this query has two
plans within noise of each other and ANY resampling picks between them.

    old baseline (08-18)                  174,345
    a run recorded after an ANALYZE       174,340
    the next run, same code and procedure 333,414

Three values, one commit. So the "+91% regression" that blocked promotion for a
day was a coin flip, and chasing it — including the forty minutes spent excluding
every commit — was chasing noise that the bench presents as a number.

**FIXED 2026-08-20 by gating the claim instead of the cost.**

The bench's own assertion was never the problem: it asserts that cost does not
DROP with depth, as a RATIO, and that survives the flip untouched. What gated the
coin flip was the recorded `shared_buffers`, taken from a single EXPLAIN of the
deepest page.

    [bench."query.kgquery.deep_paging.monotonic"]
    shared_buffers = { report_only = true }
    shared_read    = { report_only = true }

And `min_ratio` — the metric that carries the claim — **had no threshold rule at
all**, so the drift detector had nothing to say about this bench except the coin
flip. It is now gated, `direction = "decrease"`, because below 1.0 the curve is
non-monotonic: `issues/080` measured a sorted page getting FASTER with depth
(13.5s -> 5.6s -> 2.7s) as the planner abandoned a nested loop it should never
have chosen. A win-shaped defect.

Verified both ways against the real baseline:

    the coin flip (333,402 -> 174,341)   0 failing, 1 informational
    a non-monotonic curve (ratio 0.4)    1 failing

This is scoped to one query's plan, not a relaxation: `shared_buffers` still
gates every other bench at 5%/15%.

The underlying tie is NOT fixed and probably should not be — the two plans are
genuinely within noise of each other, and forcing one would be pinning a planner
decision on the basis of a benchmark. What is fixed is that the suite no longer
reports the tie as a regression.

`query.kgquery.deep_paging.monotonic[100k]` against the 2026-08-18 baseline:

    shared_buffers   174,345 -> 333,408   (+91%)
    execution_ms       237.6 ->   474.2   (2x)
    min_ratio          0.981 ->   1.525
    plan shape       'Gather Merge','Sort' -> 'Sort',...,'Gather'

It blocked promoting a new baseline, and cost about forty minutes to attribute.
**Nothing in the repository changed it.**

## What was excluded, and how

* **Not the code.** Checking out `a8a0509` — the exact commit the baseline was
  recorded at — into `vitalgraph/` while keeping the tests at HEAD reproduces
  **333,407**, the current number. Both of the day's suspect changes were also
  A/B'd individually and neither moves it:

      slot_sort_range on / off              333,407 / 333,407
      selective-driven fix applied/reverted 333,407 / 333,407

* **Not the configuration.** `perf_record` stamps PG settings (`issues/081`
  built that for exactly this). All nine identical, including `shared_buffers`
  16GB, `work_mem` 64MB, `max_parallel_workers_per_gather` 2, and server version
  18.4.

* **Not extended statistics.** `stat_sp_lead_synth_100k_quad_po` exists now.
  Dropped it, re-ANALYZEd, re-measured: **333,342**. Recreated afterwards.

* **Not the data.** The bench's own recorded facts are identical on both sides:
  `actual_rows` 25, `max_actual_rows` 33,333, `estimated_rows` 1,
  `offsets_measured` 3, `heap_fetches` 0.

## What did change

Every table in the fixture was ANALYZEd **today at 08:05**, and **394 tables were
analyzed today** across the database. The app's own `MaintenanceJob` scores each
space and runs ANALYZE/VACUUM on a schedule — it is a background process inside
`vitalgraph-test-app`, and it ran repeatedly yesterday while `issues/109` was
being worked on.

So the planner got fresh base statistics and chose differently: `Gather Merge`
(parallel, order-preserving) became a `Sort` above a plain `Gather`. Same rows,
same estimates at the root, twice the execution time.

## Why this matters more than one bench

**A committed perf baseline is only valid until the next maintenance cycle
touches the fixtures.** Nothing announces that. The comparison reports it as a
regression against the last commit, so the natural reading — and the reading it
got — is that somebody's change caused it.

This is `issues/081` one level deeper. That issue established that a benchmark
compared against an unrecorded CONFIGURATION is meaningless, and added
`PG_SETTINGS` stamping. The same argument applies to the STATISTICS STATE, which
is not recorded and which the application mutates on its own schedule.

## Options

*(1 done, 2 tried and reverted, 3 open — kept for the reasoning.)*

1. **Stamp the statistics state.** Record `last_analyze` / `last_autoanalyze` and
   `reltuples` per fixture table in `perf_record.env`, so `perf_compare` can say
   "the statistics were refreshed between these runs" instead of "+91% worse".
   Cheapest, and it makes the phantom legible rather than preventing it.
2. **ANALYZE deterministically before a recorded run**, so both sides start from
   a known state. Makes runs comparable at the cost of hiding the effect of
   stale statistics, which is itself something worth seeing.
3. **Exclude the benchmark fixtures from the maintenance job.** They are not
   spaces anyone serves. Keeps the fixture stable, and diverges from how a real
   space behaves — the maintenance job IS part of production behaviour.

1 and 2 compose; 3 is a separate call.

### Option 3, as landed (`d68e2f3`)

`VG_MAINTENANCE_EXCLUDE_SPACES`, read once at construction and applied in
`_only_registered` beside the registry filter. **Empty by default**, so
production behaviour is unchanged and nothing in shipped code names a fixture.

The divergence this option costs is real and was the reason it stayed open, so
it is opt-in per deployment rather than a default: the fixture names belong to
a dev machine rather than to the product, and a deployment should choose to
make its benchmarks unlike production instead of inheriting that silently.

Set on the test stack for its nine fixtures and overridable from the
environment. Confirmed from the running server:

    MaintenanceJob: 9 space(s) exempt from maintenance: sp_graph_forms_20k,
    sp_graph_skew_2k, sp_graph_synth_100k, sp_graph_synth_10k, sp_lead_dup,
    sp_lead_synth_100k, sp_lead_synth_10k, sp_sql_lead_dataset, wordnet_frames

`tests/unit/test_maintenance_exclusions.py` covers the default, the empty
string, named spaces, hand-edited whitespace and trailing commas, and naming a
space that is not there.

## Related

- `issues/081` — a benchmark measured against a configuration nobody recorded.
  Same shape, one level down: nobody records the statistics either.
- `issues/108` — a green suite measuring something other than what it names.

## Option 3 has a cost, and it is not the one the file predicted — 2026-08-22

The downside recorded above was philosophical: excluding the fixtures "diverges
from how a real space behaves". The actual cost is operational and sharper.

**Nothing re-ANALYZEs an excluded space.** The maintenance job was not only
disturbing the fixtures, it was also the thing keeping their statistics fresh.
Turn it off and they go stale, and a stale-statistics plan can be far worse
than a disturbed one.

Measured on `query.kgquery.growth_curve.eq[NY-10k]`, on unmodified code:

    before ANALYZE   6.62s   5,961,023 buffers
    after  ANALYZE   2.63s      46,244 buffers

46,244 is exactly the baseline value. The 129x was entirely stale statistics —
the same bistable plan this issue is about, just reached from the other
direction. Four of the seven genuine failures in a 2026-08-22 control run were
this, on three benches.

### So option 3 comes with an obligation

**ANALYZE the excluded fixtures explicitly** before a run whose numbers matter,
and certainly before promoting a baseline. Excluding them from maintenance
removes the accidental refresh; it does not remove the need for one.

    for sp in <the excluded spaces>; do
      ANALYZE every <sp>_* table
    done

The difference from option 2 — which was tried and reverted — is WHEN. Option 2
ANALYZEd before every recorded run, which randomised a bistable plan between
runs and emptied a 45 GB cache each time. This is a deliberate, occasional
refresh under an operator's control, at a moment of their choosing, not a
per-run reflex.