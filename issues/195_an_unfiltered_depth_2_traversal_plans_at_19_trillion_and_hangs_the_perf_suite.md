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

## THE SUITE STILL CANNOT COMPLETE — it was never one bench

A full run after the migration reached **185/307 in 35 minutes** and was stopped
on another query that had been executing for **10m56s** with three parallel
workers. Better than 83/307 in 25 minutes, and still not a suite anyone can run
four times.

The next blocker is `test_nested_frame_traversal`, on the same
`sp_graph_synth_10k`. Planning every nested-criterion shape it uses, EXPLAIN
only, no execution:

| criterion | depth 1 | depth 2 | depth 3 |
|---|---:|---:|---:|
| `has_nested` (structure only) | 46.53 | 103.99 | 119.97 |
| `nested_category_in_alpha_beta` | 893,200 | 4,323,546 | **4.19 x 10^21** |
| `nested_score_gte_50` | 1,083,089 | 18,673,383 | **2.06 x 10^13** |

Four SEXTILLION for the first — worse than the 19 trillion this issue was
raised for.

**The pattern is the criterion, not the depth.** `has_nested` asks only about
structure and is trivial at every depth. The two that carry a FILTER on a
nested value — `category IN ("alpha","beta")`, `score >= 50` — are already a
million at depth 1 and astronomical at depth 3. `traversal_decision` reports
`criterion admits 0%` on these, which is the gate looking at a criterion it
cannot price and declining to act.

So the original diagnosis was too narrow. The unmigrated fixtures were real and
fixing them was worth it, but **a family of criterion-bearing traversal shapes
plans at 10^13 to 10^21**, and any one of them stalls a run. `issues/188`'s
sampling and `issues/190`'s re-promotion stay blocked until that family is
either fixed or excluded from the suite.

This belongs with `issues/197` (the detector cannot link these shapes) rather
than here: this issue is about the data gap, which is closed.

## THE CODE FIX WAS WRONG AND IS REVERTED (2026-09-13)

`4614b3f5` claimed to make the gate count only criteria the hop can use. It did
not. `chain_criterion_predicates` returned `uuid.UUID` objects while
`range_stats` / `text_stats` / `in_stats` key their predicates by STRING, so
`p_uuid not in _usable` was true for EVERY predicate and every criterion was
dropped. Hop-wise emission was globally disabled, and the result reported here
— 7.85e15 down to 122 — was that side effect rather than the restriction
working.

Corrected to compare like with like, the filter is actively HARMFUL:

    filter off             d2   458,118,635   d3   1,468,974,130
    filter on, corrected   d2 5,620,525,005,640,507
                           d3 1,328,856,705,654,390

The nested criterion it was written to exclude reads as ON-CHAIN, so the
restriction never applied to it; where it does change a decision it chooses
worse. Reverted in `c80fff87`.

**So the nested-criterion pathology is UNSOLVED** and the benches will stall the
suite as before.

### What the accident is evidence for — AND A FRAMING ERROR, corrected

I first wrote that this raised the question "does hop-wise emission still earn
its keep now that `frame_slot` exists?" **That question is not supported by any
of the evidence here, and the reason is a distinction I had collapsed.**

The `frame_slot` rewrite applies ONLY to frame-slot shaped traversals. It has
nothing to do with general traversal over the edge table. Verified directly on
the same fixture:

    frame_hop     frame_slot=True   edge=False   decision=None
    relation_hop  frame_slot=False  edge=True    decision=hop-wise, depth 2

So on `frame_hop` the collapse takes the query and **the gate never runs at
all** — `decide` returns None. Every measurement I cited for that question was a
`frame_hop` shape: the nested family, the `CRITERIA` family, the `issues/197`
direction tests, the `issues/197` bench. "Disabling hop-wise left `CRITERIA`
unchanged" says nothing, because hop-wise was not running on `CRITERIA` in the
first place.

**For general traversal the collapse is irrelevant and the gate is the only
mechanism there is.** Hop-wise is not superseded on that path; nothing else
serves it.

What the accident actually showed is narrower and still worth having: on
frame-slot shapes, where the collapse already wins, the criteria the gate
measures are not doing useful work. That is a statement about one shape, not
about hop-wise.

I originally added that this made `issues/198` more serious — a criterion at
depth 2 on `relation_hop` being unrunnable, on the path with no collapse to fall
back on. **`issues/198` is WITHDRAWN as invalid**: that query paired
`relation_hop` with a criterion written for `frame_hop`, leaving `?f{n}`
unbound, so it measured a cross product. With a criterion bound to the walk,
general traversal runs in 0.32-2.42 ms at depths 1 to 3 and chooses hop-wise
every time.

Which settles the scope question in the other direction: the gate IS earning its
keep on general traversal. What remains unsolved here is the nested-criterion
pathology on FRAME-SLOT shapes, and only that.

## MEASURED IN WALL-CLOCK, 2026-09-13 — and a correction to this issue

Everything above quotes PLAN COST ESTIMATES. That was the wrong instrument, and
this issue overstated in places because of it. Measured with
`EXPLAIN ANALYZE` and `statement_timeout = 120s`, same fixture, same starts:

| shape | d1 | d2 | d3 |
|---|---:|---:|---:|
| `has_nested` (structure only) | 1.2 ms | 2.1 ms | 2.3 ms |
| `nested_category_in_alpha_beta` | 1,769 ms | 1,458 ms | **KILLED at 120 s** |
| `nested_score_gte_50` | 2,208 ms | **KILLED** | **KILLED** |

**The pathology is real** — three of six cases do not finish in two minutes, and
the ones that do are a thousand times slower than the structure-only query. But
the estimates are unreliable in BOTH directions: `nested_category` at depth 2
estimates 486,294,496 and runs in 1.5 s. So "19 trillion" and "7.85e15" in this
issue are estimates of plans, not measurements of time, and should be read that
way.

The one number here that WAS wall-clock is the original: the frame-slot depth-2
walk that ran 24m41s before the fixture migration. That still stands.

### What the plan does wrong

At depth 1, where it is small enough to read: `has_nested` runs in tight nested
loops driven from the pinned start entity. Add a value filter on the nested
frame and the planner abandons that for a **Seq Scan over all 144,598 rows of
the edge table**, hash-joined to 123,395 rows.

The query is pinned to ONE entity (`FILTER(?e0 = <entity:45>)`). That pin should
drive. Instead the nested criterion does, because a filter looks selective to
the planner while the pin is expressed as a join it does not start from.

`enable_seqscan=off` as a diagnostic confirms the direction without fixing it:

    d1  default 792 ms (1 seq scan)   seqscan off 518 ms (0)
    d2  default 4,699 ms (2)          seqscan off 1,175 ms (0)   4x

Better, and still three orders off `has_nested`. So the seq scan is a symptom of
the join order, not the cause, and forcing it off is not the fix.

### Narrowed further, 2026-09-13 — two hypotheses eliminated

**The pin IS materialised.** `FILTER(?e0 = <entity:45>)` becomes a literal uuid
in the SQL, once, in both the fast and slow cases. So this is not a
constant-folding failure.

**Where it lands is the difference:**

    has_nested       Index Cond:  (role_uuid = ... AND entity_uuid = '1b90c259...')
    nested_category  Filter:      (entity_uuid = '1b90c259...')

In the fast plan the pin is an index condition on `idx_fs_role_entity` and
drives the scan. In the slow one it is a Filter on an `idx_fs_cover` scan,
applied after a Seq Scan of all 144,598 edge rows has been hash-joined to
123,395.

**ELIMINATED — the index choice.** `fs_cover` leads with `context_uuid`, so the
pin cannot be an index condition on it, and `idx_fs_entity_role` (entity-leading)
exists and would allow it. That made "the planner picks the wrong index" the
obvious hypothesis. It is wrong: `enable_indexonlyscan=off` forces a different
index and makes it WORSE — 1,339 ms to 3,012 ms at depth 1, neutral at depth 2.
The covering index is a reasonable choice.

**ELIMINATED — the sequential scan as a cause.** `enable_seqscan=off` is 4x
better at depth 2 (4,699 ms to 1,175 ms) and still three orders of magnitude off
`has_nested`. It is a symptom.

**What is left** is the join order itself. The nested criterion is a filter on a
frame one edge out; the planner starts from it because a filter looks selective,
while the pin — one entity, the most selective thing in the query — is reached
only after the criterion side has been materialised. With the pin driving there
are a handful of frames to check; with the criterion driving there are 123,395
rows before the pin is applied at all.

### ROOT CAUSE FOUND, 2026-09-13: hop-wise emission never reorders joins

`reorder_joins` is the only component that picks a selective root. Counted per
query:

    has_nested            reorder_joins calls = 1   (5 quad tables)
    nested_score_gte_50   reorder_joins calls = 0

**Zero.** It is not called at all for the slow shape, so nothing ever considers
selectivity and the pin cannot be chosen to drive.

The reason is the emitter. `emit_traversal` mentions `reorder_joins` twice and
both are COMMENTS; it does not call it. It places tables by lexical scope —
"within the hop it hangs on the last-placed table it mentions, so every
reference is already in scope" — which is a DEPENDENCY rule, not a selectivity
one. Correct SQL, arbitrary order.

So the full chain is:

1. the nested criterion is measured, so the gate chooses hop-wise;
2. `emit_traversal` emits it, ordering tables by scope alone;
3. `reorder_joins` never runs, so no leaf is chosen as a selective root;
4. the pin — one entity, the most selective thing in the query — does not
   drive, and lands as a late `Filter`;
5. the plan seq-scans 144,598 edge rows and hash-joins 123,395 before the pin
   applies.

`has_nested` carries no measured criterion, takes the flat path through
`emit_bgp`, gets `reorder_joins`, and runs in 1.2 ms.

**This reframes hop-wise entirely.** It is not inherently slow — it is
UNORDERED. Where the emitter's incidental order happens to be good it wins big
(the 134x in `traversal_decision`'s docstring); where it is not, nothing
corrects it. That is why the same mechanism measures 134x better on one shape
and a thousand times worse on another.

It also explains why `issues/197`'s direction gate has so little to show: the
gate chooses WHICH END to drive from, while the thing that decides whether any
selective leaf drives at all is a component the hop-wise path does not use.

### THE OBVIOUS FIX WAS TRIED AND IS A REGRESSION (2026-09-13)

Given the root cause above, the obvious fix is to give hop-wise placement the
selectivity `reorder_joins` already computes: pass `_leaf_cardinality` into
`emit_hop_wise` -> `partition_hops` -> `_place`, and order each hop's greedy
choice by cheapest leaf after the existing `prefer`.

Implemented, and measured A/B with two repetitions per cell:

| case | baseline | with cardinality ordering |
|---|---|---|
| `nested_category` d1 | 1,451 / 840 ms | 1,751 / 713 ms (noise) |
| **`nested_category` d2** | **12,288 / 12,617 ms** | **KILLED / KILLED (>90 s)** |
| `nested_score` d1 | 1,113 / 1,014 ms | 1,591 / 990 ms (noise) |

**Worse, decisively, at the depth that matters.** Reverted, not committed.

Why it backfires is not established, and the honest answer is that it is not
obvious. A plausible reading: within a hop the tables form a correlated lateral,
and the dependency order the greedy loop produces keeps each join driven by the
row already in hand. Reordering by leaf cardinality breaks that correlation for
a leaf that looks cheap in isolation, which is exactly the trade `reorder_joins`
does not have to make on the flat path.

### Three hypotheses now measured and rejected

1. **Count only criteria the hop can use** — shipped, then reverted
   (`c80fff87`). Harmful when implemented correctly.
2. **The planner picks the wrong index** — eliminated before shipping.
   `enable_indexonlyscan=off` is worse.
3. **Give hop-wise placement selectivity** — this one. Worse at depth 2.

All three were sound in reasoning and wrong in measurement. That is worth
recording as a property of this area: the plan is sensitive to something the
obvious models do not capture, and every attempt so far has been decided by
wall-clock rather than by argument.

**What is established and not in doubt:** `reorder_joins` runs 0 times on the
hop-wise path and once on the flat path, the pin lands as a late `Filter` rather
than an index condition, and the flat path is a thousand times faster on this
shape. The mechanism is known; the remedy is not.

The next attempt should probably NOT be another ordering heuristic. The
alternative worth pricing is refusing hop-wise for this shape outright — the
flat path already answers it in 1.2 ms, and `has_nested` proves the shape is
cheap when it takes that path.

### The fix, and why it is not attempted here

Hop-wise emission needs selectivity-aware placement — at minimum a selective
root per hop, which is what `reorder_joins` already computes for the flat path.
That is a real piece of work in `emit_traversal`, not a guard to add, and it
should be measured in wall-clock on all six cells of the table above plus the
`CRITERIA` family that hop-wise currently wins on.

Two fixes have already been attempted from this issue on worse evidence than
this — one shipped and reverted (`c80fff87`), one eliminated before shipping
(the index-choice hypothesis). This one has a mechanism, a count, and a
reproduction, which the others did not.

### Why this is left open rather than fixed

It is a join-order problem on a shape where the pin is the most selective thing
in the query and is not driving. That is `reorder_joins` territory, it is not
recorded in `plan_decisions` for this query, and a change there affects every
query in the system.

One wrong fix has already shipped from this issue (`c80fff87`). The next attempt
should start by establishing why the pin does not drive — and should be measured
in WALL-CLOCK on all six cells above, not in plan cost.

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
