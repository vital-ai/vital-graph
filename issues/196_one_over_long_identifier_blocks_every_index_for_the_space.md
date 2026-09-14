# One Over-Long Identifier Blocks EVERY Index For The Space

## Status: FIXED 2026-09-14 — options 1 and 2, and the fixture is repaired

Both halves of the recommendation below, and the space did NOT need renaming.

**1. The check is per-STATEMENT now.** `split_by_identifier_fit` emits the index
SQL that fits and refuses only the statements that do not, reporting them at
ERROR with the space id's byte count and the limit. `space_lead_dataset_test`
went from raising — 0 index statements — to 70 of 71.

**2. The limit is enforced where a space is CREATED.** `SparqlSQLSchema.create_space`
refuses an over-long id outright, which is where a rename is free.

That second half is not optional, and finding out why was the useful part: the
generators CANNOT hold this check. `max_space_id_bytes` derives the limit by
CALLING them, so a check inside one recurses — and the names that overflow first
are INDEX names, so `create_space_tables_sql` never sees the problem at all.
Without the creation-time check, making index generation partial would have
traded a loud refusal for a silent one: an over-long space would be created
looking fine and quietly missing indexes.

**The fixture is repaired.** `space_lead_dataset_test_frame_slot` now has 7
indexes, matching a healthy space exactly, applied from the SQL the fixed
generator produces.

    before   1 index   (PK only, created with the table)
    after    7 indexes (== sp_graph_rel_10k_frame_slot)

The one genuinely impossible name — `space_lead_dataset_test_document_segmentation
_config_doc_type_idx` at 65 bytes — is still refused, still reported, and still
needs a rename or option 3 to recover. That is one index on one table, not the
whole space.

## Original filing

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
