# A Property Path Seeds Only From a Literal URI, Not From a Bound Variable

## Status: OPEN and VALIDATED on a real fixture 2026-08-22. This is a
## core-workload defect: 67 seconds against 26 milliseconds for the same 53
## results on `sp_lead_synth_100k`. The fix shape is SET-SEEDING; LATERAL is
## proven wrong. See "Validated at scale" at the end — it reverses the
## small-fixture conclusion above it.

The same query, the same data, the same 100 results. The only difference is
whether the path's start arrives as a constant or through a join:

    <urn:sd:c0> rdf:rest* ?n . ?n rdf:first ?item
        100 items    22.8 ms     27,896 buffers

    <urn:sd:s> :items ?l . ?l rdf:rest* ?n . ?n rdf:first ?item
        100 items   244.9 ms    389,002 buffers

**14x the buffers, 11x the time**, for an identical answer.

## Mechanism

`emit_path.py:143`

    seed_start_sql = seed_end_sql = None
    if isinstance(subject, URINode):
        seed_start_sql = (
            f"(SELECT term_uuid FROM {term_table} "
            f"WHERE term_text = '{_esc(subject.value)}' AND term_type = 'U' LIMIT 1)")

The seed is built only when the path's subject is a **URINode** — a URI written
literally in the query. A variable bound by a preceding triple pattern is a
`VarNode`, so no seed is produced and the recursion runs unseeded.

The file already explains what that costs, at `:134`:

> A pinned SUBJECT is handed down so a recursive path can seed its base term
> from it rather than **closing over the whole graph and filtering afterwards**.

Closing over the whole graph is exactly what the join-bound case does. Measured
on a 101-cell chain, the unseeded recursion materialises **5,252 rows** — the
full transitive closure, every cell to every later cell — where the seeded form
needs 101.

## Why this is bigger than the case that found it

Collections made it visible because a list is a long thin chain, so the closure
is quadratic in an obvious way. But the condition is just "the path's start is
a variable", and that is the ordinary shape of our own traversal queries:

    ?entity :hasFrame ?f . ?f :hasSubFrame* ?sub

Any query that reaches a node and then walks from it pays this. Entity-to-frame
traversal, frame nesting — the workload the derived tables and the collapse
rewrite exist to serve — is written this way.

**Not measured on those shapes yet.** The 14x above is one list. Whether the
same gap appears on the lead and graph fixtures is the first thing to check,
and it is cheap: the fixtures and benches already exist.

## What a fix has to deal with

Not a one-liner. `seed_start_sql` is a **scalar** SQL expression substituted
into the CTE's base term. A bound variable's value is per-row, so seeding from
it means either:

* a **LATERAL** join, so the path CTE is evaluated once per outer binding with
  that binding as the seed; or
* passing the outer binding's column reference into the CTE as a correlated
  value, which PostgreSQL does not allow for a `WITH RECURSIVE` term directly.

The first is the real option and it changes the shape of the emitted SQL, not
just a predicate. It is the same family as `_try_selective_driven` — use a
known binding to drive the work rather than computing everything and filtering
— and it carries the same risk that repository has already been burned by: a
plan-selection change that helps one shape and hurts another.

## Before implementing

1. **Measure it on the real traversal shapes**, not on a synthetic list. If the
   gap is small there, this is a collections curiosity; if it is 14x, it is a
   core-workload defect.
2. **Check the interaction with `issues/123`.** That proposes removing the
   `depth` column so the recursion terminates by dedup. An unseeded closure is
   where dedup matters most, so the two changes touch the same code and should
   be reasoned about together.
3. **Baseline first.** `query.json` and `ingest.json` were re-promoted
   2026-08-22 and are current, so a before/after is meaningful today.

## Relationship to other issues

* `issues/122` — collections truncate past 100 elements. Different defect, same
  file.
* `issues/123` — the depth cap. Same CTEs.
* `rdf_collections.md` §4.1 attributes the position query's cost to the
  double-closure idiom. That is true, but this issue is the larger multiplier
  underneath it, and §4.1 should be read with that in mind.


## Implementation explored 2026-08-22 — and nothing is ready to build

Three forms were written by hand in raw SQL and measured against each other, so
the emitter was never touched. Two failed, and the third result invalidates the
premise.

### LATERAL is definitively wrong

Seeding from a bound variable means the recursion runs per outer row, which is
what LATERAL does. Measured on a 100-cell chain:

    unseeded + join (today)     99 items    23.3 ms      7,674 buffers
    LATERAL seeded             100 items   249.7 ms    727,768 buffers

The plan says why:

    727,200 buf  loops=100  CTE Scan
    727,200 buf  loops=100  Recursive Union

**`loops=100`.** The planner put the LATERAL on the inner side of a nested loop
driven by the 100 `rdf:first` rows, so the entire closure was recomputed a
hundred times. LATERAL converts a once-computed closure into a per-row
recursion and hands the planner the choice of how many rows. Do not do this.

### A SET-SEEDED base term is correct, and not obviously faster

Restricting the base term to the bound starts — one recursion, still evaluated
once — is the right shape and close to the existing code: `seed_where` already
emits `WHERE _base.start_uuid = <scalar>` and would become `IN (<subquery>)`.

    one list, 100 elements
      unseeded              99 items    16.8 ms      7,674 buffers
      SET-seeded           100 items     2.9 ms      7,543 buffers

    50 lists x 20 elements, querying ONE list
      unseeded              20 items     5.1 ms      3,060 buffers
      SET-seeded            20 items     6.1 ms     21,305 buffers

On the fixture where seeding SHOULD win — many lists, query one — it loses, and
the plan shows why: the seeded `Recursive Union` costs 20,254 buffers for a
20-step walk, about a thousand per iteration, because each iteration re-scans
rather than probing. The unseeded form gets one hash join over a small table
instead.

### Which invalidates the measurement this issue was filed on

Every fixture here is tiny — a few thousand quads. At that size buffer counts
are dominated by per-iteration and scan-versus-probe choices, not by how much
of the graph the closure covers. **The 27,896-vs-389,002 measurement at the top
of this issue was taken the same way**, on one 100-cell list in a space holding
about two hundred quads.

So the 14x may be a small-scale planner artifact rather than evidence that
unseeded closure is asymptotically wrong. That is the `issues/118` mistake
exactly — a real measurement generalised past what it measured — and it is
better to notice it here than after changing path emission.

### What would actually settle it

Measure seeded versus unseeded on a REAL fixture, not a synthetic list.
`sp_lead_synth_100k` carries frame nesting reached through bound variables,
which is the shape §"Why this is bigger" claims is affected, and both perf
baselines were re-promoted 2026-08-22 so a before/after is meaningful.

If the gap is large there, this is a core-workload defect and the set-seed
shape is the candidate. If it is small, this issue closes as a curiosity and
`rdf_collections.md` §4.1's cost stands on the double-closure idiom alone.

## Validated at scale 2026-08-22 — and it reverses the toy result

The section above hedged because seeding lost on a 2,000-quad fixture. That
hedge was right to demand a real measurement and wrong about the answer.

**Through the generator, on `sp_lead_synth_100k` (50.5M quads)**, the same
frame-nesting walk written two ways —
`(^vital:hasEdgeSource/vital:hasEdgeDestination)*`:

    start PINNED as a constant     34 rows     4.2 ms      723 buffers
    start BOUND by a join          did not finish in 120 s

**In raw SQL on the same table**, counting the same reachable set from one
entity's frames:

    unseeded closure          53 results   67,122.5 ms
    SET-seeded from entity    53 results        25.9 ms

Same answer. **2,600x.**

### Why the toy fixture said the opposite

On a 2,000-quad fixture the "whole graph" the unseeded form closes over IS
2,000 quads, so closing over it is nearly free and the per-iteration cost of a
seeded recursion dominates. That inverts the comparison and hides the effect
entirely.

On a real fixture the unseeded closure is over 50 million quads. This is the
same lesson as `issues/081` and `issues/118`, arriving from the other
direction: there, a measurement on an unrepresentative fixture made a problem
look bigger than it was; here it made one look smaller, and very nearly closed
a real defect as a curiosity.

### What is now established

* **The premise holds, and 14x understated it.** A path whose start is bound by
  a preceding triple is not slightly worse, it is unusable at scale.
* **SET-SEEDING is the fix.** Restrict the recursion's base term to the bound
  starts. `seed_where` already emits `WHERE _base.start_uuid = <scalar>`; this
  makes it `IN (<subquery producing the bound starts>)`.
* **LATERAL remains wrong**, for the reason measured above: it re-runs the
  recursion per driving row.

### Remaining work

1. The path node must receive the SQL that produces its start variable. That is
   a plan-level dependency between a JOIN's two children — the same analysis
   `_try_selective_driven` does for anchor and driver.
2. **ONE FORM, NO HEURISTIC.** Decided 2026-08-22. Seed always; do not choose
   between seeded and unseeded based on graph size, cardinality estimates or
   anything else.

   The small-fixture result that made this tempting — 21,305 buffers seeded
   against 3,060 unseeded on 2,000 quads — is a few thousand buffers on a graph
   where everything is fast. Against it, the unseeded form is 67 SECONDS on a
   real one. Trading an unbounded worst case for a bounded few-thousand-buffer
   regression is the right trade taken unconditionally.

   And a switch would be the `issues/118` shape: a rewrite that fires or
   declines on a plan property, where the declining case is silent and nobody
   notices which one they got. If the seeded form ever proves unacceptable
   somewhere, that is a reason to find a better SINGLE form, not to branch.

3. ~~A regression test on a REAL fixture.~~ DONE —
   `tests/performance/test_path_start_bound_by_a_join.py`. It measures the same
   walk pinned and bound on `sp_lead_synth_100k` and asserts the bound form
   costs about `starts x pinned`, so the gate is a self-calibrating ratio
   rather than a maintained threshold. Currently `xfail(strict=True)`, failing
   with:

       the walk from a BOUND start did not finish in 60000ms, while the same
       walk from a PINNED start cost 660 buffers ... closing over the graph
       instead of walking from the 2 start(s) it was given

   Strict, so it fails the moment seeding lands and the xfail has to be
   removed.