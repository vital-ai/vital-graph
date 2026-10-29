# 278 — Gen-2 GC pauses tripled after the 2026-10-17 releases

## Status: OPEN — the 60 s timer is gone (269, verified on production 2026-10-29). Remaining: whether the natural gen-2 collections need a second `gc.freeze()` after warm-up, decided at the 6-hour read with memory (RSS) alongside.

## 2026-10-28: the minute timer is gone

Every pause in the table below is one of `issues/269`'s timed full collections:
VitalSigns' background thread calling `gc.collect()` every 60 s, now stopped at
startup. That removes the pauses' FREQUENCY; what this issue measured is their
LENGTH, which is the cost of scanning the heap that is not frozen.

What the vg test stack shows for that length (census, idle server, ~100,000
referents unfrozen):

* a full collection run right after the census walked the heap: 8-19 ms;
* one run first, on the heap as the requests left it: 45-214 ms, cpu = wall.

So the scan is cheap and the time is touching cold memory. The local numbers
are inflated: the Mac was 33 GB into swap, under the Docker VM. Production has
no swap but the same shape: a cache filled over six hours (more cold objects) is
consistent with the climb.

Without the timer, CPython runs a full collection only when the objects
promoted since the last one reach 25 % of the long-lived heap, so these become
rare, and rarer as the heap grows. Under load the vg test stack still shows
natural gen-2 collections that free tens of thousands of objects, which is the
collector doing its job.

**After deploy:** count `GC PAUSE: gen2` per task-hour on production streams
(`ecs/vitalgraph/` prefix) against the table below. The line now names the
thread and the CPU time. If long pauses remain, set `VG_HEAP_CENSUS_INTERVAL_S=900`.
Each pass now also logs a cold and a warm full collection, the referent total,
and the widest objects.

**Related:** `issues/269` (the once-a-minute gen-2 collection, ~160 ms then),
the event-loop monitor (`vitalgraph/utils/event_loop_monitor.py`) that logs the
pauses, the startup `gc.freeze()` in `vitalgraph/impl/vitalgraphapp_impl.py`.

## What production shows

`/ecs/vitalgraph-prod`, production streams only (`ecs/vitalgraph/…`), `GC PAUSE:
gen2` lines:

| day (UTC) | gen-2 pauses | median | p90 | max |
|---|---|---|---|---|
| Oct 12 | 1,863 | 160 ms | 180 | 226 |
| Oct 13 | 3,062 | 154 ms | 170 | 231 |
| Oct 15 | 3,939 | 156 ms | 175 | 242 |
| Oct 16 | 4,499 | 167 ms | 183 | 268 |
| Oct 17 | 3,880 | 185 ms | 300 | 440 |
| **Oct 18** | 3,651 | **483 ms** | 676 | 777 |
| **Oct 19** (to 10:00) | 1,194 | **504 ms** | 548 | 643 |

Each pause collects a few dozen objects (37-114 on Oct 19) — the time is the
scan, not the garbage. Each one stops the task, so a request that lands in a
pause waits up to half a second; the same pauses are most of the ~85
`EVENT LOOP STALL` warnings per task per hour.

**The shape, by task (2-hour medians):** every task boots near 140 ms. Before
Oct 17 the tasks stayed flat at ~185 ms for days. Since then each task climbs
for about six hours and levels off:

| boot (UTC) | version | climb |
|---|---|---|
| Oct 17 12:35 | v0.0.86 | ~145 ms for 3 h (replaced) |
| Oct 17 15:25 | v0.0.87 | ~130 ms for 1 h (replaced; too short to tell) |
| Oct 17 16:36 | v0.0.88 | 145 → 370 ms in 4 h |
| Oct 17 21:37 | v0.0.89 | 209 → 649 ms in 8 h |
| Oct 18 12:43 | (current) | 170 → 290 → 440 → 480-545 ms, flat from ~6 h |

A climb that levels off is a BOUNDED structure filling to its cap — a cache —
not a leak. The startup freeze is unchanged (646,3xx objects frozen at every
boot), so the growth is objects that became long-lived after startup.

**Two candidate causes, not yet separated:** code in v0.0.88, or the workload
that began the same evening — the nurture-action cleanup (from ~17:30 on Oct 17,
many entity reads and deletes) and the restarted lead backfill. Either can fill
a cache the old traffic never filled.

## The diagnostic

`vitalgraph/process/heap_census_job.py`, registered only when
`VG_HEAP_CENSUS_INTERVAL_S` > 0, as a `single_runner` job so it runs on one
task. Each pass logs:

* **types** — tracked objects by type (`gc.get_objects()`, which excludes the
  frozen set: exactly what a gen-2 collection walks), and growth since the last
  pass;
* **holders** — the largest containers reachable by attribute from the
  `vitalgraph` modules and the app instance, named by path, with growth;
* **kinds** — the same summed by holder type and attribute, so many small caches
  (one per pooled connection, one per space) show as one row.

Why both: a cache built before the startup `gc.freeze()` is in the permanent
generation, and `gc.get_objects()` / `gc.get_referrers()` do not see it — only
its later entries. The type count says WHAT grows; the attribute walk names the
holder whatever its generation.

A pass costs about one gen-2 collection (0.3-0.5 s on the test stack's server);
the duration is in its log line.

## Production

1. Release, then set `VG_HEAP_CENSUS_INTERVAL_S=900` on the production service.
2. After 6-8 hours (past the climb), read `heap census #` lines: the holder or
   kind whose length tracks the pause growth is the cause.
3. Fix it (cap, smaller entries, or move it off the GC's path), then set the
   interval back to 0.

## Verification

`tests/unit/test_heap_census_names_the_growing_holder.py` (6): a cache frozen at
startup and filled afterwards is named by path with its growth; `__slots__`,
short containers and `lru_cache` functions are reached; a big container is
measured, not entered; extra roots are walked; many small caches add up by kind;
the job is off by default and single-runner. On the vg test stack the census
registers at a 60 s interval and reports the server's heap under API load.

## Production, first hour after v0.0.97 (2026-10-29)

Both new tasks, 14:45-15:50Z steady state, new-format lines only
(`"GC PAUSE" "cpu"`): about **44 gen-2 pauses an hour per task at ~190 ms**,
irregular, CPU = wall, so **~8 s of pause an hour per task**. On Oct 18-19 it was
~60 x ~480 ms ~= 29 s an hour per task: already ~3.5x less.

Lengths are still climbing (one task 142 -> 194 ms in its first 23 min), as this
issue recorded for every task: ~6 hours to level off. **Decide at 6 h+**, on
pause seconds per task-hour, and with RSS over the same window: a second
`gc.freeze()` after warm-up would shorten the scans, but anything it freezes
that later becomes cyclic garbage is never collected.
