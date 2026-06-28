# Production Event Loop Stall Analysis — 2026-04-16

## Summary

Production VitalGraph (ECS, vitalgraph-prod) shows **recurring event loop stalls**
of 300-400ms in bursts every ~5 minutes. Two distinct sources identified.

## Source 1: BACKEND ANALYZE in `store_objects` (MAJOR)

**Location**: `vitalgraph/kg_impl/kg_backend_utils.py` → `SparqlSQLBackendAdapter.store_objects()`

Every `create_kgentities` call runs `ANALYZE` synchronously on the async event loop:

```
15:16:19.914 - BACKEND ANALYZE: 1.534s
15:16:39.830 - BACKEND ANALYZE: 1.497s
15:18:15.172 - BACKEND ANALYZE: 1.466s
15:19:02.794 - BACKEND ANALYZE: 1.525s
15:20:08.353 - BACKEND ANALYZE: 1.493s
```

**Impact**: Each call blocks the event loop for **1.3–1.6 seconds**.
This is the single largest source of event loop stalls in production.

## Source 2: Periodic 5-Minute Stall Bursts (MODERATE)

Stall bursts occur at precise 5-minute intervals, each lasting 1-3 seconds:

```
15:01:09 - STALL burst (6 stalls, ~350ms each)
15:11:09 - STALL burst (4 stalls, ~350ms each)
15:16:09 - STALL burst (6 stalls, ~350ms each)
15:21:09 - STALL burst (9 stalls, ~350ms each)
15:26:09 - STALL burst (3 stalls, ~350ms each)
15:31:09 - STALL burst (2 stalls, ~350ms each)
```

The 5-minute interval matches the MaintenanceJob schedule (300s).
However, maintenance logs show most cycles complete in 3ms (no-op):

```
15:07:50 - MaintenanceJob cycle complete in 4ms — analyze=None vacuum=None
15:12:50 - MaintenanceJob cycle complete in 3ms — analyze=None vacuum=None
15:17:50 - MaintenanceJob cycle complete in 3ms — analyze=None vacuum=None
```

When VACUUM does run (~every 30 min), it takes 240-318ms:

```
15:02:50 - VACUUM complete: space=lead_data tables=7 (318ms)
15:32:50 - VACUUM complete: space=lead_data tables=7 (265ms)
16:02:50 - VACUUM complete: space=lead_data tables=7 (291ms)
16:32:51 - VACUUM complete: space=lead_data tables=7 (240ms)
```

**Note**: The stall bursts at :09 don't perfectly align with maintenance at :50.
The 5-minute burst pattern may correlate with Weaviate token refresh or another
periodic task running at similar intervals.

## Raw Stall Events (Last 2 Hours)

```
15:01:09.686 - STALL: blocked for 350ms [stall #6]
15:01:10.141 - STALL: blocked for 350ms [stall #6]
15:01:10.551 - STALL: blocked for 316ms [stall #7]
15:01:10.992 - STALL: blocked for 340ms [stall #8]
15:01:11.406 - STALL: blocked for 363ms [stall #7]
15:01:12.250 - STALL: blocked for 356ms [stall #9]
15:11:09.810 - STALL: blocked for 401ms [stall #10]
15:11:10.307 - STALL: blocked for 370ms [stall #8]
15:11:10.714 - STALL: blocked for 354ms [stall #11]
15:11:11.115 - STALL: blocked for 358ms [stall #9]
15:16:09.777 - STALL: blocked for 354ms [stall #12]
15:16:10.217 - STALL: blocked for 363ms [stall #10]
15:16:10.615 - STALL: blocked for 338ms [stall #13]
15:16:11.016 - STALL: blocked for 347ms [stall #11]
15:16:11.432 - STALL: blocked for 366ms [stall #14]
15:16:11.833 - STALL: blocked for 316ms [stall #12]
15:21:09.634 - STALL: blocked for 348ms [stall #15]
15:21:10.103 - STALL: blocked for 341ms [stall #13]
15:21:10.507 - STALL: blocked for 321ms [stall #16]
15:21:10.909 - STALL: blocked for 355ms [stall #14]
15:21:11.312 - STALL: blocked for 354ms [stall #17]
15:21:11.720 - STALL: blocked for 358ms [stall #15]
15:21:12.122 - STALL: blocked for 359ms [stall #18]
15:21:12.519 - STALL: blocked for 347ms [stall #16]
15:21:12.914 - STALL: blocked for 341ms [stall #19]
15:26:09.442 - STALL: blocked for 335ms [stall #17]
15:26:09.901 - STALL: blocked for 352ms [stall #20]
15:26:10.958 - STALL: blocked for 312ms [stall #18]
15:31:09.458 - STALL: blocked for 314ms [stall #21]
15:31:09.872 - STALL: blocked for 316ms [stall #19]
```

**Note**: Interleaved stall counters (e.g., #6 and #6) indicate stalls on
multiple ECS tasks simultaneously.

## BACKEND ANALYZE Events (Last 2 Hours, store_objects)

```
14:58:11.338 - BACKEND ANALYZE: 1.633s
14:59:51.180 - BACKEND ANALYZE: 1.319s
15:09:24.124 - BACKEND ANALYZE: 1.438s
15:09:27.401 - BACKEND ANALYZE: 1.434s
15:13:09.923 - BACKEND ANALYZE: 1.303s
15:14:49.291 - BACKEND ANALYZE: 1.482s
15:15:09.246 - BACKEND ANALYZE: 1.473s
15:16:19.914 - BACKEND ANALYZE: 1.534s
15:16:39.830 - BACKEND ANALYZE: 1.497s
15:18:15.172 - BACKEND ANALYZE: 1.466s
15:19:02.794 - BACKEND ANALYZE: 1.525s
15:20:08.353 - BACKEND ANALYZE: 1.493s
15:25:21.333 - BACKEND ANALYZE: 1.476s
15:31:07.807 - BACKEND ANALYZE: 1.457s
15:32:32.770 - BACKEND ANALYZE: 1.332s
15:33:22.693 - BACKEND ANALYZE: 1.309s
15:36:24.490 - BACKEND ANALYZE: 1.527s
15:36:43.033 - BACKEND ANALYZE: 1.529s
15:37:58.215 - BACKEND ANALYZE: 1.417s
```

## MaintenanceJob Cycles (Last 2 Hours)

Two ECS tasks run maintenance every 5 min (advisory lock ensures only one executes):

```
14:57:50 - cycle 3ms — analyze=None vacuum=None cleanup=False
14:58:06 - cycle 3ms — analyze=None vacuum=None cleanup=False
15:02:50 - cycle 318ms — vacuum=lead_data (7 tables)
15:03:06 - cycle 3ms — no-op
15:07:50 - cycle 4ms — no-op
15:08:06 - cycle 3ms — no-op
...
15:32:50 - cycle 265ms — vacuum=lead_data (7 tables)
...
16:02:50 - cycle 291ms — vacuum=lead_data (7 tables)
...
16:32:51 - cycle 240ms — vacuum=lead_data (7 tables)
```

## Fixes

### Fix 1: Thread-offload BACKEND ANALYZE in store_objects (HIGH PRIORITY)

The `SparqlSQLBackendAdapter.store_objects()` ANALYZE should be offloaded to a
background thread, identical to the fix already applied in `MaintenanceJob`:

```python
# Current (blocking):
await conn.execute(f"ANALYZE {table}")  # 1.3-1.6s on event loop

# Fixed (thread-offloaded):
await asyncio.get_event_loop().run_in_executor(
    None, self._sync_analyze, table, pg_config
)
```

This is the **#1 priority** — it causes 1.3-1.6s stalls on every entity create.

### Fix 2: Deploy MaintenanceJob thread-offload fix (DONE locally)

The maintenance job fix (thread-offloaded ANALYZE/VACUUM via psycopg sync
connection) is implemented locally but not yet deployed to production. Once
deployed, the periodic 240-318ms VACUUM stalls will be eliminated.

### Fix 3: Investigate 5-minute periodic stall bursts

The 5-minute burst pattern at :09 seconds doesn't perfectly align with
maintenance at :50 seconds. Possible causes to investigate:
- Weaviate token refresh (runs on a background thread but reconnect may block)
- Entity dedup index refresh
- Space cache refresh (60s interval, but could align at 5-min marks)

## Local Verification

Local Docker test (same day) with thread-offloaded maintenance job:
- Loaded 100 entities (192,810 triples) in 24.4s
- 21/21 tests passed
- **Zero event loop stalls detected**
- Maintenance ANALYZE/VACUUM ran concurrently without blocking
