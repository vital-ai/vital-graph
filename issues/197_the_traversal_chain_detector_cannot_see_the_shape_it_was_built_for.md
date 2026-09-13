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

## 4. THE GATE MAY NO LONGER HAVE A JOB — measured 2026-09-12

Fifteen tests in `test_traversal_direction_gate.py` fail, and they are not a
regression in the gate. They are the gate being CORRECTLY bypassed.

The test that fails first says so itself:

> `decide` needs a chain AND a measured criterion. If either goes missing — **a
> rewrite that stops producing a chain for this shape** — every direction
> assertion below would pass by never running, which is the failure mode this
> whole suite exists to avoid.

That is exactly what happened, and the rewrite that stopped producing a chain is
the `frame_slot` collapse, which now fires on `sp_graph_skew_2k` because
`issues/195` migrated the fixture. Measured on the gate's own query, same
query, collapse forced off and on:

    collapse OFF (the state the tests were written in)   201,539 buffers  159.9 ms
    collapse ON  (today)                                  53,278 buffers   42.4 ms

**3.8x fewer buffers and 3.8x faster with the gate not firing at all.** The
collapse dominates the thing the gate was choosing between, so `decide` returns
None and every direction assertion has nothing to assert against.

So the question in step 3 below is not hypothetical, and this is its answer so
far: on every shape available in this fixture, the collapse beats hop-wise, and
the gate has no case. Extending the detector to see these shapes would be
building machinery for a choice that no longer matters.

**What the tests should become** is the real question. They are good tests —
the first one caught this precisely — but they assert a mechanism rather than an
outcome. Either they move to a query the collapse CANNOT serve (which is the
same query step 3 needs, so one piece of work answers both), or they are
rewritten to assert the outcome — that this shape is served in ~53k buffers,
however that is achieved.

### 4a. The five `test_traversal_bench` failures are the same class, different cause

Measured the same way, on `test_pinned_depth_2`'s own query:

    collapse ON  (today)      29,011 buffers    18.4 ms   decision None
    collapse OFF (before)  1,853,488 buffers  2,176.5 ms   decision "as-is"

**64x fewer buffers and 118x faster**, which is a larger margin than the gate
tests showed.

But the cause is NOT the collapse, and the "before" column says so: with the
collapse off the decision is already `as-is: depth 1, pinned but no measured
criterion` — flat either way. These benches assert hop-wise and dedup emission
and were getting flat regardless, because **the gate never measured their
criterion**. That predates the collapse and predates the
`issues/195` change (verified by reverting it: identical failures).

So the two sets fail for different reasons and arrive at the same place:

| tests | why no hop-wise | current vs previous |
|---|---|---|
| 7 in `test_traversal_direction_gate` | the collapse removed the chain, so `decide` returns None | 3.8x better |
| 5 in `test_traversal_bench` | the criterion is not measured, so the gate says "as-is" | 118x better |

Every one of the twelve asserts a MECHANISM that no longer runs, while the plan
that replaced it is between 3.8x and 118x better. None of them is a regression.

The unmeasured criterion in the second set is worth its own look: `SCORE` sits
on `?f{n}`, the hop's own frame, which is exactly the shape hop-wise exists for
and exactly what `issues/195` established the gate SHOULD count. That it reads
as unmeasured there is a separate defect from anything recorded here.

## 5. Five tests query a table that was dropped

Separate and simpler. `test_traversal_direction_gate.py` queries
`{space}_frame_entity` directly at four sites, and asserts on it at a fifth:

    line 250   FROM {SKEW.space}_frame_entity fe
    line 276   SELECT count(*) FROM {SKEW.space}_frame_entity fe ...
    line 291   SELECT count(*) FROM {SKEW.space}_frame_entity fe ...
    line 358   assert f"{SKEW.space}_frame_entity" in gen.sql

These fail with `UndefinedTableError: relation "sp_graph_skew_2k_frame_entity"
does not exist` — the table was dropped by `b94484a9` on 2026-09-10 and the
tests were not updated with it. `graph_fixtures.py` line 202 also documents a
row count for it.

Mechanical: the replacement is `frame_slot`, with the role as data rather than
in the column names. Worth doing regardless of how 4 is resolved, since these
five say nothing about the gate — they just error.

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
