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
