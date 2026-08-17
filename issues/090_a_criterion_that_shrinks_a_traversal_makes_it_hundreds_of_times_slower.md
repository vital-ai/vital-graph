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

### A second real-data case, priced both ways — `096`

`issues/096` §"What was DELIBERATELY NOT shipped" carries a worked instance of
the direction problem on `prod_kg`, a 2-hop entity→frame→slot sort. Useful
here because both arms are measured, so it constrains a fix rather than only
motivating one:

| | buffers | exec |
|---|---:|---:|
| anchor-driven (ships today), 2,863 entities | 507,492 | 360 ms |
| slot-driven (selective end pinned) | 279,323 | **125 ms** |
| **the same slot-driven form, entity pinned to ONE URI** | **133,067** | **60.8 ms** |
| anchor-driven, entity pinned to ONE URI | 222 | 0.7 ms |

2.9x the right way round, **87x the wrong way**. The separating statistic is
already cheap to obtain (2,863 entities against 5,726 slots of the sort type,
from `rdf_stats`, 3 ms) — so what is missing is not a measurement but the gate:
`traversal_decision` recognises only a URI-pinned end, and a type-constrained
end like `hasKGSlotType = CompanyName` (1.9% of its predicate) does not count.
Nothing reads the decision in any case.

### RE-MEASURED 2026-08-16 on the test stack — the asymmetry holds, and is bigger

The numbers above were taken on the host cluster before the lateral-join work
landed, and `096` then removed the query that produced them. Re-measured on a
copy of that data loaded into the docker test cluster as `sp_slot_skew`, five
interleaved passes, medians, both arms verified to return the same 2,863 rows:

| | buffers | exec |
|---|---:|---:|
| **entity end UNPINNED** (2,863 entities, 5,726 slots of the type) | | |
| anchor-driven (ships today) | 2,452,092 | 537.1 ms |
| end-driven (selective end fenced first) | **338,252** | **58.4 ms** |
| **entity pinned to ONE uri** | | |
| anchor-driven (ships today) | **542** | **0.2 ms** |
| end-driven | 601 | 1.0 ms |

**9.2x the right way round, 4.2x the wrong way** — against 2.9x / 87x recorded
before. The direction still has to be chosen per query; the win for choosing
correctly is larger than recorded and the penalty for choosing wrongly is
smaller.

**A join reorder is NOT a direction.** The first attempt at this measurement
wrote the two arms as different join orders and got IDENTICAL buffer counts —
2,452,092 both — because the planner normalises them to the same plan. Direction
only exists once it is expressed as an optimisation fence; the end-driven arm
above is `WITH sel AS MATERIALIZED (...)`. Anything the gate emits has to be a
fence, not an ordering hint, or it will do nothing at all and measure as a
no-op.

**Only one of the two changes `096` asked for remains.** It says the decision
must be acted on and "today nothing reads the decision" — `emit_bgp.py:168`
reads it now and chooses the hop-wise shape. What is left is the first: a
type-constrained end has to count as a driving set.

**This is not a reopening of the symptom below, which is fixed.** It belongs to
the shapes handed on to `traversal_chain_plan.md` in "Where this leaves
issues/090" — specifically the tail-only pin, here with both arms priced. It is
recorded at this point in the document because the mechanism is the same one the
sections above characterise.

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

### Each hop's criteria must be FENCED behind its link — 2026-08-14

The first version listed the link table first in each hop's FROM and let the
rest of the hop join normally. That is not enough, and a boolean criterion
proved it: `hasActive = true` at depth 2 measured **47 ms flat against 2,599 ms
hop-wise, a 55x regression**. The plan shows why:

    Nested Loop (rows=13,198)                 <- drove from the CRITERION
      Index Scan term (term_text = 'true')       1 row
      Index Scan quad_po q9                      13,198 rows
    Index Scan fe_frame femv0 (loops=13,198)
      Filter: source_entity_uuid = '<pin>'    <- the pin, applied LAST

3.4M buffers — inside hop 0, the exact pathology the module exists to remove.
PostgreSQL reorders freely within a hop, and `score >= 50` on the identical
shape happened to pick the link. So the first version was not right, it was
LUCKY, and the luck ran out on a different criterion.

The fix is structural: each hop emits its LINK ALONE in the FROM, with its
criterion tables in a fenced lateral beneath it. A lateral makes the dependency
one-way, so nothing can be joined ahead of the link. After it, on the same
queries:

    criterion   depth   sparse start          dense start
    hasActive       1   158 ms -> 0.4 ms      72 ms -> 3.0 ms
    hasActive       2   112 ms -> 0.6 ms      65 ms -> 8.6 ms
    hasActive       3   TIMEOUT -> 5 ms       TIMEOUT -> 16 ms
    score >= 50     1    31 ms -> 0.2 ms      34 ms -> 1.7 ms
    score >= 50     2    55 ms -> 0.4 ms      56 ms -> 2.0 ms
    score >= 50     3    60 ms -> 5.1 ms      59 ms -> 5.3 ms
    category IN     3    42 ms -> 3.3 ms     114 ms -> 43 ms

No case is slower. The 55x loss became a 7.6x win, and the flat form now TIMES
OUT at 120 s on the depth-3 boolean walk that hop-wise answers in 16 ms.

**Depth 1 qualifies because of this.** It was declined while a hop was one flat
join, since there was no lateral to place and the SQL would have been identical.
Fencing gave one hop a structure of its own, and it is the largest win measured
— 417x. Same mechanism throughout: a pinned constant that ought to drive, and
does not without the fence.

**Still declined, deliberately**: tail-only pins (a reverse walk, unmeasured),
a single hop carrying no criterion at all (the SQL would be identical), and
anything that will not partition into a line.

### Unfiltered walks too, via deduplication — 2026-08-14

The fence fixed FILTERED traversals. Unfiltered ones stayed slow, and the
criterion gate declined them precisely because they fan out.

`emit_dedup_chain` emits one CTE per hop holding the SET of entities reachable
at that depth, so each hop's input is distinct entities rather than distinct
paths. The wordnet depth-3 walk was materialising 501,538 rows to produce 3,108
answers — the distinct entity count per hop is only 671 -> 583 -> 3,108 and the
rest is the same entities reached different ways.

    query                              before      dedup      ratio
    wordnet_frames   open d3          3,092 ms      52 ms      59x
    graph_synth_100k open d3 (hub)    2,892 ms      79 ms    36.7x

Verified against the manifest BFS on 120 cases — both fixtures, every criterion,
depths 1-3, both traversal shapes — 0 mismatches.

It is deliberately NOT subject to the criterion gate: that gate exists because
the path-wise form fans out, and deduplicating removes the fan-out by
construction. Its own precondition is a correctness proof (a DISTINCT must be
present, the projection confined to the final hop, nothing else needing text),
not a cost estimate.

### The remaining node, and the column that removed it — 2026-08-14

With the walk itself fixed, the single most expensive node left is the frame
TYPE check: on the wordnet depth-3 plan it was 79% of all buffers (2,006,247 of
2,543,685), probed once per output row.

`frame_entity.frame_type_uuid` now exists, is populated on both sync paths, and
is migrated onto all 79 spaces — the `issues/060` treatment applied one table
later. Against a materialised typed copy it is worth 5.8x on the dedup path
(53 ms -> 9 ms) and 2.2x on a filtered hub walk (1,037 ms -> 466 ms).

**Consumed as of `ce9d64c`**: `<frame> vitaltype <Type>` now emits
`femv.frame_type_uuid = '...'::uuid` rather than joining back to rdf_quad.
Measured with absorption toggled on the identical query, 7 interleaved
repetitions: **48.1 ms -> 20.3 ms, 2.4x**, same 3,108 rows. Lower than the 5.8x
estimated against a materialised copy, because that comparison was a bare
`count(*)` over a hand-written CTE chain rather than the SQL the pipeline emits.

A first attempt returned correct answers while absorbing nothing:
`_remap_constraint_sql` leaves a column mapped to None untouched, so
`q0.predicate_uuid` survived, the leftover check saw a removed alias still
referenced, and the whole rewrite declined to the original plan. Silently
correct, no faster, no symptom.

The near-miss is why the suite now carries a test constraining on a type NOTHING
has, asserting zero rows. Had the absorption taken effect through the generic
path — which drops constraints owned by a removed table — the type filter would
have been lost, and every differential would still have passed, because every
frame in both fixtures IS a KGFrame and the constraint is a tautology there.

### Where this leaves issues/090

The reported symptom — "a criterion that shrinks a traversal makes it hundreds
of times slower" — is FIXED, and the unfiltered case that was never part of the
original report is fixed too. Remaining slow shapes are recorded in
`planning_performance/traversal_chain_plan.md`: filtered walks from a hub that
decline dedup (1-3 s), tail-only pins, and branching/UNION traversals.

## The direction gate, and what it turned out to reach

Added 2026-08-17. The gate now prices BOTH ends of a chain from `rdf_stats` and
picks the smaller, rather than recognising only a pinned end:

    a PINNED end       1 by definition
    a CONSTRAINED end  one `rdf_stats` lookup on its (predicate, object) pair
    an OPEN end        unknown — and unknown must not be compared as if it were
                       large, or an open end always loses and a direction gets
                       chosen on no evidence

`Decision` carries a `direction`, `TraversalChain.reversed()` re-orients the
chain, and `GenerateResult.traversal_decision` carries the result out so it can
be asserted on rather than re-derived.

### The fixture that could ask the question

None of the three existing fixtures could. `wordnet_frames`,
`sp_graph_synth_10k` and `sp_graph_synth_100k` all draw their five entity kinds
uniformly, so a kind-constrained end is ~20% of the entity set either way and
"which end is smaller" has no interesting answer.

`sp_graph_skew_2k` — `--rare-entity-fraction 0.02` — adds a sixth kind at 2%,
giving 40 entities against ~390. Small on purpose: the question is a
distribution, not a size.

A rare SLOT TYPE was tried first and is the wrong axis. `hasKGSlotType` is how a
hop is recognised as a source/destination pair, so a third value there produces
hops of a different kind — "no multi-hop chain found (2 single hops)" — and the
whole rewrite declines. The ends of a chain are ENTITIES, so the skew has to sit
on the entity.

### What the fixture then showed: decided, but not expressed

The gate chooses the right end. `emit_hop_wise` cannot drive from it. Measured at
depth 2, every arm returning identical answers:

    driving end                         shared buffers, hop-wise vs flat
    pinned to one uri                       490 vs  16,303      33x BETTER
    kind-constrained, 40 entities        108,900 vs  17,237     6.3x WORSE
    kind-constrained, 394 entities        93,803 vs  37,220     2.5x WORSE
    kind-constrained, 19.6M-quad space      8.1M vs    2.6M     3.7x WORSE

The two ends land in different places, which is the whole of it. A PIN becomes a
literal predicate on the link, so the outer relation is one row. A CONSTRAINT is
a join to a quad table, and `_place` puts it among the hop's criteria — inside
the `OFFSET 0` fence, BENEATH the link. The outer relation is then the entire
link table with the driving check applied per row, which is the opposite of
driving from it.

Rarity makes it worse rather than better: the 40-entity end is the worst of the
three, because fencing discards exactly the selectivity that made it small.

At depth 1 the direction is provably inert — reversing a one-link chain emits
byte-identical SQL, which is how this was first noticed (two arms, 450,638
buffers each).

**So `emit_hop_wise` declines a constrained drive** rather than emitting it
badly. Without that decline the extension shipped a 2.5-6.3x pessimisation on
every shape measured. The decision layer keeps its direction: it is correct, it
is asserted against real statistics, and it is what the hoist will need.

### The hoist — IMPLEMENTED 2026-08-17

Shipped. The generated SQL now matches the hand-built variant exactly (4,717
buffers on the rare end, 39,949 on the common one), and the tail-constrained
case works through the reversal: 2,998 against 13,743 flat, 4.6x.

Two things it needed, and the second was not visible from reading the code.

**Which table carries the driving constraint.** `_place` assigns by hop, not by
role, so the emitter has to be told. `partition_hops` now asks `_driving_alias`
before `_place` and orders that table first among its hop's non-link tables,
which puts its conditions in `crit_where` — exactly the constraints whose
deepest table is that one, its own predicate and object checks plus the
correlation back to the link. Those become its JOIN ON in the body. Whatever
table then opens the lateral takes its conditions from `on_map` to `crit_where`,
by the same rule `_place` used to put them there.

**The alias has to come from the CHAIN, not from the SQL.** The first version
looked for the `head_constraint` pair's uuids in the constraint text and found
nothing, every time, silently — at emit time the constants are still
`__CONST_c_N__` tokens, because `substitute_constants` resolves them at the very
end of generation. So `TraversalChain` now records `head_constraint_alias` /
`tail_constraint_alias` where `_constrained` already had the alias in hand, and
`reversed()` swaps them with the pairs.

The recorded alias is still VERIFIED at emit: it must be a non-link table of the
driving hop, and it must correlate to the link's driving column. A constraint on
the same pair elsewhere in the query never bounded this end, and hoisting it
would move a table that restricts nothing.

Re-measured after implementation, all arms returning identical answers:

    fixture / driving end        flat     hoisted
    2k,    Rare on head        17,237       4,717   3.7x
    2k,    Rare on tail        13,743       2,998   4.6x
    2k,    Person (394)        37,220      39,949   parity
    19.6M, Person (~20%)     2,598,155   2,424,29x  parity, 6.7% fewer buffers

Wall time on the last one straddles: 2,902-3,158 ms flat against 2,614-3,305 ms
hoisted over three runs. The buffer count is the stable number and it is
consistently better; one 3,982 ms reading was an outlier, not a regression.

Left open: whether the driving end's SIZE should become a threshold rather than
only a direction. At 20% the hoisted form is parity, so there is nothing to lose
today, and a gate that cannot lose is not urgent. It wants its own measurement
rather than a guess — and note this is a different question from criterion
selectivity, which was tried as a threshold and was wrong (see the correction
above).

### How it was measured before it was built

**Hoist the driving end's constraint out of the criteria fence** and into the
outer FROM beside the link. The criteria lateral nests INSIDE the body, so
anything placed in the body stays in lexical scope for it — the move is
mechanically available.

Built by hand and measured (`test_scripts/debug/measure_hoist_value.py`), which
moves exactly one JOIN in the emitted SQL. Depth 2, all three arms returning
identical answers:

    fixture / driving end        flat      hop-wise    hop-wise + HOIST
    2k,    Rare (40 entities)  17,237  106,040 6.2x W    4,717  3.7x BETTER
    2k,    Person (394)        37,220   93,803 2.5x W   39,949  parity
    19.6M, Person (~20%)         2.60M    8.12M 3.1x W    2.42M  parity

So the hoist is the missing half of the direction work, not an optimisation on
top of it. It converts the pessimisation into a win, and the size of the win
tracks how SMALL the driving end is — 3.7x at 40 entities, parity at 394 and at
20% of a 19.6M-quad space. That is precisely what `_end_sizes` already prices,
so the two compose: drive from the smaller end, and the payoff scales with how
much smaller it is.

Left open with it: whether the driving end's size should become a THRESHOLD, not
just a direction. At 20% the hoisted form is parity rather than a win, so there
is nothing to lose today; the question is worth its own measurement rather than
a guess. Note this is a different question from criterion selectivity, which was
tried as a threshold and was wrong (see the correction above).

What the fix needed is above.

## Related

- `issues/048` — the parent plan. This is Problem 2 of the three priced there;
  the collapse itself is working, and Problem 1 (the slot-type decline) is a
  separate cause with its own price
- `issues/072` — nested-loop misplanning, the same family of symptom
- `issues/096` — a tail-only pin on real data with BOTH arms priced (2.9x right,
  87x wrong) and the separating statistic identified; see §"The same shape on
  real data" above
- `planning/planning_performance/unexplored_performance_surface.md`
