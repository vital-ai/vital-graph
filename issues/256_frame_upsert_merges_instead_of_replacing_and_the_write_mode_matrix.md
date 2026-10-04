# 256 — Frame upsert MERGES instead of replacing, and the rest of the write-mode matrix

## Status: OPEN, filed 2026-10-02. BUILT AND RELEASED: items 1 and 8 and the
## entity graph delete (2026-10-03); the delete contract, client entity upsert,
## client retry marking by mode, item 4 (`replace`), decision 3 on writes and
## the in-transaction entity check — all in 0.0.44 (`cfb9cc5a`). Fourth round in
## 0.0.45 (`ed186757`): item 3's create half, behind
## VITALGRAPH_FRAME_CREATE_REFUSES_EXISTING (default off), and the slot routes'
## contract with `/kgentities/kgframes/kgslots`. Deploying to production is
## separate, per planning/planning_deploy.
## FIXED 2026-10-04 (`81e718db`), for the next release — see "Fifth round":
## the switch is REMOVED, `create` always refuses an existing frame (VitalGraph
## does not wait on its callers); the entity route's `update` decides the whole
## request first and no longer reports success for a frame it did not write.
## The slot routes need no caller change. What the Resource API should change
## for its own writes is advice, not a dependency.

## The rule (decided 2026-10-02)

**Upsert never merges. It replaces the graph it addresses**: the entity graph
for an entity upsert, the frame graph for a frame upsert. Anything in that graph
that the request does not carry is gone afterwards. `update` follows the same
rule and differs only in requiring the target to exist.

The definitions this file uses:

- **Entity graph**: every subject whose `hasKGGraphURI` is the entity. This is
  what `update_entity_graph` and `upsert_objects_atomic` already delete by.
- **Frame graph**: the frame, plus every subject whose `frameGraphURI` is the
  frame (its slots, its `Edge_hasKGSlot` edges). Whether a frame's DESCENDANT
  frames belong to it is open question 1 below.

## The contract (decided 2026-10-02)

| mode | precondition | frame routes (`/kgentities/kgframes`, `/kgframes`) replace | `/kgentities` replaces |
|---|---|---|---|
| `create` | target must NOT exist, else ALREADY_EXISTS | nothing; insert | nothing; insert |
| `update` | target MUST exist, else NOT_FOUND, on EVERY route including `/kgentities` | the frame graph: the frame + every subject with `hasFrameGraphURI = frame`. Child frames are untouched (shallow) | the entity graph |
| `upsert` | none | as `update` | as `update` |
| `replace` | none; a missing frame is created | the subtree: the frame graph + every descendant frame's graph (deep) | **does not apply**: INVALID_REQUEST in a 200 |
| `entity_only` | entity MUST exist | — | the entity subject only; frames kept |
| `DELETE` | see "Delete: decisions needed" | the frame graph + its structural edges; with `recursive=true` the subtree, otherwise refused if the frame has children | the entity graph (see decision 1) |

Three rules hold across every cell:

- **Only what you name.** A write touches the frames the request names, plus
  their subtrees for `replace`, and nothing else. Two services can co-own one
  entity's frames only because of this. It applies to `replace` WITH a
  `parent_frame_uri` too: today both routes delete ALL of that parent's
  children, and under this rule they delete only the named frames and their
  descendants. Wiping every frame on an entity is `delete` followed by `create`.
- **One transaction.** Every mode resolves its delete set, deletes and inserts
  inside one transaction, under the owning grouping's lock, and honours
  `if_unmodified_since`. `replace` included. The owning grouping differs by
  route (`issues/174`):
  - `/kgentities` and `/kgentities/kgframes`: the **entity**. The lock key and
    the `if_unmodified_since` stamp are both the entity's.
  - `/kgframes`: the **frame**. Standalone frames have no entity, so the lock
    keys are the written objects' `hasFrameGraphURI` values, and the guard
    compares that frame's stamp. A guarded write spanning more than one frame
    grouping is refused with AmbiguousPrecondition. The fix must keep that: a
    standalone `replace` locks the named frame's grouping and every
    descendant's, and still guards exactly one.
- **A refused or invalid mode is a domain outcome.** It answers in a 200 with a
  status, never a 500. A mode the route does not know is INVALID_REQUEST, never
  a silent fallback to `create`.

## How this was found

A downstream service reviewed 0.0.43 to choose how to write a lead that two
services co-own: the portal writes some frames and the API writes others
(campaign participation, processing state, `BusinessURI`). Entity upsert
replaces the whole entity graph, so neither side can use it without deleting
the other's frames. The review therefore chose frame-level upsert, and noted in
passing:

> a slot that's already on a frame but isn't re-sent stays as it is. The portal
> re-sends its merged slot set, so it isn't affected.

The observation is correct, and it is a defect, not a detail. "Isn't affected"
holds only while the portal's slot set never shrinks. When a slot is REMOVED
client-side and the frame is upserted without it, the write succeeds and the
slot survives. Its `Edge_hasKGSlot` survives too, so it is not orphaned: it is
still attached and is returned on every read. Nothing looks wrong.

## What was intended, and when it was lost

The planning docs answer this, and the answer is a REGRESSION, not a design gap.

**The design was frame-graph replace, from the start.**
`planning/planning_fuseki/endpoints/fuseki_psql_kgentities_endpoint_plan.md`
(§1, "Frame Operation Principles", Jan 2026) says it plainly: "Frames are Atomic
Wholes ... **Complete Replacement**: Frame updates replace the entire frame graph
as a single atomic operation ... **No Partial Updates**". It defines the unit as
"KGFrame + all slots + all related objects sharing the same `frameGraphURI` +
connecting edges". `planning/planning_kg_model/kg_update_plan.md` (Nov 2025,
"Grouping URI Block Operations") says the same thing: "Delete entire frame graph
by grouping URI. Replace with new frame graph atomically."

**The code did that until 2026-04-30.** The pre-migration delete,
`build_delete_quads_for_frames` (`kgentity_frame_create_impl.py:~612`, still
there as the fallback for backends without `update_subjects_graph`), selects
every subject with `hasFrameGraphURI = <frame>`, which is a frame-graph replace.

**2026-04-30 narrowed the scope without saying so.**
`planning/planning_sql/kg_query/sparql_sql_datatype_loss_plan.md` ("Write Path
Migration") moved every frame write to `update_subjects_graph` to fix a
datatype-loss bug in quad-level deletes (commit `70706223`). The doc describes
the change as purely mechanical: "subject-level delete via direct SQL ... no
UUID matching fragility". It never mentions that the delete set changed from
"the frame graph" to "the subjects in the payload". The entity path got the
equivalent change correctly: `update_entity_graph` resolves its subjects by
`hasKGGraphURI` first. The frame paths took the payload's URIs instead.

**2026-05-29 wrote the regression up as the contract.**
`planning/planning_sql/kg_query/child_frame_update_duplication_bug.md`, "Issue 2:
Correct API Usage", observed the merge directly ("Old slot URIs not in the
payload are untouched") and recorded it as correct usage that clients must work
around (retrieve the full frame graph, modify in place, send it all back). That
is a workaround for a scope change nobody had decided on. The downstream review
that prompted this issue is relying on the same workaround. This file
supersedes that section.

**Descendants: `update` is SHALLOW, `replace` is DEEP. This was decided and is
pinned by tests.** `planning/planning_sql/kg_query/frame_hierarchy_consistency_plan.md`
§3 defines the two modes:

- `update`: "Update the target frame's properties/slots only. Children are
  untouched." Pinned by `case_kgframe_hierarchy.py::test_update_preserves_children`.
- `replace`: "Delete the target frame's entire subtree ... then insert the new
  frame graph." Pinned by `test_replace_mode` and `test_replace_with_hierarchy`
  on both routes.

So the frame graph that update and upsert replace is the frame, its slots and
its slot edges. It does NOT include child frames. That answers open question 1
below.

**Upsert has no separate written design.** Every doc groups it with update
("UPDATE/UPSERT"), and the code shares update's path. The rule decided
2026-10-02 makes that explicit: upsert is update without the existence
requirement.

**Don't revive the dead replace code as it stands.** `handle_frame_update_deletion`
(`kgentity_frame_create_impl.py:755`) matches on `haley-ai-kg#frameGraphURI`.
The ontology property is `hasFrameGraphURI` (`haley-ai-kg-0.1.0.owl:140`; the
three live uses in `vitalgraph/` spell it that way). As written, it would find no
slots and delete only the frame itself.

## The mechanism

Every frame write — create, update and upsert, on both the entity-scoped and
the standalone route — ends in `update_subjects_graph`
(`kg_impl/kg_backend_utils.py:1433`). That function deletes and re-inserts the
SUBJECTS IT IS GIVEN. The callers give it the URIs of the objects in the request:

- `kgentity_frame_create_impl.py:546` (`execute_atomic_frame_update`, update/upsert)
- `kgentity_frame_create_impl.py:954` (`execute_frame_creation`, create)
- `kgframe_create_impl.py` `execute_atomic_frame_update` / `execute_frame_creation`
  (standalone, same shape)

So the delete set is "what was sent", not "what the frame owns". A slot, slot
edge or child frame that was not sent is not in the delete set and is never
touched.

**The replace-by-grouping delete already exists and is dead.**
`handle_frame_update_deletion` (`kgentity_frame_create_impl.py:755`) finds
every subject with `frameGraphURI = <frame>` and deletes them with the frame.
Nothing calls it. It looks like the replace semantics were lost when frame
writes moved to the subject-level path, and nothing failed when that happened:
every existing test re-sends the full slot set.

## The matrix

Grouped by route. "Correct" means it matches the rule above. It does not mean
the cell has been tested.

### A. `POST /kgentities` — entity graph

| mode | what it does | verdict |
|---|---|---|
| `create` | Refuses with ALREADY_EXISTS if the entity URI or ANY sub-object URI exists (`kgentity_create_impl.py` `_handle_create_mode`), then `store_objects`. | Correct semantics. The existence check and the store are separate operations; whether anything serialises two concurrent creates of one URI is unverified. |
| `update` | Requires the entity to exist, checks sub-object ownership, then `update_entity_graph`: whole-graph replace by `hasKGGraphURI` under the entity lock. | **Correct.** A missing entity answers NOT_FOUND, single and batch (`kgentities_endpoint.py:1037`), but **no test pins it**. No `if_unmodified_since` on this route. |
| `upsert` | `upsert_objects_atomic`: whole-graph replace in one locked transaction (`issues/173`), with the stored creation time carried over. | **Correct.** A backend without the atomic path falls back to unserialised delete-then-store and says so in the log. |
| `replace` | Accepted by the `OperationMode` enum, then `_convert_operation_mode` raises `ValueError` (`kgentities_endpoint.py:1281`). The outer handler turns that into **HTTP 500**. | **Defect.** A caller error answered as a server error, against the 200-with-status convention. Either support it (as an alias of `update`) or answer INVALID_REQUEST. |
| `entity_only` | Rewrites only the entity's own subject triples and keeps every frame. | Correct by design, and it is not an upsert. |

### B. `POST /kgentities/kgframes` — entity-scoped frames

| mode | what it does | verdict |
|---|---|---|
| `create` | Checks the entity exists, creates `Edge_hasEntityKGFrame` (or `Edge_hasKGFrame` under `parent_frame_uri`), then a subject-level overwrite. **It does not check whether the frame already exists.** | **Defect (by reading).** Creating an existing frame URI overwrites the subjects sent and keeps the rest — a silent merge where entity `create` would refuse. |
| `update` | `_update_entity_frames` groups by frame, `validate_frame_ownership`, then the same subject-level path (`KGEntityFrameUpdateProcessor.update_frames`). | **Defect: merges.** Its docstring says "update frames and their complete frame graphs". |
| `upsert` | Goes through `_create_or_update_frames`, then `create_entity_frame(operation_mode="UPSERT")`, then a subject-level overwrite. | **Defect: merges** (the defect this issue is about). **Three more by reading** — see below. |
| `replace` | `_replace_entity_frames`: with no `parent_frame_uri`, deletes ALL of the entity's top-level frames and their descendants, then CREATE. | **Defect.** The scope is wrong under the rule: it wipes frames the request did not name, so it cannot be used on a co-owned lead. It is also not atomic: a series of SPARQL deletes, then a separate create, with no lock. It deliberately ignores `if_unmodified_since` (comment at `kgentities_endpoint.py:455`). A failure between the deletes and the create leaves neither the old frames nor the new ones. |

**The other three entity-frame upsert defects, all by reading:**

1. **No ownership check.** `kgentity_frame_create_impl.py:171` skips the
   entity-existence check for UPDATE/UPSERT because "validate_frame_ownership
   already confirmed entity exists upstream". That is true for `update`. It is
   false for `upsert`: `_create_or_update_frames` validates nothing. Upserting a
   frame URI that belongs to ANOTHER entity overwrites it, and
   `assign_grouping_uris` re-stamps its `hasKGGraphURI` to this entity. The
   other entity's `Edge_hasEntityKGFrame` still points at it.
2. **No entity-existence check.** For the same reason, upserting against an
   entity URI that does not exist writes frames that belong to nothing.
3. **No linking edge for a NEW frame.** Step 5 (`:205`) creates the
   entity→frame or parent→child edge only for CREATE. When upsert takes its
   create branch, the frame is written unlinked unless the client sent the edge
   itself. Reads that walk `Edge_hasEntityKGFrame` will not find it. Reads that
   group by `hasKGGraphURI` will. So the frame shows up on some read paths and
   not others.

Also on this route: a successful upsert or update answers `status=CREATED`,
"Successfully created N frames" (`kgentities_endpoint.py:1724`).

### C. `POST /kgframes` — standalone frames

| mode | what it does | verdict |
|---|---|---|
| `create` | Subject-level overwrite, locked on the `frameGraphURI` values. No existence check. | **Defect (by reading)**: as B/create. |
| `update` | Its docstring says "verify frames exist, then update". It verifies only the parent relationship, never existence, then does a subject-level overwrite. | **Defect: merges**, and it creates a frame that does not exist instead of answering NOT_FOUND. |
| `upsert` | Subject-level overwrite. | **Defect: merges.** |
| `replace` | Deletes the replacement's frame URIs and their descendants (or the parent frame's children), then CREATE. | The scope is right. Same non-atomic, unlocked, unguarded shape as B/replace. |
| unknown mode | `OperationMode(operation_mode.lower())` failing falls back to CREATE (`kgframes_endpoint.py:167`). | **Defect.** A typo in the mode silently becomes a create. Should answer INVALID_REQUEST. |

### D. Python client

- `create_kgentities` hard-codes `operation_mode="create"`
  (`client/endpoint/kgentities_endpoint.py:602`). The client has no entity
  upsert, so a client user cannot reach A/upsert, the one cell in the matrix
  that already behaves correctly.
- `create_entity_frames` and the standalone frame methods pass
  `operation_mode` through, so they reach every defective cell in B and C.
- **`delete_kgentity` reported deletes that did not happen** (found
  2026-10-03). It defaulted `deleted_count` to 1 and `deleted_uris` to the
  requested URI when the server omitted them, and its message was always
  "Deleted N items", including on a NO_OP. `delete_kgentities_batch` and
  `delete_entity_frames` defaulted both to everything requested. And
  `deleted_uris` is optional on the server model, so a `null` would have failed
  the client's `List[str]` validation. FIXED 2026-10-04: the server's count,
  list and message, `or []` for a null.

### E. Deletes

Three routes. The slot route `DELETE /kgframes/kgslots` is out of scope, as for
writes. Unlike writes, every delete already has the RIGHT SCOPE except the
entity default. What the deletes get wrong is atomicity, locking and the status
for a target that is absent.

| route / form | what it deletes | how | absent target | verdict |
|---|---|---|---|---|
| `DELETE /kgentities`, `delete_entity_graph=false` **(the DEFAULT)** | the entity subject's own triples ONLY (`kgentity_delete_impl.py:34`) | SPARQL read of the subject's triples, then quad-level `remove_rdf_quads_batch`: the fragile pattern the 2026-04-30 migration moved every other path off. No lock. | NO_OP | **Defect.** Every frame, slot and edge survives, still carrying `hasKGGraphURI` = a deleted entity, and `Edge_hasEntityKGFrame` points from nothing. This is the default, so any caller that didn't know about the flag has been leaving orphans. **Decided: refuse when members exist; otherwise a subject-level delete under the entity lock** (delete decision 1). |
| `DELETE /kgentities`, `delete_entity_graph=true` | the entity graph by `hasKGGraphURI` | `delete_entity_graph_bulk`: one transaction under the entity lock (`sparql_sql_space_impl.py:1749`, `issues/174` item 1) | single: **STORE_FAILED**, "Failed to delete". Batch: STORE_FAILED, a known imprecision recorded at the site | Scope, atomicity and lock are correct. **TO FIX (decided 2026-10-02), two defects:** (1) **Absent is reported as a failure.** It should answer NO_OP, as the entity-only form already does. (2) **The members' VECTOR, GEO and FUZZY rows outlive the entity** (verified by reading, see below). |
| `DELETE /kgentities/kgframes` | the frame graph by `hasFrameGraphURI` + `Edge_hasEntityKGFrame` + incoming `Edge_hasKGFrame` (`kgentity_frame_delete_impl.py`); `recursive` for descendants, otherwise refused if there are children | ownership check, SPARQL discovery, then one `DELETE DATA` of the discovered quads. No lock, and discovery is not in the delete's transaction. The entity is stamped AFTER, outside the lock (acknowledged at `kgentities_endpoint.py:2214`). | STORE_FAILED (ownership finds nothing) | Scope correct. **Not atomic with its discovery and not locked**: a frame write landing between discovery and delete leaves its new slots behind. Quad-level delete is again the pattern 2026-04-30 retired. Frames that fail ownership are skipped and the response is still DELETED, with the skip mentioned only in the message. **TO FIX (decided 2026-10-02)**: see "Entity-frame delete fix" below. |
| `DELETE /kgframes` (single, `uri_list`) | the frame graph by `hasFrameGraphURI` + the frame's own triples + incoming/outgoing `Edge_hasKGFrame` + `Edge_hasEntityKGFrame` (`_delete_frame_from_backend`, `kgframes_endpoint.py:2864`); `recursive` likewise | **five separate SPARQL updates per frame**, frame by frame, no transaction, no lock | single: NOT_FOUND. Batch: counted as not deleted, so PARTIAL or STORE_FAILED | Scope correct. **Not atomic at any level**: a failure part-way through a recursive delete leaves a partial subtree, possibly children whose parent edge is already gone. **It also deletes ENTITY-owned frames with none of the entity route's handling**: no ownership check, no entity lock, no entity stamp, no entity-cache invalidation. A frame deleted this way stays in the cached entity graph, and a caller holding `if_unmodified_since` sees no change. **TO FIX (decided 2026-10-02)**: see "`/kgframes` delete and `replace` fix" below. |

**FIXED 2026-10-03 (released in 0.0.44): entity graph delete — absent is NO_OP, and the
members' derived rows go with it.** `delete_entity_graph_bulk` resolves the
member URIs in its transaction and returns them through a new `collected_uris`
argument, filled after the commit. `delete_entity_graph_direct` and the
processor RAISE on failure instead of returning 0, so 0 now means absent. The
single and batch endpoints answer NO_OP for absent and STORE_FAILED only for a
real failure. The batch reports per URI ("deleted"/"absent"/"failed") and hands
auto-sync every member. `BaseDeleteResponse` and the client `DeleteResponse`
gain `absent_uris`, and the client batch delete gains the
`delete_entity_graph` argument the server always accepted. Verified on the
rebuilt vg test stack, driven by the `vital-graph` conda env:
`tests/api/test_delete_contract.py` 8/8 FAIL on HEAD's server code, each for
its own defect, and 8/8 PASS with the fix. With six neighbouring API modules
(entities, residue, cache, entity frames, workflows, geo) it is 63/63 pass.

**The entity graph delete's derived-data leak, verified by reading
2026-10-02.** This corrects the first version of this section, which said FTS.
FTS is FINE: `delete_entity_graph_bulk` clears the members' FTS rows itself, in
the delete's own transaction (`sparql_sql_space_impl.py:1825`, the
`issues/217` bulk-path fix). Vector, geo and fuzzy rows are NOT cleaned there.
They are deleted per subject by the endpoint's auto-sync
(`vectorization/auto_sync.py`: `delete_subject_vectors`,
`delete_subject_geo`, and the fuzzy delete), which gets its subject list from
`collected_uris`. On the production path, `KGEntityDeleteProcessor.delete_entity_graph`
takes the fast path (`kgentity_delete_impl.py:138`) and returns without ever
appending to `collected_uris`. So the auto-sync is handed `[entity_uri]` alone.
Any vector, geo or fuzzy row keyed on a frame or slot survives the entity,
matches searches, and resolves to nothing.

The batch delete is worse. `_delete_entities_by_uris` passes no
`collected_uris` at all, on either path.

**Fix:** `delete_entity_graph_bulk` already computes the member subject UUIDs
(its inner `_do_delete` returns them). Return them to the caller, convert them
or pass them as UUIDs, and fill `collected_uris` on the fast path. Then do the
same in the batch delete. The verdict needs the same care, because the fast path
returns `1 if deleted_quads > 0`: an entity graph with zero quads is
indistinguishable from a failure, which is defect (1).

**Entity-frame delete fix (decided 2026-10-02).** `DELETE /kgentities/kgframes`
becomes one transaction under the ENTITY lock, the same key every entity-frame
write takes (`issues/174`). Everything it decides is decided inside that
transaction, after the lock:

- **Ownership.** Each requested frame belongs to this entity: a root via
  `Edge_hasEntityKGFrame`, or a child via `hasKGGraphURI`, as
  `validate_frame_ownership` does today.
- **The children check** for `recursive=false`, and the descendant walk for
  `recursive=true`.
- **The delete set**: each frame plus every subject with `hasFrameGraphURI` =
  that frame, its incoming `Edge_hasEntityKGFrame` / `Edge_hasKGFrame`, and,
  when recursive, the same for every descendant.
- **The delete itself** is subject-level, `DELETE ... WHERE subject_uuid =
  ANY(...)` as `update_subjects_graph` does, instead of the SPARQL discovery
  plus quad-level `DELETE DATA`.
- **The entity stamp** (`hasObjectModificationDateTime`) moves inside the
  transaction, as the writes' stamp did in `issues/253`. The post-commit
  `touch_entity_modification_time` at `kgentities_endpoint.py:2214`, outside
  the lock, is removed. Its own comment says it stays only because deletion did
  not go through the transactional path; after this, it does.
- **The aux tables** (frame_slot, edge, entity_slot_sort, FTS, prop-sort) are
  synced in the same transaction, as `delete_entity_graph_bulk` does.
  Vector, geo and fuzzy rows get the full member subject list through
  auto-sync, not just the frame URIs, so this delete doesn't repeat the
  entity-graph leak above.

**Ownership failures stop reporting DELETED.** A request is all or nothing:

- If any requested frame exists but belongs to ANOTHER entity, or to no entity,
  the whole request is refused with INVALID_REQUEST in a 200 and nothing is
  deleted. The message names the frames. This is a caller error, and deleting
  the rest would make the outcome depend on the request's order.
- A requested frame that does not exist at all is NO_OP for that frame, per
  delete decision 2. It does not refuse the request.
- The status is then DELETED if everything requested was deleted, NO_OP if
  nothing requested existed, and a mix of the two reports per URI.

This matches the default stance: a delete that is all or nothing, under the
lock, is the same shape as entity graph delete. It is my default rather than a
decision you took; say if a mixed request should instead delete what it can and
answer PARTIAL.

**`replace` inherits these.** Both `replace` routes delete through the last two
rows (`_delete_frame_from_backend`, and the inline SPARQL in
`_replace_entity_frames`). Making `replace` one transaction means replacing its
delete, not wrapping it.

**`/kgframes` delete and `replace` fix (decided 2026-10-02).**

*One primitive, four callers.* A frame delete is a subtree replace with nothing
to insert. So build ONE backend operation, "replace these frame subtrees",
taking:
- the root frames;
- `recursive` / deep;
- the quads to insert (empty for a delete);
- the lock keys;
- the guard subject and `if_unmodified_since`.

Both frame delete routes and both `replace` routes call it. Today the four are
four implementations: `_delete_frame_from_backend`, the inline SPARQL in
`_replace_entity_frames`, `KGEntityFrameDeleteProcessor`, and
`_handle_replace_mode`. That is how they drifted apart. Inside one transaction,
after the lock, it:

1. resolves the subtree: the roots, plus their descendants when deep. With
   `recursive=false` it refuses if any root has children;
2. resolves the delete set: every subtree frame, every subject with
   `hasFrameGraphURI` = one of them, and the structural edges into and out of
   the subtree (`Edge_hasEntityKGFrame`, `Edge_hasKGFrame`). Edges from a
   frame OUTSIDE the subtree to a root are kept for `replace`, which re-links
   under the same parent, and deleted for `delete`;
3. syncs the aux tables (frame_slot, edge, entity_slot_sort, FTS, prop-sort)
   before and after, as `delete_entity_graph_bulk` does;
4. deletes subject-level and inserts;
5. compares and stamps the guard, as `update_subjects_graph` does;
6. returns the member subject list, so auto-sync can clear vector, geo and
   fuzzy rows for every member, not only the frames.

A failure anywhere rolls back everything, so a half-deleted subtree can't
exist.

*Locks and guards per route:*
- **`/kgentities/kgframes`** (delete and replace): the entity's lock, the
  entity's guard and the entity's stamp.
- **`/kgframes`** (delete and replace): the lock keys are the `hasFrameGraphURI`
  groupings of EVERY frame in the subtree. A concurrent write to a descendant
  must be excluded too, and it locks on its own grouping. The guard is the one
  ROOT frame. This separates the lock set from the guard, which
  `update_subjects_graph` already allows (`lock_uris` vs `guard_subject`). Only
  the `len(_lock_uris) != 1` check in `kgframe_create_impl.py` conflates them,
  and that check must not apply here.

*Entity-owned frames through `/kgframes`.* A frame (or any frame in the
subtree) with a `hasKGGraphURI` is owned by an entity. `/kgframes` does not
take that entity's lock, so it cannot safely touch it. **Refused, per delete
decision 3 (DECIDED)**: INVALID_REQUEST in a 200, naming the entity and
pointing to `/kgentities/kgframes`, for every `/kgframes` operation. The check
runs inside the transaction, after the lock, on every frame in the subtree.

*Afterwards:* the endpoint invalidates the entity graph cache for the owning
entity (entity route), and schedules auto-sync with the full member list. Both
happen after commit and only on success.

**Delete: decisions needed**

1. **Entity delete without the graph. DECIDED 2026-10-02: it FAILS if the
   entity has members, and otherwise deletes the entity under its lock.** This
   mirrors frame delete's `recursive=false`.
   - With `delete_entity_graph=false`, if any subject other than the entity
     itself has `hasKGGraphURI` = the entity, the delete is refused with
     INVALID_REQUEST in a 200. The message names the member count and says to
     use `delete_entity_graph=true`. Nothing is deleted.
   - With no members, the entity's triples are deleted SUBJECT-LEVEL, in one
     transaction under the entity lock. That replaces the SPARQL read plus
     quad-level `remove_rdf_quads_batch`.
   - **The member check runs INSIDE that transaction, after the lock.** Checked
     before, a frame create landing in between would be orphaned by the delete
     the check just allowed. Frame writes take the same entity key
     (`issues/174`), so the lock is what makes the check true at delete time.
   - **The race has a second half, on the create side.** Entity-frame create
     checks that the entity exists in step 1 (`validate_entity_exists`,
     `kgentity_frame_create_impl.py:171`), BEFORE it takes the lock. So a
     create can pass the check, wait on the lock while the delete commits, and
     then write frames onto a deleted entity. The existence check has to move
     inside the write transaction too, after the lock. Otherwise the refusing
     delete is only half the guarantee.
   - `update_subjects_graph` cannot express "refuse if members exist", so this
     needs a small new backend method, or a precondition hook on the existing
     one, rather than a call through it unchanged.
   - Batch (`uri_list`): per-URI outcome. An entity with members is reported
     as refused and does not stop the others. The status follows the existing
     DELETED / PARTIAL / STORE_FAILED logic, with refusals counted separately
     from failures.

   **Done 2026-10-04:** the count of orphans production already held from the
   old default (frames, slots and edges whose `hasKGGraphURI` names an entity
   that no longer exists) is **0** — see "Orphan census" under the second round.
2. **The status for an absent target. DECIDED 2026-10-02: NO_OP on every
   delete route.** A delete of something already gone has achieved what was
   asked, and a replayed delete (`issues/253`'s retry work) must not read as a
   failure. NO_OP is already a success status on the server and in the client
   (`model/result_status.py:42`, whose comment names exactly this case), so no
   client change is needed to read it as success.
   - **Single:** an absent target answers NO_OP, `deleted_count=0`. This
     replaces NOT_FOUND on `/kgframes` and STORE_FAILED on entity graph delete
     and entity-frame delete. The entity-only delete already answers NO_OP.
   - **Batch:** absent counts as satisfied, not as failed. The overall status
     is:
     - DELETED if every URI was deleted or absent and at least one was deleted;
     - NO_OP if all were absent;
     - PARTIAL if some failed and others did not;
     - STORE_FAILED if every one failed.
     A REFUSAL (entity with members, a frame owned by another entity) is
     neither absent nor failed, and follows that route's own rule above.
   - **Say which were absent.** The delete responses carry only
     `deleted_uris`, so a caller cannot tell "deleted" from "was already gone".
     Add `absent_uris` to `EntityDeleteResponse` and `FrameDeleteResponse`,
     matching `missing_uris` on the read side (`model/quad_model.py:77`).
   - **This needs absent and failed separated where they are conflated
     today:** `_delete_one` in `_delete_entities_by_uris` (False for both, as
     its own comment admits), the entity graph fast path (`1 if deleted_quads
     > 0`), and the `/kgframes` batch (absent frames are skipped and counted as
     not deleted). The new subtree primitive returns the two apart.
   - **Behaviour change:** a caller of `/kgframes` that tests for NOT_FOUND on
     delete will now see NO_OP. Search the clients, the portal and the API
     service for that check before landing.
3. **Ownership on `/kgframes`. DECIDED 2026-10-02: refuse.** `/kgframes`
   operates only on standalone frames. A frame with a `hasKGGraphURI` belongs
   to an entity, and every `/kgframes` operation that would touch one is
   refused with INVALID_REQUEST in a 200. The message names the owning entity
   and points to `/kgentities/kgframes`. That covers:
   - `delete`, single and batch: the named frame, or ANY frame in a recursive
     subtree;
   - `update`, `upsert`, `replace`: the named frame, or any frame in the
     `replace` subtree;
   - `create` on a URI that already exists as an entity-owned frame. Whatever
     open question 3 decides for create on an existing standalone frame, an
     entity-owned one is refused;
   - `parent_uri` naming an entity-owned frame. A standalone child cannot be
     attached under an entity's frame, because the result would be a subtree
     with two owners.

   The check runs INSIDE the transaction, after the lock, so an entity frame
   create landing concurrently cannot slip past it. One frame now has exactly
   one route, one lock and one stamp. The alternative (taking the owner's lock
   from `/kgframes`) was declined for that reason.

   **Behaviour change:** callers using `/kgframes` on entity frames today get
   refused. `case_kgframe_hierarchy.py::test_delete_fails_if_children` and
   `::test_recursive_delete` delete an ENTITY's root frame through `/kgframes`
   (test survey, D10), and must move to `/kgentities/kgframes`. Search the
   clients, the portal and the API service for `/kgframes` writes before
   landing.
4. **`if_unmodified_since` on deletes. DECIDED 2026-10-02: every delete route
   accepts it.** A delete racing a save is the same lost-update shape
   `issues/253` fixed for writes: a caller reads, decides to delete, and
   removes a frame someone else changed in between.

   | route | guards | notes |
   |---|---|---|
   | `DELETE /kgentities/kgframes` | the ENTITY's stamp | One entity per request, so a batch of frames is still one guard. On success the delete advances the stamp in-transaction (see the entity-frame delete fix), so the next guarded writer sees it. |
   | `DELETE /kgframes` | the ROOT frame's stamp | A guarded request naming more than one root is refused with AmbiguousPrecondition, as guarded standalone writes are. A recursive delete locks every subtree grouping but guards only the root. |
   | `DELETE /kgentities` | the ENTITY's stamp | Both forms: graph delete, and the member-refusing entity-only delete. A guarded `uri_list` of more than one entity is refused with AmbiguousPrecondition. |

   Rules, all as for writes:
   - The comparison runs INSIDE the delete's transaction, after the lock, in
     the same compare-and-set `update_subjects_graph` uses, so the subtree
     primitive and `delete_entity_graph_bulk` both take it. Anywhere else is a
     race (`issues/253`).
   - **Stale** → CONFLICT in a 200, nothing deleted.
   - **Absent target with a guard** → NO_OP (decision 2). What the caller
     wanted gone is gone, so this is not a conflict, even though someone else
     deleted it.
   - **Guard subject with no stamp**, but present → `GuardUnsatisfiable`,
     STORE_FAILED, as for writes.
   - Omitted → unconditional, as today.

   **Client:** `delete_kgentity`, `delete_kgentities_batch`,
   `delete_entity_frames`, `delete_kgframe`, `delete_kgframes_batch` and
   `delete_kgframes` gain an `if_unmodified_since` argument, and their
   responses surface CONFLICT the same way the write methods do.

Whatever is decided, every delete moves to the write contract's rules: one
transaction, discovery inside it, under the owning grouping's lock, subject-level
delete rather than quad-level.

### F. Dead code — REMOVED 2026-10-02

Nine methods, none called from `vitalgraph/`, `tests/` or the live
`test_scripts/` runners, checked by name and for `getattr` dispatch. Each site
keeps a one-line deletion note, as `issues/243` did. Lint is unchanged against
HEAD apart from three module-level imports that only the removed code used, which
were removed with it.

- `KGFramesEndpoint._delete_frames`, `_get_frames`, `_get_entity_frames`,
  `_delete_entities` (`kgframes_endpoint.py`, one contiguous block).
  `_delete_entities` was "for test compatibility" and was `_delete_frames`' only
  caller. `_delete_frames` deleted with `delete_object` and reported DELETED
  whatever happened.
- `KGEntitiesEndpoint.create_entity_frames`, `update_entity_frames`,
  `delete_entity_frames` (the "from mock implementation" section).
  `create_entity_frames` passed `graph_objects=` to a function taking `quads`, so
  it raised `TypeError` on every call. `_get_all_triples_for_subjects` sits in
  the same section, is LIVE, and was kept.
- `KGEntitiesEndpoint._create_entity_frames`, which mapped upsert to UPDATE.
- `KGEntityFrameCreateProcessor.handle_frame_update_deletion`, which matched
  `#frameGraphURI` rather than `#hasFrameGraphURI`, so it would have deleted only
  the frame. The fix (item 1) builds the frame-graph delete set fresh.

Unit suite after removal: 5,247 tests, 1 failure, and that failure is
`test_every_indexed_issue_is_COMMITTED`: this file indexed in the README before
it is committed. It clears when the two are committed together.

**`test_scripts/test_script_kg_impl/` — REMOVED 2026-10-02**, all 81 tracked
files. It was the only thing that called these methods. It drove endpoint
internals directly, had no runner outside `archive/`, and was already broken
against them: it called `KGEntitiesEndpoint._delete_entities`, which never
existed, and `create_entity_frames`, which raised. No live file imports any of
its 69 modules. The same-named `case_*` imports in
`test_scripts/vitalgraph_client_test/` resolve to that harness's own
`kgframes/`, `kgqueries/` and `graphs/` folders. Its `pyproject.toml` package
exclusion went with it. The `archive/` runners that imported it were already
dead and are left as archive.

## What the fix is

1. **BUILT 2026-10-03 (see "Item 1, as built" below). DO NOT DEPLOY before
   `issues/257`'s repair has run on the target database.** On the three
   production copies, child frames and their slots are grouped under the ROOT;
   a shallow update of such a root would delete them.
   **Frame-graph replace for `update` and `upsert` on both frame routes.**
   For each frame the request sends, the delete set becomes the frame plus
   every subject whose `hasFrameGraphURI` is that frame. That restores the
   pre-2026-04-30 scope. Child frames are not included (open question 1).
   Compute the set INSIDE
   `update_subjects_graph`'s transaction, after the lock is taken: resolved
   before the lock, a concurrent writer could add a slot between the read and
   the delete. Then the lock, the `if_unmodified_since` compare-and-set and the
   stamp all keep working unchanged. Frames the request does not name are not
   touched. That is what lets two services co-own one entity's frames.
2. **Entity-frame upsert gets update's checks.** It should validate ownership
   for frames that exist, refuse frames owned by another entity, check that the
   entity exists, and create the linking edge for frames that do not exist yet,
   using the deterministic URIs from `kg_impl/edge_uris.py` (`issues/253`) so a
   replay adds nothing.
3. **`create` refuses an existing frame** with ALREADY_EXISTS, matching entity
   `create` (DECIDED 2026-10-02, open question 3). As on the entity route, ANY
   sub-object URI in the payload that already exists (slot, slot edge, child
   frame) refuses the request, not only the frame URI. The check runs inside the
   write transaction, after the lock, so two concurrent creates of one frame
   cannot both pass it. Standalone **`update` refuses a missing frame** with
   NOT_FOUND.
4. **`replace` becomes one transaction, guarded, and scoped to what it names**
   (decided): the named frames plus their descendants, on both routes, with or
   without `parent_frame_uri`. Entity-frame `replace` stops deleting the
   entity's other frames. Entity `replace` answers INVALID_REQUEST in a 200 and
   is removed from the documented entity modes.
5. **Unknown modes answer INVALID_REQUEST** on the standalone route.
6. **Client: add an entity upsert.**
7. **Status strings**: a successful frame upsert or update says UPSERTED or
   UPDATED, not CREATED.

## Item 1, as built (2026-10-03)

`update_subjects_graph` gains `replace_frame_graphs`. For each frame named, it
resolves every subject whose `hasFrameGraphURI` is that frame, plus the frame
itself, and deletes them with the request's subjects. That happens INSIDE the
transaction, after the lock and the guard, so a slot added concurrently cannot
slip between the read and the delete. Both processors' update/upsert paths
(`kgentity_frame_create_impl` and `kgframe_create_impl`,
`execute_atomic_frame_update`) pass the frames they write. `create` passes
none: it replaces nothing.

**The removed members' derived rows go too.** FTS rows are cleared in the same
transaction (`sync_fts_before_delete`). The URIs of members deleted and not
re-sent come back through a new `removed_uris` (on `CreateFrameResult` and
`UpdateFrameResult`), and the three frame write handlers schedule an auto-sync
DELETE for them, which clears vector, geo and fuzzy rows.

**Shallow, by the grouping rule.** A parent -> child `Edge_hasKGFrame` carries no
grouping (`issues/257`), so a child frame, its slots and the link to it are
never in the parent's frame graph.

**Tests:** `tests/api/test_frame_graph_replace.py`, on the vg test stack
driven by the `vital-graph` conda env. **This is the first reproduction of this
issue's defect through the API.** On the parent commit's server code, the four
slot-left-out cases (update/upsert × entity/standalone) FAIL with "MERGED: the
slot left out of the request survived", and the derived-row case fails. The two
guards (a parent update leaves its child, its slot and the link alone; upserting
one frame leaves another alone) pass, as they must before and after. With the
change, all 7 pass. Full `tests/api` 572 tests, 0 failures; `tests/unit` 5,184
tests, 6 failures, all `test_document_converter` (the env lacks `mammoth` and
`pdfplumber`).

**Tracked item 8 — entity-frame writes did not keep the derived stores in step.
FIXED 2026-10-03.** Vector, geo, fuzzy and FTS rows for a frame's slots are
maintained by auto-sync, which a write route schedules after its commit. The
standalone `/kgframes` route always did. The entity-frame routes
(`_create_or_update_frames` for create and upsert, `_update_entity_frames`, and
`_replace_entity_frames`) scheduled NOTHING for the subjects they wrote. So a
slot written or rewritten through `/kgentities/kgframes` was never embedded,
geocoded or indexed, and a rewritten one kept its OLD rows, until something
else touched it. Found while building item 1, which added only the DELETE sync
for removed members. Fixed by scheduling an `upsert` auto-sync for every
subject each of the three handlers writes.

Tests: `tests/api/test_entity_frame_auto_sync.py`, through geo (a
`KGGeoLocationSlot` is geocoded by auto-sync into a slot-keyed row, but only if
its owning entity resolves). On the parent commit's server code, the entity-frame
create, update and upsert cases FAIL with no geo row. A CONTROL, the same frame
written through `POST /kgentities`, which already scheduled auto-sync, passes,
so the mechanism works and the failures are the gap. A first control through
standalone `/kgframes` was invalid: the geo handler needs an owning entity, and a
standalone frame has none. With the fix, 4/4. Full `tests/api` 576, 0 failures;
`tests/unit` 5,185 with the 6 `test_document_converter` failures (env lacks
`mammoth`, `pdfplumber`).

## As built, 2026-10-04 (released in 0.0.44)

**Client.**
- `upsert_kgentities` (item 6), on the endpoint and the client facade. Marked
  replay-safe: the server path is `upsert_objects_atomic`, a locked
  delete-then-insert.
- The `delete_kgentity` message and defaults (section D).
- **Retry marking follows the mode (the client half of item 3).**
  `replay_safe_mode(operation_mode)` in `client/endpoint/base_endpoint.py`: update,
  upsert and replace may be replayed after a post-send failure; create may not.
  `create_entity_frames`, `create_kgframes`, `create_kgframes_with_slots` and
  `create_frame_slots` follow their argument; `create_child_frames`, which
  always sends create, is not marked. **Shipped ahead of the server half**, so
  until a create refuses an existing frame, a create that times out is no
  longer retried by the client even though the replay would be harmless. A
  caller that autosaves through `create` gets more uncertain writes until it
  moves to `upsert`, which is the move item 3 needs anyway.
- `if_unmodified_since` on `delete_kgentity`, `delete_kgentities_batch`,
  `delete_entity_frames`, `delete_kgframe`, `delete_kgframes_batch`, and the
  methods that delegate to them. `absent_uris` on the frame deletes.

**Server, the delete contract (delete decisions 1-4, both delete fixes).**
- **`/kgentities`, both forms, one locked transaction.**
  `delete_entity_graph_bulk` gains `entity_only` and `if_unmodified_since`.
  Entity-only deletes the entity subject alone and is REFUSED
  (`DeleteRefused` -> INVALID_REQUEST) while anything else names it in
  `hasKGGraphURI`; the member check runs after the entity lock. The SPARQL read
  plus quad-level `delete_entity` is gone, with `delete_entities_batch` and two
  lookups nothing called. The batch reports refused and conflicted entities
  apart from failures: PARTIAL if anything else was satisfied, otherwise
  INVALID_REQUEST / CONFLICT, or STORE_FAILED if something also failed.
- **One frame delete primitive, both routes.**
  `SparqlSQLBackendAdapter.delete_frame_subtrees`: lock, existence, ownership,
  children, guard, delete set, aux-table and FTS sync, subject-level delete,
  stamp, all in one transaction. The entity route locks the entity and stamps it
  in the transaction (the post-commit `touch_entity_modification_time` is gone);
  `/kgframes` locks every frame in the subtree, read-lock-reread until it stops
  growing. `kg_impl/frame_delete.py` maps the outcome to the response for both
  routes. `KGEntityFrameDeleteProcessor` is deleted. The subject-level delete with
  its syncs is extracted to `_delete_subjects_synced`, shared with
  `update_subjects_graph`.
- **Statuses.** A frame owned by another entity refuses the whole entity-route
  request (it was skipped under DELETED). `/kgframes` refuses any subtree holding
  an entity's frame (decision 3, DELETES ONLY so far). Absent is NO_OP on both
  frame routes (`/kgframes` single said NOT_FOUND), with `absent_uris`.
- **Guards (decision 4).** Stale -> CONFLICT, nothing deleted. Absent target ->
  NO_OP, not compared. One stamp for several entities or several `/kgframes`
  roots -> INVALID_REQUEST before anything runs. **One deviation from the
  decision as written:** a present guard subject with NO stamp answers CONFLICT,
  not STORE_FAILED, because the deletes use the writes' own `_compare_stamp`,
  and that is what the writes do. "As for writes" was the intent; the text was
  wrong about what the writes do.

**Refusals reach the caller.** `tests/unit/test_a_refusal_reaches_the_caller.py`
(from the deploy session, which had run the check by hand on three releases):
every `try` under `endpoint/` and `kg_impl/` that catches `StaleWrite` must also
catch `GuardUnsatisfiable` and `UngroupableSlot`, or a refusal falls to the broad
`except Exception` and arrives as a generic failure. It failed on this tree at
the three sites the deploy session named, all left by `issues/257` and
unreachable today: `_create_frame_slots`, `_update_frame_slots` (now
INVALID_REQUEST) and `update_subjects_graph` (re-raise). It also failed at five
sites in the delete code above, one of them REAL: the batch entity delete did
not catch `GuardUnsatisfiable`, so an undecidable guard was counted as a plain
failure with its reason only in the log. All eight are fixed. Their patch added
the create-route handler twice, the second copy returning `SlotUpdateResponse`;
it was applied by hand with one handler per site.

**Not built in that round** (all built in the next one, below): `replace`,
`/kgframes` refusing entity frames on writes, the entity-existence check inside
the frame-create transaction, the production orphan count.

## As built, 2026-10-04, second round (released in 0.0.44)

**`replace` (item 4) is `delete_frame_subtrees` with an insert.** One
transaction, under the entity lock (entity route) or the locks of every frame in
the subtree plus the frames written (`/kgframes`). Scope is what the request
NAMES: each frame in it and its descendants in the store; a frame not there yet
is created. Guarded (on the entity; on `/kgframes`, on the request's one top
frame — several with a guard is AmbiguousPrecondition). A refused or failed
replace changes nothing. Parent links: the entity route re-creates its links, so
the old ones into the subtree go; `/kgframes` keeps a link into the subtree from
outside it unless `parent_uri` re-creates it. Both used to delete with separate
SPARQL updates and then create, with no lock and no guard. Found against the
previous code by the new tests, beyond the scope:
- entity-route replace OVERWROTE ANOTHER ENTITY'S FRAME without complaint;
- `/kgframes` replace of a child without `parent_uri` DETACHED it from its
  parent;
- both deleted every top-level frame of the entity, or every child of the
  parent, whatever the request named.
Entity `replace` on `/kgentities` answers INVALID_REQUEST (was a 500).
`_delete_frame_from_backend` is deleted; nothing calls it.

**Decision 3 on writes.** `/kgframes` refuses, INVALID_REQUEST, nothing written:
create, update, upsert or replace over an entity's frame; `parent_uri` naming an
entity's frame; `parent_uri` naming an ENTITY, which attached the frame with an
`Edge_hasEntityKGFrame` without the entity's lock (not in the decision's list,
same hazard). The frame checks run in the write's transaction after its lock
(`standalone_precheck`, through a new `precheck` hook on
`update_subjects_graph` and `delete_frame_subtrees`); "is the parent an entity"
runs before it, the type of an object not being something a concurrent write
changes. The slot routes (`/kgframes/kgslots`) are still out of scope.

**The entity check under the lock (decision 1, create half).** Entity-frame
create checks the entity exists in its write transaction, after the entity lock
(`entity_present_precheck`), not before it. Same answer for a missing entity as
before (STORE_FAILED, "Target entity ... not found"); only when it is decided
changed. `validate_entity_exists` is deleted.

**One refusal base.** `kg_impl/refusals.RequestRefused`, INVALID_REQUEST.
`UngroupableSlot`, `DeleteRefused`, `FrameOwnedByEntity` and `EntityAbsent`
derive from it, every handler that caught `UngroupableSlot` catches the base, and
`test_a_refusal_reaches_the_caller.py` now requires the base on every refusal
path.

**Also fixed, found by these tests:** every early `_fail` in
`KGFramesEndpoint._create_frames` was a 500. Local imports of the response
models in its `except` blocks made the names local to the whole function, so the
helpers raised "cannot access free variable" — "space not found" and "no KGFrame
objects" included.

**Tests.** `tests/api/test_replace_and_ownership_contract.py`, 16 cases. Against
HEAD's server code 14 FAIL, each on its defect; 2 pass on both (a deep replace,
and a frame onto a missing entity — kept behaviour). With the change 16/16.
`tests/unit` 5,200 passed.

**Orphan census (2026-10-04).** `scripts/census_entity_orphans.py`, read-only
SQL: an orphan root is a `hasKGGraphURI` value that is not the subject of any
quad in its graph; its members are classified by `vitaltype`. It reports the
total roots too, because a space with no `hasKGGraphURI` at all also reads 0.
- **Production: 0 orphans.** 302,195 roots across the four spaces that have
  entity graphs (main KG 88,469; actions 86,685; lead data 79,142; lead prod
  47,899), none orphaned. The archive, underwriting, types, wordnet and test
  spaces carry no `hasKGGraphURI`. Every space under 3s.
- **Dev: 1**, in the actions space — a nurture action whose entity is gone,
  leaving 1 frame, 3 slots and 9 edges. Every other space 0. Slowest space 34s.
So the old entity-only default did not, in practice, leave orphans in
production; the refusal is prevention, and there is nothing to clean up there.
The dev orphan was deleted afterwards (2026-10-04), through the API, with its
entity graph; dev now also counts 0.

**Tests.** `tests/api/test_delete_guards_and_scope.py`, 21 cases (D11-D12e among
them), on the vg test stack driven by the `vital-graph` conda env. Against the
previous server code 13 FAIL, each on its own defect (entity-only deleted an
entity with a frame; every guard ignored; another entity's frame deleted
without complaint; absent entity frame STORE_FAILED; A deleted B's save;
`/kgframes` deleted an entity's frame; absent frame NOT_FOUND; one stamp for two
roots accepted). 8 pass on both: the unguarded deletes, a current stamp, the
client upsert. With the change, 21/21. `tests/unit/test_frame_delete_contract.py`
drives the response mapping with a stub. Unit tests that pinned the replaced
code were rewritten, not deleted: the frame-delete success guarantee
(`issues/242`) moved to the new module, the derived-table matrix lists the shared
delete and the frame delete as write paths, and the entity stamp test now
asserts the stamp in the transaction instead of the touch after it. `tests/unit`
5,196 passed.

## As built, 2026-10-04, third round (released in 0.0.44)

**Item 2 — entity-frame upsert gets update's checks.** Under the entity lock,
in the write's transaction (`entity_frames_precheck`): the entity exists (a
missing one answers as `create` does, STORE_FAILED "not found"), and every frame
named that already exists belongs to it (`owned_by_entity`, the rule the frame
delete uses, now shared) — one of another entity's, or of none, refuses the
request (`FrameNotOwned`, INVALID_REQUEST). Each frame without its link gets the
deterministic one (`Edge_hasEntityKGFrame`, or `Edge_hasKGFrame` under
`parent_frame_uri`): new frames, and any an earlier upsert left unlinked. Which
frames lack a link is read before the transaction; safe because the link URI is
deterministic, so a concurrent writer writes the same subject.

**Item 3, update half.** `/kgframes` update of a frame that does not exist
answers NOT_FOUND (`FrameAbsent`, decided under the lock) instead of creating
it. `RequestRefused` carries the status it is answered with, so the handlers
map each refusal to its own. The CREATE half (create refuses an existing frame)
still waits for the portal and the API service to autosave through `upsert`.

**Item 5.** An unknown `/kgframes` mode answers INVALID_REQUEST; it became a
create. (The entity routes take the mode as an enum, which FastAPI rejects
before the handler.)

**Item 7.** A successful entity-frame upsert answers UPSERTED, "Successfully
upserted N frames". The standalone route already did.

**Tests.** `tests/api/test_upsert_and_mode_contract.py`, 7 cases: against the
previous server code all 7 FAIL (CREATED for an upsert; a created frame
unlinked, twice; another entity's frame overwritten; frames written onto a
missing entity; update creating a missing frame; a typo becoming a create).
With the change 7/7. One existing test relied on update creating a frame
(`test_the_batch_still_works_unconditionally`); it now creates it first.

## As built, 2026-10-04, fourth round (`ed186757`, released in 0.0.45)

**Item 3, create half — built, OFF by default.** With
`VITALGRAPH_FRAME_CREATE_REFUSES_EXISTING=1`, a frame `create` on either route is
refused ALREADY_EXISTS when ANY object the client sent (frame, slot, slot edge,
child frame) already exists — decided in the write's transaction, after the lock
(`refuse_existing_precheck`). Off by default because the callers are NOT ready,
checked in the Resource API's code: `lead_sync` adds SF-mapped frames to an
existing entity with `create`; `kg_utils.write_or_update_frame` falls through to
`create` when its existence check fails and counts on the overwrite; the Resource
API's own `/kgentities/kgframes` route defaults to `create`. Switch it on after
those move to `upsert`. The three tests that asserted create-overwrites (F2, S2,
S3) now rewrite through `upsert`, keeping their stale-stamp purpose, so they pass
either way. `tests/api/test_frame_create_refuses_existing.py` (3) runs only when
`VG_TEST_FRAME_CREATE_REFUSES_EXISTING=1` says the server has it on: verified on
the vg test stack with it on (3/3; and with it on, the full frame suites pass
except the three tests named above, before they moved), and with it off (skips).

**The slot routes (decided 2026-10-04): two routes, one contract**, mirroring the
frame routes.
- `/kgframes/kgslots` writes and deletes a STANDALONE frame's slots, locked,
  guarded and stamped on the frame, and REFUSES an entity's frame
  (`FrameOwnedByEntity`), as `/kgframes` does for frames.
- NEW `POST`/`DELETE /kgentities/kgframes/kgslots` do it for an entity's frame,
  locked, guarded and stamped on the ENTITY, and refuse a frame that is not that
  entity's. The entity graph cache is invalidated. Client:
  `kgentities.create_entity_frame_slots` (create/update/upsert) and
  `delete_entity_frame_slots`.
- The contract, decided under the lock (`slot_write_precheck`,
  `delete_frame_slots`): `create` refuses an existing slot, `update` a missing
  one, `upsert` takes either; a slot of another frame is refused (update used to
  rewrite it and move it under this frame); an `Edge_hasKGSlot` is minted only
  for a NEW slot (an upsert of a slot written by the entity route added a second
  edge); an unknown mode is refused; delete is one transaction (it was two SPARQL
  updates per slot, no lock), an absent slot is NO_OP (was NOT_FOUND), and it
  accepts `if_unmodified_since`.
- **Found by the read-back test: the slot route never set `hasKGGraphURI`.** A
  slot added to an entity's frame through it was missing from the entity graph
  and would outlive the entity's graph delete (only a handler nothing called set
  it). The entity route now sets it; the standalone route drops a client-sent
  one. Census of existing data (members of an entity's frame without
  `hasKGGraphURI`): **production 0**; dev 2, both slot edges on test-dispatch
  data, left in place.
- Removed with the old handlers: `_store_frame_slots_in_backend`,
  `_update_frame_slots_in_backend`, `_delete_frame_slots_from_backend`,
  `_slot_exists_in_backend`, `_slot_connected_to_frame`,
  `_set_slot_frame_relationships`.

**Behaviour change for callers:** anything writing or deleting an ENTITY's
frame's slots through `/kgframes/kgslots` is refused after the deploy. The
Resource API passes `/kgframes/kgslots` through to this route as is; it needs
routes onto `/kgentities/kgframes/kgslots`, and the portal to use them for entity
frames.

**Tests.** `tests/api/test_slot_routes_contract.py`, 9 cases (both routes, the
modes, foreign slot, foreign frame, stale guard, delete with absent and stale,
edge not duplicated, entity graph shows the slot). Unit tests of the replaced
handlers were rewritten against `_write_frame_slots`.

## Callers, re-checked 2026-10-04 — two claims above were stale, and a defect

The fourth round named the Resource API as not ready, on a reading that
predated its own changes. Re-checked against it at its `7d80c6e2` (already on
0.0.45) and every portal, client and agent repo beside it:

- **The slot routes need no caller change.** "The Resource API passes
  `/kgframes/kgslots` through ... it needs routes onto
  `/kgentities/kgframes/kgslots`" is true of the pass-through, but NO code
  anywhere calls the slot write or delete routes — not the portals, not the
  Node or Python clients (they define the methods, nothing calls them), not the
  agents. Slots are written inside whole frames through `/kgentities/kgframes`.
  The 0.0.45 refusal breaks nothing; the entity slot route is available, not
  required.
- **The create flag does not depend on `lead_sync` / `write_or_update_frame` /
  the route default.** All three reach VitalGraph through the Resource API's
  `create_entity_frames`, which already catches `already_exists` and re-sends
  the objects. The other direct frame writers (`retention/kg_write.py`,
  `underwriting/uw_decision_kg.py`) already send `upsert`.
- **But the re-send is `update`, and that has a hole — a VitalGraph defect.**
  Measured on the vg test stack at 0.0.45, entity route, one batch holding an
  EXISTING frame A and a NEW frame B:

  | mode | answer | B written? | A's old slot |
  |---|---|---|---|
  | `update` | `updated`, `is_success` TRUE — "Successfully updated 1 complete frame(s), 1 frame(s) failed: No valid frames found for update" | **NO** | replaced |
  | `upsert` | `upserted` | yes | replaced |
  | `create`, flag off | `created` | yes | **survives** — create MERGES |

  **DEFECT: entity-route `update` reported success for a frame it did not
  write.** Item 3's update half made `/kgframes` update of a missing frame
  `not_found`; the entity route still skipped it inside a success. FIXED in the
  fifth round, below.
- **Today, with the flag off, `create` of an existing frame MERGES** (the old
  slot survives beside the new one), so any caller re-saving a frame through
  `create` accumulates stale slots. Callers that mean create-or-refresh should
  send `upsert`.

Instructions for the Resource API: `planning/planning_deploy/
resource_service_frame_writes_20261004.md` (local). Probe: a throwaway API test
of the three modes above, not kept.

## As built, 2026-10-04, fifth round (`81e718db`) — no switch, and update is all or nothing

Decided 2026-10-04: **no dependency on callers — VitalGraph gets the correct
implementation.** The switch is gone.

- **`create` always refuses an existing frame**, on both routes: anything the
  client sent (frame, slot, slot edge) that exists answers `already_exists`,
  nothing written (`refuse_existing_precheck`, under the lock). It MERGED into
  the frame, keeping its old slots. `VITALGRAPH_FRAME_CREATE_REFUSES_EXISTING`
  and `create_refuses_existing()` are removed; `tests/api/test_frame_create_
  refuses_existing.py` always runs.
- **Entity-route `update` decides the whole request before writing any of it.**
  Each frame group is its own transaction, so the check runs first over every
  frame the request touches (`run_precheck` with `entity_frames_precheck(...,
  require_existing=True)`), and again under the lock in each group's write:
  a missing frame → `not_found`; another entity's → `invalid_request`
  (`FrameNotOwned`, raised by the update processor too, which used to skip it);
  slots or edges sent without their frame → `invalid_request` (an update
  replaces the frame graph and would drop the frame). Nothing written in each
  case. Groups that commit before a later one fails answer `partial`
  (`is_success` false), not `updated`. Refusals carry their own status
  (`not_found` was answered `invalid_request`).

The table in "Callers, re-checked" is the before. After:

| batch: existing A + new B | answer | written |
|---|---|---|
| `create` | `already_exists` | nothing |
| `update` | `not_found`, naming B | nothing |
| `upsert` | `upserted` | both |

**Tests.** `tests/api/test_entity_frame_update_is_all_or_nothing.py` (5: missing
frame, another entity's frame, frameless slots, an update of two existing
frames, the mixed batch as upsert). The "before" is the probe above on the 0.0.45
stack; the stack was rebuilt from the working tree by someone else mid-change, so
the new file's first run was already against the fix. `tests/api/test_frame_create_
refuses_existing.py` (3) now unconditional. Full `tests/api`: 640 passed, 9
skipped; `tests/unit`: 5,513 passed.

What the Resource API should change for its OWN writes (its `already_exists`
fallback re-sending as `upsert`, and `upsert` where it means create-or-refresh):
`planning/planning_deploy/resource_service_frame_writes_20261004.md`.

## Open questions

1. ~~**Does a frame graph include its descendant frames?**~~ **ANSWERED by
   `frame_hierarchy_consistency_plan.md` §3: no.** `update` (and so `upsert`) is
   shallow; `replace` is the deep, subtree mode. The fix must keep
   `test_update_preserves_children` green. Concretely, the delete set is
   resolved by `hasFrameGraphURI = <frame>` and does NOT follow `Edge_hasKGFrame`.
2. **Does every slot and slot edge carry `hasFrameGraphURI`? NO, and the
   census rules out deleting by it.** Run 2026-10-02/03 on the dev cluster (all
   44 spaces) from the raw quad table, not the `_edge` projection, which is
   known to be incomplete. For every `Edge_hasKGSlot` (frame F → slot S) it
   counts: S missing the grouping, S grouped under a frame other than F, the
   edge missing `hasFrameGraphURI = F`, and slots linked from more than one
   frame.

   | spaces | slot edges | finding |
   |---|---:|---|
   | API-written test spaces (≈20) | 12–320 each | clean |
   | production copies: underwriting, lead test, actions | 122k–401k | clean (1 slot edge points at an absent slot) |
   | **production copies: the main KG space, its newer copy, its archive** | 61k–312k | **913–925 slots grouped under ANOTHER frame**; 1 slot edge missing the grouping |
   | **bulk-loaded / generated** (`sp_lead_*`, `sp_graph_synth_*`, `sp_kg_rel`, `sp_lead_types`, `kgquery_perf`, `wordnet_frames`, `sp_sql_lead_dataset`) | 220–570k | **no `hasFrameGraphURI` at all**: no term for it exists in the space. `sp_lead_depth1` has no `hasKGGraphURI` either |
   | `space_client_kgentities_test` | 14 | 9 of 14 slots missing it |
   | no slot shared between two frames | | in any space |

   (The two 100k-entity synthetic spaces were still running when this was
   written. They are loaded the same way as the other synthetic spaces.)

   **The 925, classified** (main KG production copy): in ALL of them the frame
   the slot is grouped under exists and is the PARENT of the linking frame (232
   child frames under 226 parents). The child frame itself carries
   `hasFrameGraphURI` = the parent too. So these subtrees are grouped under
   their ROOT frame, not per frame. They are campaign entities written by the
   API service.

   **Consequence for fix item 1, which deleted by `hasFrameGraphURI`:**
   - a shallow `update`/`upsert` of such a PARENT would delete its CHILD
     frames' slots, and the children themselves. Data loss;
   - a replace of such a CHILD would miss its own slots. Silent stale data, the
     defect this issue exists to fix;
   - on bulk-loaded spaces it would delete nothing but the frame.

   **DECIDED 2026-10-03: `hasFrameGraphURI` IS the definition of a frame
   graph.** A structure-based delete set (following `Edge_hasKGSlot`) was
   proposed and REJECTED. The fix deletes by `hasFrameGraphURI`, as the
   contract says. Data that does not carry a correct grouping is the defect, and
   the server's writers must never produce it. So before fix item 1 can land
   safely on these spaces:
   - the groupings the census found wrong or missing are repaired, as a data
     task with its own issue. **The rule (DECIDED 2026-10-03): every frame is
     grouped with ITSELF.** Concretely:
     - a `KGFrame`'s `hasFrameGraphURI` is its own URI;
     - a slot's is the frame that links it by `Edge_hasKGSlot`;
     - an `Edge_hasKGSlot`'s is its source frame.

     - an `Edge_hasKGFrame` (parent -> child) has NO grouping (decided
       2026-10-03, `issues/257`), so the frame graph never includes the links
       to child frames: a shallow `update`/`upsert` of a parent cannot unlink
       its children, and `replace`'s subtree delete removes those links
       explicitly, as the subtree primitive already specifies.

     So the 913–925 root-grouped child frames and their slots in the three
     production copies are regrouped under the child, and the bulk-loaded
     spaces are backfilled by the same rule. Nothing that a frame does not own
     carries its grouping, which is what keeps `update` shallow and makes
     `replace` the only subtree operation;
   - every server path that can store a wrong or missing grouping is closed
     (below), so the repaired data stays right.

   **How the bad groupings got in — two server-side openings, by reading:**
   - `_update_entity_frames` (pass 2) TAKES a slot's `hasFrameGraphURI` from the
     payload when the client sent one (`if graph_obj.frameGraphURI:`), and only
     infers it otherwise. The doc rule is that clients never set grouping URIs
     (`frame_hierarchy_consistency_plan.md` §5); this path trusts them.
   - `validation_utils.analyze_frame_structure_for_grouping`, which the update
     processor uses through `graph_operations.set_dual_grouping_uris`, knows
     only six slot classes (text, integer, boolean, double, datetime, entity).
     Choice, URI, geo, currency and other slots keep whatever grouping they
     arrived with. `graph_operations.py` also defines `set_dual_grouping_uris`
     TWICE (`:63` and `:401`); the second silently replaces the first.
   Which writer produced the 925 is not established.
3. ~~**Does any caller rely on `create` overwriting?**~~ **DECIDED: create
   refuses (option a).** It did rely on it, and `issues/253` is built on it. The test survey (below) found three tests that create an
   existing frame URI and assert SUCCESS:
   - `test_a_stale_frame_write_is_refused_over_http.py::test_the_newer_value_survives_the_slower_save`,
     which is literally named for "the reported symptom": the portal's autosave
     re-creating the same frame.
   - `test_a_stale_standalone_frame_write_is_refused.py::test_the_create_halves_refuse_a_stale_stamp_too`
     and `::test_create_child_frames_refuses_a_stale_stamp`.

   Separately, `tests/unit/test_the_client_may_replay_a_safe_write.py` marks
   `create_entity_frames`, `create_kgframes`, `create_child_frames` and
   `create_kgframes_with_slots` as **replay-safe**. That is only true because a
   repeated create overwrites. Under a refusing create, a retry of a create
   that landed answers ALREADY_EXISTS, a reported failure for a write that
   succeeded (`issues/253` already names this shape).

   **DECIDED 2026-10-02: (a), create refuses** on every route, so `create`
   means one thing for entities and frames. Writing a frame that may already
   exist is `upsert`. What follows from it:

   - **The portal moves to `upsert` FIRST.** If it re-creates frames today,
     every autosave after the server change would answer ALREADY_EXISTS. That
     answer arrives in a 200 body the portal does not read (`issues/253`), so the
     saves would be lost silently. Confirm the portal's mode from its code or
     from the API request logs (`POST /kgentities/kgframes` by
     `operation_mode`), and ship the portal change, deployed and verified, before
     the server change. The same applies to the API service's frame writes.
   - **The three `issues/253` tests move to `upsert`.** They keep their purpose
     (a stale stamp is refused, the newer value survives) under the mode a
     re-writing caller now uses. A fourth test pins the new rule: create on an
     existing frame answers ALREADY_EXISTS and changes nothing (F2/S2).
   - **The four create methods lose replay-safe** in
     `test_the_client_may_replay_a_safe_write.py`: `create_entity_frames`,
     `create_kgframes`, `create_child_frames`, `create_kgframes_with_slots`. A
     retried create that had landed would answer ALREADY_EXISTS, reporting
     failure for a write that succeeded. The corresponding `upsert` calls are
     replay-safe (a delete-then-insert replay is a no-op, per `issues/253`).
     Whether the client marks them so depends on how it distinguishes modes in
     one method. Today `operation_mode` is an argument, so the marking has to
     follow the argument, not the method name.
   - **Clients that retry a create should treat ALREADY_EXISTS on a RETRY as
     ambiguous**, not as a failure. Out of scope here; noted for the client.

## Test plan

Every case in the contract gets a test. This section records which exist, how
good they are, and what to write. It comes from a survey of `tests/`,
`test_scripts/` and `e2e/` on 2026-10-02.

### Why the contract was under-specified

The tests never pinned the semantics. Each gap below is why a regression could
land silently:

- **No test ever omitted anything.** Every update/upsert test re-sends the full
  slot set, or sends NEW slot URIs and checks something else (frame count,
  sibling name). So the 2026-04-30 scope change from frame graph to payload
  subjects broke no test, and nothing caught it.
- **No test exercises upsert at all** on `/kgentities` (live) or
  `/kgentities/kgframes`. The Python client cannot even send entity upsert:
  `create_kgentities`/`update_kgentities` take no `operation_mode`.
- **The replace tests never check what should SURVIVE.** `test_replace_mode`,
  `test_replace_with_hierarchy` and `test_replace_flat` check that the old child
  is gone and the root survives. None checks a sibling or another root frame.
  That is how entity-frame `replace` wiping every root frame went unnoticed.
- **Several "negative" tests pass whatever the server does.** E2's duplicate
  create catches its own `NameError` as "correctly raised". E4's update of a
  missing entity accepts "might succeed (create) or fail (not found)". D3, D8
  and the absent-frame half of D9 accept either outcome.
- **Many `case_*.py` tests are never run, or cannot be.** Several are
  defined but no runner calls them: F10 `replace`, D7, D8, F3, and the
  frame-update ownership/atomic cases. Several pass a `document=` keyword no
  client method accepts. And the `case_*.py` runners build
  `VitalGraphClient()` from `.env`, which points at the DEV server on :8001, not
  the test stack.
- **Three tests assert the opposite of the contract** (open question 3).

### Where the new tests go

New tests go in `tests/api` (`pytest -m api`, the :8002 test stack, a throwaway
space per module, with the stale-image check at session start), not in
`case_*.py`. One module per route:

- `tests/api/test_write_contract_entities.py`
- `tests/api/test_write_contract_entity_frames.py`
- `tests/api/test_write_contract_frames.py`
- `tests/api/test_delete_contract.py`

Rules for every test:

- **Assert on a READ-BACK** through the API, and for absence also by raw count
  in the space's quad table, as `test_entity_graph_delete_residue.py` does. A
  read path can miss an object that still exists.
- **Run each against the unfixed code first**, and record the result in the
  table. A test expected to fail is marked `xfail(strict=True)` with this
  issue's number until its fix lands, so a fix that turns it green without
  removing the marker fails the suite.
- The client gains an `operation_mode` on entity writes (fix item 6) before the
  entity upsert tests can be written through it. Until then, post the raw
  request.

### Case table

Status: **ok** = an adequate read-back test exists. **weak** = exists but
status-only or incomplete. **vacuous** = passes whatever the server does.
**NR** = defined but never run. **CONTRADICTS** = asserts the opposite. **none**.
"Today" is what the new test is expected to do against the unfixed code.

**Entity writes (`POST /kgentities`)**

| id | case | existing | status | action | today |
|---|---|---|---|---|---|
| E1 | create new | `test_integration_workflows.py::TestEntityCrudRoundTrip::test_full_lifecycle` | ok | keep | pass |
| E2 | create existing entity → ALREADY_EXISTS | `case_kgentity_create.py` Test 5 | vacuous | write; fix or delete the vacuous one | pass |
| E3 | create where a sub-object URI exists → ALREADY_EXISTS, nothing written | none | none | write | pass |
| E4 | update missing entity → NOT_FOUND, nothing written | `case_kgentity_update.py` Test 4 | vacuous | write | pass |
| E5 | update batch with one missing → NOT_FOUND, NONE of the batch written | none | none | write | pass, verify none written |
| E6 | update with a frame omitted → frame graph gone | none | none | write | pass |
| E7 | upsert missing → created | none (live) | none | write | pass |
| E8 | upsert existing with a frame omitted → gone | none | none | write | pass |
| E9 | upsert keeps the stored creation time | update only (`case_entity_server_properties.py`) | weak | write for upsert | pass |
| E10 | `replace` → 200 INVALID_REQUEST | none | none | write | **fail (500)** |
| E11 | `entity_only` keeps frames AND slots | `case_kgentity_entity_only_update.py::test_entity_only_preserves_frames` | weak (frame count only) | extend to slots | pass |
| E12 | misspelt mode → INVALID_REQUEST (both POST routes) | none | none | write | `/kgentities`: the mode is a FastAPI enum, so an unknown value is probably a **422**, against the 200 rule; check. `/kgframes`: **fail (becomes create)** |

**Entity-scoped frames (`POST /kgentities/kgframes`)**

| id | case | existing | status | action | today |
|---|---|---|---|---|---|
| F1 | create new → linked and listed | `case_kgentity_child_frame_update.py::test_create_new_child_frame_creates_edge`; `test_entity_frames_api.py` | ok | keep | pass |
| F2 | create existing frame → ALREADY_EXISTS, frame unchanged (raw count + slot value) | `test_a_stale_frame_write_is_refused_over_http.py` (2 tests) | **CONTRADICTS** | move those two to `upsert`; write this one | **fail (overwrites)** |
| F3 | update missing frame → NOT_FOUND | none | none | write | check |
| F4 | update with slot omitted → slot and its edge gone | none | none | write | **fail (merge)** |
| F5 | update keeps child frames | none on this route | none | port `test_update_preserves_children` | pass |
| F6 | upsert new frame → linked and listed | none | none | write | **fail (no edge)** |
| F7 | upsert with slot omitted → gone | none | none | write | **fail (merge)** |
| F7b | upsert keeps child frames | none | none | write (guards the fix) | pass |
| F7c | co-ownership: upsert F1, then F2 is byte-identical | none | none | write | pass |
| F8 | upsert a frame owned by another entity → refused, owner unchanged | none | none | write | **fail** |
| F9 | upsert against a missing entity → refused | `case_kgentity_frame_create.py::test_frame_creation_validation` | NR, broken | write | **fail** |
| F10 | replace without parent: named frame + subtree replaced, OTHER root frames survive | `case_kgentity_frame_hierarchical.py::test_replace_flat` | NR, no survivor check | write | **fail (wipes all)** |
| F10b | replace with parent: named child replaced, SIBLINGS survive | `::test_replace_with_hierarchy` | NR, no survivor check | write | **fail** |
| F10c | replace is atomic: a refused or failed replace leaves the old frames | none | none | write | **fail** |
| F11 | `if_unmodified_since` refuses a stale write, on update, upsert, create and replace | `test_a_stale_frame_write_is_refused_over_http.py` | ok for update/create | add upsert and replace | replace **fail (ignored)** |

**Standalone frames (`POST /kgframes`)**

| id | case | existing | status | action | today |
|---|---|---|---|---|---|
| S1 | create new | `test_kgframes_api.py::test_create_frame` | ok | keep | pass |
| S2 | create existing → ALREADY_EXISTS, frame unchanged; also when only a SLOT URI in the payload already exists | `test_a_stale_standalone_frame_write_is_refused.py` (2 tests) | **CONTRADICTS** | move those two to `upsert`; write this one | **fail (overwrites)** |
| S3 | update missing → NOT_FOUND | `::test_the_batch_still_works_unconditionally` | **CONTRADICTS** (updates a never-created frame, asserts success) | rewrite to create first | **fail (creates it)** |
| S4 | update with slot omitted → gone | none | none | write | **fail (merge)** |
| S5 | update keeps child frames | `case_kgframe_hierarchy.py::test_update_preserves_children` | ok, but `case_*` on the dev URL | port to `tests/api` | pass |
| S6 | upsert new | none (only an existing frame, status-only) | weak | write | pass |
| S7 | upsert with slot omitted → gone | none | none | write | **fail (merge)** |
| S8 | replace: subtree replaced, SIBLINGS under the same parent survive | `case_kgframe_hierarchy.py::test_replace_mode`, `::test_replace_with_hierarchy` | weak, no survivor check | extend | with parent **fail** |
| S8b | replace is atomic: inject a failure after the delete and before the insert, and assert the old subtree is fully present (raw count); a stale `if_unmodified_since` on replace is refused with the old subtree intact | none | none | write (integration, fault-injected) | **fail (the old subtree is gone; the guard is ignored)** |
| S9 | guard on the frame; a multi-frame guarded write → AmbiguousPrecondition; a guarded deep `replace` locks the subtree and guards the root | `test_a_stale_standalone_frame_write_is_refused.py`; unit precondition tests | ok for writes | add `replace` | **fail** |
| S10 | an entity-owned frame through `/kgframes` → refused (decision 3); covered by D10–D10c | none | none | see D10–D10c | **fail** |

**Deletes**

| id | case | existing | status | action | today |
|---|---|---|---|---|---|
| D1 | entity delete, default flag, entity WITH frames → INVALID_REQUEST; entity, frames, slots and edges all unchanged (raw count before = after) | `test_kgentities_api.py::test_delete_entity` (no frames) | weak | write | **fail (deletes the entity, orphans the rest)** |
| D1b | entity delete, default flag, entity with NO members → deleted, raw count 0 | `test_kgentities_api.py::test_delete_entity` | weak (status) | extend to a raw count | pass |
| D1c | entity delete, default flag, racing a frame create: under a held entity lock, start the delete and a frame create, release. Either the create lands first and the delete is refused, or the delete lands first and the create is refused (entity not found). Never an orphaned frame | none | none | write (integration, holds `lock_entities`) | **fail** |
| D1d | batch delete, default flag, one entity with members → refused per URI, the others deleted, status PARTIAL | none | none | write | **fail** |
| D2 | entity graph delete removes frames AND slots AND edges | `test_entity_graph_delete_residue.py` (frames only) | weak | extend to slots and edges | pass |
| D3 | absent entity → NO_OP with `absent_uris`, graph and entity-only | `test_delete_contract.py::test_deleting_an_absent_entity_is_no_op` | **ok — FIXED** | done | old code: graph **STORE_FAILED**, entity-only lacked `absent_uris`; fixed: pass |
| D4 | batch with one absent → DELETED, the absent one in `absent_uris`; all absent → NO_OP; graph and entity-only | `test_delete_contract.py::test_a_batch_with_an_absent_entity_is_deleted_and_names_it`, `::test_a_batch_where_everything_is_absent_is_no_op` | **ok — FIXED** | done | old code: **PARTIAL** / **STORE_FAILED**; fixed: pass |
| D5 | graph delete, single: the members' FTS rows are gone, through the API | unit source check only | weak | write | pass |
| D5b | graph delete, single: a slot's derived row is gone after auto-sync (checked through geo, seeded for the slot, geo + auto_sync enabled via the API) | `test_delete_contract.py::test_graph_delete_removes_a_slots_derived_rows` | **ok — FIXED** | done | old code: **row outlived the entity**; fixed: pass |
| D5c | graph delete, BATCH: same as D5b | `test_delete_contract.py::test_batch_graph_delete_removes_a_slots_derived_rows` | **ok — FIXED** | done | old code: **row outlived the entity**; fixed: pass |
| D6 | entity-frame delete, recursive refused / cascade | `case_kgentity_frame_hierarchical.py` (2 tests) | ok, `case_*` | port to `tests/api` | pass |
| D7 | entity-frame delete of another entity's frame → INVALID_REQUEST, frame unchanged (raw count) | `case_kgentity_frame_delete.py::test_frame_deletion_ownership_validation` | NR, broken | write | **fail (STORE_FAILED)** |
| D7b | mixed request: one own frame + one another entity's → INVALID_REQUEST, NEITHER deleted | none | none | write | **fail (deletes own, says DELETED)** |
| D7c | entity-frame delete racing a frame write that adds a slot: under a held entity lock, start both, release. Either the slot's write lands first and is deleted with the frame, or the delete lands first and the write is refused or recreates a complete frame. Never a stray slot (raw count of subjects with `hasFrameGraphURI` = frame) | none | none | write (integration, holds `lock_entities`) | **fail** |
| D7d | entity-frame delete advances the entity's `hasObjectModificationDateTime` in the same transaction: a writer holding the pre-delete stamp is refused CONFLICT | none | none | write | **fail (stamp is post-commit)** |
| D7e | entity-frame delete removes the members' vector rows, not only the frames' | none | none | write | check |
| D8 | entity-frame delete of an absent frame → NO_OP, `absent_uris` names it | `::test_nonexistent_frame_deletion` | vacuous, NR | write | **fail** |
| D9 | `/kgframes` delete single, batch, recursive; absent → NO_OP (single, was NOT_FOUND); a batch of present + absent → DELETED with `absent_uris` | `test_kgframes_api.py` (2); `case_frame_delete.py` | ok / vacuous for absent | write the absent case | batch **fail** |
| D9b | `/kgframes` recursive delete is atomic: inject a failure after the first frame's delete (patch the delete to raise for the second subtree member) and assert the WHOLE subtree is still present (raw count) | none | none | write (integration, fault-injected) | **fail (half a subtree)** |
| D9c | `/kgframes` delete racing a write to a DESCENDANT frame: under a held lock on the descendant's grouping, start both, release. Never a stray slot | none | none | write (integration, holds `lock_entities`) | **fail** |
| D10 | `/kgframes` delete of an entity-owned frame → INVALID_REQUEST (decision 3), frame and entity unchanged; also for an entity-owned DESCENDANT of a standalone root | none | none | write | **fail (deletes it, entity cache still shows it)** |
| D10b | `/kgframes` `update`/`upsert`/`replace` of an entity-owned frame → INVALID_REQUEST, frame unchanged | none | none | write | **fail** |
| D10c | `/kgframes` `create` on an existing entity-owned frame URI → INVALID_REQUEST; and `create` with `parent_uri` = an entity-owned frame → INVALID_REQUEST | none | none | write | **fail (overwrites / attaches)** |
| D11 | delete racing a frame write under a held lock: all or nothing, no stray slots | none (locking tests are SPARQL-update only) | none | write (integration, holds `lock_entities`) | **fail** |
| D12 | entity-frame delete with a STALE entity stamp → CONFLICT, frames unchanged (raw count); with the current stamp → deleted, and the stamp advanced | none | none | write | **fail (parameter not accepted)** |
| D12b | `/kgframes` delete with a stale ROOT stamp → CONFLICT, subtree unchanged; a guarded request naming two roots → AmbiguousPrecondition, nothing deleted | none | none | write | **fail** |
| D12c | `/kgentities` delete (graph and entity-only) with a stale entity stamp → CONFLICT, nothing deleted; a guarded `uri_list` of two → AmbiguousPrecondition | none | none | write | **fail** |
| D12d | a guarded delete of an ABSENT target → NO_OP, not CONFLICT, on all three routes | none | none | write | **fail** |
| D12e | the race itself: reader A reads the stamp, writer B saves a frame, A deletes with the old stamp → CONFLICT, and B's save survives | none | none | write | **fail (A deletes B's save)** |

### Existing tests to change

- **The three CONTRADICTS tests** (F2, S2, S3) and the replay-safe unit list:
  rewrite once open question 3 is decided. Don't delete them. They carry
  `issues/253`'s stale-write coverage, which must survive under whichever mode
  they move to.
- **The vacuous ones** (E2, E4, D3, D8, the absent half of D9): delete them
  once the `tests/api` replacement lands. A test that cannot fail is worse than
  none, because it reads as coverage.
- **The NR and broken `case_*` files** (F10, D7, D8, F3, F9): either wire them
  into their runner, fixed, or delete them in favour of the ports. Don't leave
  them defined and dead.

### Counts

67 cases. **ok 8** (several only partly: F11, S9 and D9 cover writes or the
present case only; S5 and D6 run against the dev URL), **weak 8**, **vacuous 4**,
**never run 4**, **CONTRADICTS 3** (plus the unit replay-safe list), **none 40**.
So 59 of 67 cases have no adequate test. Two `case_kgframe_hierarchy.py` tests
(the D10 note) use `/kgframes` on an entity's frame and must move routes under
decision 3.

## Out of scope

The slot routes (`/kgframes/kgslots`, `KGSlotCreateProcessor`) have their own
create/update/upsert and were not read for this. Relations (`/kgrelations`)
likewise. Both should get the same matrix once this one is settled.
