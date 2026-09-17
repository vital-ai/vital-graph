# Deleting A Frame Orphans Its Children Instead Of Cascading

## Status: OPEN, found 2026-09-17 on PRODUCTION while explaining the
## `entity_slot_sort` shortfall alarm (`issues/194`). The residue is real,
## contained, and currently unread; the code path that produces its exact shape
## is identified, though which caller actually ran is not provable from the data.

**Related:** `issues/194` (the alarm this surfaced under — NOT a defect, see
"Why this was mistaken for a derivation bug"), `issues/091` (grouping URIs that
lost their self-link: a different orphaning, same family)

## What is on production

Measured read-only on the main production space, 2026-09-17:

    edge rows total                                  3,466,543
    edges with a DANGLING SOURCE (node has no quads)        298
    edges with a dangling DEST                                0
    distinct dangling source nodes                           99

The 298 are not scattered. They are one structure:

    [ 99 parent frames — ZERO quads; they do not exist ]
        --Edge_hasKGSlot/Edge_hasKGFrame-->
            [ 298 child frames — intact ]
                --Edge_hasKGSlot-->
                    [ 828 slots carrying VALUES — intact ]

The 298 survivors are ordinary, complete objects:

    vital-core#vitaltype        haley-ai-kg#KGFrame
    haley-ai-kg#hasKGFrameType  urn:<client>:kg:frame:GeneratedLinkFrame
    haley-ai-kg#hasKGGraphURI   urn:<client>:campaign:cer:nurture:...
    haley-ai-kg#hasFrameSequence 0

Nothing points AT the 99 — zero dangling destinations across the whole edge
table means no edge has them as a target either. They are referenced ONLY as
`source_node_uuid` on those 298 rows. They were deleted; everything below them
was not.

## CORRECTION 2026-09-17: the first mechanism named here was wrong

This issue was filed naming `kgframes_endpoint.py:298` `_delete_frames` — which
comments "Delete frame and its associated slots" and calls `delete_object`,
removing only quads whose SUBJECT is the URI. That produces exactly this shape,
so it looked conclusive. It is not the cause, because **it is dead code**:
`_delete_frames` is called only by `_delete_entities` (line 373, "for test
compatibility"), and NOTHING calls `_delete_entities` — not a route, not a test.
The comment is still wrong and the helper is still worth deleting, but neither
can strand anything.

**The dedicated frame-delete route is protected, and has been since
2026-05-03** (`55a40b02`). `_delete_frames_by_uris` (line 1530) calls
`find_child_frames` for every URI and then either REFUSES —

    "Cannot delete frames with children (use recursive=true to cascade)"

— or, with `recursive=true`, collects all descendants first. The per-frame
delete beneath it (`_delete_frame_from_backend`, line 2690) is a complete
cascade in two phases: the frame graph (frame, slots, slot edges), then every
edge REFERENCING the frame, `Edge_hasKGFrame` and `Edge_hasEntityKGFrame`
included. So the recommendation this issue originally made — "make frame
deletion cascade, or refuse" — was already implemented before the issue existed.

## What the residue actually tells us

Two facts constrain the cause:

**It is not a stale edge table.** All 298 dangling `_edge` rows still have their
edge OBJECT present in the quads. The table faithfully mirrors data that is
really there; nothing here is a sync gap. (Worth stating because an edge table
on this space HAS shipped ~25% incomplete before.)

**Only the 99 frame nodes' own triples were removed.** Their outgoing edges,
their child frames and those frames' slots all survive untouched. That is the
signature of a delete-by-subject applied to the frame URI alone.

## A live path that produces this shape

`kgentities_endpoint.py:1898`, the REPLACE path, deletes a frame graph with two
SPARQL updates per URI:

    1. DELETE every subject where ?s haley:hasFrameGraphURI <uri>
    2. DELETE <uri>'s own triples

Step 1 is keyed on the deleted frame's OWN URI. The 298 survivors carry
`hasFrameGraphURI` of a CAMPAIGN grouping URI instead
(`urn:<client>:campaign:cer:nurture:...`), so step 1 never matched them, and
step 2 removed only the parent. Descendants grouped under a different
`hasFrameGraphURI` than the frame being deleted are exactly what survives here.

**Still not proven.** Any delete-by-subject on a frame URI — this path, the dead
helper before it died, a direct SPARQL update, a migration — leaves identical
residue, and nothing in the data records which ran. What has changed is that
the dedicated route is ruled OUT, and this one is ruled IN as capable.

## Why this was mistaken for a derivation bug

This was found because a deploy check read the `entity_slot_sort` shortfall as
missing rows. It is not: the 828 orphaned slots are CORRECTLY absent from
`entity_slot_sort`, because that table is derived by walking DOWN from an
entity and these are reachable from none. The derivation is right; the data is
wrong. Full accounting of the 927 absent slots on that space:

     99  valueless — no value to derive
    800  on frames orphaned by this defect
     28  slots whose own edge is gone, same cause
      0  REAL derivation gap

The stable count across resyncs — read as evidence of a broken rebuild — is the
opposite: a deterministic derivation excluding the same unreachable rows every
time.

## What it costs today

Very little, which is why this is OPEN rather than urgent.

* **Reads do not return them.** Every entity-led path — the listing, the fast
  paths, `slot_projection` — starts from entities and cannot reach an orphan.
* **It inflates the `issues/194` alarm**, which is how it was found, and will
  keep doing so until either the residue is removed or the alarm subtracts
  unreachable slots as well as valueless ones.
* **The rows are storage that nothing can read**, 0.0086% of the edge table.

The real cost is future: the orphans are indistinguishable from live data by
type or graph URI, so anything that ever walks frames WITHOUT starting from an
entity — an export, a migration, a grouping-URI read — will pick them up.
`issues/091` is what that looks like when it happens.

## What to do

1. **Audit the REPLACE path** (`kgentities_endpoint.py:1898`). Deleting a frame
   graph by `hasFrameGraphURI` only reaches descendants that share the deleted
   frame's grouping URI, and these did not. The dedicated route's
   `find_child_frames` / `_delete_frame_from_backend` pair already solves this
   correctly and is the thing to reuse.
2. **Delete the dead helper** `_delete_frames` / `_delete_entities`
   (`kgframes_endpoint.py:298`, `:373`). Unreachable, and its comment claims a
   cascade it does not perform — the next person to read it will believe the
   comment, as this issue initially did.
3. **Decide about the existing 298 + 828 + 99.** Removing them is a data
   change on production and needs its own authorisation — do not fold it into
   a code fix.
4. **Consider teaching the `issues/194` alarm about unreachability**, so a
   legitimately-absent slot stops being reported as a suspected gap. The
   arithmetic there subtracts only valueless slots and says so in its own
   comment.

A reusable classifier for the absent-slot accounting is at
`test_scripts/debug/slot_absence_classify.sql` (untracked; substitute the
space). On the dev copy it returns 10 / 10 / 0 / 0 with no orphans.
