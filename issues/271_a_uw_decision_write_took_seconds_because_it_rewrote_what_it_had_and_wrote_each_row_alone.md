# 271 — A UW decision write took seconds because it rewrote what it had and wrote each row alone

## Status: FIXED 2026-10-17, RELEASED: deployed as build v0.0.86-prod on 2026-10-17 with `wal_compression = lz4`, `VG_PREWARM_SPACES` and all 27 index drops (`planning_deploy/deploy_write_path_and_index_trim_20261017.md`); every fix commit, including the later `7e9ae240`, is an ancestor of v0.0.97 (`ebd6ba17`). STAYS OPEN for the performance items under Not done: writes still above 1 s under load, the unexplained diff-phase spikes, and `quad_po` vs `quad_ctx_pred` not A/B'd. Found in production on v0.0.85.

**Related:** `issues/270` (the same incident's maintenance and index findings;
this continues its index trim), `issues/269` (gen-2 GC pauses inside writes),
`issues/173` (the locked upsert this changes), `issues/194` (derived-sync
ordering, preserved).

## What production showed (2026-10-16)

A UW decision write — one new entity graph, ~1,000 objects, 5,000-9,000 quads,
~1,500 terms — took 6.5-18.7 s with the database otherwise quiet (the 270
backfill halted). The target is under a second.

* **Reads.** `INSERT INTO prod_uw_rdf_quad` since 2026-07-30: 1.02 ms/row,
  84 % of it block-read wait. prod_uw is small (2.4M quads, ~1.8 GB with
  indexes and derived tables) but shares shared_buffers with the main KG
  space's 41 GB; a `pg_prewarm` pass found **~4 % of it resident**. In the
  window before the pass, 3.05 reads and 8.85 ms per row; after one pass,
  0.27-0.95 reads and 0.12-0.20 ms per row, and the 5-9k-quad writes went from
  6.5-18.7 s to 2.1-4.8 s (14 writes, median ~2.9 s). No decay in 30 minutes.
* **WAL.** 5.3 KB of WAL per UW quad insert and 1.16 full-page images
  (7.1 KB / 1.05 per term). pg_walinspect on the test stack, 7k quads,
  7 indexes: records ~760-810 B/quad (heap insert 137 B incl. the 64 B of
  uuids; ON CONFLICT's confirm record 47 B; ~6.7 B-tree leaf inserts at ~80 B),
  page images 3.3-5.0 KB/quad (1.2-2.0 per quad at ~2.5 KB after compression).
  uuid5 keys put every row on a different leaf of every index, so most changes
  are a page's first since the last checkpoint. `wal_compression = pglz`, which
  measured ~2x slower than lz4 at the same ratio.
* **Rewrites.** `upsert_objects_atomic` deleted every quad of the entity's
  subjects and inserted the whole new graph, so an unchanged quad was deleted and
  written again. The insert path's own skip of stored quads could never fire —
  `pg_stat_statements`: calls = rows = 2,888,588 for every UW quad insert.
  248k UW quads deleted since February (~9 % of inserts, ~19 % in one hour of
  2026-10-16).
* **One statement per row.** executemany: 8,500 executor runs for one decision.
* **A mislabelled phase.** The bulk log's `stats_sync` timed the slot-sort and
  prop-sort syncs, not the stats tables — it sent the analysis looking for a
  stats cost that did not exist.

## Fixed

1. **Set-based insert** (`bulk_load.insert_terms_quads_unnest`): one
   `INSERT … SELECT FROM unnest(arrays) ORDER BY <pkey> ON CONFLICT DO NOTHING`
   per table at `VG_UNNEST_MIN_ROWS` (500) rows or more; executemany below it.
   Arrays, not COPY-to-temp: no catalog churn per write. Sorted, so every
   writer takes keys in one global order.
2. **The upsert writes only what changed** (`upsert_objects_atomic`,
   `_unchanged_subjects`): a stored subject whose (predicate, object) uuid set
   equals its new one is neither deleted nor rewritten; the rest are replaced
   as before, through the shared `_delete_subjects_synced`. Subject granularity,
   because every derived sync is keyed by touched subjects. The frames owning a
   replaced slot or edge are resolved before the delete and re-derived after it
   — the first version lost a skipped frame's surviving `frame_slot` rows when
   one of its slots was dropped, and the integration test caught it. A literal
   whose datatype the space has never seen marks its subject changed (it would
   otherwise hash as untyped and could match a stored untyped literal).
   Server-managed properties are stamped before the comparison so it sees what
   will be stored.
3. **`quad_sp` dropped** (schema + `scripts/migrate_drop_redundant_quad_indexes.py`):
   `(subject_uuid, predicate_uuid)` is the leading prefix of the primary key.
   5.0 GB on the main KG space. With 270 that is 6 index writes per quad, not 9.
4. **Prewarm job** (`vitalgraph/process/prewarm_job.py`): `pg_prewarm(...,'buffer')`
   over every relation of the spaces in `VG_PREWARM_SPACES` every
   `VG_PREWARM_INTERVAL_S` (60). Opt-in; `single_runner` (one task warms the
   database's cache for all tasks); internal pool; core indexes first; a
   `VG_PREWARM_MAX_BYTES` cap (3 GB) that logs what it skips; each relation its
   own statement with a timeout; a missing extension warns once and the job
   idles. Logs blocks touched and read per pass.
5. **Measurement.** The bulk line logs each sync separately and WAL MB
   (insert/total); the upsert line logs written/unchanged/replaced counts and
   phases (lock, members, diff, delete with its four steps, write, re-derive,
   commit).
6. **Classification memoised** per write in the bulk path and the diff
   (classify 0.13-0.22 s → 0.02 s for 7k quads), and the diff runs inline: on
   `asyncio.to_thread` it once queued 3.9 s behind the maintenance job's
   synchronous work in the shared executor.

## Verification (vg test stack, lz4)

**Through the API**, `test_scripts/perf/_issue271_uw_write_bench.py`, a bench
space filled to ~2.8M quads (380 decisions of the UW shape: 993 objects,
7,325 quads, 1,454 terms), 5 runs per cell, client wall time:

| | new 7,325-quad write | unchanged re-upsert | 5 % changed |
|---|---|---|---|
| quiet | 1.19 / **1.26** / 1.36 s | 0.31 / **0.34** / 0.45 | 0.26 / **0.28** / 0.37 |
| churn on the 74M-quad fixture | 1.81 / **1.94** / 5.18 | 0.51 / **0.58** / 0.68 | 0.34 / **0.44** / 2.10 |

Quiet, server side: `upsert_objects_atomic` 1.00-1.27 s for a new write, of
which `tq_insert` 0.52-0.78 s [unnest], slot-sort 0.17-0.24, frame_slot
0.08-0.11; re-upserts 0.14-0.35 s writing 9-177 quads.

Before, for reference: the same-sized write through executemany measured
1.6-1.9 s for `tq_insert` alone on a resident UW-sized space (pglz 2.8-3.3 s),
and production's resident writes 2.1-4.8 s.

**Prewarm on the test stack is not a fair test**: storage there is the Docker
VM's page cache, not 3,000-IOPS gp3, so an evicted page is cheap to get back and
the churn costs CPU rather than reads. With the job on, every pass read 0 blocks
(the space stayed resident) and the churn ran 3x more lookups in the same time,
and writes were slower (new 3.49 s median) — contention, not residency.
Production is where residency was measured (above).

**Correctness:**

* `tests/integration/test_an_upsert_writes_only_what_changed.py` (6): rows of
  unchanged subjects keep their `xmin` (not rewritten), and after each upsert
  every derived table equals a from-scratch rebuild of the same quads —
  unchanged re-upsert, one changed value, a repointed entity slot, a dropped
  slot and edge, an added slot, an untyped value gaining a datatype.
* `tests/integration/test_bulk_load_unnest.py`: identical term rows (including
  the generated `num_val`/`dt_val`) and quads to executemany across overlapping
  and self-repeating batches; a large write logs `[unnest]` and the new fields.
* `tests/unit/test_prewarm_job.py` (6). Existing bulk-load, datatype-fidelity,
  blank-node and derived-table-maintenance tests pass; full unit suite passes.

**quad_sp**, query-tier perf suite on all 301 spaces: two runs with it, one
without. The two runs WITH it disagreed with each other on 1 shape and 35
warnings (the suite's noise floor). Without it, no bench read more buffers: the
planner took the pkey; `duplicate_anchor_quads` read the same 720k buffers;
seven traversal benches re-arranged and read 7-15 % fewer; timings inside the
same-config spread. The only failures were the schema-consistency guard,
reporting the index missing while the schema still built it.

## Not done

* **Production**, after release and deploy:
  * `wal_compression = lz4` in the parameter group (dynamic) — deploy session.
  * `scripts/migrate_drop_redundant_quad_indexes.py --apply` as `vitalgraph_user`:
    now quad_pred, quad_ctx and quad_sp (27 indexes on 9 spaces).
  * `pg_prewarm` is already installed on production (2026-10-16, master role;
    `vitalgraph_user` has EXECUTE). Set `VG_PREWARM_SPACES=prod_uw`.
* **Still above 1 s under load** (1.6-4.4 s server-side with churn). What is left
  of a new write is index maintenance and WAL; the levers that remain are in
  `planning/planning_performance/uw_write_under_1s_plan.md`: checkpoint
  interval (fewer page images), the derived-table syncs (slot-sort is now the
  largest after the insert), and the structural options.
* **Diff-phase spikes under load**: twice in 30 re-upserts under churn the diff
  phase took 1.6 s and 5.1 s (normally 0.04-0.37 s). Not yet explained; the
  phase is a datatype lookup, a 7k-row indexed read and in-memory work.
* `quad_po` vs `quad_ctx_pred`: `context_uuid` has one distinct value per space,
  so `(c, p, o) INCLUDE s` overlaps `(p, o)`. Not A/B'd.
