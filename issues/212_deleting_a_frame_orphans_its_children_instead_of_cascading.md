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

## The mechanism

`kgframes_endpoint.py:298` `_delete_frames` says, in its own comment:

    # Delete frame and its associated slots
    result = await backend_adapter.delete_object(space_id, graph_id, frame_uri)

It does not delete associated slots. `delete_objects`
(`endpoint/impl/objects_impl.py:76`) resolves `get_existing_quads_for_uris` —
quads whose SUBJECT is the URI — and removes exactly those. Child frames, slots
and the edge rows referencing the deleted node all survive, which is precisely
the shape above.

The same behaviour is already recorded elsewhere as deliberate, for a DIFFERENT
subject: `test_derived_table_maintenance.py` exempts the entity path because it
"deletes ONLY quads whose subject IS the entity ... The entity subject carries
no edge-source/dest properties and is not a frame, so no edge, frame_slot or
slot-sort row can describe it." That reasoning is sound for an ENTITY and does
not transfer to a FRAME: a frame IS an edge source, and deleting one strands
whatever hung from it.

Cascade machinery exists and this path does not use it —
`KGSlotDeleteProcessor` is imported in the same file and driven at line 473 for
slot deletion.

**Not proven:** that this endpoint deleted these 99. The residue matches its
shape exactly, but any caller of `delete_object` on a frame URI produces the
same thing, and nothing in the data records which ran.

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

1. **Make frame deletion cascade**, or make it refuse a frame that still has
   children. Either is defensible; silently orphaning is not.
2. **Decide about the existing 298 + 828 + 99.** Removing them is a data
   change on production and needs its own authorisation — do not fold it into
   a code fix.
3. **Consider teaching the `issues/194` alarm about unreachability**, so a
   legitimately-absent slot stops being reported as a suspected gap. The
   arithmetic there subtracts only valueless slots and says so in its own
   comment.

A reusable classifier for the absent-slot accounting is at
`test_scripts/debug/slot_absence_classify.sql` (untracked; substitute the
space). On the dev copy it returns 10 / 10 / 0 / 0 with no orphans.
