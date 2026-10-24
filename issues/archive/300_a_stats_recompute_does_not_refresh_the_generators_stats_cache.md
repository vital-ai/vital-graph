# 300 — A stats recompute does not refresh the generator's stats cache

## Status: FIXED 2026-10-23 — verified on the vg test stack (rebuilt image); not yet released.

**Related:** `issues/142` (stats are recomputed, never accumulated), `issues/139`
(a corrupt `rdf_stats` repaired only by a rebuild), `issues/163` (the cache is keyed
by graph), `issues/276` (a lost invalidation stream), `issues/232` (process-local
caches on rename).

## Found

While inventorying which statistics tables the cardinality model reads (planning
for the planner extension). The generator caches each space's `rdf_stats` and
`rdf_pred_stats` in process memory, `_stats_cache` (`generator.py:283`), with no
TTL. Every writer of those two tables is `recompute_stats_tables`
(`sync_stats_tables.py:112`), and most of its callers never invalidated the cache.

The maintenance job runs **inside the server process**
(`vitalgraphapp_impl.py:548`), so the hourly recompute rewrote the tables under a
cache in the same process and left the cache as it was. A long-lived server kept
planning on the counts it loaded at the first query to each space (and graph lock),
until it restarted or something else happened to invalidate that space.

## Reproduced

`test_scripts/debug/_stats_cache_stale_after_recompute.py`, vg test stack (:8002 /
:5433). It uses a scratch space created and deleted through the API, and runs the
server's own code (the repo copy, not site-packages) in one process, as the server
does:

```
[1] db pred_stats=10  cache=10
[2] after _run_stats_recompute: db=60  cache=10
[3] after StatsRebuildOp:       db=100  cache=10
[4] after invalidate_stats_cache: db=100  cache=100
```

Steps 2 and 3 each wrote more quads and ran a recompute. The table moved from 10 to
60 to 100, and the cache stayed at 10 until step 4's explicit invalidate.

## Which writers invalidated (before the fix)

| caller of `recompute_stats_tables` | invalidates locally | notifies other instances |
|---|---|---|
| `MaintenanceJob._run_stats_recompute` (hourly, and `trigger maintenance`) `maintenance_job.py:1959` | **no** | **no** |
| `StatsRebuildOp` via `trigger stats_rebuild` (in the server) `maintenance_job.py:3156` | **no** | **no** |
| `StatsRebuildOp` via the admin CLI's rebuild-stats (**a separate process**) `vitalgraphdb_admin_cmd.py:825` | irrelevant — not the server | **no** |
| the three incremental imports, `data_import_impl.py:1024`, `:1254`, `:1486` | **no** (term cache only) | **no** |
| `bulk_export.py:263`, `partition_migrate.py:135` | **no** | **no** |
| `resync_all.py:134` (and so `import_ntriples_bulk`, `:792`) | yes, `:230` | yes, `notify_cache_invalidate("stats")`, `:240` |

The admin CLI row is the one a per-call-site local invalidate could never fix: that
process holds no cache anyone reads, so only a NOTIFY reaches the servers.

What did clear it elsewhere: a bulk insert above `REBUILD_MIN_QUADS`
(`sparql_sql_space_impl.py:1788`), the `CHANNEL_CACHE_INVALIDATE` handler
(`vitalgraphapp_impl.py:756`), `invalidate_all_stats_caches` on a lost
invalidation stream, a rename, and, incidentally, the maintenance value-stats
refresh (`maintenance_job.py:2064`) for the single most-drifted space per cycle. So
the worst case was a space that only receives small writes — which is the
production write pattern.

## Consequences (before the fix)

- Join ordering, the semi-join gate, the hop-wise and traversal decisions, and
  `absence_bounds` all read the cached counts. A space that grew after the server
  started was planned on its size at first query — the misestimate class 293 and 297
  measure, arriving from staleness instead of from the model.
- **The operator's repair for a corrupt `rdf_stats` (139) did not reach the serving
  process**, by either entry point. The table was fixed, the server kept the
  corrupt counts, and the repair looked as if it did nothing until a restart.
- Not measured: how stale production's caches got. Deploys restart the server, so
  staleness was bounded by the deploy interval.

## Fix

In `recompute_stats_tables` itself, so no caller can leave it out — which also
replaces the proposed per-call-site step and the coverage test that would have
guarded it:

1. **`pg_notify(CHANNEL_CACHE_INVALIDATE, {"cache_type": "stats", ...})` on the
   recompute's own connection, inside its transaction.** A NOTIFY is delivered at
   COMMIT and dropped on rollback, so listeners hear it exactly when the new counts
   become visible — also when a caller holds an outer transaction and the recompute
   is only a savepoint. It needs no signal manager, so it works from the admin CLI.
   Every server, the sender's included, invalidates on receipt.
2. **`invalidate_stats_cache(space_id)` locally after the transaction**, for an
   immediate effect in the calling process and for processes with no listener.
3. The receiving handler now logs `Cache invalidation: cleared STATS cache for
   <space>` at INFO (was debug), so an operator can see a `stats_rebuild` reach the
   server.

`resync_all` keeps its own invalidate and notify: it runs after that function's
later steps, so it still covers anything they change.

Also fixed, the comments that claimed `rdf_pred_stats` is maintained on every write
(`generator.py`, the freshness pre-filter; the `_run_value_stats_refresh` docstring)
— it is rewritten only by a recompute, so value-stats drift is visible only after
one. And the stale "top 10K by ascending row_count" comment in `_load_quad_stats`
and the `_load_missing_pair_stats` docstring.

## Verified

- `tests/integration/test_stats_recompute_invalidates_cache.py`: the calling
  process's cache entries for the space are dropped; a listener on another
  connection hears nothing while the recompute's transaction is open and hears it
  after COMMIT; a rolled-back recompute sends nothing. Passing, with the existing
  stats suites (`test_stats_recompute_does_not_block_readers`,
  `test_pred_stats_object_count`, `test_stats_are_per_graph`,
  `test_stats_lock_order`, `test_delete_stats`, `test_maintenance_probe_visibility`,
  `test_derived_table_maintenance`, `test_absence_is_an_upper_bound`).
- The reproduction script, rerun: `[2] db=60 cache=60`, `[3] db=100 cache=100`.
- The cross-process path, `test_scripts/debug/_stats_cache_notify_reaches_server.py`:
  `StatsRebuildOp` run in a separate host process with no signal manager; the
  rebuilt server logged `cleared STATS cache for <scratch space>` (0 lines before,
  1 after).
- The in-server operator path: `POST /processes/trigger stats_rebuild sp_kg_types`
  → the server logged `cleared STATS cache for sp_kg_types` (0 before, 1 after).

## Not this issue

- Under a graph lock, `rdf_stats` counts are graph-scoped but `rdf_pred_stats` is
  space-wide, so `Leaf.restricted` can be true only because of scoping. Recorded in
  the planner planning notes.
- The two value-histogram rebuilds — the bulk insert at `sparql_sql_space_impl.py:1788`
  and the maintenance value-stats refresh at `maintenance_job.py:2064` — still
  invalidate only the local process. With more than one serving instance, the others
  keep stale histograms and freshness verdicts. Same shape as this issue, different
  tables.
