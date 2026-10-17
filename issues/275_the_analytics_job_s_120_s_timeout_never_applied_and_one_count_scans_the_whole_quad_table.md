# 275 — The analytics job's 120 s timeout never applied, and one count scans the whole quad table

## Status: FIXED 2026-10-17 (not yet released). Found in production on v0.0.87.

**Related:** `issues/253` (`SET LOCAL` used where it does not hold, the write
path), `issues/270` (the index trim this is NOT caused by).

## What production showed

On the v0.0.87 rollout (2026-10-17):

    AnalyticsJob: failed for space <main KG space>: canceling statement due to statement timeout

Boot 15:25:27, failure 15:26:26 — ~59 s, the instance's 60 s
`statement_timeout`, not the 120 s the job asks for. In the 14 days before: 0
failures for that space. The job runs daily on warm caches; the failure needs a
cold one, which a deploy restart provides. The job is per-space
`try/except`, so other spaces still compute and store — only the main KG
space's analytics goes stale until the next daily run. No effect on user
queries or writes.

## Cause

### 1. The 120 s timeout is a no-op (the real bug)

`vitalgraph/process/analytics_job.py:142`:

```python
async with self._pool.acquire() as conn:
    await conn.execute("SET LOCAL statement_timeout = '120s'")
```

`SET LOCAL` holds only inside a transaction block. A pooled asyncpg connection
outside `conn.transaction()` is in autocommit, so PostgreSQL emits `WARNING:
SET LOCAL can only be used in transaction blocks` and the value stays at the
instance default. Reproduced against production:

    SET LOCAL statement_timeout = '120s'; SHOW statement_timeout  → 1min  (+ the warning)
    SET       statement_timeout = '120s'; SHOW statement_timeout  → 2min

So every analytics query, for every space, has had half its intended budget.

Audit of the other `SET LOCAL` call sites (2026-10-17): all run inside a
transaction — `_apply_read_fence`'s two callers open one first
(`sparql_sql_space_impl.py:2510-2518`), `sync_frame_slot_table._forced` checks
`conn.is_in_transaction()` and opens one if not. The analytics job is the only
offender.

### 2. `distinct_predicate_count` is O(quad table)

`_compute_property_analytics` (`analytics_job.py:638-652`) runs
`COUNT(DISTINCT predicate_uuid)` over the whole quad table ABOVE the 5M-quad
guard, so it runs even on the largest space. On the main KG space (79.5M quads)
the plan is a full index-only scan of `idx_<space>_quad_po` (79.5M entries) to
return 28 distinct values: 31.5 s warm. At boot the space is cold (the prewarm
job covers only the UW space), which pushes it past 60 s. The code's own comment
already says it is "NOT free … 4.1 s on a 50.5M-quad space". The other
always-on query, `most_connected`, is 7.6 s; the `rdf_stats` / edge fast paths
are < 110 ms.

Not a regression from the v0.0.86 index drop (`issues/270`/`271`): `quad_po`
still leads with `predicate_uuid` — which is what made the dropped `quad_pred`
redundant — and the planner uses it.

## Fixed

1. **The timeout applies.** `_compute_and_store` sets `statement_timeout` as a
   SESSION value on the job's connection (`VG_ANALYTICS_STATEMENT_TIMEOUT`,
   default `120s`) and RESETs it in a `finally` before the connection goes back
   to the pool. Not one long transaction: the job runs for tens of seconds and a
   snapshot held that long stops VACUUM on the tables it reads.
2. **The count is cheap where it was expensive.** On an unfiltered run above
   the 5M-quad guard, `distinct_predicate_count` is `count(*)` of
   `{space}_rdf_pred_stats` (one row per predicate, rebuilt by the hourly stats
   recompute) when that table is populated; the result carries
   `distinct_predicate_count_source` (`rdf_pred_stats` or `rdf_quad`).
   Graph-filtered runs, small spaces and a space with empty or absent stats keep
   the exact scan. Production, read-only: 28 from the stats table in 12.8 ms
   (with the round trip), the same 28 the 31.5 s scan returns on the 79.5M-quad
   main KG space.
3. **A CI guard for the class**: `tests/unit/test_set_local_runs_inside_a_transaction.py`
   parses every module under `vitalgraph/` and fails on an executed `SET LOCAL`
   that is not inside `async with ….transaction()`, not in a function checking
   `is_in_transaction()`, and not in a named caller-holds-the-transaction helper
   (`_apply_read_fence`, whose callers are checked to open one). It fails on the
   previous code at `analytics_job.py:142`.

## Verification

* `tests/integration/test_analytics_runs_with_its_own_timeout.py` (2): the job's
  queries see `statement_timeout = 2min` and the connection gets its own value
  back afterwards (a one-connection pool, so the same connection is read); above
  the guard the count comes from `rdf_pred_stats` and equals the scan, below it
  from the scan. Both fail on the previous code — the first with
  `statement_timeout='0'` inside the job, the test database's default, which is
  the no-op exactly.
* The guard test (3) passes, and fails on the previous code.
* `test_analytics_graph_scope.py`, `test_analytics_honours_the_exclusion_list.py`,
  `test_background_work_uses_the_internal_pool.py`: pass.
