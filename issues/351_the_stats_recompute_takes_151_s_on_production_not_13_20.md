# 351 — The stats recompute takes 151 s on production, not the 13-20 s its docstring records

## Status: OPEN 2026-11-25. Not started. Measured on production, read-only.

## Found

From `349`'s `pg_stat_activity` sample of production cycles (2026-11-25, 04:15 → 04:42 UTC,
read-only):

| statement | wall | share of maintenance | longest |
|---|---:|---:|---:|
| `CREATE TEMP TABLE _new_stats …` + `_new_pred_stats` / `_new_pred_objects` | 146 s | 13 % | **151 s** |

- `_run_stats_recompute`'s docstring (`maintenance_job.py` ~2011): "Measured at 13-20 s
  across three production spaces, flat in quad count."
- `recompute_stats_tables`'s docstring: "the recovery … is running this again (~17 s)".

Production has grown since those were measured; the main KG space quad table is now 102 M
rows / 47 GB. One recompute has become a 151 s single statement.

It also does not fit the cycle budget:
- `STATS_RECOMPUTE_CYCLE_BUDGET_S` is 120 s and is checked *between* spaces, so one space
  overruns it.
- In 5 of the cycles read, the log says "DEFERRED … the 120s cycle budget went on 1
  space(s)".

## What is already known (from the code)

- **The pair aggregate is fenced to stream**, with `enable_hashagg = off` over
  `idx_{space}_quad_po` (`sync_stats_tables.py` ~269-320). As shipped it was a hash that
  spilled 3.5 GB on `sp_lead_synth_100k`; streaming took 48.2 s → 13.7 s.
- **`work_mem` is not the fix,** and was measured not to be: `work_mem = 1GB` gave 48.2 s,
  no change (`sync_stats_tables.py:284-287`). This corrects the
  "raise `work_mem` on the maintenance path" lever in the 2026-11-25 production status
  note.
- **The index is the precondition.** Without `idx_…_quad_po` the fence forces a sort of the
  whole quad table.

## Hypotheses, in the order to check

1. **It is simply the full ordered pass over `quad_po` at 102 M rows,** and IO-bound. If
   so the cost is linear in the space and only an incremental recompute changes it.
2. **The streamed plan is not the one production runs.** For example the index-only scan
   needs heap fetches because the visibility map is not all-visible on a continuously
   written table, or the sort comes back.
3. **The `row_number() OVER (PARTITION BY predicate, context ORDER BY count DESC)` window
   sorts all the groups.** That sort spills whatever the aggregate does. It would also
   contribute to the ~200 GB/day temp spill (production status note, watch item 1).

## First step (read-only on production)

- **The plan, without running it.** `EXPLAIN` (no `ANALYZE`) of the `_new_stats` SELECT
  on the main KG space, with `SET enable_hashagg = off` in the same session. This shows
  which plan runs and whether a sort sits above the aggregate.
- **Heap fetches and spill.** For the same table, `pg_class.relallvisible / relpages`, and
  `temp_blks_written` for this statement in the next pgss window (`_pgss_window.py`
  diffs it if the column is captured; check).
- **A local copy at production scale.** Repeat locally on the largest vg stack space:
  `EXPLAIN (ANALYZE, BUFFERS)` there is allowed.

## Options, after the measurement

- If it is (2): fix the plan. Accept it only when production's plan changes
  (`prod_explain_ab`; see the memory note on accepting plan fixes against the production
  plan).
- If it is (1) or (3): an incremental recompute, or a longer interval for the largest
  spaces. Note that `STATS_RECOMPUTE_INTERVAL_S` is 3600 per space, so the main KG space
  pays 151 s an hour now.
- Either way: correct both docstrings' timings.

## On production after `349` + `353` (2026-11-26): now the largest maintenance cost

13.3 h of `steps=` fields (deploy session), 03:46 → 17:00 UTC:

| step | runs | mean | max | total | share of maintenance | share of wall |
|---|---:|---:|---:|---:|---:|---:|
| `stats_recompute` | 24 | 380 s | 692 s | 9,109 s | **44 %** | ~19 % |

- **24 runs in 13.3 h is ~2 an hour.** The step recomputes each due space on its own
  hourly, hash-phased schedule.
- **Next read: the per-space split.** It is in `spaces=` as `stats_recompute[<space>]`. It
  shows whether the 692 s is the main KG space alone, or several due spaces landing in
  one cycle past the 120 s budget.
- **The first step above is still the read-only `EXPLAIN`.**
