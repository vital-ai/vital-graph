# 350 — The slot-sort coverage sweep runs every cycle on every space

## Status: OPEN 2026-11-25. Not started. Measured on production, read-only.

Follow-up to `349`. That fix left this step out on purpose, because the sweep keeps
the markers the read path consults. It is now the largest part of a maintenance cycle that
no gate holds back.

## Found

From `349`'s `pg_stat_activity` sample of production cycles (2026-11-25, 04:15 → 04:42 UTC,
26.4 min, read-only):

| statement | step | wall | share of maintenance | longest |
|---|---|---:|---:|---:|
| `WITH of_type AS …` (`entity_slot_sort_coverage` / `entity_slot_sort_all_types`) | slot-sort coverage | 115 s | 10 % | 43 s |

That is about 260 s an hour of database time. The code's own estimate for the ungated half
is 220 ms (`maintenance_job.py`, comment on the coverage gate), so production
is about 200x what the comment assumes.

## Why it will grow after 349

`ProcessScheduler` sleeps 300 s after each cycle ends. Once `349` deploys, the median
production cycle should fall from ~433 s to roughly 150-250 s. That means more cycles an
hour, and this step runs in every one of them. Expected: about twice as many runs, roughly
+130 s/h.

## What the step does (`_run_entity_slot_sort_integrity`, `maintenance_job.py` ~3090-3200)

Two statements per space per cycle:

1. **`entity_slot_sort_coverage`**: the worst gaps, as `in_table` against `of_type`. It
   sits behind `probe_data_changed(…, "entity_slot_sort_coverage")`. It is kept
   unconverged while a gap is outstanding, because the backfill it drives only adds rows
   (`issues/149`). On the main production KG space, which is written continuously, the
   gate opens every cycle.
2. **`entity_slot_sort_all_types`**: coverage for every type. It has **no gate** and
   runs on every space every cycle. Its output drives:
   - `record_slot_sort_coverage`, the per-type markers for the filter fast path
     (`issues/161`);
   - `slot_sort_alarms`, the undeclared-shortfall alarm (`issues/167`);
   - `release_whole_space_block_if_complete`.

Both count entities of each type from the quads and look up their presence by
`entity_uuid`. That cost grows with the space, not with what was written.

## Constraints

- **Under the `167` block-list, a marker that says "complete" lets the read path serve
  from the table.** Writes that make the table incomplete must take a block, and this
  sweep is what *releases* blocks and *detects* a write path that forgot to take one.
- **So delaying the sweep does not make answers wrong.** What it delays:
  - releasing a block, which leaves the fast path off for longer;
  - the undeclared-shortfall alarm, which matters because a wrong answer from a short
    table is already being served by the time this alarm fires.
- **A plain minimum interval like `349`'s is therefore safe only when the space holds no
  block and the last sweep was clean.** It must not hold back a pending release.

## Options

1. **An interval only while clean.** Skip both statements for *N* after a clean sweep
   (all types complete, no block held, no alarm), and keep sweeping every cycle while any
   block is held. Small. It reuses `349`'s per-probe interval machinery with a condition.
   Cost: the undeclared-shortfall alarm can arrive up to *N* late.
2. **Incremental by type.** Recount only the entity types whose quads were written since
   the last sweep. That needs a write-side record of touched types, such as the write log
   or a per-type dirty marker, so it is larger but scales with writes.
3. **Cheaper count.** Take `of_type` from `rdf_stats` (vitaltype is single-valued, so the
   count of `(vitaltype, type)` per type is exact once stats are fresh) and leave only
   the presence count in the sweep. That depends on stats freshness. `351` is about that.

## First step

Find out which of the two statements takes the 43 s on production, and on which space:
- read-only, from a new pg_stat_activity sample, or from the per-step timings in `353`
  once they are deployed;
- `pg_stat_statements` groups both under one aliased text (see the memory note on pgss
  aliasing), so it cannot split them per space.

## On production after `349` + `353` (2026-11-26)

13.3 h of `spaces=` fields (deploy session).
- `slot_coverage[<main KG>]` was at or above the 1 s logging threshold **only in the 3
  cycles where the split also ran**, at 29-55 s. Every other cycle it was under 1 s.
  The boot cycle had `slot_coverage[<actions KG>]` at 106.5 s.
- **The sweep is not the cost this issue estimated from the 2026-11-25 sample.** Its
  heavy runs line up with the 6-hourly split, plausibly because the split's own writes
  or cold cache make the coverage counts expensive in those cycles.
- **Priority: low.** Re-check after a week. Until then nothing here needs doing.
