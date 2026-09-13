# A Criterion At Depth 2 Kills The Relation Walk, And The Estimate Says 919

## Status: OPEN, found 2026-09-13 while checking whether the traversal gate
## still has a job (`issues/197` item 4). Distinct from `issues/195`: both
## emission arms are affected, so this is not a gate mis-choice.

**Related:** `issues/195` (the nested-criterion family, fixed — same theme,
different shape), `issues/197` (the gate's relevance), `issues/151` (hop-wise
vs flat)

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
