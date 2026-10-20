# 289 — The frame_slot full build maintained six UUID indexes row by row

## ARCHIVED 2026-10-20 — fixed and verified locally at prod scale (3,877,000 rows, 79 s), in production with the current code (reported 2026-10-20); nothing remaining. Evidence: tests/integration/test_frame_slot_rebuild_drops_and_restores_indexes.py.

## Status: FIXED IN CODE 2026-10-20 (in production with the current code, reported 2026-10-20).

**Related:** `issues/248` (the fuzzy rebuild, which already drops and rebuilds
its band indexes), `issues/270` / `issues/271` (index maintenance cost on quad
inserts), `issues/183` (`frame_slot` itself).

## What showed it

Backfilling derived tables on the local dev cluster, `frame_slot` for
`sp_lead_synth_100k` (50.6M quads, 5M edges, 3,877,000 `frame_slot` rows) hit
the migration script's 30-minute statement timeout and rolled back.

## What it was NOT — two wrong turns, recorded so they are not retried

1. **It was not the statement's shape.** The full build is a single
   `INSERT ... SELECT DISTINCT ON` with hash joins over index-only scans of the
   two predicates it needs. Measured on an idle database: slot-type scan 0.9 s,
   vitaltype scan 2.5 s, edges 0.9 s, edges joined to slot types 13.5 s, and the
   whole SELECT **53 s**.
2. **Batching made it worse, not better.** A batched walk (one statement per
   2,000 source frames, resumable) was built and then thrown away. Each batch
   probes the 50M-row quad table by UUID once or twice per edge. Measured
   alongside the other work: about 100 s per batch, and the second batch hit its
   300 s timeout.

Both measurements, and the 30-minute failure itself, were taken on a machine
that was **out of memory**: 54 of 55 GB of swap in use, fewer than 3,000 free
pages, load around 19. Under that, every query was 10-20x slower, which made a
53-second SELECT look like a 30-minute one and random probes look like 7 ms
each. The diagnosis only came right after stopping the concurrent work and
re-measuring. **Check memory pressure before trusting any timing on this
machine.**

## Cause

The write side. `frame_slot` has a primary key and six secondary indexes, all
keyed on UUIDs. Inserting 3.9M rows maintained every one of them row by row, a
random write per index per row:

    insert with all 7 indexes in place          357 s
    drop 6, insert (pkey only), rebuild 6        79 s   (64 s insert + 15 s rebuild)

## Fix

`resync_frame_slot_table` — the full build behind the migration script, import,
restore, `resync_all` and repair — now, in ONE transaction:

1. raises `maintenance_work_mem` to 1 GB for the index builds (it never lowers
   it; production's parameter group sets 2 GB);
2. truncates, and drops the six secondary indexes;
3. runs the same single `INSERT ... SELECT`;
4. recreates the indexes from the schema's own definitions
   (`create_space_indexes_sql`, so an index missing before the rebuild exists
   after it), then runs ANALYZE.

The primary key stays. `DISTINCT ON` already emits rows in its order, so it is
appended to, and the per-write sync's `ON CONFLICT` keeps working. Readers wait
on the TRUNCATE's lock rather than seeing a half-built or un-indexed table, and
a failure rolls everything back, old rows and old indexes included.

Unchanged: the incremental per-write sync, and the repair backfill
(`backfill_frame_slot_table`), which runs on a populated live table where
dropping indexes is not an option.

## Verified

* `sp_lead_synth_100k` on the dev cluster was built this way: 3,877,000 rows and
  all seven indexes, 79 s in total.
* `tests/integration/test_frame_slot_rebuild_drops_and_restores_indexes.py`:
  * the rebuild derives exactly what the incremental sync built, and every index
    is restored;
  * an INSERT that fails after the TRUNCATE and the index drops leaves the
    table's rows and indexes exactly as they were.

  With the existing `frame_slot` staleness, blank-node, sync and collapse
  integration tests: 42 passed.
