# 305 — A value-histogram rebuild invalidates only the local process

## Status: RESOLVED 2026-10-28 (not yet released); verified on the vg test stack rebuilt for the fix (unit, DAWG conformance, integration and API suites, 0 failures) — reproduced first, then fixed in `resync_value_stats` itself. Was: OPEN, found by reading 2026-10-24, not reproduced.

**Related:** `issues/300` (the same defect for `rdf_stats` / `rdf_pred_stats`,
fixed), `issues/090` (the value histograms), `issues/264` (TRUNCATE blocking the
planner's stats reads), `issues/276` (a lost invalidation stream).

## Found

While fixing 300. `{space}_rdf_value_stats` has three writers, all
`resync_value_stats` (`sync_value_stats.py:62`):

| caller | invalidates locally | notifies other instances |
|---|---|---|
| `resync_all_auxiliary_tables` `resync_all.py:139` | yes, `:230` | yes, `:240` |
| bulk insert at or above `REBUILD_MIN_QUADS`, `sparql_sql_space_impl.py:1798` | yes, `:1804` | **no** |
| maintenance value-stats refresh, `maintenance_job.py:2087` | yes, after it | **no** |

Each server caches the histograms in `_value_stats_cache` (`generator.py:830`) and
its freshness verdicts in `sync_value_stats._probe_cache`, both for the life of
the process. `invalidate_stats_cache` drops both, and that is what the two
unnotified paths call, so only the process that ran the rebuild sees the new
histograms.

## Who is affected

**Single-instance deployments: no one.** The maintenance job runs in the server
process, and a bulk insert runs in whichever server took the request, so the local
invalidate reaches the only cache there is.

**With more than one serving instance**, the others keep the old histograms and
verdicts. Not checked: whether any install runs more than one instance per
database.

## How long, now that 300 is in

300's fix sends a `stats` NOTIFY from every `recompute_stats_tables`, and the
receiving handler calls `invalidate_stats_cache`, which drops the value histograms
too. So the window on other instances runs from the histogram rebuild to the next
recompute of that space:

- **Bulk insert:** the load changes data, so the next maintenance cycle recomputes
  and notifies. The window is about one cycle.
- **Maintenance refresh:** the same cycle runs `_run_stats_recompute`
  (`maintenance_job.py:801`) **before** `_run_value_stats_refresh` (`:806`). The
  recompute's NOTIFY therefore lands first. Another instance that plans a range
  query in between reloads the old histograms, and keeps them until the next
  recompute, which runs only when the space's data changes (`probe_data_changed`).
  For a space that goes quiet, that can be until restart.

The effect of a stale histogram is bounded by design. `apply_freshness` scales a
grown histogram or withdraws it on a shape change, so a stale one is less
accurate, not unsafe. This is a cost issue, not a correctness one.

## Also seen, not verified

- **The maintenance refresh is not atomic.** `resync_value_stats` TRUNCATEs, then
  inserts per predicate with `executemany`, and the maintenance caller wraps it in
  `maintenance_timeouts` only, which sets a timeout and opens no transaction. A
  load that lands mid-rebuild, in any process, would see an empty or partial table
  and cache it. The local invalidate afterwards repairs this process only.
- **TRUNCATE takes ACCESS EXCLUSIVE** (264's shape), and `load_value_stats`
  (`sync_value_stats.py:192`) reads with no `lock_timeout`. On the bulk path the
  rebuild runs on the write's connection and, presumably, inside its transaction,
  so a planner's histogram read would wait for the whole bulk write to commit.
  Check before acting on it.

## Fix (proposed)

The same shape as 300. In `resync_value_stats` itself:

1. Run it in one transaction, using `DELETE` rather than `TRUNCATE` (264's
   reasoning: readers keep the old rows under MVCC instead of blocking).
2. `pg_notify(CHANNEL_CACHE_INVALIDATE, {"cache_type": "stats", ...})` inside that
   transaction, so it is delivered at commit. The existing handler already drops the
   histograms and verdicts on `stats`, so no new cache type is needed.
3. A local `invalidate_stats_cache` after the transaction. The two call sites'
   own invalidates can then go.

Verify with a test like `test_stats_recompute_invalidates_cache.py`: a listener
hears it at commit and not on rollback. For the non-atomic claim, also have a
reader running during a maintenance-style rebuild assert it never sees an empty
table.

## Reproduced and fixed, 2026-10-28

`tests/integration/test_value_stats_rebuild_is_atomic_and_notifies.py`, 12
numeric predicates x 400 values, written first and run against the unchanged
code. All three claims held:

| claim | before |
|---|---|
| a reader during the rebuild sees an emptied / partial table | **271 of 284** concurrent reads saw fewer than the 396 rows the table holds before and after, min **0** |
| other processes are told | no `stats` NOTIFY at all |
| this process's cache is dropped | not by the function; only by two of its callers |

Fix, in `resync_value_stats` so no caller can skip it (300's shape):

1. One transaction; `DELETE` instead of `TRUNCATE`, so a reader keeps the old
   histograms under MVCC until COMMIT instead of blocking on ACCESS EXCLUSIVE or
   reading an empty table. This also settles the "bulk path makes a planner wait
   for the whole write" point: a DELETE does not block readers.
2. `pg_notify(CHANNEL_CACHE_INVALIDATE, {"cache_type": "stats", ...})` inside
   the transaction: delivered at COMMIT, dropped on rollback. The servers'
   existing handler drops the histograms and freshness verdicts on `stats`.
3. `invalidate_stats_cache(space_id)` after it, for this process.
4. The two probes that may fail (`rdf_pred_stats`, the quad-count fallback) run
   in savepoints, since a failed statement would now abort the rebuild.

After: the same test passes (0 short reads; NOTIFY heard at commit and not on
rollback; local cache dropped), with the existing value-stats unit and
integration tests. The callers' own invalidates are now redundant and harmless;
left in place.
