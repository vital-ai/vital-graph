# 328 — Replaying the schema duplicated the quad statistics on spaces named before storage keys

## Status: FIXED 2026-10-28, not yet released; verified on the vg test stack rebuilt for the fix (unit, DAWG conformance, integration and API suites, 0 failures). Open for one read-only production check: duplicate or old-named statistics objects.

**Found:** 2026-10-28, while fixing `test_extended_stats_fix_correlation_estimate`
(it failed with `est = actual = 4,170` where it expected a large underestimate).
**Related:** the storage-key rename (`planning/planning_db/space_storage_key_plan.md`),
`issues/136` (production ANALYZE / VACUUM killed by `statement_timeout`).

## What

Each space's quad table carries one extended-statistics object on
`(predicate_uuid, object_uuid)`, `(mcv, ndistinct)` at target 1000: the
correlation fix for slot-value leaves. The schema created it as

    CREATE STATISTICS IF NOT EXISTS stat_<prefix>_quad_po ...
    ALTER STATISTICS stat_<prefix>_quad_po SET STATISTICS 1000

where `<prefix>` is the space's current name prefix. A space created BEFORE
storage keys has the object as `stat_<space id>_quad_po`, on a table that was
later re-keyed to `vgs_<key>_rdf_quad`. The object kept its old name.

That DDL is REPLAYED on existing spaces: `scripts/ensure_space_indexes.py`
replays all of it on purpose (`issues/056`), and so do the schema migrations
and `partition_migrate`. On a re-keyed space the `IF NOT EXISTS` looks for
`stat_vgs_<key>_quad_po`, does not find it, and creates a SECOND object on the
same columns. Every ANALYZE of that table then builds both 1,000-entry MCV
lists: the most expensive part of ANALYZE, twice, on the biggest table, on an
RDS instance where ANALYZE and VACUUM already run into `statement_timeout`.

On the vg test stack: 462 objects under the current name, **26 under an old
one**, and **one table with both** (`space_lead_dataset_test`). That duplicate
was made by the correlation test itself, which hand-wrote the same
`CREATE ... IF NOT EXISTS` and then dropped only the new-named object, so its
"without statistics" arm still had them.

Not affected: `sync_frame_slot_table` and `space_indexes` keep only the
`CREATE INDEX` statements of the replay.

## Fix

`sparql_sql_schema.quad_po_statistics_sql(space_id, table)`, one `DO` block in
place of the two statements. It finds the table's statistics objects by
TABLE AND COLUMNS (`pg_statistic_ext.stxkeys`), not by name:

* one under the current name: kept;
* one under any other name: RENAMED to the current name;
* more than one: the current-named one (or the first) kept, the rest DROPPED;
* none: created;

then the target is set to 1000. So every replay path now heals an old-named
space instead of duplicating it. The correlation test uses the same statement.

**Where the old names came from: the re-key and the rename never moved the
statistics object.** `space_rename.object_rename_statements`, shared by both,
renamed constraints, triggers, indexes, sequences, functions and tables, not
`pg_statistic_ext`. So every re-key left `stat_<space id>_quad_po` on the new
`vgs_<key>_rdf_quad`. It now renames the object with its quad table
(`stat_<table's new prefix>_quad_po`), targeted from the table's new name so
an object an earlier re-key stranded is put right, not refused.

The first version of the reconcile statement broke the re-key: its name probe
creates the schema under the target prefix in a rolled-back savepoint, and on a
move BACK to the id prefix the space's own stranded object already held
`stat_<id>_quad_po`. The old `IF NOT EXISTS` skipped silently; the new create
collided (7 `test_space_rekey` failures). The statement now also handles its
name held by ANOTHER table's object: renamed to that table's own name, or
dropped when that table already has one.

## Verification

`tests/integration/test_quad_statistics_are_reconciled_not_duplicated.py`: a
new space has exactly one object; an old-named one is renamed; a duplicate is
dropped; none is created; a replay changes nothing.
`tests/integration/test_space_rekey.py` round trips now assert the statistics
object carries the key's name under the key and the id's name after the move
back. Applied by hand to the two
real cases on the vg test stack (`space_lead_dataset_test`: duplicate dropped;
`sp_lead_dup`: renamed), idempotent on a second run.

## Remaining

* Production, read-only: count `pg_statistic_ext` objects per quad table
  (more than one = a duplicate made by a replay), and old-named ones. A
  duplicate is removed by the next replay of the fixed DDL
  (`ensure_space_indexes.py`); no separate migration is needed.
