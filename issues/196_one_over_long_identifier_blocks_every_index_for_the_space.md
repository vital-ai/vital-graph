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

**Option 3 as well, 2026-09-14 — the suffix is shortened, so nothing is refused.**

The name that bound everything was 42 bytes of suffix. It and its four
`segmentation_jobs` siblings now use the `idx_{space}_<short>` convention the
schema already used elsewhere:

    {space}_document_segmentation_config_doc_type_idx  ->  idx_{space}_dsc_doctype
    {space}_segmentation_jobs_status_idx               ->  idx_{space}_sj_status
    {space}_segmentation_jobs_document_idx             ->  idx_{space}_sj_doc
    {space}_segmentation_jobs_space_idx                ->  idx_{space}_sj_space
    {space}_segmentation_jobs_active_doc_uq            ->  idx_{space}_sj_active_uq

    longest supported space id   21 bytes  ->  34 bytes

`space_lead_dataset_test` (23 bytes) now generates all 71 index statements with
NOTHING refused, so it does not need renaming after all — which is the answer to
"why not just rename it": the rename would have cost 15 baseline benches, ~10
source files and a re-promotion, to buy a correctly-named index on an empty
table. This buys the ceiling for every space at once instead.

The bound is now the TABLE name `{space}_document_segmentation_config` at 29
bytes. Moving that needs a data migration and is a different change; worth doing
only if 34 ever proves tight.

### The existing spaces are migrated, not just the schema

`scripts/migrate_shorten_index_names.py` renamed **769 indexes across 156
spaces** with `ALTER INDEX ... RENAME TO` — a catalogue update, atomic, no
rebuild, and no window where a live table is unindexed. Total index count
17,075 before and after, which is the check that it renamed rather than dropped.

It matches TRUNCATED names too, and that is the part worth keeping. The 65-byte
name existed as `..._doc_type_i` at exactly 63 bytes — created before the guard,
silently shortened by PostgreSQL, and therefore an orphan under a name the
schema never asked for. It is now `idx_space_lead_dataset_test_dsc_doctype`.
That is this issue's own failure mode, found already realised in the data.

Left alone deliberately: 161 `{space}_segmentation_jobs_pkey` names, which
PostgreSQL generates for primary keys and whose 23-byte suffix does not bind;
and the 63-byte `..._key` UNIQUE constraint names, which PostgreSQL truncates
itself and disambiguates, so they are not the silent-collision hazard the guard
addresses.

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
