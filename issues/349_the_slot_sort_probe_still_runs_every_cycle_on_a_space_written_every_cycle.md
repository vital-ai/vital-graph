# 349 — The slot-sort probe still runs every cycle on a space that is written every cycle

## Status: OPEN, 2026-11-25. Measured on production (read-only); fix proposed, not started.

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

## To do

1. ~~Measure each step of a production cycle~~: done, above.
2. Implement the opt-in interval in `probe_data_changed` (or a wrapper), with the setting,
   and opt in the four probes listed.
3. Tests:
   - a space written every cycle runs each opted-in probe at most once per interval;
   - a probe left unconverged still runs on the next cycle;
   - `entity_slot_sort_coverage` and `stats_recompute` are unaffected;
   - a quiet space behaves as under `343`;
   - `test_probe_change_gate.py` still passes.
4. Separately, the stats recompute's budget overrun: check the budget before starting a
   space whose last recompute took longer than the remaining budget.
5. After deploy:
   - the pgss window again;
   - the `pg_stat_activity` sample again, for maintenance's share of wall time;
   - `_prewarm_log_summary.py` for the high-read passes.
