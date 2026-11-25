# 353 — The maintenance cycle log has no per-step timings

## Status: OPEN 2026-11-25. Not started.

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
