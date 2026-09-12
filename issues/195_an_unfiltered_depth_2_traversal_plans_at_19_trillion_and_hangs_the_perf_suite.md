# An Unfiltered Depth-2 Traversal Plans At 19 Trillion And Hangs The Perf Suite

## Status: ROOT CAUSE CONFIRMED AND CLEARED ON THE TEST STACK 2026-09-12. The
## perf fixtures had no `{space}_frame_slot` table, so the collapse could not
## fire and an unfiltered depth-2 walk planned at 19 trillion. Migrating the
## fixtures took the same plan to **47.77** and the hanging bench to **1.54 s**.
## Still open: the CODE defects the investigation exposed (see "What is still
## wrong in the code").

**Related:** `issues/188` (blocked by this), `issues/190` (blocked by this),
`issues/096` / `issues/181` (the traversal gate and what it can see),
`issues/151` (hop-wise vs flat emission)

## The defect

`tests/performance/test_graph_traversal_fixture.py::test_open_frame_traversal_matches_the_manifest[2]`
does not finish. Observed twice: cancelled after **24m41s** the first time and
still running the second. It is an `entity -> frame -> entity` walk at depth 2
with NO criterion, over four sample starts, on `sp_graph_synth_10k` — the
fixture named `SMALL`, ten thousand entities.

The plan is the whole story. Same query, same fixture, depth 1 against depth 2:

| depth | estimated cost | plan lines | nested loops |
|---|---:|---:|---:|
| 1 | 741,337 | 42 | 7 |
| 2 | **19,282,929,239,712** | 77 | 12 |

**Twenty-six million times the cost for one more hop.** That is not a slow
query, it is an unrunnable plan that the suite waits on indefinitely.

The generated SQL grows modestly — 9,103 to 12,075 characters, 8 to 15 joins —
so this is a PLANNING collapse, not a code-generation explosion.

## PROVED: the fixtures were never migrated

`b94484a9` retired `frame_entity` and dropped its tables.
`scripts/migrate_frame_slot_table.py` creates the replacement for existing
spaces — and it had been run for **147 of 155** spaces. Every one of the 13 it
missed is a PERFORMANCE FIXTURE:

    space_lead_dataset_test  sp_graph_forms_20k   sp_graph_skew_2k
    sp_graph_synth_100k      sp_graph_synth_10k   sp_kg_rel
    sp_kg_types              sp_lead_dup          sp_lead_synth_100k
    sp_lead_synth_10k        sp_lead_types        sp_sql_lead_dataset
    wordnet_frames

With no table, `ensure_frame_slot_table` reports it absent, the collapse
declines, and the entity->frame->entity hop stays as raw edge rows — which is
the shape the chain detector cannot link.

Migrating `sp_graph_synth_10k` alone (91,286 rows, 3.9 s) settles it:

| depth | before | after |
|---|---:|---:|
| 1 | 741,337 | **30.25** |
| 2 | **19,282,929,239,712** | **47.77** |

Plan lines 77 -> 35, nested loops 12 -> 7, sequential scans 1 -> 0. The bench
that had run 24m41s without finishing now passes all three depths in **1.54 s**.

### The migration's own safety claim is wrong for this shape

Its docstring says:

> A space that is NOT migrated keeps working: `ensure_frame_slot_table` reports
> the table absent, the rewrite declines, and queries fall back to the quad
> joins — correct, just without the collapse.

Correct, yes. "Just without the collapse" is the part that does not hold: for an
unfiltered multi-hop walk the fallback is not slower, it is **4x10^11 times more
expensive** and never returns. A migration that is optional for correctness can
still be mandatory for usability, and nothing said so.

### All 13 are migrated now, except one that CANNOT be

`space_lead_dataset_test` fails: its generated index identifiers exceed
PostgreSQL's 63-byte limit. The migration created the TABLE and then failed on
the indexes, leaving it with 0 rows and 1 index where a healthy space has 7.
That is safe — `ensure_frame_slot_table` requires rows, so the rewrite still
declines — but that space can never have the collapse while its `space_id` is
that long, and it is a gated fixture. Worth its own issue.

## What is still wrong in the code

Clearing the data does not fix what the investigation exposed, and all of it
survives:

1. **`_TRAVERSAL_KINDS` names a retired table.** `frame_entity` is still in it;
   nothing produces that kind. Its replacement `frame_slot` is not there.
2. **The chain detector cannot link this shape even in principle.** Its rule is
   "one hop's DESTINATION variable is the next one's SOURCE", and `frame_hop`
   points both edges OUT of the frame, so hops share a source. After the
   migration the detector reports **0 hops** — the collapse removed the edge
   tables entirely — so it is bypassed rather than repaired.
3. **`frame_slot_rewrite` records neither a fire nor a decline.** A rewrite
   whose absence costs 4x10^11 is invisible in the decision record. Had it
   declined audibly, this would have been a one-line diagnosis instead of a
   day.

## ROOT CAUSE, traced 2026-09-12

The detector never links ANY of these hops, at any depth. With the chain logger
turned up:

    depth 1   traversal: no multi-hop chain found (2 single hop(s))
    depth 2   traversal: no multi-hop chain found (4 single hop(s))
    depth 3   traversal: no multi-hop chain found (6 single hop(s))

Two hops per depth are FOUND and none are ever JOINED. So this is not a
depth-2 problem — the chain machinery has never linked a walk on
`sp_graph_synth_10k`, the fixture built to exercise it. Depth 1 merely survives
being planned flat.

### Why the links do not join

`_chains_in_bgp` joins two hops when THE SAME VARIABLE is one hop's destination
and the next one's source. Dumping what it actually sees at depth 2:

    mv0  src(source_node_uuid)=f1  dest(dest_node_uuid)=ss1
    mv1  src(source_node_uuid)=f1  dest(dest_node_uuid)=ds1
    mv2  src(source_node_uuid)=f2  dest(dest_node_uuid)=ss2
    mv3  src(source_node_uuid)=f2  dest(dest_node_uuid)=ds2

**No variable is ever both a destination and a source.** Destinations are
`ss*`/`ds*`; sources are `f1`/`f2`. The `successor` map is therefore always
empty and every hop stays a singleton.

That is the shape `frame_hop` actually writes. One entity->frame->entity hop is:

    ?seN <hasEdgeSource> ?fN .  ?seN <hasEdgeDestination> ?ssN .
    ?deN <hasEdgeSource> ?fN .  ?deN <hasEdgeDestination> ?dsN .
    ?ssN <hasEntitySlotValue> ?e{N-1} .   ?dsN <hasEntitySlotValue> ?eN .

Both edges point OUT of the frame, so they share a SOURCE rather than chaining.
The hop-to-hop connection runs through `?e1` at `hasEntitySlotValue` — a QUAD,
not an edge column, and not something `_TRAVERSAL_KINDS` models.

### And half the detector's vocabulary is dead

    _TRAVERSAL_KINDS = {
        "frame_entity": ("source_entity_uuid", "dest_entity_uuid"),
        "edge":         ("source_node_uuid",   "dest_node_uuid"),
    }

`frame_entity` was RETIRED on 2026-09-10 in `b94484a9`, and nothing produces
that kind any more. It is the entry that could collapse an
entity->frame->entity hop into ONE row with a real source and destination — the
only one whose columns match the detector's dest-to-source model. Its
replacement, `frame_slot`, was never added here.

So the detector is left with `edge`, which for this shape produces the
share-a-source pattern above and cannot chain.

### A third gap, found on the way

`frame_slot_rewrite` — the collapse that would put a chainable table in the plan
— appears in the decision record **neither as fired nor as declined**. A rewrite
that does neither is invisible, which is the exact failure mode `describe_chains`
documents for itself ("a detector that finds nothing must say so where it can be
seen").

## Ordered next steps

1. Add `frame_slot` to `_TRAVERSAL_KINDS`, or establish why the dest-to-source
   model cannot express it. **Do not add it blindly**: its columns are
   `(frame_uuid, slot_uuid, role_uuid, entity_uuid)`, so two rows of one hop
   share `frame_uuid` — the same share-a-source shape, which suggests the MODEL
   needs a shared-intermediate case and not just another entry.
2. Find out why `frame_slot_rewrite` neither fires nor declines here.
3. Then re-check whether the 19-trillion plan survives. **The before/after has
   not been run**: the baselines predate `b94484a9`, so it is plausible this was
   planned differently before the retirement, and that is a check rather than a
   claim.

## The proximate cause: the chain detector does not see the second hop

`traversal_decision` reports the SAME decision for both depths:

    depth 1   Decision(hop-wise: depth 1, driving from tail, criterion admits 0%, drive from tail)
    depth 2   Decision(hop-wise: depth 1, driving from tail, criterion admits 0%, drive from tail)

It says **depth 1 for the depth-2 query.** So the chain it found is one hop
long, the decision it made applies to one hop, and the second hop is emitted by
the general path — which at depth 2 is where the trillions come from.

`criterion admits 0%` is the other half. These walks have no criterion at all,
and `traversal_decision`'s own docstring records what that costs: "Without a
criterion the walk fans out unchecked ... an unfiltered depth-3 walk on
`wordnet_frames` measured 865 ms flat against 2,044 ms hop-wise." That
measurement said flat was the better arm for an unfiltered walk. **On this
fixture at this depth, flat is not 865 ms — it is unrunnable**, so the
conclusion drawn from `wordnet_frames` does not generalise to
`sp_graph_synth_10k`.

`emit_dedup_chain` is documented as handling the unfiltered case "far better
than either arm" and as deliberately ungated. It evidently does not take this
shape; establishing why is the next step.

## Why it matters beyond the suite

1. **It blocks the perf work.** `188` requires 3-4 samples on an unmodified
   tree; the first sample reached 23% in 25 minutes and stopped here. `190`
   requires a promotable run. Neither is possible while this hangs.
2. **It is a correctness test, in the performance suite.** The assertion is
   `got == expected` against a manifest. It is not measuring speed, so the
   pathology it exposes has no threshold to breach — it just never returns.
3. **A 10k fixture is not a scale excuse.** Whatever this is, it is not "the
   fixture is too big".

## An operational hazard found alongside it

**Killing pytest does not cancel the query.** After the first run was killed,
the backend kept executing for a further 24 minutes and was still running when
the next run started — so the second run competed with the first, on the same
box, measuring nothing useful. Cancel explicitly:

```sql
SELECT pg_cancel_backend(pid) FROM pg_stat_activity
 WHERE state = 'active' AND query LIKE 'SELECT DISTINCT%';
```

Worth remembering for any perf work: an abandoned benchmark can go on consuming
the machine that the next measurement is taken on.

## What to do next

1. **Find out why `traversal_chain` reports depth 1 for a depth-2 query.** That
   is the specific, testable defect. Everything else here is a consequence.
2. **Ask why `emit_dedup_chain` declines this shape**, since it is the arm
   documented as handling unfiltered walks.
3. **Do not "fix" this by giving the bench a criterion.** The unfiltered walk is
   the shape under test, and a criterion would make the bench pass while leaving
   the plan collapse in place for any caller who writes the same query.
4. Until then the suite needs a way to run without it — a timeout per bench, or
   a marker — or every perf run costs a day. That is `issues/192`/`193`
   territory and should not be solved by deleting the test.
