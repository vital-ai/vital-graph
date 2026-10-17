# 270 — A bulk load turned maintenance into a scan loop, and every quad insert into nine index writes

## Status: FIXED 2026-10-16 (not yet released). Found in production on v0.0.85.

**Related:** `issues/150` (the drift probe ate half the box: the same class,
a probe that costs more than it is worth), `issues/236` (need gates for ANALYZE
and VACUUM), `issues/143`/`issues/149` (probe gating and client timeouts).

## What production showed (2026-10-16)

Writes failed or timed out: `prod_uw` bulk upserts died on `canceling statement
due to lock timeout` (17:40, 17:55), an upsert waited out its 10 s entity lock
(18:21), the Resource API returned `entity_busy`, and write latency went from
511 ms p90 (Oct 12) to 6.35 s p90 / 11.3 s max.

The trigger was a deliberate backfill of historical leads (22,885 leads, ~3,000
quads each) into the main KG space. Bulk-inserted quads per day: 3.1M (Oct 13),
4.2M, 12.7M (Oct 15), 19.6M (Oct 16, partial). The quad table grew from ~50M to
78.7M rows; the database is 175 GB on a db.r6g.xlarge (32 GB RAM, ~8 GB shared
buffers) with gp3 storage at its fixed 3,000 IOPS (250 GB, under the 400 GiB
threshold that allows more).

| | Oct 7-10 | Oct 14 | Oct 15 | Oct 16 |
|---|---|---|---|---|
| read IOPS, daily avg | 21-31 | 931 | 2,006 | ~2,000-2,400 hourly |
| disk queue depth, daily avg | 0 | 3 | 9 | 8-13 hourly, max 25 |
| maintenance cycle, avg / max | 0.6 / 2.3 min | 3.1 / 14.0 | 4.4 / 20.4 | 15.6 / 40.2 |

Halting the backfill took write IOPS from ~1,000 to 100-180 and the queue to
0-1 within five minutes. Read IOPS then went back up to ~1,600-1,800 with no
writes running: the maintenance job rescanning the grown table.

## Three defects that turned a large load into failures

**1. A probe that timed out was retried every cycle.** Neither the write
watermark gate nor the convergence gate remembered a failure, so a probe that
could no longer finish inside its statement timeout on the grown table ran the
same full scan every cycle. In 48 hours: `edge_integrity` timed out 59 times
(~2 min each), the type-agreement refresh 54 times (~5 min each, edge and frame
kinds). The type-agreement refresh already backed off a verdict that was "born
stale"; a TIMEOUT wrote nothing, so it had no back-off at all.

**2. ANALYZE and VACUUM triggered on an absolute 10,000 changes.** On the
78.7M-row quad table that meant "every cycle": 57 ANALYZEs in 24 hours at 0.02%
modified, each reading ~271k blocks (2.1 GB; the statistics targets are 1000 on
subject/predicate, 500 default) in ~46 s, plus a VACUUM per cycle. In one
two-minute sample, ANALYZE was 70% of all blocks read. PostgreSQL's own
autovacuum is on and table-relative (production: analyze at 0.5%, vacuum at 1%)
and had autovacuumed the table 177 times, but its autoanalyze count was 0: this
job always got there first. They don't block writes (separate connections, no
write-blocking locks); they compete for the same 3,000 IOPS.

**3. Every quad insert maintained nine indexes, ~32 GB, at a random page each.**
The heap is 8.8 GB; the keys are UUIDs, so each insert touches a random leaf in
every index, and several missed the cache half the time (`quad_sp` 49% hit,
`quad_obj` 54%, `quad_ctx` 48%, `quad_pred` 63%). Two were nearly unused:
`quad_ctx` 26k scans and `quad_pred` 385k, against 87M-7.4B for the other seven.
Each is covered by a composite with the same leading column (`quad_ctx_pred`;
`quad_po` / `quad_ps`).

With I/O saturated every write transaction ran 10-50x longer (a lead create
17-26 s, almost all in the quad insert), so waits that normally take
milliseconds (two writes to one entity; an `ON CONFLICT` insert waiting on a
concurrent insert of the same key) exceeded the 10 s `lock_timeout`.

## Fixes

1. **Probe back-off** (`maintenance_job.py`): a TIMEOUT (server statement
   timeout or driver timeout) backs the probe off for that space, 1 h doubling
   to a 24 h cap (`VG_PROBE_FAILURE_BACKOFF_S`, `VG_PROBE_FAILURE_BACKOFF_MAX_S`);
   one success clears it. Other failures still retry every cycle. Applied to
   `edge_integrity`, `frame_slot_integrity`, `frame_entity_integrity`.
   **Type agreement** (`edge_type_agreement.py`): a timed-out refresh is stored
   as an unknown verdict with its elapsed time, so the existing gate backs it
   off, 6 h for a timeout (`VG_TYPE_AGREEMENT_TIMEOUT_BACKOFF_S`) against 1 h for
   born stale.
2. **Table-relative ANALYZE/VACUUM gates**: due at `max(10,000, 2% of live
   rows)` (`VG_ANALYZE_SCALE_FACTOR`, `VG_VACUUM_SCALE_FACTOR`), at both the
   space pick and the per-table gate. On the production table: ~1.6M changes
   instead of 10,000, so autovacuum's 0.5% / 1% handles the big tables and this
   job still covers small and never-analyzed ones.
3. **Two indexes dropped**: the schema no longer builds `quad_pred` /
   `quad_ctx`; `scripts/migrate_drop_redundant_quad_indexes.py` drops them on
   existing spaces (dry run by default, only where a valid covering composite
   exists, CONCURRENTLY; partitioned indexes with a plain DROP).

## Verification (vg test stack)

- Query-tier perf suite, both indexes dropped on all 301 spaces (602 indexes)
  against a run with them: buffer counts within tolerance; the only plan change
  is `quad_ps` replacing `quad_pred` in five benches. One timing-ratio test
  (`test_min_max_sort_per_group_stays_bounded[10k-by_type]`) crossed its 6.0x
  limit once and then passed 3/3 with and 3/3 without the indexes; its plan uses
  `quad_ctx_pred` and the term key in both cases, never the dropped two, and it
  gates a sort, not index access. The other five failures were the
  schema-consistency guard reporting the indexes missing while the schema still
  built them.
- On the 100k fixture the two indexes had 6 and 0 scans.
- `tests/unit/test_maintenance_backs_off_and_scales.py` (15): 11 fail on the
  previous code; the other 4 pin behaviour that must not change.
- `tests/integration/test_bulk_load_copy.py`: the rebuilt index set excludes the
  two. Full unit suite passes.
- The migration has been applied to the test stack (602 dropped, 2 of them on a
  partitioned space, which the first version of the script missed because
  `pg_stat_user_indexes` does not list partitioned indexes).

## Not done

- Production: release, deploy, then
  `migrate_drop_redundant_quad_indexes.py` as `vitalgraph_user` (18 indexes on
  9 spaces, all ordinary tables; ~1.35 GB on the main KG space).
- Capacity is a separate decision: gp3 at 250 GB cannot exceed 3,000 IOPS;
  400 GB lifts the baseline to 12,000 (the instance sustains ~6,000), and a
  db.r6g.2xlarge doubles RAM. Neither is needed once the backfill is paced.
- The backfill itself is paused (8,500 of 22,885 done, idempotent).
