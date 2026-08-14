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

## Investigated 2026-08-14 — cause found, two fixes eliminated, one candidate

### The cause: every row estimate is 1

`EXPLAIN ANALYZE` on the depth-3 walk with `score >= 50`:

    est=1   actual=133,042   Nested Loop
    est=1   actual= 22,758   Nested Loop
    est=1   actual=      0   Index Scan ..._term   loops=133,042

**Every node estimates one row.** The planner therefore chooses a nested loop at
every join, and the traversal expands to 133,042 intermediate rows to produce a
ONE-row answer. The unfiltered walk over the same data produces 212 and takes
1.7 ms.

The estimates collapse because a quad scan filters on `predicate_uuid AND
object_uuid AND context_uuid` — heavily correlated columns that PostgreSQL
multiplies as if independent, giving a product below 1 that clamps. This is the
same root cause as the nurture-slot timeouts.

So the answer to "why does a filter make it slower" is: it does not make the
WALK slower, it changes which plan is chosen, and every available plan is being
chosen on garbage cardinality.

### Eliminated: extended statistics (2x, not enough)

`CREATE STATISTICS (ndistinct, dependencies, mcv)` on the three correlated quad
columns, then ANALYZE: 467 ms -> 241 ms, and the estimate at the 133,042-row
node moved from 1 to **2**. The correlation is not the whole story — the
underestimate is in the JOIN cardinality through nested subqueries, which
extended statistics on a base table cannot reach. Dropped again; the fixture is
in its as-loaded state.

### Eliminated: materialising the term subquery

A value criterion compiles to
`q9.object_uuid IN (SELECT term_uuid FROM ..._term WHERE num_val >= 50.0)`,
which looks exactly like the correlated re-execution of `issues/070`. Forcing it
into a `MATERIALIZED` CTE made it **worse** — 250 ms -> 340 ms. PostgreSQL was
already handling that subquery; it is not being re-executed per row.

### Eliminated: forcing the written join order

`join_collapse_limit = 1`, so the planner keeps the order the generator emits:
235 ms -> **1,417 ms**. The written order is not the good order either, so
"emit the joins in traversal order and stop the planner reordering them" is not
a fix on its own.

### Candidate: evaluate hop by hop, materialising each

One CTE per hop, each filtered before the next expands, so the intermediate
never exceeds the reachable set:

    criterion            sel    depth   generated     hop-CTE
    score >= 50          15%        3     717.4 ms      0.9 ms      791x
    occurred >= mid     ~all        3   2,056.7 ms      2.7 ms      763x
    category IN (a,b)    81%        2       1.8 ms    340.2 ms      0.005x
    category IN (a,b)    81%        3   1,623.0 ms    667.4 ms      2x

Identical answers in every row, matching the manifest.

**This is not a universal win and must not be applied blindly.** On the
least-selective criterion the generated plan is 1.8 ms at depth 2 and the CTE
form is 340 ms — the classic materialise-versus-pipeline trade, where
materialising a set that barely narrows costs more than streaming it.

Note also what the generated column shows: 1.8 ms at depth 2 and 1,623 ms at
depth 3 for the SAME criterion. That erratic behaviour is the signature of plan
instability from unusable estimates rather than of a systematically bad plan
shape, and it is why "make the estimates right" and "choose the shape
explicitly" are different fixes.

### What statistics exist, and the one gap — 2026-08-14

Before collecting anything new, what is already there and already loaded into
`AliasGenerator` at generation time:

| table | content | used by |
|---|---|---|
| `rdf_pred_stats` | per-predicate row counts | `reorder_joins` |
| `rdf_stats` | per (predicate, object) counts | `reorder_joins` |
| `edge_fanout` | avg / p99 / max fan-out per edge type and direction | `emit_slice` |

So per-hop fan-out WITH ITS TAIL is already measured, which is most of what a
traversal cost model needs, and the estimates are already consulted — but only
to order joins WITHIN a BGP. Nothing informs the plan across hops.

**The gap is range selectivity on high-cardinality values.** `rdf_stats` is a
frequent-value list, capped per predicate, and its coverage decides whether a
criterion can be estimated at all:

    predicate    distinct objects   in rdf_stats   coverage
    score                     100            100     100.0%
    category                    8              8     100.0%
    occurred               68,502            196       0.3%
    weight                 64,525          2,000       3.1%

Derived selectivity, measured against ground truth:

    score >= 50          est   6,936   actual   6,936    0.0% error
    category IN (a,b)    est  38,368   actual  38,368    0.0% error
    occurred >= mid      est     244   actual  53,455   99.5% error

Exact where the value set is small; useless where it is not — and timestamps and
doubles are precisely the criteria that arrive as ranges. So the thing to
collect is a **per-predicate quantile summary over `num_val` and `dt_val`**:
bucket boundaries, so a range predicate can be estimated by interpolation
instead of by summing a frequent-value list that does not contain the values.
Small — 32 buckets across ~20 predicates is a few hundred rows per space — and
it fits beside `rdf_stats` on the same refresh path.

Also worth fixing while there: deriving the score estimate took 90.9 ms, which
is too slow to run per query. The summary should be read like `pred_stats` is,
not computed by joining `rdf_stats` to `term` at generation time.

### The part that changes the approach

**PostgreSQL cannot be told any of this.** There are no planner hints, the
schema is generic — the predicate is a column VALUE, not a column — and
extended statistics on the correlated quad columns moved the estimate at the
133,042-row node from 1 to 2.

So "fix the estimates" cannot mean "make the planner's estimates right". It has
to mean **use our own estimates to choose the plan we emit**, and emit SQL whose
performance does not depend on the planner's estimates being right. That is what
makes the two directions below complements rather than alternatives: the
statistics work is what tells us WHEN to emit the hop-wise shape.

### Where that leaves it

Hop-wise materialisation is the strongest candidate, but it needs to be CHOSEN
rather than always applied, which means a cost model — and the estimates that
cost model would consult are the thing that is broken. Two directions worth
weighing:

1. **Make the traversal shape explicit in the generator** and pick it on
   criterion selectivity, which the term table can answer directly rather than
   through the planner's correlated guess.
2. **Fix the estimates** so the planner reaches the good plan itself. Broader
   value — every query benefits, not just traversals — and no risk of choosing
   the materialised shape when streaming is right. Extended statistics were not
   sufficient; the next thing to try is whether the emitted SQL can be shaped so
   estimates survive the subquery nesting at all.

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
