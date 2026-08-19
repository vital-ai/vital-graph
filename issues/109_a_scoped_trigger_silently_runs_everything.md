# A Scoped Trigger Silently Runs Everything

## Status: FIXED 2026-08-19 — refuse at request time, declare at registration

`POST /api/processes/trigger` takes `space_id`, documented as
"Target space (omit for auto-select)". `ProcessScheduler.trigger_now` honours it
by looking for `trigger_<process_type>` on the handler:

    if space_id:
        trigger_method = getattr(handler, f"trigger_{process_type}", None)
        if callable(trigger_method):
            return await trigger_method(space_id)
    # Fallback: call the handler's run()
    return await handler.run()

**When the method does not exist, the parameter is silently discarded** and the
whole sweep runs instead. The response is `triggered: true` either way, so
nothing distinguishes "I did what you asked" from "I ignored what you asked and
did far more". Measured on a stack with 17 spaces:

    process_type      with space_id, before      after
    analyze                       0.16 s         —          (had trigger_analyze)
    vacuum                        0.14 s         —          (had trigger_vacuum)
    stats_rebuild                 0.94 s         —          (had trigger_stats_rebuild)
    vector_reindex               46 s            —          (had trigger_vector_reindex)
    maintenance                 109 s          0.8 s        FIXED — added trigger_maintenance
    analytics                   227 s          ~1 s         FIXED — added trigger_analytics

`analytics` is the clearest case: `AnalyticsJob.trigger_compute(space_id)` already
did exactly the right work, under a name the dispatch never looks for.

## Why the dispatch is the defect, not the two jobs

Both instances were found by asking the API rather than by reading the code, and
only because a test timed out. The fallback is silent BY CONSTRUCTION:

* a handler that gains a new process type inherits the trap;
* the cost of being wrong scales with the number of spaces, so it is invisible on
  a small stack and a timeout on a large one — which is exactly how
  `tests/api::test_trigger_maintenance` behaved;
* `triggered: true` is returned for both outcomes, so no caller can detect it.

## The fix — options 1 and 3, because neither alone is enough

**Refuse, at request time.** `space_id` with no `trigger_<type>` now raises
`ProcessScheduler.ScopingUnsupported` and the endpoint answers `triggered: false`
with the reason and the way out:

    process_type='metrics' cannot be scoped to a space: its handler has no
    trigger_metrics(space_id). Omit space_id to run it for every space.

Option 2 (run the sweep, report `scoped: false`) was rejected: a caller that
named one space out of 17 is not asking for a best-effort superset, and the
227-second version of that superset is what made this visible. Refusing costs
7 ms and cannot be misread.

**Declare, at registration.** `register_job` records `supports_scope` and LOGS
the jobs that lack it, so the next job to gain a process type is stated at
startup rather than discovered by a caller:

    ProcessScheduler: job 'metrics_rollup' (process_type=metrics) has no
    trigger_metrics(space_id) — requests naming a space will be REFUSED
    rather than silently run against every space

It logs rather than failing startup, because a missing method is legitimate: a
job may have nothing per-space to do, and `register_job`'s own documented usage
passes a bound `job.run`, which cannot carry `trigger_*` at all. Failing hard
would force every such job to grow a stub whose only purpose is to satisfy the
check — and a stub that sweeps is this defect with extra steps.

Verified end to end on the test stack, the three answers now distinct:

    maintenance + space_id   0.54 s   triggered=true    (honoured)
    metrics     + space_id   0.008 s  triggered=false   ScopingUnsupported
    bogus       + space_id   0.006 s  triggered=false   UnknownProcessType

`tests/unit/test_scoped_trigger_is_honoured_or_refused.py` pins the registration
declaration for all three handler shapes, and that the two refusals stay separate
types — conflating them is the mistake documented directly below.

## A second, related conflation — FIXED 2026-08-19

`trigger_now` returned `None` for two different conditions, and the endpoint
reported both as "Lock busy or no handler registered for this process type":

* **lock busy** — transient, RETRY;
* **no handler** — permanent, FIX THE REQUEST.

`trigger_now` now raises `ProcessScheduler.UnknownProcessType`, naming the
registered types, and the busy path says the operation is already running:

    process_type=bogus_type   no handler registered for process_type='bogus_type';
                              registered types are: analytics, maintenance, metrics
    process_type=metrics      metrics is already running; another trigger holds the lock

**The fix corrected a wrong diagnosis of its own.** `metrics` was assumed to have
no handler, because the old message listed that possibility first. It HAS one —
the periodic collector — and its lock was simply held. The conflated message had
misled the reading of the very defect it was hiding, which is the argument for
splitting it: a message covering two causes will be read as whichever the reader
already suspects.

## Also drifted

`TriggerRequest.process_type` is documented as "Operation type: analyze, vacuum,
stats_rebuild, vector_reindex" while the endpoint accepts `maintenance`,
`analytics` and `metrics` as well.

## Related

- `issues/108` — the stale image that let two regressions live a day; this was
  found in the same week and by the same method: run it and measure
- `issues/105` — a failed write reported as success. Same family: an outcome the
  caller cannot distinguish from the one it asked for
