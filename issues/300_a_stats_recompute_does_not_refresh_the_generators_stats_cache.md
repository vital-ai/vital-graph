# 300 — A stats recompute does not refresh the generator's stats cache

## Status: OPEN — reproduced on the vg test stack 2026-10-23; not fixed.

**Related:** `issues/142` (stats are recomputed, never accumulated), `issues/139`
(a corrupt `rdf_stats` repaired only by a rebuild), `issues/163` (the cache is keyed
by graph), `issues/276` (a lost invalidation stream), `issues/232` (process-local
caches on rename).

## Found

While inventorying which statistics tables the cardinality model reads (planning
for the planner extension). The generator caches each space's `rdf_stats` and
`rdf_pred_stats` in process memory, `_stats_cache` (`generator.py:283`), with no
TTL. Every writer of those two tables is `recompute_stats_tables`
(`sync_stats_tables.py:110`), and most of its callers never invalidate the cache.

The maintenance job runs **inside the server process**
(`vitalgraphapp_impl.py:548`), so the hourly recompute rewrites the tables under a
cache in the same process and leaves the cache as it was. A long-lived server keeps
planning on the counts it loaded at the first query to each space (and graph lock),
until it restarts or something else happens to invalidate that space.

## Reproduced

`test_scripts/debug/_stats_cache_stale_after_recompute.py`, vg test stack (:8002 /
:5433). It uses a scratch space created and deleted through the API, and runs the
server's own code in one process, as the server does:

```
[1] db pred_stats=10  cache=10
[2] after _run_stats_recompute: db=60  cache=10
[3] after StatsRebuildOp:       db=100  cache=10
[4] after invalidate_stats_cache: db=100  cache=100
```

Steps 2 and 3 each wrote more quads and ran a recompute. The table moved from 10 to
60 to 100, and the cache stayed at 10 until step 4's explicit invalidate.

## Which writers invalidate

| caller of `recompute_stats_tables` | invalidates locally | notifies other instances |
|---|---|---|
| `MaintenanceJob._run_stats_recompute` (hourly, and `trigger maintenance`) `maintenance_job.py:1959` | **no** | **no** |
| `StatsRebuildOp` (`trigger stats_rebuild`, the 139 repair) `database_op.py:170` | **no** | **no** |
| imports, `data_import_impl.py:1024`, `:1254`, `:1486` | **no** (term cache only, `:797`) | **no** |
| `bulk_export.py:263`, `partition_migrate.py:135` | **no** | **no** |
| `resync_all.py:134` | yes, `:230` | yes, `notify_cache_invalidate("stats")`, `:240` |

What does clear it elsewhere: a bulk insert above `REBUILD_MIN_QUADS`
(`sparql_sql_space_impl.py:1788`), the `CHANNEL_CACHE_INVALIDATE` handler
(`vitalgraphapp_impl.py:756`), `invalidate_all_stats_caches` on a lost
invalidation stream, a rename, and, incidentally, the maintenance value-stats
refresh (`maintenance_job.py:2061`). That last one only applies to the single
most-drifted space per cycle, and only to spaces whose numeric or date histograms
have drifted past `VALUE_STATS_DRIFT_THRESHOLD`.

## Consequences

- Join ordering, the semi-join gate, the hop-wise and traversal decisions, and
  `absence_bounds` all read the cached counts. A space that grows after the server
  starts is planned on its size at first query. That is exactly the misestimate class
  293 and 297 measure, arriving from staleness instead of from the model.
- **`trigger stats_rebuild`, the operator's repair for a corrupt `rdf_stats` (139),
  does not reach the serving process.** The table is fixed, the server keeps the
  corrupt counts, and the repair looks as if it did nothing until a restart.
- Not measured: how stale production's caches actually get. Deploys restart the
  server, so staleness is bounded by the deploy interval. Treat the magnitude as
  unknown, not small.

## Fix (proposed)

1. One post-recompute step, `after_stats_recompute(space_id)`, that invalidates
   locally (`invalidate_stats_cache`) and notifies other instances (the
   `resync_all` pattern), called after **every** successful `recompute_stats_tables`.
   It could also go inside `recompute_stats_tables` itself, but that function takes
   only a connection, and the notify needs the signal manager.
2. A test that every call site of `recompute_stats_tables` is followed by it, the way
   `space_cache_invalidation.CACHE_INVALIDATORS` is held by a coverage test, so a
   seventh writer can't reintroduce this.
3. Verify by rerunning the script: step 2 and step 3 must show `cache == db`.

## Also wrong, same area

Comments claim `rdf_pred_stats` is "maintained incrementally on every write"
(`generator.py:1236-1237`) or "maintained on every write" (the
`_run_value_stats_refresh` docstring, `maintenance_job.py`). It isn't:
`recompute_stats_tables` is its only writer. So the value-stats drift check only
moves when a recompute runs. Fix the comments with the code. The docstrings of
`_load_missing_pair_stats` (`generator.py:1103`) and `:410-414` also describe the old
10,000-pair load.

Not this issue: under a graph lock, `rdf_stats` counts are graph-scoped but
`rdf_pred_stats` is space-wide, so `Leaf.restricted` can be true only because of
scoping. That is a separate defect, recorded in the planner planning notes.
