# 246 — Five auto-named UNIQUE constraints are truncated on every space, so the id ceiling is a fiction

## Status: RESOLVED BY REFUSAL 2026-09-27 — decided: where truncation cannot be
## prevented, refuse the operations that make it worse. The schema is UNCHANGED
## and no migration was run; the rename now declines to re-truncate. The fix
## proposed further down (name the constraints explicitly) is NOT done and is
## recorded as what it would take to lift the restriction.

## The decision: just refuse

The proposed fix below — name the over-long constraints explicitly, migrate, and
correct `max_space_id_bytes()` — was weighed and **rejected as the first move**,
because measurement showed a corrected ceiling is unusable:

| ceiling, computed honestly over every auto-generated name | value |
|---|---|
| as the schema stands today | **−7** |
| if every over-long UNIQUE were named explicitly | **6** |

At −7 no space id is legal. At 6, `lead_prod` (9), `prod_kg` (10) and
`wordnet_frames` (14) are all illegal — every space that exists. The residual
bound at 6 is not the UNIQUEs at all but PG18's NAMED NOT-NULL constraints on
`document_segmentation_config`, at 56-57 bytes of suffix. Making the guard honest
therefore requires shortening that TABLE name, which is a migration across every
space rather than a refusal.

So: **there is no ceiling that prevents this, and the only available remedy is to
decline the operations that worsen it.**

### What refuses, in `space_rename`

  * **A length-changing rename is REFUSED** when any object name is already at
    63 bytes — which is every real space, because those five UNIQUE names are
    truncated at any id length. Renaming to a different length re-truncates them
    to something that is neither the old name nor what a fresh `CREATE` would
    produce, and renaming back cannot restore it.
  * **Same-length renames are unaffected** and fully reversible.
  * **`allow_retruncation=True`** takes the loss deliberately. It only helps when
    SHORTENING; lengthening stays blocked by the separate 63-byte check, because
    a name that does not fit is a different problem from one that re-truncates.

The cost is stated plainly: shortening an over-long id — the reason rename exists
— now requires the explicit opt-in. That is the honest position until the
constraint names are shortened.

### A blind spot this found in the guard that preceded it

The earlier 63-byte check parsed only `" RENAME TO "`, so it never length-checked
a single CONSTRAINT name — `ALTER TABLE t RENAME CONSTRAINT a TO b` does not
contain that marker. Constraints are 166 of a space's ~313 objects and the
auto-named ones are the LONGEST, so the check was blind to exactly the names it
existed for. Found by the re-truncation check, not by review.

**Tests:** 6 more in `tests/integration/test_space_rename.py` (22 total), covering
the refusal in both directions, the message naming the way out, the opt-in
working for a shortening, and lengthening staying blocked even with it.

**Related:** `issues/196` (the same failure, for explicitly-named INDEXES —
fixed, and its fix is the template), `issues/232` (the rename that found this;
its length guard is the reason it surfaced), `sparql_sql_schema.max_space_id_bytes`
(the function whose answer is wrong)

## The defect

`max_space_id_bytes()` reports **34**. It derives that from the longest name the
schema CREATES EXPLICITLY — since `issues/196` shortened five index names, the
bound is the TABLE `{space}_document_segmentation_config` at 29 bytes of suffix,
so 63 − 29 = 34.

It does not account for the names PostgreSQL generates ITSELF. A `UNIQUE
(document_type_uri, segment_method_uri)` constraint is auto-named from the table
plus the column list:

    {space}_document_segmentation_config_document_type_uri_segment_method_uri_key

That suffix alone is **70 bytes**, before a single byte of space id. The ceiling it
implies is **negative**: there is no space id short enough to avoid truncation.

PostgreSQL does not error. `makeObjectName` shortens the constituent parts to fit
63 bytes and carries on silently, which is the same mechanism `issues/196`
recorded — an object under a name the schema never asked for.

## Measured, on `wordnet_frames` (a 14-byte id)

Five names, each sitting at exactly 63 bytes, each with a visibly shortened middle:

    wordnet_frames_document_segme_document_type_uri_segment_met_key
    wordnet_frames_fuzzy_mapping_proper_mapping_id_property_uri_key
    wordnet_frames_geo_subject_uuid_source_slot_uuid_context_uu_key
    wordnet_frames_search_mapping_mapping_id_index_type_index_n_key
    wordnet_frames_search_mapping_prope_mapping_id_property_uri_key

Note `document_segme`, `fuzzy_mapping_proper`, `search_mapping_prope` — the table
part was truncated to make room for the column list. And separately, the
auto-named SEQUENCE `{space}_document_segmentation_config_config_id_seq` is 42
bytes of suffix, a ceiling of 21, which `space_lead_dataset_test` (23 bytes)
already exceeds:

    space_lead_dataset_test_document_segmentation_con_config_id_seq

## Why it matters, in order of how much

**1. Every name-based routine disagrees with reality.** `classify_space_table`,
`orphan_tables_for_space`, the schema-completeness check and
`scripts/cleanup_orphan_space_tables.py` all reason about objects by name. A
truncated name is not the name they compute, so these five constraints are
invisible to all of them — on every space that exists.

**2. A rename cannot be reversible across a length change.** This is how it was
found. `issues/232`'s rename maps each object name to the new id and refuses if
the result would exceed 63 bytes. For an already-truncated name the mapping is
lossy in both directions: renaming to a longer id is refused (correctly), and
renaming to a shorter one produces a name PostgreSQL re-truncates differently, so
renaming back does not restore what was there. The rename's own tests can only
assert reversibility across a SAME-LENGTH rename, which is a real limitation
rather than a test convenience.

**3. `max_space_id_bytes()` is a guard that does not guard.** It refuses a
35-byte id while permitting a 22-byte one that silently truncates a sequence and a
34-byte one that truncates five constraints. `issues/196` moved this bound once
already, believing the binding name was a table; it is not.

## Who is affected

  * **Production: not in the way the ceiling implies.** No production space id
    exceeds 21 bytes, so no sequence name is truncated there. But all seven
    production spaces DO carry the five truncated constraint names, because those
    are over the limit at any id length.
  * **The vg test stack:** `space_lead_dataset_test` (23 bytes) additionally has
    the truncated sequence name shown above.
  * **Any new space** with an id over 21 bytes will acquire the truncated
    sequence; any space at all has the five constraints.

## The fix, and it is the `issues/196` fix again

**Name them explicitly and shortly.** `issues/196` did exactly this for five
index names and moved the ceiling from 21 to 34 for every space at once. The same
applies here: give these five constraints explicit `CONSTRAINT <short_name>
UNIQUE (...)` names in the schema, and add the auto-named sequences to whatever
`max_space_id_bytes()` measures.

Three parts, and the third is the one that keeps it fixed:

1. **Name the five constraints explicitly** in `sparql_sql_schema.py`. A
   `CONSTRAINT` clause is the only way to stop PostgreSQL choosing; there is no
   setting.
2. **A migration for existing spaces**, `ALTER TABLE … RENAME CONSTRAINT`, which
   is catalogue-only and instant — the `issues/196` migration is the template,
   including its handling of names already truncated.
3. **Make `max_space_id_bytes()` measure what PostgreSQL will actually name**,
   not only what the schema writes. Until it does, the next suffix added to a
   table with a multi-column UNIQUE will reintroduce this silently. That function
   is where the belief lives, so that is where the fix has to land.

## It is not five, and it scales with the id

The title undercounts: measured on the vg stack, the number of constraint names
sitting at exactly 63 bytes grows with the space id.

| space | id bytes | truncated constraint names |
|---|---:|---:|
| `wordnet_frames` | 14 | **11** |
| `sp_lead_synth_10k` | 17 | **16** |
| `space_lead_dataset_test` | 23 | **34** |

The five UNIQUE constraints are simply the ones that truncate at ANY length.
Beyond them, PG18's NAMED NOT-NULL constraints on the long-named tables start
going over as the id grows — at 23 bytes they read like
`space_lead_dataset_test_document_se_max_segment_tokens_not_null`, with
`document_segmentation_config` shortened to `document_se`.

So the picture is not "five bad names" but "a ceiling that is wrong by a margin
that widens with the id", and the widening is invisible because nothing reads
these names.

## Not established

  * Whether the five truncated names are STABLE — i.e. whether two databases with
    the same space id always get the same truncation. `makeObjectName` is
    deterministic, so they should be, but nothing has compared two installs.
  * Whether anything READS these constraint names. Nothing found does, which is
    why this has been invisible; a `pg_constraint` lookup by name in a migration
    or repair script would have failed loudly long ago.
  * FK names: CHECKED, and not truncated at 14 bytes — no `%fkey%` name on
    `wordnet_frames` reaches 62. `{space}_search_mapping_property_mapping_id_fkey`
    is 45 bytes of suffix, so the bound is 18 and a 19-byte id would start
    truncating them. Not verified at that length.
  * What the real ceiling is once everything auto-named is counted. For a name
    that truncates at any length there IS no ceiling, so the honest statement is
    that `max_space_id_bytes()` cannot be made correct by lowering the number —
    the over-long names have to be named explicitly instead, which is why the fix
    is `issues/196`'s and not a smaller constant.
