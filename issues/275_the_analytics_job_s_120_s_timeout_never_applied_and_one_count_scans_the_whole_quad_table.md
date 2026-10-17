# 275 — The analytics job's 120 s timeout never applied, and one count scans the whole quad table

## Status: OPEN (filed 2026-10-17). Found in production on v0.0.87.

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

## Proposed fix

1. **Make the timeout apply.** Wrap the job's per-space work in
   `async with conn.transaction():` (then `SET LOCAL` holds and is scoped to
   it), or use a session `SET statement_timeout` right after acquire and reset
   it before release. Restoring 120 s very likely ends the failure on its own:
   31.5 s warm fits easily, and a cold boot run fits in 120 s.
2. **Make the count cheap.** Source `distinct_predicate_count` from
   `{space}_rdf_stats` (or `rdf_pred_stats`), where `predicate_uuid` is already
   materialized — a distinct count there is ~instant — or move it below the 5M
   guard with the rest of property analytics. Check the stats tables' freshness
   rule first: an analytics figure from stale stats must say so.
3. **Guard against the class**: a unit test that every executable `SET LOCAL`
   in `vitalgraph/` sits inside `async with … transaction()` or behind an
   `is_in_transaction()` check, so the next no-op `SET LOCAL` fails CI rather
   than production.
4. Test: the job's queries run with `statement_timeout = 120s` (read it back
   with `SHOW` inside the job's connection), and the count's value equals the
   table scan's on a fixture space.
