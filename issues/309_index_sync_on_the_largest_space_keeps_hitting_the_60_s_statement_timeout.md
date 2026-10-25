# 309 — Index sync on the largest space keeps hitting production's 60 s statement timeout

## Status: OPEN — found in the production logs 2026-10-25; cause not yet measured.

**Related:** `issues/291` (the index-sync queue and its trigger), `issues/294`
(the consumer deadlock, fixed: 17 `DeadlockDetectedError` in the 29 h before
v0.0.96, 0 after), `issues/136` (the same RDS `statement_timeout = 60 s` killing
VACUUMs on the big quad table).

## Found

Production CloudWatch, `/ecs/vitalgraph-prod`, streams `ecs/vitalgraph/`, the
29 h after v0.0.96 went live (2026-10-24 08:41 EDT to 2026-10-25 08:37).
Extracts in `internal_data/prod_logs_20261025/` (gitignored).

The main KG space (76.2M quads, 37 GB with indexes, the largest) fails its
index sync continuously:

| message (`index_sync_worker`) | 29 h before v0.0.96 | 29 h after |
|---|---|---|
| `N subject(s) failed (attempt k), retrying in Ns: QueryCanceledError: canceling statement due to statement timeout` (WARNING, k < 5) | 1,313 | 893 |
| the same at ERROR (k >= 5) | 41 | 18 |
| `index sync sweep failed: TimeoutError` | 224 | 186 |
| `index sync consumer N on <space>: TimeoutError` | 5 | 9 |

- Every one of the 24 hours after the deploy has failures, about 50-85 an
  hour. Only that space appears.
- Batches of 100 subjects fail, and so do batches of 5, 13, 47 and 58, so a
  single statement can exceed 60 s whatever the batch size. That points at the
  statement's plan or the work per subject on this space, not at load.
- Retries back off 5 s, 10 s, ... 80 s, 160 s (attempt 6 seen) and never give
  up (`index_sync_worker.py`: ERROR from attempt 5). The queue is drained
  eventually: `vgs_<key>_index_sync_queue` for that space held **0 rows** at
  2026-10-25 ~08:45 (read-only check). So the search indexes LAG during write
  bursts, by minutes, rather than falling permanently behind. The repeated
  60 s statements are load on the shared instance meanwhile.

The same space's maintenance also times out:

| message | before | after |
|---|---|---|
| `aux-table ANALYZE(<space>) task failed` | 13 | 5 |
| `auto_analyze(<space>) task failed` | 0 | 3 |
| `edge_integrity: drift probe TIMED OUT for <space> (QueryCanceledError)` | 1 | 5 |

Not from v0.0.96: every index-sync line was present before the deploy, and
the counts fell after it.

## Other pre-existing noise in the same window (not this issue)

Recorded so it is not rediscovered as new. All present before v0.0.96, all
lower after: `auto_sync task failed` (323 -> 208), the segmentation worker's
`Error polling space` for every space (172 -> 149), `space_prewarm` failed
(42 -> 39), internal-pool `pool_wait` / `acquire timed out` (2,747 / 969 ->
1,922 / 770), event-loop stalls (6,388 -> 3,527) and GC pauses
(3,471 -> 2,948). The ERROR lines for `auto_sync` and the segmentation worker
carry no exception text after the colon, so their cause is not in the log;
that is a logging defect worth its own fix.

## Next

1. Identify the statement that times out. The warning names only the
   exception. Either log the statement (or its kind) with it, or reproduce on
   a copy of that space at prod scale and EXPLAIN the sync's queries for one
   batch.
2. Decide by what it is: a plan fix (a subject-batch lookup that scans), a
   per-session `statement_timeout` for the worker's own connection (as the
   loader and the `object_count` migration do, `issues/304`), or smaller work
   per statement.
3. Measure lag directly: the age of the oldest queued row over a write burst.
