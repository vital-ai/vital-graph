# Both Prop-Sort Tables Are Unmaintained By Seven Write Paths, And Were Absent From The Matrix

## Status: FIXED 2026-09-12 (`c00a5f83`, `82a9e5eb`) for both prop tables:
## coverage counts PAIRS and the maintenance loop repairs in bounded batches.
## Still open — `entity_slot_sort`'s probe has the same keying, and the seven
## write paths are still unwired (now a convergence-speed issue, not a
## correctness one).

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

1. ~~`frame_prop_sort` is unchanged~~ — **DONE in `82a9e5eb`.** Both reasons for
   deferring it were wrong, and both are worth recording because they are the
   kind of reason that sounds sufficient:

   * "the probe does not finish in two minutes against prod `cardiff_kg`" — that
     was a COMMAND TIMEOUT, not a property of the system. Raising it, the pair
     comparison completes in about two minutes.
   * "its denominator counts every `KGFrame` while the derivation stores
     Assertion frames only" — taken from `scripts/migrate_frame_prop_sort.py`,
     whose docstring was STALE. `_select_rows` indexes every frame and resolves
     form type to a column; membership by form type could only answer traversals
     whose results happened to share one (all 900,000 child frames on
     `lead_nurture_grouped` are Aspect). There was no mismatch. The docstring is
     corrected so the same inference is not drawn again.

   The general lesson: a deferral justified by a tool limit and a comment is not
   justified. Neither reason survived being checked.

   And the validation did not need prod at all. "Does this block anything live?"
   is a pair-count comparison — all four frame tables measured exactly complete
   (cardiff_kg 1,214,433, lead_data 659,772, wordnet_frames 570,696, lead_prod
   566,283) — while CORRECTNESS belongs in the local integration fixture, which
   creates these tables. Re-running the expensive probe against a 48M-quad
   production table would only have recomputed numbers already in hand.

2. ~~`entity_slot_sort_coverage` has the same per-subject keying~~ —
   **ADDRESSED in `00adfc70`, as an ALARM rather than a gate.**

   Measured first, and locally: all three local spaces with data are exactly
   complete at slot level (cardiff_kg 304,923, sp_lead_synth_100k 3,877,000,
   sp_lead_types 77,290), so the blindness is LATENT here, not active. The 10
   cardiff_kg slots absent from the table all carry no value and are correctly
   excluded — the derivation joins the value as INNER.

   The new check counts at the table's own key. The primary key is
   `(slot_uuid, context_uuid)`, so `count(*)` IS the covered-slot count, and
   that is what makes it affordable on a loop `issues/151` cleared an O(graph)
   walk off:

       quad side, count by predicate            3,388 buffers
       table side, count(*)                     3,065 buffers
       count(DISTINCT slot_uuid)            2,657,991 buffers
       the exact INTERSECT of both sides   33,929,100 buffers

   ~6.5k buffers for the question, against ~34M for the precise form. Two
   earlier formulations of "cheap" were not: a correlated `EXISTS` per slot came
   to 49M buffers.

   **It reports; it does not block, and that is the difference from the prop-sort
   fix.** Two reasons, both specific to this table:

   * it cannot ATTRIBUTE a shortfall to an entity type. A missing slot has no
     row, so the table cannot say whose it was, and `slot_sort_block` is keyed
     per entity type. Attribution needs the entity->frame->slot walk that 151
     removed from this loop.
   * the cheap number is an UPPER BOUND. Value-less slots inflate it, and
     blocking a live space over 10 of those would be a regression. Failing
     closed is only safe when the number is exact — which is why the expensive
     exact count runs ONLY to explain a nonzero cheap one, and the two causes
     are subtracted before anything is logged.

   **AND REPAIRED, `c6716b0f`.** The alarm on its own had nothing able to act on
   it: `backfill_entity_slot_sort_batch` seeds on entities with NO rows, so an
   entity holding slot-A rows while missing slot-B is never selected. That is
   exactly the state `entity_prop_sort` was in, and the reason fixing only a
   probe produces a permanent, correct, unactionable error.

   `backfill_entity_slot_sort_missing_slots` seeds on the ABSENT SLOTS, in three
   bounded steps: find them (the `NOT EXISTS` probes the primary key
   `(slot_uuid, context_uuid)`, one index probe per candidate, `LIMIT` stops
   early), resolve their entities from `frame_slot`, which stores
   `(slot_uuid, entity_uuid)` directly, then re-derive those entities
   idempotently. `frame_slot` rather than a reverse walk up `edge`: that needs
   recursion through nested frames for the same answer, and this derivation
   already walks `edge`, so it is the same class of dependency, not a new one.

   Slots with no `frame_slot` row are counted as **`unattributed`** and reported
   at ERROR, not skipped — both mirrors are short for those, so nothing
   incremental can rebuild them and `resync_all_auxiliary_tables` is the remedy.
   Returning 0 rows silently would read as "nothing to do" on a space that needs
   a full resync. (The commit message for `c6716b0f` lost that field name to
   shell backtick expansion; the field is `unattributed`.)

   **GATING IS STILL NOT DONE, and may not be the right goal.** Both available
   routes are bad:

   * per-ENTITY-TYPE attribution, which `slot_sort_block` is keyed on, needs the
     entity->frame->slot walk `issues/151` removed from this loop;
   * a WHOLE-SPACE block is exact and needs no attribution, but it turns the
     fast path off for everything — the schema comments already record an
     eleven-minute outage on a 74.5M-quad space from taking one — and it would
     do that over a shortfall that may be a single row in 3.8M.

   With a working repair the gap now closes on its own, which is what a gate was
   wanted for. The remaining question is whether a shortfall large enough to
   matter should escalate to a block, and that is a threshold decision rather
   than a measurement.
3. **Wire the syncs into the seven write paths**, starting with
   `update_entity_subject_only` for `entity_prop_sort`. Lower priority now: with
   a pair-keyed probe and a working repair the drift self-heals, so this is a
   convergence-speed issue rather than a correctness one.
4. **`wordnet_frames` will converge slowly.** Every one of its 109,745 entities
   is missing pairs, at 500 per cycle — about 220 cycles. A one-off
   `resync_all_auxiliary_tables` (or the unbounded backfill in a maintenance
   window) repairs it at once. Not done: this issue has not touched prod.
5. **Watch the probe's cost on the maintenance loop.** Re-keying to pairs adds a
   join, so both probes are more expensive than before. The job wraps them in
   `maintenance_timeouts` with `PROBE_CLIENT_TIMEOUT_S` and skips on failure via
   `log_probe_failure`, so a probe that gets too slow degrades to "no coverage
   recorded" — it takes no new block, but it also stops releasing old ones. The
   place to learn this is the job's own telemetry, not ad-hoc scans of prod.
6. **`prop_sort_coverage` stores pair counts in columns named `entities_in_table`
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
