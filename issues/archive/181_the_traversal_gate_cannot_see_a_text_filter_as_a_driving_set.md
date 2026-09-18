# The Traversal Gate Cannot See A Text Filter As A Driving Set

## Status: CLOSED 2026-09-11 as SUPERSEDED — do not build the fix.
##
## The DEFECT described here is still real: the traversal gate cannot see a text
## filter as a driving set. What changed is that it no longer matters for the
## query that raised it, and the fix proposed here is still the wrong one.
##
## The OUTCOME this issue wanted — the text filter driving the traversal — is
## achieved by `rewrite_merge_bgp` (`issues/178`), which merges the anchor BGP
## and the traversal BGP so `reorder_joins` chooses an order across both and
## opens on the trigram leaf. The reference CONSTRUCT now runs 341 loops for 425
## rows, entering `frame_slot` on `entity_uuid` from the 61-entity anchor.
##
## That is a DIFFERENT mechanism from the one proposed here, and the measurement
## in this file still stands as the reason not to build this one: the driving
## set as priced here was **8.6x WORSE with ORDER BY + LIMIT** and neutral on
## buffers for the full result set. A 312x on a simplified query that inverts on
## the real one is exactly the trap `issues/178` documents six times over.
##
## Reopen only with a shape the merge does NOT reach — it fires on
## `Join(BGP, BGP)`, so a traversal with no mergeable anchor is the case that
## would still want this.

**Raised:** 2026-09-09, asking why the reference happy-frame CONSTRUCT does not
use the traversal machinery at all.

**Related:** `issues/160` (equality criteria are priced but the hop-wise gate
cannot see them — the same defect, different criterion type), `issues/090`,
`issues/048` Problem 2, `issues/179` (the same filter, unusable from the other
end), `vitalgraph/db/sparql_sql/traversal_chain.py`,
`vitalgraph/db/sparql_sql/traversal_decision.py`

## First, a correction to the vocabulary

There is no "traversal table". Traversal optimisation in this codebase is a PLAN
SHAPE, chosen by `traversal_decision` and emitted by `emit_traversal`:

  * `emit_hop_wise` — nested `CROSS JOIN LATERAL` per hop, criteria fenced
    behind each link. Measured 6.4x–8,690x on filtered walks.
  * `emit_dedup_chain` — one CTE per hop holding a SET of entities. 36x–59x on
    unfiltered walks.

The derived TABLES are `edge`, `frame_entity`, `entity_fanout`, `edge_fanout`
and `entity_slot_sort`. `frame_entity` is a different mechanism (a 6-table
collapse) and is priced separately in `issues/178`.

## The defect

Neither traversal shape fires for this query. From the server log:

    traversal decision: Decision(as-is: neither end pinned or constrained,
                                 no driving set)

`as-is` means the generic plan: no hop-wise fencing, no per-hop dedup.

The reason is what `_constrained` will accept. It requires the chain end to be
the SUBJECT of a quad table whose predicate AND object are both constants:

```python
pair = _as_uuid_pair(leaf_terms.get((alias, "predicate_uuid")),
                     leaf_terms.get((alias, "object_uuid")))
```

The query constrains its entity end like this:

    ?sourceSlotEntity <hasKGraphDescription> ?description1 .
    FILTER(CONTAINS(LCASE(STR(?description1)), "happy"))

The object is a VARIABLE. There is no `(predicate, object)` constant pair, so
`_constrained` returns `(None, None)`, the end reads as OPEN, and
`decide_for_plan` declines:

    SHAPE.decline("neither end pinned or constrained, so there is no small
                   driving set and every hop would materialise the whole ...")

## Why it matters here specifically

The text filter is by a wide margin the most selective thing in the query.
`term_text ILIKE '%happy%'` matches **76 of 617,455 terms** — and the gate
cannot see any of that selectivity, because selectivity is not what it looks
for. It looks for a constant pair it can price from `rdf_stats`.

So the one constraint that could supply a small driving set is invisible to the
one mechanism whose entire purpose is to drive from a small set.

## Relationship to issues/179

Same filter, unusable from both directions, for unrelated reasons:

  * `issues/179` — the FILTER is never pushed to quad level, because
    `_text_search_operands` declines the `LCASE(STR(?v))` shape.
  * this issue — the FILTER is never treated as an end constraint, because
    `_constrained` only recognises constant `(predicate, object)` pairs.

Fixing either alone has been measured and neither is a clean win. `issues/179`'s
push is 10.7x with `LIMIT` and 25x WORSE with `ORDER BY` + `LIMIT`. This one is
unmeasured.

## PRICED — 2026-09-09

Simulated by giving the query the driving set the gate cannot derive: the same
traversal with the entity end supplied as `VALUES` holding the 61 entities whose
description actually contains "happy".

    filter, gate blind      246 ms   1,153,015 buffers   213 rows
    pinned driving set        4 ms       3,699 buffers   213 rows

**312x fewer buffers**, and the results are identical — 213 rows, 213 distinct,
same MD5 over the sorted binding set (`78d3b318a2`). Buffers are the figure to
trust; the wall-clock ratio moves with cache warmth (798 ms on a colder run).

This is the first intuition in this family to survive measurement. `issues/178`
records four that did not.

### RE-MEASURED ON THE REFERENCE CONSTRUCT — the 312x does not survive

The measurement above uses a simplified query: single branch, no UNION, no
`ORDER BY`, no `LIMIT`, three projected variables, no type patterns. Repeating
it on the actual reference CONSTRUCT, with the same 61-entity `VALUES` set
substituted for the two text filters:

    ORDER BY + LIMIT 10
      filter (ships)      896 ms    1,734,172 buffers   10 rows
      pinned set        5,593 ms   14,854,785 buffers   10 rows   <- 8.6x WORSE

    full result set
      filter (ships)    8,769 ms   15,736,127 buffers  425 rows   hash 90af96e146
      pinned set        4,915 ms   14,856,013 buffers  425 rows   hash 90af96e146

On the full set the results are identical and the driving set buys **6% fewer
buffers** — 15.74M against 14.86M — not 312x. With `ORDER BY` + `LIMIT` it is
8.6x worse.

(The 10-row hashes differ between the two `LIMIT` runs. That is ties in
`ORDER BY ?entity` returning a different arbitrary ten, not a correctness
difference; the full-set hashes match exactly.)

**So the text filter is not the CONSTRUCT's bottleneck.** Something else costs
~15M buffers regardless of how the entity set is obtained — the same ~15-16M
appears whether the filter runs, the set is pinned, or the `frame_entity`
collapse is enabled (`issues/178` measured 16.17M with the collapse on). A
simplified single-branch form of the same traversal costs 1.15M. The gap between
those two is where the query's cost actually lives, and it is NOT yet explained.

### The other surprise, which still stands

**Both** variants logged `Decision(as-is: ...)`. The pinned form did not engage
`emit_hop_wise` or `emit_dedup_chain` either — and it is still 312x cheaper.

So the win is not the traversal SHAPE. It is having a small set available early
enough for the planner to drive from. That means a fix does not necessarily
belong in `traversal_decision` at all: materialising the text match into a set
the planner can drive from would capture this without touching the gate.

That reframes this issue and connects it to `issues/179`, whose push-down is a
different way of getting the same set early — and which reached 365 ms /
511,445 buffers, an order of magnitude WORSE than the 3,699 here. The pinned
form is better because the set is small, explicit, and materialised once; the
pushed form re-derives it inside the join.

## What is NOT established

- **That this shape is the reference query.** The measurement uses a single
  branch, no `ORDER BY`, no `LIMIT`, three projected variables. `issues/179`'s
  matrix showed those choices swing results by 25x, so this 312x is for THIS
  shape and must be re-measured on the CONSTRUCT before it is quoted for it.
- **The cost of DERIVING the set**, which the `VALUES` form is handed for free.
  From `issues/179`, the trigram lookup itself is 79 buffers / 0.5 ms, so the
  honest projection is ~3,800 against 1,153,015 — still ~300x, but it is a
  projection, not a measurement.
- **Whether the gate is the right place to fix it**, given the finding above
  that the traversal shapes are not what produces the win.
- **Whether a text criterion can be priced at all** at chain-detection time.
  `_constrained` runs BEFORE statistics load, and the trigram selectivity of a
  needle is not something `rdf_stats` holds. `refine_chain_constraints` runs
  later, where statistics exist, and may be the right place instead.
- **Whether `issues/160`'s fix, if it lands, covers this.** Both are "the gate
  cannot see a criterion it should", and they may share a fix or may not.


## Why this is recorded as DO NOT BUILD

The defect is real: `_constrained` cannot see a text criterion, and it should be
able to. But the only justification offered for fixing it was a 312x that
measured a query nobody runs. On the query this came from, the same change is
neutral at best and 8.6x worse in the shape the reference file actually ships.

That makes this the FIFTH intuition in this family to fail a measurement —
after the slot-type tautology precompute, the null-tolerant join, the
`?e a KGEntity` drop, and `issues/179`'s push-down. The pattern is consistent
enough to state as a rule: **a mechanism measured on a simplified query predicts
nothing about the real one.** Every one of the five was a real mechanism,
correctly described, and priced on a shape that was easier to measure than the
one that mattered.

What would justify revisiting this: an explanation of the ~15M buffers the
CONSTRUCT spends regardless of its entity set. Until that is understood, any
fix aimed at the entity set is aimed at the wrong thing.
