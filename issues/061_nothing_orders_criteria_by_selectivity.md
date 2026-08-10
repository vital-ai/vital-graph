# Nothing Chooses Which Criterion Drives the Query

## Status: OPEN — the machinery exists, nothing consumes it at criteria level

PostgreSQL will not make this decision for us, and we already accepted that once:
`reorder_bgp.reorder_joins` orders joins **within** a BGP using `quad_stats` /
`pred_stats`, because the planner's estimates on this schema are unreliable —
measured 305x and 4,761x underestimates on multi-hop uuid joins (`issues/059`).

What is missing is the level above. Three decisions, and only the first is made:

| decision | who makes it | status |
|---|---|---|
| join order within a BGP | us, `reorder_joins` | done |
| join method/order across the emitted SQL | PostgreSQL | unreliable here |
| **which criterion drives, and traversal direction** | **nobody** | this issue |

## Why PostgreSQL cannot do the third one

Not merely "does it badly" — it is never asked. `emit_slice._emit_two_phase`
anchors on the entity-type BGP to get `subject_uuid` order for O(page) paging,
and every other criterion becomes a probe. And `emit_bgp_exists` appends
`OFFSET 0` as an explicit optimization fence, specifically to stop PostgreSQL
flattening the correlated subquery into a semi-join, because flattening destroys
the ordered scan.

That fence is right for a dense match set. It is also exactly what prevents a
better plan when the result is sparse — see `issues/059`, where a backward
set-wise form answers in 700 ms what the forward probe cannot finish in 200 s.

## What the statistics can and cannot currently tell us

Two problems, in order of severity.

**1. The bounded count saturates.** `_load_missing_pair_stats` counts pairs the
preload lacks, with `_PAIR_COUNT_CAP = 50_000`, cached per process. In the
query that times out, both candidate drivers are actually 100,000 rows:

    (vitaltype,     KGEntity)    actual 100,000  ->  reported 50,000
    (hasKGSlotType, MQLRating)   actual 100,000  ->  reported 50,000

Identical. There is no signal to order them by. The cap is deliberate and its
reasoning is sound for the **gate** — "the gate only needs to know whether a pair
is large, not how large" — but ordering needs the opposite property.

Note this does not block the case that matters most in production: a genuinely
selective criterion (a state code at ~8,800 rows) is well under the cap and is
distinguishable from a saturated one. Ranking *selective vs unselective* works
today; ranking two large criteria does not.

**2. `rdf_stats` is pruned to the wrong rows.** `prune_stats_tables` keeps the
50,000 **lowest** row_counts (`STATS_KEEP_DEFAULT`), and the loader takes the
lowest 10,000 within `[2, 200_000]`. Sensible for seeding a join from its most
selective leaf. But on a 100k-entity space every surviving row has
`row_count = 2`, and only two predicates are represented at all:

    hasEdgeSource          49,516 pairs kept
    hasDateTimeSlotValue      484 pairs kept

The predicates that actually decide plan shape are absent entirely —
`vitaltype` (10,054,000 quads), `hasKGSlotType` (3,877,000), `hasKGFrameType`
(1,100,000). So the preload contributes nothing to these queries and everything
falls through to the capped count.

This is aggravated by the fixture's unique-per-row datetimes (`issues/050`) —
409,017 distinct values, each appearing about twice, flooding the keep-window.
Any high-cardinality literal in production does the same. The pruning is by
global rank, so one noisy predicate can evict every structural one.

A per-predicate policy — keep the most common objects for each predicate, the
way PostgreSQL's MCV lists work — would survive that, and is what makes the table
usable for ranking rather than only for seeding.

## The missing metric is fan-out, not more predicate/object correlation

Predicate/object correlation is already recorded twice — `rdf_stats` holds
`(predicate, object) -> row_count`, and `stat_{space}_quad_po (mcv, ndistinct)`
teaches PostgreSQL the same thing. More of it would not help, because the errors
are not in single-table selectivity. They are **join** cardinality: 305x and
4,761x underestimates on multi-hop traversal steps (`issues/059`).

What no stored metric expresses is **edge fan-out**: given N nodes, how many rows
does one traversal step produce? Measured on the 100k fixture's edge table:

| direction | fan-out per hop |
|---|---|
| forward (source -> dest) | avg **4.15**, p99 10, max 10 |
| backward (dest -> source) | avg **1.00**, p99 1, max 1 |

Over the three hops those queries walk, that is **~71x amplification forward and
1x backward** — which is the whole of the 700 ms vs >200 s gap in `issues/059`,
and the same order as the observed underestimates.

### It is a property of the model, but only for containment edges

Confirmed with the data owner, 2026-08-10:

* a **slot** has exactly one parent;
* a **frame** has no parent or exactly one (an entity or a frame).

So for the containment hierarchy, backward fan-out is 1 **by construction**, not
by observation. A rewrite that walks containment backward is non-amplifying by
the shape of the model, which is a much stronger guarantee than a measurement on
one fixture.

It does **not** generalise to the other edge kinds:

* **relations** have a source and a destination, and an entity may participate in
  many, in either role — many-to-many in both directions;
* a **slot value** may be an entity or arbitrary URI, and many slots may point at
  the same target, so walking from a target back to its slots fans out. (This
  case is already covered by existing stats: it is an `(predicate, object)` count
  in `rdf_stats`, not an edge-table hop.)

So a blanket "always traverse backward" rule would be wrong. Fan-out has to be
recorded **per edge type**, which makes `issues/060` (the edge type column) a
prerequisite for the metric and not only a performance win — without it the edge
table cannot even distinguish the cases.

### Measured on real data: the direction rule INVERTS between edge kinds

`wordnet_frames` carries 570,696 `hasEntitySlotValue` quads — slot values that
point at entities — so the non-tree case is measurable on real data rather than
hypothesised:

| edge kind | forward | backward |
|---|---|---|
| containment (`Edge_hasKGSlot`) | avg 2.00, max 2 | **avg 1.00, max 1** |
| slot value (`hasEntitySlotValue`) | **avg 1.00, max 1** | avg 5.20, p50 2, p99 40, **max 1,342** |

Two conclusions, both of which constrain the design:

1. **Containment backward = 1 holds on real data**, confirming the model
   guarantee rather than a synthetic artefact.
2. **The safe direction is per edge kind and it inverts.** For a slot-value hop
   the safe direction is *forward*; walking it backward hits 1,342x at worst. A
   blanket "traverse backward" rule — which the 100k fixture alone would have
   justified — is wrong.

**The distribution is skewed, so an average is not enough.** 5.20 average against
a 1,342 maximum: a plan chosen on the mean can hit 250x that. The metric needs a
tail statistic (p99 and max), not a mean, and a direction choice should use the
tail when the cost of being wrong is a timeout.

### Coverage gap this exposes

The fixture contains only `Edge_hasKGSlot` (3,877,000), `Edge_hasKGFrame`
(900,000) and `Edge_hasEntityKGFrame` (200,000). **No relation edges exist in it
at all**, which matches `issues/043`/`048`: `build_relation_query` requires
`Edge_hasKGRelation`, which has zero instances anywhere.

Every fan-out number from that fixture therefore describes the tree-shaped half
of the model. `wordnet_frames` covers the slot-value case above and is the
fixture any direction-choosing rewrite must be validated against — it is the one
that would have caught a blanket backward rule.

**Relations are now covered** — `sp_kg_rel`, built 2026-08-10 by
`scripts/generate_relation_dataset.py` / `load_relation_dataset.sh`. 5,000
entities, 223,965 triples, and the first fixture anywhere with relation edges
(16,043 `Edge_hasKGRelation`; the only other instances in existence are 96 in a
handful of tiny test spaces).

Fan-out measured from the loaded space, per edge type:

| edge type | forward | backward |
|---|---|---|
| `Edge_hasEntityKGFrame` | avg 1.00, max 1 | avg 1.00, max 1 |
| `Edge_hasKGFrame` | avg 1.00, max 1 | avg 1.00, max 1 |
| `Edge_hasKGSlot` | avg 1.00, max 1 | avg 1.00, max 1 |
| **`Edge_hasKGRelation`** | **avg 4.24, max 400** | **avg 4.20, max 387** |

Two things this establishes that no existing fixture could:

1. **Relations fan out symmetrically — neither direction is safe.** A rule of the
   form "traverse in the direction whose fan-out is 1" has no answer here and
   must fall back to something else.
2. **The pooled statistic is useless.** Across all edges this space reports
   forward 1.80 / backward 1.51, which hides both the tree (1/1) and the hub
   (400/387). Fan-out recorded per space rather than per edge type would produce
   exactly this misleading number, so `issues/060`'s type column is a
   prerequisite for the metric and not merely a performance win.

The fixture also carries both frame form types, including assertion frames that
leave `hasKGFormType` unset (1,250 of 5,000), since unset defaults to assertion
and a fixture that always states it cannot catch a reader that requires the
explicit triple. The manifest records every degree distribution so a test can
assert them rather than recompute them from the data under test.

Still missing: the fixture is not yet registered anywhere the perf suite reads,
so nothing runs against it automatically.

## Suggested order

1. **Per-predicate stats retention** (problem 2). Self-contained, no query-path
   risk, and makes the other work possible.
2. **Raise or tier the cap** for pairs being *ranked* rather than gated, or
   record "at least CAP" distinctly from an exact count so the two are not
   confused. Cheap.
3. **Criteria-level driver selection.** Choose the driving criterion by
   selectivity instead of always anchoring on entity type. This is the real
   change, and `issues/059` is its most extreme case.

Steps 1 and 2 are prerequisites for 3 having anything to decide with.

## Related

- `issues/059` — backward negation; 700 ms vs >200 s, the case this would unlock
- `issues/060` — edge type column, which makes the backward hops cheap
- `issues/050` — unique-per-row datetimes, which flood the stats keep-window
- `two_phase_kgquery_paging_plan.md` — D3, of which this is the concrete form
