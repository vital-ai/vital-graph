# 338: `/fuzzy-mappings/populate` resolves every mapping as `kgentity`, and answers OK when it indexes nothing

## Status: FIXED 2026-11-12 (uncommitted), together with `339`; verified on the vg test stack: unit 6,343 passed; W3C/DAWG conformance 1,532 passed; fuzzy integration 14; API 37 (new + mappings) and 73 (auto-sync, kgqueries, text and geo search).

Found 2026-11-12 while answering a question from a client service's
session about indexing funder names on `KGEntityMention` nodes.

## The defect

`fuzzy_mappings_endpoint._run_populate` called
`populate_fuzzy_index(conn, space_id, index_name=...)` and left the function's
defaults in place: `mapping_type="kgentity"`, `type_uri=None`.
`resolve_fuzzy_mapping` then required `m.mapping_type = 'kgentity'`. So:

- **a mapping of any other type** (`kgframe`, `kgslot`, `kgdocument`) was never
  found. The populator logged a warning and indexed 0 subjects;
- **a `kgentity` mapping with a `type_uri`** was found only through the
  `type_uri IS NULL` branch, so populate picked whichever class-level mapping
  shared its `index_name`, if there was one;
- the endpoint answered `status: ok` **before** the background task ran, so a
  population that indexed nothing looked identical to one that worked.
  The only trace was a server-log warning.

Auto-sync did not have this problem (it used `339`'s first-mapping resolver),
so a non-kgentity mapping did get subjects indexed as they were written. It
could never be built or rebuilt for data already in the space.

## Fix

Populate no longer resolves a mapping. The space has one pair of band tables
and its fuzzy index is the union of its enabled mappings (`339`), so
populating any mapping rebuilds that one index from every enabled mapping:
`populate_fuzzy_index(conn, space_id)`.

The endpoint resolves the index **before** it starts the background task:

- no enabled mapping with a property: `status: no_op`, "nothing to index",
  and nothing is truncated;
- otherwise `status: ok`, with a message naming the mappings being built from,
  and saying so if the one asked for is disabled or has no properties.

## Not changed

- A mapping's `type_uri` is stored and returned but filters nothing. It never
  did, at populate, at sync or at query time. Making it filter by
  `hasKGEntityType` would narrow every existing typed mapping on every install,
  so that is a separate decision.
- Disabling or deleting a mapping does not remove the rows it contributed
  until the next populate, or the next write of each subject. That was true
  before as well.

## Tests

`tests/api/test_fuzzy_match_api.py`:
- `test_populate_indexes_a_mapping_with_no_type_filter`: a `kgframe` mapping
  on `hasName` indexes all 4 named subjects, including the `KGEntityMention`,
  and a query finds the mention. On the old code it indexed 0.
- `test_populate_of_a_kgentity_mapping_keeps_its_type_filter`: 3, not 4.
- `test_populate_with_nothing_to_index_says_so`: `no_op`.
