# 244 — Type-description vectorization read a property a type object cannot carry, and the cross-space sync query never compiled

## Status: BOTH FIXED 2026-09-26, verified against a rebuilt stack — the four
## `test_kgtypes_entity_integration` failures go green. Found while asked to fix
## the vectorization failures in `tests/api` rather than argue they predated me.

**Related:** `issues/219` (the vector auto-sync that embedded the wrong text — the
same subsystem, and the fix that introduced deliberate SKIPPING),
`issues/242`/`issues/243` (a successful-looking report of an operation that did
nothing — the reindex here logs "complete" after storing zero), `issues/184` (code
that raises on every call, behind an `except`)

## 1. The description property: instance-side vs type-side

`KGTypeDescriptionLookup` reads a type's description out of `sp_kg_types` and it
chose the property by `mapping_type`:

    self.desc_property = TYPE_DESCRIPTION_PROPERTIES.get(mapping_type)
    # "kgentity" -> haley-ai-kg#hasKGEntityTypeDescription

That property belongs to the **instance**, not the type. From the ontology:

    hasKGEntityTypeDescription    rdfs:domain  KGEntity, KGEntityMention
    hasKGraphDescription          rdfs:domain  Edge_hasKGEdge, KGNode, KGType

`KGEntityType`, `KGFrameType` and friends are `KGType` subclasses, so the
description of a TYPE lives on `hasKGraphDescription` — one property for every type
kind, not one per kind. Confirmed by round-tripping the object rather than by
reading the ontology alone:

    KGEntityType().kGraphDescription = "a person"
      -> http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription  "a person"

And `hasKGDocumentTypeDescription`, the third entry in that dict, **is not declared
in the ontology at all** (zero occurrences in `haley-ai-kg-0.1.0.owl`).

So the lookup searched `sp_kg_types` for a predicate no type object writes, got
nothing back, and every subject fell into the `type_description` skip branch:

    populate_index: apitest/vec_typeint — 4 subjects, provider=vitalsigns_onnx
    populate_index: apitest/vec_typeint done — 0 stored, 4 skipped, 2.7s
    Reindex complete: apitest/vec_typeint — 4 processed, 0 stored (2.7s)

**The two dicts are not interchangeable and now say so.** The instance-side
properties are real and used — `fast_frame_prop_sort`, `sync_frame_prop_sort`,
`kgtype_index_setup` all rely on `hasKGFrameTypeDescription` being a denormalised
copy of the type's description written ONTO the frame, which is what makes it
sortable without a cross-space lookup. `TYPE_DESCRIPTION_PROPERTIES` is therefore
left in place with a comment saying what it is for and that it must not be used to
read out of `sp_kg_types`; `TYPE_GRAPH_DESCRIPTION_PROPERTY` is the new constant
for the type side.

**Why `issues/219` makes this worse rather than better.** That issue taught the
populator to SKIP subjects its mapping does not cover, which is correct — before it,
everything was embedded regardless. But skipping is now the normal outcome for a
missing lookup, so a lookup that returns nothing is indistinguishable from a
mapping that legitimately covers nothing, and the difference is only visible as a
count in a log line that says "complete".

## 2. `_find_affected_subjects` had five wrong column names

    SELECT DISTINCT t_subj.text AS subject_uri
    FROM {space}_rdf_quad q
    JOIN {space}_term t_subj ON q.subject = t_subj.id
    WHERE q.predicate = $1 AND q.object IN (...)

The schema is `subject_uuid` / `predicate_uuid` / `object_uuid` on the quad table and
`term_uuid` / `term_text` on the term table. Every column in that query is wrong, so
it raised `UndefinedColumnError` on every call:

    cross_space_sync: query subjects in apitest_9febdc97 failed:
      column q.subject does not exist

and the `except Exception` around it logged a WARNING and returned `[]`. So the
cross-space sync — the thing that re-vectorizes subjects after their TYPE's
description changes — has never found a single affected subject. It is a no-op that
reports itself as a completed scan, which is `issues/184`'s shape: a path that
raises on every call, wrapped in a handler that turns the raise into a shrug.

Fixed and proved by running the corrected SQL against a real space before
rebuilding, rather than trusting the edit.

## Verified

`tests/api/test_kgtypes_entity_integration.py` — 4 failing, now **5 passed**,
against a rebuilt image. The three search assertions (`'man'` finds the people,
`'company'` finds the business, `'dining'` finds the restaurant) were downstream of
the zero vectors and pass without being touched, which is the evidence that the
description lookup was the single cause.

## Not established

  * **Whether a reindex that stores 0 of N should report success.** The endpoint
    logs "Reindex complete — 4 processed, 0 stored" and returns a message; nothing
    in the response distinguishes that from a reindex that stored everything. This
    is `issues/242`'s question in a third place, and it is NOT fixed here — it
    would have made this bug loud, and the argument for it is exactly the same, but
    it is a behaviour change on a different surface.
  * **Whether the cross-space sync does the right thing now that its query works.**
    It returns subjects, and `schedule_sync` is then called on them; that path has
    never run before, so nothing about its downstream behaviour is proven. It
    could be correct, or it could be the next defect.
  * **Whether `hasKGDocumentTypeDescription` should exist.** The constant named it
    and the ontology does not declare it, so the document mapping type had no
    working description property under either reading. Left as-is; the type side
    now uses `hasKGraphDescription`, which covers documents too.
  * The `test_wikipedia_document_e2e` failures were still running when this was
    written and are not claimed as fixed by it.
