# The Traversal Chain Detector Cannot See The Shape It Was Built For

## Status: OPEN, found 2026-09-12 during `issues/195`. The DATA problem there is
## fixed and these three CODE defects are not — they are why a 4x10^11 plan
## regression took a day to find instead of one line.

**Related:** `issues/195` (where these were found), `issues/183` (the
`frame_entity` retirement), `issues/096` / `issues/181` (what the gate can see)

## Context, in one paragraph

`issues/195`: an unfiltered depth-2 `entity -> frame -> entity` walk planned at
19,282,929,239,712 and never returned. The cause was DATA — the perf fixtures
had never been migrated to `frame_slot`, so the collapse could not fire.
Migrating them took the same plan to 47.77. None of what follows was fixed by
that, and all of it is what made the diagnosis slow.

## 1. `_TRAVERSAL_KINDS` names a table that no longer exists

    _TRAVERSAL_KINDS: Dict[str, Tuple[str, str]] = {
        "frame_entity": ("source_entity_uuid", "dest_entity_uuid"),
        "edge":         ("source_node_uuid",   "dest_node_uuid"),
    }

`frame_entity` was retired on 2026-09-10 in `b94484a9` and NOTHING produces that
kind any more. Half this map is dead, and it is the half whose columns actually
express a hop — a source entity and a destination entity in one row. The
replacement, `frame_slot`, was never added.

**Do not just add `frame_slot` to the map.** Its columns are
`(frame_uuid, slot_uuid, role_uuid, entity_uuid)`, so the two rows of one hop
share `frame_uuid` — the same shape as the `edge` rows below, which the model
already cannot link. Adding the entry would look like a fix and change nothing.

## 2. The linking model cannot express this traversal

`_chains_in_bgp` joins two hops when THE SAME VARIABLE is one hop's DESTINATION
and the next one's SOURCE. Dumped from the real depth-2 plan before the
migration:

    mv0  src(source_node_uuid)=f1  dest(dest_node_uuid)=ss1
    mv1  src(source_node_uuid)=f1  dest(dest_node_uuid)=ds1
    mv2  src(source_node_uuid)=f2  dest(dest_node_uuid)=ss2
    mv3  src(source_node_uuid)=f2  dest(dest_node_uuid)=ds2

No variable is ever both. Destinations are `ss*`/`ds*`, sources are `f1`/`f2`,
so `successor` is empty and every hop stays a singleton — at EVERY depth:

    depth 1   no multi-hop chain found (2 single hops)
    depth 2   no multi-hop chain found (4 single hops)
    depth 3   no multi-hop chain found (6 single hops)

That is what `frame_hop` writes. One hop is:

    ?seN <hasEdgeSource> ?fN .  ?seN <hasEdgeDestination> ?ssN .
    ?deN <hasEdgeSource> ?fN .  ?deN <hasEdgeDestination> ?dsN .
    ?ssN <hasEntitySlotValue> ?e{N-1} .   ?dsN <hasEntitySlotValue> ?eN .

Both edges point OUT of the frame, so consecutive hops share an INTERMEDIATE
(the frame) instead of chaining destination-to-source. The hop-to-hop
connection runs through `?e1` at `hasEntitySlotValue` — a QUAD, not a column
`_TRAVERSAL_KINDS` models at all.

So the detector has never linked a walk on `sp_graph_synth_10k`, the fixture
built to exercise it. After the migration it reports **0 hops**, because the
collapse removes the edge tables from the plan — it is bypassed, not repaired.

The fix is a MODEL change: a shared-intermediate case, not another table entry.

## 3. `frame_slot_rewrite` records neither a fire nor a decline

The decision record for the failing query, in full:

    fired    = ['frame_type_absorbable']
    declined = {'slot_type_tautology': 'constraint excludes rows, or unknown'}

`frame_slot_rewrite` appears in neither. Its absence was worth a factor of
4x10^11 on that query and the decision record said nothing about it.

This is the third instance of one shape in this repository — `issues/081` (a
gate disabled by an absent value), `issues/188` (a metric with no rule), and
`issues/167` (an allow-list read as a block-list). **A silent decline reads
exactly like a satisfied check.** `describe_chains` documents the principle for
itself: "a detector that finds nothing must say so where it can be seen." The
rewrite next to it does not.

Had it logged `declined: frame_slot table absent`, `issues/195` would have been
a one-line diagnosis.

## Ordered fix

1. **Record the decline.** Smallest, and it is the one that would have saved the
   day. `ensure_frame_slot_table` already returns false for a reason it knows —
   absent table, or present with no rows — so pass that through to the decision
   record.
2. **Remove `frame_entity` from `_TRAVERSAL_KINDS`**, leaving `edge` alone. It
   is dead weight that reads as coverage.
3. **Then decide whether the detector should model a shared intermediate at
   all.** With the collapse working the detector sees 0 hops on this shape, so
   it may be that the collapse is the right answer and the detector should
   document that it does not apply here — rather than being extended to a case
   nothing needs. That is a design question, and it should be answered with a
   query that the collapse CANNOT serve.
