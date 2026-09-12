# Both Prop-Sort Tables Are Unmaintained By Seven Write Paths, And Were Absent From The Matrix

## Status: PARTLY FIXED 2026-09-12 (`c00a5f83`). The entity side is repaired:
## coverage counts PAIRS and the maintenance loop now backfills. Still open —
## `frame_prop_sort`, and wiring the syncs into the seven write paths.

The twin of `issues/187`, found by asking why `entity_prop_sort` existed in no
local space. It does not reproduce 187 — it is a *different set of tables* with a
*worse failure mode* — but it was invisible for the same reason `185` describes:
**the maintenance matrix reports only on tables it lists**, and neither
`entity_prop_sort` nor `frame_prop_sort` was listed.

Adding them to `DERIVED` surfaced **13 gaps and 1 exemption** immediately.

## Why this is worse than the slot-table gap

`entity_slot_sort` going stale mis-ORDERS a page. These two are read by a
**FILTER** as well as a sort, and their read gate `prop_sort_block` is a
**BLOCK-LIST** — absence means SERVE, deliberately, per `issues/167`. So a short
table is not declined. It answers with a plausible subset, and a count drawn
from the same table agrees with it. Nothing errors.

## The severe one, which is not in 187's set

    (kg_backend, update_entity_subject_only) -> entity_prop_sort

This path is **exempt** for `edge`, `frame_slot` and `entity_slot_sort`, and the
stated reason is sound for them: "the entity subject carries no edge-source/dest
properties and is not a frame". That reasoning stops exactly one step short.
The entity subject's OWN direct quads are precisely what `entity_prop_sort`
indexes, so this is the one path where "subject only" makes the mirror WRONG
rather than irrelevant — delete a property and a filter on the removed value
still matches. `frame_prop_sort` IS legitimately exempt here (an entity is not a
frame) and is recorded as such.

## Measured on prod, 2026-09-12

Three live spaces are **exactly** complete — quad-side equals table-side for
every sortable property, and `prop_sort_coverage` records them verified
2026-09-08 with no drift since:

    cardiff_kg   5 of 5 properties complete, 84,605 entities each, 32/32 types
    lead_data    5 of 5 complete
    lead_prod    5 of 5 complete

`wordnet_frames` is NOT, and it is the space populated by the import path this
issue is about:

    hasName                          109,745 in quads   109,745 in table
    hasKGEntityType                  109,745            109,745
    hasObjectCreationTime            109,745                  0   <-- MISSING
    hasObjectStatusType              109,745                  0   <-- MISSING
    hasObjectModificationDateTime    109,745                  0   <-- MISSING

329,235 absent rows, no block row, and no coverage row. A sort or filter on any
of those three properties for that space returns an EMPTY page, not a slow one.
It has no `prop_sort_coverage` entry because it was created after the migration
ran, so nothing ever measured it — the gate serves it on absence of a block.

So the exposure today is confined to a space loaded for performance testing. The
DEFECT is not: any space populated through these paths drifts the same way, and
nothing reports it.

## A second finding, separate from the maintenance gap

**No local space has `entity_prop_sort` at all**, and neither global gate table
exists locally. The newest local space is 2026-08-16; the feature landed
2026-09-07 (`9409fae9`), and existing spaces get it only from
`scripts/migrate_entity_prop_sort.py`, which was never run here.

`prop_sort_blocked` **fails closed** — a missing block table is caught, logged at
INFO, and returns "blocked". So `fast_prop_sort` has been entirely inert in local
development since it shipped, with an INFO line as the only symptom. That is the
same shape as the missing GRANT the gate's own docstring cites, and the same
shape as the `ANALYZE` list that silently skipped five tables (`issues/183`).
Worth running the migration on dev so the path is exercised at all.

## WHY THE BACKFILL DID NOT FIX IT — investigated 2026-09-12

Two independent reasons, and the second is the serious one.

### 1. No backfill is wired for these tables

`backfill_entity_prop_sort` EXISTS. Its only caller is
`scripts/migrate_entity_prop_sort.py` — the one-time migration. Nothing in the
running system calls it.

The maintenance job gives every other derived table a REPAIRING task and gives
these two a REPORTING one:

    edge_integrity              -> _run_edge_integrity              backfills
    frame_entity_integrity      -> _run_frame_slot_backfill          backfills
    entity_slot_sort_integrity  -> _run_entity_slot_sort_integrity   backfills
    prop_sort_coverage          -> _run_prop_sort_coverage           MEASURES ONLY

`_run_prop_sort_coverage` measures and gates — "MEASURE, RECORD, GATE" in its
own words — and never adds a row. It is easy to read that list and assume the
prop tables are covered; they are observed, not repaired.

### 2. The gate cannot SEE this shortfall, so it would have certified the table

Measured read-only against prod `wordnet_frames`, the space missing 329,235 rows:

    probe returned 4 type rows
      in_table=13880  of_type=13880  COMPLETE
      in_table=  107  of_type=  107  COMPLETE
      in_table=82115  of_type=82115  COMPLETE
      in_table=13643  of_type=13643  COMPLETE
    gaps reported: 0

Presence is tested PER SUBJECT:

    EXISTS (SELECT 1 FROM {space}_entity_prop_sort f
             WHERE f.entity_uuid = o.entity_uuid)

so ANY single row makes an entity covered. Every entity there has 2 of its 5
property rows, so all four types read complete. And because
`record_prop_sort_coverage` "takes or releases the block from the number it just
measured", running the probe would have RELEASED any block and written a
positive completeness marker. That is worse than never running: it certifies a
60%-incomplete table.

The docstring's claim that the invariant is exact — "every entity in the
denominator must have at least the row for [`hasKGEntityType`] ... Anything short
of 100% is a real gap" — is TRUE and insufficient. It detects an entity with
ZERO rows. It cannot detect an entity with SOME rows, which is the shape this gap
actually takes, because the missing thing is a PROPERTY and the probe counts
ENTITIES.

### The same blindness is in all three probes

    entity_prop_sort   WHERE f.entity_uuid = o.entity_uuid
    frame_prop_sort    WHERE f.frame_uuid  = y.frame_uuid
    entity_slot_sort   WHERE e.entity_uuid = o.entity_uuid

So `entity_slot_sort` coverage is blind to a missing SLOT TYPE in exactly the
same way — an entity present with slot type A but lacking type B reads as
covered, and a sort on B returns a short page. That matters beyond reporting,
because `issues/187`'s convergence gating consumes these numbers. Its
denominator caveat ("an entity may simply own no frames") is acknowledged in the
docstring; this per-type blindness is not.

A probe that counts subjects cannot validate a table keyed by (subject,
property). The fix is to compare PAIRS, which is what the measurement earlier in
this issue does by hand.

## What to do

### DONE 2026-09-12 (`c00a5f83`) — the entity side

**Coverage is counted in pairs.** `entity_prop_sort_coverage` now tests presence
on (entity, context, property). Validated read-only against prod before and
after, which is the point of the change:

    wordnet_frames   4 of 4 types SHORT    219,490 / 548,725 pairs
    cardiff_kg       complete              423,036 / 423,036
    lead_data        complete              395,705 / 395,705
    lead_prod        complete              186,865 / 186,865

So the gap is visible and **no live space is newly blocked** — which was the risk
of making a gate stricter.

**The maintenance loop repairs it.** `backfill_entity_prop_sort_batch`, one
bounded batch for the worst-short space per cycle. Two details are load-bearing:

* BOUNDED. `backfill_entity_prop_sort` is one unbounded `INSERT ... SELECT` over
  the whole space; under an RDS `statement_timeout` it is killed and rolls back,
  so it makes ZERO progress every cycle forever. That is `issues/151` for the
  slot table and `issues/136` for VACUUM.
* PAIR-SEEDED. `backfill_entity_slot_sort_batch` seeds on entities with NO rows
  (`NOT EXISTS ... WHERE e.entity_uuid = q.subject_uuid`). On the spaces this
  issue is about every entity already has some rows, so that seed selects
  NOTHING and the table never heals. **The blindness was in the repair as well
  as the probe** — fixing only the probe would have produced a permanent,
  correct, unactionable alarm.
  The seed also applies the derivation's full population test rather than
  `hasKGEntityType` alone; broader, it would select subjects that derive nothing
  and report "cannot converge" forever.

### STILL OPEN

1. **`frame_prop_sort` is unchanged, deliberately.** Its probe's denominator
   counts every `KGFrame` (`$1..$4` only) while the derivation stores ASSERTION
   frames only, so re-keying it to pairs would multiply an adjacent pre-existing
   denominator question rather than just fix the keying. And it does not complete
   within two minutes against prod `cardiff_kg`, so the change could not be
   validated the way the entity side was. Both need settling first: does any prod
   space carry non-Assertion frames that this probe counts?
2. **`entity_slot_sort_coverage` has the same per-subject keying** and is not
   changed here either. Its gating is entangled with `issues/187`'s convergence
   machinery, and making it stricter could take blocks on live spaces — measure
   per-slot-type completeness on prod BEFORE touching it.
3. **Wire the syncs into the seven write paths**, starting with
   `update_entity_subject_only` for `entity_prop_sort`. Lower priority now: with
   a pair-keyed probe and a working repair the drift self-heals, so this is a
   convergence-speed issue rather than a correctness one.
4. **`wordnet_frames` will converge slowly.** Every one of its 109,745 entities
   is missing pairs, at 500 per cycle — about 220 cycles. A one-off
   `resync_all_auxiliary_tables` (or the unbounded backfill in a maintenance
   window) repairs it at once. Not done: this issue has not touched prod.
5. **`prop_sort_coverage` stores pair counts in columns named `entities_in_table`
   / `entities_of_type`.** Not renamed — that is a prod migration for a comment's
   worth of clarity — but the names now understate what they hold. Note that the
   same table also receives FRAME type rows in its `entity_type_uuid` column,
   which is why `cardiff_kg` shows 32 rows for 5 entity types.
2. Until then, consider whether the import paths should take a whole-space
   `prop_sort_block`, the way `bulk_export` already does for the slot table —
   that is the mechanism designed for exactly this, and it converts a wrong
   answer into a slow one.
3. Repair `wordnet_frames` with `resync_all_auxiliary_tables`, or block it.
4. Run the migration on the local database.

The 14 pairs are named in `tests/unit/sparql_sql/test_derived_table_maintenance.py`
as `_PROP_GAP` and `_EPS_SUBJECT_GAP`, so they cannot be re-lost, and
`test_no_known_gap_still_passes` promotes each one the moment it is wired.
