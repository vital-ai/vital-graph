# One Over-Long Identifier Blocks EVERY Index For The Space

## Status: OPEN, found 2026-09-12 while migrating the perf fixtures for
## `issues/195`. `space_lead_dataset_test` has a `frame_slot` table with 0 rows
## and 1 index where a healthy space has 7, and cannot be repaired without
## renaming the space.

**Related:** `issues/195` (found here — the fixture that could not be
migrated), `issues/183` (the `frame_slot` retirement this surfaced during)

## The defect

`SparqlSQLSchema.assert_identifiers_fit` refuses to generate index SQL when ANY
generated identifier would exceed PostgreSQL's 63-byte limit. For
`space_lead_dataset_test` (23 bytes) exactly one does:

    space_lead_dataset_test_document_segmentation_config_doc_type_idx    65 bytes

    "1 generated identifier(s) ... would be SILENTLY TRUNCATED. Shorten the
     space id by 2 byte(s); the longest this schema supports is 21."

**The refusal is right.** Two identifiers truncated to the same 63 bytes collide,
and PostgreSQL does it silently — that is exactly the failure the guard exists
to prevent, and it should not be softened.

**Its BLAST RADIUS is wrong.** The check is all-or-nothing over the whole space,
so one over-long name on `document_segmentation_config` — a table nothing in
this migration touches — takes down index creation for every other table too.
The `frame_slot` indexes are 34 to 42 bytes and fit comfortably:

    idx_space_lead_dataset_test_fs_cover          36
    idx_space_lead_dataset_test_fs_role_entity    42
    idx_space_lead_dataset_test_fs_entity_role    42
    idx_space_lead_dataset_test_fs_frame_role     41
    idx_space_lead_dataset_test_fs_slot           35
    idx_space_lead_dataset_test_fs_ctx            34

None of them were created.

## What it leaves behind

A HALF-MIGRATED table: `CREATE TABLE` succeeded, the indexes did not, and the
populate never ran. The space has the table, 0 rows, and 1 index (the primary
key, created with the table) against 7 on a healthy space.

**This is safe, and that is worth stating precisely.** `ensure_frame_slot_table`
returns true only when the table exists AND HOLDS ROWS, so with 0 rows the
rewrite declines and queries fall back to the quad joins. Nothing returns a
wrong answer.

What it costs is the collapse, permanently — and `issues/195` measured what
losing the collapse costs on an unfiltered multi-hop walk: an estimated plan
cost of 19,282,929,239,712 against 47.77, and a bench that ran 24m41s without
finishing. `space_lead_dataset_test` is a GATED perf fixture, so it carries that
exposure into any bench that walks it.

## Scope

One space of 155 on the test stack. The limit is `len(space_id) <= 21`;
`space_lead_dataset_test` is 23. Nothing else is close, so this is not
widespread — but the limit is undocumented anywhere a space gets created, so
the next 22-byte space id hits it the same way.

## What to do

Three options, and the first two are not exclusive:

1. **Make the check per-STATEMENT rather than per-space.** Emit the index SQL
   that fits, refuse only the statements that do not, and report those loudly.
   One bad name on an unrelated table should not deny a space every index it
   could legally have.
2. **Enforce the limit where a space is CREATED**, not where its DDL is
   generated. A space id that cannot carry this schema's identifiers should be
   refused at creation, when renaming is free, rather than at the first
   migration that happens to touch it — which is months later and after data
   has been loaded.
3. **Shorten the generated name.** `{space}_document_segmentation_config_doc_type_idx`
   is 42 bytes of suffix. A hashed or abbreviated form would raise the space-id
   ceiling for every space at once, and is the only option that fixes the
   existing fixture without renaming it.

Renaming `space_lead_dataset_test` is the quick unblock for the fixture, but it
is a fixture rename with baseline consequences (`issues/190`), so it should not
be done casually mid-investigation.
