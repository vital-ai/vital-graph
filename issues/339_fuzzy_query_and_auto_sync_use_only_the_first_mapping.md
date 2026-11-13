# 339: Fuzzy queries and auto-sync use only the first enabled mapping in a space

## Status: FIXED 2026-11-12 (uncommitted), together with `338`; verified on the vg test stack: unit 6,343 passed; W3C/DAWG conformance 1,532 passed; fuzzy integration 14; API 37 (new + mappings) and 73 (auto-sync, kgqueries, text and geo search).

Found 2026-11-12, reading the code to answer a client service's questions
about a funder-name index.

## The defect

`vg_resolve._resolve_single_fuzzy` (the `vg:fuzzyMatch` resolver) and
`fuzzy_populator.update_subject_fuzzy` (auto-sync on every write) both called
`resolve_any_fuzzy_mapping`: `WHERE enabled ORDER BY mapping_id LIMIT 1`. So in
a space with two enabled mappings, the second was invisible to both:

- its properties were never scored at query time, because candidate names were
  read through the first mapping's properties only;
- a write never indexed them;
- but populate (`338`), when it found a mapping at all, found one by
  `index_name` and type, which could be the second. The three paths could each
  read a different mapping.

The `index_name` passed when creating a mapping suggests separate indexes per
space. There are none: a space has ONE `{space}_fuzzy_band` and one
`{space}_fuzzy_phonetic_band`, keyed by subject, recording no mapping, and
populate TRUNCATEs both.

## Fix

The space's fuzzy index is now explicitly the union of its enabled mappings:
`fuzzy_mapping_manager.SpaceFuzzyIndex`, from `resolve_space_fuzzy_index`.

- **Scopes.** Each enabled mapping with properties contributes a scope: its
  properties, on subjects of its mapping type's exact `rdf:type` (`kgentity`
  means KGEntity, `kgdocument` means KGDocument), or on any subject for a type
  with no filter. `MAPPING_TYPE_RDF_TYPES` moved to the manager unchanged.
- **One reader of names.** `fuzzy_populator.fetch_scoped_names` returns each
  subject's names under those scopes, deduplicated. Populate, per-subject sync
  and the query's candidate scoring all use it, so the three agree. The query
  previously read every mapped property on a candidate with no type check, so a
  value it never indexed could still be scored.
- **Settings.** The band tables hold one set of MinHash parameters, taken from
  the enabled mapping with the lowest id. Creating or updating an enabled
  mapping whose own `shingle_k`/`num_perm`/`lsh_threshold`/`phonetic_bonus`
  differ now returns a message saying which mapping's settings are in use. Its
  properties are indexed either way.
- **Sync repairs.** `update_subject_fuzzy` deletes the subject's rows before
  checking scope. A subject no mapping covers now ends with no rows, where it
  previously returned early and kept stale ones (the same repair `issues/219`
  made for vectors).

No schema change. A space with one mapping sees three small changes:
- a name repeated on two mapped properties is indexed once;
- a candidate is scored only on names its mapping covers;
- an out-of-scope subject loses stale rows on its next write.

Its index is otherwise unchanged.

## Tests

`tests/api/test_fuzzy_match_api.py`:
- `test_a_second_mappings_property_is_searched`: two `kgentity` mappings,
  `hasName` and an alias property. Populating either finds a funder by its
  alias at score 100.
- `test_auto_sync_indexes_a_second_mappings_property`: an alias written after
  populate is found by query once auto-sync has run.
- `test_mappings_with_different_settings_are_reported`.
