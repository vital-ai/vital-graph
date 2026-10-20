# 273 — Incremental derived-table syncs scanned the space, not the write

## ARCHIVED 2026-10-20 — fixed and verified locally, in production with the current code (reported 2026-10-20). The Not done items are an evaluated-and-not-adopted change and an unmeasured micro-optimisation, not defects. Evidence: tests/unit/test_incremental_derivations_probe_by_write.py.

## Status: FIXED 2026-10-17 (in production with the current code, reported 2026-10-20). Found measuring v0.0.86 in production.

**Related:** `issues/271` (the write path this continues), `issues/238` and
`issues/253` (the same class on the delete side: a filter the planner could not
drive by the write's uuids), `work_proportional_to_answer_plan.md`.

## What production showed

v0.0.86, a UW decision write (7,325 quads) into the real UW space, 2026-10-17:
the upsert took 0.95-1.09 s; the quad/term insert 0.38-0.51 s; the derived-table
syncs after it ~0.38 s, the slot-sort sync the largest at 0.16-0.19 s.

## Cause

Every statement of a 7k-quad write profiled with `EXPLAIN (ANALYZE, BUFFERS)` on
a UW-sized test-stack space (2.9M quads, 200,880 edges), warm cache. Three of the
derived-table statements did work proportional to the SPACE:

| statement | before | what it read |
|---|---|---|
| `entity_slot_sort` insert (seeded walk) | 111-150 ms, 128k buffers | merge join of the walked frames against **every slot edge of the space** (149,251) in `idx_edge_type_src` order |
| `frame_slot` insert | 62-72 ms | `IN (SELECT … FROM edge …)` hash-joined against a **sequential scan of the edge table** (200,880) plus every slot-type quad (150,660) |
| `entity_slot_sort` pre-delete | 27-29 ms | a sequential scan of the table (not changed, see below) |

for 372 derived rows. The recursive CTE's row estimate is a guess, and with
plain joins the planner chose the plan that is right for the full resync.

## Fixed

* `sync_frame_slot_table`: the frames are resolved first by their own
  BitmapOr lookup (`_edge_owners`, exactly the set the subquery produced) and the
  INSERT probes the edge table by `= ANY`.
* `sync_entity_slot_sort._select_rows`, seeded form only: the slot edges are a
  `JOIN LATERAL (… OFFSET 0)` per walked frame — one `(edge_type, source)` index
  probe each. `OFFSET 0` is required: without it the planner pulls the subquery
  up and picks the same merge join (measured). The full resync and backfill keep
  the set-based join.

Measured as the write experiences it — the `BULK insert` phase timings of real
7k-quad decision writes in-process on the UW-sized space, new and old sync code
alternated, four rounds of 5-8 measured writes (first write of each run
dropped), median per round:

| phase | old | new |
|---|---|---|
| `slot_sort_sync` | 198 / 237 / 235 / 262 ms | **81 / 81 / 96 / 180 ms** (the 180 in a round where every phase ran slow) |
| `fe_sync` (frame_slot) | 98 / 109 / 108 / 116 ms | 108 / 62 / 67 / 115 ms — modest, noisy |

The EXPLAIN ANALYZE figures that found them (slot-sort insert 111-150 → 19-25
ms, frame_slot insert 62-72 → ~12 ms) are inflated by per-row timing inside
Docker — see `frame_prop_sort` below — so these real timings are the result.
The buffer counts are not affected by that: the slot-sort insert read 128k
buffers before and ~7k after.

**Tried and reverted**: the slot-sort pre-delete as one indexed arm per
condition, deleted by key. With ~2,000 touched uuids per arm the planner still
scans, twice — 51 ms against the original 27 ms. The original stays.

## Verification

* 19 derived-table integration files (136 tests: slot-sort maintenance and
  seeded walk, frame_slot sync, upsert-only-what-changed with its
  derived-tables-equal-a-rebuild checks, edge sync, frame graph, slot filters):
  pass.
* `tests/unit/test_incremental_derivations_probe_by_write.py` pins the shapes
  (LATERAL with OFFSET 0 when seeded, the set join when not; frame_slot probing
  by `= ANY`, no subquery).

## Not done

* `frame_prop_sort`: EVALUATED, NOT ADOPTED. Its EXPLAIN ANALYZE showed a
  BitmapAnd reading ~308k `quad_po` entries (~22 ms) in the seeded `frames`
  CTE, and a LATERAL pkey probe per touched subject looked like the 273 fix.
  Measured properly it is not: real write timings unchanged (fprop_sync
  40-44 ms new vs 43-50 ms old over four rounds), and the CTE alone with
  `TIMING OFF` was FASTER in the old form on both a UW-sized space (0.6 vs
  1.1 ms, 62k frames) and a 1.2M-frame space (3.3 vs 4.0 ms). The ~22 ms was
  EXPLAIN's per-row timing overhead inside Docker. Lesson for this class:
  confirm an EXPLAIN-only win with real statement timings or `TIMING OFF`.
* The slot-sort pre-delete (27 ms) does nothing on a new entity; skipping it
  when no touched uuid has a row would need its own probe.
