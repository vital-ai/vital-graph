# 269 — A full gen-2 garbage collection every 60 seconds freezes each task for ~150 ms

## Status: RESOLVED — released in v0.0.97; verified on production 2026-10-29: the 60 s forced collection is gone.
##
## Was: FIXED 2026-10-28 — the trigger is VitalSigns' 60 s `gc.collect()` thread, stopped at server startup. Not yet released; confirm in production logs after deploy.

## Cause (2026-10-28)

The `VitalSigns` singleton (`vital_ai_vitalsigns/vitalsigns.py`, 0.1.55) starts a
daemon thread, `BackgroundTaskMixin.background_task`, whose tick calls
`gc.collect()` — a FULL collection — every `GC_INTERVAL_SECONDS = 60`. Its
purpose there is to clear GraphObject reference cycles sooner than CPython's own
gen-2 trigger. In the server it is the whole of this issue: a full collection on
a timer, holding the GIL, finding a few hundred dead objects.

How it was found, on the vg test stack: the GC-pause line now names the thread
and the thread's own CPU time. Every 60 s pause was `thread Thread-1
(background_task)` with cpu = wall (scanning, not waiting). The earlier search
missed it because it grepped `vitalgraph/` only.

**Fix.** `startup_event` (`vitalgraph/impl/vitalgraphapp_impl.py`) calls
`VitalSigns().stop()` before the startup `gc.freeze()`. CPython's own collector
still clears cycles.

**Measured, vg test stack, idle server (same image, before / after):** before,
an automatic gen-2 every 60.2 s, 101-288 ms (cpu 104-214 ms). After, no
automatic gen-2 collection in 10 minutes; the only full collections were the
heap census's own.

**Related:** the event-loop monitor (`vitalgraph/utils/event_loop_monitor.py`) that
reports it; the startup `gc.freeze()` in `vitalgraph/impl/vitalgraphapp_impl.py`.

## What production shows

`/ecs/vitalgraph-prod`, production streams only (`ecs/vitalgraph/…`; the AWS test
env writes `ecs-test/…` into the same group, see below), 2026-10-12 03:21-16:08 UTC:

| | per task |
|---|---|
| gen-2 collections | 815 and 807 in ~12.8 h |
| interval | **60.1-60.2 s, on both tasks** (e.g. 12:00:56.02, 12:01:56.17, 12:02:56.34, ... on one task) |
| pause | 118-237 ms, median 164 ms (gen 2 only; no gen-0/1 pause crosses the 100 ms report threshold) |
| objects collected per pause | median 350, p90 951, max 3,284; uncollectable 0 |
| `EVENT LOOP STALL` reports | 1,813 over both tasks: 100-564 ms, median 151 ms, none > 1 s; the same pauses seen from the loop |

So every minute each task stops serving for ~150 ms to scan a large heap and find
a few hundred dead objects. Nothing is logged in the 1.5 s before each pause.

**Not a regression.** Same 13-hour window, production streams only: GC pauses
1,530 (Oct 10, v0.0.78) / 1,613 (Oct 11, v0.0.78) / 1,623 (Oct 12, v0.0.85).
Stalls rose 1,292 / 1,538 / 1,813, tracking the new KG-writer traffic, at the same
size.

**The startup freeze is already there.** Both tasks log `gc.freeze(): 639,604
gen-2 objects frozen` and `GC thresholds: gen0=700, gen1=10, gen2=10` at boot. So
the scan cost is objects that became long-lived AFTER startup (caches filling,
pools, compiled plans), not the startup set.

## The trigger was not known (as of 2026-10-12)

The exact 60.15 s cadence on both tasks looks like a timer, not organic
allocation. Checked and ruled out:

- VitalGraph's own `gc.collect()` calls are all shutdown paths
  (`utils/aggressive_cleanup.py`, `utils/resource_manager.py`) plus the one before
  the startup freeze.
- The only 60 s loop found in VitalGraph, the pool monitor
  (`db/pool.py`, `POOL_MONITOR_INTERVAL = 60.0`), only reads pool counters.
- No `gc.get_objects`, `tracemalloc` or memory sampling elsewhere in `vitalgraph/`.

Open candidates: a dependency running a 60 s loop that allocates enough to cross
the gen-2 threshold each minute, or one that calls `gc.collect()` itself.

## Next steps

1. **Identify the trigger.** In the GC callback (`event_loop_monitor`), on
   `phase == "start"` for generation 2, log `traceback.extract_stack()` (a few
   frames) once per N collections. An explicit `gc.collect()` shows its caller; an
   automatic collection shows the allocation site that tipped the threshold. One
   deploy, a few minutes of logs.
2. **Then fix by cause:**
   - an explicit periodic `gc.collect()` in a dependency → disable or lengthen it;
   - allocation-driven → re-run `gc.freeze()` once caches have warmed (e.g. after
     the first maintenance cycle), and/or raise the gen-2 threshold
     (`gc.set_threshold(700, 10, 50)`), then measure pause count and size again.
3. **Measure before and after** with the same window and the production-only
   stream filter: count, median and max pause, and the `EVENT LOOP STALL` count.

## Note: the test env logs into the production log group

The AWS test environment's VitalGraph task writes into `/ecs/vitalgraph-prod`
under stream prefix `ecs-test/`. It contributed 1,909 of the 8,373 warnings in
the window above, including all the test KG space's lines. Any production log
analysis must filter on `--log-stream-name-prefix ecs/vitalgraph/`. A separate
log group for the test task definition belongs to the deploy repo.

## Verified on production, 2026-10-29

Production, v0.0.97 (live 2026-10-29 14:23Z), checked read-only in CloudWatch `/ecs/vitalgraph-prod`, streams `ecs/vitalgraph/`, scoped to the two new tasks (the old tasks drained until ~14:29 and their lines are indistinguishable for this message).

- Both new tasks log `VitalSigns periodic gc.collect() thread stopped` at boot.
- Every gen-2 pause since is on `MainThread` or `uvloop_0` (never
  `background_task`), at IRREGULAR intervals (5-94 s apart), with CPU = wall:
  natural, allocation-triggered collections. No 60 s cadence.
- What remains is the pause LENGTH and the natural rate, tracked in
  `issues/278`.
