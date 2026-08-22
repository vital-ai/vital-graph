# A Non-Selective Entity-Type Predicate Costs 6x Buffers and 10x Time

## Status: DOWNGRADED to fixture-specific 2026-08-22, and the proposed fix is
## DECLINED. The 5.9x is real on `sp_lead_synth_100k` and does NOT reproduce on
## a fixture with real entity types. Mechanism below is still correct; what was
## wrong was assuming it generalised.

Adding an entity-type criterion that matches **every** entity makes the same
KGQuery 5.9x more expensive in buffers and 9.8x slower. It filters nothing and
costs six times the work.

## Measured

`sp_lead_synth_100k`, `contains "CA"` on `CompanyStateCode`, page 25. Both
sides warmed first, then alternated, median of three — the cold-first ordering
that produced this question in the first place is exactly what `issues/081`
warns about:

    entity type   needs_ordered_scan   median      buffers
    generic       False                 6.37s      4,043,455
    specific      False                62.56s     23,861,490
    ratio                               9.81x          5.90x

Both return the same 25 rows from the same 9,220 candidates.

## The type predicate is not a filter here

Every entity in the fixture carries it:

    subjects with vitaltype = KGEntity                     100,000
    subjects with hasKGEntityType = urn:acme:kg:entity:Lead 100,000

So `specific` and `generic` select the identical entity set. The 6x is pure
overhead.

## Where it goes: intermediate rows, not extra output

The two plans have the same shape — `Nested Loop / Limit / Unique / Sort` over
9,220 candidates — and diverge underneath. Rows at matching depths:

    depth                       generic     specific
    below the text criterion    100,000     100,000
    next                        100,000     700,000
    next                        100,000     800,000
    Gather                      100,000     800,000

The generic arm holds 100,000 rows from the bottom of the tree upward. The
specific arm expands to 800,000 and is then reduced back to 100,000 and finally
to 9,220. Same answer, eight times the intermediate material.

## Traced: the restructuring is never even considered

The two arms produce structurally different SQL.

**Generic** isolates the entity set as its own subquery and joins it once:

    FROM (SELECT q0.subject_uuid AS v0__uuid
          FROM ..._rdf_quad AS q0
          WHERE q0.predicate_uuid = <vitaltype>
            AND q0.object_uuid = <KGEntity> AND q0.context_uuid = <graph>) ...
    JOIN (<the whole frame/slot walk>) AS j1 ON j0.v0__uuid = j1.v2__uuid

**Specific** inlines the type triples into one flat join tree, correlated but
positioned among the frame and slot joins:

    JOIN ..._rdf_quad AS q0 ON q0.predicate_uuid = <hasKGEntityType>
       AND q0.object_uuid = <Lead> AND q0.context_uuid = <graph>
       AND mv0.source_node_uuid = q0.subject_uuid

The joins ARE correlated — this is not a cartesian product. The difference is
that the generic shape reduces to the entity set once, while the flat shape
lets the walk expand first.

The emitter's own decision log says why, and the two arms fail for **different**
reasons:

    generic   selective-driven declined: driver 50000 not selective vs anchor 100000
    specific  selective-driven declined: no 2-child JOIN within 6 hops

The generic arm was evaluated and declined on the merits. The specific arm was
never evaluated at all. Instrumenting the decline shows why — `node=None`:

`emit_slice.py:589`

    node = plan.child
    for _ in range(6):
        if node is None or node.kind == KIND_JOIN:
            break
        node = node.children[0] if node.children else None
    if node is None or node.kind != KIND_JOIN or len(node.children or []) != 2:
        return None

The search follows **one spine**, `children[0]`, for six hops, and `node`
becomes `None`.

### That reading was wrong, and the correction is the finding

The obvious inference — the spine misses a join that is off to one side — is
false. Replacing the spine walk with a breadth-first search over every child
declines identically. Dumping the plan trees shows why:

    generic                       specific
    order                         order
      distinct                      distinct
        project                       project
          filter                        filter
            join   (2 children)           bgp   (0 children)
              bgp
              bgp

**The specific query has no JOIN node at all.** Its entire pattern is one BGP,
so there is nothing for a join-restructuring pass to restructure, and
`_try_selective_driven` is right to decline. The generic query is a JOIN of two
BGPs, which is what gives it a two-sided shape to work with — an entity side
that reduces to 100,000 rows, joined once to the walk.

So the cost is decided BEFORE the optimizer sees it, by whatever builds one BGP
in one case and a join of two in the other. Adding the entity-type criterion is
what collapses the plan into a single BGP; the flat SQL join tree, and the
800,000 intermediate rows, follow from that.

### What that means for a fix

Widening the optimizer's search — the change this issue previously proposed —
is pointless. It was written, tested against this shape, and made no
difference: the decline is correct.

The question is instead why the plan builder emits a single BGP once an entity
type is present, and whether it should emit the same JOIN-of-two-BGPs shape it
produces without one. That is in the plan construction, not in `emit_slice`,
and it has not been traced.

## Next step

Trace the plan builder: find where the entity-type criterion causes one BGP
instead of a JOIN of two, and establish whether the single-BGP form is
deliberate. Only then is there a fix worth measuring.

Note for whoever picks this up: the perf baseline `query.json` was stale on
statistics as of 2026-08-22 — 20 benches differ from it, most as `shared_read`
(cold pool) and some as genuine plan flips, with
`stats.fixture_last_analyze` moving 2026-08-20 -> 2026-08-22. Compare a change
against a control run taken in the same session, not against that baseline,
until it is re-promoted.

## Why it matters beyond the benchmark

`needs_ordered_scan=False` on both, so the fence is not involved. A caller
asking for a typed entity list — the ordinary case, since real queries name an
entity type — pays this on every page. And the cost is invisible in the small
fixture: the same shape on the 10k fixture finishes inside the fence bench's
20 s probe, which is why it surfaced only as a skip.

## How it was found

`issues/117`, investigating six skipped shapes in the fence bench. Four were a
needle that could not match; two were cold cache. This is what remained after
both were accounted for, and it is the only one of the three that is a product
problem rather than a test defect.

## Isolated by experiment, 2026-08-22

The generic arm's SPARQL differs from the specific arm's in exactly one place.
`KGQueryCriteriaBuilder` emits, for a generic entity type:

    { ?entity vital-core:vitaltype haley:KGEntity . }
    UNION { ?entity vital-core:vitaltype haley:KGNewsEntity . }
    UNION { ?entity vital-core:vitaltype haley:KGProductEntity . }
    UNION { ?entity vital-core:vitaltype haley:KGWebEntity . }

and for a specific one, a single triple that merges into the flat BGP:

    ?entity haley:hasKGEntityType <urn:acme:kg:entity:Lead> .

Four variants of the same query, changing only that fragment:

    variant                              time      buffers
    A  hasKGEntityType (as-is)          61.7s   23,861,490
    B  vitaltype, no UNION              44.3s   23,562,030
    C  vitaltype, UNION-of-ONE          50.6s   23,932,012
    D  hasKGEntityType + 2-branch UNION  7.9s    4,043,842

D matches the generic arm's 4,043,455 buffers. So:

* **It is not the predicate.** `hasKGEntityType` and `vitaltype` behave the
  same (A vs B).
* **It is not braces, or a union in name only.** A single-branch UNION is as
  slow as no union at all (C).
* **A genuine multi-branch UNION is the entire difference** (D), and the second
  branch in D matches nothing — its presence alone flips the plan.

**The generic path is therefore fast by accident.** It is fast because
`KGEntity` happens to expand to four type alternatives. Expand it to one and it
would be as slow as the specific path.

## Two hypotheses tested and refuted

Recorded because each was plausible and each cost a measurement.

1. **"The optimizer's search misses the join."** `_try_selective_driven` walks
   only the `children[0]` spine, and for the specific arm `node` came back
   `None`. Replacing that with a breadth-first search over every child was
   written and measured: **no change**. The plan has no JOIN node at all — it is
   `order/distinct/project/filter/BGP` — so the decline is correct.

2. **"Any JOIN node will do."** Wrapping the type triple in a sub-SELECT DOES
   produce `join(project(bgp), bgp)`, and the emitter then declines for the
   same reason the generic arm does (`driver 50000 not selective vs anchor
   100000`). Measured: **23,932,014 buffers, no better**. A JOIN node is not
   sufficient; the UNION is doing something the sub-SELECT is not.

## The mechanism, established

It is not `emit_union` — that emits `UNION ALL`, and the generic SQL contains
no UNION at all. The union is gone before emission, removed by
`prune_union.py`, whose docstring describes this exact case:

> Prune dead UNION branches whose constants did not resolve to UUIDs. [...]
> dramatically reducing PostgreSQL planning time for queries with entity
> subtype UNIONs (e.g. KGEntity | KGNewsEntity | KGProductEntity |
> KGWebEntity) where only one subtype exists in the space.

In this fixture exactly one of the four resolves:

    KGEntity 1 term    KGNewsEntity 0    KGProductEntity 0    KGWebEntity 0

So the four-branch UNION is pruned to one surviving branch — and that branch
stays a **separate BGP node**, leaving `JOIN(bgp, bgp)`: the entity-type
constraint in one operand, the frame/slot walk in the other. That is the whole
advantage. The entity side reduces to 100,000 rows once and is joined to the
walk, instead of being one more pattern inside a flat BGP that PostgreSQL
orders late.

Every variant now lines up with this:

* **D** (2-branch UNION, second branch a nonexistent type) — the dead branch is
  pruned, the live one survives as its own BGP, `JOIN(bgp, bgp)`. **Fast.**
* **C** (UNION-of-one) — `{ X }` is a group, not a union. No boundary is ever
  created, nothing to prune. **Slow.**
* **A/B** (bare triple, either predicate) — merges straight into the flat BGP.
  **Slow.**

## One detail that does NOT fit, and is worth knowing before fixing

The sub-SELECT variant produced `JOIN(project(bgp), bgp)` — a genuine two-
operand join with the entity constraint isolated — and was still **23.9M
buffers**. So `JOIN(bgp, bgp)` is fast while `JOIN(project(bgp), bgp)` is not.
The join boundary alone is not sufficient; something about the `project`
wrapper defeats it. That has not been traced, and any fix that produces the
isolated operand needs to produce the BARE-BGP form, not merely a join.

## Next step

Make the shape deliberate: have the plan builder, or a rewrite pass beside
`prune_union`, split an entity-type constraint into its own BGP operand joined
to the rest — producing `JOIN(bgp, bgp)` on purpose rather than as a residue of
pruning. Then measure across the suite, because this changes plan shape for
every typed entity query, not just this one.

**Prerequisite:** re-promote `baselines/query.json`. It is stale on statistics
(20 benches differ on unmodified code, 2026-08-22), so it cannot referee a
plan-shape change. The fixtures are now exempt from the maintenance job, so a
fresh promotion should hold still.

**Do not** "fix" this by emitting a fake second UNION branch. It would work — D
proves it — and it would turn a pruning side effect into a protocol, which is
how the current behaviour came to depend on an accident in the first place.
## It does not reproduce where entity types are real — 2026-08-22

The 5.9x was measured where `hasKGEntityType` matches **100,000 of 100,000**
entities: a type predicate that partitions nothing, which is a property of the
synthetic fixture rather than of the product. Real data has entity types that
discriminate. `wordnet_frames` does:

    NounSynsetNode 82,115   AdjectiveSynsetNode 13,880
    VerbSynsetNode 13,643   AdverbSynsetNode 107

Same experiment there — one query, one entity type, only flat-BGP vs
pruned-UNION differing, both warmed, best of three, both returning 25 rows:

    entity type                    flat BGP        pruned UNION
    AdverbSynsetNode  (0.1%)          4,182 buf       4,182 buf   identical
    NounSynsetNode    (75%)       6,068,974 buf   7,572,671 buf   UNION WORSE

Neither case reproduces it. At 0.1% the two shapes are byte-identical. At 75% —
the closest available to the lead fixture's 100% — the pruned UNION is **1.25x
worse**, the opposite direction.

So "a specific entity type produces a flat BGP and that is slow" is not a
general property. It is an interaction between this one fixture's shape and its
statistics.

### The fix is declined

Making the plan builder emit `JOIN(bgp_type, bgp_walk)` deliberately would
change plan shape for **every typed entity query** in the product, and the
evidence for it is one synthetic fixture whose entity type filters nothing.
That is the shape of the mistake `issues/081` exists to prevent, one level up:
a real measurement generalised past what it measured.

Reopen if a fixture or a production space shows the same gap with an entity
type that actually discriminates. The experiment above is the test to run, and
it is cheap.

### What stays true

The mechanism is correct and worth knowing: a pruned multi-branch UNION leaves
its surviving branch as a separate BGP operand, and `JOIN(bgp, bgp)` can be
much cheaper than one flat BGP. `sp_lead_synth_100k` benefits from that by
accident. That is a fact about the emitter, not a defect, and the benchmarks
that run on that fixture are measuring it.