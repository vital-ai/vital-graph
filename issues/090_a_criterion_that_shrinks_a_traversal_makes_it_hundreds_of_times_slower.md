# A Criterion That Shrinks a Traversal Makes It Hundreds of Times Slower

## Status: OPEN — characterised 2026-08-14 on a purpose-built fixture

Following edges between entities is fast until you say which edges to follow.
Adding a criterion — the thing that makes a traversal a query rather than a
crawl — costs 150x to 950x, **while returning fewer rows**.

Measured on `sp_graph_synth_10k`, a 3-hop walk from one entity, one criterion
applied per hop:

| criterion | depth 3 | rows |
|---|---|---|
| none | **0.9 ms** | 63 |
| `hasScore >= 50` (integer) | 859.1 ms | 4 |
| `hasWeight >= 0.5` (double) | 776.3 ms | 0 |
| `hasOccurredAt >=` (dateTime) | 332.8 ms | 6 |
| `hasCategory IN (...)` (string) | 525.2 ms | 27 |
| `hasActive = true` (boolean) | 716.8 ms | 12 |
| `hasKGFrameType =` (uri) | 147.3 ms | 1 |

Every datatype, same direction. The one returning ZERO rows takes 776 ms to say
so.

## This is not the frame_entity rewrite declining

The collapse happens in every row above — 3 `frame_entity` joins at depth 3, one
per hop, exactly as `issues/048` intends. The six tables per hop have already
become one. What costs is how the per-hop criterion is joined onto the collapsed
rows.

That distinction matters because `048` reads as "the table is unused"; here it
IS used, the traversal is 0.9 ms without a filter, and the filter is what
undoes it.

## The same shape on real data

On `wordnet_frames` (285,348 frames), restricting each hop to hypernyms — the
only criterion that space can express:

    depth   unfiltered   frame type = hypernym   rows
    1          0.2 ms                  0.2 ms       1
    2          0.2 ms                  0.3 ms       1
    3          0.7 ms              4,043.3 ms       1

So it is not an artefact of the synthetic fixture, and it grows with depth: the
criterion is free at depth 1-2 and catastrophic at 3.

## Why there was no fixture until now

Neither existing fixture can pose the question:

* `wordnet_frames` has connection frames but no literal values anywhere, so the
  only criterion is the traversal type;
* `lead_synth` has every datatype and comparator but only ATTRIBUTE frames —
  entity to literal — so nothing connects two entities and there is nothing to
  walk.

`scripts/generate_graph_dataset.py` produces both at once at 10k and 100k:
entities of several kinds, connection frames carrying six criterion datatypes,
and KG relations as a structurally different second traversal. Ground truth is a
BFS over the same edge list the triples are written from, so the expected
answers share no code with the pipeline under test.
`tests/performance/test_graph_traversal_fixture.py` checks the two against each
other — 14 cases, currently agreeing.

## What to look at first

Unmeasured, and the obvious next step: the PLAN. Every number above is
wall-clock with no `EXPLAIN` behind it. The candidates worth separating are

* whether the criterion join is driven per collapsed row rather than set-based,
  which would explain the growth with depth;
* whether the criterion's selectivity is visible to the planner at all — a
  filter believed non-selective would be applied last, after the traversal has
  been expanded;
* whether the literal comparison lands in the typed lane or falls back to text,
  since `hasWeight >= 0.5` returning zero rows still costs 776 ms.

## Related

- `issues/048` — the parent plan. This is Problem 2 of the three priced there;
  the collapse itself is working, and Problem 1 (the slot-type decline) is a
  separate cause with its own price
- `issues/072` — nested-loop misplanning, the same family of symptom
- `planning/planning_performance/unexplored_performance_surface.md`
