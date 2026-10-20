# 277 — The slot-sort shortfall alarm counted drift and empty slots as missing rows

## Status: FIXED IN CODE 2026-10-17; in production with the current code (reported 2026-10-20). No production repair needed. STAYS OPEN for the nested-frame gap under Not done, which the local vg stack's maintenance job reports live on `probe_nurture` (500 valued slots it cannot attribute, 2026-10-20).

**Related:** `issues/194` (the `entity_slot_sort` alarm, repair and gate this
corrects), `issues/268` (the same multi-statement drift in a count), `issues/212`
(the valueless-slot floor).

## What production showed (2026-10-17)

From 17:37 UTC, seven minutes after the nurture-action cleanup began deleting
old entity graphs from the main KG space, the maintenance job logged every
cycle:

```
entity_slot_sort SUSPECTED SHORTFALL: <space> has ... slots; N of the M missing carry a value ...
entity_slot_sort: <space> has 79 absent slots with no frame_slot row — both mirrors are short,
so this needs resync_all_auxiliary_tables. See issues/194.
```

N ranged from 57 to 207. Nothing was missing:

| measurement | shortfall | no value | real gap |
|---|---|---|---|
| two statements, as the job ran them | 3,368 | 3,339 | 29 (phantom) |
| one REPEATABLE READ snapshot | 3,339 | 3,339 | **0** |

All 3,339 absent slots have no value of any kind — none with a sortable value,
none an entity slot. The 79 "unattributed" were valueless slots under nested
frames. Not caused by `issues/273` (v0.0.87 ran two hours with no ERROR); no
cross-graph edges on the 30 campaign graphs checked.

## Cause

Three faults, each making the next look worse:

1. **Counts from different snapshots.** `entity_slot_sort_row_shortfall` (slots
   in the quad table, rows in the table) and `entity_slot_sort_valueless_slots`
   were separate statements on an autocommit connection. Under ~60 graph deletes
   a minute the quad count moves between them, and the difference was reported
   as missing rows. `issues/268` was the same shape.
2. **The repair selected slots that can never have a row.** The "absent
   slots" batch took any slot with no `entity_slot_sort` row, valueless ones
   included. With 3,339 valueless slots on the space it filled its batch with
   them, derived nothing, and reported the ones it could not attribute.
3. **The ERROR named a cause nobody measured.** "No frame_slot row — both
   mirrors are short" was the message for "the repair's two edge hops (slot →
   frame → entity) did not reach it". A nested frame does that too, and it
   recommended `resync_all_auxiliary_tables` on a space that needed nothing.

Entity slots are counted separately, not as valueless: `hasEntitySlotValue` is a
URI that may name an entity in this space and graph or in another space or
graph. It is a value — it is derived into `frame_slot.entity_uuid` — but not one
`entity_slot_sort` sorts on (`SLOT_VALUE_URIS`), so such a slot is correctly
absent. Whether the target exists here is never consulted.

## Fixed (code)

* `entity_slot_sort_row_shortfall` is one statement.
* New `entity_slot_sort_gap`: one statement returning `quad_slots`,
  `table_rows`, `shortfall`, `no_value`, `entity_slots` and
  `real = shortfall − no_value − entity_slots`. The maintenance job takes `real`
  from it, and the WARNING reports both correctly-absent kinds.
* `backfill_entity_slot_sort_missing_slots` selects only absent slots carrying a
  sortable value.
* The unattributed ERROR says what was measured: absent with a value, not reached
  through one frame (a nested frame, or a short edge table).

## Verification

`tests/integration/test_slot_sort_gap_is_one_snapshot.py` (3), on the vg test
stack: the gap splits four absent slots into 1 valued, 1 empty and 2 entity
slots (one naming an entity in another space); both counts are single
statements; the repair selects the valued slot and none of the others. The last
two fail on the previous code. `test_slot_sort_shortfall_is_visible.py`'s exact-
selection test now counts only valued absent slots, the repair's new contract;
it and `test_entity_slot_sort_maintenance.py` pass (19 in all).

## Production

* **Now**: nothing to repair. The ERROR is a false alarm; ignore it until
  release. Do not run `resync_all_auxiliary_tables` for it.
* **After release**: during the next mass delete, the WARNING and ERROR should
  not appear on the main KG space; `entity_slot_sort_gap` there should read
  `real = 0`.

## Not done

* A nested-frame slot that does carry a value is still unattributed by the
  repair (one frame hop). On 2026-10-17 production had none — all 79 were
  valueless — but how common they are elsewhere is not measured; a walk to the
  owning entity would close it.
