# 265 — The frame_slot sweep deletes every value-slot row it reads

## FIXED IN CODE 2026-10-10, not yet deployed (see "Fix" at the end).
##
## Status: OPEN — found 2026-10-10 while investigating `263`. Confirmed on
## production data and reproduced read-only on the vg test stack. A correctness
## defect: after a WHERE-bound delete, frame-slot queries are served from a table
## missing up to 50,000 valid rows until the next backfill.

## The defect

`cleanup_stale_frame_slot` (`sync_frame_slot_table.py:334`) decides a row is
stale unless this exists:

```sql
JOIN {quad} sv ON sv.subject_uuid = emv.dest_node_uuid
              AND sv.predicate_uuid = <hasEntitySlotValue>
              AND sv.object_uuid = fs.entity_uuid        -- inner join, plain '='
```

`entity_uuid` is NULLABLE by design: every builder fills it with a LEFT JOIN,
because "a slot with a role but no `hasEntitySlotValue` is still a slot of that
frame" (`sparql_sql_schema.py:1208`, `resync_frame_slot_table`). A value slot
(text, date, number, boolean) has no `hasEntitySlotValue` at all, so its row
has `entity_uuid = NULL`, `sv.object_uuid = NULL` never matches, and the row is
judged stale. **The sweep's validity rule is stricter than the rule the table
was built by**, even though its docstring says "validity is defined exactly as
`resync_frame_slot_table` defines it".

## Reproduced (read-only, vg test stack)

The sweep's own stale test over the first 50,000-row window:

| space | slot kind | `entity_uuid` NULL | judged stale (current) | judged stale (NULL-safe) |
|---|---|---|---|---|
| `sp_lead_synth_10k` | value slots | all | **50,000 / 50,000** | 0 / 50,000 |
| `wordnet_frames` | entity slots | none | 0 / 50,000 | 0 / 50,000 |

NULL-safe means `LEFT JOIN sv ... WHERE sv.object_uuid IS NOT DISTINCT FROM
fs.entity_uuid`. That keeps a value-slot row and still rejects a row whose slot
gained, lost or changed its entity.

## It has happened on production

The sweep runs only for spaces marked by a WHERE-bound delete. On 2026-09-28
`prod_kg_actions` (3.24M rows, a lead-shaped space with mostly value
slots) was swept five times:

```
08:02:23  cleanup_stale_frame_slot(prod_kg_actions): removed 50000 stale row(s) from a 50000-row window
08:04:26  frame_slot integrity: prod_kg_actions expected 3244258 rows, has 3194258
08:10:42  backfill_frame_slot_table(prod_kg_actions): 50000 rows inserted
08:17:15  ... removed 50000 ...      08:23:03  ... 50000 rows inserted
08:40:07  ... removed 50000 ...      08:45:51  ... 50000 rows inserted
08:57:11  ... removed 50000 ...      09:03:10  ... 50000 rows inserted
13:47:52  ... removed 50000 ...      13:53:37  ... 50000 rows inserted
```

Each time the deficit was EXACTLY 50,000 and the backfill put back EXACTLY
50,000. A backfill only inserts rows that are valid, so every deleted row was
valid. For 6-8 minutes after each pass, 50,000 valid frame/slot rows were
absent from the table the frame-slot collapse answers from, so a query using
it would silently omit those frames.

## Why it has not been worse, and when it would be

It healed only because 50,000 clears the backfill threshold
`max(EDGE_DRIFT_MIN_ABS=1000, 1% of expected)` (`263`). Where it would not:

- a space whose swept window has fewer than ~1,000 value-slot rows: the
  deletions stay below the threshold and are never restored;
- a space over 5M rows: 50,000 is under 1%, so a single pass is never
  restored. Every later pass, as the cursor walks the table, adds another
  50,000, and the backfill acts only once the total crosses 1%.

`cleanup_orphan_edges` runs straight after in the same sweep; it was not
examined for the same pattern.

## Fix

Make the sweep's validity rule match the builders' rule: LEFT JOIN the slot
value and compare with `IS NOT DISTINCT FROM`, as in the table above. Add a
test that builds a frame with a value slot, marks the space for a sweep, runs
it, and asserts the row survives. The only sweep test,
`tests/integration/test_frame_slot_sync_on_delete.py`, builds entity slots
only (every slot gets a `hasEntitySlotValue`), where the inner join is harmless.

Until it is fixed, every WHERE-bound delete in a value-slot space takes a bite
out of `frame_slot`.

## Fix, 2026-10-10 — not yet deployed

`cleanup_stale_frame_slot` now LEFT JOINs the slot value and compares with
`IS NOT DISTINCT FROM`, matching the builders. The test helper `_stale_fe_rows`
in `tests/integration/test_frame_slot_sync_on_delete.py` had the same inner
join, so it could not have caught this; it is NULL-safe now too. New test
`test_sweep_keeps_value_slot_rows` seeds six value-slot frames, sweeps, and
asserts all six rows survive. It fails against the old sweep (`after ==
before`) and passes against the fix. The whole file passes: 5 tests, including
the existing WHERE-bound-delete test, which still removes rows whose entity
really was deleted.
