# FTS Auto-Sync Ignored The Index's Mapping, Its Scope, And Everything But The Entity On Delete

## Status: FIXED 2026-09-21 — found while confirming that a slot-level FTS
## index stays correct under insert / update / delete

**Related:** `issues/212` (deleting a frame orphans its children — the same
"the children are not part of the delete" shape, one layer up);
`planning/planning_vector_geo/nurture_message_keyword_search_plan.md` §3.3,
which predicted the third defect and missed the first two

Three defects in `_sync_fts_for_subjects` (`vectorization/auto_sync.py`) and the
entity delete path. None of them errors. Each produces a quietly wrong index.

The write path DOES reach the right subjects — `kgentities_endpoint.py:948`
builds `_sync_uris` from every object in the request, so posting an entity graph
hands the entity, its frames AND its slots to auto-sync. That part was never
broken, which is why this was invisible: the rows were being maintained, just
not correctly.

## Defect 1 — the mapping was not passed, so a different rule was applied

    auto_sync.py   await update_subject_fts(conn, space_id, idx_name,
                                            subj_uuid, context_uuid)

`update_subject_fts` takes `mapping_rule` and `mapping_type` keyword arguments.
Neither was given, so `mapping_rule` stayed `None` and reached:

    search_text_builder.build_search_text(literal_properties, rule=None, ...)
        rule: Optional resolved mapping rule. If None, includes all literals.

So the two writers disagreed about what a row means:

| writer | `search_text` |
|---|---|
| `populate_fts_index` (bulk) | the configured mapping — e.g. `hasTextSlotValue` alone |
| `_sync_fts_for_subjects` (every write) | **every literal property concatenated** |

On a message slot that is the difference between indexing the message and
indexing the message plus its slot-type URI, frame graph URI, KG graph URI and
timestamps. A freshly populated index was correct; it decayed on first touch,
one row at a time, and the ranking moved with it.

## Defect 2 — nothing checked whether the subject was in the index's scope

The loop ran every changed subject against **every** index in
`{space}_fts_index`. There is no type test anywhere in it.

So `slot_type_uri`, which `populate_fts_index` accepts to narrow a slot index
to one kind of slot, governed the INITIAL POPULATE ONLY. Measured on a KG
space: populating with `slot_type_uri=MsgContent` selects 3,249 subjects where
`type_uri=KGTextSlot` selects 180,878 — **55.7x**. Every subsequent write
eroded that, because writing a `CompanyName` slot, a frame or an entity
inserted it into the message index.

A "message search" index therefore drifts toward "everything in the space that
has been written since it was built", and no query fails while it does.

## Defect 3 — delete removed the entity and left its graph behind

    kgentities_endpoint.py:1286   self._schedule_auto_sync(..., [uri], "delete")
    kgentities_endpoint.py:1365   self._schedule_auto_sync(..., deleted_uris_list, "delete")

Both pass ENTITY URIs only. `delete_subject_fts` removes exactly
`(subject_uuid, context_uuid)`, so the entity's own row went and **every slot
row stayed** — still matching searches, still resolving to an entity that no
longer exists.

`delete_entity_graph` already computed the member list
(`kgentity_delete_impl.py:150`, every subject with
`hasKGGraphURI = <entity graph>`), then discarded it and returned a count.

It cannot be fixed inside `auto_sync`: `schedule_sync` is fire-and-forget and
runs AFTER the delete commits, so by then the quads that would identify the
members are gone. The list has to come from the code that still has it.

## Why none of this failed loudly

    except Exception as e:
        logger.warning("auto_sync fts %s/%s/%s failed: %s", ...)

Every per-subject failure is a warning. An index that stops updating keeps
answering queries with whatever it last held.

## The fix

**1 + 2 — resolve the mapping, and treat "no mapping" as "not in scope".**
`_sync_fts_for_subjects` now derives what each subject IS — `hasKGSlotType`
for a slot, else `hasKGEntityType`, else `rdf:type` — in ONE batched query for
the whole write, then resolves the index's mapping for that
`(mapping_type, type_uri)` and passes the rule through.

The behavioural change is deliberate and is the point: **no mapping now means
skip**, where it used to mean index-every-property. That matches what the bulk
populator already does — `populate_fts_index` returns early when
`resolve_search_mapping` finds nothing — so the two writers now agree.

A subject found to be out of scope is also DELETED from that index, so the fix
repairs rows the defect wrote rather than leaving them to be found later.

**3 — return the member URIs.** `delete_entity_graph` takes an optional
`collected_uris` list and appends every member subject it removes; the endpoint
passes the entity plus those members to auto-sync, de-duplicated with
`dict.fromkeys` since an entity is its own graph member.

## What this does NOT fix

- **The bulk delete path** (`:1365`) still passes entity URIs only. It calls
  `delete_entities_batch`, which loops `delete_entity_graph` internally; the
  same `collected_uris` thread has to be run through it.
- **Existing indexes are already polluted** wherever writes have happened since
  a populate. The per-subject repair above only fires when a subject is written
  again. A full re-populate is the reliable repair.
- **Vector, geo and fuzzy sync take the same `mapping_rule`-free path.** Only
  FTS was audited here. `_sync_vectors_for_subjects` is the one most likely to
  carry defect 1 too, and an embedding built from the wrong text is more
  expensive to discover than a tsvector.
