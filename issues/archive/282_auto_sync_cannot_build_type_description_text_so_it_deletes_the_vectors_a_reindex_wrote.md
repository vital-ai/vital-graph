# 282 — Auto-sync cannot build type-description text, so it deletes the vectors a reindex wrote

## ARCHIVED 2026-10-20 — fixed and verified locally, in production with the current code (reported 2026-10-20); nothing remaining. Evidence: tests/api/test_kgtypes_entity_integration.py.

## Status: FIXED IN CODE 2026-10-19 (in production with the current code, reported 2026-10-20). Not live in production: no production space uses either affected mapping.

**Related:** `issues/244` (type-description vectorization; introduced the
cross-space sync), `issues/260` (indexing a new KGType).

## What showed it

`tests/api/test_kgtypes_entity_integration.py` passed twice on 2026-10-19 and
then failed 4 of 5 tests on every run: "Expected >=4 vectors after reindex,
got 0". The vector searches found nothing. The reindex logs
"4 processed, 4 stored", with no error.

`test_scripts/debug/_issue282_vectors_vanish.py` replays the fixture and
samples the index table every 0.2 s. The rows land and are then deleted by a
second session while the reindex is still writing. With 1,500 entities:

    rows  0 → 158 → 330 → 508 → 708 → 646 → 510 → 359 → 228 → 328 → … → 528 (of 1,500)
    session A: INSERT INTO <space>_vec_<index> …   (the reindex)
    session B: DELETE FROM <space>_vec_<index> WHERE subject_uuid = …

With 4 entities, all 4 are gone within ~0.5 s. The server logs the deleter:
`cross_space_sync: scheduling re-sync for 4 subjects in <space>
(mapping_types=['kgentity'], updated_types=[<the new type>])`. It was triggered
by the fixture's creation of the types in `sp_kg_types`. Whether it lands
before the reindex (nothing to delete) or after it (everything deleted) is a
race, which is why the test passed and then failed.

## Cause

`auto_sync` (its vector phase) builds each subject's text with
`build_search_text(props, rule)` and **never resolves the type description**.
The populator does (`KGTypeDescriptionLookup`, then
`build_search_text(..., type_description=...)`). For a mapping whose
`source_type` is:

* `type_description`: `build_search_text` returns `""` without a description,
  so the subject goes to `to_delete` and its vector is removed;
* `properties_type`: the text is built from the properties alone, so the vector
  differs from the one a reindex writes for the same subject.

Two triggers reach it:

1. **The cross-space sync** (`kgtype_cross_space_sync`, `issues/244`). Its job
   is to refresh, after a KGType changes, the vectors of every subject of that
   type in spaces with a type-description mapping. Through auto-sync it
   deletes them instead.
2. **Ordinary auto-sync on an entity write**, in any space with such a
   mapping. Each write deletes (or degrades) that entity's vector, so a
   type-description index only stays complete until its entities are next
   written.

`populate_subject` (the per-subject populator path) handles both source types
correctly. Auto-sync is the copy that does not.

## Production

Checked read-only on 2026-10-19 (`vitalgraph-pg18-prod`, every
`<space>_search_mapping`): **no space has a `type_description` or
`properties_type` mapping**. Every mapping is `default` (document segments) or
`properties` (slots, KG types), and neither uses a type description. So nothing
has been lost. The defect was latent until such a mapping was configured.

## Fixed (code)

* `auto_sync`'s vector phase resolves each subject's mapping first, then
  batch-looks-up the type descriptions for the subjects whose rule needs one
  (`KGTypeDescriptionLookup`, one call for type URIs and one for descriptions
  per mapping type, as the populator does), and builds the text with them.
  A `type_description` rule is built from the type alone, as in the populator.
  The FTS phase was already right: it delegates to `update_subject_fts` with
  the rule, and that resolves the description.

## Verification

vg test stack, rebuilt:

* `tests/api/test_kgtypes_entity_integration.py`: all 7 pass on two runs,
  including the new `TestTypeDescriptionVectorsSurviveSync` (the cross-space
  sync leaves every vector; an entity write keeps its own). Before the fix
  the file's 4 vector tests failed on every run. The two new tests were not
  run against the old code.
* `test_scripts/debug/_issue282_vectors_vanish.py` with 1,500 entities: the
  row count rises monotonically to 1,500, with no deletes. Before the fix it
  peaked at 708 and settled at 528.
* Unit suite passes.
