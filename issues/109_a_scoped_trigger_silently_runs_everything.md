# A Scoped Trigger Silently Runs Everything

## Status: two instances FIXED 2026-08-19; the DISPATCH that produces them is open

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

**Options, none applied yet:**

1. **Refuse.** If `space_id` is given and no `trigger_<type>` exists, return
   `triggered: false` naming the types that support scoping. Honest, and it
   turns a silent 227-second sweep into an immediate answer.
2. **Report.** Run the sweep but say so — `scoped: false` in the response — so a
   caller can tell what happened.
3. **Require by convention.** A registration-time check that every job exposes
   `trigger_<its process_type>`, failing at startup rather than per request.

Option 3 is the only one that catches the NEXT job before it ships; options 1
and 2 make the current behaviour honest.

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
