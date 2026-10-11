# 266 — Every backfill nudge forces a full, unmarked cycle, so a write burst rescans every space

## Status: FIXED 2026-10-11 (`85b5dfa3`, not yet released).
##
## Found 2026-10-10 while improving the backfill task's logging;
## measured on production 2026-10-11. Background-work cost, `239` territory.
## Not a correctness defect: the forced cycles find nothing and change nothing.

## What production shows

The backfill task wakes on a nudge. `nudge()` is called by the SPARQL insert and
update endpoints after every write (`sparql_insert_endpoint.py:144`,
`sparql_update_endpoint.py:116`) and by the import manager. Production, since
the 2026-10-01 deploy, wake-ups per day across both tasks:

| day | woken by nudge | safety-net polls |
|---|---|---|
| 10-01 .. 10-02 | 0 | 20, 96 |
| **10-03** | **1,067** | 92 |
| **10-04** | **572** | 90 |
| 10-05 .. 10-10 | 0 | 96 each |

Nudges are bursty, not constant. Ordinary traffic writes through the
kgentities endpoints, which do not nudge. The burst lines up with SPARQL
`/update` traffic (1,742 POSTs in the window) during the 2026-10-03 production
frame-grouping repair (`257`). Nudges by hour: 1,067 at 23:00 UTC (one every
3.4 s), then 376, 196, 34, ... into 10-04.

Pairing each "woken by nudge" with its "cycle complete", 2026-10-03 23:00 to
10-04 03:00 UTC:

```
forced cycles 1,639    wall time 2,516 s (42 min)
per cycle     min 0.45 s   p50 0.93 s   p90 1.73 s   max 73.48 s
"another instance holds the lock" skips: 123     batch failures: 7
```

**The 7 batch failures are the ones from the 2026-10-10 log review**: empty
`failed: ` messages at 23:09-00:41, which `e0828f8d` made log their exception
type. They fall inside this burst, where each was a batch scan run while a bulk
repair held the tables.

## Why each nudge costs a full cycle

`nudge()` sets `_force_full_check = True` (`backfill_server_properties_task.py`),
and a forced cycle ignores both of the gates `237` added:

- `_discover_graphs_cached` re-derives discovery, a `SELECT DISTINCT` over every
  space's quad table, instead of trusting the `quad_activity` cache;
- `_iteration` skips the `backfill_state.is_complete` check, so every graph gets
  a batch scan even when it was marked complete.

The flag is cleared only when a full cycle completes. So under a burst, every
cycle is forced: nudge → full forced cycle (~1 s) → idle → nudge 3 s later →
another full forced cycle. The force exists for a real reason
(`pg_stat_user_tables` lags commits, so a marker checked right after a nudge can
read "unchanged"), but it is honoured per NUDGE when it is only needed per
BURST. One forced cycle after the burst sees everything the burst wrote.

Both instances run the task, each doing the same forced discovery; only the
batch scan itself is single-flight (a per-graph advisory lock, hence the 123
skips).

## Fix

1. **Coalesce nudges.** After a forced cycle starts, further nudges within
   `BACKFILL_NUDGE_MIN_INTERVAL_S` (e.g. 30 s) leave the force armed, but the
   next forced cycle waits for the window to end. A burst of N writes then
   costs about burst-length / 30 s forced cycles instead of N. Stamping is
   already eventually consistent; it gains at most 30 s of delay, against a
   30-minute safety net.
2. **Scope the force to the space written.** The SPARQL endpoints and the
   import manager know the space. `nudge(space_id)` would bypass the cache and
   markers for that space only; the other spaces keep their gates.
   `NOTIFY` without a payload stays a force-all.

## Verifying

Locally, on the vg test stack: drive N SPARQL updates at one space a few seconds
apart and count forced cycles and the discovery/batch statements they issue,
before and after. On production after deploy: a SPARQL-update burst like
10-03's should show forced cycles at most every 30 s, and discovery only for the
written space.

## Fix, 2026-10-11

`backfill_server_properties_task.py`. The single `_force_full_check` flag is now
a PENDING force (set by nudges) and an ACTIVE one (snapshotted when a cycle
starts):

- **Coalesced.** A cycle takes the pending force at most once per
  `BACKFILL_NUDGE_MIN_INTERVAL_S` (default 30 s). A nudge inside the window stays
  pending; the idle loop sleeps out the rest of the window instead of waiting for
  another nudge, so the last write of a burst is not left to the 30-minute
  safety net.
- **Scoped.** `nudge(space_id)` bypasses the discovery cache and completion
  markers for that space only. The SPARQL insert/update endpoints and the import
  manager now pass the space. A nudge with no space, a `NOTIFY` with no payload,
  and startup still force every space.
- **A mid-cycle nudge is no longer lost.** The old flag was cleared at the end of
  every cycle, wiping a nudge that arrived during it, contrary to the comment
  beside it. A nudge now lands in pending and is taken by the next cycle.

Tests: `tests/unit/test_backfill_nudge_is_coalesced.py` (9). Replaying
production's burst (one nudge every 3.4 s for ten minutes, a cycle after each)
gives one forced cycle per 30 s window instead of one per nudge (176 nudges),
while still forcing once in every window. Plus scoping, a held nudge honoured
when its window ends, mid-cycle survival, `NOTIFY` payload scoping, startup
force-all, and that both endpoints name the space. The existing backfill tests
(`test_backfill_state.py`, `test_backfill_discovery_is_gated_on_writes.py`)
were ported to the new state.

Not measured live: forced-cycle counts under a real SPARQL burst on the test
stack. After deploy, a burst like 10-03's should show forced cycles at most every
30 s.
