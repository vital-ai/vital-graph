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

### The "category IN is 200x worse" counter-example was a BENCHMARK error

Retracted 2026-08-14. The hop-wise form was recorded as 200x slower on a
non-selective string criterion, and a narrow selectivity gate was built to
exclude it. `EXPLAIN` on that query showed the cause, and it was not the shape:

    Index Scan rdf_quad   actual=19,184 rows  loops=2   ->  38,368 rows

38,368 is every quad whose category is alpha or beta. The plan was enumerating
the VALUE side to answer a question about 11 rows, because the hand-written
comparison filtered `t.term_text IN ('alpha','beta')` while the generated SQL
resolves those values to term UUIDs first. That is precisely the failure
`_in_as_constants` documents — 11,679 ms against 37 ms on has_any/Text — and it
was reproduced here by writing the benchmark the wrong way.

With the constants resolved the same query is 0.2 ms. Corrected surface, three
start entities, identical answers:

    criterion         depth   generated    hop-wise
    score >= 50           2    132.6 ms     0.9 ms    145x
    score >= 50           3    170.0 ms     1.8 ms     97x
    category IN (a,b)     3     88.4 ms     1.4 ms     65x
    occurred >= mid       3     62.8 ms     1.7 ms     37x
    category IN (a,b)     2      1.9 ms     0.7 ms      3x
    occurred >= mid       2      2.3 ms     0.9 ms      3x

**Hop-wise is better in every case measured**, and by more as depth grows. There
is no counter-example, the decision no longer gates on selectivity, and the
threshold that existed to exclude this case is gone.

The lesson is about the measurement, not the optimisation: a hand-written
comparison has to be written the way the generator writes it, or it measures the
benchmark. Three of the day's conclusions in this issue came from hand-written
SQL, and this is the one that was wrong.

### All three criterion families are measured now — 2026-08-14

Two of the three were invisible to every selectivity gate, each for its own
reason, and all three now report:

    family                 was              now
    numeric range          collected        unchanged
    temporal range         NEVER measured   0.03% error (53,438 vs 53,455)
    IN over terms          NEVER measured   EXACT (38,368)

**Temporal ranges.** `_try_numeric_filter` handles a dateTime and records it in
`range_leaves`, but `needed_ranges` only tried `_numeric_literal`, so the count
was never requested. `emit_bgp` looks the value up by that exact
`(predicate, op, literal)` key, so an unsurfaced range read as UNMEASURED —
which it explicitly treats as "comparison unsafe" for join ordering. Surfacing
it required rendering the literal exactly as the push-down renders it, and
counting it against `dt_val` through the same normalisation: comparing a
timestamp to `num_val` matches nothing, which reads as *perfectly selective* and
is the most dangerous wrong answer available.

**IN over terms.** The cheapest of the three and the last to work. Every value
is one term, so `rdf_stats` already holds the counts keyed by
(predicate, object) — `category IN ('alpha','beta')` is 21,491 + 16,043 = 37,534
exactly. It was invisible because an IN's constants are registered during
PUSH-DOWN, at emit time, long after the gate runs, so nothing could resolve them
to uuids. Two attempts failed before that was clear: resolving the uuids up
front (they do not exist yet) and reading the preloaded pair stats (the preload
keeps the 10,000 LEAST COMMON pairs, and an IN value is usually a common one —
alpha alone has 21,491). It now resolves and sums in one query against
`rdf_stats`, and reports nothing at all if that table lacks a row for any value,
because a partial sum is an undercount rather than an estimate.

This benefits the semi-join gate and join ordering as much as the traversal
decision — an unmeasured range or IN was making both run blind.

### Criterion coverage, audited across every datatype — 2026-08-14

Asked whether all datatypes are handled, including boolean, uri and
multi-valued. Audited by running one query per shape through the gate on the
traversal fixture, which carries all six:

    integer  >=                  range stat
    double   >=                  range stat
    dateTime >=                  range stat
    string   IN     category IN (alpha,beta)   37,534  exact
    string   =      category = alpha           21,491  exact
    boolean  =      active = true              13,198  exact
    uri      IN     tag IN (external,archived) 36,434
    uri      =      tag = external             18,225
    string   CONTAINS            text stat
    string / boolean / uri INLINE in the triple
                                 constant pair, already counted

Numbers are against the CURRENT `graph_synth_10k`, re-verified 2026-08-14 —
"exact" means the summed `rdf_stats` estimate equals a `count(*)` over the
quads. An earlier version of this table carried 38,368 / 21,852 / 23,719 /
11,823 from before the fixture was regenerated; those no longer describe any
data, which is the hazard of recording a count without the query beside it, so
each row now names the criterion it came from.

The audit found one coherent gap and one exclusion that looked
deliberate and turned out to be wrong.

**Equality as a FILTER was unmeasured for every datatype** — string, boolean and
uri alike — while the same constant written INLINE in the triple was counted as
an ordinary leaf pair. That mattered more after the equality push-down landed
(`6d56a87`), which turns exactly that FILTER into a leaf constraint at emit
time while nothing measured it at gate time. An equality is an IN of one value,
so it now reuses that path.

**Boolean as a FILTER: the exclusion was wrong, fixed 2026-08-14.** It was
originally left out on the reasoning that `true` and `1` are two terms and one
value, the same reason typed numerics are excluded. Revisited on the question
"wouldn't a distribution of booleans be helpful in the stats?" — and it would,
because that reasoning applies to the wrong gate:

    _literal_term_key   governs PUSH-DOWN. Must still refuse a boolean: a
                        constraint emitted on one lexical form silently DROPS
                        rows written as the other. Unchanged.
    _stat_keys (new)    governs COUNTING. Sums both forms, which is EXACT —
                        there are only two, unlike a numeric where the set of
                        equal forms is unbounded.

Measured on the traversal fixture: `hasActive` is 13,198 true against 53,648
false — 19.7%, a genuinely selective criterion that was reading as "selectivity
unknown". `rdf_stats` already held both counts; the pipeline was querying for
them and discarding the answer. End-to-end through the generator the estimate is
13,198, matching the quad count exactly.

The datatype is constrained in the lookup, and that is not decoration: `'1'` and
`'0'` exist in the same space as xsd:INTEGER terms (`hasScore` holds 203 rows of
integer 1), so matching on lexical form alone would sum boolean-true with
integer-one for any predicate holding both. No predicate in this fixture does,
so the guard is currently inert — it is there because the generic schema permits
a mixed-type predicate and nothing prevents one.

Numerics stay excluded from the equality path for the reason booleans no longer
are: `5`, `5.0` and `05` are three forms and the set is unbounded, so there is
nothing finite to sum. The range path owns them.

**Multi-valued predicates: MEASURED 2026-08-14.** The fixture generator now
emits `hasTag`, a uri-valued criterion carrying one to four values per edge, so
the case is observable rather than argued about:

    hasTag                  108,867 quads over 66,846 subjects   ratio 1.63
    IN (urgent, review)     estimate 36,266
                            actual quads 36,266   (exact)
                            actual subjects 32,487
                            overcount 3,779       (12%)

So the estimate is EXACTLY the quad count — it is a stored sum, not an
approximation — and overcounts matching subjects by 12% on this data. The error
direction is "looks less selective than it is": conservative for choosing a plan
shape, wrong for ranking two criteria against each other. That is now a measured
property with a test asserting both halves, rather than a caveat.

Nothing needs fixing unless a caller starts asking "how many frames match",
which is a different question from the one the gates ask.

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

### FIXED for filtered traversals — 2026-08-14

Both directions above were taken. The estimates were fixed as far as they go
(value histograms, temporal ranges, IN, equality, booleans), and the shape is
now chosen explicitly: `emit_traversal.py` emits one nested
`CROSS JOIN LATERAL (... OFFSET 0)` per hop so the pinned end drives the walk.

The plan question at the top of "What to look at first" is answered. The flat
join was driving from the CRITERION and probing the pinned entity last:

    inner query, depth 3, score >= 50, one start entity
    flat join        70,180 buffers   planning 26.5 ms   execution 56.6 ms
    nested lateral      194 buffers   planning 30.0 ms   execution  1.9 ms

362x fewer buffers. The nested form drives from
`femv0.source_entity_uuid = <pin>` — 7 rows — and probes outward. End to end on
graph_synth_10k, same answers, verified against the manifest BFS:

    score >= 50        depth 2    42.3 ms -> 0.2 ms    214x
    score >= 50        depth 3    61.4 ms -> 4.7 ms     13x
    occurred >= mid    depth 2    45.3 ms -> 0.4 ms    122x
    occurred >= mid    depth 3    57.9 ms -> 4.4 ms     13x
    category IN (a,b)  depth 3    27.8 ms -> 4.4 ms    6.4x

Planning is a flat ~28 ms in both shapes — the constant cost of a nine-table
plan, and why wall-clock shows 13x where execution shows 29x. Nothing here
touches it.

**An unfiltered walk is the losing case, and is declined.** The first working
version applied hop-wise to every pinned chain and regressed `wordnet_frames`
depth 3 with no criterion: 865 ms flat against 2,044 ms hop-wise, 3,108 results
from a start of out-degree 671. Hop-wise is a nested-loop strategy — it pays
while each hop's input stays small and loses when the walk fans out. The split
across both fixtures is exact:

    criterion measured    1.8x - 234x faster, 6 of 6 cases
    no criterion          parity on 4 synthetic cases, and that one 2.4x loss

so a measured criterion is now required. Not a SELECTIVE one — `category IN`
admits 56% of its predicate and still wins 6.4x.

Worth naming plainly: that regression passed every test, because the answers
were correct. It was caught only by benchmarking a second fixture with a
different shape.

**Still declined, deliberately**: depth 1 (no lateral to place — the depth-1 win
needs a different structure, see `traversal_chain_plan.md`), tail-only pins
(a reverse walk, unmeasured), and anything that will not partition into a line.

## Related

- `issues/048` — the parent plan. This is Problem 2 of the three priced there;
  the collapse itself is working, and Problem 1 (the slot-type decline) is a
  separate cause with its own price
- `issues/072` — nested-loop misplanning, the same family of symptom
- `planning/planning_performance/unexplored_performance_surface.md`
