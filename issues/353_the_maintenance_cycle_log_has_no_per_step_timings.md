# 353 — The maintenance cycle log has no per-step timings

## Status: FIXED 2026-11-25, per step and per space. Unit-tested (unit suite 6,472, 0 failed) and VERIFIED on the vg test stack (`vgtest_core`, scratch EC2, 2026-11-26). DEPLOYED to production 2026-11-26 in `v0.0.106-prod` (task definition rev 100); first production cycle carried both fields. `result_details` not done.

## Found

`MaintenanceJob`'s completion line (`maintenance_job.py` ~915) logs only the cycle total
and four flags:

    MaintenanceJob cycle complete in %.0fms — analyze=%s vacuum=%s vector_reindex=%s cleanup=%s

So the question "where does a production cycle's time go" could not be answered from the
logs. For `349` it took a 26-minute `pg_stat_activity` sampler against production, which:
- classified statements by their text;
- missed one statement at first (`_new_stats` was excluded by an unanchored match);
- ended early on a network timeout.

`350`, `351` and `352` each need the same answer again, and so does the remeasurement after
`349` deploys.

## Proposal

- Time every step of the cycle with `time.monotonic()`, accumulated per step name (and,
  for the per-space steps, per space).
- Emit them on the completion line, e.g. `steps=slot_split:98.1s(main),stats:151.0s,…`
  for any step over a threshold (1 s), or as one structured `extra=` dict.
- Also record the per-space breakdown in the process tracker's `result_details`, which
  is already written per cycle.

Small. No behaviour change, and one `try/finally` per step.

## Tests

- A unit test drives a cycle with stub steps of known duration on a fake clock. It
  checks that the completion line and the summary carry each step over the threshold,
  and omit the ones under it.
- An aborted cycle still reports the steps that ran before the failure.

## After deploy

A CloudWatch Logs Insights query over the production streams (`ecs/vitalgraph/*` only; the
group also carries `ecs-test/*`) then replaces the sampler for `349`'s remeasurement and
`350`-`352`'s first steps.

## Fix (2026-11-25)

- **`MaintenanceJob.run()` times every step it awaits** through `_timed`, on
  `_step_clock` (`time.monotonic`), with the time added in a `finally`.
  - The timings are in `summary["step_timings"]`.
  - `analyze` and `vacuum` are named with their space, e.g. `analyze(sp_x)`, because each
    runs on one space.
- **Both the completion line and the ABORTED line end with
  `steps=stats_recompute:151.0s,entity_slot_sort_integrity:98.0s,…,+9 under 1s`.**
  - Slowest first.
  - The threshold is `VG_MAINTENANCE_STEP_LOG_THRESHOLD_S`, default 1.
  - A step that raised is still counted, which is the one an operator needs.
- **Per space, inside a step**, with a second field, `spaces=slot_split[sp_main]:98.1s,slot_coverage[sp_main]:43.0s,…`.
  - It uses the same formatter and threshold.
  - `run()` sets a context variable for the cycle. The per-space loops iterate through
    `timed_spaces(part, space_ids)`: a generator that times each loop body. That is one
    changed line per loop, with no `continue` or `except` moved.
  - The loops:
    - `slot_split` and `slot_coverage`, which are the two halves of
      `entity_slot_sort_integrity` (`350`);
    - `stats_recompute` (`351`);
    - `edge_integrity`, `referential_sweep`, `frame_slot_integrity` and
      `frame_slot_backfill`.
  - Outside a cycle (a direct trigger, a test) nothing is recorded.
- **Not done: `result_details`.** The cycle has no tracker row of its own; each step writes
  its own.

Tests: `tests/unit/test_maintenance_step_timings.py`:
- every step is timed, and the slow ones are logged in order;
- an aborted cycle reports the steps that ran, including the failing one;
- the formatter;
- `timed_spaces` with `continue`, `break` and a raise;
- the real `_run_entity_slot_sort_integrity` with stubbed queries, which records split
  and coverage per space separately.

Logs Insights, once deployed (production streams only):

    fields @timestamp, @message
    | filter @logStream like /^ecs\/vitalgraph\// and @message like /cycle complete/
    | parse @message "steps=* spaces=*" as steps, spaces

## Verified on the vg test stack (2026-11-26)

`test_scripts/debug/_issue353_cycle_line_verify.py`, run in the rebuilt app container on
a scratch EC2 instance (`scripts/scratch_stack.sh`). It runs two real
`MaintenanceJob.run()` cycles over all 15 KG spaces, with the threshold at 0 so that every
entry is listed. **PASS.**

| | cycle 1 (fresh process, as after a deploy) | cycle 2 |
|---|---:|---:|
| wall | 268.7 s | 3.3 s |
| sum of `step_timings` | 268.7 s | 3.3 s |
| `steps=` / `spaces=` on the line | yes / yes | yes / yes |
| spaces with `slot_split[…]` and `slot_coverage[…]` | 15 / 15 | 15 / 15 |

- **Cycle 1's slowest steps:**
  - `entity_slot_sort_integrity:199.4s`;
  - `edge_integrity:37.2s`;
  - `grouping_self_link_check:12.2s`.
- **Cycle 1's slowest spaces:**
  - `slot_split[uw_prodshape]:85.1s` and `slot_split[uw_prodshape2]:85.1s`;
  - `slot_split[sp_graph_rel_10k]:20.7s`;
  - `edge_integrity[uw_prodshape]:14.7s`.

  This is the split separated from the coverage sweep, and named by space. Before this
  only a `pg_stat_activity` sample could show it.
- **Cycle 2:** the 349 interval holds every split at 0.0 s. Coverage still runs, and the
  largest step is the hourly `grouping_self_link_check` at 3.0 s.

## On production (2026-11-26, deploy session's report)

`v0.0.106-prod` (task definition rev 100, 2/2 tasks). The first cycle after the restart
ended 04:28 UTC after 1,923 s. That is the expected boot cycle: the in-memory gate was
reset, so every probe ran once. Its line carried both fields:

    steps=entity_slot_sort_integrity:996.5s,edge_integrity:369.0s,grouping_self_link_check:363.5s,frame_slot_integrity:53.2s,graph_registration_check:52.5s,…
    spaces=slot_split[<main KG>]:359.8s,edge_integrity[<main KG>]:162.4s,slot_split[<lead data>]:109.9s,slot_coverage[<actions KG>]:106.5s,…,slot_coverage[<main KG>]:55.7s,slot_split[<actions KG>]:55.4s,…

Space ids are replaced by roles here. What the boot cycle shows:

- **The split and the coverage sweep are now separate, per space, in the log:**
  `slot_split[<main KG>]` 360 s against `slot_coverage[<main KG>]` 56 s. `349` holds the
  split for 6 h after this; the coverage sweep (`350`) is not held.
- **`grouping_self_link_check` took 363.5 s.** It is a REPORT-only watch, run at most
  hourly per space (`should_run_watch`, `VITALGRAPH_WATCH_INTERVAL_S`). The pgss window
  saw its `WITH targets … NOT EXISTS` counts at 55 s and 50 s. Not yet tracked by an issue;
  watch its share in steady-state cycles before opening one.
- **`edge_integrity` took 369 s.** It is gated by `349` and runs once per 6 h per space.
