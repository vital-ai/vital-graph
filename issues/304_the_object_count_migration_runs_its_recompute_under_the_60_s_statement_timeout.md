# 304 — The `object_count` migration runs its recompute under the 60 s `statement_timeout`

## Status: FIXED 2026-10-24, not yet released (hit the same day during the production deploy of `issues/293`; reproduced and verified on the vg test stack). Nothing is wrong in query results; the big spaces just don't get 293's object-count pricing until a recompute fills the column.

**Related:** `issues/293` (what added `rdf_pred_stats.object_count`), `issues/275`
(the same 60 s ceiling, in the analytics job), `issues/136` (in VACUUM).

## Found

`scripts/migrate_pred_stats_object_count.py --all` on production stopped at the
first space, cardiff_kg (76.4M quads):

```
File ".../sync_stats_tables.py", line 308, in recompute_stats_tables
asyncpg.exceptions.QueryCanceledError: canceling statement due to statement timeout
...
File ".../sync_stats_tables.py", line 321, in recompute_stats_tables
asyncpg.exceptions.InFailedSQLTransactionError: current transaction is aborted, commands ignored until end of transaction block
```

## Mechanism

The script does two things per space:

1. `ALTER TABLE … ADD COLUMN object_count`, in its own transaction with a
   `lock_timeout`. A catalogue change; fast, and it committed.
2. `recompute_stats_tables(conn, space_id)` to fill the column.

Step 2 is not a recompute of `object_count`. It is the full statistics recompute
(`rdf_stats`, `rdf_pred_stats`, value stats), aggregating over the whole quad
table. The script never raises `statement_timeout`, and it passes no `timeout`,
so the recompute runs at the parameter group's 60 s. On cardiff_kg and
cardiff_kg_actions (53.8M) that is not enough. The cancel aborts
`recompute_stats_tables`'s transaction, the next statement in it raises
`InFailedSQLTransactionError`, and the exception leaves `main()`. `--all` goes in
`space_id` order, so cardiff_kg was first and the other 10 spaces were never
reached.

The script's docstring cites "+8.1 s on a 74.2M-quad space, measured on the vg
test stack". That is the extra cost of the new column, not the duration of the
whole recompute, and the test stack has no 60 s parameter-group timeout.

Two other migrations already deal with this. `migrate_sort_value_key.py:158` and
`migrate_term_uri_limit.py:76` both `SET LOCAL statement_timeout = 0` inside a
transaction for their heavy step, with a comment naming the production 60 s.
This one doesn't. (`migrate_space_storage_key.py` sets only a lock timeout,
which is right for it.)

`tests/unit/test_set_local_runs_inside_a_transaction.py` (275's guard) scans only
`vitalgraph/`, so it says nothing about `scripts/`. It could not have caught this
anyway, since the defect here is a missing `SET` and not a misplaced one.

## State left on production

- Re-run with `--no-recompute`: the column exists on all 11 spaces. It is filled
  on the small ones and NULL on cardiff_kg, cardiff_kg_actions, lead_prod and
  lead_data.
- NULL is safe. `generator.py:408` keeps only non-NULL counts in
  `pred_object_counts`, and `bgp_cardinality.py` declines ("a leaf has no
  statistics") when one is missing, so those spaces plan as they did before 293.

**The maintenance cycle should fill it.** Its stats recompute
(`maintenance_job.py`, `_run_stats_recompute`) runs inside
`maintenance_timeouts(conn)`, which sets `statement_timeout` to
`MAINTENANCE_STATEMENT_TIMEOUT_MS` (15 min by default) and passes the same
budget as the client-side `timeout`. So it is not held to 60 s. It runs only when
`probe_data_changed` reports a write since the last recompute, and that is
normal on these spaces. Check before re-running anything: if
`SELECT count(*) FILTER (WHERE object_count IS NULL) FROM <space>_rdf_pred_stats`
is already 0, maintenance has done it.

The runtime line seen at the same time,
`index sync cardiff_kg: 19 subject(s) failed … statement timeout, retrying`, is
a different caller. The index-sync worker hit 60 s on a batch and retried with
backoff, so nothing was lost there. It is not this issue.

## Fix

In `migrate_space`, wrap the recompute so its statements are not held to the
session default:

```python
async with conn.transaction():
    # Production's parameter group sets 60 s; a full recompute of a large
    # space takes longer. LOCAL so it ends with the transaction.
    await conn.execute("SET LOCAL statement_timeout = 0")
    counts = await recompute_stats_tables(conn, space_id)
```

`recompute_stats_tables`'s own `transaction()` then becomes a savepoint, which it
already supports (its `enable_hashagg` save-and-restore exists for exactly the
case where a caller holds a transaction). Also correct the docstring's 8.1 s
figure so it reads as the column's cost, not the recompute's.

Then, if maintenance hasn't already filled the column, run
`--space cardiff_kg` and `--space cardiff_kg_actions` (and the two lead spaces).
The script skips any space whose column is already fully non-NULL.

## Reproduced and verified (vg test stack, 2026-10-24)

`test_scripts/debug/_issue304_recompute_timeout.py` runs `migrate_space` from
the HEAD copy of the script and from the working tree, on a connection whose
session default is the ceiling (as the parameter group delivers it; no database
setting changed). A proxy answers the "already filled" probe with no, so the
recompute path runs without NULLing any data. Space `sp_lead_synth_100k`
(74.2M quads, excluded from maintenance, so no concurrent recompute):

```
CEILING=60s  unfixed: OK in 41.0s, counted 24/24
CEILING=10s  unfixed: FAILED after 10.0s -> InFailedSQLTransactionError: current transaction is aborted
CEILING=10s  fixed:   OK in 33.0s, counted 24/24; session statement_timeout after = 10s
```

**At 60 s this machine does not reproduce it.** The whole recompute takes ~41 s
here, and production's 2-vCPU instance on a 76.4M-quad space exceeded 60 s in a
single statement. At a ceiling below the longest statement, the unfixed script
fails with production's exact error, and the fixed one completes. The setting
does not leak past the migration's transaction.

`--all --dry-run` on the test stack (target confirmed `localhost:5433`) runs
clean. 25 of its 28 spaces reported `would add column`: the test stack itself
had never been migrated.

## Migrated locally with the fixed script (2026-10-24)

- **vg test stack** (`localhost:5433`): `--all` migrated 25 spaces, all fully
  counted, no errors; the other 4 were already done.
- **Host cluster used by the dev stack** (`localhost:5432/sparql_sql_graph`):
  `--all` migrated all 44 spaces with no errors. The slowest recompute was 21.2 s
  (`sp_lead_synth_100k`).

Two leftovers. `dawg_test_rdf_pred_stats` on the test stack has no `space` row,
so `--all` never reaches it. And an EMPTY space never reads as migrated:
`bool_and` over zero rows is NULL, so `rt_verify` (test stack) and
`test_multivalue` (host) are recomputed, in 0.0 s, on every run. Harmless;
`coalesce(…, true)` on that probe would end it.
