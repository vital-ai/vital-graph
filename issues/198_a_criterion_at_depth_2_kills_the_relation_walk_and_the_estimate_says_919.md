# A Criterion At Depth 2 Kills The Relation Walk, And The Estimate Says 919

## Status: WITHDRAWN 2026-09-13 — INVALID. The query I measured was a CROSS
## PRODUCT, not a traversal with a criterion, and the engine was answering it
## correctly. General traversal with a real criterion is 0.3-2.4 ms and hop-wise
## at every depth. Kept rather than deleted because the mistake is easy to
## repeat and the corrected measurement is worth having.

**Related:** `issues/195` (the nested-criterion family, fixed — same theme,
different shape), `issues/197` (the gate's relevance), `issues/151` (hop-wise
vs flat)

## WHY IT IS INVALID

I built the query by pairing `relation_hop` with `CRITERIA["score_gte_50"]`.
`relation_hop` binds `?r{n}`, `?e{n-1}` and `?e{n}`. That criterion constrains
`?f{n}` — the frame — because it was written for `frame_hop`. So the SPARQL I
measured was:

    ?r1 a Edge_hasKGRelation . ?r1 hasEdgeSource ?e0 . ?r1 hasEdgeDestination ?e1 .
    ?f1 hasScore ?sc1 . FILTER(?sc1 >= 50)          <-- ?f1 APPEARS NOWHERE ELSE
    ?r2 a Edge_hasKGRelation . ?r2 hasEdgeSource ?e1 . ?r2 hasEdgeDestination ?e2 .
    ?f2 hasScore ?sc2 . FILTER(?sc2 >= 50)          <-- nor does ?f2

`?f1` and `?f2` are unbound. Each joins the whole set of subjects carrying
`hasScore >= 50` — about 2,006 — against the walk, unconstrained. At depth 1
that is one such factor and runs in 67 ms; at depth 2 it is 2,006 x 2,006, four
million rows of cartesian product, and the query never returns.

**The engine was right and the query was wrong.** A cross product is what that
SPARQL asks for. Nothing here was a planner or gate defect, and the estimate of
919 was not an under-estimate of a traversal — it was an estimate of a different
query than the one I thought I had written.

The real benches never make this mistake: `test_relation_traversal` calls
`chain_query(..., hop=relation_hop)` with NO criterion.

## THE CORRECTED MEASUREMENT

With the criterion bound to what the walk actually reaches —
`?e{n} hasScore ?sc{n} . FILTER(?sc{n} >= 50)` — on the same fixture:

| depth | estimate | actual | decision |
|---|---:|---:|---|
| 1 | 76.29 | **0.32 ms** | hop-wise, depth 1 |
| 2 | 57.14 | **2.42 ms** | hop-wise, depth 2 |
| 3 | 74.51 | **0.27 ms** | hop-wise, depth 3 |

Fast at every depth, the chain detected at full depth, and hop-wise chosen every
time. **General traversal with a criterion works**, which is the path where the
`frame_slot` collapse does not apply and the gate is the only mechanism. The
gate is earning its keep there.

## The lesson worth keeping

`CRITERIA` and `NESTED_CRITERIA` are written against `frame_hop`'s variables.
Pairing either with `relation_hop` silently produces a cross product rather than
an error, because SPARQL has no notion of an unused variable being a mistake.
`chain_query`'s docstring warns that a criterion "must be numbered per hop"; it
does not warn that the criterion must reference variables the HOP BINDS, and
that is the trap.

A guard in `graph_fixtures` — refuse a criterion whose variables the hop does
not bind — would have turned this into an immediate error instead of a day
chasing a planner defect that was not there.

## What was originally filed (retained for the record)

## The defect

`relation_hop` is the traversal shape with no frames and no slots — "the edge
table is what has to carry it". On `sp_graph_synth_10k`, 10,000 entities,
`EXPLAIN ANALYZE` with `statement_timeout = 45s`:

| shape | estimated cost | actual |
|---|---:|---:|
| depth 2, NO criterion | 49.63 | **6.2 ms** |
| depth 1, `score >= 50` | 488.06 | **67 ms** |
| depth 2, `score >= 50` | 919.30 | **KILLED at 45 s** |

Each ingredient is fine on its own. Together they are unrunnable, and **the
planner estimates 919** — so nothing in the plan says so, and no cost-based
guard would catch it.

## It is NOT the gate choosing badly

The obvious suspicion, given `issues/195`, is that the gate picks hop-wise where
flat would win. It does pick hop-wise here —
`Decision(hop-wise: depth 2, driving from ...)` — but forcing flat does not
help:

    relation d2 hop-wise   KILLED at 45s
    relation d2 FLAT       KILLED at 45s

Both arms. So the emission choice is not the problem and the fix from
`issues/195` — declining to count a criterion the hop cannot use — does not
apply: this criterion sits on the hop's OWN node (`?f{n} hasScore ?sc{n}`),
which is exactly the case hop-wise is supposed to exploit.

## What is interesting about it

**The chain detector works fine here.** For this shape it reports
`depth 2` and `depth 3` chains, unlike the frame shape in `issues/197` where
it never links anything. So the machinery is engaged, the decision is made on a
real multi-hop chain, and the result is still unrunnable.

That makes this the strongest available evidence on the question `issues/197`
step 3 asks — whether the gate should be extended to shapes it cannot currently
see. Here it CAN see the shape, and seeing it does not help.

## Reproducing

    tests/performance/graph_fixtures.py :: chain_query(SMALL, start, 2,
        criterion=CRITERIA["score_gte_50"], hop=relation_hop)

against `sp_graph_synth_10k` on the seeded test stack. Plan it first —
`EXPLAIN` without `ANALYZE` returns instantly and shows the 919.

**Set a `statement_timeout` before running it.** Killing the client does not
cancel the query (`issues/195`): one abandoned run of this family executed for
a further 24 minutes and competed with the next measurement.

## What to look at

1. **Why the estimate is 919 when execution exceeds 45 s.** An estimate wrong
   by four or more orders of magnitude is its own defect, and it is what makes
   every cost-based approach here blind.
2. **What the second hop does differently.** Depth 1 with the same criterion is
   67 ms; the criterion is per-hop, so depth 2 applies it twice, and that should
   not be a cliff.
3. Whether the five failures in `test_traversal_bench.py` are this — they are in
   the same shape and were failing before any of this week's work.
