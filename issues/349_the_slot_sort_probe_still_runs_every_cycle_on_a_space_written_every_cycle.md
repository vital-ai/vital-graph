# 349 — The slot-sort probe still runs every cycle on a space that is written every cycle

## Status: FIXED 2026-11-25: opt-in minimum interval in `probe_data_changed`. Unit-tested (11 of the new tests fail on the unfixed code; unit suite 6,462, 0 failed) and VERIFIED on the vg test stack (`vgtest_core`, run on a scratch EC2 instance via `scripts/scratch_stack.sh`). DEPLOYED to production 2026-11-25 ~16:28 EST in `v0.0.105-prod` (task definition rev 99, built from `4e35573e`); production effect not yet measured.

Follow-up to `343`. That fix is deployed (2026-11-23) and works for quiet spaces. It
cannot help a space whose quads change between every two maintenance cycles. On
production that is the main KG space, the one where the probe costs most. The same holds
for every other probe behind the same write gate, so this issue covers the gate, not
only the slot-sort probe.

## Found

A one-hour pg_stat_statements window on production, read-only
(`test_scripts/perf/_pgss_window.py`), 2026-11-25 02:38 → 03:41 UTC, about 28 h after
the rollout. 1,822 s of execution over 3,765 s, +4 evictions (clean):

| statement | calls | mean | share of the hour |
|---|---:|---:|---:|
| `WITH slots AS …` (`entity_slot_sort_gap`), main KG space | 4 | 98 s | 21.5 % |
| same, other spaces | 3 | 26 s | 4.3 % |

Before the rollout the same statement was ~750 s/h, 51 % of a quiet hour
(2026-11-15), and 322 s a call on a weekday (2026-11-16). Now ~470 s/h: a real drop,
but it is still the top statement. 4 calls in an hour is one per 15-minute cycle.

Quad churn per space over 10 minutes (`pg_stat_user_tables`, 03:45 UTC): main KG space
61,426 rows; every other space 0. That space is written continuously.

The cycle log, from the production task's own log streams, 24 h before vs 24 h after the
rollout. (The log group also carries the test service's streams, `ecs-test/*`, which must
be filtered out.)

| | cycles | median | max | total |
|---|---:|---:|---:|---:|
| before | 77 | 756 s | 1,846 s | 17.5 h |
| after | 105 | 433 s | 1,479 s | 15.2 h |

Maintenance still runs about 63 % of the time on production. The test service, with
quiet spaces, went from a 102 s median to 0.7 s: there the `343` gate does all it was
meant to.

No `SUSPECTED SHORTFALL`, `repaired` or `edge table is short` line was logged in the
window. The exact split ran and found nothing to report.

## Where a production cycle's time goes (measured 2026-11-25)

The job does not log per-step timings, so this was measured by sampling
`pg_stat_activity` every 2 s, read-only. The window was 04:15 → 04:42 UTC: 780 samples,
26.4 min, ending early on a network timeout.

Client backends only; parallel workers are not counted twice. Statements are classified by
text; user traffic (inserts, SPARQL SELECTs, the write-path syncs, `pg_prewarm`) is
excluded.

- **A maintenance statement was running in 69 % of samples,** which matches the cycle
  log's ~63 %.
- Two ran at once in 6 %.
- So cycle time is statement time. There is no large gap of Python work or waiting
  between steps.

| statement | step | wall | share of maintenance | longest |
|---|---|---:|---:|---:|
| `WITH slots AS …` (`entity_slot_sort_gap`) | slot-sort shortfall (`343`) | 457 s | 42 % | 248 s |
| `CREATE TEMP TABLE _new_stats …` + `_new_pred_stats` / `_new_pred_objects` | stats recompute | 146 s | 13 % | 151 s |
| `WITH of_type AS …` (`entity_slot_sort_coverage` / `_all_types`) | slot-sort coverage (read-path markers) | 115 s | 10 % | 43 s |
| `ANALYZE` (term 98 s, quad 24 s, others) | analyze | 129 s | 12 % | 84 s |
| edge drift "expected" + `count(DISTINCT (subject_uuid, context_uuid))` + dangling endpoints | edge integrity | 144 s | 13 % | 23 s |
| `frame_slot` drift + frame counts | frame_slot integrity / backfill | 80 s | 7 % | 8 s |
| other | | 27 s | 2 % | |
| **total** | | **1,098 s** of 1,584 s wall | | |

Attributed by space, the slot-sort split was 405 s on the main KG space and 53 s on the
UW space. Most of every other probe's time was on the same two spaces.

Two notes on the table:
- The `of_type` statements are the coverage sweep, which records the per-type
  slot-sort coverage markers the read path's fast sort and filter paths consult, and
  releases whole-space blocks. They are **not** a diagnostic.
- The stats recompute has its own per-space schedule and a 120 s cycle budget. The budget
  is checked between spaces, so one space's recompute runs past it. That is the "DEFERRED
  … the 120s cycle budget went on 1 space(s)" log line, seen in 5 of the cycles read.

## Cause

`probe_data_changed` (`vitalgraph/process/maintenance_job.py:551`) is True whenever the
space's quad table has any insert, update or delete since the probe last ran. A space
written between every two cycles therefore opens every probe behind it every cycle:

| probe key | step | what it maintains |
|---|---|---|
| `entity_slot_sort_row_shortfall` (`~2917`) | slot-sort shortfall split + slot-seeded repair | a warning, and a repair of rows the write path missed. Nothing the read path consults (`slot_gaps` is never populated) |
| `edge_table_drift` (`~2268`) | edge integrity | warnings and repairs of edge-table drift |
| `frame_slot_integrity` (`~2534`) | frame_slot integrity | warnings |
| `frame_entity_drift` (`~2604`) | frame_slot backfill | a repair of rows the write path missed |
| `entity_slot_sort_coverage` (`~3060`) | slot-sort coverage | **read-path markers and blocks** |
| `stats_recompute` (`~2053`) | stats recompute | `rdf_stats`; already schedule-gated per space |

Not yet explained: the 3 runs at 26 s on other spaces in the pgss hour, when those spaces
showed no writes in the 10-minute churn sample. They may have been written earlier in that
hour.

## Proposal: a minimum interval per space, for the probes that only warn or repair

Add an optional minimum interval to the write gate, as a per-probe opt-in: a probe whose
gate opened less than *N* ago on this space does not run again yet, written or not. One
setting (e.g. `VG_MAINTENANCE_PROBE_MIN_INTERVAL_S`), default a few hours.

- **Opt in:**
  - `entity_slot_sort_row_shortfall`;
  - `edge_table_drift`;
  - `frame_slot_integrity`;
  - `frame_entity_drift`.

  Each of these only produces warnings and repairs rows that the write path keeps in sync
  itself. A delay of up to *N* delays a warning, or a repair of a write-path miss. No read
  depends on the probe having run.
- **Leave out:**
  - `entity_slot_sort_coverage`: it sets the markers and blocks that decide whether the
    fast sort and filter paths serve a type. Delaying it can serve a fast path on stale
    coverage, which is a correctness question. It needs its own answer: incremental
    coverage, or a cheaper check. That is not this issue.
  - `stats_recompute`: already has its schedule.
- **Keep the unconverged override:** a probe whose last pass repaired rows, or failed
  partway, still runs on the next cycle regardless of the interval. `343`'s convergence
  rule is unchanged.
- The `ANALYZE` step and the coverage sweep are not touched.

**Expected effect,** from the measured cycle above:
- Removed: the four opted-in probes, ~680 s of the 1,098 s (62 %) of maintenance statement
  time in that window.
- Production maintenance time would drop from ~69 % of wall to roughly 25-30 %.
- What remains: the stats recompute, the coverage sweep and `ANALYZE`.

This is one 26-minute window. It includes one slot-sort split of 248 s (the pgss mean was
98 s), so it may overstate that probe's share somewhat. Measure again after the change.

**Also fixes** the main contributor to prewarm eviction: 93 % of the prewarm passes that
re-read >= 30 % of the cap fell inside a maintenance cycle (`issues/346`).

Alternatives, for later:
- Bound each split to the subjects written since its last run, using the write log where a
  space has one. Cost would then track the write rate, not the space size.
- Make the shortfall and drift exact at write time. That's the largest change, the same
  direction as the durable `344` fix.

## Fix

`vitalgraph/process/maintenance_job.py`, in `probe_data_changed` itself, so every call
site gets it with no change of its own:

- `PROBE_MIN_INTERVAL_S`, from `VG_MAINTENANCE_PROBE_MIN_INTERVAL_S`. The default is
  21600 (6 h), the same as the edge-fanout refresh interval. 0 turns it off, which is
  `343`'s behaviour exactly.
- `INTERVAL_GATED_PROBES` lists the four probes above. A probe in it whose gate opened
  less than the interval ago on this space returns False, written or not.
- The watermark is not advanced while the interval holds a probe, so writes made during
  the interval still count when it ends. With no write, nothing runs after the interval
  either.
- Unconverged work still runs: a probe whose last pass repaired rows or failed partway
  opens every cycle. The interval counts from the last time the gate opened for any
  reason, including an unreadable counter.
- In memory and per process, like the rest of the gate, so a restart runs each probe once.

Not changed:
- `entity_slot_sort_coverage` and `stats_recompute`, which still open on any write.
- The `ANALYZE` step.

**To-do 4 dropped.** The stats recompute "overrun" is by design. The budget is checked
before starting each space, and a recompute is one transaction, so the first due space
always runs and the rest are deferred, not dropped. Checking the last duration first would
move the time between cycles, not remove it.

## Tests

- `tests/unit/test_probe_min_interval.py` (new, 13), on `probe_data_changed` with a fake
  clock and watermark:
  - the opted-in set (and that coverage and stats are not in it);
  - each of the four waits out the interval and then sees the write made during it;
  - no write means no run after the interval;
  - coverage and stats still reopen on any write;
  - unconverged work still runs inside the interval;
  - the interval is per space;
  - 0 turns it off;
  - an unreadable counter does not defeat the interval;
  - the 6 h default.
- `tests/unit/test_slot_sort_shortfall_gate.py`, which drives the real
  `_run_entity_slot_sort_integrity` through a fake pool, gets a fake clock:
  - `test_a_write_reopens_it` became `…_once_the_interval_has_passed`;
  - new `test_a_space_written_every_cycle_runs_once_per_interval` covers the production
    case: a write before every 15-minute cycle over two intervals gives 2 splits, where
    `343` alone gave 48.
  - The repair, failed-pass and timeout tests pass unchanged.
- Negative control: both files against `HEAD` (`834176ab`) in a throwaway copy. 11 fail;
  the rest pin behaviour that is unchanged.
- Unit suite: 6,462 tests, 0 failed, 17 skipped.

## To do

1. ~~Measure each step of a production cycle~~: done, above.
2. ~~Implement the opt-in interval~~: done (Fix).
3. ~~Tests~~: done.
4. ~~Stats recompute budget~~: dropped, see Fix.
5. ~~Run on the vg test stack~~: done, below.
6. After deploy:
   - the pgss window again: `WITH slots AS` on the main KG space from 4 calls an hour to
     about one per 6 h;
   - the `pg_stat_activity` sample again, for maintenance's share of wall time;
   - `_prewarm_log_summary.py` for the high-read passes.

## Verified on the vg test stack (2026-11-25)

The test stack was built from the working tree on a scratch EC2 instance (`r8g.2xlarge`,
`scripts/scratch_stack.sh`), on the `vgtest_core` volume restored from its snapshot. The
local Mac was swapping too hard to run it.

`test_scripts/debug/_issue349_interval_verify.py`, run inside the app container:
- It drives the real `_run_edge_integrity`, `_run_frame_slot_integrity`,
  `_run_frame_slot_backfill` and `_run_entity_slot_sort_integrity`.
- It uses the real 6 h default and a fake clock.
- It writes one quad (inserted and deleted) before cycles 2 and 3.
- It ran on two spaces the app's MaintenanceJob excludes.

| cycle | `sp_lead_synth_10k` | `sp_lead_types` |
|---|---|---|
| 1 cold | 43.22 s: split, coverage, edge drift, frame drift ×2 | 8.85 s: same |
| 2 written, +15 min | **0.15 s: coverage only** | **0.03 s: coverage only** |
| 3 written, +15 min | 0.15 s: coverage only | 0.03 s: coverage only |
| 4 no new write, interval passed | 7.56 s: split, edge drift, frame drift ×2 | 1.28 s: same |
| 5 no write, interval passed again | 0.03 s: nothing | 0.01 s: nothing |

Verdict PASS on both:
- The opted-in probes are held inside the interval despite writes.
- The writes made during the interval count once it ends (cycle 4).
- With no write, nothing runs.
- The coverage sweep, not opted in, still runs on every write.

Under `343` alone, cycles 2 and 3 would each have rerun the split and the drift probes.

