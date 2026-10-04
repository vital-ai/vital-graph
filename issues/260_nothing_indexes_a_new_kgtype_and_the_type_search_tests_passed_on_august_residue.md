# 260 — Nothing indexes a new KGType, and the type search tests passed on August residue

## Status: FIXED 2026-10-04 (uncommitted). Found by the deploy session running
## `tests/api` against the test deployment; cause established and fixed here.

## What was seen

Against the test deployment, five tests in
`tests/api/test_kgtypes_api.py::TestKGTypeSearch` failed — `test_fts_search`,
the three vector searches and `test_hybrid_search` — while the two keyword
searches passed. Keyword search reads the quad store; the five read the FTS and
vector indexes. Measured there: a new type's 5 quads land, and `fts=0 vec=0`
for it at every check out to 30s, with no `auto_sync` / `vectoriz` /
`kgtype_default` line in a DEBUG log of that window.

The same five PASSED on the local stack at the same commit, which made it look
like an environment difference for most of a day. It was not: the types space
on the local stacks held index rows from 2026-08-18, for types with the SAME
NAMES left behind by a run whose teardown did not finish, and the tests matched
results by name.

## Cause

`vectorization/auto_sync._subject_scopes` decides what each written subject is,
so the index's mapping can be resolved for it. It had branches for a slot, an
entity, a document segment and a document, and a fallback of
`("kgentity", rdf:type)`. **No branch for a KGType.** A new type fell to the
fallback; `sp_kg_types`'s `kgtype_default` index has only `kgtype` mappings, so
nothing resolved; and since `issues/219` ("no mapping now means skip") the sync
skipped the subject — deleting any row it had, logging nothing.

So nothing has indexed a new or changed KGType since `issues/219`
(2026-08-18 is the newest row on both local stacks). The deploy session's
suspicion — `db_impl` None in `kgtypes_endpoint._schedule_auto_sync` — does not
hold: the entity routes use the identical helper and their auto-sync works; the
task ran and found nothing in scope. Same shape as `issues/245`, where document
segments fell to the same fallback.

## Fix

`_subject_scopes` classifies a subject whose `rdf:type` is `KGType` or any
subclass as `("kgtype", rdf:type)`, before every other branch — resolved the
way the bulk populator resolves the `kgtype` scope
(`vector_populator._resolve_vitaltype_filter`, from VitalSigns). And a subject
out of scope for an index is now said at DEBUG on both the vector and FTS
paths: it is the normal case, and also exactly how a missing scope looks.

## Tests

- `tests/unit/test_auto_sync_scopes_a_kgtype.py`: a KGEntityType, KGFrameType,
  KGSlotType and KGType are each `kgtype`; an entity and a slot are unchanged.
  4 of the 6 FAIL without the fix.
- `TestKGTypeSearch` now matches results by the URI the fixture created, not by
  name, and the fixture's index check counts the three types it created rather
  than the table (that half from the deploy session). On the local stack, with
  `auto_sync.py` at HEAD: the fixture warns `fts=0 vector=0` and the five FAIL
  exactly as on the deployment — results contain an older "PersonSearchTest",
  never the new one. With the fix: 21/21 and no warning.

## Deploy note

Types created on production since 2026-08-18 are not in `sp_kg_types`'s indexes.
After deploying, re-populate `kgtype_default` there (the bulk populator handles
the `kgtype` scope correctly) and check that the residue is gone.
