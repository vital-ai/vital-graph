# 264 — Both instances recompute `lead_prod`'s stats every hour, and each TRUNCATE can fail a planner read

## FIXED IN CODE 2026-10-10, both defects, not yet deployed (see "Fix" at the end).
##
## Status: OPEN — found 2026-10-10 reading the production logs.
## Low severity per event, cheap to fix. Two defects: the stats recompute still
## takes ACCESS EXCLUSIVE on `rdf_stats` (shorter since `145`, not gone), and
## every instance runs the recompute independently, so production pays it twice
## an hour per space. BOTH CONFIRMED 2026-10-10 (see "Investigation"). Defect 2
## is bigger than the recompute: the WHOLE maintenance job runs once per instance.

## Investigation, 2026-10-10

### Defect 1 reproduced locally, and the fix verified

`test_scripts/debug/_issue264_stats_truncate_lock.py`, vg test stack,
`sp_lead_synth_100k_rdf_stats` (50,000 rows, the production cap). It replays
the recompute's critical section (empty, then re-insert 50k rows from a temp
table) in a transaction that is rolled back, so the table is unchanged, while a
second connection reads it every 5 ms with `lock_timeout = 100ms`
(`STATS_LOCK_TIMEOUT_MS`). Three runs of each:

| | rewrite | reads ok | lock timeouts | rows the reader saw |
|---|---|---|---|---|
| `TRUNCATE` (current) | 246 / 315 / 425 ms | 68 / 61 / 91 | **7 / 7 / 8** | 50,000 |
| `DELETE` (proposed) | 277 / 449 / 503 ms | 77 / 130 / 111 | **0 / 0 / 0** | 50,000 (old contents) |

Every read that landed in the TRUNCATE window failed at ~100 ms, which is the
production symptom. With `DELETE`, none failed and every reader saw the
pre-rewrite contents until the end. The rewrite costs about the same either way,
within the noise of three runs. `DELETE` leaves 50k dead tuples per recompute;
at one recompute an hour that is ordinary autovacuum work.

### Defect 2 covers every maintenance step

Production, 2026-10-02 to 10-09, INFO lines per step per task:

| step | task 001d | task e0e5 |
|---|---|---|
| cycles (`run`) | 3,186 | 3,188 |
| `_run_analyze` | 216 | 215 |
| `_run_vacuum` | 10 | 11 |
| `recompute_stats_tables` | 199 | 197 |
| `compute_edge_fanout` | 288 | 288 |
| `refresh_type_agreement` | 802 | 780 |
| `_run_entity_slot_sort_integrity` | 12,744 | 12,752 |

Every step runs on both instances at the same rate. Each instance picks the
same "worst" table by the same rule, so the ANALYZEs and VACUUMs land on the
same tables. `239` puts maintenance at a large share of production database time
(`143`: 38% of wall-clock); on these counts, about half of it is the second
instance repeating the first. The fix belongs at the job level: one instance
runs maintenance, chosen by a session-level advisory lock held for the
process's lifetime, with failover when it dies. Per-step locks would leave the
probes running twice. `239` should take this as a member.

## What the logs show

Eight `_load_missing_pair_stats` lock timeouts on production between the
2026-10-01 deploy and 2026-10-10:

```
generator - _load_missing_pair_stats - WARNING - semijoin gate: pair stats
lookup failed, plan will be chosen without leaf statistics: canceling statement
due to lock timeout
```

**Every one of them lands 100-190 ms before a `recompute_stats_tables(lead_prod)`
completion line**, from one instance or the other:

| lock timeout (UTC) | failing task | recompute logged | recompute task | gap |
|---|---|---|---|---|
| 10-02 06:50:28.268 | e0e5 | 06:50:28.415 | 001d | 147 ms |
| 10-02 14:54:16.198 | e0e5 | 14:54:16.367 | 001d | 169 ms |
| 10-04 03:49:28.862 | 001d | 03:49:29.000 | 001d | 138 ms |
| 10-04 12:51:54.211 | e0e5 | 12:51:54.404 | 001d | 193 ms |
| 10-05 03:50:06.503 | 001d | 03:50:06.620 | e0e5 | 117 ms |
| 10-06 18:54:34.685 | 001d | 18:54:34.859 | 001d | 174 ms |
| 10-07 18:53:10.490 | 001d | 18:53:10.643 | 001d | 153 ms |
| 10-09 21:58:58.938 | e0e5 | 21:58:59.035 | e0e5 | 97 ms |

Eight out of eight, with no exceptions. An earlier reading (in conversation,
2026-10-10) said these "cluster around 03:50 and 18:5x UTC" and suggested a
recurring job. The job is right, but the hours are not: `lead_prod`'s
hash-phased slot falls at :48-:59 past EVERY hour, and which hours show a
failure just depends on whether a query happened to arrive during the window.

## Defect 1 — the recompute still blocks readers, just for less time

`recompute_stats_tables` (`sync_stats_tables.py:294-334`) builds the new
contents in temp tables first (that was `145`'s fix, `3f8d7b5`), then inside the
same transaction:

```python
await conn.execute(f"TRUNCATE {t_stats}")          # ACCESS EXCLUSIVE until commit
await conn.execute(f"INSERT INTO {t_stats} ... FROM _new_stats")   # up to 50,000 rows
await conn.execute(f"TRUNCATE {t_pred}")
await conn.execute(f"INSERT INTO {t_pred} ... FROM _new_pred_stats")
```

The lock window is now the re-insert alone, about 100-200 ms going by the gaps
above, down from `145`'s minutes. But `TRUNCATE` still conflicts with
everything, including a plain `SELECT`. So any query that plans during the
window waits `STATS_LOCK_TIMEOUT_MS = 100` and then plans with every leaf
unmeasured. That fallback is the input `issues/138`/`139` showed can turn a
2.7 ms lookup into 54,949 ms.

**This also settles `255`'s open question for these eight.** `255` could not tell
whether a "pair stats lookup failed" came from the fenced `rdf_stats` read
(100 ms) or the unfenced `rdf_quad` count (database `lock_timeout`, 10 s). The
recompute takes no lock on `rdf_quad`, and each failure lands within 200 ms of
the `rdf_stats` TRUNCATE window. So all eight are the fenced read doing what
`145` designed it to do. `255`'s unfenced read is still unfenced; it simply
was not involved here.

**Fix:** replace `TRUNCATE` with `DELETE FROM {t_stats}` in the same
transaction. `DELETE` takes ROW EXCLUSIVE, which does not conflict with a
reader's ACCESS SHARE, and MVCC hands concurrent readers the old contents until
commit. At 50,000 rows the extra dead tuples are small, and autovacuum (or the
maintenance VACUUM) reclaims them. That removes the conflict rather than
shrinking it. The 100 ms fence stays as the backstop for anything else that
takes an exclusive lock.

## Defect 2 — every instance recomputes on its own

The schedule is per process (`_recompute_slot`, an in-memory dict,
`maintenance_job.py:341`), and nothing coordinates between instances: no
advisory lock and no shared marker. Production runs two tasks, and Oct 2-9 shows:

```
lead_prod   e0e5   192 recomputes
lead_prod   001d   192 recomputes
```

That is 24 a day each, so 48 full aggregates of `lead_prod`'s quad table a day
where 24 would do. Each is "13-20 s, flat in quad count" by the step's own
docstring. The phase offset comes from a hash of the space id, so both
instances pick the SAME slot and run within minutes of each other (the
completion lines above are 1-6 minutes apart). The second recompute
produces the same table as the first and opens a second lock window.

Other spaces barely recompute (`prod_kg` 3+2, `lead_data` 2+2), because the
change gate skips them; `lead_prod` is written continuously, so it never
skips.

**Fix:** take a per-space `pg_try_advisory_xact_lock` around the recompute, and
skip if another instance already holds it. Better, also record the last
recompute time in the database rather than in process memory, so the second
instance sees the slot as already served instead of merely busy. The backfill
task already uses the try-advisory-lock pattern for the same reason
(`kg_server_properties.py:660`, "another instance holds the lock").

Whether other per-cycle maintenance steps are duplicated the same way has not
been checked. The maintenance job is per process, so probably most of them are,
and that belongs in `239`'s accounting.

## Verifying

- Defect 1: after deploy, `pair stats lookup failed ... lock timeout` should
  stop appearing within 200 ms before a `recompute_stats_tables(` line. Locally,
  run a recompute in a loop against a vg-stack space while a second connection
  issues `SELECT ... FROM {space}_rdf_stats` with `lock_timeout = 100ms`. The
  current code fails some of those reads and the fix should fail none.
- Defect 2: `recompute_stats_tables(lead_prod)` should log 24 times a day across
  both tasks combined, not 24 per task.

## Fix, 2026-10-10 — both defects, not yet deployed

**Defect 1: `DELETE`, not `TRUNCATE`** (`sync_stats_tables.recompute_stats_tables`,
both `rdf_stats` and `rdf_pred_stats`). Test:
`tests/integration/test_stats_recompute_does_not_block_readers.py` runs the REAL
recompute inside an outer transaction, so its locks are still held when it
returns, then reads both tables with the 100 ms fence. Against the old code it
fails with the production symptom ("a 100 ms-fenced read ... timed out while a
recompute was uncommitted"). Against the fix it passes and the reader sees the
pre-recompute counts. With `test_stats_lock_order.py`,
`test_stats_tables_after_crud.py` and `test_stats_lock_timeout.py`: 19 passed.

**Defect 2: one maintenance runner.** The cause was in `ProcessScheduler`, not
the job. It already took an advisory lock per cycle, but released it after each
run. That gives mutual exclusion, not deduplication: the two tasks took turns,
each on its own 300 s clock. A job registered with `single_runner=True` now
keeps its lock between cycles (`db_maintenance` does). The holder runs every
cycle, the other instances find the lock busy, and when the holder stops, its
session ends, the server releases the lock, and the next instance takes over.
`ProcessLockManager.holds()` checks the connection is alive instead of
re-acquiring, because advisory locks are re-entrant per session and
re-acquiring would stack holds. Tests:
`tests/integration/test_maintenance_has_one_runner.py`, using two real
schedulers on two lock connections. One instance runs 5 of 5 interleaved cycles
and the other 0, with exactly one hold on the server. The standby takes over
when the runner disconnects. A runner whose lock connection is terminated
server-side stops running. A job without the flag still takes turns (3 and 3).

**Verified on the rebuilt vg test stack:** the app logged "this instance is now
the single runner for 'db_maintenance'" on its first cycle, the cycle completed
(153.5 s, no errors), and afterwards `pg_locks` shows that one session holding
the lock exactly once.

Not changed: `space_analytics` and `metrics_rollup` are registered the same way
and presumably also run once per instance. They are now one keyword argument
away from the same fix, but were not measured here.
