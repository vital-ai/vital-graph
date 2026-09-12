# Both Prop-Sort Tables Are Unmaintained By Seven Write Paths, And Were Absent From The Matrix

## Status: OPEN 2026-09-12 — latent on all three live prod spaces, ACTIVE on one
## perf-test space. The matrix now names the gaps; the syncs are not wired.

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

## What to do

1. Wire `sync_entity_prop_sort` / `sync_frame_prop_sort` into the seven paths,
   starting with `update_entity_subject_only` for `entity_prop_sort`.
2. Until then, consider whether the import paths should take a whole-space
   `prop_sort_block`, the way `bulk_export` already does for the slot table —
   that is the mechanism designed for exactly this, and it converts a wrong
   answer into a slow one.
3. Repair `wordnet_frames` with `resync_all_auxiliary_tables`, or block it.
4. Run the migration on the local database.

The 14 pairs are named in `tests/unit/sparql_sql/test_derived_table_maintenance.py`
as `_PROP_GAP` and `_EPS_SUBJECT_GAP`, so they cannot be re-lost, and
`test_no_known_gap_still_passes` promotes each one the moment it is wired.
