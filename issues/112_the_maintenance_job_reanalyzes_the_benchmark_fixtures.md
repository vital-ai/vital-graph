# A Perf "Regression" With Identical Code: the App Re-ANALYZEs the Fixtures

## Status: EXPLAINED 2026-08-20 — not a code regression; the mitigation is a decision

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

## Related

- `issues/081` — a benchmark measured against a configuration nobody recorded.
  Same shape, one level down: nobody records the statistics either.
- `issues/108` — a green suite measuring something other than what it names.
