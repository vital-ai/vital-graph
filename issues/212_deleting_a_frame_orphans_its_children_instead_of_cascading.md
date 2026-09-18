# Deleting A Frame Orphans Its Children Instead Of Cascading

## Status: CAUSE IDENTIFIED 2026-09-18, cannot recur. The residue came from
## `DELETE /kgframes` BEFORE `55a40b02` (2026-05-03), whose per-frame delete
## removed the frame's own quads and its own slots and never touched
## `Edge_hasKGFrame` — so child frames, their slots and the edges pointing at
## them survived. All 298 dangling rows on production are that one edge type,
## which is what pins it. Post-`55a40b02` the endpoint refuses or cascades.
## What REMAINS is a decision about the existing residue, which needs its own
## authorisation, and detection, which is now in place.

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

## Every live deletion path, audited 2026-09-17

The second filing named the REPLACE path as the likely culprit. That was also
wrong, and for the same reason as the first: a partial read. REPLACE is
complete. Full audit of everything that can delete a frame:

| path | descendants | edges | verdict |
|---|---|---|---|
| `DELETE /kgframes` -> `_delete_frames_by_uris:1530` | refuses, or `collect_all_descendants` | `_delete_frame_from_backend` phase 2: `Edge_hasKGFrame` + `Edge_hasEntityKGFrame` | SAFE |
| entity frames REPLACE `kgentities_endpoint.py:1855` | `collect_all_descendants` | incoming + outgoing `Edge_hasKGFrame`, then `Edge_hasEntityKGFrame` | SAFE |
| `DELETE /kgentities?delete_entity_graph=true` | whole group by `kgGraphURI` | group-wide | SAFE |
| `_delete_frames:298` | none | none | DEAD — unreachable |

**Both frame paths gained descendant collection on 2026-05-03** (`3b512618`,
`55a40b02`). Since that date neither can strand a child frame or an edge, so
the residue predates it or came from outside the API.

**Conclusion: this cannot recur through any live path.** The remaining value of
this issue is the residue itself, the missing detection, and the dead helper —
not a fix to the deletion code, which is correct.

## One latent case, asserted as possible and NOT as occurring

`DELETE /kgentities` defaults to `delete_entity_graph=false`, which deletes
only the entity's own quads. `Edge_hasEntityKGFrame` has the ENTITY as its
SOURCE, so an entity deleted in this mode while it still has frames would leave
that edge with a dangling source — the same shape, one level up.

`test_derived_table_maintenance.py` exempts this path on the reasoning that
"the entity subject carries no edge-source/dest properties and is not a frame",
which is true of the entity NODE and does not address the edge OBJECT that
points at it.

**Production: no evidence.** Every one of the 298 dangling sources there is a
FRAME; entity-sourced dangling edges measure ZERO.

**DEV: CONFIRMED 2026-09-18.** The case is real and reachable, found while
explaining an unrelated phantom grouping URI. One entity-sourced dangling edge
on the dev copy of the main KG space:

    <root>:edge:i  vitaltype             Edge_hasEntityKGFrame
                   hasEdgeSource      -> <root>          (ZERO quads — deleted)
                   hasEdgeDestination -> <root>:frame:nurture_info:0  (intact)

The root was a probe fixture (`urn:<client>:probe:dupframe:<hex>`) written by a
diagnostic script in the REST repo — a sibling of
`test_scripts/_append_frames_behaviour_probe.py`, which builds exactly this
shape and DOES create its root entity. So the entity existed and was removed
while its frame and edge were not, which is the signature of a delete-by-subject
on an entity URI: what `delete_entity_graph=false` does by definition.

This does not change the production picture and it does change the status of
the case above from "possible" to "observed". The maintenance probe added for
this issue reported it — `{'dangling_source': 1, 'dangling_dest': 0}` on that
space — which was also an independent check of the probe against a case nobody
constructed for it.

**The instance itself was removed 2026-09-18**, so this description is now the
only record of it: 14 quads deleted through the SPARQL path (not behind it), so
the edge table synced and the probe went to `{0, 0}`. The quads are backed up
at `/tmp/dupframe_probe_quads_20260918.tsv` — four columns, s/p/o/g — and that
file is temporary. If this case ever needs reproducing, the shape above is the
recipe: create an entity with a frame and an `Edge_hasEntityKGFrame`, then
delete ONLY the entity's own quads.

## A SECOND detection gap, found by the first probe's blind spot

`edge_table_dangling_endpoints` follows arrows, so it needs an arrow to follow.
Delete an edge OBJECT whole — rather than the node at its tail — and nothing
dangles: what it held up is simply unreachable, and the space reports clean.

Found on dev while explaining a space that stayed blocked: 5 slots carrying text
values on 5 intact frames, none reachable from an entity, 3 with nothing
pointing at them at all — on a space the dangling probe had just called clean.

`unreferenced_kg_objects` closes it, on the rule each object breaks: a KGFrame
is reached by `Edge_hasEntityKGFrame` or `Edge_hasKGFrame` and a slot by
`Edge_hasKGSlot`, so one with NEITHER is unreachable by construction. It also
catches the partial-write shape above, where four schedule slots were written
and their parent frame never was.

EXACT for what it asks and an UNDER-COUNT of what you want to know — a frame
whose parent is itself unreachable still has an incoming edge. Full reachability
is the O(graph) walk `issues/151` removed from this loop for costing 216-303 s,
so this is the cheap necessary condition: two anti-joins on an indexed column.
Everything it reports is genuinely unreachable; not everything unreachable is
reported.

## Detection ADDED 2026-09-17

`edge_table_dangling_endpoints` (`sync_edge_table.py`) now runs per space in
the maintenance edge-integrity pass and WARNS, naming both counts separately.
Verified against production: it returns `{'dangling_source': 298,
'dangling_dest': 0}` — the numbers this issue was written from, reproduced by
the probe rather than by hand.

It REPORTS and does not repair or gate, deliberately. Deleting a dangling row
would destroy the only remaining evidence of what was orphaned, and the frames
and slots below it would still be unreachable — a tidier table describing the
same broken graph. Repair is a data decision.

`tests/integration/test_edge_dangling_endpoints_are_detected.py` pins it in
three parts: a control proving a healthy table reports zero, the residue shape
reproduced by deleting a source node's quads, and an assertion that
`edge_table_orphan_rate` still reports 0.0 on that same data — which is the
whole reason a second probe was needed.

## Nothing detected this (the gap that made it invisible)

The residue was found sideways, through a slot-sort shortfall alarm, which is
the part worth fixing. `maintenance_job` has `edge_table_orphan_rate`, but its
orphan is "a row whose defining EDGE is gone" — the quad missing under a row.
The condition here is the opposite and is not probed anywhere: a row whose
SOURCE NODE has no quads.

One query finds it, and it is cheap enough to run per cycle:

    SELECT count(*) FROM {space}_edge e
     WHERE NOT EXISTS (SELECT 1 FROM {space}_rdf_quad q
                        WHERE q.subject_uuid = e.source_node_uuid)

On production that returns 298 of 3,466,543, and zero for the destination form.

## CAUSE IDENTIFIED 2026-09-18 — `DELETE /kgframes` before the cascade landed

I had written, in this document, that the cause "cannot be recovered from the
data". That was wrong. It could not be recovered from the DATA; it was sitting
in the history of the endpoint. The suggestion that the frame-delete endpoint
had simply been used without deleting the whole graph is what found it.

`_delete_frame_from_backend` before `55a40b02` (2026-05-03) issued exactly two
deletes per frame:

    1. DELETE <frame_uri> ?p ?o                     -- the frame's own quads
    2. DELETE ?slot/?edge WHERE ?edge a Edge_hasKGSlot ;
                                hasEdgeSource <frame_uri>   -- its OWN slots

`Edge_hasKGFrame` appears nowhere. Child frames, the edges pointing at them and
everything below them were never touched. The residue is that gap, exactly:

    what the old code deleted        what we observe
    ---------------------------      -----------------------------------------
    the frame's own quads       ->   99 frames with ZERO quads
    its own slots + slot edges  ->   ZERO dangling Edge_hasKGSlot rows
    (nothing else)              ->   298 dangling Edge_hasKGFrame rows
                                     298 intact child frames
                                     828 intact slots — the CHILDREN's, not
                                     the deleted frames'

Confirmed on production: every one of the 298 dangling rows is
`Edge_hasKGFrame` and there are no others. That single fact distinguishes this
explanation from every other one — a delete that missed slots would leave
dangling `Edge_hasKGSlot` rows, and there are none.

It also explains the asymmetry noted below: zero entity-sourced dangling edges,
because this path only ever ran on frames.

**Nobody did anything wrong.** There was no flag to forget — the pre-`55a40b02`
endpoint took no `recursive` parameter and had no cascade for child frames at
all. Any caller deleting a frame that had children produced this. The
capability was missing, not the caller's care.

**It necessarily predates 2026-05-03 and cannot recur.** After that commit the
endpoint either refuses ("Cannot delete frames with children (use
recursive=true to cascade)") or collects all descendants, and
`_delete_frame_from_backend` became a two-phase cascade that includes both edge
types. So the dating question this document could not answer from the data is
answered by the code: the residue is older than the fix, and the fix is what
stopped it.

## RESIDUE REMOVED 2026-09-18

Authorised and executed against production in one transaction, after proving
the subtree self-contained: 2,196 objects (298 frames, 298 `Edge_hasKGFrame`,
800 slot edges, 800 slots) with ZERO referencing subjects outside the set.

    frame_prop_sort              596 rows
    frame_slot                   800
    edge                       1,098
    rdf_quad                  15,074
    entity_slot_sort               0   (the orphans were never in it)

Verified after:

    dangling edge sources       298 -> 0
    absent slots                927 -> 127
                                      99 valueless + 28 edge-less orphans

Backed up first to `/tmp/prod_frame_residue_backup_20260918.csv.gz` — 15,074
rows, CSV with proper quoting, validated by parsing it back and confirming
exactly 2,196 distinct subjects. A TSV dump was taken first and DISCARDED: it
reported 2,197 subjects because a slot value contains a newline, which split a
row. Worth stating, because that file would have looked like a backup.

### A claim in this document was wrong

This issue said the residue "costs nothing today — every read path is
entity-led and cannot reach an orphan". The inventory above disproves it: 596
`frame_prop_sort` rows described these frames. That table serves FRAME listings
sorted by property, which are not entity-scoped, so the orphans were reachable
by a real read path the whole time. Nobody reported seeing them, so the
practical impact was likely nil — but "unreachable" was an assertion about the
read paths I had looked at, stated as though it were about all of them.

### The 28 edge-less slots, removed separately and NOT as debris

Removed on a second authorisation, after the check below changed what they
appeared to be. Recorded in full because the deletion was made with the
disagreement on the record, not resolved by it.

They were described here as orphans of the same family. They were not:

    frames they named                              6
    those frames reachable from an ENTITY       6 / 6
    slots those frames already hold, edged         36
    those frames present in entity_slot_sort    6 / 6

So each was a slot object carrying a TEXT VALUE, naming a live,
entity-reachable frame that is actively served, missing only the
`Edge_hasKGSlot` joining it to that frame. That is a missing-edge anomaly on
live data, not an unreachable subtree — the 800 above hung off frames whose
parents did not exist, and nothing could ever reach them. These sat beside 36
working siblings.

The alternative remedy was to restore the six frames' missing edges, which
would have made the values visible and put the slots into `entity_slot_sort`
where their siblings already are. The decision was to delete; 196 quads went,
with zero rows in `edge`, `frame_slot` or `entity_slot_sort` because they were
in none. Backed up first to
`/tmp/prod_orphan_slots_backup_20260918.csv.gz` — 196 rows, 28 subjects,
validated by re-parsing.

**Why the edges were missing: ANSWERED from the backup.** Not a deletion at
all — a PARTIAL WRITE, which makes these the only finding today that is not in
the delete family.

The slots are named `<...>:frame:generated_message:N:frame:schedule:M:slot:<x>`,
four per group — `ScheduleDays`, `ScheduleTimeStart`, `ScheduleTimeEnd`,
`ScheduleTimezone` — across 7 groups. Their implied parent, the
`:frame:schedule:M` sub-frame, has **no term row at all**.

That is what rules a deletion out. Terms SURVIVE quad deletion: a frame whose
quads were removed an hour earlier still has its term row, checked as a
control. A URI with no term has never appeared in any quad, so it was never
written and therefore never deleted.

The model does create these frames normally — 438 schedule frames in the space
are complete, each with quads, an incoming `Edge_hasKGFrame` and slots hanging
off it. And the anomaly is confined: of 1,752 schedule slots that were written,
**every one** has a parent that was written, now that these 28 are gone.

So seven schedule groups had their four slots written while the parent frame
and its two edges were not. A write that landed in pieces.

`hasFrameGraphURI` is not the discriminator and was a red herring: working
schedule slots point it at the `generated_message` frame too, because it names
the grouping graph rather than the immediate parent.

**No instances remain and none is reproducible from here.** The writer lives in
the REST service, not this repository. What can be said is that the store
accepted a partial graph without complaint, which is the part that belongs to
this codebase — nothing rejected slots whose parent frame was absent, and
nothing detected them afterwards except an upper-bound shortfall probe several
inferences away.

### Final state

    absent slots     927 -> 99, and all 99 are VALUELESS
    dangling edges   298 -> 0, both directions

99 valueless slots is the floor, not a remainder: a slot with a type and no
value derives nothing by design, and `entity_slot_sort_row_shortfall` counts
them because it is an upper bound. There is nothing left to remove.

## What this cost, as a lesson

Three mechanisms were proposed in this document before the right one. The first
two were guesses at WHICH CURRENT code path did it, and both were wrong because
I read part of a function and stopped. The third was a conclusion that the
question was unanswerable, reached by exhausting the DATA and never once
looking at what the endpoint used to do.

The residue is a fossil. The way to date a fossil is to ask what was alive at
the time.

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

1. **Probe for dangling edge endpoints** in the maintenance cycle, per the
   query above. This is the only recommendation that would have caught the
   residue directly; everything else here was found by accident.
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
