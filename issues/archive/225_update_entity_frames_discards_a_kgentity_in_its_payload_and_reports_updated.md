# `update_entity_frames` Discards A `KGEntity` In Its Payload And Reports `updated`

## Status: FIXED 2026-09-21. Fix 1 shipped; **fix 2 REJECTED BY DESIGN** — see
## below. Reproduced before fixing, and the fix landed in BOTH copies.

### Fix 2 is not deferred, it is refused

Updating a frame must not update the entity node. `update_entity_frames` is
FRAME-SCOPED by definition, and honouring a `KGEntity` in its payload would
make the blast radius of the call depend on what the caller happened to put in
the list — the same call touching one subject or two, decided by payload
contents rather than by which endpoint was called.

That is worse than the silence this issue started as. So the entity node stays
unwritten, and the fix is that the API now SAYS so instead of pretending.

The message names the right door:

    NOTE: KGEntity in the payload was NOT written -- update_entity_frames
    writes frames, slots and edges only. Change entity properties with the
    entity update endpoint

**The reporter's underlying need is still real and is NOT met by this issue.**
They want an entity property and a frame slot changed atomically, to keep a
denormalised projection in step without a reconciler. That is a request for a
write whose SCOPE IS BOTH, stated up front — not for a frame write that
silently grows when handed an extra object. If it is wanted, it belongs in its
own endpoint or an explicit flag, filed separately, and designed knowing what
`execute_atomic_frame_update` already provides (below).

### What the storage layer already does, recorded so nobody re-derives it

Relevant if that separate request is ever taken up: the write is ALREADY
subject-level and already transactional, and already locks the entity.

    subject_uris = list({str(obj.URI) for obj in all_objects ...})
    await backend_adapter.update_subjects_graph(
        space_id, graph_id, subject_uris, insert_quads,
        lock_uris=[entity_uri] if entity_uri else None)

Subject-level delete + insert in one transaction, taking the ENTITY key as its
lock (`issues/174`: entity upsert and entity-graph delete hold that key, so a
frame write must take the same one). So the storage layer never needed changing
for this — only the question of which subjects an endpoint is ALLOWED to touch,
which is the scope question answered above.

One trap for that future design: the delete is per subject, WHOLE subject. An
endpoint accepting an entity node would replace all of its quads, so a caller
sending a partial node would silently lose every property it omitted — this
issue's own failure mode in a new place.

### What changed

`categorize_frame_objects` now has an `else` arm collecting anything that is
not a frame, slot or edge into `FrameObjectCategories.unhandled`. That is
carried to `CreateFrameResult.unhandled_types` and named in the message the
caller reads:

    Successfully updated 1 frame graphs. NOTE: KGEntity in the payload was NOT
    written -- update_entity_frames writes frames, slots and edges only. Change
    entity properties with the entity update endpoint

Plus a WARNING log naming the types. Collected rather than raised: the defect
is the SILENCE, and rejecting outright would break any caller that has been
passing extra objects harmlessly.

### THERE WERE TWO COPIES, and fixing one would have been the same mistake

`kgframe_create_impl.py` defines its OWN `FrameObjectCategories`,
`CreateFrameResult` and `categorize_frame_objects` — duplicates of the ones in
`kgentity_frame_create_impl.py`, with the identical three branches and the
identical missing `else`. It is reachable from `/kgframes`
(`kgframes_endpoint.py:2340`).

Fixing only the `/kgqueries` copy would have left one surface reporting the
discard and the other silent — the asymmetry `can_serve_filter`'s own comment
warns about ("an asymmetry between two gates over one table is how the last
four defects here happened"), and the same mistake made earlier the same day in
`resync_all.py`, where three of four import paths were converted and the one a
restore actually uses was not. Both copies are fixed; the test covers both.

### Reproduced first, not reasoned about

    payload in : 4 objects -> ['KGEntity', 'KGFrame', 'Edge_hasKGSlot', 'KGTextSlot']
    payload out: 3 objects -> ['KGFrame', 'KGTextSlot', 'Edge_hasKGSlot']
    DROPPED: ['KGEntity']

`tests/unit/test_frame_update_does_not_discard_a_payload_silently.py`, 9 cells,
failing before and passing after. It pins the SILENCE, not the discarding — and
asserts the entity is still not written, so implementing fix 2 has to come here
and change that line deliberately rather than silently inverting what the test
claims. The control cell (an ordinary payload reports NOTHING unhandled) is what
stops the first cell passing against an implementation that flags everything.

### Original report

**Related:** `issues/223` (the other half of the same report, already FIXED in
`0dd38a48` before it was received — see "What this is not" below)

## The defect

`update_entity_frames(entity_uri=…, objects=[…])` takes the entity URI as an
ADDRESS. A caller who also puts the `KGEntity` itself in `objects` — the
natural way to change an entity property and a frame slot in one write — has
the entity node silently dropped, and gets `status: "updated"`.

Measured by the reporter on a throwaway entity:

    create   NurtureStatus slot   = "enrolled"
             kGActionTypeList     = ["…:status:enrolled"]

    update_entity_frames(objects=[entity(kGActionTypeList=[…:message_ready]),
                                  frame, edge, slot(NurtureStatus="message_ready")])

    -> is_success = True, status = "updated"
       slot      -> 'message_ready'                   APPLIED
       property  -> '…:status:enrolled'               SILENTLY DROPPED

No error, no warning, no partial-success status.

## Where it is dropped — three branches, and `KGEntity` is not one of them

The reporter located the passthrough at
`kgentity_frame_update_impl.py:132-139`, which is correct: a non-`KGFrame`
object survives validation deliberately, because slots and edges must.

    for obj in frame_objects:
        if isinstance(obj, KGFrame):
            ...ownership check...
            validated_frame_objects.append(obj)
        else:
            validated_frame_objects.append(obj)      # non-frames survive HERE

But that is where it is KEPT. It is discarded one layer down, in
`kgentity_frame_create_impl.py:284`, `_categorize_objects`:

    for obj in graph_objects:
        if isinstance(obj, VITAL_Edge):   edge_objects.append(obj)
        elif isinstance(obj, KGFrame):    frame_objects.append(obj)
        elif isinstance(obj, KGSlot):     slot_objects.append(obj)
        # no else — a KGEntity matches nothing and joins no list

`FrameObjectCategories` carries exactly those three lists, so an object of any
other type ceases to exist at this line. There is no `else`, so nothing counts
it, logs it, or fails on it.

**It is mutated before it is dropped**, which is worth knowing when reading the
code: `assign_grouping_uris` runs FIRST and sets `obj.kGGraphURI = entity_uri`
on every object including this one, before the type dispatch below it. So the
entity node is prepared for a write that then never happens.

That shape — passed through validation, prepared, then dropped by a
classification that has no default arm — is why this reads as a GAP rather than
a deliberate contract, and why it looked supported from the call site.

## Why `status: "updated"` is the part that matters

Defensible in isolation: the FRAMES it was given were updated. But it is the
only signal the caller gets, and it does not distinguish "applied everything"
from "applied the part I recognised". A caller cannot detect the loss from the
response — they have to read back the property and compare.

This is the same class as `issues/171`: a success status on work that was
partly not done, where the failure is invisible at the call site.

## Fix — two, and the cheap one stands alone

1. **MINIMUM — stop reporting `updated` for a payload that was partly
   discarded.** Give `_categorize_objects` an `else` arm: either reject the
   unexpected type, or count it and report what was applied. This is the
   silent-failure half and is worth having on its own, independent of 2.
2. **BETTER — honour the entity node**, so an entity property and a frame slot
   can be changed in ONE atomic write.

Do 1 even if 2 is not scheduled. An explicit rejection is a worse API than
honouring the node and a much better one than silent loss.

## Why the reporter needs 2 specifically

They are adding a denormalised entity property that projects a frame slot,
because filtering status and date together costs **8–50 s** as a frame join and
**~1.4 s** as two entity properties. The projection must stay in step with the
slot, and the two writers that move status most often use
`update_entity_frames` — so today they cannot write both in one call. That
forces a second post-commit write, a strict slot-then-property ordering, and a
reconciler for the window between them.

They considered and REJECTED switching those writers to whole-entity
`update_entities`: it turns every status transition into a read-modify-write
over the whole entity graph, which is a lost-update race against concurrent
message appends. Trading a detectable drift for a silent data-loss race is a
bad trade. That reasoning is sound and is the argument for 2 — it lets them
delete the reconciler.

## What this is not

The same report carried a second defect — an entity query with a criterion on a
REPEATED frame returning duplicate URIs and a frame-count `total_count`
(320,628 against an 84,519-entity population; 26 distinct URIs on a page of
100). **That is `issues/223`, and it was already fixed in `0dd38a48`** hours
before the report was received, so their "checked against `issues/`, not filed"
was accurate when they checked.

Verified rather than assumed — their reproduction shape, run against current
code on a copy of the same production space:

    can_serve_filter                        True     (their shape IS the fast path)
    entity population (distinct)          87,110
    total_count                           83,183     (they measured 320,628)
    page-1 rows / distinct               100 / 100   (they measured 26 / 100)

    assert total_count <= population       PASS
    assert page URIs distinct              PASS

No action needed there beyond telling them to retest on a build containing
`0dd38a48`.
