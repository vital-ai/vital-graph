# 303 — Partition migration drops the triggers on `rdf_quad`

## Status: RESOLVED 2026-10-29 (not yet released): the migration carries every trigger on its three tables across the swap. Verified on the vg test stack. Was: OPEN, LATENT (reproduced 2026-10-24 on the planner stack); only `tests/performance/test_partition_pruning.py` calls the migration.

**Related:** `issues/291` (the index-sync trigger), `write_log.py` (the write-log
trigger), `partition_migrate.py`.

## Found

While designing the write log: a verdict that relies on a trigger must survive
every way the table under it can be replaced. `migrate_space_to_partitioned`
builds `{space}_rdf_quad_new` with `LIKE {q} INCLUDING DEFAULTS`, copies the
rows, then `DROP TABLE {q} CASCADE` and renames `_new` into place. `LIKE` copies
no triggers, and the `DROP` removes the old ones. Nothing recreates them.

## Reproduced

`test_scripts/debug/_partition_migrate_drops_triggers.py`: a scratch space
created and deleted through the API, the write log installed by its script, one
triple written, then the migration in one transaction:

```
before: b'r' ['trg_vgs_nhqjvouk_isq_del', 'trg_vgs_nhqjvouk_isq_ins', 'trg_vgs_nhqjvouk_wlog']
migrate: {'old_quads': 1, 'new_quads': 1, 'dupes_dropped': 0}
after:  b'p' []
a write after the migration: index-sync rows queued 0, write log 1 -> 1
```

## Why it matters

- **The index-sync trigger** (`issues/291`) is the outbox for vectors and FTS on
  every write path. Without it, SPARQL UPDATE, the objects endpoint and
  relations stop queueing their subjects, so their vectors and FTS rows go
  stale, silently. The paths that also enqueue after the write keep working only
  where they check for the trigger's absence (cached per process, so a long-lived
  server can keep believing it is there).
- **The write log** stops counting. The pattern verdicts that rely on it are safe
  (a reader requires the trigger present and enabled and the quad table's OID
  unchanged, and the swap changes the OID), but they stay unusable until the
  trigger is reinstalled: `scripts/install_write_log.py --space S --apply` repairs it.

The migration also replaces `edge` and `frame_slot`; whether anything hangs a
trigger on those was not checked.

## Fix

Recreate the triggers from their own definitions after the swap, in the same
transaction: `index_sync_trigger.create_sql(space_id)` and, where the space had
it, `write_log.create_sql(space_id)`. Then test it: the repro script must report
the same trigger list before and after, and a write after the migration must
queue a subject and count in the log.

## Fixed, 2026-10-29

Not the two known definitions, as proposed above, but every trigger the
catalogue holds: `partition_migrate._triggers_of` reads the user-defined
(non-internal) triggers on `rdf_quad`, `edge` and `frame_slot` with
`pg_get_triggerdef` before the swap, and replays them after the rename, then
re-disables any that were disabled. The new table takes the old name, so each
definition applies unchanged; the trigger functions survive the `DROP ...
CASCADE`. Any trigger added later, on any of the three tables, comes across
too, which also settles the "edge and frame_slot were not checked" point above.

Both triggers in use are statement-level with transition tables, which
PostgreSQL allows on a partitioned parent (they collect the rows of every
partition), and both derive the space from `TG_TABLE_NAME`, the parent's name.

`tests/integration/test_partition_migration_keeps_the_triggers.py`: the
trigger list (names and enabled state) is identical after the migration, the
table is partitioned, and a write afterwards queues its subject for index sync
and counts in the write log; a disabled trigger stays disabled. Both fail on
the old code (the list comes back empty). `tests/performance/test_partition_pruning.py`,
the migration's other caller, passes.
