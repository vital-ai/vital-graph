# 279 — The frame write routes accept edges and slots naming a frame that does not exist

## Status: FIXED IN CODE 2026-10-19 (not yet released). Refuses from the first release.

**Related:** `issues/212` (the same gap, first seen as 28 schedule slots on the
main KG space; recorded there in passing and never opened as an item),
`issues/256` (the write-mode matrix and prechecks this belongs in),
`issues/257` (frame groupings), `issues/225` (objects a frame write drops).

## What production shows

The UW space, 2026-10-14 to 2026-10-19. The maintenance job's dangling-endpoint
probe (`edge_table_dangling_endpoints`, added under `issues/212`) has warned
every cycle, and the count grows with every decision explanation written (13,172
→ 13,518 dangling sources and 4,293 → 4,411 dangling destinations over six hours
on Oct 18-19). The client team traced it (their issue on the resource
service):

| | edges | distinct missing nodes | edge type |
|---|---|---|---|
| missing source | 14,428 | 4,704 | `Edge_hasKGSlot` |
| missing destination | 4,704 | 4,704 | `Edge_hasKGFrame` |

The same 4,704 nodes on both sides: child frames (driver, item and
stipulation-note frames) of decision-explanation frames. None of them has a
single quad. The client's frame builder sent the parent frames, the children's
slots, their `Edge_hasKGSlot` and the parent → child `Edge_hasKGFrame`, and left
out the child `KGFrame` objects. `POST /kgentities/kgframes` (upsert) accepted
every one of those writes.

The client bug is the client's to fix. This issue is VitalGraph's part. **A
write naming a frame that is neither in the request nor in the store is
accepted.** Had it been refused, the first explanation write would have failed
loudly on 2026-10-14 instead of leaving 4,704 unreachable subtrees, found five
days later.

## Confirmed

`tests/api/test_frame_write_refuses_a_missing_endpoint.py`, vg test stack,
2026-10-19. Each test sends a parent frame with one slot, plus a child's slot,
`Edge_hasKGSlot` (child → slot) and `Edge_hasKGFrame` (parent → child), but no
child `KGFrame`:

| route | today |
|---|---|
| `POST /kgentities/kgframes`, `create` | **accepted** — "Successfully created 7 frames" |
| `POST /kgentities/kgframes`, `upsert` | **accepted** — "Successfully upserted 7 frames" |
| `POST /kgframes` (standalone) | **accepted** |
| `POST /kgentities` (entity + frames) | refused — "Entity validation failed: Edge destination not found in objects: …child…" |

The whole-entity create is safe because `KGEntityValidator.validate_entity_structure`
(`kg_impl/kg_validation_utils.py`) requires every edge endpoint to be in the
request. The frame routes have nothing like it:

* `KGEntityFrameCreateProcessor.create_entity_frame`
  (`kg_impl/kgentity_frame_create_impl.py`) categorises frames, slots and edges
  and writes them; nothing compares an edge's endpoints with what exists.
* `kgframes_endpoint._validate_frame_structure` checks frame properties, not
  edges.
* `utils/validation_utils.validate_no_orphaned_objects` is a placeholder that
  always returns valid. `KGEntityValidator._check_orphaned_objects` only warns,
  and only when the request has no edge of the right TYPE at all.

The request-only rule cannot simply be copied: a frame write legitimately names
things that are already stored. That covers the entity (`Edge_hasEntityKGFrame`),
an existing parent (`parent_frame_uri`), and an existing frame that a new slot
attaches to.

A second, smaller defect: the success message counts every written URI, edges
and links included, as "frames" (`len(result.created_uris)` in
`kgentities_endpoint._create_or_update_frames`). One frame was sent above, and the
reply said 7.

## Fix (proposed)

1. **Refuse what cannot be reached.** For each structural edge in a frame write
   (`Edge_hasKGFrame`, `Edge_hasKGSlot`, `Edge_hasEntityKGFrame`), and for
   `parent_frame_uri`, every endpoint must be in the request or present in the
   graph. Check the request first, which costs nothing. Check whatever is left
   against the store as a `precheck` inside the write transaction, under the
   entity lock, like `entity_present_precheck`. Checked earlier, a delete
   between the check and the write would let the gap back in. Refuse as a
   domain outcome (HTTP 200, `success: false`) naming every missing URI, and
   write nothing.
2. **Also refuse a slot with no `Edge_hasKGSlot`**, in the request or the store.
   That is the other unreachable shape `issues/212` found (`unreferenced_kg_objects`).
3. **Same rule on both frame routes**, `/kgentities/kgframes` (all modes, with
   and without `parent_frame_uri`) and `/kgframes`, through one shared function,
   so the two routes cannot drift apart again.
4. **Message**: count frames as frames.
5. **Refuse from the first release; no log-only phase** (decided 2026-10-19).
   Any client sending this shape gets refusals instead of silent orphans. In
   production that is the UW explanation write, until the client fix ships, and
   that is the intended outcome: a refused write is reported by the client,
   where an accepted one left 4,704 orphans unnoticed for five days.


## Fixed (code)

* `vitalgraph/kg_impl/frame_reachability.py`. `outside_references` reads the
  request, and `reachability_postcheck` runs the two rules (1 and 2 above) on
  what the request cannot answer. A self-contained request gets no check at
  all. A refusal is `UnreachableObjects` (INVALID_REQUEST in a 200), naming
  every missing object and loose slot, and nothing is written.
* **The check runs after the write, not before it.** `update_subjects_graph`
  and `delete_frame_subtrees` take a `postcheck`, which runs in the
  transaction after the delete and the insert and before the stamp and the
  commit. A frame upsert replaces each named frame's graph, and a replace
  deletes subtrees, so a stored object an edge names can be removed by the same
  write. A check before the write would pass that. A check after it sees the
  outcome.
* Wired on every frame write: `/kgentities/kgframes` create, update/upsert and
  replace (`kgentity_frame_create_impl`), and `/kgframes` create, update/upsert
  and replace (`kgframe_create_impl`). The slot routes already mint an edge for
  each new slot and check the frame.
* Message: "Successfully created N frame(s), M object(s)".

## Verification

`tests/api/test_frame_write_refuses_a_missing_endpoint.py` (8), vg test stack:

* the production shape is refused on create and upsert, and on `/kgframes`;
* the whole-entity create still refuses it;
* an upsert that keeps an edge to a slot the same write deletes is refused, and
  the stored slot survives (the case a pre-write check misses);
* a slot sent without its edge is refused;
* children written under a stored parent via `parent_frame_uri` (create and
  upsert), and an upsert re-sending its slots and edges, still succeed.

The first four tests fail on the previous code. `tests/unit/test_frame_reachability_rules.py`
(7) covers the request analysis. The full API suite passes against the rebuilt
stack.

## Not covered

* The whole-entity UPDATE path (`validate_entity_graph_structure`) checks
  entity → frame and frame → slot edges against the request, but not
  frame → frame `Edge_hasKGFrame`. Not probed yet.

## Not VitalGraph's

* The client's builder fix and the repair of the 4,704 missing child frames.
  Both are in the client team's issue. The repair is a production data change
  that needs its own authorisation, and it has to come before (or together with)
  the client fix, because a regeneration would otherwise replace the earlier
  generations with their empty read-back.
* The dangling-endpoint WARNING keeps firing until that repair, and should be
  checked again after it.
